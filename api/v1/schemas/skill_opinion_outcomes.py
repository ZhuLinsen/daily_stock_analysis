# -*- coding: utf-8 -*-
"""Schemas for admin Skill Opinion Outcome execution and read-only queries."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


SkillOpinionOutcomeHorizon = Literal["1d", "3d", "5d", "10d"]
SkillOpinionOutcomeStatus = Literal["pending", "evaluated", "observational", "unable"]
SkillOpinionOutcomeValue = Literal["hit", "miss", "observational"]


class SkillOpinionOutcomeRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: Optional[int] = Field(None, gt=0)
    analysis_history_id: Optional[int] = Field(None, gt=0)
    skill_id: Optional[str] = Field(None, min_length=1, max_length=128)
    stock_code: Optional[str] = Field(None, min_length=1, max_length=16)
    horizons: Optional[List[SkillOpinionOutcomeHorizon]] = None
    limit: int = Field(100, ge=1, le=500)


class SkillOpinionOutcomeItem(BaseModel):
    id: int
    skill_opinion_sample_id: int
    analysis_history_id: int
    stock_code: str
    skill_id: str
    signal: str
    horizon: SkillOpinionOutcomeHorizon
    engine_version: str
    eval_status: SkillOpinionOutcomeStatus
    outcome: Optional[SkillOpinionOutcomeValue] = None
    direction_correct: Optional[bool] = None
    unable_reason: Optional[str] = None
    analysis_date: Optional[str] = None
    start_trade_date: Optional[str] = None
    end_trade_date: Optional[str] = None
    start_price: Optional[float] = None
    end_close: Optional[float] = None
    stock_return_pct: Optional[float] = None
    directional_return_pct: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SkillOpinionOutcomeRunError(BaseModel):
    sample_id: int
    horizon: SkillOpinionOutcomeHorizon
    error_type: str


class SkillOpinionOutcomeRunResponse(BaseModel):
    items: List[SkillOpinionOutcomeItem] = Field(default_factory=list)
    processed_keys: int
    created: int
    updated: int
    skipped: int
    failed: int
    errors: List[SkillOpinionOutcomeRunError] = Field(default_factory=list)
    limit_unit: Literal["outcome_key"]
    engine_version: str


class SkillOpinionOutcomeListResponse(BaseModel):
    items: List[SkillOpinionOutcomeItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
