# -*- coding: utf-8 -*-
"""Protocol-neutral shims, exception hierarchy, secret redaction, and HTTP error classification.

Issue #2622 Phase 2: pure data types and error classifiers shared across the
native 4-protocol HTTPX + SSE engine (OpenAI Chat, OpenAI Responses, Anthropic
Messages, and Google Gemini REST). Contains no routing heuristics, default base
URLs, or network execution logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import parse_qsl, unquote_plus, urlsplit

import httpx

_BEARER_TOKEN_RE = re.compile(r"(Bearer\s+)[^\s\"',;<>]+", re.IGNORECASE)
_SK_TOKEN_RE = re.compile(r"\b(?:sk-ant-|sk-)[A-Za-z0-9_-]{6,}")
_GOOGLE_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_-]{20,}")
_QUERY_SECRET_RE = re.compile(r"([?&](?:api_?key|key|token|secret)=)[^&\s\"'<>]+", re.IGNORECASE)
_HEADER_SECRET_RE = re.compile(
    r"((?:x-api-key|x-goog-api-key|authorization|api-key)\s*[:=]\s*)(?:Bearer\s+)?[^\s\"',;<>]+",
    re.IGNORECASE,
)

_DATA_URL_RE = re.compile(
    r"^data:([^;,\s]+)(?:;[^,]*)?;base64,(.+)$",
    re.IGNORECASE | re.DOTALL,
)

_CONTEXT_WINDOW_MARKERS = (
    "context_length_exceeded",
    "maximum context length",
    "context window",
    "too many tokens",
    "max tokens exceeded",
    "reduce the length of the messages",
    "prompt is too long",
    "exceed context limit",
    "exceeds the maximum number of tokens",
    "input is too long",
    "token count exceeds",
)

_HTML_MARKERS = (
    "<!doctype html",
    "<html",
    "<head>",
    "<body",
    "<title>just a moment",
    "cf-browser-verification",
)

_WAF_MARKERS = (
    "just a moment",
    "attention required",
    "cloudflare",
    "cf-browser-verification",
    "access denied |",
    "error 1020",
    "enable javascript and cookies",
    "checking your browser",
    "ddos-guard",
    "web application firewall",
)

_MODEL_ACCESS_DENIED_MARKERS = (
    "model disabled",
    "model is disabled",
    "disabled model",
    "model has been disabled",
    "model not enabled",
    "model not available",
    "model is not available",
    "not authorized",
    "access denied",
    "permission denied",
    "not allowed",
)

MAX_HTML_ERROR_BODY_CHARS = 512

PreparedRequest = Tuple[str, Dict[str, str], Dict[str, Any], Any]


# ============================================================
# Shared Deployment & Resolution Contracts
# ============================================================


@dataclass(frozen=True)
class DeploymentSpec:
    """Normalized single-deployment contract shared across transport engines.

    This immutable contract preserves PR 1's normalization fields and carries
    resolved Phase 2 native execution attributes (``protocol``, ``provider``,
    ``endpoint_url``, ``auth_header_name``, ``allow_keyless``).
    """

    alias: str
    wire_model: str
    channel_protocol: str = ""
    wire_protocol: str = ""
    custom_llm_provider: str = ""
    api_surface: str = ""
    api_base: str = ""
    api_key: str = field(default="", repr=False)
    extra_headers: Dict[str, str] = field(default_factory=dict, repr=False)
    extra_body: Dict[str, Any] = field(default_factory=dict)
    request_defaults: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    timeout: Optional[float] = None
    model_info: Dict[str, Any] = field(default_factory=dict)
    deployment_id: str = ""
    protocol: str = ""
    provider: str = ""
    endpoint_url: str = ""
    auth_header_name: str = ""
    allow_keyless: bool = False


@dataclass(frozen=True)
class Unsupported:
    """Typed non-native resolution outcome for fail-closed ``native`` or hybrid ``auto``."""

    reason: str
    provider: str
    detail: str
    model: str = ""


# ============================================================
# Secret Redaction & Body Truncation
# ============================================================


_SENSITIVE_HEADER_NAME_TOKENS = (
    "auth",
    "key",
    "token",
    "secret",
    "cookie",
    "pass",
    "cred",
    "jwt",
    "session",
)

_SENSITIVE_QUERY_PARAM_NAMES = frozenset(
    {
        "key",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "auth",
        "secret",
        "password",
        "sig",
        "signature",
        "x-goog-api-key",
    }
)


_CROSS_ORIGIN_SAFE_HEADERS: frozenset[str] = frozenset(
    {
        "content-type",
        "accept",
        "user-agent",
        "x-request-id",
        "x-correlation-id",
        "traceparent",
        "tracestate",
    }
)


def is_sensitive_header_name(name: str) -> bool:
    """Return True when ``name`` looks like a credential/auth/private session header."""
    lower_name = str(name or "").strip().lower()
    if not lower_name:
        return False
    return any(tok in lower_name for tok in _SENSITIVE_HEADER_NAME_TOKENS)


def is_cross_origin_safe_header(name: str) -> bool:
    """Return True ONLY for explicitly allowlisted telemetry/content headers safe across origins (P0-2)."""
    return str(name or "").strip().lower() in _CROSS_ORIGIN_SAFE_HEADERS


def collect_secret_values(
    *values: Any,
    headers: Optional[Mapping[str, Any]] = None,
    url: Optional[str] = None,
) -> List[str]:
    """Collect non-empty credential strings for redaction from keys, auth headers, and URL query params."""
    collected: List[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        if raw is None:
            return
        text = str(raw).strip()
        if not text:
            return
        for candidate in (text, *(seg.strip() for seg in text.split(","))):
            if len(candidate) >= 4 and candidate not in seen:
                seen.add(candidate)
                collected.append(candidate)
            if candidate.lower().startswith("bearer "):
                token = candidate[7:].strip()
                if len(token) >= 4 and token not in seen:
                    seen.add(token)
                    collected.append(token)

    for value in values:
        _add(value)

    if isinstance(headers, Mapping):
        for header_name, header_val in headers.items():
            if is_sensitive_header_name(str(header_name or "")):
                _add(header_val)

    if url:
        try:
            raw_query = urlsplit(str(url)).query
        except ValueError:
            raw_query = ""
        if raw_query:
            for qk, qv in parse_qsl(raw_query, keep_blank_values=True):
                qk_l = str(qk or "").strip().lower()
                if qk_l in _SENSITIVE_QUERY_PARAM_NAMES or any(
                    tok in qk_l for tok in ("key", "token", "secret", "auth", "pass")
                ):
                    _add(qv)
            # P1-7c: Decode percent-encoded key names too so raw & decoded secret values are both collected.
            for part in raw_query.split("&"):
                if "=" not in part:
                    continue
                raw_k, raw_v = part.split("=", 1)
                rk_l = unquote_plus(raw_k).strip().lower()
                if rk_l in _SENSITIVE_QUERY_PARAM_NAMES or any(
                    tok in rk_l for tok in ("key", "token", "secret", "auth", "pass")
                ):
                    _add(raw_v)
                    _add(unquote_plus(raw_v))

    return sorted(collected, key=len, reverse=True)


def looks_like_html(
    text: str,
    content_type: Optional[str] = None,
    *,
    ignore_content_type: bool = False,
) -> bool:
    """Return True when ``content_type`` declares HTML or non-JSON ``text`` starts with HTML markup."""
    if not ignore_content_type:
        ct = str(content_type or "").lower()
        if "text/html" in ct or "application/xhtml" in ct:
            return True
        if "application/json" in ct or "text/json" in ct or "+json" in ct:
            return False
    sample = str(text or "").lstrip("\ufeff").lstrip()[:512].lower()
    if not sample:
        return False
    if sample.startswith(("{", "[")):
        return False
    if sample.startswith(("<!doctype html", "<html", "<head", "<body", "<title")):
        return True
    if sample.startswith("<!--") and ("<html" in sample or "<!doctype html" in sample):
        return True
    return False


def truncate_html_body(text: str, *, max_len: int = MAX_HTML_ERROR_BODY_CHARS) -> str:
    """Truncate raw HTML error payloads cleanly to at most ``max_len`` characters."""
    if len(text) <= max_len:
        return text
    suffix = "... [truncated]"
    keep = max(0, max_len - len(suffix))
    return text[:keep] + suffix


def sanitize_error_message(text: Any, secrets: Iterable[str] = ()) -> str:
    """Redact API keys, auth headers, query secrets, and explicit secret values."""
    raw = str(text or "")
    if not raw:
        return ""
    explicit: List[str] = []
    for secret in secrets:
        s = str(secret or "").strip()
        if len(s) >= 4:
            explicit.append(s)
            if s.lower().startswith("bearer "):
                bare = s[7:].strip()
                if len(bare) >= 4:
                    explicit.append(bare)
        for seg in s.split(","):
            seg_clean = seg.strip()
            if len(seg_clean) >= 4:
                explicit.append(seg_clean)

    for secret in sorted(set(explicit), key=len, reverse=True):
        raw = raw.replace(secret, "***")

    raw = _BEARER_TOKEN_RE.sub(r"\1***", raw)
    raw = _SK_TOKEN_RE.sub("sk-***", raw)
    raw = _GOOGLE_KEY_RE.sub("AIza***", raw)
    raw = _QUERY_SECRET_RE.sub(r"\1***", raw)
    raw = _HEADER_SECRET_RE.sub(r"\1***", raw)
    return raw


def sanitize_error_body(
    body: Any,
    secrets: Iterable[str] = (),
    *,
    max_html_len: int = MAX_HTML_ERROR_BODY_CHARS,
    content_type: Optional[str] = None,
) -> Any:
    """Recursively redact secrets from ``exc.body`` and cap HTML payloads."""
    if body is None:
        return None
    if isinstance(body, str):
        redacted = sanitize_error_message(body, secrets)
        if looks_like_html(redacted, content_type=content_type):
            return truncate_html_body(redacted, max_len=max_html_len)
        return redacted
    if isinstance(body, Mapping):
        return {
            sanitize_error_message(k, secrets): sanitize_error_body(
                v,
                secrets,
                max_html_len=max_html_len,
            )
            for k, v in body.items()
        }
    if isinstance(body, list):
        return [
            sanitize_error_body(item, secrets, max_html_len=max_html_len)
            for item in body
        ]
    if isinstance(body, tuple):
        return tuple(
            sanitize_error_body(item, secrets, max_html_len=max_html_len)
            for item in body
        )
    return body


# ============================================================
# Catchable Exception Hierarchy (compatible with src/llm/errors.py)
# ============================================================


class NativeAPIError(Exception):
    """Base error raised by native HTTPX transport with automatic redaction on message and body."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        provider: str = "openai",
        body: Any = None,
        param: Optional[str] = None,
        secrets: Iterable[str] = (),
        error_code: Optional[str] = None,
        is_waf_blocked: bool = False,
        content_type: Optional[str] = None,
    ) -> None:
        self.status_code = status_code
        self.llm_provider = provider
        self.param = param
        self.error_code = error_code
        self.is_waf_blocked = bool(is_waf_blocked)
        self.body = sanitize_error_body(body, secrets, content_type=content_type)
        redacted_msg = sanitize_error_message(message, secrets)
        if looks_like_html(redacted_msg, content_type=content_type):
            redacted_msg = truncate_html_body(redacted_msg)
        self.message = redacted_msg
        super().__init__(self.message)


