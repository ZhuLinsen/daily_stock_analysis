# -*- coding: utf-8 -*-
"""Experimental runtime-owned Codex App Server Agent backend."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from src.agent.agent_backend import (
    AGENT_BACKEND_ERROR_CODES,
    AgentBackend,
    AgentRunRequest,
    AgentRunResult,
)
from src.agent.codex_app_server_transport import (
    PERMISSION_PROFILE,
    CodexAppServerError,
    CodexAppServerTransport,
    ToolCallRecord,
    build_hardened_command,
)
from src.agent.codex_tool_process import MAX_TOOL_RESULT_BYTES
from src.agent.stream_events import stream_event
from src.agent.tool_surface import ToolSurface
from src.agent.tools.execution import ToolAccessContext, redact_diagnostic_value
from src.llm.usage import should_persist_usage_telemetry
from src.storage import persist_llm_usage


_BASE_INSTRUCTIONS = (
    "You are the DSA stock-analysis Agent runtime. DSA instructions and DSA tools define your task; "
    "coding-agent defaults do not. Never modify files, request approval, or use unregistered tools. "
    "Only the tools shown for this turn are safe to cancel; never imply access to live quotes, news, "
    "portfolio data, or recalculation tools when they are not listed."
)
_NO_STOCK_SCOPE_INSTRUCTION = (
    "No stock scope was established for this turn. Do not call any DSA tool that requires a "
    "stock_code. If the user asks about a specific stock, ask them in plain language to provide "
    "or select an exact stock code. Non-stock market tools remain available."
)

_PUBLIC_ERROR_MESSAGES = {
    "command_not_found": "运行 DSA 的设备找不到 Codex，请前往 Agent 设置检查安装和 PATH。",
    "login_required": "Codex 尚未登录，请在运行 DSA 的设备上完成登录后重试。",
    "capability_unsupported": "当前 Codex 安装不满足问股所需能力，请前往 Agent 设置查看运行状态。",
    "unsupported_agent_arch": "Codex 本地 Agent 当前只支持单 Agent 问股。",
    "approval_required": "Codex 请求了本次问股不允许的授权，运行已安全停止。",
    "timeout": "Codex Agent 本次问股超时，请稍后重试或检查 Agent 整体超时设置。",
    "cancelled": "本次 Codex Agent 问股已取消。",
    "output_too_large": "Codex Agent 返回的数据超过安全限制，本次问股已停止。",
    "resource_limit_exceeded": "Codex Agent 本次问股超过允许的工作量，后台任务已结束。",
    "tool_roundtrip_failed": "Codex Agent 本次未能完成只读数据调用，请根据提示重试或切换到默认模型。",
    "resource_cleanup_failed": "Codex Agent 未能安全结束本次后台任务，请重启 DSA 服务后再试。",
    "invalid_timeout": "Codex Agent 必须设置明确的整体时限，请在 Agent 设置中填写大于 0 的秒数。",
}
_DEFAULT_PUBLIC_ERROR_MESSAGE = "Codex Agent 暂时无法完成本次问股，请前往 Agent 设置查看运行状态。"


class CodexAgentBackend(AgentBackend):
    """Execute one DSA Chat turn in a new ephemeral Codex App Server."""

    backend_id = "codex_app_server"
    runtime_owns_loop = True

    def __init__(
        self,
        tool_surface: ToolSurface,
        config: Any,
        transport_factory: Callable[..., CodexAppServerTransport] = CodexAppServerTransport,
    ) -> None:
        self.tool_surface = tool_surface
        self.config = config
        self.transport_factory = transport_factory

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        timeout = request.max_wall_clock_seconds
        if timeout is None:
            timeout = float(getattr(self.config, "agent_orchestrator_timeout_s", 0))
        if timeout <= 0:
            return self._error_result(
                request,
                "invalid_timeout",
                "Codex Agent requires a positive overall timeout",
                total_steps=0,
            )
        deadline = time.monotonic() + timeout

        def remaining_timeout() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexAppServerError("timeout", "Codex Agent exceeded the overall timeout")
            return remaining

        if request.cancel_event is not None and request.cancel_event.is_set():
            return self._error_result(request, "cancelled", "Agent request was cancelled", total_steps=0)

        if request.progress_callback:
            request.progress_callback(stream_event("thinking", step=1, message="正在连接 Codex…"))

        tool_context = ToolAccessContext(
            stock_scope=request.stock_scope,
            backend=self.backend_id,
            session_id=request.session_id,
            timeout_seconds=timeout,
            deadline=deadline,
            cancel_event=request.cancel_event,
            max_result_bytes=MAX_TOOL_RESULT_BYTES,
            redact_result=True,
        )

        def on_tool_event(event_type: str, record: ToolCallRecord) -> None:
            if request.progress_callback is None:
                return
            if event_type == "start":
                request.progress_callback(stream_event("tool_start", step=1, tool=record.tool_name))
            else:
                request.progress_callback(
                    stream_event(
                        "tool_done",
                        step=1,
                        tool=record.tool_name,
                        success=record.success,
                        duration=round(record.finished_at - record.started_at, 2),
                    )
                )

        try:
            command = build_hardened_command(
                timeout=remaining_timeout(),
                deadline=deadline,
                cancel_event=request.cancel_event,
            )
            with self.transport_factory(
                command,
                tool_surface=self.tool_surface,
                tool_context=tool_context,
                request_timeout=remaining_timeout(),
                tool_event_callback=on_tool_event,
                deadline=deadline,
                cancel_event=request.cancel_event,
                max_tool_calls=request.max_steps,
            ) as client:
                client.request_timeout = remaining_timeout()
                tool_names = [
                    item["name"]
                    for item in self.tool_surface.list_tools(
                        "public",
                        cancellation_safe_only=True,
                    )
                ]
                if not tool_names:
                    raise CodexAppServerError(
                        "capability_unsupported",
                        "No cancellation-safe DSA tools are available to Codex",
                    )
                developer_instructions = request.system_prompt
                if request.stock_scope is None:
                    developer_instructions = (
                        f"{developer_instructions}\n\n{_NO_STOCK_SCOPE_INSTRUCTION}"
                    )
                thread_id = client.start_thread(
                    tool_names=tool_names,
                    base_instructions=_BASE_INSTRUCTIONS,
                    developer_instructions=developer_instructions,
                )
                client.request_timeout = remaining_timeout()
                isolation = client.inspect_external_tool_isolation(thread_id)
                if not isolation.get("passed"):
                    raise CodexAppServerError(
                        "capability_unsupported",
                        "Codex external tool isolation check failed",
                    )
                client.request_timeout = remaining_timeout()
                client.inject_history(thread_id, request.history_messages)
                if request.progress_callback:
                    request.progress_callback(stream_event("thinking", step=1, message="正在准备分析…"))
                turn_timeout = remaining_timeout()
                tool_context.timeout_seconds = turn_timeout
                turn = client.run_turn(
                    thread_id,
                    request.user_message,
                    timeout=turn_timeout,
                    cancel_event=request.cancel_event,
                )
                tool_calls_log = [
                    {
                        "step": 1,
                        "tool": record.tool_name,
                        "arguments_summary": redact_diagnostic_value(record.arguments),
                        "success": record.success,
                        "duration": round(record.finished_at - record.started_at, 2),
                    }
                    for record in client.tool_calls
                    if record.turn_id == turn.turn_id
                ]
                diagnostics = {
                    "permission_profile": PERMISSION_PROFILE,
                    "active_permission_profile": client.thread_metadata(thread_id).get(
                        "active_permission_profile"
                    ),
                    "external_tool_isolation": isolation,
                    "stderr_preview": client.stderr_preview,
                }
        except CodexAppServerError as exc:
            code = self._normalize_error_code(exc.code)
            return self._error_result(
                request,
                code,
                str(exc),
                total_steps=1 if exc.turn_started else 0,
            )
        except OSError:
            return self._error_result(
                request,
                "unknown_backend_error",
                "Codex App Server could not be started",
                total_steps=0,
            )

        model = turn.model or "Codex"
        usage = turn.usage
        if usage and should_persist_usage_telemetry(usage):
            persist_llm_usage(usage, model, call_type="agent")
        if request.progress_callback:
            request.progress_callback(stream_event("generating", step=1, message="正在整理分析结果…"))
        messages = [
            *request.history_messages,
            {"role": "user", "content": request.user_message},
            {"role": "assistant", "content": turn.final_text},
        ]
        return AgentRunResult(
            success=bool(turn.final_text),
            final_answer=turn.final_text,
            tool_calls_log=tool_calls_log,
            model=model,
            backend=self.backend_id,
            usage=usage,
            diagnostics=diagnostics,
            error_code=None if turn.final_text else "unknown_backend_error",
            error_message=None if turn.final_text else "Codex returned an empty final answer",
            messages=messages,
            total_steps=1,
        )

    @staticmethod
    def _normalize_error_code(code: str) -> str:
        if code in AGENT_BACKEND_ERROR_CODES:
            return code
        if code in {"permission_profile_mismatch", "unsupported_mcp_name", "tool_not_found"}:
            return "capability_unsupported"
        return "unknown_backend_error"

    def _error_result(
        self,
        request: AgentRunRequest,
        code: str,
        message: str,
        *,
        total_steps: int,
    ) -> AgentRunResult:
        internal_message = redact_diagnostic_value(message, limit=500)
        return AgentRunResult(
            success=False,
            backend=self.backend_id,
            diagnostics={"internal_error": internal_message},
            error_code=code,
            error_message=_PUBLIC_ERROR_MESSAGES.get(code, _DEFAULT_PUBLIC_ERROR_MESSAGE),
            total_steps=total_steps,
        )
