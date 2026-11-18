# -*- coding: utf-8 -*-
"""
Unit tests for StockTrendAnalyzer._generate_signal bias and strong-trend relief logic (Issue #296).
"""

import math
import unittest
from unittest.mock import patch, MagicMock

from src.stock_analyzer import (
    BuySignal,
    StockTrendAnalyzer,
    TrendAnalysisResult,
    TrendStatus,
    VolumeStatus,
    MACDStatus,
    RSIStatus,
)
from src.schemas.decision_scale import action_for_score, decision_type_for_score, signal_key_for_score


def _make_result(
    code: str = "000001",
    trend_status: TrendStatus = TrendStatus.BULL,
    trend_strength: float = 50.0,
    bias_ma5: float = 0.0,
    volume_status: VolumeStatus = VolumeStatus.NORMAL,
    macd_status: MACDStatus = MACDStatus.BULLISH,
    rsi_status: RSIStatus = RSIStatus.NEUTRAL,
    support_ma5: bool = False,
    support_ma10: bool = False,
) -> TrendAnalysisResult:
    """Build TrendAnalysisResult with defaults for _generate_signal bias branch testing."""
    return TrendAnalysisResult(
        code=code,
        trend_status=trend_status,
        ma_alignment="",
        trend_strength=trend_strength,
        ma5=10.0,
        ma10=9.5,
        ma20=9.0,
        ma60=8.5,
        current_price=10.0,
        bias_ma5=bias_ma5,
        bias_ma10=0.0,
        bias_ma20=0.0,
        volume_status=volume_status,
        volume_ratio_5d=1.0,
        volume_trend="",
        support_ma5=support_ma5,
        support_ma10=support_ma10,
        macd_status=macd_status,
        rsi_status=rsi_status,
    )