class NativeRateLimitError(NativeAPIError):
    """Raised on HTTP 429 or in-band rate-limit errors."""


class NativeContextWindowExceededError(NativeAPIError):
    """Raised when provider rejects a prompt exceeding context length."""


class NativeAuthenticationError(NativeAPIError):
    """Raised on HTTP 401/403 authentication failures (excluding WAF / model-disabled 403)."""


class NativeProviderBlockedError(NativeAPIError):
    """Raised on Cloudflare/WAF HTML 403 or model-disabled 403 (not an invalid API key)."""


class NativeBadRequestError(NativeAPIError):
    """Raised on non-retryable 400/413/422 validation or unsupported-parameter errors."""


class NativeConfigError(NativeBadRequestError):
    """Raised before network I/O when a deployment cannot run in strict native mode."""


class NativeNotFoundError(NativeAPIError):
    """Raised on fail-fast HTTP 404 endpoint or model not found errors."""


class NativeTimeoutError(NativeAPIError, TimeoutError):
    """Typed timeout error subclassing both NativeAPIError and TimeoutError."""

    def __init__(
        self,
        message: str = "LLM request timed out",
        *,
        status_code: Optional[int] = None,
        provider: str = "openai",
        body: Any = None,
        secrets: Iterable[str] = (),
    ) -> None:
        clean = str(message or "").strip()
        if not clean:
            clean = "LLM request timed out"
        elif "timeout" not in clean.lower() and "timed out" not in clean.lower():
            clean = f"Request timed out: {clean}"
        super().__init__(
            clean,
            status_code=status_code,
            provider=provider,
            body=body,
            secrets=secrets,
            error_code="timeout",
        )


