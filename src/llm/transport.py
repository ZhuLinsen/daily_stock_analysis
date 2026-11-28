# -*- coding: utf-8 -*-
"""Unified internal LLM transport facade and native 4-protocol router/transport.

Phase 1 (Issue #2622) centralized all runtime ``litellm`` interactions behind
``LLMTransport``. Phase 2 plugs in the native 4-protocol HTTPX + SSE engine
(``NativeUnifiedTransport`` + ``NativeUnifiedRouter``) controlled by the
env-only ``LLM_TRANSPORT_MODE`` switch (default ``litellm``; opt-in ``auto``
per-alias hybrid or strict ``native``).
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import copy
import importlib
import logging
import math
import os
import sys
import threading
import time
import weakref
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Protocol,
    Tuple,
    runtime_checkable,
)

from src.core.stock_execution_context import raise_if_stock_cancelled
from src.llm.native_engine import (
    close_pooled_clients,
    execute_pooled_completion,
    stream_pooled_completion,
)
from src.llm.native_pool import DeploymentPool
from src.llm.native_resolve import (
    ALLOWED_REQUEST_DEFAULT_KEYS,
    CANONICAL_LITELLM_PROVIDERS,
    find_unresolved_env_var,
    resolve_deployment,
    resolve_env_reference,
    resolve_headers_env,
    url_origin,
)
from src.llm.native_types import (
    DeploymentSpec,
    NativeAPIError,
    NativeAuthenticationError,
    NativeBadRequestError,
    NativeCompletionResponse,
    NativeConfigError,
    NativeConnectionError,
    NativeContentFilterError,
    NativeContextWindowExceededError,
    NativeIncompleteStreamError,
    NativeNotFoundError,
    NativeProviderBlockedError,
    NativeRateLimitError,
    NativeServiceUnavailableError,
    NativeStreamChunk,
    NativeTimeoutError,
    PreparedRequest,
    Unsupported,
    extract_client_overrides,
)

logger = logging.getLogger(__name__)

_ALLOWED_REQUEST_DEFAULT_KEYS: frozenset[str] = ALLOWED_REQUEST_DEFAULT_KEYS

_NATIVE_EXCEPTION_MAP: Dict[str, type[BaseException]] = {
    "RateLimitError": NativeRateLimitError,
    "ContextWindowExceededError": NativeContextWindowExceededError,
    "Timeout": NativeTimeoutError,
    "APITimeoutError": NativeTimeoutError,
    "APIConnectionError": NativeConnectionError,
    "ServiceUnavailableError": NativeServiceUnavailableError,
    "AuthenticationError": NativeAuthenticationError,
    "BadRequestError": NativeBadRequestError,
    "NotFoundError": NativeNotFoundError,
    "PermissionDeniedError": NativeProviderBlockedError,
    "APIError": NativeAPIError,
    "ContentPolicyViolationError": NativeContentFilterError,
}

# Shared dynamic model pricing registry across native and hybrid fallback paths.
_SHARED_MODEL_COSTS_LOCK = threading.Lock()
_SHARED_MODEL_COSTS: Dict[str, Any] = {}


def _apply_disable_streaming_logging(module: Any) -> None:
    """Keep LiteLLM per-chunk async streaming logging disabled (Issue #2524)."""
    if module is None:
        return
    try:
        setattr(module, "disable_streaming_logging", True)
    except (AttributeError, TypeError):
        pass


def resolve_litellm_params_env(params: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a non-mutating copy of ``litellm_params`` with ``os.environ/`` resolved."""
    if not isinstance(params, Mapping):
        return {}
    resolved: Dict[str, Any] = {}
    for key, value in params.items():
        if key == "extra_headers" and isinstance(value, Mapping):
            resolved[key] = resolve_headers_env(value)
        elif isinstance(value, str):
            resolved[key] = resolve_env_reference(value)
        elif isinstance(value, (Mapping, list)):
            resolved[key] = copy.deepcopy(value)
        else:
            resolved[key] = value
    return resolved


def normalize_model_list_entries(
    model_list: Optional[Iterable[Mapping[str, Any]]],
) -> List[Dict[str, Any]]:
    """Return a normalized copy of Router ``model_list`` entries.

    Resolves ``os.environ/VAR`` references in ``litellm_params`` while preserving
    ``model_info`` metadata such as ``dsa_api_surface`` and ``dsa_channel_protocol``.
    """
    normalized: List[Dict[str, Any]] = []
    for entry in model_list or ():
        if not isinstance(entry, Mapping):
            continue
        copied = dict(entry)
        raw_params = entry.get("litellm_params")
        if isinstance(raw_params, Mapping):
            copied["litellm_params"] = resolve_litellm_params_env(raw_params)
        raw_info = entry.get("model_info")
        if isinstance(raw_info, Mapping):
            copied["model_info"] = copy.deepcopy(dict(raw_info))
        normalized.append(copied)
    return normalized


def _is_allowed_request_default_key(key: str) -> bool:
    return str(key).strip().lower() in _ALLOWED_REQUEST_DEFAULT_KEYS


def _is_responses_api_surface(api_surface: Any) -> bool:
    raw_surface = str(api_surface or "").strip().lower().replace("-", "_")
    return raw_surface in {"responses", "response", "responses_api"}


def _encode_litellm_responses_wire_model(model: Any, api_surface: Any) -> Any:
    """Apply LiteLLM's ``openai/responses/<model>`` encoding when ``api_surface`` is responses."""
    if not _is_responses_api_surface(api_surface):
        return model
    if not isinstance(model, str) or not model.strip():
        return model
    from src.config import apply_litellm_api_surface

    return apply_litellm_api_surface(model.strip(), "responses")


def _validate_prebuilt_router_api_surface(router: Any, model: Any, api_surface: Any) -> None:
    """Fail closed if a caller requests Responses on a prebuilt router without Responses deployments."""
    if not _is_responses_api_surface(api_surface):
        return
    target = str(model or "").strip()
    model_list = getattr(router, "model_list", None)
    if not isinstance(model_list, list) or not model_list:
        return
    matching_entries: List[Mapping[str, Any]] = []
    for entry in model_list:
        if not isinstance(entry, Mapping):
            continue
        params = entry.get("litellm_params")
        wire = str(params.get("model") or "").strip() if isinstance(params, Mapping) else ""
        # P1-2 & P1-6b: Match reachable deployments by exact alias (model_name, falling back to wire
        # only when model_name is empty) even if the alias string itself contains "/responses/".
        alias = str(entry.get("model_name") or "").strip() or wire
        if not target or target == alias:
            matching_entries.append(entry)
    if not matching_entries:
        return
    all_responses = True
    for entry in matching_entries:
        params = entry.get("litellm_params")
        wire = str(params.get("model") or "").strip() if isinstance(params, Mapping) else ""
        if not (wire.startswith("openai/responses/") or "/responses/" in wire):
            all_responses = False
            break
    if not all_responses:
        raise ValueError(
            f"Router deployment for model '{target}' is not configured for the OpenAI Responses API surface"
        )


def normalize_deployment_spec(entry: Mapping[str, Any]) -> DeploymentSpec:
    """Normalize a Router ``model_list`` entry into a ``DeploymentSpec``."""
    raw_params = entry.get("litellm_params")
    params = resolve_litellm_params_env(raw_params if isinstance(raw_params, Mapping) else {})
    raw_info = entry.get("model_info")
    model_info = copy.deepcopy(dict(raw_info)) if isinstance(raw_info, Mapping) else {}

    alias = str(entry.get("model_name") or params.get("model") or "").strip()
    wire_model = str(params.get("model") or alias).strip()
    channel_protocol = str(model_info.get("dsa_channel_protocol") or "").strip()
    wire_protocol = str(params.get("wire_protocol") or "").strip()
    custom_llm_provider = str(params.get("custom_llm_provider") or "").strip()
    api_surface = str(
        model_info.get("dsa_api_surface")
        or params.get("api_surface")
        or ""
    ).strip()
    if "base_url" in params and params.get("base_url") is not None:
        api_base = str(params.get("base_url")).strip()
    else:
        api_base = str(params.get("api_base") or "").strip()
    api_key = str(params.get("api_key") or "").strip()
    raw_resolved_headers = params.get("extra_headers")
    extra_headers = (
        dict(raw_resolved_headers)
        if isinstance(raw_resolved_headers, Mapping)
        else {}
    )
    raw_extra_body = params.get("extra_body")
    extra_body = copy.deepcopy(dict(raw_extra_body)) if isinstance(raw_extra_body, Mapping) else {}

    raw_priority = model_info.get(
        "priority",
        params.get("priority", params.get("order", 0)),
    )
    try:
        priority = int(raw_priority) if raw_priority is not None else 0
    except (TypeError, ValueError):
        priority = 0

    raw_timeout = params.get("timeout")
    timeout: Optional[float] = None
    if raw_timeout is not None and raw_timeout != "":
        try:
            parsed_timeout = float(raw_timeout)
            if math.isfinite(parsed_timeout) and parsed_timeout > 0:
                timeout = parsed_timeout
        except (TypeError, ValueError):
            timeout = None

    request_defaults = {
        key: copy.deepcopy(value)
        for key, value in params.items()
        if _is_allowed_request_default_key(key) and value is not None
    }

    return DeploymentSpec(
        alias=alias,
        wire_model=wire_model,
        channel_protocol=channel_protocol,
        wire_protocol=wire_protocol,
        custom_llm_provider=custom_llm_provider,
        api_surface=api_surface,
        api_base=api_base,
        api_key=api_key,
        extra_headers=extra_headers,
        extra_body=extra_body,
        request_defaults=request_defaults,
        priority=priority,
        timeout=timeout,
        model_info=model_info,
    )


def normalize_deployment_specs(
    model_list: Optional[Iterable[Mapping[str, Any]]],
) -> List[DeploymentSpec]:
    """Normalize a sequence of Router ``model_list`` dicts into ``DeploymentSpec``s."""
    return [
        normalize_deployment_spec(entry)
        for entry in (model_list or ())
        if isinstance(entry, Mapping)
    ]


def _is_cjk_char(ch: str) -> bool:
    """Return True when ``ch`` is a CJK ideograph, punctuation, kana, or hangul char."""
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2A6DF
        or 0xF900 <= code <= 0xFAFF
        or 0x3000 <= code <= 0x303F
        or 0xFF00 <= code <= 0xFFEF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def estimate_tokens_fallback(text: str) -> int:
    """CJK-aware fallback token estimate used when a tokenizer is unavailable."""
    normalized = str(text or "")
    if not normalized:
        return 0
    cjk_chars = sum(1 for ch in normalized if _is_cjk_char(ch))
    other_chars = len(normalized) - cjk_chars
    if cjk_chars == 0:
        return int(math.ceil(other_chars / 3))
    return int(math.ceil(cjk_chars * 1.5 + other_chars / 3))


@runtime_checkable
class LLMTransport(Protocol):
    """Internal transport contract consumed by all LLM call sites."""

    def completion(self, **kwargs: Any) -> Any: ...

    def create_router(self, model_list: List[Dict[str, Any]], **kwargs: Any) -> Any: ...

    def can_register_model(self) -> bool: ...

    def register_model(self, model_cost: Mapping[str, Any]) -> None: ...

    def get_model_cost(self) -> Dict[str, Any]: ...

    def estimate_tokens(self, text: str, *, model: Optional[str] = None) -> int: ...

    def get_model_providers(self) -> frozenset[str]: ...

    def disable_streaming_logging(self) -> None: ...

    def silence_logs(self) -> None: ...

    def resolve_exception(self, name: str) -> type[BaseException]: ...


class LiteLLMPatchProxy:
    """Lazy compatibility surface preserving legacy ``module.litellm.<attr>`` test mocks."""

    def __init__(self, *, disable_streaming_logging: bool = False) -> None:
        self.completion: Optional[Callable[..., Any]] = None
        self.register_model: Optional[Callable[..., Any]] = None
        self.model_cost: Optional[Dict[str, Any]] = None
        self.RateLimitError: Optional[type[BaseException]] = None
        self.ContextWindowExceededError: Optional[type[BaseException]] = None
        if disable_streaming_logging:
            self.disable_streaming_logging = True


def create_litellm_compat_proxy(*, disable_streaming_logging: bool = False) -> LiteLLMPatchProxy:
    """Create a lazy compatibility proxy without importing LiteLLM at module load time."""
    if disable_streaming_logging:
        _apply_disable_streaming_logging(sys.modules.get("litellm"))
    return LiteLLMPatchProxy(disable_streaming_logging=disable_streaming_logging)


_SYNTHETIC_EXCEPTIONS: Dict[str, type[BaseException]] = {}


def _build_synthetic_exception(name: str) -> type[BaseException]:
    cached = _SYNTHETIC_EXCEPTIONS.get(name)
    if cached is not None:
        return cached

    class _FallbackLiteLLMError(Exception):
        pass

    _FallbackLiteLLMError.__name__ = f"Fallback{name}"
    _SYNTHETIC_EXCEPTIONS[name] = _FallbackLiteLLMError
    return _FallbackLiteLLMError


_MATERIALIZED_FALLBACK_TRANSPORTS: "weakref.WeakSet[Any]" = weakref.WeakSet()
_PRICING_SYNC_LOCK = threading.Lock()


def _tag_response_transport_engine(response: Any, engine: str) -> Any:
    """Tag confirmed transport engine (``native`` or ``litellm``) onto response/stream (P1-13)."""
    if response is None or engine not in {"native", "litellm"}:
        return response
    hidden = getattr(response, "_hidden_params", None)
    if isinstance(hidden, dict):
        hidden["transport_engine"] = engine
        return response
    try:
        setattr(response, "transport_engine", engine)
    except Exception:
        pass
    return response


def _strip_internal_litellm_kwargs(kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    """Strip native-only transport metadata keys before calling LiteLLM SDK (including extra_body, F5)."""
    cleaned: Dict[str, Any] = {}
    for key, value in kwargs.items():
        if key in {"wire_protocol", "dsa_channel_protocol"} or str(key).startswith("_dsa_"):
            continue
        if key == "extra_body" and isinstance(value, Mapping):
            filtered_extra = {
                ek: ev
                for ek, ev in value.items()
                if ek not in {"wire_protocol", "dsa_channel_protocol"} and not str(ek).startswith("_dsa_")
            }
            if filtered_extra or not value:
                cleaned[key] = filtered_extra
            continue
        cleaned[key] = value
    return cleaned


_HARD_CONFIG_ERROR_REASONS = frozenset(
    {
        "invalid_deployment_param",
        "unsupported_channel_protocol",
        "unresolved_endpoint_env",
        "conflicting_api_base",
        "endpoint_surface_mismatch",
    }
)


def _is_synthetic_zero_cost_spec(spec: Any) -> bool:
    if not isinstance(spec, Mapping):
        return False
    return spec.get("input_cost_per_token") == 0.0 and spec.get("output_cost_per_token") == 0.0


def _sync_shared_pricing_to_transport(
    transport: Optional[LLMTransport],
    entries: Optional[Mapping[str, Any]] = None,
) -> None:
    """Mirror dynamically registered model costs into a fallback transport without clobbering SDK costs (P1-14, F5)."""
    if transport is None:
        return
    try:
        _MATERIALIZED_FALLBACK_TRANSPORTS.add(transport)
    except TypeError:
        pass
    try:
        # F5: Acquire _PRICING_SYNC_LOCK BEFORE snapshotting _SHARED_MODEL_COSTS so an older
        # snapshot can never revert a newer concurrent price update (strict lock order: sync -> costs).
        with _PRICING_SYNC_LOCK:
            with _SHARED_MODEL_COSTS_LOCK:
                if entries is None:
                    snapshot = dict(_SHARED_MODEL_COSTS)
                else:
                    snapshot = {
                        k: _SHARED_MODEL_COSTS.get(k, v)
                        for k, v in entries.items()
                    }
            if not snapshot or not transport.can_register_model():
                return
            existing_costs = transport.get_model_cost()
            filtered: Dict[str, Any] = {}
            for model_name, spec in snapshot.items():
                # P1-14: Never overwrite an existing built-in LiteLLM cost with synthetic 0.0 fallback defaults.
                if model_name in existing_costs and _is_synthetic_zero_cost_spec(spec):
                    continue
                filtered[model_name] = spec
            if filtered:
                sync_register = getattr(transport, "_register_model_sdk_only", None) or transport.register_model
                sync_register(filtered)
    except Exception as exc:
        logger.debug("Skipping shared model cost sync to fallback transport: %s", exc)


class LiteLLMTransport:
    """Default ``LLMTransport`` backed lazily by ``litellm``."""

    transport_engine: str = "litellm"

    @staticmethod
    def _load_litellm() -> Any:
        if "litellm" not in sys.modules:
            os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
        module = importlib.import_module("litellm")
        _apply_disable_streaming_logging(module)
        return module

    def completion(self, **kwargs: Any) -> Any:
        payload = _strip_internal_litellm_kwargs(kwargs)
        api_surface = payload.pop("api_surface", None)
        if api_surface and "model" in payload:
            payload["model"] = _encode_litellm_responses_wire_model(payload["model"], api_surface)
        return _tag_response_transport_engine(
            self._load_litellm().completion(**payload),
            "litellm",
        )

    def create_router(self, model_list: List[Dict[str, Any]], **kwargs: Any) -> Any:
        module = self._load_litellm()
        router_cls = getattr(module, "Router", None)
        if router_cls is None:
            router_cls = importlib.import_module("litellm").Router
        sanitized_list: List[Dict[str, Any]] = []
        changed = False
        for entry in model_list:
            if isinstance(entry, dict):
                params = entry.get("litellm_params")
                model_info = entry.get("model_info")
                if isinstance(params, dict):
                    effective_surface = (
                        model_info.get("dsa_api_surface")
                        if isinstance(model_info, Mapping)
                        else None
                    ) or params.get("api_surface")
                    has_internal_keys = any(
                        k in {"api_surface", "wire_protocol", "dsa_channel_protocol"} or str(k).startswith("_dsa_")
                        for k in params
                    )
                    raw_wire_model = params.get("model") or entry.get("model_name")
                    try:
                        encoded_wire_model = _encode_litellm_responses_wire_model(
                            raw_wire_model,
                            effective_surface,
                        )
                    except ValueError as exc:
                        logger.warning(
                            "Skipping Responses wire-model encoding for router entry %r: %s",
                            raw_wire_model,
                            exc,
                        )
                        encoded_wire_model = raw_wire_model
                    if has_internal_keys or encoded_wire_model != params.get("model"):
                        copied_params = _strip_internal_litellm_kwargs(params)
                        copied_params.pop("api_surface", None)
                        if encoded_wire_model:
                            copied_params["model"] = encoded_wire_model
                        copied_entry = dict(entry)
                        copied_entry["litellm_params"] = copied_params
                        sanitized_list.append(copied_entry)
                        changed = True
                        continue
            sanitized_list.append(entry)
        return router_cls(model_list=sanitized_list if changed else model_list, **kwargs)

    def can_register_model(self) -> bool:
        try:
            module = self._load_litellm()
        except Exception:
            return False
        return callable(getattr(module, "register_model", None))

    def _register_model_sdk_only(self, model_cost: Mapping[str, Any]) -> None:
        register = getattr(self._load_litellm(), "register_model", None)
        if callable(register):
            register(dict(model_cost))

    def register_model(self, model_cost: Mapping[str, Any]) -> None:
        with _SHARED_MODEL_COSTS_LOCK:
            _SHARED_MODEL_COSTS.update(dict(model_cost))
        self._register_model_sdk_only(model_cost)

    def get_model_cost(self) -> Dict[str, Any]:
        try:
            module = self._load_litellm()
        except Exception:
            with _SHARED_MODEL_COSTS_LOCK:
                return dict(_SHARED_MODEL_COSTS)
        cost_map = getattr(module, "model_cost", {})
        if isinstance(cost_map, dict):
            return cost_map
        return {}

    def estimate_tokens(self, text: str, *, model: Optional[str] = None) -> int:
        normalized_text = str(text or "")
        if not normalized_text:
            return 0
        try:
            count = self._load_litellm().token_counter(model=model, text=normalized_text)
            parsed = int(count or 0)
            if parsed > 0:
                return parsed
            logger.debug(
                "Token counter returned non-positive count for non-empty text; using CJK-aware heuristic"
            )
            return estimate_tokens_fallback(normalized_text)
        except Exception as exc:
            logger.debug("Token counter failed; using CJK-aware character heuristic: %s", exc)
            return estimate_tokens_fallback(normalized_text)

    def get_model_providers(self) -> frozenset[str]:
        # R9 / P2: Transport-mode-independent canonical LiteLLM provider registry
        # matching litellm.types.utils.LlmProviders without importing litellm.
        return CANONICAL_LITELLM_PROVIDERS

    def disable_streaming_logging(self) -> None:
        _apply_disable_streaming_logging(sys.modules.get("litellm"))

    def silence_logs(self) -> None:
        os.environ.setdefault("LITELLM_LOG", "ERROR")
        try:
            module = self._load_litellm()
            for attr, value in (
                ("set_verbose", False),
                ("suppress_debug_info", True),
                ("disable_streaming_logging", True),
            ):
                try:
                    setattr(module, attr, value)
                except Exception:
                    pass
        except Exception:
            pass
        for logger_name in ("LiteLLM", "litellm"):
            logging.getLogger(logger_name).setLevel(logging.WARNING)

    def resolve_exception(self, name: str) -> type[BaseException]:
        try:
            module = self._load_litellm()
        except Exception:
            return _build_synthetic_exception(name)
        exc = getattr(module, name, None)
        if isinstance(exc, type) and issubclass(exc, BaseException):
            return exc
        return _build_synthetic_exception(name)


# ============================================================
# Phase 2: Native 4-Protocol HTTPX + SSE Router & Transport
# ============================================================


def _prepare_protocol_request(
    entry: DeploymentSpec,
    messages: List[Dict[str, Any]],
    stream: bool,
    kwargs: Mapping[str, Any],
    *,
    default_timeout: float = 120.0,
) -> PreparedRequest:
    if entry.protocol == "anthropic":
        from src.llm.anthropic_transport import prepare_anthropic_request

        return prepare_anthropic_request(
            entry, messages, stream, kwargs, default_timeout=default_timeout
        )
    if entry.protocol == "gemini":
        from src.llm.gemini_transport import prepare_gemini_request

        return prepare_gemini_request(
            entry, messages, stream, kwargs, default_timeout=default_timeout
        )
    from src.llm.openai_transport import prepare_openai_request

    return prepare_openai_request(
        entry, messages, stream, kwargs, default_timeout=default_timeout
    )


def _parse_protocol_response(
    entry: DeploymentSpec,
    payload: Mapping[str, Any],
    secrets: Iterable[str] = (),
) -> NativeCompletionResponse:
    if entry.protocol == "anthropic":
        from src.llm.anthropic_transport import parse_anthropic_response

        return parse_anthropic_response(
            payload,
            default_model=entry.wire_model,
            provider=entry.provider or "anthropic",
            secrets=secrets,
        )
    if entry.protocol == "gemini":
        from src.llm.gemini_transport import parse_gemini_response

        return parse_gemini_response(
            payload,
            default_model=entry.wire_model,
            provider=entry.provider or "gemini",
            secrets=secrets,
        )
    from src.llm.openai_transport import parse_openai_response

    return parse_openai_response(entry, payload, secrets=secrets)


def _iter_protocol_stream_chunks(
    entry: DeploymentSpec,
    byte_chunks: Iterable[bytes],
    secrets: Iterable[str] = (),
    cancel_check: Optional[Callable[[], None]] = None,
) -> Iterator[NativeStreamChunk]:
    if entry.protocol == "anthropic":
        from src.llm.anthropic_transport import iter_anthropic_stream_chunks

        return iter_anthropic_stream_chunks(
            byte_chunks,
            default_model=entry.wire_model,
            provider=entry.provider or "anthropic",
            secrets=secrets,
            cancel_check=cancel_check,
        )
    if entry.protocol == "gemini":
        from src.llm.gemini_transport import iter_gemini_stream_chunks

        return iter_gemini_stream_chunks(
            byte_chunks,
            default_model=entry.wire_model,
            provider=entry.provider or "gemini",
            secrets=secrets,
            cancel_check=cancel_check,
        )
    from src.llm.openai_transport import iter_openai_stream_chunks

    return iter_openai_stream_chunks(
        entry,
        byte_chunks,
        secrets=secrets,
        cancel_check=cancel_check,
    )


class NativeUnifiedRouter:
    """Pooled 4-protocol router with R6 exact alias matching and R7 per-alias hybrid routing."""

    _dsa_accepts_transport_metadata = True

    def __init__(
        self,
        model_list: Optional[List[Dict[str, Any]]] = None,
        *,
        pool: Optional[DeploymentPool] = None,
        fallback_transport: Optional[LLMTransport] = None,
        http_transport: Optional[Any] = None,
        timeout: float = 120.0,
        num_retries: int = 2,
        cooldown_time: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        now_wall: Optional[Callable[[], float]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
        routing_strategy: Optional[str] = None,
        allowed_fails: Optional[int] = None,
        **_extra_kwargs: Any,
    ) -> None:
        self.model_list: List[Dict[str, Any]] = list(model_list or [])
        self._fallback_transport = fallback_transport
        self._http_transport = http_transport
        self._timeout = float(timeout)
        self._num_retries = max(0, int(num_retries))
        self._cooldown_time = max(1.0, float(cooldown_time))
        self._clock = clock
        self._now_wall = now_wall
        self._sleep_fn = sleep_fn
        self._router_kwargs: Dict[str, Any] = {
            "num_retries": self._num_retries,
        }
        if routing_strategy is not None:
            self._router_kwargs["routing_strategy"] = routing_strategy
        if allowed_fails is not None:
            self._router_kwargs["allowed_fails"] = allowed_fails
        self._router_kwargs.update(_extra_kwargs)

        self._fallback_entries_by_alias: Dict[str, List[Dict[str, Any]]] = {}
        self._fallback_router: Optional[Any] = None
        self._fallback_router_lock = threading.Lock()
        self._deployment_clients: Dict[str, Any] = {}
        self._populated = False

        if pool is not None:
            self._pool = pool
            self._populated = bool(pool.deployments)
        else:
            native_specs: List[DeploymentSpec] = []
            # Group entries by exact alias so R7 hybrid routing decides per alias group.
            grouped: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
            for idx, raw_entry in enumerate(self.model_list):
                if not isinstance(raw_entry, Mapping):
                    continue
                entry_dict = dict(raw_entry)
                raw_params = entry_dict.get("litellm_params")
                params = raw_params if isinstance(raw_params, Mapping) else {}
                alias = str(entry_dict.get("model_name") or params.get("model") or "").strip()
                if not alias:
                    continue
                grouped.setdefault(alias, []).append((idx, entry_dict))

            self._populated = bool(grouped)

            for alias, indexed_entries in grouped.items():
                resolved_group: List[DeploymentSpec] = []
                group_clients: Dict[str, Any] = {}
                first_unsupported: Optional[Unsupported] = None
                hard_config_error: Optional[Unsupported] = None
                # F1: Scan ALL entries in the alias group so hard config errors never hide
                # behind an earlier delegatable Unsupported entry.
                for idx, entry_dict in indexed_entries:
                    res = resolve_deployment(
                        entry_dict,
                        deployment_id=f"{alias}:{idx}",
                        alias=alias,
                    )
                    if isinstance(res, Unsupported):
                        if first_unsupported is None:
                            first_unsupported = res
                        if res.reason in _HARD_CONFIG_ERROR_REASONS and hard_config_error is None:
                            hard_config_error = res
                        continue
                    resolved_group.append(res)
                    raw_params = entry_dict.get("litellm_params")
                    if isinstance(raw_params, Mapping):
                        _, dep_client_base, dep_http = extract_client_overrides(raw_params)
                        if dep_http is not None:
                            # P0-3b: Only bind deployment client when its base origin matches res.api_base.
                            dep_origin = url_origin(dep_client_base) if dep_client_base else None
                            res_origin = url_origin(res.api_base)
                            if dep_origin is None or (res_origin is not None and dep_origin == res_origin):
                                group_clients[res.deployment_id] = dep_http

                if hard_config_error is not None:
                    # F1 & P1-5: Hard deployment config errors fail closed in BOTH native and auto modes.
                    raise NativeConfigError(
                        f"Alias '{alias}' cannot run in native transport: {hard_config_error.detail}",
                        status_code=400,
                        provider=hard_config_error.provider,
                        error_code=hard_config_error.reason,
                    )
                if first_unsupported is not None:
                    if self._fallback_transport is not None:
                        self._fallback_entries_by_alias[alias] = [e for _, e in indexed_entries]
                    else:
                        raise NativeConfigError(
                            f"Alias '{alias}' cannot run in native transport: {first_unsupported.detail}",
                            status_code=400,
                            provider=first_unsupported.provider,
                            error_code=first_unsupported.reason,
                        )
                else:
                    native_specs.extend(resolved_group)
                    self._deployment_clients.update(group_clients)

            self._pool = DeploymentPool(
                native_specs,
                clock=clock,
                base_cooldown_seconds=self._cooldown_time,
            )

    @property
    def pool(self) -> DeploymentPool:
        """Expose underlying :class:`DeploymentPool`."""
        return self._pool

    @property
    def fallback_aliases(self) -> frozenset[str]:
        """Return exact aliases delegated to the fallback transport in ``auto`` mode."""
        return frozenset(self._fallback_entries_by_alias.keys())

    def _get_or_create_fallback_router(self) -> Any:
        with self._fallback_router_lock:
            if self._fallback_router is not None:
                return self._fallback_router
            if self._fallback_transport is None:
                raise NativeConfigError(
                    "Fallback transport is unavailable in strict native mode",
                    status_code=400,
                )
            _sync_shared_pricing_to_transport(self._fallback_transport)
            all_fallback_entries: List[Dict[str, Any]] = []
            for entries in self._fallback_entries_by_alias.values():
                all_fallback_entries.extend(entries)
            self._fallback_router = self._fallback_transport.create_router(
                all_fallback_entries,
                **self._router_kwargs,
            )
            return self._fallback_router

    def _prepare_request(
        self,
        entry: DeploymentSpec,
        messages: List[Dict[str, Any]],
        stream: bool,
        kwargs: Mapping[str, Any],
    ) -> PreparedRequest:
        return _prepare_protocol_request(
            entry,
            messages,
            stream,
            kwargs,
            default_timeout=self._timeout,
        )

    def completion(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Execute pooled completion with R6 exact alias matching and R7 per-alias delegation."""
        req_kwargs = dict(kwargs)
        raw_retries = req_kwargs.pop("num_retries", self._num_retries)
        effective_retries = max(0, int(raw_retries if raw_retries is not None else self._num_retries))
        _, caller_client_base, caller_http = extract_client_overrides(req_kwargs)
        caller_client_origin = url_origin(caller_client_base) if caller_client_base else None
        raw_caller_base = (
            resolve_env_reference(req_kwargs.get("base_url"))
            or resolve_env_reference(req_kwargs.get("api_base"))
            or caller_client_base
        )
        caller_header_origin = url_origin(str(raw_caller_base)) if raw_caller_base else None
        target_alias = str(model or "").strip()

        if self._populated:
            if self._pool.has_alias(target_alias):
                # P1-3: Peek without advancing round-robin cursor; engine advances once on attempt 0.
                candidates = self._pool.peek_candidates(target_alias)
                using_pool = True
            elif target_alias in self._fallback_entries_by_alias:
                _sync_shared_pricing_to_transport(self._fallback_transport)
                fallback_router = self._get_or_create_fallback_router()
                return _tag_response_transport_engine(
                    dispatch_completion(
                        router=fallback_router,
                        model=target_alias,
                        messages=messages,
                        stream=stream,
                        num_retries=effective_retries,
                        **req_kwargs,
                    ),
                    "litellm",
                )
            else:
                # R6: Never silently create an ephemeral entry on a populated router miss.
                raise NativeBadRequestError(
                    f"Model alias '{target_alias}' is not registered in NativeUnifiedRouter",
                    status_code=400,
                    provider="openai",
                    error_code="unknown_router_alias",
                )
        else:
            resolved = resolve_deployment(
                target_alias,
                deployment_id=f"direct:{target_alias}",
                alias=target_alias,
                params=req_kwargs,
            )
            if isinstance(resolved, Unsupported):
                if (
                    self._fallback_transport is not None
                    and resolved.reason not in _HARD_CONFIG_ERROR_REASONS
                ):
                    _sync_shared_pricing_to_transport(self._fallback_transport)
                    return _tag_response_transport_engine(
                        self._fallback_transport.completion(
                            model=target_alias,
                            messages=messages,
                            stream=stream,
                            num_retries=effective_retries,
                            **req_kwargs,
                        ),
                        "litellm",
                    )
                raise NativeConfigError(
                    resolved.detail,
                    status_code=400,
                    provider=resolved.provider,
                    error_code=resolved.reason,
                )
            candidates = [resolved]
            using_pool = False

        if stream:
            return stream_pooled_completion(
                candidates=candidates,
                pool=self._pool,
                using_pool=using_pool,
                messages=messages,
                kwargs=req_kwargs,
                prepare_request_fn=self._prepare_request,
                iter_stream_fn=_iter_protocol_stream_chunks,
                http_transport=self._http_transport,
                http_client=caller_http,
                deployment_clients=self._deployment_clients,
                caller_client_origin=caller_client_origin,
                caller_header_origin=caller_header_origin,
                request_model=target_alias,
                num_retries=effective_retries,
                default_timeout=self._timeout,
                clock=self._clock,
                now_wall=self._now_wall,
                sleep_fn=self._sleep_fn,
                cancel_check=raise_if_stock_cancelled,
            )

        return execute_pooled_completion(
            candidates=candidates,
            pool=self._pool,
            using_pool=using_pool,
            messages=messages,
            kwargs=req_kwargs,
            prepare_request_fn=self._prepare_request,
            parse_response_fn=_parse_protocol_response,
            http_transport=self._http_transport,
            http_client=caller_http,
            deployment_clients=self._deployment_clients,
            caller_client_origin=caller_client_origin,
            caller_header_origin=caller_header_origin,
            request_model=target_alias,
            num_retries=effective_retries,
            default_timeout=self._timeout,
            clock=self._clock,
            now_wall=self._now_wall,
            sleep_fn=self._sleep_fn,
            cancel_check=raise_if_stock_cancelled,
        )


class NativeUnifiedTransport:
    """Unified 4-protocol native ``httpx`` transport implementing ``LLMTransport``."""

    transport_engine: str = "native"

    def __init__(
        self,
        *,
        http_transport: Optional[Any] = None,
        fallback_transport: Optional[LLMTransport] = None,
        clock: Callable[[], float] = time.monotonic,
        now_wall: Optional[Callable[[], float]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
        default_timeout: float = 120.0,
    ) -> None:
        self._http_transport = http_transport
        self._fallback_transport = fallback_transport
        self._clock = clock
        self._now_wall = now_wall
        self._sleep_fn = sleep_fn
        self._default_timeout = float(default_timeout)

    def completion(self, **kwargs: Any) -> Any:
        """Dispatch single completion via native HTTPX or ``fallback_transport`` (in ``auto``)."""
        model = str(kwargs.get("model") or "").strip()
        resolved = resolve_deployment(model, deployment_id=f"direct:{model}", alias=model, params=kwargs)

        if isinstance(resolved, Unsupported):
            if (
                self._fallback_transport is not None
                and resolved.reason not in _HARD_CONFIG_ERROR_REASONS
            ):
                _sync_shared_pricing_to_transport(self._fallback_transport)
                return _tag_response_transport_engine(
                    self._fallback_transport.completion(**kwargs),
                    "litellm",
                )
            raise NativeConfigError(
                resolved.detail,
                status_code=400,
                provider=resolved.provider,
                error_code=resolved.reason,
            )

        call_kwargs = dict(kwargs)
        raw_retries = call_kwargs.pop("num_retries", 0)
        effective_retries = max(0, int(raw_retries if raw_retries is not None else 0))
        messages = call_kwargs.pop("messages", [])
        stream = bool(call_kwargs.pop("stream", False))
        call_kwargs.pop("model", None)
        _, caller_client_base, caller_http = extract_client_overrides(call_kwargs)
        caller_client_origin = url_origin(caller_client_base) if caller_client_base else None
        raw_caller_base = (
            resolve_env_reference(call_kwargs.get("base_url"))
            or resolve_env_reference(call_kwargs.get("api_base"))
            or caller_client_base
        )
        caller_header_origin = url_origin(str(raw_caller_base)) if raw_caller_base else None

        def _prepare(
            entry: DeploymentSpec,
            msgs: List[Dict[str, Any]],
            is_stream: bool,
            kw: Mapping[str, Any],
        ) -> PreparedRequest:
            return _prepare_protocol_request(
                entry,
                msgs,
                is_stream,
                kw,
                default_timeout=self._default_timeout,
            )

        if stream:
            return stream_pooled_completion(
                candidates=[resolved],
                pool=None,
                using_pool=False,
                messages=messages,
                kwargs=call_kwargs,
                prepare_request_fn=_prepare,
                iter_stream_fn=_iter_protocol_stream_chunks,
                http_transport=self._http_transport,
                http_client=caller_http,
                caller_client_origin=caller_client_origin,
                caller_header_origin=caller_header_origin,
                request_model=model,
                num_retries=effective_retries,
                default_timeout=self._default_timeout,
                clock=self._clock,
                now_wall=self._now_wall,
                sleep_fn=self._sleep_fn,
                cancel_check=raise_if_stock_cancelled,
            )

        return execute_pooled_completion(
            candidates=[resolved],
            pool=None,
            using_pool=False,
            messages=messages,
            kwargs=call_kwargs,
            prepare_request_fn=_prepare,
            parse_response_fn=_parse_protocol_response,
            http_transport=self._http_transport,
            http_client=caller_http,
            caller_client_origin=caller_client_origin,
            caller_header_origin=caller_header_origin,
            request_model=model,
            num_retries=effective_retries,
            default_timeout=self._default_timeout,
            clock=self._clock,
            now_wall=self._now_wall,
            sleep_fn=self._sleep_fn,
            cancel_check=raise_if_stock_cancelled,
        )

    def create_router(self, model_list: List[Dict[str, Any]], **kwargs: Any) -> Any:
        """Create a pooled :class:`NativeUnifiedRouter` with per-alias hybrid routing in ``auto``."""
        router_kwargs = dict(kwargs)
        timeout = float(router_kwargs.pop("timeout", None) or self._default_timeout)
        num_retries = int(router_kwargs.pop("num_retries", 2))
        cooldown_time = float(router_kwargs.pop("cooldown_time", 30.0))
        return NativeUnifiedRouter(
            model_list=model_list,
            fallback_transport=self._fallback_transport,
            http_transport=self._http_transport,
            timeout=timeout,
            num_retries=num_retries,
            cooldown_time=cooldown_time,
            clock=self._clock,
            now_wall=self._now_wall,
            sleep_fn=self._sleep_fn,
            **router_kwargs,
        )

    def can_register_model(self) -> bool:
        return True

    def register_model(self, model_cost: Mapping[str, Any]) -> None:
        if isinstance(model_cost, Mapping):
            new_entries = dict(model_cost)
            with _SHARED_MODEL_COSTS_LOCK:
                _SHARED_MODEL_COSTS.update(new_entries)
            # P1-14: Propagate later registrations to any already-materialized fallback transports.
            for fb in list(_MATERIALIZED_FALLBACK_TRANSPORTS):
                _sync_shared_pricing_to_transport(fb, new_entries)
            if self._fallback_transport is not None and "litellm" in sys.modules:
                _sync_shared_pricing_to_transport(self._fallback_transport, new_entries)

    def get_model_cost(self) -> Dict[str, Any]:
        with _SHARED_MODEL_COSTS_LOCK:
            return dict(_SHARED_MODEL_COSTS)

    def estimate_tokens(self, text: str, *, model: Optional[str] = None) -> int:
        del model
        return estimate_tokens_fallback(text)

    def get_model_providers(self) -> frozenset[str]:
        # R9: Static canonical LiteLLM provider registry, identical across transport modes
        # and free of org prefixes (qwen/glm/zhipu/ark/siliconflow/google/claude).
        return CANONICAL_LITELLM_PROVIDERS

    def disable_streaming_logging(self) -> None:
        return None

    def silence_logs(self) -> None:
        return None

    def resolve_exception(self, name: str) -> type[BaseException]:
        if name in _NATIVE_EXCEPTION_MAP:
            return _NATIVE_EXCEPTION_MAP[name]
        if self._fallback_transport is not None and "litellm" in sys.modules:
            return self._fallback_transport.resolve_exception(name)
        return NativeAPIError


def create_native_transport(
    *,
    http_transport: Optional[Any] = None,
    fallback_transport: Optional[LLMTransport] = None,
    fallback_to_litellm: bool = True,
    clock: Callable[[], float] = time.monotonic,
    now_wall: Optional[Callable[[], float]] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
    default_timeout: float = 120.0,
) -> LLMTransport:
    """Create the unified 4-protocol native HTTPX transport (OpenAI/Anthropic/Gemini)."""
    resolved_fallback = fallback_transport
    if resolved_fallback is None and fallback_to_litellm:
        resolved_fallback = LiteLLMTransport()
    return NativeUnifiedTransport(
        http_transport=http_transport,
        fallback_transport=resolved_fallback,
        clock=clock,
        now_wall=now_wall,
        sleep_fn=sleep_fn,
        default_timeout=default_timeout,
    )


# ============================================================
# Mode Resolution, Transport Registry & Lifecycle Cache
# ============================================================

_ACTIVE_TRANSPORT: ContextVar[Optional[LLMTransport]] = ContextVar(
    "dsa_active_llm_transport",
    default=None,
)
_DEFAULT_TRANSPORT: Optional[LLMTransport] = None
_CACHED_TRANSPORTS: Dict[str, LLMTransport] = {}


def resolve_llm_transport_mode(
    raw: Optional[str] = None,
    *,
    config: Optional[Any] = None,
) -> str:
    """Single source of truth resolving ``LLM_TRANSPORT_MODE`` -> ``litellm`` | ``auto`` | ``native``."""
    candidate: Optional[str] = raw
    if candidate is None:
        env_val = os.getenv("LLM_TRANSPORT_MODE")
        if env_val is not None and env_val.strip():
            candidate = env_val
        elif config is not None:
            cfg_mode = getattr(config, "llm_transport_mode", None)
            if cfg_mode is not None and str(cfg_mode).strip():
                candidate = str(cfg_mode)

    cleaned = str(candidate or "").strip().lower()
    if not cleaned or cleaned == "litellm":
        return "litellm"
    if cleaned in {"auto", "native_httpx", "hybrid"}:
        return "auto"
    if cleaned in {"native", "native_only", "httpx"}:
        return "native"
    logger.warning(
        "[LLMTransport] Unsupported LLM_TRANSPORT_MODE=%r; falling back to 'litellm'",
        candidate,
    )
    return "litellm"


def _get_transport_for_mode(mode: str) -> LLMTransport:
    cached = _CACHED_TRANSPORTS.get(mode)
    if cached is not None:
        return cached
    if mode == "native":
        instance: LLMTransport = create_native_transport(fallback_to_litellm=False)
    elif mode == "auto":
        instance = create_native_transport(fallback_to_litellm=True)
    else:
        instance = LiteLLMTransport()
    _CACHED_TRANSPORTS[mode] = instance
    return instance


def get_transport_override() -> Optional[LLMTransport]:
    """Return the active context-scoped transport override, if installed."""
    return _ACTIVE_TRANSPORT.get()


def set_default_transport(transport: Optional[LLMTransport]) -> None:
    """Override the process-wide default LLM transport (pass ``None`` to clear)."""
    global _DEFAULT_TRANSPORT
    _DEFAULT_TRANSPORT = transport
    reset_transport_cache()


def reset_transport_cache() -> None:
    """Close pooled HTTPX clients and clear cached transports, provider, and pricing caches."""
    close_pooled_clients()
    _CACHED_TRANSPORTS.clear()
    _MATERIALIZED_FALLBACK_TRANSPORTS.clear()
    with _SHARED_MODEL_COSTS_LOCK:
        _SHARED_MODEL_COSTS.clear()
    config_mod = sys.modules.get("src.config")
    if config_mod is not None:
        provider_getter = getattr(config_mod, "get_litellm_model_providers", None)
        cache_clear = getattr(provider_getter, "cache_clear", None)
        if callable(cache_clear):
            cache_clear()
    adapter_mod = sys.modules.get("src.agent.llm_adapter")
    if adapter_mod is not None:
        registered = getattr(adapter_mod, "_FALLBACK_MODEL_PRICING_REGISTERED", None)
        if isinstance(registered, set):
            registered.clear()


def get_transport_for_config(config: Optional[Any] = None) -> LLMTransport:
    """Return active override, process-wide default, or mode-resolved transport for ``config``."""
    active = _ACTIVE_TRANSPORT.get()
    if active is not None:
        return active
    if _DEFAULT_TRANSPORT is not None:
        return _DEFAULT_TRANSPORT
    mode = resolve_llm_transport_mode(config=config)
    return _get_transport_for_mode(mode)


def get_transport() -> LLMTransport:
    """Return the active context-scoped, process-wide, or mode-resolved transport."""
    return get_transport_for_config(None)


def is_native_transport_active(config: Optional[Any] = None) -> bool:
    """Return True when the effective transport executes via native HTTPX instead of LiteLLM."""
    return isinstance(get_transport_for_config(config), NativeUnifiedTransport)


def get_transport_engine_label(
    response: Optional[Any] = None,
    *,
    transport: Optional[LLMTransport] = None,
    config: Optional[Any] = None,
) -> str:
    """Return the actual transport engine label (``native`` or ``litellm``) for telemetry/audit."""
    if response is not None:
        hidden = getattr(response, "_hidden_params", None)
        if isinstance(hidden, Mapping):
            engine = str(hidden.get("transport_engine") or "").strip().lower()
            if engine in {"native", "litellm"}:
                return engine
        direct_engine = str(getattr(response, "transport_engine", "") or "").strip().lower()
        if direct_engine in {"native", "litellm"}:
            return direct_engine
    active = transport or get_transport_for_config(config)
    engine_attr = str(getattr(active, "transport_engine", "") or "").strip().lower()
    if engine_attr in {"native", "litellm"}:
        return engine_attr
    return "native" if isinstance(active, NativeUnifiedTransport) else "litellm"


@contextmanager
def use_transport(transport: Optional[LLMTransport]) -> Iterator[Optional[LLMTransport]]:
    """Temporarily bind ``transport`` for the current thread/async context."""
    token = _ACTIVE_TRANSPORT.set(transport)
    try:
        yield transport
    finally:
        _ACTIVE_TRANSPORT.reset(token)


def dispatch_completion(
    *,
    router: Optional[Any] = None,
    compat_proxy: Optional[Any] = None,
    transport: Optional[LLMTransport] = None,
    config: Optional[Any] = None,
    **kwargs: Any,
) -> Any:
    """Dispatch a completion call through a router, active transport, or legacy mock."""
    if router is not None:
        if not getattr(router, "_dsa_accepts_transport_metadata", False):
            if "api_surface" in kwargs or "wire_protocol" in kwargs:
                _validate_prebuilt_router_api_surface(
                    router,
                    kwargs.get("model"),
                    kwargs.get("api_surface"),
                )
            router_kwargs = _strip_internal_litellm_kwargs(kwargs)
            router_kwargs.pop("api_surface", None)
            return router.completion(**router_kwargs)
        return router.completion(**kwargs)
    if transport is not None:
        return transport.completion(**kwargs)
    override = get_transport_override()
    if override is not None:
        return override.completion(**kwargs)
    patched_completion = (
        getattr(compat_proxy, "completion", None) if compat_proxy is not None else None
    )
    if callable(patched_completion):
        return patched_completion(**kwargs)
    return get_transport_for_config(config).completion(**kwargs)


def create_router(
    model_list: List[Dict[str, Any]],
    *,
    router_factory: Optional[Any] = None,
    transport: Optional[LLMTransport] = None,
    config: Optional[Any] = None,
    **kwargs: Any,
) -> Any:
    """Create a multi-deployment router through the active transport or legacy patch."""
    if transport is not None:
        return transport.create_router(model_list, **kwargs)
    override = get_transport_override()
    if override is not None:
        return override.create_router(model_list, **kwargs)
    if router_factory is not None and callable(router_factory):
        return router_factory(model_list=model_list, **kwargs)
    return get_transport_for_config(config).create_router(model_list, **kwargs)


def can_register_model(*, compat_proxy: Optional[Any] = None) -> bool:
    """Return whether dynamic model pricing registration is available."""
    override = get_transport_override()
    if override is not None:
        return override.can_register_model()
    if compat_proxy is not None and callable(getattr(compat_proxy, "register_model", None)):
        return True
    return get_transport().can_register_model()


def register_model(
    model_cost: Mapping[str, Any],
    *,
    compat_proxy: Optional[Any] = None,
) -> None:
    """Register dynamic model pricing metadata via the active transport or compat patch."""
    override = get_transport_override()
    if override is not None:
        override.register_model(dict(model_cost))
        return
    patched_register = (
        getattr(compat_proxy, "register_model", None) if compat_proxy is not None else None
    )
    if callable(patched_register):
        patched_register(dict(model_cost))
        return
    get_transport().register_model(dict(model_cost))


def get_model_cost(*, compat_proxy: Optional[Any] = None) -> Dict[str, Any]:
    """Return the active model cost registry via the active transport or compat patch."""
    override = get_transport_override()
    if override is not None:
        return override.get_model_cost()
    if compat_proxy is not None:
        patched_cost_map = getattr(compat_proxy, "model_cost", None)
        if isinstance(patched_cost_map, dict):
            return patched_cost_map
    return get_transport().get_model_cost()


def estimate_tokens(
    text: str,
    *,
    model: Optional[str] = None,
    transport: Optional[LLMTransport] = None,
) -> int:
    """Estimate tokens for ``text`` through the active transport with CJK-aware fallback."""
    normalized_text = str(text or "")
    if not normalized_text:
        return 0
    active = transport or get_transport()
    try:
        parsed = int(active.estimate_tokens(normalized_text, model=model) or 0)
        if parsed > 0:
            return parsed
        return estimate_tokens_fallback(normalized_text)
    except Exception as exc:
        logger.debug("Transport estimate_tokens failed; using CJK-aware heuristic: %s", exc)
        return estimate_tokens_fallback(normalized_text)


def get_model_providers(*, transport: Optional[LLMTransport] = None) -> frozenset[str]:
    """Return provider routing prefixes exposed by the active transport."""
    active = transport or get_transport()
    return active.get_model_providers()


def silence_litellm_logs(*, transport: Optional[LLMTransport] = None) -> None:
    """Suppress verbose transport logs through the active transport."""
    active = transport or get_transport()
    active.silence_logs()


def resolve_exception_types(
    name: str,
    *,
    compat_proxy: Optional[Any] = None,
) -> Tuple[type[BaseException], ...]:
    """Return all catchable exception classes for ``name`` across active and compat transports."""
    classes: List[type[BaseException]] = []

    def _add(candidate: Any) -> None:
        if (
            isinstance(candidate, type)
            and issubclass(candidate, BaseException)
            and candidate not in classes
        ):
            classes.append(candidate)

    override = get_transport_override()
    if override is not None:
        _add(override.resolve_exception(name))

    if compat_proxy is not None:
        _add(getattr(compat_proxy, name, None))

    active = get_transport()
    if override is None:
        _add(active.resolve_exception(name))

    # Always include native exception mapping when active transport is native/auto.
    if isinstance(active, NativeUnifiedTransport) and name in _NATIVE_EXCEPTION_MAP:
        _add(_NATIVE_EXCEPTION_MAP[name])

    loaded_litellm = sys.modules.get("litellm")
    if loaded_litellm is not None and not isinstance(active, LiteLLMTransport):
        _add(getattr(loaded_litellm, name, None))

    if not classes:
        _add(_NATIVE_EXCEPTION_MAP.get(name) or _build_synthetic_exception(name))

    return tuple(classes)
