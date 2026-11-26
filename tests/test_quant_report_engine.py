# -*- coding: utf-8 -*-
"""Tests for Quantitative Factor & Sniper Risk/Reward Jinja2 report engine integration."""

from __future__ import annotations

from datetime import datetime, timedelta
import sys
import unittest
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from src.analyzer import AnalysisResult
from src.services.quant_report_helpers import (
    compute_sniper_risk_reward,
    extract_quant_factors,
    parse_strategy_price_value,
)
from src.services.report_renderer import render
from src.stock_analyzer import analyze_stock


def _sample_df(n: int = 80) -> pd.DataFrame:
    dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(n)]
    closes = [100.0 + i * 0.45 + 1.2 * np.sin(i / 4.0) for i in range(n)]
    return pd.DataFrame(
        {
            "date": dates,
            "open": [c - 0.3 for c in closes],
            "high": [c + 1.1 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1_000_000 + (i % 7) * 80_000 for i in range(n)],
        }
    )


def _make_result(
    *,
    language: str = "zh",
    quant_factors: dict | None = None,
    sniper: dict | None = None,
    context_snapshot: dict | None = None,
) -> AnalysisResult:
    result = AnalysisResult(
        code="600519",
        name="贵州茅台",
        trend_prediction="看多",
        sentiment_score=78,
        operation_advice="买入",
        analysis_summary="量价配合突破蓄势平台",
        decision_type="buy",
        report_language=language,
        dashboard={
            "core_conclusion": {"one_sentence": "量价共振上看前高"},
            "intelligence": {"risk_alerts": []},
            "battle_plan": {
                "sniper_points": sniper
                if sniper is not None
                else {
                    "ideal_buy": "1480元（回踩支撑）",
                    "secondary_buy": "1450元",
                    "stop_loss": "1400元",
                    "take_profit": "1680元",
                }
            },
        },
    )
    if context_snapshot is not None:
        result.context_snapshot = context_snapshot
    if quant_factors is not None:
        result.quant_factors = quant_factors
    return result


class QuantReportHelpersTests(unittest.TestCase):
    def test_parse_strategy_price_and_risk_reward(self) -> None:
        self.assertIsNone(parse_strategy_price_value("暂无理想买点：需先站稳MA5（52.68）"))
        self.assertIsNone(parse_strategy_price_value("需先站稳MA5（52.68）"))
        self.assertEqual(parse_strategy_price_value("站稳MA5（52.68）后看60元"), 60.0)
        self.assertIsNone(parse_strategy_price_value("Wait for 20-day moving average reclaim"))
        self.assertEqual(parse_strategy_price_value("首个止盈目标：风险回报比 2:1，止盈 60 元"), 60.0)
        self.assertEqual(parse_strategy_price_value("$1,480.50"), 1480.5)

        rr = compute_sniper_risk_reward(
            {
                "ideal_buy": "100元",
                "stop_loss": "92元",
                "take_profit": "120元",
            }
        )
        self.assertIsNotNone(rr)
        self.assertEqual(rr["ratio_display"], "1:2.5")
        self.assertEqual(rr["summary"], "1:2.5 (+20.0% / -8.0%)")

        # Invalid risk geometry (stop >= entry) yields None cleanly
        self.assertIsNone(
            compute_sniper_risk_reward(
                {"ideal_buy": "100", "stop_loss": "105", "take_profit": "120"}
            )
        )

    def test_stock_trend_analyzer_populates_quant_factors_and_extracts_across_snapshots(self) -> None:
        trend = analyze_stock(_sample_df(80), "600519")
        self.assertIsNotNone(trend.quant_factors)
        self.assertTrue(trend.quant_factors["sufficient_data"])

        # Extracted cleanly from AnalysisResult.quant_factors
        r_direct = _make_result(quant_factors=trend.quant_factors, language="zh")
        extracted_direct = extract_quant_factors(r_direct, report_language="zh")
        self.assertIsNotNone(extracted_direct)
        self.assertIn("score", extracted_direct)

        # Extracted cleanly from nested context_snapshot.trend_analysis.quant_factors
        r_ctx = _make_result(
            context_snapshot={"trend_analysis": {"quant_factors": trend.quant_factors}},
            language="en",
        )
        extracted_ctx = extract_quant_factors(r_ctx, report_language="en")
        self.assertIsNotNone(extracted_ctx)

        # Extracted cleanly from extra_context quant_factors_by_code map
        r_plain = _make_result(language="ko")
        extracted_extra = extract_quant_factors(
            r_plain,
            quant_factors_by_code={"600519": trend.quant_factors},
            report_language="ko",
        )
        self.assertIsNotNone(extracted_extra)

    def test_all_real_quant_regimes_localize_without_snake_case_leakage(self) -> None:
        regimes = (
            "trending_bullish",
            "trending_bearish",
            "volatility_squeeze",
            "oversold_rebound",
            "overbought_extension",
            "range_bound",
        )
        for lang in ("zh", "en", "ko"):
            for regime in regimes:
                payload = {
                    "sufficient_data": True,
                    "quant_composite_score": 68,
                    "quant_regime": regime,
                }
                extracted = extract_quant_factors(
                    _make_result(language=lang, quant_factors=payload),
                    report_language=lang,
                )
                self.assertIsNotNone(extracted)
                self.assertNotEqual(extracted["regime_label"], regime)
                self.assertNotIn("_", extracted["regime_label"])

    def test_pipeline_and_fill_price_position_propagate_quant_factors(self) -> None:
        from src.analyzer import fill_price_position_if_needed
        from src.config import Config
        from src.core.pipeline import StockAnalysisPipeline

        trend = analyze_stock(_sample_df(80), "600519")

        # Additive to_dict behavior: omitted when absent, included when populated
        plain = _make_result(quant_factors=None)
        self.assertNotIn("quant_factors", plain.to_dict())

        fill_price_position_if_needed(plain, trend)
        self.assertIsNotNone(plain.quant_factors)
        self.assertIn("quant_factors", plain.to_dict())

        # Pipeline _enhance_context preserves trend_result.quant_factors under enhanced_context.trend_analysis
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = Config(report_language="zh")
        pipeline.search_service = None
        enhanced = pipeline._enhance_context(
            context={"code": "600519", "today": {}, "yesterday": {}},
            realtime_quote=None,
            chip_data=None,
            trend_result=trend,
            stock_name="贵州茅台",
            fundamental_context={},
        )
        self.assertIn("quant_factors", enhanced["trend_analysis"])

        diag_result = _make_result(language="zh", quant_factors=None)
        diag_result.diagnostic_context_snapshot = {"enhanced_context": enhanced}
        extracted = extract_quant_factors(diag_result, report_language="zh")
        self.assertIsNotNone(extracted)
        self.assertEqual(extracted["score"], trend.quant_factors["quant_composite_score"])


