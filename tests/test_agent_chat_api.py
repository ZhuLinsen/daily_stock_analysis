# -*- coding: utf-8 -*-
"""Agent Chat API transaction and compatibility regressions."""

import asyncio
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.v1.endpoints import agent as agent_endpoint
from src.config import Config
from src.storage import DatabaseManager


def setup_function() -> None:
    DatabaseManager.reset_instance()
    Config.reset_instance()


def teardown_function() -> None:
    DatabaseManager.reset_instance()
    Config.reset_instance()


def _litellm_config(**overrides):
    return SimpleNamespace(
        agent_backend="auto",
        is_agent_available=lambda: True,
        **overrides,
    )


def _codex_config(**overrides):
    return SimpleNamespace(
        agent_backend="codex_app_server",
        agent_arch="single",
        agent_orchestrator_timeout_s=600,
        **overrides,
    )


def _result(*, backend: str = "litellm", success: bool = True, error_code=None):
    return SimpleNamespace(
        success=success,
        content="ok" if success else "",
        error=None if success else error_code,
        total_steps=1,
        backend=backend,
        error_code=error_code,
    )


def _executor(result=None) -> MagicMock:
    executor = MagicMock()
    executor.prepare_turn.return_value = object()
    executor.execute_turn.return_value = result or _result()
    return executor


