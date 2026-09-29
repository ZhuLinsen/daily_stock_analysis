# -*- coding: utf-8 -*-
import math
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.agent.chat_context import (  # noqa: E402
    SUMMARY_USER_PREFIX,
    VisibleMessage,
    _split_protected_tail,
    build_agent_chat_context_bundle,
    build_visible_chat_history,
    estimate_text_tokens,
)
from src.agent.llm_adapter import LLMToolAdapter  # noqa: E402
from src.config import Config  # noqa: E402
from src.llm.usage import normalize_litellm_usage  # noqa: E402
from src.storage import DatabaseManager  # noqa: E402


def _reset_db() -> DatabaseManager:
    DatabaseManager.reset_instance()
    Config.reset_instance()
    return DatabaseManager(db_url="sqlite:///:memory:")


def _config(
    *,
    enabled: bool = True,
    trigger: int = 12000,
    protected: int = 1,
    profile: str = "balanced",
) -> SimpleNamespace:
    return SimpleNamespace(
        agent_context_compression_enabled=enabled,
        agent_context_compression_profile=profile,
        agent_context_compression_trigger_tokens=trigger,
        agent_context_protected_turns=protected,
        llm_model_list=[],
        agent_litellm_model="openai/test-model",
        litellm_model="openai/test-model",
        litellm_fallback_models=[],
    )


def _add_messages(db: DatabaseManager, session_id: str, messages: list[tuple[str, str]]) -> None:
    for role, content in messages:
        db.save_conversation_message(session_id, role, content)


def teardown_function() -> None:
    DatabaseManager.reset_instance()
    Config.reset_instance()


def test_disabled_compression_returns_recent_20_messages() -> None:
    db = _reset_db()
    session_id = "chat-disabled"
    _add_messages(db, session_id, [("user", f"msg-{idx}") for idx in range(25)])

    history = build_visible_chat_history(session_id, MagicMock(), _config(enabled=False))

    assert len(history) == 20
    assert history[0]["content"] == "msg-5"
    assert history[-1]["content"] == "msg-24"


def test_runtime_owned_history_ignores_litellm_compression_and_returns_recent_20() -> None:
    db = _reset_db()
    session_id = "chat-runtime-owned"
    _add_messages(db, session_id, [("user", f"msg-{idx}") for idx in range(25)])
    adapter = MagicMock()

    history = build_visible_chat_history(
        session_id,
        adapter,
        _config(enabled=True, trigger=1),
        allow_llm_compression=False,
    )

    assert len(history) == 20
    assert history[0]["content"] == "msg-5"
    assert history[-1]["content"] == "msg-24"
    adapter.call_text.assert_not_called()


def test_enabled_under_trigger_without_summary_returns_full_history_over_20() -> None:
    db = _reset_db()
    session_id = "chat-full-raw"
    _add_messages(db, session_id, [("user", f"msg-{idx}") for idx in range(25)])

    history = build_visible_chat_history(session_id, MagicMock(), _config(trigger=999999))

    assert len(history) == 25
    assert history[0]["content"] == "msg-0"
    assert history[-1]["content"] == "msg-24"


def test_existing_summary_under_trigger_returns_summary_and_uncovered_messages() -> None:
    db = _reset_db()
    session_id = "chat-summary-under"
    _add_messages(
        db,
        session_id,
        [
            ("user", "u1"),
            ("assistant", "a1"),
            ("user", "u2"),
            ("assistant", "a2"),
        ],
    )
    db.upsert_conversation_summary(session_id, "old summary", 2, 2, 10)

    history = build_visible_chat_history(session_id, MagicMock(), _config(trigger=999999))

    assert history[0]["role"] == "user"
    assert history[0]["content"].startswith(SUMMARY_USER_PREFIX)
    assert [msg["content"] for msg in history[1:]] == ["u2", "a2"]


