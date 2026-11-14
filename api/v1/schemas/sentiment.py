"""Contracts for the opt-in A-share close sentiment backend."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class BoardPromotion(BaseModel):
    numerator: int
    denominator: int
    rate: float | None


class SentimentMetrics(BaseModel):
    limit_up_count: int | None
    break_rate: float | None
    max_consecutive: int | None
    promotion_1_to_2: float | None
    limit_down_coverage: float | None = None
    advancing_ratio: float | None = None
    limit_up_ladder: dict[int, int] | None = None
    higher_board_promotions: dict[str, BoardPromotion] | None = None
    turnover_yuan: float | None = None
    previous_turnover_yuan: float | None = None
    turnover_change_yuan: float | None = None
    turnover_change_ratio: float | None = None


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
    eligible_quote_count: int | None = None
    limit_down_count: int | None = None
    advancing_count: int | None = None
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
    window_sessions: int
    definition_version: str | None
    session_dates: list[date]
    missing_dates: list[date]
    different_definition_dates: list[date]
    items: list[SentimentSnapshotItem] = Field(default_factory=list)
