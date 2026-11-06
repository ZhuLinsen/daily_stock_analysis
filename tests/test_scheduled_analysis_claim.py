# -*- coding: utf-8 -*-
"""Real SQLite/process regressions for daily CLI/API occurrence deduplication."""

import multiprocessing
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import schedule

from src.scheduler import Scheduler
from src.services.scheduled_analysis_claim import (
    ScheduledAnalysisSkipped, claim_scheduled_analysis, run_claimed_scheduled_analysis,
)


DUE = datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc)


def _config(database_path, stocks=None):
    return SimpleNamespace(database_path=database_path, stock_list=stocks or ["600519"])


def _scheduler(config, task, args=None):
    def dispatch(scheduled_for=None):
        if scheduled_for is None:
            return task()
        try:
            return run_claimed_scheduled_analysis(
                config, args or SimpleNamespace(), scheduled_for, lambda snapshot: task(),
            )
        except ScheduledAnalysisSkipped:
            return None

    scheduler = Scheduler(register_signals=False, pass_scheduled_for=True)
    scheduler.schedule = schedule.Scheduler()
    scheduler.set_daily_task(dispatch, run_immediately=False)
    return scheduler


def _dispatch_process(database_path, ready, start, result):
    calls = []
    scheduler = _scheduler(_config(database_path), lambda: calls.append("dispatched"))
    ready.put(True)
    if not start.wait(20):
        raise RuntimeError("test process did not receive dispatch signal")
    scheduler._daily_job.next_run = DUE
    scheduler._daily_job.job_func()
    result.put(len(calls))


class ScheduledAnalysisClaimTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / "analysis.db")
        self.config = _config(self.database)
        self.args = SimpleNamespace()

    def test_parallel_processes_dispatch_only_once(self):
        context = multiprocessing.get_context("spawn")
        ready, result, start = context.Queue(), context.Queue(), context.Event()
        processes = [
            context.Process(target=_dispatch_process, args=(self.database, ready, start, result))
            for _ in range(4)
        ]
        try:
            for process in processes:
                process.start()
            for _ in processes:
                self.assertTrue(ready.get(timeout=20))
            start.set()
            self.assertEqual(sum(result.get(timeout=20) for _ in processes), 1)
            for process in processes:
                process.join(20)
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(5)
            ready.close()
            result.close()

    def test_staggered_process_after_first_exits_does_not_dispatch_again(self):
        context = multiprocessing.get_context("spawn")
        ready, result, start = context.Queue(), context.Queue(), context.Event()
        start.set()
        try:
            for expected in (1, 0):
                process = context.Process(target=_dispatch_process, args=(self.database, ready, start, result))
                process.start()
                try:
                    self.assertTrue(ready.get(timeout=20))
                    self.assertEqual(result.get(timeout=20), expected)
                    process.join(20)
                    self.assertEqual(process.exitcode, 0)
                finally:
                    if process.is_alive():
                        process.terminate()
                        process.join(5)
        finally:
            ready.close()
            result.close()

    def test_actual_due_timestamp_survives_late_polling_and_multiple_slots(self):
        calls = []
        scheduler = _scheduler(self.config, lambda: calls.append("run"))
        scheduler._configure_daily_tasks(["09:00", "18:00"])
        due_times = [DUE - timedelta(hours=9), DUE]
        for job, due in zip(scheduler._daily_jobs, due_times):
            job.next_run = due
            # Both callbacks are dispatched at the same wall clock time, which
            # is deliberately unrelated to the captured original due date.
            job.job_func()
            job.job_func()
        self.assertEqual(calls, ["run", "run"])
        scheduler._daily_jobs[0].next_run = due_times[0] + timedelta(days=1)
        scheduler._daily_jobs[0].job_func()
        self.assertEqual(len(calls), 3)

    def test_timezone_offsets_identify_the_same_instant(self):
        self.assertTrue(claim_scheduled_analysis(self.config, self.args, DUE))
        equivalent = DUE.astimezone(timezone(timedelta(hours=8)))
        self.assertFalse(claim_scheduled_analysis(self.config, self.args, equivalent))
        self.assertTrue(claim_scheduled_analysis(self.config, self.args, equivalent + timedelta(hours=1)))

    @unittest.skipUnless(hasattr(__import__("time"), "tzset"), "requires POSIX TZ support")
    def test_naive_schedule_timestamp_uses_process_timezone(self):
        import time

        try:
            with patch.dict(os.environ, {"TZ": "UTC-8"}):
                time.tzset()
                local_due = datetime(2026, 10, 3, 2, 0)
                self.assertTrue(claim_scheduled_analysis(self.config, self.args, local_due))
                self.assertFalse(claim_scheduled_analysis(self.config, self.args, DUE))
        finally:
            time.tzset()

    def test_distinct_workloads_are_not_suppressed(self):
        self.assertTrue(claim_scheduled_analysis(self.config, self.args, DUE))
        for config, args in [
            (_config(self.database, ["000001"]), self.args),
            (self.config, SimpleNamespace(no_notify=True)),
            (self.config, SimpleNamespace(dry_run=True)),
            (self.config, SimpleNamespace(portfolio="futu")),
        ]:
            with self.subTest(args=args, config=config):
                self.assertTrue(claim_scheduled_analysis(config, args, DUE))
        config = _config(self.database, ["600519", "AAPL"])
        self.assertTrue(claim_scheduled_analysis(config, self.args, DUE))
        reordered = _config(self.database, ["aapl", "600519", "AAPL"])
        self.assertFalse(claim_scheduled_analysis(reordered, self.args, DUE))

    def test_startup_and_manual_callbacks_bypass_claims(self):
        calls = []
        scheduler = _scheduler(self.config, lambda: calls.append("run"))
        scheduler._daily_job.next_run = DUE
        scheduler._daily_job.job_func()
        scheduler._daily_job.job_func()
        scheduler._safe_run_task()
        scheduler.set_daily_task(lambda scheduled_for=None: calls.append("run"), run_immediately=True)
        self.assertEqual(len(calls), 3)

    def test_failed_dispatch_keeps_claim_to_avoid_repeating_partial_delivery(self):
        def fail_after_possible_delivery():
            raise RuntimeError("analysis failed")

        scheduler = _scheduler(self.config, fail_after_possible_delivery)
        with self.assertLogs("src.scheduler", level="ERROR"):
            scheduler._safe_run_task(scheduled_for=DUE)
        self.assertFalse(claim_scheduled_analysis(self.config, self.args, DUE))

    def test_claim_errors_are_visible_and_do_not_dispatch_uncoordinated(self):
        calls = []
        # A directory cannot be opened as the SQLite database.
        scheduler = _scheduler(_config(self.directory.name), lambda: calls.append("run"))
        with self.assertLogs("src.scheduler", level="ERROR") as logs:
            scheduler._safe_run_task(scheduled_for=DUE)
        self.assertEqual(calls, [])
        self.assertIn("unable to open database file", "\n".join(logs.output))

    def test_cleanup_removes_old_claims_but_retains_recent_ones(self):
        self.assertTrue(claim_scheduled_analysis(self.config, self.args, DUE))
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE scheduled_analysis_claims SET claimed_at = 0")
        tomorrow = DUE + timedelta(days=1)
        self.assertTrue(claim_scheduled_analysis(self.config, self.args, tomorrow))
        self.assertTrue(claim_scheduled_analysis(self.config, self.args, DUE))
        self.assertFalse(claim_scheduled_analysis(self.config, self.args, tomorrow))

    def test_config_edit_between_claim_and_execution_cannot_change_claimed_watchlist(self):
        persisted = {"stocks": ["600519"]}

        class RefreshingConfig(SimpleNamespace):
            def refresh_stock_list(self):
                self.stock_list = list(persisted["stocks"])

        config = RefreshingConfig(database_path=self.database, stock_list=[])
        executed = []

        def claim_then_edit(snapshot, args, due):
            claimed = claim_scheduled_analysis(snapshot, args, due)
            persisted["stocks"] = ["000001"]
            config.stock_list = ["000001"]
            return claimed

        with patch(
            "src.services.scheduled_analysis_claim.claim_scheduled_analysis",
            side_effect=claim_then_edit,
        ):
            run_claimed_scheduled_analysis(
                config, self.args, DUE, lambda snapshot: executed.append(snapshot.stock_list),
            )
        run_claimed_scheduled_analysis(
            config, self.args, DUE, lambda snapshot: executed.append(snapshot.stock_list),
        )
        with self.assertRaises(ScheduledAnalysisSkipped):
            run_claimed_scheduled_analysis(config, self.args, DUE, lambda snapshot: executed.append(snapshot.stock_list))
        self.assertEqual(executed, [["600519"], ["000001"]])
