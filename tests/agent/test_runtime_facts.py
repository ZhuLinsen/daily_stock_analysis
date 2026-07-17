# -*- coding: utf-8 -*-
"""Runtime coverage for internal Agent facts and reserved-field cleanup."""

import json
import sys
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.modules.setdefault("litellm", MagicMock())

from src.agent.agents.base_agent import BaseAgent
from src.agent.executor import AgentExecutor
from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import (
    AgentContext,
    AgentOpinion,
    StageFailureReason,
    StageResult,
    StageStatus,
)
from src.agent.runner import (
    RunLoopResult,
    _build_budget_guard_result,
    _build_timeout_result,
    run_agent_loop,
)
from src.agent.runtime_facts import (
    BaseAgentOpinionFact,
    DegradedEvent,
    build_agent_runtime_facts,
)


def _orchestrator(*, risk_override=True):
    return AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(
            agent_orchestrator_timeout_s=0,
            agent_risk_override=risk_override,
        ),
    )


def _dashboard(signal="buy"):
    return {
        "stock_name": "Test Stock",
        "decision_type": signal,
        "sentiment_score": 72,
        "operation_advice": "test advice",
        "analysis_summary": "test summary",
        "dashboard": {
            "core_conclusion": {
                "one_sentence": "test conclusion",
                "position_advice": {"no_position": "watch", "has_position": "hold"},
            }
        },
    }


def _clock(values, fallback):
    timeline = iter(values)

    def _next():
        return next(timeline, fallback)

    return _next


class _Stage:
    def __init__(self, name, signal="buy", *, status=StageStatus.COMPLETED, failure_reason=None):
        self.agent_name = name
        self.signal = signal
        self.status = status
        self.failure_reason = failure_reason
        self.tool_names = []

    def run(self, ctx, progress_callback=None, timeout_seconds=None):
        if self.status == StageStatus.FAILED:
            return StageResult(
                stage_name=self.agent_name,
                status=self.status,
                error="opaque provider failure",
                failure_reason=self.failure_reason,
            )
        raw_data = {}
        if self.agent_name == "risk":
            raw_data = {"veto_buy": True}
        opinion = AgentOpinion(
            agent_name=self.agent_name,
            signal=self.signal,
            confidence=0.8,
            reasoning="private reasoning",
            raw_data=raw_data,
        )
        ctx.add_opinion(opinion)
        if self.agent_name == "decision":
            dashboard = _dashboard(self.signal)
            opinion.raw_data = dashboard
            ctx.set_data("final_dashboard", dashboard)
        return StageResult(
            stage_name=self.agent_name,
            status=self.status,
            opinion=opinion,
        )


class _TestAgent(BaseAgent):
    agent_name = "intel"

    def system_prompt(self, ctx):
        return "system"

    def build_user_message(self, ctx):
        return "user"


def test_runtime_facts_only_project_independent_low_sensitivity_opinions():
    ctx = AgentContext()
    ctx.add_opinion(AgentOpinion(
        agent_name="technical",
        signal="strong_buy",
        confidence=0.876,
        reasoning="secret reasoning",
        raw_data={"token": "secret-token"},
    ))
    ctx.add_opinion(AgentOpinion(
        agent_name="risk",
        signal="buy",
        confidence=0.7,
        reasoning="risk clear",
    ))
    ctx.add_opinion(AgentOpinion(agent_name="skill_consensus", signal="buy", confidence=0.9))
    ctx.add_opinion(AgentOpinion(agent_name="strategy_consensus", signal="buy", confidence=0.9))
    ctx.add_opinion(AgentOpinion(agent_name="decision", signal="buy", confidence=0.9))

    facts = build_agent_runtime_facts(ctx)

    assert facts.base_agent_opinions == (
        BaseAgentOpinionFact(agent="technical", signal="strong_buy", confidence=0.88),
        BaseAgentOpinionFact(agent="risk", signal="hold", confidence=0.7),
    )
    serialized = json.dumps(asdict(facts), ensure_ascii=False, default=str).lower()
    for forbidden in ("reasoning", "raw_data", "token", "secret"):
        assert forbidden not in serialized


def test_legacy_executor_content_uses_sanitized_dashboard():
    payload = _dashboard()
    payload["agent_disagreement_explanation"] = {"token": "top-secret"}
    payload["dashboard"]["agent_disagreement_explanation"] = {"reasoning": "private"}
    loop_result = RunLoopResult(success=True, content=json.dumps(payload, ensure_ascii=False))
    executor = AgentExecutor(MagicMock(), MagicMock())

    with patch("src.agent.executor.run_agent_loop", return_value=loop_result):
        result = executor._run_loop([], [], parse_dashboard=True)

    assert result.success is True
    assert result.dashboard is not None
    assert "agent_disagreement_explanation" not in result.dashboard
    assert "agent_disagreement_explanation" not in result.dashboard["dashboard"]
    assert "agent_disagreement_explanation" not in result.content
    assert "top-secret" not in result.content
    assert "private" not in result.content


