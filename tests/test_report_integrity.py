# -*- coding: utf-8 -*-
"""
===================================
Report Engine - Content integrity tests
===================================

Tests for check_content_integrity, apply_placeholder_fill, and retry/placeholder behavior.
"""

import json
import sys
import unittest
from unittest.mock import MagicMock, patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from src.analyzer import AnalysisResult, GeminiAnalyzer, check_content_integrity, apply_placeholder_fill


class TestCheckContentIntegrity(unittest.TestCase):
    """Content integrity check tests."""

    def test_pass_when_all_required_present(self) -> None:
        """Integrity passes when all mandatory fields are present."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            dashboard={
                "core_conclusion": {"one_sentence": "持有观望"},
                "intelligence": {"risk_alerts": []},
                "battle_plan": {"sniper_points": {"stop_loss": "110元"}},
            },
        )
        ok, missing = check_content_integrity(result)
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_pass_when_signal_attribution_missing(self) -> None:
        """Signal attribution is optional and does not enter missing_fields."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            dashboard={
                "core_conclusion": {"one_sentence": "持有观望"},
                "intelligence": {"risk_alerts": []},
                "battle_plan": {"sniper_points": {"stop_loss": "110元"}},
            },
        )
        ok, missing = check_content_integrity(result)
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_fail_when_analysis_summary_empty(self) -> None:
        """Integrity fails when analysis_summary is empty."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="",
            decision_type="hold",
            dashboard={
                "core_conclusion": {"one_sentence": "持有"},
                "intelligence": {"risk_alerts": []},
                "battle_plan": {"sniper_points": {"stop_loss": "110"}},
            },
        )
        ok, missing = check_content_integrity(result)
        self.assertFalse(ok)
        self.assertIn("analysis_summary", missing)

    def test_fail_when_one_sentence_missing(self) -> None:
        """Integrity fails when core_conclusion.one_sentence is missing."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            dashboard={
                "core_conclusion": {},
                "intelligence": {"risk_alerts": []},
                "battle_plan": {"sniper_points": {"stop_loss": "110"}},
            },
        )
        ok, missing = check_content_integrity(result)
        self.assertFalse(ok)
        self.assertIn("dashboard.core_conclusion.one_sentence", missing)

    def test_fail_when_one_sentence_blank(self) -> None:
        """Integrity fails when one_sentence is blank whitespace."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            dashboard={
                "core_conclusion": {"one_sentence": "   "},
                "intelligence": {"risk_alerts": []},
                "battle_plan": {"sniper_points": {"stop_loss": "110"}},
            },
        )
        ok, missing = check_content_integrity(result)
        self.assertFalse(ok)
        self.assertIn("dashboard.core_conclusion.one_sentence", missing)

    def test_fail_when_stop_loss_missing_for_buy(self) -> None:
        """Integrity fails when stop_loss missing and decision_type is buy."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="买入",
            analysis_summary="稳健",
            decision_type="buy",
            dashboard={
                "core_conclusion": {"one_sentence": "可买入"},
                "intelligence": {"risk_alerts": []},
                "battle_plan": {"sniper_points": {}},
            },
        )
        ok, missing = check_content_integrity(result)
        self.assertFalse(ok)
        self.assertIn("dashboard.battle_plan.sniper_points.stop_loss", missing)

    def test_pass_when_stop_loss_missing_for_sell(self) -> None:
        """Integrity passes when stop_loss missing and decision_type is sell."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看空",
            sentiment_score=35,
            operation_advice="卖出",
            analysis_summary="弱势",
            decision_type="sell",
            dashboard={
                "core_conclusion": {"one_sentence": "建议卖出"},
                "intelligence": {"risk_alerts": []},
                "battle_plan": {"sniper_points": {}},
            },
        )
        ok, missing = check_content_integrity(result)
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_fail_when_risk_alerts_missing(self) -> None:
        """Integrity fails when intelligence.risk_alerts field is missing."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            dashboard={
                "core_conclusion": {"one_sentence": "持有"},
                "intelligence": {},
                "battle_plan": {"sniper_points": {"stop_loss": "110"}},
            },
        )
        ok, missing = check_content_integrity(result)
        self.assertFalse(ok)
        self.assertIn("dashboard.intelligence.risk_alerts", missing)

    def test_phase_decision_missing_only_when_required(self) -> None:
        """Phase decision fields are required only for phase-aware analysis."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            dashboard={
                "core_conclusion": {"one_sentence": "持有"},
                "intelligence": {"risk_alerts": []},
                "battle_plan": {"sniper_points": {"stop_loss": "110"}},
            },
        )

        ok, missing = check_content_integrity(result)
        self.assertTrue(ok)
        self.assertEqual(missing, [])

        ok, missing = check_content_integrity(result, require_phase_decision=True)
        self.assertFalse(ok)
        self.assertIn("dashboard.phase_decision.phase_context", missing)
        self.assertIn("dashboard.phase_decision.watch_conditions", missing)
        self.assertIn("dashboard.phase_decision.data_limitations", missing)

    def test_fail_when_risk_alerts_is_none(self) -> None:
        """Integrity fails when risk_alerts is None."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            dashboard={
                "core_conclusion": {"one_sentence": "持有"},
                "intelligence": {"risk_alerts": None},
                "battle_plan": {"sniper_points": {"stop_loss": "110"}},
            },
        )
        ok, missing = check_content_integrity(result)
        self.assertFalse(ok)
        self.assertIn("dashboard.intelligence.risk_alerts", missing)

    def test_fail_when_risk_alerts_is_invalid_type(self) -> None:
        """Integrity fails when risk_alerts is not list."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            dashboard={
                "core_conclusion": {"one_sentence": "持有"},
                "intelligence": {"risk_alerts": "需留意"},
                "battle_plan": {"sniper_points": {"stop_loss": "110"}},
            },
        )
        ok, missing = check_content_integrity(result)
        self.assertFalse(ok)
        self.assertIn("dashboard.intelligence.risk_alerts", missing)

    def test_fail_when_stop_loss_is_blank(self) -> None:
        """Integrity fails when stop_loss is blank whitespace."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="买入",
            analysis_summary="稳健",
            decision_type="buy",
            dashboard={
                "core_conclusion": {"one_sentence": "可买入"},
                "intelligence": {"risk_alerts": []},
                "battle_plan": {"sniper_points": {"stop_loss": "   "}},
            },
        )
        ok, missing = check_content_integrity(result)
        self.assertFalse(ok)
        self.assertIn("dashboard.battle_plan.sniper_points.stop_loss", missing)


