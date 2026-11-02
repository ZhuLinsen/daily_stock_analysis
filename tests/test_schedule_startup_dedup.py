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
from src.analyzer import AnalysisResult
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
        "schema_version": 2,
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
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["run_date"], date.today().isoformat())
        self.assertEqual(payload["scope"], "full")
        self.assertEqual(
            payload["stock_list_fingerprint"],
            compute_stock_list_fingerprint(self.config.stock_list),
        )
        # The covered stock_codes feed the schema-2 coverage gate: the
        # recorded list must equal what this run actually analyzed.
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
        self.assertIn("covers", decision.reason)

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

    def test_marker_not_covering_expected_list_executes_with_reason(self):
        # Schema-2 semantics: the fingerprint is observability only. The
        # gate must execute (and say why) when the marker's covered
        # stock_codes miss any expected code — here the marker covers only
        # 000001 while the watchlist expects 600519.
        self._write_raw_marker(
            _raw_marker_payload(
                stock_list_fingerprint=compute_stock_list_fingerprint(
                    ["000001"]
                ),
                stock_codes=["000001"],
            )
        )
        decision = should_skip_startup_immediate_run(self.config)
        self.assertFalse(decision.skip, decision.reason)
        self.assertIn("does not cover", decision.reason)
        self.assertIn("600519", decision.reason)

    def test_schema_v1_marker_executes_fail_open(self):
        # Schema 1 markers may stem from partial-failure rounds recorded by
        # the old fingerprint-only writer: they must fail open exactly once
        # so the next full run upgrades the marker to schema 2.
        self._write_raw_marker(
            _raw_marker_payload(
                schema_version=1,
                stock_list_fingerprint=compute_stock_list_fingerprint(
                    self.config.stock_list
                ),
                stock_codes=list(self.config.stock_list),
            )
        )
        decision = should_skip_startup_immediate_run(self.config)
        self.assertFalse(decision.skip, decision.reason)
        self.assertIn("schema version", decision.reason)
        self.assertIn("fail-open", decision.reason)

    def test_marker_missing_stock_codes_field_executes_fail_open(self):
        # A schema-2 marker without a usable stock_codes list cannot prove
        # coverage: missing or non-array values must fail open.
        payload = _raw_marker_payload(
            stock_list_fingerprint=compute_stock_list_fingerprint(
                self.config.stock_list
            )
        )
        del payload["stock_codes"]
        self._write_raw_marker(payload)
        decision = should_skip_startup_immediate_run(self.config)
        self.assertFalse(decision.skip, decision.reason)
        self.assertIn("stock_codes", decision.reason)

        payload = _raw_marker_payload(
            stock_list_fingerprint=compute_stock_list_fingerprint(
                self.config.stock_list
            ),
            stock_codes="600519",
        )
        self._write_raw_marker(payload)
        decision = should_skip_startup_immediate_run(self.config)
        self.assertFalse(decision.skip, decision.reason)
        self.assertIn("stock_codes", decision.reason)

    def test_covered_superset_of_expected_skips(self):
        # Coverage is a subset check: extra covered codes (e.g. a watchlist
        # that shrank since the morning run) must still allow the skip.
        self._write_raw_marker(
            _raw_marker_payload(
                stock_list_fingerprint=compute_stock_list_fingerprint(
                    self.config.stock_list
                ),
                stock_codes=["600519", "000001"],
            )
        )
        decision = should_skip_startup_immediate_run(self.config)
        self.assertTrue(decision.skip, decision.reason)

    def test_gate_requires_covered_superset(self):
        # Blocker OR-COR-9a7cb728: the marker's covered ``stock_codes`` being
        # a strict subset of the currently expected list (e.g. only the CN
        # market was covered in a morning run; US opens later the same day)
        # must reopen the gate instead of skipping. The fingerprint is
        # deliberately kept identical on both sides so ONLY the coverage
        # semantics can decide the outcome; the schema version tracks the
        # module constant so this test fails before AND after the schema bump.
        subset_config = _marker_config(
            self._tmp.name, stock_list=("600519", "AAPL")
        )
        self._write_raw_marker(
            _raw_marker_payload(
                schema_version=analysis_run_marker.MARKER_SCHEMA_VERSION,
                stock_list_fingerprint=compute_stock_list_fingerprint(
                    subset_config.stock_list
                ),
                stock_codes=["600519"],
            )
        )
        decision = should_skip_startup_immediate_run(subset_config)
        self.assertFalse(
            decision.skip,
            "covered stock_codes must cover the whole expected list to skip",
        )
        self.assertIn("AAPL", decision.reason)

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
            def refresh_stock_list(self):
                # The gate mirrors the run entry's STOCK_LIST .env hot-reload;
                # stand-in configs keep it a no-op (same shape as the
                # RealRun harness dummy below).
                pass

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
        # Schema-2 semantics: a marker recorded over a different watchlist
        # (here fingerprint/codes for 000001) cannot cover the current
        # expected list (600519), so the gate reopens with a coverage reason.
        config = self._make_config()
        self._preset_full_marker(config, fingerprint_codes=["000001"])
        with self._patched_schedule_main(
            config, self._make_args()
        ) as (task, run_immediately, fake_analysis):
            task()

            self.assertEqual(fake_analysis.call_count, 1)
            self.assertIn("启动立即执行去重检查通过", self._joined_logs())
            self.assertIn("does not cover", self._joined_logs())

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

    def test_cross_market_second_phase_reopens_gate(self):
        # Blocker OR-COR-9a7cb728 (integration, two phases): the morning
        # startup run covered only the CN stock; after the US market opens
        # the same day a restart must re-run because the marker's covered
        # stock_codes do not include AAPL. The fingerprint is identical on
        # both sides (written over the full watchlist), so only the covered
        # subset can decide. get_open_markets_today is the single time
        # source of the trading-day filter (offline ZoneInfo + local
        # holiday table), patched here to claim both markets are open.
        config = self._make_config(
            stock_list=["600519", "AAPL"],
            trading_day_check_enabled=True,
        )
        record_config = SimpleNamespace(
            database_path=config.database_path,
            stock_list=list(config.stock_list),
        )
        record_analysis_run_marker(
            record_config,
            scope="full",
            stock_codes=["600519"],
            market_review_requested=False,
            market_review_completed=None,
        )
        with patch(
            "src.core.trading_calendar.get_open_markets_today",
            return_value={"cn", "us"},
        ):
            with self._patched_schedule_main(
                config, self._make_args()
            ) as (task, run_immediately, fake_analysis):
                self.assertTrue(run_immediately)

                task()

                self.assertEqual(
                    fake_analysis.call_count,
                    1,
                    "second phase with a not-fully-covered marker must execute",
                )
                self.assertIn("启动立即执行去重检查通过", self._joined_logs())
                self.assertNotIn("启动立即执行已跳过", self._joined_logs())

    def _real_config_from_env(self):
        """Build a REAL Config through the production resolution chain.

        ``Config._load_from_env()`` reads the process env and the active
        ``ENV_FILE`` (set up by ``setUp``) — no SimpleNamespace shortcuts —
        so the SCHEDULE_STARTUP_DEDUP value under test comes from the same
        ``_resolve_env_value`` path production uses.
        """
        with patch.object(Config, "_parse_litellm_yaml", return_value=[]):
            with patch.object(
                Config, "_parse_stock_email_groups", return_value=[]
            ):
                Config.reset_instance()
                try:
                    return Config._load_from_env()
                finally:
                    Config.reset_instance()

    def test_kill_switch_process_env_bypasses_gate_with_real_config(self):
        # Blockers OR-COM-cf8f915a / OR-COM-440796b8: the kill switch must
        # honor an explicit process-env value (docker -e / compose
        # environment / shell export) that differs from the persisted .env,
        # exactly like SCHEDULE_RUN_IMMEDIATELY. The .env keeps the dedup
        # enabled; the process env disables it.
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
                    "SCHEDULE_STARTUP_DEDUP=true",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"SCHEDULE_STARTUP_DEDUP": "false"}):
            real_config = self._real_config_from_env()

        self.assertFalse(
            real_config.schedule_startup_dedup,
            "process env SCHEDULE_STARTUP_DEDUP=false must override .env",
        )

        self._preset_full_marker(real_config)
        with self._patched_schedule_main(
            real_config, self._make_args()
        ) as (task, run_immediately, fake_analysis):
            self.assertTrue(run_immediately)

            task()

            self.assertEqual(fake_analysis.call_count, 1)
            self.assertNotIn("启动立即执行已跳过", self._joined_logs())

    # -- second-round review blockers (OR-COR-e59aed48 / OR-COR-c4971c31) --
    #
    # The gate must compute its expected list through the SAME real target
    # resolution chain the run entry uses (Futu portfolio first, .env
    # hot-reload second), not ``config.stock_list``. All cases below drive
    # the real task() chain; ``run_full_analysis`` stays the faked boundary
    # and the broker resolver is patched (zero network, zero real broker).

    def test_new_futu_position_reopens_gate(self):
        # Scenario 1: with --portfolio futu the run analyzes the LIVE
        # positions resolved at the run entry. A marker that only covers the
        # old watchlist must not skip a startup whose positions gained a new
        # code; the gate has to consult the real portfolio resolution.
        config = self._make_config()
        self._preset_full_marker(config)  # covered=["600519"]
        with patch(
            "main._resolve_portfolio_stock_codes",
            return_value=["600519", "000001"],
        ) as fake_resolver:
            with self._patched_schedule_main(
                config, self._make_args(portfolio="futu")
            ) as (task, run_immediately, fake_analysis):
                self.assertTrue(run_immediately)

                task()

                fake_resolver.assert_called_once()
                self.assertEqual(
                    fake_analysis.call_count,
                    1,
                    "a new Futu position outside the covered marker must re-run",
                )
                joined = self._joined_logs()
                self.assertIn("启动立即执行去重检查通过", joined)
                self.assertIn("000001", joined)
                self.assertNotIn("启动立即执行已跳过", joined)

    def test_covered_portfolio_targets_still_skip(self):
        # Guard against over-fixing: portfolio positions fully covered by
        # today's marker must still skip.
        config = self._make_config()
        self._preset_full_marker(config)  # covered=["600519"]
        with patch(
            "main._resolve_portfolio_stock_codes",
            return_value=["600519"],
        ):
            with self._patched_schedule_main(
                config, self._make_args(portfolio="futu")
            ) as (task, run_immediately, fake_analysis):
                self.assertTrue(run_immediately)

                task()

                self.assertEqual(fake_analysis.call_count, 0)
                self.assertIn("启动立即执行已跳过", self._joined_logs())

    def test_pure_portfolio_empty_watchlist_new_position_reopens_gate(self):
        # Scenario 2: pure-portfolio deployment (empty persisted watchlist).
        # The old gate computed expected=[] from config.stock_list, which is
        # vacuously covered by any marker and skipped the run; the real run
        # would have analyzed the live positions, so a new position must
        # re-open the gate.
        config = self._make_config(stock_list=[])
        self._preset_full_marker(config, fingerprint_codes=["600519"])
        with patch(
            "main._resolve_portfolio_stock_codes",
            return_value=["600519", "000001"],
        ):
            with self._patched_schedule_main(
                config, self._make_args(portfolio="futu")
            ) as (task, run_immediately, fake_analysis):
                self.assertTrue(run_immediately)

                task()

                self.assertEqual(
                    fake_analysis.call_count,
                    1,
                    "empty watchlist + live positions must not be a vacuous skip",
                )
                joined = self._joined_logs()
                self.assertIn("启动立即执行去重检查通过", joined)
                self.assertIn("000001", joined)
                self.assertNotIn("启动立即执行已跳过", joined)

    def test_covered_pure_portfolio_targets_still_skip(self):
        # Guard: pure-portfolio deployment whose live positions are fully
        # covered by today's marker must still skip.
        config = self._make_config(stock_list=[])
        self._preset_full_marker(config, fingerprint_codes=["600519"])
        with patch(
            "main._resolve_portfolio_stock_codes",
            return_value=["600519"],
        ):
            with self._patched_schedule_main(
                config, self._make_args(portfolio="futu")
            ) as (task, run_immediately, fake_analysis):
                self.assertTrue(run_immediately)

                task()

                self.assertEqual(fake_analysis.call_count, 0)
                self.assertIn("启动立即执行已跳过", self._joined_logs())

    def test_pure_portfolio_empty_resolution_never_skips(self):
        # Empty portfolio resolution (no tradable positions) can never prove
        # coverage: the gate must fail open and let the run decide, never
        # skip on a vacuously-covered empty expected list.
        config = self._make_config(stock_list=[])
        self._preset_full_marker(config, fingerprint_codes=["600519"])
        with patch(
            "main._resolve_portfolio_stock_codes",
            return_value=[],
        ):
            with self._patched_schedule_main(
                config, self._make_args(portfolio="futu")
            ) as (task, run_immediately, fake_analysis):
                self.assertTrue(run_immediately)

                task()

                self.assertEqual(
                    fake_analysis.call_count,
                    1,
                    "an empty portfolio resolution must never skip the run",
                )
                joined = self._joined_logs()
                self.assertIn("fail-open", joined)
                self.assertNotIn("启动立即执行已跳过", joined)

    def test_portfolio_resolution_failure_fails_open(self):
        # A broker resolution failure must never become a skip decision
        # ("never miss a run" outranks "never re-run"); the task must not
        # raise either.
        config = self._make_config(stock_list=[])
        self._preset_full_marker(config, fingerprint_codes=["600519"])
        with patch(
            "main._resolve_portfolio_stock_codes",
            side_effect=RuntimeError("futu unavailable"),
        ):
            with self._patched_schedule_main(
                config, self._make_args(portfolio="futu")
            ) as (task, run_immediately, fake_analysis):
                self.assertTrue(run_immediately)

                task()

                self.assertEqual(
                    fake_analysis.call_count,
                    1,
                    "portfolio resolution failure must fail open and run",
                )
                joined = self._joined_logs()
                self.assertIn("fail-open", joined)
                self.assertNotIn("启动立即执行已跳过", joined)

    def test_process_env_stock_list_with_updated_env_file_reopens_gate(self):
        # Scenario 3: WebUI/.env hot update after the container started with
        # an explicit process-env STOCK_LIST. Bootstrap config keeps the
        # process value (600519) while refresh_stock_list() at the run entry
        # prefers the .env file (600519,000001). The gate must mirror that
        # chain or it would skip with a stale expected list.
        #
        # patch.dict scope: the STOCK_LIST override only needs to cover the
        # config bootstrap phase (explicit process override capture); the
        # task()-phase refresh_stock_list() reads the ENV_FILE directly via
        # dotenv_values and never consults the process env. The outer bare
        # patch.dict(os.environ) snapshots the whole environment so side
        # effects of setup_env()/reload helpers (e.g. DATABASE_PATH loaded
        # from the temp .env) cannot leak into other tests.
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519,000001",
                    "DATABASE_PATH="
                    + str(
                        Path(self.temp_dir.name) / "data" / "stock_analysis.db"
                    ),
                    "SCHEDULE_ENABLED=true",
                    "SCHEDULE_RUN_IMMEDIATELY=true",
                    "SCHEDULE_TIME=23:59",
                    "SCHEDULE_TIMES=",
                    "MARKET_REVIEW_ENABLED=false",
                    # Same baseline as the kill-switch case above: keep the
                    # trading-day filter off so the decision is not
                    # date-sensitive on market holidays.
                    "TRADING_DAY_CHECK_ENABLED=false",
                    "SCHEDULE_STARTUP_DEDUP=true",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ):
            with patch.dict(os.environ, {"STOCK_LIST": "600519"}):
                real_config = self._real_config_from_env()

            self.assertEqual(
                real_config.stock_list,
                ["600519"],
                "bootstrap config must keep the explicit process-env STOCK_LIST",
            )

            self._preset_full_marker(real_config)  # covered=["600519"]
            with self._patched_schedule_main(
                real_config, self._make_args()
            ) as (task, run_immediately, fake_analysis):
                self.assertTrue(run_immediately)

                task()

                self.assertEqual(
                    fake_analysis.call_count,
                    1,
                    "a .env hot update adding a stock must re-open the gate",
                )
                self.assertEqual(
                    real_config.stock_list,
                    ["600519", "000001"],
                    "the gate must hot-reload STOCK_LIST from the .env file "
                    "like the run entry does",
                )
                joined = self._joined_logs()
                self.assertIn("启动立即执行去重检查通过", joined)
                self.assertIn("000001", joined)
                self.assertNotIn("启动立即执行已跳过", joined)


