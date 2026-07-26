"""Typed contract for the public strategy synthesis projection."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, FiniteFloat


StrategySignal = Literal["strong_buy", "buy", "hold", "sell", "strong_sell"]
ConsensusLevel = Literal["high", "medium", "low", "insufficient"]
ConflictSeverity = Literal["none", "low", "medium", "high"]


class StrategyOpinionItem(BaseModel):
    skill_id: str
    agent_name: str = ""
    signal: StrategySignal
    confidence: FiniteFloat = 0.0
    applied_weight: Optional[FiniteFloat] = None
    reasoning: str = ""
    score_adjustment: FiniteFloat = 0.0
    conditions_met: List[str] = Field(default_factory=list)
    invalid_signal: bool = False


class StrategySignalDistributionBucket(BaseModel):
    count: int = 0
    weight_share: Optional[FiniteFloat] = None


class StrategySignalDistribution(BaseModel):
    bullish: StrategySignalDistributionBucket
    neutral: StrategySignalDistributionBucket
    bearish: StrategySignalDistributionBucket


class StrategyConflictItem(BaseModel):
    conflict_type: str
    severity: ConflictSeverity
    description_key: str = ""
    participants: List[str] = Field(default_factory=list)


class StrategySynthesisSummaryParams(BaseModel):
    opinion_count: int = 0
    total_opinion_count: int = 0
    invalid_opinion_count: int = 0
    final_signal: StrategySignal
    consensus_level: ConsensusLevel
    conflict_severity: ConflictSeverity
    conflict_count: int = 0


class StrategyDeliberationAgendaItem(BaseModel):
    agenda_id: str
    conflict_type: str
    severity: ConflictSeverity
    participants: List[str] = Field(default_factory=list)
    question_key: str = ""


class StrategyDeliberationResponseItem(BaseModel):
    agenda_id: str
    skill_id: str
    stance: Literal["defend", "challenge"]
    revision: Literal["unchanged", "softened"]
    original_signal: StrategySignal
    revised_signal: StrategySignal
    original_confidence: FiniteFloat = 0.0
    revised_confidence: FiniteFloat = 0.0
    critique_key: str = ""


class StrategyDeliberationSummary(BaseModel):
    resolution_status: Literal["unresolved", "partially_resolved"]
    resolved_conflict_count: int = 0
    unresolved_conflict_count: int = 0
    minority_view_preserved: bool = False
    confidence_adjustment: FiniteFloat = 0.0
    confidence_adjustment_reason_key: str = ""


class StrategyDeliberationRound(BaseModel):
    round: int
    source_mode: str
    status: str
    changed_response_count: int = 0
    confidence_adjustment: FiniteFloat = 0.0


class StrategyDeliberation(BaseModel):
    status: str
    mode: str
    rounds: int = 0
    agenda: List[StrategyDeliberationAgendaItem] = Field(default_factory=list)
    responses: List[StrategyDeliberationResponseItem] = Field(default_factory=list)
    summary: StrategyDeliberationSummary
    round_history: List[StrategyDeliberationRound] = Field(default_factory=list)


class StrategyRevisionProjection(BaseModel):
    status: Literal["computed"]
    mode: Literal["preview_only"]
    source_mode: str = ""
    projected_signal: StrategySignal
    projected_weighted_score: FiniteFloat
    projected_confidence: FiniteFloat
    projected_original_confidence: FiniteFloat
    projected_conflict_count: int = 0
    projected_conflict_severity: ConflictSeverity
    projected_consensus_level: ConsensusLevel
    changed_skill_count: int = 0
    changed_skills: List[str] = Field(default_factory=list)
    final_signal_overridden: Literal[False] = False


class StrategySynthesis(BaseModel):
    schema_version: Literal["strategy-synthesis-v1"]
    final_signal: StrategySignal
    weighted_score: FiniteFloat
    confidence: FiniteFloat
    original_confidence: FiniteFloat
    conflict_count: int = 0
    conflict_severity: ConflictSeverity
    conflicts: List[StrategyConflictItem] = Field(default_factory=list)
    supporting_skills: List[StrategyOpinionItem] = Field(default_factory=list)
    opposing_skills: List[StrategyOpinionItem] = Field(default_factory=list)
    signal_distribution: StrategySignalDistribution
    primary_dissent: Optional[StrategyOpinionItem] = None
    consensus_level: ConsensusLevel
    summary_key: str
    summary_params: StrategySynthesisSummaryParams
    deliberation: Optional[StrategyDeliberation] = None
    revision_projection: Optional[StrategyRevisionProjection] = None
