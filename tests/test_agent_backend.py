# -*- coding: utf-8 -*-
"""AgentBackend contract and LiteLLM parity tests.

The Codex App Server backend was removed; provider API (LiteLLM) is the only
Chat backend, so these tests cover the remaining contract and guard against
the removed backend being reintroduced through config values.
"""

from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.agent.agent_backend import (
    AgentRunRequest,
    AgentRunResult,
    LiteLLMAgentBackend,
    resolve_agent_backend_id,
)
from src.agent.chat_executor import AgentChatExecutor
from src.agent.runner import run_agent_loop
from src.agent.tools.registry import ToolRegistry
from src.llm.backend_registry import REMOVED_AGENT_BACKEND_IDS


class _FinalAnswerAdapter:
    def __init__(self) -> None:
        self.calls = []

    def call_with_tools(self, messages, tools, timeout=None):
        self.calls.append((messages, tools, timeout))
        from src.agent.llm_adapter import LLMResponse

        return LLMResponse(content="answer", provider="deepseek", model="deepseek/chat")


def _request(**overrides):
    values = {
        "system_prompt": "system",
        "history_messages": [{"role": "assistant", "content": "history"}],
        "user_message": "question",
        "session_id": "session-1",
        "stock_scope": None,
        "max_steps": 3,
        "max_wall_clock_seconds": 30,
        "progress_callback": None,
        "cancel_event": None,
    }
    values.update(overrides)
    return AgentRunRequest(**values)


def test_agent_run_request_does_not_carry_tool_dependencies() -> None:
    names = {item.name for item in fields(AgentRunRequest)}
    assert "tool_registry" not in names
    assert "tool_surface" not in names


def test_agent_run_result_contains_only_consumed_terminal_state() -> None:
    names = {item.name for item in fields(AgentRunResult)}
    assert "session_id" not in names
    assert "finish_reason" not in names


def test_auto_agent_backend_remains_litellm() -> None:
    assert resolve_agent_backend_id(SimpleNamespace(agent_backend="auto")) == "litellm"
    assert resolve_agent_backend_id(SimpleNamespace()) == "litellm"


@pytest.mark.parametrize("removed_backend", sorted(REMOVED_AGENT_BACKEND_IDS))
def test_removed_codex_backend_is_rejected(removed_backend: str) -> None:
    with pytest.raises(Exception) as exc_info:
        resolve_agent_backend_id(SimpleNamespace(agent_backend=removed_backend))

    assert "Unsupported AGENT_BACKEND" in str(exc_info.value)


def test_litellm_multi_chat_keeps_existing_orchestrator_factory() -> None:
    sentinel = object()
    with patch("src.agent.factory.build_agent_executor", return_value=sentinel) as build_existing:
        from src.agent.factory import build_agent_chat_executor

        result = build_agent_chat_executor(
            SimpleNamespace(agent_backend="auto", agent_arch="multi"),
            skills=["bull_trend"],
        )

    assert result is sentinel
    build_existing.assert_called_once()


def test_litellm_backend_matches_existing_runner_result() -> None:
    registry = ToolRegistry()
    direct_events = []
    wrapped_events = []
    direct = run_agent_loop(
        messages=[
            {"role": "system", "content": "system"},
            {"role": "assistant", "content": "history"},
            {"role": "user", "content": "question"},
        ],
        tool_registry=registry,
        llm_adapter=_FinalAnswerAdapter(),
        max_steps=3,
        progress_callback=direct_events.append,
        max_wall_clock_seconds=30,
    )
    wrapped = LiteLLMAgentBackend(registry, _FinalAnswerAdapter()).run(
        _request(progress_callback=wrapped_events.append)
    )

    assert wrapped.success == direct.success
    assert wrapped.final_answer == direct.content
    assert wrapped.tool_calls_log == direct.tool_calls_log
    assert wrapped.total_steps == direct.total_steps
    assert wrapped.model == direct.model
    assert wrapped.diagnostics["provider"] == direct.provider
    assert wrapped.error_message == direct.error
    assert wrapped.messages == direct.messages
    assert wrapped.usage == (
        {"total_tokens": direct.total_tokens} if direct.total_tokens > 0 else None
    )
    assert wrapped_events == direct_events
    assert wrapped.backend == "litellm"


def test_litellm_preparation_keeps_the_existing_chat_workflow() -> None:
    backend = LiteLLMAgentBackend(ToolRegistry(), _FinalAnswerAdapter())
    executor = AgentChatExecutor(
        backend=backend,
        config=SimpleNamespace(),
        context_llm_adapter=object(),
    )

    with patch("src.agent.executor.build_agent_chat_context_bundle") as build_context, patch(
        "src.agent.chat_executor.conversation_manager.get_or_create"
    ), patch(
        "src.agent.chat_executor.conversation_manager.add_message",
        return_value=1,
    ):
        build_context.return_value.context_messages = []
        turn = executor.prepare_turn(
            message="分析 AAPL",
            session_id="session-1",
            context={"stock_code": "AAPL"},
        )

    assert "get_realtime_quote" in turn.prepared.system_prompt
    assert "get_daily_history" in turn.prepared.system_prompt
    assert "analyze_trend" in turn.prepared.system_prompt
    assert "get_chip_distribution" in turn.prepared.system_prompt
    assert "search_stock_news" in turn.prepared.system_prompt


def test_removed_backend_modules_are_absent() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "src/agent/codex_agent_backend.py",
        "src/agent/codex_app_server_transport.py",
        "src/agent/codex_tool_process.py",
        "src/agent/tool_surface.py",
        "src/llm/local_cli_backend.py",
    ):
        assert not (root / relative_path).exists(), relative_path
