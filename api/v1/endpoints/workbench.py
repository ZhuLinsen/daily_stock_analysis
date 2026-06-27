# -*- coding: utf-8 -*-
"""AI 股票复盘工作台 API."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

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

logger = logging.getLogger(__name__)

router = APIRouter()


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
