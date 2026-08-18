# -*- coding: utf-8 -*-
"""
Agent API endpoints.
"""

import asyncio
import json
import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from api.deps import get_agent_chat_session_service
from api.v1.schemas.system_config import AgentBackendStatusResponse
from src.config import get_config
from src.services.agent_chat_session_service import AgentChatSessionService
from src.services.agent_model_service import list_agent_model_deployments

# Tool name -> Chinese display name mapping
TOOL_DISPLAY_NAMES: Dict[str, str] = {
    "get_realtime_quote":         "获取实时行情",
    "get_daily_history":          "获取历史K线",
    "get_chip_distribution":      "分析筹码分布",
    "get_analysis_context":       "获取分析上下文",
    "get_stock_info":             "获取股票基本面",
    "search_stock_news":          "搜索股票新闻",
    "search_comprehensive_intel": "搜索综合情报",
    "analyze_trend":              "分析技术趋势",
    "calculate_ma":               "计算均线系统",
    "get_volume_analysis":        "分析量能变化",
    "analyze_pattern":            "识别K线形态",
    "get_market_indices":         "获取市场指数",
    "get_sector_rankings":        "分析行业板块",
    "get_skill_backtest_summary": "获取技能回测概览",
    "get_strategy_backtest_summary": "获取策略回测概览",
    "get_stock_backtest_summary": "获取个股回测数据",
}

logger = logging.getLogger(__name__)

router = APIRouter()

_ACTIVE_CODEX_STREAMS: Dict[str, threading.Event] = {}
_ACTIVE_CODEX_STREAMS_LOCK = threading.Lock()

class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message: str
    session_id: Optional[str] = None
    request_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    skills: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("skills", "strategies"),
    )
    context: Optional[Dict[str, Any]] = None  # Previous analysis context for data reuse

    @property
    def effective_skills(self) -> Optional[List[str]]:
        """Return skill ids from the unified request shape."""
        return self.skills


def _build_agent_chat_context(request: ChatRequest, config, skills: Optional[List[str]]) -> Dict[str, Any]:
    """Build the shared context contract for regular and streaming Agent Chat."""
    context = dict(request.context or {})
    context.pop("skills", None)
    context.pop("strategies", None)
    if skills is not None:
        context["skills"] = skills
    report_language = context.get("report_language")
    if report_language is None or (isinstance(report_language, str) and not report_language.strip()):
        context["report_language"] = config.report_language
    return context


class ChatResponse(BaseModel):
    success: bool
    content: str
    session_id: str
    error: Optional[str] = None


class SkillInfo(BaseModel):
    id: str
    name: str
    description: str

class SkillsResponse(BaseModel):
    skills: List[SkillInfo]
    default_skill_id: str = ""


class StrategiesResponse(BaseModel):
    strategies: List[SkillInfo]
    default_strategy_id: str = ""


class AgentModelDeployment(BaseModel):
    deployment_id: str
    model: str
    provider: str
    source: str
    api_base: Optional[str] = None
    deployment_name: Optional[str] = None
    is_primary: bool = False
    is_fallback: bool = False


class AgentModelsResponse(BaseModel):
    models: List[AgentModelDeployment]


@router.get("/models", response_model=AgentModelsResponse)
async def get_agent_models():
    """Get configured Agent model deployments for frontend selection."""
    config = get_config()
    from src.agent.agent_backend import AgentBackendConfigError, resolve_agent_backend_id

    try:
        selected_backend = resolve_agent_backend_id(config)
    except AgentBackendConfigError:
        return AgentModelsResponse(models=[])
    if selected_backend == "codex_app_server":
        return AgentModelsResponse(models=[])
    return AgentModelsResponse(
        models=[AgentModelDeployment(**item) for item in list_agent_model_deployments(config)]
    )


@router.get("/status", response_model=AgentBackendStatusResponse)
async def get_agent_status():
    """Return the current effective Chat backend status for the Chat page."""
    payload = await asyncio.to_thread(_get_agent_chat_status, get_config())
    return _agent_status_response(payload)


