# -*- coding: utf-8 -*-
"""Backend-neutral Agent Chat orchestration and conversation persistence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from src.agent.agent_backend import AgentBackend, AgentRunRequest
from src.agent.conversation import conversation_manager
from src.agent.executor import AgentResult, PreparedAgentChat, prepare_agent_chat
from src.agent.provider_trace import persist_provider_trace_turns
from src.agent.stock_scope import StockScopeResolution
from src.storage import DatabaseManager

if TYPE_CHECKING:
    from src.services.agent_chat_session_service import AgentChatSessionService, ResolvedChatTurn


@dataclass(frozen=True)
class PreparedAgentChatTurn:
    """A persisted user turn that is ready for backend execution."""

    message: str
    session_id: str
    prepared: PreparedAgentChat
    baseline_len: int
    run_id: str
    user_message_id: int
    accepted_snapshot: Optional[Dict[str, Any]] = None
    db_manager: Optional[DatabaseManager] = None


class AgentChatExecutor:
    """Prepare one DSA Chat request and delegate only execution to a backend."""

    def __init__(
        self,
        *,
        backend: AgentBackend,
        config: Any,
        context_llm_adapter: Any,
        skill_instructions: str = "",
        default_skill_policy: str = "",
        use_legacy_default_prompt: bool = False,
        max_steps: int = 10,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.backend = backend
        self.config = config
        self.context_llm_adapter = context_llm_adapter
        self.skill_instructions = skill_instructions
        self.default_skill_policy = default_skill_policy
        self.use_legacy_default_prompt = use_legacy_default_prompt
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds

    def chat(
        self,
        message: str,
        session_id: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        context: Optional[Dict[str, Any]] = None,
        cancel_event=None,
        selected_skill_ids: Optional[List[str]] = None,
        resolved_turn: Optional[ResolvedChatTurn] = None,
        session_service: Optional[AgentChatSessionService] = None,
    ) -> AgentResult:
        turn = self.prepare_turn(
            message=message,
            session_id=session_id,
            context=context,
            selected_skill_ids=selected_skill_ids,
            resolved_turn=resolved_turn,
            session_service=session_service,
        )
        return self.execute_turn(
            turn,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    def prepare_turn(
        self,
        *,
        message: str,
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
        selected_skill_ids: Optional[List[str]] = None,
        resolved_turn: Optional[ResolvedChatTurn] = None,
        session_service: Optional[AgentChatSessionService] = None,
    ) -> PreparedAgentChatTurn:
        """Prepare context and persist the user message without starting a backend."""
        resolved_kwargs = {}
        if resolved_turn is not None:
            if (session_service is None or resolved_turn.snapshot["session_id"] != session_id
                    or resolved_turn.message != message or resolved_turn.clarification is not None):
                raise ValueError("Resolved Chat preparation requires its session owner and a non-clarification turn")
            resolved_kwargs = {
                "scope_resolution": StockScopeResolution(resolved_turn.effective_context, resolved_turn.stock_scope),
                "db_manager": session_service.db,
                "source_snapshot": resolved_turn.snapshot,
            }
        else:
            db, snapshot = conversation_manager.prepare_turn(session_id)
            resolved_kwargs = {"db_manager": db, "source_snapshot": snapshot}
        prepared = prepare_agent_chat(
            message=message,
            session_id=session_id,
            context=context,
            config=self.config,
            context_llm_adapter=self.context_llm_adapter,
            skill_instructions=self.skill_instructions,
            default_skill_policy=self.default_skill_policy,
            use_legacy_default_prompt=self.use_legacy_default_prompt,
            use_codex_prompt=self.backend.backend_id == "codex_app_server",
            include_provider_trace=not self.backend.runtime_owns_loop,
            strict_initial_stock_scope=self.backend.runtime_owns_loop,
            **resolved_kwargs,
        )
        baseline_len = len(prepared.history_messages) + 2
        run_id = str(uuid.uuid4())
        accepted = None
        if resolved_turn is not None:
            accepted = session_service.commit_user_turn(resolved_turn)
            user_message_id = accepted["user_message_id"]
        else:
            accepted = conversation_manager.commit_user_turn(db, snapshot, message, selected_skill_ids)
            user_message_id = accepted["user_message_id"]
        return PreparedAgentChatTurn(
            message=message,
            session_id=session_id,
            prepared=prepared,
            baseline_len=baseline_len,
            run_id=run_id,
            user_message_id=user_message_id,
            accepted_snapshot=accepted,
            db_manager=session_service.db if resolved_turn is not None else db,
        )

    def execute_turn(
        self,
        turn: PreparedAgentChatTurn,
        *,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        cancel_event=None,
    ) -> AgentResult:
        """Execute a previously accepted turn and persist its terminal result."""
        backend_result = self.backend.run(
            AgentRunRequest(
                system_prompt=turn.prepared.system_prompt,
                history_messages=turn.prepared.history_messages,
                user_message=turn.message,
                session_id=turn.session_id,
                stock_scope=turn.prepared.stock_scope,
                max_steps=self.max_steps,
                max_wall_clock_seconds=self.timeout_seconds,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
            )
        )
        total_tokens = 0
        if isinstance(backend_result.usage, dict):
            total_tokens = int(backend_result.usage.get("total_tokens") or 0)
        result = AgentResult(
            success=backend_result.success,
            content=backend_result.final_answer,
            dashboard=None,
            tool_calls_log=backend_result.tool_calls_log,
            total_steps=backend_result.total_steps,
            total_tokens=total_tokens,
            provider=str(backend_result.diagnostics.get("provider") or backend_result.backend),
            model=backend_result.model,
            error=backend_result.error_message,
            messages=backend_result.messages,
            backend=backend_result.backend,
            error_code=backend_result.error_code,
            usage=backend_result.usage,
        )

        if result.success:
            if turn.accepted_snapshot is not None:
                assistant_message_id = conversation_manager.add_message(
                    turn.session_id, "assistant", result.content, accepted_turn=turn.accepted_snapshot,
                    db_manager=turn.db_manager,
                )
            else:
                assistant_message_id = conversation_manager.add_message(turn.session_id, "assistant", result.content)
            if not self.backend.runtime_owns_loop and assistant_message_id is not None:
                persist_provider_trace_turns(
                    session_id=turn.session_id,
                    run_id=turn.run_id,
                    messages=result.messages,
                    baseline_len=turn.baseline_len,
                    user_message_id=turn.user_message_id,
                    assistant_message_id=assistant_message_id,
                    **({"accepted_turn": turn.accepted_snapshot, "db_factory": lambda: turn.db_manager}
                       if turn.accepted_snapshot is not None else {}),
                )
        else:
            if not self.backend.runtime_owns_loop:
                failure_note = f"[分析失败] {result.error or '未知错误'}"
            elif result.error_code == "cancelled":
                failure_note = "[已停止] 本次分析已由用户停止。"
            elif result.error_code == "timeout":
                failure_note = "[已超时] 本次分析已在时间限制内结束。"
            else:
                failure_note = f"[分析失败] {result.error or '未知错误'}"
            if turn.accepted_snapshot is not None:
                conversation_manager.add_message(
                    turn.session_id, "assistant", failure_note, accepted_turn=turn.accepted_snapshot,
                    db_manager=turn.db_manager,
                )
            else:
                conversation_manager.add_message(turn.session_id, "assistant", failure_note)
        return result
