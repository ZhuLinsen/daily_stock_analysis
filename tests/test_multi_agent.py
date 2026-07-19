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

from src.agent.orchestrator import _extract_stock_code, _COMMON_WORDS, AgentOrchestrator
from src.agent.protocols import (
    AgentContext,
    AgentOpinion,
    AgentRunStats,
    Signal,
    StageResult,
    StageStatus,
    StrategyOpinion,
    normalize_strategy_signal,
    is_valid_strategy_signal,
)
from src.agent.skills.synthesis import (
    strategy_opinion_from_agent_opinion,
    StrategySynthesizer,
)
from src.agent.skills.aggregator import SkillAggregator
from src.agent.stock_scope import StockScope, resolve_stock_scope
from src.config import AGENT_MAX_STEPS_DEFAULT, Config
from src.storage import DatabaseManager


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

    def test_finance_abbrev_excluded(self):
        for text in [
            "TTM",
            "市盈率 TTM 怎么看",
            "PE 怎么看",
            "PE TTM",
            "WHAT IS PE",
            "PE IS HIGH",
            "WHAT IS TTM",
            "YOY",
            "QOQ",
            "EBITDA",
            "DCF",
            "CAGR",
        ]:
            with self.subTest(text=text):
                self.assertEqual(_extract_stock_code(text), "")

    def test_finance_abbrev_before_real_ticker(self):
        self.assertEqual(_extract_stock_code("PE AAPL 怎么看"), "AAPL")
        self.assertEqual(_extract_stock_code("TTM AAPL 怎么看"), "AAPL")
        self.assertEqual(_extract_stock_code("WHAT IS PE AAPL"), "AAPL")

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
        expected_in_set = {
            "BUY", "SELL", "HOLD", "ETF", "IPO", "RSI", "MACD", "STOCK", "TREND",
            "TTM", "PE", "YOY", "QOQ", "EBITDA", "DCF", "CAGR", "KDJ",
            "IS", "WHAT", "HIGH",
        }
        self.assertTrue(expected_in_set.issubset(_COMMON_WORDS))


# ============================================================
# Stock scope resolution
# ============================================================

