# -*- coding: utf-8 -*-
"""Preview-only decision-profile reassessment from persisted analysis history."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Optional

from src.schemas.decision_action import build_action_fields, normalize_decision_action
from src.schemas.decision_profile import normalize_decision_profile
from src.schemas.decision_scale import action_for_score, score_action_conflicts_without_guardrail
from src.services.decision_profile_policy import (
    PROFILE_POLICY_VERSION,
    SCORING_VERSION,
    SIGNAL_GENERATION_VERSION,
    DecisionSignalCandidate,
    apply_decision_profile_policy,
)
from src.services.decision_signal_data_quality import normalize_decision_signal_data_quality
from src.storage import AnalysisHistory, DatabaseManager
from src.utils.data_processing import parse_json_field
from src.utils.sniper_points import find_sniper_points, parse_sniper_value


UNSUPPORTED_PERSIST_MESSAGE = (
    "Persisting reassessed decision_profile signals is tracked by #1757."
)


class DecisionSignalSourceReportNotFoundError(Exception):
    """Raised when the requested source report does not exist."""


class DecisionSignalUnsupportedReportTypeError(Exception):
    """Raised when the source report is not a stock analysis report."""


class DecisionSignalUnsupportedReportSnapshotError(Exception):
    """Raised when the persisted report snapshot is insufficient for reassess."""


class DecisionSignalReassessUnsupportedOperationError(Exception):
    """Raised when the request asks for a future reassess operation."""


class DecisionSignalReassessService:
    """Build preview-only reassess responses without touching DecisionSignal rows."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager.get_instance()

    def reassess(
        self,
        *,
        source_report_id: int,
        decision_profile: str,
        persist: bool = False,
    ) -> dict[str, Any]:
        if persist:
            raise DecisionSignalReassessUnsupportedOperationError(UNSUPPORTED_PERSIST_MESSAGE)
        decision_profile_norm = normalize_decision_profile(decision_profile)
        if decision_profile_norm is None:
            raise ValueError("decision_profile is required")

        record = self.db.get_analysis_history_by_id(source_report_id)
        if record is None:
            raise DecisionSignalSourceReportNotFoundError(f"source report not found: {source_report_id}")

        raw_result = _parse_mapping(getattr(record, "raw_result", None))
        context_snapshot = _parse_mapping(getattr(record, "context_snapshot", None))
        candidate = _build_candidate(record, raw_result, context_snapshot)
        data_quality_level = normalize_decision_signal_data_quality(
            _first_present(
                _nested_get(context_snapshot, ("analysis_context_pack_overview", "data_quality")),
                _nested_get(context_snapshot, ("data_quality",)),
                _nested_get(raw_result, ("analysis_context_pack_overview", "data_quality")),
                _nested_get(raw_result, ("data_quality",)),
            )
        )
        policy = apply_decision_profile_policy(
            candidate,
            decision_profile=decision_profile_norm,
            data_quality_level=data_quality_level,
        )
        preview_candidate = policy.candidate
        metadata = {
            "decision_profile": decision_profile_norm,
            "profile_source": "user_selected",
            "profile_policy_version": PROFILE_POLICY_VERSION,
            "signal_generation_version": SIGNAL_GENERATION_VERSION,
            "scoring_version": SCORING_VERSION,
            "scoring_breakdown": policy.scoring_breakdown,
            "data_quality_level": data_quality_level,
            "guardrail_result": policy.guardrail_result.as_dict(),
        }
        preview = {
            "action": preview_candidate.action,
            "score": preview_candidate.score,
            "confidence": preview_candidate.confidence,
            "horizon": preview_candidate.horizon,
            "entry_low": preview_candidate.entry_low,
            "entry_high": preview_candidate.entry_high,
            "stop_loss": preview_candidate.stop_loss,
            "target_price": preview_candidate.target_price,
            "invalidation": preview_candidate.invalidation,
            "reason": preview_candidate.reason,
            "risk_summary": preview_candidate.risk_summary,
            "watch_conditions": preview_candidate.watch_conditions,
            "metadata": metadata,
        }
        return {
            "preview": preview,
            "item": None,
            "created": False,
            "warnings": policy.warnings,
            "blocked_reason": policy.blocked_reason,
        }


