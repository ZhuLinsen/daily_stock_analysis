# -*- coding: utf-8 -*-
"""RSI formula tests for StockTrendAnalyzer."""

import math
import unittest

import pandas as pd

from src.services.alert_indicators import _calculate_rsi as calculate_alert_rsi
from src.services.screening import daily as screening_daily
from src.stock_analyzer import StockTrendAnalyzer


REPORT_RSI_CLOSE = [
    10,
    11,
    12,
    11,
    13,
    12,
    14,
    15,
    13,
    16,
    17,
    15,
    18,
    19,
    17,
    20,
    21,
    19,
    22,
    23,
    21,
    24,
    25,
    23,
    26,
]


class StockAnalyzerRsiTestCase(unittest.TestCase):
    def test_calculate_rsi_uses_wilder_for_report_periods(self) -> None:
        analyzer = StockTrendAnalyzer()
        df = pd.DataFrame({"close": REPORT_RSI_CLOSE})

        result = analyzer._calculate_rsi(df)
        latest = result.iloc[-1]

        # Wilder RSI seeded with the simple mean of the first `period` changes (TA-Lib).
        self.assertAlmostEqual(float(latest["RSI_6"]), 69.05771152621479)
        self.assertAlmostEqual(float(latest["RSI_12"]), 68.39342679214782)
        self.assertAlmostEqual(float(latest["RSI_24"]), 68.18181818181819)

    def test_report_and_alert_rsi_use_same_formula_for_report_periods(self) -> None:
        analyzer = StockTrendAnalyzer()
        close = pd.Series(REPORT_RSI_CLOSE, dtype="float64")
        report_rsi = analyzer._calculate_rsi(pd.DataFrame({"close": close}))

        for period in (analyzer.RSI_SHORT, analyzer.RSI_MID, analyzer.RSI_LONG):
            with self.subTest(period=period):
                alert_rsi = calculate_alert_rsi(close, period)
                self.assertAlmostEqual(float(report_rsi[f"RSI_{period}"].iloc[-1]), float(alert_rsi.iloc[-1]))


class ScreeningRsiTestCase(unittest.TestCase):
    def test_screening_rsi_matches_talib_wilder_reference(self) -> None:
        close = pd.Series(REPORT_RSI_CLOSE, dtype="float64")

        # talib.RSI(close, 14)[-1]; the old rolling-mean version returned 65.517.
        self.assertAlmostEqual(screening_daily._compute_rsi(close), 68.4606939553397)

    def test_screening_rsi_agrees_with_report_and_alert_rsi(self) -> None:
        close = pd.Series([20 + 3 * math.sin(i / 4) + 0.05 * i for i in range(200)], dtype="float64")
        screening_rsi = screening_daily._compute_rsi(close)
        alert_rsi = float(calculate_alert_rsi(close, 14).iloc[-1])

        # The old rolling-mean version returned 26.36 here and screened the stock as oversold.
        self.assertAlmostEqual(screening_rsi, alert_rsi, places=4)
        self.assertEqual(screening_daily._classify_rsi(screening_rsi), "neutral")

    def test_screening_rsi_returns_none_without_enough_or_any_price_change(self) -> None:
        self.assertIsNone(screening_daily._compute_rsi(pd.Series([10.0] * 14)))
        self.assertIsNone(screening_daily._compute_rsi(pd.Series([10.0] * 30)))



# Short history from review OR-COR-ea5fc833: 30 daily bars, the shortest valid
# DAILY_LOOKBACK_DAYS. The old ewm (seeded with a zero change) and the
# screening RSI disagreed here: 65.49 vs 72.04 for period 14.
SHORT_HISTORY_CLOSE = [float(100 + i) for i in range(19)] + [117.0] * 9 + [116.0, 115.0]


class RsiConsistencyTestCase(unittest.TestCase):
    def test_screening_alert_and_report_agree_on_short_history(self) -> None:
        close = pd.Series(SHORT_HISTORY_CLOSE, dtype="float64")
        analyzer = StockTrendAnalyzer()
        report = analyzer._calculate_rsi(pd.DataFrame({"close": close})).iloc[-1]

        screening_rsi = screening_daily._compute_rsi(close, 14)
        alert_rsi = float(calculate_alert_rsi(close, 14).iloc[-1])
        self.assertAlmostEqual(screening_rsi, 72.03601666264457)
        self.assertAlmostEqual(alert_rsi, screening_rsi, places=12)

        for period in (analyzer.RSI_SHORT, analyzer.RSI_MID, analyzer.RSI_LONG):
            with self.subTest(period=period):
                self.assertAlmostEqual(
                    float(report[f"RSI_{period}"]),
                    float(calculate_alert_rsi(close, period).iloc[-1]),
                    places=12,
                )
                self.assertAlmostEqual(
                    screening_daily._compute_rsi(close, period),
                    float(calculate_alert_rsi(close, period).iloc[-1]),
                    places=12,
                )

    def test_overbought_classification_matches_alert_threshold(self) -> None:
        close = pd.Series(SHORT_HISTORY_CLOSE, dtype="float64")
        screening_status = screening_daily._classify_rsi(screening_daily._compute_rsi(close, 14))
        alert_rsi = float(calculate_alert_rsi(close, 14).iloc[-1])

        self.assertEqual(screening_status, "overbought")
        self.assertGreaterEqual(alert_rsi, 70)

    def test_warmup_and_flat_prices_stay_neutral(self) -> None:
        close = pd.Series([10.0] * 20 + [11.0, 12.0], dtype="float64")
        alert = calculate_alert_rsi(close, 14)

        # Warm-up bars and bars with no price change yet are neutral (50), as before.
        self.assertTrue((alert.iloc[:20] == 50.0).all())
        self.assertIsNone(screening_daily._compute_rsi(pd.Series([10.0] * 20), 14))


if __name__ == "__main__":
    unittest.main()
