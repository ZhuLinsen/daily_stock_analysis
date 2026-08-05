# -*- coding: utf-8 -*-
"""Agent Chat API transaction and compatibility regressions."""

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.v1.endpoints import agent as agent_endpoint
from src.config import Config
from src.services.agent_chat_session_service import AgentChatSessionService
from src.storage import DatabaseManager


def setup_function() -> None:
    DatabaseManager.reset_instance()
    Config.reset_instance()


def teardown_function() -> None:
    DatabaseManager.reset_instance()
    Config.reset_instance()


def _litellm_config(**overrides):
    values = {
        "agent_backend": "auto",
        "is_agent_available": lambda: True,
        "report_language": "zh",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _codex_config(**overrides):
    values = {
        "agent_backend": "codex_app_server",
        "agent_arch": "single",
        "agent_orchestrator_timeout_s": 600,
        "report_language": "zh",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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


async def _collect_stream_events(request: "agent_endpoint.ChatRequest") -> list[dict]:
    response = await agent_endpoint.agent_chat_stream(
        request,
        session_service=AgentChatSessionService(),
    )
    return [
        json.loads(chunk.removeprefix("data: ").strip())
        async for chunk in response.body_iterator
    ]


async def _immediate_to_thread(func, /, *args, **kwargs):
    return func(*args, **kwargs)


def test_chat_session_messages_api_does_not_expose_provider_trace(tmp_path: Path) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'trace.db'}")
    session_id = "api-trace-hidden"
    user_id = db.save_conversation_user_turn(
        session_id,
        "visible question",
        ["technical"],
    )
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
    assert response.json()["session_state"] == {
        "selected_skill_ids": ["technical"],
    }
    assert "SECRET_REASONING" not in response.text
    assert "SECRET_TOOL_RESULT" not in response.text


def test_agent_chat_forwards_stock_context_to_executor(tmp_path: Path) -> None:
    executor = MagicMock()
    executor.chat.return_value = _result()

    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.get_config", return_value=_litellm_config(report_language="en")), \
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
    assert kwargs["context"] == {
        "stock_code": "600519",
        "stock_name": "匿名标的",
        "report_language": "en",
    }


def test_agent_chat_preserves_explicit_report_language(tmp_path: Path) -> None:
    executor = MagicMock()
    executor.chat.return_value = _result()

    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.get_config", return_value=_litellm_config(report_language="en")), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor):
        response = TestClient(create_app(static_dir=tmp_path / "static")).post(
            "/api/v1/agent/chat",
            json={
                "message": "분석해 주세요",
                "session_id": "explicit-language",
                "context": {"report_language": "ko"},
            },
        )

    assert response.status_code == 200
    assert executor.chat.call_args.kwargs["context"]["report_language"] == "ko"


@pytest.mark.parametrize("provided_language", [None, "", "   "])
def test_agent_chat_treats_null_or_blank_report_language_as_missing(
    tmp_path: Path, provided_language
) -> None:
    executor = MagicMock()
    executor.chat.return_value = _result()

    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.get_config", return_value=_litellm_config(report_language="en")), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor):
        response = TestClient(create_app(static_dir=tmp_path / "static")).post(
            "/api/v1/agent/chat",
            json={
                "message": "analyze",
                "session_id": "default-language",
                "context": {"report_language": provided_language},
            },
        )

    assert response.status_code == 200
    assert executor.chat.call_args.kwargs["context"]["report_language"] == "en"


@pytest.mark.parametrize("provided_language", [None, "", "   "])
def test_agent_chat_stream_treats_null_or_blank_report_language_as_missing(
    tmp_path: Path, provided_language
) -> None:
    executor = _executor(_result(backend="litellm"))

    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
         patch("api.v1.endpoints.agent.get_config", return_value=_litellm_config(report_language="en")), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor):
        events = asyncio.run(
            _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="analyze",
                    session_id="stream-default-language",
                    context={"report_language": provided_language},
                )
            )
        )

    assert [event["type"] for event in events] == ["accepted", "done"]
    assert executor.prepare_turn.call_args.kwargs["context"]["report_language"] == "en"


