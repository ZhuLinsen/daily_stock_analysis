# -*- coding: utf-8 -*-
"""Extract DecisionSignal payloads from completed analysis reports."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Literal, Mapping, Optional

from data_provider.base import normalize_stock_code

from src.analyzer import AnalysisResult
from src.core.trading_calendar import get_market_for_stock
from src.schemas.decision_action import build_action_fields, normalize_decision_action
from src.schemas.decision_scale import (
    CANONICAL_DECISION_SCALE_VERSION,
    action_for_score,
    score_action_conflicts_without_guardrail,
    score_band_metadata,
)
from src.services.decision_signal_service import DecisionSignalService
from src.services.portfolio_service import VALID_MARKETS
from src.utils.sniper_points import extract_sniper_points


logger = logging.getLogger(__name__)

ProfileSource = Literal["auto_default", "backfill_defaulted", "legacy_unknown"]

_PROFILE_SOURCES = frozenset({"auto_default", "backfill_defaulted", "legacy_unknown"})

_CONFIDENCE_MAP = {
    "高": 0.8,
    "high": 0.8,
    "中": 0.6,
    "medium": 0.6,
    "mid": 0.6,
    "低": 0.4,
    "low": 0.4,
}


def build_decision_signal_payload_from_report(
    result: AnalysisResult,
    *,
    context_snapshot: Dict[str, Any] | None = None,
    portfolio_context: Dict[str, Any] | None = None,
    source_report_id: int | None = None,
    trace_id: str,
    query_source: str,
    report_type: str,
    profile_source: ProfileSource,
) -> Dict[str, Any] | None:
    """Build a DecisionSignal payload from a completed stock analysis report."""

    if result is None or not getattr(result, "success", True):
        return None
    if profile_source not in _PROFILE_SOURCES:
        raise ValueError(f"invalid profile_source: {profile_source}")

    dashboard = _as_mapping(getattr(result, "dashboard", None))
    score_calibration = _as_mapping(dashboard.get("decision_score_calibration"))
    score = _effective_signal_score(
        _score_from_result(getattr(result, "sentiment_score", None)),
        score_calibration,
    )
    raw_action = _raw_action_from_report(result)
    guardrail_reason = _extract_guardrail_reason(result, dashboard, score=score, raw_action=raw_action)
    action_fields = build_action_fields(
        operation_advice=getattr(result, "operation_advice", None),
        explicit_action=getattr(result, "action", None),
        report_type=report_type,
        report_language=getattr(result, "report_language", None),
        sentiment_score=score,
        guardrail_reason=guardrail_reason,
        align_with_score=True,
    )
    action = action_fields.get("action")
    if not action:
        return None

    raw_code = str(getattr(result, "code", "") or "").strip()
    market = get_market_for_stock(normalize_stock_code(raw_code))
    if not market:
        logger.warning("Skip decision signal extraction: unrecognized market stock_code=%s", raw_code)
        return None
    if market not in VALID_MARKETS:
        # A market the data layer recognizes but the decision-signal service
        # layer does not accept (e.g. a market added to detection ahead of
        # VALID_MARKETS). Skip gracefully instead of letting create_signal
        # raise a swallowed ValueError + noisy traceback.
        logger.info(
            "Skip decision signal extraction: market=%s not yet wired for signals stock_code=%s",
            market,
            raw_code,
        )
        return None

    sniper_points = extract_sniper_points(result)
    entry_low, entry_high = _entry_range(
        sniper_points.get("ideal_buy"),
        sniper_points.get("secondary_buy"),
    )

    metadata = {
        "report_type": report_type,
        "decision_type": getattr(result, "decision_type", None),
        "report_confidence_level": getattr(result, "confidence_level", None),
        "report_language": getattr(result, "report_language", None),
        "decision_profile": "balanced",
        "profile_source": profile_source,
        "profile_policy_version": "decision-profile-v1",
        "signal_generation_version": "legacy-report-extractor-v1",
        "decision_signal_metadata_version": "decision-signal-metadata-v1",
        "canonical_decision_scale_version": CANONICAL_DECISION_SCALE_VERSION,
    }
    score_metadata = score_band_metadata(score)
    if score_metadata:
        metadata["score_scale"] = score_metadata
        metadata["raw_score"] = _calibrated_or_raw_score(
            score_calibration,
            prefer="raw",
            fallback=score_metadata["score"],
        )
        metadata["adjusted_score"] = _calibrated_or_raw_score(
            score_calibration,
            prefer="adjusted",
            fallback=score_metadata["score"],
        )
        metadata["final_action"] = action
        if raw_action:
            metadata["raw_action"] = raw_action
        if raw_action and raw_action != action:
            metadata["action_adjustment_reason"] = "canonical_score_alignment"
    if guardrail_reason:
        metadata["guardrail_reason"] = guardrail_reason
    market_phase_summary = _extract_market_phase_summary(context_snapshot, result)
    if market_phase_summary:
        metadata["market_phase_summary"] = market_phase_summary
    metadata["holding_state"] = _extract_holding_state(portfolio_context)

    payload: Dict[str, Any] = {
        "stock_code": raw_code,
        "stock_name": getattr(result, "name", None),
        "market": market,
        "source_type": "analysis",
        "source_report_id": source_report_id,
        "trace_id": trace_id,
        "market_phase": _extract_market_phase(context_snapshot, result),
        "trigger_source": str(query_source or "").strip() or "system",
        "action": action,
        "action_label": action_fields.get("action_label"),
        "confidence": _confidence_from_level(getattr(result, "confidence_level", None)),
        "score": score,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": sniper_points.get("stop_loss"),
        "target_price": sniper_points.get("take_profit"),
        "reason": _first_text(
            getattr(result, "analysis_summary", None),
            getattr(result, "buy_reason", None),
            getattr(result, "key_points", None),
        ),
        "risk_summary": _risk_summary(result, dashboard),
        "catalyst_summary": _catalyst_summary(dashboard),
        "watch_conditions": _watch_conditions(dashboard),
        "evidence": _evidence(result, sniper_points),
        "data_quality_summary": _extract_data_quality(context_snapshot, result),
        "metadata": metadata,
        "report_language": getattr(result, "report_language", None),
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def extract_and_persist_from_analysis_result(
    result: AnalysisResult,
    *,
    context_snapshot: Dict[str, Any] | None = None,
    portfolio_context: Dict[str, Any] | None = None,
    source_report_id: int | None = None,
    trace_id: str,
    query_source: str,
    report_type: str,
    profile_source: ProfileSource,
    service: Optional[DecisionSignalService] = None,
) -> Dict[str, Any] | None:
    """Best-effort extract and persist a DecisionSignal from an analysis result."""

    try:
        payload = build_decision_signal_payload_from_report(
            result,
            context_snapshot=context_snapshot,
            portfolio_context=portfolio_context,
            source_report_id=source_report_id,
            trace_id=trace_id,
            query_source=query_source,
            report_type=report_type,
            profile_source=profile_source,
        )
        if payload is None:
            return None
        writer = service or DecisionSignalService()
        return writer.create_signal(payload)
    except Exception as exc:
        logger.warning(
            "Decision signal extraction failed: query_id=%s stock_code=%s error=%s",
            trace_id,
            getattr(result, "code", None),
            exc,
            exc_info=True,
        )
        return None


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _calibrated_or_raw_score(
    calibration: Dict[str, Any],
    *,
    prefer: Literal["raw", "adjusted"],
    fallback: Optional[int] = None,
) -> Optional[int]:
    if prefer == "raw":
        value = calibration.get("raw_score")
    else:
        value = calibration.get("adjusted_score")
    parsed = _score_from_result(value)
    if parsed is not None:
        return parsed
    return fallback


def _effective_signal_score(
    score: Optional[int],
    calibration: Dict[str, Any],
) -> Optional[int]:
    adjusted = _calibrated_or_raw_score(calibration, prefer="adjusted")
    return adjusted if adjusted is not None else score


def _first_text(*values: Any) -> Optional[str]:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _score_from_result(value: Any) -> Optional[int]:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        return None
    return score if 0 <= score <= 100 else None


def _raw_action_from_report(result: AnalysisResult) -> Optional[str]:
    explicit_action = normalize_decision_action(getattr(result, "action", None))
    if explicit_action:
        return explicit_action
    return normalize_decision_action(getattr(result, "operation_advice", None))


_NEUTRAL_GUARDRAIL_HINTS = (
    "等待",
    "待",
    "需要确认",
    "回踩",
    "支撑",
    "压力",
    "风险",
    "资金",
    "突破",
    "不追",
    "不宜",
    "缺少",
    "缺少确认",
    "未确认",
    "wait",
    "waiting",
    "pending confirmation",
    "lack confirmation",
    "pullback",
    "support",
    "resistance",
    "risk",
    "flow",
)


def _extract_guardrail_reason(
    result: AnalysisResult,
    dashboard: Mapping[str, Any],
    *,
    score: Optional[int],
    raw_action: Optional[str],
) -> Optional[str]:
    score_calibration = _as_mapping(dashboard.get("decision_score_calibration"))
    reason = _first_text(
        score_calibration.get("guardrail_reason"),
        _as_mapping(dashboard.get("decision_stability")).get("reason"),
        getattr(result, "guardrail_reason", None),
    )
    if reason:
        return reason

    if score_action_conflicts_without_guardrail(score=score, action=raw_action):
        candidates = [getattr(result, "operation_advice", None)]
        if action_for_score(score) == "buy":
            candidates.extend(
                [
                    getattr(result, "analysis_summary", None),
                    getattr(result, "buy_reason", None),
                    _watch_conditions(dashboard),
                ]
            )
        for candidate in candidates:
            text = _first_text(candidate)
            if not text:
                continue
            normalized = text.lower()
            if any(hint in normalized for hint in _NEUTRAL_GUARDRAIL_HINTS):
                return text
    return None


def _confidence_from_level(value: Any) -> Optional[float]:
    key = str(value or "").strip().lower()
    return _CONFIDENCE_MAP.get(key)


def _entry_range(ideal_buy: Optional[float], secondary_buy: Optional[float]) -> tuple[Optional[float], Optional[float]]:
    """Return numeric entry bounds while preserving single-value source semantics."""

    low = ideal_buy if ideal_buy is not None and math.isfinite(ideal_buy) and ideal_buy > 0 else None
    high = secondary_buy if secondary_buy is not None and math.isfinite(secondary_buy) and secondary_buy > 0 else None
    if low is not None and high is not None and low > high:
        return high, low
    return low, high


def _extract_market_phase(context_snapshot: Optional[Mapping[str, Any]], result: AnalysisResult) -> Optional[str]:
    snapshot_phase = _as_mapping(_as_mapping(context_snapshot).get("market_phase_summary")).get("phase")
    if snapshot_phase:
        return str(snapshot_phase)
    result_phase = _as_mapping(getattr(result, "market_phase_summary", None)).get("phase")
    return str(result_phase) if result_phase else None


def _extract_market_phase_summary(
    context_snapshot: Optional[Mapping[str, Any]],
    result: AnalysisResult,
) -> Optional[Dict[str, Any]]:
    raw_summary = _as_mapping(_as_mapping(context_snapshot).get("market_phase_summary"))
    if not raw_summary:
        raw_summary = _as_mapping(getattr(result, "market_phase_summary", None))
    allowed_fields = ("phase", "session_date", "minutes_to_open", "minutes_to_close")
    summary = {
        field_name: raw_summary.get(field_name)
        for field_name in allowed_fields
        if raw_summary.get(field_name) not in (None, "")
    }
    return summary or None


def _extract_data_quality(context_snapshot: Optional[Mapping[str, Any]], result: AnalysisResult) -> Optional[Any]:
    snapshot_quality = _as_mapping(
        _as_mapping(context_snapshot).get("analysis_context_pack_overview")
    ).get("data_quality")
    if snapshot_quality:
        return snapshot_quality
    return _as_mapping(getattr(result, "analysis_context_pack_overview", None)).get("data_quality")


def _extract_holding_state(portfolio_context: Optional[Mapping[str, Any]]) -> str:
    context = _as_mapping(portfolio_context)
    quantity = context.get("quantity")
    if quantity in (None, ""):
        return "unknown"
    try:
        numeric_quantity = float(quantity)
    except (TypeError, ValueError):
        return "unknown"
    if not math.isfinite(numeric_quantity):
        return "unknown"
    return "holding" if abs(numeric_quantity) > 0 else "empty"


def _risk_summary(result: AnalysisResult, dashboard: Mapping[str, Any]) -> Optional[Any]:
    risks = []
    risk_warning = getattr(result, "risk_warning", None)
    if risk_warning:
        risks.append(str(risk_warning))
    intelligence = _as_mapping(dashboard.get("intelligence"))
    risk_alerts = intelligence.get("risk_alerts")
    if isinstance(risk_alerts, list):
        risks.extend(str(item) for item in risk_alerts if str(item or "").strip())
    return risks[:5] or None


def _catalyst_summary(dashboard: Mapping[str, Any]) -> Optional[Any]:
    catalysts = _as_mapping(dashboard.get("intelligence")).get("positive_catalysts")
    if not isinstance(catalysts, list):
        return None
    out = [str(item) for item in catalysts if str(item or "").strip()]
    return out[:5] or None


def _watch_conditions(dashboard: Mapping[str, Any]) -> Optional[Any]:
    phase_decision = _as_mapping(dashboard.get("phase_decision"))
    watch_conditions = phase_decision.get("watch_conditions")
    if isinstance(watch_conditions, list) and watch_conditions:
        return [str(item) for item in watch_conditions if str(item or "").strip()] or None

    battle_plan = _as_mapping(dashboard.get("battle_plan"))
    checklist = battle_plan.get("action_checklist")
    if isinstance(checklist, list) and checklist:
        return [str(item) for item in checklist if str(item or "").strip()] or None
    return None


def _evidence(result: AnalysisResult, sniper_points: Mapping[str, Any]) -> Dict[str, Any]:
    evidence = {
        "operation_advice": getattr(result, "operation_advice", None),
        "decision_type": getattr(result, "decision_type", None),
        "trend_prediction": getattr(result, "trend_prediction", None),
        "confidence_level": getattr(result, "confidence_level", None),
        "current_price": getattr(result, "current_price", None),
        "change_pct": getattr(result, "change_pct", None),
        "sniper_points": dict(sniper_points),
    }
    return {key: value for key, value in evidence.items() if value not in (None, "", [], {})}
