# -*- coding: utf-8 -*-
"""Tests for the schedule-mode startup daily dedup gate.

Two layers:

1. Unit tests for the ``src.core.analysis_run_marker`` contract (marker file
   read/write, stock-list fingerprint, dedup decision, fail-open semantics)
   using plain ``SimpleNamespace`` configs — zero network, zero real ``.env``.
2. Integration tests driving ``main.main()`` in schedule mode with
   ``src.scheduler.run_with_schedule`` patched out: the captured task callable
   is invoked manually to simulate the "startup immediate run" and the
   "daily scheduled run" without entering the real scheduler loop.
"""

import hashlib
import json
import logging
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

import main
from src.config import Config
import src.core.analysis_run_marker as analysis_run_marker
from src.core.analysis_run_marker import (
    analysis_run_marker_path,
    compute_stock_list_fingerprint,
    record_analysis_run_marker,
    should_skip_startup_immediate_run,
)


def _marker_config(temp_dir, stock_list=("600519",), schedule_startup_dedup=True):
    """Minimal config stand-in: only the attributes the gate/record touch."""
    return SimpleNamespace(
        database_path=str(Path(temp_dir) / "stock_analysis.db"),
        stock_list=list(stock_list),
        schedule_startup_dedup=schedule_startup_dedup,
    )


def _raw_marker_payload(**overrides):
    payload = {
        "schema_version": 1,
        "run_date": date.today().isoformat(),
        "scope": "full",
        "stock_list_fingerprint": "a" * 16,
        "stock_codes": ["600519"],
        "market_review": {"requested": False, "completed": None},
        "completed_at": "2026-09-28T18:00:00",
        "pid": 4242,
    }
    payload.update(overrides)
    return payload


class _ListLogHandler(logging.Handler):
    def __init__(self, sink):
        super().__init__()
        self._sink = sink

    def emit(self, record):
        self._sink.append(record.getMessage())


