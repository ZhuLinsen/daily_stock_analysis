# -*- coding: utf-8 -*-
"""Unified internal LLM transport facade.

Phase 1 (Issue #2622) centralizes all runtime ``litellm`` interactions
(completion dispatch, Router construction, dynamic model pricing registration,
token estimation, provider prefix discovery, exception resolution, and log
silencing) behind an explicit ``LLMTransport`` boundary so callers never couple
directly to the LiteLLM SDK and Phase 2 native HTTPX transports can plug into
the same seam without touching call sites again.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import copy
from dataclasses import dataclass, field
import importlib
import logging
import math
import os
import sys
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

logger = logging.getLogger(__name__)

_ALLOWED_REQUEST_DEFAULT_KEYS: frozenset[str] = frozenset(
    {
        "temperature",
        "top_p",
        "top_k",
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
        "stop",
        "stop_sequences",
        "seed",
        "presence_penalty",
        "frequency_penalty",
        "response_format",
        "reasoning_effort",
        "thinking",
        "thinking_config",
        "generation_config",
        "store",
        "parallel_tool_calls",
        "prompt_cache_key",
        "prompt_cache_retention",
        "stream_options",
        "user",
    }
)


def _apply_disable_streaming_logging(module: Any) -> None:
    """Keep LiteLLM per-chunk async streaming logging disabled (Issue #2524)."""
    if module is None:
        return
    try:
        setattr(module, "disable_streaming_logging", True)
    except (AttributeError, TypeError):
        pass


def find_unresolved_env_var(value: Any) -> Optional[str]:
    """Return the missing env var name if ``value`` is an unset ``os.environ/VAR`` ref."""
    if not isinstance(value, str) or not value.startswith("os.environ/"):
        return None
    env_name = value.split("/", 1)[1].strip()
    if not env_name:
        return "<empty>"
    if not os.getenv(env_name, "").strip():
        return env_name
    return None


def resolve_env_reference(value: Any) -> Any:
    """Resolve ``os.environ/VAR`` syntax used in LiteLLM YAML configs."""
    if isinstance(value, str) and value.startswith("os.environ/"):
        env_name = value.split("/", 1)[1].strip()
        return os.getenv(env_name, "") if env_name else ""
    return value


def resolve_headers_env(headers: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Copy a header mapping while resolving any ``os.environ/VAR`` values."""
    if not isinstance(headers, Mapping):
        return {}
    resolved: Dict[str, str] = {}
    for key, raw_value in headers.items():
        header_name = str(key).strip()
        if not header_name:
            continue
        value = resolve_env_reference(raw_value)
        if value is None:
            continue
        resolved[header_name] = str(value)
    return resolved


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

    Resolves ``os.environ/VAR`` references in ``litellm_params`` (including
    ``api_key``, ``api_base``, ``base_url``, and ``extra_headers`` values) while
    preserving ``model_info`` metadata such as ``dsa_api_surface`` and
    ``dsa_channel_protocol``.
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
    if target.startswith("openai/responses/") or "/responses/" in target:
        return
    model_list = getattr(router, "model_list", None)
    if not isinstance(model_list, list) or not model_list:
        return
    matching_entries: List[Mapping[str, Any]] = []
    for entry in model_list:
        if not isinstance(entry, Mapping):
            continue
        params = entry.get("litellm_params")
        wire = str(params.get("model") or "").strip() if isinstance(params, Mapping) else ""
        alias = str(entry.get("model_name") or "").strip()
        if not target or target in {alias, wire}:
            matching_entries.append(entry)
    if not matching_entries:
        return
    for entry in matching_entries:
        params = entry.get("litellm_params")
        wire = str(params.get("model") or "").strip() if isinstance(params, Mapping) else ""
        if wire.startswith("openai/responses/") or "/responses/" in wire:
            return
    raise ValueError(
        f"Router deployment for model '{target}' is not configured for the OpenAI Responses API surface"
    )


@dataclass(frozen=True)
class DeploymentSpec:
    """Normalized single-deployment contract shared across transport engines.

    This immutable contract separates channel protocol, explicit wire protocol,
    and LiteLLM ``custom_llm_provider`` while lifting generation defaults and
    routing priority cleanly for Phase 2 native HTTPX engines.
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
    # Match LiteLLM 1.98.1 precedence: any non-None base_url overrides api_base,
    # including an explicit empty string base_url="".
    if "base_url" in params and params.get("base_url") is not None:
        api_base = str(params.get("base_url")).strip()
    else:
        api_base = str(params.get("api_base") or "").strip()
    api_key = str(params.get("api_key") or "").strip()
    # ``params`` already resolved ``extra_headers`` once; copy without re-resolving.
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
    """CJK-aware fallback token estimate used when a tokenizer is unavailable.

    Pure ASCII/non-CJK text uses ``ceil(len / 3)`` for backward compatibility,
    while CJK characters are weighted at ``1.5`` tokens per character so Chinese
    chat compression never underestimates into context-window overflow.
    """
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


class LiteLLMTransport:
    """Default ``LLMTransport`` backed lazily by ``litellm``."""

    @staticmethod
    def _load_litellm() -> Any:
        if "litellm" not in sys.modules:
            # Prevent litellm.__init__ from fetching GitHub's model_prices JSON
            # during offline FastAPI/CLI/library lazy initialization.
            os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
        # Always go through importlib.import_module so concurrent first imports
        # synchronize on Python's module import lock while still returning any
        # test stub installed in sys.modules["litellm"].
        module = importlib.import_module("litellm")
        _apply_disable_streaming_logging(module)
        return module

    def completion(self, **kwargs: Any) -> Any:
        payload = dict(kwargs)
        # ``api_surface`` and ``wire_protocol`` are internal transport metadata:
        # encode Responses onto the LiteLLM wire model before stripping them so
        # strict OpenAI-compatible endpoints never reject unknown body params.
        api_surface = payload.pop("api_surface", None)
        payload.pop("wire_protocol", None)
        if api_surface and "model" in payload:
            payload["model"] = _encode_litellm_responses_wire_model(payload["model"], api_surface)
        return self._load_litellm().completion(**payload)

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
                    has_internal_keys = "api_surface" in params or "wire_protocol" in params
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
                        copied_params = dict(params)
                        copied_params.pop("api_surface", None)
                        copied_params.pop("wire_protocol", None)
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

    def register_model(self, model_cost: Mapping[str, Any]) -> None:
        register = getattr(self._load_litellm(), "register_model", None)
        if callable(register):
            register(dict(model_cost))

    def get_model_cost(self) -> Dict[str, Any]:
        try:
            module = self._load_litellm()
        except Exception:
            return {}
        cost_map = getattr(module, "model_cost", {})
        return cost_map if isinstance(cost_map, dict) else {}

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
        providers: set[str] = set()
        if "litellm" not in sys.modules:
            os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
        try:
            utils_mod = importlib.import_module("litellm.types.utils")
            llm_providers = getattr(utils_mod, "LlmProviders", ())
            providers.update(
                str(provider.value).strip().lower()
                for provider in llm_providers
                if str(getattr(provider, "value", "")).strip()
            )
        except (ImportError, AttributeError, TypeError):
            logger.debug("LiteLLM provider metadata unavailable; returning empty provider set")
        if "litellm" in sys.modules:
            _apply_disable_streaming_logging(sys.modules.get("litellm"))
        return frozenset(providers)

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


_ACTIVE_TRANSPORT: ContextVar[Optional[LLMTransport]] = ContextVar(
    "dsa_active_llm_transport",
    default=None,
)
_DEFAULT_TRANSPORT: Optional[LLMTransport] = None
_CACHED_TRANSPORTS: Dict[str, LLMTransport] = {}


def get_transport_override() -> Optional[LLMTransport]:
    """Return the active context-scoped transport override, if installed."""
    return _ACTIVE_TRANSPORT.get()


def set_default_transport(transport: Optional[LLMTransport]) -> None:
    """Override the process-wide default LLM transport (pass ``None`` to clear)."""
    global _DEFAULT_TRANSPORT
    _DEFAULT_TRANSPORT = transport
    reset_transport_cache()


def reset_transport_cache() -> None:
    """Clear cached transport instances and transport-adjacent provider/pricing caches."""
    _CACHED_TRANSPORTS.clear()
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


def get_transport() -> LLMTransport:
    """Return the active context-scoped, process-wide, or cached default transport."""
    active = _ACTIVE_TRANSPORT.get()
    if active is not None:
        return active
    if _DEFAULT_TRANSPORT is not None:
        return _DEFAULT_TRANSPORT
    cached = _CACHED_TRANSPORTS.get("litellm")
    if cached is None:
        cached = LiteLLMTransport()
        _CACHED_TRANSPORTS["litellm"] = cached
    return cached


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
    **kwargs: Any,
) -> Any:
    """Dispatch a completion call through a router, active transport, or legacy mock."""
    if router is not None:
        if (
            ("api_surface" in kwargs or "wire_protocol" in kwargs)
            and not getattr(router, "_dsa_accepts_transport_metadata", False)
        ):
            _validate_prebuilt_router_api_surface(
                router,
                kwargs.get("model"),
                kwargs.get("api_surface"),
            )
            router_kwargs = dict(kwargs)
            router_kwargs.pop("api_surface", None)
            router_kwargs.pop("wire_protocol", None)
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
    return get_transport().completion(**kwargs)


def create_router(
    model_list: List[Dict[str, Any]],
    *,
    router_factory: Optional[Any] = None,
    transport: Optional[LLMTransport] = None,
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
    return get_transport().create_router(model_list, **kwargs)


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

    loaded_litellm = sys.modules.get("litellm")
    if loaded_litellm is not None and not isinstance(active, LiteLLMTransport):
        _add(getattr(loaded_litellm, name, None))

    if not classes:
        _add(_build_synthetic_exception(name))

    return tuple(classes)
