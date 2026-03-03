# -*- coding: utf-8 -*-
"""
Multi-provider LLM Tool-Calling Adapter.

Normalizes function-calling / tool-use across all providers into a unified
interface consumed by the AgentExecutor, via LiteLLM.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import litellm
from litellm import Router

from src.config import get_config

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
    raw: Any = None                        # raw provider response for debugging


# Models that auto-return reasoning_content; do NOT send extra_body (may cause 400).
_AUTO_THINKING_MODELS: List[str] = ["deepseek-reasoner", "deepseek-r1", "qwq"]

# Models that need explicit opt-in via extra_body; payload decoupled from model name.
_OPT_IN_THINKING_MODELS: Dict[str, dict] = {
    "deepseek-chat": {"thinking": {"type": "enabled"}},
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
        self._init_litellm()

    def _get_api_keys_for_model(self, model: str) -> List[str]:
        """Return API keys for the given litellm model based on provider prefix."""
        config = self._config
        if model.startswith("gemini/") or model.startswith("vertex_ai/"):
            return [k for k in config.gemini_api_keys if k and len(k) >= 8]
        if model.startswith("anthropic/"):
            return [k for k in config.anthropic_api_keys if k and len(k) >= 8]
        # openai/, deepseek/, or any other provider uses openai_api_keys
        return [k for k in config.openai_api_keys if k and len(k) >= 8]

    def _extra_litellm_params(self, model: str) -> dict:
        """Build extra litellm params (api_base, custom headers) for a model."""
        config = self._config
        params: Dict[str, Any] = {}
        if not model.startswith("gemini/") and not model.startswith("anthropic/") and not model.startswith("vertex_ai/"):
            if config.openai_base_url:
                params["api_base"] = config.openai_base_url
            if config.openai_base_url and "aihubmix.com" in config.openai_base_url:
                params["extra_headers"] = {"APP-Code": "GPIJ3886"}
        return params

    def _init_litellm(self) -> None:
        """Initialize litellm Router for multi-key, or flag single-key availability."""
        config = self._config
        litellm_model = config.litellm_model
        if not litellm_model:
            logger.warning("Agent LLM: LITELLM_MODEL not configured")
            return

        keys = self._get_api_keys_for_model(litellm_model)
        if not keys:
            logger.warning(f"Agent LLM: No API keys found for model {litellm_model}")
            return

        self._litellm_available = True

        if len(keys) > 1:
            extra_params = self._extra_litellm_params(litellm_model)
            model_list = [
                {
                    "model_name": litellm_model,
                    "litellm_params": {
                        "model": litellm_model,
                        "api_key": k,
                        **extra_params,
                    },
                }
                for k in keys
            ]
            self._router = Router(
                model_list=model_list,
                routing_strategy="simple-shuffle",
                num_retries=2,
            )
            models_in_router = list(dict.fromkeys(m["litellm_params"]["model"] for m in model_list))
            logger.info(f"Agent LLM: Router initialized with {len(keys)} keys for {litellm_model} (models: {models_in_router})")
        else:
            logger.info(f"Agent LLM: litellm initialized (model={litellm_model})")

    @property
    def is_available(self) -> bool:
        """True if litellm is configured and at least one API key is present."""
        return self._router is not None or self._litellm_available

    @property
    def primary_provider(self) -> str:
        """Provider name extracted from litellm_model prefix."""
        model = self._config.litellm_model or ""
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
        config = self._config
        models_to_try = [config.litellm_model] + (config.litellm_fallback_models or [])
        models_to_try = [m for m in models_to_try if m]

        last_error = None
        for model in models_to_try:
            try:
                return self._call_litellm_model(messages, tools, model)
            except Exception as e:
                logger.warning(f"Agent LLM call failed with {model}: {e}")
                last_error = e
                continue

        error_msg = f"All LLM models failed. Last error: {last_error}"
        logger.error(error_msg)
        return LLMResponse(content=error_msg, provider="error")

    def _call_litellm_model(
        self,
        messages: List[Dict[str, Any]],
        tools: List[dict],
        model: str,
    ) -> LLMResponse:
        """Call a specific litellm model with OpenAI-format messages and tools."""
        openai_messages = self._convert_messages(messages)

        # Use short model name (without provider prefix) for thinking model lookup
        model_short = model.split("/")[-1] if "/" in model else model

        call_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
            "temperature": self._get_temperature(model),
        }

        extra = get_thinking_extra_body(model_short)
        if extra:
            call_kwargs["extra_body"] = extra

        if tools:
            call_kwargs["tools"] = tools

        # Use Router for primary model (multi-key), direct litellm for others
        if self._router and model == self._config.litellm_model:
            response = self._router.completion(**call_kwargs)
        else:
            keys = self._get_api_keys_for_model(model)
            if keys:
                call_kwargs["api_key"] = keys[0]
            call_kwargs.update(self._extra_litellm_params(model))
            response = litellm.completion(**call_kwargs)

        return self._parse_litellm_response(response, model)

    def _get_temperature(self, model: str) -> float:
        """Return temperature from config based on provider prefix."""
        config = self._config
        if model.startswith("gemini/") or model.startswith("vertex_ai/"):
            return config.gemini_temperature
        if model.startswith("anthropic/"):
            return config.anthropic_temperature
        return config.openai_temperature

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
        text_content = choice.message.content
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
            raw=response,
        )
