# -*- coding: utf-8 -*-
"""
===================================
股票数据相关模型
===================================

职责：
1. 定义股票实时行情模型
2. 定义历史 K 线数据模型
"""

from typing import Dict, Literal, Optional, List

from pydantic import BaseModel, ConfigDict, Field

from api.v1.schemas.history import HistoryItem
from api.v1.schemas.intelligence import IntelligenceItem
from api.v1.schemas.research_artifact import ResearchArtifact

StockProfileStatus = Literal["fresh", "partial", "unavailable"]


class StockQuote(BaseModel):
    """个股行情快照（issue #771 看板口径：22 字段 + 数据质量元数据）

    22 字段清单（计划默认值 4 钉死，不得增删口径）：
    - 直出 15（UnifiedRealtimeQuote）：price/pre_close/open_price/high/low/volume/
      amount/change_amount/change_pct/amplitude/volume_ratio/turnover_rate/
      change_60d/high_52w/low_52w
    - 派生 3：vwap（amount/volume 均价口径，缺 amount 则 null）、
      bid_ask_ratio（委比%，仅 A 股盘口可得）、trade_count（成交笔数，em 标准接口不可得恒 null）
    - MA 4 档：ma5/ma10/ma20/ma60（历史日线严格全窗，不足 N 条 null）

    多市场降级：缺失一律显式 null 并随 missing_fields 透出，前端以"—"占位，
    不做字段级硬失败。
    """

    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")

    # === 数据质量元数据（随响应透出） ===
    source: Optional[str] = Field(None, description="数据源 token（如 akshare_em/yfinance）")
    fetched_at: Optional[str] = Field(None, description="本系统获取时间（ISO 8601）")
    provider_timestamp: Optional[str] = Field(None, description="行情源时间戳（ISO 8601）")
    is_stale: Optional[bool] = Field(None, description="行情是否超过 realtime_cache_ttl 阈值")
    stale_seconds: Optional[int] = Field(None, description="行情源时间距获取时刻秒数")
    market: Optional[str] = Field(None, description="市场标签（cn/hk/us/jp/kr/tw）")
    currency: Optional[str] = Field(None, description="报价币种")
    data_quality: Optional[str] = Field(None, description="数据质量（ok/partial/unavailable）")
    fallback_from: Optional[str] = Field(None, description="整源 fallback 的失败首选源 token")
    missing_fields: List[str] = Field(
        default_factory=list,
        description="本响应中为 null 的字段名集合（含 provider 缺失与派生不可得）",
    )

    # === 直出 15（UnifiedRealtimeQuote 同名） ===
    price: Optional[float] = Field(None, description="最新价")
    pre_close: Optional[float] = Field(None, description="昨收价")
    open_price: Optional[float] = Field(None, description="开盘价")
    high: Optional[float] = Field(None, description="最高价")
    low: Optional[float] = Field(None, description="最低价")
    volume: Optional[int] = Field(None, description="成交量（股，与历史日线口径一致）")
    amount: Optional[float] = Field(None, description="成交额（元）")
    change_amount: Optional[float] = Field(None, description="涨跌额")
    change_pct: Optional[float] = Field(None, description="涨跌幅 (%)")
    amplitude: Optional[float] = Field(None, description="振幅 (%)")
    volume_ratio: Optional[float] = Field(None, description="量比")
    turnover_rate: Optional[float] = Field(None, description="换手率 (%)")
    change_60d: Optional[float] = Field(None, description="60日涨跌幅 (%)")
    high_52w: Optional[float] = Field(None, description="52周最高")
    low_52w: Optional[float] = Field(None, description="52周最低")

    # === 派生 3 ===
    vwap: Optional[float] = Field(None, description="VWAP（amount/volume 均价口径；缺 amount 则 null）")
    bid_ask_ratio: Optional[float] = Field(None, description="委比 (%)（五档盘口派生，仅 A 股可得，否则 null）")
    trade_count: Optional[int] = Field(None, description="成交笔数（em 标准接口不可得，恒 null）")

    # === MA 4 档（历史日线严格全窗，不足 N 条 null） ===
    ma5: Optional[float] = Field(None, description="MA5（最近 5 条收盘均值，不足 5 条 null）")
    ma10: Optional[float] = Field(None, description="MA10（最近 10 条收盘均值，不足 10 条 null）")
    ma20: Optional[float] = Field(None, description="MA20（最近 20 条收盘均值，不足 20 条 null）")
    ma60: Optional[float] = Field(None, description="MA60（最近 60 条收盘均值，不足 60 条 null）")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "source": "akshare_em",
            "fetched_at": "2024-01-01T15:00:00+08:00",
            "provider_timestamp": "2024-01-01T15:00:00+08:00",
            "is_stale": False,
            "stale_seconds": 0,
            "market": "cn",
            "currency": "CNY",
            "data_quality": "ok",
            "fallback_from": None,
            "missing_fields": ["trade_count"],
            "price": 1800.00,
            "pre_close": 1785.00,
            "open_price": 1785.00,
            "high": 1810.00,
            "low": 1780.00,
            "volume": 10000000,
            "amount": 18000000000,
            "change_amount": 15.00,
            "change_pct": 0.84,
            "amplitude": 1.68,
            "volume_ratio": 1.10,
            "turnover_rate": 0.80,
            "change_60d": 12.5,
            "high_52w": 1900.00,
            "low_52w": 1550.00,
            "vwap": 1800.00,
            "bid_ask_ratio": 8.5,
            "trade_count": None,
            "ma5": 1795.0,
            "ma10": 1780.0,
            "ma20": 1760.0,
            "ma60": 1700.0,
        }
    })


