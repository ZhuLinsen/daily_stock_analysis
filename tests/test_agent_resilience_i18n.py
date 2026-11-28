# -*- coding: utf-8 -*-
"""Regression tests for multi-agent post_process resilience and zh/en/ko parity."""

from __future__ import annotations

import json
import os
import re
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from api.v1.endpoints.agent import ChatRequest, _build_agent_chat_context
from src.agent.agent_backend import AgentRunResult
from src.agent.agents.base_agent import coerce_text
from src.agent.agents.decision_agent import DecisionAgent
from src.agent.agents.intel_agent import IntelAgent
from src.agent.agents.portfolio_agent import PortfolioAgent
from src.agent.agents.risk_agent import RiskAgent, is_complete_risk_review
from src.agent.agents.technical_agent import TechnicalAgent
from src.agent.chat_executor import AgentChatExecutor
from src.agent.disagreement import (
    _safe_confidence as disagreement_safe_confidence,
    build_agent_disagreement_summary,
    build_evidence_debate_brief,
    should_trigger_evidence_debate,
)
from src.agent.executor import (
    _ENGLISH_DASHBOARD_JSON_FORMAT_SECTION,
    AgentExecutor,
    PreparedAgentChat,
    _build_language_section,
    prepare_agent_chat,
)
from src.agent.factory import build_agent_chat_executor, build_agent_executor, resolve_skill_prompt_state
from src.agent.orchestrator import AgentOrchestrator, OrchestratorResult, PreparedOrchestratorChatTurn
from src.agent.protocols import AgentContext, AgentOpinion, AgentRunStats, StageStatus, StrategyOpinion
from src.agent.risk_override import (
    RiskApplicationReason,
    RiskOverrideApplication,
    RiskTrigger,
    build_risk_override_plan,
)
from src.agent.runner import (
    _build_budget_guard_result as runner_budget_guard_result,
    _build_timeout_result as runner_timeout_result,
    parse_dashboard_json,
    run_agent_loop,
    sanitize_non_finite_floats,
    try_parse_json,
)
from src.agent.runtime_facts import (
    _safe_confidence as runtime_facts_safe_confidence,
    build_agent_runtime_facts,
)
from src.agent.skills.aggregator import SkillAggregator
from src.agent.skills.base import SkillManager
from src.agent.skills.defaults import CORE_TRADING_SKILL_POLICY_EN, CORE_TRADING_SKILL_POLICY_ZH
from src.agent.skills.engine import StrategyEngine, StrategyResultStatus
from src.agent.skills.router import SkillRouter
from src.agent.skills.skill_agent import SkillAgent
from src.agent.skills.synthesis import ConflictDetector
from src.agent.tools.registry import ToolRegistry
from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType
from src.notification import NotificationService
from src.report_language import (
    format_chat_failure_message,
    is_supported_report_language_value,
    normalize_report_language,
)
from src.services.history_service import HistoryService
from src.stock_analyzer import TrendAnalysisResult, VolumeStatus
from src.storage import DatabaseManager
from src.utils.data_processing import normalize_signal_attribution_values

_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")


def _make_orchestrator(config=None) -> AgentOrchestrator:
    return AgentOrchestrator(
        tool_registry=MagicMock(),
        llm_adapter=MagicMock(),
        config=config,
    )


def _assert_locale_text(text: str, lang: str, label: str = "") -> None:
    if lang == "en":
        assert not _HAN_RE.search(text), f"Unexpected Han text in en ({label}): {text}"
        assert not _HANGUL_RE.search(text), f"Unexpected Hangul text in en ({label}): {text}"
    elif lang == "ko":
        assert not _HAN_RE.search(text), f"Unexpected Han text in ko ({label}): {text}"
        assert _HANGUL_RE.search(text), f"Expected Hangul text in ko ({label}): {text}"


def test_protocol_and_confidence_math_reject_nan_inf_and_bool() -> None:
    nan_op = AgentOpinion(agent_name="technical", signal="buy", confidence=float("nan"))
    assert nan_op.confidence == 0.0
    assert nan_op.confidence_input_valid is False

    inf_op = AgentOpinion(agent_name="technical", signal="buy", confidence=float("inf"))
    assert inf_op.confidence == 0.0
    assert inf_op.confidence_input_valid is False

    ninf_op = AgentOpinion(agent_name="technical", signal="buy", confidence=float("-inf"))
    assert ninf_op.confidence == 0.0
    assert ninf_op.confidence_input_valid is False

    bool_op = AgentOpinion(agent_name="technical", signal="buy", confidence=True)
    assert bool_op.confidence == 0.0
    assert bool_op.confidence_input_valid is False

    bad_str_op = AgentOpinion(agent_name="technical", signal="buy", confidence="invalid")  # type: ignore[arg-type]
    assert bad_str_op.confidence == 0.0
    assert bad_str_op.confidence_input_valid is False

    str_num_op = AgentOpinion(agent_name="technical", signal="buy", confidence="0.8")  # type: ignore[arg-type]
    assert str_num_op.confidence == pytest.approx(0.8)
    assert str_num_op.confidence_input_valid is False

    overflow_op = AgentOpinion(agent_name="technical", signal="buy", confidence=10**400)  # type: ignore[arg-type]
    assert overflow_op.confidence == 0.0
    assert overflow_op.confidence_input_valid is False

    assert StrategyOpinion(confidence=float("nan")).confidence == 0.0
    assert StrategyOpinion(confidence=float("inf")).confidence == 0.0
    assert StrategyOpinion(confidence=float("-inf")).confidence == 0.0
    assert StrategyOpinion(confidence=True).confidence == 0.0  # type: ignore[arg-type]
    assert StrategyOpinion(confidence="bad").confidence == 0.0  # type: ignore[arg-type]
    assert StrategyOpinion(confidence=10**400).confidence == 0.0  # type: ignore[arg-type]

    for fn in (disagreement_safe_confidence, runtime_facts_safe_confidence):
        assert fn(float("nan")) == 0.0
        assert fn(float("inf")) == 0.0
        assert fn(float("-inf")) == 0.0
        assert fn(True) == 0.0
        assert fn(False) == 0.0
        assert fn("bad") == 0.0
        assert fn(10**400) == 0.0
        assert fn(0.736) == 0.74
        assert fn(1.5) == 1.0
        assert fn(-0.4) == 0.0

    # Downstream disagreement/runtime_facts/synthesis never see confidence=1.0 from +inf.
    ctx = AgentContext(stock_code="600519", stock_name="Test")
    ctx.add_opinion(inf_op)
    ctx.add_opinion(AgentOpinion(agent_name="skill_a", signal="buy", confidence=0.8))
    ctx.add_opinion(AgentOpinion(agent_name="skill_b", signal="sell", confidence=float("inf")))

    facts = build_agent_runtime_facts(ctx)
    assert [(op.agent, op.confidence) for op in facts.base_agent_opinions] == [
        ("technical", 0.0),
        ("skill_a", 0.8),
        ("skill_b", 0.0),
    ]
    assert [(s.skill_id, s.confidence) for s in facts.skill_opinions] == [("a", 0.8)]

    summary = build_agent_disagreement_summary(ctx)
    assert summary["bullish_agents"][0]["confidence"] == 0.0
    assert summary["bearish_agents"][0]["confidence"] == 0.0

    brief = build_evidence_debate_brief(ctx, summary)
    assert brief["bull_arguments"][0]["confidence"] == 0.0
    assert brief["bear_arguments"][0]["confidence"] == 0.0

    conflicts = ConflictDetector().detect(
        [
            StrategyOpinion(skill_id="a", agent_name="skill_a", signal="buy", confidence=0.8),
            StrategyOpinion(skill_id="b", agent_name="skill_b", signal="sell", confidence=float("inf")),
        ],
        final_signal="buy",
    )
    conflict_types = [c.conflict_type for c in conflicts]
    assert "high_confidence_dissent" not in conflict_types


