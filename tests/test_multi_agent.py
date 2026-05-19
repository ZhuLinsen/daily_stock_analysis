# -*- coding: utf-8 -*-
"""
Tests for the multi-agent architecture modules.

Covers:
- _extract_stock_code: Chinese boundary, HK, US, common word filtering
- AgentContext / AgentOpinion / StageResult protocol basics
- AgentOrchestrator: pipeline execution, mode selection, error handling
- StrategyRouter: regime detection, manual mode, user override
- StrategyAggregator: weighted consensus, empty input
- PortfolioAgent.post_process: JSON parsing via try_parse_json
"""

import json
import sys
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Keep test runnable when optional LLM deps are missing
try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from src.agent.orchestrator import _extract_stock_code, _COMMON_WORDS
from src.agent.protocols import (
    AgentContext,
    AgentOpinion,
    AgentRunStats,
    Signal,
    StageResult,
    StageStatus,
)
from src.config import AGENT_MAX_STEPS_DEFAULT


# ============================================================
# _extract_stock_code
# ============================================================

class TestExtractStockCode(unittest.TestCase):
    """Validate stock code extraction from free text."""

    # --- A-share ---

    def test_a_share_plain(self):
        self.assertEqual(_extract_stock_code("600519"), "600519")

    def test_a_share_chinese_prefix(self):
        """Critical: Chinese char + digits must still match (no \\b)."""
        self.assertEqual(_extract_stock_code("分析600519"), "600519")

    def test_a_share_chinese_suffix(self):
        self.assertEqual(_extract_stock_code("600519怎么样"), "600519")

    def test_a_share_in_sentence(self):
        self.assertEqual(_extract_stock_code("请帮我看看600519的走势"), "600519")

    def test_a_share_with_prefix_0(self):
        self.assertEqual(_extract_stock_code("分析000858"), "000858")

    def test_a_share_with_prefix_3(self):
        self.assertEqual(_extract_stock_code("分析300750"), "300750")

    def test_a_share_not_match_7_digits(self):
        """Should not match 7-digit number."""
        self.assertEqual(_extract_stock_code("1234567"), "")

    def test_a_share_embedded_in_longer_number(self):
        """Should not extract from within a longer number."""
        self.assertEqual(_extract_stock_code("86006005190001"), "")

    # --- HK ---

    def test_hk_lowercase(self):
        self.assertEqual(_extract_stock_code("look at hk00700"), "HK00700")

    def test_hk_uppercase(self):
        self.assertEqual(_extract_stock_code("HK00700 analysis"), "HK00700")

    def test_hk_chinese(self):
        self.assertEqual(_extract_stock_code("分析hk00700"), "HK00700")

    def test_hk_not_match_alpha_prefix(self):
        """Letters before 'hk' should not prevent match."""
        # "xhk00700" has alpha before hk, lookbehind should block
        self.assertNotEqual(_extract_stock_code("xhk00700"), "HK00700")

    # --- US ---

    def test_us_ticker(self):
        self.assertEqual(_extract_stock_code("analyze AAPL"), "AAPL")

    def test_us_ticker_in_chinese(self):
        self.assertEqual(_extract_stock_code("看看TSLA"), "TSLA")

    def test_us_ticker_5_chars(self):
        self.assertEqual(_extract_stock_code("check GOOGL"), "GOOGL")

    def test_lowercase_us_ticker_with_analysis_hint(self):
        self.assertEqual(_extract_stock_code("分析tsla"), "TSLA")

    def test_lowercase_us_ticker_bare(self):
        self.assertEqual(_extract_stock_code("tsla"), "TSLA")

    def test_bse_code_with_8_prefix(self):
        self.assertEqual(_extract_stock_code("分析830799"), "830799")

    def test_bse_code_with_92_prefix(self):
        self.assertEqual(_extract_stock_code("看看920748"), "920748")

    # --- Common word filtering ---

    def test_common_word_buy(self):
        self.assertEqual(_extract_stock_code("should I BUY"), "")

    def test_common_word_sell(self):
        self.assertEqual(_extract_stock_code("should I SELL"), "")

    def test_common_word_hold(self):
        self.assertEqual(_extract_stock_code("should I HOLD"), "")

    def test_common_word_etf(self):
        self.assertEqual(_extract_stock_code("what about ETF"), "")

    def test_common_word_rsi(self):
        self.assertEqual(_extract_stock_code("RSI is high"), "")

    def test_common_word_macd(self):
        self.assertEqual(_extract_stock_code("check MACD"), "")

    def test_common_word_stock(self):
        self.assertEqual(_extract_stock_code("good STOCK pick"), "")

    def test_common_word_trend(self):
        self.assertEqual(_extract_stock_code("the TREND is up"), "")

    # --- Priority: A-share > HK > US ---

    def test_a_share_takes_priority_over_us(self):
        """When both A-share code and US ticker appear, A-share wins."""
        self.assertEqual(_extract_stock_code("600519 vs AAPL"), "600519")

    # --- Empty / irrelevant ---

    def test_empty_string(self):
        self.assertEqual(_extract_stock_code(""), "")

    def test_no_code(self):
        self.assertEqual(_extract_stock_code("hello world"), "")

    def test_single_char_uppercase(self):
        """Single uppercase letter should not match."""
        self.assertEqual(_extract_stock_code("I think"), "")

    def test_lowercase_not_us_ticker(self):
        """Lowercase letters should not match US regex."""
        self.assertEqual(_extract_stock_code("analyze aapl"), "")

    def test_common_words_set_completeness(self):
        """Ensure critical finance terms are in _COMMON_WORDS."""
        expected_in_set = {"BUY", "SELL", "HOLD", "ETF", "IPO", "RSI", "MACD", "STOCK", "TREND"}
        self.assertTrue(expected_in_set.issubset(_COMMON_WORDS))


# ============================================================
# Protocol dataclasses
# ============================================================

class TestAgentContext(unittest.TestCase):
    """Test AgentContext helpers."""

    def test_add_opinion(self):
        ctx = AgentContext(query="test", stock_code="600519")
        op = AgentOpinion(agent_name="tech", signal="buy", confidence=0.8)
        ctx.add_opinion(op)
        self.assertEqual(len(ctx.opinions), 1)
        self.assertGreater(op.timestamp, 0)

    def test_add_risk_flag(self):
        ctx = AgentContext()
        ctx.add_risk_flag("insider", "major sell-down", severity="high")
        self.assertTrue(ctx.has_risk_flags)
        self.assertEqual(ctx.risk_flags[0]["severity"], "high")

    def test_set_get_data(self):
        ctx = AgentContext()
        ctx.set_data("foo", {"bar": 1})
        self.assertEqual(ctx.get_data("foo"), {"bar": 1})
        self.assertIsNone(ctx.get_data("missing"))
        self.assertEqual(ctx.get_data("missing", "default"), "default")


class TestAgentOpinion(unittest.TestCase):
    """Test AgentOpinion clamping and signal parsing."""

    def test_confidence_clamp_high(self):
        op = AgentOpinion(confidence=1.5)
        self.assertEqual(op.confidence, 1.0)

    def test_confidence_clamp_low(self):
        op = AgentOpinion(confidence=-0.3)
        self.assertEqual(op.confidence, 0.0)

    def test_signal_enum_valid(self):
        op = AgentOpinion(signal="buy")
        self.assertEqual(op.signal_enum, Signal.BUY)

    def test_signal_enum_invalid(self):
        op = AgentOpinion(signal="maybe")
        self.assertIsNone(op.signal_enum)


class TestAgentRunStats(unittest.TestCase):
    """Test AgentRunStats aggregation."""

    def test_record_stage(self):
        stats = AgentRunStats()
        r1 = StageResult(
            stage_name="tech", status=StageStatus.COMPLETED,
            tokens_used=100, tool_calls_count=3, duration_s=1.2,
        )
        r2 = StageResult(
            stage_name="intel", status=StageStatus.FAILED,
            tokens_used=50, tool_calls_count=1, duration_s=0.8,
        )
        stats.record_stage(r1)
        stats.record_stage(r2)

        self.assertEqual(stats.total_stages, 2)
        self.assertEqual(stats.completed_stages, 1)
        self.assertEqual(stats.failed_stages, 1)
        self.assertEqual(stats.total_tokens, 150)
        self.assertEqual(stats.total_tool_calls, 4)

    def test_to_dict(self):
        stats = AgentRunStats()
        d = stats.to_dict()
        self.assertIn("total_stages", d)
        self.assertIn("models_used", d)


# ============================================================
# Legacy StrategyRouter Compatibility
# ============================================================

