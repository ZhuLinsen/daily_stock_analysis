# -*- coding: utf-8 -*-
"""AI 股票复盘工作台 API."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.v1.errors import api_error
from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.workbench import (
    WorkbenchDailyReviewResponse,
    WorkbenchDashboardResponse,
    WorkbenchMarkdownResponse,
    WorkbenchStockDetailResponse,
    WorkbenchWatchlistResponse,
)
from src.services.workbench_service import WorkbenchService
from data_provider.provider_router import get_provider_router

logger = logging.getLogger(__name__)

router = APIRouter()


class MiaoxiangQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="自然语言查询")
    timeout_seconds: int = Field(30, ge=5, le=60, description="查询超时秒数")


class MiaoxiangZixuanRequest(BaseModel):
    command: str = Field("query", min_length=1, max_length=120, description="query/add/delete 或自然语言指令")
    stock: Optional[str] = Field(None, max_length=80, description="可选股票名称或代码")
    timeout_seconds: int = Field(30, ge=5, le=60, description="查询超时秒数")


def _service() -> WorkbenchService:
    return WorkbenchService()


def _internal_error(message: str, exc: Exception) -> HTTPException:
    logger.error("%s: %s", message, exc, exc_info=True)
    return api_error(500, "internal_error", f"{message}: {str(exc)}")


@router.get(
    "/dashboard",
    response_model=WorkbenchDashboardResponse,
    responses={500: {"model": ErrorResponse}},
    summary="AI 股票复盘工作台 - 市场总览",
)
def get_dashboard() -> WorkbenchDashboardResponse:
    try:
        return WorkbenchDashboardResponse(**_service().get_dashboard())
    except Exception as exc:
        raise _internal_error("获取市场总览失败", exc)


@router.get(
    "/watchlist",
    response_model=WorkbenchWatchlistResponse,
    responses={500: {"model": ErrorResponse}},
    summary="AI 股票复盘工作台 - 自选股",
)
def get_watchlist() -> WorkbenchWatchlistResponse:
    try:
        return WorkbenchWatchlistResponse(**_service().get_watchlist())
    except Exception as exc:
        raise _internal_error("获取自选股工作台失败", exc)


@router.get(
    "/stocks/{symbol}",
    response_model=WorkbenchStockDetailResponse,
    responses={500: {"model": ErrorResponse}},
    summary="AI 股票复盘工作台 - 个股详情",
)
def get_stock_detail(symbol: str) -> WorkbenchStockDetailResponse:
    try:
        return WorkbenchStockDetailResponse(**_service().get_stock_detail(symbol))
    except Exception as exc:
        raise _internal_error(f"获取个股详情失败: {symbol}", exc)


@router.get(
    "/daily-review",
    response_model=WorkbenchDailyReviewResponse,
    responses={500: {"model": ErrorResponse}},
    summary="AI 股票复盘工作台 - 每日复盘",
)
def get_daily_review() -> WorkbenchDailyReviewResponse:
    try:
        return WorkbenchDailyReviewResponse(**_service().get_daily_review())
    except Exception as exc:
        raise _internal_error("获取每日复盘失败", exc)


@router.get(
    "/daily-review/markdown",
    response_model=WorkbenchMarkdownResponse,
    responses={500: {"model": ErrorResponse}},
    summary="导出每日复盘 Markdown",
)
def export_daily_review_markdown() -> WorkbenchMarkdownResponse:
    try:
        review = _service().get_daily_review()
        today = datetime.now().strftime("%Y-%m-%d")
        return WorkbenchMarkdownResponse(
            markdown=str(review.get("markdown") or ""),
            filename=f"daily-review-{today}.md",
            source=str(review.get("source") or "workbench"),
            stale=bool(review.get("stale")),
            error=review.get("error"),
            meta={"date": today, "disclaimer": review.get("disclaimer")},
        )
    except Exception as exc:
        raise _internal_error("导出每日复盘 Markdown 失败", exc)


@router.get(
    "/providers/eastmoney/quote/{symbol}",
    responses={500: {"model": ErrorResponse}},
    summary="东方财富 Provider - 实时行情",
)
def eastmoney_quote(symbol: str) -> dict:
    try:
        return get_provider_router().get_realtime_quote(symbol)
    except Exception as exc:
        raise _internal_error(f"东方财富实时行情失败: {symbol}", exc)


@router.get(
    "/providers/eastmoney/kline/{symbol}",
    responses={500: {"model": ErrorResponse}},
    summary="东方财富 Provider - 日 K 与技术指标",
)
def eastmoney_kline(symbol: str, period: str = "daily", allow_remote: bool = True) -> dict:
    try:
        return get_provider_router().get_daily_kline(symbol, period=period, allow_remote=allow_remote)
    except Exception as exc:
        raise _internal_error(f"东方财富K线失败: {symbol}", exc)


@router.get(
    "/providers/eastmoney/money-flow/{symbol}",
    responses={500: {"model": ErrorResponse}},
    summary="东方财富 Provider - 资金流",
)
def eastmoney_money_flow(symbol: str, allow_remote: bool = True) -> dict:
    try:
        return get_provider_router().get_money_flow(symbol, allow_remote=allow_remote)
    except Exception as exc:
        raise _internal_error(f"东方财富资金流失败: {symbol}", exc)


@router.get(
    "/providers/eastmoney/lhb/{symbol}",
    responses={500: {"model": ErrorResponse}},
    summary="东方财富 Provider - 龙虎榜",
)
def eastmoney_lhb(symbol: str) -> dict:
    try:
        return get_provider_router().get_lhb(symbol)
    except Exception as exc:
        raise _internal_error(f"东方财富龙虎榜失败: {symbol}", exc)


@router.get(
    "/providers/eastmoney/limit-up-pool",
    responses={500: {"model": ErrorResponse}},
    summary="东方财富 Provider - 涨停池",
)
def eastmoney_limit_up_pool() -> dict:
    try:
        return get_provider_router().get_limit_up_pool()
    except Exception as exc:
        raise _internal_error("东方财富涨停池失败", exc)


@router.get(
    "/providers/eastmoney/news/{symbol}",
    responses={500: {"model": ErrorResponse}},
    summary="东方财富 Provider - 个股新闻",
)
def eastmoney_news(symbol: str) -> dict:
    try:
        return get_provider_router().get_stock_news(symbol)
    except Exception as exc:
        raise _internal_error(f"东方财富新闻失败: {symbol}", exc)


@router.get(
    "/providers/ths/snapshot/{symbol}",
    responses={500: {"model": ErrorResponse}},
    summary="同花顺 Fuyao Provider - 个股快照",
)
def ths_snapshot(symbol: str) -> dict:
    try:
        return get_provider_router().get_ths_stock_snapshot(symbol)
    except Exception as exc:
        raise _internal_error(f"同花顺Fuyao快照失败: {symbol}", exc)


@router.get(
    "/providers/ths/kline/{symbol}",
    responses={500: {"model": ErrorResponse}},
    summary="同花顺 Fuyao Provider - 日 K 与技术指标",
)
def ths_kline(symbol: str) -> dict:
    try:
        return get_provider_router().get_ths_stock_daily_kline(symbol)
    except Exception as exc:
        raise _internal_error(f"同花顺Fuyao K线失败: {symbol}", exc)


@router.get(
    "/providers/ths/industry-boards",
    responses={500: {"model": ErrorResponse}},
    summary="同花顺 Provider - 行业板块",
)
def ths_industry_boards() -> dict:
    try:
        return get_provider_router().get_industry_boards()
    except Exception as exc:
        raise _internal_error("同花顺行业板块失败", exc)


@router.get(
    "/providers/ths/concept-boards",
    responses={500: {"model": ErrorResponse}},
    summary="同花顺 Provider - 概念板块",
)
def ths_concept_boards() -> dict:
    try:
        return get_provider_router().get_concept_boards()
    except Exception as exc:
        raise _internal_error("同花顺概念板块失败", exc)


@router.get(
    "/providers/ths/industry-constituents/{board_name}",
    responses={500: {"model": ErrorResponse}},
    summary="同花顺 Provider - 行业成分股",
)
def ths_industry_constituents(board_name: str) -> dict:
    try:
        return get_provider_router().get_industry_constituents(board_name)
    except Exception as exc:
        raise _internal_error(f"同花顺行业成分股失败: {board_name}", exc)


@router.get(
    "/providers/ths/concept-constituents/{concept_name}",
    responses={500: {"model": ErrorResponse}},
    summary="同花顺 Provider - 概念成分股",
)
def ths_concept_constituents(concept_name: str) -> dict:
    try:
        return get_provider_router().get_concept_constituents(concept_name)
    except Exception as exc:
        raise _internal_error(f"同花顺概念成分股失败: {concept_name}", exc)


@router.get(
    "/providers/ths/themes/{symbol}",
    responses={500: {"model": ErrorResponse}},
    summary="同花顺 Provider - 个股题材推断",
)
def ths_themes(symbol: str, allow_remote: bool = False) -> dict:
    try:
        return get_provider_router().infer_stock_themes(symbol, allow_remote=allow_remote)
    except Exception as exc:
        raise _internal_error(f"同花顺题材推断失败: {symbol}", exc)


@router.post(
    "/providers/miaoxiang/data-query",
    responses={500: {"model": ErrorResponse}},
    summary="东方财富妙想 Skill - 金融数据查询",
)
def miaoxiang_data_query(request: MiaoxiangQueryRequest) -> dict:
    try:
        from src.agent.tools.mx_tools import _handle_mx_data_query

        return _handle_mx_data_query(request.query, timeout_seconds=request.timeout_seconds)
    except Exception as exc:
        raise _internal_error("妙想金融数据查询失败", exc)


@router.post(
    "/providers/miaoxiang/search-query",
    responses={500: {"model": ErrorResponse}},
    summary="东方财富妙想 Skill - 资讯搜索",
)
def miaoxiang_search_query(request: MiaoxiangQueryRequest) -> dict:
    try:
        from src.agent.tools.mx_tools import _handle_mx_search_query

        return _handle_mx_search_query(request.query, timeout_seconds=request.timeout_seconds)
    except Exception as exc:
        raise _internal_error("妙想资讯搜索失败", exc)


@router.post(
    "/providers/miaoxiang/xuangu-query",
    responses={500: {"model": ErrorResponse}},
    summary="东方财富妙想 Skill - 智能选股",
)
def miaoxiang_xuangu_query(request: MiaoxiangQueryRequest) -> dict:
    try:
        from src.agent.tools.mx_tools import _handle_mx_xuangu_query

        return _handle_mx_xuangu_query(request.query, timeout_seconds=request.timeout_seconds)
    except Exception as exc:
        raise _internal_error("妙想智能选股失败", exc)


@router.post(
    "/providers/miaoxiang/zixuan-query",
    responses={500: {"model": ErrorResponse}},
    summary="东方财富妙想 Skill - 自选股查询/管理",
)
def miaoxiang_zixuan_query(request: MiaoxiangZixuanRequest) -> dict:
    try:
        from src.agent.tools.mx_tools import _handle_mx_zixuan_query

        return _handle_mx_zixuan_query(request.command, stock=request.stock, timeout_seconds=request.timeout_seconds)
    except Exception as exc:
        raise _internal_error("妙想自选股查询失败", exc)
