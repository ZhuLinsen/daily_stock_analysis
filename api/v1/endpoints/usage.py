# -*- coding: utf-8 -*-
"""LLM usage tracking endpoint."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from api.deps import get_database_manager
from api.v1.schemas.usage import UsageDashboardResponse, UsageSummaryResponse
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))  # Beijing time (UTC+8)

router = APIRouter()

_VALID_PERIODS = {"today", "month", "all"}


def _date_range(period: str):
    """Return (from_dt, to_dt) as naive datetimes in Beijing time (UTC+8)."""
    now = datetime.now(tz=_CST).replace(tzinfo=None)  # naive, Beijing local
    if period == "today":
        from_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        from_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # all
        from_dt = datetime(2000, 1, 1)
    return from_dt, now


def _normalize_period(period: str) -> str:
    return period if period in _VALID_PERIODS else "month"


def _enrich_call_record(row: dict[str, Any]) -> dict[str, Any]:
    called_at = row.get("called_at")
    if isinstance(called_at, datetime):
        called_at_value = called_at.isoformat()
    else:
        called_at_value = str(called_at or "")
    return {
        **row,
        "called_at": called_at_value,
    }


def _build_summary_payload(period: str, from_dt: datetime, to_dt: datetime, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "period": period,
        "from_date": from_dt.date().isoformat(),
        "to_date": to_dt.date().isoformat(),
        "total_calls": data.get("total_calls", 0),
        "total_prompt_tokens": data.get("total_prompt_tokens", 0),
        "total_completion_tokens": data.get("total_completion_tokens", 0),
        "total_tokens": data.get("total_tokens", 0),
        "by_call_type": data.get("by_call_type", []),
        "by_model": data.get("by_model", []),
    }


@router.get(
    "/summary",
    response_model=UsageSummaryResponse,
    summary="LLM token usage summary",
    description="Aggregate token consumption by period, call type, and model.",
)
def get_usage_summary(
    period: str = Query("month", description="'today' | 'month' | 'all'"),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> UsageSummaryResponse:
    normalized_period = _normalize_period(period)
    from_dt, to_dt = _date_range(normalized_period)
    data = db_manager.get_llm_usage_summary(from_dt, to_dt)
    return UsageSummaryResponse(**_build_summary_payload(normalized_period, from_dt, to_dt, data))


@router.get(
    "/dashboard",
    response_model=UsageDashboardResponse,
    summary="LLM token usage monitoring dashboard",
    description="Return token totals, model breakdowns, and recent LLM call records.",
)
def get_usage_dashboard(
    period: str = Query("month", description="'today' | 'month' | 'all'"),
    limit: int = Query(50, ge=1, le=200, description="Recent call records to include"),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> UsageDashboardResponse:
    normalized_period = _normalize_period(period)
    from_dt, to_dt = _date_range(normalized_period)
    data = db_manager.get_llm_usage_summary(from_dt, to_dt)
    records = db_manager.get_llm_usage_records(from_dt, to_dt, limit=limit)
    payload = _build_summary_payload(normalized_period, from_dt, to_dt, data)
    payload["recent_calls"] = [_enrich_call_record(row) for row in records]
    return UsageDashboardResponse(**payload)