def _sse_events(text: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def test_chat_session_messages_api_does_not_expose_provider_trace(tmp_path: Path) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'trace.db'}")
    session_id = "api-trace-hidden"
    user_id = db.save_conversation_message(session_id, "user", "visible question")
    assistant_id = db.save_conversation_message(session_id, "assistant", "visible answer")
    db.save_agent_provider_turn(
        session_id=session_id,
        run_id="run-hidden",
        provider="deepseek",
        model="deepseek/deepseek-chat",
        anchor_user_message_id=user_id,
        anchor_assistant_message_id=assistant_id,
        messages=[
            {
                "role": "assistant",
                "content": "checking",
                "reasoning_content": "SECRET_REASONING",
                "tool_calls": [{"id": "call_1", "name": "echo", "arguments": {}}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "SECRET_TOOL_RESULT"},
        ],
        contains_reasoning=True,
        contains_tool_calls=True,
        contains_thinking_blocks=False,
        must_roundtrip=True,
        estimated_tokens=10,
    )

    with patch("api.middlewares.auth.is_auth_enabled", return_value=False):
        response = TestClient(create_app(static_dir=tmp_path / "static")).get(
            f"/api/v1/agent/chat/sessions/{session_id}"
        )

    assert response.status_code == 200
    assert [(msg["role"], msg["content"]) for msg in response.json()["messages"]] == [
        ("user", "visible question"),
        ("assistant", "visible answer"),
    ]
    assert "SECRET_REASONING" not in response.text
    assert "SECRET_TOOL_RESULT" not in response.text


def test_agent_chat_forwards_stock_context_to_executor(tmp_path: Path) -> None:
    executor = MagicMock()
    executor.chat.return_value = _result()

    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.get_config", return_value=_litellm_config()), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor):
        response = TestClient(create_app(static_dir=tmp_path / "static")).post(
            "/api/v1/agent/chat",
            json={
                "message": "如果不考虑 TTM 呢",
                "session_id": "s1",
                "context": {"stock_code": "600519", "stock_name": "匿名标的"},
            },
        )

    assert response.status_code == 200
    kwargs = executor.chat.call_args.kwargs
    assert kwargs["context"] == {"stock_code": "600519", "stock_name": "匿名标的"}


def test_codex_agent_chat_rejects_non_streaming_entrypoint(tmp_path: Path) -> None:
    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.get_config", return_value=_codex_config()), \
         patch("api.v1.endpoints.agent._build_executor") as build_executor:
        response = TestClient(create_app(static_dir=tmp_path / "static")).post(
            "/api/v1/agent/chat",
            json={"message": "分析 600519"},
        )

    assert response.status_code == 400
    assert response.json()["error"] == "capability_unsupported"
    build_executor.assert_not_called()


def test_agent_status_exposes_only_compatibility_fields() -> None:
    payload = {
        "backend": "codex_app_server",
        "available": True,
        "experimental": True,
        "version": "codex-cli test",
        "error_code": None,
        "message": None,
        "stderr_preview": "must-not-leak",
    }
    with patch("api.v1.endpoints.agent.get_config", return_value=SimpleNamespace()), \
         patch("api.v1.endpoints.agent._get_agent_chat_status", return_value=payload):
        response = asyncio.run(agent_endpoint.get_agent_status())

    assert response.model_dump() == {
        "backend": "codex_app_server",
        "available": True,
        "experimental": True,
        "version": "codex-cli test",
        "error_code": None,
        "message": None,
    }


def test_agent_models_is_compatible_empty_list_for_codex() -> None:
    with patch("api.v1.endpoints.agent.get_config", return_value=_codex_config()):
        response = asyncio.run(agent_endpoint.get_agent_models())
    assert response.models == []


def test_agent_models_do_not_fall_back_to_litellm_for_codex_or_invalid_backend() -> None:
    deployment = {
        "deployment_id": "default-model",
        "model": "openai/model",
        "provider": "openai",
        "source": "env",
    }
    for config in (
        SimpleNamespace(agent_backend="invalid", agent_arch="single"),
        SimpleNamespace(agent_backend="codex_app_server", agent_arch="multi"),
    ):
        with patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("api.v1.endpoints.agent.list_agent_model_deployments", return_value=[deployment]) as deployments:
            response = asyncio.run(agent_endpoint.get_agent_models())
        assert response.models == []
        deployments.assert_not_called()


def test_agent_models_does_not_hide_unexpected_backend_resolution_errors() -> None:
    with patch("api.v1.endpoints.agent.get_config", return_value=_litellm_config()), \
         patch(
             "src.agent.agent_backend.resolve_agent_backend_id",
             side_effect=ValueError("programming error"),
         ), \
         pytest.raises(ValueError, match="programming error"):
        asyncio.run(agent_endpoint.get_agent_models())


def test_stream_prepares_and_persists_before_accepted_then_starts_backend() -> None:
    executor = _executor(_result(backend="codex_app_server"))

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.get_config", return_value=_codex_config()), \
             patch("api.v1.endpoints.agent._get_agent_chat_status", side_effect=AssertionError("status probe repeated")), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            response = await agent_endpoint.agent_chat_stream(
                agent_endpoint.ChatRequest(
                    message="分析 AAPL",
                    session_id="accepted-session",
                    request_id="accepted-request",
                    context={"stock_code": "AAPL"},
                )
            )
            iterator = response.body_iterator
            first = json.loads((await anext(iterator)).removeprefix("data: ").strip())
            executor.prepare_turn.assert_called_once_with(
                message="分析 AAPL",
                session_id="accepted-session",
                context={"stock_code": "AAPL"},
            )
            executor.execute_turn.assert_not_called()
            rest = [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in iterator]
            return [first, *rest]

    events = asyncio.run(exercise())
    assert events[0] == {
        "type": "accepted",
        "backend": "codex_app_server",
        "request_id": "accepted-request",
        "session_id": "accepted-session",
    }
    assert sum(event["type"] == "accepted" for event in events) == 1
    executor.execute_turn.assert_called_once()
    assert executor.execute_turn.call_args.kwargs["cancel_event"] is not None


