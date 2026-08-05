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

    def test_jp_kr_prompt_uses_region_aware_english_shell(self):
        cases = [
            ("jp", "Japan market"),
            ("kr", "Korea market"),
        ]

        for region, market_scope_name in cases:
            with self.subTest(region=region), patch(
                "src.market_analyzer.get_config",
                return_value=SimpleNamespace(report_language="en"),
            ):
                analyzer = MarketAnalyzer(region=region)
                prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

            self.assertIn(f"professional {market_scope_name} analyst", prompt)
            self.assertIn("## Data Limits", prompt)
            self.assertIn("### 3. News Catalysts", prompt)
            self.assertNotIn("### 3. Fund Flows", prompt)
            self.assertNotIn("### 4. Sector Highlights", prompt)
            self.assertNotIn("Interpret what turnover, participation, and flow signals imply", prompt)
            self.assertNotIn("professional US/A/H market analyst", prompt)

    def test_us_prompt_localizes_strategy_markdown_when_report_language_is_zh(self):
        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="zh")):
            analyzer = MarketAnalyzer(region="us")

        prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

        self.assertIn("美股市场", prompt)
        self.assertNotIn("US Market Regime Strategy", prompt)
        self.assertNotIn("Strategy Blueprint", prompt)
        self.assertIn("风险偏好", prompt)

    def test_jp_kr_prompt_uses_region_aware_chinese_shell(self):
        cases = [
            ("jp", "日本市场", "日本市场三段式复盘策略"),
            ("kr", "韩国市场", "韩国市场三段式复盘策略"),
        ]

        for region, market_scope_name, strategy_title in cases:
            with self.subTest(region=region), patch(
                "src.market_analyzer.get_config",
                return_value=SimpleNamespace(report_language="zh"),
            ):
                analyzer = MarketAnalyzer(region=region)
                prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

            self.assertIn(f"专业的{market_scope_name}分析师", prompt)
            self.assertIn(f"结构化的{market_scope_name}大盘复盘报告", prompt)
            self.assertIn(f"## 2026-02-24 {market_scope_name}大盘复盘", prompt)
            self.assertIn("## 数据边界", prompt)
            self.assertIn("### 三、消息催化", prompt)
            self.assertIn(strategy_title, prompt)
            self.assertNotIn("### 三、板块主线", prompt)
            self.assertNotIn("### 四、资金与情绪", prompt)
            self.assertNotIn("解读成交额、涨跌停结构、市场宽度", prompt)
            self.assertNotIn("A/H/美股市场分析师", prompt)

    def test_cn_prompt_uses_english_shell_when_report_language_is_en(self):
        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="en")):
            analyzer = MarketAnalyzer(region="cn")

        prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

        self.assertIn("# Today's Market Data", prompt)
        self.assertIn("### 1. Market Summary", prompt)
        self.assertIn("A-share Three-Phase Recap Strategy", prompt)
        self.assertNotIn("### 一、市场总结", prompt)
        self.assertNotIn("A股市场三段式复盘策略", prompt)

    def test_jp_kr_strategy_blocks_are_localized_when_report_language_is_en(self):
        cases = [
            ("jp", "Japan Market Regime Strategy", "Macro & FX", "日本市场三段式复盘策略"),
            ("kr", "Korea Market Regime Strategy", "Technology Cycle", "韩国市场三段式复盘策略"),
        ]

        for region, title, dimension, chinese_title in cases:
            with self.subTest(region=region):
                with patch(
                    "src.market_analyzer.get_config",
                    return_value=SimpleNamespace(report_language="en"),
                ):
                    analyzer = MarketAnalyzer(region=region)

                prompt_block = analyzer._get_strategy_prompt_block()
                markdown_block = analyzer._get_strategy_markdown_block("en")

                self.assertIn(title, prompt_block)
                self.assertIn(dimension, prompt_block)
                self.assertNotIn(chinese_title, prompt_block)
                self.assertNotIn("只基于可得指数", prompt_block)
                self.assertIn("### 6. Strategy Framework", markdown_block)
                self.assertIn(dimension, markdown_block)
                self.assertNotIn("### 六、策略框架", markdown_block)

    def test_jp_kr_review_prompt_roles_are_market_aware(self):
        cases = [
            ("jp", "Japan market", "日本市场"),
            ("kr", "Korea market", "韩国市场"),
        ]

        for region, english_market, chinese_market in cases:
            with self.subTest(region=region, language="en"):
                with patch(
                    "src.market_analyzer.get_config",
                    return_value=SimpleNamespace(report_language="en"),
                ):
                    analyzer = MarketAnalyzer(region=region)

                prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

                self.assertIn(
                    f"You are a professional {english_market} analyst.",
                    prompt,
                )
                self.assertNotIn("US/A/H market analyst", prompt)

            with self.subTest(region=region, language="zh"):
                with patch(
                    "src.market_analyzer.get_config",
                    return_value=SimpleNamespace(report_language="zh"),
                ):
                    analyzer = MarketAnalyzer(region=region)

                prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

                self.assertIn(f"你是一位专业的{chinese_market}分析师", prompt)
                self.assertNotIn("A/H/美股市场分析师", prompt)

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