def test_bundle_splices_provider_trace_before_visible_final_assistant() -> None:
    db = _reset_db()
    session_id = "chat-trace-splice"
    user_id = db.save_conversation_message(session_id, "user", "u1")
    assistant_id = db.save_conversation_message(session_id, "assistant", "a1-final")
    db.save_agent_provider_turn(
        session_id=session_id,
        run_id="run-1",
        provider="openai",
        model="openai/test-model",
        anchor_user_message_id=user_id,
        anchor_assistant_message_id=assistant_id,
        messages=[
            {
                "role": "assistant",
                "content": "checking",
                "reasoning_content": "r1",
                "tool_calls": [{"id": "call_1", "name": "echo", "arguments": {"message": "x"}}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "tool-result"},
        ],
        contains_reasoning=True,
        contains_tool_calls=True,
        contains_thinking_blocks=False,
        must_roundtrip=True,
        estimated_tokens=10,
    )

    bundle = build_agent_chat_context_bundle(session_id, MagicMock(), _config(enabled=False))

    assert [msg["role"] for msg in bundle.context_messages] == ["user", "assistant", "tool", "assistant"]
    assert bundle.context_messages[0]["content"] == "u1"
    assert bundle.context_messages[1]["reasoning_content"] == "r1"
    assert bundle.context_messages[2]["tool_call_id"] == "call_1"
    assert bundle.context_messages[3]["content"] == "a1-final"
    assert sum(1 for msg in bundle.context_messages if msg.get("content") == "a1-final") == 1
    assert bundle.diagnostics["trace_injected"] is True


def test_bundle_drops_trace_on_model_mismatch_budget_and_summarized_anchor() -> None:
    db = _reset_db()
    mismatch_session = "chat-trace-mismatch"
    user_id = db.save_conversation_message(mismatch_session, "user", "u1")
    assistant_id = db.save_conversation_message(mismatch_session, "assistant", "a1")
    db.save_agent_provider_turn(
        session_id=mismatch_session,
        run_id="run-mismatch",
        provider="deepseek",
        model="deepseek/deepseek-chat",
        anchor_user_message_id=user_id,
        anchor_assistant_message_id=assistant_id,
        messages=[{"role": "assistant", "reasoning_content": "r", "tool_calls": [{"id": "c", "name": "echo", "arguments": {}}]}],
        contains_reasoning=True,
        contains_tool_calls=True,
        contains_thinking_blocks=False,
        must_roundtrip=True,
        estimated_tokens=10,
    )

    mismatch = build_agent_chat_context_bundle(mismatch_session, MagicMock(), _config(enabled=False))

    assert mismatch.diagnostics["model_mismatch"] == 1
    assert mismatch.diagnostics["trace_injected"] is False
    assert all("reasoning_content" not in msg for msg in mismatch.context_messages)

    budget_session = "chat-trace-budget"
    user_id = db.save_conversation_message(budget_session, "user", "u1")
    assistant_id = db.save_conversation_message(budget_session, "assistant", "a1")
    db.save_agent_provider_turn(
        session_id=budget_session,
        run_id="run-budget",
        provider="openai",
        model="openai/test-model",
        anchor_user_message_id=user_id,
        anchor_assistant_message_id=assistant_id,
        messages=[{"role": "assistant", "reasoning_content": "r", "tool_calls": [{"id": "c", "name": "echo", "arguments": {}}]}],
        contains_reasoning=True,
        contains_tool_calls=True,
        contains_thinking_blocks=False,
        must_roundtrip=True,
        estimated_tokens=999999,
    )

    budget = build_agent_chat_context_bundle(budget_session, MagicMock(), _config(enabled=False))

    assert budget.diagnostics["budget_exceeded"] is True
    assert budget.diagnostics["trace_injected"] is False
    assert all("reasoning_content" not in msg for msg in budget.context_messages)

    summarized_session = "chat-trace-summary-anchor"
    user_id = db.save_conversation_message(summarized_session, "user", "u1")
    assistant_id = db.save_conversation_message(summarized_session, "assistant", "a1")
    db.save_conversation_message(summarized_session, "user", "u2")
    db.upsert_conversation_summary(summarized_session, "old summary", assistant_id, 2, 10)
    db.save_agent_provider_turn(
        session_id=summarized_session,
        run_id="run-summary",
        provider="openai",
        model="openai/test-model",
        anchor_user_message_id=user_id,
        anchor_assistant_message_id=assistant_id,
        messages=[{"role": "assistant", "reasoning_content": "r", "tool_calls": [{"id": "c", "name": "echo", "arguments": {}}]}],
        contains_reasoning=True,
        contains_tool_calls=True,
        contains_thinking_blocks=False,
        must_roundtrip=True,
        estimated_tokens=10,
    )

    summarized = build_agent_chat_context_bundle(summarized_session, MagicMock(), _config(trigger=999999))

    assert summarized.diagnostics["anchor_summarized"] == 1
    assert summarized.diagnostics["trace_injected"] is False
    assert all("reasoning_content" not in msg for msg in summarized.context_messages)


def test_bundle_injects_trace_for_configured_fallback_model_with_trace_metadata() -> None:
    db = _reset_db()
    session_id = "chat-trace-fallback-model"
    user_id = db.save_conversation_message(session_id, "user", "u1")
    assistant_id = db.save_conversation_message(session_id, "assistant", "a1-final")
    db.save_agent_provider_turn(
        session_id=session_id,
        run_id="run-fallback",
        provider="deepseek",
        model="deepseek/deepseek-chat",
        anchor_user_message_id=user_id,
        anchor_assistant_message_id=assistant_id,
        messages=[
            {
                "role": "assistant",
                "content": "checking",
                "reasoning_content": "r",
                "tool_calls": [{"id": "call_1", "name": "echo", "arguments": {}}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "tool-result"},
        ],
        contains_reasoning=True,
        contains_tool_calls=True,
        contains_thinking_blocks=False,
        must_roundtrip=True,
        estimated_tokens=10,
    )
    config = _config(enabled=False)
    config.agent_litellm_model = "openai/test-model"
    config.litellm_model = "openai/test-model"
    config.litellm_fallback_models = ["deepseek/deepseek-chat"]

    bundle = build_agent_chat_context_bundle(session_id, MagicMock(), config)

    assert bundle.diagnostics["trace_injected"] is True
    assistant_trace = bundle.context_messages[1]
    assert assistant_trace["role"] == "assistant"
    assert assistant_trace["reasoning_content"] == "r"
    assert assistant_trace["_trace_provider"] == "deepseek"
    assert assistant_trace["_trace_model"] == "deepseek/deepseek-chat"
    tool_trace = bundle.context_messages[2]
    assert tool_trace["role"] == "tool"
    assert tool_trace["_trace_provider"] == "deepseek"
    assert tool_trace["_trace_model"] == "deepseek/deepseek-chat"


def test_bundle_trace_is_replayed_only_for_matching_fallback_attempt() -> None:
    db = _reset_db()
    session_id = "chat-trace-fallback-attempt"
    user_id = db.save_conversation_message(session_id, "user", "u1")
    assistant_id = db.save_conversation_message(session_id, "assistant", "a1-final")
    db.save_agent_provider_turn(
        session_id=session_id,
        run_id="run-fallback-attempt",
        provider="deepseek",
        model="deepseek/deepseek-chat",
        anchor_user_message_id=user_id,
        anchor_assistant_message_id=assistant_id,
        messages=[
            {
                "role": "assistant",
                "content": "checking",
                "reasoning_content": "r",
                "tool_calls": [{"id": "call_1", "name": "echo", "arguments": {}}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "tool-result"},
        ],
        contains_reasoning=True,
        contains_tool_calls=True,
        contains_thinking_blocks=False,
        must_roundtrip=True,
        estimated_tokens=10,
    )
    config = _config(enabled=False)
    config.agent_litellm_model = "openai/test-model"
    config.litellm_model = "openai/test-model"
    config.litellm_fallback_models = ["deepseek/deepseek-chat"]
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    adapter._config = config

    bundle = build_agent_chat_context_bundle(session_id, MagicMock(), config)
    primary_messages = adapter._convert_messages(bundle.context_messages, target_model="openai/test-model")
    fallback_messages = adapter._convert_messages(bundle.context_messages, target_model="deepseek/deepseek-chat")

    assert bundle.diagnostics["trace_injected"] is True
    assert [msg["role"] for msg in primary_messages] == ["user", "assistant"]
    assert primary_messages[-1]["content"] == "a1-final"
    assert all(msg.get("tool_call_id") != "call_1" for msg in primary_messages)
    assert [msg["role"] for msg in fallback_messages] == ["user", "assistant", "tool", "assistant"]
    assert fallback_messages[1]["reasoning_content"] == "r"
    assert fallback_messages[2]["tool_call_id"] == "call_1"
    assert fallback_messages[-1]["content"] == "a1-final"


def test_bundle_does_not_match_hermes_only_fallback_trace() -> None:
    db = _reset_db()
    session_id = "chat-trace-hermes-fallback"
    user_id = db.save_conversation_message(session_id, "user", "u1")
    assistant_id = db.save_conversation_message(session_id, "assistant", "a1-final")
    db.save_agent_provider_turn(
        session_id=session_id,
        run_id="run-hermes-fallback",
        provider="openai",
        model="openai/hermes-agent",
        anchor_user_message_id=user_id,
        anchor_assistant_message_id=assistant_id,
        messages=[{"role": "assistant", "content": "hermes-trace"}],
        contains_reasoning=False,
        contains_tool_calls=False,
        contains_thinking_blocks=False,
        must_roundtrip=True,
        estimated_tokens=10,
    )
    config = _config(enabled=False)
    config.agent_litellm_model = "openai/test-model"
    config.litellm_model = "openai/test-model"
    config.litellm_fallback_models = ["openai/hermes-agent"]
    config.llm_model_list = [
        {
            "model_name": "openai/test-model",
            "litellm_params": {"model": "openai/test-model", "api_key": "sk-openai"},
        },
        {
            "model_name": "openai/hermes-agent",
            "litellm_params": {
                "model": "openai/hermes-agent",
                "api_key": "sk-hermes",
                "api_base": "http://127.0.0.1:8642/v1",
            },
            "model_info": {"dsa_channel": "hermes"},
        },
    ]

    bundle = build_agent_chat_context_bundle(session_id, MagicMock(), config)

    assert bundle.diagnostics["trace_injected"] is False
    assert bundle.diagnostics["model_mismatch"] == 1
    assert [msg["content"] for msg in bundle.context_messages] == ["u1", "a1-final"]


def test_bundle_does_not_fallback_to_unfiltered_try_order_for_hermes_only_agent() -> None:
    db = _reset_db()
    session_id = "chat-trace-hermes-only-agent"
    user_id = db.save_conversation_message(session_id, "user", "u1")
    assistant_id = db.save_conversation_message(session_id, "assistant", "a1-final")
    db.save_agent_provider_turn(
        session_id=session_id,
        run_id="run-hermes-only-agent",
        provider="openai",
        model="openai/hermes-agent",
        anchor_user_message_id=user_id,
        anchor_assistant_message_id=assistant_id,
        messages=[{"role": "assistant", "content": "hermes-trace"}],
        contains_reasoning=False,
        contains_tool_calls=False,
        contains_thinking_blocks=False,
        must_roundtrip=True,
        estimated_tokens=10,
    )
    config = _config(enabled=False)
    config.agent_litellm_model = ""
    config.litellm_model = "openai/hermes-agent"
    config.litellm_fallback_models = []
    config.llm_model_list = [
        {
            "model_name": "openai/hermes-agent",
            "litellm_params": {
                "model": "openai/hermes-agent",
                "api_key": "sk-hermes",
                "api_base": "http://127.0.0.1:8642/v1",
            },
            "model_info": {"dsa_channel": "hermes"},
        },
    ]

    bundle = build_agent_chat_context_bundle(session_id, MagicMock(), config)

    assert bundle.diagnostics["trace_injected"] is False
    assert bundle.diagnostics["model_mismatch"] == 1


def test_bundle_matches_slashless_router_alias_fallback_by_resolved_provider() -> None:
    db = _reset_db()
    session_id = "chat-trace-router-alias"
    user_id = db.save_conversation_message(session_id, "user", "u1")
    assistant_id = db.save_conversation_message(session_id, "assistant", "a1-final")
    db.save_agent_provider_turn(
        session_id=session_id,
        run_id="run-router-alias",
        provider="openai",
        model="gpt4o",
        anchor_user_message_id=user_id,
        anchor_assistant_message_id=assistant_id,
        messages=[
            {
                "role": "assistant",
                "content": "checking",
                "reasoning_content": "r",
                "tool_calls": [{"id": "call_1", "name": "echo", "arguments": {}}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "tool-result"},
        ],
        contains_reasoning=True,
        contains_tool_calls=True,
        contains_thinking_blocks=False,
        must_roundtrip=True,
        estimated_tokens=10,
    )
    config = _config(enabled=False)
    config.agent_litellm_model = "anthropic/claude-test"
    config.litellm_model = "anthropic/claude-test"
    config.litellm_fallback_models = ["gpt4o"]
    config.llm_model_list = [
        {
            "model_name": "gpt4o",
            "litellm_params": {"model": "openai/gpt-4o-mini"},
        }
    ]

    bundle = build_agent_chat_context_bundle(session_id, MagicMock(), config)

    assert bundle.diagnostics["trace_injected"] is True
    assert bundle.diagnostics["model_mismatch"] == 0
    assistant_trace = bundle.context_messages[1]
    assert assistant_trace["_trace_provider"] == "openai"
    assert assistant_trace["_trace_model"] == "gpt4o"


def test_over_trigger_generates_summary_and_updates_covered_message_id() -> None:
    db = _reset_db()
    session_id = "chat-summarize"
    _add_messages(
        db,
        session_id,
        [
            ("user", "u1"),
            ("assistant", "a1"),
            ("user", "u2"),
            ("assistant", "a2"),
            ("user", "u3"),
        ],
    )
    adapter = MagicMock()
    adapter.call_text.return_value = SimpleNamespace(
        content="## 会话摘要\n新摘要",
        provider="openai",
        model="openai/test-model",
        usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    )

    with patch("src.agent.chat_context.estimate_messages_tokens", return_value=999999):
        history = build_visible_chat_history(session_id, adapter, _config(trigger=1, protected=1))

    summary = db.get_conversation_summary(session_id)
    assert summary is not None
    assert summary["covered_message_id"] == 4
    assert summary["source_message_count"] == 4
    assert history[0]["content"].startswith(SUMMARY_USER_PREFIX)
    assert [msg["content"] for msg in history[1:]] == ["u3"]


def test_summary_compression_does_not_persist_agent_usage_without_provider_usage() -> None:
    db = _reset_db()
    session_id = "chat-summarize-no-usage"
    _add_messages(
        db,
        session_id,
        [
            ("user", "u1"),
            ("assistant", "a1"),
            ("user", "u2"),
        ],
    )
    adapter = MagicMock()
    adapter.call_text.return_value = SimpleNamespace(
        content="## 会话摘要\n新摘要",
        provider="openai",
        model="openai/test-model",
        usage={},
    )

    with patch("src.agent.chat_context.estimate_messages_tokens", return_value=999999):
        with patch("src.agent.chat_context.persist_llm_usage") as persist_usage:
            history = build_visible_chat_history(session_id, adapter, _config(trigger=1, protected=1))

    assert history[0]["content"].startswith(SUMMARY_USER_PREFIX)
    persist_usage.assert_not_called()


def test_summary_compression_does_not_persist_metadata_only_provider_usage() -> None:
    db = _reset_db()
    session_id = "chat-summarize-metadata-only-usage"
    _add_messages(
        db,
        session_id,
        [
            ("user", "u1"),
            ("assistant", "a1"),
            ("user", "u2"),
        ],
    )
    adapter = MagicMock()
    adapter.call_text.return_value = SimpleNamespace(
        content="## 会话摘要\n新摘要",
        provider="openai",
        model="openai/test-model",
        usage=normalize_litellm_usage(
            {"estimated_prefix_tokens": 123},
            model="openai/gpt-4o",
        ),
    )

    with patch("src.agent.chat_context.estimate_messages_tokens", return_value=999999):
        with patch("src.agent.chat_context.persist_llm_usage") as persist_usage:
            history = build_visible_chat_history(session_id, adapter, _config(trigger=1, protected=1))

    assert history[0]["content"].startswith(SUMMARY_USER_PREFIX)
    persist_usage.assert_not_called()


def test_summary_compression_persists_invalid_provider_usage_diagnostics() -> None:
    db = _reset_db()
    session_id = "chat-summarize-invalid-usage"
    _add_messages(
        db,
        session_id,
        [
            ("user", "u1"),
            ("assistant", "a1"),
            ("user", "u2"),
        ],
    )
    usage = normalize_litellm_usage({"prompt_tokens": -1}, model="openai/gpt-4o")
    adapter = MagicMock()
    adapter.call_text.return_value = SimpleNamespace(
        content="## 会话摘要\n新摘要",
        provider="openai",
        model="openai/test-model",
        usage=usage,
    )

    with patch("src.agent.chat_context.estimate_messages_tokens", return_value=999999):
        with patch("src.agent.chat_context.persist_llm_usage") as persist_usage:
            history = build_visible_chat_history(session_id, adapter, _config(trigger=1, protected=1))

    assert history[0]["content"].startswith(SUMMARY_USER_PREFIX)
    assert usage["cache_observation"] == "invalid_provider_usage"
    persist_usage.assert_called_once_with(usage, "openai/test-model", call_type="agent")


def test_summary_compression_persists_agent_usage_with_provider_usage() -> None:
    db = _reset_db()
    session_id = "chat-summarize-with-usage"
    _add_messages(
        db,
        session_id,
        [
            ("user", "u1"),
            ("assistant", "a1"),
            ("user", "u2"),
        ],
    )
    usage = {"total_tokens": 3}
    adapter = MagicMock()
    adapter.call_text.return_value = SimpleNamespace(
        content="## 会话摘要\n新摘要",
        provider="openai",
        model="openai/test-model",
        usage=usage,
    )

    with patch("src.agent.chat_context.estimate_messages_tokens", return_value=999999):
        with patch("src.agent.chat_context.persist_llm_usage") as persist_usage:
            history = build_visible_chat_history(session_id, adapter, _config(trigger=1, protected=1))

    assert history[0]["content"].startswith(SUMMARY_USER_PREFIX)
    persist_usage.assert_called_once_with(usage, "openai/test-model", call_type="agent")


def test_second_request_only_summarizes_incremental_unprotected_messages() -> None:
    db = _reset_db()
    session_id = "chat-incremental"
    _add_messages(
        db,
        session_id,
        [
            ("user", "u1"),
            ("assistant", "a1"),
            ("user", "u2"),
            ("assistant", "a2"),
            ("user", "u3"),
        ],
    )
    db.upsert_conversation_summary(session_id, "old summary", 2, 2, 10)
    adapter = MagicMock()
    adapter.call_text.return_value = SimpleNamespace(content="new summary", provider="openai", model="m", usage={})

    with patch("src.agent.chat_context.estimate_messages_tokens", return_value=999999):
        build_visible_chat_history(session_id, adapter, _config(trigger=1, protected=1))

    payload = adapter.call_text.call_args.args[0][1]["content"]
    assert "old summary" in payload
    assert "u2" in payload
    assert "a2" in payload
    assert "u1" not in payload
    assert "a1" not in payload
    assert "u3" not in payload
    assert db.get_conversation_summary(session_id)["covered_message_id"] == 4


def test_protected_tail_counts_recent_user_turns_and_keeps_following_messages() -> None:
    messages = [
        VisibleMessage(1, "user", "u1"),
        VisibleMessage(2, "assistant", "a1"),
        VisibleMessage(3, "assistant", "a-orphan"),
        VisibleMessage(4, "user", "u2"),
        VisibleMessage(5, "assistant", "a2"),
        VisibleMessage(6, "user", "u3"),
    ]

    tail = _split_protected_tail(messages, protected_turns=2)

    assert [msg.id for msg in tail] == [4, 5, 6]


def test_empty_to_summarize_warns_and_does_not_call_llm() -> None:
    db = _reset_db()
    session_id = "chat-protected-only"
    _add_messages(db, session_id, [("user", "u1"), ("assistant", "a1")])
    db.upsert_conversation_summary(session_id, "old summary", 2, 2, 10)
    adapter = MagicMock()

    with patch("src.agent.chat_context.estimate_messages_tokens", return_value=999999):
        with patch("src.agent.chat_context.logger.warning") as warning:
            history = build_visible_chat_history(session_id, adapter, _config(trigger=1, protected=1))

    adapter.call_text.assert_not_called()
    assert warning.called
    assert history[0]["content"].startswith(SUMMARY_USER_PREFIX)
    assert [msg["content"] for msg in history[1:]] == ["u1", "a1"]


def test_empty_to_summarize_without_summary_returns_full_history_and_does_not_call_llm() -> None:
    db = _reset_db()
    session_id = "chat-protected-only-no-summary"
    _add_messages(db, session_id, [("user", "u1"), ("assistant", "a1")])
    adapter = MagicMock()

    with patch("src.agent.chat_context.estimate_messages_tokens", return_value=999999):
        with patch("src.agent.chat_context.logger.warning") as warning:
            history = build_visible_chat_history(session_id, adapter, _config(trigger=1, protected=1))

    adapter.call_text.assert_not_called()
    assert warning.called
    assert history == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]


def test_summary_failure_falls_back_to_recent_20_without_old_summary() -> None:
    db = _reset_db()
    session_id = "chat-summary-fails"
    _add_messages(db, session_id, [("user", f"msg-{idx}") for idx in range(25)])
    adapter = MagicMock()
    adapter.call_text.return_value = SimpleNamespace(content="", provider="error", model="", usage={})

    with patch("src.agent.chat_context.estimate_messages_tokens", return_value=999999):
        history = build_visible_chat_history(session_id, adapter, _config(trigger=1, protected=1))

    assert len(history) == 20
    assert history[0]["content"] == "msg-5"


def test_summary_failure_with_old_summary_returns_candidate() -> None:
    db = _reset_db()
    session_id = "chat-summary-fails-old"
    _add_messages(db, session_id, [("user", "u1"), ("assistant", "a1"), ("user", "u2")])
    db.upsert_conversation_summary(session_id, "old summary", 2, 2, 10)
    adapter = MagicMock()
    adapter.call_text.return_value = SimpleNamespace(content="", provider="error", model="", usage={})

    with patch("src.agent.chat_context.estimate_messages_tokens", return_value=999999):
        history = build_visible_chat_history(session_id, adapter, _config(trigger=1, protected=1))

    assert history[0]["content"].startswith(SUMMARY_USER_PREFIX)
    assert [msg["content"] for msg in history[1:]] == ["u2"]


def test_token_estimator_falls_back_to_character_heuristic() -> None:
    with patch("src.agent.chat_context.get_effective_agent_primary_model", side_effect=RuntimeError("no model")):
        assert estimate_text_tokens("abcdefg", _config()) == math.ceil(7 / 3)
