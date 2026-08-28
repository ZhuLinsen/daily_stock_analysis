# -*- coding: utf-8 -*-
"""Trade journal API schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

TradeJournalSide = Literal["buy", "sell"]
TradeJournalEmotion = Literal["excited", "calm", "fearful", "fomo", "neutral", "regretful"]
TradeJournalMarket = Literal["cn", "hk", "us", "jp", "kr", "tw"]


class TradeJournalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=32)
    name: Optional[str] = Field(None, max_length=64)
    market: TradeJournalMarket
    side: str = Field(..., description="buy/sell（也接受 add/reduce/加仓/减仓 等别名）")
    quantity: float = Field(..., gt=0)
    price: float = Field(..., ge=0)
    fee: float = Field(0.0, ge=0)
    tax: float = Field(0.0, ge=0)
    currency: str = Field("CNY", max_length=8)
    trade_date: str = Field(..., description="YYYY-MM-DD")
    thesis: Optional[str] = None
    strategy: Optional[str] = Field(None, max_length=64)
    emotion: Optional[TradeJournalEmotion] = None
    plan_followed: Optional[bool] = None
    linked_signal_id: Optional[int] = Field(None, gt=0)
    tags: Optional[List[str]] = None


class TradeJournalUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=64)
    side: Optional[str] = None
    quantity: Optional[float] = Field(None, gt=0)
    price: Optional[float] = Field(None, ge=0)
    fee: Optional[float] = Field(None, ge=0)
    tax: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, max_length=8)
    trade_date: Optional[str] = None
    thesis: Optional[str] = None
    strategy: Optional[str] = Field(None, max_length=64)
    emotion: Optional[TradeJournalEmotion] = None
    plan_followed: Optional[bool] = None
    linked_signal_id: Optional[int] = Field(None, gt=0)
    tags: Optional[List[str]] = None


class TradeJournalItem(BaseModel):
    id: int
    code: str
    name: Optional[str] = None
    market: str
    side: str
    quantity: float
    price: float
    fee: float
    tax: float
    currency: str
    trade_date: Optional[str] = None
    thesis: Optional[str] = None
    strategy: Optional[str] = None
    emotion: Optional[str] = None
    plan_followed: Optional[bool] = None
    linked_signal_id: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TradeJournalMutationResponse(BaseModel):
    item: TradeJournalItem


class TradeJournalListResponse(BaseModel):
    items: List[TradeJournalItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class TradeJournalRealizedTrade(BaseModel):
    buy_price: float
    sell_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    entry_date: Optional[str] = None


class TradeJournalPositionPnlResponse(BaseModel):
    market: str
    code: str
    realized_pnl: float
    realized_trades: List[TradeJournalRealizedTrade] = Field(default_factory=list)
    closed_count: int
    open_quantity: float
    avg_cost: Optional[float] = None


class TradeJournalDisciplineResponse(BaseModel):
    entry_id: int
    side: str
    linked_signal_id: Optional[int] = None
    signal_action: Optional[str] = None
    signal_score: Optional[int] = None
    discipline: str


class TradeJournalReviewResponse(BaseModel):
    entry_count: int
    closed_trade_count: int
    win_rate: Optional[int] = None
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    profit_factor: Optional[float] = None
    total_pnl: float
    discipline_score: Optional[int] = None
    plan_declared: int
    plan_followed: int
    linked_signal_count: int
    aligned_count: int
    emotion_breakdown: Dict[str, int] = Field(default_factory=dict)
