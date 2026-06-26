# -*- coding: utf-8 -*-
"""Provider-specific protocol trace helpers for Agent chat.

These helpers keep opaque thinking/tool-call protocol material on a separate
track from user-visible conversation history.  The persisted payload is the
minimal provider protocol slice required for roundtrip:

    assistant(tool_calls + reasoning/thinking metadata) -> tool ...

Final assistant text is intentionally excluded because it is already stored in
``conversation_messages`` and merged back by id anchor.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.llm.generation_params import resolve_litellm_wire_model


PROVIDER_TRACE_RETENTION_LIMIT = 3
TRACE_PROVIDER_KEY = "_trace_provider"
TRACE_MODEL_KEY = "_trace_model"

THINKING_BLOCK_TYPES = {"thinking", "redacted_thinking", "signature"}


@dataclass
class ProviderTraceTurn:
    """One persisted provider protocol turn for a completed chat run."""

    session_id: str = ""
    run_id: str = ""
    provider: str = ""
    model: str = ""
    anchor_user_message_id: int = 0
    anchor_assistant_message_id: int = 0
    messages: List[Dict[str, Any]] = field(default_factory=list)
    contains_reasoning: bool = False
    contains_tool_calls: bool = False
    contains_thinking_blocks: bool = False
    must_roundtrip: bool = False
    estimated_tokens: int = 0


@dataclass
class TraceDiagnostics:
    """Structured trace context diagnostics for tests and server logs."""

    trace_injected: bool = False
    trace_dropped_reason: str = ""
    trace_tokens: int = 0
    visible_tokens: int = 0
    retention_trimmed_count: int = 0
    dropped_trace_count: int = 0
    mixed_model_trace: bool = False
    model_mismatch: int = 0
    anchor_summarized: int = 0
    budget_exceeded: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_injected": self.trace_injected,
            "trace_dropped_reason": self.trace_dropped_reason,
            "trace_tokens": self.trace_tokens,
            "visible_tokens": self.visible_tokens,
            "retention_trimmed_count": self.retention_trimmed_count,
            "dropped_trace_count": self.dropped_trace_count,
            "mixed_model_trace": self.mixed_model_trace,
            "model_mismatch": self.model_mismatch,
            "anchor_summarized": self.anchor_summarized,
            "budget_exceeded": self.budget_exceeded,
        }


def normalize_model_name(model: Any) -> str:
    """Normalize a model string for exact trace compatibility checks."""
    return str(model or "").strip().lower()


def provider_namespace(model: Any) -> str:
    """Return the provider namespace used by LiteLLM-style model strings."""
    normalized = normalize_model_name(model)
    if not normalized:
        return ""
    if "/" in normalized:
        return normalized.split("/", 1)[0]
    return "openai"


def resolved_provider_namespace(
    model: Any,
    model_list: Optional[Sequence[Dict[str, Any]]] = None,
) -> str:
    """Resolve router aliases before deriving the provider namespace."""
    return resolved_model_provider_identity(model, model_list)[1]


def resolved_model_provider_identity(
    model: Any,
    model_list: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    """Resolve router aliases to the LiteLLM wire model and provider namespace."""
    normalized = str(model or "").strip()
    if not normalized:
        return "", ""
    wire_model = resolve_litellm_wire_model(normalized, list(model_list or []))
    return wire_model, provider_namespace(wire_model)


def trace_model_matches(
    trace_provider: Any,
    trace_model: Any,
    current_model: Any,
    *,
    current_provider: Any = None,
) -> bool:
    """Return True only when provider namespace and full model string match."""
    trace_model_normalized = normalize_model_name(trace_model)
    current_model_normalized = normalize_model_name(current_model)
    if not trace_model_normalized or not current_model_normalized:
        return False
    if trace_model_normalized != current_model_normalized:
        return False
    provider_normalized = normalize_model_name(trace_provider)
    expected_provider = normalize_model_name(current_provider) or provider_namespace(current_model_normalized)
    return provider_normalized == expected_provider


def estimate_protocol_tokens(messages: Sequence[Dict[str, Any]]) -> int:
    """Cheap deterministic estimate used only for trace budget decisions."""
    payload = json.dumps(messages, ensure_ascii=False, default=str)
    return int(math.ceil(len(payload) / 3))


def extract_provider_trace_turns(
    messages: Sequence[Dict[str, Any]],
    *,
    baseline_len: int,
    run_id: str = "",
    anchor_user_message_id: int = 0,
    anchor_assistant_message_id: int = 0,
) -> Tuple[List[ProviderTraceTurn], TraceDiagnostics]:
    """Extract this run's provider trace from ``messages[baseline_len:]``.

    Only the current run's appended tool-loop protocol messages are considered.
    Existing traces injected into the request live before ``baseline_len`` and
    are therefore not persisted again.
    """
    diagnostics = TraceDiagnostics()
    protocol_messages: List[Dict[str, Any]] = []
    providers: set[str] = set()
    models: set[str] = set()
    contains_reasoning = False
    contains_tool_calls = False
    contains_thinking_blocks = False
    contains_provider_specific_fields = False

    for raw_msg in list(messages)[max(0, int(baseline_len)) :]:
        role = raw_msg.get("role")
        if role == "assistant" and raw_msg.get("tool_calls"):
            provider = normalize_model_name(raw_msg.get(TRACE_PROVIDER_KEY))
            model = normalize_model_name(raw_msg.get(TRACE_MODEL_KEY))
            if provider:
                providers.add(provider)
            if model:
                models.add(model)

            contains_tool_calls = True
            contains_reasoning = contains_reasoning or raw_msg.get("reasoning_content") is not None
            contains_thinking_blocks = contains_thinking_blocks or message_contains_thinking_blocks(raw_msg)
            contains_provider_specific_fields = (
                contains_provider_specific_fields
                or _tool_calls_have_provider_specific_fields(raw_msg.get("tool_calls") or [])
            )
            protocol_messages.append(strip_trace_metadata(raw_msg))
            continue

        if role == "tool" and protocol_messages:
            protocol_messages.append(strip_trace_metadata(raw_msg))

    if not protocol_messages or not contains_tool_calls:
        return [], diagnostics

    if len(providers) != 1 or len(models) != 1:
        diagnostics.mixed_model_trace = True
        diagnostics.trace_dropped_reason = "mixed_model_trace"
        diagnostics.dropped_trace_count = 1
        return [], diagnostics

    provider = next(iter(providers))
    model = next(iter(models))
    if provider == "deepseek":
        must_roundtrip = contains_tool_calls and contains_reasoning
    elif provider == "anthropic":
        must_roundtrip = contains_tool_calls and contains_thinking_blocks
    else:
        must_roundtrip = contains_tool_calls and (
            contains_reasoning or contains_thinking_blocks or contains_provider_specific_fields
        )
    if not must_roundtrip:
        diagnostics.trace_dropped_reason = "not_required"
        diagnostics.dropped_trace_count = 1
        return [], diagnostics

    trace = ProviderTraceTurn(
        run_id=run_id,
        provider=provider,
        model=model,
        anchor_user_message_id=int(anchor_user_message_id or 0),
        anchor_assistant_message_id=int(anchor_assistant_message_id or 0),
        messages=protocol_messages,
        contains_reasoning=contains_reasoning,
        contains_tool_calls=contains_tool_calls,
        contains_thinking_blocks=contains_thinking_blocks,
        must_roundtrip=True,
        estimated_tokens=estimate_protocol_tokens(protocol_messages),
    )
    diagnostics.trace_tokens = trace.estimated_tokens
    return [trace], diagnostics


def strip_trace_metadata(message: Dict[str, Any]) -> Dict[str, Any]:
    """Return a JSON-safe message without internal trace routing metadata."""
    return {
        key: _strip_trace_metadata_value(value)
        for key, value in message.items()
        if not str(key).startswith("_trace_")
    }


def message_contains_thinking_blocks(message: Dict[str, Any]) -> bool:
    """Detect Claude/Gemini opaque thinking blocks in known message locations."""
    candidates: List[Any] = []
    for key in ("provider_blocks", "content", "thinking_blocks"):
        if key in message:
            candidates.append(message.get(key))
    return any(_contains_thinking_block(candidate) for candidate in candidates)


def _contains_thinking_block(value: Any) -> bool:
    if isinstance(value, dict):
        block_type = str(value.get("type") or "").strip()
        if block_type in THINKING_BLOCK_TYPES:
            return True
        return any(_contains_thinking_block(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_thinking_block(item) for item in value)
    return False


def _tool_calls_have_provider_specific_fields(tool_calls: Iterable[Dict[str, Any]]) -> bool:
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        if tool_call.get("provider_specific_fields"):
            return True
        if tool_call.get("thought_signature") is not None:
            return True
    return False


def _strip_trace_metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_trace_metadata_value(child)
            for key, child in value.items()
            if not str(key).startswith("_trace_")
        }
    if isinstance(value, list):
        return [_strip_trace_metadata_value(item) for item in value]
    return value
