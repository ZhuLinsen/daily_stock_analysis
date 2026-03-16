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
# StrategyRouter
# ============================================================

class TestStrategyRouter(unittest.TestCase):
    """Test StrategyRouter selection logic."""

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

    @patch("src.agent.strategies.router.StrategyRouter._get_routing_mode", return_value="manual")
    @patch("src.agent.strategies.router.StrategyRouter._get_available_ids", return_value={"chan_theory", "wave_theory"})
    @patch("src.config.get_config", return_value=SimpleNamespace(agent_skills=["chan_theory", "wave_theory"]))
    def test_manual_mode_uses_configured_agent_skills(self, _mock_config, _mock_available, _mock):
        from src.agent.strategies.router import StrategyRouter
        router = StrategyRouter()
        ctx = AgentContext()
        result = router.select_strategies(ctx)
        self.assertEqual(result, ["chan_theory", "wave_theory"])

    @patch("src.agent.strategies.router.StrategyRouter._get_routing_mode", return_value="manual")
    @patch("src.agent.strategies.router.StrategyRouter._get_available_ids", return_value={"bull_trend", "shrink_pullback"})
    @patch("src.config.get_config", return_value=SimpleNamespace(agent_skills=[]))
    def test_manual_mode_falls_back_to_defaults_when_no_skills_configured(self, _mock_config, _mock_available, _mock):
        from src.agent.strategies.router import StrategyRouter, _DEFAULT_STRATEGIES
        router = StrategyRouter()
        ctx = AgentContext()
        result = router.select_strategies(ctx)
        self.assertEqual(result, _DEFAULT_STRATEGIES[:3])

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
        self.assertEqual(result.agent_name, "strategy_consensus")
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
        orch = self._make_orchestrator("full")
        orch.max_steps = 9
        ctx = AgentContext(query="test", stock_code="600519")
        chain = orch._build_agent_chain(ctx)
        self.assertTrue(chain)
        self.assertTrue(all(agent.max_steps == 9 for agent in chain))

    def test_build_context_from_dict(self):
        orch = self._make_orchestrator()
        ctx = orch._build_context(
            "Analyze 600519",
            context={"stock_code": "600519", "stock_name": "贵州茅台", "strategies": ["bull_trend"]},
        )
        self.assertEqual(ctx.stock_code, "600519")
        self.assertEqual(ctx.stock_name, "贵州茅台")
        self.assertEqual(ctx.meta["strategies_requested"], ["bull_trend"])

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
        orch.mode = "strategy"
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

        def _build_strategy_agents(run_ctx):
            self.assertTrue(any(op.agent_name == "technical" for op in run_ctx.opinions))
            return [strategy]

        with patch.object(orch, "_build_agent_chain", return_value=[technical, intel, risk, decision]):
            with patch.object(orch, "_build_strategy_agents", side_effect=_build_strategy_agents) as build_strategy_agents:
                result = orch._execute_pipeline(ctx, parse_dashboard=False)

        self.assertTrue(result.success)
        self.assertEqual(result.content, "final answer")
        build_strategy_agents.assert_called_once()
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
            strategy_id="chan_theory",
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


if __name__ == '__main__':
    unittest.main()
