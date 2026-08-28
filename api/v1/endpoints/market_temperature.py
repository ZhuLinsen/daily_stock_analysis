# -*- coding: utf-8 -*-
"""Market temperature API endpoints."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Security
from fastapi.security import APIKeyCookie

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.market_temperature import (
    MarketDashboardResponse,
    MarketTemperatureComputeRequest,
    MarketTemperatureComputeResponse,
    MarketTemperatureListResponse,
    MarketTemperatureSnapshotItem,
)
from src.services.market_dashboard_service import MarketDashboardService
from src.auth import COOKIE_NAME
from src.services.market_temperature_service import MarketTemperatureService

logger = logging.getLogger(__name__)

admin_session_cookie = APIKeyCookie(name=COOKIE_NAME, scheme_name="AdminSessionCookie", auto_error=False)
router = APIRouter(dependencies=[Security(admin_session_cookie)])

AUTH_RESPONSE = {
    401: {"model": ErrorResponse, "description": "未登录或管理员会话无效（ADMIN_AUTH_ENABLED=true 时）"},
}


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": "validation_error", "message": str(exc)})


def _internal_error(message: str, exc: Exception) -> HTTPException:
    logger.error("%s: %s", message, exc, exc_info=True)
    return HTTPException(status_code=500, detail={"error": "internal_error", "message": message})


@router.post(
    "",
    response_model=MarketTemperatureComputeResponse,
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="计算并保存市场温度（恐惧贪婪指数）",
)
def compute_temperature(request: MarketTemperatureComputeRequest) -> MarketTemperatureComputeResponse:
    service = MarketTemperatureService()
    try:
        snapshot = request.model_dump(exclude_unset=True)
        market = snapshot.pop("market")
        trade_date = snapshot.pop("trade_date", None)
        result = service.snapshot(market, snapshot, trade_date=trade_date)
        return MarketTemperatureComputeResponse(**result)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Compute market temperature failed", exc)


@router.get(
    "",
    response_model=MarketTemperatureListResponse,
    responses={**AUTH_RESPONSE, 500: {"model": ErrorResponse}},
    summary="查询市场温度历史",
)
def list_temperature(
    market: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> MarketTemperatureListResponse:
    service = MarketTemperatureService()
    try:
        items, total = service.history(market=market, page=page, page_size=page_size)
        return MarketTemperatureListResponse(
            items=[MarketTemperatureSnapshotItem(**item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        raise _internal_error("List market temperature failed", exc)


@router.get(
    "/latest",
    response_model=Optional[MarketTemperatureSnapshotItem],
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="查询某市场最新温度（无快照时返回 null）",
)
def latest_temperature(market: str = Query(..., description="market: cn/hk/us/jp/kr/tw")) -> Optional[MarketTemperatureSnapshotItem]:
    service = MarketTemperatureService()
    try:
        item = service.latest(market)
        return MarketTemperatureSnapshotItem(**item) if item else None
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Get latest market temperature failed", exc)


@router.post(
    "/compute",
    response_model=MarketTemperatureComputeResponse,
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="从实时数据源抓取全市场宽度并计算温度（当前仅支持 A 股，结果落库）",
)
def compute_from_provider(
    market: str = Query(..., description="market: 目前仅支持 cn"),
) -> MarketTemperatureComputeResponse:
    service = MarketTemperatureService()
    try:
        result = service.compute_from_provider(market)
        return MarketTemperatureComputeResponse(**result)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Compute market temperature from provider failed", exc)


@router.post(
    "/dashboard",
    response_model=MarketDashboardResponse,
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="构建大盘仪表盘：温度+指数+宽度+热门板块+资金流+候选观察池（仅 A 股，可能耗时数十秒）",
)
def market_dashboard(market: str = Query(..., description="目前仅支持 cn")) -> MarketDashboardResponse:
    service = MarketDashboardService()
    try:
        result = service.dashboard(market)
        return MarketDashboardResponse(**result)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Build market dashboard failed", exc)


@router.post(
    "/from-database",
    response_model=MarketTemperatureComputeResponse,
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="基于本地自选股日线兜底计算市场宽度温度（结果落库）",
)
def from_database(
    market: str = Query(..., description="market: cn/hk/us/jp/kr/tw"),
    index_pct_chg: Optional[float] = Query(None),
) -> MarketTemperatureComputeResponse:
    service = MarketTemperatureService()
    try:
        result = service.compute_from_database(market, index_pct_chg=index_pct_chg)
        result.setdefault("market", market)
        result.setdefault("trade_date", result.get("source_trade_date", ""))
        return MarketTemperatureComputeResponse(**result)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Compute market temperature from database failed", exc)
