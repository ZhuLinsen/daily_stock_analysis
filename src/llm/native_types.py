# -*- coding: utf-8 -*-
"""
===================================
Shared Native HTTPX Types, Errors, Protocol Resolution, and Pooled Execution Engine
===================================

Issue #2622 Phase 2b: protocol-neutral shims (preserving LiteLLM response/exception/
usage contracts), error classification, base64 data-URL helpers, and shared pooled
request/stream execution across OpenAI Chat, OpenAI Responses, Anthropic Messages,
and Google Gemini REST APIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

import httpx

from src.llm.pool import DeploymentEntry, DeploymentPool, parse_retry_after, sanitize_error_message

logger = logging.getLogger(__name__)

# Providers handled cleanly through native OpenAI Chat Completions / Responses HTTPX paths.
NATIVE_OPENAI_PROVIDERS: frozenset[str] = frozenset(
    {
        "openai",
        "openai_compatible",
        "custom",
        "deepseek",
        "moonshot",
        "dashscope",
        "qwen",
        "zhipu",
        "glm",
        "minimax",
        "volcengine",
        "ark",
        "siliconflow",
        "openrouter",
        "ollama",
        "groq",
        "xai",
        "together_ai",
        "fireworks_ai",
        "mistral",
        "perplexity",
    }
)

NATIVE_ANTHROPIC_PROVIDERS: frozenset[str] = frozenset({"anthropic", "claude"})
NATIVE_GEMINI_PROVIDERS: frozenset[str] = frozenset({"gemini", "google"})

FALLBACK_ONLY_PROVIDERS: frozenset[str] = frozenset(
    {
        "vertex_ai",
        "vertex_ai_beta",
        "bedrock",
        "azure",
        "azure_ai",
    }
)

DEFAULT_ANTHROPIC_BASE = "https://api.anthropic.com"
DEFAULT_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

DEFAULT_PROVIDER_BASES: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": DEFAULT_ANTHROPIC_BASE,
    "claude": DEFAULT_ANTHROPIC_BASE,
    "gemini": DEFAULT_GEMINI_BASE,
    "google": DEFAULT_GEMINI_BASE,
    "deepseek": "https://api.deepseek.com/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "minimax": "https://api.minimax.chat/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "groq": "https://api.groq.com/openai/v1",
    "xai": "https://api.x.ai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "perplexity": "https://api.perplexity.ai",
}

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
)

_DATA_URL_RE = re.compile(
    r"^data:([^;,\s]+)(?:;[^,]*)?;base64,(.+)$",
    re.IGNORECASE | re.DOTALL,
)


# ============================================================
# Catchable exception hierarchy (compatible with src/llm/errors.py)
# ============================================================


class NativeAPIError(Exception):
    """Base error raised by native HTTPX LLM transport with automatic secret redaction."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        provider: str = "openai",
        body: Any = None,
        param: Optional[str] = None,
        secrets: Iterable[str] = (),
    ) -> None:
        self.status_code = status_code
        self.llm_provider = provider
        self.body = body
        self.param = param
        self.message = sanitize_error_message(message, secrets)
        super().__init__(self.message)


class NativeRateLimitError(NativeAPIError):
    """Raised on HTTP 429 rate limits."""


class NativeContextWindowExceededError(NativeAPIError):
    """Raised when provider rejects a prompt exceeding context length."""


class NativeAuthenticationError(NativeAPIError):
    """Raised on HTTP 401/403 authentication failures."""


class NativeBadRequestError(NativeAPIError):
    """Raised on non-retryable 400/413/422 validation or unsupported-parameter errors."""


# ============================================================
# LiteLLM-compatible response & streaming chunk shims
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
    """Message/delta shim preserving reasoning text and Anthropic provider thinking blocks."""

    role: str = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[NativeToolCall]] = None
    reasoning_content: Optional[str] = None
    provider_blocks: Optional[List[Dict[str, Any]]] = None
    thinking_blocks: Optional[List[Dict[str, Any]]] = None

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
        return payload


