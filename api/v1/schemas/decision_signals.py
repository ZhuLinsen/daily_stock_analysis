# -*- coding: utf-8 -*-
"""DecisionSignal API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from api.v1.schemas.market_phase import MarketPhaseValue
from src.schemas.decision_action import DecisionAction


DecisionSignalSourceType = Literal["analysis", "agent", "alert", "market_review", "manual"]
DecisionSignalStatus = Literal["active", "expired", "invalidated", "closed", "archived"]
DecisionSignalPlanQuality = Literal["complete", "partial", "minimal", "unknown"]
DecisionSignalHorizon = Literal["intraday", "1d", "3d", "5d", "10d", "swing", "long"]
DecisionSignalMarket = Literal["cn", "hk", "us", "jp", "kr", "tw"]
DecisionSignalOutcomeStatus = Literal["completed", "unable"]
DecisionSignalOutcomeValue = Literal["hit", "miss", "neutral"]
DecisionSignalFeedbackValue = Literal["useful", "not_useful"]
DecisionSignalFeedbackSource = Literal["web", "api"]


class DecisionSignalCreateRequest(BaseModel):
    stock_code: str = Field(..., min_length=1, max_length=32)
    stock_name: Optional[str] = Field(None, json_schema_extra={"maxLength": 64})
    market: DecisionSignalMarket
    source_type: DecisionSignalSourceType
    source_agent: Optional[str] = Field(None, json_schema_extra={"maxLength": 64})
    source_report_id: Optional[int] = None
    trace_id: Optional[str] = Field(None, json_schema_extra={"maxLength": 64})
    market_phase: Optional[MarketPhaseValue] = None
    trigger_source: str = Field(..., min_length=1, json_schema_extra={"maxLength": 64})
    action: DecisionAction
    action_label: Optional[str] = Field(None, json_schema_extra={"maxLength": 32})
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    score: Optional[int] = Field(None, ge=0, le=100)
    horizon: Optional[DecisionSignalHorizon] = None
    entry_low: Optional[float] = Field(None, gt=0, allow_inf_nan=False)
    entry_high: Optional[float] = Field(None, gt=0, allow_inf_nan=False)
    stop_loss: Optional[float] = Field(None, gt=0, allow_inf_nan=False)
    target_price: Optional[float] = Field(None, gt=0, allow_inf_nan=False)
    invalidation: Optional[Any] = None
    watch_conditions: Optional[Any] = None
    reason: Optional[Any] = None
    risk_summary: Optional[Any] = None
    catalyst_summary: Optional[Any] = None
    evidence: Optional[Any] = None
    data_quality_summary: Optional[Any] = None
    plan_quality: Optional[DecisionSignalPlanQuality] = None
    status: Optional[DecisionSignalStatus] = None
    expires_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None
    report_language: Optional[Literal["zh", "en"]] = None


class DecisionSignalStatusUpdateRequest(BaseModel):
    status: DecisionSignalStatus
    metadata: Optional[Dict[str, Any]] = None


class DecisionSignalOutcomeRunRequest(BaseModel):
    signal_id: Optional[int] = Field(None, gt=0)
    horizons: Optional[List[DecisionSignalHorizon]] = None
    force: bool = False
    market: Optional[DecisionSignalMarket] = None
    stock_code: Optional[str] = Field(None, json_schema_extra={"maxLength": 32})
    action: Optional[DecisionAction] = None
    source_type: Optional[DecisionSignalSourceType] = None
    status: Optional[DecisionSignalStatus] = None
    limit: int = Field(100, ge=1, le=500)


class DecisionSignalOutcomeItem(BaseModel):
    id: int
    signal_id: int
    horizon: str
    engine_version: str
    eval_status: str
    outcome: Optional[str] = None
    direction_expected: Optional[str] = None
    direction_correct: Optional[bool] = None
    unable_reason: Optional[str] = None
    anchor_date: Optional[str] = None
    eval_window_days: Optional[int] = None
    start_price: Optional[float] = None
    end_close: Optional[float] = None
    max_high: Optional[float] = None
    min_low: Optional[float] = None
    stock_return_pct: Optional[float] = None
    action: Optional[str] = None
    market: Optional[str] = None
    market_phase: Optional[str] = None
    source_type: Optional[str] = None
    source_agent: Optional[str] = None
    plan_quality: Optional[str] = None
    data_quality_level: Optional[str] = None
    holding_state: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DecisionSignalOutcomeRunResponse(BaseModel):
    items: List[DecisionSignalOutcomeItem] = Field(default_factory=list)
    evaluated: int
    created: int
    updated: int
    skipped: int
    engine_version: str


class DecisionSignalOutcomeListResponse(BaseModel):
    items: List[DecisionSignalOutcomeItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class DecisionSignalOutcomeStatsBucket(BaseModel):
    dimension: str
    value: str
    total: int
    completed: int
    unable: int
    hit: int
    miss: int
    neutral: int
    hit_rate_pct: Optional[float] = None
    avg_stock_return_pct: Optional[float] = None
    unable_reasons: Dict[str, int] = Field(default_factory=dict)


class DecisionSignalOutcomeStatsResponse(BaseModel):
    engine_version: str
    horizons: Optional[List[str]] = None
    statuses: List[str] = Field(default_factory=list)
    total: int
    completed: int
    unable: int
    hit: int
    miss: int
    neutral: int
    hit_rate_pct: Optional[float] = None
    avg_stock_return_pct: Optional[float] = None
    unable_reasons: Dict[str, int] = Field(default_factory=dict)
    breakdowns: Dict[str, List[DecisionSignalOutcomeStatsBucket]] = Field(default_factory=dict)


class DecisionSignalFeedbackRequest(BaseModel):
    feedback_value: DecisionSignalFeedbackValue
    reason_code: Optional[str] = Field(None, json_schema_extra={"maxLength": 64})
    note: Optional[str] = Field(None, json_schema_extra={"maxLength": 1000})
    source: DecisionSignalFeedbackSource = "api"


class DecisionSignalFeedbackItem(BaseModel):
    signal_id: int
    feedback_value: Optional[DecisionSignalFeedbackValue] = None
    reason_code: Optional[str] = None
    note: Optional[str] = None
    source: Optional[DecisionSignalFeedbackSource] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DecisionSignalItem(BaseModel):
    id: int
    stock_code: str
    stock_name: Optional[str] = None
    market: str
    source_type: str
    source_agent: Optional[str] = None
    source_report_id: Optional[int] = None
    trace_id: Optional[str] = None
    market_phase: Optional[str] = None
    trigger_source: str
    action: str
    action_label: Optional[str] = None
    confidence: Optional[float] = None
    score: Optional[int] = None
    horizon: Optional[str] = None
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    invalidation: Optional[str] = None
    watch_conditions: Optional[str] = None
    reason: Optional[str] = None
    risk_summary: Optional[str] = None
    catalyst_summary: Optional[str] = None
    evidence: Optional[Any] = None
    data_quality_summary: Optional[Any] = None
    plan_quality: str
    status: str
    expires_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Optional[Any] = None


class DecisionSignalMutationResponse(BaseModel):
    item: DecisionSignalItem
    created: bool


class DecisionSignalListResponse(BaseModel):
    items: List[DecisionSignalItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
