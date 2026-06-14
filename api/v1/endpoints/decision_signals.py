# -*- coding: utf-8 -*-
"""DecisionSignal API endpoints."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Security
from fastapi.security import APIKeyCookie

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.decision_signals import (
    DecisionSignalCreateRequest,
    DecisionSignalItem,
    DecisionSignalListResponse,
    DecisionSignalMutationResponse,
    DecisionSignalStatusUpdateRequest,
)
from src.auth import COOKIE_NAME
from src.services.decision_signal_service import (
    DecisionSignalNotFoundError,
    DecisionSignalService,
    DecisionSignalStorageError,
)


logger = logging.getLogger(__name__)

admin_session_cookie = APIKeyCookie(
    name=COOKIE_NAME,
    scheme_name="AdminSessionCookie",
    auto_error=False,
)
router = APIRouter(dependencies=[Security(admin_session_cookie)])

AUTH_RESPONSE = {
    401: {
        "model": ErrorResponse,
        "description": "未登录或管理员会话无效（ADMIN_AUTH_ENABLED=true 时）",
    },
}


def _bad_request(exc: Exception, *, error: str = "validation_error") -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"error": error, "message": str(exc)},
    )


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error": "not_found", "message": str(exc)},
    )


def _internal_error(message: str, exc: Exception) -> HTTPException:
    logger.error("%s: %s", message, exc, exc_info=True)
    return HTTPException(
        status_code=500,
        detail={"error": "internal_error", "message": message},
    )


@router.post(
    "",
    response_model=DecisionSignalMutationResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "请求字段非法"},
        422: {"model": ErrorResponse, "description": "请求体或路径参数校验失败"},
        500: {"model": ErrorResponse, "description": "创建失败"},
    },
    summary="创建或去重决策信号",
    description=(
        "显式写入 DecisionSignal。命中同源去重键时返回已有记录和 created=false；"
        "若已有记录为 expired 且新请求为 active 并携带未来 expires_at，则原地刷新该记录；"
        "P1 不保证并发绝对幂等。"
    ),
    operation_id="createDecisionSignal",
)
def create_signal(request: DecisionSignalCreateRequest) -> DecisionSignalMutationResponse:
    service = DecisionSignalService()
    try:
        payload = request.model_dump()
        return DecisionSignalMutationResponse(**service.create_signal(payload))
    except DecisionSignalStorageError as exc:
        raise _internal_error("Create decision signal failed", exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Create decision signal failed", exc)


@router.get(
    "",
    response_model=DecisionSignalListResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "查询参数非法"},
        422: {"model": ErrorResponse, "description": "查询参数校验失败"},
        500: {"model": ErrorResponse, "description": "查询失败"},
    },
    summary="查询决策信号列表",
    description=(
        "分页查询 DecisionSignal；读取前会懒过期已到 expires_at 的 active 信号。"
        "holding_only=true 只读取 active 账户的 portfolio_positions 缓存持仓，不触发 portfolio snapshot replay。"
    ),
    operation_id="listDecisionSignals",
)
def list_signals(
    market: Optional[str] = Query(None, description="Optional market filter: cn/hk/us"),
    stock_code: Optional[str] = Query(None, description="Optional stock code filter"),
    action: Optional[str] = Query(None, description="Optional decision action filter"),
    market_phase: Optional[str] = Query(None, description="Optional market phase filter"),
    source_type: Optional[str] = Query(None, description="Optional source type filter"),
    source_report_id: Optional[int] = Query(None, description="Optional source report id filter"),
    trace_id: Optional[str] = Query(None, description="Optional trace id filter"),
    trigger_source: Optional[str] = Query(None, description="Optional trigger source filter"),
    status: Optional[str] = Query(None, description="Optional status filter"),
    created_from: Optional[str] = Query(None, description="Inclusive created_at lower bound"),
    created_to: Optional[str] = Query(None, description="Inclusive created_at upper bound"),
    expires_from: Optional[str] = Query(None, description="Inclusive expires_at lower bound"),
    expires_to: Optional[str] = Query(None, description="Inclusive expires_at upper bound"),
    holding_only: bool = Query(False, description="Filter to active cached portfolio holdings only"),
    account_id: Optional[int] = Query(
        None,
        description="Optional active portfolio account id for holding_only",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> DecisionSignalListResponse:
    service = DecisionSignalService()
    try:
        return DecisionSignalListResponse(
            **service.list_signals(
                market=market,
                stock_code=stock_code,
                action=action,
                market_phase=market_phase,
                source_type=source_type,
                source_report_id=source_report_id,
                trace_id=trace_id,
                trigger_source=trigger_source,
                status=status,
                created_from=created_from,
                created_to=created_to,
                expires_from=expires_from,
                expires_to=expires_to,
                holding_only=holding_only,
                account_id=account_id,
                page=page,
                page_size=page_size,
            )
        )
    except DecisionSignalStorageError as exc:
        raise _internal_error("List decision signals failed", exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("List decision signals failed", exc)


@router.get(
    "/latest/{stock_code}",
    response_model=DecisionSignalListResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "请求参数非法"},
        422: {"model": ErrorResponse, "description": "路径或查询参数校验失败"},
        500: {"model": ErrorResponse, "description": "查询失败"},
    },
    summary="查询股票最新 active 决策信号",
    description="返回指定股票最新 active 信号列表；读取前会执行懒过期。",
    operation_id="getLatestDecisionSignals",
)
def get_latest_active(
    stock_code: str,
    market: Optional[str] = Query(None, description="Optional market filter: cn/hk/us"),
    limit: int = Query(1, ge=1, le=100),
) -> DecisionSignalListResponse:
    service = DecisionSignalService()
    try:
        return DecisionSignalListResponse(
            **service.get_latest_active(
                stock_code=stock_code,
                market=market,
                limit=limit,
            )
        )
    except DecisionSignalStorageError as exc:
        raise _internal_error("Get latest decision signals failed", exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Get latest decision signals failed", exc)


@router.get(
    "/{signal_id}",
    response_model=DecisionSignalItem,
    responses={
        **AUTH_RESPONSE,
        404: {"model": ErrorResponse, "description": "信号不存在"},
        422: {"model": ErrorResponse, "description": "路径参数校验失败"},
        500: {"model": ErrorResponse, "description": "查询失败"},
    },
    summary="查询单条决策信号",
    description="按 ID 查询单条 DecisionSignal；读取前会执行懒过期。",
    operation_id="getDecisionSignal",
)
def get_signal(signal_id: int) -> DecisionSignalItem:
    service = DecisionSignalService()
    try:
        return DecisionSignalItem(**service.get_signal(signal_id))
    except DecisionSignalNotFoundError as exc:
        raise _not_found(exc)
    except DecisionSignalStorageError as exc:
        raise _internal_error("Get decision signal failed", exc)
    except Exception as exc:
        raise _internal_error("Get decision signal failed", exc)


@router.patch(
    "/{signal_id}/status",
    response_model=DecisionSignalItem,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "状态非法"},
        404: {"model": ErrorResponse, "description": "信号不存在"},
        422: {"model": ErrorResponse, "description": "请求体或路径参数校验失败"},
        500: {"model": ErrorResponse, "description": "更新失败"},
    },
    summary="更新决策信号状态",
    description="只更新合法状态和可选 metadata；传入 metadata 时按整包替换保存，P1 不实现复杂状态机。",
    operation_id="updateDecisionSignalStatus",
)
def update_status(signal_id: int, request: DecisionSignalStatusUpdateRequest) -> DecisionSignalItem:
    service = DecisionSignalService()
    try:
        return DecisionSignalItem(
            **service.update_status(
                signal_id,
                status=request.status,
                metadata=request.metadata,
                replace_metadata="metadata" in request.model_fields_set,
            )
        )
    except DecisionSignalNotFoundError as exc:
        raise _not_found(exc)
    except DecisionSignalStorageError as exc:
        raise _internal_error("Update decision signal status failed", exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Update decision signal status failed", exc)