@dataclass
class NativeChoice:
    """Single completion or stream choice shim."""

    index: int = 0
    message: Optional[NativeMessage] = None
    delta: Optional[NativeMessage] = None
    finish_reason: Optional[str] = None

    def model_dump(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "index": self.index,
            "finish_reason": self.finish_reason,
        }
        if self.message is not None:
            payload["message"] = self.message.model_dump()
        if self.delta is not None:
            payload["delta"] = self.delta.model_dump()
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


# ============================================================
# Shared utility helpers
# ============================================================


def strip_provider_prefix(model: str) -> Tuple[str, str]:
    """Extract ``(provider, wire_model)``, inferring Anthropic/Gemini when unprefixed."""
    raw = str(model or "").strip()
    if not raw:
        return "openai", ""
    if "/" not in raw:
        lowered = raw.lower()
        if lowered.startswith("claude"):
            return "anthropic", raw
        if lowered.startswith("gemini"):
            return "gemini", raw
        return "openai", raw
    prefix, rest = raw.split("/", 1)
    provider = prefix.strip().lower()
    return provider, rest.strip()


def resolve_openai_wire_protocol(
    model: str,
    *,
    api_base: Optional[str] = None,
    wire_protocol: Optional[str] = None,
) -> str:
    """Resolve ``openai_chat`` vs ``openai_responses`` for an OpenAI-family target."""
    explicit = (wire_protocol or "").strip().lower()
    if explicit in {"openai_chat", "chat", "chat_completions"}:
        return "openai_chat"
    if explicit in {"openai_responses", "responses", "openai-responses"}:
        return "openai_responses"

    normalized_base = (api_base or "").strip().rstrip("/").lower()
    if normalized_base.endswith("/responses"):
        return "openai_responses"

    provider, wire_model = strip_provider_prefix(model)
    lowered_model = wire_model.lower()
    if provider in {"openai", "openai_compatible"} and (
        (lowered_model.startswith("gpt-5") and "chat-latest" not in lowered_model)
        or lowered_model.startswith("o3")
        or lowered_model.startswith("o4")
        or "codex" in lowered_model
    ):
        return "openai_responses"

    return "openai_chat"


def resolve_native_protocol(
    model: str,
    *,
    api_base: Optional[str] = None,
    custom_llm_provider: Optional[str] = None,
    wire_protocol: Optional[str] = None,
) -> Optional[str]:
    """Resolve native wire protocol (``openai_chat``, ``openai_responses``, ``anthropic``, ``gemini``) or ``None``."""
    explicit = (wire_protocol or "").strip().lower()
    if explicit in {"openai_chat", "chat", "chat_completions"}:
        return "openai_chat"
    if explicit in {"openai_responses", "responses", "openai-responses"}:
        return "openai_responses"
    if explicit in {"anthropic", "anthropic_messages", "messages", "claude"}:
        return "anthropic"
    if explicit in {"gemini", "gemini_generate_content", "google_gemini"}:
        return "gemini"

    provider_hint = (custom_llm_provider or "").strip().lower()
    if provider_hint:
        if provider_hint in FALLBACK_ONLY_PROVIDERS:
            return None
        if provider_hint in NATIVE_ANTHROPIC_PROVIDERS:
            return "anthropic"
        if provider_hint in NATIVE_GEMINI_PROVIDERS:
            return "gemini"
        if provider_hint in {"openai", "openai_compatible"} or provider_hint in NATIVE_OPENAI_PROVIDERS:
            return resolve_openai_wire_protocol(model, api_base=api_base, wire_protocol=wire_protocol)

    provider, _ = strip_provider_prefix(model)
    if provider in FALLBACK_ONLY_PROVIDERS:
        return None
    if provider in NATIVE_ANTHROPIC_PROVIDERS:
        return "anthropic"
    if provider in NATIVE_GEMINI_PROVIDERS:
        return "gemini"
    if provider in NATIVE_OPENAI_PROVIDERS:
        return resolve_openai_wire_protocol(model, api_base=api_base, wire_protocol=wire_protocol)

    if api_base:
        normalized_base = str(api_base).strip().lower()
        if "anthropic.com" in normalized_base:
            return "anthropic"
        if "generativelanguage.googleapis.com" in normalized_base:
            return "gemini"
        return resolve_openai_wire_protocol(model, api_base=api_base, wire_protocol=wire_protocol)

    return None


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


