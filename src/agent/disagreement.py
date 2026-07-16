# -*- coding: utf-8 -*-
"""
Low-sensitivity disagreement summary for multi-agent decision synthesis.

This module intentionally exposes pure functions only.  The orchestrator owns
when to compute the summary; DecisionAgent owns how to present it to the LLM.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Any, Dict, List

from src.agent.protocols import AgentContext, normalize_decision_signal
from src.agent.risk_override import RiskOverrideApplication, build_risk_override_plan

_BULLISH_SIGNALS = {"strong_buy", "buy"}
_BEARISH_SIGNALS = {"strong_sell", "sell"}
_RISK_AGENT_NAMES = {"risk"}
_SUMMARY_STAGE_LIMIT = 8


class BaseDisagreementType(str, Enum):
    """Finite classifications derived only from normalized agent opinions."""

    INSUFFICIENT_OPINIONS = "insufficient_opinions"
    ALIGNED_BULLISH = "aligned_bullish"
    ALIGNED_BEARISH = "aligned_bearish"
    ALIGNED_NEUTRAL = "aligned_neutral"
    BULLISH_WITH_NEUTRAL = "bullish_with_neutral"
    BEARISH_WITH_NEUTRAL = "bearish_with_neutral"
    MIXED_DIRECTIONAL_SIGNALS = "mixed_directional_signals"


class DegradedReason(str, Enum):
    """Low-sensitivity reasons why a successful dashboard is partial."""

    STAGE_FAILURE = "stage_failure"
    TIMEOUT = "timeout"
    BUDGET_SKIP = "budget_skip"


class DecisionPath(str, Enum):
    """Deterministic synthesis paths exposed in the final explanation."""

    ALIGNED_AGENT_CONSENSUS = "aligned_agent_consensus"
    NON_CONFLICTING_SIGNALS_SYNTHESIZED = "non_conflicting_signals_synthesized"
    MIXED_SIGNALS_SYNTHESIZED = "mixed_signals_synthesized"
    LIMITED_OPINION_SYNTHESIS = "limited_opinion_synthesis"
    RISK_VETO_APPLIED = "risk_veto_applied"
    RISK_DOWNGRADE_APPLIED = "risk_downgrade_applied"
    DEGRADED_SYNTHESIS = "degraded_synthesis"


def classify_base_disagreement(signals: Iterable[Any]) -> BaseDisagreementType:
    """Classify normalized opinion signals without considering risk or degradation."""
    normalized = [_normalize_signal(signal) for signal in signals]
    if len(normalized) <= 1:
        return BaseDisagreementType.INSUFFICIENT_OPINIONS

    bullish = any(signal in _BULLISH_SIGNALS for signal in normalized)
    bearish = any(signal in _BEARISH_SIGNALS for signal in normalized)
    neutral = any(signal == "hold" for signal in normalized)

    if bullish and bearish:
        return BaseDisagreementType.MIXED_DIRECTIONAL_SIGNALS
    if bullish:
        return (
            BaseDisagreementType.BULLISH_WITH_NEUTRAL
            if neutral
            else BaseDisagreementType.ALIGNED_BULLISH
        )
    if bearish:
        return (
            BaseDisagreementType.BEARISH_WITH_NEUTRAL
            if neutral
            else BaseDisagreementType.ALIGNED_BEARISH
        )
    return BaseDisagreementType.ALIGNED_NEUTRAL


def derive_decision_path(
    base_type: BaseDisagreementType,
    risk_application_reason: Any,
    *,
    has_degraded_events: bool,
) -> DecisionPath:
    """Derive the public decision path from the three orthogonal fact dimensions."""
    reason = str(getattr(risk_application_reason, "value", risk_application_reason))
    if reason == DecisionPath.RISK_VETO_APPLIED.value:
        return DecisionPath.RISK_VETO_APPLIED
    if reason == DecisionPath.RISK_DOWNGRADE_APPLIED.value:
        return DecisionPath.RISK_DOWNGRADE_APPLIED
    if has_degraded_events:
        return DecisionPath.DEGRADED_SYNTHESIS

    normalized_type = BaseDisagreementType(base_type)
    if normalized_type == BaseDisagreementType.INSUFFICIENT_OPINIONS:
        return DecisionPath.LIMITED_OPINION_SYNTHESIS
    if normalized_type == BaseDisagreementType.MIXED_DIRECTIONAL_SIGNALS:
        return DecisionPath.MIXED_SIGNALS_SYNTHESIZED
    if normalized_type in {
        BaseDisagreementType.BULLISH_WITH_NEUTRAL,
        BaseDisagreementType.BEARISH_WITH_NEUTRAL,
    }:
        return DecisionPath.NON_CONFLICTING_SIGNALS_SYNTHESIZED
    return DecisionPath.ALIGNED_AGENT_CONSENSUS


def build_agent_disagreement_explanation(
    ctx: AgentContext,
    final_dashboard: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the final explanation strictly from post-run low-sensitivity facts."""
    application = ctx.meta.get("risk_override_application")
    if not isinstance(application, RiskOverrideApplication):
        raise ValueError("final explanation requires a RiskOverrideApplication")

    final_signal = normalize_decision_signal(final_dashboard.get("decision_type", "hold"))
    if application.final_signal.value != final_signal:
        raise ValueError("risk application final_signal does not match the final dashboard")

    agents: List[Dict[str, Any]] = []
    for opinion in ctx.opinions:
        if str(opinion.agent_name or "").strip().lower() == "decision":
            continue
        signal = _effective_signal(opinion.agent_name, opinion.signal)
        agents.append({
            "agent": str(opinion.agent_name or "unknown"),
            "signal": signal,
            "confidence": _safe_confidence(opinion.confidence),
        })

    base_type = classify_base_disagreement(agent["signal"] for agent in agents)
    degraded_events = _build_final_degraded_events(ctx)
    decision_path = derive_decision_path(
        base_type,
        application.reason,
        has_degraded_events=bool(degraded_events),
    )
    return {
        "base_disagreement": {
            "type": base_type,
            "agents": agents,
        },
        "risk_control": application.to_risk_control_dict(),
        "degraded_events": degraded_events,
        "decision_path": decision_path,
    }


