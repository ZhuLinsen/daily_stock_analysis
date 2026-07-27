# -*- coding: utf-8 -*-
"""Internal, low-sensitivity facts produced by the multi-agent runtime.

These types are intentionally separate from report schemas.  They describe
what happened inside an Agent run without publishing reasoning, raw payloads,
errors, tokens, or a user-facing final explanation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, Tuple

from src.agent.protocols import (
    AgentContext,
    AgentOpinion,
    StageFailureReason,
    normalize_stage_failure_reason,
)

if TYPE_CHECKING:
    from src.agent.risk_override import RiskOverrideApplication


_BULLISH_SIGNALS = {"strong_buy", "buy"}
_RISK_AGENT_NAMES = {"risk"}


@dataclass(frozen=True)
class BaseAgentOpinionFact:
    """Prompt-safe projection of one independently executed upstream opinion."""

    agent: str
    signal: str
    confidence: float


@dataclass(frozen=True)
class SkillOpinionFact:
    """Low-sensitivity snapshot of one valid individual skill opinion."""

    skill_id: str
    signal: str
    confidence: float
    observed_at: Optional[float] = None
    skill_version: Optional[str] = None
    horizon: Optional[str] = None


class DegradationBoundary(str, Enum):
    """Whether an incomplete stage failed or never started."""

    DURING_STAGE = "during_stage"
    BEFORE_STAGE = "before_stage"


@dataclass(frozen=True)
class DegradedEvent:
    """Low-sensitivity fact for a stage that did not complete normally."""

    stage: str
    reason: StageFailureReason
    boundary: DegradationBoundary

    def __post_init__(self) -> None:
        normalized_stage = str(self.stage or "").strip()
        if not normalized_stage:
            raise ValueError("degraded event requires a stage")
        object.__setattr__(self, "stage", normalized_stage)
        object.__setattr__(self, "reason", normalize_stage_failure_reason(self.reason))
        object.__setattr__(self, "boundary", DegradationBoundary(self.boundary))


@dataclass(frozen=True)
class PipelineTerminationFact:
    """Pipeline deadline fact with the latest completed stage, when any."""

    reason: StageFailureReason
    last_completed_stage: Optional[str] = None

    def __post_init__(self) -> None:
        normalized_reason = normalize_stage_failure_reason(self.reason)
        if normalized_reason != StageFailureReason.TIMEOUT:
            raise ValueError("pipeline termination currently supports timeout only")
        normalized_stage = str(self.last_completed_stage or "").strip() or None
        object.__setattr__(self, "reason", normalized_reason)
        object.__setattr__(self, "last_completed_stage", normalized_stage)


@dataclass(frozen=True)
class AgentRuntimeFacts:
    """Immutable internal snapshot carried by ``AgentResult``.

    This object is not inserted into dashboard JSON or report schemas.  A
    later pipeline layer may consume it to build a final public explanation,
    but this module does not define that public contract.
    """

    base_agent_opinions: Tuple[BaseAgentOpinionFact, ...] = ()
    skill_opinions: Tuple[SkillOpinionFact, ...] = ()
    degraded_events: Tuple[DegradedEvent, ...] = ()
    pipeline_termination: Optional[PipelineTerminationFact] = None
    risk_override_application: Optional[RiskOverrideApplication] = None


def build_agent_runtime_facts(ctx: AgentContext) -> AgentRuntimeFacts:
    """Build a validated low-sensitivity snapshot from an Agent context."""
    return AgentRuntimeFacts(
        base_agent_opinions=tuple(_iter_base_agent_opinions(ctx)),
        skill_opinions=tuple(_iter_skill_opinions(ctx)),
        degraded_events=tuple(_iter_degraded_events(ctx)),
        pipeline_termination=_pipeline_termination(ctx),
        risk_override_application=_risk_override_application(ctx),
    )


def _iter_base_agent_opinions(ctx: AgentContext):
    for opinion in ctx.opinions:
        if not _is_base_agent_opinion(opinion):
            continue
        signal = _effective_signal(opinion.agent_name, opinion.signal)
        if signal is None:
            continue
        yield BaseAgentOpinionFact(
            agent=str(opinion.agent_name or "unknown"),
            signal=signal,
            confidence=_safe_confidence(opinion.confidence),
        )


def _is_base_agent_opinion(opinion: AgentOpinion) -> bool:
    from src.agent.skills.defaults import is_skill_consensus_name

    agent_name = str(opinion.agent_name or "").strip().lower()
    return agent_name != "decision" and not is_skill_consensus_name(agent_name)


def _iter_skill_opinions(ctx: AgentContext):
    """Yield the latest valid opinion for each individual skill.

    The orchestrator has already partitioned invalid skill opinions before
    runtime facts are built on normal and degraded specialist paths.  This
    projection validates again so custom/legacy executors cannot persist an
    invalid signal as a neutral sample.
    """
    from src.agent.protocols import normalize_strategy_signal
    from src.agent.skills.defaults import (
        extract_skill_id,
        is_skill_agent_name,
        is_skill_consensus_name,
    )

    latest = {}
    for opinion in ctx.opinions:
        if is_skill_consensus_name(opinion.agent_name) or not is_skill_agent_name(
            opinion.agent_name
        ):
            continue
        skill_id = extract_skill_id(opinion.agent_name)
        signal, invalid, _ = normalize_strategy_signal(opinion.signal)
        confidence = _valid_skill_confidence(opinion)
        if not skill_id or invalid or confidence is None:
            continue
        latest[skill_id] = SkillOpinionFact(
            skill_id=skill_id,
            signal=signal,
            confidence=round(confidence, 2),
            observed_at=_safe_timestamp(opinion.timestamp),
        )
    yield from latest.values()


def _iter_degraded_events(ctx: AgentContext):
    source = ctx.meta.get("degraded_events")
    if not isinstance(source, list):
        return

    seen = set()
    for item in source:
        if isinstance(item, DegradedEvent):
            event = item
        elif isinstance(item, dict):
            try:
                event = DegradedEvent(
                    stage=item.get("stage", ""),
                    reason=item.get("reason", StageFailureReason.STAGE_FAILURE),
                    boundary=item.get("boundary", ""),
                )
            except (TypeError, ValueError):
                continue
        else:
            continue
        key = (event.stage, event.reason, event.boundary)
        if key in seen:
            continue
        seen.add(key)
        yield event


def _pipeline_termination(ctx: AgentContext) -> Optional[PipelineTerminationFact]:
    source = ctx.meta.get("pipeline_termination")
    if isinstance(source, PipelineTerminationFact):
        return source
    if not isinstance(source, dict):
        return None
    try:
        return PipelineTerminationFact(
            reason=source.get("reason", ""),
            last_completed_stage=source.get("last_completed_stage", ""),
        )
    except (TypeError, ValueError):
        return None


def _risk_override_application(ctx: AgentContext) -> Optional[RiskOverrideApplication]:
    from src.agent.risk_override import RiskOverrideApplication

    application = ctx.meta.get("risk_override_application")
    return application if isinstance(application, RiskOverrideApplication) else None


def _effective_signal(agent_name: str, signal: Any) -> Optional[str]:
    """Apply the base-opinion semantics established in PR #2021."""
    from src.agent.protocols import normalize_strategy_signal

    normalized, invalid, _ = normalize_strategy_signal(signal)
    if invalid:
        return None
    if _is_risk_agent(agent_name) and normalized in _BULLISH_SIGNALS:
        return "hold"
    return normalized


def _is_risk_agent(agent_name: str) -> bool:
    return str(agent_name or "").strip().lower() in _RISK_AGENT_NAMES


def _safe_confidence(confidence: Any) -> float:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        value = 0.0
    return round(max(0.0, min(1.0, value)), 2)


def _valid_skill_confidence(opinion: AgentOpinion) -> Optional[float]:
    """Reject invalid skill confidence instead of converting it into a sample."""
    if not opinion.confidence_input_valid:
        return None
    confidence = opinion.confidence
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    try:
        value = float(confidence)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        return None
    return value


def _safe_timestamp(value: Any) -> Optional[float]:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return timestamp if timestamp > 0 else None


__all__ = [
    "AgentRuntimeFacts",
    "BaseAgentOpinionFact",
    "DegradationBoundary",
    "DegradedEvent",
    "PipelineTerminationFact",
    "SkillOpinionFact",
    "build_agent_runtime_facts",
]
