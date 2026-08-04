# -*- coding: utf-8 -*-
"""Agent Chat session service tests."""

from types import SimpleNamespace
from unittest.mock import patch

from src.services.agent_chat_session_service import AgentChatSessionService
from src.storage import DatabaseManager


def test_skill_selection_distinguishes_inherit_clear_and_explicit() -> None:
    db = DatabaseManager(db_url="sqlite:///:memory:")
    service = AgentChatSessionService(db)
    config = SimpleNamespace()

    new_selection = service.resolve_skill_selection(config, "new-session", None)
    assert new_selection.effective_skill_ids is None
    assert new_selection.selected_skill_ids_update is None

    db.save_conversation_user_turn(
        "saved-session",
        "question",
        ["technical", "risk"],
    )
    inherited = service.resolve_skill_selection(config, "saved-session", None)
    assert inherited.effective_skill_ids == ["technical", "risk"]
    assert inherited.selected_skill_ids_update is None

    cleared = service.resolve_skill_selection(config, "saved-session", [])
    assert cleared.effective_skill_ids == []
    assert cleared.selected_skill_ids_update == []

    with patch(
        "src.services.agent_chat_session_service.normalize_requested_skill_ids",
        return_value=["technical"],
    ) as normalize:
        explicit = service.resolve_skill_selection(
            config,
            "saved-session",
            [" technical ", "technical", "unknown"],
        )

    assert explicit.effective_skill_ids == ["technical"]
    assert explicit.selected_skill_ids_update == ["technical"]
    normalize.assert_called_once_with(
        config,
        [" technical ", "technical", "unknown"],
    )


def test_session_detail_resolves_runtime_default_without_persisting_it() -> None:
    db = DatabaseManager(db_url="sqlite:///:memory:")
    service = AgentChatSessionService(db)
    db.save_conversation_message("legacy-session", "user", "legacy question")

    with patch(
        "src.services.agent_chat_session_service.resolve_skill_prompt_state",
        return_value=SimpleNamespace(skills_to_activate=["bull_trend"]),
    ):
        detail = service.get_session_detail(
            SimpleNamespace(),
            "legacy-session",
            limit=100,
        )

    assert [message["content"] for message in detail.messages] == ["legacy question"]
    assert detail.selected_skill_ids == ["bull_trend"]
    assert db.get_conversation_session_selected_skill_ids("legacy-session") is None
