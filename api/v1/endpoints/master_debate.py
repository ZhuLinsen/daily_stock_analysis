# -*- coding: utf-8 -*-
"""Master debate API endpoints."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Security
from fastapi.security import APIKeyCookie

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.master_debate import (
    MasterDebateListResponse,
    MasterDebateRecordItem,
    MasterDebateRequest,
    MasterDebateResponse,
)
from src.auth import COOKIE_NAME
from src.services.master_debate_service import MasterDebateError, MasterDebateService

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
    response_model=MasterDebateResponse,
    responses={**AUTH_RESPONSE, 400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="发起大师视角多空辩论",
)
def run_debate(request: MasterDebateRequest) -> MasterDebateResponse:
    service = MasterDebateService()
    try:
        result = service.run_debate(
            code=request.code,
            name=request.name,
            market=request.market,
            context=request.context,
            analysis_history_id=request.analysis_history_id,
            persist=request.persist,
        )
        return MasterDebateResponse(**result)
    except (ValueError, MasterDebateError) as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Run master debate failed", exc)


@router.get(
    "",
    response_model=MasterDebateListResponse,
    responses={**AUTH_RESPONSE, 500: {"model": ErrorResponse}},
    summary="查询辩论历史",
)
def list_debates(
    market: Optional[str] = Query(None),
    code: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> MasterDebateListResponse:
    service = MasterDebateService()
    try:
        items, total = service.list_records(market=market, code=code, page=page, page_size=page_size)
        return MasterDebateListResponse(
            items=[MasterDebateRecordItem(**item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception as exc:
        raise _internal_error("List master debates failed", exc)


@router.get(
    "/{record_id}",
    response_model=MasterDebateRecordItem,
    responses={**AUTH_RESPONSE, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="查询单次辩论记录",
)
def get_debate(record_id: int) -> MasterDebateRecordItem:
    service = MasterDebateService()
    try:
        return MasterDebateRecordItem(**service.get_record(record_id))
    except ValueError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal_error("Get master debate record failed", exc)
