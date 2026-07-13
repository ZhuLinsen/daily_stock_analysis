# -*- coding: utf-8 -*-
"""Tests for low-sensitivity multi-agent disagreement summaries."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.agent.disagreement import (
    build_agent_disagreement_summary,
    build_base_agent_disagreement,
    build_base_agent_disagreement_from_buckets,
)
from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus
from src.agent.risk_override import (
    RISK_CONTROL_STATE_SPECS,
    RiskControlState,
    RiskControlStateFacts,
    derive_risk_control_state,
)
from src.schemas.report_schema import (
    AgentDisagreementBase,
    AgentDisagreementExplanation,
    AgentDisagreementRiskControl,
)


def _schema_base_payload(*, mixed: bool = False):
    if mixed:
        return {
            "type": "mixed_directional_signals",
            "bullish_agents": [
                {"agent_name": "technical", "signal": "buy", "confidence": 0.8}
            ],
            "bearish_agents": [
                {"agent_name": "intel", "signal": "sell", "confidence": 0.7}
            ],
            "neutral_agents": [],
        }
    return {
        "type": "aligned_bullish",
        "bullish_agents": [
            {"agent_name": "technical", "signal": "buy", "confidence": 0.8}
        ],
        "bearish_agents": [],
        "neutral_agents": [],
    }


def _schema_risk_control_payload(**overrides):
    payload = {
        "evidence_present": False,
        "trigger": "none",
        "planned_action": "none",
        "applied": False,
        "not_applied_reason": "none",
        "override_enabled": True,
        "current": "buy",
        "target": "buy",
    }
    payload.update(overrides)
    return payload


def _schema_applied_veto_payload(**overrides):
    payload = {
        "evidence_present": True,
        "trigger": "risk_veto",
        "planned_action": "cap_buy_to_hold",
        "applied": True,
        "not_applied_reason": "none",
        "override_enabled": True,
        "from": "buy",
        "to": "hold",
        "reason": "risk_veto",
    }
    payload.update(overrides)
    return payload


def _schema_explanation_payload(
    *,
    risk_control=None,
    degraded_events=None,
    decision_path="synthesize_agent_inputs",
    mixed=False,
):
    return {
        "base_disagreement": _schema_base_payload(mixed=mixed),
        "risk_control": risk_control or _schema_risk_control_payload(),
        "degraded_events": degraded_events or [],
        "decision_path": decision_path,
        "summary": "Low-sensitivity contract fixture.",
    }


def test_consensus_bullish_summary_is_low_sensitivity():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(
        AgentOpinion(
            agent_name="technical",
            signal="buy",
            confidence=0.82,
            reasoning="secret reasoning",
            raw_data={"token": "secret-token", "private_payload": "private position payload"},
        )
    )
    ctx.add_opinion(AgentOpinion(agent_name="intel", signal="strong_buy", confidence=0.76))

    summary = build_agent_disagreement_summary(ctx)
    summary_text = str(summary)

    assert summary["conflict_type"] == "aligned_bullish"
    assert [item["agent_name"] for item in summary["bullish_agents"]] == ["technical", "intel"]
    assert summary["bearish_agents"] == []
    assert summary["risk_override_present"] is False
    assert "secret reasoning" not in summary_text
    assert "raw_data" not in summary_text
    assert "secret-token" not in summary_text
    assert "private position payload" not in summary_text


def test_empty_opinions_are_conservative():
    summary = build_agent_disagreement_summary(AgentContext())

    assert summary["conflict_type"] == "insufficient_opinions"
    assert summary["bullish_agents"] == []
    assert summary["bearish_agents"] == []
    assert summary["neutral_agents"] == []
    assert summary["decision_path_hint"] == "prefer_conservative_hold_due_to_limited_agent_input"


def test_mixed_directional_signals():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.72))
    ctx.add_opinion(AgentOpinion(agent_name="intel", signal="sell", confidence=0.68))
    ctx.add_opinion(AgentOpinion(agent_name="risk", signal="hold", confidence=0.66))

    summary = build_agent_disagreement_summary(ctx)

    assert summary["conflict_type"] == "mixed_directional_signals"
    assert len(summary["bullish_agents"]) == 1
    assert len(summary["bearish_agents"]) == 1
    assert len(summary["neutral_agents"]) == 1


def test_risk_agent_buy_signal_is_neutral_risk_clear_not_bullish():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.72))
    ctx.add_opinion(
        AgentOpinion(
            agent_name="risk",
            signal="buy",
            confidence=0.66,
            raw_data={"risk_level": "none", "private_payload": "private risk payload"},
        )
    )

    summary = build_agent_disagreement_summary(ctx)
    summary_text = str(summary)

    assert [item["agent_name"] for item in summary["bullish_agents"]] == ["technical"]
    assert [item["agent_name"] for item in summary["neutral_agents"]] == ["risk"]
    assert summary["conflict_type"] == "bullish_with_neutral"
    assert "risk_level" not in summary_text
    assert "private risk payload" not in summary_text


def test_base_disagreement_uses_same_bucket_contract_as_summary():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.72))
    ctx.add_opinion(AgentOpinion(agent_name="risk", signal="buy", confidence=0.66))

    summary = build_agent_disagreement_summary(ctx)
    base_from_runtime = build_base_agent_disagreement(ctx)
    base_from_summary = build_base_agent_disagreement_from_buckets(summary)

    assert summary["conflict_type"] == "bullish_with_neutral"
    assert base_from_runtime == base_from_summary
    assert base_from_runtime["type"] == "bullish_with_neutral"
    assert [item["agent_name"] for item in base_from_runtime["bullish_agents"]] == ["technical"]
    assert [item["agent_name"] for item in base_from_runtime["neutral_agents"]] == ["risk"]


def test_risk_clear_buy_bucket_contract_matrix():
    cases = [
        (
            [
                ("technical", "buy"),
                ("risk", "buy"),
            ],
            "bullish_with_neutral",
            ["technical"],
            [],
            ["risk"],
        ),
        (
            [
                ("technical", "sell"),
                ("risk", "buy"),
            ],
            "bearish_with_neutral",
            [],
            ["technical"],
            ["risk"],
        ),
        (
            [
                ("technical", "buy"),
                ("intel", "sell"),
                ("risk", "buy"),
            ],
            "mixed_directional_signals",
            ["technical"],
            ["intel"],
            ["risk"],
        ),
        (
            [
                ("technical", "buy"),
                ("intel", "buy"),
                ("risk", "buy"),
            ],
            "bullish_with_neutral",
            ["technical", "intel"],
            [],
            ["risk"],
        ),
        (
            [
                ("technical", "sell"),
                ("intel", "sell"),
                ("risk", "buy"),
            ],
            "bearish_with_neutral",
            [],
            ["technical", "intel"],
            ["risk"],
        ),
        (
            [
                ("risk", "buy"),
            ],
            "aligned_neutral",
            [],
            [],
            ["risk"],
        ),
    ]

    for opinions, expected_type, bullish_names, bearish_names, neutral_names in cases:
        ctx = AgentContext(query="test", stock_code="600519")
        for agent_name, signal in opinions:
            raw_data = {"risk_level": "none"} if agent_name == "risk" else {}
            ctx.add_opinion(
                AgentOpinion(
                    agent_name=agent_name,
                    signal=signal,
                    confidence=0.7,
                    raw_data=raw_data,
                )
            )

        summary = build_agent_disagreement_summary(ctx)
        base_from_runtime = build_base_agent_disagreement(ctx)
        base_from_summary = build_base_agent_disagreement_from_buckets(summary)

        assert summary["conflict_type"] == expected_type
        assert base_from_runtime == base_from_summary
        assert base_from_runtime["type"] == expected_type
        assert [item["agent_name"] for item in base_from_runtime["bullish_agents"]] == bullish_names
        assert [item["agent_name"] for item in base_from_runtime["bearish_agents"]] == bearish_names
        assert [item["agent_name"] for item in base_from_runtime["neutral_agents"]] == neutral_names
        assert base_from_runtime["type"] != "aligned_bullish" or neutral_names == []
        assert base_from_runtime["type"] != "aligned_bearish" or neutral_names == []


def test_disagreement_schema_rejects_type_bucket_contradiction():
    with pytest.raises(ValidationError, match="contradicts bucket contents"):
        AgentDisagreementBase.model_validate({
            "type": "aligned_bullish",
            "bullish_agents": [
                {"agent_name": "technical", "signal": "buy", "confidence": 0.8}
            ],
            "neutral_agents": [
                {"agent_name": "risk", "signal": "hold", "confidence": 0.7}
            ],
        })


def test_risk_control_from_alias_default_dump_round_trips():
    model = AgentDisagreementRiskControl.model_validate({
        "evidence_present": True,
        "trigger": "risk_veto",
        "planned_action": "cap_buy_to_hold",
        "applied": True,
        "override_enabled": True,
        "from": "buy",
        "to": "hold",
        "reason": "risk_veto",
    })

    dumped = model.model_dump()

    assert dumped["from"] == "buy"
    assert "from_" not in dumped
    assert AgentDisagreementRiskControl.model_validate(dumped).from_ == "buy"


def test_risk_control_public_dump_omits_irrelevant_state_fields():
    snapshot = AgentDisagreementRiskControl.model_validate(
        _schema_risk_control_payload()
    ).model_dump()
    applied = AgentDisagreementRiskControl.model_validate(
        _schema_applied_veto_payload()
    ).model_dump()

    assert snapshot == {
        "evidence_present": False,
        "trigger": "none",
        "planned_action": "none",
        "applied": False,
        "not_applied_reason": "none",
        "override_enabled": True,
        "current": "buy",
        "target": "buy",
    }
    assert applied == {
        "evidence_present": True,
        "trigger": "risk_veto",
        "planned_action": "cap_buy_to_hold",
        "applied": True,
        "not_applied_reason": "none",
        "override_enabled": True,
        "from": "buy",
        "to": "hold",
        "reason": "risk_veto",
    }


def test_disagreement_explanation_requires_decision_path():
    payload = _schema_explanation_payload()
    payload.pop("decision_path")

    with pytest.raises(ValidationError):
        AgentDisagreementExplanation.model_validate(payload)


@pytest.mark.parametrize(
    ("facts", "expected_state"),
    [
        pytest.param(
            RiskControlStateFacts(False, False, "none", True, None),
            RiskControlState.NO_EVIDENCE,
            id="no-evidence",
        ),
        pytest.param(
            RiskControlStateFacts(False, True, "high_risk_evidence", False, None),
            RiskControlState.EVIDENCE_WITHOUT_OVERRIDE_TRIGGER,
            id="evidence-without-override-trigger",
        ),
        pytest.param(
            RiskControlStateFacts(False, True, "risk_veto", False, None),
            RiskControlState.VETO_DISABLED,
            id="veto-disabled",
        ),
        pytest.param(
            RiskControlStateFacts(False, True, "risk_downgrade", False, None),
            RiskControlState.DOWNGRADE_DISABLED,
            id="downgrade-disabled",
        ),
        pytest.param(
            RiskControlStateFacts(False, True, "risk_veto", True, None),
            RiskControlState.VETO_WITHIN_LIMIT,
            id="veto-within-limit",
        ),
        pytest.param(
            RiskControlStateFacts(False, True, "risk_downgrade", True, None),
            RiskControlState.DOWNGRADE_WITHIN_LIMIT,
            id="downgrade-within-limit",
        ),
        pytest.param(
            RiskControlStateFacts(True, True, "risk_veto", True, "risk_veto"),
            RiskControlState.VETO_APPLIED,
            id="veto-applied",
        ),
        pytest.param(
            RiskControlStateFacts(True, True, "risk_veto", True, "high_severity_flag"),
            RiskControlState.VETO_APPLIED,
            id="high-severity-veto-applied",
        ),
        pytest.param(
            RiskControlStateFacts(True, True, "risk_downgrade", True, "downgrade_one"),
            RiskControlState.DOWNGRADE_ONE_APPLIED,
            id="downgrade-one-applied",
        ),
        pytest.param(
            RiskControlStateFacts(True, True, "risk_downgrade", True, "downgrade_two"),
            RiskControlState.DOWNGRADE_TWO_APPLIED,
            id="downgrade-two-applied",
        ),
    ],
)
def test_risk_control_state_derivation_uses_complete_finite_contract(facts, expected_state):
    assert derive_risk_control_state(facts) is expected_state


def test_risk_control_state_registry_defines_every_finite_state():
    assert set(RISK_CONTROL_STATE_SPECS) == set(RiskControlState)
    assert all(state is spec.state for state, spec in RISK_CONTROL_STATE_SPECS.items())


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            _schema_explanation_payload(),
            id="no-risk-evidence",
        ),
        pytest.param(
            _schema_explanation_payload(
                risk_control=_schema_risk_control_payload(
                    evidence_present=True,
                    trigger="high_risk_evidence",
                    not_applied_reason="no_trigger",
                    current="hold",
                    target="hold",
                ),
                decision_path="preserve_final_signal_after_risk_check",
            ),
            id="high-risk-evidence-without-override-trigger",
        ),
        pytest.param(
            _schema_explanation_payload(
                risk_control=_schema_risk_control_payload(
                    evidence_present=True,
                    trigger="risk_veto",
                    planned_action="cap_buy_to_hold",
                    not_applied_reason="override_disabled",
                    override_enabled=False,
                ),
                decision_path="preserve_final_signal_after_risk_check",
            ),
            id="risk-veto-with-override-disabled",
        ),
        pytest.param(
            _schema_explanation_payload(
                risk_control=_schema_risk_control_payload(
                    evidence_present=True,
                    trigger="risk_downgrade",
                    planned_action="downgrade",
                    not_applied_reason="override_disabled",
                    override_enabled=False,
                ),
                decision_path="preserve_final_signal_after_risk_check",
            ),
            id="risk-downgrade-with-override-disabled",
        ),
        pytest.param(
            _schema_explanation_payload(
                risk_control=_schema_risk_control_payload(
                    evidence_present=True,
                    trigger="risk_veto",
                    planned_action="cap_buy_to_hold",
                    not_applied_reason="final_signal_already_within_risk_limit",
                    current="hold",
                    target="hold",
                ),
                decision_path="preserve_final_signal_after_risk_check",
            ),
            id="risk-veto-with-conservative-final-signal",
        ),
        pytest.param(
            _schema_explanation_payload(
                risk_control=_schema_risk_control_payload(
                    evidence_present=True,
                    trigger="risk_downgrade",
                    planned_action="downgrade",
                    not_applied_reason="final_signal_already_within_risk_limit",
                    current="sell",
                    target="sell",
                ),
                decision_path="preserve_final_signal_after_risk_check",
            ),
            id="risk-downgrade-with-conservative-final-signal",
        ),
        pytest.param(
            _schema_explanation_payload(
                risk_control=_schema_applied_veto_payload(),
                decision_path="apply_risk_control",
            ),
            id="risk-veto-applied",
        ),
        pytest.param(
            _schema_explanation_payload(
                risk_control={
                    "evidence_present": True,
                    "trigger": "risk_downgrade",
                    "planned_action": "downgrade",
                    "applied": True,
                    "not_applied_reason": "none",
                    "override_enabled": True,
                    "from": "hold",
                    "to": "sell",
                    "reason": "downgrade_one",
                },
                decision_path="apply_risk_control",
            ),
            id="risk-downgrade-applied",
        ),
        pytest.param(
            _schema_explanation_payload(
                risk_control={
                    "evidence_present": True,
                    "trigger": "risk_downgrade",
                    "planned_action": "downgrade",
                    "applied": True,
                    "not_applied_reason": "none",
                    "override_enabled": True,
                    "from": "buy",
                    "to": "sell",
                    "reason": "downgrade_two",
                },
                decision_path="apply_risk_control",
            ),
            id="risk-downgrade-two-applied",
        ),
        pytest.param(
            _schema_explanation_payload(
                degraded_events=[
                    {"stage": "intel", "reason": "timeout", "critical": False}
                ],
                decision_path="degraded_partial_result",
            ),
            id="degraded-partial-result",
        ),
        pytest.param(
            _schema_explanation_payload(
                risk_control=_schema_applied_veto_payload(),
                degraded_events=[
                    {"stage": "intel", "reason": "timeout", "critical": False}
                ],
                decision_path="apply_risk_control",
            ),
            id="applied-risk-control-precedes-degraded-event",
        ),
        pytest.param(
            _schema_explanation_payload(
                decision_path="synthesize_mixed_signals",
                mixed=True,
            ),
            id="mixed-signals-without-risk-or-degradation",
        ),
    ],
)
def test_disagreement_explanation_valid_state_matrix_round_trips(payload):
    model = AgentDisagreementExplanation.model_validate(payload)
    dumped = model.model_dump()
    restored = AgentDisagreementExplanation.model_validate(dumped)

    assert restored.model_dump() == dumped
    assert "from_" not in dumped["risk_control"]
    if model.risk_control.applied:
        assert dumped["risk_control"]["from"] in {"buy", "hold"}


@pytest.mark.parametrize(
    ("payload", "expected_markers"),
    [
        pytest.param(
            _schema_applied_veto_payload(evidence_present=False),
            ("applied=True", "evidence_present=False"),
            id="applied-without-evidence",
        ),
        pytest.param(
            _schema_applied_veto_payload(override_enabled=False),
            ("applied=True", "override_enabled=False"),
            id="applied-while-override-disabled",
        ),
        pytest.param(
            _schema_applied_veto_payload(
                trigger="high_risk_evidence",
                planned_action="none",
                reason="high_risk_evidence",
            ),
            ("reason", "high_risk_evidence"),
            id="applied-without-override-trigger",
        ),
        pytest.param(
            _schema_applied_veto_payload(**{"from": None}),
            ("state='veto_applied'", "requires from, to, and reason"),
            id="applied-without-transition-fields",
        ),
        pytest.param(
            _schema_applied_veto_payload(
                not_applied_reason="final_signal_already_within_risk_limit"
            ),
            ("state='veto_applied'", "not_applied_reason"),
            id="applied-with-not-applied-reason",
        ),
        pytest.param(
            _schema_applied_veto_payload(to="buy"),
            ("state='veto_applied'", "transition 'buy'->'buy' is not allowed"),
            id="applied-with-identical-transition",
        ),
        pytest.param(
            _schema_applied_veto_payload(**{"from": "hold", "to": "sell"}),
            ("state='veto_applied'", "transition 'hold'->'sell' is not allowed"),
            id="veto-action-with-downgrade-transition",
        ),
        pytest.param(
            _schema_risk_control_payload(**{"from": "buy", "to": "hold"}),
            ("state='no_evidence'", "forbids from, to, and reason"),
            id="not-applied-with-transition",
        ),
        pytest.param(
            _schema_risk_control_payload(
                evidence_present=False,
                trigger="risk_veto",
                planned_action="cap_buy_to_hold",
            ),
            ("evidence_present=False", "trigger='risk_veto'"),
            id="override-trigger-without-evidence",
        ),
        pytest.param(
            _schema_risk_control_payload(
                evidence_present=True,
                trigger="risk_veto",
                planned_action="downgrade",
                not_applied_reason="override_disabled",
                override_enabled=False,
            ),
            ("state='veto_disabled'", "planned_action='downgrade'"),
            id="trigger-action-mismatch",
        ),
        pytest.param(
            _schema_risk_control_payload(
                evidence_present=True,
                trigger="risk_veto",
                planned_action="cap_buy_to_hold",
                not_applied_reason="override_disabled",
                current="hold",
                target="hold",
            ),
            ("state='veto_within_limit'", "not_applied_reason='override_disabled'"),
            id="override-disabled-reason-while-enabled",
        ),
        pytest.param(
            _schema_risk_control_payload(
                evidence_present=True,
                trigger="risk_veto",
                planned_action="cap_buy_to_hold",
                not_applied_reason="no_trigger",
                current="hold",
                target="hold",
            ),
            ("state='veto_within_limit'", "not_applied_reason='no_trigger'"),
            id="no-trigger-reason-with-override-trigger",
        ),
        pytest.param(
            _schema_risk_control_payload(
                evidence_present=True,
                trigger="high_risk_evidence",
                not_applied_reason="final_signal_already_within_risk_limit",
                current="hold",
                target="hold",
            ),
            (
                "state='evidence_without_override_trigger'",
                "not_applied_reason='final_signal_already_within_risk_limit'",
            ),
            id="within-limit-reason-without-override-trigger",
        ),
        pytest.param(
            _schema_risk_control_payload(
                evidence_present=True,
                trigger="risk_veto",
                planned_action="cap_buy_to_hold",
                not_applied_reason="final_signal_already_within_risk_limit",
                override_enabled=False,
            ),
            (
                "state='veto_disabled'",
                "not_applied_reason='final_signal_already_within_risk_limit'",
            ),
            id="within-limit-reason-while-override-disabled",
        ),
        pytest.param(
            _schema_risk_control_payload(current="buy", target="hold"),
            ("state='no_evidence'", "current and target to match"),
            id="not-applied-with-different-current-and-target",
        ),
    ],
)
def test_risk_control_schema_rejects_contradictory_state_matrix(payload, expected_markers):
    with pytest.raises(ValidationError) as exc_info:
        AgentDisagreementRiskControl.model_validate(payload)

    error = str(exc_info.value)
    assert all(marker in error for marker in expected_markers)


@pytest.mark.parametrize(
    ("payload", "expected_path"),
    [
        pytest.param(
            _schema_explanation_payload(decision_path="apply_risk_control"),
            "synthesize_agent_inputs",
            id="apply-path-without-applied-risk-control",
        ),
        pytest.param(
            _schema_explanation_payload(
                risk_control=_schema_applied_veto_payload(),
                decision_path="preserve_final_signal_after_risk_check",
            ),
            "apply_risk_control",
            id="applied-risk-control-with-non-apply-path",
        ),
        pytest.param(
            _schema_explanation_payload(decision_path="degraded_partial_result"),
            "synthesize_agent_inputs",
            id="degraded-path-without-event",
        ),
        pytest.param(
            _schema_explanation_payload(
                degraded_events=[
                    {"stage": "intel", "reason": "timeout", "critical": False}
                ],
                decision_path="synthesize_agent_inputs",
            ),
            "degraded_partial_result",
            id="timeout-event-with-normal-synthesis-path",
        ),
        pytest.param(
            _schema_explanation_payload(
                risk_control=_schema_risk_control_payload(
                    evidence_present=True,
                    trigger="high_risk_evidence",
                    not_applied_reason="no_trigger",
                ),
                decision_path="synthesize_agent_inputs",
            ),
            "preserve_final_signal_after_risk_check",
            id="risk-evidence-with-normal-synthesis-path",
        ),
        pytest.param(
            _schema_explanation_payload(
                decision_path="synthesize_agent_inputs",
                mixed=True,
            ),
            "synthesize_mixed_signals",
            id="mixed-signals-with-generic-synthesis-path",
        ),
    ],
)
def test_disagreement_schema_rejects_decision_path_contradictions(payload, expected_path):
    with pytest.raises(ValidationError) as exc_info:
        AgentDisagreementExplanation.model_validate(payload)

    message = str(exc_info.value)
    assert "decision_path=" in message
    assert f"expected {expected_path!r}" in message


def test_high_severity_risk_flag_takes_override_priority():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.86))
    ctx.add_risk_flag(category="regulatory", description="material investigation", severity="high")

    summary = build_agent_disagreement_summary(ctx)

    assert summary["risk_override_present"] is True
    assert summary["risk_control"]["evidence_present"] is True
    assert summary["risk_control"]["override_trigger_present"] is True
    assert summary["conflict_type"] == "risk_override"
    assert summary["decision_path_hint"] == "prioritize_risk_controls_and_cap_buy_signal"


def test_risk_level_high_is_evidence_not_override_by_itself():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.86))
    ctx.add_opinion(
        AgentOpinion(
            agent_name="risk",
            signal="hold",
            confidence=0.7,
            raw_data={"risk_level": "high"},
        )
    )

    summary = build_agent_disagreement_summary(ctx)

    assert summary["risk_override_present"] is False
    assert summary["risk_control"]["evidence_present"] is True
    assert summary["risk_control"]["override_trigger_present"] is False
    assert summary["conflict_type"] != "risk_override"
    assert summary["decision_path_hint"] != "prioritize_risk_controls_and_cap_buy_signal"


def test_disabled_risk_override_keeps_evidence_but_omits_override_hint():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.86))
    ctx.add_opinion(
        AgentOpinion(
            agent_name="risk",
            signal="sell",
            confidence=0.9,
            raw_data={"veto_buy": True},
        )
    )

    summary = build_agent_disagreement_summary(ctx, risk_override_enabled=False)

    assert summary["risk_override_present"] is False
    assert summary["risk_control"]["evidence_present"] is True
    assert summary["risk_control"]["override_enabled"] is False
    assert summary["risk_control"]["override_trigger_present"] is True
    assert summary["conflict_type"] != "risk_override"
    assert summary["decision_path_hint"] != "prioritize_risk_controls_and_cap_buy_signal"


def test_degraded_stage_summary_is_low_sensitivity():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="hold", confidence=0.64))
    ctx.meta["degraded_stages"] = [
        {
            "stage_name": "intel",
            "status": "failed",
            "non_critical": True,
            "error": "raw failure text",
            "private_payload": "private tool payload",
        }
    ]

    summary = build_agent_disagreement_summary(ctx)
    summary_text = str(summary)

    assert summary["degraded_result"]["present"] is True
    assert summary["degraded_result"]["non_critical_stage_present"] is True
    assert summary["degraded_result"]["stages"] == [
        {"stage_name": "intel", "status": "failed", "non_critical": True}
    ]
    assert "raw failure text" not in summary_text
    assert "private tool payload" not in summary_text


def test_degraded_reader_uses_only_failed_meta_records_and_dedupes():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.set_data("degraded_stages", [
        {"stage_name": "risk", "status": "failed", "non_critical": True}
    ])
    ctx.meta["stage_results"] = [
        {"stage_name": "intel", "status": "failed", "non_critical": True}
    ]
    ctx.set_data("stage_results", [
        {"stage_name": "skill", "status": "failed", "non_critical": True}
    ])
    ctx.meta["degraded_stages"] = [
        {"stage_name": "intel", "status": "failed", "non_critical": True},
        {"stage_name": "intel", "status": "failed", "non_critical": True},
        {"stage_name": "risk", "status": "timeout", "non_critical": True},
        {"stage": "legacy_alias", "status": "failed", "non_critical": True},
    ]

    summary = build_agent_disagreement_summary(ctx)

    assert summary["degraded_result"]["stages"] == [
        {"stage_name": "intel", "status": "failed", "non_critical": True}
    ]


def test_directional_opinion_with_intel_failure_is_partial_not_bullish_consensus():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.74))
    ctx.meta["degraded_stages"] = [
        {"stage_name": "intel", "status": "failed", "non_critical": True}
    ]

    summary = build_agent_disagreement_summary(ctx)

    assert summary["conflict_type"] == "partial_bullish_with_degraded_inputs"
    assert summary["decision_path_hint"] == "state_degraded_inputs_before_any_bullish_lean"
    assert summary["conflict_type"] != "aligned_bullish"
    assert summary["decision_path_hint"] != "use_bullish_consensus_with_price_and_risk_checks"


def test_directional_opinion_with_risk_failure_is_partial_not_bullish_consensus():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.74))
    ctx.add_opinion(AgentOpinion(agent_name="intel", signal="hold", confidence=0.52))
    ctx.meta["degraded_stages"] = [
        {"stage_name": "risk", "status": "failed", "non_critical": True}
    ]

    summary = build_agent_disagreement_summary(ctx)

    assert summary["conflict_type"] == "partial_bullish_with_degraded_inputs"
    assert summary["degraded_result"]["non_critical_stage_present"] is True
    assert summary["conflict_type"] != "aligned_bullish"


def test_directional_opinion_with_specialist_failure_is_partial_and_non_critical():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="sell", confidence=0.74))
    ctx.add_opinion(AgentOpinion(agent_name="intel", signal="hold", confidence=0.52))
    ctx.meta["degraded_stages"] = [
        {"stage_name": "chan_theory", "status": "failed", "non_critical": True}
    ]

    summary = build_agent_disagreement_summary(ctx)

    assert summary["conflict_type"] == "partial_bearish_with_degraded_inputs"
    assert summary["decision_path_hint"] == "state_degraded_inputs_before_any_bearish_lean"
    assert summary["degraded_result"]["non_critical_stage_present"] is True
    assert summary["degraded_result"]["stages"] == [
        {"stage_name": "chan_theory", "status": "failed", "non_critical": True}
    ]


def _mock_optional_litellm(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", MagicMock())


def test_decision_agent_prompt_includes_disagreement_summary_when_present(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.agents.decision_agent import DecisionAgent

    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.72))
    ctx.add_opinion(AgentOpinion(agent_name="intel", signal="sell", confidence=0.68))
    summary = build_agent_disagreement_summary(ctx)
    ctx.meta["agent_disagreement_summary"] = summary

    message = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock()).build_user_message(ctx)

    assert "## Agent Disagreement Summary" in message
    assert "mixed_directional_signals" in message
    assert "technical" in message


def test_decision_agent_build_messages_injects_disagreement_summary_once(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.agents.decision_agent import DecisionAgent

    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.72))
    ctx.add_opinion(AgentOpinion(agent_name="intel", signal="sell", confidence=0.68))
    ctx.set_data("realtime_quote", {"price": 123.45})
    ctx.meta["agent_disagreement_summary"] = build_agent_disagreement_summary(ctx)

    messages = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())._build_messages(ctx)
    combined = "\n".join(str(message.get("content", "")) for message in messages)

    assert combined.count("## Agent Disagreement Summary") == 1
    assert combined.count("mixed_directional_signals") == 1
    assert "[Pre-fetched: realtime_quote]" in combined
    assert "[Pre-fetched: agent_disagreement_summary]" not in combined


def test_decision_agent_prompt_omits_summary_when_context_lacks_it(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.agents.decision_agent import DecisionAgent

    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8))

    message = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock()).build_user_message(ctx)

    assert "## Agent Opinions" in message
    assert "## Agent Disagreement Summary" not in message


def test_orchestrator_prepare_decision_context_sets_summary_without_running_agents(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.orchestrator import AgentOrchestrator

    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.72))
    ctx.add_opinion(AgentOpinion(agent_name="intel", signal="sell", confidence=0.68))
    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=True),
    )

    orchestrator._prepare_decision_context(ctx)

    summary = ctx.meta.get("agent_disagreement_summary")
    assert summary
    assert summary["conflict_type"] == "mixed_directional_signals"
    assert ctx.get_data("agent_disagreement_summary") is None


def test_orchestrator_prepare_decision_context_respects_risk_override_config(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.orchestrator import AgentOrchestrator

    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.72))
    ctx.add_opinion(
        AgentOpinion(
            agent_name="risk",
            signal="sell",
            confidence=0.9,
            raw_data={"veto_buy": True},
        )
    )
    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=False),
    )

    orchestrator._prepare_decision_context(ctx)

    summary = ctx.meta.get("agent_disagreement_summary")
    assert summary["risk_override_present"] is False
    assert summary["risk_control"]["override_enabled"] is False
    assert summary["risk_control"]["override_trigger_present"] is True
    assert summary["conflict_type"] != "risk_override"


def test_orchestrator_builds_final_disagreement_explanation(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.orchestrator import AgentOrchestrator

    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8))
    ctx.add_opinion(AgentOpinion(agent_name="risk", signal="sell", confidence=0.9))
    ctx.meta["agent_disagreement_summary"] = {
        "conflict_type": "risk_override",
        "decision_path_hint": "prioritize_risk_controls_and_cap_buy_signal",
        "bullish_agents": [{"agent_name": "technical", "signal": "buy", "confidence": 0.8}],
        "bearish_agents": [{"agent_name": "risk", "signal": "sell", "confidence": 0.9}],
        "neutral_agents": [],
        "risk_control": {
            "evidence_present": True,
            "override_enabled": True,
            "override_trigger_present": True,
            "reason": "risk_veto",
        },
        "degraded_result": {
            "present": True,
            "stages": [
                {
                    "stage_name": "intel",
                    "status": "failed",
                    "non_critical": True,
                    "error": "raw secret error",
                }
            ],
        },
    }
    ctx.set_data("risk_override_applied", {
        "from": "buy",
        "to": "hold",
        "adjustment": "veto",
        "reason": "risk_veto",
    })
    ctx.set_data("final_dashboard", {"decision_type": "hold", "dashboard": {}})
    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=True),
    )

    explanation = orchestrator._build_agent_disagreement_explanation(ctx)

    assert explanation["base_disagreement"]["type"] == "mixed_directional_signals"
    assert explanation["decision_path"] == "apply_risk_control"
    assert explanation["degraded_events"] == [
        {"stage": "intel", "reason": "non_critical_failure", "critical": False}
    ]
    assert explanation["risk_control"]["applied"] is True
    assert explanation["risk_control"]["trigger"] == "risk_veto"
    assert explanation["risk_control"]["planned_action"] == "cap_buy_to_hold"
    assert explanation["risk_control"]["from"] == "buy"
    assert explanation["risk_control"]["to"] == "hold"
    assert AgentDisagreementExplanation.model_validate(explanation).model_dump() == explanation
    assert "conflict_type=" not in explanation["summary"]
    assert "raw secret error" not in str(explanation)


def test_orchestrator_preserves_base_disagreement_when_risk_control_does_not_apply(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.orchestrator import AgentOrchestrator

    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8))
    ctx.add_opinion(AgentOpinion(agent_name="intel", signal="sell", confidence=0.7))
    ctx.add_opinion(AgentOpinion(
        agent_name="risk",
        signal="sell",
        confidence=0.9,
        raw_data={"veto_buy": True},
    ))
    ctx.meta["agent_disagreement_summary"] = {
        "conflict_type": "risk_override",
        "decision_path_hint": "prioritize_risk_controls_and_cap_buy_signal",
        "bullish_agents": [{"agent_name": "technical", "signal": "buy", "confidence": 0.8}],
        "bearish_agents": [
            {"agent_name": "intel", "signal": "sell", "confidence": 0.7},
            {"agent_name": "risk", "signal": "sell", "confidence": 0.9},
        ],
        "neutral_agents": [],
        "risk_control": {
            "evidence_present": True,
            "override_enabled": True,
            "override_trigger_present": True,
            "reason": "risk_veto",
        },
        "degraded_result": {"present": False, "stages": []},
    }
    ctx.set_data("final_dashboard", {"decision_type": "hold", "dashboard": {}})
    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=True),
    )

    explanation = orchestrator._build_agent_disagreement_explanation(ctx)

    assert explanation["base_disagreement"]["type"] == "mixed_directional_signals"
    assert explanation["decision_path"] == "preserve_final_signal_after_risk_check"
    assert explanation["risk_control"]["evidence_present"] is True
    assert explanation["risk_control"]["trigger"] == "risk_veto"
    assert explanation["risk_control"]["planned_action"] == "cap_buy_to_hold"
    assert explanation["risk_control"]["applied"] is False
    assert explanation["risk_control"]["not_applied_reason"] == "final_signal_already_within_risk_limit"
    assert "conflict_type=" not in explanation["summary"]


def test_orchestrator_reports_no_trigger_for_high_risk_evidence_when_override_is_disabled(
    monkeypatch,
):
    _mock_optional_litellm(monkeypatch)
    from src.agent.orchestrator import AgentOrchestrator

    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8))
    ctx.add_opinion(AgentOpinion(
        agent_name="risk",
        signal="hold",
        confidence=0.7,
        raw_data={"risk_level": "high"},
    ))
    ctx.meta["agent_disagreement_summary"] = build_agent_disagreement_summary(
        ctx,
        risk_override_enabled=False,
    )
    ctx.set_data("final_dashboard", {"decision_type": "hold", "dashboard": {}})
    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=False),
    )

    explanation = orchestrator._build_agent_disagreement_explanation(ctx)

    assert explanation["risk_control"]["evidence_present"] is True
    assert explanation["risk_control"]["trigger"] == "high_risk_evidence"
    assert explanation["risk_control"]["planned_action"] == "none"
    assert explanation["risk_control"]["not_applied_reason"] == "no_trigger"
    assert explanation["decision_path"] == "preserve_final_signal_after_risk_check"


def test_orchestrator_records_actual_downgrade_when_high_flag_also_implies_veto(
    monkeypatch,
):
    _mock_optional_litellm(monkeypatch)
    from src.agent.orchestrator import AgentOrchestrator

    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="hold", confidence=0.8))
    ctx.add_opinion(AgentOpinion(
        agent_name="risk",
        signal="sell",
        confidence=0.9,
        raw_data={"signal_adjustment": "downgrade_one"},
    ))
    ctx.add_risk_flag("regulatory", "material investigation", severity="high")
    ctx.meta["agent_disagreement_summary"] = build_agent_disagreement_summary(ctx)
    ctx.set_data("final_dashboard", {"decision_type": "hold", "dashboard": {}})
    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=True),
    )

    orchestrator._apply_risk_override(ctx)
    explanation = orchestrator._build_agent_disagreement_explanation(ctx)

    assert ctx.get_data("risk_override_applied") == {
        "from": "hold",
        "to": "sell",
        "adjustment": "downgrade_one",
        "reason": "downgrade_one",
    }
    assert explanation["risk_control"]["trigger"] == "risk_downgrade"
    assert explanation["risk_control"]["planned_action"] == "downgrade"
    assert explanation["risk_control"]["from"] == "hold"
    assert explanation["risk_control"]["to"] == "sell"
    assert explanation["risk_control"]["reason"] == "downgrade_one"
    assert explanation["decision_path"] == "apply_risk_control"


def test_final_explanation_reuses_summary_contract_for_risk_clear_buy(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.orchestrator import AgentOrchestrator

    def make_context(with_summary: bool) -> AgentContext:
        ctx = AgentContext(query="test", stock_code="600519")
        ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8))
        ctx.add_opinion(AgentOpinion(
            agent_name="risk",
            signal="buy",
            confidence=0.7,
            raw_data={"risk_level": "none"},
        ))
        if with_summary:
            ctx.meta["agent_disagreement_summary"] = build_agent_disagreement_summary(ctx)
        ctx.set_data("final_dashboard", {"decision_type": "buy", "dashboard": {}})
        return ctx

    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=True),
    )

    with_summary = orchestrator._build_agent_disagreement_explanation(make_context(True))
    without_summary = orchestrator._build_agent_disagreement_explanation(make_context(False))

    assert with_summary["base_disagreement"] == without_summary["base_disagreement"]
    assert with_summary["base_disagreement"]["type"] == "bullish_with_neutral"
    assert [item["agent_name"] for item in with_summary["base_disagreement"]["bullish_agents"]] == ["technical"]
    assert [item["agent_name"] for item in with_summary["base_disagreement"]["neutral_agents"]] == ["risk"]


def test_orchestrator_final_explanation_summary_is_localized(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=True),
    )

    summaries = {}
    for language in ("zh", "en", "ko"):
        ctx = AgentContext(query="test", stock_code="600519")
        ctx.meta["report_language"] = language
        ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8))
        ctx.add_opinion(AgentOpinion(agent_name="intel", signal="sell", confidence=0.7))
        ctx.set_data("final_dashboard", {"decision_type": "hold", "dashboard": {}})
        summaries[language] = orchestrator._build_agent_disagreement_explanation(ctx)["summary"]

    assert "基础 Agent" in summaries["zh"]
    assert "Base agents" in summaries["en"]
    assert "기초 Agent" in summaries["ko"]
    for summary in summaries.values():
        assert "conflict_type=" not in summary
        assert "risk_evidence_present=" not in summary
        assert "decision_path=" not in summary


def test_orchestrator_builds_no_explanation_without_summary(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=True),
    )

    assert orchestrator._build_agent_disagreement_explanation(AgentContext()) is None


def test_orchestrator_attach_explanation_without_summary_uses_runtime_facts(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.orchestrator import AgentOrchestrator

    ctx = AgentContext(query="test", stock_code="600519")
    dashboard = {"decision_type": "buy", "dashboard": {"core_conclusion": {"one_sentence": "ok"}}}
    ctx.set_data("final_dashboard", dashboard)
    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=True),
    )

    orchestrator._attach_agent_disagreement_explanation(ctx)

    explanation = ctx.get_data("final_dashboard")["dashboard"]["agent_disagreement_explanation"]
    assert explanation["base_disagreement"]["type"] == "insufficient_opinions"
    assert explanation["risk_control"]["applied"] is False


def test_orchestrator_prepare_decision_context_propagates_summary_errors(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent import orchestrator as orchestrator_module
    from src.agent.orchestrator import AgentOrchestrator

    def raise_summary_error(*args, **kwargs):
        raise RuntimeError("summary bug")

    monkeypatch.setattr(orchestrator_module, "build_agent_disagreement_summary", raise_summary_error)
    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=True),
    )

    try:
        orchestrator._prepare_decision_context(AgentContext(query="test", stock_code="600519"))
    except RuntimeError as exc:
        assert str(exc) == "summary bug"
    else:
        raise AssertionError("summary errors must not be swallowed")


def test_orchestrator_records_specialist_failure_using_single_criticality_source(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.orchestrator import AgentOrchestrator

    ctx = AgentContext(query="test", stock_code="600519")
    result = StageResult(stage_name="chan_theory", status=StageStatus.FAILED, error="raw error")
    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=True),
    )
    orchestrator._skill_agent_names = {"chan_theory"}

    assert orchestrator._is_non_critical_stage("intel") is True
    assert orchestrator._is_non_critical_stage("risk") is True
    assert orchestrator._is_non_critical_stage("chan_theory") is True
    assert orchestrator._is_non_critical_stage("technical") is False

    orchestrator._record_degraded_stage(ctx, "chan_theory", result)

    assert ctx.meta["degraded_stages"] == [
        {"stage_name": "chan_theory", "status": "failed", "non_critical": True}
    ]
    summary = build_agent_disagreement_summary(ctx)
    assert summary["degraded_result"]["non_critical_stage_present"] is True


def test_orchestrator_rejects_non_failed_degraded_stage_markers(monkeypatch):
    _mock_optional_litellm(monkeypatch)
    from src.agent.orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=True),
    )
    result = StageResult(stage_name="intel", status=StageStatus.SKIPPED)

    try:
        orchestrator._record_degraded_stage(AgentContext(), "intel", result)
    except ValueError as exc:
        assert "failed stages" in str(exc)
    else:
        raise AssertionError("only failed stage results may produce degraded markers")
