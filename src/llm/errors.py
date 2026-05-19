# -*- coding: utf-8 -*-
"""LiteLLM error classification and one-shot parameter recovery."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from src.llm.generation_params import (
    GenerationParamRecovery,
    apply_litellm_param_recovery,
    remember_litellm_generation_param_recovery,
)

_UNSUPPORTED_PARAM_MARKERS = (
    "unsupported",
    "not supported",
    "unrecognized",
    "unknown parameter",
    "not allowed",
    "invalid parameter",
    "does not support",
)

_TEMPERATURE_VALUE_PATTERN = r"-?\d+(?:\.\d+)?"
_ALLOWED_TEMPERATURE_PATTERNS = (
    re.compile(
        rf"\bonly\s+(?:the\s+)?(?:default\s+)?(?:temperature\s+)?(?:value\s+)?[\(`'\"]*(?P<value>{_TEMPERATURE_VALUE_PATTERN})(?!\w)"
    ),
    re.compile(
        rf"\bdefault(?:\s+temperature)?(?:\s+value)?\s*(?:is|=|:)\s*[\(`'\"]*(?P<value>{_TEMPERATURE_VALUE_PATTERN})(?!\w)"
    ),
)


def _collect_error_text(value: Any, seen: Optional[set] = None) -> List[str]:
    if seen is None:
        seen = set()
    if value is None:
        return []
    value_id = id(value)
    if value_id in seen:
        return []
    seen.add(value_id)

    chunks = [str(value)]
    if isinstance(value, BaseException):
        chunks.extend(_collect_error_text(getattr(value, "args", None), seen))
    if isinstance(value, dict):
        for item in value.values():
            chunks.extend(_collect_error_text(item, seen))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            chunks.extend(_collect_error_text(item, seen))
    else:
        for attr in ("message", "body", "response", "llm_provider", "param"):
            if hasattr(value, attr):
                chunks.extend(_collect_error_text(getattr(value, attr), seen))
    return chunks


def _normalized_error_text(error: BaseException) -> str:
    return " ".join(chunk for chunk in _collect_error_text(error) if chunk).lower()


def _parse_allowed_temperature(text: str) -> Optional[float]:
    for segment in re.split(r"(?<!\d)\.(?!\d)|[!?;\n]+", text):
        if "only" not in segment:
            continue
        for pattern in _ALLOWED_TEMPERATURE_PATTERNS:
            match = pattern.search(segment[segment.find("only") :])
            if match is None:
                continue
            value = float(match.group("value"))
            if 0 <= value <= 2:
                return value
    return None


def classify_litellm_generation_param_error(
    error: BaseException,
) -> Optional[GenerationParamRecovery]:
    """Classify explicit provider parameter errors into a safe one-shot recovery."""
    text = _normalized_error_text(error)
    if not text:
        return None

    if "temperature" in text:
        allowed_temperature = _parse_allowed_temperature(text)
        if allowed_temperature is not None:
            return GenerationParamRecovery(
                set_params={"temperature": allowed_temperature},
                reason="temperature_default_only",
            )
        if "only" in text and "default" in text:
            return GenerationParamRecovery(
                omit_params=("temperature",),
                reason="temperature_default_only",
            )
        if any(marker in text for marker in _UNSUPPORTED_PARAM_MARKERS):
            return GenerationParamRecovery(
                omit_params=("temperature",),
                reason="temperature_unsupported",
            )

    for param in ("top_p", "presence_penalty", "frequency_penalty", "seed"):
        if param in text and any(marker in text for marker in _UNSUPPORTED_PARAM_MARKERS):
            return GenerationParamRecovery(
                omit_params=(param,),
                reason=f"{param}_unsupported",
            )
    return None


def call_litellm_with_param_recovery(
    call: Callable[[Dict[str, Any]], Any],
    *,
    model: str,
    call_kwargs: Dict[str, Any],
    model_list: Optional[List[Dict[str, Any]]] = None,
    cache_recovery: bool = True,
    logger: Optional[Any] = None,
    log_label: str = "[LiteLLM]",
) -> Any:
    """Call LiteLLM once, then retry once for explicit generation-parameter errors."""
    effective_kwargs = dict(call_kwargs)
    try:
        return call(effective_kwargs)
    except Exception as exc:
        recovery = classify_litellm_generation_param_error(exc)
        if recovery is None:
            raise
        retry_kwargs = apply_litellm_param_recovery(effective_kwargs, recovery)
        if retry_kwargs == effective_kwargs:
            raise
        if logger is not None:
            logger.warning(
                "%s %s generation parameter rejected (%s), retrying once with request-scoped recovery",
                log_label,
                model,
                recovery.reason,
            )
        response = call(retry_kwargs)
        if cache_recovery:
            remember_litellm_generation_param_recovery(
                model,
                recovery,
                model_list=model_list,
                request_overrides=retry_kwargs,
            )
        return response
