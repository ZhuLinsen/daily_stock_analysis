# -*- coding: utf-8 -*-
"""Tests for the deterministic Pipeline-final Agent explanation."""

import pytest
from pydantic import ValidationError

from src.agent.final_explanation import (
    PipelineActionAdjustment,
    build_pipeline_final_explanation,
)
from src.agent.risk_override import RiskOverrideApplication
from src.agent.runtime_facts import (
    AgentRuntimeFacts,
    BaseAgentOpinionFact,
    DegradationBoundary,
    DegradedEvent,
    PipelineTerminationFact,
)
from src.agent.protocols import StageFailureReason
from src.schemas.report_schema import AgentDisagreementExplanation, AnalysisReportSchema


def _facts() -> AgentRuntimeFacts:
    return AgentRuntimeFacts(
        base_agent_opinions=(
            BaseAgentOpinionFact(agent="technical", signal="buy", confidence=0.82),
            BaseAgentOpinionFact(agent="intel", signal="sell", confidence=0.68),
        ),
        degraded_events=(
            DegradedEvent(
                stage="intel",
                reason=StageFailureReason.TIMEOUT,
                boundary=DegradationBoundary.DURING_STAGE,
            ),
        ),
        pipeline_termination=PipelineTerminationFact(
            reason=StageFailureReason.TIMEOUT,
            last_completed_stage="technical",
        ),
        risk_override_application=RiskOverrideApplication(
            evidence_present=True,
            override_enabled=True,
            trigger="risk_veto",
            applied=True,
            reason="risk_veto_applied",
            post_risk_signal="hold",
            from_signal="buy",
            to_signal="hold",
        ),
    )


def test_build_explanation_keeps_risk_and_pipeline_adjustments_distinct():
    facts = _facts()
    facts = AgentRuntimeFacts(
        base_agent_opinions=facts.base_agent_opinions,
        degraded_events=facts.degraded_events,
        pipeline_termination=facts.pipeline_termination,
        risk_override_application=RiskOverrideApplication(
            evidence_present=False,
            override_enabled=True,
            trigger="none",
            applied=False,
            reason="no_risk_evidence",
            post_risk_signal="buy",
        ),
    )

    payload = build_pipeline_final_explanation(
        runtime_facts=facts,
        pipeline_start_signal="buy",
        pipeline_start_action="buy",
        final_action="watch",
        pipeline_adjustments=(
            PipelineActionAdjustment(
                source="daily_market_context",
                from_action="buy",
                to_action="watch",
            ),
        ),
        data_quality={
            "level": "limited",
            "limitations": ["capital flow unavailable"],
        },
    )

    assert payload["risk_control"]["applied"] is False
    assert payload["risk_control"]["post_risk_signal"] == "buy"
    assert payload["final_adjustments"] == [
        {
            "source": "daily_market_context",
            "from_action": "buy",
            "to_action": "watch",
        }
    ]
    assert payload["pipeline_start_action"] == "buy"
    assert payload["final_action"] == "watch"
    assert payload["decision_path"] == "daily_market_context_adjusted"
    assert payload["data_quality"] == {
        "level": "limited",
        "limitations": ["capital flow unavailable"],
    }
    assert payload["pipeline_termination"] == {
        "reason": "timeout",
        "last_completed_stage": "technical",
    }


def test_build_explanation_uses_actual_risk_application_without_pipeline_relabeling():
    payload = build_pipeline_final_explanation(
        runtime_facts=_facts(),
        pipeline_start_signal="hold",
        pipeline_start_action="hold",
        final_action="hold",
    )

    assert payload["risk_control"]["reason"] == "risk_veto_applied"
    assert payload["risk_control"]["from_signal"] == "buy"
    assert payload["risk_control"]["to_signal"] == "hold"
    assert payload["final_adjustments"] == []
    assert payload["decision_path"] == "risk_veto_applied"


def test_schema_rejects_discontinuous_pipeline_adjustment_chain():
    payload = build_pipeline_final_explanation(
        runtime_facts=_facts(),
        pipeline_start_signal="hold",
        pipeline_start_action="hold",
        final_action="hold",
    )
    payload["final_adjustments"] = [
        {
            "source": "market_phase",
            "from_action": "buy",
            "to_action": "sell",
        }
    ]
    payload["final_action"] = "sell"

    with pytest.raises(ValidationError):
        AgentDisagreementExplanation.model_validate(payload)


