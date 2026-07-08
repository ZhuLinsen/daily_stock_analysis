# -*- coding: utf-8 -*-
"""Tests for extracting DecisionSignal assets from completed reports."""

from __future__ import annotations

import os

import pytest

from src.analyzer import AnalysisResult
from src.config import Config
from src.services.decision_signal_extractor import (
    build_decision_signal_payload_from_report,
    extract_and_persist_from_analysis_result,
)
from src.services.decision_signal_service import DecisionSignalService
from src.storage import DatabaseManager


BUILD_PROFILE_SOURCE = "legacy_unknown"


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    db_path = tmp_path / "decision_signal_extractor.db"
    os.environ["DATABASE_PATH"] = str(db_path)
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


def _result(**overrides) -> AnalysisResult:
    result = AnalysisResult(
        code="600519",
        name="贵州茅台",
        sentiment_score=82,
        trend_prediction="看多",
        operation_advice="买入",
        decision_type="buy",
        confidence_level="高",
        analysis_summary="趋势确认，量价配合。",
        risk_warning="跌破支撑需止损",
        report_language="zh",
    )
    result.dashboard = {
        "battle_plan": {
            "sniper_points": {
                "ideal_buy": "理想买入点：1700元",
                "secondary_buy": "1680-1690（回踩MA5附近）",
                "stop_loss": "止损位：1600元",
                "take_profit": "目标位：1850元",
            },
            "action_checklist": ["放量突破前高", "回踩不破MA10"],
        },
        "phase_decision": {
            "watch_conditions": ["盘中量能继续放大"],
        },
        "intelligence": {
            "risk_alerts": ["估值偏高"],
            "positive_catalysts": ["业绩超预期"],
        },
    }
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


def test_build_payload_rejects_invalid_profile_source() -> None:
    with pytest.raises(ValueError, match="profile_source"):
        build_decision_signal_payload_from_report(
            _result(),
            trace_id="trace-invalid-profile-source",
            query_source="api",
            report_type="simple",
            profile_source="typo",
        )


def test_build_payload_includes_tw_market() -> None:
    """A Taiwan (`tw`) stock is now first-class on the DecisionSignal write path
    (service VALID_MARKETS accepts tw, matching jp/kr).

    Regression guard for the data-layer MVP follow-up: the analysis pipeline
    auto-extracts a DecisionSignal after history save, so tw must PRODUCE a
    payload (market == "tw") rather than be silently dropped by _normalize_market.
    A plain action ("buy") is set so the path reaches the market mapping.
    """
    result = _result(code="2330.TW", name="台积电")

    payload = build_decision_signal_payload_from_report(
        result,
        context_snapshot=None,
        portfolio_context=None,
        source_report_id=None,
        trace_id="trace-tw",
        query_source="api",
        report_type="full",
        profile_source=BUILD_PROFILE_SOURCE,
    )

    assert payload is not None
    assert payload["market"] == "tw"
    assert payload["action"] == "buy"


def test_build_payload_maps_report_context_and_price_plan() -> None:
    result = _result()
    result.market_phase_summary = {"phase": "postmarket"}
    result.analysis_context_pack_overview = {"data_quality": {"overall_score": 55, "level": "fair"}}
    context_snapshot = {
        "market_phase_summary": {
            "phase": "intraday",
            "session_date": "2026-06-15",
            "minutes_to_open": None,
            "minutes_to_close": 120,
        },
        "analysis_context_pack_overview": {
            "data_quality": {"overall_score": 91, "level": "good"},
        },
    }

    payload = build_decision_signal_payload_from_report(
        result,
        context_snapshot=context_snapshot,
        portfolio_context={"quantity": "200"},
        source_report_id=88,
        trace_id="trace-88",
        query_source="api",
        report_type="full",
        profile_source=BUILD_PROFILE_SOURCE,
    )

    assert payload is not None
    assert payload["stock_code"] == "600519"
    assert payload["stock_name"] == "贵州茅台"
    assert payload["market"] == "cn"
    assert payload["source_type"] == "analysis"
    assert payload["source_report_id"] == 88
    assert payload["trace_id"] == "trace-88"
    assert payload["decision_profile"] == "balanced"
    assert payload["trigger_source"] == "api"
    assert payload["action"] == "buy"
    assert payload["confidence"] == 0.8
    assert payload["score"] == 82
    assert payload["market_phase"] == "intraday"
    assert payload["entry_low"] == 1690.0
    assert payload["entry_high"] == 1700.0
    assert payload["stop_loss"] == 1600.0
    assert payload["target_price"] == 1850.0
    assert payload["data_quality_summary"]["overall_score"] == 91
    assert payload["watch_conditions"] == ["盘中量能继续放大"]
    assert payload["risk_summary"] == ["跌破支撑需止损", "估值偏高"]
    assert payload["catalyst_summary"] == ["业绩超预期"]
    assert payload["metadata"]["report_confidence_level"] == "高"
    assert payload["metadata"]["decision_profile"] == "balanced"
    assert payload["metadata"]["profile_source"] == BUILD_PROFILE_SOURCE
    assert payload["metadata"]["profile_policy_version"] == "decision-profile-v1"
    assert payload["metadata"]["signal_generation_version"] == "legacy-report-extractor-v1"
    assert payload["metadata"]["decision_signal_metadata_version"] == "decision-signal-metadata-v1"
    assert "scoring_version" not in payload["metadata"]
    assert "scoring_breakdown" not in payload["metadata"]
    assert payload["metadata"]["market_phase_summary"] == {
        "phase": "intraday",
        "session_date": "2026-06-15",
        "minutes_to_close": 120,
    }
    assert payload["metadata"]["holding_state"] == "holding"


