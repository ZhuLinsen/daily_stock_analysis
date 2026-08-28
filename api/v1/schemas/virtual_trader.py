# -*- coding: utf-8 -*-
"""Virtual trader API schemas."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VirtualTraderPositionItem(_StrictModel):
    id: int
    stock_code: str
    name: Optional[str] = None
    market: str
    currency: str
    quantity: float
    avg_cost: float
    last_price: Optional[float] = None
    market_value: Optional[float] = None
    market_value_cny: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    realized_pnl: float = 0.0
    status: str
    opened_at: Optional[str] = None


class VirtualTraderAccountResponse(_StrictModel):
    account_id: int
    name: str
    status: str
    initial_cash_cny: float
    cash_cny: float
    cash_hkd: float
    cash_usd: float
    cash_total_cny: float
    positions: List[VirtualTraderPositionItem]
    positions_value_cny: float
    total_value_cny: float
    total_return_pct: float
    created_at: Optional[str] = None


class VirtualTraderTradeItem(_StrictModel):
    id: int
    stock_code: str
    market: str
    side: str
    quantity: float
    price: float
    fee: float
    currency: str
    reason: Optional[str] = None
    trade_date: str
    traded_at: Optional[str] = None


class VirtualTraderTradeListResponse(_StrictModel):
    items: List[VirtualTraderTradeItem]
    total: int
    page: int
    page_size: int


class VirtualTraderPredictionItem(_StrictModel):
    id: int
    stock_code: str
    market: str
    direction: str
    anchor_date: str
    horizon_days: int
    target_price: float
    entry_price: float
    rationale: Optional[str] = None
    status: str
    outcome: Optional[str] = None
    actual_return_pct: Optional[float] = None
    window_high: Optional[float] = None
    window_low: Optional[float] = None


class VirtualTraderPredictionListResponse(_StrictModel):
    items: List[VirtualTraderPredictionItem]
    total: int
    page: int
    page_size: int


class VirtualTraderEquityPoint(_StrictModel):
    trade_date: str
    total_value_cny: float
    daily_return_pct: Optional[float] = None
    positions_count: int = 0


class VirtualTraderEquityCurveResponse(_StrictModel):
    points: List[VirtualTraderEquityPoint]
    initial_cash_cny: float


class VirtualTraderStatsResponse(_StrictModel):
    prediction: dict
    total_trades: int
    sell_trades: int
    buy_trades: int
    win_rate_pct: Optional[float] = None  # 已平仓 realized_pnl>0 占比
    realized_pnl_total: float


class VirtualTraderRunRequest(_StrictModel):
    market: Optional[str] = Field(None, description="仅执行单一市场（cn/hk/us），为空执行全部")
    force: bool = False


class VirtualTraderRunResponse(_StrictModel):
    results: List[dict]


class VirtualTraderResetRequest(_StrictModel):
    confirm: bool = Field(False, description="必须显式传 true 才会重置")


class VirtualTraderResetResponse(_StrictModel):
    success: bool
    account_id: int
