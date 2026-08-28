# -*- coding: utf-8 -*-
"""Trade journal API endpoints."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Security
from fastapi.security import APIKeyCookie

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.trade_journals import (
    TradeJournalCreateRequest,
    TradeJournalDisciplineResponse,
    TradeJournalItem,
    TradeJournalListResponse,
    TradeJournalMutationResponse,
    TradeJournalPositionPnlResponse,
    TradeJournalReviewResponse,
    TradeJournalUpdateRequest,
)
from src.auth import COOKIE_NAME
from src.services.trade_journal_service import (
    TradeJournalNotFoundError,
    TradeJournalService,
    TradeJournalValidationError,
)

logger = logging.getLogger(__name__)

admin_session_cookie = APIKeyCookie(name=COOKIE_NAME, scheme_name="AdminSessionCookie", auto_error=False)
router = APIRouter(dependencies=[Security(admin_session_cookie)])

AUTH_RESPONSE = {
    401: {"model": ErrorResponse, "description": "未登录或管理员会话无效（ADMIN_AUTH_ENABLED=true 时）"},
}


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": "validation_error", "message": str(exc)})


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": "not_found", "message": str(exc)})


def _internal_error(message: str, exc: Exception) -> HTTPException:
    logger.error("%s: %s", message, exc, exc_info=True)
    return HTTPException(status_code=500, detail={"error": "internal_error", "message": message})


@router.post(
    "",
    response_model=TradeJournalMutationResponse,
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="记录一笔交易",
)
def create_entry(request: TradeJournalCreateRequest) -> TradeJournalMutationResponse:
    service = TradeJournalService()
    try:
        item = service.create_entry(request.model_dump(exclude_unset=True))
        return TradeJournalMutationResponse(item=TradeJournalItem(**item))
    except TradeJournalValidationError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Create trade journal entry failed", exc)


@router.get(
    "",
    response_model=TradeJournalListResponse,
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="查询交易日记列表",
)
def list_entries(
    market: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    side: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    emotion: Optional[str] = Query(None),
    trade_date_from: Optional[str] = Query(None),
    trade_date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> TradeJournalListResponse:
    service = TradeJournalService()
    try:
        items, total = service.list_entries(
            market=market,
            code=code,
            side=side,
            strategy=strategy,
            emotion=emotion,
            trade_date_from=trade_date_from,
            trade_date_to=trade_date_to,
            page=page,
            page_size=page_size,
        )
        return TradeJournalListResponse(
            items=[TradeJournalItem(**item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    except TradeJournalValidationError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("List trade journal entries failed", exc)


@router.get(
    "/review",
    response_model=TradeJournalReviewResponse,
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="交易复盘统计（胜率/纪律分/情绪）",
)
def review(
    market: Optional[str] = Query(None),
    trade_date_from: Optional[str] = Query(None),
    trade_date_to: Optional[str] = Query(None),
) -> TradeJournalReviewResponse:
    service = TradeJournalService()
    try:
        return TradeJournalReviewResponse(**service.review(
            market=market,
            trade_date_from=trade_date_from,
            trade_date_to=trade_date_to,
        ))
    except TradeJournalValidationError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Trade journal review failed", exc)


@router.get(
    "/pnl",
    response_model=TradeJournalPositionPnlResponse,
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="按 FIFO 计算某持仓已实现盈亏",
)
def position_pnl(
    market: str = Query(..., description="market: cn/hk/us/jp/kr/tw"),
    code: str = Query(..., description="stock code"),
) -> TradeJournalPositionPnlResponse:
    service = TradeJournalService()
    try:
        return TradeJournalPositionPnlResponse(**service.compute_position_pnl(market=market, code=code))
    except TradeJournalValidationError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Compute position PnL failed", exc)


@router.get(
    "/{entry_id}",
    response_model=TradeJournalItem,
    responses={**AUTH_RESPONSE, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="查询单笔交易",
)
def get_entry(entry_id: int) -> TradeJournalItem:
    service = TradeJournalService()
    try:
        return TradeJournalItem(**service.get_entry(entry_id))
    except TradeJournalNotFoundError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal_error("Get trade journal entry failed", exc)


@router.get(
    "/{entry_id}/discipline",
    response_model=TradeJournalDisciplineResponse,
    responses={**AUTH_RESPONSE, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="评估一笔交易与 AI 信号的纪律对齐",
)
def entry_discipline(entry_id: int) -> TradeJournalDisciplineResponse:
    service = TradeJournalService()
    try:
        return TradeJournalDisciplineResponse(**service.classify_entry_discipline(entry_id))
    except TradeJournalNotFoundError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal_error("Classify entry discipline failed", exc)


@router.patch(
    "/{entry_id}",
    response_model=TradeJournalMutationResponse,
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="修改一笔交易",
)
def update_entry(entry_id: int, request: TradeJournalUpdateRequest) -> TradeJournalMutationResponse:
    service = TradeJournalService()
    try:
        item = service.update_entry(entry_id, request.model_dump(exclude_unset=True))
        return TradeJournalMutationResponse(item=TradeJournalItem(**item))
    except TradeJournalNotFoundError as exc:
        raise _not_found(exc)
    except TradeJournalValidationError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Update trade journal entry failed", exc)


@router.delete(
    "/{entry_id}",
    responses={**AUTH_RESPONSE, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="删除一笔交易",
)
def delete_entry(entry_id: int) -> dict:
    service = TradeJournalService()
    try:
        service.delete_entry(entry_id)
        return {"success": True}
    except TradeJournalNotFoundError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal_error("Delete trade journal entry failed", exc)
