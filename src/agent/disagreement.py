# -*- coding: utf-8 -*-
"""
Low-sensitivity disagreement summary for multi-agent decision synthesis.

This module intentionally exposes pure functions only.  The orchestrator owns
when to compute the summary; DecisionAgent owns how to present it to the LLM.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Dict, List

from src.agent.protocols import AgentContext
from src.agent.risk_override import build_risk_override_plan

_BULLISH_SIGNALS = {"strong_buy", "buy"}
_BEARISH_SIGNALS = {"strong_sell", "sell"}
_RISK_AGENT_NAMES = {"risk"}
_SUMMARY_STAGE_LIMIT = 8


def build_agent_disagreement_summary(
    ctx: AgentContext,
    *,
    risk_override_enabled: bool = True,
) -> Dict[str, Any]:
    """Build a structured, low-sensitivity summary of prior agent disagreement."""
    buckets = build_agent_disagreement_buckets(ctx)

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


def build_base_agent_disagreement(
    ctx: AgentContext,
    *,
    include_decision: bool = False,
) -> Dict[str, Any]:
    """Return the base directional disagreement using the shared bucket contract."""
    buckets = build_agent_disagreement_buckets(ctx, include_decision=include_decision)
    return build_base_agent_disagreement_from_buckets(buckets)


def build_base_agent_disagreement_from_buckets(
    buckets: Dict[str, Any],
) -> Dict[str, Any]:
    """Return base disagreement facts from pre-sanitized or raw bucket lists."""
    sanitized = sanitize_agent_disagreement_buckets(buckets)
    return {
        "type": classify_base_agent_disagreement(
            sanitized["bullish_agents"],
            sanitized["bearish_agents"],
            sanitized["neutral_agents"],
        ),
        **sanitized,
    }


def build_agent_disagreement_buckets(
    ctx: AgentContext,
    *,
    include_decision: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """Bucket agent opinions using the canonical low-sensitivity signal semantics."""
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "bullish_agents": [],
        "bearish_agents": [],
        "neutral_agents": [],
    }

    for opinion in ctx.opinions:
        agent_name = str(getattr(opinion, "agent_name", "") or "").strip()
        if not include_decision and agent_name.lower() == "decision":
            continue
        signal = _effective_signal(agent_name, getattr(opinion, "signal", None))
        agent_summary = _summarize_opinion(
            agent_name,
            signal,
            getattr(opinion, "confidence", None),
        )
        if signal in _BULLISH_SIGNALS:
            buckets["bullish_agents"].append(agent_summary)
        elif signal in _BEARISH_SIGNALS:
            buckets["bearish_agents"].append(agent_summary)
        else:
            buckets["neutral_agents"].append(agent_summary)

    return buckets


def sanitize_agent_disagreement_buckets(buckets: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Sanitize bucket payloads without changing the established bucket membership."""
    return {
        "bullish_agents": _sanitize_bucket_items(buckets.get("bullish_agents")),
        "bearish_agents": _sanitize_bucket_items(buckets.get("bearish_agents")),
        "neutral_agents": _sanitize_bucket_items(buckets.get("neutral_agents")),
    }


def classify_base_agent_disagreement(
    bullish_agents: List[Dict[str, Any]],
    bearish_agents: List[Dict[str, Any]],
    neutral_agents: List[Dict[str, Any]],
) -> str:
    """Classify base directional disagreement without risk or degradation overrides."""
    if bullish_agents and bearish_agents:
        return "mixed_directional_signals"
    if bullish_agents and not bearish_agents:
        return "aligned_bullish" if not neutral_agents else "bullish_with_neutral"
    if bearish_agents and not bullish_agents:
        return "aligned_bearish" if not neutral_agents else "bearish_with_neutral"
    if neutral_agents:
        return "aligned_neutral"
    return "insufficient_opinions"


def _sanitize_bucket_items(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        items.append(
            _summarize_opinion(
                str(item.get("agent_name") or "unknown"),
                item.get("signal"),
                item.get("confidence"),
            )
        )
    return items


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
    return classify_base_agent_disagreement(bullish_agents, bearish_agents, neutral_agents)


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
    "build_agent_disagreement_summary",
    "build_base_agent_disagreement",
    "build_base_agent_disagreement_from_buckets",
    "classify_base_agent_disagreement",
    "sanitize_agent_disagreement_buckets",
]
