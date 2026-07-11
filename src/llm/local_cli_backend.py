# -*- coding: utf-8 -*-
"""Local CLI generation backend.

Phase 4 exposes restricted local CLI presets as opt-in generation backends.
It is intentionally process-oriented. Generic safe presets treat stdout as the
model output; the Codex CLI preset reads its final answer from
``--output-last-message`` because stdout includes session diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Sequence
from urllib.parse import parse_qsl, urlsplit

from src.llm.backend_registry import (
    CLAUDE_CODE_CLI_BACKEND_ID,
    CODEX_CLI_BACKEND_ID,
    OPENCODE_CLI_BACKEND_ID,
)
from src.llm.generation_backend import (
    GenerationBackend,
    GenerationCapabilities,
    GenerationError,
    GenerationErrorCode,
    GenerationResult,
)


DEFAULT_LOCAL_CLI_TIMEOUT_SECONDS = 300
DEFAULT_LOCAL_CLI_MAX_OUTPUT_BYTES = 1024 * 1024
DEFAULT_GENERATION_BACKEND_MAX_CONCURRENCY = 1
DEFAULT_LOCAL_CLI_BACKEND_MAX_CONCURRENCY = 1
MAX_LOCAL_CLI_TIMEOUT_SECONDS = 3600
MAX_LOCAL_CLI_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_GENERATION_BACKEND_MAX_CONCURRENCY = 16
MAX_LOCAL_CLI_BACKEND_MAX_CONCURRENCY = 4

_PREVIEW_LIMIT = 800
_FINAL_MESSAGE_OMITTED_PREVIEW = "<final-message omitted from stdout preview>"
_STDOUT_PREVIEW_OMITTED = "<stdout preview omitted because output-last-message was too large>"
_PROCESS_POLL_INTERVAL_SECONDS = 0.05
_URL_PATTERN = re.compile(r"https?://[^\s,;)\]}]+", re.IGNORECASE)
_SHELL_META_CHARS = ("|", ">", "<", ";", "`")
_SHELL_META_STRINGS = ("&&", "||", "$(")
_UNSUPPORTED_ARG_MARKERS = (
    "unknown option",
    "unrecognized option",
    "unknown argument",
    "unrecognized argument",
    "unexpected argument",
    "unexpected option",
    "no such option",
    "unknown flag",
    "unrecognized flag",
)
_SENSITIVE_URL_KEY_PARTS = {
    "access_token",
    "api_key",
    "apikey",
    "auth_token",
    "authorization",
    "cookie",
    "password",
    "secret",
    "sendkey",
    "token",
    "webhook",
}
_SAFE_ENV_EXACT = {
    "PATH",
    "HOME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "NO_COLOR",
    "TERM",
    "CODEX_HOME",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "HOMEDRIVE",
    "HOMEPATH",
    "SYSTEMROOT",
    "WINDIR",
    "PATHEXT",
    "COMSPEC",
    "USERPROFILE",
}
_SAFE_ENV_PREFIXES = ("LC_",)
_SENSITIVE_ENV_PATTERNS = (
    "ACCESS_TOKEN",
    "API_KEY",
    "API_KEYS",
    "AUTHORIZATION",
    "AUTH_TOKEN",
    "AWS_",
    "AZURE_",
    "BASE_URL",
    "CLAUDE_",
    "COOKIE",
    "DATABASE_URL",
    "DB_URL",
    "FEISHU",
    "GEMINI",
    "GITHUB_TOKEN",
    "OPENAI",
    "ANTHROPIC",
    "OPENCODE_",
    "DEEPSEEK",
    "GOOGLE_",
    "MODEL",
    "SECRET",
    "SESSION",
    "TOKEN",
    "TUSHARE",
    "VERTEX_",
    "WEBHOOK",
)
_CLAUDE_CODE_STATIC_INSTRUCTION = (
    "Generate the requested DSA analysis output from stdin. "
    "Return only the final response content. Do not call tools, read files, "
    "use MCP, or ask for interactive approval."
)
_PROMPT_FILE_PLACEHOLDER = "{prompt_file}"
_OPENCODE_STATIC_INSTRUCTION = (
    "Generate the requested DSA output from the attached prompt file. "
    "Follow the output format required by that prompt. Return only the final response "
    "content. Do not use tools, do not read additional files, do not browse the web, "
    "do not edit files, do not ask questions, and do not request approval."
)
_OPENCODE_ALLOWED_EVENT_TYPES = {"step_start", "text", "step_finish"}
_OPENCODE_BLOCKED_EVENT_TYPES = {
    "tool",
    "tool_call",
    "tool_result",
    "tool_use",
    "error",
    "question",
    "permission",
}
_OPENCODE_DISABLED_TOOL_NAMES = (
    "bash",
    "edit",
    "glob",
    "grep",
    "list",
    "lsp",
    "patch",
    "question",
    "read",
    "skill",
    "task",
    "todoread",
    "todowrite",
    "webfetch",
    "websearch",
    "write",
)
_CONCURRENCY_CONDITION = threading.Condition()
_CONCURRENCY_ACTIVE = 0


@dataclass(frozen=True)
class LocalCliExecutionResult:
    """Raw subprocess output passed to a preset-specific extractor."""

    stdout: str
    stderr: str
    returncode: int
    final_message: str = ""
    diagnostics: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class LocalCliExtractionError(Exception):
    """Extractor failure mapped to a structured GenerationError by the backend."""

    error_code: GenerationErrorCode
    reason: str
    retryable: bool = True
    fallbackable: bool = True
    details: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class LocalCliPreset:
    """Safe executable preset exposed to Web/API users."""

    preset_id: str
    executable: str
    argv: Sequence[str]
    display_name: str
    output_last_message_arg: Optional[str] = None
    extractor: Callable[[LocalCliExecutionResult], str] = lambda result: (
        result.final_message or result.stdout
    ).strip()
    contract_args: Sequence[str] = ()
    prompt_transport: str = "stdin"


CODEX_CLI_PRESET = LocalCliPreset(
    preset_id=CODEX_CLI_BACKEND_ID,
    executable="codex",
    argv=(
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--ephemeral",
        "-",
    ),
    display_name="Codex CLI",
    output_last_message_arg="--output-last-message",
    contract_args=(
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--ephemeral",
        "--output-last-message",
    ),
)

CLAUDE_CODE_CLI_PRESET = LocalCliPreset(
    preset_id=CLAUDE_CODE_CLI_BACKEND_ID,
    executable="claude",
    argv=(
        "--safe-mode",
        "--tools",
        "",
        "--disallowedTools",
        "mcp__*",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--output-format",
        "json",
        "-p",
        _CLAUDE_CODE_STATIC_INSTRUCTION,
    ),
    display_name="Claude Code CLI",
    extractor=lambda result: _extract_claude_code_json(result, schema_mode=False),
    contract_args=(
        "--safe-mode",
        "--tools",
        "",
        "--disallowedTools",
        "mcp__*",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--output-format",
        "json",
        "-p",
    ),
)

OPENCODE_CLI_PRESET = LocalCliPreset(
    preset_id=OPENCODE_CLI_BACKEND_ID,
    executable="opencode",
    argv=(
        "--pure",
        "run",
        "--format",
        "json",
        _OPENCODE_STATIC_INSTRUCTION,
        "--file",
        _PROMPT_FILE_PLACEHOLDER,
    ),
    display_name="OpenCode CLI",
    extractor=lambda result: _extract_opencode_json_events(result),
    contract_args=(
        "--pure",
        "run",
        "--format",
        "json",
        "--file",
    ),
    prompt_transport="file",
)

SAFE_LOCAL_CLI_PRESETS = {
    CODEX_CLI_BACKEND_ID: CODEX_CLI_PRESET,
    CLAUDE_CODE_CLI_BACKEND_ID: CLAUDE_CODE_CLI_PRESET,
    OPENCODE_CLI_BACKEND_ID: OPENCODE_CLI_PRESET,
}


def effective_local_cli_concurrency(config: Any) -> int:
    """Return the effective local CLI concurrency limit."""

    backend_limit = _positive_int(
        getattr(config, "generation_backend_max_concurrency", None),
        DEFAULT_GENERATION_BACKEND_MAX_CONCURRENCY,
    )
    local_limit = _positive_int(
        getattr(config, "local_cli_backend_max_concurrency", None),
        DEFAULT_LOCAL_CLI_BACKEND_MAX_CONCURRENCY,
    )
    backend_limit = min(backend_limit, MAX_GENERATION_BACKEND_MAX_CONCURRENCY)
    local_limit = min(local_limit, MAX_LOCAL_CLI_BACKEND_MAX_CONCURRENCY)
    return max(1, min(local_limit, backend_limit))


def build_local_cli_env(source: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Build an allowlisted child environment with sensitive names removed."""

    source_env = source if source is not None else os.environ
    child_env: Dict[str, str] = {}
    for key, value in source_env.items():
        upper = key.upper()
        allowed = upper in _SAFE_ENV_EXACT or any(
            upper.startswith(prefix) for prefix in _SAFE_ENV_PREFIXES
        )
        if not allowed or _is_sensitive_env_name(upper):
            continue
        child_env[key] = value
    return child_env


