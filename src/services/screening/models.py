# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""Data models."""

from typing import Any
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class HardFilterConfig:
    exclude_st: bool = True
    price_min: float | None = None
    price_max: float | None = None
    amount_min: float | None = None
    market_cap_min: float | None = None
    market_cap_max: float | None = None
    pe_ttm_min: float | None = None
    pe_ttm_max: float | None = None
    pb_min: float | None = None
    pb_max: float | None = None
    volume_ratio_min: float | None = None
    turnover_rate_min: float | None = None
    change_pct_min: float | None = None
    change_pct_max: float | None = None
    change_60d_min: float | None = None
    change_60d_max: float | None = None
    require_ma_bullish: bool = False
    require_price_above_ma20: bool = False
    signal_score_min: int | None = None
    macd_status_whitelist: list[str] | None = None
    rsi_status_whitelist: list[str] | None = None
    breakout_20d_pct_min: float | None = None
    breakout_20d_pct_max: float | None = None
    range_20d_pct_max: float | None = None
    volume_ratio_20d_min: float | None = None
    volume_ratio_20d_max: float | None = None
    body_pct_min: float | None = None
    body_pct_max: float | None = None
    pullback_to_ma20_pct_min: float | None = None
    pullback_to_ma20_pct_max: float | None = None
    consolidation_days_20d_min: int | None = None
    consolidation_days_20d_max: int | None = None
    volatility_20d_pct_min: float | None = None
    volatility_20d_pct_max: float | None = None
    max_drawdown_20d_pct_min: float | None = None
    max_drawdown_20d_pct_max: float | None = None
    atr_20_pct_min: float | None = None
    atr_20_pct_max: float | None = None


@dataclass
class ScreeningConfig:
    enabled: bool = False
    market_scope: list[str] = field(default_factory=lambda: ["cn"])
    hard_filters: HardFilterConfig = field(default_factory=HardFilterConfig)
    tech_weight: float = 0.35
    factor_weights: dict[str, float] = field(default_factory=dict)
    scoring_profile: dict[str, Any] = field(default_factory=dict)
    risk_profile: dict[str, Any] = field(default_factory=dict)
    portfolio_profile: dict[str, Any] = field(default_factory=dict)
    scorecard_profile: dict[str, Any] = field(default_factory=dict)
    event_profile: dict[str, Any] = field(default_factory=dict)
    ranking_hints: str = ""
    max_output: int = 5


@dataclass
class StrategyStyle:
    """Human/UI-facing strategy style metadata."""

    risk_profile: str = ""
    holding_period: str = ""
    execution_style: str = ""
    market_regime: list[str] = field(default_factory=list)
    capital_profile: str = ""
    ui_badge: str = ""


@dataclass
class Strategy:
    name: str
    display_name: str
    description: str
    version: str = "1"
    category: str = "trend"
    tags: list[str] = field(default_factory=list)
    analysis_skills: list[str] = field(default_factory=list)
    style: StrategyStyle = field(default_factory=StrategyStyle)
    screening: ScreeningConfig = field(default_factory=ScreeningConfig)


@dataclass
class StrategyInfo:
    """Strategy metadata for list_strategies()."""
    name: str
    display_name: str
    description: str
    version: str
    category: str
    tags: list[str]
    market_scope: list[str]
    analysis_skills: list[str] = field(default_factory=list)
    requires_daily_features: bool = False
    data_requirements: list[str] = field(default_factory=list)
    required_snapshot_fields: list[str] = field(default_factory=list)
    required_daily_fields: list[str] = field(default_factory=list)
    active_filters: list[str] = field(default_factory=list)
    factor_weights: dict[str, float] = field(default_factory=dict)
    profile_keys: dict[str, list[str]] = field(default_factory=dict)
    style: dict[str, object] = field(default_factory=dict)


