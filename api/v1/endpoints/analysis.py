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
import re
from datetime import datetime
from typing import Optional, Union, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from api.deps import get_config_dep
from api.v1.schemas.analysis import (
    AnalyzeRequest,
    AnalysisResultResponse,
    TaskAccepted,
    BatchTaskAcceptedResponse,
    BatchTaskAcceptedItem,
    BatchDuplicateTaskItem,
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
from data_provider.base import canonical_stock_code, normalize_stock_code
from src.config import Config
from src.report_language import get_localized_stock_name, normalize_report_language
from src.services.name_to_code_resolver import resolve_name_to_code
from src.services.stock_code_utils import is_code_like
from src.services.task_queue import (
    get_task_queue,
    DuplicateTaskError,
    TaskStatus as TaskStatusEnum,
)
from src.utils.data_processing import (
    normalize_model_used,
    parse_json_field,
    extract_fundamental_detail_fields,
    extract_board_detail_fields,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_SUPPORTED_FREE_TEXT_RE = re.compile(r"^[A-Za-z0-9.*\-+\u3400-\u9fff\s]+$")


def _invalid_analysis_input_error() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "error": "validation_error",
            "message": "请输入有效的股票代码或股票名称",
        },
    )


def _is_obviously_invalid_analysis_input(text: str) -> bool:
    """Reject mixed alphanumeric noise and unsupported symbols early."""
    if not text or is_code_like(text):
        return False

    if not _SUPPORTED_FREE_TEXT_RE.fullmatch(text):
        return True

    has_letters = any(ch.isalpha() and ch.isascii() for ch in text)
    has_digits = any(ch.isdigit() for ch in text)
    return has_letters and has_digits


def _resolve_and_normalize_input(raw_value: str) -> str:
    """
    Resolve and normalize a stock input for analysis requests.

    Code-like values keep the existing canonical path.
    Non-code inputs must resolve to a known stock code. Obvious garbage
    input is rejected before expensive resolver and task-queue work.
    """
    text = (raw_value or "").strip()
    if not text:
        return ""

    if is_code_like(text):
        return canonical_stock_code(text)

    if _is_obviously_invalid_analysis_input(text):
        raise _invalid_analysis_input_error()

    resolved = resolve_name_to_code(text)
    if resolved:
        return canonical_stock_code(resolved)

    raise _invalid_analysis_input_error()


# ============================================================
# POST /analyze - 触发股票分析
# ============================================================

@router.post(
    "/analyze",
    response_model=AnalysisResultResponse,
    responses={
        200: {"description": "分析完成（同步模式）", "model": AnalysisResultResponse},
        202: {
            "description": "分析任务已接受（异步模式）",
            "model": Union[TaskAccepted, BatchTaskAcceptedResponse],
        },
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
        TaskAccepted | BatchTaskAcceptedResponse: 任务已接受（异步模式，返回 202）
        
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

    # Normalize and de-duplicate inputs while preserving compatibility.
    resolved = [_resolve_and_normalize_input(c) for c in stock_codes]
    
    seen = set()
    unique_codes = []
    for code in resolved:
        if not code:
            continue
        # Use normalize_stock_code to ensure '600519' and '600519.SH' are merged
        norm = normalize_stock_code(code)
        if norm not in seen:
            seen.add(norm)
            unique_codes.append(code)
    
    stock_codes = unique_codes

    # Limit the number of stocks in a single request to prevent DoS
    MAX_BATCH_SIZE = 50
    if len(stock_codes) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": f"单次分析请求最多支持 {MAX_BATCH_SIZE} 只股票"
            }
        )

    if not stock_codes:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": "股票代码不能为空或仅包含空白字符"
            }
        )

    # Sync mode only supports single-stock analysis.
    if not request.async_mode:
        if len(stock_codes) > 1:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "validation_error",
                    "message": "同步模式仅支持单只股票分析，请使用 async_mode=true 进行批量分析"
                }
            )
        return _handle_sync_analysis(stock_codes[0], request)

    # Async mode submits one task per stock.
    return _handle_async_analysis_batch(stock_codes, request)