@pytest.mark.parametrize("provided_language, expected_language", [
    (None, "en"),
    ("", "en"),
    ("   ", "en"),
    ("ko", "ko"),
])
def test_build_agent_chat_context_normalizes_default_report_language(
    provided_language, expected_language
) -> None:
    request = agent_endpoint.ChatRequest(
        message="question",
        context={"report_language": provided_language} if provided_language is not None else {"report_language": None},
    )

    context = agent_endpoint._build_agent_chat_context(
        request,
        _litellm_config(report_language="en"),
        skills=None,
    )

    assert context["report_language"] == expected_language


def test_requested_skill_normalization_reuses_agent_factory_catalog_rules() -> None:
    from src.agent.factory import normalize_requested_skill_ids

    skill_manager = MagicMock()
    skill_manager.list_skills.return_value = [
        SimpleNamespace(name="technical"),
        SimpleNamespace(name="risk"),
    ]

    with patch("src.agent.factory.get_skill_manager", return_value=skill_manager):
        normalized = normalize_requested_skill_ids(
            _litellm_config(),
            [" technical ", "technical", "unknown", "risk"],
        )

    assert normalized == ["technical", "risk"]


def test_agent_chat_inherits_saved_skills_without_rewriting_session_state(tmp_path: Path) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'inherit.db'}")
    db.save_conversation_user_turn("saved-session", "first", ["technical"])
    config = _litellm_config()
    executor = MagicMock()
    executor.chat.return_value = _result()

    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.get_config", return_value=config), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor) as build_executor:
        response = TestClient(create_app(static_dir=tmp_path / "static")).post(
            "/api/v1/agent/chat",
            json={
                "message": "follow up",
                "session_id": "saved-session",
                "context": {
                    "stock_code": "600519",
                    "skills": ["old_skill"],
                    "strategies": ["older_strategy"],
                },
            },
        )

    assert response.status_code == 200
    build_executor.assert_called_once_with(config, ["technical"])
    context = executor.chat.call_args.kwargs["context"]
    assert context["stock_code"] == "600519"
    assert context["skills"] == ["technical"]
    assert "strategies" not in context
    assert executor.chat.call_args.kwargs["selected_skill_ids"] is None


def test_agent_chat_all_invalid_skills_inherit_without_clearing_state(tmp_path: Path) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'all-invalid.db'}")
    db.save_conversation_user_turn("saved-session", "first", ["technical"])
    config = _litellm_config()
    executor = MagicMock()
    executor.chat.return_value = _result()
    skill_manager = MagicMock()
    skill_manager.list_skills.return_value = [SimpleNamespace(name="technical")]

    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.get_config", return_value=config), \
         patch("src.agent.factory.get_skill_manager", return_value=skill_manager), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor) as build_executor:
        response = TestClient(create_app(static_dir=tmp_path / "static")).post(
            "/api/v1/agent/chat",
            json={
                "message": "follow up",
                "session_id": "saved-session",
                "skills": ["old_technical"],
            },
        )

    assert response.status_code == 200
    build_executor.assert_called_once_with(config, ["technical"])
    assert executor.chat.call_args.kwargs["context"]["skills"] == ["technical"]
    assert executor.chat.call_args.kwargs["selected_skill_ids"] is None
    assert db.get_conversation_session_selected_skill_ids("saved-session") == [
        "technical"
    ]


def test_chat_session_messages_returns_null_when_state_is_missing(tmp_path: Path) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'default-state.db'}")
    db.save_conversation_message("legacy-session", "user", "legacy question")

    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.get_config", return_value=_litellm_config()):
        response = TestClient(create_app(static_dir=tmp_path / "static")).get(
            "/api/v1/agent/chat/sessions/legacy-session"
        )

    assert response.status_code == 200
    assert response.json()["session_state"] == {
        "selected_skill_ids": None,
    }


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

    async def exercise() -> dict:
        with patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("api.v1.endpoints.agent.get_config", return_value=_codex_config()), \
             patch("api.v1.endpoints.agent._get_agent_chat_status", side_effect=AssertionError("status probe repeated")), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            response = await agent_endpoint.agent_chat_stream(
                agent_endpoint.ChatRequest(
                    message="分析 AAPL",
                    session_id="accepted-session",
                    request_id="accepted-request",
                    context={"stock_code": "AAPL"},
                ),
                session_service=AgentChatSessionService(),
            )
            iterator = response.body_iterator
            first = json.loads((await anext(iterator)).removeprefix("data: ").strip())
            executor.prepare_turn.assert_called_once_with(
                message="分析 AAPL",
                session_id="accepted-session",
                context={"stock_code": "AAPL", "report_language": "zh"},
                selected_skill_ids=None,
            )
            executor.execute_turn.assert_not_called()
            await iterator.aclose()
            return first

    first_event = asyncio.run(exercise())
    assert first_event == {
        "type": "accepted",
        "backend": "codex_app_server",
        "request_id": "accepted-request",
        "session_id": "accepted-session",
    }
    executor.execute_turn.assert_not_called()


