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

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from api.v1.schemas.system_config import AgentBackendStatusResponse
from src.config import get_config
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
async def agent_chat(request: ChatRequest):
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
        skills = request.effective_skills
        executor = _build_executor(config, skills or None)

        # Pass explicit skills into context for the orchestrator.
        # Direct assignment so caller-provided skills always take precedence
        # over any stale value carried in the context dict.
        ctx = dict(request.context or {})
        if skills is not None:
            ctx["skills"] = skills

        # Offload the blocking call to a thread to avoid blocking the event loop.
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: executor.chat(message=request.message, session_id=session_id,
                                  context=ctx),
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

class SessionMessagesResponse(BaseModel):
    session_id: str
    messages: List[Dict[str, Any]]


@router.get("/chat/sessions", response_model=SessionsResponse)
async def list_chat_sessions(limit: int = 50, user_id: Optional[str] = None):
    """获取聊天会话列表

    Args:
        limit: Maximum number of sessions to return.
        user_id: Optional platform-prefixed user identifier for session
            isolation.  When provided, only sessions whose session_id
            starts with this prefix are returned.  The value must
            include the platform prefix, e.g. ``telegram_12345``,
            ``feishu_ou_abc``.
    """
    from src.storage import get_db
    sessions = get_db().get_chat_sessions(
        limit=limit,
        session_prefix=user_id,
        extra_session_ids=[user_id] if user_id else None,
    )
    return SessionsResponse(sessions=sessions)


@router.get("/chat/sessions/{session_id}", response_model=SessionMessagesResponse)
async def get_chat_session_messages(session_id: str, limit: int = 100):
    """获取单个会话的完整消息"""
    from src.storage import get_db
    messages = get_db().get_conversation_messages(session_id, limit=limit)
    return SessionMessagesResponse(session_id=session_id, messages=messages)


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    """删除指定会话"""
    from src.storage import get_db
    count = get_db().delete_conversation_session(session_id)
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
async def agent_chat_stream(request: ChatRequest):
    """
    Chat with the AI Agent, streaming progress via SSE.
    Each SSE event is a JSON object with a 'type' field:
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

    # Pass explicit skills into context for the orchestrator.
    # Direct assignment so caller-provided skills always take precedence.
    skills = request.effective_skills
    stream_ctx = dict(request.context or {})
    if skills is not None:
        stream_ctx["skills"] = skills

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
        try:
            try:
                executor = await asyncio.to_thread(_build_executor, config, skills or None)
                turn = await asyncio.to_thread(
                    executor.prepare_turn,
                    message=request.message,
                    session_id=session_id,
                    context=stream_ctx,
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

            accepted_event = {
                "type": "accepted",
                "backend": backend_id,
                "request_id": request_id,
                "session_id": session_id,
            }
            yield "data: " + json.dumps(accepted_event, ensure_ascii=False) + "\n\n"

            # Backend execution starts only after the accepted event has been
            # yielded, so Web state and server persistence share one commit point.
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