def _agent_status_response(payload: Dict[str, Any]) -> AgentBackendStatusResponse:
    return AgentBackendStatusResponse(
        backend=payload["backend"],
        available=payload["available"],
        experimental=payload["experimental"],
        version=payload.get("version"),
        error_code=payload.get("error_code"),
        message=payload.get("message"),
    )


def _build_skills_response(config) -> SkillsResponse:
    from src.agent.factory import get_skill_manager
    from src.agent.skills.defaults import get_primary_default_skill_id

    skill_manager = get_skill_manager(config)
    available_skills = sorted(
        [
            skill
            for skill in skill_manager.list_skills()
            if getattr(skill, "user_invocable", True)
        ],
        key=lambda skill: (
            int(getattr(skill, "default_priority", 100)),
            skill.display_name,
            skill.name,
        ),
    )
    skills = [
        SkillInfo(id=skill.name, name=skill.display_name, description=skill.description)
        for skill in available_skills
    ]
    return SkillsResponse(
        skills=skills,
        default_skill_id=get_primary_default_skill_id(available_skills),
    )


@router.get("/skills", response_model=SkillsResponse)
async def get_skills():
    """
    Get available agent strategy skills.
    """
    return _build_skills_response(get_config())


@router.get("/strategies", response_model=StrategiesResponse, include_in_schema=False)
async def get_strategies():
    """Compatibility alias for legacy clients."""
    payload = _build_skills_response(get_config())
    return StrategiesResponse(
        strategies=payload.skills,
        default_strategy_id=payload.default_skill_id,
    )

@router.post("/chat", response_model=ChatResponse)
async def agent_chat(
    request: ChatRequest,
    session_service: AgentChatSessionService = Depends(get_agent_chat_session_service),
):
    """
    Chat with the AI Agent without progress events.

    Codex Agent callers must use ``/chat/stream``, which provides progress
    events and request cancellation. The default LiteLLM Agent keeps this
    endpoint's existing behavior.
    """
    config = get_config()
    backend_id = _select_agent_chat_backend(config)
    if backend_id == "codex_app_server":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "capability_unsupported",
                "message": "Codex Agent requires the Chat interface with progress and stop support",
            },
        )
    
    session_id = request.session_id or str(uuid.uuid4())
    
    try:
        skill_selection = session_service.resolve_skill_selection(
            config,
            session_id,
            request.effective_skills,
        )
        skills = skill_selection.effective_skill_ids
        selected_skill_ids = skill_selection.selected_skill_ids_update
        executor = _build_executor(config, skills or None)

        ctx = _build_agent_chat_context(request, config, skills)

        # Offload the blocking call to a thread to avoid blocking the event loop.
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: executor.chat(message=request.message, session_id=session_id,
                                  context=ctx, selected_skill_ids=selected_skill_ids),
        )

        return ChatResponse(
            success=result.success,
            content=result.content,
            session_id=session_id,
            error=result.error,
        )
            
    except Exception as e:
        logger.error(f"Agent chat API failed: {e}")
        logger.exception("Agent chat error details:")
        raise HTTPException(status_code=500, detail=str(e))


class SessionItem(BaseModel):
    session_id: str
    title: str
    message_count: int
    created_at: Optional[str] = None
    last_active: Optional[str] = None

class SessionsResponse(BaseModel):
    sessions: List[SessionItem]

class SessionStateResponse(BaseModel):
    selected_skill_ids: Optional[List[str]]

class SessionMessagesResponse(BaseModel):
    session_id: str
    messages: List[Dict[str, Any]]
    session_state: SessionStateResponse


@router.get("/chat/sessions", response_model=SessionsResponse)
async def list_chat_sessions(
    limit: int = 50,
    user_id: Optional[str] = None,
    session_service: AgentChatSessionService = Depends(get_agent_chat_session_service),
):
    """获取聊天会话列表

    Args:
        limit: Maximum number of sessions to return.
        user_id: Optional platform-prefixed user identifier for session
            isolation.  When provided, only sessions whose session_id
            starts with this prefix are returned.  The value must
            include the platform prefix, e.g. ``telegram_12345``,
            ``feishu_ou_abc``.
    """
    sessions = session_service.list_sessions(limit, user_id)
    return SessionsResponse(sessions=sessions)