class QuantReportRenderingTests(unittest.TestCase):
    def test_render_markdown_wechat_and_brief_trilingual_with_quant_and_rr(self) -> None:
        trend = analyze_stock(_sample_df(80), "600519")
        qf = dict(trend.quant_factors)
        qf["boll_squeeze"] = True

        md_zh = render("markdown", [_make_result(language="zh", quant_factors=qf)])
        self.assertIsNotNone(md_zh)
        self.assertIn("量化多因子透视", md_zh)
        self.assertIn("盈亏比测算", md_zh)
        self.assertIn("1:2.5 (+13.5% / -5.4%)", md_zh)
        self.assertIn("BOLL收口", md_zh)

        # Feishu markdown table escaping must remain valid
        from src.formatters import format_feishu_markdown

        feishu = format_feishu_markdown(md_zh)
        self.assertIn("量化多因子透视", feishu)
        self.assertNotIn("列4", feishu)

        md_en = render(
            "markdown",
            [_make_result(language="en", quant_factors=qf)],
            extra_context={"report_language": "en"},
        )
        self.assertIn("Quantitative Factors", md_en)
        self.assertIn("Risk / Reward", md_en)
        self.assertIn("BOLL Squeeze", md_en)

        md_ko = render(
            "markdown",
            [_make_result(language="ko", quant_factors=qf)],
            extra_context={"report_language": "ko"},
        )
        self.assertIn("정량 멀티팩터", md_ko)
        self.assertIn("손익비", md_ko)

        wechat_zh = render("wechat", [_make_result(language="zh", quant_factors=qf)])
        self.assertIsNotNone(wechat_zh)
        self.assertIn("📐 量化", wechat_zh)
        self.assertIn("盈亏比 1:2.5", wechat_zh)

        brief_en = render("brief", [_make_result(language="en", quant_factors=qf)])
        self.assertIsNotNone(brief_en)
        self.assertIn("Quant ", brief_en)
        self.assertIn("R:R 1:2.5", brief_en)

    def test_backward_compatible_when_quant_factors_absent(self) -> None:
        plain = _make_result(language="zh", quant_factors=None, sniper={"stop_loss": "110"})
        md = render("markdown", [plain])
        self.assertIsNotNone(md)
        self.assertNotIn("量化多因子透视", md)
        self.assertNotIn("盈亏比测算", md)

    def test_default_notification_service_parity_across_formats_when_renderer_disabled(self) -> None:
        from unittest import mock

        from src.config import Config
        from src.notification import NotificationService

        trend = analyze_stock(_sample_df(80), "600519")
        qf = dict(trend.quant_factors)
        qf["boll_squeeze"] = True

        with mock.patch("src.notification.get_config", return_value=Config(stock_list=[], report_renderer_enabled=False)):
            svc = NotificationService()

            dash_zh = svc.generate_dashboard_report([_make_result(language="zh", quant_factors=qf)])
            self.assertIn("量化多因子透视", dash_zh)
            self.assertIn("盈亏比测算", dash_zh)
            self.assertIn("1:2.5 (+13.5% / -5.4%)", dash_zh)
            self.assertIn("BOLL收口", dash_zh)

            dash_en = svc.generate_dashboard_report([_make_result(language="en", quant_factors=qf)])
            self.assertIn("Quantitative Factors", dash_en)
            self.assertIn("Risk / Reward", dash_en)
            self.assertIn("BOLL Squeeze", dash_en)

            wechat_zh = svc.generate_wechat_dashboard([_make_result(language="zh", quant_factors=qf)])
            self.assertIn("📐 量化", wechat_zh)
            self.assertIn("盈亏比 1:2.5", wechat_zh)

            brief_en = svc.generate_brief_report([_make_result(language="en", quant_factors=qf)])
            self.assertIn("Quant ", brief_en)
            self.assertIn("R:R 1:2.5", brief_en)

            single_zh = svc.generate_single_stock_report(_make_result(language="zh", quant_factors=qf))
            self.assertIn("量化多因子透视", single_zh)
            self.assertIn("盈亏比测算", single_zh)
            self.assertIn("1:2.5 (+13.5% / -5.4%)", single_zh)

            plain = _make_result(language="zh", quant_factors=None, sniper={"stop_loss": "110"})
            plain_dash = svc.generate_dashboard_report([plain])
            self.assertNotIn("量化多因子透视", plain_dash)
            self.assertNotIn("盈亏比测算", plain_dash)


if __name__ == "__main__":
    unittest.main()
