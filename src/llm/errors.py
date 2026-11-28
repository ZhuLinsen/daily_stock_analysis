# -*- coding: utf-8 -*-
"""LiteLLM error classification and one-shot parameter recovery."""

from __future__ import annotations

import math
import re
import time
from typing import Any, Callable, Dict, List, Optional

from src.core.stock_execution_context import get_current_stock_cancellation, raise_if_stock_cancelled
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

    if "max_tokens" in text and "max_completion_tokens" in text:
        if (
            "use 'max_completion_tokens'" in text
            or 'use "max_completion_tokens"' in text
            or "use max_completion_tokens" in text
            or ("max_tokens" in text and any(marker in text for marker in _UNSUPPORTED_PARAM_MARKERS))
        ):
            if "max_completion_tokens" in text and "use 'max_tokens'" not in text and 'use "max_tokens"' not in text:
                if (
                    "max_completion_tokens" in text
                    and any(
                        phrase in text
                        for phrase in (
                            "max_completion_tokens is not supported",
                            "max_completion_tokens' is not supported",
                            "unsupported parameter: 'max_completion_tokens'",
                            'unsupported parameter: "max_completion_tokens"',
                            "unrecognized request argument supplied: max_completion_tokens",
                            "unknown parameter: 'max_completion_tokens'",
                        )
                    )
                ):
                    return GenerationParamRecovery(
                        rename_params={"max_completion_tokens": "max_tokens"},
                        reason="max_completion_tokens_use_max_tokens",
                    )
                return GenerationParamRecovery(
                    rename_params={"max_tokens": "max_completion_tokens"},
                    reason="max_tokens_use_max_completion_tokens",
                )
        if "use 'max_tokens'" in text or 'use "max_tokens"' in text or "use max_tokens" in text:
            return GenerationParamRecovery(
                rename_params={"max_completion_tokens": "max_tokens"},
                reason="max_completion_tokens_use_max_tokens",
            )
    elif "max_completion_tokens" in text and any(marker in text for marker in _UNSUPPORTED_PARAM_MARKERS):
        return GenerationParamRecovery(
            rename_params={"max_completion_tokens": "max_tokens"},
            reason="max_completion_tokens_use_max_tokens",
        )
    elif "max_tokens" in text and any(marker in text for marker in _UNSUPPORTED_PARAM_MARKERS):
        return GenerationParamRecovery(
            rename_params={"max_tokens": "max_completion_tokens"},
            reason="max_tokens_use_max_completion_tokens",
        )

    if "stream_options" in text and any(marker in text for marker in _UNSUPPORTED_PARAM_MARKERS):
        return GenerationParamRecovery(
            omit_params=("stream_options",),
            reason="stream_options_unsupported",
        )

    for param in ("top_p", "presence_penalty", "frequency_penalty", "seed"):
        if param in text and any(marker in text for marker in _UNSUPPORTED_PARAM_MARKERS):
            return GenerationParamRecovery(
                omit_params=(param,),
                reason=f"{param}_unsupported",
            )
    return None


def _extract_recovery_timeout_seconds(raw_timeout: Any) -> Optional[float]:
    """Extract a positive finite timeout in seconds from float, tuple/list, or httpx.Timeout (P1-8)."""
    if raw_timeout is None or raw_timeout == "":
        return None
    if isinstance(raw_timeout, (int, float)) and not isinstance(raw_timeout, bool):
        val = float(raw_timeout)
        return val if math.isfinite(val) and val > 0 else None
    if isinstance(raw_timeout, (tuple, list)):
        nums = [
            float(v)
            for v in raw_timeout
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) and float(v) > 0
        ]
        return max(nums) if nums else None
    read_v = getattr(raw_timeout, "read", None)
    connect_v = getattr(raw_timeout, "connect", None)
    write_v = getattr(raw_timeout, "write", None)
    pool_v = getattr(raw_timeout, "pool", None)
    nums = [
        float(v)
        for v in (read_v, connect_v, write_v, pool_v)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) and float(v) > 0
    ]
    return max(nums) if nums else None


