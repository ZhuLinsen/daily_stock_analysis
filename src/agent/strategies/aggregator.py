# -*- coding: utf-8 -*-
"""
StrategyAggregator — weighted aggregation of strategy opinions.

Takes multiple :class:`AgentOpinion` from strategy agents and produces
a single consensus opinion with confidence-weighted signal.

Weighting factors:
1. Strategy confidence (self-reported by each strategy agent)
2. Historical performance (backtest win-rate, if samples >= min threshold)
3. Market regime match score (from router context)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from src.agent.memory import AgentMemory
from src.agent.protocols import AgentContext, AgentOpinion

logger = logging.getLogger(__name__)

# Minimum backtest samples to use historical weighting
_MIN_BACKTEST_SAMPLES = 30

# Signal → numeric score for weighted averaging
_SIGNAL_SCORES: Dict[str, float] = {
    "strong_buy": 5.0,
    "buy": 4.0,
    "hold": 3.0,
    "sell": 2.0,
    "strong_sell": 1.0,
}

_SCORE_TO_SIGNAL = [
    (4.5, "strong_buy"),
    (3.5, "buy"),
    (2.5, "hold"),
    (1.5, "sell"),
    (0.0, "strong_sell"),
]


class StrategyAggregator:
    """Aggregate multiple strategy agent opinions into one consensus.

    Usage::

        aggregator = StrategyAggregator()
        consensus = aggregator.aggregate(ctx)  # reads ctx.opinions for strategy_* agents
    """

    def aggregate(
        self,
        ctx: AgentContext,
        min_samples: int = _MIN_BACKTEST_SAMPLES,
    ) -> Optional[AgentOpinion]:
        """Aggregate strategy opinions from ``ctx.opinions``.

        Returns a consensus ``AgentOpinion`` or ``None`` if no strategy
        opinions are found.
        """
        strategy_opinions = [
            op for op in ctx.opinions
            if op.agent_name.startswith("strategy_")
        ]
        if not strategy_opinions:
            return None

        strategy_ids = [op.agent_name.replace("strategy_", "") for op in strategy_opinions]
        memory = AgentMemory.from_config()
        perf_weights = (
            memory.compute_strategy_weights(
                strategy_ids,
                use_backtest=self._use_backtest_autoweight(),
            )
            if memory.enabled
            else {}
        )

        # Build weights
        weights: List[float] = []
        for op in strategy_opinions:
            strategy_id = op.agent_name.replace("strategy_", "")
            w = self._compute_weight(
                op,
                min_samples,
                perf_weight=perf_weights.get(strategy_id),
            )
            weights.append(w)

        total_weight = sum(weights) or 1.0

        # Weighted signal score
        weighted_score = sum(
            _SIGNAL_SCORES.get(op.signal, 3.0) * w
            for op, w in zip(strategy_opinions, weights)
        ) / total_weight

        # Weighted confidence
        weighted_confidence = sum(
            op.confidence * w
            for op, w in zip(strategy_opinions, weights)
        ) / total_weight

        # Score adjustment from strategy raw_data
        total_adjustment = sum(
            op.raw_data.get("score_adjustment", 0)
            for op in strategy_opinions
            if isinstance(op.raw_data.get("score_adjustment"), (int, float))
        )

        # Map score back to signal
        final_signal = "hold"
        for threshold, signal in _SCORE_TO_SIGNAL:
            if weighted_score >= threshold:
                final_signal = signal
                break

        # Build reasoning summary
        strategy_names = [op.agent_name.replace("strategy_", "") for op in strategy_opinions]
        reasoning_parts = [
            f"Strategy consensus from {len(strategy_opinions)} strategies "
            f"({', '.join(strategy_names)}): weighted score {weighted_score:.2f}/5.0"
        ]
        for op, w in zip(strategy_opinions, weights):
            name = op.agent_name.replace("strategy_", "")
            reasoning_parts.append(f"  - {name}: {op.signal} ({op.confidence:.0%}) weight={w:.2f}")

        consensus = AgentOpinion(
            agent_name="strategy_consensus",
            signal=final_signal,
            confidence=min(1.0, weighted_confidence),
            reasoning="\n".join(reasoning_parts),
            raw_data={
                "weighted_score": round(weighted_score, 2),
                "total_adjustment": total_adjustment,
                "strategy_count": len(strategy_opinions),
                "individual_signals": {
                    op.agent_name: {"signal": op.signal, "confidence": op.confidence}
                    for op in strategy_opinions
                },
            },
        )
        return consensus

    def _compute_weight(
        self,
        opinion: AgentOpinion,
        min_samples: int,
        perf_weight: Optional[float] = None,
    ) -> float:
        """Compute the aggregation weight for one strategy opinion.

        Weight = confidence × backtest_factor.
        """
        base_weight = opinion.confidence  # 0.0–1.0

        if perf_weight is not None:
            return base_weight * perf_weight

        # Backtest performance multiplier
        bt_factor = self._backtest_factor(opinion.agent_name, min_samples)

        return base_weight * bt_factor

    @staticmethod
    def _backtest_factor(agent_name: str, min_samples: int) -> float:
        """Look up backtest win-rate for a strategy; return a multiplier.

        - If win-rate data exists and samples >= threshold: factor = 0.5 + win_rate
        - Otherwise: factor = 1.0 (neutral)
        """
        if not StrategyAggregator._use_backtest_autoweight():
            return 1.0
        strategy_id = agent_name.replace("strategy_", "")
        try:
            from src.services.backtest_service import BacktestService
            service = BacktestService()
            summary = service.get_strategy_summary(strategy_id)
            if summary and summary.get("total_evaluations", 0) >= min_samples:
                win_rate = summary.get("win_rate", 0.5)
                # Range: 0.5 (0% win) to 1.5 (100% win)
                return 0.5 + win_rate
        except Exception:
            pass
        return 1.0  # neutral factor

    @staticmethod
    def _use_backtest_autoweight() -> bool:
        """Read whether historical backtest weighting is enabled."""
        try:
            from src.config import get_config
            config = get_config()
            return getattr(config, "agent_strategy_autoweight", True)
        except Exception:
            return True