@pytest.mark.parametrize(
    ("raw_conf", "expected_conf", "expected_valid"),
    [
        (None, 0.5, False),
        ("", 0.5, False),
        ("high", 0.5, False),
        ("0.8", 0.8, False),
        (True, 0.5, False),
        (False, 0.5, False),
        (float("nan"), 0.5, False),
        (float("inf"), 0.5, False),
        (float("-inf"), 0.5, False),
        (10**400, 0.5, False),
        (-10, 0.0, False),
        (1.5, 1.0, False),
        (0, 0.0, True),
    ],
)
def test_subagent_post_process_resilience_matrix(
    raw_conf,
    expected_conf: float,
    expected_valid: bool,
) -> None:
    ctx = AgentContext(stock_code="600519", stock_name="Test")

    tech = TechnicalAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    tech_op = tech.post_process(
        ctx,
        json.dumps(
            {
                "signal": None,
                "confidence": raw_conf,
                "reasoning": None,
                "key_levels": None,
            }
        ),
    )
    assert tech_op is not None
    assert tech_op.signal == "hold"
    assert tech_op.confidence == pytest.approx(expected_conf)
    assert tech_op.confidence_input_valid is expected_valid
    assert tech_op.reasoning == ""
    assert tech_op.key_levels == {}

    intel = IntelAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    intel_op = intel.post_process(
        ctx,
        json.dumps(
            {
                "signal": "buy",
                "confidence": raw_conf,
                "reasoning": ["unexpected-list"],
                "risk_alerts": None,
            }
        ),
    )
    assert intel_op is not None
    assert intel_op.confidence == pytest.approx(expected_conf)
    assert intel_op.confidence_input_valid is expected_valid
    assert intel_op.reasoning == ""

    if raw_conf == -10:
        score_raw = -10
        risk_expected_conf = 0.0
    elif raw_conf == 1.5:
        score_raw = 150
        risk_expected_conf = 1.0
    elif raw_conf == "0.8":
        score_raw = "80"
        risk_expected_conf = 0.8
    elif raw_conf == 10**400:
        score_raw = 10**400
        risk_expected_conf = expected_conf
    elif isinstance(raw_conf, (int, float)) and not isinstance(raw_conf, bool) and raw_conf != 0:
        score_raw = raw_conf * 100.0
        risk_expected_conf = expected_conf
    else:
        score_raw = raw_conf
        risk_expected_conf = expected_conf

    risk = RiskAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    risk_ctx = AgentContext(stock_code="600519", stock_name="Test")
    risk_op = risk.post_process(
        risk_ctx,
        json.dumps(
            {
                "risk_level": None,
                "risk_score": score_raw,
                "flags": None,
                "reasoning": None,
            }
        ),
    )
    assert risk_op is not None
    assert risk_op.signal == "hold"
    assert risk_op.confidence == pytest.approx(risk_expected_conf)
    assert risk_op.confidence_input_valid is expected_valid
    assert risk_op.reasoning == ""
    assert risk_ctx.risk_flags == []

    decision = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    decision_op = decision.post_process(
        ctx,
        json.dumps(
            {
                "stock_name": "Test",
                "decision_type": "hold",
                "sentiment_score": score_raw,
                "analysis_summary": None,
            }
        ),
    )
    decision_expected_conf = 0.5 if score_raw in (-10, 150) else risk_expected_conf
    assert decision_op is not None
    assert decision_op.confidence == pytest.approx(decision_expected_conf)
    assert decision_op.confidence_input_valid is expected_valid
    assert decision_op.reasoning == ""


def test_risk_agent_malformed_risk_level_maps_to_hold_never_buy() -> None:
    orch = _make_orchestrator()
    risk = RiskAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    for bad_level in (None, False, True, "", [], {}, "unknown"):
        ctx = AgentContext(query="test", stock_code="600519", stock_name="Test")
        op = risk.post_process(ctx, json.dumps({"risk_level": bad_level, "risk_score": 50}))
        assert op is not None
        assert op.signal == "hold"
        ctx.add_opinion(op)
        dashboard = orch._finalize_dashboard_payload({}, ctx)
        assert dashboard is not None
        assert dashboard["decision_type"] == "hold"

    omitted_ctx = AgentContext(query="test", stock_code="600519", stock_name="Test")
    omitted_op = risk.post_process(omitted_ctx, json.dumps({"risk_score": 20}))
    assert omitted_op is not None
    assert omitted_op.signal == "hold"

    explicit_none_op = risk.post_process(AgentContext(stock_code="600519"), json.dumps({"risk_level": "none", "risk_score": 10}))
    assert explicit_none_op is not None
    assert explicit_none_op.signal == "buy"


def test_omitted_confidence_and_malformed_high_confidence_do_not_trigger_debate() -> None:
    tech = TechnicalAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    omitted = tech.post_process(AgentContext(stock_code="600519"), json.dumps({"signal": "buy"}))
    assert omitted is not None
    assert omitted.confidence == 0.5
    assert omitted.confidence_input_valid is False

    for bad_conf in (1.5, float("inf"), float("nan"), "high", "0.8", True, None, 10**400):
        ctx = AgentContext(stock_code="600519", stock_name="Test")
        op = tech.post_process(
            ctx,
            json.dumps({"signal": "buy", "confidence": bad_conf, "reasoning": "Bullish setup"}),
        )
        assert op is not None
        assert op.confidence_input_valid is False
        ctx.add_opinion(op)
        triggered, reason = should_trigger_evidence_debate(ctx, enabled=True)
        assert (triggered, reason) == (False, "consensus_clear")


def test_overflow_response_type_guards_and_downstream_consumers() -> None:
    # 1) coerce_text and sub-agent post_process survive 10**400 without OverflowError.
    assert coerce_text(10**400, default="fallback") == "fallback"
    ctx = AgentContext(stock_code="600519", stock_name="Test")
    tech = TechnicalAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    assert tech.post_process(ctx, json.dumps({"signal": "buy", "reasoning": 10**400})).reasoning == ""
    assert not is_complete_risk_review(
        {
            "risk_level": "low",
            "risk_score": 10**400,
            "reasoning": "valid",
            "flags": [],
            "veto_buy": False,
            "signal_adjustment": "none",
        }
    )

    # 2) Signal attribution rejects bool and 10**400 without crashing.
    attr = normalize_signal_attribution_values(
        {
            "technical_indicators": True,
            "news_sentiment": 10**400,
            "fundamentals": "bad",
            "market_conditions": 50,
        }
    )
    assert attr == {
        "technical_indicators": None,
        "news_sentiment": None,
        "fundamentals": None,
        "market_conditions": 50.0,
    }

    # 3) Non-string responses fail closed cleanly in parser, runner, DecisionAgent, and PortfolioAgent.
    for non_str in ({"a": 1}, [1, 2], 123, None):
        assert try_parse_json(non_str) is None  # type: ignore[arg-type]
        assert parse_dashboard_json(non_str) is None  # type: ignore[arg-type]

    portfolio = PortfolioAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    for non_str in ({"portfolio_risk_score": 1}, ["x"], 123):
        assert portfolio.post_process(ctx, non_str) is None  # type: ignore[arg-type]

    decision = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    chat_ctx = AgentContext(stock_code="600519", meta={"response_mode": "chat"})
    for non_str in ({"text": "hi"}, ["hi"], 123):
        assert decision.post_process(chat_ctx, non_str) is None  # type: ignore[arg-type]
        assert decision.post_process(ctx, non_str) is None  # type: ignore[arg-type]

    adapter = MagicMock()
    adapter.call_with_tools.return_value = SimpleNamespace(
        content={"unexpected": "dict"},
        tool_calls=[],
        provider="mock",
        model="mock-model",
        usage={},
        reasoning_content=None,
        provider_blocks=None,
    )
    loop_res = run_agent_loop(
        messages=[{"role": "user", "content": "hi"}],
        tool_registry=ToolRegistry(),
        llm_adapter=adapter,
        max_steps=1,
    )
    assert loop_res.success is False
    assert loop_res.content == ""

    # 4) PortfolioAgent enforces 1-10 risk score scale.
    for score_input, expected_sig in (
        (None, "hold"),
        ("8", "sell"),
        ("2", "buy"),
        ("bad", "hold"),
        (True, "hold"),
        (float("nan"), "hold"),
        (float("inf"), "hold"),
        (10**400, "hold"),
        (0, "hold"),
        (-5, "hold"),
        (15, "hold"),
        (1, "buy"),
        (10, "sell"),
    ):
        pop = portfolio.post_process(
            ctx,
            json.dumps({"portfolio_risk_score": score_input, "summary": None}),
        )
        assert pop is not None
        assert pop.signal == expected_sig

    # 5) Router, Aggregator, Synthesis, RiskOverride reject inf / bool / string veto.
    for bad_trend in (float("inf"), float("nan"), 10**400, True, 150, -5):
        r_ctx = AgentContext(stock_code="600519")
        r_ctx.add_opinion(
            AgentOpinion(
                agent_name="technical",
                signal="buy",
                confidence=0.8,
                raw_data={"ma_alignment": "bullish", "trend_score": bad_trend},
            )
        )
        assert SkillRouter()._detect_regime(r_ctx) == "sideways"  # fallback trend_score=50 -> sideways

    agg_ctx = AgentContext(stock_code="600519")
    agg_ctx.add_opinion(
        AgentOpinion(
            agent_name="skill_a",
            signal="buy",
            confidence=0.8,
            raw_data={"signal": "buy", "score_adjustment": float("inf")},
        )
    )
    agg_ctx.add_opinion(
        AgentOpinion(
            agent_name="skill_b",
            signal="buy",
            confidence=0.8,
            raw_data={"signal": "buy", "score_adjustment": True},
        )
    )
    agg_ctx.add_opinion(
        AgentOpinion(
            agent_name="skill_c",
            signal="buy",
            confidence=0.8,
            raw_data={"signal": "buy", "score_adjustment": 10**400},
        )
    )
    consensus = SkillAggregator().aggregate(agg_ctx)
    assert consensus is not None
    assert consensus.raw_data["total_adjustment"] == 0.0

    for bad_veto in ("false", "no", [1], float("nan"), 1):
        v_ctx = AgentContext(stock_code="600519")
        v_ctx.add_opinion(
            AgentOpinion(
                agent_name="risk",
                signal="hold",
                confidence=0.5,
                raw_data={"veto_buy": bad_veto},
            )
        )
        plan = build_risk_override_plan(v_ctx, current_signal="buy", override_enabled=True)
        assert plan.veto_buy is False
        assert plan.will_apply is False


