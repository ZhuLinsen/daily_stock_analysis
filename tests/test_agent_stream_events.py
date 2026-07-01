# -*- coding: utf-8 -*-
"""Tests for agent progress stream event helpers."""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent.llm_adapter import LLMResponse
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


def test_run_agent_loop_emits_stage_start_and_legacy_progress_events() -> None:
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
    assert any(event["type"] == "thinking" and "step" in event for event in events)
    assert any(event["type"] == "generating" and "step" in event for event in events)
