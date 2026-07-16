# -*- coding: utf-8 -*-
"""Focused runtime coverage for structured timeout and budget degradation."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("litellm", MagicMock())

from src.agent.agents.base_agent import BaseAgent
from src.agent.disagreement import DegradedReason
from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus
from src.agent.runner import _build_timeout_result


def _orchestrator(*, timeout=0):
    return AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(
            agent_orchestrator_timeout_s=timeout,
            agent_risk_override=True,
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
                "position_advice": {
                    "no_position": "watch",
                    "has_position": "hold",
                },
            }
        },
    }


class _OpinionStage:
    def __init__(self, name, signal="buy", *, final_dashboard=False):
        self.agent_name = name
        self.signal = signal
        self.final_dashboard = final_dashboard
        self.tool_names = []

    def run(self, ctx, progress_callback=None, timeout_seconds=None):
        opinion = AgentOpinion(
            agent_name=self.agent_name,
            signal=self.signal,
            confidence=0.8,
            reasoning="fixture",
        )
        ctx.add_opinion(opinion)
        if self.final_dashboard:
            dashboard = _dashboard(self.signal)
            opinion.raw_data = dashboard
            ctx.set_data("final_dashboard", dashboard)
        return StageResult(
            stage_name=self.agent_name,
            status=StageStatus.COMPLETED,
            opinion=opinion,
        )


class _FailedStage:
    def __init__(self, name, *, error, failure_reason=None):
        self.agent_name = name
        self.error = error
        self.failure_reason = failure_reason
        self.tool_names = []

    def run(self, ctx, progress_callback=None, timeout_seconds=None):
        return StageResult(
            stage_name=self.agent_name,
            status=StageStatus.FAILED,
            error=self.error,
            failure_reason=self.failure_reason,
        )


def _explanation(result):
    assert result.success
    assert result.dashboard is not None
    return result.dashboard["dashboard"]["agent_disagreement_explanation"]


def _clock(values, fallback):
    timeline = iter(values)

    def _next():
        return next(timeline, fallback)

    return _next


@pytest.mark.parametrize(
    ("skipped_stage", "agents", "times"),
    [
        (
            "decision",
            [_OpinionStage("technical"), _OpinionStage("decision", final_dashboard=True)],
            [0.0, 0.1, 0.2, 0.3, 14.6],
        ),
        (
            "risk",
            [_OpinionStage("technical"), _OpinionStage("intel", "hold"), _OpinionStage("risk", "sell")],
            [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 14.6],
        ),
    ],
)
def test_budget_skip_records_real_stage_in_partial_dashboard(skipped_stage, agents, times):
    orchestrator = _orchestrator(timeout=20)
    ctx = AgentContext(query="test", stock_code="600519", stock_name="Test Stock")
    progress_events = []

    with patch.object(orchestrator, "_build_agent_chain", return_value=agents):
        with patch("src.agent.orchestrator.time.time", side_effect=_clock(times, 14.7)):
            result = orchestrator._execute_pipeline(
                ctx,
                parse_dashboard=True,
                progress_callback=progress_events.append,
            )

    explanation = _explanation(result)
    assert explanation["degraded_events"] == [
        {"stage": skipped_stage, "reason": "budget_skip"},
    ]
    assert explanation["decision_path"] == "degraded_synthesis"
    assert "insufficient budget" in result.error.lower()
    assert any(
        event.get("type") == "pipeline_budget_skipped"
        and event.get("stage") == skipped_stage
        for event in progress_events
    )
    assert all(
        event["stage"] not in {"budget", "budget_skip"}
        for event in explanation["degraded_events"]
    )


def test_pipeline_timeout_before_stage_records_next_real_stage():
    orchestrator = _orchestrator(timeout=1)
    ctx = AgentContext(query="test", stock_code="600519", stock_name="Test Stock")
    agents = [_OpinionStage("technical"), _OpinionStage("intel", "hold")]
    progress_events = []

    with patch.object(orchestrator, "_build_agent_chain", return_value=agents):
        with patch(
            "src.agent.orchestrator.time.time",
            side_effect=_clock([0.0, 0.1, 0.2, 0.3, 1.2], 1.3),
        ):
            result = orchestrator._execute_pipeline(
                ctx,
                parse_dashboard=True,
                progress_callback=progress_events.append,
            )

    explanation = _explanation(result)
    assert explanation["degraded_events"] == [
        {"stage": "intel", "reason": "timeout"},
    ]
    assert "timed out" in result.error.lower()
    assert any(
        event.get("type") == "pipeline_timeout" and event.get("stage") == "intel"
        for event in progress_events
    )
    assert all(event["stage"] != "timeout" for event in explanation["degraded_events"])


def test_pipeline_timeout_after_stage_records_completed_real_stage():
    orchestrator = _orchestrator(timeout=1)
    ctx = AgentContext(query="test", stock_code="600519", stock_name="Test Stock")
    agents = [_OpinionStage("technical")]

    with patch.object(orchestrator, "_build_agent_chain", return_value=agents):
        with patch(
            "src.agent.orchestrator.time.time",
            side_effect=_clock([0.0, 0.1, 0.2, 1.2], 1.3),
        ):
            result = orchestrator._execute_pipeline(ctx, parse_dashboard=True)

    explanation = _explanation(result)
    assert explanation["degraded_events"] == [
        {"stage": "technical", "reason": "timeout"},
    ]
    assert explanation["decision_path"] == "degraded_synthesis"
    assert "timed out" in result.error.lower()


@pytest.mark.parametrize(
    ("error", "failure_reason", "expected_reason"),
    [
        ("opaque provider termination", "timeout", "timeout"),
        ("Agent timed out after 1 second", None, "stage_failure"),
    ],
)
def test_non_critical_failure_uses_structured_reason_not_error_text(
    error,
    failure_reason,
    expected_reason,
):
    orchestrator = _orchestrator()
    ctx = AgentContext(query="test", stock_code="600519", stock_name="Test Stock")
    agents = [
        _OpinionStage("technical"),
        _FailedStage("intel", error=error, failure_reason=failure_reason),
        _OpinionStage("decision", final_dashboard=True),
    ]

    with patch.object(orchestrator, "_build_agent_chain", return_value=agents):
        result = orchestrator._execute_pipeline(ctx, parse_dashboard=True)

    explanation = _explanation(result)
    assert explanation["degraded_events"] == [
        {"stage": "intel", "reason": expected_reason},
    ]
    assert ctx.meta["degraded_stages"] == [
        {"stage_name": "intel", "status": "failed", "non_critical": True},
    ]
    serialized = str(explanation["degraded_events"]).lower()
    for forbidden in ("error", "message", "exception", "traceback", "reasoning", "raw_data"):
        assert forbidden not in serialized


def test_degraded_event_deduplicates_same_pair_but_allows_distinct_reasons():
    ctx = AgentContext(query="test")
    orchestrator = _orchestrator()

    orchestrator._record_degraded_event(
        ctx,
        stage="intel",
        reason=DegradedReason.TIMEOUT,
    )
    orchestrator._record_degraded_event(
        ctx,
        stage="intel",
        reason=DegradedReason.TIMEOUT,
    )
    orchestrator._record_degraded_event(
        ctx,
        stage="intel",
        reason=DegradedReason.STAGE_FAILURE,
    )

    assert ctx.meta["degraded_events"] == [
        {"stage": "intel", "reason": "timeout"},
        {"stage": "intel", "reason": "stage_failure"},
    ]


def test_base_agent_propagates_structured_loop_timeout_reason():
    class _TestAgent(BaseAgent):
        agent_name = "intel"

        def system_prompt(self, ctx):
            return "system"

        def build_user_message(self, ctx):
            return "user"

    agent = _TestAgent(MagicMock(), MagicMock())
    loop_result = _build_timeout_result(
        start_time=0.0,
        max_wall_clock_seconds=1.0,
        step=1,
        tool_calls_log=[],
        total_tokens=0,
        provider_used="",
        models_used=[],
        messages=[],
    )

    with patch("src.agent.agents.base_agent.run_agent_loop", return_value=loop_result):
        result = agent.run(AgentContext(query="test"))

    assert result.status == StageStatus.FAILED
    assert result.error == loop_result.error
    assert result.failure_reason == "timeout"


def test_base_agent_marks_timeout_exception_without_matching_its_message():
    class _TestAgent(BaseAgent):
        agent_name = "intel"

        def system_prompt(self, ctx):
            return "system"

        def build_user_message(self, ctx):
            return "user"

    agent = _TestAgent(MagicMock(), MagicMock())

    with patch(
        "src.agent.agents.base_agent.run_agent_loop",
        side_effect=TimeoutError("opaque provider termination"),
    ):
        result = agent.run(AgentContext(query="test"))

    assert result.status == StageStatus.FAILED
    assert result.error == "opaque provider termination"
    assert result.failure_reason == "timeout"


def test_critical_failure_without_dashboard_does_not_fabricate_explanation():
    orchestrator = _orchestrator()
    ctx = AgentContext(query="test", stock_code="600519")
    technical = _FailedStage(
        "technical",
        error="opaque timeout",
        failure_reason="timeout",
    )

    with patch.object(orchestrator, "_build_agent_chain", return_value=[technical]):
        result = orchestrator._execute_pipeline(ctx, parse_dashboard=True)

    assert result.success is False
    assert result.dashboard is None
    assert "agent_disagreement_explanation" not in str(result.content)
