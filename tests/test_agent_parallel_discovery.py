# -*- coding: utf-8 -*-
"""Tests for Wave-1 parallel discovery wave and Empirical Bayes smoothed skill weights."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

sys.modules.setdefault("litellm", MagicMock())

from src.agent.agents.intel_agent import IntelAgent
from src.agent.agents.technical_agent import TechnicalAgent
from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus
from src.services.skill_opinion_weight_service import (
    MAX_SKILL_OPINION_WEIGHT_FACTOR,
    MIN_SKILL_OPINION_WEIGHT_FACTOR,
    SkillOpinionWeightService,
)


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
