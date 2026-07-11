# -*- coding: utf-8 -*-
"""DecisionSignal API endpoints."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Security
from fastapi.security import APIKeyCookie

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.decision_signals import (
    DecisionSignalCreateRequest,
    DecisionSignalFeedbackItem,
    DecisionSignalFeedbackRequest,
    DecisionSignalItem,
    DecisionSignalListResponse,
    DecisionSignalMutationResponse,
    DecisionSignalOutcomeListResponse,
    DecisionSignalOutcomeRunRequest,
    DecisionSignalOutcomeRunResponse,
    DecisionSignalOutcomeStatsResponse,
    DecisionSignalReassessRequest,
    DecisionSignalReassessResponse,
    DecisionSignalStatusUpdateRequest,
)
from src.auth import COOKIE_NAME
from src.services.decision_signal_service import (
    DecisionSignalNotFoundError,
    DecisionSignalService,
    DecisionSignalStorageError,
)
from src.services.decision_signal_outcome_service import DecisionSignalOutcomeService
from src.services.decision_signal_reassess_service import (
    DecisionSignalReassessService,
    DecisionSignalReassessUnsupportedOperationError,
    DecisionSignalSourceReportNotFoundError,
    DecisionSignalUnsupportedReportSnapshotError,
    DecisionSignalUnsupportedReportTypeError,
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


def _error(status_code: int, exc: Exception, *, error: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": error, "message": str(exc)},
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
        "显式写入 DecisionSignal。未传 horizon/expires_at 时由服务补默认生命周期；"
        "命中同源去重键或窄 relaxed 去重时返回已有记录和 created=false；"
        "active 新建或 expired 续期会失效同股旧 active 相反信号，"
        "active duplicate retry 也会重跑该修复；普通旧 duplicate/replay 不作为新的激活事件；"
        "不保证并发绝对幂等。"
    ),
    operation_id="createDecisionSignal",
)
def create_signal(request: DecisionSignalCreateRequest) -> DecisionSignalMutationResponse:
    service = DecisionSignalService()
    try:
        payload = request.model_dump(exclude_unset=True)
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
        "当 source_type=analysis 且只传 source_report_id 查询时，若无命中信号会尝试基于该历史报告一次性懒回填 "
        "（仅首次命中列表场景，且该精确查询会触发历史决策信号回填写入，属于 read-with-write 行为；"
        "不影响其他分页列表筛选参数场景）。"
        "holding_only=true 只读取 active 账户的 portfolio_positions 缓存持仓，不触发 portfolio snapshot replay。"
    ),
    operation_id="listDecisionSignals",
)
def list_signals(
    market: Optional[str] = Query(None, description="Optional market filter: cn/hk/us/jp/kr/tw"),
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


@router.post(
    "/outcomes/run",
    response_model=DecisionSignalOutcomeRunResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "请求字段非法"},
        404: {"model": ErrorResponse, "description": "信号不存在"},
        422: {"model": ErrorResponse, "description": "请求体校验失败"},
        500: {"model": ErrorResponse, "description": "后验计算失败"},
    },
    summary="触发决策信号后验评估",
    description=(
        "显式触发 signal-level outcome 计算；默认跳过 completed 和终态 unable，"
        "但会重算缺少行情数据等可恢复 unable；force=true 会重算并覆盖同一 "
        "signal_id+horizon+engine_version。"
    ),
    operation_id="runDecisionSignalOutcomes",
)
def run_outcomes(request: DecisionSignalOutcomeRunRequest) -> DecisionSignalOutcomeRunResponse:
    service = DecisionSignalOutcomeService()
    try:
        return DecisionSignalOutcomeRunResponse(
            **service.run_outcomes(
                signal_id=request.signal_id,
                horizons=request.horizons,
                force=request.force,
                market=request.market,
                stock_code=request.stock_code,
                action=request.action,
                source_type=request.source_type,
                status=request.status,
                limit=request.limit,
            )
        )
    except DecisionSignalNotFoundError as exc:
        raise _not_found(exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Run decision signal outcomes failed", exc)


@router.get(
    "/outcomes",
    response_model=DecisionSignalOutcomeListResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "查询参数非法"},
        422: {"model": ErrorResponse, "description": "查询参数校验失败"},
        500: {"model": ErrorResponse, "description": "查询失败"},
    },
    summary="查询决策信号后验结果",
    description="分页查询 signal-level outcome；默认只查当前 signal 后验 engine_version。",
    operation_id="listDecisionSignalOutcomes",
)
def list_outcomes(
    signal_id: Optional[int] = Query(None, gt=0),
    horizon: Optional[str] = Query(None),
    engine_version: Optional[str] = Query(None),
    eval_status: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> DecisionSignalOutcomeListResponse:
    service = DecisionSignalOutcomeService()
    try:
        return DecisionSignalOutcomeListResponse(
            **service.list_outcomes(
                signal_id=signal_id,
                horizon=horizon,
                engine_version=engine_version,
                eval_status=eval_status,
                outcome=outcome,
                page=page,
                page_size=page_size,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("List decision signal outcomes failed", exc)


@router.get(
    "/outcomes/stats",
    response_model=DecisionSignalOutcomeStatsResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "查询参数非法"},
        422: {"model": ErrorResponse, "description": "查询参数校验失败"},
        500: {"model": ErrorResponse, "description": "统计失败"},
    },
    summary="查询决策信号后验统计",
    description="默认统计当前 engine_version，且排除 archived 信号。",
    operation_id="getDecisionSignalOutcomeStats",
)
def get_outcome_stats(
    horizons: Optional[List[str]] = Query(None),
    engine_version: Optional[str] = Query(None),
    statuses: Optional[List[str]] = Query(None),
) -> DecisionSignalOutcomeStatsResponse:
    service = DecisionSignalOutcomeService()
    try:
        return DecisionSignalOutcomeStatsResponse(
            **service.get_stats(
                horizons=horizons,
                engine_version=engine_version,
                statuses=statuses,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Get decision signal outcome stats failed", exc)


@router.post(
    "/reassess",
    response_model=DecisionSignalReassessResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "重评估请求不支持或历史报告不适用"},
        404: {"model": ErrorResponse, "description": "来源历史报告不存在"},
        422: {"model": ErrorResponse, "description": "请求体校验失败"},
        500: {"model": ErrorResponse, "description": "重评估失败"},
    },
    summary="预览决策风格重评估",
    description=(
        "基于 source_report_id 对应的持久化历史报告快照生成 decision_profile preview；"
        "P3a 仅支持 persist=false，不写入 DecisionSignal。"
    ),
    operation_id="reassessDecisionSignalPreview",
)
def reassess_signal(request: DecisionSignalReassessRequest) -> DecisionSignalReassessResponse:
    if request.persist:
        raise _error(
            400,
            DecisionSignalReassessUnsupportedOperationError(
                "Persisting reassessed decision_profile signals requires decision_profile "
                "to be promoted to a first-class field."
            ),
            error="unsupported_operation",
        )

    service = DecisionSignalReassessService()
    try:
        return DecisionSignalReassessResponse(
            **service.reassess(
                source_report_id=request.source_report_id,
                decision_profile=request.decision_profile,
                persist=request.persist,
            )
        )
    except DecisionSignalSourceReportNotFoundError as exc:
        raise _error(404, exc, error="source_report_not_found")
    except DecisionSignalUnsupportedReportTypeError as exc:
        raise _error(400, exc, error="unsupported_report_type")
    except DecisionSignalUnsupportedReportSnapshotError as exc:
        raise _error(400, exc, error="unsupported_report_snapshot")
    except DecisionSignalReassessUnsupportedOperationError as exc:
        raise _error(400, exc, error="unsupported_operation")
    except Exception as exc:
        raise _internal_error("Reassess decision signal preview failed", exc)


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
    market: Optional[str] = Query(None, description="Optional market filter: cn/hk/us/jp/kr/tw"),
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


@router.get(
    "/{signal_id}/outcomes",
    response_model=DecisionSignalOutcomeListResponse,
    responses={
        **AUTH_RESPONSE,
        404: {"model": ErrorResponse, "description": "信号不存在"},
        422: {"model": ErrorResponse, "description": "路径参数校验失败"},
        500: {"model": ErrorResponse, "description": "查询失败"},
    },
    summary="查询单个决策信号后验结果",
    description="返回指定 signal_id 在当前 engine_version 下的后验结果。",
    operation_id="listDecisionSignalOutcomesBySignal",
)
def list_signal_outcomes(signal_id: int) -> DecisionSignalOutcomeListResponse:
    service = DecisionSignalOutcomeService()
    try:
        return DecisionSignalOutcomeListResponse(**service.list_signal_outcomes(signal_id))
    except DecisionSignalNotFoundError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal_error("List decision signal outcomes failed", exc)


@router.get(
    "/{signal_id}/feedback",
    response_model=DecisionSignalFeedbackItem,
    responses={
        **AUTH_RESPONSE,
        404: {"model": ErrorResponse, "description": "信号不存在"},
        422: {"model": ErrorResponse, "description": "路径参数校验失败"},
        500: {"model": ErrorResponse, "description": "查询失败"},
    },
    summary="查询决策信号用户反馈",
    description="没有反馈时返回 feedback_value=null；信号不存在时返回 404。",
    operation_id="getDecisionSignalFeedback",
)
def get_feedback(signal_id: int) -> DecisionSignalFeedbackItem:
    service = DecisionSignalOutcomeService()
    try:
        return DecisionSignalFeedbackItem(**service.get_feedback(signal_id))
    except DecisionSignalNotFoundError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal_error("Get decision signal feedback failed", exc)


@router.put(
    "/{signal_id}/feedback",
    response_model=DecisionSignalFeedbackItem,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "请求字段非法"},
        404: {"model": ErrorResponse, "description": "信号不存在"},
        422: {"model": ErrorResponse, "description": "请求体或路径参数校验失败"},
        500: {"model": ErrorResponse, "description": "更新失败"},
    },
    summary="写入决策信号用户反馈",
    description="按 signal_id upsert 最新 useful/not_useful 反馈。",
    operation_id="putDecisionSignalFeedback",
)
def put_feedback(signal_id: int, request: DecisionSignalFeedbackRequest) -> DecisionSignalFeedbackItem:
    service = DecisionSignalOutcomeService()
    try:
        return DecisionSignalFeedbackItem(
            **service.put_feedback(
                signal_id,
                feedback_value=request.feedback_value,
                reason_code=request.reason_code,
                note=request.note,
                source=request.source,
            )
        )
    except DecisionSignalNotFoundError as exc:
        raise _not_found(exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Put decision signal feedback failed", exc)


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
    description=(
        "只更新合法状态和可选 metadata；传入 metadata 时按整包替换保存。"
        "expired/invalidated/closed/archived 等 terminal 状态不能直接 PATCH 回 active。"
    ),
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
