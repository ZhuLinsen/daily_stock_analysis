# -*- coding: utf-8 -*-
"""Market phase summary schemas."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


MarketPhaseValue = Literal[
    "premarket",
    "intraday",
    "lunch_break",
    "closing_auction",
    "postmarket",
    "non_trading",
    "unknown",
]


class MarketPhaseSummary(BaseModel):
    """Low-sensitivity market phase metadata exposed on report meta."""

    market: Optional[str] = Field(None, description="市场区域")
    phase: MarketPhaseValue = Field(..., description="市场阶段")
    market_local_time: Optional[str] = Field(None, description="市场本地时间")
    session_date: Optional[str] = Field(None, description="市场本地日期")
    effective_daily_bar_date: Optional[str] = Field(None, description="最新可复用完整日线日期")
    is_trading_day: Optional[bool] = Field(None, description="是否交易日")
    is_market_open_now: Optional[bool] = Field(None, description="当前是否开市")
    is_partial_bar: Optional[bool] = Field(None, description="最新日线是否可能未完成")
    minutes_to_open: Optional[int] = Field(None, description="距离开盘分钟数")
    minutes_to_close: Optional[int] = Field(None, description="距离收盘分钟数")
    trigger_source: Optional[str] = Field(None, description="触发来源")
    analysis_intent: Optional[str] = Field(None, description="分析意图")
    warnings: List[str] = Field(default_factory=list, description="阶段推断降级告警码")