class AllStockTargetsSucceededUnitTestCase(unittest.TestCase):
    """Contract tests for main._all_stock_targets_succeeded (AD-A)."""

    def _result(self, code):
        return SimpleNamespace(code=code)

    def test_empty_target_list_is_vacuous_success(self):
        # Pure-review deployments (no stock targets) keep same-day dedup.
        self.assertTrue(main._all_stock_targets_succeeded([], []))
        self.assertTrue(main._all_stock_targets_succeeded(None, []))
        self.assertTrue(
            main._all_stock_targets_succeeded(None, [self._result("600519")])
        )

    def test_missing_target_code_fails(self):
        results = [self._result("600519")]
        self.assertFalse(
            main._all_stock_targets_succeeded(["600519", "000001"], results)
        )

    def test_duplicates_and_disorder_still_succeed(self):
        results = [self._result("000001"), self._result("600519")]
        self.assertTrue(
            main._all_stock_targets_succeeded(
                ["600519", "600519", "000001"], results
            )
        )

    def test_normalization_matches_marker_writer_str_only(self):
        # The completeness check normalizes exactly like the marker writer
        # (str(code) verbatim) so the covered stock_codes recorded in the
        # marker are the codes the check actually verified.
        self.assertTrue(
            main._all_stock_targets_succeeded(
                [600519], [self._result("600519")]
            )
        )
        self.assertTrue(
            main._all_stock_targets_succeeded(
                ["600519"], [self._result(600519)]
            )
        )


