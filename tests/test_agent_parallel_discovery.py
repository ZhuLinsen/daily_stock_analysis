# -*- coding: utf-8 -*-
"""Tests for Wave-1 parallel discovery wave and Empirical Bayes smoothed skill weights."""

from __future__ import annotations

import sys
import threading
from datetime import date
from unittest.mock import MagicMock

sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("fxmacrodata_public", MagicMock())

from src.agent.agents.intel_agent import IntelAgent
from src.agent.agents.technical_agent import TechnicalAgent
from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus
from src.services.skill_opinion_weight_service import (
    MAX_SKILL_OPINION_WEIGHT_FACTOR,
    MIN_SKILL_OPINION_WEIGHT_FACTOR,
    SkillOpinionWeightService,
)
from src.agent.news_evidence import (
    activate_news_evidence_scope,
    get_current_news_evidence,
    reset_news_evidence_scope,
    record_news_evidence,
)
from src.services.history_loader import get_frozen_target_date, reset_frozen_target_date, set_frozen_target_date
from src.services.run_diagnostics import (
    activate_run_diagnostic_context,
    current_diagnostic_snapshot,
    record_provider_run,
    reset_run_diagnostic_context,
)


def test_orchestrator_parallel_discovery_wave_merges_in_order() -> None:
    orch = AgentOrchestrator(tool_registry=MagicMock(), llm_adapter=MagicMock())
    tech_agent = TechnicalAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    intel_agent = IntelAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())

    assert orch._can_parallelize_discovery_pair(tech_agent, intel_agent) is True

    def fake_run_stage(agent, run_ctx, progress_callback=None, timeout_seconds=None):
        if progress_callback:
            progress_callback({"type": "agent_progress", "stage": agent.agent_name})
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
    assert [e["type"] for e in events[:2]] == ["stage_start", "stage_start"]
    assert {e["stage"] for e in events[2:4]} == {"technical", "intel"}
    assert [e["type"] for e in events[4:]] == ["stage_done", "stage_done"]


def test_parallel_discovery_forwards_progress_before_wave_finishes() -> None:
    orch = AgentOrchestrator(tool_registry=MagicMock(), llm_adapter=MagicMock())
    tech_agent = TechnicalAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    intel_agent = IntelAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    progress_seen = threading.Event()
    release_workers = threading.Event()
    events = []

    def fake_run_stage(agent, run_ctx, progress_callback=None, timeout_seconds=None):
        del run_ctx, timeout_seconds
        progress_callback({"type": "thinking", "stage": agent.agent_name})
        progress_seen.set()
        release_workers.wait(timeout=2)
        return StageResult(stage_name=agent.agent_name, status=StageStatus.COMPLETED)

    orch._run_stage_agent = fake_run_stage  # type: ignore[method-assign]
    worker = threading.Thread(
        target=orch._run_discovery_wave_parallel,
        args=(tech_agent, intel_agent, AgentContext(stock_code="600519")),
        kwargs={"progress_callback": events.append},
    )
    worker.start()
    try:
        assert progress_seen.wait(timeout=1)
        assert any(event["type"] == "thinking" for event in events)
    finally:
        release_workers.set()
        worker.join(timeout=2)
    assert not worker.is_alive()


def test_parallel_discovery_propagates_runtime_contexts() -> None:
    orch = AgentOrchestrator(tool_registry=MagicMock(), llm_adapter=MagicMock())
    tech_agent = TechnicalAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    intel_agent = IntelAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    observed = []
    news_token = activate_news_evidence_scope()
    frozen_token = set_frozen_target_date(date(2026, 5, 22))
    diagnostic_token = activate_run_diagnostic_context(trace_id="wave-1")
    try:
        def make_fake_agent_run(agent_name):
            def fake_agent_run(run_ctx, progress_callback=None, timeout_seconds=None):
                del run_ctx, progress_callback, timeout_seconds
                record_news_evidence(5)
                record_provider_run(
                    data_type="daily_history",
                    provider=agent_name,
                    operation="wave1",
                    success=True,
                    record_count=1,
                )
                observed.append((agent_name, get_frozen_target_date()))
                return StageResult(stage_name=agent_name, status=StageStatus.COMPLETED)

            return fake_agent_run

        # Keep the real stage wrapper so this exercises the exact
        # copy_context().run boundary used by Wave 1.
        tech_agent.run = make_fake_agent_run("technical")  # type: ignore[method-assign]
        intel_agent.run = make_fake_agent_run("intel")  # type: ignore[method-assign]
        orch._run_discovery_wave_parallel(tech_agent, intel_agent, AgentContext(stock_code="600519"))

        assert sorted(observed) == [("intel", date(2026, 5, 22)), ("technical", date(2026, 5, 22))]
        assert get_current_news_evidence().total == 10
        assert len(current_diagnostic_snapshot()["provider_runs"]) == 2
    finally:
        reset_run_diagnostic_context(diagnostic_token)
        reset_frozen_target_date(frozen_token)
        reset_news_evidence_scope(news_token)


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
