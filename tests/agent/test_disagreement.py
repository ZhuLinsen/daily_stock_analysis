# -*- coding: utf-8 -*-
"""Business-level tests for the final disagreement explanation."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import AgentContext, AgentOpinion
from src.schemas.report_schema import AnalysisReportSchema


def _orchestrator(*, risk_override: bool = True) -> AgentOrchestrator:
    return AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=SimpleNamespace(agent_risk_override=risk_override),
    )


def _context(*, decision_type: str = "hold") -> AgentContext:
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.set_data(
        "final_dashboard",
        {"decision_type": decision_type, "dashboard": {}},
    )
    return ctx


def _explanation(orchestrator: AgentOrchestrator, ctx: AgentContext):
    orchestrator._apply_risk_override(ctx)
    return orchestrator._build_agent_disagreement_explanation(ctx)


def test_final_explanation_preserves_mixed_agent_disagreement():
    ctx = _context()
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.72))
    ctx.add_opinion(AgentOpinion(agent_name="intel", signal="sell", confidence=0.68))

    explanation = _explanation(_orchestrator(), ctx)

    assert explanation["base_disagreement"]["type"] == "mixed_directional_signals"
    assert explanation["base_disagreement"]["bullish_agents"] == [
        {"agent_name": "technical", "signal": "buy", "confidence": 0.72}
    ]
    assert explanation["base_disagreement"]["bearish_agents"] == [
        {"agent_name": "intel", "signal": "sell", "confidence": 0.68}
    ]


def test_final_explanation_records_applied_risk_override():
    ctx = _context(decision_type="buy")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8))
    ctx.add_opinion(
        AgentOpinion(
            agent_name="risk",
            signal="sell",
            confidence=0.9,
            raw_data={"veto_buy": True},
        )
    )

    explanation = _explanation(_orchestrator(), ctx)

    assert ctx.get_data("final_dashboard")["decision_type"] == "hold"
    assert explanation["risk_control"] == {
        "evidence_present": True,
        "override_enabled": True,
        "trigger": "risk_veto",
        "applied": True,
        "from_signal": "buy",
        "to_signal": "hold",
        "reason": "risk_veto",
    }


def test_final_explanation_records_risk_without_signal_change():
    ctx = _context(decision_type="hold")
    ctx.add_opinion(
        AgentOpinion(
            agent_name="risk",
            signal="sell",
            confidence=0.9,
            raw_data={"veto_buy": True},
        )
    )

    explanation = _explanation(_orchestrator(), ctx)

    assert ctx.get_data("final_dashboard")["decision_type"] == "hold"
    assert explanation["risk_control"] == {
        "evidence_present": True,
        "override_enabled": True,
        "trigger": "risk_veto",
        "applied": False,
        "reason": "final_signal_already_within_risk_limit",
    }


def test_final_explanation_surfaces_real_degraded_stage():
    ctx = _context()
    orchestrator = _orchestrator()
    orchestrator._record_degraded_event(
        ctx,
        stage="intel",
        reason="timeout",
    )

    explanation = _explanation(orchestrator, ctx)

    assert explanation["degraded_events"] == [
        {"stage": "intel", "reason": "timeout"}
    ]


def test_final_explanation_is_low_sensitivity():
    ctx = _context()
    ctx.add_opinion(
        AgentOpinion(
            agent_name="technical",
            signal="buy",
            confidence=0.82,
            reasoning="secret reasoning",
            raw_data={"token": "secret-token", "private_payload": "private position"},
        )
    )

    explanation = _explanation(_orchestrator(), ctx)
    serialized = json.dumps(explanation)

    assert "technical" in serialized
    assert "secret reasoning" not in serialized
    assert "secret-token" not in serialized
    assert "private position" not in serialized


def test_top_level_report_schema_round_trip_preserves_explanation():
    ctx = _context(decision_type="buy")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8))
    ctx.add_opinion(
        AgentOpinion(
            agent_name="risk",
            signal="sell",
            confidence=0.9,
            raw_data={"veto_buy": True},
        )
    )
    orchestrator = _orchestrator()
    explanation = _explanation(orchestrator, ctx)
    report_payload = ctx.get_data("final_dashboard")
    report_payload["dashboard"]["agent_disagreement_explanation"] = explanation

    report = AnalysisReportSchema.model_validate(report_payload)
    dumped = report.model_dump()
    json_dumped = json.loads(report.model_dump_json())
    round_tripped = AnalysisReportSchema.model_validate(json_dumped).model_dump()

    expected = dumped["dashboard"]["agent_disagreement_explanation"]
    assert expected["risk_control"]["from_signal"] == "buy"
    assert json_dumped["dashboard"]["agent_disagreement_explanation"] == expected
    assert round_tripped["dashboard"]["agent_disagreement_explanation"] == expected
