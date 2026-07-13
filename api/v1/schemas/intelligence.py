# -*- coding: utf-8 -*-
"""Intelligence source API schemas."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

SourceTypeValue = Literal["rss", "atom", "newsnow"]
ScopeTypeValue = Literal["symbol", "market", "sector"]
MarketValue = Literal["cn", "hk", "us", "jp", "kr", "tw", "global"]


class IntelligenceSourceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=1, max_length=1000)
    source_type: SourceTypeValue = "rss"
    enabled: bool = True
    scope_type: ScopeTypeValue = "market"
    scope_value: Optional[str] = Field(None, max_length=64)
    market: MarketValue = "cn"
    description: Optional[str] = None


class IntelligenceSourceTemplateCreateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    enabled: Optional[bool] = None
    scope_type: Optional[ScopeTypeValue] = None
    scope_value: Optional[str] = Field(None, max_length=64)
    market: Optional[MarketValue] = None
    description: Optional[str] = None


class IntelligenceDefaultSourcesCreateRequest(BaseModel):
    enabled: Optional[bool] = None


class IntelligenceSourceItem(BaseModel):
    id: int
    name: str
    source_type: str
    url: str
    enabled: bool
    scope_type: str
    scope_value: Optional[str] = None
    market: str
    description: Optional[str] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    last_fetched_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class IntelligenceSourceTemplateItem(BaseModel):
    template_id: str
    name: str
    source_type: str
    url: str
    scope_type: str
    scope_value: Optional[str] = None
    market: str
    description: Optional[str] = None


class IntelligenceSourceListResponse(BaseModel):
    items: List[IntelligenceSourceItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class IntelligenceSourceTemplateListResponse(BaseModel):
    items: List[IntelligenceSourceTemplateItem] = Field(default_factory=list)
    total: int


class IntelligenceDefaultSourceResult(BaseModel):
    created: bool
    source: IntelligenceSourceItem


class IntelligenceDefaultSourceCreateResponse(BaseModel):
    items: List[IntelligenceDefaultSourceResult] = Field(default_factory=list)
    created_count: int
    total: int


class IntelligenceItem(BaseModel):
    id: int
    source_id: Optional[int] = None
    source_name: Optional[str] = None
    source_type: str
    title: str
    summary: Optional[str] = None
    url: str
    source: Optional[str] = None
    published_at: Optional[str] = None
    fetched_at: Optional[str] = None
    scope_type: str
    scope_value: Optional[str] = None
    market: str


class IntelligenceSampleItem(BaseModel):
    title: str
    summary: Optional[str] = None
    url: str
    source: Optional[str] = None
    published_at: Optional[str] = None


class IntelligenceItemListResponse(BaseModel):
    items: List[IntelligenceItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class IntelligenceFetchResponse(BaseModel):
    ok: bool
    source_id: Optional[int] = None
    source_count: Optional[int] = None
    fetched_count: Optional[int] = None
    saved_count: Optional[int] = None
    retention_deleted: Optional[int] = None
    dry_run: Optional[bool] = None
    sample_items: List[IntelligenceSampleItem] = Field(default_factory=list)
    results: Optional[List[dict]] = None
    error: Optional[str] = None


class IntelligenceSourceTestResponse(BaseModel):
    ok: bool
    source: dict
    fetched_count: int
    sample_items: List[IntelligenceSampleItem] = Field(default_factory=list)
