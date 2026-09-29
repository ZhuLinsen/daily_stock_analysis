# -*- coding: utf-8 -*-
"""AgentBackend contract and the zero-regression LiteLLM wrapper."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.agent.llm_adapter import LLMToolAdapter
from src.agent.runner import run_agent_loop
from src.agent.stock_scope import StockScope
from src.agent.tools.registry import ToolRegistry


AGENT_BACKEND_ERROR_CODES = frozenset(
    {
        "command_not_found",
        "login_required",
        "capability_unsupported",
        "unsupported_agent_arch",
        "approval_required",
        "timeout",
        "cancelled",
        "protocol_error",
        "output_too_large",
        "resource_limit_exceeded",
        "tool_roundtrip_failed",
        "resource_cleanup_failed",
        "invalid_timeout",
        "unknown_backend_error",
    }
)
AGENT_BACKEND_IDS = frozenset({"auto", "litellm", "codex_app_server"})


class AgentBackendConfigError(ValueError):
    """Structured Agent backend selection error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_agent_backend_id(config: Any) -> str:
    """Resolve Chat backend; ``auto`` deliberately remains LiteLLM."""
    requested = str(getattr(config, "agent_backend", "auto") or "auto").strip().lower()
    if requested not in AGENT_BACKEND_IDS:
        raise AgentBackendConfigError(
            "capability_unsupported",
            f"Unsupported AGENT_BACKEND: {requested}",
        )
    return "litellm" if requested == "auto" else requested


@dataclass(frozen=True)
class AgentRunRequest:
    system_prompt: str
    history_messages: List[Dict[str, Any]]
    user_message: str
    session_id: str
    stock_scope: Optional[StockScope]
    max_steps: int
    max_wall_clock_seconds: Optional[float]
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    cancel_event: Optional[threading.Event] = None


@dataclass
class AgentRunResult:
    success: bool = False
    final_answer: str = ""
    tool_calls_log: List[Dict[str, Any]] = field(default_factory=list)
    model: str = ""
    backend: str = ""
    usage: Optional[Dict[str, Any]] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    total_steps: int = 0


class AgentBackend(ABC):
    """One execution backend for Agent Chat."""

    backend_id: str
    runtime_owns_loop: bool

    @abstractmethod
    def run(self, request: AgentRunRequest) -> AgentRunResult:
        """Run one Agent turn and return the normalized result."""


class LiteLLMAgentBackend(AgentBackend):
    """Thin wrapper around the existing DSA-owned ``run_agent_loop``."""

    backend_id = "litellm"
    runtime_owns_loop = False

    def __init__(self, tool_registry: ToolRegistry, llm_adapter: LLMToolAdapter) -> None:
        self.tool_registry = tool_registry
        self.llm_adapter = llm_adapter

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": request.system_prompt},
            *request.history_messages,
            {"role": "user", "content": request.user_message},
        ]
        loop_result = run_agent_loop(
            messages=messages,
            tool_registry=self.tool_registry,
            llm_adapter=self.llm_adapter,
            max_steps=request.max_steps,
            progress_callback=request.progress_callback,
            max_wall_clock_seconds=request.max_wall_clock_seconds,
            stock_scope=request.stock_scope,
        )
        usage = {"total_tokens": loop_result.total_tokens} if loop_result.total_tokens > 0 else None
        error_code = None
        if not loop_result.success and "timed out" in str(loop_result.error or "").lower():
            error_code = "timeout"
        elif not loop_result.success:
            error_code = "unknown_backend_error"
        return AgentRunResult(
            success=loop_result.success,
            final_answer=loop_result.content,
            tool_calls_log=loop_result.tool_calls_log,
            model=loop_result.model,
            backend=self.backend_id,
            usage=usage,
            diagnostics={"provider": loop_result.provider},
            error_code=error_code,
            error_message=loop_result.error,
            messages=loop_result.messages,
            total_steps=loop_result.total_steps,
        )