def _make_fake_pipeline_cls(results, report_path):
    """Build a fresh ``StockAnalysisPipeline`` stand-in (AD-D harness).

    The fake must be patched at ``src.core.pipeline.StockAnalysisPipeline``:
    ``run_full_analysis`` imports the pipeline locally (``from src.core.pipeline
    import StockAnalysisPipeline``), which silently shadows any
    ``main.StockAnalysisPipeline`` attribute patch. ``results`` is returned
    by ``run()`` verbatim; ``report_path`` simulates a persisted local
    summary report so the deferred report-save failure branch stays ``None``
    and cannot mask the marker contract under test.
    """

    class _FakeStockAnalysisPipeline:
        def __init__(self, **kwargs):
            self.init_kwargs = kwargs
            self.notifier = SimpleNamespace(
                is_available=lambda: False,
                send=lambda *args, **kwargs_: False,
                generate_aggregate_report=lambda *args, **kwargs_: "",
            )
            self.analyzer = SimpleNamespace()
            self.search_service = SimpleNamespace()
            self._last_local_report_path = str(report_path)
            self.run_calls = []

        def run(self, **kwargs):
            self.run_calls.append(kwargs)
            return list(results)

    return _FakeStockAnalysisPipeline


class RealRunClosureMarkerTestCase(unittest.TestCase):
    """Blocker1/4 closure harness: REAL ``main.run_full_analysis``.

    The previous integration tests patched ``main.run_full_analysis``
    outright, so the marker-write path (the very code the review flagged)
    never executed. Here only the ``StockAnalysisPipeline`` boundary and
    the network/filesystem collaborators are patched; the whole closure —
    including the marker write — is real and offline.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.report_path = Path(self.temp_dir.name) / "report.md"
        self.config = self._make_config()
        self.args = self._make_args()
        self.marker_path = analysis_run_marker_path(self.config)

    # -- builders ---------------------------------------------------------

    def _make_config(self, **overrides):
        defaults = {
            "log_dir": self.temp_dir.name,
            "database_path": str(
                Path(self.temp_dir.name) / "data" / "stock_analysis.db"
            ),
            "stock_list": ["600519", "000001"],
            "market_review_enabled": False,
            "daily_market_context_enabled": False,
            "market_review_region": "cn",
            "trading_day_check_enabled": False,
            "merge_email_notification": False,
            "single_stock_notify": False,
            "analysis_delay": 0,
            "report_type": "simple",
            "report_language": "zh",
            "schedule_enabled": True,
            "schedule_startup_dedup": True,
        }
        defaults.update(overrides)

        class _DummyConfig(SimpleNamespace):
            def refresh_stock_list(self):
                pass

            def validate(self):
                return []

        return _DummyConfig(**defaults)

    def _make_args(self, **overrides):
        defaults = {
            "debug": False,
            "stocks": None,
            "portfolio": "",
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
            "no_notify": True,
            "check_notify": False,
            "no_market_review": False,
            "dry_run": False,
            "workers": 1,
            "force_run": False,
            "single_notify": False,
            "no_context_snapshot": True,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _analysis_result(self, code):
        return AnalysisResult(
            code=code,
            name=f"stock-{code}",
            sentiment_score=60,
            trend_prediction="震荡",
            operation_advice="观望",
        )

    def _run_real_full_analysis(
        self,
        *,
        results,
        market_review_report=None,
        config=None,
        args=None,
    ):
        config = config if config is not None else self.config
        args = args if args is not None else self.args
        fake_cls = _make_fake_pipeline_cls(results, self.report_path)
        with ExitStack() as stack:
            stack.enter_context(
                patch("src.core.pipeline.StockAnalysisPipeline", fake_cls)
            )
            stack.enter_context(
                patch("main._refresh_stock_index_cache_for_analysis")
            )
            stack.enter_context(patch("main._run_auto_backtest"))
            stack.enter_context(
                patch(
                    "main._prime_daily_market_context",
                    return_value=("", ""),
                )
            )
            if market_review_report is not None:
                stack.enter_context(
                    patch(
                        "main._run_market_review_with_shared_lock",
                        return_value=market_review_report,
                    )
                )
            return main.run_full_analysis(config, args)

    # -- cases ------------------------------------------------------------

    def test_partial_stock_failure_must_not_record_full_marker(self):
        # Blocker OR-COR-0438bcbe: 600519 succeeds, 000001 fails (the fake
        # pipeline boundary returns only the successful result, mirroring
        # the real pipeline contract of returning just the successes).
        results = [self._analysis_result("600519")]

        result = self._run_real_full_analysis(results=results)

        # Upstream lenient semantics preserved: partial success still True.
        self.assertTrue(result)
        self.assertFalse(
            self.marker_path.exists(),
            "startup dedup marker must NOT be recorded when a stock "
            "target failed",
        )

    def test_all_stocks_failed_with_market_review_must_not_record_full_marker(
        self,
    ):
        # Blocker OR-COR-51dff048: every stock target fails, but the market
        # review succeeds and produces a report — the run must not record a
        # full-scope marker (the review must not resurrect the marker).
        config = self._make_config(market_review_enabled=True)
        marker_path = analysis_run_marker_path(config)

        result = self._run_real_full_analysis(
            results=[],
            market_review_report="# 大盘复盘（mock）",
            config=config,
        )

        # Upstream lenient semantics preserved: review success still True.
        self.assertTrue(result)
        self.assertFalse(
            marker_path.exists(),
            "startup dedup marker must NOT be recorded when every stock "
            "target failed, even with a successful market review",
        )


class SerialStartupDedupRegressionTestCase(unittest.TestCase):
    """Serial regression for the startup dedup (review suggestion 2).

    One true story against ONE database/marker location, told in order:

    a) A REAL ``main.run_full_analysis`` run with every stock target
       succeeding (only the ``StockAnalysisPipeline`` boundary and offline
       collaborators patched, same harness as
       ``RealRunClosureMarkerTestCase``) records the marker: schema v2,
       scope=full, covered ``stock_codes`` containing every analyzed target.
    b) A same-parameter restart (fresh config object, SAME
       ``database_path``) in schedule mode: ``main.main()`` is driven with
       ``src.scheduler.run_with_schedule`` patched so the ``scheduled_task``
       callable is captured; the first invocation with ``scheduled_for=None``
       must be skipped by the startup gate — ``run_full_analysis`` is never
       called.
    c) The SAME captured task invoked with a concrete ``scheduled_for`` (the
       daily scheduled occurrence) must still execute ``run_full_analysis``:
       daily invocations never consult the startup gate (fork at main.py
       ``if scheduled_for is None``).
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.report_path = Path(self.temp_dir.name) / "report.md"
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519,000001",
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

    # -- builders ---------------------------------------------------------

    def _make_config(self, **overrides):
        # Union of the two existing harness configs: the real-run harness
        # keys (analysis path) plus the schedule-mode keys main.main()
        # touches. One builder for both acts so the restart in act b is a
        # literal same-parameter restart of act a's run.
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
            "merge_email_notification": False,
            "single_stock_notify": False,
            "analysis_delay": 0,
            "report_type": "simple",
            "report_language": "zh",
            "stock_list": ["600519", "000001"],
            "database_path": str(
                Path(self.temp_dir.name) / "data" / "stock_analysis.db"
            ),
            "schedule_startup_dedup": True,
        }
        defaults.update(overrides)

        class _DummyConfig(SimpleNamespace):
            def refresh_stock_list(self):
                pass

            def validate(self):
                return []

        return _DummyConfig(**defaults)

    def _make_args(self, **overrides):
        defaults = {
            "debug": False,
            "stocks": None,
            "portfolio": "",
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
            "no_notify": True,
            "check_notify": False,
            "no_market_review": False,
            "dry_run": False,
            "workers": 1,
            "force_run": False,
            "single_notify": False,
            "no_context_snapshot": True,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _analysis_result(self, code):
        return AnalysisResult(
            code=code,
            name=f"stock-{code}",
            sentiment_score=60,
            trend_prediction="震荡",
            operation_advice="观望",
        )

    def _run_real_full_analysis(self, *, results, config, args):
        """REAL ``main.run_full_analysis`` with only boundary patches."""
        fake_cls = _make_fake_pipeline_cls(results, self.report_path)
        with ExitStack() as stack:
            stack.enter_context(
                patch("src.core.pipeline.StockAnalysisPipeline", fake_cls)
            )
            stack.enter_context(
                patch("main._refresh_stock_index_cache_for_analysis")
            )
            stack.enter_context(patch("main._run_auto_backtest"))
            stack.enter_context(
                patch(
                    "main._prime_daily_market_context",
                    return_value=("", ""),
                )
            )
            return main.run_full_analysis(config, args)

    @contextmanager
    def _patched_schedule_main(self, config, args):
        """Drive ``main.main()`` into schedule mode and yield the task.

        Same capture pattern as
        ``ScheduleStartupDedupIntegrationTestCase._patched_schedule_main``:
        ``src.scheduler.run_with_schedule`` is patched out so the captured
        ``scheduled_task`` can be invoked manually, and
        ``main.run_full_analysis`` is the faked execution boundary whose
        call count decides the serial-b/serial-c assertions.
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
            self.assertEqual(
                exit_code,
                0,
                "serial-b: schedule-mode main.main() must exit cleanly",
            )
            self.assertTrue(
                fake_run_with_schedule.called,
                "serial-b: run_with_schedule must be entered so the task "
                "callable can be captured",
            )
            task = fake_run_with_schedule.call_args.kwargs["task"]
            run_immediately = fake_run_with_schedule.call_args.kwargs[
                "run_immediately"
            ]
            # setup_logging() replaced the root handlers inside main.main();
            # re-attach the capture handler only now (same reason as the
            # integration harness above).
            root_logger = logging.getLogger()
            root_logger.addHandler(self._log_handler)
            try:
                yield task, run_immediately, fake_run_full_analysis
            finally:
                root_logger.removeHandler(self._log_handler)

    def _joined_logs(self):
        return "\n".join(self.log_sink)

    # -- the serial regression ---------------------------------------------

    def test_serial_real_run_writes_marker_restart_skips_daily_still_runs(
        self,
    ):
        from datetime import datetime

        # -- Act a: real full run over both targets records the marker ----
        config_a = self._make_config()
        args = self._make_args()
        marker_path_a = analysis_run_marker_path(config_a)
        results = [
            self._analysis_result("600519"),
            self._analysis_result("000001"),
        ]

        run_ok = self._run_real_full_analysis(
            results=results, config=config_a, args=args
        )

        self.assertTrue(
            run_ok,
            "serial-a: a run with every stock target succeeding must "
            "return True",
        )
        self.assertTrue(
            marker_path_a.exists(),
            "serial-a: the successful full run must write the analysis "
            f"run marker at {marker_path_a}",
        )
        payload = json.loads(marker_path_a.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["schema_version"],
            2,
            "serial-a: the recorded marker must be schema v2",
        )
        self.assertEqual(
            payload["scope"],
            "full",
            "serial-a: an entry-level run without --stocks must record "
            "scope=full",
        )
        self.assertEqual(
            payload["run_date"],
            date.today().isoformat(),
            "serial-a: the marker must be stamped with today's run date",
        )
        self.assertTrue(
            {"600519", "000001"}.issubset(set(payload["stock_codes"])),
            "serial-a: the covered stock_codes "
            f"{payload['stock_codes']} must contain every analyzed "
            "target 600519/000001",
        )

        # -- Act b: same-parameter restart is deduplicated at startup -----
        restart_config = self._make_config()
        self.assertEqual(
            Path(restart_config.database_path),
            Path(config_a.database_path),
            "serial-b: the restart must target the same database_path "
            "(and therefore the same marker)",
        )
        with self._patched_schedule_main(
            restart_config, args
        ) as (task, run_immediately, fake_analysis):
            self.assertTrue(
                run_immediately,
                "serial-b: the restart must be the startup-immediate "
                "invocation",
            )

            task()  # scheduled_for=None: the gated startup-immediate call

            self.assertEqual(
                fake_analysis.call_count,
                0,
                "serial-b: the startup-immediate run must be skipped by "
                "the dedup gate — run_full_analysis must not be called",
            )
            self.assertIn(
                "启动立即执行已跳过",
                self._joined_logs(),
                "serial-b: the skip log semantics must be present",
            )

            # -- Act c: same captured task, daily scheduled occurrence -----
            logs_before_daily = len(self.log_sink)
            scheduled_for = datetime(2026, 10, 23, 23, 59)

            task(scheduled_for=scheduled_for)

            self.assertEqual(
                fake_analysis.call_count,
                1,
                "serial-c: the daily scheduled invocation must still "
                "execute run_full_analysis (daily runs are never "
                "deduplicated)",
            )
            self.assertEqual(
                getattr(fake_analysis.call_args.args[1], "_scheduled_for"),
                scheduled_for,
                "serial-c: the concrete scheduled_for occurrence must "
                "reach the run",
            )
            self.assertNotIn(
                "启动立即执行已跳过",
                "\n".join(self.log_sink[logs_before_daily:]),
                "serial-c: the daily scheduled invocation must not be "
                "gated by the startup dedup (fork at "
                "main.py `if scheduled_for is None`)",
            )


if __name__ == "__main__":
    unittest.main()
