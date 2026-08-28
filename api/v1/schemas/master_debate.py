# -*- coding: utf-8 -*-
"""Master debate API schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

MasterDebateMarket = Literal["cn", "hk", "us", "jp", "kr", "tw"]


class MasterDebateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=32)
    name: Optional[str] = Field(None, max_length=64)
    market: MasterDebateMarket
    context: Optional[str] = None
    analysis_history_id: Optional[int] = Field(None, gt=0)
    persist: bool = True


class MasterDebatePersona(BaseModel):
    persona_id: str
    name: str
    english_name: str
    philosophy: str
    stance: str
    confidence: float
    thesis: str
    key_points: List[str] = Field(default_factory=list)
    key_levels: Dict[str, Any] = Field(default_factory=dict)
    risk: str


class MasterDebateResponse(BaseModel):
    id: Optional[int] = None
    code: str
    name: Optional[str] = None
    market: str
    consensus: str
    divergence: int
    conviction: int
    bull_count: int
    bear_count: int
    neutral_count: int
    bull_arguments: List[str] = Field(default_factory=list)
    bear_arguments: List[str] = Field(default_factory=list)
    personas: List[MasterDebatePersona] = Field(default_factory=list)
    summary: str


class MasterDebateRecordItem(BaseModel):
    id: int
    code: str
    name: Optional[str] = None
    market: str
    consensus: str
    divergence: int
    bull_count: int
    bear_count: int
    neutral_count: int
    personas: List[MasterDebatePersona] = Field(default_factory=list)
    summary: Optional[str] = None
    created_at: Optional[str] = None


class MasterDebateListResponse(BaseModel):
    items: List[MasterDebateRecordItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
