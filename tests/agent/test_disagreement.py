# -*- coding: utf-8 -*-
"""Tests for low-sensitivity multi-agent disagreement summaries."""

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

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


def test_evidence_debate_uses_agent_output_fields_and_preserves_high_risk_flags():
    from src.agent.agents.intel_agent import IntelAgent
    from src.agent.agents.risk_agent import RiskAgent
    from src.agent.agents.technical_agent import TechnicalAgent
    from src.agent.disagreement import build_evidence_debate_brief, should_trigger_evidence_debate

    ctx = AgentContext(stock_code="600519")
    agent_kwargs = dict(tool_registry=MagicMock(), llm_adapter=MagicMock())
    technical = TechnicalAgent(**agent_kwargs).post_process(ctx, json.dumps({
        "signal": "strong-buy", "confidence": 0.90, "reasoning": "MA5 support holds",
        "trend_score": 90,
    }))
    ctx.add_opinion(technical)
    assert should_trigger_evidence_debate(ctx, enabled=False) == (False, "disabled")
    assert should_trigger_evidence_debate(ctx, enabled=True) == (True, "high_conviction_buy")

    intel = IntelAgent(**agent_kwargs).post_process(ctx, json.dumps({
        "signal": "strong-sell", "confidence": 0.72, "reasoning": "Margin pressure",
        "key_news": [{"title": "Earnings warning", "impact": "negative"}],
        "risk_alerts": ["First alert", "Second alert", "Third alert"],
    }))
    ctx.add_opinion(intel)
    risk = RiskAgent(**agent_kwargs).post_process(ctx, json.dumps({
        "risk_level": "high",
        "flags": [{
            "category": "regulatory", "severity": "high", "description": "Material investigation",
            "source": "Exchange disclosure",
        }],
    }))
    ctx.add_opinion(risk)

    summary = build_agent_disagreement_summary(ctx)
    assert summary["conflict_type"] == "risk_override"
    assert should_trigger_evidence_debate(ctx, enabled=True) == (True, "mixed_directional_signals")
    brief = build_evidence_debate_brief(ctx, summary)
    assert brief["bull_arguments"][0]["signal"] == "strong_buy"
    assert brief["bull_arguments"][0]["source_evidence_ids"] == ["technical#0/trend_score"]
    assert brief["bear_arguments"][0]["signal"] == "strong_sell"
    assert "intel#1/key_news" in brief["bear_arguments"][0]["source_evidence_ids"]
    assert brief["risk_flags"][0] == {
        "category": "regulatory", "severity": "high", "description": "Material investigation",
        "source": "Exchange disclosure",
    }
    assert len(brief["risk_flags"]) == 3


@pytest.mark.parametrize("risk_level", ["none", "medium"])
def test_risk_opinion_alone_does_not_trigger_debate(risk_level):
    from src.agent.agents.risk_agent import RiskAgent
    from src.agent.disagreement import should_trigger_evidence_debate

    ctx = AgentContext()
    ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.72))
    ctx.add_opinion(AgentOpinion(agent_name="intel", signal="hold", confidence=0.62))
    risk = RiskAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    ctx.add_opinion(risk.post_process(ctx, json.dumps({"risk_level": risk_level, "risk_score": 85})))

    assert should_trigger_evidence_debate(ctx, enabled=True) == (False, "consensus_clear")


