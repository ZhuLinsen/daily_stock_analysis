# -*- coding: utf-8 -*-
"""Internal, low-sensitivity facts produced by the multi-agent runtime.

These types are intentionally separate from report schemas.  They describe
what happened inside an Agent run without publishing reasoning, raw payloads,
errors, tokens, or a user-facing final explanation.
"""

from __future__ import annotations

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
    degraded_events: Tuple[DegradedEvent, ...] = ()
    pipeline_termination: Optional[PipelineTerminationFact] = None
    risk_override_application: Optional[RiskOverrideApplication] = None


def build_agent_runtime_facts(ctx: AgentContext) -> AgentRuntimeFacts:
    """Build a validated low-sensitivity snapshot from an Agent context."""
    return AgentRuntimeFacts(
        base_agent_opinions=tuple(_iter_base_agent_opinions(ctx)),
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


__all__ = [
    "AgentRuntimeFacts",
    "BaseAgentOpinionFact",
    "DegradationBoundary",
    "DegradedEvent",
    "PipelineTerminationFact",
    "build_agent_runtime_facts",
]
