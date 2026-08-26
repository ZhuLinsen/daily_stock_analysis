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
from src.report_language import normalize_report_language
from src.storage import persist_llm_usage


_BASE_INSTRUCTIONS = (
    "You are the DSA stock-analysis Agent runtime. DSA instructions and DSA tools define your task; "
    "coding-agent defaults do not. Never modify files, request approval, or use unregistered tools. "
    "Only the tools shown for this turn are approved for bounded, non-action data collection. Every displayed "
    "tool runs in a separately cancellable process boundary; a normal DSA data cache may be updated, but never "
    "imply access to data sources that are not listed."
)
_NO_STOCK_SCOPE_INSTRUCTION = (
    "No stock scope was established for this turn. Do not call any DSA tool that requires a "
    "stock_code. If the user asks about a specific stock, ask them in plain language to provide "
    "or select an exact stock code. Non-stock market tools remain available."
)

_PUBLIC_ERROR_MESSAGES = {
    "command_not_found": {
        "zh": "运行 DSA 的设备找不到 Codex，请前往 Agent 设置检查安装和 PATH。",
        "en": "Codex is not available on the device running DSA. Check installation and PATH in Agent settings.",
        "ko": "DSA를 실행하는 장치에서 Codex를 찾을 수 없습니다. 에이전트 설정에서 설치와 PATH를 확인하세요.",
    },
    "login_required": {
        "zh": "Codex 尚未登录，请在运行 DSA 的设备上完成登录后重试。",
        "en": "Codex is not signed in. Sign in on the device running DSA and try again.",
        "ko": "Codex에 로그인되어 있지 않습니다. DSA를 실행하는 장치에서 로그인한 뒤 다시 시도하세요.",
    },
    "capability_unsupported": {
        "zh": "当前 Codex 安装不满足问股所需能力，请前往 Agent 设置查看运行状态。",
        "en": "This Codex installation does not provide the capabilities needed for stock queries. Check Agent settings.",
        "ko": "현재 Codex 설치 환경이 종목 질의에 필요한 기능을 제공하지 않습니다. 에이전트 설정에서 실행 상태를 확인하세요.",
    },
    "unsupported_agent_arch": {
        "zh": "Codex 本地 Agent 当前只支持单 Agent 问股。",
        "en": "The local Codex Agent currently supports single-agent stock queries only.",
        "ko": "로컬 Codex 에이전트는 현재 단일 에이전트 종목 질의만 지원합니다.",
    },
    "approval_required": {
        "zh": "Codex 请求了本次问股不允许的授权，运行已安全停止。",
        "en": "Codex requested an approval that is not allowed for this stock query, so the run stopped safely.",
        "ko": "Codex가 이번 종목 질의에 허용되지 않은 권한을 요청하여 실행을 안전하게 중단했습니다.",
    },
    "timeout": {
        "zh": "Codex Agent 本次问股超时，请稍后重试或检查 Agent 整体超时设置。",
        "en": "This Codex Agent stock query timed out. Try again later or check the overall Agent timeout.",
        "ko": "이번 Codex 에이전트 종목 질의 시간이 초과되었습니다. 잠시 후 다시 시도하거나 전체 에이전트 제한 시간을 확인하세요.",
    },
    "cancelled": {
        "zh": "本次 Codex Agent 问股已取消。",
        "en": "This Codex Agent stock query was cancelled.",
        "ko": "이번 Codex 에이전트 종목 질의를 취소했습니다.",
    },
    "output_too_large": {
        "zh": "Codex Agent 返回的数据超过安全限制，本次问股已停止。",
        "en": "Codex Agent returned data beyond the safety limit, so this stock query stopped.",
        "ko": "Codex 에이전트가 안전 제한을 넘는 데이터를 반환하여 이번 종목 질의를 중단했습니다.",
    },
    "resource_limit_exceeded": {
        "zh": "Codex Agent 本次问股超过允许的工作量，后台任务已结束。",
        "en": "This Codex Agent stock query exceeded the allowed work limit, so the background task ended.",
        "ko": "이번 Codex 에이전트 종목 질의가 허용된 작업량을 초과하여 백그라운드 작업을 종료했습니다.",
    },
    "tool_roundtrip_failed": {
        "zh": "Codex Agent 本次未能完成只读数据调用，请根据提示重试或切换到默认模型。",
        "en": "Codex Agent could not complete the read-only data call. Try again or switch to the default model.",
        "ko": "Codex 에이전트가 읽기 전용 데이터 호출을 완료하지 못했습니다. 다시 시도하거나 기본 모델로 전환하세요.",
    },
    "resource_cleanup_failed": {
        "zh": "Codex Agent 未能安全结束本次后台任务，请重启 DSA 服务后再试。",
        "en": "Codex Agent could not safely finish this background task. Restart DSA and try again.",
        "ko": "Codex 에이전트가 이번 백그라운드 작업을 안전하게 종료하지 못했습니다. DSA 서비스를 재시작한 뒤 다시 시도하세요.",
    },
    "invalid_timeout": {
        "zh": "Codex Agent 必须设置明确的整体时限，请在 Agent 设置中填写大于 0 的秒数。",
        "en": "Codex Agent requires a positive overall timeout. Set a value greater than zero in Agent settings.",
        "ko": "Codex 에이전트에는 명확한 전체 제한 시간이 필요합니다. 에이전트 설정에 0보다 큰 초 단위 값을 입력하세요.",
    },
}
_DEFAULT_PUBLIC_ERROR_MESSAGE = {
    "zh": "Codex Agent 暂时无法完成本次问股，请前往 Agent 设置查看运行状态。",
    "en": "Codex Agent cannot complete this stock query right now. Check Agent settings for runtime status.",
    "ko": "Codex 에이전트가 현재 이 종목 질의를 완료할 수 없습니다. 에이전트 설정에서 실행 상태를 확인하세요.",
}