def _popen_session_kwargs() -> Dict[str, Any]:
    """Return platform-specific subprocess isolation kwargs."""

    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": creationflags} if creationflags else {}
    return {"start_new_session": True}


def redact_diagnostic_text(text: str, *, home: Optional[str] = None, limit: int = _PREVIEW_LIMIT) -> str:
    """Redact sensitive diagnostics and return a bounded preview."""

    redacted = text or ""
    home_path = home or os.path.expanduser("~")
    if home_path:
        redacted = redacted.replace(home_path, "~")
    redacted = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@", r"\1<redacted>@", redacted)
    redacted = _URL_PATTERN.sub(_redact_sensitive_diagnostic_url, redacted)
    redacted = re.sub(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s]+", r"\1<redacted>", redacted)
    redacted = re.sub(r"(?i)(cookie\s*[:=]\s*)[^\n\r]+", r"\1<redacted>", redacted)
    redacted = re.sub(r"(?i)(session[_-]?secret\s*[:=]\s*)[^\s]+", r"\1<redacted>", redacted)
    redacted = re.sub(r"\b(sk-[A-Za-z0-9_-]{12,})\b", "<redacted-api-key>", redacted)
    redacted = re.sub(r"\b(AIza[A-Za-z0-9_-]{16,})\b", "<redacted-api-key>", redacted)
    redacted = re.sub(r"\b(gh[pousr]_[A-Za-z0-9_]{16,})\b", "<redacted-token>", redacted)
    # Conservative by design: local CLI diagnostics may contain opaque long-lived credentials.
    redacted = re.sub(r"\b([A-Za-z0-9_-]{32,})\b", "<redacted-token>", redacted)
    if len(redacted) > limit:
        return redacted[:limit] + "...<truncated>"
    return redacted


def _redact_sensitive_diagnostic_url(match: re.Match[str]) -> str:
    url = match.group(0)
    return "<redacted-url>" if _is_sensitive_diagnostic_url(url) else url


def _is_sensitive_diagnostic_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return True
    if parsed.username or parsed.password:
        return True
    if _is_webhook_diagnostic_url(parsed.hostname or "", parsed.path):
        return True
    return (
        _has_sensitive_url_params(parsed.query)
        or _has_sensitive_url_params(parsed.fragment)
    )


def _is_webhook_diagnostic_url(hostname: str, path: str) -> bool:
    hostname = str(hostname or "").lower().strip(".")
    normalized_path = f"/{path.lstrip('/').lower()}"
    path_segments = {segment for segment in normalized_path.split("/") if segment}

    if hostname == "hooks.slack.com" and normalized_path.startswith("/services/"):
        return True
    if hostname == "oapi.dingtalk.com" and normalized_path.startswith("/robot/send"):
        return True
    if hostname in {"discord.com", "discordapp.com"} and "/api/webhooks/" in normalized_path:
        return True
    if hostname == "open.feishu.cn" and "/open-apis/bot/" in normalized_path and "/hook/" in normalized_path:
        return True
    if hostname == "qyapi.weixin.qq.com" and normalized_path.startswith("/cgi-bin/webhook/send"):
        return True
    if hostname.startswith("hooks."):
        return True
    return bool({"hook", "webhook", "webhooks"} & path_segments)