@pytest.mark.parametrize("failure", ["context preparation failed", "database write failed"])
def test_stream_preparation_failure_emits_no_accepted_and_never_starts_backend(failure: str) -> None:
    executor = _executor()
    executor.prepare_turn.side_effect = RuntimeError(failure)

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.get_config", return_value=_codex_config()), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            response = await agent_endpoint.agent_chat_stream(
                agent_endpoint.ChatRequest(message="question", session_id="failed-session")
            )
            return [
                json.loads(chunk.removeprefix("data: ").strip())
                async for chunk in response.body_iterator
            ]

    events = asyncio.run(exercise())
    assert [event["type"] for event in events] == ["error"]
    assert events[0]["error_code"] == "request_not_accepted"
    executor.execute_turn.assert_not_called()


def test_server_selects_actual_backend_for_stream(tmp_path: Path) -> None:
    executor = _executor(_result(backend="codex_app_server"))
    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.get_config", return_value=_codex_config()), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor):
        response = TestClient(create_app(static_dir=tmp_path / "static")).post(
            "/api/v1/agent/chat/stream",
            json={"message": "分析 AAPL", "session_id": "actual-backend"},
        )

    assert response.status_code == 200
    events = _sse_events(response.text)
    assert events[0]["type"] == "accepted"
    assert events[0]["backend"] == "codex_app_server"


def test_agent_chat_stream_cancels_backend_when_generator_closes() -> None:
    captured_cancel_event = None
    release_worker = threading.Event()
    worker_finished = threading.Event()

    def execute_turn(_turn, **kwargs):
        nonlocal captured_cancel_event
        captured_cancel_event = kwargs["cancel_event"]
        kwargs["progress_callback"]({"type": "thinking", "step": 1, "message": "working"})
        captured_cancel_event.wait(timeout=2)
        release_worker.wait(timeout=2)
        worker_finished.set()
        return _result(backend="codex_app_server", success=False, error_code="cancelled")

    executor = _executor()
    executor.execute_turn.side_effect = execute_turn

    async def exercise() -> None:
        with patch("api.v1.endpoints.agent.get_config", return_value=_codex_config()), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            response = await agent_endpoint.agent_chat_stream(
                agent_endpoint.ChatRequest(message="question", session_id="cancel-session")
            )
            iterator = response.body_iterator
            assert '"type": "accepted"' in await anext(iterator)
            assert '"type": "thinking"' in await anext(iterator)
            close_task = asyncio.create_task(iterator.aclose())
            assert await asyncio.to_thread(captured_cancel_event.wait, 1)
            assert close_task.done() is False
            release_worker.set()
            await asyncio.wait_for(close_task, timeout=1)

    asyncio.run(exercise())
    assert captured_cancel_event is not None and captured_cancel_event.is_set()
    assert worker_finished.wait(timeout=2)


def test_codex_stop_waits_for_cleanup_and_emits_one_terminal_event() -> None:
    worker_entered = threading.Event()
    worker_finished = threading.Event()

    def execute_turn(_turn, **kwargs):
        cancel_event = kwargs["cancel_event"]
        kwargs["progress_callback"]({"type": "thinking", "step": 1, "message": "working"})
        worker_entered.set()
        assert cancel_event.wait(timeout=2)
        time.sleep(0.05)
        worker_finished.set()
        return SimpleNamespace(
            success=False,
            content="",
            error="本次 Codex Agent 问股已取消。",
            total_steps=1,
            backend="codex_app_server",
            error_code="cancelled",
        )

    executor = _executor()
    executor.execute_turn.side_effect = execute_turn

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.get_config", return_value=_codex_config()), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            response = await agent_endpoint.agent_chat_stream(
                agent_endpoint.ChatRequest(
                    message="question",
                    session_id="cancel-session",
                    request_id="cancel-request",
                )
            )
            iterator = response.body_iterator
            accepted = json.loads((await anext(iterator)).removeprefix("data: ").strip())
            thinking = json.loads((await anext(iterator)).removeprefix("data: ").strip())
            assert worker_entered.wait(timeout=1)
            assert await agent_endpoint.cancel_agent_chat_stream("cancel-request") == {
                "accepted": True,
                "request_id": "cancel-request",
            }
            rest = [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in iterator]
            return [accepted, thinking, *rest]

    events = asyncio.run(exercise())
    terminal = [event for event in events if event["type"] in {"done", "error"}]
    assert len(terminal) == 1
    assert terminal[0]["error_code"] == "cancelled"
    assert worker_finished.is_set()