class TestStrategyRouter(unittest.TestCase):
    """Test the legacy StrategyRouter alias for SkillRouter."""

    def test_user_requested_strategies_take_priority(self):
        from src.agent.strategies.router import StrategyRouter
        router = StrategyRouter()
        ctx = AgentContext(query="test")
        ctx.meta["strategies_requested"] = ["chan_theory", "wave_theory"]
        result = router.select_strategies(ctx)
        self.assertEqual(result, ["chan_theory", "wave_theory"])

    def test_user_requested_capped_at_max(self):
        from src.agent.strategies.router import StrategyRouter
        router = StrategyRouter()
        ctx = AgentContext()
        ctx.meta["strategies_requested"] = ["a", "b", "c", "d", "e"]
        result = router.select_strategies(ctx, max_count=2)
        self.assertEqual(len(result), 2)

    @patch("src.agent.skills.router.StrategyRouter._get_routing_mode", return_value="manual")
    @patch(
        "src.agent.skills.router.StrategyRouter._get_available_skills",
        return_value=[
            SimpleNamespace(name="chan_theory"),
            SimpleNamespace(name="wave_theory"),
        ],
    )
    @patch("src.config.get_config", return_value=SimpleNamespace(agent_skills=["chan_theory", "wave_theory"]))
    def test_manual_mode_uses_configured_agent_skills(self, _mock_config, _mock_available, _mock):
        from src.agent.strategies.router import StrategyRouter
        router = StrategyRouter()
        ctx = AgentContext()
        result = router.select_strategies(ctx)
        self.assertEqual(result, ["chan_theory", "wave_theory"])

    @patch("src.agent.skills.router.StrategyRouter._get_routing_mode", return_value="manual")
    @patch(
        "src.agent.skills.router.StrategyRouter._get_available_skills",
        return_value=[
            SimpleNamespace(name="bull_trend", default_router=True, default_priority=10),
            SimpleNamespace(name="shrink_pullback", default_router=True, default_priority=40),
        ],
    )
    @patch("src.config.get_config", return_value=SimpleNamespace(agent_skills=[]))
    def test_manual_mode_falls_back_to_defaults_when_no_skills_configured(self, _mock_config, _mock_available, _mock):
        from src.agent.strategies.router import StrategyRouter, _DEFAULT_STRATEGIES
        router = StrategyRouter()
        ctx = AgentContext()
        result = router.select_strategies(ctx)
        self.assertEqual(result, list(_DEFAULT_STRATEGIES[:3]))

    def test_detect_regime_bullish(self):
        from src.agent.strategies.router import StrategyRouter
        router = StrategyRouter()
        ctx = AgentContext()
        ctx.add_opinion(AgentOpinion(
            agent_name="technical",
            signal="buy",
            confidence=0.8,
            raw_data={"ma_alignment": "bullish", "trend_score": 80, "volume_status": "normal"},
        ))
        regime = router._detect_regime(ctx)
        self.assertEqual(regime, "trending_up")

    def test_detect_regime_bearish(self):
        from src.agent.strategies.router import StrategyRouter
        router = StrategyRouter()
        ctx = AgentContext()
        ctx.add_opinion(AgentOpinion(
            agent_name="technical",
            signal="sell",
            confidence=0.7,
            raw_data={"ma_alignment": "bearish", "trend_score": 20, "volume_status": "light"},
        ))
        regime = router._detect_regime(ctx)
        self.assertEqual(regime, "trending_down")

    def test_detect_regime_none_without_technical(self):
        from src.agent.strategies.router import StrategyRouter
        router = StrategyRouter()
        ctx = AgentContext()
        regime = router._detect_regime(ctx)
        self.assertIsNone(regime)


# ============================================================
# StrategyAggregator
# ============================================================

class TestStrategyAggregator(unittest.TestCase):
    """Test StrategyAggregator consensus logic."""

    def test_no_strategy_opinions_returns_none(self):
        from src.agent.strategies.aggregator import StrategyAggregator
        agg = StrategyAggregator()
        ctx = AgentContext()
        ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8))
        result = agg.aggregate(ctx)
        self.assertIsNone(result)

    def test_single_strategy_consensus(self):
        from src.agent.strategies.aggregator import StrategyAggregator
        agg = StrategyAggregator()
        ctx = AgentContext()
        ctx.add_opinion(AgentOpinion(agent_name="strategy_bull_trend", signal="buy", confidence=0.7))
        result = agg.aggregate(ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.agent_name, "skill_consensus")
        self.assertEqual(result.signal, "buy")

    def test_mixed_signals_produce_hold(self):
        from src.agent.strategies.aggregator import StrategyAggregator
        agg = StrategyAggregator()
        ctx = AgentContext()
        ctx.add_opinion(AgentOpinion(agent_name="strategy_a", signal="buy", confidence=0.6))
        ctx.add_opinion(AgentOpinion(agent_name="strategy_b", signal="sell", confidence=0.6))
        result = agg.aggregate(ctx)
        self.assertIsNotNone(result)
        # Average of buy(4) + sell(2) = 3.0, which maps to "hold"
        self.assertEqual(result.signal, "hold")


# ============================================================
# PortfolioAgent.post_process
# ============================================================

class TestPortfolioAgentPostProcess(unittest.TestCase):
    """Test PortfolioAgent.post_process uses try_parse_json correctly."""

    def _make_agent(self):
        from src.agent.agents.portfolio_agent import PortfolioAgent
        mock_registry = MagicMock()
        mock_adapter = MagicMock()
        return PortfolioAgent(tool_registry=mock_registry, llm_adapter=mock_adapter)

    def test_parse_plain_json(self):
        agent = self._make_agent()
        ctx = AgentContext()
        data = {"portfolio_risk_score": 3, "summary": "Looks good"}
        op = agent.post_process(ctx, json.dumps(data))
        self.assertIsNotNone(op)
        self.assertEqual(op.signal, "buy")
        self.assertEqual(ctx.data.get("portfolio_assessment"), data)

    def test_parse_markdown_json(self):
        agent = self._make_agent()
        ctx = AgentContext()
        data = {"portfolio_risk_score": 8, "summary": "High risk"}
        raw = f"Here is the analysis:\n```json\n{json.dumps(data)}\n```"
        op = agent.post_process(ctx, raw)
        self.assertIsNotNone(op)
        self.assertEqual(op.signal, "sell")

    def test_parse_failure_returns_hold(self):
        agent = self._make_agent()
        ctx = AgentContext()
        op = agent.post_process(ctx, "This is not JSON at all")
        self.assertIsNotNone(op)
        self.assertEqual(op.signal, "hold")
        self.assertAlmostEqual(op.confidence, 0.3)


class TestDecisionAgentPostProcess(unittest.TestCase):
    """Test DecisionAgent dashboard normalization behaviour."""

    def test_normalizes_strong_decision_type_to_legacy_enum(self):
        from src.agent.agents.decision_agent import DecisionAgent

        agent = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
        ctx = AgentContext(query="test", stock_code="600519")
        dashboard = {
            "decision_type": "strong_buy",
            "sentiment_score": 88,
            "analysis_summary": "High conviction",
            "stock_name": "贵州茅台",
        }

        opinion = agent.post_process(ctx, json.dumps(dashboard))

        self.assertIsNotNone(opinion)
        self.assertEqual(opinion.signal, "buy")
        self.assertEqual(ctx.get_data("final_dashboard")["decision_type"], "buy")


class TestIntelAgentPostProcess(unittest.TestCase):
    """Test IntelAgent JSON parsing and context caching behaviour."""

    def test_repairs_json_and_caches_intel_context(self):
        from src.agent.agents.intel_agent import IntelAgent

        agent = IntelAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
        ctx = AgentContext(query="test", stock_code="600519")
        raw = """```json
        {
          "signal": "hold",
          "confidence": 0.72,
          "reasoning": "情绪中性偏谨慎",
          "risk_alerts": ["股东减持"],
          "positive_catalysts": ["行业复苏"],
        }
        ```"""

        opinion = agent.post_process(ctx, raw)

        self.assertIsNotNone(opinion)
        self.assertEqual(opinion.signal, "hold")
        self.assertEqual(ctx.get_data("intel_opinion")["positive_catalysts"], ["行业复苏"])
        self.assertEqual(ctx.risk_flags[0]["description"], "股东减持")


# ============================================================
# AgentOrchestrator (with mocked sub-agents)
# ============================================================

