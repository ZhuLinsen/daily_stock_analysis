# -*- coding: utf-8 -*-
"""Backend-neutral Agent Chat orchestration and conversation persistence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from src.agent.agent_backend import AgentBackend, AgentRunRequest
from src.agent.conversation import conversation_manager
from src.agent.executor import AgentResult, PreparedAgentChat, prepare_agent_chat
from src.agent.provider_trace import persist_provider_trace_turns


@dataclass(frozen=True)
class PreparedAgentChatTurn:
    """A persisted user turn that is ready for backend execution."""

    message: str
    session_id: str
    prepared: PreparedAgentChat
    baseline_len: int
    run_id: str
    user_message_id: int


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
    ) -> AgentResult:
        turn = self.prepare_turn(
            message=message,
            session_id=session_id,
            context=context,
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
    ) -> PreparedAgentChatTurn:
        """Prepare context and persist the user message without starting a backend."""
        conversation_manager.get_or_create(session_id)
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
        )
        baseline_len = len(prepared.history_messages) + 2
        run_id = str(uuid.uuid4())
        user_message_id = conversation_manager.add_message(session_id, "user", message)
        return PreparedAgentChatTurn(
            message=message,
            session_id=session_id,
            prepared=prepared,
            baseline_len=baseline_len,
            run_id=run_id,
            user_message_id=user_message_id,
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
            assistant_message_id = conversation_manager.add_message(turn.session_id, "assistant", result.content)
            if not self.backend.runtime_owns_loop:
                persist_provider_trace_turns(
                    session_id=turn.session_id,
                    run_id=turn.run_id,
                    messages=result.messages,
                    baseline_len=turn.baseline_len,
                    user_message_id=turn.user_message_id,
                    assistant_message_id=assistant_message_id,
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
            conversation_manager.add_message(
                turn.session_id,
                "assistant",
                failure_note,
            )
        return result
