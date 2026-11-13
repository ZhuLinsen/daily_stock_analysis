# -*- coding: utf-8 -*-
"""Tests for numeric grounding verifier, ATR position sizing, parallel discovery wave, and smoothed skill weights."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

sys.modules.setdefault("litellm", MagicMock())

from api.v1.schemas.history import AnalysisReport, ReportMeta, ReportStrategy, ReportSummary
from src.agent.agents.intel_agent import IntelAgent
from src.agent.agents.technical_agent import TechnicalAgent
from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus
from src.core.grounding_verifier import (
    compute_atr_position_sizing,
    verify_and_normalize_levels,
)
from src.services.skill_opinion_weight_service import (
    MAX_SKILL_OPINION_WEIGHT_FACTOR,
    MIN_SKILL_OPINION_WEIGHT_FACTOR,
    SkillOpinionWeightService,
)


def test_verify_and_normalize_levels_valid_long_setup() -> None:
    strategy = {
        "ideal_buy": "100.00元",
        "secondary_buy": "95.00元",
        "stop_loss": "92.00元",
        "take_profit": "120.00元",
    }
    levels = verify_and_normalize_levels(strategy, current_price=102.0, action="buy")

    assert levels["ideal_buy"] == 100.0
    assert levels["secondary_buy"] == 95.0
    assert levels["stop_loss"] == 92.0
    assert levels["take_profit"] == 120.0
    assert levels["reference_price"] == 102.0
    assert levels["status"] == "active"
    assert levels["validation"] == "ok"
    assert levels["risk_reward_ratio"] == 2.5


def test_verify_and_normalize_levels_detects_conflict_and_watch_status() -> None:
    strategy = {
        "ideal_buy": "100.0",
        "stop_loss": "105.0",
        "take_profit": "120.0",
    }
    levels = verify_and_normalize_levels(strategy, current_price=101.0, action="watch")

    assert levels["status"] == "conditional_watch"
    assert levels["validation"] == "direction_conflict"
    assert levels["risk_reward_ratio"] is None


def test_verify_and_normalize_levels_detects_out_of_range_anchor() -> None:
    strategy = {
        "ideal_buy": "60.0",
        "stop_loss": "55.0",
        "take_profit": "80.0",
    }
    levels = verify_and_normalize_levels(strategy, current_price=100.0, action="buy")

    assert levels["validation"] == "out_of_range"


def test_compute_atr_position_sizing_caps_and_non_offensive_zero() -> None:
    levels = {"reference_price": 100.0, "stop_loss": 96.0}

    buy_pos = compute_atr_position_sizing("buy", 80, levels, data_quality_level="good")
    assert buy_pos["min_pct"] >= 5
    assert buy_pos["max_pct"] <= 35
    assert buy_pos["min_pct"] <= buy_pos["max_pct"]
    assert buy_pos["stop_distance_pct"] == 4.0

    limited_pos = compute_atr_position_sizing("buy", 85, levels, data_quality_level="limited")
    assert limited_pos["max_pct"] <= 20
    assert limited_pos["cap_reason"] == "limited_data_quality"

    hold_pos = compute_atr_position_sizing("hold", 80, levels, data_quality_level="good")
    assert hold_pos["min_pct"] == 0
    assert hold_pos["max_pct"] == 0
    assert hold_pos["cap_reason"] == "non_offensive_action"


def test_analysis_report_auto_populates_structured_report() -> None:
    report = AnalysisReport(
        meta=ReportMeta(
            query_id="q-100",
            stock_code="600519",
            stock_name="贵州茅台",
            report_type="detailed",
            current_price=1680.0,
        ),
        summary=ReportSummary(
            analysis_summary="均线多头排列，回踩支撑位。",
            operation_advice="买入",
            action="buy",
            trend_prediction="看多",
            sentiment_score=76,
        ),
        strategy=ReportStrategy(
            ideal_buy="1660.0",
            secondary_buy="1620.0",
            stop_loss="1580.0",
            take_profit="1840.0",
        ),
    )

    assert report.structured_report is not None
    assert report.structured_report.schema_version == "research-artifact-v1"
    meta = report.structured_report.metadata
    assert meta["levels"]["ideal_buy"] == 1660.0
    assert meta["levels"]["status"] == "active"
    assert meta["levels"]["validation"] == "ok"
    assert meta["position"]["max_pct"] >= 5


def test_orchestrator_parallel_discovery_wave_merges_in_order() -> None:
    orch = AgentOrchestrator(tool_registry=MagicMock(), llm_adapter=MagicMock())
    tech_agent = TechnicalAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    intel_agent = IntelAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())

    assert orch._can_parallelize_discovery_pair(tech_agent, intel_agent) is True

    def fake_run_stage(agent, run_ctx, progress_callback=None, timeout_seconds=None):
        if agent.agent_name == "technical":
            op = AgentOpinion(agent_name="technical", signal="buy", confidence=0.8, reasoning="tech ok")
            run_ctx.add_opinion(op)
            run_ctx.set_data("trend_result", {"ma_alignment": "bullish"})
            return StageResult(stage_name="technical", status=StageStatus.COMPLETED, opinion=op)
        op = AgentOpinion(agent_name="intel", signal="hold", confidence=0.7, reasoning="intel ok")
        run_ctx.add_opinion(op)
        run_ctx.set_data("intel_opinion", {"positive_catalysts": ["earnings"]})
        run_ctx.add_risk_flag("news", "watch guidance", severity="low")
        return StageResult(stage_name="intel", status=StageStatus.COMPLETED, opinion=op)

    orch._run_stage_agent = fake_run_stage  # type: ignore[method-assign]
    ctx = AgentContext(query="Analyze 600519", stock_code="600519")
    events = []

    tech_res, intel_res = orch._run_discovery_wave_parallel(
        tech_agent,
        intel_agent,
        ctx,
        progress_callback=events.append,
    )

    assert tech_res.status == StageStatus.COMPLETED
    assert intel_res.status == StageStatus.COMPLETED
    assert [op.agent_name for op in ctx.opinions] == ["technical", "intel"]
    assert ctx.get_data("trend_result") == {"ma_alignment": "bullish"}
    assert ctx.get_data("intel_opinion") == {"positive_catalysts": ["earnings"]}
    assert len(ctx.risk_flags) == 1
    assert [e["type"] for e in events] == ["stage_start", "stage_start", "stage_done", "stage_done"]


def test_skill_opinion_weight_service_smoothed_small_samples() -> None:
    fake_perf = MagicMock()
    fake_perf.get_stats.return_value = {
        "engine_version": "skill_outcome_v1",
        "buckets": [
            {
                "skill_id": "bull_trend",
                "horizon": "5d",
                "engine_version": "skill_outcome_v1",
                "evaluated": 8,
                "hit": 7,
                "miss": 1,
                "unable": 0,
                "observational": 0,
                "sample_sufficient": False,
            },
            {
                "skill_id": "hot_theme",
                "horizon": "5d",
                "engine_version": "skill_outcome_v1",
                "evaluated": 8,
                "hit": 1,
                "miss": 7,
                "unable": 0,
                "observational": 0,
                "sample_sufficient": False,
            },
        ],
    }

    service = SkillOpinionWeightService(
        performance_service=fake_perf,
        engine_version="skill_outcome_v1",
    )
    weights = service.compute_smoothed_weights(["bull_trend", "hot_theme", "unknown_skill"])

    assert 1.0 < weights["bull_trend"] <= MAX_SKILL_OPINION_WEIGHT_FACTOR
    assert MIN_SKILL_OPINION_WEIGHT_FACTOR <= weights["hot_theme"] < 1.0
    assert weights["unknown_skill"] == 1.0