def test_technical_intel_risk_skill_containers() -> None:
    tech = TechnicalAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    ctx = AgentContext(stock_code="600519")
    op = tech.post_process(
        ctx,
        json.dumps(
            {
                "signal": "buy",
                "confidence": 0.7,
                "key_levels": {
                    "support": True,
                    "resistance": "nan",
                    "pivot": float("inf"),
                    "huge": 10**400,
                    "stop_loss": "180.5",
                },
            }
        ),
    )
    assert op is not None
    assert op.key_levels == {"stop_loss": 180.5}
    assert tech.post_process(ctx, json.dumps({"signal": "buy", "key_levels": []})).key_levels == {}

    intel = IntelAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    intel_ctx = AgentContext(stock_code="600519")
    intel.post_process(
        intel_ctx,
        json.dumps({"signal": "hold", "confidence": 0.6, "risk_alerts": "single string risk"}),
    )
    assert len(intel_ctx.risk_flags) == 1
    assert intel_ctx.risk_flags[0]["description"] == "single string risk"

    risk = RiskAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    risk_ctx = AgentContext(stock_code="600519")
    risk.post_process(risk_ctx, json.dumps({"risk_level": "low", "flags": "not-a-list"}))
    assert risk_ctx.risk_flags == []

    risk.post_process(
        risk_ctx,
        json.dumps(
            {
                "risk_level": "medium",
                "risk_score": 0,
                "flags": [{"category": None, "description": None, "severity": None, "source": 123}],
            }
        ),
    )
    assert len(risk_ctx.risk_flags) == 1
    assert risk_ctx.risk_flags[0]["category"] == "unknown"
    assert risk_ctx.risk_flags[0]["severity"] == "medium"
    assert "source" not in risk_ctx.risk_flags[0]

    with patch.object(SkillAgent, "_load_skill", return_value=None):
        skill = SkillAgent(skill_id="bull_trend", tool_registry=MagicMock(), llm_adapter=MagicMock())
    for bad_conf in (None, "0.8", float("nan"), float("inf"), 1.5, -0.1, True, False):
        assert skill.post_process(ctx, json.dumps({"signal": "buy", "confidence": bad_conf})) is None
    valid_skill_op = skill.post_process(
        ctx,
        json.dumps({"signal": "buy", "confidence": 0.8, "reasoning": 10**400}),
    )
    assert valid_skill_op is not None
    assert valid_skill_op.reasoning == ""


def test_orchestrator_and_single_agent_json_sanitize_levels_and_bool_sentiment() -> None:
    orch = _make_orchestrator()
    # sentiment_score=True must NOT coerce to 1; fallback for hold@0.8 is 56.
    ctx_bool = AgentContext(query="Analyze AAPL", stock_code="AAPL", stock_name="Apple Inc.")
    ctx_bool.meta["report_language"] = "en"
    ctx_bool.add_opinion(AgentOpinion(agent_name="technical", signal="hold", confidence=0.8))
    dash_bool = orch._finalize_dashboard_payload({"decision_type": "hold", "sentiment_score": True}, ctx_bool)
    assert dash_bool is not None
    assert dash_bool["sentiment_score"] == 56

    # Malformed existing sniper levels, zero level fallback, inf trend_score, non-dict quote, 10**400.
    ctx = AgentContext(query="Analyze AAPL", stock_code="AAPL", stock_name="Apple Inc.")
    ctx.meta["report_language"] = "en"
    ctx.set_data("realtime_quote", "bad-quote-str")
    ctx.set_data("trend_result", {"current_price": 10**400, "ma5": True, "bias_ma5": float("inf")})
    ctx.set_data("chip_distribution", {"profit_ratio": True, "avg_cost": [1, 2], "concentration": float("nan")})
    ctx.add_opinion(
        AgentOpinion(
            agent_name="technical",
            signal="buy",
            confidence=float("nan"),
            raw_data={"ma_alignment": "bullish", "trend_score": float("inf"), "volume_status": "normal"},
            key_levels={"stop_loss": 0.0, "resistance": 210.0, "support": 185.0},
        )
    )
    dashboard = orch._finalize_dashboard_payload(
        {
            "decision_type": "buy",
            "sentiment_score": float("inf"),
            "dashboard": {
                "battle_plan": {
                    "sniper_points": {
                        "ideal_buy": [12, 13],
                        "stop_loss": True,
                        "take_profit": float("inf"),
                    }
                },
                "key_levels": {
                    "support": float("nan"),
                    "resistance": float("inf"),
                    "stop_loss": 0.0,
                },
            },
        },
        ctx,
    )
    assert dashboard is not None
    dumped = json.dumps(dashboard, ensure_ascii=False, allow_nan=False)
    assert "NaN" not in dumped
    assert "inf" not in dashboard["trend_prediction"].lower()
    sniper = dashboard["dashboard"]["battle_plan"]["sniper_points"]
    assert sniper["ideal_buy"] == 185.0
    assert sniper["stop_loss"] == 0.0
    assert sniper["take_profit"] == 210.0
    dp = dashboard["dashboard"]["data_perspective"]
    assert dp["price_position"]["current_price"] == "N/A"
    assert dp["price_position"]["ma5"] == "N/A"
    assert dp["chip_structure"]["profit_ratio"] == "N/A"
    assert dp["chip_structure"]["avg_cost"] == "N/A"

    # Single-agent parse_dashboard_json also scrubs NaN/Infinity for strict json.dumps(..., allow_nan=False).
    single_parsed = parse_dashboard_json(
        '{"stock_name":"Apple Inc.","decision_type":"hold","sentiment_score":55,"support":NaN,"dashboard":{"sniper_points":{"stop_loss":Infinity}}}'
    )
    assert single_parsed is not None
    json.dumps(single_parsed, ensure_ascii=False, allow_nan=False)


def test_non_string_request_language_and_prompts_and_cached_volume_status() -> None:
    assert normalize_report_language(True) == "zh"  # type: ignore[arg-type]
    assert normalize_report_language({"lang": "en"}) == "zh"  # type: ignore[arg-type]
    assert is_supported_report_language_value(True) is False  # type: ignore[arg-type]

    chat_ctx = _build_agent_chat_context(
        ChatRequest(message="Analyze AAPL", context={"report_language": True}),
        SimpleNamespace(report_language="ko"),
        None,
    )
    assert chat_ctx["report_language"] == "ko"

    assert format_chat_failure_message("  boom  ", "zh") == "[分析失败]   boom  "

    with patch.object(SkillAgent, "_load_skill", return_value=None):
        agents = [
            TechnicalAgent(tool_registry=MagicMock(), llm_adapter=MagicMock()),
            IntelAgent(tool_registry=MagicMock(), llm_adapter=MagicMock()),
            RiskAgent(tool_registry=MagicMock(), llm_adapter=MagicMock()),
            PortfolioAgent(tool_registry=MagicMock(), llm_adapter=MagicMock()),
            SkillAgent(skill_id="bull_trend", tool_registry=MagicMock(), llm_adapter=MagicMock()),
        ]
    decision = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
    exec_instance = AgentExecutor(ToolRegistry(), MagicMock(), max_steps=1)

    for lang in ("zh", "en", "ko"):
        ctx = AgentContext(query="test", stock_code="AAPL", stock_name="Apple Inc.")
        ctx.meta["report_language"] = lang
        ctx.meta["invalid_opinions"] = [{"agent_name": "skill_a", "reason": "skill_timeout"}]
        for agent in agents:
            p = agent.system_prompt(ctx)
            if lang == "en":
                assert "in English" in p
                assert not _HAN_RE.search(p), f"Han leak in {agent.agent_name} en system_prompt: {p}"
            elif lang == "ko":
                assert "한국어" in p
                assert not _HAN_RE.search(p), f"Han leak in {agent.agent_name} ko system_prompt: {p}"
            else:
                assert "输出语言" in p

        if lang != "zh":
            intel_user = agents[1].build_user_message(ctx)
            assert not _HAN_RE.search(intel_user)

        dec_sys = decision.system_prompt(ctx)
        dec_user = decision.build_user_message(ctx)
        if lang == "en":
            assert not _HAN_RE.search(dec_sys)
            assert not _HAN_RE.search(dec_user)
        elif lang == "ko":
            assert not _HAN_RE.search(dec_sys)
            assert not _HAN_RE.search(dec_user)
            assert _HANGUL_RE.search(dec_user)
        else:
            assert "执行超时" in dec_user

        with patch("src.agent.executor.build_agent_chat_context_bundle", return_value=SimpleNamespace(context_messages=[])):
            prepared = prepare_agent_chat(
                message="Check AAPL",
                session_id="s1",
                context={
                    "stock_code": "AAPL",
                    "stock_name": "Apple Inc.",
                    "previous_price": 190.0,
                    "previous_analysis_summary": "Steady uptrend",
                    "report_language": lang,
                },
                config=SimpleNamespace(),
                context_llm_adapter=MagicMock(),
                skill_instructions="",
                default_skill_policy="",
                use_legacy_default_prompt=False,
                include_provider_trace=True,
            )
            exec_user_msg = exec_instance._build_user_message(
                "Analyze AAPL",
                context={
                    "stock_code": "AAPL",
                    "report_type": "simple",
                    "report_language": lang,
                    "realtime_quote": {"price": 190.0},
                },
            )
            if lang != "zh":
                hist_joined = "\n".join(str(m.get("content", "")) for m in prepared.history_messages)
                assert not _HAN_RE.search(hist_joined)
                assert not _HAN_RE.search(exec_user_msg)
                if lang == "ko":
                    assert _HANGUL_RE.search(exec_user_msg)
            else:
                assert "[系统提供的历史分析上下文，可供参考对比]" in prepared.history_messages[0]["content"]
                assert "股票代码: AAPL" in exec_user_msg

    assert "in English" in _build_language_section("en", chat_mode=False)
    assert "한국어" in _build_language_section("ko", chat_mode=False)
    assert "中文" in _build_language_section("zh", chat_mode=False)
    assert "Reply in English" in _build_language_section("en", chat_mode=True)
    assert "한국어" in _build_language_section("ko", chat_mode=True)
    assert "中文" in _build_language_section("zh", chat_mode=True)