class TestOrchestratorModes(unittest.TestCase):
    """Test that _build_agent_chain returns the right agents for each mode."""

    def _make_orchestrator(self, mode="standard"):
        from src.agent.orchestrator import AgentOrchestrator
        mock_registry = MagicMock()
        mock_adapter = MagicMock()
        return AgentOrchestrator(
            tool_registry=mock_registry,
            llm_adapter=mock_adapter,
            mode=mode,
        )

    def test_quick_mode(self):
        orch = self._make_orchestrator("quick")
        ctx = AgentContext(query="test", stock_code="600519")
        chain = orch._build_agent_chain(ctx)
        names = [a.agent_name for a in chain]
        self.assertEqual(names, ["technical", "decision"])

    def test_standard_mode(self):
        orch = self._make_orchestrator("standard")
        ctx = AgentContext(query="test", stock_code="600519")
        chain = orch._build_agent_chain(ctx)
        names = [a.agent_name for a in chain]
        self.assertEqual(names, ["technical", "intel", "decision"])

    def test_full_mode(self):
        orch = self._make_orchestrator("full")
        ctx = AgentContext(query="test", stock_code="600519")
        chain = orch._build_agent_chain(ctx)
        names = [a.agent_name for a in chain]
        self.assertEqual(names, ["technical", "intel", "risk", "decision"])

    def test_invalid_mode_falls_back_to_standard(self):
        orch = self._make_orchestrator("nonsense")
        self.assertEqual(orch.mode, "standard")

    def test_chain_agents_inherit_orchestrator_max_steps(self):
        """Default/lowered limits cap agents; raised limits hard-override all agents."""
        orch = self._make_orchestrator("full")
        orch.max_steps = AGENT_MAX_STEPS_DEFAULT
        high_limit_chain = orch._build_agent_chain(AgentContext(query="test", stock_code="600519"))
        self.assertEqual(
            {agent.agent_name: agent.max_steps for agent in high_limit_chain},
            {"technical": 6, "intel": 4, "risk": 4, "decision": 3},
        )

        orch.max_steps = 5
        low_limit_chain = orch._build_agent_chain(AgentContext(query="test", stock_code="600519"))
        self.assertEqual(
            {agent.agent_name: agent.max_steps for agent in low_limit_chain},
            {"technical": 5, "intel": 4, "risk": 4, "decision": 3},
        )

        orch.max_steps = AGENT_MAX_STEPS_DEFAULT + 2
        raised_limit_chain = orch._build_agent_chain(AgentContext(query="test", stock_code="600519"))
        self.assertEqual(
            {agent.agent_name: agent.max_steps for agent in raised_limit_chain},
            {"technical": AGENT_MAX_STEPS_DEFAULT + 2, "intel": AGENT_MAX_STEPS_DEFAULT + 2, "risk": AGENT_MAX_STEPS_DEFAULT + 2, "decision": AGENT_MAX_STEPS_DEFAULT + 2},
        )

    def test_prepare_agent_raised_limit_overrides_low_default_agent(self):
        orch = self._make_orchestrator("full")
        orch.max_steps = AGENT_MAX_STEPS_DEFAULT + 2
        decision = MagicMock(agent_name="decision", max_steps=3)

        prepared = orch._prepare_agent(decision)

        self.assertIs(prepared, decision)
        self.assertEqual(prepared.max_steps, AGENT_MAX_STEPS_DEFAULT + 2)

    def test_build_context_from_dict(self):
        orch = self._make_orchestrator()
        ctx = orch._build_context(
            "Analyze 600519",
            context={"stock_code": "600519", "stock_name": "贵州茅台", "skills": ["bull_trend"]},
        )
        self.assertEqual(ctx.stock_code, "600519")
        self.assertEqual(ctx.stock_name, "贵州茅台")
        self.assertEqual(ctx.meta["skills_requested"], ["bull_trend"])

    def test_build_context_extracts_code_from_query(self):
        orch = self._make_orchestrator()
        ctx = orch._build_context("分析600519的走势")
        self.assertEqual(ctx.stock_code, "600519")

    def test_fallback_summary(self):
        orch = self._make_orchestrator()
        ctx = AgentContext(query="test", stock_code="600519", stock_name="贵州茅台")
        ctx.add_opinion(AgentOpinion(agent_name="tech", signal="buy", confidence=0.8, reasoning="Strong trend"))
        ctx.add_risk_flag("insider", "Minor sell-down", severity="low")
        summary = orch._fallback_summary(ctx)
        self.assertIn("600519", summary)
        self.assertIn("Strong trend", summary)
        self.assertIn("Minor sell-down", summary)


