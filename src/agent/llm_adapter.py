# -*- coding: utf-8 -*-
"""
Multi-provider LLM Tool-Calling Adapter.

Normalizes function-calling / tool-use across all providers into a unified
interface consumed by the AgentExecutor, via LiteLLM.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import litellm
from litellm import Router

from src.config import (
    extra_litellm_params,
    get_api_keys_for_model,
    get_config,
    get_configured_llm_models,
    get_effective_agent_models_to_try,
    get_effective_agent_primary_model,
)
from src.agent.provider_trace import (
    TRACE_MODEL_KEY,
    TRACE_PROVIDER_KEY,
    resolved_model_provider_identity,
    resolved_provider_namespace,
    trace_model_matches,
)
from src.llm.errors import call_litellm_with_param_recovery
from src.llm.backend_registry import (
    AUTO_AGENT_BACKEND_ID,
    CODEX_CLI_BACKEND_ID,
    LITELLM_BACKEND_ID,
    resolve_agent_generation_backend_id,
)
from src.llm.generation_backend import GenerationError, GenerationErrorCode
from src.llm.generation_params import apply_litellm_generation_params, resolve_litellm_wire_model
from src.llm.usage import attach_message_hmacs, extract_usage_payload, normalize_litellm_usage
from src.llm.provider_cache import (
    build_provider_cache_route_context,
    filter_prompt_cache_telemetry,
    normalize_prompt_cache_diagnostics_level,
    resolve_provider_cache_caps,
)

logger = logging.getLogger(__name__)


def _resolve_litellm_exception(name: str) -> type[BaseException]:
    """Return a catchable LiteLLM exception class even in stubbed test environments."""
    exc = getattr(litellm, name, None)
    if isinstance(exc, type) and issubclass(exc, BaseException):
        return exc

    class _FallbackLiteLLMError(Exception):
        pass

    _FallbackLiteLLMError.__name__ = f"Fallback{name}"
    return _FallbackLiteLLMError


# ============================================================
# Unified response types
# ============================================================

@dataclass
class ToolCall:
    """A single tool call requested by the LLM."""
    id: str
    name: str
    arguments: Dict[str, Any]
    thought_signature: Optional[str] = None
    provider_specific_fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider."""
    content: Optional[str] = None          # text response (final answer)
    tool_calls: List[ToolCall] = field(default_factory=list)  # tool calls to execute
    reasoning_content: Optional[str] = None  # Chain-of-thought (CoT) from DeepSeek thinking mode; must be passed back in multi-turn assistant messages; None for other providers
    provider_blocks: List[Dict[str, Any]] = field(default_factory=list)  # Opaque provider content blocks (e.g. Claude thinking/redacted_thinking)
    usage: Dict[str, Any] = field(default_factory=dict)       # token usage info
    provider: str = ""                     # which provider handled this call
    model: str = ""                        # full model name used (e.g. gemini/gemini-2.0-flash), for report meta
    raw: Any = None                        # raw provider response for debugging


# Models that auto-return reasoning_content; do NOT send extra_body (may cause 400).
_AUTO_THINKING_MODELS: List[str] = ["deepseek-reasoner", "deepseek-r1", "qwq"]

# Models that need explicit opt-in via extra_body; payload decoupled from model name.
_OPT_IN_THINKING_MODELS: Dict[str, dict] = {
    "deepseek-chat": {"thinking": {"type": "enabled"}},
}