@pytest.mark.parametrize("source", ["agent_result_conversion", "final_action_refresh"])
def test_schema_rejects_unreachable_action_adjustment_sources(source):
    payload = build_pipeline_final_explanation(
        runtime_facts=_facts(),
        pipeline_start_signal="hold",
        pipeline_start_action="buy",
        final_action="buy",
    )
    payload["final_adjustments"] = [
        {
            "source": source,
            "from_action": "buy",
            "to_action": "watch",
        }
    ]
    payload["final_action"] = "watch"

    with pytest.raises(ValidationError):
        AgentDisagreementExplanation.model_validate(payload)


def test_optional_report_schema_round_trips_final_explanation():
    explanation = build_pipeline_final_explanation(
        runtime_facts=_facts(),
        pipeline_start_signal="hold",
        pipeline_start_action="hold",
        final_action="hold",
    )
    report = AnalysisReportSchema.model_validate(
        {
            "stock_name": "Test",
            "decision_type": "hold",
            "dashboard": {"agent_disagreement_explanation": explanation},
        }
    )
    dumped = report.model_dump(mode="json", exclude_none=True)

    assert dumped["dashboard"]["agent_disagreement_explanation"] == explanation
    legacy = AnalysisReportSchema.model_validate(
        {"stock_name": "Legacy", "dashboard": {"core_conclusion": {}}}
    )
    assert legacy.dashboard.agent_disagreement_explanation is None


@pytest.mark.parametrize("field", ["reasoning", "raw_data", "token", "error"])
def test_schema_rejects_sensitive_or_unknown_fields(field):
    payload = build_pipeline_final_explanation(
        runtime_facts=_facts(),
        pipeline_start_signal="hold",
        pipeline_start_action="hold",
        final_action="hold",
    )
    payload[field] = "private"

    with pytest.raises(ValidationError):
        AgentDisagreementExplanation.model_validate(payload)


def test_missing_risk_application_preserves_pipeline_start_signal():
    facts = AgentRuntimeFacts(
        base_agent_opinions=(
            BaseAgentOpinionFact(agent="technical", signal="buy", confidence=0.8),
        ),
        risk_override_application=None,
    )

    payload = build_pipeline_final_explanation(
        runtime_facts=facts,
        pipeline_start_signal="buy",
        pipeline_start_action="buy",
        final_action="watch",
        pipeline_adjustments=(
            PipelineActionAdjustment(
                source="daily_market_context",
                from_action="buy",
                to_action="watch",
            ),
        ),
    )

    assert payload["risk_control"] == {
        "evidence_present": False,
        "override_enabled": False,
        "trigger": "none",
        "applied": False,
        "reason": "not_evaluated",
        "post_risk_signal": "buy",
    }
    assert payload["final_adjustments"] == [
        {
            "source": "daily_market_context",
            "from_action": "buy",
            "to_action": "watch",
        }
    ]


def test_final_explanation_has_one_authoritative_public_action():
    facts = AgentRuntimeFacts(
        base_agent_opinions=(
            BaseAgentOpinionFact(agent="technical", signal="buy", confidence=0.8),
        ),
    )

    payload = build_pipeline_final_explanation(
        runtime_facts=facts,
        pipeline_start_signal="hold",
        pipeline_start_action="buy",
        final_action="buy",
    )

    assert "final_signal" not in payload
    assert payload["pipeline_start_action"] == "buy"
    assert payload["final_action"] == "buy"
    assert payload["base_disagreement"]["type"] == "insufficient_opinions"


def test_final_explanation_excludes_invalid_runtime_facts_instead_of_forging_neutral():
    facts = AgentRuntimeFacts(
        base_agent_opinions=(
            BaseAgentOpinionFact(agent="technical", signal="sideways", confidence=0.8),
            BaseAgentOpinionFact(agent="intel", signal="unknown", confidence=0.7),
        ),
    )

    payload = build_pipeline_final_explanation(
        runtime_facts=facts,
        pipeline_start_signal="hold",
        pipeline_start_action="watch",
        final_action="watch",
    )

    assert payload["base_disagreement"] == {
        "type": "insufficient_opinions",
        "agents": [],
    }
