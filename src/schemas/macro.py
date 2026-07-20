"""Stable boundary models for macro data providers and reports."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class MacroObservation(BaseModel):
    region: str
    indicator: str
    series_id: str
    value: float | None = None
    unit: str | None = None
    observation_date: date | None = None
    fetched_at: datetime
    source_name: str
    source_url: str | None = None
    frequency: str | None = None
    is_stale: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class USMacroSnapshot(BaseModel):
    as_of: datetime
    observations: list[MacroObservation] = Field(default_factory=list)
    market_data: list[dict[str, Any]] = Field(default_factory=list)
    missing_indicators: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class USMacroAIExplanation(BaseModel):
    core_logic: str
    bullish_factors: list[str] = Field(default_factory=list)
    bearish_factors: list[str] = Field(default_factory=list)
    sector_impacts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