@pytest.mark.parametrize(
    ("lang", "expected_boom", "expected_unknown"),
    [
        ("zh", "[分析失败] boom", "[分析失败] 未知错误"),
        ("en", "[Analysis Failed] boom", "[Analysis Failed] Unknown error"),
        ("ko", "[분석 실패] boom", "[분석 실패] 알 수 없는 오류"),
    ],
)
def test_chat_failure_persistence_localized_across_executors(
    tmp_path,
    lang: str,
    expected_boom: str,
    expected_unknown: str,
) -> None:
    DatabaseManager.reset_instance()
    _ = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'chat_i18n.db'}")
    try:
        orch = _make_orchestrator()
        for err, expected in (("boom", expected_boom), (None, expected_unknown)):
            ctx = AgentContext(query="test", stock_code="AAPL")
            ctx.meta["report_language"] = lang
            turn_with_snapshot = PreparedOrchestratorChatTurn(
                session_id="s-orch",
                context=ctx,
                accepted_snapshot={"user_message_id": 1},
            )
            turn_without_snapshot = PreparedOrchestratorChatTurn(
                session_id="s-orch-legacy",
                context=ctx,
                accepted_snapshot=None,
            )
            fake_result = OrchestratorResult(success=False, error=err)
            with patch.object(orch, "_execute_pipeline", return_value=fake_result), patch(
                "src.agent.conversation.conversation_manager.add_message"
            ) as add_msg:
                orch.execute_turn(turn_with_snapshot)
                assert add_msg.call_args.args == ("s-orch", "assistant", expected)
                orch.execute_turn(turn_without_snapshot)
                assert add_msg.call_args.args == ("s-orch-legacy", "assistant", expected)

        mock_adapter = MagicMock()
        executor = AgentExecutor(tool_registry=MagicMock(), llm_adapter=mock_adapter)
        prepared_exec = PreparedAgentChat(
            system_prompt="sys",
            history_messages=[],
            stock_scope=None,
            report_language=lang,
        )
        with patch("src.agent.conversation.conversation_manager.prepare_turn", return_value=(MagicMock(), {})), patch(
            "src.services.agent_chat_session_service.AgentChatSessionService.prepare_compatibility_turn",
            return_value=(SimpleNamespace(effective_context={"report_language": lang}, stock_scope=None), None),
        ), patch("src.agent.executor.prepare_agent_chat", return_value=prepared_exec), patch(
            "src.agent.conversation.conversation_manager.commit_user_turn",
            return_value={"user_message_id": 1},
        ), patch(
            "src.agent.executor.run_agent_loop",
            return_value=SimpleNamespace(
                success=False,
                content="",
                tool_calls_log=[],
                total_steps=1,
                total_tokens=0,
                provider="error",
                models_used=[],
                model="",
                error="boom",
                messages=[],
            ),
        ), patch("src.agent.conversation.conversation_manager.add_message") as add_msg:
            executor.chat("hello", "s-exec", context={"report_language": lang})
            assert add_msg.call_args.args == ("s-exec", "assistant", expected_boom)

        class _FailBackend:
            backend_id = "litellm"
            runtime_owns_loop = False

            def run(self, _request):
                return AgentRunResult(
                    success=False,
                    backend="litellm",
                    error_code="unknown_backend_error",
                    error_message="boom",
                    total_steps=1,
                )

        chat_exec = AgentChatExecutor(
            backend=_FailBackend(),
            config=SimpleNamespace(),
            context_llm_adapter=object(),
        )
        with patch("src.agent.chat_executor.prepare_agent_chat", return_value=prepared_exec), patch(
            "src.agent.chat_executor.conversation_manager.prepare_turn",
            return_value=(MagicMock(), {}),
        ), patch(
            "src.agent.chat_executor.conversation_manager.commit_user_turn",
            return_value={"user_message_id": 1},
        ), patch(
            "src.agent.chat_executor.conversation_manager.add_message",
            return_value=2,
        ) as add_msg:
            chat_exec.chat("hello", "s-chat", context={"report_language": lang})
            assert add_msg.call_args.args == ("s-chat", "assistant", expected_boom)
    finally:
        DatabaseManager.reset_instance()


@pytest.mark.parametrize("lang", ["zh", "en", "ko"])
def test_orchestrator_dashboard_and_fallbacks_localized_by_report_language(lang: str) -> None:
    orch = _make_orchestrator(config=SimpleNamespace(agent_orchestrator_timeout_s=20, agent_risk_override=True))

    # 1) Minimal fallback + real cached TrendAnalysisResult (with Chinese VolumeStatus.NORMAL)
    real_trend = TrendAnalysisResult(
        code="AAPL",
        current_price=190.5,
        ma5=185.0,
        ma10=182.0,
        ma20=178.0,
        bias_ma5=6.1,
        volume_status=VolumeStatus.NORMAL,
    ).to_dict()
    ctx = AgentContext(query="Analyze AAPL", stock_code="AAPL", stock_name="Apple Inc.")
    ctx.meta["report_language"] = lang
    ctx.set_data("realtime_quote", {"price": 190.5, "volume_ratio": 1.2, "turnover_rate": 0.9})
    ctx.set_data("trend_result", real_trend)
    ctx.set_data("chip_distribution", {"profit_ratio": 0.72, "avg_cost": 180.0, "concentration": 0.12})
    ctx.add_opinion(
        AgentOpinion(
            agent_name="technical",
            signal="buy",
            confidence=0.8,
            reasoning="",
            raw_data={"ma_alignment": "bullish", "trend_score": 82, "volume_status": "normal"},
        )
    )
    dashboard = orch._finalize_dashboard_payload({"decision_type": "buy"}, ctx)
    assert dashboard is not None
    serialized = json.dumps(dashboard, ensure_ascii=False)
    _assert_locale_text(serialized, lang, "minimal_dashboard")
    if lang == "en":
        assert dashboard["dashboard"]["data_perspective"]["volume_analysis"]["volume_status"] == "Normal Volume"
    elif lang == "ko":
        assert dashboard["dashboard"]["data_perspective"]["volume_analysis"]["volume_status"] == "거래량 보통"
        assert dashboard["confidence_level"] == "높음"
    else:
        assert dashboard["dashboard"]["data_perspective"]["volume_analysis"]["volume_status"] == "量能正常"
        assert dashboard["confidence_level"] == "高"
        assert dashboard["risk_warning"] == "暂无额外风险提示"
        assert dashboard["dashboard"]["battle_plan"]["sniper_points"]["stop_loss"] == "待补充"
        assert dashboard["dashboard"]["core_conclusion"]["time_sensitivity"] == "本周内"
        assert dashboard["dashboard"]["data_perspective"]["price_position"]["bias_status"] == "超买"
        assert dashboard["dashboard"]["data_perspective"]["chip_structure"]["chip_health"] == "一般"

    # 2) Risk override applied path
    risk_ctx = AgentContext(query="Analyze AAPL", stock_code="AAPL", stock_name="Apple Inc.")
    risk_ctx.meta["report_language"] = lang
    risk_ctx.meta["risk_override_application"] = RiskOverrideApplication(
        evidence_present=True,
        override_enabled=True,
        trigger=RiskTrigger.RISK_VETO,
        applied=True,
        reason=RiskApplicationReason.RISK_VETO_APPLIED,
        post_risk_signal="hold",
        from_signal="buy",
        to_signal="hold",
    )
    risk_ctx.add_opinion(
        AgentOpinion(
            agent_name="risk",
            signal="strong_sell",
            confidence=0.9,
            reasoning="High dilution risk",
            raw_data={"veto_buy": True, "reasoning": "High dilution risk"},
        )
    )
    risk_ctx.add_risk_flag("insider", "Shareholder sell-down", severity="high")
    risk_dash = orch._finalize_dashboard_payload(
        {"decision_type": "buy", "analysis_summary": "Bullish momentum"},
        risk_ctx,
    )
    assert risk_dash is not None
    risk_serialized = json.dumps(risk_dash, ensure_ascii=False)
    _assert_locale_text(risk_serialized, lang, "risk_override")
    if lang == "ko":
        assert "[리스크 하향:" in risk_dash["analysis_summary"]
        assert "리스크 통제 발동" in risk_dash["risk_warning"]
    elif lang == "zh":
        assert "[风控下调: buy -> hold]" in risk_dash["analysis_summary"]
        assert "风控接管" in risk_dash["risk_warning"]
        assert "止损参考：" in risk_dash["dashboard"]["battle_plan"]["position_strategy"]["risk_control"]

    # 3) Incomplete mandatory risk review path
    incomplete_ctx = AgentContext(query="Analyze AAPL", stock_code="AAPL", stock_name="Apple Inc.")
    incomplete_ctx.meta["report_language"] = lang
    incomplete_ctx.meta["risk_review_required"] = True
    incomplete_ctx.meta["risk_review_status"] = StageStatus.FAILED
    incomplete_ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8, reasoning=""))
    incomplete_dash = orch._finalize_dashboard_payload(
        {
            "decision_type": "buy",
            "operation_advice": "买入" if lang == "zh" else "Buy",
            "dashboard": {"phase_decision": {"action_window": "intraday", "immediate_action": "buy"}},
        },
        incomplete_ctx,
    )
    assert incomplete_dash is not None
    incomplete_serialized = json.dumps(incomplete_dash, ensure_ascii=False)
    _assert_locale_text(incomplete_serialized, lang, "incomplete_risk_review")
    if lang == "zh":
        assert "风控必审尚未完成" in incomplete_dash["analysis_summary"]
        assert "风控必审尚未完成" in incomplete_dash["risk_warning"]

    # 4) Timeout & budget skip partial dashboards + fallback summary
    for expected_ko_prefix, builder in (
        ("[축소 결과] ", lambda c: orch._build_timeout_result(AgentRunStats(), [], ["m"], 10.0, 10, ctx=c)),
        ("[축소 결과] ", lambda c: orch._build_budget_skip_result(AgentRunStats(), [], ["m"], 10.0, 20, "intel", 5.0, 15, ctx=c)),
    ):
        partial_ctx = AgentContext(query="Analyze AAPL", stock_code="AAPL", stock_name="Apple Inc.")
        partial_ctx.meta["report_language"] = lang
        partial_ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8, reasoning=""))
        res = builder(partial_ctx)
        assert res.dashboard is not None
        partial_serialized = json.dumps(res.dashboard, ensure_ascii=False)
        _assert_locale_text(partial_serialized, lang, "partial_dashboard")
        if lang == "en":
            assert res.dashboard["analysis_summary"].startswith("[Degraded Result] ")
        elif lang == "ko":
            assert res.dashboard["analysis_summary"].startswith(expected_ko_prefix)
            assert "멀티 에이전트" in res.dashboard["risk_warning"]
        else:
            assert res.dashboard["analysis_summary"].startswith("[降级结果] ")

    summary_text = orch._fallback_summary(risk_ctx)
    if lang == "ko":
        _assert_locale_text(summary_text, "ko", "fallback_summary")
        assert summary_text.startswith("# 분석 요약:")
        assert "## 리스크 플래그" in summary_text
    else:
        if lang == "en":
            _assert_locale_text(summary_text, "en", "fallback_summary")
        assert summary_text.startswith("# Analysis Summary:")
        assert "## Risk Flags" in summary_text


