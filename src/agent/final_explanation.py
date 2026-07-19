# -*- coding: utf-8 -*-
"""Build the public multi-agent explanation after Pipeline finalization."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, Iterable, Optional, Sequence

from src.agent.protocols import normalize_decision_signal
from src.agent.runtime_facts import AgentRuntimeFacts
from src.schemas.report_schema import AgentDisagreementExplanation


@dataclass(frozen=True)
class PipelineDecisionAdjustment:
    """One real signal transition made after Agent risk application."""

    source: str
    from_signal: str
    to_signal: str

    def __post_init__(self) -> None:
        source = str(self.source or "").strip()
        if not source:
            raise ValueError("pipeline adjustment requires a source")
        from_signal = normalize_decision_signal(self.from_signal)
        to_signal = normalize_decision_signal(self.to_signal)
        if from_signal == to_signal:
            raise ValueError("pipeline adjustment must change the signal")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "from_signal", from_signal)
        object.__setattr__(self, "to_signal", to_signal)


def capture_pipeline_adjustment(
    adjustments: list[PipelineDecisionAdjustment],
    *,
    source: str,
    before: Any,
    after: Any,
) -> None:
    """Append a transition only when a Pipeline step changed the signal."""
    before_signal = normalize_decision_signal(before)
    after_signal = normalize_decision_signal(after)
    if before_signal == after_signal:
        return
    adjustments.append(
        PipelineDecisionAdjustment(
            source=source,
            from_signal=before_signal,
            to_signal=after_signal,
        )
    )


def build_pipeline_final_explanation(
    *,
    runtime_facts: AgentRuntimeFacts,
    pipeline_start_signal: Any,
    final_signal: Any,
    pipeline_adjustments: Sequence[PipelineDecisionAdjustment] = (),
    data_quality: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Return the single validated explanation for the final report signal."""
    normalized_start = normalize_decision_signal(pipeline_start_signal)
    normalized_final = normalize_decision_signal(final_signal)
    opinions = [
        {
            "agent": fact.agent,
            "signal": normalize_decision_signal(fact.signal),
            "confidence": fact.confidence,
        }
        for fact in runtime_facts.base_agent_opinions
    ]
    base_type = _classify_base_disagreement(item["signal"] for item in opinions)
    risk_control = _risk_control_payload(
        runtime_facts,
        pipeline_start_signal=normalized_start,
    )
    degraded_events = [
        {
            "stage": event.stage,
            "reason": event.reason.value,
            "boundary": event.boundary.value,
        }
        for event in runtime_facts.degraded_events
    ]
    termination = runtime_facts.pipeline_termination
    payload: dict[str, Any] = {
        "base_disagreement": {"type": base_type, "agents": opinions},
        "risk_control": risk_control,
        "degraded_events": degraded_events,
        "final_adjustments": [
            {
                "source": item.source,
                "from_signal": item.from_signal,
                "to_signal": item.to_signal,
            }
            for item in pipeline_adjustments
        ],
        "final_signal": normalized_final,
        "decision_path": _decision_path(
            base_type=base_type,
            risk_control=risk_control,
            degraded=bool(degraded_events or termination),
            pipeline_adjustments=pipeline_adjustments,
        ),
    }
    quality_payload = _data_quality_payload(data_quality)
    if quality_payload is not None:
        payload["data_quality"] = quality_payload
    if termination is not None:
        payload["pipeline_termination"] = {
            "reason": termination.reason.value,
            "last_completed_stage": termination.last_completed_stage,
        }
    return AgentDisagreementExplanation.model_validate(payload).model_dump(
        mode="json",
        exclude_none=True,
    )


def _data_quality_payload(value: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    level = str(value.get("level") or "").strip().lower()
    if level not in {"good", "usable", "limited", "poor"}:
        level = "unknown"
    source_limitations = value.get("limitations")
    limitations: list[str] = []
    if isinstance(source_limitations, list):
        for item in source_limitations:
            text = str(item or "").strip()
            if text and text not in limitations:
                limitations.append(text[:200])
    if level == "unknown" and not limitations:
        return None
    return {"level": level, "limitations": limitations[:5]}


def _risk_control_payload(
    runtime_facts: AgentRuntimeFacts,
    *,
    pipeline_start_signal: str,
) -> dict[str, Any]:
    application = runtime_facts.risk_override_application
    if application is None:
        return {
            "evidence_present": False,
            "override_enabled": False,
            "trigger": "none",
            "applied": False,
            "reason": "not_evaluated",
            "post_risk_signal": pipeline_start_signal,
        }
    payload = {
        "evidence_present": application.evidence_present,
        "override_enabled": application.override_enabled,
        "trigger": application.trigger.value,
        "applied": application.applied,
        "reason": application.reason.value,
        "post_risk_signal": application.post_risk_signal.value,
    }
    if application.from_signal is not None:
        payload["from_signal"] = application.from_signal.value
    if application.to_signal is not None:
        payload["to_signal"] = application.to_signal.value
    return payload


def _classify_base_disagreement(signals: Iterable[str]) -> str:
    values = list(signals)
    if len(values) < 2:
        return "insufficient_opinions"
    unique = set(values)
    if unique == {"buy"}:
        return "aligned_bullish"
    if unique == {"sell"}:
        return "aligned_bearish"
    if unique == {"hold"}:
        return "aligned_neutral"
    if unique <= {"buy", "hold"}:
        return "bullish_with_neutral"
    if unique <= {"sell", "hold"}:
        return "bearish_with_neutral"
    return "mixed_directional_signals"


def _decision_path(
    *,
    base_type: str,
    risk_control: dict[str, Any],
    degraded: bool,
    pipeline_adjustments: Sequence[PipelineDecisionAdjustment],
) -> str:
    if pipeline_adjustments:
        return f"{pipeline_adjustments[-1].source}_adjusted"
    if risk_control.get("applied"):
        return str(risk_control["reason"])
    if degraded:
        return "degraded_synthesis"
    if base_type.startswith("aligned_"):
        return "aligned_agent_consensus"
    if base_type == "insufficient_opinions":
        return "limited_opinion_synthesis"
    return "mixed_signals_synthesized"


__all__ = [
    "PipelineDecisionAdjustment",
    "build_pipeline_final_explanation",
    "capture_pipeline_adjustment",
]
