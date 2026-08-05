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
from functools import lru_cache
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
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Sequence, Tuple
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
_ANSI_ESCAPE_PATTERN = re.compile(
    r"""
    \x1B
    (?:
        \[[0-?]*[ -/]*[@-~]
        |
        \][^\x07\x1B]*(?:\x07|\x1B\\)
        |
        [@-_]
    )
    """,
    re.VERBOSE,
)
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
_SENSITIVE_ENV_EXACT_NAMES = frozenset({
    "AIHUBMIX_KEY",
    "DINGTALK_APP_KEY",
    "LONGBRIDGE_APP_KEY",
    "PUSHOVER_USER_KEY",
    "WECOM_ENCODING_AES_KEY",
})
_SENSITIVE_DIAGNOSTIC_FIELDS = frozenset({
    "access_token",
    "access_key",
    "access_key_id",
    "api_key",
    "api_keys",
    "apikey",
    "api_secret",
    "app_secret",
    "auth_token",
    "authorization",
    "client_secret",
    "cookie",
    "credential",
    "credentials",
    "csrf_token",
    "database_url",
    "db_url",
    "github_token",
    "id_token",
    "encryption_key",
    "password",
    "passwd",
    "private_key",
    "proxy_authorization",
    "refresh_token",
    "secret",
    "secret_access_key",
    "secret_key",
    "sendkey",
    "set_cookie",
    "session_secret",
    "signing_key",
    "token",
    "tushare_token",
    "verification_token",
    "webhook",
    "webhook_url",
})
_SENSITIVE_DIAGNOSTIC_FIELD_SUFFIXES = (
    "_access_key",
    "_access_key_id",
    "_access_token",
    "_api_key",
    "_api_keys",
    "_api_secret",
    "_app_secret",
    "_auth_token",
    "_client_secret",
    "_credential",
    "_credentials",
    "_database_url",
    "_db_url",
    "_encryption_key",
    "_password",
    "_passwd",
    "_private_key",
    "_secret",
    "_secret_access_key",
    "_secret_key",
    "_sendkey",
    "_session_secret",
    "_signing_key",
    "_token",
    "_webhook",
    "_webhook_url",
)
_DIGEST_AUTH_PARAM_NAMES = frozenset({
    "algorithm",
    "charset",
    "cnonce",
    "nc",
    "nonce",
    "opaque",
    "qop",
    "realm",
    "response",
    "uri",
    "userhash",
    "username",
})
_DIAGNOSTIC_ASSIGNMENT_VALUE_PATTERN = r"""
    (?P<value>
        (?:
            "(?:\\.|[^"\\])*"
            |
            '(?:''|\\.|[^'\\])*'
            |
            \\\r?\n[ \t]*
            |
            \\[^\r\n]
            |
            [^\s,;}\]"']
        )+
    )
"""


@lru_cache(maxsize=1)
def _diagnostic_field_name_pattern() -> str:
    """Build field syntax after the lazy config registry can be imported safely."""

    sensitive_names = (
        {name.upper() for name in _SENSITIVE_DIAGNOSTIC_FIELDS}
        | _SENSITIVE_ENV_EXACT_NAMES
        | _registered_sensitive_env_exact_names()
    )
    title_patterns = sorted(
        (re.escape(title) for title in _registered_sensitive_field_titles()),
        key=len,
        reverse=True,
    )
    spaced_sensitive_names = sorted(
        (
            re.escape(name).replace("_", r"[ \t]+")
            for name in sensitive_names
            if "_" in name
        ),
        key=len,
        reverse=True,
    )
    explicit_sensitive_names = "|".join(title_patterns + spaced_sensitive_names)
    return (
        rf"(?:(?i:{explicit_sensitive_names})|"
        r"[A-Za-z][A-Za-z0-9_-]*)"
    )


@lru_cache(maxsize=1)
def _diagnostic_field_assignment_pattern() -> re.Pattern[str]:
    return re.compile(
        rf"""
        (?<![A-Za-z0-9_-])
        (?P<name_quote>'?)
        (?P<name>{_diagnostic_field_name_pattern()})
        (?P=name_quote)
        (?P<separator>[ \t]*(?:=|:)[ \t]*)
        {_DIAGNOSTIC_ASSIGNMENT_VALUE_PATTERN}
        """,
        re.VERBOSE,
    )


@lru_cache(maxsize=1)
def _diagnostic_json_assignment_pattern() -> re.Pattern[str]:
    return re.compile(
        rf"""
        "
        (?P<name>(?:\\.|[^"\\])*)
        "
        (?P<separator>[ \t\r\n]*:[ \t\r\n]*)
        {_DIAGNOSTIC_ASSIGNMENT_VALUE_PATTERN}
        """,
        re.VERBOSE,
    )


@lru_cache(maxsize=1)
def _diagnostic_line_field_pattern() -> re.Pattern[str]:
    field_name_pattern = _diagnostic_field_name_pattern()
    return re.compile(
        rf"""
        (?<![A-Za-z0-9_-])
        (?P<name_quote>'?)
        (?P<name>{field_name_pattern})
        (?P=name_quote)
        (?P<separator>[ \t]*(?:=|:)[ \t]*)
        (?P<value>[^\r\n]*?)
        (?=
            (?:(?:[,;][ \t]*)|[ \t]+)'?{field_name_pattern}'?[ \t]*(?:=|:)[ \t]*
            |
            \r?\n?
            $
        )
        """,
        re.VERBOSE,
    )