# Custom model pricing for models not in LiteLLM's built-in price list.
# Official MiniMax pricing: https://platform.minimax.io/docs/guides/pricing-paygo
# - MiniMax-M3: $0.6/M input tokens, $2.4/M output tokens for prompts <=512K input
#   tokens. Officially supports up to 1M input tokens with a separate higher
#   price tier for the >512K bucket; we conservatively register only the
#   <=512K bucket here because the cost tracker carries a single per-token
#   price and the higher-tier price is not modeled. Long prompts will be
#   cost-estimated using the <=512K rate; treat the estimate as a floor in
#   that case.
# - MiniMax-M2.7: $0.3/M input tokens, $1.2/M output tokens.
# - MiniMax-M2.5: kept as legacy so existing user configs continue to report
#   accurate cost. Still listed as a Legacy Model on the official pricing
#   page; remove only after we have user-facing migration guidance.
_CUSTOM_MODEL_PRICING: Dict[str, dict] = {
    "MiniMax-M3": {
        "supports_function_calling": True,
        "supports_vision": True,
        "supports_audio_input": False,
        "supports_audio_output": False,
        # Project-conservative bound for the <=512K input-token price tier.
        # MiniMax-M3 supports up to 1M input tokens officially, but pricing
        # changes above 512K; see comment block above.
        "context_window": 512000,
        "max_tokens": 128000,
        "input_cost_per_token": 0.0000006,   # $0.6 / 1M tokens (<=512K input bucket)
        "output_cost_per_token": 0.0000024,   # $2.4 / 1M tokens (<=512K input bucket)
    },
    "MiniMax-M2.7": {
        "supports_function_calling": True,
        "supports_vision": False,
        "supports_audio_input": False,
        "supports_audio_output": False,
        "context_window": 100000,
        "max_tokens": 10000,
        "input_cost_per_token": 0.0000003,   # $0.3 / 1M tokens
        "output_cost_per_token": 0.0000012,   # $1.2 / 1M tokens
    },
    # Legacy model retained for backward compatibility with existing user
    # configs; values match the previous M2.5 entry to avoid silently
    # zero-costing prior cost estimates.
    "MiniMax-M2.5": {
        "supports_function_calling": True,
        "supports_vision": False,
        "supports_audio_input": False,
        "supports_audio_output": False,
        "context_window": 245760,
        "max_tokens": 8192,
        "input_cost_per_token": 0.0000003,   # $0.3 / 1M tokens (legacy)
        "output_cost_per_token": 0.0000012,   # $1.2 / 1M tokens (legacy)
    },
}

_FALLBACK_MODEL_PRICING: Dict[str, Any] = {
    "supports_function_calling": True,
    "supports_vision": False,
    "supports_audio_input": False,
    "supports_audio_output": False,
    "context_window": 100000,
    "max_tokens": 10000,
    "input_cost_per_token": 0.0,
    "output_cost_per_token": 0.0,
}
_FALLBACK_MODEL_PRICING_REGISTERED: set[str] = set()


def _split_provider_model(model: str) -> Tuple[str, str]:
    normalized = (model or "").strip()
    if not normalized:
        return "", ""
    if "/" in normalized:
        provider, remainder = normalized.split("/", 1)
        return provider.lower(), remainder.strip()
    return "openai", normalized


def _object_to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            dumped = value.dict()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
    result: Dict[str, Any] = {}
    for key in ("type", "text", "content", "thinking", "signature", "data"):
        if hasattr(value, key):
            result[key] = getattr(value, key)
    return result


