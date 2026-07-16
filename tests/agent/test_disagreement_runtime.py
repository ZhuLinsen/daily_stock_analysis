# -*- coding: utf-8 -*-
"""Focused runtime tests for deterministic final dashboard explanations."""

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("litellm", MagicMock())

from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus
from src.schemas.report_schema import AgentDisagreementExplanation


def _orchestrator(*, override_enabled=True):
    return AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=override_enabled),
    )


def _dashboard(signal):
    return {
        "stock_name": "Test Stock",
        "decision_type": signal,
        "sentiment_score": 72,
        "operation_advice": "test advice",
        "analysis_summary": "test summary",
        "dashboard": {
            "core_conclusion": {
                "one_sentence": "test conclusion",
                "position_advice": {
                    "no_position": "watch",
                    "has_position": "hold",
                },
            }
        },
    }


def _opinion(ctx, agent, signal, confidence=0.7, *, raw_data=None, reasoning="fixture"):
    ctx.add_opinion(AgentOpinion(
        agent_name=agent,
        signal=signal,
        confidence=confidence,
        reasoning=reasoning,
        raw_data=raw_data or {},
    ))


def _finalize(orchestrator, ctx, signal):
    dashboard = orchestrator._resolve_dashboard_payload(ctx, _dashboard(signal), None)
    assert dashboard is not None
    return dashboard, dashboard["dashboard"]["agent_disagreement_explanation"]


def test_final_dashboard_preserves_mixed_directional_signals():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "technical", "buy", 0.82)
    _opinion(ctx, "intel", "sell", 0.68)
    _opinion(ctx, "decision", "hold", 0.55)

    _, explanation = _finalize(_orchestrator(), ctx, "hold")

    assert explanation["base_disagreement"]["type"] == "mixed_directional_signals"
    assert explanation["risk_control"]["reason"] == "no_risk_evidence"
    assert explanation["decision_path"] == "mixed_signals_synthesized"


def test_final_dashboard_reports_aligned_bullish_consensus():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "technical", "buy", 0.82)
    _opinion(ctx, "intel", "buy", 0.68)
    _opinion(ctx, "decision", "buy", 0.75)

    dashboard, explanation = _finalize(_orchestrator(), ctx, "buy")

    assert dashboard["dashboard"]["agent_disagreement_explanation"] is explanation
    assert explanation["base_disagreement"]["type"] == "aligned_bullish"
    assert explanation["decision_path"] == "aligned_agent_consensus"


def test_final_dashboard_reports_bullish_with_neutral_synthesis():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "technical", "buy", 0.82)
    _opinion(ctx, "intel", "hold", 0.68)
    _opinion(ctx, "decision", "buy", 0.75)

    dashboard, explanation = _finalize(_orchestrator(), ctx, "buy")

    assert dashboard["dashboard"]["agent_disagreement_explanation"] is explanation
    assert explanation["base_disagreement"]["type"] == "bullish_with_neutral"
    assert explanation["decision_path"] == "non_conflicting_signals_synthesized"


def test_final_dashboard_records_veto_that_changes_buy_to_hold():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "technical", "buy", 0.82)
    _opinion(ctx, "risk", "sell", 0.9, raw_data={"veto_buy": True})
    _opinion(ctx, "decision", "buy", 0.8)

    dashboard, explanation = _finalize(_orchestrator(), ctx, "buy")

    assert dashboard["decision_type"] == "hold"
    assert explanation["risk_control"] == {
        "evidence_present": True,
        "override_enabled": True,
        "trigger": "risk_veto",
        "applied": True,
        "reason": "risk_veto_applied",
        "final_signal": "hold",
        "from_signal": "buy",
        "to_signal": "hold",
    }
    assert explanation["decision_path"] == "risk_veto_applied"


def test_final_dashboard_records_disabled_veto_without_transition():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "technical", "buy", 0.82)
    _opinion(ctx, "risk", "sell", 0.9, raw_data={"veto_buy": True})
    _opinion(ctx, "decision", "buy", 0.8)

    dashboard, explanation = _finalize(_orchestrator(override_enabled=False), ctx, "buy")
    risk_control = explanation["risk_control"]

    assert dashboard["decision_type"] == "buy"
    assert risk_control["reason"] == "override_disabled"
    assert risk_control["applied"] is False
    assert risk_control["final_signal"] == "buy"
    assert "from_signal" not in risk_control
    assert "to_signal" not in risk_control


