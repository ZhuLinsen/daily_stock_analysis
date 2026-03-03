# -*- coding: utf-8 -*-
"""
===================================
股票分析接口
===================================

职责：
1. 提供 POST /api/v1/analysis/analyze 触发分析接口
2. 提供 GET /api/v1/analysis/status/{task_id} 查询任务状态接口
3. 提供 GET /api/v1/analysis/tasks 获取任务列表接口
4. 提供 GET /api/v1/analysis/tasks/stream SSE 实时推送接口

特性：
- 异步任务队列：分析任务异步执行，不阻塞请求
- 防重复提交：相同股票代码正在分析时返回 409
- SSE 实时推送：任务状态变化实时通知前端
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, Union, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from api.deps import get_config_dep
from api.v1.schemas.analysis import (
    AnalyzeRequest,
    AnalysisResultResponse,
    TaskAccepted,
    TaskStatus,
    TaskInfo,
    TaskListResponse,
    DuplicateTaskErrorResponse,
)
from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.history import (
    AnalysisReport,
    ReportMeta,
    ReportSummary,
    ReportStrategy,
    ReportDetails,
)
from data_provider.base import canonical_stock_code
from src.config import Config
from src.services.task_queue import (
    get_task_queue,
    DuplicateTaskError,
    TaskStatus as TaskStatusEnum,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# POST /analyze - 触发股票分析
# ============================================================

@router.post(
    "/analyze",
    response_model=AnalysisResultResponse,
    responses={
        200: {"description": "分析完成（同步模式）", "model": AnalysisResultResponse},
        202: {"description": "分析任务已接受（异步模式）", "model": TaskAccepted},
        400: {"description": "请求参数错误", "model": ErrorResponse},
        409: {"description": "股票正在分析中，拒绝重复提交", "model": DuplicateTaskErrorResponse},
        500: {"description": "分析失败", "model": ErrorResponse},
    },
    summary="触发股票分析",
    description="启动 AI 智能分析任务，支持同步和异步模式。异步模式下相同股票代码不允许重复提交。"
)
def trigger_analysis(
        request: AnalyzeRequest,
        config: Config = Depends(get_config_dep)
) -> Union[AnalysisResultResponse, JSONResponse]:
    """
    触发股票分析
    
    启动 AI 智能分析任务，支持单只或多只股票批量分析
    
    流程：
    1. 校验请求参数
    2. 异步模式：检查重复 -> 提交任务队列 -> 返回 202
    3. 同步模式：直接执行分析 -> 返回 200
    
    Args:
        request: 分析请求参数
        config: 配置依赖
        
    Returns:
        AnalysisResultResponse: 分析结果（同步模式）
        TaskAccepted: 任务已接受（异步模式，返回 202）
        
    Raises:
        HTTPException: 400 - 请求参数错误
        HTTPException: 409 - 股票正在分析中
        HTTPException: 500 - 分析失败
    """
    # 校验请求参数
    stock_codes = []
    if request.stock_code:
        stock_codes.append(request.stock_code)
    if request.stock_codes:
        stock_codes.extend(request.stock_codes)

    if not stock_codes:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": "必须提供 stock_code 或 stock_codes 参数"
            }
        )

    # 统一大小写后去重，确保 ['aapl', 'AAPL'] 被识别为同一股票（Issue #355）
    stock_codes = [canonical_stock_code(c) for c in stock_codes]
    stock_codes = list(dict.fromkeys(stock_codes))
    stock_code = stock_codes[0]  # 当前只处理第一个

    # 异步模式：使用任务队列
    if request.async_mode:
        return _handle_async_analysis(stock_code, request)

    # 同步模式：直接执行分析
    return _handle_sync_analysis(stock_code, request)


def _handle_async_analysis(
    stock_code: str,
    request: AnalyzeRequest
) -> JSONResponse:
    """
    处理异步分析请求
    
    提交任务到队列，立即返回 202
    如果股票正在分析中，返回 409
    """
    task_queue = get_task_queue()
    
    try:
        # 提交任务（如果重复会抛出 DuplicateTaskError）
        task_info = task_queue.submit_task(
            stock_code=stock_code,
            stock_name=None,  # 名称在分析过程中获取
            report_type=request.report_type,
            force_refresh=request.force_refresh,
        )
        
        # 返回 202 Accepted
        task_accepted = TaskAccepted(
            task_id=task_info.task_id,
            status="pending",
            message=f"分析任务已加入队列: {stock_code}"
        )
        return JSONResponse(
            status_code=202,
            content=task_accepted.model_dump()
        )
        
    except DuplicateTaskError as e:
        # 股票正在分析中，返回 409 Conflict
        error_response = DuplicateTaskErrorResponse(
            error="duplicate_task",
            message=str(e),
            stock_code=e.stock_code,
            existing_task_id=e.existing_task_id,
        )
        return JSONResponse(
            status_code=409,
            content=error_response.model_dump()
        )


def _handle_sync_analysis(
    stock_code: str,
    request: AnalyzeRequest
) -> AnalysisResultResponse:
    """
    处理同步分析请求
    
    直接执行分析，等待完成后返回结果
    """
    import uuid
    from src.services.analysis_service import AnalysisService
    
    query_id = uuid.uuid4().hex
    
    try:
        service = AnalysisService()
        result = service.analyze_stock(
            stock_code=stock_code,
            report_type=request.report_type,
            force_refresh=request.force_refresh,
            query_id=query_id
        )

        if result is None:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "analysis_failed",
                    "message": f"分析股票 {stock_code} 失败"
                }
            )

        # 构建报告结构
        report_data = result.get("report", {})
        report = _build_analysis_report(
            report_data, query_id, stock_code, result.get("stock_name")
        )

        return AnalysisResultResponse(
            query_id=query_id,
            stock_code=result.get("stock_code", stock_code),
            stock_name=result.get("stock_name"),
            report=report.model_dump() if report else None,
            created_at=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"分析失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"分析过程发生错误: {str(e)}"
            }
        )


# ============================================================
# GET /tasks - 获取任务列表
# ============================================================

@router.get(
    "/tasks",
    response_model=TaskListResponse,
    responses={
        200: {"description": "任务列表"},
    },
    summary="获取分析任务列表",
    description="获取当前所有分析任务，可按状态筛选"
)
def get_task_list(
    status: Optional[str] = Query(
        None,
        description="筛选状态：pending, processing, completed, failed（支持逗号分隔多个）"
    ),
    limit: int = Query(20, description="返回数量限制", ge=1, le=100),
) -> TaskListResponse:
    """
    获取分析任务列表
    
    Args:
        status: 状态筛选（可选）
        limit: 返回数量限制
        
    Returns:
        TaskListResponse: 任务列表响应
    """
    task_queue = get_task_queue()
    
    # 获取所有任务
    all_tasks = task_queue.list_all_tasks(limit=limit)
    
    # 状态筛选
    if status:
        status_list = [s.strip().lower() for s in status.split(",")]
        all_tasks = [t for t in all_tasks if t.status.value in status_list]
    
    # 统计信息
    stats = task_queue.get_task_stats()
    
    # 转换为 Schema
    task_infos = [
        TaskInfo(
            task_id=t.task_id,
            stock_code=t.stock_code,
            stock_name=t.stock_name,
            status=t.status.value,
            progress=t.progress,
            message=t.message,
            report_type=t.report_type,
            created_at=t.created_at.isoformat(),
            started_at=t.started_at.isoformat() if t.started_at else None,
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
            error=t.error,
        )
        for t in all_tasks
    ]
    
    return TaskListResponse(
        total=stats["total"],
        pending=stats["pending"],
        processing=stats["processing"],
        tasks=task_infos,
    )


# ============================================================
# GET /tasks/stream - SSE 实时推送
# ============================================================

@router.get(
    "/tasks/stream",
    responses={
        200: {"description": "SSE 事件流", "content": {"text/event-stream": {}}},
    },
    summary="任务状态 SSE 流",
    description="通过 Server-Sent Events 实时推送任务状态变化"
)
async def task_stream():
    """
    SSE 任务状态流
    
    事件类型：
    - connected: 连接成功
    - task_created: 新任务创建
    - task_started: 任务开始执行
    - task_completed: 任务完成
    - task_failed: 任务失败
    - heartbeat: 心跳（每 30 秒）
    
    Returns:
        StreamingResponse: SSE 事件流
    """
    async def event_generator():
        task_queue = get_task_queue()
        event_queue: asyncio.Queue = asyncio.Queue()
        
        # 发送连接成功事件
        yield _format_sse_event("connected", {"message": "Connected to task stream"})
        
        # 发送当前进行中的任务
        pending_tasks = task_queue.list_pending_tasks()
        for task in pending_tasks:
            yield _format_sse_event("task_created", task.to_dict())
        
        # 订阅任务事件
        task_queue.subscribe(event_queue)
        
        try:
            while True:
                try:
                    # 等待事件，超时发送心跳
                    event = await asyncio.wait_for(event_queue.get(), timeout=30)
                    yield _format_sse_event(event["type"], event["data"])
                except asyncio.TimeoutError:
                    # 心跳
                    yield _format_sse_event("heartbeat", {
                        "timestamp": datetime.now().isoformat()
                    })
        except asyncio.CancelledError:
            # 客户端断开连接
            pass
        finally:
            task_queue.unsubscribe(event_queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        }
    )


def _format_sse_event(event_type: str, data: Dict[str, Any]) -> str:
    """
    格式化 SSE 事件
    
    Args:
        event_type: 事件类型
        data: 事件数据
        
    Returns:
        SSE 格式字符串
    """
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ============================================================
# GET /status/{task_id} - 查询单个任务状态
# ============================================================

@router.get(
    "/status/{task_id}",
    response_model=TaskStatus,
    responses={
        200: {"description": "任务状态"},
        404: {"description": "任务不存在", "model": ErrorResponse},
    },
    summary="查询分析任务状态",
    description="根据 task_id 查询单个任务的状态"
)
def get_analysis_status(task_id: str) -> TaskStatus:
    """
    查询分析任务状态
    
    优先从任务队列查询，如果不存在则从数据库查询历史记录
    
    Args:
        task_id: 任务 ID
        
    Returns:
        TaskStatus: 任务状态信息
        
    Raises:
        HTTPException: 404 - 任务不存在
    """
    # 1. 先从任务队列查询
    task_queue = get_task_queue()
    task = task_queue.get_task(task_id)
    
    if task:
        return TaskStatus(
            task_id=task.task_id,
            status=task.status.value,
            progress=task.progress,
            result=None,  # 进行中的任务没有结果
            error=task.error,
        )
    
    # 2. 从数据库查询已完成的记录
    try:
        from src.storage import DatabaseManager
        db = DatabaseManager.get_instance()
        records = db.get_analysis_history(query_id=task_id, limit=1)

        if records:
            record = records[0]
            # Build report from DB record so completed tasks return real data
            report_dict = AnalysisReport(
                meta=ReportMeta(
                    id=record.id,
                    query_id=task_id,
                    stock_code=record.code,
                    stock_name=record.name,
                    report_type=getattr(record, 'report_type', None),
                    created_at=record.created_at.isoformat() if record.created_at else None,
                ),
                summary=ReportSummary(
                    sentiment_score=record.sentiment_score,
                    operation_advice=record.operation_advice,
                    trend_prediction=record.trend_prediction,
                    analysis_summary=record.analysis_summary,
                ),
                strategy=ReportStrategy(
                    ideal_buy=str(getattr(record, 'ideal_buy', None)) if getattr(record, 'ideal_buy', None) is not None else None,
                    secondary_buy=str(getattr(record, 'secondary_buy', None)) if getattr(record, 'secondary_buy', None) is not None else None,
                    stop_loss=str(getattr(record, 'stop_loss', None)) if getattr(record, 'stop_loss', None) is not None else None,
                    take_profit=str(getattr(record, 'take_profit', None)) if getattr(record, 'take_profit', None) is not None else None,
                ),
            ).model_dump()
            return TaskStatus(
                task_id=task_id,
                status="completed",
                progress=100,
                result=AnalysisResultResponse(
                    query_id=task_id,
                    stock_code=record.code,
                    stock_name=record.name,
                    report=report_dict,
                    created_at=record.created_at.isoformat() if record.created_at else datetime.now().isoformat()
                ),
                error=None
            )

    except Exception as e:
        logger.error(f"查询任务状态失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"查询任务状态失败: {str(e)}"
            }
        )

    # 3. 任务不存在
    raise HTTPException(
        status_code=404,
        detail={
            "error": "not_found",
            "message": f"任务 {task_id} 不存在或已过期"
        }
    )


# ============================================================
# 辅助函数
# ============================================================

def _build_analysis_report(
        report_data: Dict[str, Any],
        query_id: str,
        stock_code: str,
        stock_name: Optional[str] = None
) -> AnalysisReport:
    """
    构建符合 API 规范的分析报告
    
    Args:
        report_data: 原始报告数据
        query_id: 查询 ID
        stock_code: 股票代码
        stock_name: 股票名称
        
    Returns:
        AnalysisReport: 结构化的分析报告
    """
    meta_data = report_data.get("meta", {})
    summary_data = report_data.get("summary", {})
    strategy_data = report_data.get("strategy", {})
    details_data = report_data.get("details", {})

    meta = ReportMeta(
        query_id=meta_data.get("query_id", query_id),
        stock_code=meta_data.get("stock_code", stock_code),
        stock_name=meta_data.get("stock_name", stock_name),
        report_type=meta_data.get("report_type", "detailed"),
        created_at=meta_data.get("created_at", datetime.now().isoformat()),
        current_price=meta_data.get("current_price"),
        change_pct=meta_data.get("change_pct"),
    )

    summary = ReportSummary(
        analysis_summary=summary_data.get("analysis_summary"),
        operation_advice=summary_data.get("operation_advice"),
        trend_prediction=summary_data.get("trend_prediction"),
        sentiment_score=summary_data.get("sentiment_score"),
        sentiment_label=summary_data.get("sentiment_label")
    )

    strategy = None
    if strategy_data:
        strategy = ReportStrategy(
            ideal_buy=strategy_data.get("ideal_buy"),
            secondary_buy=strategy_data.get("secondary_buy"),
            stop_loss=strategy_data.get("stop_loss"),
            take_profit=strategy_data.get("take_profit")
        )

    details = None
    if details_data:
        details = ReportDetails(
            news_content=details_data.get("news_summary") or details_data.get("news_content"),
            raw_result=details_data,
            context_snapshot=None
        )

    return AnalysisReport(
        meta=meta,
        summary=summary,
        strategy=strategy,
        details=details
    )