def test_build_payload_uses_result_fallbacks_and_optional_catalysts() -> None:
    result = _result(confidence_level="低")
    result.dashboard = {
        "battle_plan": {
            "sniper_points": {"ideal_buy": "1700"},
            "action_checklist": ["等待回踩确认"],
        },
        "intelligence": {},
    }
    result.market_phase_summary = {"phase": "postmarket"}
    result.analysis_context_pack_overview = {"data_quality": {"level": "limited"}}

    payload = build_decision_signal_payload_from_report(
        result,
        context_snapshot=None,
        source_report_id=None,
        trace_id="trace-fallback",
        query_source="",
        report_type="simple",
        profile_source=BUILD_PROFILE_SOURCE,
    )

    assert payload is not None
    assert payload["market_phase"] == "postmarket"
    assert payload["data_quality_summary"] == {"level": "limited"}
    assert payload["entry_low"] == 1700.0
    assert "entry_high" not in payload
    assert payload["watch_conditions"] == ["等待回踩确认"]
    assert "catalyst_summary" not in payload
    assert payload["trigger_source"] == "system"
    assert payload["confidence"] == 0.4
    assert payload["metadata"]["holding_state"] == "unknown"


def test_build_payload_aligns_high_neutral_action_without_guardrail_to_buy() -> None:
    result = _result(
        sentiment_score=72,
        operation_advice="持有",
        decision_type="hold",
        action=None,
    )

    payload = build_decision_signal_payload_from_report(
        result,
        trace_id="trace-high-neutral",
        query_source="api",
        report_type="simple",
        profile_source=BUILD_PROFILE_SOURCE,
    )

    assert payload is not None
    assert payload["action"] == "buy"
    assert payload["action_label"] == "买入"
    assert payload["metadata"]["raw_action"] == "hold"
    assert payload["metadata"]["final_action"] == "buy"
    assert payload["metadata"]["action_adjustment_reason"] == "canonical_score_alignment"
    assert payload["metadata"]["score_scale"]["score_band"] == "60-79"


def test_build_payload_keeps_high_neutral_action_with_guardrail_reason() -> None:
    result = _result(
        sentiment_score=72,
        operation_advice="持有/观望待回踩",
        decision_type="hold",
        action=None,
    )

    payload = build_decision_signal_payload_from_report(
        result,
        trace_id="trace-high-neutral-guarded",
        query_source="api",
        report_type="simple",
        profile_source=BUILD_PROFILE_SOURCE,
    )

    assert payload is not None
    assert payload["action"] == "watch"
    assert payload["action_label"] == "观望"
    assert payload["metadata"]["raw_action"] == "watch"
    assert payload["metadata"]["final_action"] == "watch"
    assert payload["metadata"]["guardrail_reason"] == "持有/观望待回踩"


def test_build_payload_uses_stability_calibration_raw_and_adjusted_scores() -> None:
    result = _result(
        sentiment_score=59,
        operation_advice="观望",
        decision_type="hold",
        action=None,
    )
    dashboard = result.dashboard or {}
    dashboard["decision_score_calibration"] = {
        "raw_score": 72,
        "adjusted_score": 59,
        "final_action": "watch",
        "guardrail_reason": "资金流较弱，按风险规则降级",
    }
    result.dashboard = dashboard

    payload = build_decision_signal_payload_from_report(
        result,
        trace_id="trace-stability-calibration",
        query_source="api",
        report_type="simple",
        profile_source=BUILD_PROFILE_SOURCE,
    )

    assert payload is not None
    assert payload["score"] == 59
    assert payload["metadata"]["raw_score"] == 72
    assert payload["metadata"]["adjusted_score"] == 59
    assert payload["metadata"]["score_scale"]["score_band"] == "40-59"
    assert payload["metadata"]["raw_action"] == "watch"
    assert payload["metadata"]["final_action"] == "watch"
    assert payload["metadata"]["guardrail_reason"] == "资金流较弱，按风险规则降级"


