# -*- coding: utf-8 -*-
"""
Low-sensitivity disagreement summary for multi-agent decision synthesis.

This module intentionally exposes pure functions only.  The orchestrator owns
when to compute the summary; DecisionAgent owns how to present it to the LLM.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Dict, List

from src.agent.protocols import AgentContext, AgentOpinion, is_valid_strategy_signal
from src.agent.risk_override import build_risk_override_plan
from src.agent.skills.defaults import is_skill_agent_name

_BULLISH_SIGNALS = {"strong_buy", "buy"}
_BEARISH_SIGNALS = {"strong_sell", "sell"}
_RISK_AGENT_NAMES = {"risk"}
_SUMMARY_STAGE_LIMIT = 8
_RISK_SEVERITY = {"high": 0, "medium": 1, "low": 2}
_OPINION_SOURCE_FIELDS = {
    "technical": ("trend_score", "ma_alignment", "volume_status", "pattern"),
    "intel": ("key_news", "capital_flow_signal", "risk_alerts", "positive_catalysts", "sentiment_label"),
    "risk": ("flags", "risk_level", "signal_adjustment"),
}


def build_agent_disagreement_summary(
    ctx: AgentContext,
    *,
    risk_override_enabled: bool = True,
) -> Dict[str, Any]:
    """Build a structured, low-sensitivity summary of prior agent disagreement.

    Per docs/multi-strategy-contract.md §"Disagreement": ctx.opinions is
    already partitioned by the orchestrator, so invalid skill opinions
    never appear here. Invalid counts come from ctx.meta["invalid_opinions"]
    (Diagnostics), not from re-filtering.
    """
    buckets = {
        "bullish_agents": [],
        "bearish_agents": [],
        "neutral_agents": [],
    }

    valid_count = 0
    for opinion in ctx.opinions:
        if not is_valid_strategy_signal(opinion.signal):
            continue
        valid_count += 1
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

    invalid_bucket = ctx.meta.get("invalid_opinions") or []
    if not isinstance(invalid_bucket, list):
        invalid_bucket = []

    result = {
        **buckets,
        "conflict_type": conflict_type,
        "decision_path_hint": _decision_path_hint(conflict_type),
        "risk_override_present": risk_override_plan.override_enabled
        and risk_override_plan.override_trigger_present,
        "risk_control": risk_override_plan.to_low_sensitivity_dict(),
        "degraded_result": degraded_result,
        "valid_opinion_count": valid_count,
    }

    if invalid_bucket:
        result["diagnostics"] = {
            "invalid_opinions": [
                {
                    "agent_name": str(item.get("agent_name") or "unknown"),
                    "reason": str(item.get("reason") or "unrecognized_signal"),
                }
                for item in invalid_bucket
                if isinstance(item, dict)
            ],
            "invalid_count": len(invalid_bucket),
        }

    return result


def _summarize_opinion(agent_name: str, signal: Any, confidence: Any) -> Dict[str, Any]:
    """Keep only low-sensitivity opinion metadata for downstream synthesis."""
    return {
        "agent_name": str(agent_name or "unknown"),
        "signal": _normalize_signal(signal),
        "confidence": _safe_confidence(confidence),
    }


def _normalize_signal(signal: Any) -> str:
    from src.agent.protocols import normalize_strategy_signal
    canonical, invalid, _ = normalize_strategy_signal(signal)
    return "hold" if invalid else canonical


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


def should_trigger_evidence_debate(
    ctx: AgentContext,
    *,
    enabled: bool = False,
) -> tuple[bool, str]:
    """Return ``(triggered, reason)`` for opt-in Bull/Bear evidence debate.

    Triggers only when explicitly enabled AND either:
    1. Multi-agent opinions have directional conflict (``mixed_directional_signals``), or
    2. High-conviction bullish lean (``confidence >= 0.75``) requiring mandatory risk review.
    """
    if not enabled:
        return False, "disabled"

    directional_opinions = [
        (_effective_signal(op.agent_name, op.signal), op)
        for op in ctx.opinions
        if op.agent_name != "decision" and not _is_risk_agent(op.agent_name)
    ]
    signals = {signal for signal, _ in directional_opinions}
    if signals & _BULLISH_SIGNALS and signals & _BEARISH_SIGNALS:
        return True, "mixed_directional_signals"

    if any(
        signal in _BULLISH_SIGNALS and op.confidence_input_valid and op.confidence >= 0.75
        for signal, op in directional_opinions
    ):
        return True, "high_conviction_buy"

    return False, "consensus_clear"


def opinion_evidence_id(opinion: AgentOpinion, index: int) -> str:
    return f"{opinion.agent_name or 'unknown'}#{index}"


def build_evidence_debate_brief(
    ctx: AgentContext,
    summary: Dict[str, Any],
    *,
    trigger_reason: str = "mixed_directional_signals",
    max_items_per_side: int = 3,
) -> Dict[str, Any]:
    """Build an evidence-bound Bull/Bear contrast brief + mandatory risk checklist."""
    bull_cases: List[Dict[str, Any]] = []
    bear_cases: List[Dict[str, Any]] = []
    risk_cases: List[Dict[str, Any]] = []

    for idx, op in enumerate(ctx.opinions):
        agent_name = op.agent_name or "unknown"
        if agent_name == "decision":
            continue
        signal = _effective_signal(agent_name, op.signal)
        is_risk = _is_risk_agent(agent_name)
        if not is_risk and signal not in _BULLISH_SIGNALS | _BEARISH_SIGNALS:
            continue

        evidence_id = opinion_evidence_id(op, idx)
        source_fields = {"key_levels": op.key_levels} if op.key_levels else {}
        raw_data = op.raw_data if isinstance(op.raw_data, dict) else {}
        field_names = _OPINION_SOURCE_FIELDS.get(agent_name, ())
        if is_skill_agent_name(agent_name):
            field_names = ("conditions_met", "conditions_missed")
        source_fields.update({
            key: raw_data[key]
            for key in field_names
            if raw_data.get(key) or (key == "trend_score" and raw_data.get(key) == 0)
        })
        source_ids = [f"{evidence_id}/{key}" for key in source_fields]
        tool_sources = list(op.source_evidence_ids)
        if tool_sources:
            source_ids = [tool_sources[0], *source_ids, *tool_sources[1:]]
        source_ids = source_ids[:3]
        entry = {
            "evidence_id": evidence_id,
            "agent_name": agent_name,
            "signal": signal,
            "confidence": round(op.confidence, 3),
            "claim": str(op.reasoning or "").strip()[:240],
            "source_evidence_ids": source_ids,
        }
        excerpts = {}
        for key, value in source_fields.items():
            reference = f"{evidence_id}/{key}"
            if reference in source_ids:
                excerpt = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
                excerpts[reference] = excerpt if len(excerpt) <= 240 else f"{excerpt[:239]}…"
        if excerpts:
            entry["source_excerpts"] = excerpts
        if is_risk:
            risk_cases.append(entry)
        elif signal in _BULLISH_SIGNALS:
            bull_cases.append(entry)
        else:
            bear_cases.append(entry)

    flags = sorted(
        (flag for flag in ctx.risk_flags if isinstance(flag, dict)),
        key=lambda flag: _RISK_SEVERITY.get(str(flag.get("severity", "medium")).strip().lower(), 1),
    )
    risk_flags = []
    for flag in flags[:max_items_per_side]:
        entry = {
            "category": flag.get("category") or "risk",
            "severity": flag.get("severity") or "medium",
            "description": str(flag.get("description") or "")[:160],
        }
        if flag.get("source"):
            entry["source"] = flag["source"]
        risk_flags.append(entry)

    return {
        "triggered": True,
        "trigger_reason": trigger_reason,
        "conflict_type": summary.get("conflict_type"),
        "risk_review_required": True,
        "bull_arguments": bull_cases[:max_items_per_side],
        "bear_arguments": bear_cases[:max_items_per_side],
        "risk_agent_inputs": risk_cases[:max_items_per_side],
        "risk_flags": risk_flags,
    }


__all__ = [
    "build_agent_disagreement_summary",
    "build_evidence_debate_brief",
    "should_trigger_evidence_debate",
]