@pytest.mark.parametrize(
    "mode,enabled,risk_reply,override_enabled,low_conviction",
    [
        ("standard", False, "high", True, False),
        ("standard", True, "high", True, True),
        ("standard", True, "high", True, False),
        ("standard", True, None, False, False),
        ("standard", True, "invalid", True, False),
        ("standard", True, "invalid_score", True, False),
        ("standard", True, "incomplete", True, False),
        ("standard", True, "invalid_flags", True, False),
        ("quick", True, "missing_decisions", True, False),
        ("quick", True, "missing_veto", True, False),
        ("quick", True, "missing_adjustment", True, False),
        ("full", True, "high", True, False),
        ("specialist", True, "high", False, True),
        ("quick", True, "high", True, False),
    ],
)
def test_evidence_debate_runs_through_decision_and_risk_runtime(
    mode, enabled, risk_reply, override_enabled, low_conviction,
):
    from src.agent.llm_adapter import LLMResponse, ToolCall
    from src.agent.orchestrator import AgentOrchestrator
    from src.agent.tools.registry import ToolDefinition, ToolRegistry
    from src.core.pipeline import StockAnalysisPipeline
    from src.enums import ReportType

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="analyze_trend", description="Technical trend", parameters=[],
        handler=lambda: {"ma_alignment": "bullish"},
    ))
    decision_prompt = []
    risk_prompt = []

    def call_model(messages, tools, **kwargs):
        user_prompt = messages[-1]["content"]
        if user_prompt.startswith("Perform technical analysis"):
            return LLMResponse(tool_calls=[ToolCall("trend-call", "analyze_trend", {})])
        if messages[-1]["role"] == "tool":
            return LLMResponse(content=json.dumps({
                "signal": "buy", "confidence": 0.72 if low_conviction else 0.85, "reasoning": "Rising averages",
                "trend_score": 80,
            }))
        if user_prompt.startswith("Gather intelligence"):
            return LLMResponse(content=json.dumps({
                "signal": "hold" if low_conviction else "sell", "confidence": 0.72, "reasoning": "Earnings warning",
                "key_news": [{"title": "Earnings warning", "impact": "negative"}],
                "risk_alerts": ["First alert", "Second alert", "Third alert"],
            }))
        if user_prompt.startswith("Screen stock"):
            risk_prompt.append(user_prompt)
            if risk_reply is None:
                return LLMResponse(provider="error")
            if risk_reply == "incomplete":
                return LLMResponse(content='{"risk_level":"none"}')
            if risk_reply.startswith("missing_"):
                assessment = {
                    "risk_level": "medium", "risk_score": 65, "flags": [],
                    "reasoning": "Waiting to verify an earnings warning.",
                }
                if risk_reply == "missing_veto":
                    assessment["signal_adjustment"] = "none"
                elif risk_reply == "missing_adjustment":
                    assessment["veto_buy"] = False
                return LLMResponse(content=json.dumps(assessment))
            if risk_reply in {"invalid", "invalid_score", "invalid_flags"}:
                return LLMResponse(content=json.dumps({
                    "risk_level": "invalid" if risk_reply == "invalid" else "high",
                    "risk_score": "invalid" if risk_reply == "invalid_score" else 90,
                    "veto_buy": True,
                    "signal_adjustment": "downgrade_two",
                    "reasoning": "Unvalidated claim",
                    "flags": [
                        {"category": "regulatory", "severity": "high", "description": "Unvalidated claim"},
                        *([{"severity": "high"}] if risk_reply == "invalid_flags" else []),
                    ],
                }))
            return LLMResponse(content=json.dumps({
                "risk_level": risk_reply, "risk_score": 90, "veto_buy": True, "signal_adjustment": "none",
                "flags": [{"category": "regulatory", "severity": "high", "description": "Material investigation"}],
                "reasoning": "A material investigation is ongoing.",
            }))
        if user_prompt.startswith("Evaluate **"):
            return LLMResponse(content=json.dumps({
                "signal": "sell", "confidence": 0.66, "conditions_met": ["Volume contraction"],
            }))
        decision_prompt.append(user_prompt)
        return LLMResponse(content=json.dumps({
            "decision_type": "hold" if mode == "full" else "buy",
            "action": "add", "operation_advice": "立即买入", "sentiment_score": 80,
            "analysis_summary": "可以买入", "key_points": ["立即买入"],
            "phase_decision": {"immediate_action": "立即买入"},
            "dashboard": {
                "action": "buy", "phase_decision": {"immediate_action": "立即买入"},
                "battle_plan": {"action_checklist": ["立即买入"]},
            },
        }))

    adapter = SimpleNamespace(call_with_tools=call_model)
    orchestrator = AgentOrchestrator(
        tool_registry=registry,
        llm_adapter=adapter,
        mode=mode,
        config=SimpleNamespace(agent_risk_override=override_enabled, agent_debate_enabled=enabled),
    )
    result = orchestrator.run("Analyze 600519", {"stock_code": "600519"})

    assert result.success
    assert len(decision_prompt) == 1
    stages = [item["stage_name"] for item in result.stage_trajectories]
    if not enabled or (mode == "standard" and low_conviction):
        assert stages == ["technical", "intel", "decision"]
        assert not risk_prompt
        assert "Bull/Bear Evidence Debate" not in decision_prompt[0]
        assert result.dashboard["decision_type"] == "buy"
        assert not result.runtime_facts.risk_review_required
        assert result.runtime_facts.risk_review_status is None
        return

    expected_discovery = ["technical"] if mode == "quick" else ["technical", "intel"]
    assert stages[:len(expected_discovery)] == expected_discovery
    subsequent_stages = stages[len(expected_discovery):]
    assert subsequent_stages[-2:] == ["risk", "decision"]
    if mode == "specialist":
        assert subsequent_stages[:-2]
        assert all(name.startswith("skill_") for name in subsequent_stages[:-2])
        assert "/conditions_met" in decision_prompt[0]
        assert "/conditions_met" in risk_prompt[0]
    else:
        assert subsequent_stages == ["risk", "decision"]
    assert len(risk_prompt) == 1 and "tool:trend-call" in risk_prompt[0]
    assert '"technical#0/trend_score": "80"' in risk_prompt[0]
    assert "Bull/Bear Evidence Debate" in decision_prompt[0]
    assert "tool:trend-call" in decision_prompt[0]
    if mode != "quick" and not low_conviction:
        assert "intel#1/key_news" in decision_prompt[0]
    assert result.tool_calls_log[0]["tool_call_id"] == "trend-call"
    expected_trigger = "high_conviction_buy" if mode == "quick" else "mixed_directional_signals"
    assert result.runtime_facts.evidence_debate_trigger_reason == expected_trigger
    assert result.runtime_facts.risk_review_required
    if risk_reply == "high":
        assert "Mandatory risk review status: completed" in decision_prompt[0]
        assert '"risk_flags": [{"category": "regulatory", "severity": "high"' in decision_prompt[0]
        assert result.runtime_facts.risk_review_status == StageStatus.COMPLETED
        assert result.runtime_facts.risk_override_application.applied is override_enabled
        assert result.dashboard["decision_type"] == ("hold" if override_enabled else "buy")
        if override_enabled:
            assert result.runtime_facts.risk_override_application.from_signal.value == "buy"
            assert "风控审查已下调操作建议。" in result.dashboard["analysis_summary"]
            assert result.dashboard["dashboard"]["battle_plan"]["action_checklist"] == [result.dashboard["analysis_summary"]]
    else:
        assert "Mandatory risk review status: failed" in decision_prompt[0]
        assert "Unvalidated claim" not in decision_prompt[0]
        assert result.runtime_facts.risk_review_status == StageStatus.FAILED
        assert result.runtime_facts.risk_override_application.post_risk_signal.value == "hold"
        assert result.dashboard["decision_type"] == "hold"
        assert result.dashboard["operation_advice"] == "观望"
        assert "风控必审尚未完成" in result.dashboard["analysis_summary"]
        assert "立即买入" not in result.dashboard["key_points"]
        assert result.dashboard["phase_decision"]["immediate_action"] == "观望"
        assert result.dashboard["dashboard"]["phase_decision"]["immediate_action"] == "观望"
        assert result.stage_trajectories[-2]["status"] == "failed"

    if risk_reply != "high" or override_enabled:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(report_language="zh")
        analysis = pipeline._agent_result_to_analysis_result(result, "600519", "贵州茅台", ReportType.FULL, "test")
        assert analysis.action == "watch"


