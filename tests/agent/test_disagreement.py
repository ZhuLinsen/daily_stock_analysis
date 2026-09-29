# -*- coding: utf-8 -*-
"""Tests for low-sensitivity multi-agent disagreement summaries."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.agent.disagreement import build_agent_disagreement_summary
from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus


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
    assert summary["conflict_type"] != "aligned_bullish"
    assert "risk_level" not in summary_text
    assert "private risk payload" not in summary_text


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
