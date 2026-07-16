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

from src.agent.disagreement import (
    BaseDisagreementType,
    DecisionPath,
    DegradedReason,
    classify_base_disagreement,
    derive_decision_path,
)
from src.agent.protocols import Signal
from src.agent.risk_override import (
    DashboardDecisionSignal,
    RiskApplicationReason,
    RiskTrigger,
    classify_risk_application_reason,
    validate_risk_application_transition,
)


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


class AgentOpinionSummary(BaseModel):
    """Low-sensitivity projection of one pre-decision agent opinion."""

    model_config = ConfigDict(extra="forbid")

    agent: str = Field(..., min_length=1)
    signal: Signal
    confidence: float = Field(..., ge=0.0, le=1.0)


class BaseDisagreement(BaseModel):
    """Opinion-only disagreement facts with a deterministically derived type."""

    model_config = ConfigDict(extra="forbid")

    type: BaseDisagreementType
    agents: List[AgentOpinionSummary]

    @model_validator(mode="after")
    def validate_type_matches_agents(self) -> "BaseDisagreement":
        expected = classify_base_disagreement(agent.signal.value for agent in self.agents)
        if self.type != expected:
            raise ValueError(f"base disagreement type must be {expected.value} for the supplied agents")
        return self


class RiskControlOutcome(BaseModel):
    """Final risk-control result after evaluating the post-decision dashboard signal."""

    model_config = ConfigDict(extra="forbid")

    evidence_present: bool
    override_enabled: bool
    trigger: RiskTrigger
    applied: bool
    reason: RiskApplicationReason
    final_signal: DashboardDecisionSignal
    from_signal: Optional[DashboardDecisionSignal] = None
    to_signal: Optional[DashboardDecisionSignal] = None

    @model_validator(mode="after")
    def validate_application_state(self) -> "RiskControlOutcome":
        validate_risk_application_transition(
            applied=self.applied,
            reason=self.reason,
            final_signal=self.final_signal,
            from_signal=self.from_signal,
            to_signal=self.to_signal,
        )
        if self.applied and not self.override_enabled:
            raise ValueError("applied risk control requires override_enabled=true")

        if not self.evidence_present and self.trigger != RiskTrigger.NONE:
            raise ValueError("risk trigger requires risk evidence")

        expected_reason = classify_risk_application_reason(
            evidence_present=self.evidence_present,
            trigger=self.trigger,
            override_enabled=self.override_enabled,
            applied=self.applied,
        )
        if self.reason != expected_reason:
            raise ValueError(f"risk application reason must be {expected_reason.value} for the supplied facts")

        if self.reason == RiskApplicationReason.FINAL_SIGNAL_ALREADY_WITHIN_RISK_LIMIT:
            if (
                self.trigger == RiskTrigger.RISK_VETO
                and self.final_signal == DashboardDecisionSignal.BUY
            ):
                raise ValueError("buy is not within an enabled risk veto limit")
            if (
                self.trigger == RiskTrigger.RISK_DOWNGRADE
                and self.final_signal != DashboardDecisionSignal.SELL
            ):
                raise ValueError("only sell is unchanged by an enabled risk downgrade")
        return self


class DegradedEvent(BaseModel):
    """Low-sensitivity runtime degradation fact."""

    model_config = ConfigDict(extra="forbid")

    stage: str = Field(..., min_length=1)
    reason: DegradedReason


class AgentDisagreementExplanation(BaseModel):
    """Three orthogonal explanation facts plus their deterministic decision path."""

    model_config = ConfigDict(extra="forbid")

    base_disagreement: BaseDisagreement
    risk_control: RiskControlOutcome
    degraded_events: List[DegradedEvent]
    decision_path: DecisionPath

    @model_validator(mode="after")
    def validate_decision_path(self) -> "AgentDisagreementExplanation":
        expected = derive_decision_path(
            self.base_disagreement.type,
            self.risk_control.reason,
            has_degraded_events=bool(self.degraded_events),
        )
        if self.decision_path != expected:
            raise ValueError(f"decision_path must be {expected.value} for the supplied facts")
        return self


class Dashboard(BaseModel):
    """Dashboard block."""

    core_conclusion: Optional[CoreConclusion] = None
    data_perspective: Optional[DataPerspective] = None
    intelligence: Optional[Intelligence] = None
    battle_plan: Optional[BattlePlan] = None
    phase_decision: Optional[PhaseDecision] = None
    signal_attribution: Optional[SignalAttribution] = None
    agent_disagreement_explanation: Optional[AgentDisagreementExplanation] = None


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
