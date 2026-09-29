# -*- coding: utf-8 -*-
"""RSI formula tests for StockTrendAnalyzer."""

import unittest

import pandas as pd

from src.services.alert_indicators import _calculate_rsi as calculate_alert_rsi
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
    def test_calculate_rsi_uses_wilder_ema_for_report_periods(self) -> None:
        analyzer = StockTrendAnalyzer()
        df = pd.DataFrame({"close": REPORT_RSI_CLOSE})

        result = analyzer._calculate_rsi(df)
        latest = result.iloc[-1]

        self.assertAlmostEqual(float(latest["RSI_6"]), 69.01902761094098)
        self.assertAlmostEqual(float(latest["RSI_12"]), 68.1701033115944)
        self.assertAlmostEqual(float(latest["RSI_24"]), 68.04934582724741)

    def test_report_and_alert_rsi_use_same_formula_for_report_periods(self) -> None:
        analyzer = StockTrendAnalyzer()
        close = pd.Series(REPORT_RSI_CLOSE, dtype="float64")
        report_rsi = analyzer._calculate_rsi(pd.DataFrame({"close": close}))

        for period in (analyzer.RSI_SHORT, analyzer.RSI_MID, analyzer.RSI_LONG):
            with self.subTest(period=period):
                alert_rsi = calculate_alert_rsi(close, period)
                self.assertAlmostEqual(float(report_rsi[f"RSI_{period}"].iloc[-1]), float(alert_rsi.iloc[-1]))


if __name__ == "__main__":
    unittest.main()