def test_orchestrator_returns_internal_facts_without_public_dashboard_fields():
    orchestrator = _orchestrator()
    ctx = AgentContext(query="test", stock_code="600519", stock_name="Test Stock")
    stages = [
        _Stage("technical", "buy"),
        _Stage("intel", status=StageStatus.FAILED, failure_reason=StageFailureReason.TIMEOUT),
        _Stage("risk", "hold"),
        _Stage("decision", "buy"),
    ]
    call_order = []
    normalized_dashboards = []
    normalize_dashboard = orchestrator._normalize_dashboard_payload
    apply_risk_override = orchestrator._apply_risk_override

    def _normalize_once(payload, runtime_ctx):
        normalized = normalize_dashboard(payload, runtime_ctx)
        normalized_dashboards.append(normalized)
        call_order.append("normalize")
        return normalized

    def _apply_after_normalize(runtime_ctx):
        assert normalized_dashboards
        assert runtime_ctx.get_data("final_dashboard") is normalized_dashboards[-1]
        call_order.append("risk")
        return apply_risk_override(runtime_ctx)

    with (
        patch.object(orchestrator, "_build_agent_chain", return_value=stages),
        patch.object(
            orchestrator,
            "_normalize_dashboard_payload",
            side_effect=_normalize_once,
        ) as normalize_spy,
        patch.object(
            orchestrator,
            "_apply_risk_override",
            side_effect=_apply_after_normalize,
        ) as risk_spy,
    ):
        result = orchestrator._execute_pipeline(ctx, parse_dashboard=True)

    assert result.success is True
    assert result.dashboard["decision_type"] == "hold"
    normalize_spy.assert_called_once()
    risk_spy.assert_called_once_with(ctx)
    assert call_order == ["normalize", "risk"]
    assert result.runtime_facts is not None
    assert result.runtime_facts.degraded_events == (
        DegradedEvent(stage="intel", reason=StageFailureReason.TIMEOUT),
    )
    assert [fact.agent for fact in result.runtime_facts.base_agent_opinions] == [
        "technical",
        "risk",
    ]
    application = result.runtime_facts.risk_override_application
    assert application is not None
    assert application.applied is True
    assert application.post_risk_signal.value == "hold"
    assert application.from_signal.value == "buy"
    assert application.to_signal.value == "hold"
    assert "agent_disagreement_explanation" not in json.dumps(result.dashboard)
    assert "runtime_facts" not in result.content


def test_unknown_custom_failure_reason_falls_back_without_breaking_pipeline():
    orchestrator = _orchestrator()
    ctx = AgentContext(query="test", stock_code="600519")
    stages = [
        _Stage("technical", "buy"),
        _Stage("intel", status=StageStatus.FAILED, failure_reason="provider_timeout"),
        _Stage("decision", "buy"),
    ]

    with patch.object(orchestrator, "_build_agent_chain", return_value=stages):
        result = orchestrator._execute_pipeline(ctx, parse_dashboard=True)

    assert result.success is True
    assert result.runtime_facts is not None
    assert result.runtime_facts.degraded_events == (
        DegradedEvent(stage="intel", reason=StageFailureReason.STAGE_FAILURE),
    )


def test_critical_stage_failure_is_not_reported_as_degraded_event():
    orchestrator = _orchestrator()
    ctx = AgentContext(query="test", stock_code="600519")
    stages = [
        _Stage(
            "technical",
            status=StageStatus.FAILED,
            failure_reason=StageFailureReason.STAGE_FAILURE,
        ),
    ]

    with patch.object(orchestrator, "_build_agent_chain", return_value=stages):
        result = orchestrator._execute_pipeline(ctx, parse_dashboard=True)

    assert result.success is False
    assert result.runtime_facts is not None
    assert result.runtime_facts.degraded_events == ()
    assert "degraded_events" not in ctx.meta


def test_public_orchestrator_result_carries_internal_facts_only():
    orchestrator = _orchestrator()
    stages = [_Stage("technical", "buy"), _Stage("decision", "buy")]

    with patch.object(orchestrator, "_build_agent_chain", return_value=stages):
        result = orchestrator.run("analyze", {"stock_code": "600519"})

    assert result.runtime_facts is not None
    assert [fact.agent for fact in result.runtime_facts.base_agent_opinions] == ["technical"]
    assert "runtime_facts" not in result.content
    assert "agent_disagreement_explanation" not in result.content