@lru_cache(maxsize=1)
def _diagnostic_double_quoted_yaml_line_pattern() -> re.Pattern[str]:
    return re.compile(
        r"""
        ^
        (?P<indent>[ ]*)
        (?P<sequence_prefix>-[ \t]+)?
        (?P<node_properties>(?:(?:!(?:<[^>\r\n]+>|[^ \t\r\n]*)?|&[^ \t\r\n]+)[ \t]+)*)
        "
        (?P<name>(?:\\.|[^"\\])*)
        "
        (?P<separator>[ \t]*:[ \t]*)
        (?P<value>[^\r\n]*)
        (?P<newline>\r?\n?)
        $
        """,
        re.VERBOSE,
    )


@lru_cache(maxsize=1)
def _diagnostic_yaml_explicit_key_pattern() -> re.Pattern[str]:
    return re.compile(
        rf"""
        ^
        (?P<indent>[ ]*)
        (?P<sequence_prefix>-[ \t]+)?
        \?[ \t]+
        (?P<node_properties>(?:(?:!(?:<[^>\r\n]+>|[^ \t\r\n]*)?|&[^ \t\r\n]+)[ \t]+)*)
        (?P<name_token>
            "(?:\\.|[^"\\])*"
            |
            '(?:''|[^'])*'
            |
            [^\r\n#]+?
        )
        [ \t]*(?:\#.*)?
        \r?\n?
        $
        """,
        re.VERBOSE,
    )


