# -*- coding: utf-8 -*-
"""Admin endpoints for per-skill opinion forward outcomes."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Security
from fastapi.security import APIKeyCookie

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.skill_opinion_outcomes import (
    SkillOpinionOutcomeHorizon,
    SkillOpinionOutcomeListResponse,
    SkillOpinionOutcomeRunRequest,
    SkillOpinionOutcomeRunResponse,
    SkillOpinionOutcomeStatus,
    SkillOpinionOutcomeValue,
)
from src.auth import COOKIE_NAME
from src.services.skill_opinion_outcome_service import SkillOpinionOutcomeService


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


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"error": "validation_error", "message": str(exc)},
    )


def _internal_error(message: str, exc: Exception) -> HTTPException:
    logger.error("%s: %s", message, exc, exc_info=True)
    return HTTPException(
        status_code=500,
        detail={"error": "internal_error", "message": message},
    )


@router.post(
    "/run",
    response_model=SkillOpinionOutcomeRunResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "请求字段非法"},
        422: {"model": ErrorResponse, "description": "请求体校验失败"},
        500: {"model": ErrorResponse, "description": "Skill opinion outcome 计算失败"},
    },
    summary="触发 Skill opinion outcome 计算",
    description="仅使用已持久化 sample 与本地日线，按每条 sample 自身 signal 独立评价。",
    operation_id="runSkillOpinionOutcomes",
)
def run_outcomes(request: SkillOpinionOutcomeRunRequest) -> SkillOpinionOutcomeRunResponse:
    service = SkillOpinionOutcomeService()
    try:
        return SkillOpinionOutcomeRunResponse(
            **service.run_outcomes(
                sample_id=request.sample_id,
                analysis_history_id=request.analysis_history_id,
                skill_id=request.skill_id,
                stock_code=request.stock_code,
                horizons=request.horizons,
                limit=request.limit,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Run skill opinion outcomes failed", exc)


@router.get(
    "",
    response_model=SkillOpinionOutcomeListResponse,
    responses={
        **AUTH_RESPONSE,
        400: {"model": ErrorResponse, "description": "查询参数非法"},
        422: {"model": ErrorResponse, "description": "查询参数校验失败"},
        500: {"model": ErrorResponse, "description": "Skill opinion outcome 查询失败"},
    },
    summary="逐条查询 Skill opinion outcome",
    description="只读分页查询，不提供表现统计、排名或权重信息。",
    operation_id="listSkillOpinionOutcomes",
)
def list_outcomes(
    sample_id: Optional[int] = Query(None, gt=0),
    analysis_history_id: Optional[int] = Query(None, gt=0),
    skill_id: Optional[str] = Query(None, min_length=1, max_length=128),
    stock_code: Optional[str] = Query(None, min_length=1, max_length=16),
    horizon: Optional[SkillOpinionOutcomeHorizon] = Query(None),
    engine_version: Optional[str] = Query(None, min_length=1, max_length=32),
    eval_status: Optional[SkillOpinionOutcomeStatus] = Query(None),
    outcome: Optional[SkillOpinionOutcomeValue] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> SkillOpinionOutcomeListResponse:
    service = SkillOpinionOutcomeService()
    try:
        return SkillOpinionOutcomeListResponse(
            **service.list_outcomes_page(
                sample_id=sample_id,
                analysis_history_id=analysis_history_id,
                skill_id=skill_id,
                stock_code=stock_code,
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
        raise _internal_error("List skill opinion outcomes failed", exc)