class TestOrchestratorExecution(unittest.TestCase):
    """Test main orchestrator execution paths."""

    @staticmethod
    def _make_orchestrator(config=None):
        from src.agent.orchestrator import AgentOrchestrator
        return AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
            config=config,
        )

    @staticmethod
    def _stage_result(name, status=StageStatus.COMPLETED, error=None, raw_text="ok"):
        result = StageResult(stage_name=name, status=status, error=error)
        result.meta["raw_text"] = raw_text
        result.meta["models_used"] = ["test/model"]
        return result

    def test_prepare_agent_uses_default_constant_as_raise_threshold(self):
        orch = self._make_orchestrator()
        agent = MagicMock(agent_name="technical", max_steps=6)

        prepared = orch._prepare_agent(agent)
        self.assertIs(prepared, agent)
        self.assertEqual(agent.max_steps, 6)

        orch.max_steps = 12
        agent.max_steps = 6
        orch._prepare_agent(agent)
        self.assertEqual(agent.max_steps, 12)

        orch.max_steps = 5
        agent.max_steps = 6
        orch._prepare_agent(agent)
        self.assertEqual(agent.max_steps, 5)

    def test_execute_pipeline_stops_on_critical_failure(self):
        orch = self._make_orchestrator()
        technical = MagicMock(agent_name="technical")
        technical.run.return_value = self._stage_result("technical", StageStatus.FAILED, error="boom")

        with patch.object(orch, "_build_agent_chain", return_value=[technical]):
            result = orch._execute_pipeline(AgentContext(query="test"))

        self.assertFalse(result.success)
        self.assertIn("technical", result.error)
        self.assertEqual(result.total_tokens, 0)

    def test_execute_pipeline_degrades_on_intel_failure(self):
        orch = self._make_orchestrator()
        ctx = AgentContext(query="test", stock_code="600519")
        ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8, reasoning="Strong trend"))

        intel = MagicMock(agent_name="intel")
        intel.run.return_value = self._stage_result("intel", StageStatus.FAILED, error="news down")
        decision = MagicMock(agent_name="decision")
        decision.run.return_value = self._stage_result("decision")

        with patch.object(orch, "_build_agent_chain", return_value=[intel, decision]):
            result = orch._execute_pipeline(ctx, parse_dashboard=False)

        self.assertTrue(result.success)
        self.assertIn("Analysis Summary", result.content)

    def test_execute_pipeline_degrades_on_skill_agent_failure_and_continues_to_decision(self):
        orch = self._make_orchestrator()
        orch.mode = "specialist"
        ctx = AgentContext(query="test", stock_code="600519")
        ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8, reasoning="Strong trend"))

        technical = MagicMock(agent_name="technical")
        technical.run.return_value = self._stage_result("technical")
        intel = MagicMock(agent_name="intel")
        intel.run.return_value = self._stage_result("intel")
        risk = MagicMock(agent_name="risk")
        risk.run.return_value = self._stage_result("risk")
        skill = MagicMock(agent_name="strategy_bull_trend")
        skill.run.return_value = self._stage_result("strategy_bull_trend", StageStatus.FAILED, error="skill boom")
        decision = MagicMock(agent_name="decision")
        decision.run.return_value = self._stage_result("decision")

        with patch.object(orch, "_build_agent_chain", return_value=[technical, intel, risk, decision]):
            with patch.object(orch, "_build_specialist_agents", return_value=[skill]):
                result = orch._execute_pipeline(ctx, parse_dashboard=False)

        self.assertTrue(result.success)
        self.assertIn("Analysis Summary", result.content)
        skill.run.assert_called_once()
        decision.run.assert_called_once()

    def test_execute_pipeline_skips_stage_when_remaining_budget_below_minimum(self):
        orch = self._make_orchestrator(config=SimpleNamespace(agent_orchestrator_timeout_s=20))
        ctx = AgentContext(query="test", stock_code="600519", stock_name="贵州茅台")

        technical = MagicMock(agent_name="technical")

        def _run_technical(run_ctx, progress_callback=None):
            run_ctx.add_opinion(AgentOpinion(
                agent_name="technical",
                signal="buy",
                confidence=0.8,
                reasoning="技术面结构未出现明显拐点，趋势偏强。",
                raw_data={"ma_alignment": "bullish", "trend_score": 82, "volume_status": "normal"},
            ))
            return self._stage_result("technical")

        technical.run.side_effect = _run_technical
        intel = MagicMock(agent_name="intel", tool_names=["news_search"])
        intel.run.side_effect = AssertionError("intel should be skipped due to budget guard")
        times = iter([0.0, 0.2, 0.3, 14.6, 14.7])

        def _next_time():
            return next(times, 100.0)

        with patch.object(orch, "_build_agent_chain", return_value=[technical, intel]):
            with patch("src.agent.orchestrator.time.time", side_effect=_next_time):
                result = orch._execute_pipeline(ctx)

        self.assertTrue(result.success)
        self.assertIsNotNone(result.dashboard)
        self.assertIsNotNone(result.content)
        self.assertIn("insufficient budget", (result.error or "").lower())
        self.assertIn("[降级结果]", result.dashboard["analysis_summary"])
        technical.run.assert_called_once()
        intel.run.assert_not_called()

    def test_execute_pipeline_skips_toolless_decision_with_low_remaining_budget(self):
        orch = self._make_orchestrator(config=SimpleNamespace(agent_orchestrator_timeout_s=20))
        ctx = AgentContext(query="test", stock_code="600519", stock_name="贵州茅台")

        technical = MagicMock(agent_name="technical")

        def _run_technical(run_ctx, progress_callback=None):
            run_ctx.add_opinion(AgentOpinion(
                agent_name="technical",
                signal="buy",
                confidence=0.8,
                reasoning="技术面结构未出现明显拐点，趋势偏强。",
                raw_data={"ma_alignment": "bullish", "trend_score": 82, "volume_status": "normal"},
            ))
            return self._stage_result("technical")

        technical.run.side_effect = _run_technical
        decision = MagicMock(agent_name="decision", tool_names=[])

        def _run_decision(run_ctx, progress_callback=None):
            run_ctx.add_opinion(AgentOpinion(
                agent_name="decision",
                signal="buy",
                confidence=0.87,
                reasoning="综合技术与情绪判断，倾向于买入。",
            ))
            return self._stage_result("decision")

        decision.run.side_effect = _run_decision
        times = iter([0.0, 0.2, 0.3, 14.6, 14.7])

        def _next_time():
            return next(times, 100.0)

        with patch.object(orch, "_build_agent_chain", return_value=[technical, decision]):
            with patch("src.agent.orchestrator.time.time", side_effect=_next_time):
                result = orch._execute_pipeline(ctx)

        self.assertTrue(result.success)
        self.assertIsNotNone(result.content)
        self.assertIn("insufficient budget", (result.error or "").lower())
        self.assertEqual(result.total_steps, 1)
        technical.run.assert_called_once()
        decision.run.assert_not_called()

    def test_execute_pipeline_first_stage_still_runs_when_timeout_short(self):
        orch = self._make_orchestrator(config=SimpleNamespace(agent_orchestrator_timeout_s=10))
        ctx = AgentContext(query="test", stock_code="600519", stock_name="贵州茅台")

        technical = MagicMock(agent_name="technical")
        technical.run.side_effect = lambda run_ctx, progress_callback=None: self._stage_result("technical")
        times = iter([0.0, 0.2, 0.3, 0.4, 0.5])

        def _next_time():
            return next(times, 1.0)

        with patch.object(orch, "_build_agent_chain", return_value=[technical]):
            with patch("src.agent.orchestrator.time.time", side_effect=_next_time):
                result = orch._execute_pipeline(ctx)

        self.assertIsNotNone(result.error)
        self.assertEqual(result.total_steps, 1)
        technical.run.assert_called_once()
        self.assertNotIn("insufficient budget", (result.error or "").lower())

    def test_execute_pipeline_times_out_after_stage(self):
        orch = self._make_orchestrator(config=SimpleNamespace(agent_orchestrator_timeout_s=1))
        agent = MagicMock(agent_name="technical")
        agent.run.return_value = self._stage_result("technical")

        with patch.object(orch, "_build_agent_chain", return_value=[agent]):
            with patch("src.agent.orchestrator.time.time", side_effect=[0.0, 0.1, 1.2, 1.2, 1.2, 1.2]):
                result = orch._execute_pipeline(AgentContext(query="test"))

        self.assertFalse(result.success)
        self.assertIn("timed out", result.error)

    def test_execute_pipeline_timeout_after_decision_preserves_dashboard(self):
        orch = self._make_orchestrator(config=SimpleNamespace(agent_orchestrator_timeout_s=1, agent_risk_override=True))
        ctx = AgentContext(query="test", stock_code="600519", stock_name="贵州茅台")
        decision = MagicMock(agent_name="decision")

        def _run_decision(run_ctx, progress_callback=None):
            dashboard = {
                "stock_name": "贵州茅台",
                "decision_type": "strong_buy",
                "sentiment_score": 88,
                "operation_advice": {
                    "no_position": "分批布局",
                    "has_position": "继续持有",
                },
                "analysis_summary": "趋势仍强，回踩可观察。",
                "dashboard": {
                    "key_levels": {
                        "support": 1800,
                        "stop_loss": 1760,
                        "resistance": 1900,
                    }
                },
            }
            run_ctx.set_data("final_dashboard", dashboard)
            run_ctx.add_opinion(AgentOpinion(
                agent_name="decision",
                signal="buy",
                confidence=0.88,
                reasoning="趋势仍强，回踩可观察。",
                raw_data=dashboard,
            ))
            return self._stage_result("decision")

        decision.run.side_effect = _run_decision

        with patch.object(orch, "_build_agent_chain", return_value=[decision]):
            with patch("src.agent.orchestrator.time.time", side_effect=[0.0, 0.1, 1.2, 1.2, 1.2]):
                result = orch._execute_pipeline(ctx, parse_dashboard=True)

        self.assertTrue(result.success)
        self.assertIn("timed out", result.error)
        self.assertEqual(result.dashboard["decision_type"], "buy")
        self.assertEqual(result.dashboard["operation_advice"], "买入")
        self.assertEqual(
            result.dashboard["dashboard"]["battle_plan"]["sniper_points"]["stop_loss"],
            1760.0,
        )

    def test_execute_pipeline_timeout_after_intel_synthesizes_dashboard(self):
        orch = self._make_orchestrator(config=SimpleNamespace(agent_orchestrator_timeout_s=1, agent_risk_override=True))
        ctx = AgentContext(query="test", stock_code="301308", stock_name="江波龙")
        ctx.set_data("realtime_quote", {"price": 326.17, "volume_ratio": 1.0, "turnover_rate": 6.77})
        ctx.set_data("chip_distribution", {"profit_ratio": 68.8, "avg_cost": 307.67, "concentration_90": 15.28})

        technical = MagicMock(agent_name="technical")
        intel = MagicMock(agent_name="intel")

        def _run_technical(run_ctx, progress_callback=None):
            run_ctx.add_opinion(AgentOpinion(
                agent_name="technical",
                signal="buy",
                confidence=0.75,
                reasoning="强势多头排列，价格回踩 MA5。",
                key_levels={"support": 301.61, "resistance": 340.44, "stop_loss": 295.0},
                raw_data={"ma_alignment": "bullish", "trend_score": 73, "volume_status": "normal"},
            ))
            return self._stage_result("technical")

        technical.run.side_effect = _run_technical
        intel.run.return_value = self._stage_result("intel")

        with patch.object(orch, "_build_agent_chain", return_value=[technical, intel]):
            with patch("src.agent.orchestrator.time.time", side_effect=[0.0, 0.1, 0.2, 0.3, 1.2, 1.2, 1.2]):
                result = orch._execute_pipeline(ctx, parse_dashboard=True)

        self.assertTrue(result.success)
        self.assertIn("timed out", result.error)
        self.assertEqual(result.dashboard["decision_type"], "buy")
        self.assertIn("降级结果", result.dashboard["analysis_summary"])
        self.assertEqual(
            result.dashboard["dashboard"]["battle_plan"]["sniper_points"]["stop_loss"],
            295.0,
        )

    def test_run_wraps_orchestrator_result(self):
        from src.agent.orchestrator import OrchestratorResult

        orch = self._make_orchestrator()
        fake_result = OrchestratorResult(success=True, content="done", total_steps=2, total_tokens=11, model="x")
        with patch.object(orch, "_execute_pipeline", return_value=fake_result):
            result = orch.run("Analyze 600519")

        self.assertTrue(result.success)
        self.assertEqual(result.content, "done")
        self.assertEqual(result.total_steps, 2)

    def test_chat_loads_prior_history_into_context(self):
        from src.agent.orchestrator import OrchestratorResult

        orch = self._make_orchestrator()
        history = [
            {"role": "user", "content": "之前的问题"},
            {"role": "assistant", "content": "之前的回答"},
        ]
        captured = {}

        def fake_execute(ctx, parse_dashboard=False, progress_callback=None):
            captured["history"] = ctx.meta.get("conversation_history")
            return OrchestratorResult(success=True, content="assistant reply")

        with patch.object(orch, "_execute_pipeline", side_effect=fake_execute):
            with patch("src.agent.conversation.conversation_manager.get_or_create") as get_or_create:
                get_or_create.return_value.get_history.return_value = history
                with patch("src.agent.conversation.conversation_manager.add_message"):
                    orch.chat("hello", "session-1")

        self.assertEqual(captured["history"], history)

    def test_chat_persists_user_and_assistant_messages(self):
        from src.agent.orchestrator import OrchestratorResult

        orch = self._make_orchestrator()
        fake_result = OrchestratorResult(success=True, content="assistant reply")

        with patch.object(orch, "_execute_pipeline", return_value=fake_result):
            with patch("src.agent.conversation.conversation_manager.add_message") as add_message:
                result = orch.chat("hello", "session-1")

        self.assertTrue(result.success)
        self.assertEqual(add_message.call_count, 2)
        add_message.assert_any_call("session-1", "user", "hello")
        add_message.assert_any_call("session-1", "assistant", "assistant reply")

    def test_chat_persists_failure_message(self):
        from src.agent.orchestrator import OrchestratorResult

        orch = self._make_orchestrator()
        fake_result = OrchestratorResult(success=False, error="boom")

        with patch.object(orch, "_execute_pipeline", return_value=fake_result):
            with patch("src.agent.conversation.conversation_manager.add_message") as add_message:
                result = orch.chat("hello", "session-2")

        self.assertFalse(result.success)
        add_message.assert_any_call("session-2", "assistant", "[分析失败] boom")

    def test_execute_pipeline_fails_when_dashboard_parse_fails(self):
        orch = self._make_orchestrator()
        ctx = AgentContext(query="test", stock_code="600519")
        decision = MagicMock(agent_name="decision")

        def fake_run(pipeline_ctx, progress_callback=None):
            pipeline_ctx.set_data("final_dashboard_raw", "not valid json")
            return self._stage_result("decision")

        decision.run.side_effect = fake_run

        with patch.object(orch, "_build_agent_chain", return_value=[decision]):
            result = orch._execute_pipeline(ctx, parse_dashboard=True)

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Failed to parse dashboard JSON from agent response")

    def test_execute_pipeline_chat_prefers_free_form_response(self):
        orch = self._make_orchestrator()
        ctx = AgentContext(query="请总结一下", stock_code="600519")
        ctx.meta["response_mode"] = "chat"
        decision = MagicMock(agent_name="decision")

        def fake_run(pipeline_ctx, progress_callback=None):
            pipeline_ctx.set_data("final_dashboard", {"decision_type": "buy", "analysis_summary": "json dashboard"})
            pipeline_ctx.set_data("final_response_text", "这是自然语言回复")
            return self._stage_result("decision", raw_text="这是自然语言回复")

        decision.run.side_effect = fake_run

        with patch.object(orch, "_build_agent_chain", return_value=[decision]):
            result = orch._execute_pipeline(ctx, parse_dashboard=False)

        self.assertTrue(result.success)
        self.assertEqual(result.content, "这是自然语言回复")

    def test_strategy_agents_are_selected_after_technical_stage(self):
        orch = self._make_orchestrator()
        orch.mode = "specialist"
        ctx = AgentContext(query="分析600519", stock_code="600519")
        ctx.meta["response_mode"] = "chat"

        technical = MagicMock(agent_name="technical")

        def _run_technical(run_ctx, progress_callback=None):
            run_ctx.add_opinion(AgentOpinion(
                agent_name="technical",
                signal="buy",
                confidence=0.8,
                reasoning="trend ok",
                raw_data={"ma_alignment": "bullish", "trend_score": 78, "volume_status": "normal"},
            ))
            return self._stage_result("technical")

        technical.run.side_effect = _run_technical

        intel = MagicMock(agent_name="intel")
        intel.run.return_value = self._stage_result("intel")

        risk = MagicMock(agent_name="risk")
        risk.run.return_value = self._stage_result("risk")

        strategy = MagicMock(agent_name="strategy_bull_trend")

        def _run_strategy(run_ctx, progress_callback=None):
            run_ctx.add_opinion(AgentOpinion(
                agent_name="strategy_bull_trend",
                signal="buy",
                confidence=0.7,
                reasoning="strategy ok",
            ))
            return self._stage_result("strategy_bull_trend")

        strategy.run.side_effect = _run_strategy

        decision = MagicMock(agent_name="decision")
        decision.run.return_value = self._stage_result("decision", raw_text="final answer")

        def _build_specialist_agents(run_ctx):
            self.assertTrue(any(op.agent_name == "technical" for op in run_ctx.opinions))
            return [strategy]

        with patch.object(orch, "_build_agent_chain", return_value=[technical, intel, risk, decision]):
            with patch.object(orch, "_build_specialist_agents", side_effect=_build_specialist_agents) as build_specialist_agents:
                result = orch._execute_pipeline(ctx, parse_dashboard=False)

        self.assertTrue(result.success)
        self.assertEqual(result.content, "final answer")
        build_specialist_agents.assert_called_once()
        strategy.run.assert_called_once()


