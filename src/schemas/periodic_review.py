# -*- coding: utf-8 -*-
"""Pydantic schemas for periodic (weekly/monthly) review reports."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class PeriodicReviewType(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class IndexPerformance(BaseModel):
    """Index performance over the review period."""

    name: str
    code: str
    start_close: float
    end_close: float
    change_pct: float
    avg_amount: float = 0.0  # average daily turnover in 亿元


class SectorPerformance(BaseModel):
    """Sector performance over the review period."""

    name: str
    change_pct: float
    rank: int = 0


class MarketLightTrendPoint(BaseModel):
    """A single day's market light score for trend display."""

    trade_date: str
    score: int
    status: str


class PeriodicReviewData(BaseModel):
    """Aggregated data for a weekly or monthly review report."""

    review_type: PeriodicReviewType
    region: str = "cn"
    period_start: str
    period_end: str
    trade_days: int
    indices: List[IndexPerformance] = Field(default_factory=list)
    top_sectors: List[SectorPerformance] = Field(default_factory=list)
    bottom_sectors: List[SectorPerformance] = Field(default_factory=list)
    market_light_trend: List[MarketLightTrendPoint] = Field(default_factory=list)
    avg_amount: float = 0.0
    sector_rotation: Optional[str] = None
    highlights: str = ""

    model_config = {"use_enum_values": True}
