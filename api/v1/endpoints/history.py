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

from fastapi import APIRouter, HTTPException, Query, Depends

from api.deps import get_database_manager
from api.v1.schemas.history import (
    HistoryListResponse,
    HistoryItem,
    NewsIntelItem,
    NewsIntelResponse,
    AnalysisReport,
    ReportMeta,
    ReportSummary,
    ReportStrategy,
    ReportDetails,
)
from api.v1.schemas.common import ErrorResponse
from src.storage import DatabaseManager
from src.services.history_service import HistoryService

logger = logging.getLogger(__name__)

router = APIRouter()


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
                sentiment_score=item.get("sentiment_score"),
                operation_advice=item.get("operation_advice"),
                created_at=item.get("created_at")
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
        current_price = None
        change_pct = None
        context_snapshot = result.get("context_snapshot")
        if context_snapshot and isinstance(context_snapshot, dict):
            # 尝试从 enhanced_context.realtime 获取
            enhanced_context = context_snapshot.get("enhanced_context") or {}
            realtime = enhanced_context.get("realtime") or {}
            current_price = realtime.get("price")
            change_pct = realtime.get("change_pct") or realtime.get("change_60d")
            
            # 也尝试从 realtime_quote_raw 获取
            if current_price is None:
                realtime_quote_raw = context_snapshot.get("realtime_quote_raw") or {}
                current_price = realtime_quote_raw.get("price")
                change_pct = change_pct or realtime_quote_raw.get("change_pct") or realtime_quote_raw.get("pct_chg")
        
        # 构建响应模型
        meta = ReportMeta(
            id=result.get("id"),
            query_id=result.get("query_id", ""),
            stock_code=result.get("stock_code", ""),
            stock_name=result.get("stock_name"),
            report_type=result.get("report_type"),
            created_at=result.get("created_at"),
            current_price=current_price,
            change_pct=change_pct
        )
        
        summary = ReportSummary(
            analysis_summary=result.get("analysis_summary"),
            operation_advice=result.get("operation_advice"),
            trend_prediction=result.get("trend_prediction"),
            sentiment_score=result.get("sentiment_score"),
            sentiment_label=result.get("sentiment_label")
        )
        
        strategy = ReportStrategy(
            ideal_buy=result.get("ideal_buy"),
            secondary_buy=result.get("secondary_buy"),
            stop_loss=result.get("stop_loss"),
            take_profit=result.get("take_profit")
        )
        
        details = ReportDetails(
            news_content=result.get("news_content"),
            raw_result=result.get("raw_result"),
            context_snapshot=result.get("context_snapshot")
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