class TestApplyPlaceholderFill(unittest.TestCase):
    """Placeholder fill tests."""

    def test_fills_missing_analysis_summary(self) -> None:
        """Placeholder fills analysis_summary when missing."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="",
            decision_type="hold",
            dashboard={},
        )
        apply_placeholder_fill(result, ["analysis_summary"])
        self.assertEqual(result.analysis_summary, "待补充")

    def test_fills_missing_analysis_summary_in_english(self) -> None:
        """English report should use English placeholder text for missing analysis_summary."""
        result = AnalysisResult(
            code="600519",
            name="MacaoTech",
            report_language="en",
            trend_prediction="Bullish",
            sentiment_score=70,
            operation_advice="Buy",
            analysis_summary="",
            decision_type="buy",
            dashboard={},
        )
        apply_placeholder_fill(result, ["analysis_summary"])
        self.assertEqual(result.analysis_summary, "TBD")

    def test_fills_missing_stop_loss(self) -> None:
        """Placeholder fills stop_loss when missing."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="买入",
            analysis_summary="稳健",
            decision_type="buy",
            dashboard={"battle_plan": {"sniper_points": {}}},
        )
        apply_placeholder_fill(result, ["dashboard.battle_plan.sniper_points.stop_loss"])
        self.assertEqual(
            result.dashboard["battle_plan"]["sniper_points"]["stop_loss"],
            "待补充",
        )

    def test_fills_risk_alerts_empty_list(self) -> None:
        """Placeholder fills risk_alerts with empty list when missing."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            dashboard={"intelligence": {}},
        )
        apply_placeholder_fill(result, ["dashboard.intelligence.risk_alerts"])
        self.assertEqual(result.dashboard["intelligence"]["risk_alerts"], [])

    def test_fills_risk_alerts_when_none(self) -> None:
        """Placeholder fills risk_alerts when value is None."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            risk_warning="注意融资",
            dashboard={"intelligence": {"risk_alerts": None}},
        )
        apply_placeholder_fill(result, ["dashboard.intelligence.risk_alerts"])
        self.assertEqual(result.dashboard["intelligence"]["risk_alerts"], ["注意融资"])

    def test_fills_risk_alerts_when_invalid_type(self) -> None:
        """Placeholder fills risk_alerts when value is non-list."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            dashboard={"intelligence": {"risk_alerts": "注意回撤"}},
        )
        apply_placeholder_fill(result, ["dashboard.intelligence.risk_alerts"])
        self.assertEqual(result.dashboard["intelligence"]["risk_alerts"], [])

    def test_fills_risk_alerts_when_risk_warning_is_list(self) -> None:
        """Placeholder handles list risk_warning and flattens valid text values."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            risk_warning=["回撤风险", "波动加大"],
            dashboard={"intelligence": {"risk_alerts": ""}},
        )
        apply_placeholder_fill(result, ["dashboard.intelligence.risk_alerts"])
        self.assertEqual(result.dashboard["intelligence"]["risk_alerts"], ["回撤风险", "波动加大"])

    def test_fills_risk_alerts_when_risk_warning_is_dict(self) -> None:
        """Placeholder serializes dict risk_warning into a string risk alert."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="持有",
            analysis_summary="稳健",
            decision_type="hold",
            risk_warning={"note": "技术面偏弱"},
            dashboard={"intelligence": {"risk_alerts": ""}},
        )
        apply_placeholder_fill(result, ["dashboard.intelligence.risk_alerts"])
        self.assertEqual(
            json.loads(result.dashboard["intelligence"]["risk_alerts"][0]),
            {"note": "技术面偏弱"},
        )

    def test_fills_stop_loss_when_blank(self) -> None:
        """Placeholder fills stop_loss when blank whitespace."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="买入",
            analysis_summary="稳健",
            decision_type="buy",
            dashboard={"battle_plan": {"sniper_points": {"stop_loss": "   "}}},
        )
        apply_placeholder_fill(result, ["dashboard.battle_plan.sniper_points.stop_loss"])
        self.assertEqual(
            result.dashboard["battle_plan"]["sniper_points"]["stop_loss"],
            "待补充",
        )

    def test_fills_stop_loss_when_invalid_type(self) -> None:
        """Placeholder fills stop_loss when value is invalid type."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="买入",
            analysis_summary="稳健",
            decision_type="buy",
            dashboard={"battle_plan": {"sniper_points": {"stop_loss": {}}}},
        )
        apply_placeholder_fill(result, ["dashboard.battle_plan.sniper_points.stop_loss"])
        self.assertEqual(
            result.dashboard["battle_plan"]["sniper_points"]["stop_loss"],
            "待补充",
        )

    def test_fills_none_dashboard_blocks_from_existing_context(self) -> None:
        """Placeholder fill handles null dashboard blocks and reuses existing result text."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=70,
            operation_advice="买入",
            analysis_summary="已有趋势摘要",
            risk_warning="跌破支撑需减仓",
            decision_type="buy",
            dashboard={
                "core_conclusion": None,
                "intelligence": None,
                "battle_plan": None,
            },
        )

        apply_placeholder_fill(
            result,
            [
                "dashboard.core_conclusion.one_sentence",
                "dashboard.intelligence.risk_alerts",
                "dashboard.battle_plan.sniper_points.stop_loss",
            ],
        )

        self.assertEqual(result.dashboard["core_conclusion"]["one_sentence"], "已有趋势摘要")
        self.assertEqual(result.dashboard["intelligence"]["risk_alerts"], ["跌破支撑需减仓"])
        self.assertEqual(result.dashboard["battle_plan"]["sniper_points"]["stop_loss"], "待补充")

    def test_phase_decision_placeholder_fill_satisfies_integrity_contract(self) -> None:
        """Phase placeholders close the retry-exhausted integrity contract without fake conditions."""
        result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="震荡",
            sentiment_score=50,
            operation_advice="持有",
            analysis_summary="已有摘要",
            decision_type="hold",
            dashboard={
                "core_conclusion": {"one_sentence": "持有观望"},
                "intelligence": {"risk_alerts": []},
                "battle_plan": {"sniper_points": {"stop_loss": "100"}},
                "phase_decision": {
                    "phase_context": "invalid",
                    "watch_conditions": "invalid",
                    "data_limitations": None,
                },
            },
        )

        ok, missing = check_content_integrity(result, require_phase_decision=True)
        self.assertFalse(ok)

        apply_placeholder_fill(result, missing)

        ok, missing = check_content_integrity(result, require_phase_decision=True)
        self.assertTrue(ok)
        self.assertEqual(missing, [])
        phase_decision = result.dashboard["phase_decision"]
        self.assertEqual(phase_decision["phase_context"], {})
        self.assertEqual(phase_decision["watch_conditions"], [])
        self.assertEqual(phase_decision["data_limitations"], [])
        self.assertEqual(phase_decision["action_window"], "模型未提供阶段化行动窗口")
        self.assertEqual(phase_decision["immediate_action"], "模型未提供阶段化即时动作")
        self.assertEqual(phase_decision["next_check_time"], "模型未提供下一次检查点")
        self.assertEqual(phase_decision["confidence_reason"], "模型未提供阶段化置信度理由")


