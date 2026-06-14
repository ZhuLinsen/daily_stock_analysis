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
_INTRADAY_BUCKET_PHASES = {"intraday", "lunch_break", "closing_auction"}
_PUBLIC_SOURCE_LABELS_ZH = {
    "alert_trigger_market_context": "告警触发上下文",
    "analysis_history_snapshot": "最近分析快照",
    "evaluator_snapshot": "评估器快照",
    "legacy_text": "历史文本",
}
_PUBLIC_SOURCE_LABELS_EN = {
    "alert_trigger_market_context": "alert trigger context",
    "analysis_history_snapshot": "recent analysis snapshot",
    "evaluator_snapshot": "evaluator snapshot",
    "legacy_text": "legacy text",
}
_MARKET_STATUS_PREFIX = {
    "zh": "市场状态",
    "en": "Market status",
}
_MARKET_LABELS_ZH = {
    "cn": "A股",
    "hk": "港股",
    "us": "美股",
}
_MARKET_LABELS_EN = {
    "cn": "A-shares",
    "hk": "Hong Kong",
    "us": "US",
}
_PHASE_LABELS_ZH = {
    "premarket": "盘前",
    "intraday": "盘中",
    "lunch_break": "午间休市",
    "closing_auction": "临近收盘",
    "postmarket": "盘后",
    "non_trading": "非交易日",
    "unknown": "阶段未知",
}
_PHASE_LABELS_EN = {
    "premarket": "Pre-market",
    "intraday": "Intraday",
    "lunch_break": "Lunch break",
    "closing_auction": "Near close",
    "postmarket": "Post-market",
    "non_trading": "Non-trading",
    "unknown": "Unknown phase",
}


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


def normalize_analysis_phase_bucket(value: Any) -> str:
    """Fold detailed phase labels into the public backtest/statistics buckets."""
    phase = _safe_text(value)
    if phase == "premarket":
        return "premarket"
    if phase in _INTRADAY_BUCKET_PHASES:
        return "intraday"
    if phase == "postmarket":
        return "postmarket"
    return "unknown"


def format_public_phase_pack_excerpt(
    market_phase_summary: Any,
    analysis_context_pack_overview: Any = None,
    *,
    source: Optional[str] = None,
    report_language: str = "zh",
) -> str:
    """Format a low-sensitivity phase/pack excerpt for notifications."""
    phase_summary = _as_mapping(market_phase_summary)
    overview = _as_mapping(analysis_context_pack_overview)
    if not phase_summary and not overview:
        return ""
    lang = "en" if str(report_language or "").lower().startswith("en") else "zh"
    source_label = _source_label(source, lang)

    lines: List[str] = []
    if phase_summary:
        phase = _safe_text(phase_summary.get("phase")) or "unknown"
        market = _safe_text(phase_summary.get("market"))
        trigger_source = _safe_text(phase_summary.get("trigger_source"))
        if lang == "en":
            parts = [f"phase: {phase}"]
            if market:
                parts.append(f"market: {market}")
            if trigger_source:
                parts.append(f"trigger: {trigger_source}")
            if source_label:
                parts.append(f"source: {source_label}")
            lines.append("- " + " | ".join(parts))
            if phase_summary.get("is_partial_bar") is True:
                lines.append("- partial-bar warning: intraday data may be incomplete")
        else:
            parts = [f"阶段：{phase}"]
            if market:
                parts.append(f"市场：{market}")
            if trigger_source:
                parts.append(f"触发来源：{trigger_source}")
            if source_label:
                parts.append(f"摘要来源：{source_label}")
            lines.append("- " + " | ".join(parts))
            if phase_summary.get("is_partial_bar") is True:
                lines.append("- 盘中数据提示：当前 K 线可能未完结")

    quality = overview.get("data_quality") if isinstance(overview, Mapping) else None
    if isinstance(quality, Mapping):
        level = _safe_text(quality.get("level"))
        if level:
            lines.append(f"- {'data quality' if lang == 'en' else '数据质量'}: {level}")
        limitations = _list_strings(quality.get("limitations"), limit=2)
        for item in limitations:
            lines.append(f"- {'limitation' if lang == 'en' else '限制'}: {item}")

    return "\n".join(lines)


def format_public_market_status_line(
    market_phase_summary: Any,
    *,
    report_language: str = "zh",
) -> str:
    """Format one compact market/phase line for aggregate reports."""
    phase_summary = _as_mapping(market_phase_summary)
    if not phase_summary:
        return ""
    phase = _safe_phase(phase_summary.get("phase"))
    if phase is None:
        return ""

    lang = "en" if str(report_language or "").lower().startswith("en") else "zh"
    phase_labels = _PHASE_LABELS_EN if lang == "en" else _PHASE_LABELS_ZH
    market_labels = _MARKET_LABELS_EN if lang == "en" else _MARKET_LABELS_ZH
    phase_label = phase_labels.get(phase, phase)
    market = _safe_text(phase_summary.get("market"))
    market_key = market.lower()
    if market_key:
        market_label = market_labels.get(market_key, market.upper() if lang == "en" else market)
        value = f"{market_label} · {phase_label}"
    else:
        value = phase_label
    separator = ": " if lang == "en" else "："
    return f"{_MARKET_STATUS_PREFIX[lang]}{separator}{value}"


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


def _source_label(value: Any, lang: str) -> Optional[str]:
    source = _safe_text(value)
    if not source:
        return None
    labels = _PUBLIC_SOURCE_LABELS_EN if lang == "en" else _PUBLIC_SOURCE_LABELS_ZH
    return labels.get(source, source)


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