def test_pipeline_budget_guard_records_skipped_real_stage():
    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(
            agent_orchestrator_timeout_s=20,
            agent_risk_override=True,
        ),
    )
    ctx = AgentContext(query="test", stock_code="600519")
    stages = [_Stage("technical", "buy"), _Stage("decision", "buy")]

    with patch.object(orchestrator, "_build_agent_chain", return_value=stages):
        with patch(
            "src.agent.orchestrator.time.time",
            side_effect=_clock([0.0, 0.1, 0.2, 0.3, 14.6], 14.7),
        ):
            result = orchestrator._execute_pipeline(ctx, parse_dashboard=True)

    assert result.runtime_facts is not None
    assert result.runtime_facts.degraded_events == (
        DegradedEvent(stage="decision", reason=StageFailureReason.BUDGET_SKIP),
    )
    assert "insufficient budget" in result.error.lower()


def test_pipeline_timeout_records_next_real_stage():
    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(
            agent_orchestrator_timeout_s=1,
            agent_risk_override=True,
        ),
    )
    ctx = AgentContext(query="test", stock_code="600519")
    stages = [_Stage("technical", "buy"), _Stage("intel", "hold")]

    with patch.object(orchestrator, "_build_agent_chain", return_value=stages):
        with patch(
            "src.agent.orchestrator.time.time",
            side_effect=_clock([0.0, 0.1, 0.2, 0.3, 1.2], 1.3),
        ):
            result = orchestrator._execute_pipeline(ctx, parse_dashboard=True)

    assert result.runtime_facts is not None
    assert result.runtime_facts.degraded_events == (
        DegradedEvent(stage="intel", reason=StageFailureReason.TIMEOUT),
    )
    assert "timed out" in result.error.lower()


def test_orchestrator_cleans_forged_fields_from_direct_dashboard_input():
    orchestrator = _orchestrator()
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8))
    ctx.add_opinion(AgentOpinion(agent_name="decision", signal="buy", confidence=0.8))
    payload = _dashboard("buy")
    payload["agent_disagreement_explanation"] = {
        "token": "top-secret",
        "reasoning": "private top-level reasoning",
    }
    payload["dashboard"]["agent_disagreement_explanation"] = {
        "raw_data": {"secret": "nested-secret"},
        "error": "private nested error",
    }
    ctx.set_data("final_dashboard", payload)

    dashboard, content = orchestrator._resolve_final_output(ctx, parse_dashboard=True)

    assert dashboard is not None
    assert "agent_disagreement_explanation" not in dashboard
    assert "agent_disagreement_explanation" not in dashboard["dashboard"]
    serialized = json.dumps(dashboard, ensure_ascii=False).lower()
    for forbidden in (
        "top-secret",
        "nested-secret",
        "private top-level reasoning",
        "private nested error",
    ):
        assert forbidden not in serialized
        assert forbidden not in content.lower()


def test_runner_failure_sources_propagate_through_base_agent():
    timeout_result = _build_timeout_result(
        start_time=0.0,
        max_wall_clock_seconds=1.0,
        step=1,
        tool_calls_log=[],
        total_tokens=0,
        provider_used="test",
        models_used=[],
        messages=[],
    )
    budget_result = _build_budget_guard_result(
        start_time=0.0,
        step=1,
        tool_calls_log=[],
        total_tokens=0,
        provider_used="test",
        models_used=[],
        messages=[],
        remaining_timeout_s=0.5,
        min_step_budget_s=1.0,
    )
    max_steps_result = run_agent_loop(
        messages=[],
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        max_steps=0,
    )

    agent = _TestAgent(MagicMock(), MagicMock())
    for loop_result, expected_reason in (
        (timeout_result, StageFailureReason.TIMEOUT),
        (budget_result, StageFailureReason.BUDGET_SKIP),
        (max_steps_result, StageFailureReason.STAGE_FAILURE),
    ):
        with patch("src.agent.agents.base_agent.run_agent_loop", return_value=loop_result):
            stage_result = agent.run(AgentContext())

        assert stage_result.status == StageStatus.FAILED
        assert stage_result.failure_reason == expected_reason

    with patch("src.agent.agents.base_agent.run_agent_loop", side_effect=RuntimeError("opaque")):
        stage_result = agent.run(AgentContext())

    assert stage_result.status == StageStatus.FAILED
    assert stage_result.failure_reason == StageFailureReason.STAGE_FAILURE