@pytest.mark.parametrize(
    "veto_buy,signal_adjustment,override_enabled,blocked",
    [(True, "none", True, True), (False, "downgrade_one", True, True),
     (True, "none", False, False), (False, "none", True, False)],
)
def test_chat_saves_the_reply_after_mandatory_risk_review(veto_buy, signal_adjustment, override_enabled, blocked):
    from src.agent.conversation import conversation_manager
    from src.agent.llm_adapter import LLMResponse
    from src.agent.orchestrator import AgentOrchestrator, PreparedOrchestratorChatTurn
    from src.agent.tools.registry import ToolRegistry

    adapter = SimpleNamespace(call_with_tools=MagicMock(side_effect=[
        LLMResponse(content='{"signal":"buy","confidence":0.85}'),
        LLMResponse(content='{"signal":"hold","confidence":0.72}'),
        LLMResponse(content=json.dumps({
            "risk_level": "medium", "risk_score": 65, "flags": [], "reasoning": "Earnings warning confirmed.",
            "veto_buy": veto_buy, "signal_adjustment": signal_adjustment,
        })),
        LLMResponse(content="现在立即买入。"),
    ]))
    orchestrator = AgentOrchestrator(
        tool_registry=ToolRegistry(), llm_adapter=adapter, mode="standard",
        config=SimpleNamespace(agent_debate_enabled=True, agent_risk_override=override_enabled),
    )
    ctx = AgentContext(stock_code="600519", query="现在可以买入吗？")
    ctx.meta.update(response_mode="chat", report_language="zh")
    snapshot, db_manager = {"session_id": "risk-chat"}, MagicMock()
    turn = PreparedOrchestratorChatTurn(
        session_id="risk-chat", context=ctx, accepted_snapshot=snapshot, db_manager=db_manager,
    )
    with patch.object(conversation_manager, "add_message") as add_message:
        result = orchestrator.execute_turn(turn)

    assert result.success
    assert result.runtime_facts.risk_review_status == StageStatus.COMPLETED
    expected = "风控审查要求暂缓买入。" if blocked else "现在立即买入。"
    assert result.content == expected
    add_message.assert_called_once_with("risk-chat", "assistant", expected, accepted_turn=snapshot, db_manager=db_manager)


