# -*- coding: utf-8 -*-
"""Shared reasoning-effort (thinking level) handling for every LiteLLM call path.

Reasoning models spend part of their output budget on internal thinking. This module
is the single source of truth for how that level is named, normalized, read from the
environment, and attached to an outgoing LiteLLM request.

Two defaults exist on purpose:

* General analysis paths (chat, single-stock analysis, market review) default to
  ``auto`` — no parameter is sent, so behavior matches the provider default and
  nothing changes for deployments that never opt in.
* Screening's candidate re-rank defaults to ``high``: it compares candidates against
  each other and is the most reasoning-heavy step in the product.

Setting ``LLM_REASONING_EFFORT`` overrides both.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

REASONING_EFFORT_ENV = "LLM_REASONING_EFFORT"
#: Levels accepted by OpenAI-compatible gateways, lowest thinking first.
#: The set matches what the LLMGates gateway reports when it rejects a bad value:
#: ``reasoning_effort must be one of: none, minimal, low, medium, high, xhigh, max``.
#: Providers that do not know a level reject the request, and
#: ``classify_litellm_generation_param_error`` drops the parameter for one retry.
REASONING_EFFORT_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
#: Values meaning "send nothing and let the provider decide".
#: ``none`` is deliberately NOT here: providers treat it as an explicit
#: "do not think" level, which is different from omitting the parameter.
PASSTHROUGH_VALUES = ("", "auto", "default", "provider_default")
#: Chat / single-stock analysis / market review keep the provider default unless asked.
DEFAULT_ANALYSIS_REASONING_EFFORT = "auto"
#: Screening's re-rank is the most reasoning-heavy step, so it leans high.
DEFAULT_SCREENING_REASONING_EFFORT = "high"


def normalize_reasoning_effort(value: Any, *, fallback: str = DEFAULT_ANALYSIS_REASONING_EFFORT) -> str:
    """Normalize a level; returns "" when the parameter should not be sent."""
    text = str(value or "").strip().lower()
    if text in PASSTHROUGH_VALUES:
        return ""
    if text in REASONING_EFFORT_LEVELS:
        return text
    logger.warning(
        "Unknown %s=%r, falling back to %r (valid: %s, or auto to leave unset)",
        REASONING_EFFORT_ENV,
        value,
        fallback,
        ", ".join(REASONING_EFFORT_LEVELS),
    )
    return normalize_reasoning_effort(fallback, fallback="") if fallback else ""


def resolve_reasoning_effort(*, default: str = DEFAULT_ANALYSIS_REASONING_EFFORT) -> str:
    """Read the configured level from the environment, applying a per-caller default."""
    raw = os.getenv(REASONING_EFFORT_ENV)
    if raw is None:
        return normalize_reasoning_effort(default, fallback=default)
    return normalize_reasoning_effort(raw, fallback=default)


def apply_reasoning_effort(call_kwargs: Dict[str, Any], level: Optional[str]) -> Dict[str, Any]:
    """Attach the level to LiteLLM kwargs in place; a blank level is a no-op.

    LiteLLM only forwards ``reasoning_effort`` for models its own map declares as
    supporting it. Custom model names behind OpenAI-compatible gateways (for example
    ``openai/glm-5.3``) raise ``UnsupportedParamsError`` locally, so the request never
    leaves the process. ``allowed_openai_params`` is LiteLLM's explicit opt-in for
    exactly this case. ``classify_litellm_generation_param_error`` drops both together
    for one retry when a backend rejects them, so unsupported providers degrade to the
    default thinking behavior instead of failing the call.
    """
    normalized = normalize_reasoning_effort(level, fallback="")
    if not normalized:
        return call_kwargs
    call_kwargs["reasoning_effort"] = normalized
    allowed = call_kwargs.get("allowed_openai_params")
    merged = list(allowed) if isinstance(allowed, (list, tuple)) else []
    if "reasoning_effort" not in merged:
        merged.append("reasoning_effort")
    call_kwargs["allowed_openai_params"] = merged
    return call_kwargs