def _build_candidate(
    record: AnalysisHistory,
    raw_result: Mapping[str, Any],
    context_snapshot: Mapping[str, Any],
) -> DecisionSignalCandidate:
    report_type = str(getattr(record, "report_type", "") or "").strip().lower()
    if report_type == "market_review":
        raise DecisionSignalUnsupportedReportTypeError("source report is not a stock analysis report")

    raw_code = str(getattr(record, "code", "") or "").strip()
    market = _infer_market(raw_code)
    if not raw_code or not market:
        raise DecisionSignalUnsupportedReportSnapshotError("source report has no supported stock identity")

    dashboard = _as_mapping(raw_result.get("dashboard"))
    score = _effective_signal_score(
        _score_from_value(_first_present(raw_result.get("sentiment_score"), getattr(record, "sentiment_score", None))),
        dashboard=dashboard,
    )
    raw_action = normalize_decision_action(raw_result.get("action")) or normalize_decision_action(
        _first_present(raw_result.get("operation_advice"), getattr(record, "operation_advice", None))
    )
    guardrail_reason = _extract_guardrail_reason(raw_result, score=score, raw_action=raw_action)
    action_fields = build_action_fields(
        operation_advice=_first_present(
            raw_result.get("operation_advice"),
            getattr(record, "operation_advice", None),
        ),
        explicit_action=raw_result.get("action"),
        report_type=report_type,
        report_language=raw_result.get("report_language"),
        sentiment_score=score,
        guardrail_reason=guardrail_reason,
        align_with_score=True,
    )
    action = action_fields.get("action")
    if not action:
        raise DecisionSignalUnsupportedReportSnapshotError("source report has no structured decision action")

    sniper_points = _extract_persisted_sniper_points(record, raw_result)
    entry_low, entry_high = _entry_range(
        sniper_points.get("ideal_buy"),
        sniper_points.get("secondary_buy"),
    )
    market_phase = _extract_market_phase(raw_result, context_snapshot)
    return DecisionSignalCandidate(
        action=action,
        score=score,
        confidence=_confidence_from_level(raw_result.get("confidence_level")),
        horizon=_extract_horizon(raw_result, context_snapshot, market_phase, action),
        entry_low=entry_low,
        entry_high=entry_high,
        stop_loss=sniper_points.get("stop_loss"),
        target_price=sniper_points.get("take_profit"),
        invalidation=_extract_invalidation(raw_result),
        reason=_first_text(
            getattr(record, "analysis_summary", None),
            raw_result.get("analysis_summary"),
            raw_result.get("buy_reason"),
            raw_result.get("key_points"),
        ),
        risk_summary=_extract_risk_summary(raw_result),
        watch_conditions=_extract_watch_conditions(raw_result),
        market_phase=market_phase,
    )


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _parse_mapping(value: Any) -> Mapping[str, Any]:
    parsed = parse_json_field(value)
    return parsed if isinstance(parsed, Mapping) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _first_text(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, list):
            joined = "；".join(str(item).strip() for item in value if str(item or "").strip())
            if joined:
                return joined
        text = str(value or "").strip()
        if text:
            return text
    return None


def _nested_get(value: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _infer_market(code: str) -> Optional[str]:
    text = str(code or "").strip().upper()
    if not text:
        return None
    if text.startswith("HK") or text.endswith(".HK"):
        return "hk"
    if (
        text.endswith((".SH", ".SZ", ".BJ"))
        or (len(text) == 8 and text[:2] in {"SH", "SZ", "BJ"} and text[2:].isdigit())
    ):
        return "cn"
    if text.endswith((".T", ".JP")):
        return "jp"
    if text.endswith((".KS", ".KQ")):
        return "kr"
    if text.endswith((".TW", ".TWO")):
        return "tw"
    if text.isdigit() and len(text) == 6:
        return "cn"
    if re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z]{1,2})?", text):
        return "us"
    return None


def _score_from_value(value: Any) -> Optional[int]:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        return None
    return score if 0 <= score <= 100 else None


def _effective_signal_score(
    score: Optional[int],
    *,
    dashboard: Mapping[str, Any],
) -> Optional[int]:
    calibration = _as_mapping(dashboard.get("decision_score_calibration"))
    adjusted = _score_from_value(calibration.get("adjusted_score"))
    return adjusted if adjusted is not None else score


