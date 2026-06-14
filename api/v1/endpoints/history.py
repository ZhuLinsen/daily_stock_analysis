# -*- coding: utf-8 -*-
"""
===================================
历史记录接口
===================================

职责：
1. 提供 GET /api/v1/history 历史列表查询接口
2. 提供 GET /api/v1/history/{query_id} 历史详情查询接口
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends, Body

from api.deps import get_database_manager
from api.v1.schemas.history import (
    HistoryListResponse,
    HistoryItem,
    DeleteHistoryRequest,
    DeleteHistoryResponse,
    NewsIntelItem,
    NewsIntelResponse,
    AnalysisReport,
    ReportMeta,
    ReportSummary,
    ReportStrategy,
    ReportDetails,
    MarkdownReportResponse,
    RunDiagnosticSummaryResponse,
    StockBarItem,
    StockBarResponse,
)
from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.run_flow import RunFlowSnapshot
from src.storage import DatabaseManager
from src.report_language import (
    get_sentiment_label,
    get_localized_stock_name,
    localize_operation_advice,
    localize_trend_prediction,
    normalize_report_language,
)
from src.services.history_service import HistoryService, MarkdownReportGenerationError
from src.schemas.decision_action import build_action_fields
from src.utils.data_processing import (
    normalize_model_used,
    extract_fundamental_detail_fields,
    extract_board_detail_fields,
    extract_realtime_detail_fields,
)
from src.analysis_context_pack_overview import (
    extract_analysis_context_pack_overview,
    sanitize_context_snapshot_for_api,
)
from src.market_phase_summary import extract_market_phase_summary

logger = logging.getLogger(__name__)

router = APIRouter()


def _normalize_code_for_grouping(code: str) -> str:
    """Normalize stock code for deduplication grouping.

    Delegates to data_provider.base.normalize_stock_code which handles
    SH600519, 600519.SH, HK00700, 00700.HK, BJ920748, etc.
    """
    from data_provider.base import normalize_stock_code
    return normalize_stock_code(code or "")


@router.get(
    "",
    response_model=HistoryListResponse,
    responses={
        200: {"description": "历史记录列表"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取历史分析列表",
    description="分页获取历史分析记录摘要，支持按股票代码和日期范围筛选"
)
def get_history_list(
    stock_code: Optional[str] = Query(None, description="股票代码筛选"),
    report_type: Optional[str] = Query(None, description="报告类型筛选，如 market_review"),
    start_date: Optional[str] = Query(None, description="开始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期 (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="页码（从 1 开始）"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    db_manager: DatabaseManager = Depends(get_database_manager)
) -> HistoryListResponse:
    """
    获取历史分析列表
    
    分页获取历史分析记录摘要，支持按股票代码和日期范围筛选
    
    Args:
        stock_code: 股票代码筛选
        report_type: 报告类型筛选
        start_date: 开始日期
        end_date: 结束日期
        page: 页码
        limit: 每页数量
        db_manager: 数据库管理器依赖
        
    Returns:
        HistoryListResponse: 历史记录列表
    """
    try:
        service = HistoryService(db_manager)
        
        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_history_list(
            stock_code=stock_code,
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            page=page,
            limit=limit
        )
        
        # 转换为响应模型
        items = [
            HistoryItem(
                id=item.get("id"),
                query_id=item.get("query_id", ""),
                stock_code=item.get("stock_code", ""),
                stock_name=item.get("stock_name"),
                report_type=item.get("report_type"),
                trend_prediction=item.get("trend_prediction"),
                analysis_summary=item.get("analysis_summary"),
                sentiment_score=item.get("sentiment_score"),
                operation_advice=item.get("operation_advice"),
                action=item.get("action"),
                action_label=item.get("action_label"),
                current_price=item.get("current_price"),
                change_pct=item.get("change_pct"),
                volume_ratio=item.get("volume_ratio"),
                turnover_rate=item.get("turnover_rate"),
                model_used=item.get("model_used"),
                created_at=item.get("created_at"),
                market_phase_summary=item.get("market_phase_summary"),
            )
            for item in result.get("items", [])
        ]
        
        return HistoryListResponse(
            total=result.get("total", 0),
            page=page,
            limit=limit,
            items=items
        )
        
    except Exception as e:
        logger.error(f"查询历史列表失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"查询历史列表失败: {str(e)}"
            }
        )


@router.delete(
    "/by-code/{stock_code}",
    response_model=DeleteHistoryResponse,
    responses={
        200: {"description": "删除成功"},
        404: {"description": "未找到记录", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="按股票代码删除历史分析记录",
    description="删除指定股票代码的所有分析历史记录（支持代码变体归一化匹配）",
)
def delete_history_by_code(
    stock_code: str,
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> DeleteHistoryResponse:
    try:
        candidates = HistoryService._history_code_filter_candidates(stock_code)
        records, _ = db_manager.get_analysis_history_paginated(code=candidates, limit=10000)
        record_ids = [r.id for r in records if r.id is not None]
        if not record_ids:
            return DeleteHistoryResponse(deleted=0)
        deleted = db_manager.delete_analysis_history_records(record_ids)
        return DeleteHistoryResponse(deleted=deleted)
    except Exception as e:
        logger.error(f"按股票代码删除历史记录失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"删除失败: {str(e)}"},
        )


@router.delete(
    "",
    response_model=DeleteHistoryResponse,
    responses={
        200: {"description": "删除成功"},
        400: {"description": "请求参数错误", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="删除历史分析记录",
    description="按历史记录主键 ID 批量删除分析历史"
)
def delete_history_records(
    request: DeleteHistoryRequest = Body(...),
    db_manager: DatabaseManager = Depends(get_database_manager)
) -> DeleteHistoryResponse:
    """
    按主键 ID 批量删除历史分析记录。
    """
    record_ids = sorted({record_id for record_id in request.record_ids if record_id is not None})
    if not record_ids:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_request",
                "message": "record_ids 不能为空"
            }
        )

    try:
        service = HistoryService(db_manager)
        deleted = service.delete_history_records(record_ids)
        return DeleteHistoryResponse(deleted=deleted)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除历史记录失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"删除历史记录失败: {str(e)}"
            }
        )


@router.get(
    "/stocks",
    response_model=StockBarResponse,
    responses={
        200: {"description": "不重复个股列表"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取不重复个股列表",
    description="返回历史记录中每只股票的最新一条分析摘要，不包含大盘复盘（code=MARKET）。",
)
def get_stock_bar(
    start_date: Optional[str] = Query(None, description="开始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期 (YYYY-MM-DD)"),
    limit: int = Query(200, ge=1, le=500, description="最大返回数量"),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> StockBarResponse:
    try:
        from datetime import date as date_type
        from src.utils.data_processing import parse_json_field

        start = date_type.fromisoformat(start_date) if start_date else None
        end = date_type.fromisoformat(end_date) if end_date else None

        # Fetch more than limit to compensate for normalization dedup shrinkage
        # (e.g. 002460 + 002460.SZ both initially counted but merged to one)
        fetch_limit = min(limit * 3, 500)
        records = db_manager.get_distinct_stocks_from_history(
            start_date=start,
            end_date=end,
            limit=fetch_limit,
        )

        # Deduplicate by normalized code, keeping the record with highest id
        seen: dict = {}
        for record in records:
            norm_code = _normalize_code_for_grouping(record.code or "")
            if norm_code not in seen or record.id > seen[norm_code].id:
                seen[norm_code] = record

        items = []
        for norm_code in seen:
            record = seen[norm_code]
            raw_result = parse_json_field(getattr(record, "raw_result", None))
            model_used = raw_result.get("model_used") if isinstance(raw_result, dict) else None
            action_fields = build_action_fields(
                operation_advice=(
                    raw_result.get("operation_advice") if isinstance(raw_result, dict) else None
                )
                or record.operation_advice,
                explicit_action=raw_result.get("action") if isinstance(raw_result, dict) else None,
                report_type=record.report_type,
                report_language=normalize_report_language(
                    raw_result.get("report_language") if isinstance(raw_result, dict) else None
                ),
            )

            analysis_count = db_manager.get_analysis_history_paginated(
                code=HistoryService._history_code_filter_candidates(
                    record.code or "",
                ),
                limit=1,
            )[1]
            items.append(
                StockBarItem(
                    id=record.id,
                    stock_code=record.code or "",
                    stock_name=record.name,
                    report_type=record.report_type,
                    sentiment_score=record.sentiment_score,
                    operation_advice=record.operation_advice,
                    action=action_fields["action"],
                    action_label=action_fields["action_label"],
                    analysis_count=analysis_count,
                    last_analysis_time=(
                        record.created_at.isoformat() if record.created_at else None
                    ),
                    model_used=normalize_model_used(model_used),
                    market_phase_summary=extract_market_phase_summary(getattr(record, "context_snapshot", None)),
                )
            )

        items = items[:limit]
        return StockBarResponse(total=len(items), items=items)

    except Exception as e:
        logger.error(f"查询个股栏失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"查询个股栏失败: {str(e)}",
            },
        )


@router.get(
    "/{record_id}",
    response_model=AnalysisReport,
    responses={
        200: {"description": "报告详情"},
        404: {"description": "报告不存在", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取历史报告详情",
    description="根据分析历史记录 ID 或 query_id 获取完整的历史分析报告"
)
def get_history_detail(
    record_id: str,
    db_manager: DatabaseManager = Depends(get_database_manager)
) -> AnalysisReport:
    """
    获取历史报告详情
    
    根据分析历史记录主键 ID 或 query_id 获取完整的历史分析报告。
    优先尝试按主键 ID（整数）查询，若参数不是合法整数则按 query_id 查询。
    
    Args:
        record_id: 分析历史记录主键 ID（整数）或 query_id（字符串）
        db_manager: 数据库管理器依赖
        
    Returns:
        AnalysisReport: 完整分析报告
        
    Raises:
        HTTPException: 404 - 报告不存在
    """
    try:
        service = HistoryService(db_manager)
        
        # Try integer ID first, fall back to query_id string lookup
        result = service.resolve_and_get_detail(record_id)
        
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"未找到 id/query_id={record_id} 的分析记录"
                }
            )
        
        # 从 context_snapshot 中提取价格信息
        # 注意：使用 `is None` 而非 `or`，避免把 0.0（平盘）误判为缺失值；
        # 同时不混用 `change_60d`（60 日累计涨跌幅）作为日内 change_pct 的兜底。
        context_snapshot = result.get("context_snapshot")
        analysis_context_pack_overview = extract_analysis_context_pack_overview(context_snapshot)
        market_phase_summary = extract_market_phase_summary(context_snapshot)
        api_context_snapshot = sanitize_context_snapshot_for_api(context_snapshot)
        realtime_fields = extract_realtime_detail_fields(context_snapshot)
        current_price = realtime_fields.get("current_price")
        change_pct = realtime_fields.get("change_pct")
        
        raw_result = result.get("raw_result")
        if not isinstance(raw_result, dict):
            raw_result = {}
        report_language = normalize_report_language(
            result.get("report_language")
            or raw_result.get("report_language")
            or (
                context_snapshot.get("report_language")
                if isinstance(context_snapshot, dict)
                else None
            )
        )
        stock_name = get_localized_stock_name(
            result.get("stock_name"),
            result.get("stock_code", ""),
            report_language,
        )

        # 构建响应模型
        meta = ReportMeta(
            id=result.get("id"),
            query_id=result.get("query_id", ""),
            stock_code=result.get("stock_code", ""),
            stock_name=stock_name,
            report_type=result.get("report_type"),
            report_language=report_language,
            created_at=result.get("created_at"),
            current_price=current_price,
            change_pct=change_pct,
            model_used=normalize_model_used(result.get("model_used")),
            market_phase_summary=market_phase_summary,
        )
        
        summary = ReportSummary(
            analysis_summary=result.get("analysis_summary"),
            operation_advice=localize_operation_advice(
                result.get("operation_advice"),
                report_language,
            ),
            action=result.get("action"),
            action_label=result.get("action_label"),
            trend_prediction=localize_trend_prediction(
                result.get("trend_prediction"),
                report_language,
            ),
            sentiment_score=result.get("sentiment_score"),
            sentiment_label=(
                get_sentiment_label(result.get("sentiment_score"), report_language)
                if result.get("sentiment_score") is not None
                else result.get("sentiment_label")
            )
        )
        
        strategy = ReportStrategy(
            ideal_buy=result.get("ideal_buy"),
            secondary_buy=result.get("secondary_buy"),
            stop_loss=result.get("stop_loss"),
            take_profit=result.get("take_profit")
        )
        
        fallback_fundamental = db_manager.get_latest_fundamental_snapshot(
            query_id=result.get("query_id", ""),
            code=result.get("stock_code", ""),
        )
        extracted_fundamental = extract_fundamental_detail_fields(
            context_snapshot=result.get("context_snapshot"),
            fallback_fundamental_payload=fallback_fundamental,
        )
        extracted_boards = extract_board_detail_fields(
            context_snapshot=result.get("context_snapshot"),
            fallback_fundamental_payload=fallback_fundamental,
        )

        details = ReportDetails(
            news_content=result.get("news_content"),
            raw_result=result.get("raw_result"),
            context_snapshot=api_context_snapshot,
            analysis_context_pack_overview=analysis_context_pack_overview,
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询历史详情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"查询历史详情失败: {str(e)}"
            }
        )


@router.get(
    "/{record_id}/diagnostics",
    response_model=RunDiagnosticSummaryResponse,
    responses={
        200: {"description": "运行诊断摘要"},
        404: {"description": "报告不存在", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取历史报告运行诊断摘要",
    description="根据分析历史记录 ID 或 query_id 获取用户可读诊断摘要和脱敏复制文本。",
)
def get_history_diagnostics(
    record_id: str,
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> RunDiagnosticSummaryResponse:
    """
    获取历史报告运行诊断摘要。
    """
    try:
        service = HistoryService(db_manager)
        summary = service.resolve_and_get_diagnostics(record_id)
        if summary is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"未找到 id/query_id={record_id} 的分析记录",
                },
            )
        return RunDiagnosticSummaryResponse.model_validate(summary)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询运行诊断摘要失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"查询运行诊断摘要失败: {str(e)}",
            },
        )


@router.get(
    "/{record_id}/flow",
    response_model=RunFlowSnapshot,
    responses={
        200: {"description": "运行流快照"},
        404: {"description": "报告不存在", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取历史报告运行流",
    description="根据分析历史记录 ID 或 query_id 获取数据流/信息流快照。",
)
def get_history_run_flow(
    record_id: str,
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> RunFlowSnapshot:
    """
    获取历史报告运行流。
    """
    try:
        service = HistoryService(db_manager)
        snapshot = service.resolve_and_get_run_flow(record_id)
        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"未找到 id/query_id={record_id} 的分析记录",
                },
            )
        return snapshot
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询运行流快照失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"查询运行流快照失败: {str(e)}",
            },
        )


@router.get(
    "/{record_id}/news",
    response_model=NewsIntelResponse,
    responses={
        200: {"description": "新闻情报列表"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取历史报告关联新闻",
    description="根据分析历史记录 ID 获取关联的新闻情报列表（为空也返回 200）"
)
def get_history_news(
    record_id: str,
    limit: int = Query(20, ge=1, le=100, description="返回数量限制"),
    db_manager: DatabaseManager = Depends(get_database_manager)
) -> NewsIntelResponse:
    """
    获取历史报告关联新闻

    根据分析历史记录 ID 或 query_id 获取关联的新闻情报列表。
    在内部完成 record_id → query_id 的解析。

    Args:
        record_id: 分析历史记录主键 ID（整数）或 query_id（字符串）
        limit: 返回数量限制
        db_manager: 数据库管理器依赖

    Returns:
        NewsIntelResponse: 新闻情报列表
    """
    try:
        service = HistoryService(db_manager)
        items = service.resolve_and_get_news(record_id=record_id, limit=limit)

        response_items = [
            NewsIntelItem(
                title=item.get("title", ""),
                snippet=item.get("snippet"),
                url=item.get("url", "")
            )
            for item in items
        ]

        return NewsIntelResponse(
            total=len(response_items),
            items=response_items
        )

    except Exception as e:
        logger.error(f"查询新闻情报失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"查询新闻情报失败: {str(e)}"
            }
        )


@router.get(
    "/{record_id}/markdown",
    response_model=MarkdownReportResponse,
    responses={
        200: {"description": "Markdown 格式报告"},
        404: {"description": "报告不存在", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取历史报告 Markdown 格式",
    description="根据分析历史记录 ID 获取 Markdown 格式的完整分析报告"
)
def get_history_markdown(
    record_id: str,
    db_manager: DatabaseManager = Depends(get_database_manager)
) -> MarkdownReportResponse:
    """
    获取历史报告的 Markdown 格式内容

    根据分析历史记录 ID 或 query_id 生成与推送通知格式一致的 Markdown 报告。

    Args:
        record_id: 分析历史记录主键 ID（整数）或 query_id（字符串）
        db_manager: 数据库管理器依赖

    Returns:
        MarkdownReportResponse: Markdown 格式的完整报告

    Raises:
        HTTPException: 404 - 报告不存在
        HTTPException: 500 - 报告生成失败（服务器内部错误）
    """
    service = HistoryService(db_manager)

    try:
        markdown_content = service.get_markdown_report(record_id)
    except MarkdownReportGenerationError as e:
        logger.error(f"Markdown report generation failed for {record_id}: {e.message}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "generation_failed",
                "message": f"生成 Markdown 报告失败: {e.message}"
            }
        )
    except Exception as e:
        logger.error(f"获取 Markdown 报告失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取 Markdown 报告失败: {str(e)}"
            }
        )

    if markdown_content is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": f"未找到 id/query_id={record_id} 的分析记录"
            }
        )

    return MarkdownReportResponse(content=markdown_content)
