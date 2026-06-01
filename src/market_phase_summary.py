# -*- coding: utf-8 -*-
"""Low-sensitivity public summary for Issue #1386 market phase context."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Dict, List, Optional

from src.core.trading_calendar import MarketPhase


MARKET_PHASE_SUMMARY_KEY = "market_phase_summary"

_ALLOWED_PHASES = tuple(phase.value for phase in MarketPhase)
_BOOLEAN_KEYS = ("is_trading_day", "is_market_open_now", "is_partial_bar")
_INTEGER_KEYS = ("minutes_to_open", "minutes_to_close")
_TEXT_KEYS = (
    "market",
    "market_local_time",
    "session_date",
    "effective_daily_bar_date",
    "trigger_source",
    "analysis_intent",
)
_SENSITIVE_MARKERS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "credential",
    "webhook",
)


def render_market_phase_summary(phase_context: Any) -> Optional[Dict[str, Any]]:
    """Project a runtime MarketPhaseContext dict into a stable public summary."""
    payload = _as_mapping(phase_context)
    if not payload:
        return None

    phase = _safe_phase(payload.get("phase"))
    if phase is None:
        return None

    summary: Dict[str, Any] = {"phase": phase}
    for key in _TEXT_KEYS:
        summary[key] = _safe_text(payload.get(key)) or None
    for key in _BOOLEAN_KEYS:
        summary[key] = payload.get(key) if isinstance(payload.get(key), bool) else None
    for key in _INTEGER_KEYS:
        summary[key] = _safe_int(payload.get(key))
    summary["warnings"] = _list_strings(payload.get("warnings"))
    return summary


def extract_market_phase_summary(context_snapshot: Any) -> Optional[Dict[str, Any]]:
    """Extract and re-sanitize a persisted market phase summary."""
    snapshot = _as_mapping(context_snapshot)
    if not snapshot:
        return None
    summary = snapshot.get(MARKET_PHASE_SUMMARY_KEY)
    if not isinstance(summary, Mapping):
        return None
    return render_market_phase_summary(summary)


def _as_mapping(value: Any) -> Optional[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, Mapping) else None
    return None


def _safe_phase(value: Any) -> Optional[str]:
    text = _safe_text(value)
    return text if text in _ALLOWED_PHASES else None


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (Mapping, list, tuple, set)):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    lowered = text.lower()
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        return "[REDACTED]"
    return text


def _safe_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _list_strings(value: Any, *, limit: int = 5) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        text = _safe_text(item)
        if text and text not in result:
            result.append(text)
    return result[:limit]