_DIAGNOSTIC_ENV_ASSIGNMENT_PATTERN = re.compile(
    rf"""
    (?<![A-Za-z0-9_])
    (?P<prefix>(?:export[ \t]+)?)
    (?P<name>[A-Z][A-Z0-9_]*)
    (?P<separator>[ \t]*\+?=[ \t]*)
    {_DIAGNOSTIC_ASSIGNMENT_VALUE_PATTERN}
    """,
    re.VERBOSE,
)
_DIAGNOSTIC_ENV_ASSIGNMENT_PREFIX_PATTERN = re.compile(
    r"""
    (?<![A-Za-z0-9_])
    (?P<prefix>(?:export[ \t]+)?)
    (?P<name>[A-Z][A-Z0-9_]*)
    (?P<separator>[ \t]*\+?=[ \t]*)
    """,
    re.VERBOSE,
)
_AUTHORIZATION_FIELD_PATTERN = re.compile(
    r"""
    (?<![A-Za-z0-9_-])
    (?P<prefix>
        (?:
            (?P<quote>["'])
            (?:(?:proxy[-_ \t]?)?authorization)
            (?P=quote)
            |
            (?:proxy[-_ \t]?)?authorization
        )
        [ \t]*(?:=|:)[ \t]*
    )
    (?P<value>[^\r\n]*?)
    (?=
        [ \t]+["']?(?:proxy[-_ \t]?)?authorization["']?[ \t]*(?:=|:)
        |
        \r?\n
        |
        $
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_YAML_BLOCK_SCALAR_PATTERN = re.compile(r"^[|>][0-9+-]*$")
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
        "--ask-for-approval",
        "never",
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
        "--ask-for-approval",
        "never",
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


def _redact_assignment_value(match: re.Match[str]) -> str:
    """Replace one parsed assignment value while preserving its surrounding syntax."""

    original = match.group(0)
    value = match.group("value")
    replacement = "<redacted>"
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        replacement = f"{value[0]}<redacted>{value[0]}"
    value_start = match.start("value") - match.start()
    value_end = match.end("value") - match.start()
    return f"{original[:value_start]}{replacement}{original[value_end:]}"


def _is_field_specific_sensitive_redaction_target(name: str) -> bool:
    normalized_name = _normalize_diagnostic_field_name(name)
    return (
        _is_sensitive_structured_assignment_name(name)
        and normalized_name not in {"authorization", "proxy_authorization"}
    )


def _is_multiline_sensitive_redaction_target(name: str) -> bool:
    return _is_sensitive_structured_assignment_name(name)


def _normalize_diagnostic_field_name(name: str) -> str:
    normalized = re.sub(r"[- \t]+", "_", str(name or ""))
    normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", normalized)
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized)
    return normalized.lower()


def _decode_diagnostic_double_quoted_field_name(name: str) -> str:
    """Decode YAML/JSON double-quoted escapes before applying name matching."""

    if "\\" not in name:
        return name

    simple_escapes = {
        "0": "\0",
        "a": "\a",
        "b": "\b",
        "t": "\t",
        "\t": "\t",
        "n": "\n",
        "v": "\v",
        "f": "\f",
        "r": "\r",
        "e": "\x1b",
        " ": " ",
        '"': '"',
        "/": "/",
        "\\": "\\",
        "N": "\x85",
        "_": "\xa0",
        "L": "\u2028",
        "P": "\u2029",
    }
    decoded = []
    index = 0
    while index < len(name):
        char = name[index]
        if char != "\\":
            decoded.append(char)
            index += 1
            continue
        if index + 1 >= len(name):
            return name
        escape = name[index + 1]
        if escape in simple_escapes:
            decoded.append(simple_escapes[escape])
            index += 2
            continue
        if escape in {"x", "u", "U"}:
            widths = {"x": 2, "u": 4, "U": 8}
            width = widths[escape]
            digits = name[index + 2:index + 2 + width]
            if len(digits) != width or not re.fullmatch(r"[0-9A-Fa-f]+", digits):
                return name
            try:
                decoded.append(chr(int(digits, 16)))
            except ValueError:
                return name
            index += 2 + width
            continue
        if escape in {"\n", "\r"}:
            index += 2
            if escape == "\r" and index < len(name) and name[index] == "\n":
                index += 1
            while index < len(name) and name[index] in {" ", "\t"}:
                index += 1
            continue
        return name
    return "".join(decoded)


def _decode_diagnostic_yaml_field_name(name_token: str) -> str:
    """Decode a YAML key token to its logical field name."""

    token = str(name_token or "")
    if len(token) >= 2 and token[0] == token[-1] == '"':
        return _decode_diagnostic_double_quoted_field_name(token[1:-1])
    if len(token) >= 2 and token[0] == token[-1] == "'":
        return token[1:-1].replace("''", "'")
    return token.strip()


def _is_sensitive_diagnostic_field_name(name: str) -> bool:
    normalized = _normalize_diagnostic_field_name(name)
    return (
        normalized in _SENSITIVE_DIAGNOSTIC_FIELDS
        or any(normalized.endswith(suffix) for suffix in _SENSITIVE_DIAGNOSTIC_FIELD_SUFFIXES)
    )


@lru_cache(maxsize=1)
def _sensitive_exact_diagnostic_field_names() -> frozenset[str]:
    return _SENSITIVE_ENV_EXACT_NAMES | _registered_sensitive_env_exact_names()


@lru_cache(maxsize=1)
def _registered_sensitive_field_titles() -> frozenset[str]:
    try:
        from src.core.config_registry import _FIELD_DEFINITIONS
    except Exception:
        return frozenset()

    return frozenset(
        str(metadata.get("title"))
        for metadata in _FIELD_DEFINITIONS.values()
        if isinstance(metadata, Mapping)
        and metadata.get("is_sensitive")
        and isinstance(metadata.get("title"), str)
        and metadata.get("title")
    )


def _compact_diagnostic_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", str(name or "")).upper()


@lru_cache(maxsize=1)
def _compact_sensitive_exact_diagnostic_field_names() -> frozenset[str]:
    return frozenset(
        _compact_diagnostic_name(name)
        for name in _sensitive_exact_diagnostic_field_names()
    )


@lru_cache(maxsize=1)
def _sensitive_registered_diagnostic_field_titles() -> frozenset[str]:
    return frozenset(title.upper() for title in _registered_sensitive_field_titles())


@lru_cache(maxsize=1)
def _compact_sensitive_registered_diagnostic_field_titles() -> frozenset[str]:
    return frozenset(
        _compact_diagnostic_name(title) for title in _registered_sensitive_field_titles()
    )


def _is_sensitive_structured_assignment_name(name: str) -> bool:
    exact_name = _normalize_diagnostic_field_name(name).upper()
    upper_name = str(name or "").upper()
    compact_name = _compact_diagnostic_name(name)
    return (
        _is_sensitive_diagnostic_field_name(name)
        or exact_name in _sensitive_exact_diagnostic_field_names()
        or upper_name in _sensitive_registered_diagnostic_field_titles()
        or compact_name in _compact_sensitive_exact_diagnostic_field_names()
        or compact_name in _compact_sensitive_registered_diagnostic_field_titles()
    )


def _is_registered_sensitive_field_title(name: str) -> bool:
    return str(name or "").upper() in _sensitive_registered_diagnostic_field_titles()


def _leading_space_count(text: str) -> int:
    return len(text) - len(text.lstrip(" "))


def _yaml_value_without_node_properties(value: str) -> str:
    """Return a YAML value with leading tags and anchors removed."""

    remaining = value.strip()
    while remaining.startswith(("!", "&")):
        if remaining.startswith("&"):
            property_match = re.match(r"&[^ \t]+(?:[ \t]+|$)", remaining)
        else:
            property_match = re.match(r"!(?:<[^>]+>|[^ \t]*)?(?:[ \t]+|$)", remaining)
        if property_match is None:
            break
        remaining = remaining[property_match.end():].lstrip()
    return remaining


def _is_yaml_block_value(value: str) -> bool:
    """Return whether a YAML value introduces content on following lines."""

    stripped = _yaml_value_without_node_properties(value)
    if not stripped or stripped.startswith("#"):
        return True

    tokens = stripped.split()
    if not tokens or tokens[0].startswith("#"):
        return True
    if not _YAML_BLOCK_SCALAR_PATTERN.match(tokens[0]):
        return False
    return len(tokens) == 1 or tokens[1].startswith("#")


def _yaml_value_allows_indentless_sequence(value: str) -> bool:
    """Return whether a following same-indent sequence belongs to this value."""

    stripped = _yaml_value_without_node_properties(value)
    return not stripped or stripped.startswith("#")


def _replace_spans(text: str, replacements: Sequence[Tuple[int, int, str]]) -> str:
    updated = text
    for start, end, replacement in sorted(replacements, reverse=True):
        updated = f"{updated[:start]}{replacement}{updated[end:]}"
    return updated


def _consume_redacted_yaml_block_lines(
    lines: Sequence[str],
    *,
    start_index: int,
    base_indent: int,
    allows_indentless_sequence: bool,
) -> tuple[list[str], int]:
    kept_lines: list[str] = []
    index = start_index
    while index < len(lines):
        next_line = lines[index]
        stripped_next_line = next_line.strip()
        next_indent = _leading_space_count(next_line)
        if stripped_next_line and next_indent <= base_indent:
            is_same_indent_comment = (
                next_indent == base_indent and stripped_next_line.startswith("#")
            )
            is_indentless_sequence = (
                allows_indentless_sequence
                and next_indent == base_indent
                and (
                    stripped_next_line == "-"
                    or stripped_next_line.startswith("- ")
                )
            )
            if not is_same_indent_comment and not is_indentless_sequence:
                break
        if not stripped_next_line:
            kept_lines.append(next_line)
        index += 1
    return kept_lines, index


def _consume_redacted_multiline_quote_lines(
    lines: Sequence[str],
    *,
    start_index: int,
    multiline_quote: str,
) -> tuple[list[str], int]:
    kept_lines: list[str] = []
    index = start_index
    while index < len(lines):
        next_line = lines[index]
        close_index = _diagnostic_quote_close_index(next_line, multiline_quote, start=0)
        if close_index is None:
            index += 1
            continue
        trailing = next_line[close_index:]
        if trailing.strip():
            kept_lines.append(trailing)
        index += 1
        break
    return kept_lines, index


def _is_inside_diagnostic_flow_collection(text: str) -> bool:
    closing_by_opening = {"{": "}", "[": "]"}
    stack: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in {"'", '"'}:
            index = _consume_diagnostic_scalar(text, index)
            continue
        if char in closing_by_opening:
            stack.append(closing_by_opening[char])
            index += 1
            continue
        if stack and char == stack[-1]:
            stack.pop()
        index += 1
    return bool(stack)


def _redact_double_quoted_yaml_sensitive_field(
    lines: Sequence[str],
    index: int,
) -> Optional[tuple[list[str], int]]:
    line = lines[index]
    match = _diagnostic_double_quoted_yaml_line_pattern().match(line)
    if match is None:
        return None

    decoded_name = _decode_diagnostic_double_quoted_field_name(match.group("name"))
    if not _is_multiline_sensitive_redaction_target(decoded_name):
        return None
    if _is_inside_diagnostic_flow_collection("".join(lines[:index])):
        return None

    value = match.group("value")
    normalized_name = _normalize_diagnostic_field_name(decoded_name)
    if (
        normalized_name in {"authorization", "proxy_authorization"}
        and value.lstrip(" \t").startswith("<redacted>")
    ):
        return None
    stripped_value = value.strip()
    yaml_scalar_value = _yaml_value_without_node_properties(value)
    base_indent = _leading_space_count(line)
    value_span = (match.start("value"), match.end("value"))

    if _is_yaml_block_value(value):
        replacement = "<redacted>"
        if not match.group("separator")[-1:].isspace():
            replacement = f" {replacement}"
        kept_lines, next_index = _consume_redacted_yaml_block_lines(
            lines,
            start_index=index + 1,
            base_indent=base_indent,
            allows_indentless_sequence=_yaml_value_allows_indentless_sequence(value),
        )
        return (
            [_replace_spans(line, [(value_span[0], value_span[1], replacement)]), *kept_lines],
            next_index,
        )

    yaml_quote = yaml_scalar_value[:1]
    yaml_quote_is_closed = bool(
        yaml_quote and _has_closed_diagnostic_quote(yaml_scalar_value, yaml_quote)
    )
    if yaml_quote in {"'", '"'} and (
        yaml_scalar_value != stripped_value or not yaml_quote_is_closed
    ):
        kept_lines = [_replace_spans(line, [(value_span[0], value_span[1], "<redacted>")])]
        next_index = index + 1
        if not yaml_quote_is_closed:
            trailing_lines, next_index = _consume_redacted_multiline_quote_lines(
                lines,
                start_index=next_index,
                multiline_quote=yaml_quote,
            )
            kept_lines.extend(trailing_lines)
        return kept_lines, next_index

    if stripped_value and stripped_value[0] not in {"'", '"', "{", "["}:
        redacted_line = _replace_spans(line, [(value_span[0], value_span[1], "<redacted>")])
        kept_lines = [redacted_line]
        continuation_index = index + 1
        while continuation_index < len(lines):
            next_line = lines[continuation_index]
            if not next_line.strip():
                kept_lines.append(next_line)
                continuation_index += 1
                continue
            if _leading_space_count(next_line) <= base_indent:
                break
            continuation_index += 1
        return kept_lines, continuation_index

    return None


def _redact_sensitive_collection_assignments(text: str) -> str:
    def replace_matches(
        source: str,
        pattern: re.Pattern[str],
        is_sensitive_name: Callable[[str], bool],
    ) -> str:
        replacements = []
        last_end = -1
        for match in pattern.finditer(source):
            name = match.group("name")
            value = match.group("value")
            if not is_sensitive_name(name) or not value or value[0] not in "{[":
                continue
            value_start = match.start("value")
            if value_start < last_end:
                continue
            value_end = _consume_diagnostic_collection(source, value_start)
            replacements.append((value_start, value_end, "<redacted>"))
            last_end = value_end
        return _replace_spans(source, replacements)

    redacted = replace_matches(text, _DIAGNOSTIC_ENV_ASSIGNMENT_PATTERN, _is_sensitive_env_name)
    redacted = replace_matches(
        redacted,
        _diagnostic_json_assignment_pattern(),
        lambda name: _is_sensitive_structured_assignment_name(
            _decode_diagnostic_double_quoted_field_name(name)
        ),
    )
    return replace_matches(
        redacted,
        _diagnostic_field_assignment_pattern(),
        _is_field_specific_sensitive_redaction_target,
    )


def _redact_multiline_sensitive_fields(text: str) -> str:
    """Redact YAML/log scalar fields that span spaces or indented block lines."""

    lines = text.splitlines(keepends=True)
    if not lines:
        return text

    redacted_lines = []
    index = 0
    while index < len(lines):
        line = lines[index]
        quoted_yaml_redaction = _redact_double_quoted_yaml_sensitive_field(lines, index)
        if quoted_yaml_redaction is not None:
            kept_lines, index = quoted_yaml_redaction
            redacted_lines.extend(kept_lines)
            continue

        matches = list(_diagnostic_line_field_pattern().finditer(line))
        if not matches:
            redacted_lines.append(line)
            index += 1
            continue

        replacements = []
        block_match: Optional[re.Match[str]] = None
        block_allows_indentless_sequence = False
        multiline_quote: Optional[str] = None
        for match in matches:
            name = match.group("name")
            value = match.group("value")
            normalized_name = _normalize_diagnostic_field_name(name)
            is_redacted_authorization = (
                normalized_name in {"authorization", "proxy_authorization"}
                and value.strip() == "<redacted>"
            )
            is_authorization_yaml_block = (
                normalized_name in {"authorization", "proxy_authorization"}
                and ":" in match.group("separator")
                and _is_yaml_block_value(value)
            )
            if (
                not _is_field_specific_sensitive_redaction_target(name)
                and not is_redacted_authorization
                and not is_authorization_yaml_block
            ):
                continue

            stripped_value = value.strip()
            yaml_scalar_value = _yaml_value_without_node_properties(value)
            if ":" in match.group("separator") and _is_yaml_block_value(value):
                replacement = "<redacted>"
                if not match.group("separator")[-1:].isspace():
                    replacement = f" {replacement}"
                replacements.append((match.start("value"), match.end("value"), replacement))
                block_match = block_match or match
                block_allows_indentless_sequence = (
                    block_allows_indentless_sequence
                    or _yaml_value_allows_indentless_sequence(value)
                )
                continue

            yaml_quote = yaml_scalar_value[:1]
            yaml_quote_is_closed = bool(
                yaml_quote
                and _has_closed_diagnostic_quote(yaml_scalar_value, yaml_quote)
            )
            if yaml_quote in {"'", '"'} and (
                yaml_scalar_value != stripped_value or not yaml_quote_is_closed
            ):
                replacements.append((match.start("value"), match.end("value"), "<redacted>"))
                if not yaml_quote_is_closed:
                    multiline_quote = multiline_quote or yaml_quote
                continue

            if stripped_value and stripped_value[0] not in {"'", '"', "{", "["}:
                value_end = match.end("value")
                if (
                    ":" in match.group("separator")
                    and stripped_value != "<redacted>"
                    and not _is_registered_sensitive_field_title(name)
                ):
                    flow_value_end = _find_diagnostic_flow_scalar_end(line, match.start("value"))
                    if flow_value_end is not None:
                        value_end = flow_value_end
                    else:
                        # Outside YAML flow collections, an unquoted scalar has
                        # no reliable same-line boundary. Fail closed instead
                        # of treating assignment-like text inside the
                        # credential as a separate diagnostic field.
                        value_end = len(line.rstrip("\r\n"))
                replacements.append((match.start("value"), value_end, "<redacted>"))
                if ":" in match.group("separator") and value_end == len(line.rstrip("\r\n")):
                    block_match = block_match or match
                if value_end == len(line.rstrip("\r\n")):
                    break

        if not replacements:
            redacted_lines.append(line)
            index += 1
            continue

        redacted_lines.append(_replace_spans(line, replacements))
        index += 1

        if block_match is not None:
            base_indent = _leading_space_count(line)
            kept_lines, index = _consume_redacted_yaml_block_lines(
                lines,
                start_index=index,
                base_indent=base_indent,
                allows_indentless_sequence=block_allows_indentless_sequence,
            )
            redacted_lines.extend(kept_lines)
            continue

        if multiline_quote is None:
            continue

        kept_lines, index = _consume_redacted_multiline_quote_lines(
            lines,
            start_index=index,
            multiline_quote=multiline_quote,
        )
        redacted_lines.extend(kept_lines)

    return "".join(redacted_lines)


def _redact_yaml_explicit_sensitive_fields(text: str) -> str:
    """Redact YAML ``? key`` / ``: value`` entries and their continuations."""

    lines = text.splitlines(keepends=True)
    redacted_lines = []
    index = 0
    while index < len(lines):
        key_line = lines[index]
        key_match = _diagnostic_yaml_explicit_key_pattern().match(key_line)
        key_name = (
            _decode_diagnostic_yaml_field_name(key_match.group("name_token"))
            if key_match is not None
            else ""
        )
        if (
            key_match is None
            or not _is_multiline_sensitive_redaction_target(key_name)
        ):
            redacted_lines.append(key_line)
            index += 1
            continue

        base_indent = len(key_match.group("indent")) + len(key_match.group("sequence_prefix") or "")
        value_index = index + 1
        while value_index < len(lines):
            candidate_line = lines[value_index]
            candidate_stripped = candidate_line.strip()
            if not candidate_stripped:
                value_index += 1
                continue
            if candidate_line[_leading_space_count(candidate_line):].startswith("#"):
                value_index += 1
                continue
            break
        if value_index >= len(lines):
            redacted_lines.append(key_line)
            index += 1
            continue

        value_line = lines[value_index]
        value_indent = _leading_space_count(value_line)
        value_content = value_line[value_indent:].rstrip("\r\n")
        if (
            value_indent != base_indent
            or not value_content.startswith(":")
            or (
                len(value_content) > 1
                and value_content[1] not in {" ", "\t"}
            )
        ):
            redacted_lines.append(key_line)
            index += 1
            continue

        newline = (
            "\r\n"
            if value_line.endswith("\r\n")
            else "\n"
            if value_line.endswith("\n")
            else ""
        )
        value = value_content[1:].lstrip(" \t")
        redacted_lines.append(key_line)
        for skipped_line in lines[index + 1:value_index]:
            if not skipped_line.strip():
                redacted_lines.append(skipped_line)
        redacted_lines.append(f"{' ' * value_indent}: <redacted>{newline}")
        index = value_index + 1
        allows_indentless_sequence = _yaml_value_allows_indentless_sequence(value)

        while index < len(lines):
            next_line = lines[index]
            stripped_next_line = next_line.strip()
            next_indent = _leading_space_count(next_line)
            if stripped_next_line and next_indent <= base_indent:
                is_same_indent_comment = (
                    next_indent == base_indent and stripped_next_line.startswith("#")
                )
                is_indentless_sequence = (
                    allows_indentless_sequence
                    and next_indent == base_indent
                    and (
                        stripped_next_line == "-"
                        or stripped_next_line.startswith("- ")
                    )
                )
                if not is_same_indent_comment and not is_indentless_sequence:
                    break
            if not stripped_next_line:
                redacted_lines.append(next_line)
            index += 1

    return "".join(redacted_lines)


def _redact_sensitive_diagnostic_assignments(text: str) -> str:
    """Redact parsed env and structured-field assignments under separate contracts."""

    def redact_env(match: re.Match[str]) -> str:
        name = match.group("name")
        return _redact_assignment_value(match) if _is_sensitive_env_name(name) else match.group(0)

    def redact_structured_field(match: re.Match[str]) -> str:
        return (
            _redact_assignment_value(match)
            if _is_field_specific_sensitive_redaction_target(match.group("name"))
            else match.group(0)
        )

    def redact_sensitive_env_command_substitutions(source: str) -> str:
        replacements = []
        last_end = -1
        # Collect all sensitive-env-assignment spans from the first pass
        # so the second pass can skip any ``$(...)`` that sits inside one
        # of those already-redacted regions. Without this overlap guard
        # the second pass re-adds the same span and ``_replace_spans``
        # silently drops trailing diagnostics such as ``session_id``
        # (regression OR-COR-7c0a5d41).
        first_pass_spans: list[tuple[int, int]] = []
        for match in _DIAGNOSTIC_ENV_ASSIGNMENT_PREFIX_PATTERN.finditer(source):
            value_start = match.end()
            if value_start < last_end or source[value_start:value_start + 2] != "$(":
                continue
            if not _is_sensitive_env_name(match.group("name")):
                continue
            value_end = _consume_shell_command_substitution(source, value_start)
            if value_end <= value_start:
                continue
            replacements.append((value_start, value_end, "<redacted>"))
            first_pass_spans.append((value_start, value_end))
            last_end = value_end
        # Scan remaining $(...) command substitutions not bound to any env
        # assignment, so multi-segment diagnostics like
        # A=$(echo X);B=ok; tail $(printenv SECRET_TOKEN)
        # redact every sensitive reference regardless of how it is invoked.
        tail_start = 0
        while True:
            sub = source.find("$(", tail_start)
            if sub == -1:
                break
            if sub > 0 and source[sub - 1] == "$":
                tail_start = sub + 1
                continue
            # Skip $( that is the direct value of a sensitive env assignment
            # already handled above, so we don't double-rewrite it. A leading
            # non-sensitive token like A=$(echo SECRET) must still be scanned
            # because the inner token triggers the redaction. We use the
            # collected spans rather than re-deriving the leading prefix
            # so that the ``export SENSITIVE=$(...)`` shape is recognised
            # the same way as ``SENSITIVE=$(...)`` (both share the same
            # leading match in ``_DIAGNOSTIC_ENV_ASSIGNMENT_PREFIX_PATTERN``
            # which already accepts an optional ``export`` prefix).
            skip_due_to_first_pass = any(
                start <= sub < end for start, end in first_pass_spans
            )
            if skip_due_to_first_pass:
                tail_start = sub + 1
                continue
            prior_semi = source.rfind(";", 0, sub)
            if prior_semi == -1:
                prior_nl = source.rfind("\n", 0, sub)
            else:
                prior_nl = -1
            skip_due_to_prior = False
            if prior_semi != -1:
                candidate = source[prior_semi + 1:sub].strip(" \t")
                if candidate:
                    prior_match = re.match(
                        r"(?:export[ \t]+)?(?P<name>[A-Z][A-Z0-9_]*)\s*=\s*$",
                        candidate,
                    )
                    if prior_match and _is_sensitive_env_name(prior_match.group("name")):
                        skip_due_to_prior = True
            if not skip_due_to_prior and prior_nl != -1:
                candidate = source[prior_nl + 1:sub].strip(" \t")
                if candidate:
                    prior_match = re.match(
                        r"(?:export[ \t]+)?(?P<name>[A-Z][A-Z0-9_]*)\s*=\s*$",
                        candidate,
                    )
                    if prior_match and _is_sensitive_env_name(prior_match.group("name")):
                        skip_due_to_prior = True
            if not skip_due_to_prior and prior_semi == -1 and prior_nl == -1:
                head = source[:sub].lstrip(" \t")
                if head:
                    prior_match = re.match(
                        r"(?:export[ \t]+)?(?P<name>[A-Z][A-Z0-9_]*)\s*=\s*$",
                        head,
                    )
                    if prior_match and _is_sensitive_env_name(prior_match.group("name")):
                        skip_due_to_prior = True
            if skip_due_to_prior:
                tail_start = sub + 1
                continue
            value_end = _consume_shell_command_substitution(source, sub)
            if value_end <= sub:
                tail_start = sub + 1
                continue
            snippet = source[sub + 2:value_end - 1] if value_end > sub + 2 else source[sub + 2:]
            # Scan every uppercase token inside the command substitution so
            # that printenv SECRET_TOKEN, echo API_KEY=..., ${TOKEN:+x}, and
            # similar forms each trigger redaction even when the leading word
            # is a generic command name like "echo" or "printenv".
            sensitive_hit = any(
                _is_sensitive_env_name(token)
                for token in re.findall(r"[A-Z][A-Z0-9_]*", snippet)
            )
            if sensitive_hit:
                replacements.append((sub, value_end, "<redacted>"))
                last_end = value_end
                tail_start = value_end
            else:
                tail_start = sub + 1
        return _replace_spans(source, replacements)

    redacted = _redact_yaml_explicit_sensitive_fields(text)
    redacted = redact_sensitive_env_command_substitutions(redacted)
    redacted = _DIAGNOSTIC_ENV_ASSIGNMENT_PATTERN.sub(redact_env, redacted)
    redacted = _redact_sensitive_collection_assignments(redacted)
    redacted = _redact_multiline_sensitive_fields(redacted)
    redacted = _diagnostic_json_assignment_pattern().sub(
        lambda match: (
            _redact_assignment_value(match)
            if _is_sensitive_structured_assignment_name(
                _decode_diagnostic_double_quoted_field_name(match.group("name"))
            )
            else match.group(0)
        ),
        redacted,
    )
    redacted = _diagnostic_field_assignment_pattern().sub(redact_structured_field, redacted)
    return _redact_partially_redacted_flow_scalars(redacted)


def _redact_partially_redacted_flow_scalars(text: str) -> str:
    """Collapse any flow-style sensitive scalar tail left after token-level redaction."""

    field_name_pattern = _diagnostic_field_name_pattern()
    pattern = re.compile(
        r"""
        (?P<prefix>
            "
            (?P<json_name>(?:\\.|[^"\\])*)
            "
            (?P<json_separator>[ \t\r\n]*:[ \t\r\n]*)
            |
            (?<![A-Za-z0-9_-])
            (?P<field_name_quote>')
            (?P<field_name>"""
        + field_name_pattern
        + r""")
            (?P=field_name_quote)
            (?P<field_separator>[ \t]*(?:=|:)[ \t]*)
        )
        <redacted>
        (?P<tail>[ \t]+[^\r\n,}\]]+?)
        (?=[ \t]*[,}\]]|\r?\n?$)
        """,
        re.VERBOSE,
    )

    def replace(match: re.Match[str]) -> str:
        json_name = match.group("json_name")
        normalized_name: Optional[str]
        if json_name is not None:
            normalized_name = _normalize_diagnostic_field_name(
                _decode_diagnostic_double_quoted_field_name(json_name)
            )
            sensitive = _is_sensitive_structured_assignment_name(normalized_name)
        else:
            normalized_name = _normalize_diagnostic_field_name(match.group("field_name"))
            sensitive = _is_field_specific_sensitive_redaction_target(match.group("field_name"))
        if not sensitive:
            return match.group(0)
        if normalized_name in {"authorization", "proxy_authorization"}:
            trailing_field = match.group("tail").lstrip(" \t")
            if _diagnostic_field_assignment_pattern().match(trailing_field):
                return match.group(0)
        return f"{match.group('prefix')}<redacted>"

    return pattern.sub(replace, text)


def _has_closed_diagnostic_quote(value: str, quote: str) -> bool:
    return _diagnostic_quote_close_index(value, quote, start=1) is not None


def _diagnostic_quote_close_index(value: str, quote: str, *, start: int) -> Optional[int]:
    index = start
    while index < len(value):
        char = value[index]
        if quote == "'" and char == "'" and index + 1 < len(value) and value[index + 1] == "'":
            index += 2
            continue
        if char == "\\" and index + 1 < len(value):
            index += 2
            continue
        if char == quote:
            return index + 1
        index += 1
    return None


def _consume_diagnostic_scalar(
    value: str,
    start: int,
    *,
    stop_chars: str = " \t,;",
) -> int:
    if start >= len(value):
        return start
    quote = value[start]
    if quote in {"'", '"'}:
        index = start + 1
        while index < len(value):
            char = value[index]
            if quote == "'" and char == "'" and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            if char == "\\" and index + 1 < len(value):
                index += 2
                continue
            if char == quote:
                return index + 1
            index += 1
        return len(value)

    index = start
    while index < len(value) and value[index] not in stop_chars:
        index += 1
    return index


def _consume_diagnostic_collection(value: str, start: int) -> int:
    if start >= len(value) or value[start] not in "{[":
        return start

    closing_by_opening = {"{": "}", "[": "]"}
    stack = [closing_by_opening[value[start]]]
    index = start + 1
    while index < len(value):
        char = value[index]
        if char in {"'", '"'}:
            index = _consume_diagnostic_scalar(value, index)
            continue
        if char in closing_by_opening:
            stack.append(closing_by_opening[char])
            index += 1
            continue
        if stack and char == stack[-1]:
            stack.pop()
            index += 1
            if not stack:
                return index
            continue
        index += 1
    return len(value)


def _consume_shell_command_substitution(value: str, start: int) -> int:
    if start + 1 >= len(value) or value[start:start + 2] != "$(":
        return start

    depth = 1
    index = start + 2
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            index += 2
            continue
        if char in {"'", '"'}:
            index = _consume_diagnostic_scalar(value, index)
            continue
        if value.startswith("$(", index):
            depth += 1
            index += 2
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth -= 1
            index += 1
            if depth == 0:
                return index
            continue
        index += 1
    return len(value)


def _find_diagnostic_flow_scalar_end(value: str, start: int) -> Optional[int]:
    """Return the end of an unquoted YAML flow scalar when delimiters are reliable."""

    closing_by_opening = {"{": "}", "[": "]"}
    stack: list[str] = []
    index = 0
    while index < start:
        char = value[index]
        if char in {"'", '"'}:
            index = _consume_diagnostic_scalar(value, index)
            continue
        if char in closing_by_opening:
            stack.append(closing_by_opening[char])
            index += 1
            continue
        if stack and char == stack[-1]:
            stack.pop()
        index += 1

    if not stack:
        return None

    index = start
    while index < len(value):
        char = value[index]
        if char in {"'", '"'}:
            index = _consume_diagnostic_scalar(value, index)
            continue
        if char in closing_by_opening:
            stack.append(closing_by_opening[char])
            index += 1
            continue
        if len(stack) == 1 and char in {",", stack[-1]}:
            return index
        if stack and char == stack[-1]:
            stack.pop()
            index += 1
            continue
        index += 1

    return None


def _authorization_value_end(value: str) -> int:
    scheme_match = re.match(r"[A-Za-z][A-Za-z0-9_-]*", value)
    if scheme_match is None:
        return len(value)

    index = scheme_match.end()
    while index < len(value) and value[index].isspace():
        index += 1

    auth_end = _consume_authorization_param_list(value, index)
    if auth_end > index:
        return auth_end

    simple_value_end = _consume_diagnostic_scalar(value, index)
    return simple_value_end if simple_value_end > index else len(value)


def _consume_authorization_param_list(
    value: str,
    start: int,
    *,
    allowed_names: Optional[frozenset[str]] = None,
) -> int:
    index = start
    auth_end = start
    consumed_any = False
    first_param = True
    while index < len(value):
        while index < len(value) and value[index].isspace():
            index += 1
        if not first_param:
            if index >= len(value) or value[index] != ",":
                break
            index += 1
            while index < len(value) and value[index].isspace():
                index += 1
        name_match = re.match(r"[A-Za-z][A-Za-z0-9_-]*", value[index:])
        if name_match is None:
            break
        name = _normalize_diagnostic_field_name(name_match.group(0))
        if allowed_names is not None and name not in allowed_names:
            break
        index += name_match.end()
        while index < len(value) and value[index].isspace():
            index += 1
        if index >= len(value) or value[index] != "=":
            break
        index += 1
        saw_whitespace_after_equals = False
        while index < len(value) and value[index].isspace():
            saw_whitespace_after_equals = True
            index += 1
        if saw_whitespace_after_equals and re.match(r"[A-Za-z][A-Za-z0-9_-]*\s*=", value[index:]):
            break
        scalar_end = _consume_diagnostic_scalar(value, index, stop_chars=" \t,")
        if scalar_end <= index:
            break
        consumed_any = True
        auth_end = scalar_end
        index = scalar_end
        first_param = False

    return auth_end if consumed_any else start


def _redact_authorization_fields(text: str) -> str:
    def redact(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        value = match.group("value") or ""
        if match.group("quote") is not None and value.lstrip(" \t")[:1] in {'"', "'", "{", "["}:
            return match.group(0)
        if not value.strip():
            return f"{prefix}<redacted>"
        auth_end = _authorization_value_end(value)
        if auth_end <= 0:
            return f"{prefix}<redacted>"
        return f"{prefix}<redacted>{value[auth_end:]}"

    return _AUTHORIZATION_FIELD_PATTERN.sub(redact, text)


def redact_diagnostic_text(text: str, *, home: Optional[str] = None, limit: int = _PREVIEW_LIMIT) -> str:
    """Redact sensitive diagnostics and return a bounded preview.

    Uppercase environment assignments intentionally reuse the fail-closed child
    environment contract. Scalar YAML/JSON/log fields use a narrower allowlist
    so ordinary fields such as ``token_budget`` and ``session_id`` remain useful
    for troubleshooting.
    """

    redacted = _ANSI_ESCAPE_PATTERN.sub("", text or "")
    home_path = home or os.path.expanduser("~")
    if home_path:
        redacted = redacted.replace(home_path, "~")
    redacted = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@", r"\1<redacted>@", redacted)
    redacted = _URL_PATTERN.sub(_redact_sensitive_diagnostic_url, redacted)
    redacted = _redact_authorization_fields(redacted)
    redacted = re.sub(r"(?i)(cookie[ \t]*[:=][ \t]*)[^\n\r]+", r"\1<redacted>", redacted)
    redacted = _redact_sensitive_diagnostic_assignments(redacted)
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


@lru_cache(maxsize=1)
def _registered_sensitive_env_exact_names() -> frozenset[str]:
    """Reuse the config registry's secret-field contract without creating an import cycle."""

    try:
        from src.core.config_registry import _FIELD_DEFINITIONS
    except Exception:
        return frozenset()

    return frozenset(
        str(name).upper()
        for name, metadata in _FIELD_DEFINITIONS.items()
        if isinstance(metadata, Mapping) and metadata.get("is_sensitive")
    )


def _is_sensitive_env_name(upper_name: str) -> bool:
    return (
        upper_name in _SENSITIVE_ENV_EXACT_NAMES
        or upper_name in _registered_sensitive_env_exact_names()
    ) or any(
        pattern in upper_name for pattern in _SENSITIVE_ENV_PATTERNS
    )


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
