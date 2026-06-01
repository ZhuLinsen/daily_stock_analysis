# -*- coding: utf-8 -*-
"""Alert worker tests for Issue #1202 P2."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

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
from src.storage import DatabaseManager


class AlertIndicatorHelperTestCase(unittest.TestCase):
    def test_required_bars_and_requested_days_are_stable(self) -> None:
        cases = {
            "ma_price_cross": ({"window": 20, "direction": "above"}, 21),
            "rsi_threshold": ({"period": 12, "threshold": 70, "direction": "above"}, 13),
            "macd_cross": (
                {"fast_period": 12, "slow_period": 26, "signal_period": 9, "direction": "bullish_cross"},
                36,
            ),
            "kdj_cross": ({"period": 9, "k_period": 3, "d_period": 3, "direction": "bullish_cross"}, 16),
            "cci_threshold": ({"period": 14, "threshold": 100, "direction": "above"}, 15),
        }

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
        close = pd.Series([10.0, 9.0, 11.0])
        old_sma_rsi = 66.66666666666666
        wilder_rsi = _calculate_rsi(close, 2)

        self.assertNotAlmostEqual(float(wilder_rsi.iloc[-1]), old_sma_rsi)
        self.assertAlmostEqual(float(wilder_rsi.iloc[-1]), 80.0)

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
            pd.DataFrame({"日期": pd.date_range("2026-01-01", periods=3), "收盘": [10, 9, 11]}),
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
        self.assertAlmostEqual(rsi.observed_value, 80.0)
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


if __name__ == "__main__":
    unittest.main()