@pytest.mark.parametrize(
    "scenario,review_completed,expected_action",
    [
        ("position", False, "watch"),
        ("watch_conditions", False, "watch"),
        ("mixed_advice", False, "sell"),
        ("mixed_advice", True, "sell"),
    ],
)
def test_blocking_risk_review_removes_buy_instructions_from_reports_and_signals(
    scenario, review_completed, expected_action,
):
    from src.agent.llm_adapter import LLMResponse
    from src.agent.orchestrator import AgentOrchestrator
    from src.agent.tools.registry import ToolRegistry
    from src.core.pipeline import StockAnalysisPipeline
    from src.enums import ReportType
    from src.services.decision_signal_extractor import build_decision_signal_payload_from_report
    from src.services.report_renderer import render

    signal, advice, phase, core = "sell", "减仓", {}, {}
    if scenario == "position":
        core["position_advice"] = {"no_position": "立即买入"}
    elif scenario == "watch_conditions":
        signal, advice = "buy", "买入"
        phase = {"immediate_action": advice, "watch_conditions": ["现在立即买入 30%"]}
    else:
        advice = "先减仓，尾盘立即买入"
        phase = {
            "immediate_action": advice,
            "action_window": "尾盘立即买入",
            "watch_conditions": [advice],
        }
    risk_reply = LLMResponse(content=json.dumps({
        "risk_level": "medium", "risk_score": 65, "flags": [], "reasoning": "Earnings warning confirmed.",
        "veto_buy": True, "signal_adjustment": "none",
    })) if review_completed else LLMResponse(provider="error")
    adapter = SimpleNamespace(call_with_tools=MagicMock(side_effect=[
        LLMResponse(content='{"signal":"buy","confidence":0.85}'),
        risk_reply,
        LLMResponse(content=json.dumps({
            "decision_type": signal, "operation_advice": advice,
            "phase_decision": phase,
            "dashboard": {
                "core_conclusion": core,
                "phase_decision": phase,
            },
        })),
    ]))
    orchestrator = AgentOrchestrator(
        tool_registry=ToolRegistry(), llm_adapter=adapter, mode="quick",
        config=SimpleNamespace(agent_debate_enabled=True, agent_risk_override=True),
    )
    result = orchestrator.run("Analyze 600519", {"stock_code": "600519"})

    assert result.success
    expected_status = StageStatus.COMPLETED if review_completed else StageStatus.FAILED
    expected_note = "风控审查要求暂缓买入。" if review_completed else "风控必审尚未完成，暂缓买入。"
    assert result.runtime_facts.risk_review_status == expected_status
    assert result.dashboard["action"] == expected_action
    assert "立即买入" not in result.content
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(report_language="zh")
    report = pipeline._agent_result_to_analysis_result(result, "600519", "贵州茅台", ReportType.FULL, "test")
    rendered = render("markdown", [report], "2026-02-01")
    assert expected_note in rendered
    assert "立即买入" not in rendered
    payload = build_decision_signal_payload_from_report(
        report, trace_id="test-risk", query_source="agent", report_type="full", profile_source="legacy_unknown",
    )
    assert payload["action"] == expected_action
    assert payload["watch_conditions"] == [expected_note]


