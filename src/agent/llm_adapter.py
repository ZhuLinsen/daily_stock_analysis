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
from typing import Any, Dict, List, Optional

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

logger = logging.getLogger(__name__)


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


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider."""
    content: Optional[str] = None          # text response (final answer)
    tool_calls: List[ToolCall] = field(default_factory=list)  # tool calls to execute
    reasoning_content: Optional[str] = None  # Chain-of-thought (CoT) from DeepSeek thinking mode; must be passed back in multi-turn assistant messages; None for other providers
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

# Custom model pricing for models not in LiteLLM's built-in price list
# Official MiniMax pricing: https://platform.minimax.io/docs/guides/pricing-paygo
# - MiniMax-M2.7 / M2.5: $0.3/M input tokens, $1.2/M output tokens
_CUSTOM_MODEL_PRICING: Dict[str, dict] = {
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
    "MiniMax-M2.5": {
        "supports_function_calling": True,
        "supports_vision": False,
        "supports_audio_input": False,
        "supports_audio_output": False,
        "context_window": 100000,
        "max_tokens": 10000,
        "input_cost_per_token": 0.0000003,   # $0.3 / 1M tokens
        "output_cost_per_token": 0.0000012,   # $1.2 / 1M tokens
    },
}


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
        self._litellm_available = False
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
        litellm_model = get_effective_agent_primary_model(config)
        if not litellm_model:
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
        models_to_try = get_effective_agent_models_to_try(config)
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
            except litellm.RateLimitError as e:
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
            except litellm.ContextWindowExceededError as e:
                logger.warning("Agent LLM context window exceeded on %s: %s", model, e)
                last_error = e
                continue
            except Exception as e:
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
        openai_messages = self._convert_messages(messages)

        # Use short model name (without provider prefix) for thinking model lookup
        model_short = model.split("/")[-1] if "/" in model else model

        call_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
            "temperature": self._get_temperature(model) if temperature is None else temperature,
        }
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens
        if timeout is not None:
            call_kwargs["timeout"] = timeout

        extra = get_thinking_extra_body(model_short)
        if extra:
            call_kwargs["extra_body"] = extra

        if tools:
            call_kwargs["tools"] = tools

        # Use Router for primary model (multi-key), direct litellm for others
        use_channel_router = self._has_channel_config()
        _router_model_names = set(get_configured_llm_models(self._config.llm_model_list))
        agent_primary_model = get_effective_agent_primary_model(self._config)
        if use_channel_router and self._router and model in _router_model_names:
            # Channel / YAML path: Router manages all models in its model_list
            response = self._router.completion(**call_kwargs)
        elif self._router and model == agent_primary_model and not use_channel_router:
            # Legacy path: Router for primary model multi-key
            response = self._router.completion(**call_kwargs)
        else:
            # Legacy/direct-env path: direct call (also handles direct-env
            # providers like groq/ or bedrock/ that are not in the Router
            # model_list even when channel mode is active)
            keys = get_api_keys_for_model(model, self._config)
            if keys:
                call_kwargs["api_key"] = keys[0]
            call_kwargs.update(extra_litellm_params(model, self._config))
            response = litellm.completion(**call_kwargs)

        return self._parse_litellm_response(response, model)

    def _get_temperature(self, model: str) -> float:
        """Return unified temperature from config."""
        return self._config.llm_temperature

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert internal message format to OpenAI-compatible format for litellm."""
        openai_messages: List[Dict[str, Any]] = []
        for msg in messages:
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
                    sig = tc.get("thought_signature")
                    if sig is not None:
                        tc_dict["provider_specific_fields"] = {"thought_signature": sig}
                    openai_tc.append(tc_dict)
                openai_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.get("content"),
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

    def _parse_litellm_response(self, response: Any, model: str) -> LLMResponse:
        """Parse litellm OpenAI-compatible response into LLMResponse."""
        choice = response.choices[0]
        tool_calls: List[ToolCall] = []

        # Handle MiniMax-specific content_blocks format
        # MiniMax-M2.7 may return content_blocks at choice level or inside message
        # Check both possible locations for content_blocks to ensure consistency
        # Concatenate ALL text blocks to avoid truncating multi-block responses
        text_content = choice.message.content
        if text_content is None:
            content_blocks = None
            if hasattr(choice, "content_blocks"):
                content_blocks = choice.content_blocks
            elif hasattr(choice.message, "content_blocks"):
                content_blocks = choice.message.content_blocks

            if content_blocks:
                # MiniMax response format: content_blocks[].text
                # Concatenate ALL text blocks to preserve complete response
                text_parts = []
                for block in content_blocks:
                    if getattr(block, "type", None) == "text":
                        text = getattr(block, "text", "") or ""
                        if text:
                            text_parts.append(text)
                    elif hasattr(block, "content") and block.content:
                        text_parts.append(block.content)
                text_content = "".join(text_parts).strip()

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

                # Extract thought_signature: stored in provider_specific_fields (Gemini 3 via LiteLLM proxy)
                psf = getattr(tc, "provider_specific_fields", None)
                if psf is not None:
                    sig = psf.get("thought_signature") if isinstance(psf, dict) else getattr(psf, "thought_signature", None)
                else:
                    func_psf = getattr(tc.function, "provider_specific_fields", None)
                    if func_psf is not None:
                        sig = func_psf.get("thought_signature") if isinstance(func_psf, dict) else getattr(func_psf, "thought_signature", None)
                    else:
                        sig = getattr(tc, "thought_signature", None)

                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                    thought_signature=sig,
                ))

        usage: Dict[str, Any] = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        provider_name = model.split("/")[0] if "/" in model else model
        return LLMResponse(
            content=text_content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            usage=usage,
            provider=provider_name,
            model=model,
            raw=response,
        )
