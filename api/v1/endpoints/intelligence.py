# -*- coding: utf-8 -*-
"""Intelligence source API endpoints."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.intelligence import (
    IntelligenceDefaultSourceCreateResponse,
    IntelligenceDefaultSourcesCreateRequest,
    IntelligenceFetchResponse,
    IntelligenceItemListResponse,
    IntelligenceSourceCreateRequest,
    IntelligenceSourceItem,
    IntelligenceSourceListResponse,
    IntelligenceSourceTemplateCreateRequest,
    IntelligenceSourceTemplateListResponse,
    IntelligenceSourceTestResponse,
)
from src.services.intelligence_service import IntelligenceService, IntelligenceServiceError
from src.services.run_diagnostics import sanitize_diagnostic_text

logger = logging.getLogger(__name__)
router = APIRouter()


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": "validation_error", "message": str(exc)})


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": "not_found", "message": message})


def _internal_error(message: str, exc: Exception) -> HTTPException:
    sanitized_error = sanitize_diagnostic_text(str(exc), max_length=300) or "internal intelligence error"
    logger.error("%s: %s", message, sanitized_error)
    return HTTPException(
        status_code=500,
        detail={"error": "internal_error", "message": f"{message}: internal intelligence service error"},
    )


@router.post("/sources", response_model=IntelligenceSourceItem, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}, summary="Create intelligence source")
def create_source(request: IntelligenceSourceCreateRequest) -> IntelligenceSourceItem:
    try:
        return IntelligenceSourceItem(**IntelligenceService().create_source(request.model_dump()))
    except IntelligenceServiceError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Create intelligence source failed", exc)


@router.get("/sources", response_model=IntelligenceSourceListResponse, responses={500: {"model": ErrorResponse}}, summary="List intelligence sources")
def list_sources(
    enabled: Optional[bool] = Query(None),
    source_type: Optional[str] = Query(None),
    scope_type: Optional[str] = Query(None),
    market: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> IntelligenceSourceListResponse:
    try:
        return IntelligenceSourceListResponse(**IntelligenceService().list_sources(
            enabled=enabled, source_type=source_type, scope_type=scope_type,
            market=market, page=page, page_size=page_size,
        ))
    except Exception as exc:
        raise _internal_error("List intelligence sources failed", exc)


@router.get("/sources/templates", response_model=IntelligenceSourceTemplateListResponse, responses={500: {"model": ErrorResponse}}, summary="List built-in intelligence source templates")
def list_source_templates(
    source_type: Optional[str] = Query(None),
    market: Optional[str] = Query(None),
) -> IntelligenceSourceTemplateListResponse:
    try:
        return IntelligenceSourceTemplateListResponse(**IntelligenceService().list_source_templates(
            source_type=source_type,
            market=market,
        ))
    except Exception as exc:
        raise _internal_error("List intelligence source templates failed", exc)


@router.post("/sources/templates/{template_id}", response_model=IntelligenceSourceItem, responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}, summary="Create intelligence source from a built-in template")
def create_source_from_template(
    template_id: str,
    request: IntelligenceSourceTemplateCreateRequest = IntelligenceSourceTemplateCreateRequest(),
) -> IntelligenceSourceItem:
    try:
        return IntelligenceSourceItem(**IntelligenceService().create_source_from_template(
            template_id,
            request.model_dump(exclude_none=True),
        ))
    except IntelligenceServiceError as exc:
        message = str(exc)
        if "template not found" in message.lower():
            raise _not_found(message)
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Create intelligence source from template failed", exc)


@router.post("/sources/defaults", response_model=IntelligenceDefaultSourceCreateResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}, summary="Create built-in default intelligence sources")
def create_default_sources(
    request: IntelligenceDefaultSourcesCreateRequest = IntelligenceDefaultSourcesCreateRequest(),
) -> IntelligenceDefaultSourceCreateResponse:
    try:
        return IntelligenceDefaultSourceCreateResponse(**IntelligenceService().create_default_sources(
            request.model_dump(exclude_none=True),
        ))
    except IntelligenceServiceError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Create default intelligence sources failed", exc)


@router.post("/sources/test", response_model=IntelligenceSourceTestResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}, summary="Dry-run an intelligence source payload")
def test_source_payload(request: IntelligenceSourceCreateRequest) -> IntelligenceSourceTestResponse:
    try:
        return IntelligenceSourceTestResponse(**IntelligenceService().test_source(request.model_dump()))
    except IntelligenceServiceError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Test intelligence source failed", exc)


@router.post("/sources/{source_id}/fetch", response_model=IntelligenceFetchResponse, responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}, summary="Fetch one intelligence source")
def fetch_source(source_id: int, dry_run: bool = Query(False)) -> IntelligenceFetchResponse:
    try:
        return IntelligenceFetchResponse(**IntelligenceService().fetch_source(source_id, dry_run=dry_run))
    except IntelligenceServiceError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise _not_found(message)
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Fetch intelligence source failed", exc)


@router.post("/sources/fetch-enabled", response_model=IntelligenceFetchResponse, responses={500: {"model": ErrorResponse}}, summary="Fetch all enabled intelligence sources with fail-open semantics")
def fetch_enabled_sources() -> IntelligenceFetchResponse:
    try:
        return IntelligenceFetchResponse(**IntelligenceService().fetch_enabled_sources())
    except Exception as exc:
        raise _internal_error("Fetch enabled intelligence sources failed", exc)


@router.get("/items", response_model=IntelligenceItemListResponse, responses={500: {"model": ErrorResponse}}, summary="List persisted intelligence items")
def list_items(
    scope_type: Optional[str] = Query(None),
    scope_value: Optional[str] = Query(None),
    market: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    days: Optional[int] = Query(None, ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> IntelligenceItemListResponse:
    try:
        return IntelligenceItemListResponse(**IntelligenceService().list_items(
            scope_type=scope_type, scope_value=scope_value, market=market,
            query=query, days=days, page=page, page_size=page_size,
        ))
    except Exception as exc:
        raise _internal_error("List intelligence items failed", exc)