def _provider_specific_fields_from(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    data = _object_to_dict(value)
    return data if isinstance(data, dict) else {}


def _extract_provider_blocks(choice: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Return opaque provider blocks and joined text block content, if present."""
    block_sources = []
    message = getattr(choice, "message", None)
    for owner in (message, choice):
        if owner is None:
            continue
        for attr in ("content", "content_blocks", "provider_blocks", "thinking_blocks"):
            value = getattr(owner, attr, None)
            if isinstance(value, list):
                block_sources.append(value)

    blocks: List[Dict[str, Any]] = []
    text_parts: List[str] = []
    for source in block_sources:
        for raw_block in source:
            block = _object_to_dict(raw_block)
            if not block:
                continue
            blocks.append(block)
            block_type = str(block.get("type") or "")
            text = block.get("text") or block.get("content")
            if block_type == "text" and text:
                text_parts.append(str(text))
    return blocks, ("".join(text_parts).strip() or None)


def _message_trace_matches_target(
    message: Dict[str, Any],
    target_model: Optional[str],
    *,
    target_provider: Optional[str] = None,
) -> bool:
    """Whether provider-specific fields in ``message`` can be sent to target."""
    if not target_model:
        return True
    trace_provider = message.get(TRACE_PROVIDER_KEY)
    trace_model = message.get(TRACE_MODEL_KEY)
    if not trace_provider and not trace_model:
        return True
    return trace_model_matches(
        trace_provider,
        trace_model,
        target_model,
        current_provider=target_provider,
    )


def _model_matches(model: str, entries: List[str]) -> bool:
    """Check if model name matches any entry (exact or prefix with version suffix)."""
    if not model:
        return False
    m = model.lower().strip()
    for e in entries:
        if m == e or m.startswith(e + "-"):
            return True
    return False


def _get_opt_in_payload(model: str, opt_in: Dict[str, dict]) -> Optional[dict]:
    """Return extra_body payload for opt-in thinking models, or None."""
    if not model:
        return None
    m = model.lower().strip()
    for key, payload in opt_in.items():
        if m == key or m.startswith(key + "-"):
            return payload
    return None


def get_thinking_extra_body(model: str) -> Optional[dict]:
    """Return extra_body for thinking mode, or None.

    - Auto-thinking models (_AUTO_THINKING_MODELS: deepseek-reasoner, deepseek-r1, qwq):
      These models automatically return reasoning_content in API responses; sending
      extra_body would cause 400 because the API already enables thinking by default.
      Return None to avoid duplicate activation.
    - Opt-in models (_OPT_IN_THINKING_MODELS: deepseek-chat): Return the activation
      payload to explicitly enable thinking mode.
    - All other models: Return None (no thinking mode).
    """
    if _model_matches(model, _AUTO_THINKING_MODELS):
        return None
    return _get_opt_in_payload(model, _OPT_IN_THINKING_MODELS)


def resolve_fallback_litellm_wire_models(
    model: str,
    model_list: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """Resolve all wire models reachable from a configured alias."""
    normalized_model = (model or "").strip()
    if not normalized_model:
        return []

    resolved: List[str] = []
    if model_list:
        for entry in model_list:
            if not isinstance(entry, dict):
                continue
            entry_model_name = str(entry.get("model_name", "") or "").strip()
            if not entry_model_name:
                entry_params = entry.get("litellm_params", {}) or {}
                entry_model_name = str(entry_params.get("model") or "").strip()
            if entry_model_name != normalized_model:
                continue

            entry_params = entry.get("litellm_params", {}) or {}
            wire_model = str(entry_params.get("model") or normalized_model).strip()
            if wire_model and wire_model not in resolved:
                resolved.append(wire_model)

    if not resolved:
        wire_model = resolve_litellm_wire_model(normalized_model, model_list)
        if wire_model and wire_model not in resolved:
            resolved.append(wire_model)
    return resolved


# ============================================================
# LLM Tool Adapter
# ============================================================

class LLMToolAdapter:
    """Unified adapter for tool-calling via LiteLLM.

    Supports all providers (Gemini, Anthropic, OpenAI, DeepSeek, etc.) through
    a single litellm.completion() interface with optional Router for multi-key
    load balancing.
    """

    def __init__(self, config=None):
        config = config or get_config()
        self._config = config
        self._router = None          # litellm Router (multi-key primary model)
        self._legacy_router_model_list: List[Dict[str, Any]] = []
        self._litellm_available = False
        self._backend_error: Optional[GenerationError] = None
        self._generation_backend_id = ""
        self._register_custom_model_pricing()
        self._init_litellm()

    @staticmethod
    def _register_custom_model_pricing() -> None:
        """Register custom model pricing for models not in LiteLLM's built-in price list.

        This prevents cost calculation errors for MiniMax-M2.7 and similar models.
        """
        for model_name, pricing in _CUSTOM_MODEL_PRICING.items():
            try:
                litellm.register_model(
                    {
                        model_name: pricing
                    }
                )
                logger.debug(f"Registered custom pricing for {model_name}")
            except Exception as e:
                logger.debug(f"Model {model_name} may already be registered or pricing error: {e}")
    def _has_channel_config(self) -> bool:
        """Check if multi-channel config (channels / YAML) is active."""
        return bool(self._config.llm_model_list) and not all(
            e.get('model_name', '').startswith('__legacy_') for e in self._config.llm_model_list
        )

    def _init_litellm(self) -> None:
        """Initialize litellm Router from channels / YAML / legacy keys."""
        config = self._config
        self._legacy_router_model_list = []
        try:
            self._generation_backend_id = resolve_agent_generation_backend_id(config)
        except GenerationError as exc:
            self._backend_error = exc
            logger.error("Agent LLM backend configuration error: %s", exc.message)
            return
        if self._generation_backend_id != LITELLM_BACKEND_ID:
            self._backend_error = GenerationError(
                error_code=GenerationErrorCode.UNSUPPORTED_TOOL_CALLING,
                stage="generation",
                retryable=False,
                fallbackable=False,
                backend=self._generation_backend_id,
                provider=self._generation_backend_id,
                details={
                    "field": "AGENT_GENERATION_BACKEND",
                    "requested_backend": self._generation_backend_id,
                    "supported_tool_backend": LITELLM_BACKEND_ID,
                },
            )
            logger.error(
                "Agent LLM backend %s does not support tool calling",
                self._generation_backend_id,
            )
            return

        litellm_model = get_effective_agent_primary_model(config)
        if not litellm_model:
            generation_backend = str(
                getattr(config, "generation_backend", LITELLM_BACKEND_ID) or LITELLM_BACKEND_ID
            ).strip().lower()
            agent_backend = str(
                getattr(config, "agent_generation_backend", AUTO_AGENT_BACKEND_ID)
                or AUTO_AGENT_BACKEND_ID
            ).strip().lower()
            if generation_backend == CODEX_CLI_BACKEND_ID and agent_backend == AUTO_AGENT_BACKEND_ID:
                self._backend_error = GenerationError(
                    error_code=GenerationErrorCode.UNSUPPORTED_TOOL_CALLING,
                    stage="generation",
                    retryable=False,
                    fallbackable=False,
                    backend=CODEX_CLI_BACKEND_ID,
                    provider=CODEX_CLI_BACKEND_ID,
                    details={
                        "field": "AGENT_GENERATION_BACKEND",
                        "requested_backend": AUTO_AGENT_BACKEND_ID,
                        "generation_backend": CODEX_CLI_BACKEND_ID,
                        "supported_tool_backend": LITELLM_BACKEND_ID,
                        "reason": "litellm_agent_backend_unavailable",
                    },
                )
                logger.error(
                    "Agent auto backend cannot inherit %s because it does not support tool calling",
                    CODEX_CLI_BACKEND_ID,
                )
                return
            logger.warning("Agent LLM: no effective primary model configured")
            return

        self._litellm_available = True

        # --- Channel / YAML path ---
        if self._has_channel_config():
            model_list = config.llm_model_list
            self._router = Router(
                model_list=model_list,
                routing_strategy="simple-shuffle",
                num_retries=2,
            )
            unique_models = list(dict.fromkeys(
                e['litellm_params']['model'] for e in model_list
            ))
            logger.info(
                f"Agent LLM: Router initialized from channels/YAML — "
                f"{len(model_list)} deployment(s), models: {unique_models}"
            )
            return

        # --- Legacy path ---
        keys = get_api_keys_for_model(litellm_model, config)
        if not keys:
            logger.info(
                f"Agent LLM: litellm initialized (model={litellm_model}, "
                f"API key from environment)"
            )
            return

        if len(keys) > 1:
            ep = extra_litellm_params(litellm_model, config)
            legacy_model_list = [
                {
                    "model_name": litellm_model,
                    "litellm_params": {
                        "model": litellm_model,
                        "api_key": k,
                        **ep,
                    },
                }
                for k in keys
            ]
            self._legacy_router_model_list = legacy_model_list
            self._router = Router(
                model_list=legacy_model_list,
                routing_strategy="simple-shuffle",
                num_retries=2,
            )
            logger.info(
                f"Agent LLM: Legacy Router initialized with {len(keys)} keys "
                f"for {litellm_model}"
            )
        else:
            logger.info(f"Agent LLM: litellm initialized (model={litellm_model})")

    @property
    def is_available(self) -> bool:
        """True if litellm is configured and at least one API key is present."""
        if self._backend_error is not None:
            return False
        return self._router is not None or self._litellm_available

    @property
    def primary_provider(self) -> str:
        """Provider name extracted from litellm_model prefix."""
        model = get_effective_agent_primary_model(self._config)
        if "/" in model:
            return model.split("/")[0]
        return model or "none"

    # ============================================================
    # Unified call
    # ============================================================

    def call_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[dict],
        provider: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        """Send messages + tool declarations to LLM, return normalized response.

        Args:
            messages: Conversation history in provider-neutral format:
                      [{"role": "system"/"user"/"assistant"/"tool", "content": ...}, ...]
            tools: OpenAI-format tool declarations; litellm converts to each provider's format.
            provider: Ignored (kept for backward compatibility).

        Returns:
            LLMResponse with either content (final answer) or tool_calls.
        """
        return self.call_completion(messages, tools=tools, provider=provider, timeout=timeout)

    def call_text(
        self,
        messages: List[Dict[str, Any]],
        *,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        """Send a text-only completion through the shared routing stack."""
        return self.call_completion(
            messages,
            tools=None,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    def call_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        tools: Optional[List[dict]] = None,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        """Shared completion path for both tool and text-only calls."""
        config = self._config
        if self._backend_error is not None:
            error_msg = (
                "Agent generation backend configuration error: "
                f"{self._backend_error.message}"
            )
            logger.error(error_msg)
            return LLMResponse(content=error_msg, provider="error")
        models_to_try = get_effective_agent_models_to_try(config)
        if not models_to_try:
            error_msg = (
                "No LLM configured. Please set LITELLM_MODEL, LLM_CHANNELS, "
                "or provider API keys before using Agent."
            )
            logger.error(error_msg)
            return LLMResponse(content=error_msg, provider="error")
        started_at = time.time()
        providers = [self._get_model_provider(model) for model in models_to_try]

        last_error = None
        hit_rate_limit = False
        for idx, model in enumerate(models_to_try):
            remaining_timeout = timeout
            if timeout is not None and timeout > 0:
                remaining_timeout = max(0.0, float(timeout) - (time.time() - started_at))
                if remaining_timeout <= 0:
                    last_error = TimeoutError(
                        f"LLM completion timed out before trying fallback model {model}"
                    )
                    break
            try:
                return self._call_litellm_model(
                    messages,
                    tools or [],
                    model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=remaining_timeout,
                )
            except Exception as e:
                if isinstance(e, _resolve_litellm_exception("RateLimitError")):
                    logger.warning("Agent LLM rate-limited on %s: %s", model, e)
                    last_error = e
                    hit_rate_limit = True

                    # Avoid blind backoff across different providers; cross-provider
                    # fallback usually means different accounts/rate-limit buckets.
                    should_backoff = (
                        idx + 1 < len(models_to_try)
                        and providers[idx] == providers[idx + 1]
                    )
                    if should_backoff:
                        backoff_sleep = min(2.0, (time.time() - started_at) * 0.1 + 0.5)
                        if timeout is not None and timeout > 0:
                            remaining_timeout = max(0.0, float(timeout) - (time.time() - started_at))
                            if remaining_timeout > 0:
                                time.sleep(min(backoff_sleep, remaining_timeout))
                        else:
                            time.sleep(backoff_sleep)
                    continue
                if isinstance(e, _resolve_litellm_exception("ContextWindowExceededError")):
                    logger.warning("Agent LLM context window exceeded on %s: %s", model, e)
                    last_error = e
                    continue
                logger.warning("Agent LLM call failed with %s: %s", model, e)
                last_error = e
                continue

        suffix = " (rate-limit encountered during fallback)" if hit_rate_limit else ""
        error_msg = f"All LLM models failed{suffix}. Last error: {last_error}"
        logger.error(error_msg)
        return LLMResponse(content=error_msg, provider="error")

    @staticmethod
    def _get_model_provider(model: str) -> str:
        """Return LiteLLM provider namespace for model fallback grouping."""
        if "/" in model:
            return model.split("/", 1)[0]
        return "openai"

    def _call_litellm_model(
        self,
        messages: List[Dict[str, Any]],
        tools: List[dict],
        model: str,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        """Call a specific litellm model with OpenAI-format messages and tools."""
        openai_messages = self._convert_messages(messages, target_model=model)

        # Use short model name (without provider prefix) for thinking model lookup
        model_short = model.split("/")[-1] if "/" in model else model
        extra = get_thinking_extra_body(model_short)

        call_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
        }
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens
        if timeout is not None:
            call_kwargs["timeout"] = timeout

        if extra:
            call_kwargs["extra_body"] = extra

        if tools:
            call_kwargs["tools"] = tools

        # Use Router for primary model (multi-key), direct litellm for others
        use_channel_router = self._has_channel_config()
        _router_model_names = set(get_configured_llm_models(self._config.llm_model_list))
        agent_primary_model = get_effective_agent_primary_model(self._config)
        uses_router = (
            bool(use_channel_router and self._router and model in _router_model_names)
            or bool(self._router and model == agent_primary_model and not use_channel_router)
        )
        recovery_model_list = self._config.llm_model_list
        if self._router and model == agent_primary_model and not use_channel_router:
            recovery_model_list = self._legacy_router_model_list or self._config.llm_model_list
        if not uses_router:
            keys = get_api_keys_for_model(model, self._config)
            if keys:
                call_kwargs["api_key"] = keys[0]
            call_kwargs.update(extra_litellm_params(model, self._config))
        call_kwargs = apply_litellm_generation_params(
            call_kwargs,
            model,
            self._get_temperature() if temperature is None else temperature,
            model_list=recovery_model_list,
        )
        diagnostics_level = normalize_prompt_cache_diagnostics_level(
            getattr(self._config, "llm_prompt_cache_diagnostics_level", "off")
        )
        if diagnostics_level != "off":
            route_context = build_provider_cache_route_context(
                model=model,
                call_kwargs=call_kwargs,
                model_list=recovery_model_list,
                call_type="agent",
            )
            caps = resolve_provider_cache_caps(route_context)
            logger.debug(
                "[PromptCache] agent diagnostics provider=%s api_surface=%s verification=%s activation=%s",
                caps.provider,
                caps.api_surface,
                caps.verification_status,
                caps.cache_activation,
            )
        register_fallback_model_pricing(
            resolve_fallback_litellm_wire_models(model, self._config.llm_model_list)
        )
        if use_channel_router and self._router and model in _router_model_names:
            # Channel / YAML path: Router manages all models in its model_list
            response = call_litellm_with_param_recovery(
                lambda kwargs: self._router.completion(**kwargs),
                model=model,
                call_kwargs=call_kwargs,
                model_list=recovery_model_list,
                logger=logger,
            )
        elif self._router and model == agent_primary_model and not use_channel_router:
            # Legacy path: Router for primary model multi-key
            response = call_litellm_with_param_recovery(
                lambda kwargs: self._router.completion(**kwargs),
                model=model,
                call_kwargs=call_kwargs,
                model_list=recovery_model_list,
                logger=logger,
            )
        else:
            # Legacy/direct-env path: direct call (also handles direct-env
            # providers like groq/ or bedrock/ that are not in the Router
            # model_list even when channel mode is active)
            response = call_litellm_with_param_recovery(
                lambda kwargs: litellm.completion(**kwargs),
                model=model,
                call_kwargs=call_kwargs,
                model_list=self._config.llm_model_list,
                logger=logger,
            )

        return self._parse_litellm_response(
            response,
            model,
            openai_messages,
            model_list=recovery_model_list,
        )

    def _get_temperature(self) -> float:
        """Return the raw configured temperature before per-model normalization."""
        return float(self._config.llm_temperature)

    def _convert_messages(
        self,
        messages: List[Dict[str, Any]],
        *,
        target_model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Convert internal message format to OpenAI-compatible format for litellm."""
        openai_messages: List[Dict[str, Any]] = []
        target_provider = self._trace_provider_for_target(target_model)
        for msg in messages:
            trace_matches_target = _message_trace_matches_target(
                msg,
                target_model,
                target_provider=target_provider,
            )
            if not trace_matches_target:
                continue
            if msg["role"] == "tool":
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", ""),
                    "content": msg["content"] if isinstance(msg["content"], str) else json.dumps(msg["content"]),
                })
            elif msg["role"] == "assistant" and msg.get("tool_calls"):
                openai_tc = []
                for tc in msg["tool_calls"]:
                    tc_dict: Dict[str, Any] = {
                        "id": tc.get("id", str(uuid.uuid4())[:8]),
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    provider_specific_fields = dict(tc.get("provider_specific_fields") or {})
                    sig = tc.get("thought_signature")
                    if sig is not None:
                        provider_specific_fields.setdefault("thought_signature", sig)
                    if provider_specific_fields:
                        tc_dict["provider_specific_fields"] = provider_specific_fields
                    openai_tc.append(tc_dict)
                content = (
                    msg.get("provider_blocks")
                    if msg.get("provider_blocks")
                    else msg.get("content")
                )
                openai_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": openai_tc,
                }
                if msg.get("reasoning_content") is not None:
                    openai_msg["reasoning_content"] = msg["reasoning_content"]
                openai_messages.append(openai_msg)
            else:
                openai_messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })
        return openai_messages

    def _trace_provider_for_target(self, target_model: Optional[str]) -> str:
        if not target_model:
            return ""
        model_list = getattr(getattr(self, "_config", None), "llm_model_list", []) or []
        return resolved_provider_namespace(target_model, model_list)

    def _parse_litellm_response(
        self,
        response: Any,
        model: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        *,
        model_list: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Parse litellm OpenAI-compatible response into LLMResponse."""
        choice = response.choices[0]
        tool_calls: List[ToolCall] = []

        provider_blocks, provider_text = _extract_provider_blocks(choice)

        # Handle MiniMax-specific content_blocks format
        # MiniMax-M3 may return content_blocks at choice level or inside message
        # Check both possible locations for content_blocks to ensure consistency
        # Concatenate ALL text blocks to avoid truncating multi-block responses
        text_content = choice.message.content
        if isinstance(text_content, list):
            text_content = provider_text
        if text_content is None:
            text_content = provider_text

        # DeepSeek/Qwen thinking mode; not in standard OpenAI type, accessed via getattr
        reasoning_content = getattr(choice.message, "reasoning_content", None)

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                args: Dict[str, Any] = {}
                if tc.function.arguments:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {"raw": tc.function.arguments}

                provider_specific_fields = _provider_specific_fields_from(
                    getattr(tc, "provider_specific_fields", None)
                )
                provider_specific_fields.update(
                    _provider_specific_fields_from(
                        getattr(tc.function, "provider_specific_fields", None)
                    )
                )
                sig = provider_specific_fields.get("thought_signature")
                if sig is None:
                    sig = getattr(tc, "thought_signature", None)

                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                    thought_signature=sig,
                    provider_specific_fields=provider_specific_fields,
                ))

        usage_model_list = (
            model_list
            if model_list is not None
            else getattr(getattr(self, "_config", None), "llm_model_list", []) or []
        )
        usage_model, provider_name = resolved_model_provider_identity(model, usage_model_list)
        usage_payload = extract_usage_payload(response)
        if usage_payload:
            usage = normalize_litellm_usage(
                usage_payload,
                model=usage_model or model,
                provider=provider_name,
            )
            usage = attach_message_hmacs(usage, messages)
            usage = filter_prompt_cache_telemetry(usage, getattr(self, "_config", None))
        else:
            usage = {}
        return LLMResponse(
            content=text_content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            provider_blocks=provider_blocks,
            usage=usage,
            provider=provider_name,
            model=model,
            raw=response,
        )


def register_fallback_model_pricing(models: Iterable[str]) -> None:
    """Register zero-cost pricing for unknown OpenAI-compatible models."""
    if not models:
        return
    register = getattr(litellm, "register_model", None)
    if not callable(register):
        return
    cost_map = getattr(litellm, "model_cost", {})
    if not isinstance(cost_map, dict):
        cost_map = {}
    for model in models:
        provider, wire_model = _split_provider_model(str(model))
        if provider != "openai":
            continue
        if not wire_model or wire_model.startswith("__legacy_"):
            continue
        custom_pricing = _CUSTOM_MODEL_PRICING.get(wire_model)
        if custom_pricing is not None:
            if wire_model in cost_map:
                continue
            try:
                register({wire_model: dict(custom_pricing)})
                logger.debug("Registered custom pricing for %s", wire_model)
            except Exception as exc:
                logger.debug(
                    "Custom pricing registration failed for %s, will try fallback pricing: %s",
                    wire_model,
                    exc,
                )
            else:
                continue
        if wire_model in cost_map or wire_model in _FALLBACK_MODEL_PRICING_REGISTERED:
            continue
        try:
            register({wire_model: dict(_FALLBACK_MODEL_PRICING)})
            _FALLBACK_MODEL_PRICING_REGISTERED.add(wire_model)
            logger.debug("Registered fallback pricing for %s", wire_model)
        except Exception as exc:
            logger.debug("Fallback pricing registration skipped for %s: %s", wire_model, exc)