def test_round3_pipeline_backfill_deep_sanitizer_skills_and_executor_prompts() -> None:
    # 1) Korean placeholder ("미정") triggers support-level stop-loss backfill just like zh/en.
    trend_with_support = TrendAnalysisResult(
        code="005930.KS",
        support_levels=[180.0],
        volume_status=VolumeStatus.NORMAL,
    )
    orch = _make_orchestrator()
    for lang in ("zh", "en", "ko"):
        ctx = AgentContext(query="Analyze 005930.KS", stock_code="005930.KS", stock_name="Samsung")
        ctx.meta["report_language"] = lang
        dash = orch._finalize_dashboard_payload({"decision_type": "buy"}, ctx)
        assert dash is not None
        res = AnalysisResult(
            code="005930.KS",
            name="Samsung",
            sentiment_score=int(dash["sentiment_score"]),
            trend_prediction=dash["trend_prediction"],
            operation_advice=dash["operation_advice"],
            decision_type=dash["decision_type"],
            confidence_level=dash["confidence_level"],
            analysis_summary=dash["analysis_summary"],
            dashboard=dash["dashboard"],
        )
        pipeline = object.__new__(StockAnalysisPipeline)
        pipeline._backfill_agent_dashboard_fields(res, trend_with_support, lang)
        assert res.dashboard["battle_plan"]["sniper_points"]["stop_loss"] == 180.0

    # 2) Single-agent parse_dashboard_json scrubs bool sentiment_score, and pipeline._safe_int rejects bool.
    bool_dash = parse_dashboard_json(
        '{"stock_name":"Apple","decision_type":"hold","sentiment_score":true}'
    )
    assert bool_dash is not None
    assert bool_dash["sentiment_score"] is None
    assert StockAnalysisPipeline._is_agent_field_missing(True, scalar=True) is True
    assert StockAnalysisPipeline._safe_int(True, 50) == 50
    assert StockAnalysisPipeline._safe_int(10**400, 50) == 50

    # 3) 600-level nested JSON succeeds in parse_dashboard_json and iterative sanitize_non_finite_floats.
    deep_raw = '{"decision_type":"hold","sentiment_score":55,"deep":' + ("[" * 600) + "1" + ("]" * 600) + "}"
    deep_dash = parse_dashboard_json(deep_raw)
    assert deep_dash is not None
    node = deep_dash["deep"]
    for _ in range(599):
        node = node[0]
    assert node == [1]
    assert sanitize_non_finite_floats((1.0, float("nan"), [float("inf")])) == (1.0, None, [None])

    # 4) Model-authored data_perspective & fractional sentiment_score truncation (59.9 -> 59).
    dp_ctx = AgentContext(query="Analyze AAPL", stock_code="AAPL", stock_name="Apple Inc.")
    dp_ctx.meta["report_language"] = "ko"
    dp_dash = orch._finalize_dashboard_payload(
        {
            "decision_type": "hold",
            "sentiment_score": 59.9,
            "dashboard": {
                "data_perspective": {
                    "trend_status": {"ma_alignment": "bullish", "trend_score": float("inf"), "is_bullish": "yes"},
                    "price_position": {
                        "current_price": True,
                        "ma5": [1],
                        "bias_ma5": "Infinity",
                        "bias_status": "安全",
                        "support_level": True,
                    },
                    "volume_analysis": {"volume_ratio": "NaN", "volume_status": "normal", "volume_meaning": 10**400},
                    "chip_structure": {"profit_ratio": True, "chip_health": "健康"},
                }
            },
        },
        dp_ctx,
    )
    assert dp_dash is not None
    assert dp_dash["sentiment_score"] == 59
    dp = dp_dash["dashboard"]["data_perspective"]
    assert dp["trend_status"] == {"ma_alignment": "bullish", "trend_score": "N/A", "is_bullish": True}
    assert dp["price_position"]["current_price"] == "N/A"
    assert dp["price_position"]["ma5"] == "N/A"
    assert dp["price_position"]["bias_ma5"] == "N/A"
    assert dp["price_position"]["bias_status"] == "안전"
    assert dp["price_position"]["support_level"] == "N/A"
    assert dp["volume_analysis"] == {"volume_ratio": "N/A", "volume_status": "거래량 보통", "volume_meaning": ""}
    assert dp["chip_structure"] == {"profit_ratio": "N/A", "chip_health": "양호"}

    # Korean technical-agent enum volume_status without cached TrendAnalysisResult.
    tech_vol_ctx = AgentContext(query="Analyze AAPL", stock_code="AAPL", stock_name="Apple Inc.")
    tech_vol_ctx.meta["report_language"] = "ko"
    tech_vol_ctx.set_data("trend_result", {"current_price": 190.5})
    tech_vol_ctx.add_opinion(
        AgentOpinion(agent_name="technical", signal="hold", confidence=0.6, raw_data={"volume_status": "normal"})
    )
    tech_vol_dash = orch._finalize_dashboard_payload({"decision_type": "hold"}, tech_vol_ctx)
    assert tech_vol_dash is not None
    assert tech_vol_dash["dashboard"]["data_perspective"]["volume_analysis"]["volume_status"] == "거래량 보통"

    # 5) Invalid skill confidence (e.g. 1.5 -> 1.0, input_valid=False) is moved to diagnostics and cannot trigger debate.
    invalid_skill = AgentOpinion(agent_name="skill_a", signal="buy", confidence=1.5)
    assert invalid_skill.confidence_input_valid is False
    engine_res = StrategyEngine().process([invalid_skill])
    assert engine_res.status == StrategyResultStatus.NO_CONSENSUS
    assert engine_res.consensus_opinion is None
    assert engine_res.valid_skill_opinions == []
    assert engine_res.invalid_count == 1
    assert engine_res.invalid_records[0]["reason"] == "invalid_confidence"

    direct_consensus = SkillAggregator().aggregate(AgentContext(stock_code="600519", opinions=[invalid_skill]))
    assert direct_consensus is not None
    assert direct_consensus.signal == "hold"
    assert direct_consensus.confidence == 0.0
    assert direct_consensus.confidence_input_valid is False
    debate_ctx = AgentContext(stock_code="600519", opinions=[direct_consensus])
    assert should_trigger_evidence_debate(debate_ctx, enabled=True) == (False, "consensus_clear")

    # 6) Oversized skill score_adjustment (1e308 / "1e308" / -1e308) is ignored cleanly without inf or distortion.
    huge_ctx = AgentContext(stock_code="600519")
    huge_ctx.add_opinion(
        AgentOpinion(
            agent_name="skill_a",
            signal="buy",
            confidence=0.8,
            raw_data={"signal": "buy", "score_adjustment": 1e308},
        )
    )
    huge_ctx.add_opinion(
        AgentOpinion(
            agent_name="skill_b",
            signal="buy",
            confidence=0.8,
            raw_data={"signal": "buy", "score_adjustment": "1e308"},
        )
    )
    huge_ctx.add_opinion(
        AgentOpinion(
            agent_name="skill_c",
            signal="sell",
            confidence=0.6,
            raw_data={"signal": "sell", "score_adjustment": -1e308},
        )
    )
    agg = SkillAggregator().calculate(huge_ctx.opinions)
    assert agg is not None
    assert agg.total_adjustment == 0.0
    assert "adjustment_contradiction" not in [c.conflict_type for c in agg.conflicts]
    assert ConflictDetector().detect(agg.strategy_opinions, final_signal="buy")

    # 7) Single-agent executor system prompts + real loaded SkillAgent have English scaffolding in en/ko.
    skill_agent = SkillAgent(skill_id="bull_trend", tool_registry=MagicMock(), llm_adapter=MagicMock())
    assert skill_agent._skill is not None
    real_skill_instructions = skill_agent._skill.instructions
    for lang in ("en", "ko"):
        ko_or_en_ctx = AgentContext(stock_code="005930.KS", stock_name="Samsung", meta={"report_language": lang})
        skill_prompt = skill_agent.system_prompt(ko_or_en_ctx)
        prompt_without_skill_body = skill_prompt.replace(real_skill_instructions, "")
        assert not _HAN_RE.search(prompt_without_skill_body)

        with patch("src.agent.executor.build_agent_chat_context_bundle", return_value=SimpleNamespace(context_messages=[])):
            prepared = prepare_agent_chat(
                message="Check AAPL",
                session_id="s-sys",
                context={"stock_code": "AAPL", "report_language": lang},
                config=SimpleNamespace(),
                context_llm_adapter=MagicMock(),
                skill_instructions=real_skill_instructions,
                default_skill_policy=CORE_TRADING_SKILL_POLICY_ZH,
                use_legacy_default_prompt=True,
                include_provider_trace=True,
            )
            assert not _HAN_RE.search(prepared.system_prompt.replace(real_skill_instructions, ""))
            assert CORE_TRADING_SKILL_POLICY_EN in prepared.system_prompt

        mock_adapter = MagicMock()
        mock_adapter.call_with_tools.return_value = SimpleNamespace(
            tool_calls=[],
            content='{"stock_name":"Apple","decision_type":"hold","sentiment_score":50}',
            provider="mock",
            model="mock-model",
            usage={},
            reasoning_content=None,
            provider_blocks=None,
        )
        run_exec = AgentExecutor(
            ToolRegistry(),
            mock_adapter,
            skill_instructions=real_skill_instructions,
            default_skill_policy=CORE_TRADING_SKILL_POLICY_ZH,
            use_legacy_default_prompt=False,
        )
        run_exec.run("Analyze AAPL", context={"stock_code": "AAPL", "report_language": lang})
        sent_system_prompt = mock_adapter.call_with_tools.call_args.args[0][0]["content"]
        assert not _HAN_RE.search(sent_system_prompt.replace(real_skill_instructions, ""))
        assert CORE_TRADING_SKILL_POLICY_EN in sent_system_prompt