def _has_sensitive_url_params(params_text: str) -> bool:
    if not params_text:
        return False
    try:
        params = parse_qsl(params_text, keep_blank_values=True)
    except ValueError:
        return True
    for key, value in params:
        key_text = str(key or "").strip().lower().replace("-", "_")
        if key_text in _SENSITIVE_URL_KEY_PARTS or any(part in key_text for part in _SENSITIVE_URL_KEY_PARTS):
            return True
        if re.search(r"\b(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{16,}|[A-Za-z0-9_-]{32,})\b", str(value or "")):
            return True
    return False


def _extract_claude_code_json(result: LocalCliExecutionResult, *, schema_mode: bool) -> str:
    raw = (result.stdout or "").strip()
    if not raw:
        raise LocalCliExtractionError(
            GenerationErrorCode.EMPTY_OUTPUT,
            "empty_output",
        )
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LocalCliExtractionError(
            GenerationErrorCode.INVALID_JSON,
            "invalid_json",
            details={"error": redact_diagnostic_text(str(exc), limit=200)},
        ) from exc
    if not isinstance(envelope, dict):
        raise LocalCliExtractionError(
            GenerationErrorCode.SCHEMA_VALIDATION_FAILED,
            "schema_validation_failed",
            details={"expected": "object_envelope"},
        )

    event_type = str(envelope.get("type") or "").strip()
    subtype = str(envelope.get("subtype") or "").strip()
    if event_type != "result":
        raise LocalCliExtractionError(
            GenerationErrorCode.CAPABILITY_UNSUPPORTED,
            "unexpected_cli_event",
            retryable=False,
            details={"event_type": event_type or "missing"},
        )
    if subtype == "error_max_structured_output_retries":
        raise LocalCliExtractionError(
            GenerationErrorCode.SCHEMA_VALIDATION_FAILED,
            "structured_output_retries_exhausted",
        )
    if envelope.get("is_error") is True:
        raise LocalCliExtractionError(
            GenerationErrorCode.UNKNOWN_BACKEND_ERROR,
            "cli_result_error",
            retryable=False,
            details={"subtype": subtype or "unknown"},
        )
    if subtype != "success":
        raise LocalCliExtractionError(
            GenerationErrorCode.UNKNOWN_BACKEND_ERROR,
            "cli_result_not_success",
            retryable=False,
            details={"subtype": subtype or "missing"},
        )

    if schema_mode:
        if "structured_output" not in envelope:
            raise LocalCliExtractionError(
                GenerationErrorCode.SCHEMA_VALIDATION_FAILED,
                "missing_structured_output",
            )
        structured_output = envelope.get("structured_output")
        return json.dumps(
            structured_output,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    text = str(envelope.get("result") or "").strip()
    if not text:
        raise LocalCliExtractionError(
            GenerationErrorCode.EMPTY_OUTPUT,
            "empty_result",
        )
    return text


def _extract_opencode_json_events(result: LocalCliExecutionResult) -> str:
    raw = (result.stdout or "").strip()
    if not raw:
        raise LocalCliExtractionError(
            GenerationErrorCode.EMPTY_OUTPUT,
            "empty_output",
        )

    text_parts: list[str] = []
    saw_finish = False
    finish_reason = ""
    for event in _iter_opencode_events(raw):
        event_type = str(event.get("type") or "").strip()
        event_type_lower = event_type.lower()
        blocked_reason = _opencode_blocked_event_reason(event, event_type_lower)
        if blocked_reason:
            raise LocalCliExtractionError(
                GenerationErrorCode.CAPABILITY_UNSUPPORTED,
                "capability_unsupported",
                retryable=False,
                details={
                    "event_type": event_type or "missing",
                    "blocked_reason": blocked_reason,
                },
            )
        if event.get("error") or event.get("is_error") is True:
            raise LocalCliExtractionError(
                GenerationErrorCode.UNKNOWN_BACKEND_ERROR,
                "cli_result_error",
                retryable=False,
                details={"event_type": event_type or "missing"},
            )
        if event_type_lower not in _OPENCODE_ALLOWED_EVENT_TYPES:
            raise LocalCliExtractionError(
                GenerationErrorCode.CAPABILITY_UNSUPPORTED,
                "unexpected_cli_event",
                retryable=False,
                details={"event_type": event_type or "missing"},
            )

        if event_type_lower == "text":
            text_value = event.get("text")
            if text_value is None and isinstance(event.get("part"), dict):
                text_value = event["part"].get("text")
            if text_value:
                text_parts.append(str(text_value))
            continue

        if event_type_lower == "step_finish":
            saw_finish = True
            finish_reason = str(
                event.get("reason")
                or (
                    event.get("part", {}).get("reason")
                    if isinstance(event.get("part"), dict)
                    else ""
                )
                or ""
            ).strip().lower()

    if not saw_finish:
        raise LocalCliExtractionError(
            GenerationErrorCode.SCHEMA_VALIDATION_FAILED,
            "missing_step_finish",
        )
    if finish_reason and finish_reason not in {"stop", "end_turn", "complete", "completed"}:
        raise LocalCliExtractionError(
            GenerationErrorCode.CAPABILITY_UNSUPPORTED,
            "unexpected_finish_reason",
            retryable=False,
            details={"finish_reason": finish_reason},
        )

    text = "".join(text_parts).strip()
    if not text:
        raise LocalCliExtractionError(
            GenerationErrorCode.EMPTY_OUTPUT,
            "empty_text",
        )
    return text


def _iter_opencode_events(output_text: str) -> Iterator[Dict[str, Any]]:
    """Yield strict OpenCode JSON events from JSONL, arrays, or raw JSON output."""

    raw = str(output_text or "")
    decoder = json.JSONDecoder()
    index = 0
    event_index = 0
    length = len(raw)
    while index < length:
        while index < length and raw[index].isspace():
            index += 1
        if index >= length:
            break
        try:
            decoded, next_index = decoder.raw_decode(raw, index)
        except json.JSONDecodeError as exc:
            raise LocalCliExtractionError(
                GenerationErrorCode.INVALID_JSON,
                "invalid_json",
                details={"error": redact_diagnostic_text(str(exc), limit=200)},
            ) from exc
        if next_index <= index:
            raise LocalCliExtractionError(
                GenerationErrorCode.INVALID_JSON,
                "invalid_json",
                details={"error": "json_decoder_made_no_progress"},
            )
        index = next_index

        if isinstance(decoded, list):
            for item in decoded:
                event_index += 1
                yield _validate_opencode_event(item, event_index=event_index)
            continue

        event_index += 1
        yield _validate_opencode_event(decoded, event_index=event_index)


def _validate_opencode_event(value: Any, *, event_index: int) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise LocalCliExtractionError(
            GenerationErrorCode.SCHEMA_VALIDATION_FAILED,
            "schema_validation_failed",
            details={"event_index": event_index, "expected": "object_event"},
        )
    event_type = value.get("type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise LocalCliExtractionError(
            GenerationErrorCode.SCHEMA_VALIDATION_FAILED,
            "schema_validation_failed",
            details={"event_index": event_index, "expected": "event_type"},
        )
    return value


def _opencode_blocked_event_reason(event: Dict[str, Any], event_type_lower: str) -> str:
    if (
        event_type_lower in _OPENCODE_BLOCKED_EVENT_TYPES
        or any(blocked in event_type_lower for blocked in _OPENCODE_BLOCKED_EVENT_TYPES)
    ):
        return event_type_lower or "blocked_event"
    if event_type_lower in _OPENCODE_DISABLED_TOOL_NAMES:
        return event_type_lower

    for container in (event, event.get("part") if isinstance(event.get("part"), dict) else None):
        if not isinstance(container, dict):
            continue
        for key in ("name", "tool", "tool_name"):
            value = container.get(key)
            if isinstance(value, str) and value.strip().lower() in _OPENCODE_DISABLED_TOOL_NAMES:
                return value.strip().lower()
    return ""


def _is_cli_contract_unsupported(output_text: str) -> bool:
    text = str(output_text or "").lower()
    return any(marker in text for marker in _UNSUPPORTED_ARG_MARKERS)


def _opencode_output_has_error_event(output_text: str) -> bool:
    try:
        events = _iter_opencode_events(output_text)
        for event in events:
            event_type_lower = str(event.get("type") or "").strip().lower()
            if (
                _opencode_blocked_event_reason(event, event_type_lower)
                or bool(event.get("error"))
                or event.get("is_error") is True
            ):
                return True
    except LocalCliExtractionError:
        return False
    return False


def resolve_local_cli_preset(preset_id: str) -> LocalCliPreset:
    """Return a safe preset or raise a structured unsafe_config error."""

    preset = SAFE_LOCAL_CLI_PRESETS.get((preset_id or "").strip().lower())
    if preset is None:
        raise GenerationError(
            error_code=GenerationErrorCode.UNSAFE_CONFIG,
            stage="configuration",
            retryable=False,
            fallbackable=False,
            backend=preset_id or "local_cli",
            provider=preset_id or "local_cli",
            details={
                "reason": "unknown_local_cli_preset",
                "preset_id": preset_id,
                "allowed_presets": sorted(SAFE_LOCAL_CLI_PRESETS),
            },
        )
    return preset


class LocalCliGenerationBackend(GenerationBackend):
    """Restricted subprocess-backed generation backend."""

    capabilities = GenerationCapabilities(
        supports_json=True,
        supports_tools=False,
        supports_stream=False,
        supports_vision=False,
        supports_health_check=False,
        supports_smoke_test=False,
    )

    def __init__(
        self,
        config: Any,
        *,
        preset_id: str = CODEX_CLI_BACKEND_ID,
        preset: Optional[LocalCliPreset] = None,
    ) -> None:
        self._config = config
        self._preset = preset or resolve_local_cli_preset(preset_id)

    @property
    def backend_id(self) -> str:
        return self._preset.preset_id

    @property
    def preset_id(self) -> str:
        return self._preset.preset_id

    def get_config_error(self) -> Optional[GenerationError]:
        """Return executable/config validation errors without running a prompt."""

        try:
            self._resolve_command()
        except GenerationError as exc:
            return exc
        return None

    def generate(
        self,
        prompt: str,
        generation_config: Dict[str, Any],
        *,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        stream_progress_callback: Optional[Callable[[int], None]] = None,
        response_validator: Optional[Callable[[str], None]] = None,
        audit_context: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        executable, argv, executable_summary = self._resolve_command()
        timeout_seconds = min(
            _positive_int(
                getattr(self._config, "generation_backend_timeout_seconds", None),
                DEFAULT_LOCAL_CLI_TIMEOUT_SECONDS,
            ),
            MAX_LOCAL_CLI_TIMEOUT_SECONDS,
        )
        max_output_bytes = min(
            _positive_int(
                getattr(self._config, "generation_backend_max_output_bytes", None),
                DEFAULT_LOCAL_CLI_MAX_OUTPUT_BYTES,
            ),
            MAX_LOCAL_CLI_OUTPUT_BYTES,
        )
        concurrency_limit = effective_local_cli_concurrency(self._config)

        prompt_text = prompt
        if system_prompt:
            prompt_text = f"{system_prompt.strip()}\n\n{prompt}"

        diagnostics: Dict[str, Any] = {
            "preset_id": self._preset.preset_id,
            "executable": executable_summary,
            "contract_args": list(self._preset.contract_args),
            "stream_degraded": bool(stream),
            "timeout_seconds": timeout_seconds,
            "max_output_bytes": max_output_bytes,
            "concurrency_limit": concurrency_limit,
        }

        stdout = ""
        stderr = ""
        text = ""
        stdio_output_bytes = 0
        final_output_bytes = 0
        last_message_path: Optional[Path] = None

        with _local_cli_concurrency_slot(concurrency_limit):
            self._emit_progress(stream_progress_callback, 0)
            try:
                with tempfile.TemporaryDirectory(prefix="dsa-local-cli-") as cwd:
                    cwd_path = Path(cwd)
                    try:
                        cwd_path.chmod(0o700)
                    except OSError:
                        pass
                    diagnostics["cwd_kind"] = "temporary"
                    child_env = build_local_cli_env()
                    child_env.update(self._build_preset_child_env(cwd_path, diagnostics))
                    diagnostics["env_allowlist_names"] = sorted(child_env)
                    diagnostics["runtime_argv_contract_checked"] = True
                    prompt_path = cwd_path / "prompt.txt"
                    stdout_path = cwd_path / "stdout.txt"
                    stderr_path = cwd_path / "stderr.txt"
                    prompt_path.write_text(prompt_text, encoding="utf-8")
                    try:
                        prompt_path.chmod(0o600)
                    except OSError:
                        pass
                    self._prepare_preset_runtime_files(cwd_path, prompt_path, diagnostics)
                    command_argv, last_message_path = self._build_runtime_argv(
                        argv,
                        cwd,
                        prompt_path=prompt_path,
                    )
                    with ExitStack() as stack:
                        if self._preset.prompt_transport == "stdin":
                            stdin_handle = stack.enter_context(
                                prompt_path.open("r", encoding="utf-8")
                            )
                        elif self._preset.prompt_transport == "file":
                            stdin_handle = subprocess.DEVNULL
                            diagnostics["prompt_transport"] = "file"
                            diagnostics["prompt_file_mode"] = "0600"
                        else:
                            raise self._error(
                                GenerationErrorCode.UNSAFE_CONFIG,
                                stage="configuration",
                                retryable=False,
                                fallbackable=False,
                                details={
                                    **diagnostics,
                                    "reason": "unsupported_prompt_transport",
                                    "prompt_transport": self._preset.prompt_transport,
                                },
                            )
                        stdout_handle = stack.enter_context(stdout_path.open("wb"))
                        stderr_handle = stack.enter_context(stderr_path.open("wb"))
                        process = subprocess.Popen(
                            [executable, *command_argv],
                            stdin=stdin_handle,
                            stdout=stdout_handle,
                            stderr=stderr_handle,
                            cwd=cwd,
                            env=child_env,
                            text=True,
                            shell=False,
                            **_popen_session_kwargs(),
                        )
                        self._emit_progress(stream_progress_callback, 1)
                        deadline = time.monotonic() + timeout_seconds
                        while True:
                            stdout_handle.flush()
                            stderr_handle.flush()
                            try:
                                stdio_output_bytes = _combined_path_size_required(stdout_path, stderr_path)
                            except OSError as exc:
                                self._terminate_process_group(process)
                                diagnostics.update(_preview_diagnostics_from_files(stdout_path, stderr_path))
                                raise self._output_file_error(
                                    diagnostics,
                                    reason="output_stat_failed",
                                    exc=exc,
                                ) from exc
                            if stdio_output_bytes > max_output_bytes:
                                self._terminate_process_group(process)
                                diagnostics.update(_preview_diagnostics_from_files(stdout_path, stderr_path))
                                raise self._error(
                                    GenerationErrorCode.OUTPUT_TOO_LARGE,
                                    stage="execution",
                                    retryable=False,
                                    fallbackable=True,
                                    details={
                                        **diagnostics,
                                        "reason": "output_too_large",
                                        "output_bytes": stdio_output_bytes,
                                    },
                                )
                            if process.poll() is not None:
                                break
                            if time.monotonic() >= deadline:
                                self._terminate_process_group(process)
                                diagnostics.update(_preview_diagnostics_from_files(stdout_path, stderr_path))
                                raise self._error(
                                    GenerationErrorCode.TIMEOUT,
                                    stage="execution",
                                    retryable=True,
                                    fallbackable=True,
                                    details={
                                        **diagnostics,
                                        "reason": "timeout",
                                        "timeout_seconds": timeout_seconds,
                                    },
                                )
                            time.sleep(_PROCESS_POLL_INTERVAL_SECONDS)

                    try:
                        stdio_output_bytes = _combined_path_size_required(stdout_path, stderr_path)
                    except OSError as exc:
                        diagnostics.update(_preview_diagnostics_from_files(stdout_path, stderr_path))
                        raise self._output_file_error(
                            diagnostics,
                            reason="output_stat_failed",
                            exc=exc,
                        ) from exc
                    if stdio_output_bytes > max_output_bytes:
                        diagnostics.update(_preview_diagnostics_from_files(stdout_path, stderr_path))
                        raise self._error(
                            GenerationErrorCode.OUTPUT_TOO_LARGE,
                            stage="execution",
                            retryable=False,
                            fallbackable=True,
                            details={
                                **diagnostics,
                                "reason": "output_too_large",
                                "output_bytes": stdio_output_bytes,
                            },
                        )
                    try:
                        stdout = _read_text_file_required(stdout_path)
                        stderr = _read_text_file_required(stderr_path)
                    except OSError as exc:
                        diagnostics.update(_preview_diagnostics_from_files(stdout_path, stderr_path))
                        raise self._output_file_error(
                            diagnostics,
                            reason="output_read_failed",
                            exc=exc,
                        ) from exc
                    if last_message_path is not None:
                        diagnostics["output_source"] = "output_last_message"
                        if process.returncode != 0:
                            preview_stdout, omitted = _stdout_preview_without_repeated_final_message(
                                stdout,
                                last_message_path,
                                max_output_bytes,
                            )
                            diagnostics.update(_preview_diagnostics(preview_stdout, stderr))
                            if omitted:
                                diagnostics["stdout_final_message_omitted"] = True
                            raise self._non_zero_exit_error(
                                process.returncode,
                                stdout,
                                stderr,
                                diagnostics,
                            )

                        try:
                            final_output_bytes = _path_size_required(last_message_path)
                        except FileNotFoundError as exc:
                            diagnostics.update(_preview_diagnostics(stdout, stderr))
                            raise self._error(
                                GenerationErrorCode.EMPTY_OUTPUT,
                                stage="execution",
                                retryable=True,
                                fallbackable=True,
                                details={
                                    **diagnostics,
                                    "reason": "missing_last_message_output",
                                    "error": redact_diagnostic_text(str(exc), limit=200),
                                },
                            ) from exc
                        except OSError as exc:
                            diagnostics.update(_preview_diagnostics(stdout, stderr))
                            raise self._output_file_error(
                                diagnostics,
                                reason="output_stat_failed",
                                exc=exc,
                            ) from exc
                        if final_output_bytes > max_output_bytes:
                            diagnostics.update(
                                _preview_diagnostics(_STDOUT_PREVIEW_OMITTED, stderr)
                            )
                            raise self._error(
                                GenerationErrorCode.OUTPUT_TOO_LARGE,
                                stage="execution",
                                retryable=False,
                                fallbackable=True,
                                details={
                                    **diagnostics,
                                    "reason": "output_too_large",
                                    "output_bytes": final_output_bytes,
                                },
                            )
                        try:
                            text = _read_text_file_required(last_message_path).strip()
                        except OSError as exc:
                            diagnostics.update(_preview_diagnostics(stdout, stderr))
                            raise self._output_file_error(
                                diagnostics,
                                reason="output_read_failed",
                                exc=exc,
                            ) from exc
                        diagnostic_stdout, omitted = _strip_repeated_final_message_from_stdout(
                            stdout,
                            text,
                            replacement="",
                        )
                        preview_stdout, _ = _strip_repeated_final_message_from_stdout(
                            stdout,
                            text,
                            replacement=_FINAL_MESSAGE_OMITTED_PREVIEW,
                        )
                        stdio_output_bytes = _text_size_bytes(diagnostic_stdout) + _text_size_bytes(
                            stderr
                        )
                        diagnostics.update(_preview_diagnostics(preview_stdout, stderr))
                        if omitted:
                            diagnostics["stdout_final_message_omitted"] = True
                    else:
                        diagnostics.update(_preview_diagnostics(stdout, stderr))
                        if process.returncode != 0:
                            raise self._non_zero_exit_error(
                                process.returncode,
                                stdout,
                                stderr,
                                diagnostics,
                            )
                        diagnostics["output_source"] = "stdout"
                        text = (stdout or "").strip()
            except OSError as exc:
                if _is_command_not_executable_error(exc):
                    raise self._error(
                        GenerationErrorCode.COMMAND_NOT_EXECUTABLE,
                        stage="execution",
                        retryable=False,
                        fallbackable=True,
                        details={
                            **diagnostics,
                            "reason": "process_start_failed",
                            "error": redact_diagnostic_text(str(exc), limit=200),
                        },
                    ) from exc
                raise self._error(
                    GenerationErrorCode.UNKNOWN_BACKEND_ERROR,
                    stage="execution",
                    retryable=False,
                    fallbackable=True,
                    details={
                        **diagnostics,
                        "reason": "process_start_failed",
                        "error": redact_diagnostic_text(str(exc), limit=200),
                    },
                ) from exc

        raw_result = LocalCliExecutionResult(
            stdout=stdout,
            stderr=stderr,
            returncode=0,
            final_message=text,
            diagnostics=diagnostics,
        )
        try:
            text = self._preset.extractor(raw_result)
        except LocalCliExtractionError as exc:
            raise self._error(
                exc.error_code,
                stage="validation",
                retryable=exc.retryable,
                fallbackable=exc.fallbackable,
                details={
                    **diagnostics,
                    "reason": exc.reason,
                    **(exc.details or {}),
                },
            ) from exc
        except GenerationError:
            raise
        except Exception as exc:
            raise self._error(
                GenerationErrorCode.UNKNOWN_BACKEND_ERROR,
                stage="validation",
                retryable=False,
                fallbackable=True,
                details={
                    **diagnostics,
                    "reason": "extractor_failed",
                    "error": redact_diagnostic_text(str(exc), limit=200),
                },
            ) from exc

        total_output_bytes = stdio_output_bytes + final_output_bytes
        if total_output_bytes > max_output_bytes:
            raise self._error(
                GenerationErrorCode.OUTPUT_TOO_LARGE,
                stage="execution",
                retryable=False,
                fallbackable=True,
                details={
                    **diagnostics,
                    "reason": "output_too_large",
                    "output_bytes": total_output_bytes,
                },
            )

        if not text:
            reason = "empty_last_message_output" if last_message_path is not None else "empty_stdout"
            raise self._error(
                GenerationErrorCode.EMPTY_OUTPUT,
                stage="execution",
                retryable=True,
                fallbackable=True,
                details={**diagnostics, "reason": reason},
            )

        self._emit_progress(stream_progress_callback, 2)
        if response_validator is not None:
            try:
                response_validator(text)
            except GenerationError:
                raise
            except Exception as exc:
                raise self._error(
                    GenerationErrorCode.INVALID_JSON,
                    stage="validation",
                    retryable=True,
                    fallbackable=True,
                    details={
                        **diagnostics,
                        "reason": str(exc) or "invalid_json",
                    },
                ) from exc

        return GenerationResult(
            text=text,
            model=self._preset.preset_id,
            provider=self._preset.preset_id,
            backend=self.backend_id,
            usage={
                "usage_available": False,
                "usage_source": "unavailable",
                "backend": self._preset.preset_id,
            },
            raw=None,
            diagnostics=diagnostics,
        )

    def _resolve_command(self) -> tuple[str, list[str], Dict[str, str]]:
        tokens = [self._preset.executable, *self._preset.argv]
        if self._preset.output_last_message_arg:
            tokens.append(self._preset.output_last_message_arg)
        unsafe = _first_unsafe_token(tokens)
        if unsafe:
            raise self._error(
                GenerationErrorCode.UNSAFE_CONFIG,
                stage="configuration",
                retryable=False,
                fallbackable=False,
                details={"reason": "shell_metachar", "token_preview": unsafe},
            )

        resolved = shutil.which(self._preset.executable)
        if not resolved:
            raise self._error(
                GenerationErrorCode.COMMAND_NOT_FOUND,
                stage="configuration",
                retryable=False,
                fallbackable=True,
                details={
                    "reason": "executable_not_found",
                    "preset_id": self._preset.preset_id,
                    "executable_basename": Path(self._preset.executable).name,
                },
            )
        if not os.access(resolved, os.X_OK):
            raise self._error(
                GenerationErrorCode.COMMAND_NOT_EXECUTABLE,
                stage="configuration",
                retryable=False,
                fallbackable=True,
                details={
                    "reason": "executable_not_executable",
                    "preset_id": self._preset.preset_id,
                    "executable": _executable_summary(resolved),
                },
            )
        return resolved, list(self._preset.argv), _executable_summary(resolved)

    def _build_runtime_argv(
        self,
        argv: Sequence[str],
        cwd: str,
        *,
        prompt_path: Optional[Path] = None,
    ) -> tuple[list[str], Optional[Path]]:
        output_arg = self._preset.output_last_message_arg
        if not output_arg:
            runtime_argv = self._replace_runtime_placeholders(list(argv), prompt_path)
            self._validate_runtime_contract_args(runtime_argv)
            return runtime_argv, None

        last_message_path = Path(cwd) / "last-message.txt"
        runtime_argv = self._replace_runtime_placeholders(list(argv), prompt_path)
        injected = [output_arg, str(last_message_path)]
        if runtime_argv and runtime_argv[-1] == "-":
            runtime_argv = [*runtime_argv[:-1], *injected, runtime_argv[-1]]
        else:
            runtime_argv = [*runtime_argv, *injected]

        unsafe = _first_unsafe_token(runtime_argv)
        if unsafe:
            raise self._error(
                GenerationErrorCode.UNSAFE_CONFIG,
                stage="configuration",
                retryable=False,
                fallbackable=False,
                details={"reason": "shell_metachar", "token_preview": unsafe},
            )
        self._validate_runtime_contract_args(runtime_argv)
        return runtime_argv, last_message_path

    def _replace_runtime_placeholders(
        self,
        argv: list[str],
        prompt_path: Optional[Path],
    ) -> list[str]:
        if self._preset.preset_id != OPENCODE_CLI_BACKEND_ID:
            return argv
        model = self._get_opencode_cli_model()
        if prompt_path is None:
            raise self._error(
                GenerationErrorCode.UNSAFE_CONFIG,
                stage="configuration",
                retryable=False,
                fallbackable=False,
                details={"reason": "missing_prompt_file"},
            )
        runtime_argv = [
            str(prompt_path) if token == _PROMPT_FILE_PLACEHOLDER else token
            for token in argv
        ]
        if model:
            try:
                format_index = runtime_argv.index("--format")
                insert_at = format_index + 2
            except ValueError:
                insert_at = 0
            runtime_argv = [
                *runtime_argv[:insert_at],
                "--model",
                model,
                *runtime_argv[insert_at:],
            ]
        return runtime_argv

    def _get_opencode_cli_model(self) -> str:
        model = str(getattr(self._config, "opencode_cli_model", "") or "").strip()
        if not model:
            return ""
        unsafe = _first_unsafe_token([model])
        if unsafe or any(ch.isspace() for ch in model) or "$" in model:
            raise self._error(
                GenerationErrorCode.UNSAFE_CONFIG,
                stage="configuration",
                retryable=False,
                fallbackable=False,
                details={
                    "reason": "unsafe_opencode_cli_model",
                    "field": "OPENCODE_CLI_MODEL",
                    "token_preview": unsafe or redact_diagnostic_text(model, limit=120),
                },
            )
        return model

    def _build_preset_child_env(
        self,
        cwd: Path,
        diagnostics: Dict[str, Any],
    ) -> Dict[str, str]:
        if self._preset.preset_id != OPENCODE_CLI_BACKEND_ID:
            return {}
        diagnostics["opencode_child_env_hardened"] = True
        diagnostics["opencode_provider_credentials_managed_by_dsa"] = False
        return {
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "true",
            "OPENCODE_DISABLE_CLAUDE_CODE": "true",
            "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT": "true",
            "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "true",
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
            "OPENCODE_DISABLE_LSP_DOWNLOAD": "true",
        }

    def _prepare_preset_runtime_files(
        self,
        cwd: Path,
        prompt_path: Path,
        diagnostics: Dict[str, Any],
    ) -> None:
        if self._preset.preset_id != OPENCODE_CLI_BACKEND_ID:
            return
        diagnostics["opencode_model_override"] = bool(self._get_opencode_cli_model())
        config = {
            "$schema": "https://opencode.ai/config.json",
            "share": "disabled",
            "autoupdate": False,
            "snapshot": False,
            "mcp": {},
            "plugin": [],
            "instructions": [],
            "tools": {tool_name: False for tool_name in _OPENCODE_DISABLED_TOOL_NAMES},
        }
        config_path = cwd / "opencode.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            config_path.chmod(0o600)
        except OSError:
            pass
        diagnostics["opencode_project_config_written"] = True
        diagnostics["opencode_config_contains_provider_credentials"] = False
        diagnostics["opencode_prompt_file"] = prompt_path.name

    def _validate_runtime_contract_args(self, runtime_argv: Sequence[str]) -> None:
        runtime_tokens = [str(arg) for arg in runtime_argv]
        missing_contract_args: list[str] = []
        search_start = 0
        for contract_arg in self._preset.contract_args:
            contract_token = str(contract_arg)
            try:
                matched_at = runtime_tokens.index(contract_token, search_start)
            except ValueError:
                missing_contract_args.append(contract_token)
                continue
            search_start = matched_at + 1
        if missing_contract_args:
            raise self._error(
                GenerationErrorCode.CAPABILITY_UNSUPPORTED,
                stage="configuration",
                retryable=False,
                fallbackable=True,
                details={
                    "reason": "missing_runtime_contract_arg",
                    "missing_contract_args": [
                        redact_diagnostic_text(str(arg), limit=120)
                        for arg in missing_contract_args
                    ],
                    "preset_id": self._preset.preset_id,
                },
            )

    def _non_zero_exit_error(
        self,
        returncode: int,
        stdout: str,
        stderr: str,
        diagnostics: Dict[str, Any],
    ) -> GenerationError:
        combined = f"{stdout}\n{stderr}".lower()
        code = GenerationErrorCode.NON_ZERO_EXIT
        reason = "non_zero_exit"
        if _is_cli_contract_unsupported(combined):
            code = GenerationErrorCode.CAPABILITY_UNSUPPORTED
            reason = "cli_contract_unsupported"
        elif (
            self._preset.preset_id == OPENCODE_CLI_BACKEND_ID
            and _opencode_output_has_error_event(f"{stdout}\n{stderr}")
        ):
            code = GenerationErrorCode.UNKNOWN_BACKEND_ERROR
            reason = "cli_result_error"
        elif "login" in combined or "authentication" in combined or "not authenticated" in combined:
            code = GenerationErrorCode.LOGIN_REQUIRED
            reason = "login_required"
        elif "approval" in combined or "approve" in combined or "permission" in combined:
            code = GenerationErrorCode.APPROVAL_REQUIRED
            reason = "approval_required"
        elif "tty" in combined or "interactive" in combined or "prompt" in combined:
            code = GenerationErrorCode.INTERACTIVE_PROMPT_REQUIRED
            reason = "interactive_prompt_required"
        return self._error(
            code,
            stage="execution",
            retryable=False,
            fallbackable=True,
            details={**diagnostics, "reason": reason, "returncode": returncode},
        )

    def _output_file_error(
        self,
        diagnostics: Dict[str, Any],
        *,
        reason: str,
        exc: OSError,
    ) -> GenerationError:
        return self._error(
            GenerationErrorCode.UNKNOWN_BACKEND_ERROR,
            stage="execution",
            retryable=True,
            fallbackable=True,
            details={
                **diagnostics,
                "reason": reason,
                "error": redact_diagnostic_text(str(exc), limit=200),
            },
        )

    def _error(
        self,
        error_code: GenerationErrorCode,
        *,
        stage: str,
        retryable: bool,
        fallbackable: bool,
        details: Dict[str, Any],
    ) -> GenerationError:
        return GenerationError(
            error_code=error_code,
            stage=stage,
            retryable=retryable,
            fallbackable=fallbackable,
            backend=self.backend_id,
            provider=self._preset.preset_id,
            details=details,
        )

    @staticmethod
    def _emit_progress(callback: Optional[Callable[[int], None]], value: int) -> None:
        if callback is None:
            return
        try:
            callback(value)
        except Exception:
            return

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
            if ctrl_break is not None:
                try:
                    process.send_signal(ctrl_break)
                    process.wait(timeout=2)
                    return
                except Exception:
                    pass
            try:
                process.terminate()
            except Exception:
                return
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except Exception:
                    return
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    return
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except Exception:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except Exception:
                process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return


@contextmanager
def _local_cli_concurrency_slot(limit: int):
    global _CONCURRENCY_ACTIVE
    normalized_limit = max(1, int(limit or 1))
    with _CONCURRENCY_CONDITION:
        _CONCURRENCY_CONDITION.wait_for(lambda: _CONCURRENCY_ACTIVE < normalized_limit)
        _CONCURRENCY_ACTIVE += 1
    try:
        yield
    finally:
        with _CONCURRENCY_CONDITION:
            _CONCURRENCY_ACTIVE -= 1
            _CONCURRENCY_CONDITION.notify_all()


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _is_command_not_executable_error(exc: OSError) -> bool:
    if not isinstance(exc, OSError):
        return False
    if os.name == "nt" and getattr(exc, "winerror", None) == 193:
        return True
    return False


def _is_sensitive_env_name(upper_name: str) -> bool:
    return any(pattern in upper_name for pattern in _SENSITIVE_ENV_PATTERNS)


def _first_unsafe_token(tokens: Sequence[str]) -> str:
    for token in tokens:
        value = str(token)
        if any(marker in value for marker in _SHELL_META_CHARS):
            return redact_diagnostic_text(value, limit=120)
        if any(marker in value for marker in _SHELL_META_STRINGS):
            return redact_diagnostic_text(value, limit=120)
    return ""


def _executable_summary(path: str) -> Dict[str, str]:
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]
    return {
        "basename": Path(path).name,
        "path_hash": digest,
    }


def _preview_diagnostics(stdout: str, stderr: str) -> Dict[str, str]:
    return {
        "stdout_preview": redact_diagnostic_text(stdout or ""),
        "stderr_preview": redact_diagnostic_text(stderr or ""),
    }


def _preview_diagnostics_from_files(stdout_path: Path, stderr_path: Path) -> Dict[str, str]:
    return _preview_diagnostics(
        _read_text_file(stdout_path, limit_bytes=_PREVIEW_LIMIT * 4),
        _read_text_file(stderr_path, limit_bytes=_PREVIEW_LIMIT * 4),
    )


def _stdout_preview_without_repeated_final_message(
    stdout: str,
    final_message_path: Path,
    max_output_bytes: int,
) -> tuple[str, bool]:
    try:
        if _path_size_required(final_message_path) > max_output_bytes:
            return _STDOUT_PREVIEW_OMITTED, True
        final_message = _read_text_file_required(final_message_path).strip()
    except OSError:
        return stdout, False
    return _strip_repeated_final_message_from_stdout(
        stdout,
        final_message,
        replacement=_FINAL_MESSAGE_OMITTED_PREVIEW,
    )


def _strip_repeated_final_message_from_stdout(
    stdout: str,
    final_message: str,
    *,
    replacement: str,
) -> tuple[str, bool]:
    final = (final_message or "").strip()
    if not final or final not in stdout:
        return stdout, False
    return stdout.replace(final, replacement), True


def _text_size_bytes(text: str) -> int:
    return len((text or "").encode("utf-8", errors="replace"))


def _combined_path_size_required(*paths: Path) -> int:
    return sum(_path_size_required(path) for path in paths)


def _path_size_required(path: Path) -> int:
    return path.stat().st_size


def _read_text_file(path: Path, *, limit_bytes: Optional[int] = None) -> str:
    try:
        with path.open("rb") as handle:
            raw = handle.read() if limit_bytes is None else handle.read(limit_bytes)
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def _read_text_file_required(path: Path) -> str:
    with path.open("rb") as handle:
        raw = handle.read()
    return raw.decode("utf-8", errors="replace")
