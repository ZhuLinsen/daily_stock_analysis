# -*- coding: utf-8 -*-
"""
Low-sensitivity disagreement summary for multi-agent decision synthesis.

This module intentionally exposes pure functions only.  The orchestrator owns
when to compute the summary; DecisionAgent owns how to present it to the LLM.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Dict, List

from src.agent.protocols import AgentContext

_BULLISH_SIGNALS = {"strong_buy", "buy"}
_BEARISH_SIGNALS = {"strong_sell", "sell"}
_RISK_AGENT_NAMES = {"risk"}
_NON_CRITICAL_STAGES = {"intel", "risk"}
_SUMMARY_STAGE_LIMIT = 8


def build_agent_disagreement_summary(ctx: AgentContext) -> Dict[str, Any]:
    """Build a structured, low-sensitivity summary of prior agent disagreement."""
    buckets = {
        "bullish_agents": [],
        "bearish_agents": [],
        "neutral_agents": [],
    }

    for opinion in ctx.opinions:
        agent_summary = _summarize_opinion(opinion.agent_name, opinion.signal, opinion.confidence)
        signal = _normalize_signal(opinion.signal)
        if signal in _BULLISH_SIGNALS:
            buckets["bullish_agents"].append(agent_summary)
        elif signal in _BEARISH_SIGNALS:
            buckets["bearish_agents"].append(agent_summary)
        else:
            buckets["neutral_agents"].append(agent_summary)

    risk_override_present = _has_risk_override(ctx)
    degraded_result = _build_degraded_result(ctx)
    conflict_type = _classify_conflict_type(
        buckets["bullish_agents"],
        buckets["bearish_agents"],
        buckets["neutral_agents"],
        risk_override_present,
        degraded_result,
    )

    return {
        **buckets,
        "conflict_type": conflict_type,
        "decision_path_hint": _decision_path_hint(conflict_type),
        "risk_override_present": risk_override_present,
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


def _safe_confidence(confidence: Any) -> float:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        value = 0.0
    return round(max(0.0, min(1.0, value)), 2)


def _has_risk_override(ctx: AgentContext) -> bool:
    if any(str(flag.get("severity", "")).lower() == "high" for flag in ctx.risk_flags if isinstance(flag, dict)):
        return True

    for opinion in ctx.opinions:
        if opinion.agent_name not in _RISK_AGENT_NAMES:
            continue
        raw_data = opinion.raw_data if isinstance(opinion.raw_data, dict) else {}
        if raw_data.get("veto_buy") is True:
            return True
        if str(raw_data.get("signal_adjustment", "")).lower() == "veto":
            return True
        if str(raw_data.get("risk_level", "")).lower() == "high":
            return True
    return False


def _build_degraded_result(ctx: AgentContext) -> Dict[str, Any]:
    stages = list(_iter_degraded_stages(ctx))
    has_non_critical = any(stage.get("stage_name") in _NON_CRITICAL_STAGES for stage in stages)
    return {
        "present": bool(stages),
        "non_critical_stage_present": has_non_critical,
        "stages": stages[:_SUMMARY_STAGE_LIMIT],
    }


def _iter_degraded_stages(ctx: AgentContext) -> Iterable[Dict[str, str]]:
    for source in (
        ctx.get_data("degraded_stages"),
        ctx.meta.get("degraded_stages"),
        ctx.meta.get("stage_results"),
        ctx.get_data("stage_results"),
    ):
        for item in _coerce_stage_items(source):
            stage_name = str(item.get("stage_name") or item.get("stage") or item.get("agent_name") or "").strip()
            status = str(item.get("status") or "").strip().lower()
            if not stage_name or status not in {"failed", "skipped", "degraded", "partial", "timeout"}:
                continue
            yield {
                "stage_name": stage_name,
                "status": status,
            }


def _coerce_stage_items(source: Any) -> Iterable[Mapping[str, Any]]:
    if source is None:
        return []
    if isinstance(source, Mapping):
        return [source]
    if isinstance(source, Iterable) and not isinstance(source, (str, bytes)):
        return [item for item in source if isinstance(item, Mapping)]
    return []


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
    if degraded_result.get("present") and not bullish_agents and not bearish_agents:
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
        "aligned_bullish": "use_bullish_consensus_with_price_and_risk_checks",
        "bullish_with_neutral": "lean_bullish_but_require_confirmation",
        "aligned_bearish": "use_bearish_consensus_and_preserve_downside_controls",
        "bearish_with_neutral": "lean_defensive_and_require_recovery_confirmation",
        "aligned_neutral": "prefer_hold_watchlist_or_range_plan",
        "insufficient_opinions": "prefer_conservative_hold_due_to_limited_agent_input",
    }
    return hints.get(conflict_type, "prefer_conservative_hold_due_to_mixed_inputs")


__all__ = ["build_agent_disagreement_summary"]