def _strip_authored_skill_fields(prompt: str, manager: SkillManager) -> str:
    stripped = prompt
    for skill in manager.list_active_skills():
        if skill.instructions:
            stripped = stripped.replace(skill.instructions, "")
        if skill.description:
            stripped = stripped.replace(skill.description, "")
    return stripped


def test_round4_generated_skill_headings_localized_and_runtime_switched() -> None:
    """SkillManager generated headings are English for en/ko across factory -> executors/agents."""
    manager = SkillManager()
    assert manager.load_builtin_skills() > 0
    manager.activate(["bull_trend", "volume_breakout"])

    zh_text = manager.get_skill_instructions()
    assert "### 技能 1:" in zh_text
    assert "**适用场景**:" in zh_text

    for lang in ("en", "ko"):
        localized = manager.get_skill_instructions(report_language=lang)
        assert "#### " in localized and " Skills" in localized
        assert "### Skill 1:" in localized
        assert "**Applicability**:" in localized
        assert not _HAN_RE.search(_strip_authored_skill_fields(localized, manager))

    base_cfg = SimpleNamespace(
        agent_arch="single",
        agent_skills=["bull_trend", "volume_breakout"],
        agent_skill_dir=None,
        agent_skill_autoweight=False,
        agent_max_steps=6,
        agent_orchestrator_timeout_s=30,
        agent_orchestrator_mode="standard",
        agent_llm_model=None,
        litellm_model="openai/gpt-5",
        report_language="zh",
    )

    with patch("src.agent.factory.get_tool_registry", return_value=ToolRegistry()), patch(
        "src.agent.factory.get_skill_manager",
        side_effect=lambda cfg=None: manager,
    ), patch("src.agent.llm_adapter.LLMToolAdapter", return_value=MagicMock()) as mock_adapter_cls:
        single_exec = build_agent_executor(base_cfg)
        chat_exec = build_agent_chat_executor(base_cfg)
        multi_cfg = SimpleNamespace(**{**base_cfg.__dict__, "agent_arch": "multi"})
        multi_orch = build_agent_executor(multi_cfg)
        mock_adapter = mock_adapter_cls.return_value

        state_en = resolve_skill_prompt_state(SimpleNamespace(**{**base_cfg.__dict__, "report_language": "en"}))
        assert "### Skill 1:" in state_en.skill_instructions
        assert not _HAN_RE.search(_strip_authored_skill_fields(state_en.skill_instructions, manager))

        # Request-level switch to en/ko even when constructed with config.report_language="zh"
        mock_adapter.call_with_tools.return_value = SimpleNamespace(
            tool_calls=[],
            content='{"stock_name":"Apple","decision_type":"hold","sentiment_score":50}',
            provider="mock",
            model="mock-model",
            usage={},
            reasoning_content=None,
            provider_blocks=None,
        )
        for lang in ("en", "ko"):
            single_exec.run("Analyze AAPL", context={"stock_code": "AAPL", "report_language": lang})
            sys_prompt = mock_adapter.call_with_tools.call_args.args[0][0]["content"]
            assert "### Skill 1:" in sys_prompt
            assert "**Applicability**:" in sys_prompt
            assert not _HAN_RE.search(_strip_authored_skill_fields(sys_prompt, manager))

            with patch("src.agent.executor.build_agent_chat_context_bundle", return_value=SimpleNamespace(context_messages=[])), patch(
                "src.agent.executor.build_visible_chat_history",
                return_value=[],
            ):
                prepared = prepare_agent_chat(
                    message="Ask AAPL",
                    session_id="s-r4",
                    context={"stock_code": "AAPL", "report_language": lang},
                    config=base_cfg,
                    context_llm_adapter=mock_adapter,
                    skill_instructions=chat_exec.skill_instructions,
                    default_skill_policy=chat_exec.default_skill_policy,
                    use_legacy_default_prompt=chat_exec.use_legacy_default_prompt,
                    include_provider_trace=False,
                    skill_manager=chat_exec.skill_manager,
                )
                assert "### Skill 1:" in prepared.system_prompt
                assert "**Applicability**:" in prepared.system_prompt
                assert not _HAN_RE.search(_strip_authored_skill_fields(prepared.system_prompt, manager))

            ko_or_en_ctx = AgentContext(query="Analyze AAPL", stock_code="AAPL", meta={"report_language": lang})
            chain = multi_orch._build_agent_chain(ko_or_en_ctx)
            for sub_agent in (chain[0], chain[-1]):  # TechnicalAgent and DecisionAgent
                sub_prompt = sub_agent.system_prompt(ko_or_en_ctx)
                assert "### Skill 1:" in sub_prompt
                assert "**Applicability**:" in sub_prompt
                assert not _HAN_RE.search(_strip_authored_skill_fields(sub_prompt, manager))