def resolve_default_api_base(provider: str, protocol: str) -> str:
    """Return canonical default base URL for a given provider/protocol pair."""
    if protocol == "anthropic":
        return DEFAULT_ANTHROPIC_BASE
    if protocol == "gemini":
        return DEFAULT_GEMINI_BASE
    return DEFAULT_PROVIDER_BASES.get(provider) or DEFAULT_PROVIDER_BASES["openai"]


def extract_tool_arguments_dict(raw_arguments: Any) -> Dict[str, Any]:
    """Safely convert tool call arguments (str/dict) into a JSON object dict for Anthropic/Gemini."""
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


def classify_http_error(
    status_code: int,
    body_text: str,
    *,
    provider: str,
    secrets: Iterable[str] = (),
) -> NativeAPIError:
    """Classify an HTTP >=400 error body across OpenAI, Anthropic, and Gemini schemas."""
    parsed_body: Any = body_text
    error_message = body_text or f"HTTP {status_code}"
    error_param: Optional[str] = None
    try:
        data = json.loads(body_text) if body_text else None
    except ValueError:
        data = None
    if isinstance(data, Mapping):
        parsed_body = data
        err_obj = data.get("error")
        if isinstance(err_obj, Mapping):
            error_message = str(err_obj.get("message") or error_message)
            raw_param = err_obj.get("param")
            error_param = str(raw_param) if raw_param else None
        elif data.get("message"):
            error_message = str(data.get("message"))

    lowered = error_message.lower()
    if status_code == 429:
        return NativeRateLimitError(
            f"RateLimitError: {error_message}",
            status_code=status_code,
            provider=provider,
            body=parsed_body,
            param=error_param,
            secrets=secrets,
        )
    if status_code in (401, 403):
        return NativeAuthenticationError(
            f"AuthenticationError: {error_message}",
            status_code=status_code,
            provider=provider,
            body=parsed_body,
            param=error_param,
            secrets=secrets,
        )
    if status_code in (400, 413, 422):
        if any(marker in lowered for marker in _CONTEXT_WINDOW_MARKERS):
            return NativeContextWindowExceededError(
                f"ContextWindowExceededError: {error_message}",
                status_code=status_code,
                provider=provider,
                body=parsed_body,
                param=error_param,
                secrets=secrets,
            )
        return NativeBadRequestError(
            error_message,
            status_code=status_code,
            provider=provider,
            body=parsed_body,
            param=error_param,
            secrets=secrets,
        )
    return NativeAPIError(
        f"APIError (HTTP {status_code}): {error_message}",
        status_code=status_code,
        provider=provider,
        body=parsed_body,
        param=error_param,
        secrets=secrets,
    )


def merge_header_overrides(headers: Dict[str, str], source: Mapping[str, Any]) -> None:
    """Merge ``extra_headers``/``headers``/``default_headers`` dictionaries cleanly."""
    for hdr_key in ("extra_headers", "headers", "default_headers"):
        raw = source.get(hdr_key)
        if isinstance(raw, Mapping):
            headers.update({str(k): str(v) for k, v in raw.items()})


def has_header_case_insensitive(headers: Mapping[str, str], target_name: str) -> bool:
    """Check header existence ignoring casing."""
    lowered = target_name.lower()
    return any(k.lower() == lowered for k in headers)


# ============================================================
# Shared pooled HTTPX sync & stream runners
# ============================================================


PreparedRequest = Tuple[str, Dict[str, str], Dict[str, Any], float]


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


def _build_httpx_client(timeout: float, http_transport: Optional[httpx.BaseTransport]) -> httpx.Client:
    client_kwargs: Dict[str, Any] = {"timeout": timeout}
    if http_transport is not None:
        client_kwargs["transport"] = http_transport
    return httpx.Client(**client_kwargs)


