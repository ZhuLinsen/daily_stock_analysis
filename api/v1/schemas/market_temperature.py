# -*- coding: utf-8 -*-
"""Market temperature API schemas."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

MarketTemperatureMarket = Literal["cn", "hk", "us", "jp", "kr", "tw"]


class MarketTemperatureDimension(BaseModel):
    key: str
    name: str
    score: int
    available: bool


class MarketTemperatureComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: MarketTemperatureMarket
    trade_date: Optional[str] = Field(None, description="YYYY-MM-DD，缺省为今天")
    advancers: Optional[int] = Field(None, ge=0)
    decliners: Optional[int] = Field(None, ge=0)
    limit_up: Optional[int] = Field(None, ge=0)
    limit_down: Optional[int] = Field(None, ge=0)
    new_high_52w: Optional[int] = Field(None, ge=0)
    new_low_52w: Optional[int] = Field(None, ge=0)
    northbound_net: Optional[float] = Field(None, description="北向资金净流入（亿元）")
    margin_change_pct: Optional[float] = Field(None, description="两融余额单日变化（%）")
    turnover_pct: Optional[float] = Field(None, ge=0, description="换手率（%）")
    index_pct_chg: Optional[float] = Field(None, description="指数单日涨跌（%）")


class MarketTemperatureComputeResponse(BaseModel):
    market: str
    trade_date: str
    score: int
    label: str
    label_key: str
    dimensions: List[MarketTemperatureDimension] = Field(default_factory=list)
    available_dimensions: int
    reasons: List[str] = Field(default_factory=list)
    guidance: str
    source: Optional[str] = Field(None, description="温度来源：market_stats=实时全市场宽度；tracked_universe=本地自选股兜底")


class MarketTemperatureSnapshotItem(BaseModel):
    id: int
    market: str
    trade_date: str
    score: int
    label: str
    dimensions: List[MarketTemperatureDimension] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    guidance: Optional[str] = None
    created_at: Optional[str] = None


class MarketTemperatureListResponse(BaseModel):
    items: List[MarketTemperatureSnapshotItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class MarketDashboardIndex(BaseModel):
    code: str = ""
    name: str = ""
    change_pct: Optional[float] = None


class MarketDashboardBreadth(BaseModel):
    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    limit_up_count: int = 0
    limit_down_count: int = 0
    total_amount: float = 0.0


class MarketDashboardSectorItem(BaseModel):
    name: str
    change_pct: Optional[float] = None


class MarketDashboardSectorGroup(BaseModel):
    top: List[MarketDashboardSectorItem] = Field(default_factory=list)
    bottom: List[MarketDashboardSectorItem] = Field(default_factory=list)


class MarketDashboardFlowItem(BaseModel):
    name: str
    net_inflow: Optional[float] = None


class MarketDashboardFlowGroup(BaseModel):
    top: List[MarketDashboardFlowItem] = Field(default_factory=list)
    bottom: List[MarketDashboardFlowItem] = Field(default_factory=list)


class MarketDashboardCapitalFlow(BaseModel):
    status: str = "unavailable"
    sector_rankings: MarketDashboardFlowGroup = Field(default_factory=MarketDashboardFlowGroup)


class MarketDashboardCandidate(BaseModel):
    code: str
    name: str
    sector: str = ""
    sector_change_pct: Optional[float] = None
    change_pct: Optional[float] = None
    price: Optional[float] = None
    reason: str = ""


class MarketDashboardResponse(BaseModel):
    market: str
    trade_date: str = ""
    temperature: Optional[MarketTemperatureComputeResponse] = None
    indices: List[MarketDashboardIndex] = Field(default_factory=list)
    breadth: MarketDashboardBreadth = Field(default_factory=MarketDashboardBreadth)
    hot_sectors: MarketDashboardSectorGroup = Field(default_factory=MarketDashboardSectorGroup)
    hot_concepts: MarketDashboardSectorGroup = Field(default_factory=MarketDashboardSectorGroup)
    capital_flow: MarketDashboardCapitalFlow = Field(default_factory=MarketDashboardCapitalFlow)
    candidates: List[MarketDashboardCandidate] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    generated_at: Optional[str] = None
