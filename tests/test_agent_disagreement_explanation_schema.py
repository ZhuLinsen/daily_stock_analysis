# -*- coding: utf-8 -*-
"""Focused validation for the optional agent disagreement explanation schema."""

import copy
import json

import pytest
from pydantic import ValidationError

from src.agent.disagreement import (
    BaseDisagreementType,
    DecisionPath,
    classify_base_disagreement,
    derive_decision_path,
)
from src.agent.risk_override import RiskApplicationReason
from src.schemas.report_schema import AnalysisReportSchema


def _valid_report():
    return {
        "stock_name": "Test Stock",
        "decision_type": "hold",
        "dashboard": {
            "agent_disagreement_explanation": {
                "base_disagreement": {
                    "type": "mixed_directional_signals",
                    "agents": [
                        {"agent": "technical", "signal": "buy", "confidence": 0.82},
                        {"agent": "intel", "signal": "sell", "confidence": 0.68},
                    ],
                },
                "risk_control": {
                    "evidence_present": True,
                    "override_enabled": True,
                    "trigger": "risk_veto",
                    "applied": True,
                    "reason": "risk_veto_applied",
                    "final_signal": "hold",
                    "from_signal": "buy",
                    "to_signal": "hold",
                },
                "degraded_events": [],
                "decision_path": "risk_veto_applied",
            }
        },
    }


def test_optional_explanation_accepts_old_report():
    schema = AnalysisReportSchema.model_validate({
        "stock_name": "Legacy",
        "dashboard": {
            "core_conclusion": {"one_sentence": "legacy report"},
        },
    })

    assert schema.dashboard is not None
    assert schema.dashboard.agent_disagreement_explanation is None


def test_top_level_report_round_trips_explanation_with_public_json_fields():
    report = _valid_report()
    raw_explanation = report["dashboard"]["agent_disagreement_explanation"]
    raw_explanation["degraded_events"] = [{"stage": "intel", "reason": "stage_failure"}]
    schema = AnalysisReportSchema.model_validate(report)
    dumped_report = schema.model_dump(mode="json", exclude_none=True)
    encoded_report = json.dumps(dumped_report)
    reparsed = AnalysisReportSchema.model_validate(json.loads(encoded_report))
    assert reparsed.dashboard is not None
    assert reparsed.dashboard.agent_disagreement_explanation is not None
    assert reparsed.model_dump(mode="json", exclude_none=True) == dumped_report

    payload = dumped_report["dashboard"]["agent_disagreement_explanation"]

    assert payload["base_disagreement"]["type"] == "mixed_directional_signals"
    assert payload["base_disagreement"]["agents"][0]["signal"] == "buy"
    assert payload["risk_control"]["trigger"] == "risk_veto"
    assert payload["risk_control"]["reason"] == "risk_veto_applied"
    assert payload["risk_control"]["final_signal"] == "hold"
    assert payload["risk_control"]["from_signal"] == "buy"
    assert payload["risk_control"]["to_signal"] == "hold"
    assert payload["degraded_events"][0]["reason"] == "stage_failure"
    assert payload["decision_path"] == "risk_veto_applied"
    assert isinstance(payload["base_disagreement"]["type"], str)
    assert isinstance(payload["risk_control"]["trigger"], str)
    assert isinstance(payload["risk_control"]["reason"], str)
    assert isinstance(payload["degraded_events"][0]["reason"], str)
    assert isinstance(payload["decision_path"], str)
    assert isinstance(payload["risk_control"]["final_signal"], str)


@pytest.mark.parametrize(
    ("signals", "expected"),
    [
        ([], BaseDisagreementType.INSUFFICIENT_OPINIONS),
        (["buy"], BaseDisagreementType.INSUFFICIENT_OPINIONS),
        (["buy", "buy"], BaseDisagreementType.ALIGNED_BULLISH),
        (["sell", "sell"], BaseDisagreementType.ALIGNED_BEARISH),
        (["hold", "hold"], BaseDisagreementType.ALIGNED_NEUTRAL),
        (["buy", "hold"], BaseDisagreementType.BULLISH_WITH_NEUTRAL),
        (["sell", "hold"], BaseDisagreementType.BEARISH_WITH_NEUTRAL),
        (["buy", "sell"], BaseDisagreementType.MIXED_DIRECTIONAL_SIGNALS),
    ],
)
def test_base_disagreement_classification_boundaries(signals, expected):
    assert classify_base_disagreement(signals) == expected