class TestDecisionAgentChatMode(unittest.TestCase):
    """Test DecisionAgent chat-mode output path."""

    def test_post_process_stores_free_form_response(self):
        from src.agent.agents.decision_agent import DecisionAgent

        agent = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
        ctx = AgentContext(query="帮我总结一下", stock_code="600519")
        ctx.meta["response_mode"] = "chat"
        ctx.add_opinion(AgentOpinion(agent_name="technical", signal="buy", confidence=0.8, reasoning="趋势偏强"))

        opinion = agent.post_process(ctx, "建议继续观察量价配合，分批参与。")

        self.assertIsNotNone(opinion)
        self.assertEqual(ctx.get_data("final_response_text"), "建议继续观察量价配合，分批参与。")
        self.assertIsNone(ctx.get_data("final_dashboard"))
        self.assertEqual(opinion.signal, "buy")


class TestTechnicalAgentSkillPolicy(unittest.TestCase):
    """TechnicalAgent should only receive the legacy trend baseline for implicit/default runs."""

    def test_prompt_omits_legacy_default_policy_when_explicit_skill_selected(self):
        from src.agent.agents.technical_agent import TechnicalAgent

        agent = TechnicalAgent(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
            skill_instructions="### 技能 1: 缠论",
            technical_skill_policy="",
        )
        prompt = agent.system_prompt(AgentContext(query="分析 600519", stock_code="600519"))

        self.assertNotIn("Bias from MA5 < 2%", prompt)
        self.assertIn("### 技能 1: 缠论", prompt)

    def test_prompt_includes_legacy_default_policy_for_implicit_default_run(self):
        from src.agent.agents.technical_agent import TechnicalAgent
        from src.agent.skills.defaults import TECHNICAL_SKILL_RULES_EN

        agent = TechnicalAgent(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
            skill_instructions="### 技能 1: 默认多头趋势",
            technical_skill_policy=TECHNICAL_SKILL_RULES_EN,
        )
        prompt = agent.system_prompt(AgentContext(query="分析 600519", stock_code="600519"))

        self.assertIn("Bias from MA5 < 2%", prompt)
        self.assertIn("### 技能 1: 默认多头趋势", prompt)


class TestBaseAgentMessageAssembly(unittest.TestCase):
    """Test BaseAgent message assembly helpers."""

    @staticmethod
    def _make_agent():
        from src.agent.agents.base_agent import BaseAgent

        class DummyAgent(BaseAgent):
            agent_name = "dummy"

            def system_prompt(self, ctx: AgentContext) -> str:
                return "system"

            def build_user_message(self, ctx: AgentContext) -> str:
                return "current turn"

        return DummyAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())

    def test_build_messages_includes_conversation_history(self):
        agent = self._make_agent()
        ctx = AgentContext(query="hello")
        ctx.meta["conversation_history"] = [
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
        ]

        messages = agent._build_messages(ctx)

        self.assertEqual(messages[1], {"role": "user", "content": "old question"})
        self.assertEqual(messages[2], {"role": "assistant", "content": "old answer"})
        self.assertEqual(messages[-1], {"role": "user", "content": "current turn"})


# ============================================================
# EventMonitor serialization
# ============================================================

class TestEventMonitor(unittest.TestCase):
    """Test EventMonitor serialize/deserialize round-trip."""

    def test_round_trip(self):
        from src.agent.events import EventMonitor, PriceAlert, PriceChangeAlert, VolumeAlert
        monitor = EventMonitor()
        monitor.add_alert(PriceAlert(stock_code="600519", direction="above", price=1800.0))
        monitor.add_alert(PriceChangeAlert(stock_code="300750", direction="down", change_pct=3.5))
        monitor.add_alert(VolumeAlert(stock_code="000858", multiplier=3.0))

        data = monitor.to_dict_list()
        self.assertEqual(len(data), 3)
        self.assertEqual(data[1]["alert_type"], "price_change_percent")
        self.assertEqual(data[1]["change_pct"], 3.5)

        restored = EventMonitor.from_dict_list(data)
        self.assertEqual(len(restored.rules), 3)
        self.assertEqual(restored.rules[0].stock_code, "600519")
        self.assertEqual(restored.rules[1].stock_code, "300750")
        self.assertEqual(restored.rules[2].stock_code, "000858")

    def test_serialization_contract_keeps_supported_rule_keys_stable(self):
        from src.agent.events import (
            AlertStatus,
            EventMonitor,
            PriceAlert,
            PriceChangeAlert,
            VolumeAlert,
        )

        monitor = EventMonitor()
        monitor.add_alert(PriceAlert(stock_code="600519", direction="above", price=1800.0))
        monitor.add_alert(PriceChangeAlert(stock_code="300750", direction="down", change_pct=3.5))
        monitor.add_alert(VolumeAlert(stock_code="000858", multiplier=3.0))
        monitor.rules[1].status = AlertStatus.TRIGGERED
        monitor.rules[2].status = AlertStatus.EXPIRED

        data = monitor.to_dict_list()

        common_keys = {
            "stock_code",
            "alert_type",
            "description",
            "status",
            "created_at",
            "ttl_hours",
        }
        self.assertEqual(set(data[0]), common_keys | {"direction", "price"})
        self.assertEqual(set(data[1]), common_keys | {"direction", "change_pct"})
        self.assertEqual(set(data[2]), common_keys | {"multiplier"})
        known_status_values = {status.value for status in AlertStatus}
        for entry in data:
            self.assertIn(entry["status"], known_status_values)

        restored = EventMonitor.from_dict_list(data)

        self.assertEqual([rule.status for rule in restored.rules], [
            AlertStatus.ACTIVE,
            AlertStatus.TRIGGERED,
            AlertStatus.EXPIRED,
        ])

    def test_remove_expired(self):
        import time
        from src.agent.events import EventMonitor, PriceAlert
        monitor = EventMonitor()
        alert = PriceAlert(stock_code="600519", direction="above", price=1800.0, ttl_hours=0.0)
        alert.created_at = time.time() - 3600  # 1 hour ago
        monitor.rules.append(alert)
        removed = monitor.remove_expired()
        self.assertEqual(removed, 1)
        self.assertEqual(len(monitor.rules), 0)

    def test_add_alert_rejects_unsupported_rule_type(self):
        from src.agent.events import EventMonitor, SentimentAlert

        monitor = EventMonitor()

        with self.assertRaises(ValueError):
            monitor.add_alert(SentimentAlert(stock_code="600519"))

    def test_from_dict_list_skips_unsupported_placeholder_rule_type(self):
        from src.agent.events import EventMonitor

        data = [
            {"stock_code": "600519", "alert_type": "sentiment_shift"},
            {
                "stock_code": "000858",
                "alert_type": "volume_spike",
                "multiplier": 2.5,
            },
        ]

        monitor = EventMonitor.from_dict_list(data)

        self.assertEqual(len(monitor.rules), 1)
        self.assertEqual(monitor.rules[0].stock_code, "000858")

    def test_from_dict_list_skips_price_change_without_change_pct(self):
        from src.agent.events import EventMonitor

        data = [
            {
                "stock_code": "300750",
                "alert_type": "price_change_percent",
                "direction": "up",
            }
        ]

        monitor = EventMonitor.from_dict_list(data)

        self.assertEqual(monitor.rules, [])