def test_final_dashboard_distinguishes_high_risk_evidence_without_trigger():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "technical", "buy", 0.82)
    _opinion(ctx, "risk", "hold", 0.75, raw_data={"risk_level": "high"})
    _opinion(ctx, "decision", "buy", 0.8)

    _, explanation = _finalize(_orchestrator(), ctx, "buy")
    risk_control = explanation["risk_control"]

    assert risk_control["evidence_present"] is True
    assert risk_control["trigger"] == "none"
    assert risk_control["applied"] is False
    assert risk_control["reason"] == "no_override_trigger"


def test_final_dashboard_records_veto_when_hold_is_already_within_limit():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "technical", "buy", 0.82)
    _opinion(ctx, "intel", "sell", 0.68)
    _opinion(ctx, "risk", "sell", 0.9, raw_data={"veto_buy": True})
    _opinion(ctx, "decision", "hold", 0.6)

    dashboard, explanation = _finalize(_orchestrator(), ctx, "hold")
    risk_control = explanation["risk_control"]

    assert dashboard["decision_type"] == "hold"
    assert explanation["base_disagreement"]["type"] == "mixed_directional_signals"
    assert risk_control["applied"] is False
    assert risk_control["reason"] == "final_signal_already_within_risk_limit"
    assert risk_control["final_signal"] == "hold"
    assert explanation["decision_path"] == "mixed_signals_synthesized"


def test_final_schema_payload_excludes_sensitive_runtime_fields():
    ctx = AgentContext(stock_code="600519")
    _opinion(
        ctx,
        "technical",
        "buy",
        0.82,
        reasoning="secret reasoning",
        raw_data={"token": "secret-token", "private_payload": "private payload"},
    )
    _opinion(ctx, "decision", "buy", 0.8, raw_data={"secret": "decision secret"})
    ctx.meta["degraded_events"] = [{
        "stage": "intel",
        "reason": "stage_failure",
        "error": "private raw error",
        "token": "private token",
    }]

    _, explanation = _finalize(_orchestrator(), ctx, "buy")
    payload_text = json.dumps(explanation, ensure_ascii=False).lower()

    assert explanation["degraded_events"] == [{"stage": "intel", "reason": "stage_failure"}]
    for forbidden in (
        "reasoning",
        "raw_data",
        "error",
        "token",
        "secret",
        "private payload",
    ):
        assert forbidden not in payload_text


def test_repeated_final_output_preserves_applied_veto_application():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "technical", "buy", 0.82)
    _opinion(ctx, "risk", "sell", 0.9, raw_data={"veto_buy": True})
    _opinion(ctx, "decision", "buy", 0.8)
    ctx.set_data("final_dashboard", _dashboard("buy"))
    orchestrator = _orchestrator()

    first, _ = orchestrator._resolve_final_output(ctx, parse_dashboard=True)
    second, _ = orchestrator._resolve_final_output(ctx, parse_dashboard=True)

    assert first is not None
    assert second is not None
    assert first["decision_type"] == second["decision_type"] == "hold"
    expected = {
        "evidence_present": True,
        "override_enabled": True,
        "trigger": "risk_veto",
        "applied": True,
        "reason": "risk_veto_applied",
        "final_signal": "hold",
        "from_signal": "buy",
        "to_signal": "hold",
    }
    assert first["dashboard"]["agent_disagreement_explanation"]["risk_control"] == expected
    assert second["dashboard"]["agent_disagreement_explanation"]["risk_control"] == expected


def test_final_output_replaces_forged_llm_explanation_without_merging():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "technical", "buy", 0.82)
    _opinion(ctx, "decision", "buy", 0.8)
    dashboard = _dashboard("buy")
    dashboard["dashboard"]["agent_disagreement_explanation"] = {
        "risk_control": {
            "applied": True,
            "reason": "risk_veto_applied",
            "from_signal": "sell",
            "to_signal": "buy",
            "token": "secret-token",
        },
        "reasoning": "private reasoning",
        "raw_data": {"secret": "private payload"},
        "error": "private error",
        "forged_field": True,
    }

    final = _orchestrator()._resolve_dashboard_payload(ctx, dashboard, None)
    assert final is not None
    explanation = final["dashboard"]["agent_disagreement_explanation"]

    assert final["decision_type"] == "buy"
    assert explanation["risk_control"]["reason"] == "no_risk_evidence"
    assert explanation["risk_control"]["applied"] is False
    assert AgentDisagreementExplanation.model_validate(explanation)
    payload_text = json.dumps(explanation, ensure_ascii=False).lower()
    for forbidden in (
        "reasoning",
        "raw_data",
        "error",
        "token",
        "secret",
        "private payload",
        "forged_field",
    ):
        assert forbidden not in payload_text


