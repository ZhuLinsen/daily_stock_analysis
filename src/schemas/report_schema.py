# -*- coding: utf-8 -*-
"""
===================================
Report Engine - Pydantic Schema
===================================

Defines AnalysisReportSchema for validating LLM JSON output.
Aligns with SYSTEM_PROMPT in src/analyzer.py.
Uses Optional for lenient parsing; business-layer integrity checks are separate.
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class PositionAdvice(BaseModel):
    """Position advice for no-position vs has-position."""

    no_position: Optional[str] = None
    has_position: Optional[str] = None


class CoreConclusion(BaseModel):
    """Core conclusion block."""

    one_sentence: Optional[str] = None
    signal_type: Optional[str] = None
    time_sensitivity: Optional[str] = None
    position_advice: Optional[PositionAdvice] = None


class TrendStatus(BaseModel):
    """Trend status."""

    ma_alignment: Optional[str] = None
    is_bullish: Optional[bool] = None
    trend_score: Optional[Union[int, float, str]] = None


class PricePosition(BaseModel):
    """Price position (may contain N/A strings)."""

    current_price: Optional[Union[int, float, str]] = None
    ma5: Optional[Union[int, float, str]] = None
    ma10: Optional[Union[int, float, str]] = None
    ma20: Optional[Union[int, float, str]] = None
    bias_ma5: Optional[Union[int, float, str]] = None
    bias_status: Optional[str] = None
    support_level: Optional[Union[int, float, str]] = None
    resistance_level: Optional[Union[int, float, str]] = None


class VolumeAnalysis(BaseModel):
    """Volume analysis."""

    volume_ratio: Optional[Union[int, float, str]] = None
    volume_status: Optional[str] = None
    turnover_rate: Optional[Union[int, float, str]] = None
    volume_meaning: Optional[str] = None


class ChipStructure(BaseModel):
    """Chip structure."""

    profit_ratio: Optional[Union[int, float, str]] = None
    avg_cost: Optional[Union[int, float, str]] = None
    concentration: Optional[Union[int, float, str]] = None
    chip_health: Optional[str] = None


class DataPerspective(BaseModel):
    """Data perspective block."""

    trend_status: Optional[TrendStatus] = None
    price_position: Optional[PricePosition] = None
    volume_analysis: Optional[VolumeAnalysis] = None
    chip_structure: Optional[ChipStructure] = None


class Intelligence(BaseModel):
    """Intelligence block."""

    latest_news: Optional[str] = None
    risk_alerts: Optional[List[str]] = None
    positive_catalysts: Optional[List[str]] = None
    earnings_outlook: Optional[str] = None
    sentiment_summary: Optional[str] = None


class SniperPoints(BaseModel):
    """Sniper points (ideal_buy, stop_loss, etc.)."""

    ideal_buy: Optional[Union[str, int, float]] = None
    secondary_buy: Optional[Union[str, int, float]] = None
    stop_loss: Optional[Union[str, int, float]] = None
    take_profit: Optional[Union[str, int, float]] = None


class PositionStrategy(BaseModel):
    """Position strategy."""

    suggested_position: Optional[str] = None
    entry_plan: Optional[str] = None
    risk_control: Optional[str] = None


class BattlePlan(BaseModel):
    """Battle plan block."""

    sniper_points: Optional[SniperPoints] = None
    position_strategy: Optional[PositionStrategy] = None
    action_checklist: Optional[List[str]] = None


class Dashboard(BaseModel):
    """Dashboard block."""

    core_conclusion: Optional[CoreConclusion] = None
    data_perspective: Optional[DataPerspective] = None
    intelligence: Optional[Intelligence] = None
    battle_plan: Optional[BattlePlan] = None


class AnalysisReportSchema(BaseModel):
    """
    Top-level schema for LLM report JSON.
    Aligns with SYSTEM_PROMPT output format.
    """

    model_config = ConfigDict(extra="allow")  # Allow extra fields from LLM

    stock_name: Optional[str] = None
    sentiment_score: Optional[int] = Field(None, ge=0, le=100)
    trend_prediction: Optional[str] = None
    operation_advice: Optional[str] = None
    decision_type: Optional[str] = None
    confidence_level: Optional[str] = None

    dashboard: Optional[Dashboard] = None

    analysis_summary: Optional[str] = None
    key_points: Optional[str] = None
    risk_warning: Optional[str] = None
    buy_reason: Optional[str] = None

    trend_analysis: Optional[str] = None
    short_term_outlook: Optional[str] = None
    medium_term_outlook: Optional[str] = None
    technical_analysis: Optional[str] = None
    ma_analysis: Optional[str] = None
    volume_analysis: Optional[str] = None
    pattern_analysis: Optional[str] = None
    fundamental_analysis: Optional[str] = None
    sector_position: Optional[str] = None
    company_highlights: Optional[str] = None
    news_summary: Optional[str] = None
    market_sentiment: Optional[str] = None
    hot_topics: Optional[str] = None

    search_performed: Optional[bool] = None
    data_sources: Optional[str] = None
