# -*- coding: utf-8 -*-
"""RSI formula tests for StockTrendAnalyzer."""

from datetime import datetime, timedelta
import math
import subprocess
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.services.alert_indicators import _calculate_rsi as calculate_alert_rsi, evaluate_indicator_alert
from src.services.screening import daily as screening_daily
from src.stock_analyzer import StockTrendAnalyzer
import src.utils.rsi as rsi_utils


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


class WilderRsiFallbackTestCase(unittest.TestCase):
    def test_numpy_fallback_matches_fin_primitives_across_series(self) -> None:
        if rsi_utils.fp is None:
            self.skipTest("fin_primitives is not installed in this environment")

        rng = np.random.default_rng(42)
        cases = [
            ([], 14),
            ([10.0, 11.0], 3),
            ([10.0, 11.0, 12.0, 11.0], 3),
            ([10.0] * 20, 14),
            ([10.0 + i for i in range(25)], 6),
            ([30.0 - i for i in range(25)], 6),
            (REPORT_RSI_CLOSE, 14),
            (SHORT_HISTORY_CLOSE, 14),
            ((100.0 + np.cumsum(rng.normal(0, 1.5, 200))).tolist(), 14),
        ]
        for values, period in cases:
            series = pd.Series(values, dtype="float64")
            for fill_warmup in (True, False):
                with self.subTest(length=len(values), period=period, fill_warmup=fill_warmup):
                    expected = rsi_utils.wilder_rsi(series, period, fill_warmup=fill_warmup)
                    with patch.object(rsi_utils, "fp", None):
                        actual = rsi_utils.wilder_rsi(series, period, fill_warmup=fill_warmup)
                    self.assertTrue(
                        np.allclose(expected.to_numpy(), actual.to_numpy(), rtol=0, atol=1e-12, equal_nan=True)
                    )

    def test_rsi_modules_import_and_compute_when_fin_primitives_missing(self) -> None:
        script = (
            "import sys\n"
            "class _BlockFinPrimitives:\n"
            "    def find_spec(self, fullname, path=None, target=None):\n"
            "        if fullname == 'fin_primitives' or fullname.startswith('fin_primitives.'):\n"
            "            raise ModuleNotFoundError(\"No module named 'fin_primitives'\")\n"
            "sys.meta_path.insert(0, _BlockFinPrimitives())\n"
            "import pandas as pd\n"
            "from src.utils.rsi import wilder_rsi\n"
            "from src.stock_analyzer import StockTrendAnalyzer\n"
            "from src.services.alert_indicators import _calculate_rsi\n"
            "from src.services.screening.daily import _compute_rsi\n"
            "s = pd.Series([10.0, 11.0, 12.0, 11.0, 13.0, 12.0, 14.0, 15.0], dtype='float64')\n"
            "r = wilder_rsi(s, 3)\n"
            "assert len(r) == len(s)\n"
            "assert round(float(_calculate_rsi(pd.Series([10.0, 9.0, 11.0, 10.0, 12.0]), 2).iloc[-1]), 6) == 76.923077\n"
            "assert _compute_rsi(pd.Series([float(100 + i) for i in range(19)] + [117.0]*9 + [116.0, 115.0]), 14) > 70\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_fallback_preserves_exact_threshold_classification_across_alert_screening_and_report(self) -> None:
        alert_closes = [10.00, 10.07] + [10.04] * 13 + [9.84]
        start_date = datetime(2026, 1, 1)
        alert_df = pd.DataFrame({
            "date": [start_date + timedelta(days=i) for i in range(len(alert_closes))],
            "close": alert_closes,
        })
        fixed_now = datetime(2026, 1, 20, 18, 0)
        params = {"period": 14, "threshold": 70.0, "direction": "below"}

        with patch.object(rsi_utils, "fp", None):
            fallback_eval = evaluate_indicator_alert("rsi_threshold", "600519", params, alert_df, now=fixed_now)
        self.assertEqual(fallback_eval.status, "triggered")

        screening_closes = pd.Series([5.00] * 28 + [5.98, 5.59], dtype="float64")
        with patch.object(rsi_utils, "fp", None):
            fallback_screen_rsi = screening_daily._compute_rsi(screening_closes, 14)
        self.assertEqual(fallback_screen_rsi, 70.0)
        self.assertEqual(screening_daily._classify_rsi(fallback_screen_rsi), "overbought")

        report_df = pd.DataFrame({"close": [5.00] * 11 + [5.14] + [5.08] * 13})
        analyzer = StockTrendAnalyzer()
        with patch.object(rsi_utils, "fp", None):
            fallback_report = analyzer._calculate_rsi(report_df)
        self.assertEqual(float(fallback_report["RSI_12"].iloc[-1]), 70.0)

        if rsi_utils.fp is not None:
            native_eval = evaluate_indicator_alert("rsi_threshold", "600519", params, alert_df, now=fixed_now)
            self.assertEqual(fallback_eval.status, native_eval.status)
            self.assertEqual(fallback_screen_rsi, screening_daily._compute_rsi(screening_closes, 14))
            native_report = analyzer._calculate_rsi(report_df)
            self.assertTrue(
                np.array_equal(
                    fallback_report["RSI_12"].to_numpy(),
                    native_report["RSI_12"].to_numpy(),
                    equal_nan=True,
                )
            )

    def test_fallback_rejects_non_finite_close_values(self) -> None:
        start_date = datetime(2026, 1, 1)
        fixed_now = datetime(2026, 1, 20, 18, 0)
        params = {"period": 2, "threshold": 70.0, "direction": "above"}

        for bad_val in (float("inf"), float("-inf"), 7.922816251426434e28, -1e29):
            with self.subTest(bad_val=bad_val):
                df = pd.DataFrame({
                    "date": [start_date + timedelta(days=i) for i in range(4)],
                    "close": [10.0, 9.0, 10.0, bad_val],
                })
                with patch.object(rsi_utils, "fp", None):
                    with self.assertRaises(ValueError):
                        evaluate_indicator_alert("rsi_threshold", "600519", params, df, now=fixed_now)
                if rsi_utils.fp is not None:
                    with self.assertRaises(ValueError):
                        evaluate_indicator_alert("rsi_threshold", "600519", params, df, now=fixed_now)

    def test_fallback_matches_fin_primitives_on_fixed_scale_threshold_and_overflow_cases(self) -> None:
        alert_like = pd.Series([10.00, 10.07] + [10.04] * 42, dtype="float64")
        screening_like = pd.Series([10.00] * 13 + [10.07] + [10.04] * 321, dtype="float64")

        with patch.object(rsi_utils, "fp", None):
            fb_alert = rsi_utils.wilder_rsi(alert_like, 2)
            fb_screen_val = screening_daily._compute_rsi(screening_like, 14)

        self.assertLess(float(fb_alert.iloc[-1]), 70.0)
        self.assertLess(float(fb_screen_val), 70.0)
        self.assertEqual(screening_daily._classify_rsi(fb_screen_val), "neutral")

        if rsi_utils.fp is not None:
            native_alert = rsi_utils.wilder_rsi(alert_like, 2)
            native_screen_val = screening_daily._compute_rsi(screening_like, 14)
            self.assertEqual(float(fb_alert.iloc[-1]), float(native_alert.iloc[-1]))
            self.assertEqual(fb_screen_val, native_screen_val)
            self.assertTrue(np.array_equal(fb_alert.to_numpy(), native_alert.to_numpy(), equal_nan=True))

        overflow_series = pd.Series([7.9e28, 0.0, 7.9e28, 0.0], dtype="float64")
        with patch.object(rsi_utils, "fp", None):
            with self.assertRaises(ValueError):
                rsi_utils.wilder_rsi(overflow_series, 2)
        if rsi_utils.fp is not None:
            with self.assertRaises(ValueError):
                rsi_utils.wilder_rsi(overflow_series, 2)

        in_range_max = pd.Series([7.922816251426433e28] * 4, dtype="float64")
        with patch.object(rsi_utils, "fp", None):
            fb_max = rsi_utils.wilder_rsi(in_range_max, 2)
        self.assertEqual(float(fb_max.iloc[-1]), 50.0)
        if rsi_utils.fp is not None:
            native_max = rsi_utils.wilder_rsi(in_range_max, 2)
            self.assertTrue(np.array_equal(fb_max.to_numpy(), native_max.to_numpy(), equal_nan=True))

    def test_fallback_rejects_underflow_to_zero_and_matches_native_boundaries(self) -> None:
        start_date = datetime(2026, 1, 1)
        fixed_now = datetime(2026, 1, 20, 18, 0)
        params = {"period": 2, "threshold": 30.0, "direction": "below"}

        # OR-COR-77c746c3: nonzero finite closes that quantize to 0 under 28-decimal bounds
        # must fail just like fin_primitives instead of evaluating as 0.0 and triggering alerts.
        for tiny_bad in (1e-30, -1e-30, 4.999999999999999e-29):
            with self.subTest(tiny_bad=tiny_bad):
                df = pd.DataFrame({
                    "date": [start_date + timedelta(days=i) for i in range(4)],
                    "close": [10.0, 11.0, 10.0, tiny_bad],
                })
                with patch.object(rsi_utils, "fp", None):
                    with self.assertRaises(ValueError):
                        evaluate_indicator_alert("rsi_threshold", "600519", params, df, now=fixed_now)
                if rsi_utils.fp is not None:
                    with self.assertRaises(ValueError):
                        evaluate_indicator_alert("rsi_threshold", "600519", params, df, now=fixed_now)

        # Short series (n <= period) with out-of-range values also validate input bounds.
        for short_closes in ([10.0, 1e-30], [10.0, 1e30]):
            with self.subTest(short_closes=short_closes):
                short_series = pd.Series(short_closes, dtype="float64")
                with patch.object(rsi_utils, "fp", None):
                    with self.assertRaises(ValueError):
                        rsi_utils.wilder_rsi(short_series, 2)
                if rsi_utils.fp is not None:
                    with self.assertRaises(ValueError):
                        rsi_utils.wilder_rsi(short_series, 2)

        # 5e-29 rounds half-up to 1e-28 and matches native fin_primitives bit-for-bit.
        for boundary_closes in (
            [10.0, 11.0, 10.0, 5e-29],
            [0.0, 5e-29, 0.0, 5e-29],
        ):
            with self.subTest(boundary_closes=boundary_closes):
                boundary_series = pd.Series(boundary_closes, dtype="float64")
                with patch.object(rsi_utils, "fp", None):
                    fb_vals = rsi_utils.wilder_rsi(boundary_series, 2)
                if rsi_utils.fp is not None:
                    native_vals = rsi_utils.wilder_rsi(boundary_series, 2)
                    self.assertTrue(
                        np.array_equal(fb_vals.to_numpy(), native_vals.to_numpy(), equal_nan=True)
                    )


if __name__ == "__main__":
    unittest.main()
