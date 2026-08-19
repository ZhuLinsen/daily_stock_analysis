# -*- coding: utf-8 -*-
"""Read-only research job API: create, query, cancel. No order fields."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import APIKeyCookie

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.research import (
    ResearchJobCreateRequest,
    ResearchJobListResponse,
    ResearchJobResponse,
    job_response_from_public,
)
from src.agent.research_jobs import ResearchJobService, get_research_job_service
from src.auth import COOKIE_NAME
from src.schemas.research_contracts import Horizon, ResearchRequest

admin_session_cookie = APIKeyCookie(
    name=COOKIE_NAME,
    scheme_name="AdminSessionCookie",
    auto_error=False,
)
router = APIRouter(dependencies=[Security(admin_session_cookie)])

AUTH_RESPONSE = {
    401: {
        "model": ErrorResponse,
        "description": "未登录或管理员会话无效",
    },
}


def get_research_service(request: Request) -> ResearchJobService:
    service = getattr(request.app.state, "research_job_service", None)
    if service is None:
        service = get_research_job_service()
        request.app.state.research_job_service = service
    return service


def _parse_horizons(raw: List[str] | None) -> tuple[Horizon, ...]:
    if not raw:
        return (Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG)
    mapped = []
    allowed = {item.value: item for item in Horizon}
    for value in raw:
        horizon = allowed.get(value)
        if horizon is None:
            raise HTTPException(
                status_code=400,
                detail={"error": "validation_error", "message": f"unknown horizon: {value}"},
            )
        mapped.append(horizon)
    return tuple(mapped)


@router.post(
    "/jobs",
    response_model=ResearchJobResponse,
    responses=AUTH_RESPONSE,
)
def create_research_job(
    body: ResearchJobCreateRequest,
    service: ResearchJobService = Depends(get_research_service),
) -> ResearchJobResponse:
    as_of = body.as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    request_id = body.idempotency_key or f"api-{body.subject}-{as_of}"
    request = ResearchRequest(
        request_id=request_id,
        run_id=request_id,
        subject=body.subject.strip(),
        market=body.market,
        as_of=as_of,
        horizons=_parse_horizons(body.horizons),
        authorization_context=body.authorization_context,
        idempotency_key=body.idempotency_key or request_id,
    )
    job = service.submit(request, wait=body.wait)
    return job_response_from_public(job.to_public_dict())


@router.get(
    "/jobs",
    response_model=ResearchJobListResponse,
    responses=AUTH_RESPONSE,
)
def list_research_jobs(
    service: ResearchJobService = Depends(get_research_service),
) -> ResearchJobListResponse:
    jobs = [job_response_from_public(item.to_public_dict()) for item in service.list_jobs()]
    return ResearchJobListResponse(jobs=jobs)


@router.get(
    "/jobs/{job_id}",
    response_model=ResearchJobResponse,
    responses=AUTH_RESPONSE,
)
def get_research_job(
    job_id: str,
    service: ResearchJobService = Depends(get_research_service),
) -> ResearchJobResponse:
    job = service.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": "research job not found"},
        )
    return job_response_from_public(job.to_public_dict())


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=ResearchJobResponse,
    responses=AUTH_RESPONSE,
)
def cancel_research_job(
    job_id: str,
    service: ResearchJobService = Depends(get_research_service),
) -> ResearchJobResponse:
    job = service.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": "research job not found"},
        )
    service.cancel(job_id)
    current = service.get(job_id)
    assert current is not None
    return job_response_from_public(current.to_public_dict())