def test_stream_forwards_normalized_skill_selection_to_prepare_turn() -> None:
    executor = _executor(_result(backend="litellm"))
    config = _litellm_config()

    with patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
         patch("api.v1.endpoints.agent.get_config", return_value=config), \
         patch(
             "src.services.agent_chat_session_service.normalize_requested_skill_ids",
             return_value=["risk"],
         ), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor) as build_executor:
        events = asyncio.run(
            _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="check risk",
                    session_id="risk-session",
                    skills=[" risk ", "risk"],
                )
            )
        )

    assert [event["type"] for event in events] == ["accepted", "done"]
    build_executor.assert_called_once_with(config, ["risk"])
    executor.prepare_turn.assert_called_once_with(
        message="check risk",
        session_id="risk-session",
        context={"skills": ["risk"], "report_language": "zh"},
        selected_skill_ids=["risk"],
    )


def test_stream_all_invalid_skills_inherit_without_clearing_state() -> None:
    db = DatabaseManager(db_url="sqlite:///:memory:")
    db.save_conversation_user_turn("saved-session", "first", ["technical"])
    session_service = AgentChatSessionService(db)
    executor = _executor(_result(backend="litellm"))
    config = _litellm_config()
    skill_manager = MagicMock()
    skill_manager.list_skills.return_value = [SimpleNamespace(name="technical")]

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("api.v1.endpoints.agent.get_config", return_value=config), \
             patch("src.agent.factory.get_skill_manager", return_value=skill_manager), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor) as build_executor:
            response = await agent_endpoint.agent_chat_stream(
                agent_endpoint.ChatRequest(
                    message="follow up",
                    session_id="saved-session",
                    skills=["old_technical"],
                ),
                session_service=session_service,
            )
            events = [
                json.loads(chunk.removeprefix("data: ").strip())
                async for chunk in response.body_iterator
            ]

        build_executor.assert_called_once_with(config, ["technical"])
        return events

    events = asyncio.run(exercise())

    assert [event["type"] for event in events] == ["accepted", "done"]
    executor.prepare_turn.assert_called_once_with(
        message="follow up",
        session_id="saved-session",
        context={"skills": ["technical"], "report_language": "zh"},
        selected_skill_ids=None,
    )
    assert db.get_conversation_session_selected_skill_ids("saved-session") == [
        "technical"
    ]


def test_codex_stream_skill_resolution_failure_does_not_register_request() -> None:
    request_id = "skill-resolution-failure"
    session_service = MagicMock(spec=AgentChatSessionService)
    session_service.resolve_skill_selection.side_effect = RuntimeError("database read failed")

    try:
        with patch("api.v1.endpoints.agent.get_config", return_value=_codex_config()), \
             pytest.raises(RuntimeError, match="database read failed"):
            asyncio.run(
                agent_endpoint.agent_chat_stream(
                    agent_endpoint.ChatRequest(
                        message="question",
                        session_id="failed-session",
                        request_id=request_id,
                    ),
                    session_service=session_service,
                )
            )

        with agent_endpoint._ACTIVE_CODEX_STREAMS_LOCK:
            assert request_id not in agent_endpoint._ACTIVE_CODEX_STREAMS
    finally:
        with agent_endpoint._ACTIVE_CODEX_STREAMS_LOCK:
            agent_endpoint._ACTIVE_CODEX_STREAMS.pop(request_id, None)