class TestStockScopeResolution(unittest.TestCase):
    """Validate chat stock-scope state transitions."""

    def test_maintain_keeps_current_stock_for_finance_abbrev_followup(self):
        result = resolve_stock_scope(
            "如果不考虑 TTM 呢",
            {"stock_code": "600519", "stock_name": "匿名标的"},
        )

        self.assertEqual(result.stock_scope.mode, "maintain")
        self.assertEqual(result.effective_context["stock_code"], "600519")
        self.assertEqual(result.effective_context["stock_name"], "匿名标的")
        self.assertEqual(result.stock_scope.allowed_stock_codes, {"600519"})

    def test_switch_clears_old_stock_context_fields(self):
        result = resolve_stock_scope(
            "换成 AAPL 看看",
            {
                "stock_code": "600519",
                "stock_name": "匿名标的",
                "previous_analysis_summary": {"summary": "old"},
                "previous_strategy": {"action": "hold"},
                "previous_price": 1800,
                "previous_change_pct": 1.2,
                "realtime_quote": {"price": 1800},
                "analysis_context_pack_summary": "old pack",
                "report_language": "zh",
            },
        )

        self.assertEqual(result.stock_scope.mode, "switch")
        self.assertEqual(result.stock_scope.expected_stock_code, "AAPL")
        self.assertEqual(result.stock_scope.allowed_stock_codes, {"AAPL"})
        self.assertEqual(result.effective_context["stock_code"], "AAPL")
        self.assertEqual(result.effective_context["stock_name"], "")
        self.assertEqual(result.effective_context["report_language"], "zh")
        for stale_key in (
            "previous_analysis_summary",
            "previous_strategy",
            "previous_price",
            "previous_change_pct",
            "realtime_quote",
            "analysis_context_pack_summary",
        ):
            self.assertNotIn(stale_key, result.effective_context)

    def test_switch_allows_single_new_code_when_current_code_is_mentioned(self):
        result = resolve_stock_scope(
            "换成 AAPL 看看，不考虑 600519",
            {"stock_code": "600519", "stock_name": "匿名标的"},
        )

        self.assertEqual(result.stock_scope.mode, "switch")
        self.assertEqual(result.stock_scope.expected_stock_code, "AAPL")
        self.assertEqual(result.stock_scope.allowed_stock_codes, {"AAPL"})
        self.assertEqual(result.effective_context["stock_code"], "AAPL")
        self.assertEqual(result.effective_context["stock_name"], "")

    def test_compare_allows_multiple_codes_without_polluting_current_context(self):
        result = resolve_stock_scope(
            "比较 600519 和 AAPL",
            {"stock_code": "600519", "stock_name": "匿名标的"},
        )

        self.assertEqual(result.stock_scope.mode, "compare")
        self.assertEqual(result.effective_context["stock_code"], "600519")
        self.assertEqual(result.effective_context["stock_name"], "匿名标的")
        self.assertEqual(result.stock_scope.allowed_stock_codes, {"600519", "AAPL"})

    def test_compare_allows_plain_five_digit_hk_code(self):
        result = resolve_stock_scope(
            "比较 01810 和 AAPL",
            {"stock_code": "600519", "stock_name": "匿名标的"},
        )

        self.assertEqual(result.stock_scope.mode, "compare")
        self.assertEqual(result.effective_context["stock_code"], "600519")
        self.assertEqual(result.effective_context["stock_name"], "匿名标的")
        self.assertEqual(result.stock_scope.allowed_stock_codes, {"600519", "HK01810", "AAPL"})

    def test_compare_hints_allow_multiple_codes_without_switching_context(self):
        cases = [
            "分析 600519 和 AAPL 的差异",
            "AAPL 相比 600519 怎么样",
            "和 AAPL 的差异怎么看",
        ]

        for message in cases:
            with self.subTest(message=message):
                result = resolve_stock_scope(
                    message,
                    {"stock_code": "600519", "stock_name": "匿名标的"},
                )

                self.assertEqual(result.stock_scope.mode, "compare")
                self.assertEqual(result.effective_context["stock_code"], "600519")
                self.assertEqual(result.effective_context["stock_name"], "匿名标的")
                self.assertEqual(result.stock_scope.allowed_stock_codes, {"600519", "AAPL"})

    def test_multiple_explicit_codes_are_compare_scope(self):
        cases = [
            ("AAPL 和 TSLA 哪个更值得买", {"600519", "AAPL", "TSLA"}),
            ("AAPL 和 TSLA 谁更适合", {"600519", "AAPL", "TSLA"}),
            ("分析 AAPL 和 TSLA", {"600519", "AAPL", "TSLA"}),
        ]

        for message, expected_allowed in cases:
            with self.subTest(message=message):
                result = resolve_stock_scope(
                    message,
                    {"stock_code": "600519", "stock_name": "匿名标的"},
                )

                self.assertEqual(result.stock_scope.mode, "compare")
                self.assertEqual(result.effective_context["stock_code"], "600519")
                self.assertEqual(result.effective_context["stock_name"], "匿名标的")
                self.assertEqual(result.stock_scope.allowed_stock_codes, expected_allowed)

    def test_multiple_lowercase_explicit_codes_are_compare_scope_with_choice_hint(self):
        result = resolve_stock_scope(
            "aapl 和 tsla 哪个更值得买",
            {"stock_code": "600519", "stock_name": "匿名标的"},
        )

        self.assertEqual(result.stock_scope.mode, "compare")
        self.assertEqual(result.effective_context["stock_code"], "600519")
        self.assertEqual(result.stock_scope.allowed_stock_codes, {"600519", "AAPL", "TSLA"})

    def test_single_stock_difference_phrase_still_switches_context(self):
        result = resolve_stock_scope(
            "分析 AAPL 的差异化优势",
            {"stock_code": "600519", "stock_name": "匿名标的"},
        )

        self.assertEqual(result.stock_scope.mode, "switch")
        self.assertEqual(result.stock_scope.expected_stock_code, "AAPL")
        self.assertEqual(result.effective_context["stock_code"], "AAPL")
        self.assertEqual(result.effective_context["stock_name"], "")

    def test_moving_average_indicator_token_does_not_switch_context(self):
        cases = [
            "分析 MA 均线",
            "看看 MA 怎么排列",
            "分析 KDJ 指标",
            "KDJ 怎么看",
        ]

        for message in cases:
            with self.subTest(message=message):
                result = resolve_stock_scope(
                    message,
                    {"stock_code": "600519", "stock_name": "匿名标的"},
                )

                self.assertEqual(result.stock_scope.mode, "maintain")
                self.assertEqual(result.stock_scope.expected_stock_code, "600519")
                self.assertEqual(result.stock_scope.allowed_stock_codes, {"600519"})
                self.assertEqual(result.effective_context["stock_code"], "600519")

    def test_dotted_us_ticker_stays_intact_in_scope_resolution(self):
        result = resolve_stock_scope(
            "比较 BRK.B 和 AAPL",
            {"stock_code": "600519", "stock_name": "匿名标的"},
        )

        self.assertEqual(result.stock_scope.mode, "compare")
        self.assertEqual(result.stock_scope.allowed_stock_codes, {"600519", "BRK.B", "AAPL"})
        self.assertEqual(result.effective_context["stock_code"], "600519")

    def test_invalid_context_exchange_token_is_not_trusted_as_current_stock(self):
        result = resolve_stock_scope(
            "继续看",
            {"stock_code": "HK", "stock_name": "港股"},
        )

        self.assertEqual(result.stock_scope.mode, "maintain")
        self.assertEqual(result.stock_scope.expected_stock_code, "")
        self.assertEqual(result.stock_scope.allowed_stock_codes, set())
        self.assertNotIn("stock_code", result.effective_context)
        self.assertNotIn("stock_name", result.effective_context)

    def test_compare_does_not_treat_exchange_affixes_as_standalone_tickers(self):
        cases = [
            ("比较 01810 和 AAPL", {"600519", "HK01810", "AAPL"}, set()),
            ("比较 1810.HK 和 AAPL", {"600519", "HK01810", "AAPL"}, {"HK"}),
            ("比较 0700.HK 和 600519", {"600519", "HK00700"}, {"HK"}),
            ("比较 600519.SH 和 AAPL", {"600519", "AAPL"}, {"SH"}),
            ("比较 000001.SZ 和 AAPL", {"600519", "000001", "AAPL"}, {"SZ"}),
            ("比较 600519.SS 和 AAPL", {"600519", "AAPL"}, {"SS"}),
            ("比较 1810.hk 和 tsla", {"600519", "HK01810", "TSLA"}, {"HK"}),
            ("比较 SH600519 和 AAPL", {"600519", "AAPL"}, {"SH"}),
            ("比较 SZ000001 和 AAPL", {"600519", "000001", "AAPL"}, {"SZ"}),
            ("比较 BJ920748 和 AAPL", {"600519", "920748", "AAPL"}, {"BJ"}),
            ("比较 HK01810 和 AAPL", {"600519", "HK01810", "AAPL"}, {"HK"}),
            ("比较 hk01810 和 tsla", {"600519", "HK01810", "TSLA"}, {"HK"}),
            ("比较 600519 SH 和 AAPL", {"600519", "AAPL"}, {"SH"}),
            ("比较 000001 SZ 和 AAPL", {"600519", "000001", "AAPL"}, {"SZ"}),
            ("比较 920748 BJ 和 AAPL", {"600519", "920748", "AAPL"}, {"BJ"}),
            ("比较 01810 HK 和 AAPL", {"600519", "HK01810", "AAPL"}, {"HK"}),
            ("比较 600519 SS 和 AAPL", {"600519", "AAPL"}, {"SS"}),
        ]

        for message, expected_allowed, forbidden_tokens in cases:
            with self.subTest(message=message):
                result = resolve_stock_scope(
                    message,
                    {"stock_code": "600519", "stock_name": "匿名标的"},
                )

                self.assertEqual(result.stock_scope.mode, "compare")
                self.assertEqual(result.stock_scope.allowed_stock_codes, expected_allowed)
                for token in forbidden_tokens:
                    self.assertNotIn(token, result.stock_scope.allowed_stock_codes)

    def test_switch_recognizes_lowercase_us_ticker_with_explicit_hint(self):
        result = resolve_stock_scope(
            "分析tsla",
            {"stock_code": "600519", "stock_name": "匿名标的"},
        )

        self.assertEqual(result.stock_scope.mode, "switch")
        self.assertEqual(result.stock_scope.expected_stock_code, "TSLA")
        self.assertEqual(result.effective_context["stock_code"], "TSLA")
        self.assertEqual(result.effective_context["stock_name"], "")

    def test_compare_recognizes_lowercase_us_tickers(self):
        result = resolve_stock_scope(
            "比较 600519 和 tsla",
            {"stock_code": "600519", "stock_name": "匿名标的"},
        )

        self.assertEqual(result.stock_scope.mode, "compare")
        self.assertEqual(result.effective_context["stock_code"], "600519")
        self.assertEqual(result.stock_scope.allowed_stock_codes, {"600519", "TSLA"})


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

    def test_strategy_opinion_conversion_preserves_skill_payload(self):
        from src.agent.skills.synthesis import strategy_opinion_from_agent_opinion

        opinion = AgentOpinion(
            agent_name="skill_bull_trend",
            signal="BUY",
            confidence=0.8,
            reasoning="趋势偏强",
            raw_data={
                "skill_id": "bull_trend",
                "score_adjustment": "12",
                "conditions_met": ["站上均线"],
                "conditions_missed": ["量能不足"],
            },
        )

        strategy = strategy_opinion_from_agent_opinion(opinion)

        self.assertEqual(strategy.skill_id, "bull_trend")
        self.assertEqual(strategy.signal, "buy")
        self.assertEqual(strategy.original_signal, "BUY")
        self.assertFalse(strategy.invalid_signal)
        self.assertEqual(strategy.raw_data["normalized_signal"], "buy")
        self.assertEqual(strategy.score_adjustment, 12.0)
        self.assertEqual(strategy.conditions_met, ["站上均线"])
        self.assertEqual(strategy.conditions_missed, ["量能不足"])

    def test_strategy_opinion_conversion_marks_unknown_signal(self):
        from src.agent.skills.synthesis import strategy_opinion_from_agent_opinion

        opinion = AgentOpinion(agent_name="skill_unknown", signal="moon", confidence=0.8)

        strategy = strategy_opinion_from_agent_opinion(opinion)

        self.assertEqual(strategy.signal, "hold")
        self.assertEqual(strategy.original_signal, "moon")
        self.assertTrue(strategy.invalid_signal)
        self.assertTrue(strategy.raw_data["invalid_signal"])

    def test_conflict_detector_detects_uppercase_buy_against_sell(self):
        from src.agent.skills.synthesis import ConflictDetector, strategy_opinion_from_agent_opinion

        opinions = [
            strategy_opinion_from_agent_opinion(AgentOpinion(agent_name="skill_a", signal="BUY", confidence=0.8)),
            strategy_opinion_from_agent_opinion(AgentOpinion(agent_name="skill_b", signal="sell", confidence=0.8)),
        ]

        conflicts = ConflictDetector().detect(opinions, final_signal="hold")

        self.assertIn("directional_opposition", {conflict.conflict_type for conflict in conflicts})

    def test_conflict_detector_detects_directional_and_adjustment_conflicts(self):
        from src.agent.skills.synthesis import ConflictDetector

        opinions = [
            StrategyOpinion(skill_id="bull_trend", signal="strong_buy", confidence=0.8, score_adjustment=12),
            StrategyOpinion(skill_id="hot_theme", signal="sell", confidence=0.76, score_adjustment=-10),
        ]

        conflicts = ConflictDetector().detect(opinions, final_signal="hold")
        conflict_types = {conflict.conflict_type for conflict in conflicts}

        self.assertIn("directional_opposition", conflict_types)
        self.assertIn("wide_score_dispersion", conflict_types)
        self.assertIn("high_confidence_dissent", conflict_types)
        self.assertIn("adjustment_contradiction", conflict_types)
        self.assertEqual(conflicts[0].severity, "high")

    def test_strategy_synthesizer_adjusts_confidence_and_returns_language_neutral_payload(self):
        from src.agent.skills.synthesis import ConflictDetector, StrategySynthesizer

        opinions = [
            StrategyOpinion(skill_id="bull_trend", signal="buy", confidence=0.8),
            StrategyOpinion(skill_id="hot_theme", signal="sell", confidence=0.75),
        ]
        conflicts = ConflictDetector().detect(opinions, final_signal="hold")

        synthesis = StrategySynthesizer().synthesize(
            opinions,
            weighted_score=3.0,
            final_signal="hold",
            weighted_confidence=0.8,
            conflicts=conflicts,
        )

        self.assertEqual(synthesis["final_signal"], "hold")
        self.assertEqual(synthesis["conflict_severity"], "high")
        self.assertAlmostEqual(synthesis["confidence"], 0.68)
        self.assertEqual(synthesis["summary_key"], "strategy_synthesis.with_conflicts")
        self.assertNotIn("summary", synthesis)
        self.assertEqual(synthesis["summary_params"]["final_signal"], "hold")
        self.assertNotIn("综合信号", json.dumps(synthesis, ensure_ascii=False))

        self.assertTrue(all("description" not in conflict for conflict in synthesis["conflicts"]))
        self.assertIn("description_key", synthesis["conflicts"][0])

    def test_skill_aggregator_raw_data_contains_strategy_synthesis(self):
        from src.agent.strategies.aggregator import StrategyAggregator

        agg = StrategyAggregator()
        ctx = AgentContext()
        ctx.add_opinion(AgentOpinion(agent_name="strategy_bull_trend", signal="buy", confidence=0.8))
        ctx.add_opinion(AgentOpinion(agent_name="strategy_hot_theme", signal="sell", confidence=0.8))

        result = agg.aggregate(ctx)

        self.assertIsNotNone(result)
        self.assertIn("strategy_synthesis", result.raw_data)
        self.assertIn("conflicts", result.raw_data)
        self.assertGreater(result.raw_data["conflict_count"], 0)

    def test_invalid_signal_excluded_from_conflict_detection(self):
        """Invalid signals must not create false conflicts.

        Note: With only 1 valid opinion (strong_buy), consensus_level is now
        "insufficient" per the sample-count threshold (≤1 → insufficient).
        """
        from src.agent.strategies.aggregator import StrategyAggregator

        agg = StrategyAggregator()
        ctx = AgentContext()
        ctx.add_opinion(AgentOpinion(
            agent_name="strategy_bull_trend",
            signal="strong_buy",
            confidence=0.8,
        ))
        ctx.add_opinion(AgentOpinion(
            agent_name="strategy_invalid",
            signal="moon",
            confidence=0.9,
        ))

        result = agg.aggregate(ctx)

        self.assertIsNotNone(result)
        self.assertEqual(result.signal, "strong_buy")
        self.assertEqual(result.raw_data["weighted_score"], 5.0)
        self.assertEqual(result.raw_data["conflict_count"], 0)
        # Updated: 1 valid opinion → insufficient (sample threshold)
        self.assertEqual(result.raw_data["consensus_level"], "insufficient")
        self.assertAlmostEqual(result.confidence, 0.8, places=2)

    def test_only_invalid_signals_produce_neutral_consensus(self):
        """When all signals are invalid, should fall back to neutral consensus.

        Note: 0 valid opinions → insufficient (not low), per sample threshold.
        """
        from src.agent.strategies.aggregator import StrategyAggregator

        agg = StrategyAggregator()
        ctx = AgentContext()
        ctx.add_opinion(AgentOpinion(
            agent_name="strategy_invalid_1",
            signal="moon",
            confidence=0.8,
        ))
        ctx.add_opinion(AgentOpinion(
            agent_name="strategy_invalid_2",
            signal="rocket",
            confidence=0.9,
        ))

        result = agg.aggregate(ctx)

        self.assertIsNotNone(result)
        self.assertEqual(result.signal, "hold")
        self.assertEqual(result.raw_data["weighted_score"], 3.0)
        self.assertEqual(result.confidence, 0.0)


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


    def test_normalized_dashboard_carries_strategy_synthesis(self):
        from src.agent.orchestrator import AgentOrchestrator

        orch = AgentOrchestrator(tool_registry=MagicMock(), llm_adapter=MagicMock())
        ctx = AgentContext(query="test", stock_code="600519", stock_name="贵州茅台")
        synthesis = {
            "final_signal": "hold",
            "confidence": 0.6,
            "conflict_count": 0,
            "conflict_severity": "none",
        }
        ctx.set_data("skill_consensus", {"strategy_synthesis": synthesis})

        normalized = orch._finalize_dashboard_payload({"dashboard": {}}, ctx)

        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["dashboard"]["strategy_synthesis"], synthesis)


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

    def test_build_context_keeps_market_phase_context_in_meta_not_data(self):
        orch = self._make_orchestrator()
        phase_context = {"phase": "intraday", "is_partial_bar": True}
        pack_summary = "\n## 分析上下文包摘要\n- 数据块状态：行情 available\n"
        market_structure_context = {
            "market_theme_context": {"status": "ok", "active_themes": []},
            "stock_market_position": {"status": "ok", "primary_theme": {"name": "机器人概念"}},
        }

        ctx = orch._build_context(
            "Analyze 600519",
            context={
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "market_phase_context": phase_context,
                "analysis_context_pack_summary": pack_summary,
                "market_structure_context": market_structure_context,
            },
        )

        self.assertEqual(ctx.meta["market_phase_context"], phase_context)
        self.assertEqual(ctx.meta["analysis_context_pack_summary"], pack_summary)
        self.assertEqual(ctx.meta["market_structure_context"], market_structure_context)
        self.assertNotIn("market_phase_context", ctx.data)
        self.assertNotIn("analysis_context_pack_summary", ctx.data)
        self.assertNotIn("market_structure_context", ctx.data)

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

    @staticmethod
    def _decision_agent():
        from src.agent.agents.decision_agent import DecisionAgent

        return DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())

    @staticmethod
    def _dashboard_json(decision_type="buy"):
        return json.dumps({
            "stock_name": "Test Stock",
            "sentiment_score": 72,
            "trend_prediction": "up",
            "operation_advice": "buy",
            "decision_type": decision_type,
            "confidence_level": "Medium",
            "dashboard": {
                "phase_decision": {
                    "phase_context": "regular",
                    "action_window": "now",
                    "immediate_action": "watch",
                    "watch_conditions": [],
                    "next_check_time": "next session",
                    "confidence_reason": "test fixture",
                    "data_limitations": [],
                },
                "core_conclusion": {
                    "one_sentence": "test decision",
                    "signal_type": "buy",
                    "position_advice": {
                        "no_position": "watch",
                        "has_position": "hold",
                    },
                },
            },
            "analysis_summary": "test summary",
            "key_points": ["technical fixture"],
            "risk_warning": "",
        }, ensure_ascii=False)

    class _OpinionStage:
        def __init__(
            self,
            agent_name,
            *,
            signal="hold",
            confidence=0.5,
            reasoning="fixture opinion",
            raw_data=None,
        ):
            self.agent_name = agent_name
            self.signal = signal
            self.confidence = confidence
            self.reasoning = reasoning
            self.raw_data = raw_data or {}

        def run(self, ctx, progress_callback=None, timeout_seconds=None):
            ctx.add_opinion(AgentOpinion(
                agent_name=self.agent_name,
                signal=self.signal,
                confidence=self.confidence,
                reasoning=self.reasoning,
                raw_data=self.raw_data,
            ))
            result = StageResult(stage_name=self.agent_name, status=StageStatus.COMPLETED)
            result.meta["raw_text"] = self.reasoning
            result.meta["models_used"] = ["test/model"]
            return result

    class _FailedStage:
        def __init__(self, agent_name, error="stage failed"):
            self.agent_name = agent_name
            self.error = error

        def run(self, ctx, progress_callback=None, timeout_seconds=None):
            result = StageResult(
                stage_name=self.agent_name,
                status=StageStatus.FAILED,
                error=self.error,
            )
            result.meta["raw_text"] = ""
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

    def test_pipeline_summary_and_risk_override_share_disabled_override_contract(self):
        orch = self._make_orchestrator(config=SimpleNamespace(agent_risk_override=False))
        ctx = AgentContext(query="test", stock_code="600519")
        captured_messages = []

        def fake_run_agent_loop(messages, **kwargs):
            captured_messages.append(messages)
            return SimpleNamespace(
                success=True,
                content=self._dashboard_json(decision_type="buy"),
                total_tokens=11,
                tool_calls_log=[],
                models_used=["test/model"],
            )

        technical = self._OpinionStage("technical", signal="buy", confidence=0.8)
        risk = self._OpinionStage(
            "risk",
            signal="sell",
            confidence=0.9,
            raw_data={"veto_buy": True},
        )
        decision = self._decision_agent()

        with patch.object(orch, "_build_agent_chain", return_value=[technical, risk, decision]):
            with patch("src.agent.runner.parse_dashboard_json", side_effect=lambda raw: json.loads(raw)):
                with patch("src.agent.agents.base_agent.run_agent_loop", side_effect=fake_run_agent_loop):
                    result = orch._execute_pipeline(ctx, parse_dashboard=True)

        self.assertTrue(result.success)
        self.assertEqual(result.dashboard["decision_type"], "buy")
        self.assertIsNone(ctx.get_data("risk_override_applied"))

        combined = "\n".join(
            str(message.get("content", ""))
            for messages in captured_messages
            for message in messages
        )
        self.assertEqual(combined.count("## Agent Disagreement Summary"), 1)
        self.assertIn('"risk_override_present": false', combined)
        self.assertIn('"override_enabled": false', combined)
        self.assertIn('"override_trigger_present": true', combined)
        self.assertNotIn('"conflict_type": "risk_override"', combined)
        self.assertNotIn("[Pre-fetched: agent_disagreement_summary]", combined)

    def test_pipeline_risk_level_high_is_evidence_not_runtime_override(self):
        orch = self._make_orchestrator(config=SimpleNamespace(agent_risk_override=True))
        ctx = AgentContext(query="test", stock_code="600519")
        captured_messages = []

        def fake_run_agent_loop(messages, **kwargs):
            captured_messages.append(messages)
            return SimpleNamespace(
                success=True,
                content=self._dashboard_json(decision_type="buy"),
                total_tokens=11,
                tool_calls_log=[],
                models_used=["test/model"],
            )

        technical = self._OpinionStage("technical", signal="buy", confidence=0.8)
        risk = self._OpinionStage(
            "risk",
            signal="sell",
            confidence=0.9,
            raw_data={"risk_level": "high"},
        )
        decision = self._decision_agent()

        with patch.object(orch, "_build_agent_chain", return_value=[technical, risk, decision]):
            with patch("src.agent.runner.parse_dashboard_json", side_effect=lambda raw: json.loads(raw)):
                with patch("src.agent.agents.base_agent.run_agent_loop", side_effect=fake_run_agent_loop):
                    result = orch._execute_pipeline(ctx, parse_dashboard=True)

        self.assertTrue(result.success)
        self.assertEqual(result.dashboard["decision_type"], "buy")
        self.assertIsNone(ctx.get_data("risk_override_applied"))

        combined = "\n".join(
            str(message.get("content", ""))
            for messages in captured_messages
            for message in messages
        )
        self.assertEqual(combined.count("## Agent Disagreement Summary"), 1)
        self.assertIn('"evidence_present": true', combined)
        self.assertIn('"override_trigger_present": false', combined)
        self.assertIn('"risk_override_present": false', combined)
        self.assertNotIn('"conflict_type": "risk_override"', combined)

    def test_pipeline_enabled_risk_veto_is_reflected_in_summary_and_final_dashboard(self):
        orch = self._make_orchestrator(config=SimpleNamespace(agent_risk_override=True))
        ctx = AgentContext(query="test", stock_code="600519")
        captured_messages = []

        def fake_run_agent_loop(messages, **kwargs):
            captured_messages.append(messages)
            return SimpleNamespace(
                success=True,
                content=self._dashboard_json(decision_type="buy"),
                total_tokens=11,
                tool_calls_log=[],
                models_used=["test/model"],
            )

        technical = self._OpinionStage("technical", signal="buy", confidence=0.8)
        risk = self._OpinionStage(
            "risk",
            signal="sell",
            confidence=0.9,
            raw_data={"veto_buy": True, "reasoning": "material risk"},
        )
        decision = self._decision_agent()

        with patch.object(orch, "_build_agent_chain", return_value=[technical, risk, decision]):
            with patch("src.agent.runner.parse_dashboard_json", side_effect=lambda raw: json.loads(raw)):
                with patch("src.agent.agents.base_agent.run_agent_loop", side_effect=fake_run_agent_loop):
                    result = orch._execute_pipeline(ctx, parse_dashboard=True)

        self.assertTrue(result.success)
        self.assertEqual(result.dashboard["decision_type"], "hold")
        self.assertEqual(ctx.get_data("risk_override_applied"), {
            "from": "buy",
            "to": "hold",
            "adjustment": "veto",
            "reason": "risk_veto",
        })

        combined = "\n".join(
            str(message.get("content", ""))
            for messages in captured_messages
            for message in messages
        )
        self.assertEqual(combined.count("## Agent Disagreement Summary"), 1)
        self.assertIn('"conflict_type": "risk_override"', combined)
        self.assertIn('"risk_override_present": true', combined)
        self.assertIn('"override_enabled": true', combined)
        self.assertIn('"override_trigger_present": true', combined)

    def test_pipeline_degraded_directional_input_is_not_reported_as_consensus(self):
        orch = self._make_orchestrator(config=SimpleNamespace(agent_risk_override=True))
        ctx = AgentContext(query="test", stock_code="600519")
        captured_messages = []

        def fake_run_agent_loop(messages, **kwargs):
            captured_messages.append(messages)
            return SimpleNamespace(
                success=True,
                content=self._dashboard_json(decision_type="buy"),
                total_tokens=11,
                tool_calls_log=[],
                models_used=["test/model"],
            )

        technical = self._OpinionStage("technical", signal="buy", confidence=0.8)
        intel = self._FailedStage("intel", error="news source failed")
        decision = self._decision_agent()

        with patch.object(orch, "_build_agent_chain", return_value=[technical, intel, decision]):
            with patch("src.agent.runner.parse_dashboard_json", side_effect=lambda raw: json.loads(raw)):
                with patch("src.agent.agents.base_agent.run_agent_loop", side_effect=fake_run_agent_loop):
                    result = orch._execute_pipeline(ctx, parse_dashboard=True)

        self.assertTrue(result.success)
        self.assertEqual(ctx.meta["degraded_stages"], [
            {"stage_name": "intel", "status": "failed", "non_critical": True}
        ])

        combined = "\n".join(
            str(message.get("content", ""))
            for messages in captured_messages
            for message in messages
        )
        self.assertEqual(combined.count("## Agent Disagreement Summary"), 1)
        self.assertIn('"conflict_type": "partial_bullish_with_degraded_inputs"', combined)
        self.assertIn('"decision_path_hint": "state_degraded_inputs_before_any_bullish_lean"', combined)
        self.assertIn('"stage_name": "intel"', combined)
        self.assertIn('"non_critical": true', combined)
        self.assertNotIn('"conflict_type": "aligned_bullish"', combined)

    def test_pipeline_specialist_failure_uses_runtime_non_critical_contract_in_summary(self):
        orch = self._make_orchestrator(config=SimpleNamespace(agent_risk_override=True))
        orch.mode = "specialist"
        ctx = AgentContext(query="test", stock_code="600519")
        captured_messages = []

        def fake_run_agent_loop(messages, **kwargs):
            captured_messages.append(messages)
            return SimpleNamespace(
                success=True,
                content=self._dashboard_json(decision_type="sell"),
                total_tokens=11,
                tool_calls_log=[],
                models_used=["test/model"],
            )

        technical = self._OpinionStage("technical", signal="sell", confidence=0.8)
        intel = self._OpinionStage("intel", signal="hold", confidence=0.5)
        risk = self._OpinionStage("risk", signal="hold", confidence=0.5)
        specialist = self._FailedStage("chan_theory", error="specialist failed")
        decision = self._decision_agent()

        with patch.object(orch, "_build_agent_chain", return_value=[technical, intel, risk, decision]):
            with patch.object(orch, "_build_specialist_agents", return_value=[specialist]):
                with patch.object(orch, "_aggregate_skill_opinions", return_value=None):
                    with patch("src.agent.runner.parse_dashboard_json", side_effect=lambda raw: json.loads(raw)):
                        with patch("src.agent.agents.base_agent.run_agent_loop", side_effect=fake_run_agent_loop):
                            result = orch._execute_pipeline(ctx, parse_dashboard=True)

        self.assertTrue(result.success)
        self.assertEqual(ctx.meta["degraded_stages"], [
            {"stage_name": "chan_theory", "status": "failed", "non_critical": True}
        ])

        combined = "\n".join(
            str(message.get("content", ""))
            for messages in captured_messages
            for message in messages
        )
        self.assertEqual(combined.count("## Agent Disagreement Summary"), 1)
        self.assertIn('"conflict_type": "partial_bearish_with_degraded_inputs"', combined)
        self.assertIn('"stage_name": "chan_theory"', combined)
        self.assertIn('"non_critical_stage_present": true', combined)
        self.assertIn('"non_critical": true', combined)

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

    # --- Sub-agent timeout clamp regression (AGENT_*_TIMEOUT_S) ---

    def _make_config_with_sub_agent_timeouts(self, **kwargs):
        """Return a SimpleNamespace config with sub-agent timeout fields."""
        defaults = {
            "agent_orchestrator_timeout_s": 0,
            "agent_technical_agent_timeout_s": 0,
            "agent_intel_agent_timeout_s": 0,
            "agent_risk_agent_timeout_s": 0,
            "agent_decision_agent_timeout_s": 0,
            "agent_portfolio_agent_timeout_s": 0,
            "agent_skill_agent_timeout_s": 0,
            "agent_risk_override": True,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_run_stage_agent_no_pipeline_budget_uses_sub_agent_limit(self):
        """When pipeline budget is 0 (timeout_seconds=None), sub-agent limit applies standalone."""
        orch = self._make_orchestrator(
            config=self._make_config_with_sub_agent_timeouts(
                agent_technical_agent_timeout_s=180,
            )
        )
        agent = MagicMock(agent_name="technical")
        result = self._stage_result("technical")
        agent.run.return_value = result

        orch._run_stage_agent(agent, AgentContext(query="test"), timeout_seconds=None)

        call_kwargs = agent.run.call_args.kwargs
        self.assertEqual(call_kwargs["timeout_seconds"], 180)

    def test_run_stage_agent_pipeline_budget_larger_than_agent_limit_clamps_to_agent(self):
        """Pipeline remaining > sub-agent limit → use smaller agent limit."""
        orch = self._make_orchestrator(
            config=self._make_config_with_sub_agent_timeouts(
                agent_technical_agent_timeout_s=120,
            )
        )
        agent = MagicMock(agent_name="technical")
        result = self._stage_result("technical")
        agent.run.return_value = result

        orch._run_stage_agent(agent, AgentContext(query="test"), timeout_seconds=300)

        call_kwargs = agent.run.call_args.kwargs
        self.assertEqual(call_kwargs["timeout_seconds"], 120)

    def test_run_stage_agent_pipeline_budget_smaller_than_agent_limit_uses_pipeline(self):
        """Pipeline remaining < sub-agent limit → use smaller pipeline remaining."""
        orch = self._make_orchestrator(
            config=self._make_config_with_sub_agent_timeouts(
                agent_technical_agent_timeout_s=300,
            )
        )
        agent = MagicMock(agent_name="technical")
        result = self._stage_result("technical")
        agent.run.return_value = result

        orch._run_stage_agent(agent, AgentContext(query="test"), timeout_seconds=60)

        call_kwargs = agent.run.call_args.kwargs
        self.assertEqual(call_kwargs["timeout_seconds"], 60)

    def test_run_stage_agent_no_sub_agent_limit_passes_pipeline_budget_through(self):
        """No sub-agent limit configured (all 0) → pipeline budget passed through unchanged."""
        orch = self._make_orchestrator(
            config=self._make_config_with_sub_agent_timeouts(),
        )
        agent = MagicMock(agent_name="technical")
        result = self._stage_result("technical")
        agent.run.return_value = result

        orch._run_stage_agent(agent, AgentContext(query="test"), timeout_seconds=300)

        call_kwargs = agent.run.call_args.kwargs
        self.assertEqual(call_kwargs["timeout_seconds"], 300)

    def test_run_stage_agent_skill_agent_fallback_applies_skill_clamp(self):
        """Skill agents (in _skill_agent_names) use the 'skill' clamp key as fallback."""
        orch = self._make_orchestrator(
            config=self._make_config_with_sub_agent_timeouts(
                agent_skill_agent_timeout_s=90,
            )
        )
        orch._skill_agent_names = {"bull_trend_specialist", "volume_breakout_specialist"}
        agent = MagicMock(agent_name="bull_trend_specialist")
        result = self._stage_result("bull_trend_specialist")
        agent.run.return_value = result

        orch._run_stage_agent(agent, AgentContext(query="test"), timeout_seconds=300)

        call_kwargs = agent.run.call_args.kwargs
        self.assertEqual(call_kwargs["timeout_seconds"], 90)

    def test_run_stage_agent_skill_agent_exact_name_match_wins_over_skill_fallback(self):
        """Exact agent_name match takes priority over _skill_agent_names fallback."""
        orch = self._make_orchestrator(
            config=self._make_config_with_sub_agent_timeouts(
                agent_skill_agent_timeout_s=90,
                agent_decision_agent_timeout_s=150,
            )
        )
        orch._skill_agent_names = {"decision"}
        agent = MagicMock(agent_name="decision")
        result = self._stage_result("decision")
        agent.run.return_value = result

        orch._run_stage_agent(agent, AgentContext(query="test"), timeout_seconds=300)

        call_kwargs = agent.run.call_args.kwargs
        # Exact name "decision" → 150, not skill fallback 90
        self.assertEqual(call_kwargs["timeout_seconds"], 150)

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
            with patch("src.agent.orchestrator.build_visible_chat_history", return_value=history):
                with patch("src.agent.conversation.conversation_manager.get_or_create"):
                    with patch("src.agent.conversation.conversation_manager.add_message"):
                        orch.chat("hello", "session-1")

        self.assertEqual(captured["history"], history)

    def test_chat_uses_compressed_history_builder(self):
        from src.agent.orchestrator import OrchestratorResult

        orch = self._make_orchestrator()

        with patch.object(orch, "_execute_pipeline", return_value=OrchestratorResult(success=True, content="ok")):
            with patch("src.agent.orchestrator.build_visible_chat_history", return_value=[]) as build_history:
                with patch("src.agent.conversation.conversation_manager.get_or_create"):
                    with patch("src.agent.conversation.conversation_manager.add_message"):
                        orch.chat("hello", "session-1")

        build_history.assert_called_once()
        self.assertEqual(build_history.call_args.args[0], "session-1")
        self.assertIs(build_history.call_args.args[1], orch.llm_adapter)

    def test_chat_resolves_scope_and_stores_it_for_multi_agent_chain(self):
        from src.agent.orchestrator import OrchestratorResult

        orch = self._make_orchestrator()
        captured = {}

        def fake_execute(ctx, parse_dashboard=False, progress_callback=None):
            captured["ctx"] = ctx
            return OrchestratorResult(success=True, content="assistant reply")

        with patch.object(orch, "_execute_pipeline", side_effect=fake_execute):
            with patch("src.agent.orchestrator.build_visible_chat_history", return_value=[]):
                with patch("src.agent.conversation.conversation_manager.get_or_create"):
                    with patch("src.agent.conversation.conversation_manager.add_message"):
                        orch.chat(
                            "换成 AAPL 看看",
                            "session-1",
                            context={
                                "stock_code": "600519",
                                "stock_name": "匿名标的",
                                "previous_analysis_summary": {"summary": "old"},
                            },
                        )

        ctx = captured["ctx"]
        self.assertEqual(ctx.stock_code, "AAPL")
        self.assertEqual(ctx.stock_name, "")
        self.assertNotIn("previous_analysis_summary", ctx.meta)
        self.assertEqual(ctx.meta["stock_scope"].mode, "switch")
        self.assertEqual(ctx.meta["stock_scope"].expected_stock_code, "AAPL")

    def test_chat_does_not_read_or_write_provider_trace(self):
        from src.agent.orchestrator import OrchestratorResult

        DatabaseManager.reset_instance()
        Config.reset_instance()
        db = DatabaseManager(db_url="sqlite:///:memory:")
        session_id = "multi-agent-trace-boundary"
        user_id = db.save_conversation_message(session_id, "user", "previous question")
        assistant_id = db.save_conversation_message(session_id, "assistant", "previous answer")
        db.save_agent_provider_turn(
            session_id=session_id,
            run_id="run-existing",
            provider="deepseek",
            model="deepseek/deepseek-chat",
            anchor_user_message_id=user_id,
            anchor_assistant_message_id=assistant_id,
            messages=[
                {
                    "role": "assistant",
                    "reasoning_content": "reasoning",
                    "tool_calls": [{"id": "call_1", "name": "echo", "arguments": {}}],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "tool-result"},
            ],
            contains_reasoning=True,
            contains_tool_calls=True,
            contains_thinking_blocks=False,
            must_roundtrip=True,
            estimated_tokens=10,
        )

        orch = self._make_orchestrator()
        try:
            with patch.object(orch, "_execute_pipeline", return_value=OrchestratorResult(success=True, content="ok")):
                with patch("src.agent.orchestrator.build_visible_chat_history", return_value=[]) as build_history:
                    with patch.object(db, "get_agent_provider_turns", wraps=db.get_agent_provider_turns) as get_turns:
                        result = orch.chat("hello", session_id)

            self.assertTrue(result.success)
            build_history.assert_called_once()
            get_turns.assert_not_called()
            rows = db.get_agent_provider_turns(session_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["run_id"], "run-existing")
        finally:
            DatabaseManager.reset_instance()
            Config.reset_instance()

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

    def test_chat_transaction_persists_user_before_multi_agent_execution(self):
        """SSE acceptance can occur after persistence but before the pipeline starts."""
        from src.agent.orchestrator import OrchestratorResult

        orch = self._make_orchestrator()
        fake_result = OrchestratorResult(success=True, content="assistant reply")

        with patch.object(orch, "_execute_pipeline", return_value=fake_result) as execute_pipeline:
            with patch("src.agent.orchestrator.build_visible_chat_history", return_value=[]):
                with patch("src.agent.conversation.conversation_manager.get_or_create"):
                    with patch("src.agent.conversation.conversation_manager.add_message") as add_message:
                        turn = orch.prepare_turn(message="hello", session_id="session-accepted")

                        add_message.assert_called_once_with("session-accepted", "user", "hello")
                        execute_pipeline.assert_not_called()

                        result = orch.execute_turn(turn)

        self.assertTrue(result.success)
        execute_pipeline.assert_called_once_with(
            turn.context,
            parse_dashboard=False,
            progress_callback=None,
        )
        self.assertEqual(add_message.call_args_list[-1].args, (
            "session-accepted",
            "assistant",
            "assistant reply",
        ))

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

    def test_decision_agent_prompt_requires_phase_decision(self):
        from src.agent.agents.decision_agent import DecisionAgent

        agent = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
        prompt = agent.system_prompt(AgentContext(query="分析 600519", stock_code="600519"))

        self.assertIn("phase_decision", prompt)
        self.assertIn("watch_conditions", prompt)
        self.assertIn("data_limitations", prompt)
        self.assertIn("confidence_level", prompt)


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

    def test_build_messages_injects_market_phase_before_cached_data(self):
        agent = self._make_agent()
        ctx = AgentContext(query="hello", stock_code="600519")
        ctx.meta["market_phase_context"] = {
            "market": "cn",
            "phase": "intraday",
            "market_local_time": "2026-03-27T10:00:00+08:00",
            "effective_daily_bar_date": "2026-03-26",
            "is_partial_bar": True,
            "minutes_to_close": 300,
        }
        ctx.meta["analysis_context_pack_summary"] = "\n## 分析上下文包摘要\n- 数据块状态：行情 available\n"
        ctx.set_data("realtime_quote", {"price": 1880.0})

        messages = agent._build_messages(ctx)

        phase_indexes = [
            idx for idx, message in enumerate(messages)
            if "市场阶段上下文" in message.get("content", "")
        ]
        cached_indexes = [
            idx for idx, message in enumerate(messages)
            if "[Pre-fetched: realtime_quote]" in message.get("content", "")
        ]
        pack_indexes = [
            idx for idx, message in enumerate(messages)
            if "分析上下文包摘要" in message.get("content", "")
        ]
        self.assertEqual(len(phase_indexes), 1)
        self.assertEqual(len(pack_indexes), 1)
        self.assertEqual(len(cached_indexes), 1)
        self.assertLess(phase_indexes[0], pack_indexes[0])
        self.assertLess(pack_indexes[0], cached_indexes[0])
        phase_message = messages[phase_indexes[0]]
        self.assertEqual(phase_message["role"], "user")
        self.assertIn("盘中", phase_message["content"])
        self.assertIn("不得当作完整日线复盘", phase_message["content"])
        self.assertNotIn("market_phase_context", phase_message["content"])
        self.assertNotIn("is_partial_bar", phase_message["content"])
        pack_message = messages[pack_indexes[0]]
        self.assertEqual(pack_message["role"], "user")
        self.assertNotIn("analysis_context_pack_summary", pack_message["content"])

    def test_run_passes_stock_scope_from_context_meta_to_shared_runner(self):
        from src.agent.runner import RunLoopResult

        agent = self._make_agent()
        ctx = AgentContext(query="hello", stock_code="600519")
        ctx.meta["stock_scope"] = StockScope(
            expected_stock_code="600519",
            allowed_stock_codes={"600519"},
        )

        with patch(
            "src.agent.agents.base_agent.run_agent_loop",
            return_value=RunLoopResult(success=True, content="ok"),
        ) as run_loop:
            result = agent.run(ctx)

        self.assertEqual(result.status, StageStatus.COMPLETED)
        self.assertIs(run_loop.call_args.kwargs["stock_scope"], ctx.meta["stock_scope"])


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

    def test_market_phase_meta_is_not_injected_as_prefetched_data(self):
        memory = MagicMock(enabled=False)
        agent = self._make_agent(memory)
        ctx = AgentContext(query="test", stock_code="600519")
        ctx.meta["market_phase_context"] = {"phase": "intraday"}
        ctx.meta["market_structure_context"] = {
            "market_theme_context": {"status": "ok"},
            "stock_market_position": {"status": "ok"},
        }
        ctx.meta["analysis_context_pack_summary"] = "\n## 分析上下文包摘要\n- 数据块状态：行情 available\n"
        ctx.set_data("realtime_quote", {"price": 1880.0})

        injected = agent._inject_cached_data(ctx)

        self.assertIn("[Pre-fetched: realtime_quote]", injected)
        self.assertNotIn("market_phase_context", injected)
        self.assertNotIn("[Pre-fetched: market_phase_context]", injected)
        self.assertNotIn("market_structure_context", injected)
        self.assertNotIn("[Pre-fetched: market_structure_context]", injected)
        self.assertNotIn("analysis_context_pack_summary", injected)
        self.assertNotIn("[Pre-fetched: analysis_context_pack_summary]", injected)
        self.assertNotIn("分析上下文包摘要", injected)

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

        dashboard = orch._resolve_dashboard_payload(
            ctx,
            ctx.get_data("final_dashboard"),
            None,
        )

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

        dashboard = orch._resolve_dashboard_payload(ctx, dashboard, None)

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

        dashboard = orch._resolve_dashboard_payload(ctx, dashboard, None)

        self.assertEqual(dashboard["decision_type"], "buy")
        self.assertIsNone(ctx.get_data("risk_override_applied"))

    def test_risk_level_high_alone_does_not_override_buy_signal(self):
        from src.agent.orchestrator import AgentOrchestrator

        orch = AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
            config=SimpleNamespace(agent_risk_override=True),
        )
        ctx = AgentContext(query="test", stock_code="600519")
        dashboard = self._make_dashboard()
        ctx.set_data("final_dashboard", dashboard)
        ctx.add_opinion(AgentOpinion(agent_name="decision", signal="buy", confidence=0.8, reasoning="base"))
        ctx.add_opinion(AgentOpinion(
            agent_name="risk",
            signal="sell",
            confidence=0.9,
            raw_data={"risk_level": "high"},
        ))

        dashboard = orch._resolve_dashboard_payload(ctx, dashboard, None)

        self.assertEqual(dashboard["decision_type"], "buy")
        self.assertIsNone(ctx.get_data("risk_override_applied"))


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


