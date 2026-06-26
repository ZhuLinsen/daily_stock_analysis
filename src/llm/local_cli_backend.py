# -*- coding: utf-8 -*-
"""Local CLI generation backend.

Phase 2 exposes a restricted Codex CLI preset as an opt-in generation backend.
It is intentionally process-oriented. Generic safe presets treat stdout as the
model output; the Codex CLI preset reads its final answer from
``--output-last-message`` because stdout includes session diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional, Sequence
from urllib.parse import parse_qsl, urlsplit

from src.llm.backend_registry import CODEX_CLI_BACKEND_ID
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
_PRESET_CONTRACT_ARGS = (
    "--output-last-message",
    "--skip-git-repo-check",
    "--sandbox",
    "--color",
    "--ephemeral",
)
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
    "HOMEDRIVE",
    "HOMEPATH",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "NO_COLOR",
    "TERM",
    "CODEX_HOME",
    "SYSTEMROOT",
    "WINDIR",
    "PATHEXT",
    "COMSPEC",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
}
_SAFE_ENV_PREFIXES = ("CODEX_CLI_",)
_SENSITIVE_ENV_PATTERNS = (
    "API_KEY",
    "API_KEYS",
    "AUTHORIZATION",
    "COOKIE",
    "DATABASE_URL",
    "DB_URL",
    "FEISHU",
    "GEMINI",
    "GITHUB_TOKEN",
    "OPENAI",
    "ANTHROPIC",
    "DEEPSEEK",
    "SECRET",
    "SESSION",
    "TOKEN",
    "TUSHARE",
    "WEBHOOK",
)
_CONCURRENCY_CONDITION = threading.Condition()
_CONCURRENCY_ACTIVE = 0


@dataclass(frozen=True)
class LocalCliPreset:
    """Safe executable preset exposed to Web/API users."""

    preset_id: str
    executable: str
    argv: Sequence[str]
    display_name: str
    experimental: bool = True
    output_last_message_arg: Optional[str] = None


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
    experimental=True,
    output_last_message_arg="--output-last-message",
)

SAFE_LOCAL_CLI_PRESETS = {
    CODEX_CLI_BACKEND_ID: CODEX_CLI_PRESET,
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


def _is_cli_contract_unsupported(output_text: str) -> bool:
    text = str(output_text or "").lower()
    return (
        any(arg in text for arg in _PRESET_CONTRACT_ARGS)
        and any(marker in text for marker in _UNSUPPORTED_ARG_MARKERS)
    )


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

    backend_id = CODEX_CLI_BACKEND_ID
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
            child_env = build_local_cli_env()
            try:
                with tempfile.TemporaryDirectory(prefix="dsa-local-cli-") as cwd:
                    diagnostics["cwd_kind"] = "temporary"
                    command_argv, last_message_path = self._build_runtime_argv(argv, cwd)
                    prompt_path = Path(cwd) / "prompt.txt"
                    stdout_path = Path(cwd) / "stdout.txt"
                    stderr_path = Path(cwd) / "stderr.txt"
                    prompt_path.write_text(prompt_text, encoding="utf-8")
                    with (
                        prompt_path.open("r", encoding="utf-8") as prompt_handle,
                        stdout_path.open("wb") as stdout_handle,
                        stderr_path.open("wb") as stderr_handle,
                    ):
                        process = subprocess.Popen(
                            [executable, *command_argv],
                            stdin=prompt_handle,
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
                "backend": self.backend_id,
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
    ) -> tuple[list[str], Optional[Path]]:
        output_arg = self._preset.output_last_message_arg
        if not output_arg:
            return list(argv), None

        last_message_path = Path(cwd) / "last-message.txt"
        runtime_argv = list(argv)
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
        return runtime_argv, last_message_path

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
            reason = "cli_contract_unsupported"
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