def _build_final_degraded_events(ctx: AgentContext) -> List[Dict[str, Any]]:
    """Project runtime degradation markers into their minimal public shape."""
    source = ctx.meta.get("degraded_events")
    if not isinstance(source, list):
        return []

    events: List[Dict[str, Any]] = []
    seen = set()
    for item in source:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or "").strip()
        if not stage:
            continue
        reason = DegradedReason(item.get("reason"))
        dedupe_key = (stage, reason.value)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        events.append({"stage": stage, "reason": reason})
    return events


def build_agent_disagreement_summary(
    ctx: AgentContext,
    *,
    risk_override_enabled: bool = True,
) -> Dict[str, Any]:
    """Build a structured, low-sensitivity summary of prior agent disagreement."""
    buckets = {
        "bullish_agents": [],
        "bearish_agents": [],
        "neutral_agents": [],
    }

    for opinion in ctx.opinions:
        signal = _effective_signal(opinion.agent_name, opinion.signal)
        agent_summary = _summarize_opinion(opinion.agent_name, signal, opinion.confidence)
        if signal in _BULLISH_SIGNALS:
            buckets["bullish_agents"].append(agent_summary)
        elif signal in _BEARISH_SIGNALS:
            buckets["bearish_agents"].append(agent_summary)
        else:
            buckets["neutral_agents"].append(agent_summary)

    risk_override_plan = build_risk_override_plan(
        ctx,
        override_enabled=risk_override_enabled,
    )
    degraded_result = _build_degraded_result(ctx)
    conflict_type = _classify_conflict_type(
        buckets["bullish_agents"],
        buckets["bearish_agents"],
        buckets["neutral_agents"],
        risk_override_plan.override_enabled and risk_override_plan.override_trigger_present,
        degraded_result,
    )

    return {
        **buckets,
        "conflict_type": conflict_type,
        "decision_path_hint": _decision_path_hint(conflict_type),
        "risk_override_present": risk_override_plan.override_enabled
        and risk_override_plan.override_trigger_present,
        "risk_control": risk_override_plan.to_low_sensitivity_dict(),
        "degraded_result": degraded_result,
    }


