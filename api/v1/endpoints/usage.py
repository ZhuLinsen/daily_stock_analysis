# -*- coding: utf-8 -*-
"""LLM usage tracking endpoint."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from api.deps import get_database_manager
from api.v1.schemas.usage import UsageSummaryResponse
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
    if period not in _VALID_PERIODS:
        period = "month"

    from_dt, to_dt = _date_range(period)

    data = db_manager.get_llm_usage_summary(from_dt, to_dt)

    return UsageSummaryResponse(
        period=period,
        from_date=from_dt.date().isoformat(),
        to_date=to_dt.date().isoformat(),
        total_calls=data["total_calls"],
        total_tokens=data["total_tokens"],
        by_call_type=data["by_call_type"],
        by_model=data["by_model"],
    )
