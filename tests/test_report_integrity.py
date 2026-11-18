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


class TestSniperPriceSanity(unittest.TestCase):
    """Deterministic sniper-point math/ATR sanity checks."""

    @staticmethod
    def _make_buy_result(
        *,
        decision_type: str = "buy",
        ideal_buy: str = "98.0",
        stop_loss: str = "94.0",
        take_profit: str = "110.0",
        current_price: float = 100.0,
    ) -> AnalysisResult:
        return AnalysisResult(
            code="600519",
            name="贵州茅台",
            trend_prediction="看多",
            sentiment_score=80,
            operation_advice="买入",
            analysis_summary="test",
            decision_type=decision_type,
            market_snapshot={"current_price": current_price},
            dashboard={
                "core_conclusion": {"one_sentence": "买入"},
                "intelligence": {"risk_alerts": []},
                "data_perspective": {"price_position": {"current_price": current_price}},
                "battle_plan": {
                    "sniper_points": {
                        "ideal_buy": ideal_buy,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                    }
                },
            },
        )

    def test_valid_buy_sniper_points_pass(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        res = self._make_buy_result(ideal_buy="98", stop_loss="94", take_profit="110", current_price=100.0)
        warnings = validate_sniper_price_sanity(res, {"atr14": 3.0})
        self.assertEqual(warnings, [])
        self.assertEqual(res.dashboard["data_perspective"]["price_sanity"], {"passed": True, "warnings": []})

    def test_inverted_stop_loss_and_take_profit_flagged(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        res = self._make_buy_result(ideal_buy="100", stop_loss="105", take_profit="95", current_price=100.0)
        warnings = validate_sniper_price_sanity(res)
        self.assertIn("stop_loss_above_current_price", warnings)
        self.assertIn("take_profit_below_current_price", warnings)
        self.assertIn("stop_loss_above_ideal_buy", warnings)
        self.assertFalse(res.dashboard["data_perspective"]["price_sanity"]["passed"])

    def test_low_reward_risk_and_atr_bounds_flagged(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        res = self._make_buy_result(ideal_buy="100", stop_loss="90", take_profit="105", current_price=100.0)
        warnings = validate_sniper_price_sanity(res, {"atr14": 1.0})
        self.assertIn("reward_risk_below_1", warnings)
        self.assertIn("stop_loss_too_wide_vs_atr", warnings)

        res_tight = self._make_buy_result(ideal_buy="100", stop_loss="99.8", take_profit="110", current_price=100.0)
        warnings_tight = validate_sniper_price_sanity(res_tight, {"atr14": 2.0})
        self.assertIn("stop_loss_too_tight_vs_atr", warnings_tight)

    def test_take_profit_must_exceed_planned_entry_without_atr(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        for take_profit in ("105", "110"):
            for current_price in (100.0, None):
                with self.subTest(take_profit=take_profit, current_price=current_price):
                    res = self._make_buy_result(
                        ideal_buy="110", stop_loss="95", take_profit=take_profit, current_price=current_price,
                    )
                    warnings = validate_sniper_price_sanity(res)
                    self.assertIn("take_profit_below_ideal_buy", warnings)
                    self.assertFalse(res.dashboard["data_perspective"]["price_sanity"]["passed"])
                    self.assertTrue(any(
                        "take_profit_below_ideal_buy" in alert
                        for alert in res.dashboard["intelligence"]["risk_alerts"]
                    ))

    def test_unparseable_points_and_hold_signal_do_not_error(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        res_hold = self._make_buy_result(decision_type="hold", stop_loss="105", take_profit="90")
        self.assertEqual(validate_sniper_price_sanity(res_hold), [])

        res_text = self._make_buy_result(ideal_buy="待定", stop_loss="N/A", take_profit="-")
        self.assertEqual(validate_sniper_price_sanity(res_text), [])

    def test_price_sanity_updates_and_clears_risk_alerts_on_downgrade(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        res = self._make_buy_result(ideal_buy="100", stop_loss="105", take_profit="95", current_price=100.0)
        res.dashboard["intelligence"]["risk_alerts"] = ["已有风险"]
        warnings = validate_sniper_price_sanity(res, {"trend_result": {"atr14": 2.0}})
        self.assertTrue(warnings)
        alerts = res.dashboard["intelligence"]["risk_alerts"]
        self.assertEqual(alerts[0], "已有风险")
        self.assertTrue(any(a.startswith("[点位校验]") for a in alerts))

        # Simulate decision_type downgraded to hold by downstream guardrail
        res.decision_type = "hold"
        warnings_after = validate_sniper_price_sanity(res, {"trend_result": {"atr14": 2.0}})
        self.assertEqual(warnings_after, [])
        self.assertEqual(res.dashboard["intelligence"]["risk_alerts"], ["已有风险"])
        self.assertTrue(res.dashboard["data_perspective"]["price_sanity"]["passed"])

    def test_single_agent_trend_analysis_context_propagates_atr14(self) -> None:
        from src.analyzer import validate_sniper_price_sanity

        res = self._make_buy_result(ideal_buy="100", stop_loss="99.8", take_profit="110", current_price=100.0)
        warnings = validate_sniper_price_sanity(res, {"trend_analysis": {"atr14": 2.0}})
        self.assertIn("stop_loss_too_tight_vs_atr", warnings)