def _summarize_opinion(agent_name: str, signal: Any, confidence: Any) -> Dict[str, Any]:
    """Keep only low-sensitivity opinion metadata for downstream synthesis."""
    return {
        "agent_name": str(agent_name or "unknown"),
        "signal": _normalize_signal(signal),
        "confidence": _safe_confidence(confidence),
    }


def _normalize_signal(signal: Any) -> str:
    if not isinstance(signal, str):
        return "hold"
    normalized = signal.strip().lower()
    if normalized in _BULLISH_SIGNALS or normalized in _BEARISH_SIGNALS or normalized == "hold":
        return normalized
    return "hold"


def _effective_signal(agent_name: str, signal: Any) -> str:
    normalized = _normalize_signal(signal)
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


def _build_degraded_result(ctx: AgentContext) -> Dict[str, Any]:
    stages = list(_iter_degraded_stages(ctx))
    has_non_critical = any(stage.get("non_critical") is True for stage in stages)
    return {
        "present": bool(stages),
        "non_critical_stage_present": has_non_critical,
        "stages": stages[:_SUMMARY_STAGE_LIMIT],
    }


def _iter_degraded_stages(ctx: AgentContext) -> Iterable[Dict[str, Any]]:
    source = ctx.meta.get("degraded_stages")
    if not isinstance(source, list):
        return

    seen = set()
    for item in source:
        if not isinstance(item, dict):
            continue
        stage_name = str(item.get("stage_name") or "").strip()
        status = str(item.get("status") or "").strip().lower()
        if not stage_name or status != "failed":
            continue
        dedupe_key = (stage_name, status)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        yield {
            "stage_name": stage_name,
            "status": status,
            "non_critical": item.get("non_critical") is True,
        }


def _classify_conflict_type(
    bullish_agents: List[Dict[str, Any]],
    bearish_agents: List[Dict[str, Any]],
    neutral_agents: List[Dict[str, Any]],
    risk_override_present: bool,
    degraded_result: Dict[str, Any],
) -> str:
    if risk_override_present:
        return "risk_override"
    if bullish_agents and bearish_agents:
        return "mixed_directional_signals"
    if degraded_result.get("present"):
        if bullish_agents and not bearish_agents:
            return "partial_bullish_with_degraded_inputs"
        if bearish_agents and not bullish_agents:
            return "partial_bearish_with_degraded_inputs"
        return "degraded_only"
    if bullish_agents and not bearish_agents:
        return "aligned_bullish" if not neutral_agents else "bullish_with_neutral"
    if bearish_agents and not bullish_agents:
        return "aligned_bearish" if not neutral_agents else "bearish_with_neutral"
    if neutral_agents:
        return "aligned_neutral"
    return "insufficient_opinions"


def _decision_path_hint(conflict_type: str) -> str:
    hints = {
        "risk_override": "prioritize_risk_controls_and_cap_buy_signal",
        "mixed_directional_signals": "explain_cross_agent_conflict_before_final_signal",
        "degraded_only": "state_data_limitations_before_recommendation",
        "partial_bullish_with_degraded_inputs": "state_degraded_inputs_before_any_bullish_lean",
        "partial_bearish_with_degraded_inputs": "state_degraded_inputs_before_any_bearish_lean",
        "aligned_bullish": "use_bullish_consensus_with_price_and_risk_checks",
        "bullish_with_neutral": "lean_bullish_but_require_confirmation",
        "aligned_bearish": "use_bearish_consensus_and_preserve_downside_controls",
        "bearish_with_neutral": "lean_defensive_and_require_recovery_confirmation",
        "aligned_neutral": "prefer_hold_watchlist_or_range_plan",
        "insufficient_opinions": "prefer_conservative_hold_due_to_limited_agent_input",
    }
    return hints.get(conflict_type, "prefer_conservative_hold_due_to_mixed_inputs")


__all__ = [
    "BaseDisagreementType",
    "DecisionPath",
    "DegradedReason",
    "build_agent_disagreement_explanation",
    "build_agent_disagreement_summary",
    "classify_base_disagreement",
    "derive_decision_path",
]