def test_build_payload_aligns_low_neutral_action_to_reduce() -> None:
    result = _result(
        sentiment_score=28,
        operation_advice="观望",
        decision_type="hold",
        action=None,
    )

    payload = build_decision_signal_payload_from_report(
        result,
        trace_id="trace-low-neutral",
        query_source="api",
        report_type="simple",
        profile_source=BUILD_PROFILE_SOURCE,
    )

    assert payload is not None
    assert payload["action"] == "reduce"
    assert payload["action_label"] == "减仓"
    assert payload["metadata"]["raw_action"] == "watch"
    assert payload["metadata"]["final_action"] == "reduce"
    assert payload["metadata"]["score_scale"]["score_band"] == "20-39"


def test_build_payload_records_empty_holding_state_from_explicit_portfolio_context() -> None:
    payload = build_decision_signal_payload_from_report(
        _result(),
        portfolio_context={"quantity": 0},
        trace_id="trace-empty-holding",
        query_source="api",
        report_type="simple",
        profile_source=BUILD_PROFILE_SOURCE,
    )

    assert payload is not None
    assert payload["metadata"]["holding_state"] == "empty"


def test_runtime_decision_signal_summary_is_not_serialized_by_analysis_result_to_dict() -> None:
    result = _result()
    setattr(result, "decision_signal_summary", {"action": "sell", "reason": "risk"})

    assert "decision_signal_summary" not in result.to_dict()


def test_build_payload_maps_secondary_only_entry_to_entry_high() -> None:
    result = _result()
    result.dashboard = {
        "battle_plan": {
            "sniper_points": {"secondary_buy": "次优买入点：1680元"},
        },
    }

    payload = build_decision_signal_payload_from_report(
        result,
        trace_id="trace-secondary-only",
        query_source="api",
        report_type="simple",
        profile_source=BUILD_PROFILE_SOURCE,
    )

    assert payload is not None
    assert "entry_low" not in payload
    assert payload["entry_high"] == 1680.0


def test_build_payload_reuses_shared_sniper_fallback_paths(isolated_db) -> None:
    result = _result()
    result.dashboard = {}
    result.raw_response = {
        "dashboard": {
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": "1690",
                    "secondary_buy": "1705",
                    "stop_loss": "1620",
                    "take_profit": "1880",
                }
            }
        }
    }

    payload = build_decision_signal_payload_from_report(
        result,
        trace_id="trace-raw-sniper",
        query_source="api",
        report_type="simple",
        profile_source=BUILD_PROFILE_SOURCE,
    )
    stored_points = isolated_db._extract_sniper_points(result)

    assert payload is not None
    assert stored_points == {
        "ideal_buy": 1690.0,
        "secondary_buy": 1705.0,
        "stop_loss": 1620.0,
        "take_profit": 1880.0,
    }
    assert payload["entry_low"] == 1690.0
    assert payload["entry_high"] == 1705.0
    assert payload["stop_loss"] == 1620.0
    assert payload["target_price"] == 1880.0


def test_build_payload_skips_ambiguous_action_non_stock_and_unknown_market() -> None:
    ambiguous = _result(operation_advice="买盘增强，继续观察", action=None)
    assert build_decision_signal_payload_from_report(
        ambiguous,
        trace_id="trace-1",
        query_source="api",
        report_type="simple",
        profile_source=BUILD_PROFILE_SOURCE,
    ) is None

    market_review = _result(operation_advice="买入", action="buy")
    assert build_decision_signal_payload_from_report(
        market_review,
        trace_id="trace-2",
        query_source="api",
        report_type="market_review",
        profile_source=BUILD_PROFILE_SOURCE,
    ) is None

    unknown_market = _result(code="UNKNOWN", operation_advice="买入", action="buy")
    assert build_decision_signal_payload_from_report(
        unknown_market,
        trace_id="trace-3",
        query_source="api",
        report_type="simple",
        profile_source=BUILD_PROFILE_SOURCE,
    ) is None