class KLineData(BaseModel):
    """K 线数据点"""
    
    date: str = Field(..., description="日期")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: Optional[float] = Field(None, description="成交量")
    amount: Optional[float] = Field(None, description="成交额")
    change_percent: Optional[float] = Field(None, description="涨跌幅 (%)")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "date": "2024-01-01",
            "open": 1785.00,
            "high": 1810.00,
            "low": 1780.00,
            "close": 1800.00,
            "volume": 10000000,
            "amount": 18000000000,
            "change_percent": 0.84
        }
    })


class ExtractItem(BaseModel):
    """单条提取结果（代码、名称、置信度）"""

    code: Optional[str] = Field(None, description="股票代码，None 表示解析失败")
    name: Optional[str] = Field(None, description="股票名称（如有）")
    confidence: str = Field("medium", description="置信度：high/medium/low")


class ExtractFromImageResponse(BaseModel):
    """图片股票代码提取响应"""

    codes: List[str] = Field(..., description="提取的股票代码（已去重，向后兼容）")
    items: List[ExtractItem] = Field(default_factory=list, description="提取结果明细（代码+名称+置信度）")
    raw_text: Optional[str] = Field(None, description="原始 LLM 响应（调试用）")


class StockHistoryResponse(BaseModel):
    """股票历史行情响应"""
    
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    period: str = Field(..., description="K 线周期")
    data: List[KLineData] = Field(default_factory=list, description="K 线数据列表")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "period": "daily",
            "data": []
        }
    })


class StockProfileQuoteBlock(BaseModel):
    status: StockProfileStatus
    data: Optional[StockQuote] = None
    limitations: List[str] = Field(default_factory=list)


class StockProfileHistoryBlock(BaseModel):
    status: StockProfileStatus
    period: Literal["daily"] = "daily"
    data: List[KLineData] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class StockProfileResearchData(BaseModel):
    latest_report: Optional[HistoryItem] = None
    recent_reports: List[HistoryItem] = Field(default_factory=list)
    structured_report: Optional[ResearchArtifact] = None


class StockProfileResearchBlock(BaseModel):
    status: StockProfileStatus
    data: StockProfileResearchData = Field(default_factory=StockProfileResearchData)
    limitations: List[str] = Field(default_factory=list)


class StockProfileIntelligenceBlock(BaseModel):
    status: StockProfileStatus
    items: List[IntelligenceItem] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


class StockProfilePortfolioRelation(BaseModel):
    held: bool = False
    matched_markets: List[str] = Field(default_factory=list)


class StockProfilePortfolioBlock(BaseModel):
    status: StockProfileStatus
    data: StockProfilePortfolioRelation = Field(default_factory=StockProfilePortfolioRelation)
    limitations: List[str] = Field(default_factory=list)


class StockProfileMonitorData(BaseModel):
    total_rule_count: int = 0
    enabled_rule_count: int = 0
    rule_ids: List[int] = Field(default_factory=list)


class StockProfileMonitorBlock(BaseModel):
    status: StockProfileStatus
    data: StockProfileMonitorData = Field(default_factory=StockProfileMonitorData)
    limitations: List[str] = Field(default_factory=list)


class StockProfileEvidenceQuality(BaseModel):
    status: StockProfileStatus
    blocks: Dict[str, StockProfileStatus] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


class StockProfileResponse(BaseModel):
    requested_code: str
    canonical_code: str
    market: Literal["cn", "hk", "us", "jp", "kr", "tw"]
    as_of: str
    quote: StockProfileQuoteBlock
    history: StockProfileHistoryBlock
    research: StockProfileResearchBlock
    intelligence: StockProfileIntelligenceBlock
    portfolio: StockProfilePortfolioBlock
    monitors: StockProfileMonitorBlock
    evidence_quality: StockProfileEvidenceQuality
