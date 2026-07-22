# -*- coding: utf-8 -*-
"""
SkillAggregator — weighted aggregation of skill opinions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.agent.memory import AgentMemory
from src.agent.protocols import AgentContext, AgentOpinion, StrategyConflict, StrategyOpinion
from src.agent.skills.defaults import (
    SKILL_CONSENSUS_AGENT_NAME,
    extract_skill_id,
    is_skill_agent_name,
)
from src.agent.skills.synthesis import (
    ConflictDetector,
    StrategySynthesizer,
    strategy_opinion_from_agent_opinion,
    strategy_signal_score,
)

logger = logging.getLogger(__name__)

_MIN_BACKTEST_SAMPLES = 30

_SCORE_TO_SIGNAL = [
    (4.5, "strong_buy"),
    (3.5, "buy"),
    (2.5, "hold"),
    (1.5, "sell"),
    (0.0, "strong_sell"),
]


@dataclass
class AggregationData:
    skill_opinions: List[AgentOpinion] = field(default_factory=list)
    weights: List[float] = field(default_factory=list)
    skill_names: List[str] = field(default_factory=list)
    strategy_opinions: List[StrategyOpinion] = field(default_factory=list)
    weighted_score: float = 3.0
    weighted_confidence: float = 0.0
    insufficient_evidence: bool = False
    conflicts: List[StrategyConflict] = field(default_factory=list)
    final_signal: str = "hold"
    individual_signals: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    total_adjustment: float = 0.0


class SkillAggregator:
    """Aggregate multiple skill-agent opinions into one consensus."""

    def aggregate(
        self,
        ctx: AgentContext,
        min_samples: int = _MIN_BACKTEST_SAMPLES,
    ) -> Optional[AgentOpinion]:
        aggregation = self.calculate(ctx.opinions, min_samples=min_samples)
        if aggregation is None:
            return None

        invalid_count = sum(1 for opinion in aggregation.strategy_opinions if opinion.invalid_signal)
        synthesis = StrategySynthesizer().synthesize(
            aggregation.strategy_opinions,
            weighted_score=aggregation.weighted_score,
            final_signal=aggregation.final_signal,
            weighted_confidence=aggregation.weighted_confidence,
            conflicts=aggregation.conflicts,
            insufficient_evidence=aggregation.insufficient_evidence,
            invalid_count=invalid_count,
        )
        return self.build_consensus_opinion(aggregation, synthesis)

    def calculate(
        self,
        opinions: List[AgentOpinion],
        min_samples: int = _MIN_BACKTEST_SAMPLES,
    ) -> Optional[AggregationData]:
        skill_opinions = [op for op in opinions if is_skill_agent_name(op.agent_name)]
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

        strategy_opinions = [
            strategy_opinion_from_agent_opinion(op)
            for op in skill_opinions
        ]

        valid_opinions_with_weights = [
            (op, strategy, weight)
            for op, strategy, weight in zip(skill_opinions, strategy_opinions, weights)
            if not strategy.invalid_signal
        ]
        valid_weight_sum = sum(weight for _, _, weight in valid_opinions_with_weights)
        insufficient_evidence = (
            not valid_opinions_with_weights or valid_weight_sum <= 0
        )
        if not insufficient_evidence:
            weighted_score = sum(
                strategy_signal_score(strategy.signal) * weight
                for _, strategy, weight in valid_opinions_with_weights
            ) / valid_weight_sum
            weighted_confidence = sum(
                op.confidence * weight
                for op, _, weight in valid_opinions_with_weights
            ) / valid_weight_sum
        else:
            weighted_score = 3.0
            weighted_confidence = 0.0
        total_adjustment = sum(
            op.raw_data.get("score_adjustment", 0)
            for op, strategy, weight in valid_opinions_with_weights
            if isinstance(op.raw_data.get("score_adjustment"), (int, float))
        )

        if insufficient_evidence:
            final_signal = "hold"
        else:
            final_signal = "hold"
            for threshold, signal in _SCORE_TO_SIGNAL:
                if weighted_score >= threshold:
                    final_signal = signal
                    break

        conflicts = ConflictDetector().detect(strategy_opinions, final_signal=final_signal)
        individual_signals = {
            op.agent_name: {
                "signal": strategy.signal,
                "confidence": op.confidence,
                "original_signal": strategy.original_signal,
                "invalid_signal": strategy.invalid_signal,
            }
            for op, strategy in zip(skill_opinions, strategy_opinions)
        }
        return AggregationData(
            skill_opinions=skill_opinions,
            weights=weights,
            skill_names=skill_ids,
            strategy_opinions=strategy_opinions,
            weighted_score=weighted_score,
            weighted_confidence=weighted_confidence,
            insufficient_evidence=insufficient_evidence,
            conflicts=conflicts,
            final_signal=final_signal,
            individual_signals=individual_signals,
            total_adjustment=total_adjustment,
        )

    @staticmethod
    def build_consensus_opinion(
        aggregation: AggregationData,
        synthesis: Dict[str, Any],
    ) -> AgentOpinion:
        reasoning_parts = [
            f"Skill consensus from {len(aggregation.skill_opinions)} skills "
            f"({', '.join(aggregation.skill_names)}): weighted score {aggregation.weighted_score:.2f}/5.0, "
            f"consensus={synthesis['consensus_level']}, conflicts={synthesis['conflict_severity']}({synthesis['conflict_count']})"
        ]
        for opinion, weight in zip(aggregation.skill_opinions, aggregation.weights):
            name = extract_skill_id(opinion.agent_name) or opinion.agent_name
            reasoning_parts.append(f"  - {name}: {opinion.signal} ({opinion.confidence:.0%}) weight={weight:.2f}")

        return AgentOpinion(
            agent_name=SKILL_CONSENSUS_AGENT_NAME,
            signal=aggregation.final_signal,
            confidence=synthesis["confidence"],
            reasoning="\n".join(reasoning_parts),
            raw_data={
                "weighted_score": round(aggregation.weighted_score, 2),
                "total_adjustment": aggregation.total_adjustment,
                "skill_count": len(aggregation.skill_opinions),
                "individual_signals": aggregation.individual_signals,
                "strategy_synthesis": synthesis,
                "conflicts": synthesis["conflicts"],
                "conflict_count": synthesis["conflict_count"],
                "conflict_severity": synthesis["conflict_severity"],
                "consensus_level": synthesis["consensus_level"],
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