class TestEventMonitorAsync(unittest.IsolatedAsyncioTestCase):
    """Test async EventMonitor checks offload blocking fetches."""

    async def test_check_price_uses_to_thread_and_triggers(self):
        from src.agent.events import EventMonitor, PriceAlert

        monitor = EventMonitor()
        rule = PriceAlert(stock_code="600519", direction="above", price=1800.0)
        quote = SimpleNamespace(price=1810.0)

        with patch("src.agent.events.asyncio.to_thread", new=AsyncMock(return_value=quote)) as to_thread:
            triggered = await monitor._check_price(rule)

        self.assertIsNotNone(triggered)
        self.assertEqual(triggered.rule.stock_code, "600519")
        to_thread.assert_awaited_once()

    async def test_check_price_change_uses_to_thread_and_triggers(self):
        from src.agent.events import EventMonitor, PriceChangeAlert

        monitor = EventMonitor()
        rule = PriceChangeAlert(stock_code="300750", direction="down", change_pct=3.0)
        quote = SimpleNamespace(change_pct=-3.25)

        with patch("src.agent.events.asyncio.to_thread", new=AsyncMock(return_value=quote)) as to_thread:
            triggered = await monitor._check_price_change(rule)

        self.assertIsNotNone(triggered)
        self.assertEqual(triggered.rule.stock_code, "300750")
        self.assertEqual(triggered.current_value, -3.25)
        self.assertIn("current = -3.25%", triggered.message)
        to_thread.assert_awaited_once()

    async def test_check_price_change_accepts_dict_payload_alias(self):
        from src.agent.events import EventMonitor, PriceChangeAlert

        monitor = EventMonitor()
        rule = PriceChangeAlert(stock_code="AAPL", direction="up", change_pct=2.0)

        with patch("src.agent.events.asyncio.to_thread", new=AsyncMock(return_value={"pct_chg": "2.35%"})):
            triggered = await monitor._check_price_change(rule)

        self.assertIsNotNone(triggered)
        self.assertEqual(triggered.current_value, 2.35)

    async def test_realtime_rules_create_fetcher_manager_per_quote_check(self):
        from src.agent.events import EventMonitor, PriceAlert, PriceChangeAlert

        monitor = EventMonitor()
        monitor.add_alert(PriceAlert(stock_code="600519", direction="above", price=1800.0))
        monitor.add_alert(PriceChangeAlert(stock_code="600519", direction="up", change_pct=3.0))
        managers = [MagicMock(), MagicMock()]
        for manager in managers:
            manager.get_realtime_quote.return_value = SimpleNamespace(price=1810.0, change_pct=3.25)

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("data_provider.DataFetcherManager", side_effect=managers) as manager_factory, patch(
            "src.agent.events.asyncio.to_thread", new=_run_inline
        ):
            triggered = await monitor.check_all()

        self.assertEqual(manager_factory.call_count, 2)
        for manager in managers:
            manager.get_realtime_quote.assert_called_once_with("600519")
        self.assertEqual(len(triggered), 2)

    async def test_check_volume_safe_when_fetch_returns_none(self):
        """_check_volume must not crash when get_daily_data returns None."""
        from src.agent.events import EventMonitor, VolumeAlert

        monitor = EventMonitor()
        rule = VolumeAlert(stock_code="600519", multiplier=2.0)

        with patch("src.agent.events.asyncio.to_thread", new=AsyncMock(return_value=None)):
            result = await monitor._check_volume(rule)

        self.assertIsNone(result)

    async def test_check_all_async_callback(self):
        """on_trigger callbacks should be properly awaited if coroutine."""
        from src.agent.events import EventMonitor, PriceAlert

        monitor = EventMonitor()
        rule = PriceAlert(stock_code="600519", direction="above", price=1800.0)
        monitor.add_alert(rule)

        callback_values = []
        async_cb = AsyncMock(side_effect=lambda alert: callback_values.append(alert.rule.stock_code))
        monitor.on_trigger(async_cb)

        quote = SimpleNamespace(price=1810.0)
        with patch("src.agent.events.asyncio.to_thread", new=AsyncMock(return_value=quote)):
            triggered = await monitor.check_all()

        self.assertEqual(len(triggered), 1)
        async_cb.assert_awaited_once()


class TestEventMonitorConfigIntegration(unittest.TestCase):
    """Test config-driven EventMonitor construction."""

    def test_build_event_monitor_from_config(self):
        from src.agent.events import build_event_monitor_from_config

        config = SimpleNamespace(
            agent_event_monitor_enabled=True,
            agent_event_alert_rules_json='[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800}]',
        )

        with patch("src.notification.NotificationService", return_value=MagicMock()):
            monitor = build_event_monitor_from_config(config=config)

        self.assertIsNotNone(monitor)
        self.assertEqual(len(monitor.rules), 1)
        self.assertEqual(monitor.rules[0].stock_code, "600519")

    def test_configured_event_monitor_notification_uses_alert_route(self):
        from src.agent.events import TriggeredAlert, build_event_monitor_from_config

        config = SimpleNamespace(
            agent_event_monitor_enabled=True,
            agent_event_alert_rules_json='[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800}]',
        )
        notifier = MagicMock()
        notifier.send.return_value = True

        monitor = build_event_monitor_from_config(config=config, notifier=notifier)

        self.assertIsNotNone(monitor)
        monitor._callbacks[0](TriggeredAlert(rule=monitor.rules[0], message="hit"))
        notifier.send.assert_called_once()
        self.assertIn("hit", notifier.send.call_args.args[0])
        self.assertEqual(notifier.send.call_args.kwargs["route_type"], "alert")

    def test_build_event_monitor_from_config_accepts_price_change_percent(self):
        from src.agent.events import PriceChangeAlert, build_event_monitor_from_config

        config = SimpleNamespace(
            agent_event_monitor_enabled=True,
            agent_event_alert_rules_json=(
                '[{"stock_code":"300750","alert_type":"price_change_percent",'
                '"direction":"down","change_pct":3.5}]'
            ),
        )

        with patch("src.notification.NotificationService", return_value=MagicMock()):
            monitor = build_event_monitor_from_config(config=config)

        self.assertIsNotNone(monitor)
        self.assertEqual(len(monitor.rules), 1)
        self.assertIsInstance(monitor.rules[0], PriceChangeAlert)
        self.assertEqual(monitor.rules[0].change_pct, 3.5)

    def test_build_event_monitor_returns_none_on_invalid_json(self):
        from src.agent.events import build_event_monitor_from_config

        config = SimpleNamespace(
            agent_event_monitor_enabled=True,
            agent_event_alert_rules_json='[invalid',
        )

        monitor = build_event_monitor_from_config(config=config)
        self.assertIsNone(monitor)

    def test_build_event_monitor_skips_invalid_rule_entries(self):
        from src.agent.events import build_event_monitor_from_config

        config = SimpleNamespace(
            agent_event_monitor_enabled=True,
            agent_event_alert_rules_json=(
                '[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800},'
                '{"stock_code":"000858","alert_type":"price_cross","status":"bad","direction":"above","price":120}]'
            ),
        )

        with patch("src.notification.NotificationService", return_value=MagicMock()):
            monitor = build_event_monitor_from_config(config=config)

        self.assertIsNotNone(monitor)
        self.assertEqual(len(monitor.rules), 1)
        self.assertEqual(monitor.rules[0].stock_code, "600519")

    def test_build_event_monitor_skips_unsupported_rule_types(self):
        from src.agent.events import build_event_monitor_from_config

        config = SimpleNamespace(
            agent_event_monitor_enabled=True,
            agent_event_alert_rules_json=(
                '[{"stock_code":"600519","alert_type":"sentiment_shift"},'
                '{"stock_code":"000858","alert_type":"price_cross","direction":"above","price":120}]'
            ),
        )

        with patch("src.notification.NotificationService", return_value=MagicMock()):
            monitor = build_event_monitor_from_config(config=config)

        self.assertIsNotNone(monitor)
        self.assertEqual(len(monitor.rules), 1)
        self.assertEqual(monitor.rules[0].stock_code, "000858")


