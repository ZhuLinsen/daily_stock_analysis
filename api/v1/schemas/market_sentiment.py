"""Public responses for A-share closing sentiment snapshots."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from api.v1.schemas.analysis import TaskStatusEnum


QualityStatus = Literal["complete", "partial"]


class MarketSentimentAccepted(BaseModel):
    task_id: str
    trace_id: str
    status: Literal["accepted"] = "accepted"
    message: str
    trade_date: date


class MarketSentimentTaskResult(BaseModel):
    trade_date: date
    action: Literal["inserted", "unchanged"]
    quality_status: QualityStatus


class MarketSentimentTaskStatus(BaseModel):
    task_id: str
    trace_id: str
    status: TaskStatusEnum
    progress: int
    message: str | None = None
    error: str | None = None
    result: MarketSentimentTaskResult | None = None


class MarketSentimentSnapshotResponse(BaseModel):
    market: str
    trade_date: date
    created_at: datetime
    definition_version: str
    quality_status: QualityStatus
    metrics: dict[str, Any]
    provider_trace: dict[str, Any]
    completeness: dict[str, bool]


class MarketSentimentSnapshotList(BaseModel):
    items: list[MarketSentimentSnapshotResponse]


class MarketSentimentTrend(BaseModel):
    end_date: date
    window_sessions: Literal[10, 30, 60]
    definition_version: str | None
    session_dates: list[date]
    missing_dates: list[date]
    different_definition_dates: list[date]
    items: list[MarketSentimentSnapshotResponse]
