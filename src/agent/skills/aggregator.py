# -*- coding: utf-8 -*-
"""
SkillAggregator — weighted aggregation of skill opinions.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from src.agent.memory import AgentMemory
from src.agent.protocols import AgentContext, AgentOpinion
from src.agent.skills.defaults import (
    SKILL_CONSENSUS_AGENT_NAME,
    extract_skill_id,
    is_skill_agent_name,
)

logger = logging.getLogger(__name__)

_MIN_BACKTEST_SAMPLES = 30

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


class SkillAggregator:
    """Aggregate multiple skill-agent opinions into one consensus."""

    def aggregate(
        self,
        ctx: AgentContext,
        min_samples: int = _MIN_BACKTEST_SAMPLES,
    ) -> Optional[AgentOpinion]:
        skill_opinions = [op for op in ctx.opinions if is_skill_agent_name(op.agent_name)]
        if not skill_opinions:
            return None

        skill_ids = [extract_skill_id(op.agent_name) or op.agent_name for op in skill_opinions]
        memory = AgentMemory.from_config()
        perf_weights = (
            memory.compute_skill_weights(
                skill_ids,
                use_backtest=self._use_backtest_autoweight(),
            )
            if memory.enabled
            else {}
        )

        weights: List[float] = []
        for op in skill_opinions:
            skill_id = extract_skill_id(op.agent_name) or op.agent_name
            weight = self._compute_weight(
                op,
                min_samples,
                perf_weight=perf_weights.get(skill_id),
            )
            weights.append(weight)

        total_weight = sum(weights) or 1.0
        weighted_score = sum(
            _SIGNAL_SCORES.get(op.signal, 3.0) * weight
            for op, weight in zip(skill_opinions, weights)
        ) / total_weight
        weighted_confidence = sum(
            op.confidence * weight
            for op, weight in zip(skill_opinions, weights)
        ) / total_weight
        total_adjustment = sum(
            op.raw_data.get("score_adjustment", 0)
            for op in skill_opinions
            if isinstance(op.raw_data.get("score_adjustment"), (int, float))
        )

        final_signal = "hold"
        for threshold, signal in _SCORE_TO_SIGNAL:
            if weighted_score >= threshold:
                final_signal = signal
                break

        skill_names = [extract_skill_id(op.agent_name) or op.agent_name for op in skill_opinions]
        reasoning_parts = [
            f"Skill consensus from {len(skill_opinions)} skills "
            f"({', '.join(skill_names)}): weighted score {weighted_score:.2f}/5.0"
        ]
        for op, weight in zip(skill_opinions, weights):
            name = extract_skill_id(op.agent_name) or op.agent_name
            reasoning_parts.append(f"  - {name}: {op.signal} ({op.confidence:.0%}) weight={weight:.2f}")

        return AgentOpinion(
            agent_name=SKILL_CONSENSUS_AGENT_NAME,
            signal=final_signal,
            confidence=min(1.0, weighted_confidence),
            reasoning="\n".join(reasoning_parts),
            raw_data={
                "weighted_score": round(weighted_score, 2),
                "total_adjustment": total_adjustment,
                "skill_count": len(skill_opinions),
                "individual_signals": {
                    op.agent_name: {"signal": op.signal, "confidence": op.confidence}
                    for op in skill_opinions
                },
            },
        )

    def _compute_weight(
        self,
        opinion: AgentOpinion,
        min_samples: int,
        perf_weight: Optional[float] = None,
    ) -> float:
        base_weight = opinion.confidence
        if perf_weight is not None:
            return base_weight * perf_weight
        return base_weight * self._backtest_factor(opinion.agent_name, min_samples)

    @staticmethod
    def _backtest_factor(agent_name: str, min_samples: int) -> float:
        if not SkillAggregator._use_backtest_autoweight():
            return 1.0

        skill_id = extract_skill_id(agent_name) or agent_name
        try:
            from src.services.backtest_service import BacktestService

            service = BacktestService()
            summary = service.get_skill_summary(skill_id)
            if summary and summary.get("total_evaluations", 0) >= min_samples:
                win_rate = summary.get("win_rate", 0.5)
                return 0.5 + win_rate
        except Exception:
            logger.debug("Failed to compute backtest factor for %s", agent_name, exc_info=True)
        return 1.0

    @staticmethod
    def _use_backtest_autoweight() -> bool:
        try:
            from src.config import get_config

            config = get_config()
            return getattr(config, "agent_skill_autoweight", True)
        except Exception:
            logger.debug("Failed to get backtest autoweight config, defaulting to True", exc_info=True)
            return True


StrategyAggregator = SkillAggregator
