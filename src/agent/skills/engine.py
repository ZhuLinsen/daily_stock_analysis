# -*- coding: utf-8 -*-
"""
StrategyEngine — authoritative multi-strategy pipeline facade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.agent.protocols import AgentOpinion, normalize_strategy_signal
from src.agent.skills.aggregator import AggregationData, SkillAggregator
from src.agent.skills.defaults import (
    LEGACY_STRATEGY_CONSENSUS_AGENT_NAME,
    SKILL_CONSENSUS_AGENT_NAME,
    extract_skill_id,
    is_skill_agent_name,
)
from src.agent.skills.synthesis import StrategySynthesizer

logger = logging.getLogger(__name__)


class StrategyResultStatus(str, Enum):
    CONSENSUS = "consensus"
    NO_CONSENSUS = "no_consensus"
    NO_SKILLS = "no_skills"


@dataclass
class EvidencePartition:
    valid_skill_opinions: List[AgentOpinion] = field(default_factory=list)
    invalid_records: List[Dict[str, Any]] = field(default_factory=list)
    invalid_count: int = 0
    non_skill_opinions: List[AgentOpinion] = field(default_factory=list)
    evidence_opinions: List[AgentOpinion] = field(default_factory=list)


@dataclass
class StrategyResult:
    status: StrategyResultStatus = StrategyResultStatus.NO_SKILLS
    synthesis_dict: Optional[Dict[str, Any]] = None
    consensus_opinion: Optional[AgentOpinion] = None
    skill_consensus_data: Optional[Dict[str, Any]] = None
    valid_skill_opinions: List[AgentOpinion] = field(default_factory=list)
    non_skill_opinions: List[AgentOpinion] = field(default_factory=list)
    evidence_opinions: List[AgentOpinion] = field(default_factory=list)
    invalid_records: List[Dict[str, Any]] = field(default_factory=list)
    invalid_count: int = 0


class StrategyEngine:
    """Centralize the skill-opinion evidence chain into one facade."""

    def __init__(self, aggregator: Optional[SkillAggregator] = None) -> None:
        self.aggregator = aggregator or SkillAggregator()

    def partition_only(self, opinions: List[AgentOpinion]) -> EvidencePartition:
        valid_skill_opinions: List[AgentOpinion] = []
        invalid_records: List[Dict[str, Any]] = []
        non_skill_opinions: List[AgentOpinion] = []
        evidence_opinions: List[AgentOpinion] = []

        for opinion in opinions:
            if opinion.agent_name in {SKILL_CONSENSUS_AGENT_NAME, LEGACY_STRATEGY_CONSENSUS_AGENT_NAME}:
                continue
            if not is_skill_agent_name(opinion.agent_name):
                non_skill_opinions.append(opinion)
                evidence_opinions.append(opinion)
                continue

            raw_data = opinion.raw_data if isinstance(opinion.raw_data, dict) else {}
            raw_signal = opinion.signal if opinion.signal else raw_data.get("signal")
            canonical, invalid_signal, original_signal = normalize_strategy_signal(raw_signal)

            if raw_signal is None or (isinstance(raw_signal, str) and not raw_signal.strip()):
                invalid_records.append({
                    "agent_name": opinion.agent_name,
                    "raw_signal": None if raw_signal is None else raw_signal,
                    "confidence": opinion.confidence,
                    "reason": "missing_signal",
                })
                logger.info(
                    "[StrategyEngine] invalid skill opinion moved to diagnostics: agent=%s raw_signal=%r reason=%s",
                    opinion.agent_name,
                    raw_signal,
                    "missing_signal",
                )
                continue

            if invalid_signal:
                invalid_records.append({
                    "agent_name": opinion.agent_name,
                    "raw_signal": original_signal,
                    "confidence": opinion.confidence,
                    "reason": "unrecognized_signal",
                })
                logger.info(
                    "[StrategyEngine] invalid skill opinion moved to diagnostics: agent=%s raw_signal=%r reason=%s",
                    opinion.agent_name,
                    original_signal,
                    "unrecognized_signal",
                )
                continue

            if canonical != opinion.signal:
                normalized_raw = dict(raw_data)
                normalized_raw.setdefault("original_signal", original_signal)
                normalized_raw["normalized_signal"] = canonical
                source_opinion = opinion
                opinion = AgentOpinion(
                    agent_name=opinion.agent_name,
                    signal=canonical,
                    confidence=opinion.confidence,
                    reasoning=opinion.reasoning,
                    key_levels=dict(opinion.key_levels or {}),
                    raw_data=normalized_raw,
                    timestamp=opinion.timestamp,
                )
                opinion._confidence_input_valid = source_opinion.confidence_input_valid
            valid_skill_opinions.append(opinion)
            evidence_opinions.append(opinion)

        return EvidencePartition(
            valid_skill_opinions=valid_skill_opinions,
            invalid_records=invalid_records,
            invalid_count=len(invalid_records),
            non_skill_opinions=non_skill_opinions,
            evidence_opinions=evidence_opinions,
        )

    def process(
        self,
        opinions: List[AgentOpinion],
        *,
        diagnostic_records: Optional[List[Dict[str, Any]]] = None,
    ) -> StrategyResult:
        partition = self.partition_only(opinions)
        existing_diagnostics = [
            dict(record)
            for record in (diagnostic_records or [])
            if isinstance(record, dict)
        ]
        if existing_diagnostics:
            partition.invalid_records = existing_diagnostics + partition.invalid_records
            partition.invalid_count = len(partition.invalid_records)
        return self.process_partition(partition)

    def process_partition(self, partition: EvidencePartition) -> StrategyResult:
        eligible_skill_opinions: List[AgentOpinion] = []
        invalid_records = list(partition.invalid_records)
        for opinion in partition.valid_skill_opinions:
            if not opinion.confidence_input_valid:
                raw_data = opinion.raw_data if isinstance(opinion.raw_data, dict) else {}
                raw_display = raw_data.get("original_signal") or opinion.signal
                invalid_records.append({
                    "agent_name": opinion.agent_name,
                    "raw_signal": raw_display,
                    "confidence": opinion.confidence,
                    "reason": "invalid_confidence",
                })
                logger.info(
                    "[StrategyEngine] invalid skill opinion moved to diagnostics: agent=%s raw_signal=%r reason=%s",
                    opinion.agent_name,
                    raw_display,
                    "invalid_confidence",
                )
                continue
            eligible_skill_opinions.append(opinion)

        invalid_count = max(partition.invalid_count, len(invalid_records))
        evidence_opinions = list(partition.non_skill_opinions) + list(eligible_skill_opinions)

        if not eligible_skill_opinions:
            if invalid_count > 0:
                stub = self._build_no_consensus_stub(invalid_count)
                return StrategyResult(
                    status=StrategyResultStatus.NO_CONSENSUS,
                    synthesis_dict=stub,
                    skill_consensus_data={
                        "signal": "hold",
                        "confidence": 0.0,
                        "reasoning": "",
                        "raw_data": {},
                        "strategy_synthesis": stub,
                        "conflicts": [],
                    },
                    valid_skill_opinions=[],
                    non_skill_opinions=list(partition.non_skill_opinions),
                    evidence_opinions=list(partition.non_skill_opinions),
                    invalid_records=invalid_records,
                    invalid_count=invalid_count,
                )
            return StrategyResult(
                status=StrategyResultStatus.NO_SKILLS,
                synthesis_dict=None,
                valid_skill_opinions=[],
                non_skill_opinions=list(partition.non_skill_opinions),
                evidence_opinions=list(partition.non_skill_opinions),
                invalid_records=invalid_records,
                invalid_count=invalid_count,
            )

        aggregation = self.aggregator.calculate(eligible_skill_opinions)
        if aggregation is None:
            return StrategyResult(
                status=StrategyResultStatus.NO_SKILLS,
                synthesis_dict=None,
                valid_skill_opinions=list(eligible_skill_opinions),
                non_skill_opinions=list(partition.non_skill_opinions),
                evidence_opinions=evidence_opinions,
                invalid_records=invalid_records,
                invalid_count=invalid_count,
            )

        synthesis = StrategySynthesizer().synthesize(
            aggregation.strategy_opinions,
            weighted_score=aggregation.weighted_score,
            final_signal=aggregation.final_signal,
            weighted_confidence=aggregation.weighted_confidence,
            conflicts=aggregation.conflicts,
            insufficient_evidence=aggregation.insufficient_evidence,
            invalid_count=invalid_count,
        )
        consensus_opinion = self._build_consensus_opinion(aggregation, synthesis)
        return StrategyResult(
            status=StrategyResultStatus.CONSENSUS,
            synthesis_dict=synthesis,
            consensus_opinion=consensus_opinion,
            skill_consensus_data={
                "signal": consensus_opinion.signal,
                "confidence": consensus_opinion.confidence,
                "reasoning": consensus_opinion.reasoning,
                "raw_data": consensus_opinion.raw_data,
                "strategy_synthesis": synthesis,
                "conflicts": synthesis.get("conflicts", []),
            },
            valid_skill_opinions=list(eligible_skill_opinions),
            non_skill_opinions=list(partition.non_skill_opinions),
            evidence_opinions=evidence_opinions,
            invalid_records=invalid_records,
            invalid_count=invalid_count,
        )

    @staticmethod
    def _build_consensus_opinion(aggregation: AggregationData, synthesis: Dict[str, Any]) -> AgentOpinion:
        return SkillAggregator.build_consensus_opinion(aggregation, synthesis)

    @staticmethod
    def _build_no_consensus_stub(invalid_count: int) -> Dict[str, Any]:
        return {
            "final_signal": "hold",
            "weighted_score": 3.0,
            "confidence": 0.0,
            "original_confidence": 0.0,
            "conflict_count": 0,
            "conflict_severity": "none",
            "conflicts": [],
            "supporting_skills": [],
            "opposing_skills": [],
            "consensus_level": "insufficient",
            "summary_key": "strategy_synthesis.no_conflicts",
            "summary_params": {
                "opinion_count": 0,
                "total_opinion_count": invalid_count,
                "invalid_opinion_count": invalid_count,
                "final_signal": "hold",
                "consensus_level": "insufficient",
                "conflict_severity": "none",
                "conflict_count": 0,
            },
        }
