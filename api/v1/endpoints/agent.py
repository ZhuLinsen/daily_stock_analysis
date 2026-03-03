# -*- coding: utf-8 -*-
"""
Agent API endpoints.
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.config import get_config

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
}

logger = logging.getLogger(__name__)

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    skills: Optional[List[str]] = None
    context: Optional[Dict[str, Any]] = None  # Previous analysis context for data reuse

class ChatResponse(BaseModel):
    success: bool
    content: str
    session_id: str
    error: Optional[str] = None

class StrategyInfo(BaseModel):
    id: str
    name: str
    description: str

class StrategiesResponse(BaseModel):
    strategies: List[StrategyInfo]

@router.get("/strategies", response_model=StrategiesResponse)
async def get_strategies():
    """
    Get available agent strategies.
    """
    config = get_config()
    from src.agent.factory import get_skill_manager

    skill_manager = get_skill_manager(config)
    strategies = [
        StrategyInfo(id=skill_id, name=skill.display_name, description=skill.description)
        for skill_id, skill in skill_manager._skills.items()
    ]
    return StrategiesResponse(strategies=strategies)

@router.post("/chat", response_model=ChatResponse)
async def agent_chat(request: ChatRequest):
    """
    Chat with the AI Agent.
    """
    config = get_config()
    
    if not config.agent_mode:
        raise HTTPException(status_code=400, detail="Agent mode is not enabled")
        
    session_id = request.session_id or str(uuid.uuid4())
    
    try:
        executor = _build_executor(config, request.skills)

        # Offload the blocking call to a thread to avoid blocking the event loop.
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: executor.chat(message=request.message, session_id=session_id,
                                  context=request.context),
        )

        return ChatResponse(
            success=result.success,
            content=result.content,
            session_id=session_id,
            error=result.error
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
async def list_chat_sessions(limit: int = 50):
    """获取聊天会话列表"""
    from src.storage import get_db
    sessions = get_db().get_chat_sessions(limit=limit)
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


def _build_executor(config, skills: Optional[List[str]] = None):
    """Build and return a configured AgentExecutor (sync helper)."""
    from src.agent.factory import build_agent_executor
    return build_agent_executor(config, skills=skills)


@router.post("/chat/stream")
async def agent_chat_stream(request: ChatRequest):
    """
    Chat with the AI Agent, streaming progress via SSE.
    Each SSE event is a JSON object with a 'type' field:
      - thinking: AI is deciding next action
      - tool_start: a tool call has begun
      - tool_done: a tool call finished
      - generating: final answer being generated
      - done: analysis complete, contains 'content' and 'success'
      - error: error occurred, contains 'message'
    """
    config = get_config()
    if not config.agent_mode:
        raise HTTPException(status_code=400, detail="Agent mode is not enabled")

    session_id = request.session_id or str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def progress_callback(event: dict):
        # Enrich tool events with display names
        if event.get("type") in ("tool_start", "tool_done"):
            tool = event.get("tool", "")
            event["display_name"] = TOOL_DISPLAY_NAMES.get(tool, tool)
        asyncio.run_coroutine_threadsafe(queue.put(event), loop)

    def run_sync():
        try:
            executor = _build_executor(config, request.skills)
            result = executor.chat(
                message=request.message,
                session_id=session_id,
                progress_callback=progress_callback,
                context=request.context,
            )
            asyncio.run_coroutine_threadsafe(
                queue.put({
                    "type": "done",
                    "success": result.success,
                    "content": result.content,
                    "error": result.error,
                    "total_steps": result.total_steps,
                    "session_id": session_id,
                }),
                loop,
            )
        except Exception as exc:
            logger.error(f"Agent stream error: {exc}")
            asyncio.run_coroutine_threadsafe(
                queue.put({"type": "error", "message": str(exc)}),
                loop,
            )

    async def event_generator():
        # Start executor in a thread so we don't block the event loop
        fut = loop.run_in_executor(None, run_sync)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=300.0)
                except asyncio.TimeoutError:
                    yield "data: " + json.dumps({"type": "error", "message": "分析超时"}, ensure_ascii=False) + "\n\n"
                    break
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                if event.get("type") in ("done", "error"):
                    break
        finally:
            try:
                await asyncio.wait_for(fut, timeout=5.0)
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