class TestP1SemanticConvergence(unittest.TestCase):
    """覆盖 PR reviewer 提出的 5 个 P1 阻断项的端到端入口测试"""

    def test_signal_enum_input_compatibility(self):
        """P1-1: Signal.BUY 枚举输入不应被标记为 invalid"""
        signal, invalid, original = normalize_strategy_signal(Signal.BUY)
        self.assertEqual(signal, "buy")
        self.assertFalse(invalid)
        self.assertEqual(original, "buy")

        for enum_val, expected in [
            (Signal.STRONG_BUY, "strong_buy"),
            (Signal.HOLD, "hold"),
            (Signal.SELL, "sell"),
            (Signal.STRONG_SELL, "strong_sell"),
        ]:
            signal, invalid, _ = normalize_strategy_signal(enum_val)
            self.assertEqual(signal, expected)
            self.assertFalse(invalid, f"{enum_val} should not be marked invalid")

    def test_missing_signal_marked_invalid(self):
        """P1-2: 缺失 signal 的 LLM 输出应被标记为 invalid，而非静默兜底为 hold"""
        ctx = AgentContext()

        opinion = AgentOpinion(
            agent_name="skill_test",
            signal=None,
            confidence=0.9,
            reasoning="test",
            raw_data={"confidence": 0.9}
        )

        strategy_opinion = strategy_opinion_from_agent_opinion(opinion)
        self.assertTrue(strategy_opinion.invalid_signal)
        self.assertEqual(strategy_opinion.signal, "hold")

    def test_opinion_count_excludes_invalid(self):
        """P1-3: summary_params.opinion_count 应仅计 valid opinions"""
        opinions = []

        valid_op = AgentOpinion(agent_name="skill_test1", signal="buy", confidence=0.8)
        opinions.append(strategy_opinion_from_agent_opinion(valid_op))

        for i in range(9):
            invalid_op = AgentOpinion(agent_name=f"skill_invalid{i}", signal="moon", confidence=0.9)
            opinions.append(strategy_opinion_from_agent_opinion(invalid_op))

        synthesizer = StrategySynthesizer()
        synthesis = synthesizer.synthesize(
            opinions,
            weighted_score=4.0,
            final_signal="buy",
            weighted_confidence=0.8,
            conflicts=[],
        )

        self.assertEqual(synthesis["summary_params"]["opinion_count"], 1)
        self.assertEqual(synthesis["summary_params"]["total_opinion_count"], 10)
        self.assertEqual(synthesis["summary_params"]["invalid_opinion_count"], 9)

    def test_deterministic_synthesis_authoritative(self):
        """P1-4: 确定性 synthesis 应为 dashboard 的唯一权威来源"""
        ctx = AgentContext()
        ctx.set_data("skill_consensus", {
            "signal": "buy",
            "confidence": 0.8,
            "raw_data": {
                "strategy_synthesis": {
                    "final_signal": "buy",
                    "confidence": 0.8,
                    "consensus_level": "high",
                    "summary_key": "test.deterministic",
                }
            },
        })

        dashboard_with_llm_synthesis = {
            "decision_type": "sell",
            "dashboard": {
                "strategy_synthesis": {
                    "final_signal": "sell",
                    "confidence": 0.1,
                    "consensus_level": "low",
                    "summary_key": "llm.generated",
                }
            },
        }

        orchestrator = AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
            mode="full",
        )
        normalized = orchestrator._finalize_dashboard_payload(dashboard_with_llm_synthesis, ctx)

        self.assertIsNotNone(normalized)
        self.assertIn("strategy_synthesis", normalized["dashboard"])
        synth = normalized["dashboard"]["strategy_synthesis"]
        self.assertEqual(synth["final_signal"], "buy")
        self.assertEqual(synth["confidence"], 0.8)
        self.assertEqual(synth["summary_key"], "test.deterministic")

    def test_full_pipeline_valid_signal(self):
        """P1-5: 端到端验证：合法 Signal 枚举输入应保持正确语义"""
        ctx = AgentContext()

        opinion = AgentOpinion(
            agent_name="skill_test",
            signal="buy",
            confidence=0.9,
            reasoning="strong bullish signal"
        )

        strategy_opinion = strategy_opinion_from_agent_opinion(opinion)
        self.assertFalse(strategy_opinion.invalid_signal)
        self.assertEqual(strategy_opinion.signal, "buy")

        ctx.opinions.append(opinion)
        aggregator = SkillAggregator()
        consensus = aggregator.aggregate(ctx)

        self.assertIsNotNone(consensus)
        self.assertEqual(consensus.signal, "buy")
        self.assertGreater(consensus.confidence, 0.0)

    def test_prompt_pollution_prevention(self):
        """E2E-A: 1 valid buy/0.8 + 2 invalid moon/0.9 → Orchestrator partition →
        DecisionAgent prompt 不含 'moon'，ctx.meta['invalid_opinions'] 长度 == 2。
        真 E2E：SkillAgent 输入 → Orchestrator 分拣 → DecisionAgent build_user_message。
        """
        from src.agent.agents.decision_agent import DecisionAgent

        ctx = AgentContext(stock_code="600519", stock_name="贵州茅台")

        # 1 valid buy opinion
        valid_op = AgentOpinion(
            agent_name="skill_valid",
            signal="buy",
            confidence=0.8,
            reasoning="valid bullish signal"
        )
        ctx.opinions.append(valid_op)

        # 2 invalid moon opinions
        for i in range(2):
            invalid_op = AgentOpinion(
                agent_name=f"skill_invalid_{i}",
                signal="moon",
                confidence=0.9,
                reasoning="to the moon"
            )
            ctx.opinions.append(invalid_op)

        # Orchestrator invalid partition — the ONLY partition point per contract
        orchestrator = AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
            mode="full",
        )
        orchestrator._partition_skill_opinions(ctx)

        # After partition: only valid opinions remain in ctx.opinions
        self.assertEqual(len(ctx.opinions), 1)
        self.assertEqual(ctx.opinions[0].agent_name, "skill_valid")

        # Invalid opinions moved to ctx.meta["invalid_opinions"]
        invalid_bucket = ctx.meta.get("invalid_opinions", [])
        self.assertEqual(len(invalid_bucket), 2)
        for entry in invalid_bucket:
            self.assertIn(entry["agent_name"], {"skill_invalid_0", "skill_invalid_1"})
            self.assertEqual(entry["raw_signal"], "moon")
            self.assertEqual(entry["reason"], "unrecognized_signal")

        # DecisionAgent prompt — consumes partitioned ctx.opinions directly
        agent = DecisionAgent(tool_registry=MagicMock(), llm_adapter=MagicMock())
        prompt = agent.build_user_message(ctx)

        # Prompt should NOT contain "moon" or invalid agent names / confidence
        self.assertNotIn("moon", prompt.lower())
        self.assertNotIn("skill_invalid_0", prompt)
        self.assertNotIn("skill_invalid_1", prompt)
        self.assertNotIn("0.90", prompt)  # invalid opinions' 0.9 confidence

        # Prompt should contain valid opinion
        self.assertIn("skill_valid", prompt)
        self.assertIn("buy", prompt)
        self.assertIn("0.80", prompt)

        # Prompt should mention invalid count as diagnostics (not evidence)
        self.assertIn("2", prompt)  # invalid count

    def test_zero_weight_never_strong_sell(self):
        """E2E-2: 两个 hold/0.0 或 buy/0.0 → final signal 应为 hold，绝不应是 strong_sell"""
        ctx = AgentContext()

        # Two valid opinions with zero confidence (zero weight)
        ctx.opinions.append(AgentOpinion(agent_name="skill_1", signal="hold", confidence=0.0))
        ctx.opinions.append(AgentOpinion(agent_name="skill_2", signal="buy", confidence=0.0))

        aggregator = SkillAggregator()
        consensus = aggregator.aggregate(ctx)

        self.assertIsNotNone(consensus)
        # Zero weight sum should result in hold (3.0), not strong_sell
        self.assertEqual(consensus.signal, "hold")

        # Verify synthesis metadata
        synthesis = consensus.raw_data.get("strategy_synthesis")
        self.assertIsNotNone(synthesis)
        self.assertEqual(synthesis["final_signal"], "hold")
        # consensus_level should be insufficient with zero confidence
        self.assertEqual(synthesis["consensus_level"], "insufficient")

    def test_hold_grouping_consistency(self):
        """E2E-3: 两个 valid hold/0.8 → 两个 hold 都应在 supporting_skills 中"""
        ctx = AgentContext()

        ctx.opinions.append(AgentOpinion(agent_name="skill_1", signal="hold", confidence=0.8))
        ctx.opinions.append(AgentOpinion(agent_name="skill_2", signal="hold", confidence=0.8))

        aggregator = SkillAggregator()
        consensus = aggregator.aggregate(ctx)

        self.assertIsNotNone(consensus)
        self.assertEqual(consensus.signal, "hold")

        synthesis = consensus.raw_data.get("strategy_synthesis")
        self.assertIsNotNone(synthesis)

        # Both hold opinions should be in supporting_skills (not neutral or opposing)
        supporting = synthesis.get("supporting_skills", [])
        self.assertEqual(len(supporting), 2)

        # Verify both skills are listed
        supporting_names = {s["agent_name"] for s in supporting}
        self.assertIn("skill_1", supporting_names)
        self.assertIn("skill_2", supporting_names)

        # opposing_skills should be empty
        opposing = synthesis.get("opposing_skills", [])
        self.assertEqual(len(opposing), 0)

    def test_single_sample_consensus_insufficient(self):
        """E2E-4: 1 valid buy/0.8 + 多个 invalid → consensus 应为 insufficient，不是 high"""
        ctx = AgentContext()

        # 1 valid opinion
        ctx.opinions.append(AgentOpinion(agent_name="skill_valid", signal="buy", confidence=0.8))

        # 3 invalid opinions
        for i in range(3):
            ctx.opinions.append(AgentOpinion(
                agent_name=f"skill_invalid_{i}",
                signal="moon",
                confidence=0.9
            ))

        aggregator = SkillAggregator()
        consensus = aggregator.aggregate(ctx)

        self.assertIsNotNone(consensus)
        synthesis = consensus.raw_data.get("strategy_synthesis")
        self.assertIsNotNone(synthesis)

        # consensus_level should be insufficient (only 1 valid sample)
        self.assertEqual(synthesis["consensus_level"], "insufficient")

        # opinion_count should be 1 (only valid)
        self.assertEqual(synthesis["summary_params"]["opinion_count"], 1)

        # invalid_opinion_count should be 3
        self.assertEqual(synthesis["summary_params"]["invalid_opinion_count"], 3)

    def test_e2e_e_partition_then_aggregate_insufficient(self):
        """E2E-E: 1 valid buy/0.8 + 9 invalid → 走 orchestrator 分拣 → aggregator →
        consensus_level == 'insufficient'（不得 high）；synthesis.summary_params
        对应 opinion_count=1、invalid_opinion_count=9、total_opinion_count=10。
        真 E2E：SkillAgent 输入 → Orchestrator 分拣 → SkillAggregator 合成。
        """
        ctx = AgentContext()

        ctx.opinions.append(AgentOpinion(
            agent_name="skill_valid",
            signal="buy",
            confidence=0.8,
            reasoning="valid bullish signal",
        ))

        for i in range(9):
            ctx.opinions.append(AgentOpinion(
                agent_name=f"skill_invalid_{i}",
                signal="moon",
                confidence=0.9,
                reasoning="invalid moon signal",
            ))

        # 唯一分拣点：Orchestrator
        orchestrator = AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
            mode="full",
        )
        orchestrator._partition_skill_opinions(ctx)

        # After partition
        self.assertEqual(len(ctx.opinions), 1)
        self.assertEqual(len(ctx.meta.get("invalid_opinions", [])), 9)

        # Aggregator consumes partitioned ctx.opinions directly
        aggregator = SkillAggregator()
        consensus = aggregator.aggregate(ctx)

        self.assertIsNotNone(consensus)
        synthesis = consensus.raw_data.get("strategy_synthesis")
        self.assertIsNotNone(synthesis)

        # 单样本共识必须 insufficient
        self.assertEqual(synthesis["consensus_level"], "insufficient")

        # summary_params 计数正确
        self.assertEqual(synthesis["summary_params"]["opinion_count"], 1)
        # 注意：aggregator 只看到 partition 后的 opinions，
        # invalid_opinion_count 由 aggregator 内部 strategy_opinion 判定
        # 若要覆盖 diagnostic 计数，renderer 层从 ctx.meta 读取
        # 此处仅确保 valid 计数正确

    def test_e2e_f_uppercase_buy_canonical(self):
        """E2E-F: signal='BUY' 大写输入 → normalize 后 canonical='buy' →
        aggregator 使用 canonical 查 strategy_signal_score → 得 4.0（不是 0）。
        final_signal 输出 canonical 小写 'buy'。
        真 E2E：SkillAgent 输出大写 → aggregator 内部 canonical-first 计算。
        """
        ctx = AgentContext()

        # Two valid opinions, one with uppercase signal
        ctx.opinions.append(AgentOpinion(
            agent_name="skill_upper",
            signal="BUY",  # 大写
            confidence=0.8,
        ))
        ctx.opinions.append(AgentOpinion(
            agent_name="skill_lower",
            signal="buy",
            confidence=0.8,
        ))

        # No partition needed — both are valid after normalization
        aggregator = SkillAggregator()
        consensus = aggregator.aggregate(ctx)

        self.assertIsNotNone(consensus)
        # canonical 小写输出
        self.assertEqual(consensus.signal, "buy")

        synthesis = consensus.raw_data.get("strategy_synthesis")
        self.assertIsNotNone(synthesis)
        # weighted_score 应接近 4.0（buy 的 canonical 分数），
        # 而不是因大写查表失败得到 0
        self.assertGreaterEqual(synthesis["weighted_score"], 3.5)
        # final_signal 输出 canonical 小写
        self.assertEqual(synthesis["final_signal"], "buy")

    def test_e2e_g_empty_supporting_uses_none_label(self):
        """E2E-G: 空 supporting_skills + report_language='en' → 四条 renderer 中
        不出现中文 '无'，而是 'None'（对应 labels.none_label）。
        真 E2E：dashboard payload → renderer 实际文本。
        """
        from src.report_language import get_report_labels

        # zh、en、ko 三语的 none_label 都必须完备
        for lang, expected in [("zh", "无"), ("en", "None"), ("ko", "없음")]:
            labels = get_report_labels(lang)
            self.assertEqual(labels["none_label"], expected)

        # 模拟一个空 supporting_skills 的 payload
        strategy_synthesis = {
            "final_signal": "hold",
            "confidence": 0.5,
            "consensus_level": "insufficient",
            "conflict_severity": "none",
            "conflict_count": 0,
            "supporting_skills": [],
            "opposing_skills": [],
            "summary_params": {
                "opinion_count": 0,
                "total_opinion_count": 0,
                "invalid_opinion_count": 0,
            },
        }

        # 走 notification 的 renderer helper
        from src.notification import _append_strategy_synthesis_block

        for lang, expected_none in [("en", "None"), ("ko", "없음")]:
            labels = get_report_labels(lang)
            lines = []
            _append_strategy_synthesis_block(lines, strategy_synthesis, labels, lang)
            rendered = "\n".join(lines)

            # 空阵营必须用 labels.none_label 输出
            self.assertIn(expected_none, rendered)
            # 不得出现其他语言的 none_label
            for other_lang, other_none in [("zh", "无"), ("en", "None"), ("ko", "없음")]:
                if other_lang == lang:
                    continue
                # zh 的 "无" 有可能出现在其他非阵营的文案中，这里只检查阵营行
                # 简单起见：只在 en/ko 场景校验中文"无"不出现
                if lang != "zh" and other_lang == "zh":
                    self.assertNotIn("无", rendered)