# ============================================================
# AgentMemory
# ============================================================

class TestAgentMemory(unittest.TestCase):
    """Test AgentMemory disabled mode."""

    def test_disabled_returns_neutral(self):
        from src.agent.memory import AgentMemory
        mem = AgentMemory(enabled=False)
        cal = mem.get_calibration("technical")
        self.assertFalse(cal.calibrated)
        self.assertAlmostEqual(cal.calibration_factor, 1.0)

    def test_disabled_weights_all_equal(self):
        from src.agent.memory import AgentMemory
        mem = AgentMemory(enabled=False)
        weights = mem.compute_strategy_weights(["a", "b", "c"])
        self.assertEqual(weights, {"a": 1.0, "b": 1.0, "c": 1.0})

    def test_calibrate_confidence_passthrough_when_disabled(self):
        from src.agent.memory import AgentMemory
        mem = AgentMemory(enabled=False)
        self.assertAlmostEqual(mem.calibrate_confidence("tech", 0.75), 0.75)

    def test_get_stock_history_reads_orm_records(self):
        from src.agent.memory import AgentMemory

        record = SimpleNamespace(
            created_at=SimpleNamespace(date=lambda: SimpleNamespace(isoformat=lambda: "2026-03-01")),
            raw_result=json.dumps({"decision_type": "buy", "current_price": 1880.0}),
            sentiment_score=72,
            operation_advice="买入",
        )
        db = MagicMock()
        db.get_analysis_history.return_value = [record]

        with patch("src.storage.get_db", return_value=db):
            mem = AgentMemory(enabled=True)
            history = mem.get_stock_history("600519", limit=1)

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].signal, "buy")
        self.assertEqual(history[0].price_at_analysis, 1880.0)


class TestBaseAgentMemoryIntegration(unittest.TestCase):
    """Test BaseAgent hooks for memory injection and calibration."""

    @staticmethod
    def _make_agent(memory):
        from src.agent.agents.base_agent import BaseAgent

        class DummyAgent(BaseAgent):
            agent_name = "technical"

            def system_prompt(self, ctx):
                return "system"

            def build_user_message(self, ctx):
                return "user"

            def post_process(self, ctx, raw_text):
                return AgentOpinion(agent_name="technical", signal="buy", confidence=0.8, reasoning=raw_text)

        with patch("src.agent.agents.base_agent.AgentMemory.from_config", return_value=memory):
            return DummyAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())

    def test_memory_context_is_injected(self):
        entry = SimpleNamespace(
            date="2026-03-01",
            signal="buy",
            sentiment_score=72,
            price_at_analysis=1880.0,
            outcome_5d=0.03,
            outcome_20d=None,
            was_correct=True,
        )
        memory = MagicMock(enabled=True)
        memory.get_stock_history.return_value = [entry]
        agent = self._make_agent(memory)

        ctx = AgentContext(query="test", stock_code="600519")
        injected = agent._inject_cached_data(ctx)

        self.assertIn("Memory: recent analysis history", injected)
        self.assertIn("signal=buy", injected)

    def test_memory_calibration_updates_confidence(self):
        memory = MagicMock(enabled=True)
        memory.get_stock_history.return_value = []
        memory.get_calibration.return_value = SimpleNamespace(
            calibrated=True,
            calibration_factor=0.5,
            total_samples=40,
        )
        agent = self._make_agent(memory)
        ctx = AgentContext(query="test", stock_code="600519")

        loop_result = SimpleNamespace(
            success=True,
            content='{"signal":"buy","confidence":0.8,"reasoning":"ok"}',
            total_tokens=12,
            tool_calls_log=[],
            models_used=["test/model"],
        )
        with patch("src.agent.agents.base_agent.run_agent_loop", return_value=loop_result):
            result = agent.run(ctx)

        self.assertTrue(result.success)
        self.assertIsNotNone(result.opinion)
        self.assertAlmostEqual(result.opinion.confidence, 0.4)
        self.assertEqual(result.meta["memory_calibration"]["factor"], 0.5)
        memory.calibrate_confidence.assert_not_called()

    def test_strategy_memory_calibration_uses_strategy_factor(self):
        from src.agent.agents.base_agent import BaseAgent

        class DummyStrategyAgent(BaseAgent):
            agent_name = "strategy_chan_theory"

            def system_prompt(self, ctx):
                return "system"

            def build_user_message(self, ctx):
                return "user"

            def post_process(self, ctx, raw_text):
                return AgentOpinion(agent_name=self.agent_name, signal="buy", confidence=0.8, reasoning=raw_text)

        memory = MagicMock(enabled=True)
        memory.get_stock_history.return_value = []
        memory.get_calibration.return_value = SimpleNamespace(
            calibrated=True,
            calibration_factor=0.5,
            total_samples=40,
        )

        with patch("src.agent.agents.base_agent.AgentMemory.from_config", return_value=memory):
            agent = DummyStrategyAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
        ctx = AgentContext(query="test", stock_code="600519")

        loop_result = SimpleNamespace(
            success=True,
            content='{"signal":"buy","confidence":0.8,"reasoning":"ok"}',
            total_tokens=12,
            tool_calls_log=[],
            models_used=["test/model"],
        )
        with patch("src.agent.agents.base_agent.run_agent_loop", return_value=loop_result):
            result = agent.run(ctx)

        self.assertTrue(result.success)
        self.assertAlmostEqual(result.opinion.confidence, 0.4)
        memory.get_calibration.assert_called_once_with(
            agent_name="strategy_chan_theory",
            stock_code="600519",
            skill_id="chan_theory",
        )


class TestRiskOverride(unittest.TestCase):
    """Test orchestrator-level risk override integration."""

    def _make_dashboard(self):
        return {
            "decision_type": "buy",
            "sentiment_score": 76,
            "operation_advice": "买入",
            "analysis_summary": "原始结论",
            "risk_warning": "原风险提示",
            "dashboard": {
                "core_conclusion": {
                    "one_sentence": "可以参与",
                    "signal_type": "🟢买入信号",
                    "position_advice": {
                        "no_position": "分批买入",
                        "has_position": "继续持有",
                    },
                }
            },
        }

    def test_risk_override_vetoes_buy_signal(self):
        from src.agent.orchestrator import AgentOrchestrator

        orch = AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
            config=SimpleNamespace(agent_risk_override=True),
        )
        ctx = AgentContext(query="test", stock_code="600519")
        ctx.set_data("final_dashboard", self._make_dashboard())
        ctx.add_opinion(AgentOpinion(agent_name="decision", signal="buy", confidence=0.8, reasoning="原始结论"))
        ctx.add_opinion(AgentOpinion(
            agent_name="risk",
            signal="strong_sell",
            confidence=0.9,
            reasoning="重大风险",
            raw_data={"veto_buy": True, "reasoning": "存在重大减持风险"},
        ))
        ctx.add_risk_flag("insider", "大股东减持", severity="high")

        orch._apply_risk_override(ctx)
        dashboard = ctx.get_data("final_dashboard")

        self.assertEqual(dashboard["decision_type"], "hold")
        self.assertLessEqual(dashboard["sentiment_score"], 59)
        self.assertIn("风控接管", dashboard["risk_warning"])
        self.assertEqual(ctx.opinions[0].signal, "hold")

    def test_risk_override_normalizes_strong_buy_before_veto(self):
        from src.agent.orchestrator import AgentOrchestrator

        orch = AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
            config=SimpleNamespace(agent_risk_override=True),
        )
        ctx = AgentContext(query="test", stock_code="600519")
        dashboard = self._make_dashboard()
        dashboard["decision_type"] = "strong_buy"
        dashboard["sentiment_score"] = 92
        ctx.set_data("final_dashboard", dashboard)
        ctx.add_opinion(AgentOpinion(agent_name="decision", signal="strong_buy", confidence=0.9, reasoning="原始结论"))
        ctx.add_opinion(AgentOpinion(
            agent_name="risk",
            signal="strong_sell",
            confidence=0.9,
            raw_data={"veto_buy": True, "reasoning": "存在重大风险"},
        ))
        ctx.add_risk_flag("insider", "大股东减持", severity="high")

        orch._apply_risk_override(ctx)

        self.assertEqual(dashboard["decision_type"], "hold")
        self.assertEqual(ctx.opinions[0].signal, "hold")

    def test_risk_override_respects_disable_flag(self):
        from src.agent.orchestrator import AgentOrchestrator

        orch = AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
            config=SimpleNamespace(agent_risk_override=False),
        )
        ctx = AgentContext(query="test", stock_code="600519")
        dashboard = self._make_dashboard()
        ctx.set_data("final_dashboard", dashboard)
        ctx.add_opinion(AgentOpinion(
            agent_name="risk",
            signal="strong_sell",
            confidence=0.9,
            raw_data={"veto_buy": True},
        ))
        ctx.add_risk_flag("insider", "大股东减持", severity="high")

        orch._apply_risk_override(ctx)

        self.assertEqual(dashboard["decision_type"], "buy")


