# -*- coding: utf-8 -*-
"""Unified LLM transport boundary decoupling callers from LiteLLM and native 4-protocol HTTPX backends."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import importlib
import logging
import os
import sys
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Protocol, Tuple, runtime_checkable

from src.core.stock_execution_context import raise_if_stock_cancelled
from src.llm.native_types import (
    NATIVE_ANTHROPIC_PROVIDERS,
    NATIVE_GEMINI_PROVIDERS,
    NATIVE_OPENAI_PROVIDERS,
    NativeAPIError,
    NativeAuthenticationError,
    NativeBadRequestError,
    NativeCompletionResponse,
    NativeContextWindowExceededError,
    NativeRateLimitError,
    NativeStreamChunk,
    PreparedRequest,
    execute_pooled_completion,
    extract_client_overrides,
    merge_header_overrides,
    resolve_default_api_base,
    resolve_native_protocol,
    stream_pooled_completion,
    strip_provider_prefix,
)
from src.llm.pool import DeploymentEntry, DeploymentPool

logger = logging.getLogger(__name__)

SUPPORTED_LLM_TRANSPORT_MODES: frozenset[str] = frozenset({"litellm", "auto", "native"})

NATIVE_ALL_PROVIDERS: frozenset[str] = (
    NATIVE_OPENAI_PROVIDERS | NATIVE_ANTHROPIC_PROVIDERS | NATIVE_GEMINI_PROVIDERS
)

_NATIVE_EXCEPTION_MAP: Dict[str, type[BaseException]] = {
    "RateLimitError": NativeRateLimitError,
    "ContextWindowExceededError": NativeContextWindowExceededError,
    "AuthenticationError": NativeAuthenticationError,
    "BadRequestError": NativeBadRequestError,
    "APIError": NativeAPIError,
}


def _apply_disable_streaming_logging(module: Any) -> None:
    """Keep LiteLLM per-chunk async streaming logging disabled (issue #2524)."""
    if module is None:
        return
    try:
        setattr(module, "disable_streaming_logging", True)
    except (AttributeError, TypeError):
        pass


@runtime_checkable
class LLMTransport(Protocol):
    """Internal transport contract consumed by analyzer, agent, extractor, ranker, and config."""

    def completion(self, **kwargs: Any) -> Any: ...

    def create_router(self, model_list: List[Dict[str, Any]], **kwargs: Any) -> Any: ...

    def register_model(self, model_cost: Dict[str, Any]) -> None: ...

    def get_model_cost(self) -> Dict[str, Any]: ...

    def can_register_model(self) -> bool: ...

    def token_counter(self, *, model: str, text: str) -> int: ...

    def get_model_providers(self) -> frozenset[str]: ...

    def disable_streaming_logging(self) -> None: ...

    def silence_logs(self) -> None: ...

    def resolve_exception(self, name: str) -> type[BaseException]: ...


class LiteLLMPatchProxy:
    """Lazy patch surface preserving legacy ``module.litellm.<attr>`` test mocks."""

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


class LiteLLMTransport:
    """Default transport backed lazily by LiteLLM and ``sys.modules['litellm']`` stubs."""

    @staticmethod
    def _load_litellm() -> Any:
        module = sys.modules.get("litellm")
        if module is None:
            module = importlib.import_module("litellm")
        _apply_disable_streaming_logging(module)
        return module

    def completion(self, **kwargs: Any) -> Any:
        return self._load_litellm().completion(**kwargs)

    def create_router(self, model_list: List[Dict[str, Any]], **kwargs: Any) -> Any:
        module = self._load_litellm()
        router_cls = getattr(module, "Router", None)
        if router_cls is None:
            from litellm import Router as router_cls
        return router_cls(model_list=model_list, **kwargs)

    def can_register_model(self) -> bool:
        return callable(getattr(self._load_litellm(), "register_model", None))

    def register_model(self, model_cost: Dict[str, Any]) -> None:
        register = getattr(self._load_litellm(), "register_model", None)
        if callable(register):
            register(model_cost)

    def get_model_cost(self) -> Dict[str, Any]:
        cost_map = getattr(self._load_litellm(), "model_cost", {})
        return cost_map if isinstance(cost_map, dict) else {}

    def token_counter(self, *, model: str, text: str) -> int:
        count = self._load_litellm().token_counter(model=model, text=text)
        return max(0, int(count or 0))

    def get_model_providers(self) -> frozenset[str]:
        providers: set[str] = set()
        had_litellm = "litellm" in sys.modules
        prev_cost_map_env = os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP")
        if not had_litellm and prev_cost_map_env is None:
            # Prevent litellm.__init__ from fetching GitHub's model_prices JSON
            # during offline config/doctor initialization.
            os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
        try:
            from litellm.types.utils import LlmProviders

            providers.update(
                str(provider.value).strip().lower()
                for provider in LlmProviders
                if str(getattr(provider, "value", "")).strip()
            )
        except (ImportError, AttributeError, TypeError):
            pass
        finally:
            if not had_litellm and prev_cost_map_env is None:
                os.environ.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
            if "litellm" in sys.modules:
                _apply_disable_streaming_logging(sys.modules.get("litellm"))
        return frozenset(providers)

    def disable_streaming_logging(self) -> None:
        module = sys.modules.get("litellm")
        if module is not None:
            _apply_disable_streaming_logging(module)

    def silence_logs(self) -> None:
        os.environ.setdefault("LITELLM_LOG", "ERROR")
        try:
            module = self._load_litellm()
            setattr(module, "set_verbose", False)
            setattr(module, "suppress_debug_info", True)
        except Exception:
            pass
        for logger_name in ("LiteLLM", "litellm"):
            logging.getLogger(logger_name).setLevel(logging.WARNING)

    def resolve_exception(self, name: str) -> type[BaseException]:
        exc = getattr(self._load_litellm(), name, None)
        if isinstance(exc, type) and issubclass(exc, BaseException):
            return exc
        return _build_synthetic_exception(name)


def _build_synthetic_exception(name: str) -> type[BaseException]:
    class _FallbackLiteLLMError(Exception):
        pass

    _FallbackLiteLLMError.__name__ = f"Fallback{name}"
    return _FallbackLiteLLMError


def supports_native_protocol(
    model: str,
    *,
    api_base: Optional[str] = None,
    custom_llm_provider: Optional[str] = None,
    wire_protocol: Optional[str] = None,
) -> bool:
    """Return True when target is handled natively across OpenAI/Anthropic/Gemini."""
    return (
        resolve_native_protocol(
            model,
            api_base=api_base,
            custom_llm_provider=custom_llm_provider,
            wire_protocol=wire_protocol,
        )
        is not None
    )


class NativeUnifiedRouter:
    """Pooled 4-protocol router spanning OpenAI Chat, OpenAI Responses, Anthropic, and Gemini."""

    def __init__(
        self,
        model_list: Optional[List[Dict[str, Any]]] = None,
        *,
        pool: Optional[DeploymentPool] = None,
        http_transport: Optional[Any] = None,
        timeout: float = 120.0,
        num_retries: int = 2,
        cooldown_time: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Optional[Callable[[float], None]] = None,
        routing_strategy: Optional[str] = None,
        allowed_fails: Optional[int] = None,
        **_extra_kwargs: Any,
    ) -> None:
        del routing_strategy, allowed_fails, _extra_kwargs
        self.model_list: List[Dict[str, Any]] = list(model_list or [])
        self._http_transport = http_transport
        self._timeout = float(timeout)
        self._num_retries = max(0, int(num_retries))
        self._sleep_fn = sleep_fn
        if pool is not None:
            self._pool = pool
        else:
            entries = self._entries_from_model_list(self.model_list)
            self._pool = DeploymentPool(
                entries,
                clock=clock,
                base_cooldown_seconds=max(1.0, float(cooldown_time)),
            )

    @staticmethod
    def _build_entry(
        *,
        deployment_id: str,
        alias: str,
        raw_model: str,
        params: Mapping[str, Any],
        priority: int,
    ) -> DeploymentEntry:
        client_api_key, client_base_url, _ = extract_client_overrides(params)
        api_base_override = params.get("api_base") or params.get("base_url") or client_base_url
        custom_provider = params.get("custom_llm_provider")
        protocol = resolve_native_protocol(
            raw_model,
            api_base=str(api_base_override) if api_base_override else None,
            custom_llm_provider=str(custom_provider) if custom_provider else None,
            wire_protocol=params.get("wire_protocol"),
        )
        provider, wire_model = strip_provider_prefix(raw_model)
        if custom_provider:
            provider = str(custom_provider).strip().lower()
        if protocol is None:
            raise NativeBadRequestError(
                f"Model '{raw_model}' does not use a native HTTPX protocol",
                status_code=400,
                provider=provider,
            )

        api_base = str(api_base_override or resolve_default_api_base(provider, protocol)).strip()
        extra_headers: Dict[str, str] = {}
        merge_header_overrides(extra_headers, params)
        extra_body = dict(params.get("extra_body")) if isinstance(params.get("extra_body"), Mapping) else {}
        timeout_val = params.get("timeout")
        return DeploymentEntry(
            deployment_id=deployment_id,
            model_name=alias,
            wire_model=wire_model,
            api_base=api_base,
            api_key=params.get("api_key") or client_api_key,
            protocol=protocol,
            provider=provider,
            extra_headers=extra_headers,
            extra_body=extra_body,
            priority=priority,
            timeout=float(timeout_val) if timeout_val is not None else None,
        )

    @classmethod
    def _entries_from_model_list(cls, model_list: List[Dict[str, Any]]) -> List[DeploymentEntry]:
        entries: List[DeploymentEntry] = []
        for idx, raw_entry in enumerate(model_list):
            if not isinstance(raw_entry, Mapping):
                continue
            params = raw_entry.get("litellm_params") or {}
            if not isinstance(params, Mapping):
                params = {}
            raw_model = str(params.get("model") or raw_entry.get("model_name") or "").strip()
            alias = str(raw_entry.get("model_name") or raw_model).strip()
            priority = int((raw_entry.get("model_info") or {}).get("priority", idx))
            entries.append(
                cls._build_entry(
                    deployment_id=f"{alias}:{idx}",
                    alias=alias,
                    raw_model=raw_model,
                    params=params,
                    priority=priority,
                )
            )
        return entries

    @property
    def pool(self) -> DeploymentPool:
        """Expose underlying :class:`DeploymentPool` for cooldown inspection and health metrics."""
        return self._pool

    def _prepare_request(
        self,
        entry: DeploymentEntry,
        messages: List[Dict[str, Any]],
        stream: bool,
        kwargs: Mapping[str, Any],
    ) -> PreparedRequest:
        if entry.protocol == "anthropic":
            from src.llm.anthropic_transport import prepare_anthropic_request

            return prepare_anthropic_request(
                entry, messages, stream, kwargs, default_timeout=self._timeout
            )
        if entry.protocol == "gemini":
            from src.llm.gemini_transport import prepare_gemini_request

            return prepare_gemini_request(
                entry, messages, stream, kwargs, default_timeout=self._timeout
            )
        from src.llm.openai_transport import prepare_openai_request

        return prepare_openai_request(
            entry, messages, stream, kwargs, default_timeout=self._timeout
        )

    @staticmethod
    def _parse_response(entry: DeploymentEntry, payload: Mapping[str, Any]) -> NativeCompletionResponse:
        if entry.protocol == "anthropic":
            from src.llm.anthropic_transport import parse_anthropic_response

            return parse_anthropic_response(payload, default_model=entry.wire_model)
        if entry.protocol == "gemini":
            from src.llm.gemini_transport import parse_gemini_response

            return parse_gemini_response(payload, default_model=entry.wire_model)
        from src.llm.openai_transport import parse_openai_response

        return parse_openai_response(entry, payload)

    @staticmethod
    def _iter_stream_chunks(entry: DeploymentEntry, byte_chunks: Iterable[bytes]) -> Iterator[NativeStreamChunk]:
        if entry.protocol == "anthropic":
            from src.llm.anthropic_transport import iter_anthropic_stream_chunks

            return iter_anthropic_stream_chunks(
                byte_chunks,
                default_model=entry.wire_model,
                provider=entry.provider,
            )
        if entry.protocol == "gemini":
            from src.llm.gemini_transport import iter_gemini_stream_chunks

            return iter_gemini_stream_chunks(
                byte_chunks,
                default_model=entry.wire_model,
                provider=entry.provider,
            )
        from src.llm.openai_transport import iter_openai_stream_chunks

        return iter_openai_stream_chunks(entry, byte_chunks)

    def completion(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Execute pooled completion across heterogeneous native protocol deployments."""
        req_kwargs = dict(kwargs)
        raw_retries = req_kwargs.pop("num_retries", self._num_retries)
        effective_retries = max(0, int(raw_retries if raw_retries is not None else self._num_retries))
        _, _, client_http = extract_client_overrides(req_kwargs)
        candidates = self._pool.select_candidates(model)
        using_pool = bool(candidates)
        if not candidates:
            candidates = [
                self._build_entry(
                    deployment_id=f"ephemeral:{model}",
                    alias=model,
                    raw_model=model,
                    params=req_kwargs,
                    priority=0,
                )
            ]

        if stream:
            return stream_pooled_completion(
                candidates=candidates,
                pool=self._pool,
                using_pool=using_pool,
                messages=messages,
                kwargs=req_kwargs,
                prepare_request_fn=self._prepare_request,
                iter_stream_fn=self._iter_stream_chunks,
                http_transport=self._http_transport,
                http_client=client_http,
                request_model=model,
                num_retries=effective_retries,
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
            parse_response_fn=self._parse_response,
            http_transport=self._http_transport,
            http_client=client_http,
            request_model=model,
            num_retries=effective_retries,
            sleep_fn=self._sleep_fn,
            cancel_check=raise_if_stock_cancelled,
        )


class NativeUnifiedTransport:
    """
    Unified 4-protocol native ``httpx`` transport implementing ``LLMTransport``.

    Handles OpenAI Chat Completions, OpenAI Responses API, Anthropic Messages, and
    Google Gemini REST API directly, with optional ``fallback_transport`` for
    cloud-IAM providers (Bedrock / Vertex AI / Azure).
    """

    def __init__(
        self,
        *,
        http_transport: Optional[Any] = None,
        fallback_transport: Optional[LLMTransport] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Optional[Callable[[float], None]] = None,
        default_timeout: float = 120.0,
    ) -> None:
        self._http_transport = http_transport
        self._fallback_transport = fallback_transport
        self._clock = clock
        self._sleep_fn = sleep_fn
        self._default_timeout = float(default_timeout)
        self._registered_model_costs: Dict[str, Any] = {}

    def completion(self, **kwargs: Any) -> Any:
        """Dispatch completion to the native protocol engine or ``fallback_transport``."""
        model = str(kwargs.get("model") or "").strip()
        _, client_base_url, _ = extract_client_overrides(kwargs)
        api_base = kwargs.get("api_base") or kwargs.get("base_url") or client_base_url
        custom_provider = kwargs.get("custom_llm_provider")
        wire_protocol = kwargs.get("wire_protocol")

        if not supports_native_protocol(
            model,
            api_base=str(api_base) if api_base else None,
            custom_llm_provider=str(custom_provider) if custom_provider else None,
            wire_protocol=str(wire_protocol) if wire_protocol else None,
        ):
            if self._fallback_transport is not None:
                return self._fallback_transport.completion(**kwargs)
            raise NativeBadRequestError(
                f"NativeUnifiedTransport does not support provider for model '{model}' without fallback_transport",
                status_code=400,
                provider=strip_provider_prefix(model)[0],
            )

        call_kwargs = dict(kwargs)
        raw_retries = call_kwargs.pop("num_retries", 0)
        effective_retries = max(0, int(raw_retries if raw_retries is not None else 0))
        router = NativeUnifiedRouter(
            http_transport=self._http_transport,
            timeout=float(call_kwargs.get("timeout") or self._default_timeout),
            num_retries=effective_retries,
            clock=self._clock,
            sleep_fn=self._sleep_fn,
        )
        messages = call_kwargs.pop("messages", [])
        stream = bool(call_kwargs.pop("stream", False))
        call_kwargs.pop("model", None)
        return router.completion(model=model, messages=messages, stream=stream, **call_kwargs)

    def create_router(self, model_list: List[Dict[str, Any]], **kwargs: Any) -> Any:
        """Build a pooled :class:`NativeUnifiedRouter` when every deployment uses a native protocol."""
        all_native = all(
            supports_native_protocol(
                str((entry.get("litellm_params") or {}).get("model") or entry.get("model_name") or ""),
                api_base=(entry.get("litellm_params") or {}).get("api_base")
                or (entry.get("litellm_params") or {}).get("base_url"),
                custom_llm_provider=(entry.get("litellm_params") or {}).get("custom_llm_provider"),
                wire_protocol=(entry.get("litellm_params") or {}).get("wire_protocol"),
            )
            for entry in (model_list or [])
            if isinstance(entry, Mapping)
        )
        if not all_native:
            if self._fallback_transport is not None:
                return self._fallback_transport.create_router(model_list, **kwargs)
            raise NativeBadRequestError(
                "Router model_list contains non-native provider without fallback_transport",
                status_code=400,
                provider="unknown",
            )
        return NativeUnifiedRouter(
            model_list=model_list,
            http_transport=self._http_transport,
            timeout=float(kwargs.get("timeout") or self._default_timeout),
            num_retries=int(kwargs.get("num_retries", 2)),
            cooldown_time=float(kwargs.get("cooldown_time", 30.0)),
            clock=self._clock,
            sleep_fn=self._sleep_fn,
        )

    def can_register_model(self) -> bool:
        return True

    def register_model(self, model_cost: Dict[str, Any]) -> None:
        if isinstance(model_cost, Mapping):
            self._registered_model_costs.update(model_cost)

    def get_model_cost(self) -> Dict[str, Any]:
        return dict(self._registered_model_costs)

    def token_counter(self, *, model: str, text: str) -> int:
        raw = str(text or "")
        if not raw:
            return 0
        return max(1, (len(raw) + 2) // 3)

    def get_model_providers(self) -> frozenset[str]:
        return NATIVE_ALL_PROVIDERS

    def disable_streaming_logging(self) -> None:
        return None

    def silence_logs(self) -> None:
        return None

    def resolve_exception(self, name: str) -> type[BaseException]:
        if name in _NATIVE_EXCEPTION_MAP:
            return _NATIVE_EXCEPTION_MAP[name]
        if self._fallback_transport is not None:
            return self._fallback_transport.resolve_exception(name)
        return NativeAPIError


def create_native_openai_transport(
    *,
    http_transport: Optional[Any] = None,
    fallback_transport: Optional[LLMTransport] = None,
    fallback_to_litellm: bool = True,
    default_timeout: float = 120.0,
) -> LLMTransport:
    """Create a native HTTPX OpenAI transport with optional LiteLLM fallback for non-OpenAI models."""
    from src.llm.openai_transport import NativeOpenAITransport

    resolved_fallback = fallback_transport
    if resolved_fallback is None and fallback_to_litellm:
        resolved_fallback = LiteLLMTransport()

    return NativeOpenAITransport(
        http_transport=http_transport,
        fallback_transport=resolved_fallback,
        default_timeout=default_timeout,
    )


def create_native_transport(
    *,
    http_transport: Optional[Any] = None,
    fallback_transport: Optional[LLMTransport] = None,
    fallback_to_litellm: bool = True,
    default_timeout: float = 120.0,
) -> LLMTransport:
    """Create the unified 4-protocol native HTTPX transport (OpenAI/Anthropic/Gemini)."""
    resolved_fallback = fallback_transport
    if resolved_fallback is None and fallback_to_litellm:
        resolved_fallback = LiteLLMTransport()

    return NativeUnifiedTransport(
        http_transport=http_transport,
        fallback_transport=resolved_fallback,
        default_timeout=default_timeout,
    )


_ACTIVE_TRANSPORT: ContextVar[Optional[LLMTransport]] = ContextVar(
    "dsa_active_llm_transport",
    default=None,
)
_DEFAULT_TRANSPORT: Optional[LLMTransport] = None
_MODE_TRANSPORTS: Dict[str, LLMTransport] = {}


def resolve_llm_transport_mode(raw: Optional[str] = None) -> str:
    """Resolve runtime ``LLM_TRANSPORT_MODE`` into ``litellm``, ``auto``, or ``native``."""
    raw_value = os.getenv("LLM_TRANSPORT_MODE", "") if raw is None else raw
    cleaned = str(raw_value or "").strip().lower()
    if not cleaned or cleaned == "litellm":
        return "litellm"
    if cleaned in {"auto", "native_httpx", "hybrid"}:
        return "auto"
    if cleaned in {"native", "native_only", "httpx"}:
        return "native"
    logger.warning(
        "[LLMTransport] Unsupported LLM_TRANSPORT_MODE=%r; falling back to 'litellm'",
        raw_value,
    )
    return "litellm"


def reset_transport_cache() -> None:
    """Clear cached mode transports cleanly (for tests and dynamic config reloads)."""
    _MODE_TRANSPORTS.clear()


def _get_transport_for_mode(mode: str) -> LLMTransport:
    cached = _MODE_TRANSPORTS.get(mode)
    if cached is not None:
        return cached
    if mode == "native":
        instance: LLMTransport = create_native_transport(fallback_to_litellm=False)
    elif mode == "auto":
        instance = create_native_transport(fallback_to_litellm=True)
    else:
        instance = LiteLLMTransport()
    _MODE_TRANSPORTS[mode] = instance
    return instance


def get_transport_override() -> Optional[LLMTransport]:
    """Return the active context-scoped transport override if one is installed."""
    return _ACTIVE_TRANSPORT.get()


def set_default_transport(transport: Optional[LLMTransport]) -> None:
    """Override the process-wide default LLM transport (pass None to reset)."""
    global _DEFAULT_TRANSPORT
    _DEFAULT_TRANSPORT = transport


def get_custom_transport() -> Optional[LLMTransport]:
    """Return the active context, process-wide, or non-litellm env-configured transport."""
    active = _ACTIVE_TRANSPORT.get()
    if active is not None:
        return active
    if _DEFAULT_TRANSPORT is not None:
        return _DEFAULT_TRANSPORT
    mode = resolve_llm_transport_mode()
    if mode != "litellm":
        return _get_transport_for_mode(mode)
    return None


def get_transport() -> LLMTransport:
    """Return active context/process transport, or transport resolved from ``LLM_TRANSPORT_MODE``."""
    custom = get_custom_transport()
    if custom is not None:
        return custom
    return _get_transport_for_mode("litellm")


def is_native_transport_active() -> bool:
    """Return True when the active transport executes via native HTTPX instead of LiteLLM."""
    return not isinstance(get_transport(), LiteLLMTransport)


@contextmanager
def use_transport(transport: Optional[LLMTransport]) -> Iterator[Optional[LLMTransport]]:
    """Temporarily bind ``transport`` for the current execution context."""
    token = _ACTIVE_TRANSPORT.set(transport)
    try:
        yield transport
    finally:
        _ACTIVE_TRANSPORT.reset(token)


def resolve_litellm_module(*, load: bool = False) -> Optional[Any]:
    """Return ``sys.modules['litellm']``, optionally importing LiteLLM on demand."""
    module = sys.modules.get("litellm")
    if module is None and load:
        module = importlib.import_module("litellm")
    if module is not None:
        _apply_disable_streaming_logging(module)
    return module


def dispatch_completion(
    *,
    compat_proxy: Optional[Any] = None,
    **kwargs: Any,
) -> Any:
    """Dispatch a completion request through the active transport or legacy module patch."""
    override = get_transport_override()
    if override is not None:
        return override.completion(**kwargs)
    patched_completion = getattr(compat_proxy, "completion", None) if compat_proxy is not None else None
    if callable(patched_completion):
        return patched_completion(**kwargs)
    return get_transport().completion(**kwargs)


def create_router(model_list: List[Dict[str, Any]], **kwargs: Any) -> Any:
    """Create a multi-key router through the active LLM transport."""
    return get_transport().create_router(model_list, **kwargs)


def can_register_model(*, compat_proxy: Optional[Any] = None) -> bool:
    """Return whether dynamic model pricing registration is supported."""
    if get_transport_override() is not None:
        return get_transport().can_register_model()
    if compat_proxy is not None and callable(getattr(compat_proxy, "register_model", None)):
        return True
    return get_transport().can_register_model()


def register_model(
    model_cost: Dict[str, Any],
    *,
    compat_proxy: Optional[Any] = None,
) -> None:
    """Register dynamic model pricing metadata via the active transport or compat patch."""
    override = get_transport_override()
    if override is not None:
        override.register_model(model_cost)
        return
    patched_register = getattr(compat_proxy, "register_model", None) if compat_proxy is not None else None
    if callable(patched_register):
        patched_register(model_cost)
        return
    get_transport().register_model(model_cost)


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


def token_counter(*, model: str, text: str) -> int:
    """Count tokens using the active LLM transport."""
    return get_transport().token_counter(model=model, text=text)


def resolve_llm_transport_mode_for_config(config: Optional[Any] = None) -> str:
    """Resolve effective transport mode from env ``LLM_TRANSPORT_MODE`` or ``config.llm_transport_mode``."""
    raw_env = os.getenv("LLM_TRANSPORT_MODE")
    if raw_env is not None and raw_env.strip():
        return resolve_llm_transport_mode(raw_env)
    cfg_mode = getattr(config, "llm_transport_mode", None) if config is not None else None
    if cfg_mode is not None and str(cfg_mode).strip():
        return resolve_llm_transport_mode(str(cfg_mode))
    return "litellm"


def get_transport_for_config(config: Optional[Any] = None) -> LLMTransport:
    """Return active transport override, or resolve transport honoring ``config.llm_transport_mode``."""
    override = get_transport_override()
    if override is not None:
        return override
    if _DEFAULT_TRANSPORT is not None:
        return _DEFAULT_TRANSPORT
    mode = resolve_llm_transport_mode_for_config(config)
    return _get_transport_for_mode(mode)


def resolve_exception_types(
    name: str,
    *,
    compat_proxy: Optional[Any] = None,
) -> Tuple[type[BaseException], ...]:
    """Return all catchable exception classes for ``name`` across active native/LiteLLM paths."""
    classes: List[type[BaseException]] = []

    def _add(candidate: Any) -> None:
        if isinstance(candidate, type) and issubclass(candidate, BaseException) and candidate not in classes:
            classes.append(candidate)

    override = get_transport_override()
    if override is not None:
        _add(override.resolve_exception(name))

    if compat_proxy is not None:
        _add(getattr(compat_proxy, name, None))

    active = get_transport()
    if override is None:
        _add(active.resolve_exception(name))

    # In auto mode or mixed mocks, a loaded LiteLLM module may raise litellm.* exceptions
    # from fallback cloud-IAM deployments without eager import when native mode is active.
    loaded_litellm = sys.modules.get("litellm")
    if loaded_litellm is not None and not isinstance(active, LiteLLMTransport):
        has_fallback = getattr(active, "_fallback_transport", None) is not None
        if has_fallback or override is None:
            _add(getattr(loaded_litellm, name, None))

    if not classes:
        _add(_NATIVE_EXCEPTION_MAP.get(name, NativeAPIError))

    return tuple(classes)


def resolve_exception(
    name: str,
    *,
    compat_proxy: Optional[Any] = None,
) -> type[BaseException]:
    """Resolve an exception class from the active transport override or compat mock."""
    override = get_transport_override()
    if override is not None:
        return override.resolve_exception(name)
    if compat_proxy is not None:
        compat_exc = getattr(compat_proxy, name, None)
        if isinstance(compat_exc, type) and issubclass(compat_exc, BaseException):
            return compat_exc
    return get_transport().resolve_exception(name)