class NativeConnectionError(NativeAPIError):
    """Raised on transport/network connection failures."""


class NativeServiceUnavailableError(NativeAPIError):
    """Raised on HTTP 502/503 upstream service unavailable responses."""


class NativeIncompleteStreamError(NativeAPIError):
    """Raised when an SSE stream closes with zero chunks, truncated EOF, or missing terminal event."""


class NativeContentFilterError(NativeAPIError):
    """Raised when provider blocks generation due to safety/content filter policy."""


# ============================================================
# HTTP & In-Band Error Classification
# ============================================================


def is_waf_or_html_block(
    status_code: int,
    body_text: str,
    headers: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Distinguish Cloudflare/WAF HTML 403 blocks from invalid API key errors."""
    if int(status_code) != 403:
        return False
    lower_headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    ct = lower_headers.get("content-type", "")
    # P1-3b: Sniff document-start HTML even if proxy mislabeled Content-Type as application/json.
    if looks_like_html(body_text, content_type=ct) or looks_like_html(body_text, ignore_content_type=True):
        return True
    if "cf-mitigated" in lower_headers:
        return True
    lowered = str(body_text or "").lower()
    if any(marker in lowered for marker in _WAF_MARKERS):
        return True
    if "cf-ray" in lower_headers:
        try:
            parsed = json.loads(body_text) if body_text else None
        except ValueError:
            parsed = None
        if not isinstance(parsed, Mapping):
            return True
    return False


def is_model_access_denied_error(body_text: str) -> bool:
    """Detect HTTP 403 errors indicating a disabled/inaccessible model rather than a bad key."""
    lowered = str(body_text or "").lower()
    if "model" not in lowered:
        return False
    return any(marker in lowered for marker in _MODEL_ACCESS_DENIED_MARKERS)


def _extract_error_envelope(
    body_text: str,
    *,
    status_code: int,
) -> Tuple[Any, str, Optional[str], Optional[str]]:
    parsed_body: Any = body_text
    error_message = body_text or f"HTTP {status_code}"
    error_param: Optional[str] = None
    error_type: Optional[str] = None
    try:
        data = json.loads(body_text) if body_text else None
    except ValueError:
        data = None
    if isinstance(data, Mapping):
        parsed_body = data
        err_obj = data.get("error")
        if isinstance(err_obj, Mapping):
            error_message = str(err_obj.get("message") or err_obj.get("status") or error_message)
            raw_param = err_obj.get("param")
            error_param = str(raw_param) if raw_param else None
            raw_type = err_obj.get("type") or err_obj.get("code") or err_obj.get("status")
            error_type = str(raw_type).lower() if raw_type else None
        elif isinstance(err_obj, str) and err_obj.strip():
            error_message = err_obj.strip()
        elif data.get("message"):
            error_message = str(data.get("message"))
    return parsed_body, error_message, error_param, error_type


def classify_http_error(
    status_code: int,
    body_text: str,
    *,
    provider: str = "openai",
    secrets: Iterable[str] = (),
    headers: Optional[Mapping[str, Any]] = None,
    url: str = "",
) -> NativeAPIError:
    """Classify an HTTP >=400 error body across OpenAI, Anthropic, and Gemini schemas."""
    lower_headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    ct = lower_headers.get("content-type", "")
    code = int(status_code)

    if is_waf_or_html_block(code, body_text, headers=headers):
        snippet = truncate_html_body(sanitize_error_message(body_text, secrets))
        return NativeProviderBlockedError(
            f"ProviderBlockedError (HTTP 403 WAF/Cloudflare): blocked by Cloudflare/WAF, not invalid API key. {snippet}",
            status_code=code,
            provider=provider,
            body=body_text,
            secrets=secrets,
            error_code="provider_blocked",
            is_waf_blocked=True,
            content_type=ct or "text/html",
        )

    parsed_body, error_message, error_param, error_type = _extract_error_envelope(
        body_text,
        status_code=code,
    )
    if looks_like_html(error_message, content_type=ct):
        error_message = truncate_html_body(error_message)
    lowered = error_message.lower()

    if code == 429 or (error_type and "rate_limit" in error_type):
        return NativeRateLimitError(
            f"RateLimitError: {error_message}",
            status_code=code,
            provider=provider,
            body=parsed_body,
            param=error_param,
            secrets=secrets,
            error_code="rate_limit",
            content_type=ct,
        )

    if code == 403:
        if is_model_access_denied_error(error_message):
            return NativeProviderBlockedError(
                f"ModelAccessDenied (HTTP 403): {error_message}",
                status_code=code,
                provider=provider,
                body=parsed_body,
                param=error_param,
                secrets=secrets,
                error_code="model_access_denied",
                is_waf_blocked=False,
                content_type=ct,
            )
        return NativeAuthenticationError(
            f"AuthenticationError: {error_message}",
            status_code=code,
            provider=provider,
            body=parsed_body,
            param=error_param,
            secrets=secrets,
            error_code="api_key_rejected",
            content_type=ct,
        )

    if code == 401:
        return NativeAuthenticationError(
            f"AuthenticationError: {error_message}",
            status_code=code,
            provider=provider,
            body=parsed_body,
            param=error_param,
            secrets=secrets,
            error_code="api_key_rejected",
            content_type=ct,
        )

    if code == 404:
        hint = ""
        url_l = str(url or "").lower()
        if "/responses" in url_l and "model" not in lowered:
            hint = " (Relay lacks /responses; use Chat Completions.)"
        elif "/chat/completions" in url_l and "/v1/" not in url_l and "model" not in lowered:
            hint = " (Missing /v1? Check Base URL.)"
        return NativeNotFoundError(
            f"NotFoundError (HTTP 404): {error_message}{hint}",
            status_code=code,
            provider=provider,
            body=parsed_body,
            param=error_param,
            secrets=secrets,
            error_code="endpoint_not_found",
            content_type=ct,
        )

    if code in (400, 413, 422):
        if any(marker in lowered for marker in _CONTEXT_WINDOW_MARKERS):
            return NativeContextWindowExceededError(
                f"ContextWindowExceededError: {error_message}",
                status_code=code,
                provider=provider,
                body=parsed_body,
                param=error_param,
                secrets=secrets,
                error_code="context_window_exceeded",
                content_type=ct,
            )
        return NativeBadRequestError(
            error_message,
            status_code=code,
            provider=provider,
            body=parsed_body,
            param=error_param,
            secrets=secrets,
            error_code="bad_request",
            content_type=ct,
        )

    if code in (408, 504):
        return NativeTimeoutError(
            f"Request timed out (HTTP {code}): {error_message}",
            status_code=code,
            provider=provider,
            body=parsed_body,
            secrets=secrets,
        )

    if code in (502, 503):
        return NativeServiceUnavailableError(
            f"ServiceUnavailableError (HTTP {code}): {error_message}",
            status_code=code,
            provider=provider,
            body=parsed_body,
            param=error_param,
            secrets=secrets,
            error_code="service_unavailable",
            content_type=ct,
        )

    return NativeAPIError(
        f"APIError (HTTP {code}): {error_message}",
        status_code=code,
        provider=provider,
        body=parsed_body,
        param=error_param,
        secrets=secrets,
        content_type=ct,
    )


def check_in_band_json_error(
    payload: Mapping[str, Any],
    *,
    provider: str = "openai",
    secrets: Iterable[str] = (),
) -> None:
    """Raise a classified, redacted ``NativeAPIError`` if an HTTP 200 or SSE JSON payload carries an error envelope."""
    err_obj = payload.get("error")
    if not err_obj:
        return

    inferred_status = 500
    if isinstance(err_obj, Mapping):
        raw_code = err_obj.get("code") or err_obj.get("status_code")
        if isinstance(raw_code, int) and 400 <= raw_code < 600:
            inferred_status = raw_code
        elif isinstance(raw_code, str) and raw_code.isdigit():
            parsed_code = int(raw_code)
            if 400 <= parsed_code < 600:
                inferred_status = parsed_code
        else:
            err_type = str(err_obj.get("type") or err_obj.get("code") or err_obj.get("status") or "").lower()
            err_msg = str(err_obj.get("message") or "").lower()
            combined = f"{err_type} {err_msg}"
            if "rate_limit" in combined or "too many requests" in combined or "resource_exhausted" in combined:
                inferred_status = 429
            elif "authentication" in combined or "invalid_api_key" in combined or "unauthorized" in combined:
                inferred_status = 401
            elif "permission" in combined or "forbidden" in combined:
                inferred_status = 403
            elif "not_found" in combined or "not found" in combined:
                inferred_status = 404
            elif any(
                tok in combined
                for tok in (
                    "invalid_request",
                    "invalid_argument",
                    "bad_request",
                    "context_length",
                    "context window",
                    "unsupported",
                )
            ):
                inferred_status = 400
            elif "overloaded" in combined or "unavailable" in combined:
                inferred_status = 503

    body_text = json.dumps(payload, ensure_ascii=False, default=str)
    raise classify_http_error(
        inferred_status,
        body_text,
        provider=provider,
        secrets=secrets,
    )


def check_http_200_html_response(
    status_code: int,
    content_type: Optional[str],
    body_text: str,
    *,
    provider: str = "openai",
    secrets: Iterable[str] = (),
    ignore_content_type: bool = False,
) -> None:
    """Fail fast when an endpoint returns HTTP 200 HTML instead of JSON/SSE."""
    if not looks_like_html(body_text, content_type=content_type, ignore_content_type=ignore_content_type):
        return
    snippet = truncate_html_body(sanitize_error_message(body_text, secrets))
    raise NativeBadRequestError(
        f"Endpoint returned text/html instead of JSON; check Base URL /v1. {snippet}",
        status_code=int(status_code),
        provider=provider,
        body=body_text,
        secrets=secrets,
        error_code="non_json_html",
        content_type="text/html",
    )


# ============================================================
# LiteLLM-Compatible Response & Streaming Chunk Shims
# ============================================================


@dataclass
class NativeFunctionCall:
    """Function name and JSON argument string matching LiteLLM tool call contract."""

    name: Optional[str] = None
    arguments: Optional[str] = None

    def model_dump(self) -> Dict[str, Any]:
        return {"name": self.name, "arguments": self.arguments}


@dataclass
class NativeToolCall:
    """Tool call shim carrying optional Gemini ``thoughtSignature`` round-trip state."""

    id: Optional[str] = None
    function: NativeFunctionCall = field(default_factory=NativeFunctionCall)
    type: str = "function"
    index: int = 0
    thought_signature: Optional[str] = None
    provider_specific_fields: Dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "index": self.index,
            "function": self.function.model_dump(),
        }
        if self.thought_signature is not None:
            payload["thought_signature"] = self.thought_signature
        if self.provider_specific_fields:
            payload["provider_specific_fields"] = dict(self.provider_specific_fields)
        return payload


@dataclass
class NativeUsage:
    """Token/cache usage shim compatible with ``src/llm/usage.py`` normalization."""

    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    prompt_tokens_details: Optional[Dict[str, Any]] = None
    completion_tokens_details: Optional[Dict[str, Any]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if self.prompt_tokens is not None:
            payload["prompt_tokens"] = self.prompt_tokens
        if self.completion_tokens is not None:
            payload["completion_tokens"] = self.completion_tokens
        if self.total_tokens is not None:
            payload["total_tokens"] = self.total_tokens
        if self.prompt_tokens_details is not None:
            payload["prompt_tokens_details"] = dict(self.prompt_tokens_details)
        if self.completion_tokens_details is not None:
            payload["completion_tokens_details"] = dict(self.completion_tokens_details)
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload


@dataclass
class NativeMessage:
    """Message/delta shim preserving reasoning text, provider blocks, and content blocks."""

    role: str = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[NativeToolCall]] = None
    reasoning_content: Optional[str] = None
    provider_blocks: Optional[List[Dict[str, Any]]] = None
    thinking_blocks: Optional[List[Dict[str, Any]]] = None
    content_blocks: Optional[List[Dict[str, Any]]] = None

    def model_dump(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }
        if self.tool_calls is not None:
            payload["tool_calls"] = [tc.model_dump() for tc in self.tool_calls]
        if self.reasoning_content is not None:
            payload["reasoning_content"] = self.reasoning_content
        if self.provider_blocks is not None:
            payload["provider_blocks"] = [dict(block) for block in self.provider_blocks]
        if self.thinking_blocks is not None:
            payload["thinking_blocks"] = [dict(block) for block in self.thinking_blocks]
        if self.content_blocks is not None:
            payload["content_blocks"] = [dict(block) for block in self.content_blocks]
        return payload


@dataclass
class NativeChoice:
    """Single completion or stream choice shim."""

    index: int = 0
    message: Optional[NativeMessage] = None
    delta: Optional[NativeMessage] = None
    finish_reason: Optional[str] = None
    content_blocks: Optional[List[Dict[str, Any]]] = None

    def model_dump(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "index": self.index,
            "finish_reason": self.finish_reason,
        }
        if self.message is not None:
            payload["message"] = self.message.model_dump()
        if self.delta is not None:
            payload["delta"] = self.delta.model_dump()
        if self.content_blocks is not None:
            payload["content_blocks"] = [dict(block) for block in self.content_blocks]
        return payload


@dataclass
class NativeCompletionResponse:
    """Normalized non-streaming response shim compatible with ``LLMToolAdapter``."""

    id: str
    model: str
    choices: List[NativeChoice]
    usage: Optional[NativeUsage] = None
    created: int = field(default_factory=lambda: int(time.time()))
    object: str = "chat.completion"
    _hidden_params: Dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "object": self.object,
            "created": self.created,
            "model": self.model,
            "choices": [choice.model_dump() for choice in self.choices],
        }
        if self.usage is not None:
            payload["usage"] = self.usage.model_dump()
        return payload


@dataclass
class NativeStreamChunk:
    """Normalized streaming delta chunk shim."""

    id: str
    model: str
    choices: List[NativeChoice]
    usage: Optional[NativeUsage] = None
    created: int = field(default_factory=lambda: int(time.time()))
    object: str = "chat.completion.chunk"
    _hidden_params: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# Pure Protocol-Neutral Helpers
# ============================================================


def parse_data_url(url: str) -> Optional[Tuple[str, str]]:
    """Parse ``data:<mime>;base64,<payload>`` into ``(mime_type, cleaned_base64)``."""
    raw = str(url or "").strip()
    match = _DATA_URL_RE.match(raw)
    if not match:
        return None
    mime_type = match.group(1).strip().lower()
    b64_data = re.sub(r"\s+", "", match.group(2))
    if not mime_type or not b64_data:
        return None
    return mime_type, b64_data


def extract_tool_arguments_dict(raw_arguments: Any) -> Dict[str, Any]:
    """Safely convert tool call arguments (str/dict) into a JSON object dict."""
    if isinstance(raw_arguments, Mapping):
        return dict(raw_arguments)
    if raw_arguments is None:
        return {}
    text = str(raw_arguments).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    except ValueError:
        return {"raw": text}


def has_header_case_insensitive(headers: Mapping[str, str], target_name: str) -> bool:
    """Check header existence ignoring casing."""
    lowered = target_name.lower()
    return any(k.lower() == lowered for k in headers)


def set_header_case_insensitive(headers: Dict[str, str], name: str, value: str) -> None:
    """Insert/replace a header while removing any differently-cased duplicate key."""
    lowered = name.lower()
    for existing in list(headers.keys()):
        if existing.lower() == lowered and existing != name:
            headers.pop(existing, None)
    headers[name] = value


def parse_strict_bool(
    value: Any,
    *,
    field_name: str = "value",
    provider: str = "openai",
) -> bool:
    """Strictly parse a boolean or boolean string, rejecting ambiguous values like ``'maybe'``."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in {"true", "1", "yes", "on"}:
            return True
        if cleaned in {"false", "0", "no", "off"}:
            return False
    raise NativeBadRequestError(
        f"Invalid boolean value for '{field_name}': {value!r}",
        status_code=400,
        provider=provider,
        error_code="invalid_boolean",
    )


def merge_header_overrides(
    headers: Dict[str, str],
    source: Mapping[str, Any],
    *,
    resolve_env_fn: Optional[Callable[[Any], Any]] = None,
    skip_sensitive: bool = False,
    safe_allowlist_only: bool = False,
) -> None:
    """Merge ``extra_headers``/``headers``/``default_headers`` case-insensitively.

    When ``resolve_env_fn`` is provided, ``os.environ/VAR`` header values are
    expanded before merging. When ``safe_allowlist_only=True`` (or ``skip_sensitive=True``),
    only explicitly safe telemetry/content headers are forwarded across distinct origins (P0-2).
    """
    restrict_cross_origin = bool(safe_allowlist_only or skip_sensitive)
    for hdr_key in ("extra_headers", "headers", "default_headers"):
        raw = source.get(hdr_key)
        if isinstance(raw, Mapping):
            for k, v in raw.items():
                key_text = str(k).strip()
                if not key_text or v is None:
                    continue
                if restrict_cross_origin and not is_cross_origin_safe_header(key_text):
                    continue
                resolved_val = resolve_env_fn(v) if resolve_env_fn is not None else v
                if resolved_val is not None:
                    set_header_case_insensitive(headers, key_text, str(resolved_val))


def extract_client_overrides(
    kwargs: Mapping[str, Any],
) -> Tuple[Optional[str], Optional[str], Optional[httpx.Client]]:
    """Extract ``(api_key, base_url, httpx_client)`` from an injected OpenAI/HTTPX ``client`` kwarg."""
    client_obj = kwargs.get("client")
    if client_obj is None:
        return None, None, None
    raw_key = getattr(client_obj, "api_key", None)
    client_api_key = str(raw_key).strip() if isinstance(raw_key, str) and raw_key.strip() else None
    raw_base = getattr(client_obj, "base_url", None)
    client_base_url = str(raw_base).strip().rstrip("/") if raw_base is not None else None
    if not client_base_url:
        client_base_url = None
    inner_http = getattr(client_obj, "_client", None)
    if isinstance(inner_http, httpx.Client):
        client_http: Optional[httpx.Client] = inner_http
    elif isinstance(client_obj, httpx.Client):
        client_http = client_obj
    else:
        client_http = None
    return client_api_key, client_base_url, client_http
