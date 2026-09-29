# -*- coding: utf-8 -*-
"""Structured research artifact schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from src.schemas.decision_action import DecisionAction


ResearchQualityLevel = Literal["good", "usable", "limited", "poor", "unknown"]
ResearchDirection = Literal["bullish", "bearish", "neutral", "unknown"]
ResearchEvidenceFreshness = Literal["fresh", "stale", "unknown"]
ResearchInvalidationCategory = Literal[
    "price",
    "volume",
    "evidence",
    "market",
    "time",
    "data_quality",
    "manual",
]
ResearchInvalidationSeverity = Literal["watch", "warning", "critical"]


class ResearchSubject(BaseModel):
    """The entity being researched."""

    stock_code: str = Field(..., min_length=1)
    stock_name: Optional[str] = None
    market: Optional[str] = None
    entity_ref: Optional[str] = Field(None, description="Optional EntityLink ref when available")


class ResearchThesis(BaseModel):
    """Structured investment thesis extracted from a report."""

    direction: ResearchDirection = "unknown"
    summary: str = Field("", description="Concise thesis statement")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    score: Optional[int] = Field(None, description="Original sentiment score when available")
    horizon: Optional[str] = None
    action: Optional[DecisionAction] = None
    action_label: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)


class ResearchEvidenceItem(BaseModel):
    """One evidence item with freshness and quality status."""

    id: str = Field(..., min_length=1)
    source_type: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    summary: Optional[str] = None
    source: Optional[str] = None
    freshness: ResearchEvidenceFreshness = "unknown"
    quality_level: ResearchQualityLevel = "unknown"
    as_of: Optional[str] = None
    url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchInvalidationCondition(BaseModel):
    """Condition that should invalidate or force reassessment of the thesis."""

    id: str = Field(..., min_length=1)
    category: ResearchInvalidationCategory
    description: str = Field(..., min_length=1)
    trigger: Optional[str] = None
    severity: ResearchInvalidationSeverity = "warning"
    metric: Optional[str] = None
    threshold: Optional[str] = None
    due_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchNextAction(BaseModel):
    """Suggested next action for a human or workflow."""

    action: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    reason: Optional[str] = None
    due_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchDataQuality(BaseModel):
    """Low-sensitive quality summary for the artifact inputs."""

    level: ResearchQualityLevel = "unknown"
    overall_score: Optional[int] = Field(None, ge=0, le=100)
    source_count: int = Field(0, ge=0)
    stale_count: int = Field(0, ge=0)
    missing_blocks: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class ResearchArtifact(BaseModel):
    """Structured report artifact for dashboard, stock detail, monitor and copilot reuse."""

    schema_version: Literal["research-artifact-v1"] = "research-artifact-v1"
    artifact_id: str = Field(..., min_length=1)
    source_report_id: Optional[int] = None
    source_query_id: Optional[str] = None
    created_at: Optional[str] = None
    subject: ResearchSubject
    thesis: ResearchThesis
    evidence: List[ResearchEvidenceItem] = Field(default_factory=list)
    invalidation_conditions: List[ResearchInvalidationCondition] = Field(..., min_length=1)
    next_actions: List[ResearchNextAction] = Field(default_factory=list)
    data_quality: ResearchDataQuality = Field(default_factory=ResearchDataQuality)
    metadata: Dict[str, Any] = Field(default_factory=dict)
