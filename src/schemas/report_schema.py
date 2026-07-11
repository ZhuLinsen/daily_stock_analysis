# -*- coding: utf-8 -*-
"""
===================================
Report Engine - Pydantic Schema
===================================

Defines AnalysisReportSchema for validating LLM JSON output.
Aligns with SYSTEM_PROMPT in src/analyzer.py.
Uses Optional for lenient parsing; business-layer integrity checks are separate.
"""

import math
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class PhaseDecision(BaseModel):
    """Market-phase-aware intraday decision guardrail output."""

    phase_context: Optional[Dict[str, Any]] = None
    action_window: Optional[str] = None
    immediate_action: Optional[str] = None
    watch_conditions: List[str] = Field(default_factory=list)
    next_check_time: Optional[str] = None
    confidence_reason: Optional[str] = None
    data_limitations: List[str] = Field(default_factory=list)


class SignalAttribution(BaseModel):
    """Signal attribution analysis - explains what factors contributed most to the recommendation."""

    technical_indicators: Optional[Union[int, float, str]] = None
    news_sentiment: Optional[Union[int, float, str]] = None
    fundamentals: Optional[Union[int, float, str]] = None
    market_conditions: Optional[Union[int, float, str]] = None
    strongest_bullish_signal: Optional[str] = None
    strongest_bearish_signal: Optional[str] = None

    @model_validator(mode='after')
    def validate_and_normalize_contributions(self) -> 'SignalAttribution':
        """Validate and normalize contribution weights.

        - Try to convert string values to numbers
        - Clamp values to 0-100
        - Normalize non-zero sum to 100 if all four values are valid numbers
        - Preserve all-zero as "no effective signal"
        - Set invalid values to None
        """
        contrib_fields = ['technical_indicators', 'news_sentiment', 'fundamentals', 'market_conditions']
        values = {}

        for field in contrib_fields:
            val = getattr(self, field)
            if val is None:
                values[field] = None
                continue

            # Try to convert string to number
            if isinstance(val, str):
                # Handle "N/A", "null", etc.
                if val.strip().upper() in ('N/A', 'NULL', 'NONE', ''):
                    values[field] = None
                    continue
                # Handle "70%" or "70"
                try:
                    # Remove % sign and convert
                    cleaned = val.replace('%', '').strip()
                    val = float(cleaned)
                except (ValueError, AttributeError):
                    values[field] = None
                    continue

            # Ensure it's a number
            try:
                val = float(val)
            except (TypeError, ValueError):
                values[field] = None
                continue

            if not math.isfinite(val):
                values[field] = None
                continue

            # Clamp to 0-100
            if val < 0:
                val = 0
            if val > 100:
                val = 100

            values[field] = val

        # Normalize to sum = 100 if all values are valid and non-zero
        valid_values = {k: v for k, v in values.items() if v is not None}
        if len(valid_values) == 4:
            total = sum(valid_values.values())
            if total > 0:
                # Normalize non-zero sum to 100
                for field in contrib_fields:
                    if values[field] is not None:
                        values[field] = round(values[field] * 100 / total)

                # Adjust rounding errors to keep non-zero sums at 100
                final_sum = sum(values[f] for f in contrib_fields)
                if final_sum != 100:
                    # Add/subtract the difference to/from the first non-zero value
                    diff = 100 - final_sum
                    for field in contrib_fields:
                        if values[field] > 0:
                            values[field] += diff
                            break

        # Update the model fields
        for field in contrib_fields:
            setattr(self, field, values[field])

        return self


class Dashboard(BaseModel):
    """Dashboard block."""

    core_conclusion: Optional[CoreConclusion] = None
    data_perspective: Optional[DataPerspective] = None
    intelligence: Optional[Intelligence] = None
    battle_plan: Optional[BattlePlan] = None
    phase_decision: Optional[PhaseDecision] = None
    signal_attribution: Optional[SignalAttribution] = None


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
