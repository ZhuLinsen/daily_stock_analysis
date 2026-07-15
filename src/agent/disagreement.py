# -*- coding: utf-8 -*-
"""Low-sensitivity disagreement summaries for the multi-agent pipeline."""

from __future__ import annotations

from typing import Any, Dict, List

from src.agent.protocols import AgentContext
from src.agent.risk_override import build_risk_override_plan

_BULLISH_SIGNALS = {"strong_buy", "buy"}
_BEARISH_SIGNALS = {"strong_sell", "sell"}
_RISK_AGENT_NAMES = {"risk"}
_SUMMARY_EVENT_LIMIT = 8


def build_agent_disagreement_summary(
    ctx: AgentContext,
    *,
    risk_override_enabled: bool = True,
) -> Dict[str, Any]:
    """Build the prompt-facing summary from low-sensitivity runtime facts."""
    base = summarize_agent_opinions(ctx, include_decision=False)
    risk_plan = build_risk_override_plan(
        ctx,
        override_enabled=risk_override_enabled,
    )
    degraded_events = list(ctx.meta.get("degraded_events") or [])[:_SUMMARY_EVENT_LIMIT]
    degraded_result = {
        "present": bool(degraded_events),
        "events": degraded_events,
    }
    conflict_type = _classify_conflict_type(
        base["bullish_agents"],
        base["bearish_agents"],
        base["neutral_agents"],
        risk_plan.override_enabled and risk_plan.override_trigger_present,
        degraded_result,
    )

    return {
        "bullish_agents": base["bullish_agents"],
        "bearish_agents": base["bearish_agents"],
        "neutral_agents": base["neutral_agents"],
        "conflict_type": conflict_type,
        "decision_path_hint": _decision_path_hint(conflict_type),
        "risk_override_present": risk_plan.override_enabled
        and risk_plan.override_trigger_present,
        "risk_control": risk_plan.to_low_sensitivity_dict(),
        "degraded_result": degraded_result,
    }


def summarize_agent_opinions(
    ctx: AgentContext,
    *,
    include_decision: bool = False,
) -> Dict[str, Any]:
    """Summarize AgentOpinion objects without exposing reasoning or raw data."""
    bullish_agents: List[Dict[str, Any]] = []
    bearish_agents: List[Dict[str, Any]] = []
    neutral_agents: List[Dict[str, Any]] = []

    for opinion in ctx.opinions:
        if not include_decision and opinion.agent_name.lower() == "decision":
            continue
        signal = _effective_signal(opinion.agent_name, opinion.signal)
        item = {
            "agent_name": opinion.agent_name,
            "signal": signal,
            "confidence": round(opinion.confidence, 2),
        }
        if signal in _BULLISH_SIGNALS:
            bullish_agents.append(item)
        elif signal in _BEARISH_SIGNALS:
            bearish_agents.append(item)
        else:
            neutral_agents.append(item)

    return {
        "type": _classify_base_disagreement(
            bullish_agents,
            bearish_agents,
            neutral_agents,
        ),
        "bullish_agents": bullish_agents,
        "bearish_agents": bearish_agents,
        "neutral_agents": neutral_agents,
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
    if agent_name.strip().lower() in _RISK_AGENT_NAMES and normalized in _BULLISH_SIGNALS:
        return "hold"
    return normalized


def _classify_base_disagreement(
    bullish_agents: List[Dict[str, Any]],
    bearish_agents: List[Dict[str, Any]],
    neutral_agents: List[Dict[str, Any]],
) -> str:
    if bullish_agents and bearish_agents:
        return "mixed_directional_signals"
    if bullish_agents:
        return "bullish_with_neutral" if neutral_agents else "aligned_bullish"
    if bearish_agents:
        return "bearish_with_neutral" if neutral_agents else "aligned_bearish"
    if neutral_agents:
        return "aligned_neutral"
    return "insufficient_opinions"


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
    return _classify_base_disagreement(bullish_agents, bearish_agents, neutral_agents)


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


__all__ = ["build_agent_disagreement_summary", "summarize_agent_opinions"]
