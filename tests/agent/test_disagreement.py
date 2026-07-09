# -*- coding: utf-8 -*-
"""Tests for low-sensitivity multi-agent disagreement summaries."""

from unittest.mock import MagicMock

from src.agent.disagreement import build_agent_disagreement_summary
from src.agent.protocols import AgentContext, AgentOpinion


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


def test_high_severity_risk_flag_takes_override_priority():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.86))
    ctx.add_risk_flag(category="regulatory", description="material investigation", severity="high")

    summary = build_agent_disagreement_summary(ctx)

    assert summary["risk_override_present"] is True
    assert summary["conflict_type"] == "risk_override"
    assert summary["decision_path_hint"] == "prioritize_risk_controls_and_cap_buy_signal"


def test_degraded_stage_summary_is_low_sensitivity():
    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="hold", confidence=0.64))
    ctx.meta["degraded_stages"] = [
        {
            "stage_name": "intel",
            "status": "failed",
            "error": "raw failure text",
            "private_payload": "private tool payload",
        }
    ]

    summary = build_agent_disagreement_summary(ctx)
    summary_text = str(summary)

    assert summary["degraded_result"]["present"] is True
    assert summary["degraded_result"]["non_critical_stage_present"] is True
    assert summary["degraded_result"]["stages"] == [{"stage_name": "intel", "status": "failed"}]
    assert "raw failure text" not in summary_text
    assert "private tool payload" not in summary_text


def test_decision_agent_prompt_includes_disagreement_summary_when_present():
    from src.agent.agents.decision_agent import DecisionAgent

    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.72))
    ctx.add_opinion(AgentOpinion(agent_name="intel", signal="sell", confidence=0.68))
    summary = build_agent_disagreement_summary(ctx)
    ctx.set_data("agent_disagreement_summary", summary)

    message = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock()).build_user_message(ctx)

    assert "## Agent Disagreement Summary" in message
    assert "mixed_directional_signals" in message
    assert "technical" in message


def test_decision_agent_prompt_omits_summary_when_context_lacks_it():
    from src.agent.agents.decision_agent import DecisionAgent

    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8))

    message = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock()).build_user_message(ctx)

    assert "## Agent Opinions" in message
    assert "## Agent Disagreement Summary" not in message


def test_orchestrator_prepare_decision_context_sets_summary_without_running_agents():
    from src.agent.orchestrator import AgentOrchestrator

    ctx = AgentContext(query="test", stock_code="600519")
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.72))
    ctx.add_opinion(AgentOpinion(agent_name="intel", signal="sell", confidence=0.68))
    orchestrator = AgentOrchestrator(tool_registry=MagicMock(), llm_adapter=MagicMock())

    orchestrator._prepare_decision_context(ctx)

    summary = ctx.get_data("agent_disagreement_summary")
    assert summary
    assert summary["conflict_type"] == "mixed_directional_signals"