_PROGRESS_MESSAGES = {
    "connecting": {"zh": "正在连接 Codex…", "en": "Connecting to Codex…", "ko": "Codex에 연결하는 중…"},
    "preparing": {"zh": "正在准备分析…", "en": "Preparing analysis…", "ko": "분석을 준비하는 중…"},
    "organizing": {"zh": "正在整理分析结果…", "en": "Organizing analysis results…", "ko": "분석 결과를 정리하는 중…"},
}

# Keep Codex's dynamic surface intentionally narrow.  These are the evidence
# tools needed to answer a current stock question; portfolio/action tools and
# market-wide tools remain outside the local Codex Agent boundary.
_CODEX_EVIDENCE_TOOL_NAMES = (
    "get_analysis_context",
    "get_realtime_quote",
    "get_daily_history",
    "analyze_trend",
    "get_stock_info",
    "search_stock_news",
    "get_tracker_research_bundle",
    "get_stock_backtest_summary",
    "get_skill_backtest_summary",
    "get_strategy_backtest_summary",
)


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

    def _language(self) -> str:
        return normalize_report_language(getattr(self.config, "report_language", None))

    def _progress_message(self, key: str) -> str:
        return _PROGRESS_MESSAGES[key][self._language()]

    def _tool_names(self) -> list[str]:
        """Return only read-only tools approved for the process boundary.

        The fallback preserves the small fake surfaces used by protocol tests,
        while production uses the explicit evidence allowlist above.
        """
        descriptors = self.tool_surface.list_tools(
            "public",
            cancellation_safe_only=True,
            process_isolated=True,
        )
        names = [item["name"] for item in descriptors]
        allowed = set(names)
        selected = [name for name in _CODEX_EVIDENCE_TOOL_NAMES if name in allowed]
        return selected or names

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
            request.progress_callback(
                stream_event("thinking", step=1, message=self._progress_message("connecting"))
            )

        tool_context = ToolAccessContext(
            stock_scope=request.stock_scope,
            backend=self.backend_id,
            session_id=request.session_id,
            timeout_seconds=timeout,
            deadline=deadline,
            cancel_event=request.cancel_event,
            execution_boundary="process_isolated",
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
                tool_names = self._tool_names()
                if not tool_names:
                    raise CodexAppServerError(
                        "capability_unsupported",
                        "No bounded read-only DSA tools are available to Codex",
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
                    request.progress_callback(
                        stream_event("thinking", step=1, message=self._progress_message("preparing"))
                    )
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
            request.progress_callback(
                stream_event("generating", step=1, message=self._progress_message("organizing"))
            )
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
            error_message=_PUBLIC_ERROR_MESSAGES.get(code, _DEFAULT_PUBLIC_ERROR_MESSAGE)[
                self._language()
            ],
            total_steps=total_steps,
        )