@pytest.mark.parametrize(
    ("adjustment", "original", "expected", "applied"),
    [
        ("downgrade_one", "buy", "hold", True),
        ("downgrade_one", "hold", "sell", True),
        ("downgrade_two", "buy", "sell", True),
        ("downgrade_two", "hold", "sell", True),
        ("downgrade_one", "sell", "sell", False),
    ],
)
def test_final_dashboard_exposes_downgrade_runtime_outcome(
    adjustment,
    original,
    expected,
    applied,
):
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "technical", original, 0.82)
    _opinion(
        ctx,
        "risk",
        "sell",
        0.9,
        raw_data={"signal_adjustment": adjustment},
    )
    _opinion(ctx, "decision", original, 0.8)

    dashboard, explanation = _finalize(_orchestrator(), ctx, original)
    risk_control = explanation["risk_control"]

    assert dashboard["decision_type"] == expected
    assert risk_control["trigger"] == "risk_downgrade"
    assert risk_control["applied"] is applied
    assert risk_control["final_signal"] == expected
    if applied:
        assert risk_control["reason"] == "risk_downgrade_applied"
        assert risk_control["from_signal"] == original
        assert risk_control["to_signal"] == expected
        assert ctx.get_data("risk_override_applied")["from"] == original
        assert ctx.get_data("risk_override_applied")["to"] == expected
    else:
        assert risk_control["reason"] == "final_signal_already_within_risk_limit"
        assert "from_signal" not in risk_control
        assert "to_signal" not in risk_control
        assert ctx.get_data("risk_override_applied") is None


def test_single_technical_opinion_uses_limited_opinion_synthesis():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "technical", "buy", 0.82)

    _, explanation = _finalize(_orchestrator(), ctx, "buy")

    assert explanation["base_disagreement"]["type"] == "insufficient_opinions"
    assert explanation["decision_path"] == "limited_opinion_synthesis"


def test_single_skill_consensus_is_internal_not_an_independent_base_opinion():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "skill_xxx", "buy", 0.82)
    _opinion(ctx, "skill_consensus", "buy", 0.82)

    _, explanation = _finalize(_orchestrator(), ctx, "buy")

    assert explanation["base_disagreement"]["agents"] == [
        {"agent": "skill_xxx", "signal": "buy", "confidence": 0.82},
    ]
    assert explanation["base_disagreement"]["type"] == "insufficient_opinions"
    assert explanation["decision_path"] == "limited_opinion_synthesis"
    assert [opinion.agent_name for opinion in ctx.opinions] == [
        "skill_xxx",
        "skill_consensus",
    ]


def test_multiple_skill_consensus_does_not_duplicate_base_opinions():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "skill_a", "buy", 0.82)
    _opinion(ctx, "skill_b", "hold", 0.68)
    _opinion(ctx, "skill_consensus", "buy", 0.76)

    _, explanation = _finalize(_orchestrator(), ctx, "buy")

    assert explanation["base_disagreement"]["agents"] == [
        {"agent": "skill_a", "signal": "buy", "confidence": 0.82},
        {"agent": "skill_b", "signal": "hold", "confidence": 0.68},
    ]
    assert explanation["base_disagreement"]["type"] == "bullish_with_neutral"
    assert explanation["decision_path"] == "non_conflicting_signals_synthesized"


def test_legacy_strategy_consensus_is_not_an_independent_base_opinion():
    ctx = AgentContext(stock_code="600519")
    _opinion(ctx, "strategy_a", "sell", 0.74)
    _opinion(ctx, "strategy_consensus", "sell", 0.74)

    _, explanation = _finalize(_orchestrator(), ctx, "sell")

    assert explanation["base_disagreement"]["agents"] == [
        {"agent": "strategy_a", "signal": "sell", "confidence": 0.74},
    ]
    assert explanation["base_disagreement"]["type"] == "insufficient_opinions"
    assert explanation["decision_path"] == "limited_opinion_synthesis"


def test_non_critical_failure_keeps_legacy_marker_and_deduplicates_public_event():
    ctx = AgentContext(stock_code="600519")
    orchestrator = _orchestrator()
    failed = StageResult(
        stage_name="intel",
        status=StageStatus.FAILED,
        error="private provider error",
    )

    orchestrator._record_degraded_stage(ctx, "intel", failed)
    orchestrator._record_degraded_stage(ctx, "intel", failed)

    assert ctx.meta["degraded_stages"] == [
        {"stage_name": "intel", "status": "failed", "non_critical": True},
        {"stage_name": "intel", "status": "failed", "non_critical": True},
    ]
    assert ctx.meta["degraded_events"] == [
        {"stage": "intel", "reason": "stage_failure"},
    ]
    assert "private provider error" not in json.dumps(ctx.meta["degraded_events"])