@router.get("/chat/sessions/{session_id}", response_model=SessionMessagesResponse)
async def get_chat_session_messages(
    session_id: str,
    limit: int = 100,
    session_service: AgentChatSessionService = Depends(get_agent_chat_session_service),
):
    """获取单个会话的完整消息"""
    detail = session_service.get_session_detail(
        session_id,
        limit,
    )
    return SessionMessagesResponse(
        session_id=session_id,
        messages=detail.messages,
        session_state=SessionStateResponse(
            selected_skill_ids=detail.selected_skill_ids,
        ),
    )


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    session_service: AgentChatSessionService = Depends(get_agent_chat_session_service),
):
    """删除指定会话"""
    count = session_service.delete_session(session_id)
    return {"deleted": count}


class SendChatRequest(BaseModel):
    """Request body for sending chat content to notification channels."""

    content: str = Field(..., min_length=1, max_length=50000)
    title: Optional[str] = None


@router.post("/chat/send")
async def send_chat_to_notification(request: SendChatRequest):
    """
    Send chat session content to configured notification channels.
    Uses run_in_executor to avoid blocking the event loop.
    """
    from src.notification import NotificationService

    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(
        None,
        lambda: NotificationService().send(request.content),
    )
    if not success:
        return {
            "success": False,
            "error": "no_channels",
            "message": "未配置通知渠道，请先在设置中配置",
        }
    return {"success": True}


def _build_executor(config, skills: Optional[List[str]] = None):
    """Build and return the backend-neutral Chat executor (sync helper)."""
    from src.agent.factory import build_agent_chat_executor

    return build_agent_chat_executor(config, skills=skills)


def _get_agent_chat_status(config) -> Dict[str, Any]:
    from src.services.agent_backend_status_service import AgentBackendStatusService

    return AgentBackendStatusService(config=config).get_status()


def _select_agent_chat_backend(config) -> str:
    """Select the runtime backend without repeating the compatibility probe."""
    from src.services.agent_backend_status_service import evaluate_agent_backend_config

    evaluation = evaluate_agent_backend_config(config)
    if not evaluation["available"]:
        raise HTTPException(
            status_code=400,
            detail={
                "error": evaluation["error_code"],
                "message": evaluation["message"],
            },
        )
    return evaluation["backend"]


async def _run_research_in_background(
    agent,
    question: str,
    context: Optional[Dict[str, Any]],
    *,
    timeout: int,
):
    """Run deep research off the event loop with an internal overall timeout."""
    return await asyncio.to_thread(
        agent.research,
        question,
        context,
        timeout_seconds=timeout,
    )


# ============================================================
# Deep research endpoint
# ============================================================

class ResearchRequest(BaseModel):
    question: str
    stock_code: Optional[str] = None

class ResearchResponse(BaseModel):
    success: bool
    content: str
    sources: List[str] = Field(default_factory=list)
    token_usage: int = 0
    error: Optional[str] = None


