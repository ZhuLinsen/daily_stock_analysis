# -*- coding: utf-8 -*-
"""Tests for market strategy blueprints."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.core.market_strategy import get_market_strategy_blueprint
from src.market_analyzer import MarketAnalyzer, MarketOverview


class TestMarketStrategyBlueprint(unittest.TestCase):
    """Validate CN/US strategy blueprint basics."""

    def test_cn_blueprint_contains_action_framework(self):
        blueprint = get_market_strategy_blueprint("cn")
        block = blueprint.to_prompt_block()

        self.assertIn("A股市场三段式复盘策略", block)
        self.assertIn("Action Framework", block)
        self.assertIn("进攻", block)

    def test_us_blueprint_contains_regime_strategy(self):
        blueprint = get_market_strategy_blueprint("us")
        block = blueprint.to_prompt_block()

        self.assertIn("US Market Regime Strategy", block)
        self.assertIn("Risk-on", block)
        self.assertIn("Macro & Flows", block)


class TestMarketAnalyzerStrategyPrompt(unittest.TestCase):
    """Validate strategy section is injected into prompt/report."""

    def test_cn_prompt_contains_strategy_plan_section(self):
        analyzer = MarketAnalyzer(region="cn")
        prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

        self.assertIn("明日交易计划", prompt)
        self.assertIn("A股市场三段式复盘策略", prompt)

    def test_us_prompt_contains_strategy_plan_section(self):
        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="en")):
            analyzer = MarketAnalyzer(region="us")

        prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

        self.assertIn("Strategy Plan", prompt)
        self.assertIn("US Market Regime Strategy", prompt)

    def test_us_prompt_localizes_strategy_markdown_when_report_language_is_zh(self):
        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="zh")):
            analyzer = MarketAnalyzer(region="us")

        prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

        self.assertIn("美股市场", prompt)
        self.assertNotIn("US Market Regime Strategy", prompt)
        self.assertNotIn("Strategy Blueprint", prompt)
        self.assertIn("风险偏好", prompt)

    def test_cn_prompt_uses_english_shell_when_report_language_is_en(self):
        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="en")):
            analyzer = MarketAnalyzer(region="cn")

        prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

        self.assertIn("# Today's Market Data", prompt)
        self.assertIn("### 1. Market Summary", prompt)
        self.assertIn("A-share Three-Phase Recap Strategy", prompt)
        self.assertNotIn("### 一、市场总结", prompt)
        self.assertNotIn("A股市场三段式复盘策略", prompt)

    def test_market_stats_passes_market_review_purpose(self):
        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        analyzer.region = "hk"
        analyzer.data_manager = MagicMock()
        analyzer.data_manager.get_market_stats.return_value = {
            "up_count": 3,
            "down_count": 2,
            "flat_count": 1,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "total_amount": 12.0,
        }
        overview = MarketOverview(date="2026-02-24")

        analyzer._get_market_statistics(overview)

        analyzer.data_manager.get_market_stats.assert_called_once_with(
            purpose="market_review:hk"
        )
        self.assertEqual(overview.up_count, 3)


if __name__ == "__main__":
    unittest.main()