def _resolve_retry_sleep_fn(
    sleep_fn: Optional[Callable[[float], None]],
    http_transport: Optional[httpx.BaseTransport],
) -> Callable[[float], None]:
    if sleep_fn is not None:
        return sleep_fn
    if http_transport is not None:
        return lambda _seconds: None
    return time.sleep


def execute_pooled_completion(
    *,
    candidates: List[DeploymentEntry],
    pool: Optional[DeploymentPool],
    using_pool: bool,
    messages: List[Dict[str, Any]],
    kwargs: Mapping[str, Any],
    prepare_request_fn: Callable[[DeploymentEntry, List[Dict[str, Any]], bool, Mapping[str, Any]], PreparedRequest],
    parse_response_fn: Callable[[DeploymentEntry, Mapping[str, Any]], NativeCompletionResponse],
    http_transport: Optional[httpx.BaseTransport] = None,
    http_client: Optional[httpx.Client] = None,
    request_model: str = "",
    num_retries: int = 0,
    sleep_fn: Optional[Callable[[float], None]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
) -> NativeCompletionResponse:
    """Execute non-streaming pooled POST across healthy candidates with cooldown, retries & redaction."""
    max_rounds = 1 + max(0, int(num_retries))
    effective_sleep = _resolve_retry_sleep_fn(sleep_fn, http_transport)
    bad_auth_ids: set[str] = set()
    last_error: Optional[Exception] = None
    use_caller_client = http_client is not None and http_transport is None

    for round_idx in range(max_rounds):
        round_source = (
            pool.select_candidates(request_model)
            if (round_idx > 0 and using_pool and pool is not None)
            else candidates
        )
        round_candidates = [entry for entry in round_source if entry.deployment_id not in bad_auth_ids]
        if not round_candidates:
            break
        if round_idx > 0:
            if cancel_check is not None:
                cancel_check()
            effective_sleep(min(0.25 * round_idx, 1.0))

        for entry in round_candidates:
            if cancel_check is not None:
                cancel_check()
            secrets = [s for s in (entry.api_key, kwargs.get("api_key")) if s]
            url, headers, payload, req_timeout = prepare_request_fn(entry, messages, False, kwargs)
            try:
                if use_caller_client and http_client is not None:
                    resp = http_client.post(url, headers=headers, json=payload, timeout=req_timeout)
                else:
                    with _build_httpx_client(req_timeout, http_transport) as client:
                        resp = client.post(url, headers=headers, json=payload)
                if resp.status_code >= 400:
                    err = classify_http_error(
                        resp.status_code,
                        resp.text,
                        provider=entry.provider,
                        secrets=secrets,
                    )
                    if resp.status_code in (400, 413, 422):
                        raise err
                    if resp.status_code in (401, 403):
                        bad_auth_ids.add(entry.deployment_id)
                    if using_pool and pool is not None:
                        pool.mark_failure(
                            entry.deployment_id,
                            status_code=resp.status_code,
                            retry_after=parse_retry_after(resp.headers.get("retry-after")),
                        )
                    last_error = err
                    continue

                data = resp.json()
                if not isinstance(data, Mapping):
                    raise NativeAPIError("Unexpected non-object JSON response", provider=entry.provider)

                parsed = parse_response_fn(entry, data)
                parsed._hidden_params["deployment_id"] = entry.deployment_id
                parsed._hidden_params["protocol"] = entry.protocol
                if using_pool and pool is not None:
                    pool.mark_success(entry.deployment_id)
                return parsed

            except (NativeBadRequestError, NativeContextWindowExceededError):
                raise
            except (httpx.TimeoutException, httpx.TransportError, ValueError) as exc:
                sanitized = sanitize_error_message(exc, secrets)
                logger.warning("[NativeLLM] Deployment %s transient error: %s", entry.deployment_id, sanitized)
                if using_pool and pool is not None:
                    pool.mark_failure(entry.deployment_id)
                last_error = NativeAPIError(sanitized, provider=entry.provider, secrets=secrets)
            except NativeAPIError as exc:
                last_error = exc

    if last_error is not None:
        raise last_error
    raise NativeAPIError(f"No available deployments configured for {request_model or 'request'}", provider="openai")


def _open_stream_candidate(
    *,
    entry: DeploymentEntry,
    pool: Optional[DeploymentPool],
    using_pool: bool,
    messages: List[Dict[str, Any]],
    kwargs: Mapping[str, Any],
    prepare_request_fn: Callable[[DeploymentEntry, List[Dict[str, Any]], bool, Mapping[str, Any]], PreparedRequest],
    http_transport: Optional[httpx.BaseTransport],
    http_client: Optional[httpx.Client],
    use_caller_client: bool,
    bad_auth_ids: set[str],
) -> Tuple[Optional[Tuple[Any, httpx.Response, httpx.Client, bool]], Optional[Exception]]:
    """Open a single SSE stream candidate cleanly, closing resources on pre-stream failure."""
    secrets = [s for s in (entry.api_key, kwargs.get("api_key")) if s]
    url, headers, payload, req_timeout = prepare_request_fn(entry, messages, True, kwargs)
    owns_client = not use_caller_client
    client = http_client if (use_caller_client and http_client is not None) else _build_httpx_client(req_timeout, http_transport)
    try:
        if use_caller_client and http_client is not None:
            ctx = client.stream("POST", url, headers=headers, json=payload, timeout=req_timeout)
        else:
            ctx = client.stream("POST", url, headers=headers, json=payload)
        resp = ctx.__enter__()
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        if owns_client:
            client.close()
        sanitized = sanitize_error_message(exc, secrets)
        if using_pool and pool is not None:
            pool.mark_failure(entry.deployment_id)
        return None, NativeAPIError(sanitized, provider=entry.provider, secrets=secrets)

    if resp.status_code >= 400:
        body_text = resp.read().decode("utf-8", errors="replace")
        retry_after = parse_retry_after(resp.headers.get("retry-after"))
        ctx.__exit__(None, None, None)
        if owns_client:
            client.close()
        err = classify_http_error(
            resp.status_code,
            body_text,
            provider=entry.provider,
            secrets=secrets,
        )
        if resp.status_code in (400, 413, 422):
            raise err
        if resp.status_code in (401, 403):
            bad_auth_ids.add(entry.deployment_id)
        if using_pool and pool is not None:
            pool.mark_failure(
                entry.deployment_id,
                status_code=resp.status_code,
                retry_after=retry_after,
            )
        return None, err

    return (ctx, resp, client, owns_client), None


def stream_pooled_completion(
    *,
    candidates: List[DeploymentEntry],
    pool: Optional[DeploymentPool],
    using_pool: bool,
    messages: List[Dict[str, Any]],
    kwargs: Mapping[str, Any],
    prepare_request_fn: Callable[[DeploymentEntry, List[Dict[str, Any]], bool, Mapping[str, Any]], PreparedRequest],
    iter_stream_fn: Callable[[DeploymentEntry, Iterable[bytes]], Iterator[NativeStreamChunk]],
    http_transport: Optional[httpx.BaseTransport] = None,
    http_client: Optional[httpx.Client] = None,
    request_model: str = "",
    num_retries: int = 0,
    sleep_fn: Optional[Callable[[float], None]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
) -> Iterator[NativeStreamChunk]:
    """Open SSE stream with pre-first-chunk failover/retries and strict post-first-chunk safety."""
    max_rounds = 1 + max(0, int(num_retries))
    effective_sleep = _resolve_retry_sleep_fn(sleep_fn, http_transport)
    bad_auth_ids: set[str] = set()
    first_open: Optional[Tuple[int, int, DeploymentEntry, Any, httpx.Response, httpx.Client, bool, List[DeploymentEntry]]] = None
    last_error: Optional[Exception] = None
    use_caller_client = http_client is not None and http_transport is None

    for round_idx in range(max_rounds):
        round_source = (
            pool.select_candidates(request_model)
            if (round_idx > 0 and using_pool and pool is not None)
            else candidates
        )
        round_candidates = [entry for entry in round_source if entry.deployment_id not in bad_auth_ids]
        if not round_candidates:
            break
        if round_idx > 0:
            if cancel_check is not None:
                cancel_check()
            effective_sleep(min(0.25 * round_idx, 1.0))

        for idx, entry in enumerate(round_candidates):
            if cancel_check is not None:
                cancel_check()
            opened, err = _open_stream_candidate(
                entry=entry,
                pool=pool,
                using_pool=using_pool,
                messages=messages,
                kwargs=kwargs,
                prepare_request_fn=prepare_request_fn,
                http_transport=http_transport,
                http_client=http_client,
                use_caller_client=use_caller_client,
                bad_auth_ids=bad_auth_ids,
            )
            if opened is None:
                last_error = err
                continue
            ctx, resp, client, owns_client = opened
            first_open = (round_idx, idx, entry, ctx, resp, client, owns_client, round_candidates)
            break
        if first_open is not None:
            break

    if first_open is None:
        if last_error is not None:
            raise last_error
        raise NativeAPIError(f"No healthy deployments available for {request_model or 'stream'}", provider="openai")

    def _generator() -> Iterator[NativeStreamChunk]:
        start_round, start_idx, first_entry, first_ctx, first_resp, first_client, first_owns_client, first_round_candidates = first_open
        emitted_any = False
        stream_error: Optional[Exception] = None

        for r_idx in range(start_round, max_rounds):
            if r_idx == start_round:
                round_entries: List[Tuple[DeploymentEntry, Optional[Any], Optional[httpx.Response], Optional[httpx.Client], bool]] = [
                    (first_entry, first_ctx, first_resp, first_client, first_owns_client)
                ] + [
                    (extra, None, None, None, not use_caller_client)
                    for extra in first_round_candidates[start_idx + 1 :]
                    if extra.deployment_id not in bad_auth_ids
                ]
            else:
                if cancel_check is not None:
                    cancel_check()
                effective_sleep(min(0.25 * r_idx, 1.0))
                source = pool.select_candidates(request_model) if (using_pool and pool is not None) else candidates
                round_entries = [
                    (extra, None, None, None, not use_caller_client)
                    for extra in source
                    if extra.deployment_id not in bad_auth_ids
                ]
                if not round_entries:
                    break

            for attempt_entry, ctx, resp, client, owns_client in round_entries:
                secrets = [s for s in (attempt_entry.api_key, kwargs.get("api_key")) if s]
                try:
                    if resp is None:
                        if cancel_check is not None:
                            cancel_check()
                        opened, open_err = _open_stream_candidate(
                            entry=attempt_entry,
                            pool=pool,
                            using_pool=using_pool,
                            messages=messages,
                            kwargs=kwargs,
                            prepare_request_fn=prepare_request_fn,
                            http_transport=http_transport,
                            http_client=http_client,
                            use_caller_client=use_caller_client,
                            bad_auth_ids=bad_auth_ids,
                        )
                        if opened is None:
                            stream_error = open_err
                            continue
                        ctx, resp, client, owns_client = opened

                    for chunk in iter_stream_fn(attempt_entry, resp.iter_bytes()):
                        emitted_any = True
                        yield chunk

                    if using_pool and pool is not None:
                        pool.mark_success(attempt_entry.deployment_id)
                    return

                except (NativeBadRequestError, NativeContextWindowExceededError):
                    raise
                except (httpx.TimeoutException, httpx.TransportError, NativeAPIError) as exc:
                    sanitized = sanitize_error_message(exc, secrets)
                    if using_pool and pool is not None:
                        pool.mark_failure(attempt_entry.deployment_id)
                    wrapped = (
                        exc
                        if isinstance(exc, NativeAPIError)
                        else NativeAPIError(sanitized, provider=attempt_entry.provider, secrets=secrets)
                    )
                    if emitted_any:
                        # Post-first-chunk safety: never duplicate output by switching deployment mid-stream.
                        raise wrapped from exc
                    stream_error = wrapped
                    continue
                finally:
                    if ctx is not None:
                        try:
                            ctx.__exit__(None, None, None)
                        except Exception:
                            pass
                    if client is not None and owns_client:
                        try:
                            client.close()
                        except Exception:
                            pass

        if stream_error is not None:
            raise stream_error

    return _generator()
