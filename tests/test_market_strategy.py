# -*- coding: utf-8 -*-
"""Tests for market strategy blueprints."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.core.market_profile import get_profile
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
            purpose="market_review:hk",
            market="hk",
        )
        self.assertEqual(overview.up_count, 3)


class TestTaiwanProfileAndBlueprint(unittest.TestCase):
    """台股复盘元数据：TW_PROFILE 与 TW_BLUEPRINT。"""

    def test_tw_profile_uses_twii_index_with_market_stats(self):
        profile = get_profile("tw")

        self.assertEqual(profile.region, "tw")
        self.assertEqual(profile.mood_index_code, "TWII")
        self.assertTrue(profile.has_market_stats)
        self.assertTrue(profile.has_sector_rankings)

    def test_tw_blueprint_region_and_title(self):
        blueprint = get_market_strategy_blueprint("tw")

        self.assertEqual(blueprint.region, "tw")
        self.assertIn("台湾市场三段式复盘策略", blueprint.title)

    def test_tw_blueprint_excludes_cn_semantics(self):
        block = get_market_strategy_blueprint("tw").to_prompt_block()

        self.assertNotIn("北向资金", block)
        self.assertNotIn("龙虎榜", block)
        self.assertNotIn("涨跌停", block)
        self.assertIn("三大法人", block)


class TestTaiwanMarketAnalyzer(unittest.TestCase):
    """台股 MarketAnalyzer 区域识别（M2 功能4，防第 150 行静默回退）。"""

    def test_tw_region_not_silently_falls_back_to_cn(self):
        analyzer = MarketAnalyzer(region="tw")

        self.assertEqual(analyzer.region, "tw")
        self.assertEqual(analyzer.profile.region, "tw")
        self.assertEqual(analyzer.profile.mood_index_code, "TWII")

    def test_tw_market_scope_name(self):
        analyzer = MarketAnalyzer(region="tw")

        self.assertEqual(analyzer._get_market_scope_name("zh"), "台湾市场")
        self.assertEqual(analyzer._get_market_scope_name("en"), "Taiwan market")

    def test_tw_turnover_unit_label_and_format(self):
        analyzer = MarketAnalyzer(region="tw")

        self.assertEqual(analyzer._get_turnover_unit_label(), "十亿新台币")
        self.assertEqual(analyzer._format_turnover_value(1e9), "1.00")

        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="en")):
            analyzer_en = MarketAnalyzer(region="tw")
        self.assertEqual(analyzer_en._get_turnover_unit_label(), "TWD bn")

    def test_tw_review_title_en(self):
        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="en")):
            analyzer = MarketAnalyzer(region="tw")

        self.assertEqual(analyzer._get_review_title("2026-03-06"), "## 2026-03-06 Taiwan Market Recap")

    def test_tw_index_hint_en(self):
        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="en")):
            analyzer = MarketAnalyzer(region="tw")

        hint = analyzer._get_index_hint()
        self.assertIn("TWII", hint)
        self.assertIn("TWOII", hint)

    def test_tw_strategy_blocks_localized_en(self):
        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="en")):
            analyzer = MarketAnalyzer(region="tw")

        prompt_block = analyzer._get_strategy_prompt_block()
        markdown_block = analyzer._get_strategy_markdown_block("en")

        self.assertIn("Taiwan Market Regime Strategy", prompt_block)
        self.assertNotIn("台湾市场三段式复盘策略", prompt_block)
        self.assertIn("### 6. Strategy Framework", markdown_block)
        self.assertNotIn("### 六、策略框架", markdown_block)

    def test_tw_prompt_uses_region_aware_zh_shell(self):
        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="zh")):
            analyzer = MarketAnalyzer(region="tw")

        prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

        self.assertIn("专业的台湾市场分析师", prompt)
        self.assertIn("## 2026-02-24 台湾市场大盘复盘", prompt)
        self.assertIn("台湾市场三段式复盘策略", prompt)

    def test_tw_prompt_uses_region_aware_english_shell(self):
        with patch("src.market_analyzer.get_config", return_value=SimpleNamespace(report_language="en")):
            analyzer = MarketAnalyzer(region="tw")

        prompt = analyzer._build_review_prompt(MarketOverview(date="2026-02-24"), [])

        self.assertIn("professional Taiwan market analyst", prompt)
        self.assertIn("## Market Breadth", prompt)
        self.assertIn("### 3. Fund Flows", prompt)
        self.assertIn("### 4. Sector Highlights", prompt)
        self.assertNotIn("### 3. News Catalysts", prompt)

    def test_tw_search_market_news_uses_taiwan_context_name(self):
        search_service = MagicMock()
        search_service.search_stock_news.return_value = None

        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        analyzer.search_service = search_service
        analyzer.profile = get_profile("tw")
        analyzer.region = "tw"
        analyzer.config = SimpleNamespace(report_language="zh")

        analyzer.search_market_news()

        self.assertEqual(
            search_service.search_stock_news.call_count,
            len(analyzer.profile.news_queries),
        )
        self.assertTrue(
            all(
                call.kwargs["stock_name"] == "台湾股市"
                for call in search_service.search_stock_news.call_args_list
            )
        )

    def test_tw_stats_block_uses_twd_billion_unit(self):
        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        analyzer.region = "tw"
        analyzer.profile = get_profile("tw")
        analyzer.config = SimpleNamespace(report_language="zh")

        overview = MarketOverview(
            date="2026-03-07",
            up_count=600,
            down_count=300,
            flat_count=10,
            limit_up_count=30,
            limit_down_count=10,
            total_amount=6_620_000_000.0,  # 原始 TWD（元）
        )

        block = analyzer._build_stats_block(overview)

        self.assertIn("台股成交额", block)
        self.assertIn("十亿新台币", block)
        self.assertNotIn("两市成交额", block)
        self.assertNotIn("6620000000", block)  # 不应出现未换算的原始元
        self.assertIn("6.62", block)  # 6.62 十亿新台币

    def test_tw_stats_block_and_prompt_warn_when_breadth_partial(self):
        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        analyzer.region = "tw"
        analyzer.profile = get_profile("tw")
        analyzer.strategy = get_market_strategy_blueprint("tw")
        analyzer.config = SimpleNamespace(report_language="zh")

        overview = MarketOverview(
            date="2026-03-07",
            up_count=600,
            down_count=300,
            flat_count=10,
            limit_up_count=30,
            limit_down_count=10,
            total_amount=6_620_000_000.0,
            market_stats_data_quality="partial",  # 单一交易所失败 -> 宽度不完整
        )

        block = analyzer._build_stats_block(overview)
        self.assertIn("宽度数据不完整", block)

        prompt = analyzer._build_review_prompt(overview, [])
        self.assertIn("宽度数据不完整", prompt)

    def test_tw_describe_turnover_normalizes_yuan_to_yi(self):
        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        analyzer.region = "tw"

        # 6.62B 原始元 = 66.2 亿元 → 远低于 9000 亿阈值，不应判「高活跃度」
        self.assertEqual(analyzer._describe_turnover(6_620_000_000.0), "缩量观望")
        self.assertEqual(analyzer._describe_turnover(500_000_000.0), "缩量观望")

    def test_tw_concept_rankings_skipped(self):
        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        analyzer.region = "tw"
        analyzer.profile = get_profile("tw")
        analyzer.config = SimpleNamespace(report_language="zh")
        analyzer.data_manager = MagicMock()

        overview = MarketOverview(date="2026-03-07")
        analyzer._get_concept_rankings(overview)

        # 台股无概念/题材数据源，不得调用 A 股概念链
        analyzer.data_manager.get_concept_rankings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