def _extract_guardrail_reason(
    raw_result: Mapping[str, Any],
    *,
    score: Optional[int],
    raw_action: Optional[str],
) -> Optional[str]:
    dashboard = raw_result.get("dashboard") if isinstance(raw_result.get("dashboard"), Mapping) else {}
    calibration = (
        dashboard.get("decision_score_calibration")
        if isinstance(dashboard.get("decision_score_calibration"), Mapping)
        else {}
    )
    stability = (
        dashboard.get("decision_stability")
        if isinstance(dashboard.get("decision_stability"), Mapping)
        else {}
    )
    for candidate in (
        calibration.get("guardrail_reason"),
        stability.get("reason"),
        raw_result.get("guardrail_reason"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    if score_action_conflicts_without_guardrail(score=score, action=raw_action):
        candidates = [raw_result.get("operation_advice")]
        if action_for_score(score) == "buy":
            candidates.extend(
                [
                    raw_result.get("analysis_summary"),
                    raw_result.get("buy_reason"),
                    raw_result.get("risk_warning"),
                ]
            )
        hints = (
            "等待",
            "待",
            "需要确认",
            "缺少确认",
            "未确认",
            "回踩",
            "支撑",
            "压力",
            "风险",
            "资金",
            "突破",
            "不追",
            "不宜",
        )
        for candidate in candidates:
            text = str(candidate or "").strip()
            if not text:
                continue
            normalized = text.lower()
            if any(hint in normalized for hint in hints):
                return text
    return None


def _confidence_from_level(value: Any) -> Optional[float]:
    key = str(value or "").strip().lower()
    mapping = {
        "高": 0.8,
        "high": 0.8,
        "中": 0.6,
        "medium": 0.6,
        "mid": 0.6,
        "低": 0.4,
        "low": 0.4,
    }
    return mapping.get(key)


def _extract_persisted_sniper_points(record: AnalysisHistory, raw_result: Mapping[str, Any]) -> dict[str, Optional[float]]:
    raw_points = find_sniper_points(raw_result) or {}
    return {
        "ideal_buy": _first_price(getattr(record, "ideal_buy", None), raw_points.get("ideal_buy")),
        "secondary_buy": _first_price(getattr(record, "secondary_buy", None), raw_points.get("secondary_buy")),
        "stop_loss": _first_price(getattr(record, "stop_loss", None), raw_points.get("stop_loss")),
        "take_profit": _first_price(getattr(record, "take_profit", None), raw_points.get("take_profit")),
    }


def _first_price(*values: Any) -> Optional[float]:
    for value in values:
        parsed = parse_sniper_value(value)
        if parsed is not None:
            return parsed
    return None


def _entry_range(ideal_buy: Optional[float], secondary_buy: Optional[float]) -> tuple[Optional[float], Optional[float]]:
    if ideal_buy is not None and secondary_buy is not None and ideal_buy > secondary_buy:
        return secondary_buy, ideal_buy
    return ideal_buy, secondary_buy


def _extract_market_phase(raw_result: Mapping[str, Any], context_snapshot: Mapping[str, Any]) -> Optional[str]:
    return _first_text(
        _nested_get(context_snapshot, ("market_phase_summary", "phase")),
        _nested_get(raw_result, ("market_phase_summary", "phase")),
        _nested_get(raw_result, ("dashboard", "phase_decision", "phase")),
    )


def _extract_horizon(
    raw_result: Mapping[str, Any],
    context_snapshot: Mapping[str, Any],
    market_phase: Optional[str],
    action: str,
) -> Optional[str]:
    explicit = _first_text(
        raw_result.get("horizon"),
        raw_result.get("holding_period"),
        _nested_get(raw_result, ("dashboard", "phase_decision", "horizon")),
        _nested_get(raw_result, ("dashboard", "battle_plan", "horizon")),
    )
    if explicit in {"intraday", "1d", "3d", "5d", "10d", "swing", "long"}:
        return explicit
    phase = market_phase or _nested_get(context_snapshot, ("market_phase_summary", "phase"))
    return "intraday" if action == "alert" or phase == "intraday" else "3d"


def _extract_invalidation(raw_result: Mapping[str, Any]) -> Optional[str]:
    return _first_text(
        raw_result.get("invalidation"),
        raw_result.get("invalid_condition"),
        _nested_get(raw_result, ("dashboard", "phase_decision", "invalidation")),
        _nested_get(raw_result, ("dashboard", "battle_plan", "invalidation")),
    )


def _extract_risk_summary(raw_result: Mapping[str, Any]) -> Optional[str]:
    return _first_text(
        raw_result.get("risk_summary"),
        raw_result.get("risk_warning"),
        _nested_get(raw_result, ("dashboard", "intelligence", "risk_alerts")),
    )


def _extract_watch_conditions(raw_result: Mapping[str, Any]) -> Optional[str]:
    return _first_text(
        raw_result.get("watch_conditions"),
        _nested_get(raw_result, ("dashboard", "phase_decision", "watch_conditions")),
        _nested_get(raw_result, ("dashboard", "battle_plan", "action_checklist")),
    )