def test_codex_stop_rejects_unknown_or_finished_request() -> None:
    with pytest.raises(Exception) as exc_info:
        asyncio.run(agent_endpoint.cancel_agent_chat_stream("missing-request"))
    assert getattr(exc_info.value, "status_code", None) == 404


def test_litellm_stream_keeps_existing_execution_signature(tmp_path: Path) -> None:
    executor = _executor(_result(backend="litellm"))
    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.get_config", return_value=_litellm_config()), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor):
        response = TestClient(create_app(static_dir=tmp_path / "static")).post(
            "/api/v1/agent/chat/stream",
            json={"message": "question", "session_id": "litellm-session"},
        )

    events = _sse_events(response.text)
    assert [event["type"] for event in events] == ["accepted", "done"]
    assert events[0]["backend"] == "litellm"
    assert "cancel_event" not in executor.execute_turn.call_args.kwargs


def test_litellm_non_streaming_error_keeps_legacy_detail(tmp_path: Path) -> None:
    executor = MagicMock()
    executor.chat.side_effect = RuntimeError("legacy failure")
    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.get_config", return_value=_litellm_config()), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor):
        response = TestClient(create_app(static_dir=tmp_path / "static")).post(
            "/api/v1/agent/chat",
            json={"message": "question", "session_id": "litellm-error"},
        )
    assert response.status_code == 500
    assert response.json()["message"] == "legacy failure"


def test_litellm_streaming_error_follows_accepted(tmp_path: Path) -> None:
    executor = _executor()
    executor.execute_turn.side_effect = RuntimeError("legacy failure")
    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.get_config", return_value=_litellm_config()), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor):
        response = TestClient(create_app(static_dir=tmp_path / "static")).post(
            "/api/v1/agent/chat/stream",
            json={"message": "question", "session_id": "litellm-stream-error"},
        )
    events = _sse_events(response.text)
    assert [event["type"] for event in events] == ["accepted", "error"]
    assert events[1]["message"] == "legacy failure"


def test_research_ignores_codex_chat_backend_and_keeps_litellm_route() -> None:
    config = SimpleNamespace(
        agent_backend="codex_app_server",
        is_agent_available=lambda: True,
        agent_deep_research_budget=30000,
        agent_deep_research_timeout=180,
    )
    result = SimpleNamespace(
        success=True,
        report="research report",
        sub_questions=["q1"],
        total_tokens=12,
        error=None,
        timed_out=False,
    )
    research_agent = MagicMock()
    research_agent.research.return_value = result

    with patch("api.v1.endpoints.agent.get_config", return_value=config), \
         patch("src.agent.research.ResearchAgent", return_value=research_agent), \
         patch("src.agent.factory.get_tool_registry", return_value=MagicMock()), \
         patch("src.agent.llm_adapter.LLMToolAdapter", return_value=MagicMock()):
        response = asyncio.run(
            agent_endpoint.agent_research(agent_endpoint.ResearchRequest(question="why"))
        )

    assert response.success is True
    assert response.content == "research report"
    research_agent.research.assert_called_once()


def test_codex_chat_availability_does_not_make_research_available() -> None:
    config = SimpleNamespace(agent_backend="codex_app_server", is_agent_available=lambda: False)
    with patch("api.v1.endpoints.agent.get_config", return_value=config), \
         pytest.raises(Exception) as exc_info:
        asyncio.run(agent_endpoint.agent_research(agent_endpoint.ResearchRequest(question="why")))
    assert getattr(exc_info.value, "status_code", None) == 400
