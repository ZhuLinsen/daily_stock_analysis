# -*- coding: utf-8 -*-
"""Data capability and quality endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import get_config_dep
from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.data_capability import DataCapabilityOverviewResponse
from src.config import Config
from src.services.data_capability_service import DataCapabilityService

logger = logging.getLogger(__name__)

router = APIRouter()


def _overview_response(config: Config, *, runtime_scheduler: object = None) -> DataCapabilityOverviewResponse:
    try:
        payload = DataCapabilityService(
            config=config,
            runtime_scheduler=runtime_scheduler,
        ).get_overview()
        return DataCapabilityOverviewResponse.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - keep diagnostics fail-open at API boundary.
        logger.error("Failed to build data capability overview: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": "Failed to build data capability overview",
            },
        )


@router.get(
    "/overview",
    response_model=DataCapabilityOverviewResponse,
    responses={500: {"model": ErrorResponse}},
    summary="Get data capability overview",
    description="Return provider capabilities, dataset quality, and source priority without exposing secrets.",
)
def get_data_overview(
    request: Request,
    config: Config = Depends(get_config_dep),
) -> DataCapabilityOverviewResponse:
    """Return the canonical read-only data overview."""
    return _overview_response(
        config,
        runtime_scheduler=getattr(request.app.state, "runtime_scheduler_service", None),
    )


@router.get(
    "/capabilities",
    response_model=DataCapabilityOverviewResponse,
    responses={500: {"model": ErrorResponse}},
    summary="Get data provider capabilities",
    description="Alias of /data/overview for clients that only need capability metadata.",
)
def get_data_capabilities(
    request: Request,
    config: Config = Depends(get_config_dep),
) -> DataCapabilityOverviewResponse:
    """Return the data overview under the capability-oriented alias."""
    return _overview_response(
        config,
        runtime_scheduler=getattr(request.app.state, "runtime_scheduler_service", None),
    )