@pytest.mark.parametrize("failure", ["context preparation failed", "database write failed"])
def test_stream_preparation_failure_emits_no_accepted_and_never_starts_backend(failure: str) -> None:
    executor = _executor()
    executor.prepare_turn.side_effect = RuntimeError(failure)

    async def exercise() -> list[dict]:
        with patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("api.v1.endpoints.agent.get_config", return_value=_codex_config()), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            response = await agent_endpoint.agent_chat_stream(
                agent_endpoint.ChatRequest(message="question", session_id="failed-session"),
                session_service=AgentChatSessionService(),
            )
            return [
                json.loads(chunk.removeprefix("data: ").strip())
                async for chunk in response.body_iterator
            ]

    events = asyncio.run(exercise())
    assert [event["type"] for event in events] == ["error"]
    assert events[0]["error_code"] == "request_not_accepted"
    executor.execute_turn.assert_not_called()


def test_server_selects_actual_backend_for_stream() -> None:
    executor = _executor(_result(backend="codex_app_server"))
    with patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
         patch("api.v1.endpoints.agent.get_config", return_value=_codex_config()), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor):
        async def exercise() -> dict:
            response = await agent_endpoint.agent_chat_stream(
                agent_endpoint.ChatRequest(message="分析 AAPL", session_id="actual-backend"),
                session_service=AgentChatSessionService(),
            )
            iterator = response.body_iterator
            first = json.loads((await anext(iterator)).removeprefix("data: ").strip())
            await iterator.aclose()
            return first

        first_event = asyncio.run(exercise())

    assert first_event["type"] == "accepted"
    assert first_event["backend"] == "codex_app_server"


def test_agent_chat_stream_cancels_backend_when_generator_closes() -> None:
    executor = _executor(_result(backend="codex_app_server", success=False, error_code="cancelled"))

    async def exercise() -> dict:
        with patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
             patch("api.v1.endpoints.agent.get_config", return_value=_codex_config()), \
             patch("api.v1.endpoints.agent._build_executor", return_value=executor):
            response = await agent_endpoint.agent_chat_stream(
                agent_endpoint.ChatRequest(message="question", session_id="cancel-session"),
                session_service=AgentChatSessionService(),
            )
            iterator = response.body_iterator
            accepted = json.loads((await anext(iterator)).removeprefix("data: ").strip())
            await iterator.aclose()
            return accepted

    accepted = asyncio.run(exercise())
    assert accepted["type"] == "accepted"
    assert accepted["backend"] == "codex_app_server"


def test_codex_stop_waits_for_cleanup_and_emits_one_terminal_event() -> None:
    cancel_event = threading.Event()
    with agent_endpoint._ACTIVE_CODEX_STREAMS_LOCK:
        agent_endpoint._ACTIVE_CODEX_STREAMS["cancel-request"] = cancel_event
    try:
        assert asyncio.run(agent_endpoint.cancel_agent_chat_stream("cancel-request")) == {
            "accepted": True,
            "request_id": "cancel-request",
        }
        assert cancel_event.is_set()
    finally:
        with agent_endpoint._ACTIVE_CODEX_STREAMS_LOCK:
            agent_endpoint._ACTIVE_CODEX_STREAMS.pop("cancel-request", None)


def test_codex_stop_rejects_unknown_or_finished_request() -> None:
    with pytest.raises(Exception) as exc_info:
        asyncio.run(agent_endpoint.cancel_agent_chat_stream("missing-request"))
    assert getattr(exc_info.value, "status_code", None) == 404


def test_litellm_stream_keeps_existing_execution_signature(tmp_path: Path) -> None:
    executor = _executor(_result(backend="litellm"))
    with patch("api.middlewares.auth.is_auth_enabled", return_value=False), \
         patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
         patch("api.v1.endpoints.agent.get_config", return_value=_litellm_config(report_language="en")), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor):
        events = asyncio.run(
            _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="question",
                    session_id="litellm-session",
                    context={"report_language": "ko"},
                )
            )
        )

    assert [event["type"] for event in events] == ["accepted", "done"]
    assert events[0]["backend"] == "litellm"
    assert executor.prepare_turn.call_args.kwargs["context"]["report_language"] == "ko"
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
         patch("api.v1.endpoints.agent.asyncio.to_thread", side_effect=_immediate_to_thread), \
         patch("api.v1.endpoints.agent.get_config", return_value=_litellm_config()), \
         patch("api.v1.endpoints.agent._build_executor", return_value=executor):
        events = asyncio.run(
            _collect_stream_events(
                agent_endpoint.ChatRequest(
                    message="question",
                    session_id="litellm-stream-error",
                )
            )
        )

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