def _handle_async_analysis_batch(
    stock_codes: list,
    request: AnalyzeRequest
) -> JSONResponse:
    """
    Handle asynchronous analysis requests, including batch submission.
    """
    task_queue = get_task_queue()
    
    # Preserve metadata for single-stock requests. For batch requests,
    # only carry through metadata that semantically applies to the whole
    # batch, such as import/image source tracking.
    is_single = len(stock_codes) == 1
    preserve_batch_metadata = request.selection_source in {"import", "image"}

    stock_name = request.stock_name if is_single else None
    original_query = request.original_query if (is_single or preserve_batch_metadata) else None
    selection_source = request.selection_source if (is_single or preserve_batch_metadata) else None

    accepted_tasks, duplicate_errors = task_queue.submit_tasks_batch(
        stock_codes=stock_codes,
        stock_name=stock_name,
        original_query=original_query,
        selection_source=selection_source,
        report_type=request.report_type,
        force_refresh=request.force_refresh,
    )

    accepted = [
        BatchTaskAcceptedItem(
            task_id=task.task_id,
            stock_code=task.stock_code,
            status="pending",
            message=f"分析任务已加入队列: {task.stock_code}",
        )
        for task in accepted_tasks
    ]
    duplicates = [
        BatchDuplicateTaskItem(
            stock_code=dup.stock_code,
            existing_task_id=dup.existing_task_id,
            message=str(dup),
        )
        for dup in duplicate_errors
    ]
    
    # 单只股票且被拒绝：保持 409 兼容性
    if len(stock_codes) == 1 and duplicates:
        dup = duplicates[0]
        error_response = DuplicateTaskErrorResponse(
            error="duplicate_task",
            message=dup.message,
            stock_code=dup.stock_code,
            existing_task_id=dup.existing_task_id,
        )
        return JSONResponse(
            status_code=409,
            content=error_response.model_dump()
        )
    
    # 单只股票成功：保持原有响应格式兼容性
    if len(stock_codes) == 1 and accepted:
        task_accepted = TaskAccepted(
            task_id=accepted[0].task_id,
            status="pending",
            message=accepted[0].message,
        )
        return JSONResponse(
            status_code=202,
            content=task_accepted.model_dump()
        )
    
    # 批量：返回汇总结果
    batch_response = BatchTaskAcceptedResponse(
        accepted=accepted,
        duplicates=duplicates,
        message=f"已提交 {len(accepted)} 个任务，{len(duplicates)} 个重复跳过",
    )
    return JSONResponse(
        status_code=202,
        content=batch_response.model_dump()
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
        context_snapshot, fundamental_snapshot = _load_sync_fundamental_sources(
            query_id=query_id,
            stock_code=result.get("stock_code", stock_code),
        )
        report = _build_analysis_report(
            report_data,
            query_id,
            stock_code,
            result.get("stock_name"),
            context_snapshot=context_snapshot,
            fallback_fundamental_payload=fundamental_snapshot,
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
            original_query=t.original_query,
            selection_source=t.selection_source,
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
            result=None,  # In-progress tasks do not carry a result payload.
            error=task.error,
            stock_name=task.stock_name,
            original_query=task.original_query,
            selection_source=task.selection_source,
        )
    
    # 2. 从数据库查询已完成的记录
    try:
        from src.storage import DatabaseManager
        db = DatabaseManager.get_instance()
        records = db.get_analysis_history(query_id=task_id, limit=1)

        if records:
            record = records[0]
            raw_result = parse_json_field(record.raw_result)
            model_used = normalize_model_used(
                (raw_result or {}).get("model_used") if isinstance(raw_result, dict) else None
            )
            report_language = normalize_report_language(
                (raw_result or {}).get("report_language") if isinstance(raw_result, dict) else None
            )
            stock_name = get_localized_stock_name(record.name, record.code, report_language)
            # Build report from DB record so completed tasks return real data
            report_dict = AnalysisReport(
                meta=ReportMeta(
                    id=record.id,
                    query_id=task_id,
                    stock_code=record.code,
                    stock_name=stock_name,
                    report_type=getattr(record, 'report_type', None),
                    report_language=report_language,
                    created_at=record.created_at.isoformat() if record.created_at else None,
                    model_used=model_used,
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
                    stock_name=stock_name,
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

def _load_sync_fundamental_sources(
    query_id: str,
    stock_code: str,
) -> tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """
    Load context_snapshot and fallback fundamental snapshot for sync analyze response.
    """
    try:
        from src.storage import DatabaseManager

        db = DatabaseManager.get_instance()
        records = db.get_analysis_history(query_id=query_id, code=stock_code, limit=1)
        context_snapshot = None
        if records:
            context_snapshot = parse_json_field(getattr(records[0], "context_snapshot", None))

        fallback_fundamental = db.get_latest_fundamental_snapshot(
            query_id=query_id,
            code=stock_code,
        )
        return context_snapshot, fallback_fundamental
    except Exception as e:
        logger.debug(
            "load sync fundamental sources failed (fail-open): query_id=%s stock_code=%s err=%s",
            query_id,
            stock_code,
            e,
        )
        return None, None


def _build_analysis_report(
        report_data: Dict[str, Any],
        query_id: str,
        stock_code: str,
        stock_name: Optional[str] = None,
        context_snapshot: Optional[Any] = None,
        fallback_fundamental_payload: Optional[Dict[str, Any]] = None,
) -> AnalysisReport:
    """
    构建符合 API 规范的分析报告
    
    Args:
        report_data: 原始报告数据
        query_id: 查询 ID
        stock_code: 股票代码
        stock_name: 股票名称
        context_snapshot: 上下文快照（可选）
        fallback_fundamental_payload: 基本面快照 payload（可选）
        
    Returns:
        AnalysisReport: 结构化的分析报告
    """
    meta_data = report_data.get("meta", {})
    summary_data = report_data.get("summary", {})
    strategy_data = report_data.get("strategy", {})
    details_data = report_data.get("details", {})
    report_language = normalize_report_language(
        meta_data.get("report_language")
        or (context_snapshot or {}).get("report_language")
        or getattr(Config.get_instance(), "report_language", "zh")
    )
    localized_stock_name = get_localized_stock_name(
        meta_data.get("stock_name", stock_name),
        meta_data.get("stock_code", stock_code),
        report_language,
    )

    meta = ReportMeta(
        query_id=meta_data.get("query_id", query_id),
        stock_code=meta_data.get("stock_code", stock_code),
        stock_name=localized_stock_name,
        report_type=meta_data.get("report_type", "detailed"),
        report_language=report_language,
        created_at=meta_data.get("created_at", datetime.now().isoformat()),
        current_price=meta_data.get("current_price"),
        change_pct=meta_data.get("change_pct"),
        model_used=normalize_model_used(meta_data.get("model_used")),
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

    extracted_fundamental = extract_fundamental_detail_fields(
        context_snapshot=context_snapshot,
        fallback_fundamental_payload=fallback_fundamental_payload,
    )
    extracted_boards = extract_board_detail_fields(
        context_snapshot=context_snapshot,
        fallback_fundamental_payload=fallback_fundamental_payload,
    )
    details = None
    has_board_details = bool(extracted_boards.get("belong_boards")) or extracted_boards.get("sector_rankings") is not None
    if details_data or any(extracted_fundamental.values()) or has_board_details or context_snapshot is not None:
        details = ReportDetails(
            news_content=details_data.get("news_summary") or details_data.get("news_content"),
            raw_result=details_data,
            context_snapshot=context_snapshot,
            financial_report=extracted_fundamental.get("financial_report"),
            dividend_metrics=extracted_fundamental.get("dividend_metrics"),
            belong_boards=extracted_boards.get("belong_boards"),
            sector_rankings=extracted_boards.get("sector_rankings"),
        )

    return AnalysisReport(
        meta=meta,
        summary=summary,
        strategy=strategy,
        details=details
    )