def test_budget_skip_keeps_high_conviction_buy_on_hold():
    from src.agent.llm_adapter import LLMResponse
    from src.agent.orchestrator import AgentOrchestrator
    from src.agent.tools.registry import ToolRegistry

    adapter = SimpleNamespace(call_with_tools=MagicMock(
        return_value=LLMResponse(content='{"signal":"buy","confidence":0.75,"trend_score":80}'),
    ))
    orchestrator = AgentOrchestrator(
        tool_registry=ToolRegistry(), llm_adapter=adapter, mode="quick",
        config=SimpleNamespace(agent_debate_enabled=True, agent_orchestrator_timeout_s=14),
    )

    result = orchestrator.run("Analyze 600519", {"stock_code": "600519"})

    adapter.call_with_tools.assert_called_once()
    assert result.success and "insufficient budget" in result.error
    assert result.runtime_facts.evidence_debate_trigger_reason == "high_conviction_buy"
    assert result.runtime_facts.risk_review_status == StageStatus.SKIPPED
    assert result.dashboard["decision_type"] == "hold"


def test_decision_finishing_after_timeout_does_not_trigger_its_own_debate(monkeypatch):
    from src.agent import orchestrator as orchestrator_module
    from src.agent.llm_adapter import LLMResponse
    from src.agent.tools.registry import ToolRegistry

    now = 0

    def call_model(messages, tools, **kwargs):
        nonlocal now
        if messages[-1]["content"].startswith("Perform technical analysis"):
            return LLMResponse(content='{"signal":"hold","confidence":0.75}')
        now = 30
        return LLMResponse(content='{"decision_type":"buy","sentiment_score":85}')

    monkeypatch.setattr(orchestrator_module, "time", SimpleNamespace(time=lambda: now))
    orchestrator = orchestrator_module.AgentOrchestrator(
        tool_registry=ToolRegistry(), llm_adapter=SimpleNamespace(call_with_tools=call_model), mode="quick",
        config=SimpleNamespace(agent_debate_enabled=True, agent_orchestrator_timeout_s=30),
    )

    result = orchestrator.run("Analyze 600519", {"stock_code": "600519"})

    assert result.success and "timed out" in result.error
    assert result.runtime_facts.evidence_debate_trigger_reason is None
    assert not result.runtime_facts.risk_review_required
    assert result.dashboard["decision_type"] == "buy"
