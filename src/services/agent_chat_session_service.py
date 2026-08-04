# -*- coding: utf-8 -*-
"""Agent Chat session state service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.agent.factory import normalize_requested_skill_ids
from src.storage import DatabaseManager


@dataclass(frozen=True)
class ChatSkillSelection:
    """Effective Skill ids and the optional state update for one chat turn."""

    effective_skill_ids: Optional[List[str]]
    selected_skill_ids_update: Optional[List[str]]


@dataclass(frozen=True)
class ChatSessionDetail:
    """Visible messages and the persisted Skill selection for one session."""

    messages: List[Dict[str, Any]]
    selected_skill_ids: Optional[List[str]]


class AgentChatSessionService:
    """Coordinate Agent Chat session state without exposing storage to HTTP handlers."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def resolve_skill_selection(
        self,
        config,
        session_id: str,
        requested_skill_ids: Optional[List[str]],
    ) -> ChatSkillSelection:
        if requested_skill_ids is None:
            return ChatSkillSelection(
                effective_skill_ids=(
                    self.db.get_conversation_session_selected_skill_ids(session_id)
                ),
                selected_skill_ids_update=None,
            )
        if not requested_skill_ids:
            return ChatSkillSelection(
                effective_skill_ids=[],
                selected_skill_ids_update=[],
            )

        normalized = normalize_requested_skill_ids(config, requested_skill_ids)
        if not normalized:
            return ChatSkillSelection(
                effective_skill_ids=(
                    self.db.get_conversation_session_selected_skill_ids(session_id)
                ),
                selected_skill_ids_update=None,
            )
        return ChatSkillSelection(
            effective_skill_ids=normalized,
            selected_skill_ids_update=normalized,
        )

    def list_sessions(
        self,
        limit: int,
        user_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        return self.db.get_chat_sessions(
            limit=limit,
            session_prefix=user_id,
            extra_session_ids=[user_id] if user_id else None,
        )

    def get_session_detail(
        self,
        session_id: str,
        limit: int,
    ) -> ChatSessionDetail:
        messages = self.db.get_conversation_messages(session_id, limit=limit)
        selected_skill_ids = self.db.get_conversation_session_selected_skill_ids(session_id)

        return ChatSessionDetail(
            messages=messages,
            selected_skill_ids=selected_skill_ids,
        )

    def delete_session(self, session_id: str) -> int:
        return self.db.delete_conversation_session(session_id)
