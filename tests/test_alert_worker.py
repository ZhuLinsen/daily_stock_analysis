# -*- coding: utf-8 -*-
"""Alert worker tests for Issue #1202 P2."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

from data_provider.base import BaseFetcher, DataFetcherManager

from src.config import Config
from src.notification import ChannelAttemptResult, NotificationDispatchResult
from src.services.alert_indicators import (
    _calculate_rsi,
    compute_requested_days,
    compute_required_bars,
    evaluate_indicator_alert,
    normalize_indicator_parameters,
)
from src.services.alert_service import AlertService
from src.services.alert_worker import AlertWorker
from src.services.decision_signal_service import DecisionSignalService
from src.storage import AlertNotificationRecord, DatabaseManager


class AlertIndicatorHelperTestCase(unittest.TestCase):
    def test_required_bars_and_requested_days_are_stable(self) -> None:
        cases = {
            "ma_price_cross": ({"window": 20, "direction": "above"}, 21),
            "rsi_threshold": ({"period": 12, "threshold": 70, "direction": "above"}, 14),
            "macd_cross": (
                {"fast_period": 12, "slow_period": 26, "signal_period": 9, "direction": "bullish_cross"},
                36,
            ),
            "kdj_cross": ({"period": 9, "k_period": 3, "d_period": 3, "direction": "bullish_cross"}, 16),
            "cci_threshold": ({"period": 14, "threshold": 100, "direction": "above"}, 15),
            "kline_pattern": ({"patterns": ["red_three_soldiers"]}, 22),
        }
        self.assertEqual(
            compute_required_bars(
                "kline_pattern",
                normalize_indicator_parameters("kline_pattern", {"patterns": ["immortal_guide"]}),
            ),
            27,
        )

        for alert_type, (params, required_bars) in cases.items():
            normalized = normalize_indicator_parameters(alert_type, params)
            self.assertEqual(compute_required_bars(alert_type, normalized), required_bars)
            self.assertEqual(
                compute_requested_days(alert_type, normalized),
                min(max(required_bars * 3, required_bars + 30), 365),
            )

    def test_rejects_indicator_periods_that_exceed_fetchable_history(self) -> None:
        cases = [
            ("macd_cross", {"fast_period": 2, "slow_period": 250, "signal_period": 250}),
            ("kdj_cross", {"period": 250, "k_period": 250, "d_period": 250}),
        ]

        for alert_type, params in cases:
            with self.subTest(alert_type=alert_type):
                with self.assertRaisesRegex(ValueError, "at most 365 days"):
                    normalize_indicator_parameters(alert_type, params)

    def test_indicator_edge_cross_and_level_only_semantics(self) -> None:
        ma_params = normalize_indicator_parameters("ma_price_cross", {"window": 2, "direction": "above"})
        triggered = evaluate_indicator_alert(
            "ma_price_cross",
            "TEST",
            ma_params,
            pd.DataFrame({
                "date": pd.date_range("2026-01-01", periods=3),
                "close": [10, 9, 12],
            }),
        )
        level_only = evaluate_indicator_alert(
            "ma_price_cross",
            "TEST",
            ma_params,
            pd.DataFrame({
                "date": pd.date_range("2026-01-01", periods=3),
                "close": [10, 12, 13],
            }),
        )

        self.assertEqual(triggered.status, "triggered")
        self.assertEqual(level_only.status, "not_triggered")

    def test_rsi_uses_wilder_not_sma(self) -> None:
        # Wilder seeds with the mean of the first `period` changes (TA-Lib), then
        # smooths; a rolling SMA re-averages only the last `period` changes.
        close = pd.Series([10.0, 9.0, 11.0, 10.0, 12.0])
        old_sma_rsi = 66.66666666666666
        wilder_rsi = _calculate_rsi(close, 2)

        self.assertNotAlmostEqual(float(wilder_rsi.iloc[-1]), old_sma_rsi)
        self.assertAlmostEqual(float(wilder_rsi.iloc[-1]), 76.92307692307692)

    def test_rsi_alert_never_crosses_from_warmup_placeholder(self) -> None:
        # Review OR-COR-f904fc32: 13 bars only give one real RSI12, so an alert
        # must not compare it with the warm-up placeholder (50 -> 100 "cross").
        params_up = normalize_indicator_parameters(
            "rsi_threshold", {"period": 12, "threshold": 70, "direction": "above"}
        )
        params_down = normalize_indicator_parameters(
            "rsi_threshold", {"period": 12, "threshold": 30, "direction": "below"}
        )
        for bars, expected in ((13, "degraded"), (14, "not_triggered")):
            dates = pd.date_range("2026-01-01", periods=bars)
            rising = pd.DataFrame({"日期": dates, "收盘": [float(100 + i) for i in range(bars)]})
            falling = pd.DataFrame({"日期": dates, "收盘": [float(100 - i) for i in range(bars)]})
            with self.subTest(bars=bars, direction="above"):
                self.assertEqual(evaluate_indicator_alert("rsi_threshold", "TEST", params_up, rising).status, expected)
            with self.subTest(bars=bars, direction="below"):
                self.assertEqual(
                    evaluate_indicator_alert("rsi_threshold", "TEST", params_down, falling).status, expected
                )

    def test_indicator_formulas_cover_rsi_macd_kdj_cci_and_chinese_columns(self) -> None:
        rsi_params = normalize_indicator_parameters("rsi_threshold", {
            "period": 2,
            "threshold": 50,
            "direction": "above",
        })
        rsi = evaluate_indicator_alert(
            "rsi_threshold",
            "TEST",
            rsi_params,
            pd.DataFrame({"日期": pd.date_range("2026-01-01", periods=4), "收盘": [10, 11, 9, 12]}),
        )

        macd_params = normalize_indicator_parameters("macd_cross", {
            "fast_period": 2,
            "slow_period": 3,
            "signal_period": 2,
            "direction": "bullish_cross",
        })
        macd = evaluate_indicator_alert(
            "macd_cross",
            "TEST",
            macd_params,
            pd.DataFrame({
                "date": pd.date_range("2026-01-01", periods=7),
                "close": [10, 9, 8, 7, 6, 5, 10],
            }),
        )

        kdj_params = normalize_indicator_parameters("kdj_cross", {
            "period": 3,
            "k_period": 2,
            "d_period": 2,
            "direction": "bullish_cross",
        })
        kdj_close = [5, 5, 5, 5, 5, 5, 5, 6]
        kdj = evaluate_indicator_alert(
            "kdj_cross",
            "TEST",
            kdj_params,
            pd.DataFrame({
                "date": pd.date_range("2026-01-01", periods=len(kdj_close)),
                "high": [value + 1 for value in kdj_close],
                "low": [value - 1 for value in kdj_close],
                "close": kdj_close,
            }),
        )

        cci_params = normalize_indicator_parameters("cci_threshold", {
            "period": 3,
            "threshold": 50,
            "direction": "above",
        })
        cci_close = [5, 5, 6, 5, 7]
        cci = evaluate_indicator_alert(
            "cci_threshold",
            "TEST",
            cci_params,
            pd.DataFrame({
                "date": pd.date_range("2026-01-01", periods=len(cci_close)),
                "high": [value + 1 for value in cci_close],
                "low": [value - 1 for value in cci_close],
                "close": cci_close,
            }),
        )

        self.assertEqual(rsi.status, "triggered")
        # Changes +1, -2 seed RSI2 at 33.33; then +3 smooths to gain 1.75 / loss 0.5 = 77.78.
        self.assertAlmostEqual(rsi.observed_value, 77.77777777777777)
        self.assertEqual(macd.status, "triggered")
        self.assertAlmostEqual(macd.observed_value, 0.321823559670782)
        self.assertEqual(kdj.status, "triggered")
        self.assertAlmostEqual(kdj.observed_value, 4.166666666666664)
        self.assertEqual(cci.status, "triggered")
        self.assertAlmostEqual(cci.observed_value, 100.00000000000001)

    def test_indicator_degraded_paths_cover_missing_data_and_partial_bar(self) -> None:
        missing_columns = evaluate_indicator_alert(
            "cci_threshold",
            "TEST",
            normalize_indicator_parameters("cci_threshold", {"period": 3, "threshold": 100}),
            pd.DataFrame({"date": pd.date_range("2026-01-01", periods=4), "close": [1, 2, 3, 4]}),
        )
        partial = evaluate_indicator_alert(
            "ma_price_cross",
            "TEST",
            normalize_indicator_parameters("ma_price_cross", {"window": 2, "direction": "above"}),
            pd.DataFrame({
                "date": [date(2026, 5, 16), date(2026, 5, 17), date(2026, 5, 18), date(2026, 5, 19)],
                "close": [10, 9, 12, 8],
            }),
            now=pd.Timestamp("2026-05-19 15:00:00").to_pydatetime(),
        )

        self.assertEqual(missing_columns.status, "degraded")
        self.assertIn("missing high", missing_columns.message)
        self.assertEqual(partial.status, "triggered")
        self.assertEqual(partial.data_timestamp, pd.Timestamp("2026-05-18").to_pydatetime())

    def test_indicator_drops_unparseable_last_bar_before_cutoff(self) -> None:
        result = evaluate_indicator_alert(
            "ma_price_cross",
            "TEST",
            normalize_indicator_parameters("ma_price_cross", {"window": 2, "direction": "above"}),
            pd.DataFrame({
                "date": [date(2026, 5, 16), date(2026, 5, 17), date(2026, 5, 18), "not-a-date"],
                "close": [10, 11, 12, 8],
            }),
            now=pd.Timestamp("2026-05-19 15:00:00").to_pydatetime(),
        )

        self.assertEqual(result.status, "not_triggered")
        self.assertEqual(result.data_timestamp, pd.Timestamp("2026-05-18").to_pydatetime())

    def test_indicator_requires_two_closed_bars_for_edge_evaluation(self) -> None:
        result = evaluate_indicator_alert(
            "ma_price_cross",
            "TEST",
            normalize_indicator_parameters("ma_price_cross", {"window": 2, "direction": "above"}),
            pd.DataFrame({
                "date": [date(2026, 5, 18), "not-a-date"],
                "close": [10, 12],
            }),
            now=pd.Timestamp("2026-05-19 15:00:00").to_pydatetime(),
        )

        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.message, "insufficient closed bars for edge evaluation")
        self.assertEqual(result.data_timestamp, pd.Timestamp("2026-05-18").to_pydatetime())

    def test_kline_pattern_edge_trigger_volume_confirm_and_degraded_paths(self) -> None:
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_000_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_000_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_000_000.0),  # flat vol
        ]
        df_flat_vol = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df_flat_vol["date"] = pd.date_range("2026-01-05", periods=len(df_flat_vol), freq="B")
        last_dt_flat = pd.Timestamp(df_flat_vol["date"].iloc[-1]).date()
        now_flat = datetime(last_dt_flat.year, last_dt_flat.month, last_dt_flat.day, 15, 5)

        params_any = normalize_indicator_parameters("kline_pattern", {"patterns": ["red_three_soldiers"]})
        triggered = evaluate_indicator_alert("kline_pattern", "600519", params_any, df_flat_vol, now=now_flat)
        self.assertEqual(triggered.status, "triggered")
        self.assertIn("red_three_soldiers", triggered.message)

        # Edge-trigger does NOT fire a second time on 4th consecutive bullish candle
        df_fourth = pd.DataFrame(
            base + soldiers + [(21.6, 22.35, 21.55, 22.30, 2_000_000.0)],
            columns=["open", "high", "low", "close", "volume"],
        )
        df_fourth["date"] = pd.date_range("2026-01-05", periods=len(df_fourth), freq="B")
        last_dt_fourth = pd.Timestamp(df_fourth["date"].iloc[-1]).date()
        now_fourth = datetime(last_dt_fourth.year, last_dt_fourth.month, last_dt_fourth.day, 15, 5)
        repeated = evaluate_indicator_alert("kline_pattern", "600519", params_any, df_fourth, now=now_fourth)
        self.assertEqual(repeated.status, "not_triggered")

        # require_volume_confirm=True checks shape edge FIRST: flat Soldiers followed by high-vol 4th bar
        # must NOT masquerade as a new pattern on day 4!
        params_vol = normalize_indicator_parameters(
            "kline_pattern",
            {"patterns": ["red_three_soldiers"], "require_volume_confirm": True},
        )
        self.assertEqual(
            evaluate_indicator_alert("kline_pattern", "600519", params_vol, df_flat_vol, now=now_flat).status,
            "not_triggered",
        )
        self.assertEqual(
            evaluate_indicator_alert("kline_pattern", "600519", params_vol, df_fourth, now=now_fourth).status,
            "not_triggered",
        )

        df_high_vol = df_flat_vol.copy()
        df_high_vol.loc[df_high_vol.index[-1], "volume"] = 2_000_000.0
        self.assertEqual(
            evaluate_indicator_alert("kline_pattern", "600519", params_vol, df_high_vol, now=now_flat).status,
            "triggered",
        )

        # Volume-dependent pattern without volume column degrades instead of silently passing
        params_breakout = normalize_indicator_parameters("kline_pattern", {"patterns": ["breakout_20d_high"]})
        self.assertEqual(
            evaluate_indicator_alert(
                "kline_pattern",
                "600519",
                params_breakout,
                df_flat_vol.drop(columns=["volume"]),
                now=now_flat,
            ).status,
            "degraded",
        )

        # Interior NaN open bar must degrade instead of dropping & splicing distant bars into Soldiers
        interior_nan = df_flat_vol.copy()
        interior_nan.loc[interior_nan.index[-4], "open"] = float("nan")
        self.assertEqual(
            evaluate_indicator_alert("kline_pattern", "600519", params_any, interior_nan, now=now_flat).status,
            "degraded",
        )

        # Duplicate dates resolve by keeping last bar without corrupting detection
        dup_df = pd.concat([df_flat_vol, df_flat_vol.iloc[[-1]]], ignore_index=True)
        dup_res = evaluate_indicator_alert("kline_pattern", "600519", params_any, dup_df, now=now_flat)
        self.assertEqual(dup_res.status, "triggered")

        # Degrades on missing OHLC or insufficient history or corrupt latest OHLC
        missing_open = evaluate_indicator_alert(
            "kline_pattern",
            "600519",
            params_any,
            df_flat_vol.drop(columns=["open"]),
            now=now_flat,
        )
        self.assertEqual(missing_open.status, "degraded")
        short_df = evaluate_indicator_alert(
            "kline_pattern", "600519", params_any, df_flat_vol.iloc[-15:], now=now_flat
        )
        self.assertEqual(short_df.status, "degraded")
        corrupt_ohlc = df_flat_vol.copy()
        corrupt_ohlc.loc[corrupt_ohlc.index[-1], "high"] = corrupt_ohlc.loc[corrupt_ohlc.index[-1], "low"] - 0.5
        self.assertEqual(
            evaluate_indicator_alert("kline_pattern", "600519", params_any, corrupt_ohlc, now=now_flat).status,
            "degraded",
        )

    def test_kline_pattern_mixed_preset_missing_session_and_undated_last_row(self) -> None:
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(25)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df_soldiers = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df_soldiers["date"] = pd.date_range("2026-01-05", periods=len(df_soldiers), freq="B")
        last_dt = pd.Timestamp(df_soldiers["date"].iloc[-1]).date()
        now_closed = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)

        # 1) Mixed preset `any_bullish` without volume still triggers price-only Red Three Soldiers
        params_mixed = normalize_indicator_parameters("kline_pattern", {"patterns": ["any_bullish"]})
        mixed_no_vol = evaluate_indicator_alert(
            "kline_pattern",
            "600519",
            params_mixed,
            df_soldiers.drop(columns=["volume"]),
            now=now_closed,
        )
        self.assertEqual(mixed_no_vol.status, "triggered")
        self.assertIn("red_three_soldiers", mixed_no_vol.matched_patterns or [])
        self.assertEqual(
            set(mixed_no_vol.unavailable_patterns or []),
            {"immortal_guide", "breakout_20d_high", "ma_pullback_support"},
        )

        # Flat history without volume + mixed preset -> degrades cleanly reporting unavailable volume patterns
        df_flat = pd.DataFrame(
            [(20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02) for i in range(28)],
            columns=["open", "high", "low", "close"],
        )
        df_flat["date"] = pd.date_range("2026-01-05", periods=len(df_flat), freq="B")
        mixed_flat_no_vol = evaluate_indicator_alert("kline_pattern", "600519", params_mixed, df_flat, now=now_closed)
        self.assertEqual(mixed_flat_no_vol.status, "degraded")
        self.assertIn("immortal_guide", mixed_flat_no_vol.unavailable_patterns or [])

        # require_volume_confirm=True with missing volume still degrades even on Soldiers
        params_mixed_strict = normalize_indicator_parameters(
            "kline_pattern",
            {"patterns": ["any_bullish"], "require_volume_confirm": True},
        )
        self.assertEqual(
            evaluate_indicator_alert(
                "kline_pattern",
                "600519",
                params_mixed_strict,
                df_soldiers.drop(columns=["volume"]),
                now=now_closed,
            ).status,
            "degraded",
        )

        # 2) Omitted trading session in evaluation window must degrade (not bridge non-adjacent bars)
        params_soldiers = normalize_indicator_parameters("kline_pattern", {"patterns": ["red_three_soldiers"]})
        dates_gap = [ts for ts in pd.date_range("2026-01-05", periods=len(df_soldiers) + 1, freq="B")]
        # Drop Wednesday right before Soldiers completion
        dates_gap.pop(-4)
        df_gap = df_soldiers.copy()
        df_gap["date"] = dates_gap[: len(df_gap)]
        gap_last = pd.Timestamp(df_gap["date"].iloc[-1]).date()
        now_gap = datetime(gap_last.year, gap_last.month, gap_last.day, 15, 5)
        gap_eval = evaluate_indicator_alert("kline_pattern", "600519", params_soldiers, df_gap, now=now_gap)
        self.assertEqual(gap_eval.status, "degraded")
        self.assertIn("missing trading session", gap_eval.message)

        # 3) Undated final row before market close must degrade instead of dropping final row & firing preceding bar
        df_undated_last = pd.concat([df_soldiers, df_soldiers.iloc[[-1]].assign(date=pd.NaT)], ignore_index=True)
        pre_close_now = datetime(last_dt.year, last_dt.month, last_dt.day, 11, 0)
        undated_eval = evaluate_indicator_alert(
            "kline_pattern",
            "600519",
            params_soldiers,
            df_undated_last,
            now=pre_close_now,
        )
        self.assertEqual(undated_eval.status, "degraded")
        self.assertIn("missing", undated_eval.message)

    def test_kline_pattern_provider_delay_after_close_degrades_while_pre_close_previous_session_triggers(self) -> None:
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(22)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df_feb06 = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df_feb06["date"] = pd.date_range("2026-01-05", periods=25, freq="B")  # 25 genuine CN sessions ending 2026-02-06
        self.assertEqual(pd.Timestamp(df_feb06["date"].iloc[-1]).date(), date(2026, 2, 6))

        params = normalize_indicator_parameters("kline_pattern", {"patterns": ["red_three_soldiers"]})

        # Before Feb 9 CN close (effective closed session == Feb 6): Feb 6 signal is fresh and triggers
        pre_close_feb09 = evaluate_indicator_alert(
            "kline_pattern", "600519", params, df_feb06, now=datetime(2026, 2, 9, 11, 0)
        )
        self.assertEqual(pre_close_feb09.status, "triggered")

        # After Feb 9 CN close (effective closed session == Feb 9): stale Feb 6 frame must degrade
        post_close_feb09 = evaluate_indicator_alert(
            "kline_pattern", "600519", params, df_feb06, now=datetime(2026, 2, 9, 16, 0)
        )
        self.assertEqual(post_close_feb09.status, "degraded")
        self.assertIn("missing latest closed trading session", post_close_feb09.message)

    def test_kline_pattern_rejects_extra_weekend_non_trading_bars(self) -> None:
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(25)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),  # Sat 2026-02-07
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),  # Sun 2026-02-08
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),  # Mon 2026-02-09
        ]
        cn_sessions = list(pd.date_range("2026-01-05", periods=25, freq="B"))
        weekend_plus_mon = [pd.Timestamp("2026-02-07"), pd.Timestamp("2026-02-08"), pd.Timestamp("2026-02-09")]
        df_weekend = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df_weekend["date"] = cn_sessions + weekend_plus_mon

        params = normalize_indicator_parameters("kline_pattern", {"patterns": ["red_three_soldiers"]})
        res = evaluate_indicator_alert(
            "kline_pattern", "600519", params, df_weekend, now=datetime(2026, 2, 9, 16, 0)
        )
        self.assertEqual(res.status, "degraded")
        self.assertIn("unexpected non-trading session", res.message)

    def test_kline_pattern_degrades_when_known_exchange_calendar_unavailable(self) -> None:
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(22)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        # 2026-01-05..2026-02-06 includes 2026-01-19 (US MLK Day weekday holiday)
        df_us_holiday = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df_us_holiday["date"] = pd.date_range("2026-01-05", periods=25, freq="B")
        params = normalize_indicator_parameters("kline_pattern", {"patterns": ["red_three_soldiers"]})

        with_calendar = evaluate_indicator_alert(
            "kline_pattern", "AAPL", params, df_us_holiday, now=datetime(2026, 2, 6, 16, 30)
        )
        self.assertEqual(with_calendar.status, "degraded")
        self.assertIn("unexpected non-trading session", with_calendar.message)

        with patch("src.services.alert_indicators.get_trading_dates", return_value=None):
            without_calendar = evaluate_indicator_alert(
                "kline_pattern", "AAPL", params, df_us_holiday, now=datetime(2026, 2, 6, 16, 30)
            )
        self.assertEqual(without_calendar.status, "degraded")
        self.assertIn("trading calendar unavailable", without_calendar.message)


class AlertWorkerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.env_path = self.data_dir / ".env"
        self.db_path = self.data_dir / "alert_worker_test.db"
        self.env_path.write_text(
            "\n".join([
                "STOCK_LIST=600519",
                "GEMINI_API_KEY=test",
                "ADMIN_AUTH_ENABLED=false",
                f"DATABASE_PATH={self.db_path}",
            ])
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(self.db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.service = AlertService()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def _config(self, raw_rules: str = "") -> SimpleNamespace:
        return SimpleNamespace(
            agent_event_monitor_enabled=True,
            agent_event_alert_rules_json=raw_rules,
            trading_day_check_enabled=False,
        )

    def _create_rule(self, **overrides) -> dict:
        payload = {
            "name": "Moutai breakout",
            "target_scope": "single_symbol",
            "target": "600519",
            "alert_type": "price_cross",
            "parameters": {"direction": "above", "price": 1800},
            "severity": "warning",
            "enabled": True,
        }
        payload.update(overrides)
        return self.service.create_rule(payload)

    def _triggers(self, **filters) -> list[dict]:
        return self.service.list_triggers(page_size=100, **filters)["items"]

    def _notifications(self, **filters) -> list[dict]:
        return self.service.list_notifications(page_size=100, **filters)["items"]

    def _dispatch_result(
        self,
        success: bool = True,
        *,
        dispatched: bool = True,
        status: str | None = None,
        channel: str = "custom",
        error_code: str | None = None,
        delivery_confirmed_absent: bool = False,
    ) -> NotificationDispatchResult:
        if status is None:
            status = "sent" if success else "all_failed"
        channel_results = []
        if dispatched:
            channel_results.append(
                ChannelAttemptResult(
                    channel=channel,
                    success=success,
                    error_code=error_code if error_code is not None else (None if success else "send_failed"),
                    retryable=not success,
                    delivery_confirmed_absent=delivery_confirmed_absent,
                )
            )
        return NotificationDispatchResult(
            dispatched=dispatched,
            success=success,
            status=status,
            channel_results=channel_results,
        )

    def _notifier(self, *results) -> MagicMock:
        notifier = MagicMock()
        if not results:
            results = (self._dispatch_result(True),)
        if len(results) == 1:
            notifier.send_with_results.return_value = results[0]
        else:
            notifier.send_with_results.side_effect = list(results)
        return notifier

    def test_p6_triggered_stock_alert_links_latest_active_decision_signal(self) -> None:
        self._create_rule(target="600519")
        signal_service = DecisionSignalService()
        signal_service.create_signal({
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "market": "cn",
            "source_type": "analysis",
            "source_report_id": 1390,
            "trace_id": "analysis-1390",
            "trigger_source": "api",
            "action": "sell",
            "reason": "跌破关键支撑",
            "watch_conditions": "观察能否收回均线",
            "risk_summary": "下行风险扩大",
        })
        notifier = self._notifier()
        worker = AlertWorker(
            config_provider=lambda: self._config(),
            service=self.service,
            decision_signal_service=signal_service,
            notifier=notifier,
        )

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        all_signals = signal_service.list_signals(stock_code="600519", market="cn", page_size=10)["items"]
        self.assertEqual(len(all_signals), 1)
        self.assertEqual(all_signals[0]["source_type"], "analysis")
        trigger = self._triggers(status="triggered")[0]
        summary = trigger["decision_signal_summary"]
        self.assertEqual(summary["id"], all_signals[0]["id"])
        self.assertEqual(summary["action"], "sell")
        alert_text = notifier.send_with_results.call_args.args[0]
        self.assertIn("AI 决策信号", alert_text)
        self.assertIn("跌破关键支撑", alert_text)
        self.assertIn("观察能否收回均线", alert_text)

    def test_p6_triggered_stock_alert_creates_alert_signal_when_no_active_signal(self) -> None:
        self._create_rule(target="600519")
        signal_service = DecisionSignalService()
        notifier = self._notifier()
        worker = AlertWorker(
            config_provider=lambda: self._config(),
            service=self.service,
            decision_signal_service=signal_service,
            notifier=notifier,
        )

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        signals = signal_service.list_signals(source_type="alert", stock_code="600519", market="cn", page_size=10)[
            "items"
        ]
        self.assertEqual(len(signals), 1)
        item = signals[0]
        self.assertEqual(item["action"], "alert")
        self.assertEqual(item["trigger_source"], "alert")
        self.assertEqual(item["source_agent"], "alert_worker")
        self.assertIsNone(item["market_phase"])
        self.assertTrue(str(item["trace_id"]).startswith("alert-rule-"))
        self.assertEqual(item["metadata"]["rule_id"], 1)
        self.assertEqual(item["metadata"]["alert_type"], "price_cross")
        self.assertEqual(self._triggers(status="triggered")[0]["decision_signal_summary"]["id"], item["id"])

    def test_p6_alert_signal_trace_id_is_idempotent_for_same_rule(self) -> None:
        self._create_rule(target="600519")
        signal_service = DecisionSignalService()
        notifier = self._notifier(
            self._dispatch_result(False, dispatched=True),
            self._dispatch_result(False, dispatched=True),
        )
        worker = AlertWorker(
            config_provider=lambda: self._config(),
            service=self.service,
            decision_signal_service=signal_service,
            notifier=notifier,
        )

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            worker.run_once()
            worker.run_once()

        signals = signal_service.list_signals(source_type="alert", stock_code="600519", market="cn", page_size=10)[
            "items"
        ]
        self.assertEqual(len(signals), 1)
        self.assertIsNone(signals[0]["market_phase"])
        self.assertEqual(len(self._triggers(status="triggered")), 2)

    def test_p6_non_stock_alert_targets_skip_decision_signal_write(self) -> None:
        signal_service = MagicMock()
        worker = AlertWorker(
            config_provider=lambda: self._config(),
            service=self.service,
            decision_signal_service=signal_service,
        )
        for runtime_rule in (
            SimpleNamespace(
                key="market:cn",
                rule=SimpleNamespace(target_scope="market", target="cn", metadata={}),
                source="db",
                severity="warning",
                effective_target="cn",
                display_target="cn",
            ),
            SimpleNamespace(
                key="portfolio_account:all",
                rule=SimpleNamespace(target_scope="portfolio_account", target="all", metadata={}),
                source="db",
                severity="warning",
                effective_target="portfolio_account:all",
                display_target="all accounts",
            ),
            SimpleNamespace(
                key="single_symbol:SPX",
                rule=SimpleNamespace(
                    target_scope="single_symbol",
                    stock_code="SPX",
                    metadata={},
                ),
                source="db",
                severity="warning",
                effective_target="SPX",
                display_target="SPX",
            ),
        ):
            worker._attach_decision_signal_summary_safely(runtime_rule, {"record_status": "triggered"})

        signal_service.get_latest_active.assert_not_called()
        signal_service.create_signal.assert_not_called()

    def test_p6_notification_failure_does_not_block_alert_signal_write(self) -> None:
        self._create_rule(target="600519")
        signal_service = DecisionSignalService()

        class FailingNotifier:
            def send_with_results(self, *_args, **_kwargs):
                raise RuntimeError("webhook token=secret failed")

        worker = AlertWorker(
            config_provider=lambda: self._config(),
            service=self.service,
            decision_signal_service=signal_service,
            notifier=FailingNotifier(),
        )

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        self.assertEqual(stats["recorded"], 1)
        self.assertEqual(stats["notified"], 0)
        self.assertEqual(len(self._triggers(status="triggered")), 1)
        signals = signal_service.list_signals(source_type="alert", stock_code="600519", market="cn", page_size=10)[
            "items"
        ]
        self.assertEqual(len(signals), 1)

    def test_triggered_diagnostics_merge_visibility_and_market_scope_uses_region(self) -> None:
        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service)
        runtime_rule = SimpleNamespace(
            target_scope="market",
            target="cn",
            effective_target="cn",
        )
        result = {
            "status": "triggered",
            "diagnostics": '{"existing":"keep"}',
        }

        with patch(
            "src.services.alert_worker.build_market_phase_context",
            return_value={
                "phase": "intraday",
                "market": "cn",
                "trigger_source": "alert",
                "is_trading_day": True,
                "is_partial_bar": True,
            },
        ) as build_context, patch(
            "src.services.alert_worker.get_market_for_stock",
            side_effect=AssertionError("market scope must not infer stock market"),
        ):
            diagnostics = worker._diagnostics_for_status("triggered", result, runtime_rule)

        payload = json.loads(diagnostics)
        self.assertEqual(payload["existing"], "keep")
        visibility = payload["analysis_visibility"]
        self.assertEqual(visibility["source"], "alert_trigger_market_context")
        self.assertEqual(visibility["market_phase_summary"]["phase"], "intraday")
        self.assertEqual(visibility["market_phase_summary"]["market"], "cn")
        self.assertTrue(visibility["market_phase_summary"]["is_partial_bar"])
        build_context.assert_called_once()
        self.assertEqual(build_context.call_args.kwargs["market"], "cn")

    def test_enabled_db_rule_triggers_and_disabled_rule_is_ignored(self) -> None:
        enabled_rule = self._create_rule(target="600519")
        self._create_rule(
            name="Disabled",
            target="000001",
            parameters={"direction": "above", "price": 10},
            enabled=False,
        )
        notifier = self._notifier()
        seen_codes = []

        async def _quote(_monitor, stock_code):
            seen_codes.append(stock_code)
            return SimpleNamespace(price=1810.0)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=_quote):
            stats = worker.run_once()

        self.assertEqual(stats["loaded"], 1)
        self.assertEqual(stats["triggered"], 1)
        self.assertEqual(seen_codes, ["600519"])
        triggers = self._triggers(rule_id=enabled_rule["id"])
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["status"], "triggered")
        self.assertEqual(triggers[0]["target"], "600519")
        self.assertEqual(triggers[0]["observed_value"], 1810.0)
        self.assertEqual(triggers[0]["threshold"], 1800.0)
        notifier.send_with_results.assert_called_once()
        self.assertEqual(notifier.send_with_results.call_args.kwargs["route_type"], "alert")
        notifications = self._notifications(trigger_id=triggers[0]["id"])
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["channel"], "custom")
        self.assertTrue(notifications[0]["success"])

    def test_create_trigger_if_absent_rejects_non_dedupable_history(self) -> None:
        cases = [
            {
                "name": "non_triggered_status",
                "fields": {
                    "rule_id": 1,
                    "target": "600519",
                    "status": "skipped",
                    "data_timestamp": date(2026, 5, 15),
                },
            },
            {
                "name": "missing_rule_id",
                "fields": {
                    "target": "600519",
                    "status": "triggered",
                    "data_timestamp": date(2026, 5, 15),
                },
            },
            {
                "name": "missing_data_timestamp",
                "fields": {
                    "rule_id": 1,
                    "target": "600519",
                    "status": "triggered",
                    "data_timestamp": None,
                },
            },
        ]
        for case in cases:
            with self.subTest(case["name"]):
                with self.assertRaisesRegex(ValueError, "requires triggered status"):
                    self.service.repo.create_trigger_if_absent(case["fields"])

    def test_legacy_rules_coexist_with_db_rules_and_db_rule_wins_duplicate_key(self) -> None:
        self._create_rule(target="600519")
        legacy_rules = (
            '[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800},'
            '{"stock_code":"300750","alert_type":"price_change_percent","direction":"down","change_pct":3.5}]'
        )

        async def _quote(_monitor, stock_code):
            if stock_code == "300750":
                return {"pct_chg": "-3.75%"}
            return SimpleNamespace(price=1810.0)

        worker = AlertWorker(
            config_provider=lambda: self._config(legacy_rules),
            service=self.service,
            notifier=self._notifier(),
        )
        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=_quote):
            stats = worker.run_once()

        self.assertEqual(stats["loaded"], 2)
        self.assertEqual(stats["triggered"], 2)
        targets = {item["target"] for item in self._triggers()}
        self.assertEqual(targets, {"600519", "300750"})

    def test_legacy_rules_keep_existing_duplicate_trigger_history(self) -> None:
        legacy_rules = (
            '[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800}]'
        )
        notifier = self._notifier()

        async def _quote(_monitor, _stock_code):
            return SimpleNamespace(price=1810.0)

        worker = AlertWorker(
            config_provider=lambda: self._config(legacy_rules),
            service=self.service,
            notifier=notifier,
        )
        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=_quote):
            first = worker.run_once()
            second = worker.run_once()

        self.assertEqual(first["triggered"], 1)
        self.assertEqual(first["recorded"], 1)
        self.assertEqual(second["triggered"], 1)
        self.assertEqual(second["recorded"], 1)
        triggers = self._triggers(status="triggered")
        self.assertEqual(len(triggers), 2)
        self.assertTrue(all(item["rule_id"] is None for item in triggers))
        self.assertTrue(all(item["data_timestamp"] is None for item in triggers))
        notifier.send_with_results.assert_called_once()

    def test_legacy_json_parse_failure_does_not_crash_or_block_persisted_rules(self) -> None:
        before = self.env_path.read_text(encoding="utf-8")
        self._create_rule(target="600519")
        notifier = self._notifier()
        worker = AlertWorker(config_provider=lambda: self._config("[invalid"), service=self.service, notifier=notifier)

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["loaded"], 1)
        self.assertEqual(stats["triggered"], 1)
        self.assertEqual(len(self._triggers()), 1)
        self.assertEqual(self.env_path.read_text(encoding="utf-8"), before)

    def test_all_invalid_legacy_rules_do_not_crash(self) -> None:
        invalid_rules = (
            '[{"stock_code":"600519","alert_type":"price_cross","direction":"sideways","price":1800},'
            '{"stock_code":"300750","alert_type":"price_change_percent","direction":"down","change_pct":0}]'
        )
        worker = AlertWorker(config_provider=lambda: self._config(invalid_rules), service=self.service)

        stats = worker.run_once()

        self.assertEqual(stats["loaded"], 0)
        self.assertEqual(stats["evaluated"], 0)
        self.assertEqual(self._triggers(), [])

    def test_empty_sources_are_a_noop(self) -> None:
        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service)

        stats = worker.run_once()

        self.assertEqual(stats["loaded"], 0)
        self.assertEqual(stats["evaluated"], 0)
        self.assertEqual(self._triggers(), [])

    def test_missing_quote_writes_skipped_trigger_without_notification(self) -> None:
        self._create_rule(target="600519")
        notifier = self._notifier()
        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)

        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=AsyncMock(return_value=None)):
            stats = worker.run_once()

        self.assertEqual(stats["skipped"], 1)
        triggers = self._triggers(status="skipped")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "600519")
        self.assertIn("No realtime quote", triggers[0]["diagnostics"])
        notifier.send_with_results.assert_not_called()

    def test_price_cross_numeric_yyyymmdd_quote_date_writes_correct_timestamp(self) -> None:
        rule = self._create_rule(target="600519")
        notifier = self._notifier()
        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0, date=20260517)),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["data_timestamp"], "2026-05-17T00:00:00")

    def test_price_cross_space_separated_quote_time_writes_timestamp(self) -> None:
        rule = self._create_rule(target="600519")
        notifier = self._notifier()
        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0, quote_time="2026-05-17 15:00:00")),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["data_timestamp"], "2026-05-17T15:00:00")

    def test_ambiguous_numeric_quote_timestamp_is_not_written_as_epoch(self) -> None:
        rule = self._create_rule(target="600519")
        notifier = self._notifier()
        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0, timestamp=1700000000)),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertIsNone(triggers[0]["data_timestamp"])

    def test_service_test_rule_exception_uses_same_sanitized_reason_and_message(self) -> None:
        rule = self._create_rule(target="600519")

        async def _raise(_rule, _monitor, **_kwargs):
            raise RuntimeError("token=secret-token failed at https://example.com/webhook")

        with patch.object(self.service, "_evaluate_rule", new=_raise):
            result = self.service.test_rule(rule["id"])

        self.assertEqual(result["status"], "evaluation_error")
        self.assertEqual(result["record_status"], "failed")
        self.assertEqual(result["reason"], result["message"])
        self.assertNotIn("secret-token", result["reason"])
        self.assertNotIn("example.com/webhook", result["message"])

    def test_daily_data_unavailable_writes_degraded_trigger(self) -> None:
        self._create_rule(
            name="Volume",
            target="000858",
            alert_type="volume_spike",
            parameters={"multiplier": 2.5},
        )
        manager = MagicMock()
        manager.get_daily_data.return_value = None

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            stats = worker.run_once()

        self.assertEqual(stats["degraded"], 1)
        triggers = self._triggers(status="degraded")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "000858")
        self.assertIn("No daily volume data", triggers[0]["diagnostics"])

    def test_malformed_daily_data_response_writes_degraded_trigger(self) -> None:
        self._create_rule(
            name="Volume",
            target="000858",
            alert_type="volume_spike",
            parameters={"multiplier": 2.5},
        )
        manager = MagicMock()
        manager.get_daily_data.return_value = {"unexpected": "shape"}

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            stats = worker.run_once()

        self.assertEqual(stats["degraded"], 1)
        triggers = self._triggers(status="degraded")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "000858")
        self.assertIn("Malformed daily volume data", triggers[0]["diagnostics"])

    def test_volume_spike_trigger_writes_expected_trigger_fields(self) -> None:
        rule = self._create_rule(
            name="Volume",
            target="000858",
            alert_type="volume_spike",
            parameters={"multiplier": 2.0},
        )
        manager = MagicMock()
        daily = pd.DataFrame(
            {
                "date": [date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15)],
                "volume": [1000, 1000, 5000],
            }
        )
        manager.get_daily_data.return_value = (daily, "test_source")
        notifier = self._notifier()

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        self.assertEqual(stats["recorded"], 1)
        self.assertEqual(stats["notified"], 1)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "000858")
        self.assertEqual(triggers[0]["observed_value"], 5000.0)
        self.assertAlmostEqual(triggers[0]["threshold"], 4666.666666666667)
        self.assertEqual(triggers[0]["data_source"], "daily_data")
        self.assertEqual(triggers[0]["data_timestamp"], "2026-05-15T00:00:00")
        notifier.send_with_results.assert_called_once()

    def test_volume_spike_history_deduplicates_same_daily_signal(self) -> None:
        rule = self._create_rule(
            name="Volume",
            target="000858",
            alert_type="volume_spike",
            parameters={"multiplier": 2.0},
            cooldown_policy={"cooldown_seconds": 60},
        )
        manager = MagicMock()
        manager.get_daily_data.return_value = (
            pd.DataFrame({
                "date": [date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15)],
                "volume": [1000, 1000, 5000],
            }),
            "unit-test",
        )
        notifier = self._notifier()

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            first = worker.run_once()
            second = worker.run_once()

        self.assertEqual(first["triggered"], 1)
        self.assertEqual(first["recorded"], 1)
        self.assertEqual(second["triggered"], 1)
        self.assertEqual(second["recorded"], 0)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "000858")
        self.assertEqual(triggers[0]["data_source"], "daily_data")
        self.assertEqual(triggers[0]["data_timestamp"], "2026-05-15T00:00:00")
        cooldown_attempts = self._notifications(channel="__cooldown__")
        self.assertEqual(len(cooldown_attempts), 1)
        self.assertEqual(cooldown_attempts[0]["trigger_id"], triggers[0]["id"])
        notifier.send_with_results.assert_called_once()

    def test_technical_indicator_rules_share_run_once_daily_cache(self) -> None:
        self._create_rule(
            name="MA one",
            target="600519",
            alert_type="ma_price_cross",
            parameters={"window": 2, "direction": "above"},
        )
        self._create_rule(
            name="MA two",
            target="600519",
            alert_type="ma_price_cross",
            parameters={"window": 2, "direction": "above"},
        )
        manager = MagicMock()
        manager.get_daily_data.return_value = (
            pd.DataFrame({
                "date": [date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15)],
                "close": [10, 9, 12],
            }),
            "unit-test",
        )
        notifier = self._notifier()

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            first = worker.run_once()
            second = worker.run_once()

        self.assertEqual(first["triggered"], 2)
        self.assertEqual(second["triggered"], 2)
        self.assertEqual(len(self._triggers(status="triggered")), 2)
        self.assertEqual(manager.get_daily_data.call_count, 2)
        manager.get_daily_data.assert_called_with("600519", days=33)

    def test_db_triggered_history_deduplicates_same_daily_signal(self) -> None:
        rule = self._create_rule(
            name="MA",
            target="600519",
            alert_type="ma_price_cross",
            parameters={"window": 2, "direction": "above"},
            cooldown_policy={"cooldown_seconds": 60},
        )
        manager = MagicMock()
        manager.get_daily_data.return_value = (
            pd.DataFrame({
                "date": [date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15)],
                "close": [10, 9, 12],
            }),
            "unit-test",
        )
        notifier = self._notifier()

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            first = worker.run_once()
            second = worker.run_once()

        self.assertEqual(first["triggered"], 1)
        self.assertEqual(first["recorded"], 1)
        self.assertEqual(second["triggered"], 1)
        self.assertEqual(second["recorded"], 0)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["data_timestamp"], "2026-05-15T00:00:00")
        cooldown_attempts = self._notifications(channel="__cooldown__")
        self.assertEqual(len(cooldown_attempts), 1)
        self.assertEqual(cooldown_attempts[0]["trigger_id"], triggers[0]["id"])
        notifier.send_with_results.assert_called_once()

    def test_db_triggered_history_keeps_distinct_data_timestamps(self) -> None:
        rule = self._create_rule(
            name="MA",
            target="600519",
            alert_type="ma_price_cross",
            parameters={"window": 2, "direction": "above"},
            cooldown_policy={"cooldown_seconds": 60},
        )
        manager = MagicMock()
        manager.get_daily_data.side_effect = [
            (
                pd.DataFrame({
                    "date": [date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15)],
                    "close": [10, 9, 12],
                }),
                "unit-test",
            ),
            (
                pd.DataFrame({
                    "date": [date(2026, 5, 14), date(2026, 5, 15), date(2026, 5, 16)],
                    "close": [10, 9, 12],
                }),
                "unit-test",
            ),
        ]

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=self._notifier())
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            first = worker.run_once()
            second = worker.run_once()

        self.assertEqual(first["recorded"], 1)
        self.assertEqual(second["recorded"], 1)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 2)
        self.assertEqual(
            {item["data_timestamp"] for item in triggers},
            {"2026-05-15T00:00:00", "2026-05-16T00:00:00"},
        )

    def test_cooldown_zero_reuses_same_trigger_history_but_keeps_notifications(self) -> None:
        rule = self._create_rule(
            name="MA",
            target="600519",
            alert_type="ma_price_cross",
            parameters={"window": 2, "direction": "above"},
            cooldown_policy={"cooldown_seconds": 0},
        )
        manager = MagicMock()
        manager.get_daily_data.return_value = (
            pd.DataFrame({
                "date": [date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15)],
                "close": [10, 9, 12],
            }),
            "unit-test",
        )
        notifier = self._notifier(self._dispatch_result(True), self._dispatch_result(True))

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            first = worker.run_once()
            second = worker.run_once()

        self.assertEqual(first["notified"], 1)
        self.assertEqual(second["notified"], 1)
        self.assertEqual(second["recorded"], 0)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        notifications = self._notifications(trigger_id=triggers[0]["id"])
        self.assertEqual(len(notifications), 2)
        self.assertEqual(notifier.send_with_results.call_count, 2)

    def test_db_triggered_history_deduplicates_per_rule_id(self) -> None:
        first_rule = self._create_rule(
            name="MA one",
            target="600519",
            alert_type="ma_price_cross",
            parameters={"window": 2, "direction": "above"},
            cooldown_policy={"cooldown_seconds": 60},
        )
        second_rule = self._create_rule(
            name="MA two",
            target="600519",
            alert_type="ma_price_cross",
            parameters={"window": 2, "direction": "above"},
            cooldown_policy={"cooldown_seconds": 60},
        )
        manager = MagicMock()
        manager.get_daily_data.return_value = (
            pd.DataFrame({
                "date": [date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15)],
                "close": [10, 9, 12],
            }),
            "unit-test",
        )

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=self._notifier())
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            first = worker.run_once()
            second = worker.run_once()

        self.assertEqual(first["recorded"], 2)
        self.assertEqual(second["recorded"], 0)
        triggers = self._triggers(status="triggered")
        self.assertEqual(len(triggers), 2)
        self.assertEqual({item["rule_id"] for item in triggers}, {first_rule["id"], second_rule["id"]})

    def test_non_triggered_status_history_is_not_deduplicated(self) -> None:
        self._create_rule(name="Skipped", target="600519")
        self._create_rule(
            name="Degraded",
            target="000858",
            alert_type="volume_spike",
            parameters={"multiplier": 2.5},
        )
        self._create_rule(
            name="Failed",
            target="300750",
            alert_type="price_change_percent",
            parameters={"direction": "down", "change_pct": 3.0},
        )
        status_by_target = {
            "600519": "skipped",
            "000858": "degraded",
            "300750": "failed",
        }

        async def _evaluate(rule, _monitor, **_kwargs):
            status = status_by_target[rule.stock_code]
            return {
                "rule_id": self.service._runtime_rule_id(rule),
                "record_status": status,
                "triggered": False,
                "observed_value": None,
                "threshold": self.service._threshold_for_rule(rule),
                "data_source": self.service._data_source_for_rule(rule),
                "data_timestamp": None,
                "reason": f"{status} test",
                "message": f"{status} test",
            }

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=self._notifier())
        with patch.object(self.service, "_evaluate_rule", new=_evaluate):
            first = worker.run_once()
            second = worker.run_once()

        self.assertEqual(first["recorded"], 3)
        self.assertEqual(second["recorded"], 3)
        for status in ("skipped", "degraded", "failed"):
            self.assertEqual(len(self._triggers(status=status)), 2)

    def test_technical_indicator_insufficient_data_writes_degraded_trigger(self) -> None:
        rule = self._create_rule(
            name="MA insufficient",
            target="600519",
            alert_type="ma_price_cross",
            parameters={"window": 20, "direction": "above"},
        )
        manager = MagicMock()
        manager.get_daily_data.return_value = (
            pd.DataFrame({
                "date": [date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15)],
                "close": [10, 9, 12],
            }),
            "unit-test",
        )
        notifier = self._notifier()

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            stats = worker.run_once()

        self.assertEqual(stats["degraded"], 1)
        triggers = self._triggers(rule_id=rule["id"], status="degraded")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "600519")
        self.assertIn("insufficient data: need 21 bars, got 3", triggers[0]["diagnostics"])
        manager.get_daily_data.assert_called_once_with("600519", days=63)
        notifier.send_with_results.assert_not_called()

    def test_technical_indicator_fetch_exception_writes_failed_trigger(self) -> None:
        self._create_rule(
            name="MA",
            target="600519",
            alert_type="ma_price_cross",
            parameters={"window": 2, "direction": "above"},
        )
        manager = MagicMock()
        manager.get_daily_data.side_effect = RuntimeError("token=secret-token data fetch failed")
        notifier = self._notifier()

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            stats = worker.run_once()

        self.assertEqual(stats["failed"], 1)
        failed = self._triggers(status="failed")
        self.assertEqual(len(failed), 1)
        self.assertNotIn("secret-token", failed[0]["diagnostics"])
        notifier.send_with_results.assert_not_called()

    def test_unsupported_persisted_rule_is_skipped_without_crashing_worker(self) -> None:
        self.service.repo.create_rule({
            "name": "Future rule",
            "target_scope": "single_symbol",
            "target": "600519",
            "alert_type": "future_indicator",
            "parameters": "{}",
            "severity": "warning",
            "enabled": True,
            "source": "api",
        })

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service)
        stats = worker.run_once()

        self.assertEqual(stats["loaded"], 0)
        self.assertEqual(stats["evaluated"], 0)
        self.assertEqual(self._triggers(), [])

    def test_market_light_rule_triggers_with_market_payload_and_deduplicates_trade_date(self) -> None:
        rule = self._create_rule(
            name="Market risk-off",
            target_scope="market",
            target="cn",
            alert_type="market_light_status",
            parameters={"statuses": ["red", "yellow"]},
        )
        snapshot = {
            "region": "cn",
            "trade_date": "2026-03-07",
            "status": "red",
            "score": 35,
            "label": "偏防守",
            "temperature_label": "偏弱",
            "reasons": ["test"],
            "guidance": "test",
            "dimensions": {
                "breadth": {"score": 20, "available": True},
                "index": {"score": 30, "available": True},
                "limit": {"score": 10, "available": True},
            },
            "data_quality": "ok",
        }
        notifier = self._notifier()
        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)

        with patch("src.services.market_light_alerts.build_current_snapshot", return_value=snapshot):
            first = worker.run_once()
            second = worker.run_once()

        self.assertEqual(first["triggered"], 1)
        self.assertEqual(first["recorded"], 1)
        self.assertEqual(second["triggered"], 1)
        self.assertEqual(second["recorded"], 0)
        notifier.send_with_results.assert_called_once()
        self.assertEqual(notifier.send_with_results.call_args.kwargs["route_type"], "alert")
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "cn")
        self.assertEqual(triggers[0]["observed_value"], 35.0)
        self.assertEqual(triggers[0]["data_source"], "market_light")
        self.assertEqual(triggers[0]["data_timestamp"], "2026-03-07T00:00:00")

    def test_market_light_rule_skips_non_trading_day_when_check_enabled(self) -> None:
        self._create_rule(
            name="Market risk-off",
            target_scope="market",
            target="cn",
            alert_type="market_light_status",
            parameters={"statuses": ["red"]},
        )
        config = SimpleNamespace(
            agent_event_monitor_enabled=True,
            agent_event_alert_rules_json="",
            trading_day_check_enabled=True,
        )
        worker = AlertWorker(config_provider=lambda: config, service=self.service)

        with patch("src.services.market_light_alerts.get_open_markets_today", return_value=set()), patch(
            "src.services.market_light_alerts.build_current_snapshot"
        ) as build_snapshot:
            stats = worker.run_once()

        self.assertEqual(stats["skipped"], 1)
        build_snapshot.assert_not_called()
        triggers = self._triggers(status="skipped")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "cn")
        self.assertEqual(triggers[0]["data_source"], "market_light")

    def test_single_rule_failure_does_not_block_other_rules(self) -> None:
        self._create_rule(target="600519")
        self._create_rule(
            name="CATL drop",
            target="300750",
            alert_type="price_change_percent",
            parameters={"direction": "down", "change_pct": 3.0},
        )
        notifier = self._notifier()

        async def _quote(_monitor, stock_code):
            if stock_code == "600519":
                raise RuntimeError("token=secret-token failed at https://example.com/webhook")
            return {"pct_chg": "-3.25%"}

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=_quote):
            stats = worker.run_once()

        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["triggered"], 1)
        failed = self._triggers(status="failed")
        self.assertEqual(len(failed), 1)
        self.assertNotIn("secret-token", failed[0]["diagnostics"])
        self.assertNotIn("example.com/webhook", failed[0]["diagnostics"])
        self.assertEqual(len(self._triggers(status="triggered")), 1)

    def test_notification_failure_does_not_block_other_rules(self) -> None:
        self._create_rule(target="600519")
        self._create_rule(
            name="CATL drop",
            target="300750",
            alert_type="price_change_percent",
            parameters={"direction": "down", "change_pct": 3.0},
        )
        notifier = self._notifier(RuntimeError("webhook secret failed"), self._dispatch_result(True))

        async def _quote(_monitor, stock_code):
            if stock_code == "600519":
                return SimpleNamespace(price=1810.0)
            return {"pct_chg": "-3.25%"}

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=_quote):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 2)
        self.assertEqual(stats["recorded"], 2)
        self.assertEqual(stats["notified"], 1)
        self.assertEqual(len(self._triggers(status="triggered")), 2)
        self.assertEqual(notifier.send_with_results.call_count, 2)

    def test_notification_dispatch_results_are_recorded_and_success_updates_cooldown(self) -> None:
        rule = self._create_rule(target="600519", cooldown_policy={"cooldown_seconds": 60})

        class FakeNotifier:
            def send_with_results(self, *_args, **_kwargs):
                return NotificationDispatchResult(
                    dispatched=True,
                    success=True,
                    status="partial_failed",
                    channel_results=[
                        ChannelAttemptResult(channel="wechat", success=False, error_code="send_failed", retryable=True),
                        ChannelAttemptResult(channel="custom", success=True, latency_ms=12),
                    ],
                )

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=FakeNotifier())
        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["notified"], 1)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        notifications = self._notifications(trigger_id=triggers[0]["id"])
        by_channel = {item["channel"]: item for item in notifications}
        self.assertEqual(set(by_channel), {"wechat", "custom"})
        self.assertFalse(by_channel["wechat"]["success"])
        self.assertTrue(by_channel["custom"]["success"])
        cooldown = self.service.repo.get_rule_cooldown_summary(
            rule_id=rule["id"],
            target="600519",
            severity="warning",
        )
        self.assertIsNotNone(cooldown)

    def test_noise_suppression_records_synthetic_attempt_without_upserting_cooldown(self) -> None:
        rule = self._create_rule(target="600519", cooldown_policy={"cooldown_seconds": 60})

        class FakeNotifier:
            def send_with_results(self, *_args, **_kwargs):
                return NotificationDispatchResult(
                    dispatched=False,
                    success=False,
                    status="noise_suppressed",
                    message="cooldown: duplicated static notification",
                )

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=FakeNotifier())
        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            stats = worker.run_once()

        self.assertEqual(stats["notified"], 0)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        notifications = self._notifications(trigger_id=triggers[0]["id"])
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["channel"], "__noise_suppressed__")
        self.assertEqual(notifications[0]["error_code"], "noise_suppressed")
        cooldown = self.service.repo.get_rule_cooldown_summary(
            rule_id=rule["id"],
            target="600519",
            severity="warning",
        )
        self.assertIsNone(cooldown)

    def test_no_channel_and_all_failed_do_not_upsert_cooldown(self) -> None:
        rule = self._create_rule(target="600519", cooldown_policy={"cooldown_seconds": 60})
        dispatches = [
            NotificationDispatchResult(dispatched=False, success=False, status="no_channel", message="no channel"),
            NotificationDispatchResult(
                dispatched=True,
                success=False,
                status="all_failed",
                channel_results=[ChannelAttemptResult(channel="wechat", success=False, error_code="send_failed")],
            ),
        ]

        class FakeNotifier:
            def send_with_results(self, *_args, **_kwargs):
                return dispatches.pop(0)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=FakeNotifier())
        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            first = worker.run_once()
            second = worker.run_once()

        self.assertEqual(first["notified"], 0)
        self.assertEqual(second["notified"], 0)
        channels = {item["channel"] for item in self._notifications()}
        self.assertEqual(channels, {"__no_channel__", "wechat"})
        cooldown = self.service.repo.get_rule_cooldown_summary(
            rule_id=rule["id"],
            target="600519",
            severity="warning",
        )
        self.assertIsNone(cooldown)

    def test_trigger_record_failure_does_not_block_other_rules(self) -> None:
        self._create_rule(target="600519")
        self._create_rule(
            name="CATL drop",
            target="300750",
            alert_type="price_change_percent",
            parameters={"direction": "down", "change_pct": 3.0},
        )
        notifier = self._notifier()
        original_create_trigger = self.service.repo.create_trigger

        def _create_trigger(fields):
            if fields["target"] == "600519":
                raise RuntimeError("database locked")
            return original_create_trigger(fields)

        async def _quote(_monitor, stock_code):
            if stock_code == "600519":
                return SimpleNamespace(price=1810.0)
            return {"pct_chg": "-3.25%"}

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch.object(self.service.repo, "create_trigger", side_effect=_create_trigger), \
             patch("src.agent.events.EventMonitor._get_realtime_quote", new=_quote):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 2)
        self.assertEqual(stats["recorded"], 1)
        self.assertEqual(stats["notified"], 2)
        triggers = self._triggers(status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "300750")

    def test_db_cooldown_suppresses_duplicate_notifications_but_expires(self) -> None:
        self._create_rule(target="600519", cooldown_policy={"cooldown_seconds": 60})
        notifier = self._notifier()
        now = {"value": 1000.0}

        worker = AlertWorker(
            config_provider=lambda: self._config(),
            service=self.service,
            notifier=notifier,
            now_provider=lambda: now["value"],
            fingerprint_ttl_seconds=60,
        )
        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            worker.run_once()
            now["value"] += 30
            worker.run_once()
            now["value"] += 61
            worker.run_once()

        self.assertEqual(notifier.send_with_results.call_count, 2)
        self.assertEqual(len(self._triggers(status="triggered")), 3)
        cooldown_attempts = self._notifications(channel="__cooldown__")
        self.assertEqual(len(cooldown_attempts), 1)
        self.assertEqual(cooldown_attempts[0]["error_code"], "cooldown_active")

    def test_db_cooldown_read_failure_uses_fingerprint_fallback(self) -> None:
        self._create_rule(target="600519", cooldown_policy={"cooldown_seconds": 60})
        notifier = self._notifier()
        now = {"value": 1000.0}

        worker = AlertWorker(
            config_provider=lambda: self._config(),
            service=self.service,
            notifier=notifier,
            now_provider=lambda: now["value"],
            fingerprint_ttl_seconds=86400,
        )
        with patch.object(
            self.service.repo,
            "get_active_cooldown",
            side_effect=RuntimeError("database locked token=secret-token"),
        ), patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            first = worker.run_once()
            now["value"] += 10
            second = worker.run_once()
            now["value"] += 61
            third = worker.run_once()

        self.assertEqual(first["notified"], 1)
        self.assertEqual(second["cooldown_suppressed"], 1)
        self.assertEqual(third["notified"], 1)
        self.assertEqual(notifier.send_with_results.call_count, 2)
        self.assertEqual(len(self._triggers(status="triggered")), 3)
        suppressed_attempts = self._notifications(channel="__cooldown_read_failed__")
        self.assertEqual(len(suppressed_attempts), 1)
        self.assertEqual(suppressed_attempts[0]["error_code"], "cooldown_read_failed")
        self.assertNotIn("secret-token", suppressed_attempts[0]["diagnostics"] or "")

    def test_failed_db_notification_does_not_start_read_failure_fallback_window(self) -> None:
        self._create_rule(target="600519", cooldown_policy={"cooldown_seconds": 60})
        notifier = self._notifier(self._dispatch_result(False), self._dispatch_result(True))
        now = {"value": 1000.0}

        worker = AlertWorker(
            config_provider=lambda: self._config(),
            service=self.service,
            notifier=notifier,
            now_provider=lambda: now["value"],
            fingerprint_ttl_seconds=60,
        )
        with patch.object(
            self.service.repo,
            "get_active_cooldown",
            side_effect=RuntimeError("database locked"),
        ), patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            first = worker.run_once()
            now["value"] += 10
            second = worker.run_once()
            now["value"] += 10
            third = worker.run_once()

        self.assertEqual(first["notified"], 0)
        self.assertEqual(second["notified"], 1)
        self.assertEqual(third["cooldown_suppressed"], 1)
        self.assertEqual(notifier.send_with_results.call_count, 2)
        self.assertEqual(len(self._notifications(channel="__cooldown_read_failed__")), 1)

    def test_db_rule_with_cooldown_zero_is_not_suppressed_by_fingerprint(self) -> None:
        self._create_rule(target="600519", cooldown_policy={"cooldown_seconds": 0})
        notifier = self._notifier()
        now = {"value": 1000.0}

        worker = AlertWorker(
            config_provider=lambda: self._config(),
            service=self.service,
            notifier=notifier,
            now_provider=lambda: now["value"],
            fingerprint_ttl_seconds=60,
        )
        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            worker.run_once()
            now["value"] += 10
            worker.run_once()

        self.assertEqual(notifier.send_with_results.call_count, 2)
        self.assertEqual(len(self._triggers(status="triggered")), 2)
        self.assertEqual(self._notifications(channel="__cooldown__"), [])

    def test_legacy_rule_still_uses_fingerprint_suppression(self) -> None:
        raw_rules = '[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800}]'
        notifier = self._notifier()
        now = {"value": 1000.0}

        worker = AlertWorker(
            config_provider=lambda: self._config(raw_rules),
            service=self.service,
            notifier=notifier,
            now_provider=lambda: now["value"],
            fingerprint_ttl_seconds=60,
        )
        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            worker.run_once()
            now["value"] += 10
            worker.run_once()
            now["value"] += 61
            worker.run_once()

        self.assertEqual(notifier.send_with_results.call_count, 2)
        self.assertEqual(len(self._triggers(status="triggered")), 3)

    def test_failed_db_notification_attempts_do_not_start_cooldown_window(self) -> None:
        self._create_rule(target="600519")
        notifier = self._notifier(
            self._dispatch_result(False),
            RuntimeError("temporary webhook failure"),
            self._dispatch_result(True),
        )
        now = {"value": 1000.0}

        worker = AlertWorker(
            config_provider=lambda: self._config(),
            service=self.service,
            notifier=notifier,
            now_provider=lambda: now["value"],
            fingerprint_ttl_seconds=60,
        )
        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1810.0)),
        ):
            first = worker.run_once()
            now["value"] += 10
            second = worker.run_once()
            now["value"] += 10
            third = worker.run_once()
            now["value"] += 10
            fourth = worker.run_once()

        self.assertEqual(first["notified"], 0)
        self.assertEqual(second["notified"], 0)
        self.assertEqual(third["notified"], 1)
        self.assertEqual(fourth["notified"], 0)
        self.assertEqual(notifier.send_with_results.call_count, 3)
        self.assertEqual(len(self._triggers(status="triggered")), 4)

    def test_p6_watchlist_expands_to_child_keys_for_db_cooldown_fallback(self) -> None:
        self._create_rule(
            name="Watchlist",
            target_scope="watchlist",
            target="default",
            alert_type="price_cross",
            parameters={"direction": "above", "price": 10},
            cooldown_policy={"cooldown_seconds": 60},
        )
        notifier = self._notifier()
        config = self._config()
        config.stock_list = ["600519", "000001"]
        now = {"value": 1000.0}

        async def _quote(_monitor, _stock_code):
            return SimpleNamespace(price=11.0)

        worker = AlertWorker(
            config_provider=lambda: config,
            service=self.service,
            notifier=notifier,
            now_provider=lambda: now["value"],
            fingerprint_ttl_seconds=86400,
        )
        with patch.object(
            self.service.repo,
            "get_active_cooldown",
            side_effect=RuntimeError("database locked"),
        ), patch("src.agent.events.EventMonitor._get_realtime_quote", new=_quote):
            first = worker.run_once()
            now["value"] += 10
            second = worker.run_once()

        self.assertEqual(first["loaded"], 2)
        self.assertEqual(first["notified"], 2)
        self.assertEqual(second["cooldown_suppressed"], 2)
        self.assertEqual(notifier.send_with_results.call_count, 2)
        targets = {item["target"] for item in self._triggers(status="triggered")}
        self.assertEqual(targets, {"600519", "000001"})

    def test_p6_empty_watchlist_writes_skipped_trigger(self) -> None:
        self._create_rule(
            name="Watchlist",
            target_scope="watchlist",
            target="default",
            alert_type="price_cross",
            parameters={"direction": "above", "price": 10},
        )
        config = self._config()
        config.stock_list = []
        worker = AlertWorker(config_provider=lambda: config, service=self.service, notifier=self._notifier())

        stats = worker.run_once()

        self.assertEqual(stats["skipped"], 1)
        triggers = self._triggers(status="skipped")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "watchlist:default")
        self.assertIn("No watchlist targets", triggers[0]["diagnostics"])

    def test_p6_overflow_payload_is_dry_run_only_and_worker_does_not_write_degraded_history(self) -> None:
        rule = self._create_rule(
            name="Large watchlist",
            target_scope="watchlist",
            target="default",
            alert_type="price_cross",
            parameters={"direction": "above", "price": 10},
        )
        row = self.service.repo.get_rule(rule["id"])
        config = self._config()
        config.stock_list = [f"{index:06d}" for index in range(1, 102)]

        dry_run_payloads = self.service.build_runtime_payloads(row, config=config)
        worker_payloads = self.service.build_runtime_payloads(row, config=config, include_overflow_payload=False)

        self.assertEqual(len(dry_run_payloads), 101)
        self.assertTrue(dry_run_payloads[-1].effective_target.endswith(":overflow"))
        self.assertEqual(len(worker_payloads), 100)
        self.assertFalse(any(payload.effective_target.endswith(":overflow") for payload in worker_payloads))

        async def _not_triggered(rule_obj, *_args, **_kwargs):
            return {
                "rule_id": self.service._runtime_rule_id(rule_obj),
                "status": "not_triggered",
                "record_status": None,
                "triggered": False,
                "observed_value": 9.0,
                "threshold": 10.0,
                "data_source": "realtime_quote",
                "data_timestamp": None,
                "reason": "below threshold",
                "message": "below threshold",
            }

        worker = AlertWorker(config_provider=lambda: config, service=self.service, notifier=self._notifier())
        with patch.object(self.service, "_evaluate_rule", new=_not_triggered):
            stats = worker.run_once()

        self.assertEqual(stats["loaded"], 100)
        self.assertEqual(stats["degraded"], 0)
        self.assertEqual(self._triggers(status="degraded"), [])

    def test_p6_portfolio_account_risk_uses_account_effective_target_and_diagnostics(self) -> None:
        rule = self._create_rule(
            name="Portfolio risk",
            target_scope="portfolio_account",
            target="all",
            alert_type="portfolio_concentration",
            parameters={},
        )
        notifier = self._notifier()

        async def _evaluate_portfolio(rule_obj, *_args, **_kwargs):
            return {
                "rule_id": self.service._runtime_rule_id(rule_obj),
                "status": "triggered",
                "record_status": "triggered",
                "triggered": True,
                "observed_value": 42.0,
                "threshold": 35.0,
                "data_source": "portfolio_risk",
                "data_timestamp": None,
                "reason": "account all concentration top weight 42.00%",
                "message": "account all concentration top weight 42.00%",
                "diagnostics": '{"account_id":"all","currency":"CNY","as_of":"2026-05-20"}',
            }

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch.object(self.service, "_evaluate_rule", new=_evaluate_portfolio):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["target"], "account:all")
        self.assertIn("account_id", triggers[0]["diagnostics"])

    def test_kline_pattern_worker_durable_per_bar_delivery_dedup_and_retry(self) -> None:
        from src.services.alert_worker import AlertWorker

        rule = self._create_rule(
            name="Soldiers Dedup",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        # 1st poll confirms non-delivery -> 2nd poll retries and succeeds -> 3rd poll (new worker restart) dedups!
        notifier = self._notifier(
            self._dispatch_result(
                False,
                channel="wechat",
                error_code="rejected_400",
                delivery_confirmed_absent=True,
            ),
            self._dispatch_result(True, channel="wechat"),
            self._dispatch_result(True, channel="wechat"),
        )

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            first = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier).run_once()
            second = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier).run_once()
            third = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier).run_once()

        self.assertEqual(first["notified"], 0)
        self.assertEqual(second["notified"], 1)
        self.assertEqual(third["notified"], 0)
        self.assertEqual(third["cooldown_suppressed"], 1)
        self.assertEqual(notifier.send_with_results.call_count, 2)
        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        self.assertTrue(any(item["channel"] == "__bar_dedup__" for item in self._notifications(trigger_id=triggers[0]["id"])))

    def test_kline_pattern_overlapping_workers_send_once_atomically(self) -> None:
        from src.services.alert_worker import AlertWorker

        rule = self._create_rule(
            name="Soldiers Concurrent Claim",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        entered_dispatch = threading.Event()
        release_dispatch = threading.Event()
        dispatch_success = self._dispatch_result(True, channel="wechat")

        def _blocking_send(*_args, **_kwargs):
            entered_dispatch.set()
            assert release_dispatch.wait(timeout=5)
            return dispatch_success

        notifier_worker1 = MagicMock()
        notifier_worker1.send_with_results.side_effect = _blocking_send
        notifier_worker2 = self._notifier(self._dispatch_result(True, channel="wechat"))

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        w1_holder: dict = {}

        def _run_worker1() -> None:
            w1 = AlertWorker(
                config_provider=lambda: self._config(),
                service=AlertService(self.service.db),
                notifier=notifier_worker1,
            )
            w1_holder["stats"] = w1.run_once()

        w2 = AlertWorker(
            config_provider=lambda: self._config(),
            service=AlertService(self.service.db),
            notifier=notifier_worker2,
        )
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            t1 = threading.Thread(target=_run_worker1)
            t1.start()
            self.assertTrue(entered_dispatch.wait(timeout=5))
            w2_stats = w2.run_once()
            release_dispatch.set()
            t1.join(timeout=5)

        w1_stats = w1_holder["stats"]
        self.assertEqual(w1_stats["notified"], 1)
        self.assertEqual(w2_stats["notified"], 0)
        self.assertEqual(w2_stats["cooldown_suppressed"], 1)
        self.assertEqual(notifier_worker1.send_with_results.call_count, 1)
        notifier_worker2.send_with_results.assert_not_called()

        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        notifs = self._notifications(trigger_id=triggers[0]["id"])
        channels = {item["channel"] for item in notifs}
        self.assertEqual(channels, {"wechat", "__bar_dedup__"})
        self.assertNotIn("__bar_delivery_claim__", channels)
        with self.service.db.get_session() as session:
            claims = session.query(AlertNotificationRecord).filter(
                AlertNotificationRecord.trigger_id == triggers[0]["id"],
                AlertNotificationRecord.channel == "__bar_delivery_claim__",
            ).all()
        self.assertEqual(claims, [])

    def test_kline_pattern_worker_degrades_when_fetcher_drops_nan_row(self) -> None:
        from src.services.alert_worker import AlertWorker

        rule = self._create_rule(
            name="Soldiers Fetcher Drop",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
        )
        dates = pd.date_range("2026-01-05", periods=25, freq="B")
        last_dt = dates[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)

        class _NanRowFetcher(BaseFetcher):
            name = "NanRowFetcher"
            priority = 1

            def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
                base = [
                    (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
                    for i in range(21)
                ]
                soldiers_with_nan_gap = [
                    (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
                    (20.4, 20.5, 20.2, float("nan"), 1_100_000.0),  # dropped by _clean_data
                    (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
                    (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
                ]
                raw = pd.DataFrame(base + soldiers_with_nan_gap, columns=["open", "high", "low", "close", "volume"])
                raw["date"] = dates
                return raw

            def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
                return df

        manager = DataFetcherManager(fetchers=[_NanRowFetcher()])
        notifier = self._notifier()

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            stats = worker.run_once()

        self.assertEqual(stats["degraded"], 1)
        self.assertEqual(stats["triggered"], 0)
        notifier.send_with_results.assert_not_called()
        triggers = self._triggers(rule_id=rule["id"], status="degraded")
        self.assertEqual(len(triggers), 1)
        detail = f"{triggers[0].get('diagnostics', '')} {triggers[0].get('reason', '')}".lower()
        self.assertIn("dropped", detail)

    def test_kline_pattern_claim_failure_and_missing_trigger_id_do_not_dispatch(self) -> None:
        from src.services.alert_worker import AlertWorker, TriggerWriteResult

        rule = self._create_rule(
            name="Soldiers Claim Failure",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        entered_dispatch = threading.Event()
        release_dispatch = threading.Event()
        dispatch_success = self._dispatch_result(True, channel="wechat")

        def _blocking_send(*_args, **_kwargs):
            entered_dispatch.set()
            assert release_dispatch.wait(timeout=5)
            return dispatch_success

        notifier_worker1 = MagicMock()
        notifier_worker1.send_with_results.side_effect = _blocking_send
        notifier_worker2 = self._notifier(self._dispatch_result(True, channel="wechat"))

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        w1_holder: dict = {}

        def _run_worker1() -> None:
            w1 = AlertWorker(
                config_provider=lambda: self._config(),
                service=AlertService(self.service.db),
                notifier=notifier_worker1,
            )
            w1_holder["stats"] = w1.run_once()

        service2 = AlertService(self.service.db)
        w2 = AlertWorker(
            config_provider=lambda: self._config(),
            service=service2,
            notifier=notifier_worker2,
        )
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
             patch.object(service2.repo, "acquire_bar_delivery_claim", side_effect=RuntimeError("db busy")):
            t1 = threading.Thread(target=_run_worker1)
            t1.start()
            self.assertTrue(entered_dispatch.wait(timeout=5))
            w2_stats = w2.run_once()
            release_dispatch.set()
            t1.join(timeout=5)

        self.assertEqual(w1_holder["stats"]["notified"], 1)
        self.assertEqual(w2_stats["notified"], 0)
        self.assertEqual(notifier_worker1.send_with_results.call_count, 1)
        notifier_worker2.send_with_results.assert_not_called()

        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        claim_failures = [
            item
            for item in self._notifications(trigger_id=triggers[0]["id"])
            if item["channel"] == "__bar_delivery_claim__" and item.get("error_code") == "claim_failed"
        ]
        self.assertTrue(claim_failures)

        self.service.enable_rule(rule["id"], False)

        rule2 = self._create_rule(
            name="Soldiers Missing Trigger ID",
            target="600036",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        notifier3 = self._notifier(self._dispatch_result(True, channel="wechat"))
        w3 = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier3)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
             patch.object(w3, "_record_trigger", return_value=TriggerWriteResult(trigger_id=None, created=False)):
            w3_stats = w3.run_once()

        self.assertEqual(w3_stats["notified"], 0)
        notifier3.send_with_results.assert_not_called()
        with self.service.db.get_session() as session:
            missing_id_claims = session.query(AlertNotificationRecord).filter(
                AlertNotificationRecord.channel == "__bar_delivery_claim__",
                AlertNotificationRecord.error_code == "claim_failed",
                AlertNotificationRecord.trigger_id.is_(None),
            ).all()
        self.assertEqual(len(missing_id_claims), 1)
        self.assertEqual(self._triggers(rule_id=rule2["id"], status="triggered"), [])

    def test_kline_pattern_lease_heartbeat_prevents_expiry_and_owner_check_protects_reclaim(self) -> None:
        from src.services.alert_worker import AlertWorker

        rule_hb = self._create_rule(
            name="Soldiers Lease Heartbeat",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        entered_dispatch = threading.Event()
        dispatch_success = self._dispatch_result(True, channel="wechat")

        def _slow_send(*_args, **_kwargs):
            entered_dispatch.set()
            threading.Event().wait(0.65)
            return dispatch_success

        notifier_worker1 = MagicMock()
        notifier_worker1.send_with_results.side_effect = _slow_send
        notifier_worker2 = self._notifier(self._dispatch_result(True, channel="wechat"))

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        w1_holder: dict = {}

        def _run_worker1() -> None:
            w1 = AlertWorker(
                config_provider=lambda: self._config(),
                service=AlertService(self.service.db),
                notifier=notifier_worker1,
                bar_delivery_lease_seconds=0.3,
            )
            w1_holder["stats"] = w1.run_once()

        w2 = AlertWorker(
            config_provider=lambda: self._config(),
            service=AlertService(self.service.db),
            notifier=notifier_worker2,
            bar_delivery_lease_seconds=0.3,
        )
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            t1 = threading.Thread(target=_run_worker1)
            t1.start()
            self.assertTrue(entered_dispatch.wait(timeout=5))
            threading.Event().wait(0.45)
            w2_stats = w2.run_once()
            t1.join(timeout=5)

        self.assertEqual(w1_holder["stats"]["notified"], 1)
        self.assertEqual(w2_stats["notified"], 0)
        self.assertEqual(w2_stats["cooldown_suppressed"], 1)
        self.assertEqual(notifier_worker1.send_with_results.call_count, 1)
        notifier_worker2.send_with_results.assert_not_called()

        # Verify owner-checked release and orphaned expired claim reclaim on a separate rule
        rule_orphan = self._create_rule(
            name="Soldiers Orphan Reclaim",
            target="600036",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        self.service.enable_rule(rule_hb["id"], False)
        notifier_fail = self._notifier(self._dispatch_result(False, dispatched=False, status="no_channel"))
        notifier_reclaim = self._notifier(self._dispatch_result(True, channel="wechat"))

        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            first = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier_fail).run_once()
            self.assertEqual(first["notified"], 0)

            orphan_triggers = self._triggers(rule_id=rule_orphan["id"], status="triggered")
            self.assertEqual(len(orphan_triggers), 1)
            orphan_tid = orphan_triggers[0]["id"]

            acquired, claim_state, claim_id = self.service.repo.acquire_bar_delivery_claim(
                orphan_tid, owner_token="owner-active", lease_seconds=30.0,
            )
            self.assertTrue(acquired)
            self.assertEqual(claim_state, "claimed")
            self.assertIsNotNone(claim_id)
            self.assertFalse(self.service.repo.release_bar_delivery_claim(claim_id, owner_token="wrong"))
            with self.service.db.get_session() as session:
                still_active = session.query(AlertNotificationRecord).filter(
                    AlertNotificationRecord.id == claim_id,
                ).one_or_none()
            self.assertIsNotNone(still_active)
            self.assertTrue(self.service.repo.release_bar_delivery_claim(claim_id, owner_token="owner-active"))

            orphan_acquired, _, orphan_claim_id = self.service.repo.acquire_bar_delivery_claim(
                orphan_tid,
                owner_token="dead-owner",
                lease_seconds=30.0,
                now=datetime.now() - timedelta(seconds=600),
            )
            self.assertTrue(orphan_acquired)
            self.assertIsNotNone(orphan_claim_id)

            reclaimed = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier_reclaim).run_once()
            self.assertEqual(reclaimed["notified"], 1)
            self.assertEqual(notifier_reclaim.send_with_results.call_count, 1)

    def test_kline_pattern_fetcher_preserves_valid_ohlc_with_nan_volume_for_mixed_preset(self) -> None:
        from src.services.alert_worker import AlertWorker

        dates = pd.date_range("2026-01-05", periods=28, freq="B")
        last_dt = dates[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)

        class _NanVolumeFetcher(BaseFetcher):
            name = "NanVolumeFetcher"
            priority = 1

            def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
                base = [
                    (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
                    for i in range(25)
                ]
                soldiers = [
                    (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
                    (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
                    (21.0, 21.75, 20.95, 21.70, float("nan")),
                ]
                raw = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
                raw["date"] = dates
                return raw

            def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
                return df

        default_df = _NanVolumeFetcher().get_daily_data("600519", days=63)
        self.assertEqual(len(default_df), 27)

        rule = self._create_rule(
            name="Mixed Preset NaN Volume",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["any_bullish"], "require_volume_confirm": False},
        )
        manager = DataFetcherManager(fetchers=[_NanVolumeFetcher()])
        notifier = self._notifier(self._dispatch_result(True, channel="wechat"))

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        worker = AlertWorker(config_provider=lambda: self._config(), service=self.service, notifier=notifier)
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            stats = worker.run_once()

        self.assertEqual(stats["triggered"], 1)
        self.assertEqual(stats["notified"], 1)
        self.assertEqual(notifier.send_with_results.call_count, 1)
        listed = self.service.list_triggers(rule_id=rule["id"])
        items = listed["items"] if isinstance(listed, dict) else listed
        self.assertEqual(len(items), 1)
        self.assertIn("red_three_soldiers", items[0]["matched_patterns"])
        self.assertEqual(
            set(items[0]["unavailable_patterns"]),
            {"immortal_guide", "breakout_20d_high", "ma_pullback_support"},
        )

    def test_kline_pattern_transient_claim_failure_allows_immediate_healthy_retry(self) -> None:
        from src.services.alert_worker import AlertWorker

        rule = self._create_rule(
            name="Soldiers Transient Claim Retry",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        service_fail = AlertService(self.service.db)
        service_healthy = AlertService(self.service.db)
        notifier_fail = self._notifier(self._dispatch_result(True, channel="wechat"))
        notifier_healthy = self._notifier(self._dispatch_result(True, channel="wechat"))

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            with patch.object(service_fail.repo, "acquire_bar_delivery_claim", side_effect=RuntimeError("db busy")):
                first = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=service_fail,
                    notifier=notifier_fail,
                ).run_once()
            second = AlertWorker(
                config_provider=lambda: self._config(),
                service=service_healthy,
                notifier=notifier_healthy,
            ).run_once()

        self.assertEqual(first["notified"], 0)
        self.assertEqual(second["notified"], 1)
        notifier_fail.send_with_results.assert_not_called()
        self.assertEqual(notifier_healthy.send_with_results.call_count, 1)

        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        notifs = self._notifications(trigger_id=triggers[0]["id"])
        self.assertTrue(
            any(item["channel"] == "__bar_delivery_claim__" and item.get("error_code") == "claim_failed" for item in notifs)
        )
        self.assertTrue(any(item["channel"] == "wechat" and item.get("success") is True for item in notifs))

    def test_kline_pattern_heartbeat_guards_post_send_outcome_persistence(self) -> None:
        from src.services.alert_worker import AlertWorker

        self._create_rule(
            name="Soldiers Post Send Persist Heartbeat",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        service1 = AlertService(self.service.db)
        orig_record_attempt = service1.repo.record_notification_attempt
        persist_started = threading.Event()

        def _slow_record_attempt(fields: dict):
            if fields.get("channel") == "wechat":
                persist_started.set()
                threading.Event().wait(0.55)
            return orig_record_attempt(fields)

        service1.repo.record_notification_attempt = _slow_record_attempt
        notifier1 = self._notifier(self._dispatch_result(True, channel="wechat"))
        notifier2 = self._notifier(self._dispatch_result(True, channel="wechat"))

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        w1_holder: dict = {}

        def _run_w1() -> None:
            w1 = AlertWorker(
                config_provider=lambda: self._config(),
                service=service1,
                notifier=notifier1,
                bar_delivery_lease_seconds=0.3,
            )
            w1_holder["stats"] = w1.run_once()

        w2 = AlertWorker(
            config_provider=lambda: self._config(),
            service=AlertService(self.service.db),
            notifier=notifier2,
            bar_delivery_lease_seconds=0.3,
        )
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            t1 = threading.Thread(target=_run_w1)
            t1.start()
            self.assertTrue(persist_started.wait(timeout=5))
            threading.Event().wait(0.40)
            w2_stats = w2.run_once()
            t1.join(timeout=5)

        self.assertEqual(w1_holder["stats"]["notified"], 1)
        self.assertEqual(w2_stats["notified"], 0)
        self.assertEqual(w2_stats["cooldown_suppressed"], 1)
        self.assertEqual(notifier1.send_with_results.call_count, 1)
        notifier2.send_with_results.assert_not_called()

    def test_kline_pattern_unrecorded_successful_delivery_does_not_replay_after_lease_expiry(self) -> None:
        from src.services.alert_worker import AlertWorker

        # Case A: attempt write fails after real send -> DB claim transitions to non-expiring delivery_unrecorded
        rule_db = self._create_rule(
            name="Soldiers Unrecorded Outcome DB Hold",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        service1 = AlertService(self.service.db)
        notifier1 = self._notifier(self._dispatch_result(True, channel="wechat"))
        notifier2 = self._notifier(self._dispatch_result(True, channel="wechat"))

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            with patch.object(service1.repo, "record_notification_attempt", side_effect=RuntimeError("db write failed")):
                w1_stats = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=service1,
                    notifier=notifier1,
                    bar_delivery_lease_seconds=0.2,
                ).run_once()
            threading.Event().wait(0.35)
            w2_stats = AlertWorker(
                config_provider=lambda: self._config(),
                service=AlertService(self.service.db),
                notifier=notifier2,
                bar_delivery_lease_seconds=0.2,
            ).run_once()

        self.assertEqual(w1_stats["notified"], 1)
        self.assertEqual(w2_stats["notified"], 0)
        self.assertEqual(w2_stats["cooldown_suppressed"], 1)
        self.assertEqual(notifier1.send_with_results.call_count, 1)
        notifier2.send_with_results.assert_not_called()

        triggers_db = self._triggers(rule_id=rule_db["id"], status="triggered")
        self.assertEqual(len(triggers_db), 1)
        notifs_db = self._notifications(trigger_id=triggers_db[0]["id"])
        self.assertTrue(
            any(item["channel"] == "__bar_delivery_claim__" and item.get("error_code") == "delivery_unrecorded" for item in notifs_db)
        )
        self.assertTrue(
            any(item["channel"] == "__bar_dedup__" and item.get("error_code") == "delivery_unrecorded" for item in notifs_db)
        )

        # Case B: both attempt write AND hold write fail transiently -> fallback holds trigger and flushes on recovery
        self.service.enable_rule(rule_db["id"], False)
        rule_fallback = self._create_rule(
            name="Soldiers Unrecorded Outcome Fallback Hold",
            target="600036",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        service3 = AlertService(self.service.db)
        notifier3 = self._notifier(self._dispatch_result(True, channel="wechat"))
        notifier4 = self._notifier(self._dispatch_result(True, channel="wechat"))
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            with patch.object(service3.repo, "record_notification_attempt", side_effect=RuntimeError("db write failed")), \
                 patch.object(service3.repo, "mark_bar_delivery_claim_unrecorded", side_effect=RuntimeError("db hold failed")):
                w3_stats = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=service3,
                    notifier=notifier3,
                    bar_delivery_lease_seconds=0.2,
                ).run_once()
            threading.Event().wait(0.35)
            w4_stats = AlertWorker(
                config_provider=lambda: self._config(),
                service=AlertService(self.service.db),
                notifier=notifier4,
                bar_delivery_lease_seconds=0.2,
            ).run_once()

        self.assertEqual(w3_stats["notified"], 1)
        self.assertEqual(w4_stats["notified"], 0)
        self.assertEqual(w4_stats["cooldown_suppressed"], 1)
        self.assertEqual(notifier3.send_with_results.call_count, 1)
        notifier4.send_with_results.assert_not_called()

        triggers_fb = self._triggers(rule_id=rule_fallback["id"], status="triggered")
        self.assertEqual(len(triggers_fb), 1)
        notifs_fb = self._notifications(trigger_id=triggers_fb[0]["id"])
        self.assertTrue(
            any(item["channel"] == "__bar_delivery_claim__" and item.get("error_code") == "delivery_unrecorded" for item in notifs_fb)
        )

        # Case C1: stable _db_reconciliation_key works across reopened DatabaseManager instances on same SQLite URL
        from src.services import alert_worker as alert_worker_mod

        self.service.enable_rule(rule_fallback["id"], False)
        rule_rebind = self._create_rule(
            name="Soldiers Unrecorded Rebind DB",
            target="601318",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        service_rebind_1 = AlertService(self.service.db)
        w_rebind_1 = AlertWorker(
            config_provider=lambda: self._config(),
            service=service_rebind_1,
            notifier=self._notifier(self._dispatch_result(True, channel="wechat")),
            bar_delivery_lease_seconds=0.2,
        )
        reconcile_key = w_rebind_1._db_reconciliation_key()
        self.assertTrue(reconcile_key.startswith("sqlite:"))
        self.assertIn(self.db_path.name, reconcile_key)

        notifier_rebind_2 = self._notifier(self._dispatch_result(True, channel="wechat"))
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            with patch.object(service_rebind_1.repo, "record_notification_attempt", side_effect=RuntimeError("db write failed")), \
                 patch.object(service_rebind_1.repo, "mark_bar_delivery_claim_unrecorded", side_effect=RuntimeError("db hold failed")):
                rb1_stats = w_rebind_1.run_once()
            threading.Event().wait(0.35)
            DatabaseManager.reset_instance()
            service_rebind_2 = AlertService()
            w_rebind_2 = AlertWorker(
                config_provider=lambda: self._config(),
                service=service_rebind_2,
                notifier=notifier_rebind_2,
                bar_delivery_lease_seconds=0.2,
            )
            self.assertEqual(w_rebind_2._db_reconciliation_key(), reconcile_key)
            self.assertIsNot(service_rebind_2.db, service_rebind_1.db)
            rb2_stats = w_rebind_2.run_once()

        self.assertEqual(rb1_stats["notified"], 1)
        self.assertEqual(rb2_stats["notified"], 0)
        self.assertEqual(rb2_stats["cooldown_suppressed"], 1)
        notifier_rebind_2.send_with_results.assert_not_called()

        # Case C2: simulated fresh process restart (empty _UNRECORDED_DELIVERIES + reopened DB) still blocks via dispatch_committed
        service_rebind_2.enable_rule(rule_rebind["id"], False)
        rule_restart = service_rebind_2.create_rule({
            "name": "Soldiers Unrecorded Fresh Process",
            "target_scope": "single_symbol",
            "target": "601398",
            "alert_type": "kline_pattern",
            "parameters": {"patterns": ["red_three_soldiers"]},
            "severity": "warning",
            "enabled": True,
            "cooldown_policy": {"cooldown_seconds": 0},
        })
        service_restart_1 = AlertService(service_rebind_2.db)
        notifier_restart_1 = self._notifier(self._dispatch_result(True, channel="wechat"))
        notifier_restart_2 = self._notifier(self._dispatch_result(True, channel="wechat"))
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            with patch.object(service_restart_1.repo, "record_notification_attempt", side_effect=RuntimeError("db write failed")), \
                 patch.object(service_restart_1.repo, "mark_bar_delivery_claim_unrecorded", side_effect=RuntimeError("db hold failed")):
                rs1_stats = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=service_restart_1,
                    notifier=notifier_restart_1,
                    bar_delivery_lease_seconds=0.2,
                ).run_once()
            threading.Event().wait(0.35)
            with alert_worker_mod._UNRECORDED_DELIVERIES_LOCK:
                alert_worker_mod._UNRECORDED_DELIVERIES.clear()
            DatabaseManager.reset_instance()
            service_restart_2 = AlertService()
            rs2_stats = AlertWorker(
                config_provider=lambda: self._config(),
                service=service_restart_2,
                notifier=notifier_restart_2,
                bar_delivery_lease_seconds=0.2,
            ).run_once()

        self.assertEqual(rs1_stats["notified"], 1)
        self.assertEqual(rs2_stats["notified"], 0)
        self.assertEqual(rs2_stats["cooldown_suppressed"], 1)
        self.assertEqual(notifier_restart_1.send_with_results.call_count, 1)
        notifier_restart_2.send_with_results.assert_not_called()
        restart_triggers = service_restart_2.list_triggers(page_size=100, rule_id=rule_restart["id"], status="triggered")["items"]
        self.assertEqual(len(restart_triggers), 1)
        restart_notifs = service_restart_2.list_notifications(page_size=100, trigger_id=restart_triggers[0]["id"])["items"]
        self.assertTrue(
            any(item["channel"] == "__bar_delivery_claim__" and item.get("error_code") == "dispatch_committed" for item in restart_notifs)
        )
        self.assertTrue(
            any(item["channel"] == "__bar_dedup__" and item.get("error_code") == "delivery_unrecorded" for item in restart_notifs)
        )

    def test_kline_pattern_ambiguous_ntfy_transport_failure_holds_barrier_without_replay(self) -> None:
        import requests
        from src.notification import NotificationService
        from src.services.alert_worker import AlertWorker

        rule_ntfy = self._create_rule(
            name="Soldiers Ntfy Ambiguous Timeout",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        ok_resp = MagicMock(status_code=200, text="ok")
        try:
            with patch.dict(os.environ, {"NTFY_URL": "https://ntfy.example.test/alerts"}, clear=False):
                Config.reset_instance()
                notifier_1 = NotificationService()
                notifier_2 = NotificationService()

            patch_post = patch(
                "src.notification_sender.ntfy_sender.requests.post",
                side_effect=[requests.exceptions.Timeout("read timed out after accept"), ok_resp],
            )
            with patch("data_provider.DataFetcherManager", return_value=manager), \
                 patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
                 patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
                 patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
                 patch_post as mock_post:
                first = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=AlertService(self.service.db),
                    notifier=notifier_1,
                    bar_delivery_lease_seconds=0.2,
                ).run_once()
                threading.Event().wait(0.35)
                second = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=AlertService(self.service.db),
                    notifier=notifier_2,
                    bar_delivery_lease_seconds=0.2,
                ).run_once()
        finally:
            Config.reset_instance()

        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(first["notified"], 0)
        self.assertEqual(second["notified"], 0)
        self.assertEqual(second["cooldown_suppressed"], 1)

        ntfy_triggers = self._triggers(rule_id=rule_ntfy["id"], status="triggered")
        self.assertEqual(len(ntfy_triggers), 1)
        ntfy_notifs = self._notifications(trigger_id=ntfy_triggers[0]["id"])
        self.assertTrue(
            any(item["channel"] == "__bar_delivery_claim__" and item.get("error_code") == "delivery_unrecorded" for item in ntfy_notifs)
        )
        self.assertTrue(
            any(item["channel"] == "__bar_dedup__" and item.get("error_code") == "delivery_unrecorded" for item in ntfy_notifs)
        )

        # Definite non-delivery (dispatched=False, status="no_channel") releases barrier for clean retry
        self.service.enable_rule(rule_ntfy["id"], False)
        rule_no_chan = self._create_rule(
            name="Soldiers Definite No Channel Retry",
            target="600036",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        notifier_nc = self._notifier(
            self._dispatch_result(False, dispatched=False, status="no_channel"),
            self._dispatch_result(True, channel="wechat"),
        )
        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
             patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
             patch("src.services.alert_indicators.get_market_now", return_value=market_now):
            nc_first = AlertWorker(
                config_provider=lambda: self._config(),
                service=AlertService(self.service.db),
                notifier=notifier_nc,
            ).run_once()
            nc_second = AlertWorker(
                config_provider=lambda: self._config(),
                service=AlertService(self.service.db),
                notifier=notifier_nc,
            ).run_once()

        self.assertEqual(nc_first["notified"], 0)
        self.assertEqual(nc_second["notified"], 1)
        self.assertEqual(notifier_nc.send_with_results.call_count, 2)
        nc_triggers = self._triggers(rule_id=rule_no_chan["id"], status="triggered")
        self.assertEqual(len(nc_triggers), 1)
        nc_notifs = self._notifications(trigger_id=nc_triggers[0]["id"])
        self.assertTrue(any(item["channel"] == "wechat" and item.get("success") is True for item in nc_notifs))
        self.assertFalse(any(item["channel"] == "__bar_delivery_claim__" for item in nc_notifs))

    def test_kline_pattern_telegram_ambiguous_response_does_not_duplicate_within_single_poll(self) -> None:
        import requests
        from src.notification import NotificationService
        from src.services.alert_worker import AlertWorker

        rule = self._create_rule(
            name="Soldiers Telegram Ambiguous ReadTimeout",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        ok_resp = MagicMock(status_code=200)
        ok_resp.json.return_value = {"ok": True}
        try:
            with patch.dict(
                os.environ,
                {"TELEGRAM_BOT_TOKEN": "test-bot", "TELEGRAM_CHAT_ID": "123456"},
                clear=False,
            ):
                Config.reset_instance()
                notifier_1 = NotificationService()
                notifier_2 = NotificationService()

            patch_post = patch(
                "src.notification_sender.telegram_sender.requests.post",
                side_effect=[requests.exceptions.ReadTimeout("response lost after accept"), ok_resp],
            )
            patch_sleep = patch("src.notification_sender.telegram_sender.time.sleep")
            with patch("data_provider.DataFetcherManager", return_value=manager), \
                 patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
                 patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
                 patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
                 patch_post as mock_post, \
                 patch_sleep as mock_sleep:
                first = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=AlertService(self.service.db),
                    notifier=notifier_1,
                    bar_delivery_lease_seconds=0.2,
                ).run_once()
                threading.Event().wait(0.35)
                second = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=AlertService(self.service.db),
                    notifier=notifier_2,
                    bar_delivery_lease_seconds=0.2,
                ).run_once()
        finally:
            Config.reset_instance()

        mock_sleep.assert_not_called()
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(first["notified"], 0)
        self.assertEqual(second["notified"], 0)
        self.assertEqual(second["cooldown_suppressed"], 1)

        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        notifs = self._notifications(trigger_id=triggers[0]["id"])
        self.assertTrue(
            any(item["channel"] == "__bar_delivery_claim__" and item.get("error_code") == "delivery_unrecorded" for item in notifs)
        )
        self.assertTrue(
            any(item["channel"] == "__bar_dedup__" and item.get("error_code") == "delivery_unrecorded" for item in notifs)
        )

    def test_kline_pattern_ntfy_connect_timeout_confirms_absent_and_allows_clean_retry(self) -> None:
        import requests
        from src.notification import NotificationService
        from src.services.alert_worker import AlertWorker

        rule = self._create_rule(
            name="Soldiers Ntfy ConnectTimeout Retry",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        ok_resp = MagicMock(status_code=200, text="ok")
        try:
            with patch.dict(os.environ, {"NTFY_URL": "https://ntfy.example.test/alerts"}, clear=False):
                Config.reset_instance()
                notifier_1 = NotificationService()
                notifier_2 = NotificationService()
                notifier_3 = NotificationService()

            patch_post = patch(
                "src.notification_sender.ntfy_sender.requests.post",
                side_effect=[requests.exceptions.ConnectTimeout("connect timed out"), ok_resp],
            )
            with patch("data_provider.DataFetcherManager", return_value=manager), \
                 patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
                 patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
                 patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
                 patch_post as mock_post:
                first = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=AlertService(self.service.db),
                    notifier=notifier_1,
                ).run_once()
                second = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=AlertService(self.service.db),
                    notifier=notifier_2,
                ).run_once()
                third = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=AlertService(self.service.db),
                    notifier=notifier_3,
                ).run_once()
        finally:
            Config.reset_instance()

        self.assertEqual(first["notified"], 0)
        self.assertEqual(second["notified"], 1)
        self.assertEqual(third["notified"], 0)
        self.assertEqual(third["cooldown_suppressed"], 1)
        self.assertEqual(mock_post.call_count, 2)

        triggers = self._triggers(rule_id=rule["id"], status="triggered")
        self.assertEqual(len(triggers), 1)
        notifs = self._notifications(trigger_id=triggers[0]["id"])
        self.assertFalse(any(item["channel"] == "__bar_delivery_claim__" for item in notifs))
        self.assertTrue(
            any(item["channel"] == "ntfy" and item.get("error_code") == "connect_timeout" and not item["success"] for item in notifs)
        )
        self.assertTrue(any(item["channel"] == "ntfy" and item["success"] is True for item in notifs))
        self.assertTrue(any(item["channel"] == "__bar_dedup__" and item.get("error_code") == "already_delivered" for item in notifs))

    def test_kline_pattern_incomplete_200_response_is_ambiguous_for_feishu_and_telegram(self) -> None:
        from src.notification import NotificationService

        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        # Case A: Feishu webhook returns HTTP 200 {} -> no card->text fallback & no cross-poll replay
        feishu_rule = self._create_rule(
            name="Soldiers Feishu Incomplete 200",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        feishu_poll1_resp = MagicMock()
        feishu_poll1_resp.status_code = 200
        feishu_poll1_resp.text = "{}"
        feishu_poll1_resp.json.return_value = {}
        feishu_poll2_resp = MagicMock()
        feishu_poll2_resp.status_code = 200
        feishu_poll2_resp.text = '{"code": 0}'
        feishu_poll2_resp.json.return_value = {"code": 0}

        feishu_env = {
            "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            "FEISHU_WEBHOOK_KEYWORD": "",
            "FEISHU_APP_ID": "",
            "FEISHU_APP_SECRET": "",
            "FEISHU_CHAT_ID": "",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
            "NTFY_URL": "",
        }
        try:
            with patch.dict(os.environ, feishu_env, clear=False):
                Config.reset_instance()
                notifier_1 = NotificationService()
                notifier_2 = NotificationService()
                worker_1 = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=AlertService(self.service.db),
                    notifier=notifier_1,
                )
                worker_2 = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=AlertService(self.service.db),
                    notifier=notifier_2,
                )
                feishu_resps = [feishu_poll1_resp, feishu_poll2_resp]
                with patch("data_provider.DataFetcherManager", return_value=manager), \
                     patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
                     patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
                     patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
                     patch("src.notification_sender.feishu_sender.requests.post", side_effect=feishu_resps) as mock_feishu_post:
                    w1_stats = worker_1.run_once()
                    w2_stats = worker_2.run_once()
        finally:
            Config.reset_instance()

        self.assertEqual(mock_feishu_post.call_count, 1)
        self.assertEqual(w1_stats["notified"], 0)
        self.assertEqual(w2_stats["notified"], 0)
        self.assertEqual(w2_stats["cooldown_suppressed"], 1)
        feishu_triggers = self._triggers(rule_id=feishu_rule["id"], status="triggered")
        self.assertEqual(len(feishu_triggers), 1)
        feishu_notifs = self._notifications(trigger_id=feishu_triggers[0]["id"])
        self.assertTrue(
            any(item["channel"] == "feishu" and item.get("error_code") == "invalid_response" for item in feishu_notifs)
        )
        self.assertTrue(
            any(
                item["channel"] == "__bar_delivery_claim__" and item.get("error_code") == "delivery_unrecorded"
                for item in feishu_notifs
            )
        )
        self.assertTrue(
            any(item["channel"] == "__bar_dedup__" and item.get("error_code") == "delivery_unrecorded" for item in feishu_notifs)
        )

        # Case B: Telegram returns HTTP 200 {} -> treated as ambiguous invalid_response, no cross-poll replay
        tg_rule = self._create_rule(
            name="Soldiers Telegram Incomplete 200",
            target="000001",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        tg_poll1_resp = MagicMock()
        tg_poll1_resp.status_code = 200
        tg_poll1_resp.text = "{}"
        tg_poll1_resp.json.return_value = {}
        tg_poll2_resp = MagicMock()
        tg_poll2_resp.status_code = 200
        tg_poll2_resp.text = '{"ok": true}'
        tg_poll2_resp.json.return_value = {"ok": True}

        tg_env = {
            "FEISHU_WEBHOOK_URL": "",
            "FEISHU_WEBHOOK_KEYWORD": "",
            "FEISHU_APP_ID": "",
            "FEISHU_APP_SECRET": "",
            "FEISHU_CHAT_ID": "",
            "TELEGRAM_BOT_TOKEN": "test-bot",
            "TELEGRAM_CHAT_ID": "123456",
            "NTFY_URL": "",
        }
        try:
            with patch.dict(os.environ, tg_env, clear=False):
                Config.reset_instance()
                notifier_1 = NotificationService()
                notifier_2 = NotificationService()
                worker_1 = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=AlertService(self.service.db),
                    notifier=notifier_1,
                )
                worker_2 = AlertWorker(
                    config_provider=lambda: self._config(),
                    service=AlertService(self.service.db),
                    notifier=notifier_2,
                )
                tg_resps = [tg_poll1_resp, tg_poll2_resp]
                with patch("data_provider.DataFetcherManager", return_value=manager), \
                     patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
                     patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
                     patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
                     patch("src.notification_sender.telegram_sender.requests.post", side_effect=tg_resps) as mock_tg_post:
                    tg_w1_stats = worker_1.run_once()
                    tg_w2_stats = worker_2.run_once()
        finally:
            Config.reset_instance()

        self.assertEqual(mock_tg_post.call_count, 1)
        self.assertEqual(tg_w1_stats["notified"], 0)
        self.assertEqual(tg_w2_stats["notified"], 0)
        # feishu_rule from Case A and tg_rule from Case B are both held on Poll 2
        self.assertEqual(tg_w2_stats["cooldown_suppressed"], 2)
        tg_triggers = self._triggers(rule_id=tg_rule["id"], status="triggered")
        self.assertEqual(len(tg_triggers), 1)
        tg_notifs = self._notifications(trigger_id=tg_triggers[0]["id"])
        self.assertTrue(
            any(item["channel"] == "telegram" and item.get("error_code") == "invalid_response" for item in tg_notifs)
        )
        self.assertTrue(
            any(
                item["channel"] == "__bar_delivery_claim__" and item.get("error_code") == "delivery_unrecorded"
                for item in tg_notifs
            )
        )
        self.assertTrue(
            any(item["channel"] == "__bar_dedup__" and item.get("error_code") == "delivery_unrecorded" for item in tg_notifs)
        )

    def test_kline_pattern_feishu_preflight_keyword_budget_rejection_allows_retry_after_fix(self) -> None:
        from src.notification import NotificationService

        rule = self._create_rule(
            name="Soldiers Feishu Keyword Preflight",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.text = '{"code": 0}'
        ok_resp.json.return_value = {"code": 0}

        try:
            with patch("data_provider.DataFetcherManager", return_value=manager), \
                 patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
                 patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
                 patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
                 patch("src.notification_sender.feishu_sender.requests.post", return_value=ok_resp) as mock_post:
                bad_env = {
                    "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
                    "FEISHU_WEBHOOK_KEYWORD": "K" * 20500,
                    "FEISHU_APP_ID": "",
                    "FEISHU_APP_SECRET": "",
                    "FEISHU_CHAT_ID": "",
                    "TELEGRAM_BOT_TOKEN": "",
                    "TELEGRAM_CHAT_ID": "",
                    "NTFY_URL": "",
                }
                with patch.dict(os.environ, bad_env, clear=False):
                    Config.reset_instance()
                    notifier_1 = NotificationService()
                    worker_1 = AlertWorker(
                        config_provider=lambda: self._config(),
                        service=AlertService(self.service.db),
                        notifier=notifier_1,
                    )
                    w1_stats = worker_1.run_once()

                self.assertEqual(mock_post.call_count, 0)
                self.assertEqual(w1_stats["notified"], 0)
                triggers_p1 = self._triggers(rule_id=rule["id"], status="triggered")
                self.assertEqual(len(triggers_p1), 1)
                notifs_p1 = self._notifications(trigger_id=triggers_p1[0]["id"])
                self.assertTrue(
                    any(item["channel"] == "feishu" and item.get("error_code") == "payload_too_large" for item in notifs_p1)
                )
                self.assertFalse(any(item["channel"] == "__bar_delivery_claim__" for item in notifs_p1))

                good_env = dict(bad_env, FEISHU_WEBHOOK_KEYWORD="")
                with patch.dict(os.environ, good_env, clear=False):
                    Config.reset_instance()
                    notifier_2 = NotificationService()
                    notifier_3 = NotificationService()
                    worker_2 = AlertWorker(
                        config_provider=lambda: self._config(),
                        service=AlertService(self.service.db),
                        notifier=notifier_2,
                    )
                    worker_3 = AlertWorker(
                        config_provider=lambda: self._config(),
                        service=AlertService(self.service.db),
                        notifier=notifier_3,
                    )
                    w2_stats = worker_2.run_once()
                    w3_stats = worker_3.run_once()
        finally:
            Config.reset_instance()

        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(w2_stats["notified"], 1)
        self.assertEqual(w3_stats["notified"], 0)
        self.assertEqual(w3_stats["cooldown_suppressed"], 1)
        triggers_all = self._triggers(rule_id=rule["id"], status="triggered")
        notifs_all = [n for t in triggers_all for n in self._notifications(trigger_id=t["id"])]
        self.assertFalse(any(item["channel"] == "__bar_delivery_claim__" for item in notifs_all))
        self.assertTrue(any(item["channel"] == "feishu" and item["success"] is True for item in notifs_all))
        self.assertTrue(
            any(item["channel"] == "__bar_dedup__" and item.get("error_code") == "already_delivered" for item in notifs_all)
        )

    def test_kline_pattern_feishu_malformed_string_status_codes_are_ambiguous_without_fallback(self) -> None:
        from src.notification import NotificationService

        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        feishu_env = {
            "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            "FEISHU_WEBHOOK_KEYWORD": "",
            "FEISHU_APP_ID": "",
            "FEISHU_APP_SECRET": "",
            "FEISHU_CHAT_ID": "",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
            "NTFY_URL": "",
        }
        cases = [
            ("Soldiers Feishu String Unknown Code", "600519", {"code": "unknown"}, 1),
            ("Soldiers Feishu String Zero Code", "000001", {"code": "0"}, 2),
        ]
        try:
            with patch.dict(os.environ, feishu_env, clear=False):
                for rule_name, target_code, bad_payload, expected_suppressed in cases:
                    rule = self._create_rule(
                        name=rule_name,
                        target=target_code,
                        alert_type="kline_pattern",
                        parameters={"patterns": ["red_three_soldiers"]},
                        cooldown_policy={"cooldown_seconds": 0},
                    )
                    poll1_resp = MagicMock()
                    poll1_resp.status_code = 200
                    poll1_resp.text = json.dumps(bad_payload)
                    poll1_resp.json.return_value = bad_payload
                    poll2_resp = MagicMock()
                    poll2_resp.status_code = 200
                    poll2_resp.text = '{"code": 0}'
                    poll2_resp.json.return_value = {"code": 0}
                    resps = [poll1_resp, poll2_resp]

                    Config.reset_instance()
                    notifier_1 = NotificationService()
                    notifier_2 = NotificationService()
                    worker_1 = AlertWorker(
                        config_provider=lambda: self._config(),
                        service=AlertService(self.service.db),
                        notifier=notifier_1,
                    )
                    worker_2 = AlertWorker(
                        config_provider=lambda: self._config(),
                        service=AlertService(self.service.db),
                        notifier=notifier_2,
                    )
                    with patch("data_provider.DataFetcherManager", return_value=manager), \
                         patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
                         patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
                         patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
                         patch("src.notification_sender.feishu_sender.requests.post", side_effect=resps) as mock_post:
                        w1_stats = worker_1.run_once()
                        w2_stats = worker_2.run_once()

                    self.assertEqual(mock_post.call_count, 1)
                    self.assertEqual(w1_stats["notified"], 0)
                    self.assertEqual(w2_stats["notified"], 0)
                    self.assertEqual(w2_stats["cooldown_suppressed"], expected_suppressed)
                    triggers = self._triggers(rule_id=rule["id"], status="triggered")
                    self.assertEqual(len(triggers), 1)
                    notifs = self._notifications(trigger_id=triggers[0]["id"])
                    self.assertTrue(
                        any(item["channel"] == "feishu" and item.get("error_code") == "invalid_response" for item in notifs)
                    )
                    self.assertTrue(
                        any(
                            item["channel"] == "__bar_delivery_claim__" and item.get("error_code") == "delivery_unrecorded"
                            for item in notifs
                        )
                    )
                    self.assertTrue(
                        any(item["channel"] == "__bar_dedup__" and item.get("error_code") == "delivery_unrecorded" for item in notifs)
                    )
        finally:
            Config.reset_instance()

    def test_kline_pattern_feishu_malformed_webhook_url_confirms_absent_and_retries_after_fix(self) -> None:
        from src.notification import NotificationService

        rule = self._create_rule(
            name="Soldiers Feishu Malformed URL",
            target="600519",
            alert_type="kline_pattern",
            parameters={"patterns": ["red_three_soldiers"]},
            cooldown_policy={"cooldown_seconds": 0},
        )
        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.text = '{"code": 0}'
        ok_resp.json.return_value = {"code": 0}

        try:
            with patch("data_provider.DataFetcherManager", return_value=manager), \
                 patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
                 patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
                 patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
                 patch("src.notification_sender.feishu_sender.requests.post", return_value=ok_resp) as mock_post:
                bad_env = {
                    "FEISHU_WEBHOOK_URL": "not-a-url",
                    "FEISHU_WEBHOOK_KEYWORD": "",
                    "FEISHU_APP_ID": "",
                    "FEISHU_APP_SECRET": "",
                    "FEISHU_CHAT_ID": "",
                    "TELEGRAM_BOT_TOKEN": "",
                    "TELEGRAM_CHAT_ID": "",
                    "NTFY_URL": "",
                }
                with patch.dict(os.environ, bad_env, clear=False):
                    Config.reset_instance()
                    notifier_1 = NotificationService()
                    worker_1 = AlertWorker(
                        config_provider=lambda: self._config(),
                        service=AlertService(self.service.db),
                        notifier=notifier_1,
                    )
                    w1_stats = worker_1.run_once()

                self.assertEqual(mock_post.call_count, 0)
                self.assertEqual(w1_stats["notified"], 0)
                triggers_p1 = self._triggers(rule_id=rule["id"], status="triggered")
                self.assertEqual(len(triggers_p1), 1)
                notifs_p1 = self._notifications(trigger_id=triggers_p1[0]["id"])
                self.assertTrue(
                    any(item["channel"] == "feishu" and item.get("error_code") == "invalid_config" for item in notifs_p1)
                )
                self.assertFalse(any(item["channel"] == "__bar_delivery_claim__" for item in notifs_p1))

                good_env = dict(bad_env, FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/test")
                with patch.dict(os.environ, good_env, clear=False):
                    Config.reset_instance()
                    notifier_2 = NotificationService()
                    notifier_3 = NotificationService()
                    worker_2 = AlertWorker(
                        config_provider=lambda: self._config(),
                        service=AlertService(self.service.db),
                        notifier=notifier_2,
                    )
                    worker_3 = AlertWorker(
                        config_provider=lambda: self._config(),
                        service=AlertService(self.service.db),
                        notifier=notifier_3,
                    )
                    w2_stats = worker_2.run_once()
                    w3_stats = worker_3.run_once()
        finally:
            Config.reset_instance()

        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(w2_stats["notified"], 1)
        self.assertEqual(w3_stats["notified"], 0)
        self.assertEqual(w3_stats["cooldown_suppressed"], 1)
        triggers_all = self._triggers(rule_id=rule["id"], status="triggered")
        notifs_all = [n for t in triggers_all for n in self._notifications(trigger_id=t["id"])]
        self.assertFalse(any(item["channel"] == "__bar_delivery_claim__" for item in notifs_all))
        self.assertTrue(any(item["channel"] == "feishu" and item["success"] is True for item in notifs_all))
        self.assertTrue(
            any(item["channel"] == "__bar_dedup__" and item.get("error_code") == "already_delivered" for item in notifs_all)
        )

    def test_kline_pattern_http_307_redirect_is_disabled_and_treated_as_ambiguous_across_senders(self) -> None:
        import requests
        from src.notification import NotificationService

        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        def _make_response(request, status_code: int, body: bytes, location: str = "") -> requests.Response:
            resp = requests.Response()
            resp.status_code = status_code
            resp.url = request.url
            resp.request = request
            resp._content = body
            resp.headers["Content-Type"] = "application/json"
            if location:
                resp.headers["Location"] = location
            return resp

        base_env = {
            "FEISHU_WEBHOOK_URL": "",
            "FEISHU_WEBHOOK_KEYWORD": "",
            "FEISHU_APP_ID": "",
            "FEISHU_APP_SECRET": "",
            "FEISHU_CHAT_ID": "",
            "DISCORD_WEBHOOK_URL": "",
            "DISCORD_BOT_TOKEN": "",
            "DISCORD_MAIN_CHANNEL_ID": "",
            "NTFY_URL": "",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
        }
        cases = [
            (
                "feishu",
                "600519",
                {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"},
                "http_3xx",
                b'{"code": 0}',
                200,
                None,
            ),
            (
                "discord",
                "000001",
                {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123456/test"},
                "http_3xx",
                b"",
                204,
                None,
            ),
            (
                "ntfy",
                "600036",
                {"NTFY_URL": "https://ntfy.example.test/alerts"},
                "http_3xx",
                b'{"id": "ok"}',
                200,
                None,
            ),
            (
                "telegram",
                "000858",
                {"TELEGRAM_BOT_TOKEN": "test-bot", "TELEGRAM_CHAT_ID": "123456"},
                "http_3xx",
                b'{"ok": true}',
                200,
                None,
            ),
            (
                "feishu",
                "300750",
                {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"},
                "connection_error",
                b'{"code": 0}',
                200,
                requests.exceptions.InvalidSchema("post-send redirect error"),
            ),
        ]

        try:
            for idx, (channel_name, stock_code, ch_env, exp_err, ok_body, ok_status, poll1_exc) in enumerate(cases, start=1):
                rule = self._create_rule(
                    name=f"Soldiers Redirect Guard {idx} {channel_name}",
                    target=stock_code,
                    alert_type="kline_pattern",
                    parameters={"patterns": ["red_three_soldiers"]},
                    cooldown_policy={"cooldown_seconds": 0},
                )
                call_idx = {"n": 0}

                def _adapter_send(_adapter, request, **_kwargs):
                    call_idx["n"] += 1
                    if call_idx["n"] == 1:
                        if poll1_exc is not None:
                            raise poll1_exc
                        return _make_response(
                            request,
                            307,
                            b"redirect markdown",
                            location="ftp://unsupported.invalid/hook",
                        )
                    return _make_response(request, ok_status, ok_body)

                run_env = dict(base_env, **ch_env)
                with patch.dict(os.environ, run_env, clear=False):
                    Config.reset_instance()
                    notifier_1 = NotificationService()
                    notifier_2 = NotificationService()
                    worker_1 = AlertWorker(
                        config_provider=lambda: self._config(),
                        service=AlertService(self.service.db),
                        notifier=notifier_1,
                    )
                    worker_2 = AlertWorker(
                        config_provider=lambda: self._config(),
                        service=AlertService(self.service.db),
                        notifier=notifier_2,
                    )
                    adapter_patch = patch("requests.adapters.HTTPAdapter.send", autospec=True, side_effect=_adapter_send)
                    with patch("data_provider.DataFetcherManager", return_value=manager), \
                         patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
                         patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
                         patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
                         adapter_patch as mock_adapter_send:
                        w1_stats = worker_1.run_once()
                        w2_stats = worker_2.run_once()

                self.assertEqual(mock_adapter_send.call_count, 1)
                self.assertEqual(w1_stats["notified"], 0)
                self.assertEqual(w2_stats["notified"], 0)
                self.assertEqual(w2_stats["cooldown_suppressed"], idx)
                triggers = self._triggers(rule_id=rule["id"], status="triggered")
                self.assertEqual(len(triggers), 1)
                notifs = self._notifications(trigger_id=triggers[0]["id"])
                self.assertTrue(
                    any(item["channel"] == channel_name and item.get("error_code") == exp_err for item in notifs)
                )
                self.assertTrue(
                    any(
                        item["channel"] == "__bar_delivery_claim__" and item.get("error_code") == "delivery_unrecorded"
                        for item in notifs
                    )
                )
                self.assertTrue(
                    any(item["channel"] == "__bar_dedup__" and item.get("error_code") == "delivery_unrecorded" for item in notifs)
                )
        finally:
            Config.reset_instance()

    def test_kline_pattern_requests_prepare_malformed_label_url_recovers_after_fix(self) -> None:
        import requests
        from src.notification import NotificationService

        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        def _make_ok_response(request, body: bytes) -> requests.Response:
            resp = requests.Response()
            resp.status_code = 200
            resp.url = request.url
            resp.request = request
            resp._content = body
            resp.headers["Content-Type"] = "application/json"
            return resp

        base_env = {
            "FEISHU_WEBHOOK_URL": "",
            "FEISHU_WEBHOOK_KEYWORD": "",
            "FEISHU_APP_ID": "",
            "FEISHU_APP_SECRET": "",
            "FEISHU_CHAT_ID": "",
            "DISCORD_WEBHOOK_URL": "",
            "DISCORD_BOT_TOKEN": "",
            "DISCORD_MAIN_CHANNEL_ID": "",
            "NTFY_URL": "",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
        }
        cases = [
            (
                "feishu",
                "600519",
                {"FEISHU_WEBHOOK_URL": "https://.example.invalid/hook"},
                {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test"},
                "feishu",
                "invalid_config",
                b'{"code": 0}',
                1,
            ),
            (
                "ntfy",
                "000001",
                {"NTFY_URL": "https://.example.invalid/alerts"},
                {"NTFY_URL": "https://ntfy.example.test/alerts"},
                "__no_channel__",
                "no_channel",
                b'{"id": "ok"}',
                2,
            ),
            (
                "discord",
                "600036",
                {"DISCORD_WEBHOOK_URL": "https://.example.invalid/webhook"},
                {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123456/test"},
                "discord",
                "invalid_config",
                b"",
                3,
            ),
        ]

        try:
            for idx, (
                channel_name,
                stock_code,
                bad_ch_env,
                good_ch_env,
                exp_p1_ch,
                exp_p1_err,
                ok_body,
                exp_suppressed,
            ) in enumerate(cases, start=1):
                rule = self._create_rule(
                    name=f"Soldiers Prepare URL Guard {idx} {channel_name}",
                    target=stock_code,
                    alert_type="kline_pattern",
                    parameters={"patterns": ["red_three_soldiers"]},
                    cooldown_policy={"cooldown_seconds": 0},
                )

                def _adapter_send(_adapter, request, **_kwargs):
                    return _make_ok_response(request, ok_body)

                adapter_patch = patch("requests.adapters.HTTPAdapter.send", autospec=True, side_effect=_adapter_send)
                with patch("data_provider.DataFetcherManager", return_value=manager), \
                     patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
                     patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
                     patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
                     adapter_patch as mock_adapter_send:
                    bad_env = dict(base_env, **bad_ch_env)
                    with patch.dict(os.environ, bad_env, clear=False):
                        Config.reset_instance()
                        notifier_1 = NotificationService()
                        worker_1 = AlertWorker(
                            config_provider=lambda: self._config(),
                            service=AlertService(self.service.db),
                            notifier=notifier_1,
                        )
                        w1_stats = worker_1.run_once()

                    self.assertEqual(mock_adapter_send.call_count, 0)
                    self.assertEqual(w1_stats["notified"], 0)
                    triggers_p1 = self._triggers(rule_id=rule["id"], status="triggered")
                    self.assertEqual(len(triggers_p1), 1)
                    notifs_p1 = self._notifications(trigger_id=triggers_p1[0]["id"])
                    self.assertTrue(
                        any(item["channel"] == exp_p1_ch and item.get("error_code") == exp_p1_err for item in notifs_p1)
                    )
                    self.assertFalse(any(item["channel"] == "__bar_delivery_claim__" for item in notifs_p1))

                    good_env = dict(base_env, **good_ch_env)
                    with patch.dict(os.environ, good_env, clear=False):
                        Config.reset_instance()
                        notifier_2 = NotificationService()
                        notifier_3 = NotificationService()
                        worker_2 = AlertWorker(
                            config_provider=lambda: self._config(),
                            service=AlertService(self.service.db),
                            notifier=notifier_2,
                        )
                        worker_3 = AlertWorker(
                            config_provider=lambda: self._config(),
                            service=AlertService(self.service.db),
                            notifier=notifier_3,
                        )
                        w2_stats = worker_2.run_once()
                        w3_stats = worker_3.run_once()

                self.assertEqual(mock_adapter_send.call_count, 1)
                self.assertEqual(w2_stats["notified"], 1)
                self.assertEqual(w3_stats["notified"], 0)
                self.assertEqual(w3_stats["cooldown_suppressed"], exp_suppressed)
                triggers_all = self._triggers(rule_id=rule["id"], status="triggered")
                notifs_all = [n for t in triggers_all for n in self._notifications(trigger_id=t["id"])]
                self.assertFalse(any(item["channel"] == "__bar_delivery_claim__" for item in notifs_all))
                self.assertTrue(any(item["channel"] == channel_name and item["success"] is True for item in notifs_all))
                self.assertTrue(
                    any(
                        item["channel"] == "__bar_dedup__" and item.get("error_code") == "already_delivered"
                        for item in notifs_all
                    )
                )
        finally:
            Config.reset_instance()

    def test_kline_pattern_non_latin1_header_token_confirms_absent_and_recovers_after_fix(self) -> None:
        import requests
        from src.notification import NotificationService

        base = [
            (20.0 + (0.03 if i % 2 == 0 else -0.02), 20.1, 19.9, 20.02, 1_000_000.0)
            for i in range(20)
        ]
        soldiers = [
            (20.1, 20.65, 20.05, 20.60, 1_200_000.0),
            (20.5, 21.15, 20.45, 21.10, 1_500_000.0),
            (21.0, 21.75, 20.95, 21.70, 1_900_000.0),
        ]
        df = pd.DataFrame(base + soldiers, columns=["open", "high", "low", "close", "volume"])
        df["date"] = pd.date_range("2026-01-05", periods=len(df), freq="B")
        last_dt = df["date"].iloc[-1].date()
        market_now = datetime(last_dt.year, last_dt.month, last_dt.day, 15, 5)
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        def _make_ok_response(request, body: bytes) -> requests.Response:
            resp = requests.Response()
            resp.status_code = 200
            resp.url = request.url
            resp.request = request
            resp._content = body
            resp.headers["Content-Type"] = "application/json"
            return resp

        base_env = {
            "FEISHU_WEBHOOK_URL": "",
            "FEISHU_WEBHOOK_KEYWORD": "",
            "FEISHU_APP_ID": "",
            "FEISHU_APP_SECRET": "",
            "FEISHU_CHAT_ID": "",
            "DISCORD_WEBHOOK_URL": "",
            "DISCORD_BOT_TOKEN": "",
            "DISCORD_MAIN_CHANNEL_ID": "",
            "NTFY_URL": "",
            "NTFY_TOKEN": "",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
        }
        cases = [
            (
                "ntfy",
                "600519",
                {"NTFY_URL": "https://ntfy.example.test/alerts", "NTFY_TOKEN": "bad\u2019token"},
                {"NTFY_URL": "https://ntfy.example.test/alerts", "NTFY_TOKEN": "valid-token"},
                b'{"id": "ok"}',
                1,
            ),
            (
                "discord",
                "000001",
                {"DISCORD_BOT_TOKEN": "bot\u2019token", "DISCORD_MAIN_CHANNEL_ID": "123456"},
                {"DISCORD_BOT_TOKEN": "valid-bot-token", "DISCORD_MAIN_CHANNEL_ID": "123456"},
                b'{"id": "1"}',
                2,
            ),
        ]

        try:
            for idx, (channel_name, stock_code, bad_ch_env, good_ch_env, ok_body, exp_suppressed) in enumerate(cases, start=1):
                rule = self._create_rule(
                    name=f"Soldiers Header Encoding Guard {idx} {channel_name}",
                    target=stock_code,
                    alert_type="kline_pattern",
                    parameters={"patterns": ["red_three_soldiers"]},
                    cooldown_policy={"cooldown_seconds": 0},
                )

                def _adapter_send(_adapter, request, **_kwargs):
                    return _make_ok_response(request, ok_body)

                adapter_patch = patch("requests.adapters.HTTPAdapter.send", autospec=True, side_effect=_adapter_send)
                with patch("data_provider.DataFetcherManager", return_value=manager), \
                     patch("src.services.alert_service.asyncio.to_thread", new=_run_inline), \
                     patch("src.services.alert_indicators.get_effective_trading_date", return_value=last_dt), \
                     patch("src.services.alert_indicators.get_market_now", return_value=market_now), \
                     adapter_patch as mock_adapter_send:
                    bad_env = dict(base_env, **bad_ch_env)
                    with patch.dict(os.environ, bad_env, clear=False):
                        Config.reset_instance()
                        notifier_1 = NotificationService()
                        worker_1 = AlertWorker(
                            config_provider=lambda: self._config(),
                            service=AlertService(self.service.db),
                            notifier=notifier_1,
                        )
                        w1_stats = worker_1.run_once()

                    self.assertEqual(mock_adapter_send.call_count, 0)
                    self.assertEqual(w1_stats["notified"], 0)
                    triggers_p1 = self._triggers(rule_id=rule["id"], status="triggered")
                    self.assertEqual(len(triggers_p1), 1)
                    notifs_p1 = self._notifications(trigger_id=triggers_p1[0]["id"])
                    self.assertTrue(
                        any(item["channel"] == channel_name and item.get("error_code") == "invalid_config" for item in notifs_p1)
                    )
                    self.assertFalse(any(item["channel"] == "__bar_delivery_claim__" for item in notifs_p1))

                    good_env = dict(base_env, **good_ch_env)
                    with patch.dict(os.environ, good_env, clear=False):
                        Config.reset_instance()
                        notifier_2 = NotificationService()
                        notifier_3 = NotificationService()
                        worker_2 = AlertWorker(
                            config_provider=lambda: self._config(),
                            service=AlertService(self.service.db),
                            notifier=notifier_2,
                        )
                        worker_3 = AlertWorker(
                            config_provider=lambda: self._config(),
                            service=AlertService(self.service.db),
                            notifier=notifier_3,
                        )
                        w2_stats = worker_2.run_once()
                        w3_stats = worker_3.run_once()

                self.assertEqual(mock_adapter_send.call_count, 1)
                self.assertEqual(w2_stats["notified"], 1)
                self.assertEqual(w3_stats["notified"], 0)
                self.assertEqual(w3_stats["cooldown_suppressed"], exp_suppressed)
                triggers_all = self._triggers(rule_id=rule["id"], status="triggered")
                notifs_all = [n for t in triggers_all for n in self._notifications(trigger_id=t["id"])]
                self.assertFalse(any(item["channel"] == "__bar_delivery_claim__" for item in notifs_all))
                self.assertTrue(any(item["channel"] == channel_name and item["success"] is True for item in notifs_all))
                self.assertTrue(
                    any(
                        item["channel"] == "__bar_dedup__" and item.get("error_code") == "already_delivered"
                        for item in notifs_all
                    )
                )
        finally:
            Config.reset_instance()


if __name__ == "__main__":
    unittest.main()
