# -*- coding: utf-8 -*-
"""Pydantic schemas for backtest performance attribution (Brinson model)."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class StrategyGroupAttribution(BaseModel):
    """Attribution metrics for a single strategy group."""

    strategy: str
    stock_count: int
    portfolio_weight: float = Field(description="Weight in the strategy portfolio")
    benchmark_weight: float = Field(description="Weight in the benchmark")
    portfolio_return_pct: float = Field(description="Average simulated return %")
    benchmark_return_pct: float = Field(description="Average buy-and-hold return %")
    contribution_pct: float = Field(description="Contribution to total excess return %")
    win_rate: float = Field(default=0.0, description="Fraction of winning trades")
    selection_effect: float = 0.0
    timing_effect: float = 0.0
    interaction_effect: float = 0.0


class BrinsonAttribution(BaseModel):
    """Brinson decomposition of excess return."""

    selection_effect: float = Field(description="Stock selection effect %")
    timing_effect: float = Field(description="Timing/allocation effect %")
    interaction_effect: float = Field(description="Interaction effect %")
    total_excess_return: float = Field(description="Total excess return vs benchmark %")
    benchmark_return_pct: float = Field(description="Benchmark (buy-and-hold) return %")
    portfolio_return_pct: float = Field(description="Strategy portfolio return %")


class BacktestAttributionResult(BaseModel):
    """Full attribution result for a set of backtest results."""

    brinson: BrinsonAttribution
    strategy_groups: List[StrategyGroupAttribution] = Field(default_factory=list)
    total_results: int = 0
    eval_window_days: Optional[int] = None
    attribution_basis: str = Field(
        default="operation_advice",
        description="Field used to group strategies",
    )
