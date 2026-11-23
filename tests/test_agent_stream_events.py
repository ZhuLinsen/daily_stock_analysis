# -*- coding: utf-8 -*-
"""Tests for agent progress stream event helpers."""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent.agents.base_agent import BaseAgent
from src.agent.llm_adapter import LLMResponse
from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import AgentContext, StageResult, StageStatus
from src.agent.runner import run_agent_loop
from src.agent.stream_events import stream_event
from src.agent.tools.registry import ToolDefinition, ToolParameter, ToolRegistry


def _make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo",
            description="Echoes the message",
            parameters=[
                ToolParameter(name="message", type="string", description="Message"),
            ],
            handler=lambda message: {"echo": message},
        )
    )
    return registry


class _StreamTestAgent(BaseAgent):
    max_steps = 1

    def __init__(self, agent_name, tool_registry, llm_adapter):
        super().__init__(tool_registry=tool_registry, llm_adapter=llm_adapter)
        self.agent_name = agent_name

    def system_prompt(self, ctx: AgentContext) -> str:
        return f"{self.agent_name} system"

    def build_user_message(self, ctx: AgentContext) -> str:
        return ctx.query

    def post_process(self, ctx: AgentContext, raw_text: str) -> None:
        if self.agent_name == "decision":
            ctx.set_data("final_dashboard_raw", raw_text)
        return None


def test_stream_event_keeps_legacy_fields_and_drops_none() -> None:
    event = stream_event(
        "tool_done",
        step=2,
        tool="echo",
        success=False,
        duration=0.0,
        message=None,
    )

    assert event == {
        "type": "tool_done",
        "step": 2,
        "tool": "echo",
        "success": False,
        "duration": 0.0,
    }


def test_stream_event_supports_stage_metadata() -> None:
    event = stream_event(
        "stage_start",
        stage="decision",
        message="Starting decision analysis...",
        meta={"mode": "single"},
    )

    assert event["type"] == "stage_start"
    assert event["stage"] == "decision"
    assert event["message"] == "Starting decision analysis..."
    assert event["meta"] == {"mode": "single"}


def test_run_agent_loop_emits_paired_stage_and_legacy_progress_events() -> None:
    adapter = MagicMock()
    adapter.call_with_tools.return_value = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage={},
        provider="openai",
        model="openai/gpt-test",
    )
    events = []

    result = run_agent_loop(
        messages=[{"role": "user", "content": "Analyze"}],
        tool_registry=_make_registry(),
        llm_adapter=adapter,
        max_steps=1,
        progress_callback=events.append,
    )

    assert result.success is True
    assert events[0] == {
        "type": "stage_start",
        "stage": "agent_loop",
        "message": "Starting agent analysis...",
    }
    assert events[-1]["type"] == "stage_done"
    assert events[-1]["stage"] == "agent_loop"
    assert events[-1]["status"] == "completed"
    assert "duration" in events[-1]
    assert any(event["type"] == "thinking" and "step" in event for event in events)
    assert any(event["type"] == "generating" and "step" in event for event in events)


def test_orchestrator_real_agent_path_does_not_emit_nested_agent_loop_stage() -> None:
    adapter = MagicMock()
    adapter.call_with_tools.side_effect = [
        LLMResponse(
            content="Technical done.",
            tool_calls=[],
            usage={},
            provider="openai",
            model="openai/gpt-test",
        ),
        LLMResponse(
            content="Decision done.",
            tool_calls=[],
            usage={},
            provider="openai",
            model="openai/gpt-test",
        ),
    ]
    registry = _make_registry()
    orch = AgentOrchestrator(
        tool_registry=registry,
        llm_adapter=adapter,
        mode="quick",
        config=SimpleNamespace(agent_orchestrator_timeout_s=0),
    )
    ctx = AgentContext(query="Analyze 600519", stock_code="600519")
    agents = [
        _StreamTestAgent("technical", registry, adapter),
        _StreamTestAgent("decision", registry, adapter),
    ]
    events = []

    with patch.object(orch, "_build_agent_chain", return_value=agents):
        result = orch._execute_pipeline(
            ctx,
            parse_dashboard=False,
            progress_callback=events.append,
        )

    assert result.success is True
    assert result.content == "Decision done."
    stage_events = [
        (event["type"], event.get("stage"))
        for event in events
        if event["type"] in {"stage_start", "stage_done"}
    ]
    assert stage_events == [
        ("stage_start", "technical"),
        ("stage_done", "technical"),
        ("stage_start", "decision"),
        ("stage_done", "decision"),
    ]
    assert ("stage_start", "agent_loop") not in stage_events
    assert ("stage_done", "agent_loop") not in stage_events
    assert any(event["type"] == "thinking" for event in events)
    assert any(event["type"] == "generating" for event in events)