def test_round4_malformed_dashboard_sections_stripped_and_render_safely() -> None:
    """Non-dict data_perspective sections cannot block cached backfill or crash Markdown renderers."""
    orch = _make_orchestrator()

    # 1) Non-dict section in data_perspective + non-list action_checklist/risk_alerts with NO cached data -> cleanly omitted
    empty_ctx = AgentContext(query="Analyze AAPL", stock_code="AAPL", stock_name="Apple Inc.")
    empty_ctx.meta["report_language"] = "en"
    cleaned_empty = orch._finalize_dashboard_payload(
        {
            "decision_type": "hold",
            "dashboard": {
                "data_perspective": {
                    "trend_status": [1],
                    "price_position": "bad",
                    "volume_analysis": 42,
                    "chip_structure": True,
                },
                "battle_plan": {"action_checklist": 123},
                "intelligence": {"risk_alerts": "single warning", "positive_catalysts": 999},
            },
        },
        empty_ctx,
    )
    assert cleaned_empty is not None
    assert "data_perspective" not in cleaned_empty["dashboard"]
    assert cleaned_empty["dashboard"]["battle_plan"]["action_checklist"] == []
    assert cleaned_empty["dashboard"]["intelligence"]["risk_alerts"] == ["single warning"]
    assert "positive_catalysts" not in cleaned_empty["dashboard"]["intelligence"]

    # 2) Malformed model sections do NOT block cached TrendAnalysisResult data_perspective backfill
    cached_ctx = AgentContext(query="Analyze AAPL", stock_code="AAPL", stock_name="Apple Inc.")
    cached_ctx.meta["report_language"] = "ko"
    cached_ctx.set_data(
        "trend_result",
        TrendAnalysisResult(
            code="AAPL",
            current_price=195.0,
            ma5=192.0,
            ma10=189.0,
            ma20=185.0,
            bias_ma5=1.56,
            signal_score=80,
            support_levels=[190.0],
            resistance_levels=[205.0],
            volume_status=VolumeStatus.NORMAL,
        ).to_dict(),
    )
    cached_ctx.add_opinion(
        AgentOpinion(
            agent_name="technical",
            signal="buy",
            confidence=0.8,
            raw_data={"ma_alignment": "bullish", "trend_score": 80},
        )
    )
    cleaned_cached = orch._finalize_dashboard_payload(
        {
            "decision_type": "buy",
            "dashboard": {
                "data_perspective": {
                    "trend_status": [1],
                    "price_position": "bad",
                }
            },
        },
        cached_ctx,
    )
    assert cleaned_cached is not None
    dp = cleaned_cached["dashboard"]["data_perspective"]
    assert dp["trend_status"]["trend_score"] == 80
    assert dp["price_position"]["current_price"] == 195.0
    assert dp["volume_analysis"]["volume_status"] == "거래량 보통"

    # 3) Direct malformed sections handed to HistoryService & NotificationService never raise AttributeError
    malformed_result = AnalysisResult(
        code="AAPL",
        name="Apple",
        sentiment_score=55,
        trend_prediction="Neutral",
        operation_advice="Hold",
        decision_type="hold",
        confidence_level="Medium",
        analysis_summary="Test summary",
        report_language="en",
        dashboard={
            "intelligence": {"risk_alerts": "bad-string", "positive_catalysts": 123},
            "core_conclusion": {"one_sentence": "ok", "position_advice": [1]},
            "data_perspective": {
                "trend_status": [1],
                "price_position": "bad",
                "volume_analysis": 99,
                "chip_structure": True,
            },
            "battle_plan": {
                "sniper_points": [1],
                "position_strategy": "bad",
                "action_checklist": "check-item",
            },
        },
    )
    history_svc = object.__new__(HistoryService)
    hist_md = history_svc._generate_single_stock_markdown(malformed_result, SimpleNamespace(created_at=None))
    assert "AAPL" in hist_md

    notif_svc = NotificationService()
    notif_svc._report_summary_only = False
    for renderer_enabled in (False, True):
        fake_cfg = SimpleNamespace(
            report_renderer_enabled=renderer_enabled,
            report_language="en",
            report_show_llm_model=False,
            report_templates_dir="templates",
        )
        notif_svc._config = fake_cfg
        with patch("src.notification.get_config", return_value=fake_cfg), patch(
            "src.services.report_renderer.get_config", return_value=fake_cfg
        ):
            for bad_dashboard in (
                malformed_result.dashboard,
                [],
                ["unexpected-list"],
                "unexpected-string",
                123,
                {
                    "core_conclusion": [],
                    "battle_plan": "bad-battle-plan",
                    "intelligence": 42,
                    "signal_attribution": ["bad-signal-attr"],
                    "data_perspective": [],
                },
                {
                    "core_conclusion": {"one_sentence": 999, "position_advice": []},
                    "battle_plan": {"sniper_points": [], "action_checklist": "bad-checklist"},
                    "intelligence": {"risk_alerts": "bad-risk", "positive_catalysts": 123},
                },
            ):
                variant = AnalysisResult(
                    code="AAPL",
                    name="Apple",
                    sentiment_score=55,
                    trend_prediction="Neutral",
                    operation_advice="Hold",
                    decision_type="hold",
                    confidence_level="Medium",
                    analysis_summary="Test summary",
                    buy_reason=12345,  # type: ignore[arg-type]
                    key_points=["p1", "p2"],  # type: ignore[arg-type]
                    risk_warning={"w": 1},  # type: ignore[arg-type]
                    report_language="en",
                    dashboard=bad_dashboard,  # type: ignore[arg-type]
                )
                assert "AAPL" in notif_svc.generate_dashboard_report([variant], report_date="2026-11-27")
                assert "AAPL" in notif_svc.generate_wechat_dashboard([variant])
                assert "AAPL" in notif_svc.generate_wechat_summary([variant])
                assert "AAPL" in notif_svc.generate_brief_report([variant], report_date="2026-11-27")
                assert "AAPL" in notif_svc.generate_single_stock_report(variant)


def test_round4_single_agent_sentiment_strings_and_prompt_example(tmp_path) -> None:
    """Malformed/out-of-range sentiment_score strings fall back cleanly and SQLite persistence succeeds."""
    assert '"sentiment_score": "integer 0-100"' not in _ENGLISH_DASHBOARD_JSON_FORMAT_SECTION
    assert '"sentiment_score": 0-100 integer' in _ENGLISH_DASHBOARD_JSON_FORMAT_SECTION

    trend = TrendAnalysisResult(code="AAPL", signal_score=67)
    pipeline = object.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        enable_realtime_quote=False,
        enable_chip_distribution=False,
        report_language="en",
    )

    out_of_range_or_bad = (
        "1e309",
        "-1e309",
        "NaN",
        "Infinity",
        "integer 0-100",
        "0-100",
        "1e308",
        1e308,
        "1000",
        1000,
        "-10",
        "-1e308",
    )
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'sentiment_bounds.db'}")
    try:
        for idx, bad in enumerate(out_of_range_or_bad):
            parsed = parse_dashboard_json(json.dumps({"decision_type": "hold", "sentiment_score": bad}))
            assert parsed is not None
            assert parsed["sentiment_score"] is None
            res = pipeline._agent_result_to_analysis_result(
                SimpleNamespace(
                    success=True,
                    dashboard=parsed,
                    content="",
                    error=None,
                    provider="mock",
                    model="mock",
                ),
                "AAPL",
                "Apple",
                ReportType.FULL,
                f"q-bad-{idx}",
                trend_result=trend,
            )
            assert res.sentiment_score == 67
            assert res.dashboard["sentiment_score"] == 67

            raw_res = pipeline._agent_result_to_analysis_result(
                SimpleNamespace(
                    success=True,
                    dashboard={"decision_type": "hold", "sentiment_score": bad},
                    content="",
                    error=None,
                    provider="mock",
                    model="mock",
                ),
                "AAPL",
                "Apple",
                ReportType.FULL,
                f"q-raw-bad-{idx}",
                trend_result=trend,
            )
            assert raw_res.sentiment_score == 67
            assert raw_res.dashboard["sentiment_score"] == 67
            if bad in ("1e308", "1000"):
                saved_id = db.save_analysis_history(raw_res, f"q-raw-bad-{idx}", "full", None)
                assert saved_id > 0
    finally:
        DatabaseManager.reset_instance()

    for zero_val in (0, "0"):
        parsed_zero = parse_dashboard_json(json.dumps({"decision_type": "hold", "sentiment_score": zero_val}))
        assert parsed_zero is not None
        assert parsed_zero["sentiment_score"] == zero_val
        res_zero = pipeline._agent_result_to_analysis_result(
            SimpleNamespace(
                success=True,
                dashboard=parsed_zero,
                content="",
                error=None,
                provider="mock",
                model="mock",
            ),
            "AAPL",
            "Apple",
            ReportType.FULL,
            "q-zero",
            trend_result=trend,
        )
        assert res_zero.sentiment_score == 0
        assert res_zero.dashboard["sentiment_score"] == zero_val

    # General integer coercion contract preserved while blocking 309-digit floats:
    assert StockAnalysisPipeline._safe_int("-10") == -10
    assert StockAnalysisPipeline._safe_int("1e308", 50) == 50
    assert StockAnalysisPipeline._safe_int("1e309", 50) == 50
    assert StockAnalysisPipeline._safe_int("-1e309", 50) == 50
    assert StockAnalysisPipeline._safe_int("integer 0-100", 50) == 50
    assert StockAnalysisPipeline._safe_int("80分", 50) == 80
    assert StockAnalysisPipeline._safe_int("75%", 50) == 75