class AnalysisRunMarkerUnitTestCase(unittest.TestCase):
    """Contract tests for the analysis-run marker module (offline)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config = _marker_config(self._tmp.name)
        self.marker_path = analysis_run_marker_path(self.config)
        self.assertEqual(
            self.marker_path,
            Path(self._tmp.name) / "analysis_run_state.json",
        )

    # -- helpers ----------------------------------------------------------

    def _write_raw_marker(self, payload):
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        self.marker_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _read_raw_marker(self):
        return json.loads(self.marker_path.read_text(encoding="utf-8"))

    def _record(self, config=None, **overrides):
        kwargs = {
            "config": config if config is not None else self.config,
            "scope": "full",
            "stock_codes": list(getattr(
                config if config is not None else self.config, "stock_list", []
            )),
            "market_review_requested": False,
            "market_review_completed": None,
        }
        kwargs.update(overrides)
        return record_analysis_run_marker(**kwargs)

    # -- fingerprint ------------------------------------------------------

    def test_fingerprint_is_order_insensitive_sha256_prefix(self):
        self.assertEqual(
            compute_stock_list_fingerprint(["600519", "000001"]),
            compute_stock_list_fingerprint(["000001", "600519"]),
        )
        self.assertEqual(
            len(compute_stock_list_fingerprint(["600519"])), 16
        )
        expected_empty = hashlib.sha256(b"").hexdigest()[:16]
        self.assertEqual(compute_stock_list_fingerprint([]), expected_empty)
        self.assertEqual(compute_stock_list_fingerprint(None), expected_empty)
        self.assertNotEqual(
            compute_stock_list_fingerprint(["600519"]),
            compute_stock_list_fingerprint(["000001"]),
        )

    def test_empty_stock_list_fingerprint_matches_on_both_sides(self):
        # Pure-portfolio deployments keep stock_list empty: gate and writer
        # must agree on the empty fingerprint so the day still dedupes.
        empty_config = _marker_config(self._tmp.name, stock_list=[])
        self._record(config=empty_config)
        decision = should_skip_startup_immediate_run(empty_config)
        self.assertTrue(decision.skip, decision.reason)

    # -- marker write/read roundtrip --------------------------------------

    def test_record_then_gate_skips_today_full_run(self):
        self._record(
            market_review_requested=True,
            market_review_completed=True,
        )
        payload = self._read_raw_marker()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["run_date"], date.today().isoformat())
        self.assertEqual(payload["scope"], "full")
        self.assertEqual(
            payload["stock_list_fingerprint"],
            compute_stock_list_fingerprint(self.config.stock_list),
        )
        self.assertEqual(payload["stock_codes"], ["600519"])
        self.assertEqual(
            payload["market_review"],
            {"requested": True, "completed": True},
        )
        self.assertTrue(payload["pid"] > 0)
        self.assertIn("T", payload["completed_at"])

        decision = should_skip_startup_immediate_run(self.config)
        self.assertTrue(decision.skip, decision.reason)
        self.assertIn("already recorded", decision.reason)

    def test_record_market_review_not_requested_keeps_completed_none(self):
        self._record(market_review_requested=False, market_review_completed=None)
        payload = self._read_raw_marker()
        self.assertEqual(
            payload["market_review"],
            {"requested": False, "completed": None},
        )

    def test_full_run_overwrites_existing_marker(self):
        self._record()
        first = self._read_raw_marker()
        second_config = _marker_config(
            self._tmp.name, stock_list=("000001",)
        )
        self._record(config=second_config)
        second = self._read_raw_marker()
        self.assertNotEqual(
            first["stock_list_fingerprint"], second["stock_list_fingerprint"]
        )
        self.assertEqual(
            second["stock_list_fingerprint"],
            compute_stock_list_fingerprint(["000001"]),
        )

    # -- fail-open / gate decisions ---------------------------------------

    def test_missing_marker_executes(self):
        decision = should_skip_startup_immediate_run(self.config)
        self.assertFalse(decision.skip, decision.reason)

    def test_corrupt_marker_executes_fail_open(self):
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        self.marker_path.write_text("not-json{{{", encoding="utf-8")
        decision = should_skip_startup_immediate_run(self.config)
        self.assertFalse(decision.skip, decision.reason)
        self.assertIn("fail-open", decision.reason)

    def test_missing_marker_reason_mentions_missing_or_no_marker(self):
        # Locks the shared helper's machine-readable reason contract: the
        # missing branch must say "missing" or "no ... marker".
        decision = should_skip_startup_immediate_run(self.config)
        self.assertFalse(decision.skip, decision.reason)
        self.assertTrue(
            "missing" in decision.reason
            or "no analysis run marker" in decision.reason,
            decision.reason,
        )

    def test_corrupt_marker_reason_mentions_corrupt(self):
        # Locks the shared helper's machine-readable reason contract: the
        # corrupt branch must surface "corrupt" in the gate decision.
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        self.marker_path.write_text("not-json{{{", encoding="utf-8")
        decision = should_skip_startup_immediate_run(self.config)
        self.assertFalse(decision.skip, decision.reason)
        self.assertIn("corrupt", decision.reason)
        self.assertIn("fail-open", decision.reason)

    def test_unknown_schema_version_executes_fail_open(self):
        self._write_raw_marker(
            _raw_marker_payload(
                stock_list_fingerprint=compute_stock_list_fingerprint(
                    self.config.stock_list
                )
            )
        )
        # Same content but a future schema version must not be trusted.
        payload = self._read_raw_marker()
        payload["schema_version"] = 999
        self._write_raw_marker(payload)
        decision = should_skip_startup_immediate_run(self.config)
        self.assertFalse(decision.skip, decision.reason)

    def test_marker_run_date_not_today_executes(self):
        self._write_raw_marker(
            _raw_marker_payload(
                run_date="2000-01-01",
                stock_list_fingerprint=compute_stock_list_fingerprint(
                    self.config.stock_list
                ),
            )
        )
        decision = should_skip_startup_immediate_run(self.config)
        self.assertFalse(decision.skip, decision.reason)
        self.assertIn("run_date", decision.reason)

    def test_marker_scope_subset_executes(self):
        self._write_raw_marker(
            _raw_marker_payload(
                scope="subset",
                stock_list_fingerprint=compute_stock_list_fingerprint(
                    self.config.stock_list
                ),
            )
        )
        decision = should_skip_startup_immediate_run(self.config)
        self.assertFalse(decision.skip, decision.reason)

    def test_marker_fingerprint_mismatch_executes_with_reason(self):
        self._write_raw_marker(
            _raw_marker_payload(
                stock_list_fingerprint=compute_stock_list_fingerprint(
                    ["000001"]
                )
            )
        )
        decision = should_skip_startup_immediate_run(self.config)
        self.assertFalse(decision.skip, decision.reason)
        self.assertIn("stock list changed", decision.reason)

    def test_kill_switch_disabled_executes_even_with_matching_marker(self):
        self._record()
        gated_config = _marker_config(
            self._tmp.name, schedule_startup_dedup=False
        )
        decision = should_skip_startup_immediate_run(gated_config)
        self.assertFalse(decision.skip, decision.reason)

    def test_kill_switch_defaults_to_enabled_when_attribute_missing(self):
        self._record()
        bare_config = SimpleNamespace(
            database_path=str(Path(self._tmp.name) / "stock_analysis.db"),
            stock_list=["600519"],
        )
        decision = should_skip_startup_immediate_run(bare_config)
        self.assertTrue(decision.skip, decision.reason)

    # -- record-side overwrite rules and error tolerance -------------------

    def test_subset_run_does_not_overwrite_today_full_marker(self):
        self._record(scope="full")
        before = self._read_raw_marker()
        self._record(
            scope="subset",
            stock_codes=["000001"],
            market_review_requested=False,
            market_review_completed=None,
        )
        after = self._read_raw_marker()
        self.assertEqual(after["scope"], "full")
        self.assertEqual(after["completed_at"], before["completed_at"])
        self.assertNotIn("000001", after["stock_codes"])

    def test_subset_run_writes_when_no_valid_full_marker_exists(self):
        self._record(scope="subset", stock_codes=["000001"])
        payload = self._read_raw_marker()
        self.assertEqual(payload["scope"], "subset")
        self.assertEqual(payload["stock_codes"], ["000001"])

    def test_record_write_error_does_not_raise(self):
        # A directory at the marker path forces the atomic rename to fail.
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        self.marker_path.mkdir()
        try:
            self._record()
        except Exception as exc:  # pragma: no cover - assertion guard
            self.fail(f"record_analysis_run_marker raised: {exc}")

    def test_dry_run_args_skip_marker_write(self):
        self._record(args=SimpleNamespace(dry_run=True))
        self.assertFalse(self.marker_path.exists())

    def test_dry_run_flag_skips_marker_write(self):
        self._record(dry_run=True)
        self.assertFalse(self.marker_path.exists())


class ScheduleStartupDedupIntegrationTestCase(unittest.TestCase):
    """main() --schedule startup simulation with the real dedup gate.

    ``src.scheduler.run_with_schedule`` is patched so ``main.main()`` returns
    immediately with the task callable captured; the test then invokes the
    task manually to model the startup-immediate invocation and subsequent
    daily scheduled invocations.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519",
                    "SCHEDULE_ENABLED=true",
                    "SCHEDULE_RUN_IMMEDIATELY=true",
                    "SCHEDULE_TIME=23:59",
                    "SCHEDULE_TIMES=",
                    "MARKET_REVIEW_ENABLED=false",
                    "TRADING_DAY_CHECK_ENABLED=false",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        self.env_patch = patch.dict(
            os.environ, {"ENV_FILE": str(self.env_path)}, clear=False
        )
        self.env_patch.start()
        self.actions_env_patch = patch.dict(
            os.environ, {"GITHUB_ACTIONS": "false"}, clear=False
        )
        self.actions_env_patch.start()
        Config.reset_instance()

        self.log_sink = []
        root_logger = logging.getLogger()
        self._original_root_handlers = list(root_logger.handlers)
        self._original_root_level = root_logger.level
        self._log_handler = _ListLogHandler(self.log_sink)
        root_logger.addHandler(self._log_handler)
        if root_logger.level > logging.INFO or root_logger.level == 0:
            root_logger.setLevel(logging.INFO)

    def tearDown(self):
        root_logger = logging.getLogger()
        current_handlers = list(root_logger.handlers)
        for handler in current_handlers:
            if handler not in self._original_root_handlers:
                root_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass
        root_logger.setLevel(self._original_root_level)
        os.chdir(self.original_cwd)
        Config.reset_instance()
        self.env_patch.stop()
        self.actions_env_patch.stop()
        self.temp_dir.cleanup()

    # -- helpers ----------------------------------------------------------

    def _make_args(self, **overrides):
        defaults = {
            "debug": False,
            "stocks": None,
            "portfolio": None,
            "webui": False,
            "webui_only": False,
            "serve": False,
            "serve_only": False,
            "host": None,
            "port": None,
            "backtest": False,
            "market_review": False,
            "schedule": True,
            "no_run_immediately": False,
            "no_notify": False,
            "check_notify": False,
            "no_market_review": False,
            "dry_run": False,
            "workers": 1,
            "force_run": False,
            "single_notify": False,
            "no_context_snapshot": False,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _make_config(self, **overrides):
        defaults = {
            "log_dir": self.temp_dir.name,
            "webui_enabled": False,
            "webui_host": "127.0.0.1",
            "webui_port": 8000,
            "dingtalk_stream_enabled": False,
            "feishu_stream_enabled": False,
            "schedule_enabled": True,
            "schedule_time": "23:59",
            "schedule_times": ["23:59"],
            "schedule_run_immediately": True,
            "run_immediately": True,
            "agent_event_monitor_enabled": False,
            "agent_event_alert_rules_json": "",
            "agent_event_monitor_interval_minutes": 5,
            "daily_market_context_enabled": False,
            "market_review_enabled": False,
            "market_review_region": "cn",
            "trading_day_check_enabled": False,
            "stock_list": ["600519"],
            "database_path": str(
                Path(self.temp_dir.name) / "data" / "stock_analysis.db"
            ),
            "schedule_startup_dedup": True,
        }
        defaults.update(overrides)

        class _DummyConfig(SimpleNamespace):
            def validate(self):
                return []

        return _DummyConfig(**defaults)

    def _preset_full_marker(self, config, fingerprint_codes=None):
        record_config = SimpleNamespace(
            database_path=config.database_path,
            stock_list=list(
                fingerprint_codes
                if fingerprint_codes is not None
                else config.stock_list
            ),
        )
        record_analysis_run_marker(
            record_config,
            scope="full",
            stock_codes=list(record_config.stock_list),
            market_review_requested=False,
            market_review_completed=None,
        )

    @contextmanager
    def _patched_schedule_main(self, config, args):
        """Drive main.main() to the schedule branch and yield the task.

        All patches stay active while the caller invokes the task, so the
        analysis pipeline is never entered (fully offline, fast).
        """
        with ExitStack() as stack:
            stack.enter_context(
                patch("main.parse_arguments", return_value=args)
            )
            stack.enter_context(
                patch("main.get_config", return_value=config)
            )
            fake_run_with_schedule = stack.enter_context(
                patch("src.scheduler.run_with_schedule")
            )
            fake_run_full_analysis = stack.enter_context(
                patch("main.run_full_analysis", return_value=True)
            )
            exit_code = main.main()
            self.assertEqual(exit_code, 0)
            self.assertTrue(fake_run_with_schedule.called)
            task = fake_run_with_schedule.call_args.kwargs["task"]
            run_immediately = fake_run_with_schedule.call_args.kwargs[
                "run_immediately"
            ]
            # setup_logging() replaced the root handlers inside main.main();
            # attach the capture handler only now so it survives the task()
            # invocations (the asserted gate logs happen during task calls).
            root_logger = logging.getLogger()
            root_logger.addHandler(self._log_handler)
            try:
                yield task, run_immediately, fake_run_full_analysis
            finally:
                root_logger.removeHandler(self._log_handler)

    def _joined_logs(self):
        return "\n".join(self.log_sink)

    # -- cases -------------------------------------------------------------

    def test_startup_immediate_run_skips_when_today_full_marker_exists(self):
        config = self._make_config()
        self._preset_full_marker(config)
        with self._patched_schedule_main(
            config, self._make_args()
        ) as (task, run_immediately, fake_analysis):
            self.assertTrue(run_immediately)

            task()

            self.assertEqual(fake_analysis.call_count, 0)
            self.assertIn("启动立即执行已跳过", self._joined_logs())

    def test_startup_immediate_run_executes_without_marker(self):
        config = self._make_config()
        with self._patched_schedule_main(
            config, self._make_args()
        ) as (task, run_immediately, fake_analysis):
            self.assertTrue(run_immediately)

            task()

            self.assertEqual(fake_analysis.call_count, 1)
            self.assertIn("启动立即执行去重检查通过", self._joined_logs())
            self.assertNotIn("启动立即执行已跳过", self._joined_logs())

    def test_second_task_call_is_daily_invocation_and_never_gated(self):
        config = self._make_config()
        self._preset_full_marker(config)
        with self._patched_schedule_main(
            config, self._make_args()
        ) as (task, run_immediately, fake_analysis):
            # First invocation: startup-immediate with today's full marker
            # -> skipped by the gate.
            task()
            self.assertEqual(fake_analysis.call_count, 0)
            self.assertIn("启动立即执行已跳过", self._joined_logs())

            # Second invocation models the daily scheduled job: it must run
            # even though a matching full marker still exists (the gate flag
            # was consumed by the first invocation).
            task()
            self.assertEqual(fake_analysis.call_count, 1)

    def test_stock_list_change_reopens_the_gate(self):
        config = self._make_config()
        self._preset_full_marker(config, fingerprint_codes=["000001"])
        with self._patched_schedule_main(
            config, self._make_args()
        ) as (task, run_immediately, fake_analysis):
            task()

            self.assertEqual(fake_analysis.call_count, 1)
            self.assertIn("启动立即执行去重检查通过", self._joined_logs())

    def test_kill_switch_env_disables_the_gate(self):
        config = self._make_config(schedule_startup_dedup=False)
        self._preset_full_marker(config)
        with self._patched_schedule_main(
            config, self._make_args()
        ) as (task, run_immediately, fake_analysis), patch(
            "main.should_skip_startup_immediate_run"
        ) as fake_gate:
            task()

            # The kill switch must bypass the gate entirely.
            fake_gate.assert_not_called()
            self.assertEqual(fake_analysis.call_count, 1)
            self.assertNotIn("启动立即执行已跳过", self._joined_logs())

    def test_no_run_immediately_keeps_gate_inactive(self):
        config = self._make_config()
        self._preset_full_marker(config)
        with self._patched_schedule_main(
            config, self._make_args(no_run_immediately=True)
        ) as (task, run_immediately, fake_analysis), patch(
            "main.should_skip_startup_immediate_run"
        ) as fake_gate:
            self.assertFalse(run_immediately)

            task()

            # Daily-style invocations never consult the startup gate.
            fake_gate.assert_not_called()
            self.assertEqual(fake_analysis.call_count, 1)
            self.assertNotIn("启动立即执行已跳过", self._joined_logs())

    def test_force_run_bypasses_gate_and_executes(self):
        # --force-run is an explicit request for an immediate full run:
        # even with today's full marker present the gate is bypassed
        # entirely (same semantics as the trading-day skip override).
        config = self._make_config()
        self._preset_full_marker(config)
        with self._patched_schedule_main(
            config, self._make_args(force_run=True)
        ) as (task, run_immediately, fake_analysis), patch(
            "main.should_skip_startup_immediate_run"
        ) as fake_gate:
            self.assertTrue(run_immediately)

            task()

            fake_gate.assert_not_called()
            self.assertEqual(fake_analysis.call_count, 1)
            self.assertIn("--force-run 指定,跳过启动去重检查", self._joined_logs())
            self.assertNotIn("启动立即执行已跳过", self._joined_logs())


if __name__ == "__main__":
    unittest.main()