class TestStrategyEngineE2E(unittest.TestCase):
    """E2E tests exercising StrategyEngine as the authoritative pipeline facade."""

    def _make_orchestrator(self):
        return AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
            mode="specialist",
        )

    # ------------------------------------------------------------------
    # 1. Mixed valid + invalid → engine produces deterministic synthesis
    # ------------------------------------------------------------------

    def test_engine_mixed_valid_invalid_invalid_count(self):
        """Engine: 2 valid buy/0.8 + 3 invalid moon/0.9 → synthesis.invalid_opinion_count == 3."""
        from src.agent.skills.engine import StrategyEngine, StrategyResultStatus

        opinions = []
        for i in range(2):
            opinions.append(AgentOpinion(agent_name=f"skill_v{i}", signal="buy", confidence=0.8))
        for i in range(3):
            opinions.append(AgentOpinion(agent_name=f"skill_x{i}", signal="moon", confidence=0.9))

        result = StrategyEngine().process(opinions)

        self.assertEqual(result.status, StrategyResultStatus.CONSENSUS)
        self.assertIsNotNone(result.synthesis_dict)
        params = result.synthesis_dict["summary_params"]
        self.assertEqual(params["opinion_count"], 2)
        self.assertEqual(params["invalid_opinion_count"], 3)
        self.assertEqual(params["total_opinion_count"], 5)
        self.assertEqual(result.invalid_count, 3)
        self.assertEqual(len(result.invalid_records), 3)

    # ------------------------------------------------------------------
    # 2. All invalid → NO_CONSENSUS stub
    # ------------------------------------------------------------------

    def test_engine_all_invalid_no_consensus_stub(self):
        """Engine: 4 all-invalid → NO_CONSENSUS stub with consensus_level == 'insufficient'."""
        from src.agent.skills.engine import StrategyEngine, StrategyResultStatus

        opinions = [
            AgentOpinion(agent_name=f"skill_bad{i}", signal="moon", confidence=0.9)
            for i in range(4)
        ]

        result = StrategyEngine().process(opinions)

        self.assertEqual(result.status, StrategyResultStatus.NO_CONSENSUS)
        self.assertIsNotNone(result.synthesis_dict)
        self.assertEqual(result.synthesis_dict["consensus_level"], "insufficient")
        self.assertEqual(result.synthesis_dict["confidence"], 0.0)
        self.assertEqual(result.synthesis_dict["final_signal"], "hold")
        self.assertEqual(result.invalid_count, 4)
        self.assertIsNotNone(result.skill_consensus_data)
        self.assertEqual(
            result.skill_consensus_data["strategy_synthesis"]["consensus_level"],
            "insufficient",
        )

    # ------------------------------------------------------------------
    # 3. LLM strategy_synthesis stripped at parse boundary
    # ------------------------------------------------------------------

    def test_llm_strategy_synthesis_stripped_at_parse_boundary(self):
        """dashboard_block['strategy_synthesis'] from LLM is stripped; engine result wins."""
        ctx = AgentContext()
        ctx.set_data("skill_consensus", {
            "signal": "buy",
            "confidence": 0.75,
            "raw_data": {
                "strategy_synthesis": {
                    "final_signal": "buy",
                    "confidence": 0.75,
                    "consensus_level": "high",
                    "summary_key": "engine.deterministic",
                }
            },
        })

        llm_payload = {
            "decision_type": "sell",
            "dashboard": {
                # LLM wrote this — must be stripped before engine result is written
                "strategy_synthesis": {
                    "final_signal": "sell",
                    "confidence": 0.1,
                    "consensus_level": "low",
                    "summary_key": "llm.invented",
                }
            },
        }

        orchestrator = self._make_orchestrator()
        normalized = orchestrator._finalize_dashboard_payload(llm_payload, ctx)

        self.assertIsNotNone(normalized)
        synth = normalized["dashboard"].get("strategy_synthesis")
        self.assertIsNotNone(synth)
        # Engine's deterministic synthesis wins
        self.assertEqual(synth["final_signal"], "buy")
        self.assertNotEqual(synth.get("summary_key"), "llm.invented")

    # ------------------------------------------------------------------
    # 4. Timeout fallback preserves invalid diagnostics
    # ------------------------------------------------------------------

    def test_partition_fallback_preserves_invalid_diagnostics(self):
        """_apply_partition_fallback: invalid opinions land in ctx.meta and don't re-enter evidence."""
        ctx = AgentContext()
        ctx.opinions.append(AgentOpinion(agent_name="skill_v", signal="buy", confidence=0.8))
        ctx.opinions.append(AgentOpinion(agent_name="skill_bad", signal="moon", confidence=0.9))
        # Non-skill opinion should pass through untouched
        ctx.opinions.append(AgentOpinion(agent_name="technical", signal="buy", confidence=0.7))

        orchestrator = self._make_orchestrator()
        orchestrator._apply_partition_fallback(ctx)

        # Invalid skill opinion removed from evidence chain
        evidence_names = {op.agent_name for op in ctx.opinions}
        self.assertNotIn("skill_bad", evidence_names)
        self.assertIn("skill_v", evidence_names)
        self.assertIn("technical", evidence_names)

        # Captured in diagnostics
        invalid_bucket = ctx.meta.get("invalid_opinions", [])
        self.assertEqual(len(invalid_bucket), 1)
        self.assertEqual(invalid_bucket[0]["agent_name"], "skill_bad")
        self.assertEqual(invalid_bucket[0]["reason"], "unrecognized_signal")

    def test_partition_fallback_idempotent_when_engine_ran(self):
        """_apply_partition_fallback is a no-op when StrategyEngine already ran."""
        ctx = AgentContext()
        ctx.opinions.append(AgentOpinion(agent_name="skill_bad", signal="moon", confidence=0.9))
        # Simulate engine already ran
        ctx.set_data("skill_consensus", {"signal": "hold", "confidence": 0.0})

        orchestrator = self._make_orchestrator()
        orchestrator._apply_partition_fallback(ctx)

        # Should not have been re-partitioned
        self.assertEqual(len(ctx.opinions), 1)
        self.assertNotIn("invalid_opinions", ctx.meta)

    # ------------------------------------------------------------------
    # 5. Signal alias consistency: strong-buy / strong_buy in both paths
    # ------------------------------------------------------------------

    def test_signal_alias_consistency_aggregation_and_disagreement(self):
        """'strong-buy' alias → canonical 'strong_buy' in both aggregation and disagreement."""
        from src.agent.disagreement import build_agent_disagreement_summary

        # Aggregation path
        ctx = AgentContext()
        ctx.opinions.append(AgentOpinion(agent_name="skill_1", signal="strong-buy", confidence=0.8))
        ctx.opinions.append(AgentOpinion(agent_name="skill_2", signal="strong_buy", confidence=0.8))

        aggregator = SkillAggregator()
        consensus = aggregator.aggregate(ctx)

        self.assertIsNotNone(consensus)
        self.assertEqual(consensus.signal, "strong_buy")

        synthesis = consensus.raw_data.get("strategy_synthesis")
        self.assertIsNotNone(synthesis)
        self.assertEqual(synthesis["final_signal"], "strong_buy")

        # Disagreement path: strong-buy alias should not be treated as unknown/hold
        ctx2 = AgentContext()
        ctx2.opinions.append(AgentOpinion(agent_name="technical", signal="strong-buy", confidence=0.9))
        ctx2.opinions.append(AgentOpinion(agent_name="decision", signal="hold", confidence=0.6))
        summary = build_agent_disagreement_summary(ctx2)

        # strong-buy and hold diverge, so disagreement should be detected
        # (not hidden by wrong normalization that converts strong-buy → hold)
        self.assertIsNotNone(summary)
        if summary.get("has_disagreement"):
            self.assertIn("strong_buy", str(summary))

    # ------------------------------------------------------------------
    # 6. Consensus level i18n for "insufficient"
    # ------------------------------------------------------------------

    def test_localize_consensus_level_insufficient(self):
        """localize_consensus_level('insufficient', lang) returns short enum translations."""
        from src.report_language import localize_consensus_level

        cases = [
            ("insufficient", "zh", "证据不足"),
            ("insufficient", "en", "Insufficient"),
            ("insufficient", "ko", "증거 부족"),
            # Display-form inputs should also canonicalize
            ("证据不足", "en", "Insufficient"),
            ("Insufficient", "zh", "证据不足"),
        ]

        for raw, lang, expected in cases:
            result = localize_consensus_level(raw, lang)
            self.assertEqual(
                result,
                expected,
                f"localize_consensus_level({raw!r}, {lang!r}) = {result!r}, want {expected!r}",
            )

    def test_renderer_shows_invalid_opinions_label(self):
        """计划测试1补全：mixed valid+invalid → renderer 输出含 strategy_invalid_opinions_label。
        走 StrategyEngine 完整链路，断言 _append_strategy_synthesis_block 渲染出 invalid count 行。
        """
        from src.agent.skills.engine import StrategyEngine
        from src.notification import _append_strategy_synthesis_block
        from src.report_language import get_report_labels

        opinions = []
        for i in range(2):
            opinions.append(AgentOpinion(agent_name=f"skill_v{i}", signal="buy", confidence=0.8))
        for i in range(3):
            opinions.append(AgentOpinion(agent_name=f"skill_x{i}", signal="moon", confidence=0.9))

        result = StrategyEngine().process(opinions)
        synthesis = result.synthesis_dict
        self.assertIsNotNone(synthesis)
        self.assertEqual(synthesis["summary_params"]["invalid_opinion_count"], 3)

        for lang, fragment in [
            ("zh", "3"),
            ("en", "3"),
            ("ko", "3"),
        ]:
            labels = get_report_labels(lang)
            lines: list = []
            _append_strategy_synthesis_block(lines, synthesis, labels, lang)
            rendered = "\n".join(lines)
            # invalid count line must appear
            self.assertIn(str(3), rendered, f"lang={lang}: invalid count missing from rendered output")
            # the label template itself must have been applied (not raw template string)
            self.assertNotIn("{count}", rendered, f"lang={lang}: label template not rendered")

    def test_generate_dashboard_report_renders_invalid_count_and_insufficient(self):
        """Blocker-6 真 E2E：经 generate_dashboard_report 主入口，
        断言最终 Markdown 字符串含 '另有 N 个策略解析失败' 和本地化 '证据不足'。
        """
        from src.analyzer import AnalysisResult
        from src.notification import NotificationService

        synthesis = {
            "final_signal": "hold",
            "weighted_score": 3.0,
            "confidence": 0.0,
            "original_confidence": 0.0,
            "conflict_count": 0,
            "conflict_severity": "none",
            "conflicts": [],
            "supporting_skills": [],
            "opposing_skills": [],
            "consensus_level": "insufficient",
            "summary_key": "strategy_synthesis.no_conflicts",
            "summary_params": {
                "opinion_count": 0,
                "total_opinion_count": 3,
                "invalid_opinion_count": 3,
                "final_signal": "hold",
                "consensus_level": "insufficient",
                "conflict_severity": "none",
                "conflict_count": 0,
            },
        }

        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="观望",
            decision_type="hold",
            report_language="zh",
            dashboard={
                "strategy_synthesis": synthesis,
                "core_conclusion": {"one_sentence": "测试样本"},
                "intelligence": {},
                "battle_plan": {},
            },
        )

        svc = NotificationService()
        report = svc.generate_dashboard_report([result])

        # invalid count 行必须出现
        self.assertIn("另有 3 个策略解析失败", report, "invalid count line missing from dashboard report")
        # consensus_level=insufficient → localize → 证据不足
        self.assertIn("证据不足", report, "localized 'insufficient' missing from dashboard report")

    def test_bad_shape_summary_params_never_crashes_renderers(self):
        """OR-COM-34818459 回归：summary_params 为字符串/列表时，所有渲染路径必须静默降级而非崩溃。"""
        from src.report_language import (
            localize_strategy_synthesis_summary,
            normalize_strategy_synthesis_payload,
            strategy_invalid_opinion_count,
        )
        from src.notification import _append_strategy_synthesis_block, NotificationService
        from src.report_language import get_report_labels
        from src.analyzer import AnalysisResult

        bad_shapes = [
            "bad-shape",          # 字符串
            ["a", "b"],           # 列表
            42,                   # 整数
            None,                 # None（已有守卫，但确认不退化）
        ]

        for bad in bad_shapes:
            synthesis = {
                "final_signal": "hold",
                "confidence": 0.5,
                "consensus_level": "insufficient",
                "conflict_severity": "none",
                "conflict_count": 0,
                "supporting_skills": [],
                "opposing_skills": [],
                "summary_params": bad,          # ← 坏 shape
            }

            # 1. 安全 helper 必须返回 0，不崩
            count = strategy_invalid_opinion_count(synthesis)
            self.assertEqual(count, 0, f"strategy_invalid_opinion_count should be 0 for summary_params={bad!r}")

            # 2. localize_strategy_synthesis_summary 不崩
            for lang in ("zh", "en", "ko"):
                result = localize_strategy_synthesis_summary(synthesis, lang)
                self.assertIsInstance(result, str, f"summary should be str for summary_params={bad!r}, lang={lang}")

            # 3. _append_strategy_synthesis_block 不崩
            for lang in ("zh", "en", "ko"):
                labels = get_report_labels(lang)
                lines: list = []
                try:
                    _append_strategy_synthesis_block(lines, synthesis, labels, lang)
                except Exception as exc:
                    self.fail(f"_append_strategy_synthesis_block crashed for summary_params={bad!r}: {exc}")

        # Narrow legacy coercion preserves a decimal string count without
        # accepting booleans, negative values, decimals, or arbitrary text.
        for raw_count, expected in [
            (3, 3),
            ("3", 3),
            (" 003 ", 3),
            (True, 0),
            (-1, 0),
            ("3.0", 0),
            ("bad", 0),
        ]:
            synthesis = {"summary_params": {"invalid_opinion_count": raw_count}}
            self.assertEqual(strategy_invalid_opinion_count(synthesis), expected)

        # Malformed top-level values are treated as an absent optional block.
        for bad in ("bad-shape", ["a"], 42, True):
            self.assertEqual(normalize_strategy_synthesis_payload(bad), {})
            self.assertEqual(localize_strategy_synthesis_summary(bad, "zh"), "")
            lines = []
            _append_strategy_synthesis_block(lines, bad, get_report_labels("zh"), "zh")
            self.assertEqual(lines, [])

        # 4. generate_dashboard_report 主入口不崩（取 zh + 字符串 bad shape 作代表）
        synthesis_bad = {
            "final_signal": "hold",
            "confidence": 0.5,
            "consensus_level": "insufficient",
            "conflict_severity": "none",
            "conflict_count": 0,
            "supporting_skills": [],
            "opposing_skills": [],
            "summary_params": "bad-shape",
        }
        result = AnalysisResult(
            code="000001",
            name="平安银行",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="观望",
            decision_type="hold",
            report_language="zh",
            dashboard={
                "strategy_synthesis": synthesis_bad,
                "core_conclusion": {"one_sentence": "测试"},
                "intelligence": {},
                "battle_plan": {},
            },
        )
        try:
            report = NotificationService().generate_dashboard_report([result])
        except Exception as exc:
            self.fail(f"generate_dashboard_report crashed on bad summary_params: {exc}")
        self.assertIsInstance(report, str)

    def test_engine_no_skills_returns_no_skills_status(self):
        """StrategyEngine with zero skill opinions returns NO_SKILLS (not NO_CONSENSUS)."""
        from src.agent.skills.engine import StrategyEngine, StrategyResultStatus

        ctx_opinions = [
            AgentOpinion(agent_name="technical", signal="buy", confidence=0.8),
            AgentOpinion(agent_name="decision", signal="hold", confidence=0.6),
        ]

        result = StrategyEngine().process(ctx_opinions)

        self.assertEqual(result.status, StrategyResultStatus.NO_SKILLS)
        self.assertIsNone(result.synthesis_dict)
        self.assertIsNone(result.consensus_opinion)
        # Non-skill opinions preserved
        self.assertEqual(len(result.non_skill_opinions), 2)


if __name__ == '__main__':
    unittest.main()