def _clamp_recovery_timeout(raw_timeout: Any, remaining: float) -> Any:
    """Clamp float, tuple/list, or httpx.Timeout per-phase without lengthening any phase (F9)."""
    if raw_timeout is None or raw_timeout == "":
        return remaining
    if isinstance(raw_timeout, (int, float)) and not isinstance(raw_timeout, bool):
        val = float(raw_timeout)
        return min(val, remaining) if math.isfinite(val) and val >= 0 else remaining
    if isinstance(raw_timeout, tuple):
        return tuple(
            min(float(v), remaining)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) and float(v) >= 0
            else (remaining if v is None else v)
            for v in raw_timeout
        )
    if isinstance(raw_timeout, list):
        return [
            min(float(v), remaining)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) and float(v) >= 0
            else (remaining if v is None else v)
            for v in raw_timeout
        ]
    if all(hasattr(raw_timeout, attr) for attr in ("connect", "read", "write", "pool")):
        clamped_phases: Dict[str, Any] = {}
        for attr in ("connect", "read", "write", "pool"):
            phase_val = getattr(raw_timeout, attr, None)
            if isinstance(phase_val, (int, float)) and not isinstance(phase_val, bool) and math.isfinite(float(phase_val)) and float(phase_val) >= 0:
                clamped_phases[attr] = min(float(phase_val), remaining)
            else:
                clamped_phases[attr] = remaining
        try:
            return type(raw_timeout)(**clamped_phases)
        except Exception:
            return remaining
    return remaining


def _without_native_internal_keys(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in kwargs.items() if not str(k).startswith("_dsa_")}


def _is_native_transport_error(exc: BaseException) -> bool:
    try:
        from src.llm.native_types import NativeAPIError

        return isinstance(exc, NativeAPIError)
    except Exception:
        return False


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
    """Call LiteLLM once, then retry once for explicit generation-parameter errors.

    Enforces a single monotonic deadline across the initial attempt and any
    one-shot parameter-recovery retry (P1-6, P1-8), including tuple/httpx.Timeout
    values and calls without an active stock cancellation token.
    """
    timeout_seconds = _extract_recovery_timeout_seconds(call_kwargs.get("timeout"))
    call_deadline: Optional[float] = (
        time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    )

    def invoke(kwargs: Dict[str, Any], *, is_retry: bool = False) -> Any:
        raise_if_stock_cancelled()
        token = get_current_stock_cancellation()
        stock_remaining = token.remaining_seconds() if token is not None else None
        if stock_remaining is not None and stock_remaining <= 0:
            raise_if_stock_cancelled()

        effective_remaining: Optional[float] = stock_remaining
        if call_deadline is not None and (is_retry or stock_remaining is not None):
            deadline_remaining = call_deadline - time.monotonic()
            if deadline_remaining <= 0:
                raise TimeoutError("LLM request timed out before parameter-recovery retry")
            effective_remaining = (
                deadline_remaining
                if effective_remaining is None
                else min(effective_remaining, deadline_remaining)
            )

        if effective_remaining is None:
            return call(kwargs)

        clamped_timeout = _clamp_recovery_timeout(kwargs.get("timeout"), effective_remaining)
        # Keep the Router's same-model deployment retries. The stock executor
        # enforces the batch deadline even if the SDK is still retrying.
        response = call({**kwargs, "timeout": clamped_timeout})
        raise_if_stock_cancelled()
        return response

    effective_kwargs = dict(call_kwargs)
    try:
        return invoke(effective_kwargs, is_retry=False)
    except Exception as exc:
        recovery = classify_litellm_generation_param_error(exc)
        if recovery is None:
            raise
        retry_kwargs = apply_litellm_param_recovery(effective_kwargs, recovery)
        if retry_kwargs == effective_kwargs:
            raise
        # P1-6a: On non-native (LiteLLM) errors, native-only _dsa_* directives are stripped,
        # so do not waste a duplicate identical retry if only _dsa_* keys changed.
        if (
            not _is_native_transport_error(exc)
            and _without_native_internal_keys(retry_kwargs) == _without_native_internal_keys(effective_kwargs)
        ):
            raise
        if logger is not None:
            logger.warning(
                "%s %s generation parameter rejected (%s), retrying once with request-scoped recovery",
                log_label,
                model,
                recovery.reason,
            )
        response = invoke(retry_kwargs, is_retry=True)
        if cache_recovery:
            remember_litellm_generation_param_recovery(
                model,
                recovery,
                model_list=model_list,
                request_overrides=retry_kwargs,
            )
        return response