def test_orchestrator_emits_stage_start_and_done_events() -> None:
    orch = AgentOrchestrator(
        tool_registry=_make_registry(),
        llm_adapter=MagicMock(),
        mode="quick",
        config=SimpleNamespace(agent_orchestrator_timeout_s=0),
    )
    ctx = AgentContext(query="Analyze 600519", stock_code="600519")
    agents = [
        SimpleNamespace(agent_name="technical"),
        SimpleNamespace(agent_name="decision"),
    ]
    events = []

    def _run_stage(agent, run_ctx, **_kwargs):
        if agent.agent_name == "decision":
            run_ctx.set_data("final_dashboard_raw", "Done.")
        return StageResult(
            stage_name=agent.agent_name,
            status=StageStatus.COMPLETED,
            duration_s=0.25,
            meta={"models_used": [f"mock/{agent.agent_name}"]},
        )

    with patch.object(orch, "_build_agent_chain", return_value=agents), patch.object(
        orch,
        "_run_stage_agent",
        side_effect=_run_stage,
    ):
        result = orch._execute_pipeline(
            ctx,
            parse_dashboard=False,
            progress_callback=events.append,
        )

    assert result.success is True
    assert result.content == "Done."
    assert events == [
        {
            "type": "stage_start",
            "stage": "technical",
            "message": "Starting technical analysis...",
        },
        {
            "type": "stage_done",
            "stage": "technical",
            "status": "completed",
            "duration": 0.25,
        },
        {
            "type": "stage_start",
            "stage": "decision",
            "message": "Starting decision analysis...",
        },
        {
            "type": "stage_done",
            "stage": "decision",
            "status": "completed",
            "duration": 0.25,
        },
    ]


def test_orchestrator_emits_stage_done_before_timeout_after_stage() -> None:
    orch = AgentOrchestrator(
        tool_registry=_make_registry(),
        llm_adapter=MagicMock(),
        mode="quick",
        config=SimpleNamespace(agent_orchestrator_timeout_s=1),
    )
    ctx = AgentContext(query="Analyze 600519", stock_code="600519")
    agents = [SimpleNamespace(agent_name="technical")]
    events = []

    def _run_stage(agent, _run_ctx, **_kwargs):
        return StageResult(
            stage_name=agent.agent_name,
            status=StageStatus.COMPLETED,
            duration_s=0.25,
            meta={"models_used": ["mock/technical"]},
        )

    time_values = iter([0.0, 0.0])

    def _time():
        return next(time_values, 1.1)

    with patch.object(orch, "_build_agent_chain", return_value=agents), patch.object(
        orch,
        "_run_stage_agent",
        side_effect=_run_stage,
    ), patch("src.agent.orchestrator.time.time", side_effect=_time):
        result = orch._execute_pipeline(
            ctx,
            parse_dashboard=False,
            progress_callback=events.append,
        )

    assert result.success is False
    assert result.error == "Pipeline timed out after 1.10s (limit: 1s)"
    assert events == [
        {
            "type": "stage_start",
            "stage": "technical",
            "message": "Starting technical analysis...",
        },
        {
            "type": "stage_done",
            "stage": "technical",
            "status": "completed",
            "duration": 0.25,
        },
        {
            "type": "pipeline_timeout",
            "stage": "technical",
            "elapsed": 1.1,
            "timeout": 1,
        },
    ]


def test_orchestrator_emits_budget_skipped_before_unstarted_stage() -> None:
    orch = AgentOrchestrator(
        tool_registry=_make_registry(),
        llm_adapter=MagicMock(),
        mode="quick",
        config=SimpleNamespace(agent_orchestrator_timeout_s=20),
    )
    ctx = AgentContext(query="Analyze 600519", stock_code="600519")
    ctx.meta["response_mode"] = "chat"
    agents = [
        SimpleNamespace(agent_name="technical"),
        SimpleNamespace(agent_name="decision"),
    ]
    events = []

    def _run_stage(agent, run_ctx, **_kwargs):
        run_ctx.set_data("final_response_text", "Technical partial.")
        return StageResult(
            stage_name=agent.agent_name,
            status=StageStatus.COMPLETED,
            duration_s=0.25,
            meta={"models_used": [f"mock/{agent.agent_name}"]},
        )

    time_values = iter([0.0, 0.0, 6.0, 6.0])

    def _time():
        return next(time_values, 6.0)

    with patch.object(orch, "_build_agent_chain", return_value=agents), patch.object(
        orch,
        "_run_stage_agent",
        side_effect=_run_stage,
    ), patch("src.agent.orchestrator.time.time", side_effect=_time):
        result = orch._execute_pipeline(
            ctx,
            parse_dashboard=False,
            progress_callback=events.append,
        )

    assert result.success is True
    assert result.content == "Technical partial."
    assert result.error == (
        "Pipeline skipped before stage 'decision' due to insufficient budget "
        "(14.0s remaining, minimum 15s required)"
    )
    assert events == [
        {
            "type": "stage_start",
            "stage": "technical",
            "message": "Starting technical analysis...",
        },
        {
            "type": "stage_done",
            "stage": "technical",
            "status": "completed",
            "duration": 0.25,
        },
        {
            "type": "pipeline_budget_skipped",
            "stage": "decision",
            "elapsed": 6.0,
            "timeout": 20,
            "remaining": 14.0,
            "minimum": 15,
            "reason": "insufficient_budget",
            "message": "Skipped decision analysis due to insufficient remaining budget",
        },
    ]
    assert "pipeline_timeout" not in {event["type"] for event in events}
    assert ("stage_start", "decision") not in {
        (event["type"], event.get("stage")) for event in events
    }