@pytest.mark.parametrize(
    ("base_type", "expected"),
    [
        (BaseDisagreementType.INSUFFICIENT_OPINIONS, DecisionPath.LIMITED_OPINION_SYNTHESIS),
        (BaseDisagreementType.ALIGNED_BULLISH, DecisionPath.ALIGNED_AGENT_CONSENSUS),
        (BaseDisagreementType.ALIGNED_BEARISH, DecisionPath.ALIGNED_AGENT_CONSENSUS),
        (BaseDisagreementType.ALIGNED_NEUTRAL, DecisionPath.ALIGNED_AGENT_CONSENSUS),
        (
            BaseDisagreementType.BULLISH_WITH_NEUTRAL,
            DecisionPath.NON_CONFLICTING_SIGNALS_SYNTHESIZED,
        ),
        (
            BaseDisagreementType.BEARISH_WITH_NEUTRAL,
            DecisionPath.NON_CONFLICTING_SIGNALS_SYNTHESIZED,
        ),
        (BaseDisagreementType.MIXED_DIRECTIONAL_SIGNALS, DecisionPath.MIXED_SIGNALS_SYNTHESIZED),
    ],
)
def test_decision_path_maps_every_base_type(base_type, expected):
    assert derive_decision_path(
        base_type,
        RiskApplicationReason.NO_RISK_EVIDENCE,
        has_degraded_events=False,
    ) == expected


def test_decision_path_priority_is_risk_then_degradation_then_base_type():
    assert derive_decision_path(
        BaseDisagreementType.MIXED_DIRECTIONAL_SIGNALS,
        RiskApplicationReason.RISK_VETO_APPLIED,
        has_degraded_events=True,
    ) == DecisionPath.RISK_VETO_APPLIED
    assert derive_decision_path(
        BaseDisagreementType.ALIGNED_BULLISH,
        RiskApplicationReason.RISK_DOWNGRADE_APPLIED,
        has_degraded_events=True,
    ) == DecisionPath.RISK_DOWNGRADE_APPLIED
    assert derive_decision_path(
        BaseDisagreementType.MIXED_DIRECTIONAL_SIGNALS,
        RiskApplicationReason.NO_RISK_EVIDENCE,
        has_degraded_events=True,
    ) == DecisionPath.DEGRADED_SYNTHESIS


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["dashboard"]["agent_disagreement_explanation"]["risk_control"].update(
            override_enabled=False
        ),
        lambda value: value["dashboard"]["agent_disagreement_explanation"]["risk_control"].update(
            to_signal="buy", final_signal="buy"
        ),
        lambda value: value["dashboard"]["agent_disagreement_explanation"]["risk_control"].update(
            applied=False, reason="final_signal_already_within_risk_limit"
        ),
        lambda value: value["dashboard"]["agent_disagreement_explanation"]["base_disagreement"].update(
            type="aligned_bullish",
            agents=[{"agent": "intel", "signal": "sell", "confidence": 0.7}],
        ),
    ],
)
def test_cross_field_impossible_states_are_rejected(mutate):
    value = copy.deepcopy(_valid_report())
    mutate(value)

    with pytest.raises(ValidationError):
        AnalysisReportSchema.model_validate(value)


@pytest.mark.parametrize(
    ("path", "field", "value"),
    [
        (("base_disagreement", "agents", 0), "reasoning", "private"),
        (("risk_control",), "raw_data", {"token": "secret"}),
        (("degraded_events", 0), "error", "private failure"),
    ],
)
def test_explanation_submodels_forbid_extra_fields(path, field, value):
    report = _valid_report()
    explanation = report["dashboard"]["agent_disagreement_explanation"]
    explanation["degraded_events"] = [{"stage": "intel", "reason": "stage_failure"}]
    explanation["decision_path"] = "risk_veto_applied"

    target = explanation
    for item in path:
        target = target[item]
    target[field] = value

    with pytest.raises(ValidationError):
        AnalysisReportSchema.model_validate(report)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_agent_confidence_is_bounded(confidence):
    report = _valid_report()
    agents = report["dashboard"]["agent_disagreement_explanation"]["base_disagreement"]["agents"]
    agents[0]["confidence"] = confidence

    with pytest.raises(ValidationError):
        AnalysisReportSchema.model_validate(report)
