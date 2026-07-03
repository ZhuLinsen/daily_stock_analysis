# -*- coding: utf-8 -*-
"""Structured Market Light snapshot schema."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


MarketRegion = Literal["cn", "hk", "us", "jp", "kr"]
MarketLightStatus = Literal["green", "yellow", "red"]
MarketLightDataQuality = Literal["ok", "partial", "unavailable"]
MARKET_LIGHT_REGIONS = frozenset(("cn", "hk", "us"))


class MarketLightDimension(BaseModel):
    """A single Market Light scoring dimension."""

    score: int = Field(ge=0, le=100)
    available: bool


class MarketLightDimensions(BaseModel):
    """Canonical Market Light dimension scores.

    The three core dimensions (breadth/index/limit) are always present. The
    five extended dimensions are optional so that snapshots persisted before
    the extension still validate; they default to ``None`` and should be
    treated as "unavailable" by consumers.
    """

    breadth: MarketLightDimension
    index: MarketLightDimension
    limit: MarketLightDimension
    # Extended dimensions (optional for backward compatibility with old snapshots)
    margin_balance: Optional[MarketLightDimension] = None
    northbound_flow: Optional[MarketLightDimension] = None
    turnover_quantile: Optional[MarketLightDimension] = None
    limit_ratio: Optional[MarketLightDimension] = None
    continuous_board: Optional[MarketLightDimension] = None


class MarketLightSnapshot(BaseModel):
    """Structured Market Light snapshot persisted and consumed by alerts."""

    region: MarketRegion
    trade_date: str
    status: MarketLightStatus
    score: int = Field(ge=0, le=100)
    label: str
    temperature_label: str
    reasons: list[str]
    guidance: str
    dimensions: MarketLightDimensions
    data_quality: MarketLightDataQuality