# ============================================================
# ResearchCommand timeout guard
# ============================================================

class TestResearchCommandTimeout(unittest.TestCase):
    """Verify that ResearchCommand respects the configured timeout."""

    def test_research_timeout_returns_timeout_response(self):
        """Timed-out research results should surface the timeout response text."""
        from bot.commands.research import ResearchCommand
        from bot.models import BotMessage

        cmd = ResearchCommand()

        msg = MagicMock(spec=BotMessage)
        msg.platform = "test"
        msg.user_id = "u1"

        config = SimpleNamespace(
            agent_deep_research_budget=30000,
            agent_deep_research_timeout=0.01,  # 10ms — will trigger timeout
            litellm_model="test-model",
            agent_mode=True,
        )

        with patch("bot.commands.research.get_config", return_value=config), \
             patch("src.agent.factory.get_tool_registry", return_value=MagicMock()), \
             patch("src.agent.llm_adapter.LLMToolAdapter", return_value=MagicMock()), \
             patch("src.agent.research.ResearchAgent.research", return_value=SimpleNamespace(
                 success=False,
                 report="",
                 sub_questions=["q"],
                 findings_count=1,
                 total_tokens=100,
                 duration_s=0.01,
                 error="Deep research timed out after 0.01s",
                 timed_out=True,
             )):
            response = cmd.execute(msg, ["600519"])

        self.assertIn("超时", response.text)

    def test_research_recognizes_five_letter_us_ticker(self):
        from bot.commands.research import ResearchCommand
        from bot.models import BotMessage

        cmd = ResearchCommand()
        msg = MagicMock(spec=BotMessage)
        msg.platform = "test"
        msg.user_id = "u1"

        result = SimpleNamespace(
            success=True,
            report="ok",
            sub_questions=["q"],
            findings_count=1,
            total_tokens=100,
            duration_s=1.0,
            error=None,
            timed_out=False,
        )
        captured = {}

        def _capture_research(query, context=None, timeout_seconds=None):
            captured["query"] = query
            captured["context"] = context
            captured["timeout_seconds"] = timeout_seconds
            return result

        config = SimpleNamespace(
            agent_deep_research_budget=30000,
            agent_deep_research_timeout=1,
            litellm_model="test-model",
            agent_mode=True,
        )

        with patch("bot.commands.research.get_config", return_value=config), \
             patch("src.agent.factory.get_tool_registry", return_value=MagicMock()), \
             patch("src.agent.llm_adapter.LLMToolAdapter", return_value=MagicMock()), \
             patch("src.agent.research.ResearchAgent.research", side_effect=_capture_research):
            response = cmd.execute(msg, ["googl", "风险"])

        self.assertIn("Deep Research Report", response.text)
        self.assertEqual(captured["context"], {"stock_code": "GOOGL", "stock_name": ""})
        self.assertEqual(captured["timeout_seconds"], 1)
        self.assertTrue(captured["query"].startswith("[Stock: GOOGL]"))


# ============================================================
# ResearchAgent filtered registry & API endpoint
# ============================================================

class TestResearchAgentFilteredRegistry(unittest.TestCase):
    """Test that ResearchAgent._filtered_registry delegates to BaseAgent's implementation."""

    def test_filtered_registry_delegates_to_base(self):
        from src.agent.research import ResearchAgent
        from src.agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        fake_tool = MagicMock()
        fake_tool.name = "search_stock_news"
        registry.register(fake_tool)

        llm_adapter = MagicMock()
        agent = ResearchAgent(tool_registry=registry, llm_adapter=llm_adapter)

        filtered = agent._filtered_registry()
        self.assertIsInstance(filtered, ToolRegistry)
        self.assertIsNotNone(filtered.get("search_stock_news"))

    def test_decompose_query_uses_shared_adapter(self):
        from src.agent.research import ResearchAgent

        llm_adapter = MagicMock()
        llm_adapter.call_text.return_value = SimpleNamespace(
            provider="gemini",
            content='{"questions":["Q1","Q2"]}',
            usage={"total_tokens": 42},
        )
        agent = ResearchAgent(tool_registry=MagicMock(), llm_adapter=llm_adapter)

        result = agent._decompose_query("分析 600519", {"stock_code": "600519"})

        self.assertEqual(result["questions"], ["Q1", "Q2"])
        llm_adapter.call_text.assert_called_once()

    def test_synthesise_report_uses_shared_adapter(self):
        from src.agent.research import ResearchAgent

        llm_adapter = MagicMock()
        llm_adapter.call_text.return_value = SimpleNamespace(
            provider="gemini",
            content="Final research report",
            usage={"total_tokens": 88},
        )
        agent = ResearchAgent(tool_registry=MagicMock(), llm_adapter=llm_adapter)

        result = agent._synthesise_report(
            "分析 600519",
            [{"question": "Q1", "content": "A1"}],
            {"stock_code": "600519"},
        )

        self.assertEqual(result["content"], "Final research report")
        llm_adapter.call_text.assert_called_once()

    def test_research_marks_synthesis_fallback_as_failure(self):
        from src.agent.research import ResearchAgent

        agent = ResearchAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
        with patch.object(agent, "_decompose_query", return_value={"questions": ["Q1"], "tokens": 3}), \
             patch.object(agent, "_research_sub_question", return_value={"summary": "done", "tokens": 7}), \
             patch.object(agent, "_synthesise_report", return_value={"content": "fallback", "tokens": 5, "error": "boom"}):
            result = agent.research("分析 600519")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "boom")

    def test_research_sub_question_marks_budget_guard_as_timeout(self):
        from src.agent.research import ResearchAgent

        agent = ResearchAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
        with patch("src.agent.research.run_agent_loop", return_value=SimpleNamespace(
            success=False,
            content="",
            total_tokens=7,
            error="Agent step skipped due to insufficient budget: 3.0s remaining, minimum 8.0s required",
        )):
            result = agent._research_sub_question(
                "Q1",
                {},
                0,
                timeout_seconds=10,
            )

        self.assertFalse(result["success"])
        self.assertTrue(result["timed_out"])
        self.assertIn("insufficient budget", (result["error"] or "").lower())
        self.assertEqual(result["tokens"], 7)

    def test_research_returns_timeout_result_when_overall_deadline_is_exceeded(self):
        import time as _time
        from src.agent.research import ResearchAgent

        agent = ResearchAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())

        def _slow_sub_question(*args, **kwargs):
            _time.sleep(0.02)
            return {"question": "Q1", "content": "done", "tokens": 7, "success": True}

        with patch.object(agent, "_decompose_query", return_value={"questions": ["Q1"], "tokens": 3}), \
             patch.object(agent, "_research_sub_question", side_effect=_slow_sub_question):
            result = agent.research("分析 600519", timeout_seconds=0.01)

        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)
        self.assertIn("timed out", result.error)


class TestAgentResearchEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_agent_research_returns_timeout_response(self):
        from api.v1.endpoints.agent import ResearchRequest, agent_research

        config = SimpleNamespace(
            litellm_model="gemini/test-model",
            agent_deep_research_budget=30000,
            agent_deep_research_timeout=1,
            is_agent_available=lambda: True,
        )

        research_result = AsyncMock(return_value=SimpleNamespace(
            success=False,
            report="",
            sub_questions=[],
            findings_count=0,
            total_tokens=0,
            duration_s=1.0,
            error="Deep research timed out after 1s",
            timed_out=True,
        ))

        with (
            patch("api.v1.endpoints.agent.get_config", return_value=config),
            patch("api.v1.endpoints.agent._run_research_in_background", new=research_result),
            patch("src.agent.factory.get_tool_registry", return_value=MagicMock()),
            patch("src.agent.llm_adapter.LLMToolAdapter", return_value=MagicMock()),
        ):
            response = await agent_research(ResearchRequest(question="600519 风险"))

        self.assertFalse(response.success)
        self.assertIn("timed out", response.error)


if __name__ == '__main__':
    unittest.main()