def test_round4_mixed_valid_and_invalid_confidence_skills_isolated() -> None:
    """Invalid-confidence skill opinions are partitioned out of the entire Decision evidence chain."""
    valid_buy = AgentOpinion(
        agent_name="skill_alpha",
        signal="buy",
        confidence=0.65,
        raw_data={"skill_id": "alpha", "signal": "buy", "score_adjustment": 10},
    )
    invalid_sell = AgentOpinion(
        agent_name="skill_beta",
        signal="sell",
        confidence=1.5,
        raw_data={"skill_id": "beta", "signal": "sell", "score_adjustment": -15},
    )
    assert valid_buy.confidence_input_valid is True
    assert invalid_sell.confidence_input_valid is False

    # 1) Orchestrator StrategyEngine partition keeps valid_buy only and moves invalid_sell to diagnostics.
    orch = _make_orchestrator()
    for lang, expected_label in (
        ("en", "invalid confidence"),
        ("ko", "유효하지 않은 신뢰도"),
        ("zh", "置信度无效"),
    ):
        ctx = AgentContext(query="Analyze 600519", stock_code="600519", opinions=[valid_buy, invalid_sell])
        ctx.meta["report_language"] = lang
        orch._run_strategy_engine(ctx)

        opinion_agents = [op.agent_name for op in ctx.opinions]
        assert "skill_alpha" in opinion_agents
        assert "skill_beta" not in opinion_agents
        assert len(ctx.meta["invalid_opinions"]) == 1
        assert ctx.meta["invalid_opinions"][0]["agent_name"] == "skill_beta"
        assert ctx.meta["invalid_opinions"][0]["reason"] == "invalid_confidence"

        assert should_trigger_evidence_debate(ctx, enabled=True) == (False, "consensus_clear")
        summary = build_agent_disagreement_summary(ctx)
        assert summary["bearish_agents"] == []
        prompt_text = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock()).build_user_message(ctx)
        evidence_section, _, diagnostics_section = prompt_text.partition(
            "## Invalid Skill Opinions"
        )
        assert "skill_beta" not in evidence_section
        assert expected_label in diagnostics_section

    # Legacy _partition_skill_opinions and _apply_partition_fallback match the same contract.
    legacy_ctx = AgentContext(query="Analyze 600519", stock_code="600519", opinions=[valid_buy, invalid_sell])
    orch._partition_skill_opinions(legacy_ctx)
    assert [op.agent_name for op in legacy_ctx.opinions] == ["skill_alpha"]
    assert legacy_ctx.meta["invalid_opinions"][0]["reason"] == "invalid_confidence"

    fallback_ctx = AgentContext(query="Analyze 600519", stock_code="600519", opinions=[valid_buy, invalid_sell])
    orch._apply_partition_fallback(fallback_ctx)
    assert [op.agent_name for op in fallback_ctx.opinions] == ["skill_alpha"]
    assert fallback_ctx.meta["invalid_opinions"][0]["reason"] == "invalid_confidence"
    assert should_trigger_evidence_debate(
        AgentContext(stock_code="600519", opinions=[valid_buy, invalid_sell]),
        enabled=True,
    ) == (False, "consensus_clear")

    # 2) Aggregator and StrategyEngine behavior remains isolated even if called directly.
    aggregator = SkillAggregator()
    agg = aggregator.calculate([valid_buy, invalid_sell])
    assert agg is not None
    assert agg.final_signal == "buy"
    assert agg.weighted_confidence == pytest.approx(0.65)
    assert agg.total_adjustment == pytest.approx(10.0)
    assert agg.conflicts == []

    engine_res = StrategyEngine(aggregator=aggregator).process([valid_buy, invalid_sell])
    assert engine_res.synthesis_dict is not None
    assert engine_res.synthesis_dict["conflicts"] == []
    assert "deliberation" not in engine_res.synthesis_dict
    assert engine_res.synthesis_dict["confidence"] == pytest.approx(0.65)
    assert engine_res.synthesis_dict["opposing_skills"] == []
    assert engine_res.synthesis_dict["summary_params"]["opinion_count"] == 1
    assert engine_res.synthesis_dict["summary_params"]["invalid_opinion_count"] == 1

    direct_consensus = aggregator.aggregate(AgentContext(stock_code="600519", opinions=[valid_buy, invalid_sell]))
    assert direct_consensus is not None
    assert direct_consensus.confidence == pytest.approx(0.65)
    assert direct_consensus.raw_data["strategy_synthesis"]["conflicts"] == []
    assert "deliberation" not in direct_consensus.raw_data["strategy_synthesis"]


def test_round4_ko_chat_timeout_and_stop_loss_risk_control_sync() -> None:
    """Korean chat timeout errors localize cleanly, zh whitespace stays intact, and stop-loss backfill syncs risk_control."""
    orch = _make_orchestrator()
    ko_ctx = AgentContext(query="삼성전자 분석", stock_code="005930.KS", meta={"report_language": "ko"})
    timeout_res = orch._build_timeout_result(
        AgentRunStats(), [], [], elapsed_s=12.5, timeout_s=10, ctx=ko_ctx, parse_dashboard=False,
    )
    assert timeout_res.error == "Pipeline timed out after 12.50s (limit: 10s)"
    ko_persisted = format_chat_failure_message(timeout_res.error, "ko")
    assert ko_persisted.startswith("[분석 실패] 파이프라인 시간 초과")
    assert "Pipeline timed out" not in ko_persisted

    budget_res = orch._build_budget_skip_result(
        AgentRunStats(), [], [], elapsed_s=8.0, timeout_s=10,
        stage_name="decision", remaining_budget=2.0, min_stage_budget_s=15,
        ctx=ko_ctx, parse_dashboard=False,
    )
    ko_budget_persisted = format_chat_failure_message(budget_res.error, "ko")
    assert ko_budget_persisted.startswith("[분석 실패]")
    assert "Pipeline skipped" not in ko_budget_persisted

    run_timeout = runner_timeout_result(
        start_time=0.0,
        max_wall_clock_seconds=10.0,
        step=2,
        tool_calls_log=[],
        total_tokens=0,
        provider_used="litellm",
        models_used=[],
        messages=[],
    )
    ko_runner_timeout = format_chat_failure_message(run_timeout.error, "ko")
    assert ko_runner_timeout.startswith("[분석 실패] 에이전트 시간 초과")
    assert "Agent timed out" not in ko_runner_timeout

    ko_stage_wrapped = format_chat_failure_message(
        "Stage 'technical' failed: Agent timed out after 12.50s (limit: 10.00s)",
        "ko",
    )
    assert ko_stage_wrapped == "[분석 실패] 'technical' 단계 실행 실패: 에이전트 시간 초과 (12.50초 경과, 제한 10.00초)"

    run_budget = runner_budget_guard_result(
        start_time=0.0,
        step=2,
        tool_calls_log=[],
        total_tokens=0,
        provider_used="litellm",
        models_used=[],
        messages=[],
        remaining_timeout_s=2.5,
        min_step_budget_s=15.0,
    )
    ko_runner_budget = format_chat_failure_message(run_budget.error, "ko")
    assert ko_runner_budget.startswith("[분석 실패] 남은 시간 부족으로 에이전트 단계를 건너뛰었습니다")
    assert "Agent step skipped" not in ko_runner_budget

    ko_max_steps = format_chat_failure_message(
        "Agent exceeded max steps (10). Try increasing AGENT_MAX_STEPS if analysis tasks are complex.",
        "ko",
    )
    assert ko_max_steps.startswith("[분석 실패] 에이전트 최대 단계 수(10)")

    # Preserve origin/main zh whitespace detail behavior
    assert format_chat_failure_message("   ", "zh") == "[分析失败]    "

    # Stop-loss backfill syncs orchestrator placeholder risk_control across zh/en/ko, keeping custom text untouched
    trend_with_support = TrendAnalysisResult(
        code="005930.KS",
        support_levels=[180.0],
        volume_status=VolumeStatus.NORMAL,
    )
    pipeline = object.__new__(StockAnalysisPipeline)
    expected_prefix = {
        "zh": "止损参考 180.0",
        "en": "Stop-loss reference 180.0",
        "ko": "손절 참고 180.0",
    }
    for lang in ("zh", "en", "ko"):
        ctx = AgentContext(query="Analyze 005930.KS", stock_code="005930.KS", stock_name="Samsung")
        ctx.meta["report_language"] = lang
        dash = orch._finalize_dashboard_payload({"decision_type": "buy"}, ctx)
        assert dash is not None
        res = AnalysisResult(
            code="005930.KS",
            name="Samsung",
            sentiment_score=int(dash["sentiment_score"]),
            trend_prediction=dash["trend_prediction"],
            operation_advice=dash["operation_advice"],
            decision_type=dash["decision_type"],
            confidence_level=dash["confidence_level"],
            analysis_summary=dash["analysis_summary"],
            dashboard=dash["dashboard"],
        )
        pipeline._backfill_agent_dashboard_fields(res, trend_with_support, lang)
        assert res.dashboard["battle_plan"]["sniper_points"]["stop_loss"] == 180.0
        assert res.dashboard["battle_plan"]["position_strategy"]["risk_control"] == expected_prefix[lang]

    # Custom LLM-authored risk_control is preserved verbatim when stop_loss backfills
    custom_res = AnalysisResult(
        code="AAPL",
        name="Apple",
        sentiment_score=65,
        trend_prediction="Bullish",
        operation_advice="Buy",
        decision_type="buy",
        confidence_level="Medium",
        analysis_summary="Summary",
        dashboard={
            "battle_plan": {
                "sniper_points": {"stop_loss": "TBD"},
                "position_strategy": {"risk_control": "Cut loss if closing below 20-day MA twice"},
            }
        },
    )
    pipeline._backfill_agent_dashboard_fields(custom_res, trend_with_support, "en")
    assert custom_res.dashboard["battle_plan"]["sniper_points"]["stop_loss"] == 180.0
    assert (
        custom_res.dashboard["battle_plan"]["position_strategy"]["risk_control"]
        == "Cut loss if closing below 20-day MA twice"
    )