@dataclass
class Pick:
    rank: int
    code: str
    name: str
    final_score: float
    screen_score: float
    llm_score: float | None = None
    ranking_reason: str = ""
    risk_summary: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    amount: float = 0.0
    total_mv: float | None = None
    turnover_rate: float | None = None
    volume_ratio: float | None = None
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    industry: str = ""
    concepts: str = ""
    industry_rank: int | None = None
    industry_change_pct: float | None = None
    industry_heat_score: float | None = None
    concept_heat_score: float | None = None
    board_heat_score: float | None = None
    board_heat_latest_score: float | None = None
    board_heat_trend_score: float | None = None
    board_heat_persistence_score: float | None = None
    board_heat_cooling_score: float | None = None
    board_heat_observations: int | None = None
    board_heat_state: str = ""
    board_heat_summary: str = ""
    change_60d: float | None = None
    signal_score: float | None = None
    ma_bullish: bool | None = None
    price_above_ma20: bool | None = None
    macd_status: str = ""
    rsi_status: str = ""
    breakout_20d_pct: float | None = None
    range_20d_pct: float | None = None
    volume_ratio_20d: float | None = None
    body_pct: float | None = None
    pullback_to_ma20_pct: float | None = None
    consolidation_days_20d: int | None = None
    volatility_20d_pct: float | None = None
    max_drawdown_20d_pct: float | None = None
    atr_20_pct: float | None = None
    daily_quality_score: float | None = None
    daily_quality_flags: str = ""
    daily_source: str = ""
    factor_scores: dict[str, float] = field(default_factory=dict)
    llm_confidence: float | None = None
    llm_sector: str = ""
    llm_theme: str = ""
    llm_tags: list[str] = field(default_factory=list)
    llm_catalysts: list[str] = field(default_factory=list)
    llm_risks: list[str] = field(default_factory=list)
    llm_thesis: str = ""
    llm_style_fit: str = ""
    llm_watch_items: list[str] = field(default_factory=list)
    llm_invalidators: list[str] = field(default_factory=list)
    risk_score: float | None = None
    risk_level: str = ""
    risk_penalty: float = 0.0
    risk_flags: list[str] = field(default_factory=list)
    excluded_by_risk: bool = False
    portfolio_penalty: float = 0.0
    portfolio_flags: list[str] = field(default_factory=list)
    post_analysis_status: dict[str, str] = field(default_factory=dict)
    post_analysis_summaries: dict[str, str] = field(default_factory=dict)
    post_analysis_score_deltas: dict[str, float] = field(default_factory=dict)
    post_analysis_results: dict[str, Any] = field(default_factory=dict)
    post_analysis_tags: list[str] = field(default_factory=list)
    dsa_context: dict[str, Any] = field(default_factory=dict)
    dsa_news: list[dict[str, Any]] = field(default_factory=list)
    dsa_analysis_summary: str = ""
    deep_analysis_status: str = "not_requested"
    deep_analysis_query_id: str = ""
    deep_analysis_summary: str = ""
    deep_analysis_error: str = ""
    deep_analysis_result: dict[str, Any] | None = None
    deep_analysis_signal_score: int | None = None
    deep_analysis_sentiment_score: int | None = None
    deep_analysis_operation_advice: str = ""
    deep_analysis_trend_prediction: str = ""
    deep_analysis_risk_flags: list[str] = field(default_factory=list)


@dataclass
class ScreenResult:
    strategy: str
    market: str
    strategy_version: str = ""
    strategy_category: str = ""
    snapshot_count: int = 0
    after_filter_count: int = 0
    picks: list[Pick] = field(default_factory=list)
    run_id: str = ""
    llm_ranked: bool = False
    llm_market_view: str = ""
    llm_selection_logic: str = ""
    llm_portfolio_risk: str = ""
    llm_coverage: float | None = None
    llm_parse_errors: list[str] = field(default_factory=list)
    llm_model_used: str = ""
    llm_attempted_models: list[str] = field(default_factory=list)
    llm_failure_reason: str = ""
    ranking_mode: str = "factor"
    degradation: list[str] = field(default_factory=list)
    snapshot_source: str = ""
    source_errors: list[str] = field(default_factory=list)
    deep_analysis_requested: bool = False
    post_analyzers: list[str] = field(default_factory=list)
    daily_enriched: bool = False
    daily_enrich_count: int = 0
    risk_enabled: bool = True
    portfolio_diversity_enabled: bool = True
    portfolio_concentration_notes: list[str] = field(default_factory=list)
    result_variant_applied: bool = False
    result_variant_pool_size: int = 0
    result_variant_rotated_slots: int = 0
    saved_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PickEvaluation:
    code: str
    name: str
    rank: int
    entry_price: float
    current_price: float | None = None
    return_pct: float | None = None
    final_score: float = 0.0
    status: str = "missing"
    llm_sector: str = ""
    llm_theme: str = ""
    llm_tags: list[str] = field(default_factory=list)
    llm_catalysts: list[str] = field(default_factory=list)
    llm_risks: list[str] = field(default_factory=list)
    post_analysis_tags: list[str] = field(default_factory=list)
    risk_level: str = ""
    risk_flags: list[str] = field(default_factory=list)
    portfolio_flags: list[str] = field(default_factory=list)
    shape_status: str = ""
    shape_tags: list[str] = field(default_factory=list)
    path_status: str = ""
    path_days: int | None = None
    path_end_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    max_runup_pct: float | None = None


@dataclass
class EvaluationResult:
    run_id: str
    strategy: str
    market: str
    created_at: str
    evaluated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    elapsed_days: int | None = None
    snapshot_source: str = ""
    source_errors: list[str] = field(default_factory=list)
    picks: list[PickEvaluation] = field(default_factory=list)
    average_return_pct: float | None = None
    median_return_pct: float | None = None
    win_rate: float | None = None
    missing_codes: list[str] = field(default_factory=list)
    degradation: list[str] = field(default_factory=list)
    saved_path: str = ""