class StockAnalyzerBiasTestCase(unittest.TestCase):
    """Tests for bias_ma5 and strong-trend relief in _generate_signal."""

    def setUp(self) -> None:
        self.analyzer = StockTrendAnalyzer()

    def _assert_contains(self, items: list, substring: str) -> None:
        """Assert at least one item contains the substring."""
        self.assertTrue(
            any(substring in s for s in items),
            msg=f"Expected substring '{substring}' in {items}",
        )

    def _assert_not_contains(self, items: list, substring: str) -> None:
        """Assert no item contains the substring."""
        self.assertFalse(
            any(substring in s for s in items),
            msg=f"Did not expect substring '{substring}' in {items}",
        )

    @patch("src.stock_analyzer.get_config")
    def test_bias_nan_defense(self, mock_get_config: MagicMock) -> None:
        """bias_ma5=NaN should be treated as 0.0 without exception."""
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=float("nan"),
        )
        self.analyzer._generate_signal(result)
        self.assertIsInstance(result.signal_score, (int, float))
        self.assertFalse(math.isnan(result.signal_score))

    @patch("src.stock_analyzer.get_config")
    def test_bias_negative_pullback(self, mock_get_config: MagicMock) -> None:
        """bias=-2% should yield '回踩买点'."""
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=-2.0,
        )
        self.analyzer._generate_signal(result)
        self._assert_contains(result.signal_reasons, "回踩买点")

    @patch("src.stock_analyzer.get_config")
    def test_bias_close_to_ma5(self, mock_get_config: MagicMock) -> None:
        """bias=1.5% should yield '介入好时机'."""
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=1.5,
        )
        self.analyzer._generate_signal(result)
        self._assert_contains(result.signal_reasons, "介入好时机")

    @patch("src.stock_analyzer.get_config")
    def test_bias_slightly_high(self, mock_get_config: MagicMock) -> None:
        """bias=4% (< base_threshold=5%) should yield '可小仓介入'."""
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=4.0,
        )
        self.analyzer._generate_signal(result)
        self._assert_contains(result.signal_reasons, "可小仓介入")

    @patch("src.stock_analyzer.get_config")
    def test_strong_trend_relaxed_threshold(self, mock_get_config: MagicMock) -> None:
        """STRONG_BULL + trend_strength=75 + bias=6% -> '可轻仓追踪' (effective=7.5%)."""
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(
            trend_status=TrendStatus.STRONG_BULL,
            trend_strength=75.0,
            bias_ma5=6.0,
        )
        self.analyzer._generate_signal(result)
        self._assert_contains(result.signal_reasons, "可轻仓追踪")
        self._assert_not_contains(result.risk_factors, "严禁追高")

    @patch("src.stock_analyzer.get_config")
    def test_non_strong_trend_strict_threshold(self, mock_get_config: MagicMock) -> None:
        """BULL + bias=6% -> '严禁追高!'."""
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(
            trend_status=TrendStatus.BULL,
            bias_ma5=6.0,
        )
        self.analyzer._generate_signal(result)
        self._assert_contains(result.risk_factors, "严禁追高")

    @patch("src.stock_analyzer.get_config")
    def test_strong_trend_exceed_effective(self, mock_get_config: MagicMock) -> None:
        """STRONG_BULL + trend_strength=80 + bias=10% -> '严禁追高!' (exceeds 7.5%)."""
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(
            trend_status=TrendStatus.STRONG_BULL,
            trend_strength=80.0,
            bias_ma5=10.0,
        )
        self.analyzer._generate_signal(result)
        self._assert_contains(result.risk_factors, "严禁追高")

    @patch("src.stock_analyzer.get_config")
    def test_boundary_at_base_threshold(self, mock_get_config: MagicMock) -> None:
        """The configured limit is inclusive, matching the final prompt."""
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(trend_status=TrendStatus.BULL, bias_ma5=5.0)
        self.analyzer._generate_signal(result)
        self._assert_contains(result.signal_reasons, "可小仓介入")
        self._assert_not_contains(result.risk_factors, "严禁追高")

    @patch("src.stock_analyzer.get_config")
    def test_effective_limit_boundaries_match_emitted_threshold(self, mock_get_config: MagicMock) -> None:
        for base, multiplier, status, expected in (
            (5.0, 1.5, TrendStatus.BULL, 9.0),
            (5.0, 1.5, TrendStatus.STRONG_BULL, 13.5),
            (5.004, 0.0, TrendStatus.BULL, 5.004),
            (1.0, 0.0, TrendStatus.BULL, 1.0),
            (40.0, 0.0, TrendStatus.STRONG_BULL, 60.0),
            (50.0, 0.0, TrendStatus.STRONG_BULL, 75.0),
            (80.0, 1.5, TrendStatus.STRONG_BULL, 120.0),
        ):
            for delta in (0.0, 0.001):
                with self.subTest(base=base, multiplier=multiplier, status=status, delta=delta):
                    mock_get_config.return_value.bias_threshold = base
                    mock_get_config.return_value.bias_atr_multiplier = multiplier
                    result = _make_result(
                        trend_status=status, trend_strength=80, bias_ma5=expected + delta,
                    )
                    result.atr14 = 0.6
                    self.analyzer._generate_signal(result)
                    self.assertEqual(result.effective_bias_threshold, expected)
                    if delta > 0:
                        self._assert_contains(result.risk_factors, "严禁追高")
                    else:
                        self._assert_not_contains(result.risk_factors, "严禁追高")

    @patch("src.stock_analyzer.get_config")
    def test_signal_thresholds_follow_canonical_score_scale(self, mock_get_config: MagicMock) -> None:
        mock_get_config.return_value.bias_threshold = 5.0
        cases = [
            (
                _make_result(
                    trend_status=TrendStatus.STRONG_BULL,
                    bias_ma5=-1.0,
                    volume_status=VolumeStatus.HEAVY_VOLUME_UP,
                    macd_status=MACDStatus.BULLISH,
                    rsi_status=RSIStatus.OVERBOUGHT,
                    support_ma5=True,
                    support_ma10=True,
                    trend_strength=75,
                ),
                BuySignal.STRONG_BUY,
                80,
                signal_key_for_score(80),
                action_for_score(80),
                decision_type_for_score(80),
            ),
            (
                _make_result(
                    trend_status=TrendStatus.STRONG_BULL,
                    bias_ma5=6.0,
                    volume_status=VolumeStatus.HEAVY_VOLUME_DOWN,
                    macd_status=MACDStatus.BULLISH,
                    rsi_status=RSIStatus.STRONG_BUY,
                    support_ma5=True,
                    support_ma10=True,
                ),
                BuySignal.BUY,
                60,
                signal_key_for_score(60),
                action_for_score(60),
                decision_type_for_score(60),
            ),
            (
                _make_result(
                    trend_status=TrendStatus.BULL,
                    bias_ma5=6.0,
                    volume_status=VolumeStatus.HEAVY_VOLUME_DOWN,
                    macd_status=MACDStatus.CROSSING_UP,
                    rsi_status=RSIStatus.OVERBOUGHT,
                ),
                BuySignal.WAIT,
                40,
                signal_key_for_score(40),
                action_for_score(40),
                decision_type_for_score(40),
            ),
            (
                _make_result(
                    trend_status=TrendStatus.STRONG_BULL,
                    bias_ma5=-1.5,
                    volume_status=VolumeStatus.SHRINK_VOLUME_DOWN,
                    macd_status=MACDStatus.GOLDEN_CROSS,
                    rsi_status=RSIStatus.OVERSOLD,
                    support_ma5=True,
                    support_ma10=True,
                    trend_strength=75,
                ),
                BuySignal.STRONG_BUY,
                97,
                signal_key_for_score(97),
                action_for_score(97),
                decision_type_for_score(97),
            ),
            (
                _make_result(
                    trend_status=TrendStatus.BULL,
                    bias_ma5=1.5,
                    volume_status=VolumeStatus.NORMAL,
                    macd_status=MACDStatus.BULLISH,
                    rsi_status=RSIStatus.NEUTRAL,
                    support_ma5=True,
                ),
                BuySignal.BUY,
                72,
                signal_key_for_score(72),
                action_for_score(72),
                decision_type_for_score(72),
            ),
            (
                _make_result(
                    trend_status=TrendStatus.CONSOLIDATION,
                    bias_ma5=1.5,
                    volume_status=VolumeStatus.NORMAL,
                    macd_status=MACDStatus.BULLISH,
                    rsi_status=RSIStatus.NEUTRAL,
                ),
                BuySignal.WAIT,
                53,
                signal_key_for_score(53),
                action_for_score(53),
                decision_type_for_score(53),
            ),
            (
                _make_result(
                    trend_status=TrendStatus.WEAK_BEAR,
                    bias_ma5=5.5,
                    volume_status=VolumeStatus.NORMAL,
                    macd_status=MACDStatus.BULLISH,
                    rsi_status=RSIStatus.WEAK,
                ),
                BuySignal.SELL,
                33,
                signal_key_for_score(33),
                action_for_score(33),
                decision_type_for_score(33),
            ),
            (
                _make_result(
                    trend_status=TrendStatus.BEAR,
                    bias_ma5=6.0,
                    volume_status=VolumeStatus.HEAVY_VOLUME_DOWN,
                    macd_status=MACDStatus.DEATH_CROSS,
                    rsi_status=RSIStatus.OVERBOUGHT,
                ),
                BuySignal.STRONG_SELL,
                8,
                signal_key_for_score(8),
                action_for_score(8),
                decision_type_for_score(8),
            ),
        ]

        for result, expected_signal, expected_score, expected_scale_key, expected_scale_action, expected_scale_decision_type in cases:
            with self.subTest(expected_signal=expected_signal):
                self.analyzer._generate_signal(result)
                self.assertEqual(result.signal_score, expected_score)
                self.assertEqual(signal_key_for_score(result.signal_score), expected_scale_key)
            self.assertEqual(action_for_score(result.signal_score), expected_scale_action)
            self.assertEqual(decision_type_for_score(result.signal_score), expected_scale_decision_type)
            self.assertEqual(result.buy_signal, expected_signal)

    @patch("src.stock_analyzer.get_config")
    def test_non_bull_high_score_falls_back_to_wait(self, mock_get_config: MagicMock) -> None:
        mock_get_config.return_value.bias_threshold = 5.0
        result = _make_result(
            trend_status=TrendStatus.WEAK_BEAR,
            bias_ma5=-1.5,
            volume_status=VolumeStatus.SHRINK_VOLUME_DOWN,
            macd_status=MACDStatus.GOLDEN_CROSS,
            rsi_status=RSIStatus.OVERSOLD,
            support_ma5=True,
            support_ma10=True,
        )
        self.analyzer._generate_signal(result)
        self.assertEqual(result.signal_score, 75)
        self.assertEqual(result.buy_signal, BuySignal.WAIT)

    @patch("src.stock_analyzer.get_config")
    def test_volatility_adaptive_bias_multiplier_widens_threshold_when_enabled(
        self,
        mock_get_config: MagicMock,
    ) -> None:
        mock_get_config.return_value.bias_threshold = 5.0
        mock_get_config.return_value.bias_atr_multiplier = 0.0
        static_res = _make_result(trend_status=TrendStatus.BULL, bias_ma5=7.0)
        static_res.atr14 = 0.6  # 6% of price=10.0
        self.analyzer._generate_signal(static_res)
        self.assertEqual(static_res.effective_bias_threshold, 5.0)
        self._assert_contains(static_res.risk_factors, "严禁追高")

        mock_get_config.return_value.bias_atr_multiplier = 1.5  # 1.5 * 6% = 9.0% > 5.0%
        adaptive_res = _make_result(trend_status=TrendStatus.BULL, bias_ma5=7.0)
        adaptive_res.atr14 = 0.6
        self.analyzer._generate_signal(adaptive_res)
        self.assertEqual(adaptive_res.effective_bias_threshold, 9.0)
        self._assert_contains(adaptive_res.signal_reasons, "可小仓介入")
        self._assert_not_contains(adaptive_res.risk_factors, "严禁追高")

    @patch("src.stock_analyzer.get_config")
    def test_agent_tool_preserves_real_atr_and_effective_limit(self, mock_get_config: MagicMock) -> None:
        import pandas as pd
        from src.agent.tools.analysis_tools import _handle_analyze_trend

        mock_get_config.return_value.bias_threshold = 5.0
        mock_get_config.return_value.bias_atr_multiplier = 1.5
        prior_close = (5 * 10 / 1.07 - 10) / 4
        close = pd.Series([prior_close] * 29 + [10.0])
        frame = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=30),
            "close": close, "high": close + 0.3, "low": close - 0.3, "volume": [1000] * 30,
        })
        expected = self.analyzer.analyze(frame.copy(), "000001")
        with patch("src.agent.tools.analysis_tools._fetch_trend_data", return_value=frame):
            actual = _handle_analyze_trend("000001")
        self.assertNotIn("error", actual)
        self.assertEqual(actual["atr14"], expected.atr14)
        self.assertEqual(actual["effective_bias_threshold"], expected.effective_bias_threshold)
        self.assertGreater(actual["effective_bias_threshold"], actual["bias_ma5"])
        self.assertAlmostEqual(actual["bias_ma5"], 7.0)
