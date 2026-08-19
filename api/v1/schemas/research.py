# -*- coding: utf-8 -*-
"""Research OS API schemas. No order or broker fields."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ResearchJobCreateRequest(BaseModel):
    subject: str = Field(..., min_length=1, description="研究标的")
    market: str = ""
    as_of: str = ""
    horizons: Optional[List[str]] = None
    authorization_context: str = ""
    idempotency_key: str = ""
    wait: bool = True

    model_config = ConfigDict(extra="forbid")


class ResearchHorizonView(BaseModel):
    horizon: str
    conclusion: str = ""
    stance: str = "abstain"
    action_boundary: str = ""
    confidence: float = 0.0
    evidence_ids: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    abstain_reason: str = ""


class ResearchConflictView(BaseModel):
    claim_text: str = ""
    conflicting_providers: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    conflict_type: str = ""
    resolution_status: str = ""
    reason_cannot_average: str = ""


class ResearchDecisionView(BaseModel):
    as_of: str = ""
    short_term: ResearchHorizonView
    medium_term: ResearchHorizonView
    long_term: ResearchHorizonView
    conflicts: List[ResearchConflictView] = Field(default_factory=list)
    provider_versions: Dict[str, str] = Field(default_factory=dict)


class ResearchJobResponse(BaseModel):
    job_id: str
    task_id: str
    status: str
    idempotency_key: str = ""
    subject: str
    market: str = ""
    as_of: str = ""
    created_at: str = ""
    updated_at: str = ""
    decision: Optional[ResearchDecisionView] = None
    warnings: List[str] = Field(default_factory=list)
    error: str = ""


class ResearchJobListResponse(BaseModel):
    jobs: List[ResearchJobResponse]


def job_response_from_public(payload: Dict[str, Any]) -> ResearchJobResponse:
    return ResearchJobResponse.model_validate(payload)