class TestIntegrityRetryPrompt(unittest.TestCase):
    """Retry prompt construction tests."""

    def test_retry_prompt_includes_previous_response(self) -> None:
        """Retry prompt should carry previous response so补全是增量的。"""
        with patch.object(GeminiAnalyzer, "_init_litellm", return_value=None):
            analyzer = GeminiAnalyzer()
        prompt = analyzer._build_integrity_retry_prompt(
            "原始提示",
            '{"analysis_summary": "已有内容"}',
            ["dashboard.core_conclusion.one_sentence"],
        )
        self.assertIn("原始提示", prompt)
        self.assertIn('{"analysis_summary": "已有内容"}', prompt)
        self.assertIn("dashboard.core_conclusion.one_sentence", prompt)


class TestSniperPriceSanityChecks(unittest.TestCase):
    """Deterministic sniper-point sanity checks and full downstream exit visibility."""

    @staticmethod
    def _make_buy_result(
        *,
        ideal_buy: str,
        stop_loss: str,
        take_profit: str,
        current_price: float = 100.0,
        risk_alerts=None,
        risk_warning: str = "既有风险提示",
        report_language: str = "zh",
    ) -> AnalysisResult:
        if risk_alerts is None:
            risk_alerts = [
                "既有风险1：短期获利盘回吐压力",
                "既有风险2：大宗商品价格波动",
                "既有风险3：行业估值处于历史偏高区间",
            ]
        return AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=80,
            trend_prediction="看多",
            operation_advice="买入",
            decision_type="buy",
            confidence_level="高",
            current_price=current_price,
            change_pct=1.2,
            report_language=report_language,
            risk_warning=risk_warning,
            dashboard={
                "core_conclusion": {
                    "one_sentence": "均线多头排列，可按纪律低吸",
                    "position_advice": {
                        "no_position": "分批建仓",
                        "has_position": "持有观察",
                    },
                },
                "intelligence": {
                    "sentiment_summary": "市场情绪偏积极",
                    "risk_alerts": list(risk_alerts),
                    "positive_catalysts": ["业绩稳健增长"],
                },
                "battle_plan": {
                    "sniper_points": {
                        "ideal_buy": ideal_buy,
                        "secondary_buy": "99元",
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                    }
                },
                "data_perspective": {
                    "price_position": {
                        "current_price": current_price,
                        "ma5": 98.0,
                        "ma10": 96.0,
                        "ma20": 93.0,
                        "bias_ma5": 2.04,
                    }
                },
            },
        )

    @staticmethod
    def _dummy_config(*, report_renderer_enabled: bool = False):
        from src.config import Config

        return Config(
            report_renderer_enabled=report_renderer_enabled,
            report_type="simple",
            report_summary_only=False,
            report_language="zh",
        )

    def test_valid_buy_passes_cleanly(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        result = self._make_buy_result(
            ideal_buy="98元",
            stop_loss="94元",
            take_profit="112元",
            current_price=100.0,
        )
        warnings = validate_sniper_price_sanity(result, emit_log=False)

        self.assertEqual(warnings, [])
        sanity = result.dashboard["data_perspective"]["price_sanity"]
        self.assertEqual(sanity["status"], "ok")
        self.assertFalse(sanity["inverted"])
        self.assertNotIn("atr14", sanity)
        self.assertEqual(len(result.dashboard["intelligence"]["risk_alerts"]), 3)

    def test_breakout_buy_and_percentage_sniper_text_do_not_false_trigger(self) -> None:
        """Breakout buy above current_price and % strings must not trigger inversion."""
        from src.analyzer import validate_sniper_price_sanity

        breakout = self._make_buy_result(
            ideal_buy="105元",
            stop_loss="102元",
            take_profit="115元",
            current_price=100.0,
        )
        warnings = validate_sniper_price_sanity(breakout, emit_log=False)
        self.assertIn("stop_loss_above_secondary_buy", warnings)
        self.assertTrue(breakout.dashboard["data_perspective"]["price_sanity"]["inverted"])

        pct_text = self._make_buy_result(
            ideal_buy="回踩确认",
            stop_loss="跌破 -5%",
            take_profit="上涨 15% 止盈",
            current_price=100.0,
        )
        pct_warnings = validate_sniper_price_sanity(pct_text, emit_log=False)
        self.assertEqual(pct_warnings, [])
        self.assertFalse(pct_text.dashboard["data_perspective"]["price_sanity"]["inverted"])

    def test_inverted_sniper_points_surface_across_all_report_exits(self) -> None:
        """Counterexample from PR #2561 review: 3 existing risks + inverted points.

        Must survive truncation in simple single-stock report (risks[:3]),
        WeChat dashboard (risks[:2], plain & Jinja), and share image
        (_merge_compact_list limit_items=2, limit_chars=36), and must not
        duplicate inside DecisionSignal risk_summary.
        """
        from datetime import date
        from src.analyzer import validate_sniper_price_sanity
        from src.notification import NotificationService
        from src.services.decision_signal_extractor import build_decision_signal_payload_from_report
        from src.share_image import _stock_data_from_payload

        result = self._make_buy_result(
            ideal_buy="110元",
            stop_loss="95元",
            take_profit="105元",
            current_price=100.0,
        )
        warnings = validate_sniper_price_sanity(result, emit_log=False)

        self.assertIn("take_profit_below_ideal_buy", warnings)
        sanity = result.dashboard["data_perspective"]["price_sanity"]
        self.assertEqual(sanity["status"], "warn")
        self.assertTrue(sanity["inverted"])

        expected_warning = "点位校验：止损/目标与买入价倒挂，请复核"
        self.assertLessEqual(len(expected_warning), 36)
        self.assertEqual(result.dashboard["intelligence"]["risk_alerts"][0], expected_warning)
        self.assertTrue(result.risk_warning.startswith(expected_warning))

        with patch("src.notification.get_config", return_value=self._dummy_config(report_renderer_enabled=False)):
            service = NotificationService()
            single_report = service.generate_single_stock_report(result)
            self.assertIn(expected_warning, single_report)

            wechat_plain = service.generate_wechat_dashboard([result])
            self.assertIn(expected_warning, wechat_plain)

        with patch("src.notification.get_config", return_value=self._dummy_config(report_renderer_enabled=True)):
            service_jinja = NotificationService()
            wechat_jinja = service_jinja.generate_wechat_dashboard([result])
            self.assertIn(expected_warning, wechat_jinja)

        poster = _stock_data_from_payload(
            result.to_dict(),
            single_report,
            date(2026, 11, 20),
        )
        self.assertIn(expected_warning, poster.risks)

        signal_payload = build_decision_signal_payload_from_report(
            result,
            trace_id="trace-sanity-1",
            query_source="manual",
            report_type="detailed",
            profile_source="auto_default",
        )
        assert signal_payload is not None
        risk_summary = signal_payload.get("risk_summary") or []
        hits = sum(1 for item in risk_summary if expected_warning in item)
        self.assertEqual(hits, 1)

    def test_non_buy_skips_buy_inversion_alert_and_is_idempotent(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        watch_result = self._make_buy_result(
            ideal_buy="110元",
            stop_loss="95元",
            take_profit="105元",
            current_price=100.0,
        )
        watch_result.decision_type = "hold"
        watch_result.action = "watch"
        watch_result.operation_advice = "观望"

        warnings = validate_sniper_price_sanity(watch_result, emit_log=False)
        self.assertEqual(warnings, [])
        self.assertFalse(watch_result.dashboard["data_perspective"]["price_sanity"]["inverted"])
        self.assertEqual(len(watch_result.dashboard["intelligence"]["risk_alerts"]), 3)

        buy_result = self._make_buy_result(
            ideal_buy="100元",
            stop_loss="102元",
            take_profit="120元",
            current_price=100.0,
        )
        first = validate_sniper_price_sanity(buy_result, emit_log=False)
        second = validate_sniper_price_sanity(buy_result, emit_log=False)
        self.assertIn("stop_loss_above_ideal_buy", first)
        self.assertEqual(first, second)
        self.assertEqual(
            buy_result.dashboard["intelligence"]["risk_alerts"].count(
                "点位校验：止损/目标与买入价倒挂，请复核"
            ),
            1,
        )
        self.assertEqual(
            buy_result.risk_warning.count("点位校验：止损/目标与买入价倒挂，请复核"),
            1,
        )

        no_ideal_result = self._make_buy_result(
            ideal_buy="-",
            stop_loss="102元",
            take_profit="120元",
            current_price=100.0,
        )
        no_ideal_warnings = validate_sniper_price_sanity(no_ideal_result, emit_log=False)
        self.assertIn("stop_loss_above_secondary_buy", no_ideal_warnings)

    def test_absolute_price_is_extracted_when_percentage_is_also_present(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        result = self._make_buy_result(
            ideal_buy="10% above spot at 110 USD",
            stop_loss="95 USD",
            take_profit="105 USD",
            current_price=100.0,
        )
        warnings = validate_sniper_price_sanity(result, emit_log=False)
        self.assertIn("take_profit_below_ideal_buy", warnings)
        self.assertEqual(
            result.dashboard["data_perspective"]["price_sanity"]["ideal_buy"],
            110.0,
        )

    def test_english_stop_loss_label_with_percentage_detects_inversion(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        result = self._make_buy_result(
            ideal_buy="100", stop_loss="Stop-loss: 105 (break below MA20 or 5%)",
            take_profit="115", report_language="en",
        )

        warnings = validate_sniper_price_sanity(result, emit_log=False)

        self.assertIn("stop_loss_above_ideal_buy", warnings)
        self.assertEqual(result.dashboard["data_perspective"]["price_sanity"]["stop_loss"], 105)
        self.assertIn("Price check: stop/target inverted", result.dashboard["intelligence"]["risk_alerts"])

    def test_grouped_currency_price_with_percentage_uses_full_amount(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        for ideal in (
            "1,100 USD, 10% above spot",
            "$1,100 (10% above spot)",
            "1,100 (10% above spot)",
            "1,100, 10% above spot",
        ):
            with self.subTest(ideal=ideal):
                result = self._make_buy_result(
                    ideal_buy=ideal, stop_loss="900 USD", take_profit="1,050 USD",
                    current_price=950,
                )
                result.dashboard["battle_plan"]["sniper_points"]["secondary_buy"] = None
                warnings = validate_sniper_price_sanity(result, emit_log=False)
                sanity = result.dashboard["data_perspective"]["price_sanity"]
                self.assertEqual(sanity["ideal_buy"], 1_100)
                self.assertEqual(warnings, ["take_profit_below_ideal_buy"])

    def test_sniper_price_overflow_keeps_validation_available(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        result = self._make_buy_result(ideal_buy=10 ** 400, stop_loss=90, take_profit=120)
        result.dashboard["battle_plan"]["sniper_points"]["secondary_buy"] = 85

        warnings = validate_sniper_price_sanity(result, emit_log=False)

        self.assertEqual(warnings, ["stop_loss_above_secondary_buy"])
        self.assertIsNone(result.dashboard["data_perspective"]["price_sanity"]["ideal_buy"])

    def test_relative_sniper_price_uses_named_reference(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        for expression, expected in (
            ("10% above MA20", 99.0),
            ("10% above spot, MA20 nearby", 110.0),
            ("10% below spot", 90.0),
            ("MA20 下方 1%", 89.1),
            ("10% above MA60", None),
            ("10% above resistance, spot nearby", None),
        ):
            with self.subTest(expression=expression):
                result = self._make_buy_result(
                    ideal_buy=expression, stop_loss="89 USD", take_profit="105 USD",
                    current_price=100,
                )
                validate_sniper_price_sanity(result, {"trend_result": {"ma20": 90}}, emit_log=False)
                sanity = result.dashboard["data_perspective"]["price_sanity"]
                self.assertEqual(sanity["ideal_buy"], expected)
                self.assertEqual(sanity["inverted"], expected == 110.0)
