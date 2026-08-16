"""Pure domain models for intraday stock picking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class StrategyHit:
    stock_code: str
    strategy_id: str
    strategy_score: float
    source: str = "alphasift"
    stock_name: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    quality_score: Optional[float] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleResult:
    rule_id: str
    matched: bool
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class IntradayMetrics:
    rvol_time: Optional[float] = None
    rvol_confidence: float = 0.0
    price_strength: float = 0.0
    high_position: float = 0.5
    pullback_from_high_pct: float = 0.0
    sector_score: Optional[float] = None
    breakout_score: Optional[float] = None
    risk_quality_score: Optional[float] = None
    turnover_rate: Optional[float] = None
    limit_state: Optional[str] = None


@dataclass
class IntradayCandidate:
    stock_code: str
    stock_name: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    strategy_hits: list[StrategyHit] = field(default_factory=list)
    confirmations: list[RuleResult] = field(default_factory=list)
    metrics: IntradayMetrics = field(default_factory=IntradayMetrics)
    strategy_score: float = 0.0
    resonance_score: float = 0.0
    penalty_score: float = 0.0
    picker_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DsaAnalysisSummary:
    stock_code: str
    status: str
    dsa_score: Optional[float] = None
    operation_advice: Optional[str] = None
    risk_level: Optional[str] = None
    summary: Optional[str] = None
    task_id: Optional[str] = None


@dataclass
class FinalCandidate:
    candidate: IntradayCandidate
    dsa: Optional[DsaAnalysisSummary]
    final_score: float