def test_extract_and_persist_reuses_service_dedup_and_sanitization(isolated_db) -> None:
    service = DecisionSignalService(db_manager=isolated_db)
    result = _result(
        analysis_summary="趋势确认 token=super-secret",
    )

    first = extract_and_persist_from_analysis_result(
        result,
        context_snapshot={"market_phase_summary": {"phase": "intraday"}},
        portfolio_context={"quantity": 10},
        source_report_id=901,
        trace_id="trace-901",
        query_source="api",
        report_type="full",
        profile_source="auto_default",
        service=service,
    )
    second = extract_and_persist_from_analysis_result(
        result,
        context_snapshot={"market_phase_summary": {"phase": "intraday"}},
        portfolio_context={"quantity": 10},
        source_report_id=901,
        trace_id="trace-901",
        query_source="api",
        report_type="full",
        profile_source="auto_default",
        service=service,
    )

    assert first is not None
    assert second is not None
    assert first["created"] is True
    assert second["created"] is False
    assert first["item"]["reason"] == "趋势确认 token=[REDACTED]"
    assert first["item"]["plan_quality"] == "complete"
    assert first["item"]["horizon"] == "intraday"
    assert first["item"]["expires_at"] is not None

    listed = service.list_signals(source_report_id=901)
    assert listed["total"] == 1
    persisted = listed["items"][0]
    assert persisted["source_report_id"] == 901
    assert persisted["metadata"]["holding_state"] == "holding"
    assert persisted["metadata"]["decision_profile"] == "balanced"
    assert persisted["metadata"]["profile_source"] == "auto_default"
    assert persisted["metadata"]["profile_policy_version"] == "decision-profile-v1"
    assert persisted["metadata"]["signal_generation_version"] == "legacy-report-extractor-v1"
    assert persisted["metadata"]["decision_signal_metadata_version"] == "decision-signal-metadata-v1"
    assert "scoring_version" not in persisted["metadata"]
    assert "scoring_breakdown" not in persisted["metadata"]
    assert persisted["reason"] == "趋势确认 token=[REDACTED]"
    assert persisted["entry_low"] == 1690.0
    assert persisted["entry_high"] == 1700.0


def test_extract_and_persist_reuses_stability_score_metadata(isolated_db) -> None:
    service = DecisionSignalService(db_manager=isolated_db)
    result = _result(
        sentiment_score=59,
        operation_advice="观望",
        decision_type="hold",
        action=None,
        confidence_level="中",
    )
    dashboard = result.dashboard or {}
    dashboard["decision_score_calibration"] = {
        "raw_score": 72,
        "adjusted_score": 59,
        "final_action": "watch",
        "guardrail_reason": "资金流较弱，按风险规则降级",
    }
    result.dashboard = dashboard

    created = extract_and_persist_from_analysis_result(
        result,
        context_snapshot={"market_phase_summary": {"phase": "intraday"}},
        portfolio_context={"quantity": 10},
        source_report_id=903,
        trace_id="trace-stability-persist",
        query_source="api",
        report_type="full",
        profile_source="auto_default",
        service=service,
    )

    assert created is not None
    persisted = service.list_signals(source_report_id=903)["items"][0]
    assert persisted["metadata"]["raw_score"] == 72
    assert persisted["metadata"]["adjusted_score"] == 59
    assert persisted["metadata"]["raw_action"] == "watch"
    assert persisted["metadata"]["final_action"] == "watch"
    assert persisted["metadata"]["guardrail_reason"] == "资金流较弱，按风险规则降级"


def test_extract_and_persist_writes_tw_signal(isolated_db) -> None:
    """End-to-end write-leg guard: a tw analysis must PERSIST a DecisionSignal
    through create_signal -> _normalize_market -> DB, not merely build the payload.

    Closes the silent-failure leg where _normalize_market("tw") raised ValueError
    inside extract_and_persist and was swallowed by its broad except -> return None,
    so every tw analysis produced no signal while jp/kr did.
    """
    service = DecisionSignalService(db_manager=isolated_db)
    result = _result(code="2330.TW", name="台积电")

    created = extract_and_persist_from_analysis_result(
        result,
        context_snapshot={"market_phase_summary": {"phase": "intraday"}},
        portfolio_context={"quantity": 10},
        source_report_id=2330,
        trace_id="trace-tw-persist",
        query_source="api",
        report_type="full",
        profile_source="auto_default",
        service=service,
    )

    assert created is not None
    assert created["created"] is True
    assert created["item"]["market"] == "tw"

    listed = service.list_signals(source_report_id=2330)
    assert listed["total"] == 1
    assert listed["items"][0]["market"] == "tw"


def test_extract_and_persist_missing_price_plan_does_not_fabricate_fields(isolated_db) -> None:
    service = DecisionSignalService(db_manager=isolated_db)
    result = _result()
    result.dashboard = {"battle_plan": {"sniper_points": {}}, "intelligence": {}}

    created = extract_and_persist_from_analysis_result(
        result,
        context_snapshot={"market_phase_summary": {"phase": "postmarket"}},
        source_report_id=902,
        trace_id="trace-902",
        query_source="schedule",
        report_type="simple",
        profile_source="auto_default",
        service=service,
    )

    assert created is not None
    item = created["item"]
    assert item["plan_quality"] == "minimal"
    assert item["horizon"] == "3d"
    assert item["expires_at"] is not None
    assert item["entry_low"] is None
    assert item["entry_high"] is None
    assert item["stop_loss"] is None
    assert item["target_price"] is None