@router.post("/research", response_model=ResearchResponse)
async def agent_research(request: ResearchRequest):
    """Run a deep-research query via the ResearchAgent.

    Similar to the ``/research`` bot command but exposed as a REST endpoint.
    """
    config = get_config()
    if not config.is_agent_available():
        raise HTTPException(status_code=400, detail="Agent mode is not enabled")

    question = request.question
    context: Optional[Dict[str, Any]] = None
    if request.stock_code:
        question = f"[Stock: {request.stock_code}] {question}"
        context = {"stock_code": request.stock_code}

    try:
        from src.agent.research import ResearchAgent
        from src.agent.factory import get_tool_registry
        from src.agent.llm_adapter import LLMToolAdapter

        registry = get_tool_registry()
        llm_adapter = LLMToolAdapter(config)
        budget = getattr(config, "agent_deep_research_budget", 30000)

        agent = ResearchAgent(
            tool_registry=registry,
            llm_adapter=llm_adapter,
            token_budget=budget,
        )

        research_timeout = getattr(config, "agent_deep_research_timeout", 180)

        result = await _run_research_in_background(
            agent,
            question,
            context,
            timeout=research_timeout,
        )
        if getattr(result, "timed_out", False):
            logger.warning("Agent research API timed out after %ss", research_timeout)
            return ResearchResponse(
                success=False,
                content="",
                sources=[],
                token_usage=0,
                error=f"Deep research timed out after {research_timeout}s",
            )

        return ResearchResponse(
            success=result.success,
            content=result.report,
            sources=[f"Sub-question {i+1}: {q}" for i, q in enumerate(result.sub_questions)],
            token_usage=result.total_tokens,
            error=result.error if not result.success else None,
        )
    except Exception as e:
        logger.error("Agent research API failed: %s", e)
        logger.exception("Agent research error details:")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def agent_chat_stream(
    request: ChatRequest,
    session_service: AgentChatSessionService = Depends(get_agent_chat_session_service),
):
    """
    Chat with the AI Agent, streaming progress via SSE.
    Each SSE event is a JSON object with a 'type' field:
      - accepted: 请求已被接收（流协议提交边界，始终为第一条事件，
        包括意图确认分支）；在意图识别与 prepare_turn 之前立即发出，
        前端收到后立刻渲染用户消息气泡，无需等待意图解析或 AI 分析
      - intent_resolved: Web 意图层已完成消息分类（在 accepted 之后发出）
      - action_required: 意图层判定需要用户确认后执行（多候选股票
        或低置信度）；客户端应展示确认界面，用户确认后重新发消息。
        该事件后紧跟一个 'done' 事件，其 'content' 字段携带澄清问题文本。
        确认分支的完整事件序列为 accepted → intent_resolved →
        action_required → done（不发 accepted 会被 Web store 判为协议错误）
      - thinking: AI is deciding next action
      - stage_start: an agent or orchestrator stage has begun
      - stage_done: an agent or orchestrator stage finished
      - tool_start: a tool call has begun
      - tool_done: a tool call finished
      - generating: final answer being generated
      - pipeline_timeout: analysis stopped because the stage/pipeline budget expired
      - pipeline_budget_skipped: analysis stopped before an unstarted stage
        because the remaining budget was too low for useful work
      - done: analysis complete, contains 'content' and 'success'
      - error: error occurred, contains 'message'
    """
    config = get_config()
    backend_id = _select_agent_chat_backend(config)

    session_id = request.session_id or str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    cancel_event = threading.Event()
    request_id = request.request_id or str(uuid.uuid4())
    skill_selection = session_service.resolve_skill_selection(
        config,
        session_id,
        request.effective_skills,
    )
    skills = skill_selection.effective_skill_ids
    selected_skill_ids = skill_selection.selected_skill_ids_update
    stream_ctx = _build_agent_chat_context(request, config, skills)

    if backend_id == "codex_app_server":
        with _ACTIVE_CODEX_STREAMS_LOCK:
            if request_id in _ACTIVE_CODEX_STREAMS:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "request_conflict",
                        "message": "This Agent request is already running",
                    },
                )
            _ACTIVE_CODEX_STREAMS[request_id] = cancel_event

    def progress_callback(event: dict):
        if backend_id == "codex_app_server" and cancel_event.is_set():
            return
        # Enrich tool events with display names
        if event.get("type") in ("tool_start", "tool_done"):
            tool = event.get("tool", "")
            event["display_name"] = TOOL_DISPLAY_NAMES.get(tool, tool)
        asyncio.run_coroutine_threadsafe(queue.put(event), loop)

    def run_sync(executor, turn):
        try:
            execute_kwargs = {
                "progress_callback": progress_callback,
            }
            if backend_id == "codex_app_server":
                execute_kwargs["cancel_event"] = cancel_event
            result = executor.execute_turn(
                turn,
                **execute_kwargs,
            )
            event = {
                "type": "done",
                "success": result.success,
                "content": result.content,
                "error": result.error,
                "total_steps": result.total_steps,
                "session_id": session_id,
            }
            event.update({
                "backend": getattr(result, "backend", "") or backend_id,
                "error_code": getattr(result, "error_code", None),
                "request_id": request_id,
            })
            asyncio.run_coroutine_threadsafe(queue.put(event), loop)
        except Exception as exc:
            logger.error("Agent stream error: %s", exc)
            event = {
                "type": "error",
                "message": "Agent Chat failed" if backend_id == "codex_app_server" else str(exc),
                "error_code": getattr(exc, "code", "unknown_backend_error"),
                "backend": backend_id,
                "request_id": request_id,
            }
            asyncio.run_coroutine_threadsafe(queue.put(event), loop)

    async def event_generator():
        fut = None

        def _accepted_event() -> dict:
            # accepted 是流协议的第一条事件（提交边界）：Web store 只有在收到
            # 它之后才会渲染用户消息气泡，因此必须在任何耗时准备之前发出——
            # 意图解析的 LLM 兜底（8s 超时 + 一次重试）、AkShare 扩展下载、
            # executor 构建与 prepare_turn 持久化都发生在它之后。否则用户输入
            # （如"分析三花"触发 LLM 兜底时）要等解析完成才显示气泡。
            return {
                "type": "accepted",
                "backend": backend_id,
                "request_id": request_id,
                "session_id": session_id,
            }

        try:
            # accepted 首事件立即送达：前端无需等待意图识别或 AI 分析即可
            # 渲染用户消息。后续所有分支（正常执行 / 确认短路 / 确认失败 /
            # 准备失败）都只消费这一个 accepted，绝不重复发出。
            yield "data: " + json.dumps(_accepted_event(), ensure_ascii=False) + "\n\n"

            try:
                executor = await asyncio.to_thread(_build_executor, config, skills or None)

                # ============================================================
                # Web 意图识别层（issue #1125 需求方向）
                # 在 Agent 编排前对用户消息做意图分类，发 intent_resolved 事件；
                # 需用户确认时（多候选股票 / 低置信度）短路返回 action_required，避免未确认即执行分析。
                # getattr 默认值 False：测试/机器人等临时 Config 走原有路径；
                # 正式环境 Config（settings.json / env）默认开启此开关。
                # 必须位于 prepare_turn 之前：解析注入的 stock_code/web_intent
                # 写入 stream_ctx 后，prepare_agent_chat 在 prepare 阶段才会固化股票作用域。
                # accepted 首事件已在此块之前发出：意图解析即使触发 LLM 兜底
                # （8s 超时 + 一次重试）也不会推迟前端用户气泡的渲染。
                # ============================================================
                intent_confirmed = False
                web_intent_session: Any = None
                web_intent_resolution: Any = None
                if getattr(config, "agent_web_intent_enabled", False):
                    try:
                        # ---- 延迟 import，避免非 Web 场景加载意图模块 ----
                        from src.agent.conversation import conversation_manager
                        from src.agent.web_intent_resolver import (
                            WebIntentResolver,              # 意图解析器：分类 + 股票消歧
                            apply_resolution_to_session,    # 将解析结果写入会话上下文
                            build_action_required_event,    # 构建“需用户确认”SSE 事件
                            build_clarification_message,    # 构建澄清问题文本
                            build_intent_resolved_event,    # 构建“意图已解析”SSE 事件
                            clear_pending_actions,          # 确认流程失败时清理待确认状态
                        )
                        # 获取或创建当前会话（session_id 唯一标识一次对话）
                        web_intent_session = conversation_manager.get_or_create(session_id)

                        def _resolve_web_intent() -> Any:
                            # 意图解析可能触发 LLM 兜底（同步网络调用：8s 超时 +
                            # 一次重试）或 AkShare 扩展下载，必须在工作线程执行，
                            # 否则会阻塞 SSE 事件循环。

                            return WebIntentResolver(config).resolve(
                                request.message,              # 用户原始输入
                                session_context=web_intent_session.context,  # 会话历史上下文
                                request_context=stream_ctx,       # 请求级上下文（skills 等）
                            )

                        web_intent_resolution = await asyncio.to_thread(_resolve_web_intent)

                        # ---- 需要用户确认的分支 ----
                        if web_intent_resolution.needs_confirmation:
                            # 一旦判定需要确认，立即短路：确认分支内任何一步失败
                            # 都绝不退回 Agent 执行，否则会绕过“未确认不执行”安全门，
                            # 对歧义请求直接分析。
                            intent_confirmed = True
                            try:
                                # 构建澄清问题文本（如“您是指招商银行还是招商证券？”）
                                clarification = build_clarification_message(web_intent_resolution)
                                # 将用户原始消息和澄清回复写入会话历史（本地 SQLite 写，
                                # 移出事件循环线程，与意图解析保持一致）
                                await asyncio.to_thread(
                                    conversation_manager.add_message,
                                    session_id,
                                    "user",
                                    request.message,
                                )
                                await asyncio.to_thread(
                                    conversation_manager.add_message,
                                    session_id,
                                    "assistant",
                                    clarification,
                                )
                                # 确认分支的服务器持久化（user + assistant 会话历史）
                                # 已成功，此时才把意图层上下文写入会话，保证 Web 状态
                                # 与服务器持久化共享同一提交点。
                                apply_resolution_to_session(web_intent_session, web_intent_resolution)
                                # accepted 首事件已在流开头发出（首事件契约），
                                # 确认分支只需按序补发后续事件；确认分支已处于
                                # 事件循环线程内：直接同步入队，保证
                                # intent_resolved → action_required → done 顺序送达。
                                # 不能用 progress_callback：其 run_coroutine_threadsafe
                                # 只是调度，会被紧随其后的 done 抢先消费，导致
                                # action_required 永远到不了前端确认界面。
                                await queue.put(build_intent_resolved_event(web_intent_resolution))
                                await queue.put(build_action_required_event(web_intent_resolution))
                                # 发送 done 事件结束本次 SSE 流（content 携带澄清文本）
                                await queue.put({
                                    "type": "done",
                                    "success": True,
                                    "content": clarification,
                                    "error": None,
                                    "total_steps": 0,       # 未执行分析步骤
                                    "session_id": session_id,
                                })
                            except Exception:
                                # 确认分支失败（如会话历史写入异常）仍保持短路：
                                # 绝不执行未确认的歧义请求，发兜底终端事件结束流。
                                # 同时清空已写入会话的待确认动作，避免下一轮消息
                                # 被误当成本轮失败确认流程的回复而执行旧歧义请求。
                                # 清理本身失败也只记警告，不改变"确认失败仅 error
                                # 终态"的短路契约。
                                try:
                                    clear_pending_actions(web_intent_session)
                                except Exception:
                                    logger.warning(
                                        "Failed to clear pending intent actions "
                                        "after confirmation branch failure",
                                        exc_info=True,
                                    )
                                logger.warning(
                                    "Web intent confirmation branch failed, "
                                    "skipping analysis of unconfirmed request",
                                    exc_info=True,
                                )
                                await queue.put({
                                    "type": "error",
                                    "message": "无法完成该请求的确认流程，请稍后重试",
                                    "error_code": "confirmation_failed",
                                    "backend": backend_id,
                                    "request_id": request_id,
                                })

                        # ---- 意图已确定，无需确认的分支 ----
                        else:
                            # 推送意图解析结果事件到 SSE 流（非确认分支经后续
                            # await to_thread 挂起点被执行，仍按序送达）
                            progress_callback(build_intent_resolved_event(web_intent_resolution))
                            # 将解析出的主股票代码注入上下文（#1619 股票作用域锁定），
                            # 后续追问或仅提股票名的消息自动锁定同一只股票。
                            primary_code = web_intent_resolution.primary_stock_code
                            if primary_code and not stream_ctx.get("stock_code"):
                                # 仅在上下文未指定 stock_code 时才覆盖（显式传入优先）
                                stream_ctx["stock_code"] = primary_code
                            # 将解析出的意图类型写入上下文，供编排器按意图分流策略
                            stream_ctx["web_intent"] = web_intent_resolution.intent
                            # 确认消费轮的多股比较：确认回复本身（如"港股"）不带
                            # 任何代码，primary_stock_code 又为空串；已解析的比较对
                            # 与原始请求必须显式注入本轮上下文，否则 prepare_turn
                            # 只看到裸确认回复，无法构建比较作用域，工具调用不再
                            # 受比较对约束，退化为泛市场追问或单股回答。
                            if web_intent_resolution.source == "confirmation":
                                resolved_codes = [
                                    stock.code
                                    for stock in web_intent_resolution.stocks
                                    if getattr(stock, "code", "")
                                ]
                                if len(resolved_codes) >= 2:
                                    stream_ctx["resolved_stock_codes"] = resolved_codes
                                    if web_intent_resolution.original_request:
                                        stream_ctx["web_intent_original_request"] = (
                                            web_intent_resolution.original_request
                                        )
                    except Exception:
                        # 意图解析失败时降级：记录警告，继续走原有编排流程
                        logger.warning(
                            "Web intent resolution failed, continuing without it",
                            exc_info=True,
                        )

                if not intent_confirmed:
                    turn = await asyncio.to_thread(
                        executor.prepare_turn,
                        message=request.message,
                        session_id=session_id,
                        context=stream_ctx,
                        selected_skill_ids=selected_skill_ids,
                    )
                    # prepare_turn 是服务端持久化提交点：意图层上下文必须等它
                    # 成功后才写入会话。若 prepare_turn 失败，上面的异常路径只发
                    # request_not_accepted，会话 recent_stocks / last_intent 保持
                    # 不变，避免被拒绝的请求污染后续追问解释。
                    if web_intent_session is not None and web_intent_resolution is not None:
                        try:
                            apply_resolution_to_session(web_intent_session, web_intent_resolution)
                        except Exception:
                            logger.warning(
                                "Failed to persist web intent session context "
                                "after turn preparation; continuing without it",
                                exc_info=True,
                            )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Agent request preparation failed: %s", exc, exc_info=True)
                event = {
                    "type": "error",
                    "message": "Agent request was not accepted",
                    "error_code": "request_not_accepted",
                    "backend": backend_id,
                    "request_id": request_id,
                }
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                return

            if not intent_confirmed:
                # accepted 首事件已在流开头发出；prepare_turn 完成（含会话
                # 持久化）后才启动后端执行，提交边界语义保持不变。
                fut = loop.run_in_executor(None, run_sync, executor, turn)
            while True:
                try:
                    if backend_id == "codex_app_server":
                        # Codex owns one authoritative backend deadline.  A
                        # second API timeout would race it and could emit a
                        # terminal event before process cleanup finishes.
                        event = await queue.get()
                    else:
                        event = await asyncio.wait_for(queue.get(), timeout=300.0)
                except asyncio.TimeoutError:
                    event = {"type": "error", "message": "分析超时"}
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                    break
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                if event.get("type") in ("done", "error"):
                    break
        finally:
            if backend_id == "codex_app_server" and (fut is None or not fut.done()):
                cancel_event.set()
            try:
                if backend_id == "codex_app_server" and fut is not None:
                    while not fut.done():
                        try:
                            await asyncio.shield(fut)
                        except asyncio.CancelledError:
                            # Client disconnect cancellation must not abandon the
                            # owned Codex/tool worker before it actually exits.
                            cancel_event.set()
                    if not fut.cancelled():
                        fut.result()
                elif fut is not None:
                    await asyncio.wait_for(fut, timeout=5.0)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                # Cleanup taking longer than 5s is treated as an expected timeout; no warning.
                logger.debug("agent executor cleanup timed out after 5s for session %s", session_id)
            except Exception as exc:
                logger.warning("agent executor cleanup error (ignored): %s", exc, exc_info=True)
            finally:
                if backend_id == "codex_app_server":
                    with _ACTIVE_CODEX_STREAMS_LOCK:
                        if _ACTIVE_CODEX_STREAMS.get(request_id) is cancel_event:
                            _ACTIVE_CODEX_STREAMS.pop(request_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/chat/stream/{request_id}/cancel")
async def cancel_agent_chat_stream(request_id: str):
    """Signal cancellation while the original Codex SSE remains open."""
    with _ACTIVE_CODEX_STREAMS_LOCK:
        cancel_event = _ACTIVE_CODEX_STREAMS.get(request_id)
    if cancel_event is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "request_not_active",
                "message": "This Agent request is no longer running",
            },
        )
    cancel_event.set()
    return {"accepted": True, "request_id": request_id}
