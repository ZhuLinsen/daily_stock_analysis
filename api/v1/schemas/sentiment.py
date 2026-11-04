"""Contracts for the opt-in A-share close sentiment backend."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SentimentMetrics(BaseModel):
    limit_up_count: int | None
    break_rate: float | None
    max_consecutive: int | None
    promotion_1_to_2: float | None


class SentimentSnapshotItem(BaseModel):
    market: str
    trade_date: date
    previous_trade_date: date
    definition_version: str
    quality_status: Literal["complete", "partial", "imported"]
    metrics: SentimentMetrics
    break_numerator: int | None
    break_denominator: int | None
    promotion_numerator: int | None
    promotion_denominator: int | None
    provider_trace: dict[str, Any]
    completeness: dict[str, Any]
    created_at: datetime


class SentimentGenerateResponse(BaseModel):
    action: Literal["inserted", "unchanged"]
    snapshot: SentimentSnapshotItem


class SentimentListResponse(BaseModel):
    items: list[SentimentSnapshotItem] = Field(default_factory=list)


class SentimentTrendResponse(BaseModel):
    end_date: date
    items: list[SentimentSnapshotItem] = Field(default_factory=list)
