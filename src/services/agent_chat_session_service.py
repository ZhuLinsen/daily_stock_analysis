# -*- coding: utf-8 -*-
"""Agent Chat session state service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.agent.factory import normalize_requested_skill_ids
from src.agent.stock_scope import (
    SWITCH_CLEANUP_KEYS, StockIdentity, StockScope, StockScopeResolution, resolve_stock_scope,
)
from src.agent.chat_object_decision import decide_chat_object, validate_chat_identity as _code_identity
from src.data.stock_index_loader import get_chat_stock_lookup
from src.services.stock_list_parser import IndexRegistry, _index_entry_from_row
from src.storage import ChatSessionStateConflict, DatabaseManager


def _stock_lookup() -> tuple[IndexRegistry, dict]:
    lookup = get_chat_stock_lookup()
    entries = [_index_entry_from_row(row) for row in lookup["index_rows"]]
    return IndexRegistry(entry for entry in entries if entry is not None), lookup


def _stock_record(identity: StockIdentity, lookup: dict, registry: IndexRegistry) -> Dict[str, Any]:
    name = identity.stock_name
    for code, label, kind in lookup["codes"].get(identity.stock_code.upper(), ()):
        candidate = StockIdentity.from_code(code, registry)
        if kind == candidate.asset_type and candidate == identity:
            name = label
            break
    return dict(identity.as_payload(), stock_name=name)


def _hint_identity(context: Dict[str, Any], registry: IndexRegistry, lookup: dict) -> Optional[StockIdentity]:
    try:
        identity = _code_identity(context.get("stock_code"), registry, lookup)
    except (TypeError, ValueError):
        return None
    if (context.get("canonical_id", identity.canonical_id) != identity.canonical_id
            or context.get("asset_type", identity.asset_type) != identity.asset_type):
        return None
    return identity


def _identity(stock: Dict[str, Any]) -> StockIdentity:
    return StockIdentity(stock["stock_code"], stock["canonical_id"], stock["asset_type"], stock.get("stock_name"))


def _active_from_snapshot(snapshot: Dict[str, Any], registry: IndexRegistry, lookup: dict) -> Optional[Dict[str, Any]]:
    if not snapshot["session_generation"]:
        return None
    if snapshot["session_state_version"] > 0:
        stock = snapshot["active_stock_context"]
        if (snapshot["last_accepted_user_anchor"] is None
                or snapshot["latest_user_anchor"] != snapshot["last_accepted_user_anchor"]):
            return None
        if stock is not None and not any(
            message["id"] == stock["source_message_id"] and message["role"] == "user"
            and message["created_at"] == stock["updated_at"] for message in snapshot["messages"]
        ):
            return None
        return dict(stock) if stock else None

    active = None
    for message in snapshot["messages"]:
        if message["role"] != "user":
            continue
        current = _identity(active) if active else None
        decision = decide_chat_object(message["content"], current, registry, lookup)
        if decision.kind == "confirm" and decision.target.kind == "code":
            active = dict(_stock_record(decision.target.identity, lookup, registry),
                          source_message_id=message["id"], updated_at=message["created_at"])
        elif decision.changes_target and (
            decision.target is None or decision.target.identity != current
        ):
            # Historical names cannot confirm a target-position code fact.
            # Negative/question/compare/maintain decisions never invalidate it.
            active = None
    return active


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
    active_stock_context: Optional[Dict[str, Any]] = None
    session_state_version: int = 0
    session_generation: Optional[str] = None


@dataclass(frozen=True)
class ResolvedChatTurn:
    message: str
    snapshot: Dict[str, Any]
    active_stock_context: Optional[Dict[str, Any]]
    stock_scope: StockScope
    effective_context: Dict[str, Any]
    skill_selection: ChatSkillSelection
    confirm_stock: bool = False
    clarification: Optional[str] = None
    compatibility_disposition: str = "invalidate"


class AgentChatSessionService:
    """Coordinate Agent Chat session state without exposing storage to HTTP handlers."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def resolve_skill_selection(
        self,
        config,
        session_id: str,
        requested_skill_ids: Optional[List[str]],
        *, snapshot: Optional[Dict[str, Any]] = None,
    ) -> ChatSkillSelection:
        def inherited():
            return (snapshot["selected_skill_ids"] if snapshot is not None
                    else self.db.get_conversation_session_selected_skill_ids(session_id))
        if requested_skill_ids is None:
            return ChatSkillSelection(
                effective_skill_ids=(
                    inherited()
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
                    inherited()
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
        snapshot = self.db.read_chat_session_snapshot(session_id)
        registry, lookup = _stock_lookup()

        return ChatSessionDetail(
            messages=[dict(message, id=str(message["id"])) for message in
                      (snapshot["messages"][:limit] if limit >= 0 else snapshot["messages"])],
            selected_skill_ids=snapshot["selected_skill_ids"],
            active_stock_context=_active_from_snapshot(snapshot, registry, lookup),
            session_state_version=snapshot["session_state_version"],
            session_generation=snapshot["session_generation"],
        )

    def prepare_session_turn(
        self, config: Any, session_id: str, message: str,
        requested_skill_ids: Optional[List[str]] = None,
        *, context: Optional[Dict[str, Any]] = None, expected_generation: Optional[str] = None,
    ) -> ResolvedChatTurn:
        generation = self.db.ensure_chat_session_generation(session_id, expected_generation=expected_generation)
        snapshot = self.db.read_chat_session_snapshot(session_id)
        if snapshot["session_generation"] != generation:
            raise ChatSessionStateConflict()
        return self._resolve_session_turn(config, snapshot, message, requested_skill_ids, context=context)

    def _resolve_session_turn(
        self, config: Any, snapshot: Dict[str, Any], message: str,
        requested_skill_ids: Optional[List[str]], *, context: Optional[Dict[str, Any]],
    ) -> ResolvedChatTurn:
        skills = self.resolve_skill_selection(config, snapshot["session_id"], requested_skill_ids, snapshot=snapshot)
        registry, lookup = _stock_lookup()
        active = _active_from_snapshot(snapshot, registry, lookup)
        baseline = dict(active) if active else None
        decision = decide_chat_object(message, _identity(active) if active else None, registry, lookup)
        compare = decision.kind == "compare"
        confirm = False
        clarification = None
        if decision.kind == "clarify":
            clarification = "请明确提供本次讨论的股票或指数代码，或确认是否切换。"
        elif decision.kind == "confirm":
            selected = decision.target.identity
            if decision.target.kind != "code" and (context or {}).get("stock_code"):
                hint = _hint_identity(context, registry, lookup)
                if hint != selected:
                    clarification = "名称与报告对象不一致，请明确提供完整股票或指数代码。"
            if clarification is None:
                active = _stock_record(selected, lookup, registry)
                confirm = True

        if clarification is not None:
            active = baseline
            confirm = False
            from src.report_language import normalize_report_language

            if normalize_report_language((context or {}).get("report_language") or getattr(config, "report_language", "zh")) == "en":
                clarification = "The discussion target is not confirmed. Please provide the complete stock or index code."
        allowed = []
        if active is not None:
            allowed.append(_identity(active))
        if compare and clarification is None:
            allowed.extend(item for item in decision.participants if item not in allowed)
        scope = StockScope(expected_stock_code=active["stock_code"] if active else "",
                           allowed_stock_codes={item.stock_code for item in allowed},
                           mode="compare" if compare else "switch" if confirm else "maintain",
                           strict=True, identities=tuple(allowed))
        effective_context = dict(context or {})
        effective_context.pop("allowed_stock_codes", None)
        effective_context.pop("skills", None)
        effective_context.pop("strategies", None)
        hint_matches = False
        if active and effective_context.get("stock_code"):
            hint_matches = _hint_identity(effective_context, registry, lookup) == _identity(active)
        if not hint_matches:
            for key in SWITCH_CLEANUP_KEYS:
                effective_context.pop(key, None)
        for key in ["stock_code", "stock_name", "canonical_id", "asset_type"]:
            effective_context.pop(key, None)
        if active:
            effective_context.update({key: active[key] for key in ["stock_code", "stock_name", "canonical_id", "asset_type"]})
        if skills.effective_skill_ids is not None:
            effective_context["skills"] = list(skills.effective_skill_ids)
        preserves = (clarification is None and baseline is not None and active is not None
                     and _identity(active) == _identity(baseline))
        return ResolvedChatTurn(message, snapshot, active, scope, effective_context, skills, confirm, clarification,
                                "preserve" if preserves else "invalidate")

    def prepare_compatibility_turn(
        self, config: Any, snapshot: Dict[str, Any], message: str,
        *, context: Optional[Dict[str, Any]] = None,
    ) -> tuple[StockScopeResolution, str]:
        """Resolve a current Bot turn from its captured snapshot, without stock-write authority.

        Fresh/old version-zero sessions keep their existing single-turn context
        behavior. Positive-version sessions consume the authoritative decision
        core; only a safe maintain/compare may advance the trusted user anchor.
        """
        if snapshot["session_state_version"] == 0:
            return resolve_stock_scope(message, context), "invalidate"
        turn = self._resolve_session_turn(config, snapshot, message, None, context=context)
        if turn.clarification is not None:
            # Bot can still answer, but an unconfirmed target cannot grant tools
            # access to the previous object or carry its cached analysis facts.
            effective = dict(turn.effective_context)
            for key in SWITCH_CLEANUP_KEYS | {"stock_code", "canonical_id", "asset_type"}:
                effective.pop(key, None)
            return StockScopeResolution(effective, StockScope(strict=True)), "invalidate"
        return StockScopeResolution(turn.effective_context, turn.stock_scope), turn.compatibility_disposition

    def commit_user_turn(self, turn: ResolvedChatTurn) -> Dict[str, Any]:
        return self.db.commit_chat_user_turn(
            turn.snapshot, turn.message, selected_skill_ids=turn.skill_selection.selected_skill_ids_update,
            active_stock_context=turn.active_stock_context, confirm_stock=turn.confirm_stock,
        )

    def delete_session(self, session_id: str) -> int:
        return self.db.delete_conversation_session(session_id)
