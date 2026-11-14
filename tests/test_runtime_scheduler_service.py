# -*- coding: utf-8 -*-
"""Regression tests for RuntimeSchedulerService scheduling ownership."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.services.runtime_scheduler import (
    CLI_SCHEDULER_OWNER_ENV,
    DEFAULT_RUNTIME_SCHEDULER_TIMEOUT_SECONDS,
    RUNTIME_SCHEDULER_ARGS_ENV,
    RUNTIME_SCHEDULER_FORCE_ENABLED_ENV,
    RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV,
    RUNTIME_SCHEDULER_SUPPRESS_START_ENV,
    RUNTIME_SCHEDULER_TIMEOUT_ENV,
    RuntimeSchedulerService,
    _run_scheduled_analysis_process,
)


class _FakeJob:
    def __init__(self, schedule_module):
        self._schedule_module = schedule_module
        self.next_run = datetime(2026, 1, 1, 18, 0, 0)
        self.at_time = None
        self.job_func = None

    @property
    def day(self):
        return self

    def at(self, value):
        self.at_time = value
        hour, minute = [int(part) for part in value.split(":")]
        self.next_run = datetime(2026, 1, 1, hour, minute, 0)
        return self

    def do(self, fn):
        self.job_func = fn
        self._schedule_module.jobs.append(self)
        return self


class _FakeScheduleModule:
    def __init__(self):
        self.jobs = []

    def every(self):
        return _FakeJob(self)

    def get_jobs(self):
        return list(self.jobs)

    def run_pending(self):
        for job in list(self.jobs):
            job.job_func()

    def cancel_job(self, job):
        if job in self.jobs:
            self.jobs.remove(job)


class _NoopThread:
    def __init__(self, target=None, **kwargs):
        self.target = target
        self.kwargs = kwargs

    def start(self):
        return None

    def is_alive(self):
        return False


class _SynchronousThread(_NoopThread):
    def start(self):
        if self.target is not None:
            self.target()


_BLOCKING_THREAD_RELEASE = threading.Event()


def _blocking_thread_runner(config, args, stock_codes):
    _BLOCKING_THREAD_RELEASE.wait(timeout=5)
    return True


def _blocking_spawn_runner(result_queue, stock_codes, schedule_args_overrides):
    time.sleep(10)


def _successful_spawn_runner(result_queue, stock_codes, schedule_args_overrides):
    result_queue.put({"success": True, "error": None})


def _large_failure_spawn_runner(result_queue, stock_codes, schedule_args_overrides):
    result_queue.put({"success": False, "error": "x" * (1024 * 1024)})


def _exit_with_live_descendant_spawn_runner(result_queue, stock_codes, schedule_args_overrides):
    os.setsid()
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid_file = Path(os.environ["DSA_TEST_DESCENDANT_PID_FILE"])
    pid_file.write_text(f"{os.getpid()} {child.pid}", encoding="utf-8")


def _block_with_isolated_descendant_spawn_runner(result_queue, stock_codes, schedule_args_overrides):
    os.setsid()
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid_file = Path(os.environ["DSA_TEST_DESCENDANT_PID_FILE"])
    pid_file.write_text(f"{os.getpid()} {child.pid}", encoding="utf-8")
    time.sleep(30)


class RuntimeSchedulerServiceTestCase(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX session-isolation regression")
    def test_worker_fails_before_analysis_when_posix_session_isolation_fails(self) -> None:
        with patch(
            "src.services.runtime_scheduler.os.setsid",
            side_effect=OSError("not permitted"),
        ), patch(
            "src.services.runtime_scheduler.os.getsid",
            return_value=101,
        ), patch(
            "src.services.runtime_scheduler.os.getpid",
            return_value=202,
        ):
            with self.assertRaisesRegex(OSError, "not permitted"):
                _run_scheduled_analysis_process(MagicMock(), None, {})

    def test_child_restores_due_occurrence_and_returns_skip_status(self) -> None:
        due = datetime(2026, 10, 2, 18)
        queue = MagicMock()
        worker = MagicMock()
        worker._run_analysis_locked.return_value = True
        worker._last_error = None
        worker._last_skip_reason = "scheduled_occurrence_already_claimed"
        with patch("src.services.runtime_scheduler.os.setsid"), patch(
            "src.services.runtime_scheduler.RuntimeSchedulerService", return_value=worker,
        ) as service_type:
            _run_scheduled_analysis_process(queue, None, {"_scheduled_for": due.isoformat(), "no_notify": True})
        service_type.assert_called_once_with(schedule_args_overrides={"no_notify": True})
        worker._run_analysis_locked.assert_called_once_with(None, scheduled_for=due)
        self.assertEqual(queue.put.call_args.args[0]["skipped"], "scheduled_occurrence_already_claimed")

    def test_analysis_timeout_reads_current_environment_with_safe_bounds(self) -> None:
        service = RuntimeSchedulerService()

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                service._analysis_timeout_seconds(),
                DEFAULT_RUNTIME_SCHEDULER_TIMEOUT_SECONDS,
            )

        for value, expected in (
            ("0", 60),
            ("59", 60),
            ("60", 60),
            ("600", 600),
            ("invalid", DEFAULT_RUNTIME_SCHEDULER_TIMEOUT_SECONDS),
        ):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {RUNTIME_SCHEDULER_TIMEOUT_ENV: value},
                clear=True,
            ):
                self.assertEqual(service._analysis_timeout_seconds(), expected)

    def test_run_analysis_args_include_workers(self) -> None:
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        seen_args = []

        def runner(config_arg, args, stock_codes):
            seen_args.append(args)

        service = RuntimeSchedulerService(
            config_provider=lambda: config,
            task_runner=runner,
        )
        service._reload_config = lambda: config

        service._run_analysis_once()

        self.assertEqual(len(seen_args), 1)
        self.assertTrue(hasattr(seen_args[0], "workers"))
        self.assertIsNone(seen_args[0].workers)

    def test_run_analysis_args_preserve_startup_schedule_flags(self) -> None:
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        seen_args = []

        def runner(config_arg, args, stock_codes):
            seen_args.append(args)

        service = RuntimeSchedulerService(
            config_provider=lambda: config,
            task_runner=runner,
            schedule_args_overrides={
                "no_notify": True,
                "no_market_review": True,
                "dry_run": True,
                "force_run": True,
                "single_notify": True,
                "no_context_snapshot": True,
                "workers": 3,
                "serve": True,
            },
        )
        service._reload_config = lambda: config

        service._run_analysis_once()

        self.assertEqual(len(seen_args), 1)
        self.assertTrue(seen_args[0].no_notify)
        self.assertTrue(seen_args[0].no_market_review)
        self.assertTrue(seen_args[0].dry_run)
        self.assertTrue(seen_args[0].force_run)
        self.assertTrue(seen_args[0].single_notify)
        self.assertTrue(seen_args[0].no_context_snapshot)
        self.assertEqual(seen_args[0].workers, 3)
        self.assertFalse(seen_args[0].serve)
        self.assertTrue(seen_args[0].serve_only)

    def test_default_runner_does_not_mark_failed_analysis_return_success(self) -> None:
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._reload_config = lambda: config

        with patch("main.run_full_analysis", return_value=False) as run_full_analysis:
            service._run_analysis_once()

        run_full_analysis.assert_called_once()
        self.assertTrue(run_full_analysis.call_args.kwargs["raise_errors"])
        status = service.status()
        self.assertIsNone(status["last_success_at"])
        self.assertIn("reported failure", status["last_error"])

    def test_run_now_rejects_when_analysis_is_already_running(self) -> None:
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._run_lock.acquire()
        try:
            result = service.run_now()
        finally:
            service._run_lock.release()

        self.assertFalse(result["accepted"])
        self.assertTrue(result["running"])
        self.assertEqual(result["reason"], "analysis_already_running")
        status = service.status()
        self.assertEqual(status["last_skip_reason"], "analysis_already_running")
        self.assertIsNotNone(status["last_skipped_at"])

    def test_run_now_runs_analysis_with_default_stock_scope(self) -> None:
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._analysis_process_target = _successful_spawn_runner
        result = service.run_now()

        self.assertTrue(result["accepted"])
        deadline = time.monotonic() + 4
        while service.status()["last_success_at"] is None and time.monotonic() < deadline:
            time.sleep(0.05)
        status = service.status()
        self.assertFalse(status["running"])
        self.assertIsNotNone(status["last_run_at"])
        self.assertIsNotNone(status["last_success_at"])
        self.assertIsNone(status["last_error"])

    def test_blocked_scheduled_analysis_times_out_and_allows_next_run(self) -> None:
        fake_schedule = _FakeScheduleModule()
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        service = RuntimeSchedulerService(
            config_provider=lambda: config,
            task_runner=_blocking_thread_runner,
        )
        service._reload_config = lambda: config
        service._analysis_process_target = _blocking_spawn_runner
        service._analysis_timeout_seconds = lambda: 1

        with patch.dict(sys.modules, {"schedule": fake_schedule}), patch(
            "src.services.runtime_scheduler.threading.Thread",
            _NoopThread,
        ):
            service.reconcile_from_config()

        callback_returned = threading.Event()
        trigger = threading.Thread(
            target=lambda: (fake_schedule.run_pending(), callback_returned.set()),
            daemon=True,
        )
        _BLOCKING_THREAD_RELEASE.clear()
        trigger.start()
        try:
            self.assertTrue(
                callback_returned.wait(timeout=0.5),
                "the scheduler callback remained blocked by analysis",
            )

            deadline = time.monotonic() + 10
            while service.status()["last_error"] is None and time.monotonic() < deadline:
                time.sleep(0.05)

            status = service.status()
            self.assertFalse(status["running"])
            self.assertIn("timed out after 1s", status["last_error"])

            service._analysis_process_target = _successful_spawn_runner
            # The recovery assertion is about releasing the run lock, not
            # whether a spawn interpreter can import dependencies within 1s.
            service._analysis_timeout_seconds = lambda: 5
            self.assertTrue(service.run_now()["accepted"])

            deadline = time.monotonic() + 10
            while service.status()["last_success_at"] is None and time.monotonic() < deadline:
                time.sleep(0.05)

            status = service.status()
            self.assertFalse(status["running"])
            self.assertIsNotNone(status["last_success_at"])
            self.assertIsNone(status["last_error"])
        finally:
            _BLOCKING_THREAD_RELEASE.set()
            trigger.join(timeout=5)

    def test_stop_terminates_active_analysis_worker(self) -> None:
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._analysis_process_target = _blocking_spawn_runner

        self.assertTrue(service.run_now()["accepted"])
        deadline = time.monotonic() + 5
        while service.status()["last_run_at"] is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIsNotNone(service.status()["last_run_at"])

        service.stop()

        deadline = time.monotonic() + 5
        while service.status()["running"] and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(service.status()["running"])

    def test_stop_does_not_record_expected_worker_termination_as_error(self) -> None:
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._analysis_process_target = _blocking_spawn_runner

        self.assertTrue(service.run_now()["accepted"])
        deadline = time.monotonic() + 5
        while service.status()["last_run_at"] is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIsNotNone(service.status()["last_run_at"])

        service.stop()

        deadline = time.monotonic() + 5
        while service.status()["running"] and time.monotonic() < deadline:
            time.sleep(0.05)
        status = service.status()
        self.assertFalse(status["running"])
        self.assertIsNone(status["last_error"])

    def test_stale_scheduled_callback_cannot_start_after_stop(self) -> None:
        fake_schedule = _FakeScheduleModule()
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        service = RuntimeSchedulerService(config_provider=lambda: config)

        with patch.dict(sys.modules, {"schedule": fake_schedule}), patch(
            "src.services.runtime_scheduler.threading.Thread",
            _NoopThread,
        ):
            service.start()

        callback = fake_schedule.get_jobs()[0].job_func
        service.stop()

        with patch(
            "src.services.runtime_scheduler.multiprocessing.get_context"
        ) as get_context:
            self.assertFalse(callback())

        get_context.assert_not_called()
        self.assertFalse(service.status()["running"])

    def test_watchdog_reads_large_worker_result_before_joining(self) -> None:
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._analysis_process_target = _large_failure_spawn_runner
        service._analysis_timeout_seconds = lambda: 2

        self.assertTrue(service.run_now()["accepted"])
        deadline = time.monotonic() + 5
        while service.status()["last_error"] is None and time.monotonic() < deadline:
            time.sleep(0.05)

        self.assertTrue(service.status()["last_error"].startswith("x"))

    @unittest.skipUnless(os.name == "posix", "POSIX process-group regression")
    def test_worker_exit_without_result_terminates_remaining_process_group(self) -> None:
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._analysis_process_target = _exit_with_live_descendant_spawn_runner

        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / "descendant.pid"
            process_group_id = None
            child_pid = None
            try:
                with patch.dict(
                    os.environ,
                    {"DSA_TEST_DESCENDANT_PID_FILE": str(pid_file)},
                ):
                    self.assertTrue(service.run_now()["accepted"])
                    deadline = time.monotonic() + 5
                    while not pid_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertTrue(pid_file.exists())
                    process_group_id, child_pid = [
                        int(value) for value in pid_file.read_text(encoding="utf-8").split()
                    ]

                    while service.status()["running"] and time.monotonic() < deadline:
                        time.sleep(0.05)

                self.assertFalse(service.status()["running"])
                self.assertIn("exited without a result", service.status()["last_error"])
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                if process_group_id is not None:
                    try:
                        os.killpg(process_group_id, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    @unittest.skipUnless(os.name == "posix", "POSIX process-tree regression")
    def test_stop_terminates_descendant_in_a_nested_process_group(self) -> None:
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._analysis_process_target = _block_with_isolated_descendant_spawn_runner

        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / "descendant.pid"
            process_group_id = None
            child_pid = None
            try:
                with patch.dict(
                    os.environ,
                    {"DSA_TEST_DESCENDANT_PID_FILE": str(pid_file)},
                ):
                    self.assertTrue(service.run_now()["accepted"])
                    deadline = time.monotonic() + 5
                    while not pid_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertTrue(pid_file.exists())
                    process_group_id, child_pid = [
                        int(value) for value in pid_file.read_text(encoding="utf-8").split()
                    ]

                    service.stop()
                    while service.status()["running"] and time.monotonic() < deadline:
                        time.sleep(0.05)

                self.assertFalse(service.status()["running"])
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                for group_id in (child_pid, process_group_id):
                    if group_id is None:
                        continue
                    try:
                        os.killpg(group_id, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_run_now_uses_shared_lock_across_service_instances(self) -> None:
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        primary_service = RuntimeSchedulerService(config_provider=lambda: config)
        secondary_service = RuntimeSchedulerService(config_provider=lambda: config)

        self.assertIs(primary_service._run_lock, secondary_service._run_lock)

        primary_service._run_lock.acquire()
        try:
            result = secondary_service.run_now()
        finally:
            primary_service._run_lock.release()

        self.assertFalse(result["accepted"])
        self.assertEqual(result["running"], True)
        self.assertEqual(result["reason"], "analysis_already_running")
        status = secondary_service.status()
        self.assertEqual(status["last_skip_reason"], "analysis_already_running")
        self.assertIsNotNone(status["last_skipped_at"])

    def test_run_now_endpoint_returns_conflict_when_scheduler_is_busy(self) -> None:
        from api.v1.endpoints.system_config import run_scheduler_now

        scheduler = MagicMock()
        scheduler.run_now.return_value = {
            "accepted": False,
            "running": True,
            "reason": "analysis_already_running",
        }

        with self.assertRaises(HTTPException) as captured:
            run_scheduler_now(scheduler=scheduler)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(captured.exception.detail["error"], "scheduler_busy")
        self.assertEqual(captured.exception.detail["reason"], "analysis_already_running")

    def test_reconcile_replaces_daily_jobs_without_triggering_old_jobs(self) -> None:
        fake_schedule = _FakeScheduleModule()
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["09:20"],
        )
        calls = []

        def runner(config_arg, args, stock_codes):
            calls.append("run")

        service = RuntimeSchedulerService(
            config_provider=lambda: config,
            task_runner=runner,
        )
        service._reload_config = lambda: config

        with patch.object(
            service,
            "_start_analysis_watchdog",
            side_effect=lambda stock_codes=None, **kwargs: calls.append("run") or True,
        ), patch.dict(sys.modules, {"schedule": fake_schedule}), patch(
            "src.services.runtime_scheduler.threading.Thread",
            _NoopThread,
        ):
            service.reconcile_from_config()
            old_jobs = fake_schedule.get_jobs()
            self.assertEqual([job.at_time for job in old_jobs], ["09:20"])

            config.schedule_times = ["15:10"]
            service.reconcile_from_config()

            self.assertEqual([job.at_time for job in fake_schedule.get_jobs()], ["15:10"])
            self.assertNotIn(old_jobs[0], fake_schedule.get_jobs())

            fake_schedule.run_pending()

        self.assertEqual(calls, ["run"])

    def test_initial_reconcile_can_run_immediately_once(self) -> None:
        fake_schedule = _FakeScheduleModule()
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["09:20"],
        )
        calls = []

        def runner(config_arg, args, stock_codes):
            calls.append("run")

        service = RuntimeSchedulerService(
            config_provider=lambda: config,
            task_runner=runner,
        )
        service._reload_config = lambda: config

        with patch.object(
            service,
            "_start_analysis_watchdog",
            side_effect=lambda stock_codes=None, **kwargs: calls.append("run") or True,
        ), patch.dict(sys.modules, {"schedule": fake_schedule}), patch(
            "src.services.runtime_scheduler.threading.Thread",
            _NoopThread,
        ):
            service.reconcile_from_config(run_immediately=True)
            config.schedule_times = ["15:10"]
            service.reconcile_from_config()

        self.assertEqual(calls, ["run"])

    def test_background_task_active_requires_live_registered_scheduler(self) -> None:
        service = RuntimeSchedulerService()
        service._enabled = True
        service._scheduler = SimpleNamespace(
            _background_tasks=[{"name": "agent_event_monitor"}],
        )
        service._thread = SimpleNamespace(is_alive=lambda: True)

        self.assertTrue(service.is_background_task_active("agent_event_monitor"))
        self.assertFalse(service.is_background_task_active("missing"))

        service._thread = SimpleNamespace(is_alive=lambda: False)
        self.assertFalse(service.is_background_task_active("agent_event_monitor"))

    def test_start_registers_event_monitor_background_task(self) -> None:
        class _FakeScheduler:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.background_tasks = []
                self.daily_task = None
                self.daily_task_run_immediately = None
                self._jobs = []

            def set_daily_task(self, task, run_immediately: bool) -> None:
                self.daily_task = task
                self.daily_task_run_immediately = run_immediately

            def add_background_task(
                self,
                task: callable,
                interval_seconds: int,
                run_immediately: bool,
                name: str | None = None,
            ) -> None:
                self.background_tasks.append({
                    "task": task,
                    "interval_seconds": interval_seconds,
                    "run_immediately": run_immediately,
                    "name": name,
                })

            def run(self) -> None:
                return None

            def stop(self) -> None:
                return None

            @property
            def schedule(self):
                class _Namespace:
                    @staticmethod
                    def get_jobs():
                        return []

                return _Namespace

            @property
            def schedule_time(self):
                return self.kwargs.get("schedule_time")

        fake_worker = MagicMock()
        fake_worker.run_once.return_value = {"triggered": 2}

        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
            agent_event_monitor_enabled=True,
            agent_event_monitor_interval_minutes=7,
        )

        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._reload_config = lambda: config

        with patch(
            "src.services.runtime_scheduler.Scheduler",
            _FakeScheduler,
        ), patch(
            "src.services.runtime_scheduler.threading.Thread",
            _NoopThread,
        ), patch("src.services.alert_worker.AlertWorker", return_value=fake_worker):
            service.start()

        scheduler = service._scheduler
        self.assertIsNotNone(scheduler)
        self.assertEqual(len(scheduler.background_tasks), 1)  # type: ignore[attr-defined]
        self.assertEqual(scheduler.background_tasks[0]["name"], "agent_event_monitor")  # type: ignore[index]
        self.assertEqual(scheduler.background_tasks[0]["interval_seconds"], 7 * 60)  # type: ignore[index]
        self.assertEqual(scheduler.background_tasks[0]["run_immediately"], True)  # type: ignore[index]
        scheduler.background_tasks[0]["task"]()  # type: ignore[index]
        fake_worker.run_once.assert_called_once()

    def test_rebuild_reuses_event_monitor_without_immediate_rerun(self) -> None:
        schedulers = []

        class _FakeScheduler:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.background_tasks = []
                self.daily_task = None
                self.daily_task_run_immediately = None
                self._jobs = []
                schedulers.append(self)

            def set_daily_task(self, task, run_immediately: bool) -> None:
                self.daily_task = task
                self.daily_task_run_immediately = run_immediately

            def add_background_task(
                self,
                task: callable,
                interval_seconds: int,
                run_immediately: bool,
                name: str | None = None,
            ) -> None:
                self.background_tasks.append({
                    "task": task,
                    "interval_seconds": interval_seconds,
                    "run_immediately": run_immediately,
                    "name": name,
                })

            def run(self) -> None:
                return None

            def stop(self) -> None:
                return None

            @property
            def schedule(self):
                class _Namespace:
                    @staticmethod
                    def get_jobs():
                        return []

                return _Namespace

            @property
            def schedule_time(self):
                return self.kwargs.get("schedule_time")

        fake_worker = MagicMock()
        fake_worker.run_once.return_value = {"triggered": 0}

        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
            agent_event_monitor_enabled=True,
            agent_event_monitor_interval_minutes=7,
        )

        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._reload_config = lambda: config

        with patch(
            "src.services.runtime_scheduler.Scheduler",
            _FakeScheduler,
        ), patch(
            "src.services.runtime_scheduler.threading.Thread",
            _NoopThread,
        ), patch("src.services.alert_worker.AlertWorker", return_value=fake_worker) as worker_cls:
            service.reconcile_from_config()
            config.schedule_times = ["19:00"]
            config.agent_event_monitor_interval_minutes = 11
            service.reconcile_from_config()
            config.schedule_times = ["20:00"]
            service.reconcile_from_config()

        self.assertEqual(worker_cls.call_count, 1)
        self.assertEqual(len(schedulers), 3)
        first_task = schedulers[0].background_tasks[0]
        second_task = schedulers[1].background_tasks[0]
        third_task = schedulers[2].background_tasks[0]
        self.assertTrue(first_task["run_immediately"])
        self.assertFalse(second_task["run_immediately"])
        self.assertFalse(third_task["run_immediately"])
        self.assertIs(first_task["task"], second_task["task"])
        self.assertIs(first_task["task"], third_task["task"])
        self.assertEqual(second_task["interval_seconds"], 11 * 60)
        self.assertEqual(third_task["interval_seconds"], 11 * 60)

    def test_force_enabled_survives_time_reconcile_until_explicit_enabled_update(self) -> None:
        fake_schedule = _FakeScheduleModule()
        config = SimpleNamespace(
            schedule_enabled=False,
            schedule_time="18:00",
            schedule_times=["09:20"],
        )
        service = RuntimeSchedulerService(
            config_provider=lambda: config,
            force_enabled=True,
        )

        with patch.dict(sys.modules, {"schedule": fake_schedule}), patch(
            "src.services.runtime_scheduler.threading.Thread",
            _NoopThread,
        ):
            service.reconcile_from_config()
            self.assertTrue(service.status()["enabled"])

            config.schedule_times = ["15:10"]
            service.reconcile_from_config()
            self.assertTrue(service.status()["enabled"])
            self.assertEqual([job.at_time for job in fake_schedule.get_jobs()], ["15:10"])

            service.reconcile_from_config(clear_enabled_override=True)
            self.assertFalse(service.status()["enabled"])
            self.assertEqual(fake_schedule.get_jobs(), [])

    def test_lifespan_disables_runtime_scheduler_when_cli_owns_schedule(self) -> None:
        from api.app import create_app

        events = []

        class FakeRuntimeSchedulerService:
            def __init__(
                self,
                *,
                owns_schedule=True,
                force_enabled=False,
                run_immediately_in_background=False,
                schedule_args_overrides=None,
            ):
                self.owns_schedule = owns_schedule
                self.force_enabled = force_enabled
                events.append(("init", owns_schedule, force_enabled, run_immediately_in_background))

            def reconcile_from_config(self, *, run_immediately=False, clear_enabled_override=False):
                events.append((
                    "reconcile",
                    self.owns_schedule,
                    run_immediately,
                    clear_enabled_override,
                ))

            def stop(self):
                events.append(("stop", self.owns_schedule))

        class FakeSystemConfigService:
            def __init__(self, runtime_scheduler=None):
                self.runtime_scheduler = runtime_scheduler

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {CLI_SCHEDULER_OWNER_ENV: "true"},
            clear=False,
        ), patch(
            "src.config.get_config",
            return_value=SimpleNamespace(schedule_run_immediately=True),
        ), patch("api.app.RuntimeSchedulerService", FakeRuntimeSchedulerService), patch(
            "api.app.SystemConfigService",
            FakeSystemConfigService,
        ), patch("api.app._schedule_stock_index_background_refresh"):
            app = create_app(static_dir=Path(temp_dir))
            with TestClient(app):
                pass

        self.assertEqual(events, [
            ("init", False, False, True),
            ("reconcile", False, False, False),
            ("stop", False),
        ])

    def test_lifespan_passes_runtime_scheduler_start_flags(self) -> None:
        from api.app import create_app

        events = []

        class FakeRuntimeSchedulerService:
            def __init__(
                self,
                *,
                owns_schedule=True,
                force_enabled=False,
                run_immediately_in_background=False,
                schedule_args_overrides=None,
            ):
                events.append(("init", owns_schedule, force_enabled, run_immediately_in_background))

            def reconcile_from_config(self, *, run_immediately=False, clear_enabled_override=False):
                events.append(("reconcile", run_immediately, clear_enabled_override))

            def stop(self):
                events.append(("stop",))

        class FakeSystemConfigService:
            def __init__(self, runtime_scheduler=None):
                self.runtime_scheduler = runtime_scheduler

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {
                RUNTIME_SCHEDULER_FORCE_ENABLED_ENV: "true",
                RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV: "true",
            },
            clear=False,
        ), patch("api.app.RuntimeSchedulerService", FakeRuntimeSchedulerService), patch(
            "api.app.SystemConfigService",
            FakeSystemConfigService,
        ), patch("api.app._schedule_stock_index_background_refresh"):
            app = create_app(static_dir=Path(temp_dir))
            with TestClient(app):
                pass

        self.assertEqual(events, [
            ("init", True, True, True),
            ("reconcile", True, False),
            ("stop",),
        ])
        self.assertIsNone(os.getenv(RUNTIME_SCHEDULER_FORCE_ENABLED_ENV))
        self.assertIsNone(os.getenv(RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV))

    def test_lifespan_suppresses_initial_start_without_losing_runtime_ownership(self) -> None:
        from api.app import create_app

        events = []

        class FakeRuntimeSchedulerService:
            def __init__(
                self,
                *,
                owns_schedule=True,
                force_enabled=False,
                run_immediately_in_background=False,
                schedule_args_overrides=None,
            ):
                events.append(("init", owns_schedule, force_enabled, run_immediately_in_background))

            def reconcile_from_config(self, *, run_immediately=False, clear_enabled_override=False):
                events.append(("reconcile", run_immediately, clear_enabled_override))

            def stop(self):
                events.append(("stop",))

        class FakeSystemConfigService:
            def __init__(self, runtime_scheduler=None):
                self.runtime_scheduler = runtime_scheduler

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {RUNTIME_SCHEDULER_SUPPRESS_START_ENV: "true"},
            clear=False,
        ), patch(
            "src.config.get_config",
            return_value=SimpleNamespace(schedule_run_immediately=True),
        ), patch("api.app.RuntimeSchedulerService", FakeRuntimeSchedulerService), patch(
            "api.app.SystemConfigService",
            FakeSystemConfigService,
        ), patch("api.app._schedule_stock_index_background_refresh"):
            app = create_app(static_dir=Path(temp_dir))
            with TestClient(app):
                pass

        self.assertEqual(events, [
            ("init", True, False, True),
            ("stop",),
        ])
        self.assertIsNone(os.getenv(RUNTIME_SCHEDULER_SUPPRESS_START_ENV))

    def test_lifespan_passes_runtime_scheduler_args_overrides(self) -> None:
        from api.app import create_app

        events = []
        runtime_args = {
            "no_notify": True,
            "no_market_review": True,
            "dry_run": True,
            "force_run": True,
            "single_notify": True,
            "no_context_snapshot": True,
            "workers": 4,
        }

        class FakeRuntimeSchedulerService:
            def __init__(
                self,
                *,
                owns_schedule=True,
                force_enabled=False,
                run_immediately_in_background=False,
                schedule_args_overrides=None,
            ):
                events.append(("init_args", schedule_args_overrides))

            def reconcile_from_config(self, *, run_immediately=False, clear_enabled_override=False):
                events.append(("reconcile", run_immediately, clear_enabled_override))

            def stop(self):
                events.append(("stop",))

        class FakeSystemConfigService:
            def __init__(self, runtime_scheduler=None):
                self.runtime_scheduler = runtime_scheduler

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {RUNTIME_SCHEDULER_ARGS_ENV: json.dumps(runtime_args)},
            clear=False,
        ), patch(
            "src.config.get_config",
            return_value=SimpleNamespace(schedule_run_immediately=True),
        ), patch("api.app.RuntimeSchedulerService", FakeRuntimeSchedulerService), patch(
            "api.app.SystemConfigService",
            FakeSystemConfigService,
        ), patch("api.app._schedule_stock_index_background_refresh"):
            app = create_app(static_dir=Path(temp_dir))
            with TestClient(app):
                pass

        self.assertEqual(events[0], ("init_args", runtime_args))
        self.assertIsNone(os.getenv(RUNTIME_SCHEDULER_ARGS_ENV))

    def test_lifespan_uses_configured_run_immediately_without_override(self) -> None:
        from api.app import create_app

        events = []

        class FakeRuntimeSchedulerService:
            def __init__(
                self,
                *,
                owns_schedule=True,
                force_enabled=False,
                run_immediately_in_background=False,
                schedule_args_overrides=None,
            ):
                events.append(("init", owns_schedule, force_enabled, run_immediately_in_background))

            def reconcile_from_config(self, *, run_immediately=False, clear_enabled_override=False):
                events.append(("reconcile", run_immediately, clear_enabled_override))

            def stop(self):
                events.append(("stop",))

        class FakeSystemConfigService:
            def __init__(self, runtime_scheduler=None):
                self.runtime_scheduler = runtime_scheduler

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {}, clear=False), patch(
            "src.config.get_config",
            return_value=SimpleNamespace(schedule_run_immediately=True),
        ), patch("api.app.RuntimeSchedulerService", FakeRuntimeSchedulerService), patch(
            "api.app.SystemConfigService",
            FakeSystemConfigService,
        ), patch("api.app._schedule_stock_index_background_refresh"):
            os.environ.pop(CLI_SCHEDULER_OWNER_ENV, None)
            os.environ.pop(RUNTIME_SCHEDULER_FORCE_ENABLED_ENV, None)
            os.environ.pop(RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV, None)

            app = create_app(static_dir=Path(temp_dir))
            with TestClient(app):
                pass

        self.assertEqual(events, [
            ("init", True, False, True),
            ("reconcile", True, False),
            ("stop",),
        ])


class HotTop10DailyJobRegistrationTest(unittest.TestCase):
    """OR-COR-0bd16091 / OR-COR-095e5cc9: Web/API/Desktop runtime wiring.

    The hot-top10 daily job used to register only in the pure CLI schedule
    branch of ``main.py``; ``RuntimeSchedulerService.start()`` never added
    it, so long-lived API/Web/Desktop processes never ran the analysis
    even with HOT_TOP10_ENABLED=true. The review probe (count of auxiliary
    daily jobs after a real start()) must now include the hot-top10 job.
    """

    @staticmethod
    def _config(*, hot_top10_enabled: bool) -> SimpleNamespace:
        return SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
            hot_top10_enabled=hot_top10_enabled,
            hot_top10_schedule_time="15:10",
            hot_top10_data_ready_schedule_time="15:35",
        )

    def _start(self, config: SimpleNamespace) -> RuntimeSchedulerService:
        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._reload_config = lambda: config
        with patch(
            "src.services.runtime_scheduler.threading.Thread",
            _NoopThread,
        ):
            service.start()
        self.addCleanup(service.stop)
        return service

    def test_real_start_registers_hot_top10_extra_daily_job(self) -> None:
        service = self._start(self._config(hot_top10_enabled=True))

        scheduler = service._scheduler
        self.assertIsNotNone(scheduler)
        extra_jobs = list(getattr(scheduler, "_extra_daily_jobs", []))
        # Two slots: the primary 15:10 occurrence plus the data-ready
        # follow-up at 15:35 (after the 15:30 ranking data cut).
        self.assertEqual(len(extra_jobs), 2)
        at_times = {
            f"{job.at_time.hour:02d}:{job.at_time.minute:02d}"
            for job in extra_jobs
        }
        self.assertEqual(at_times, {"15:10", "15:35"})

    def test_real_start_registers_no_hot_top10_job_when_disabled(self) -> None:
        service = self._start(self._config(hot_top10_enabled=False))

        scheduler = service._scheduler
        self.assertIsNotNone(scheduler)
        extra_jobs = list(getattr(scheduler, "_extra_daily_jobs", []))
        self.assertEqual(extra_jobs, [])

    def test_registered_job_invokes_service_with_scheduler_semantics(self) -> None:
        service = self._start(self._config(hot_top10_enabled=True))
        scheduler = service._scheduler
        assert scheduler is not None
        extra_jobs = list(getattr(scheduler, "_extra_daily_jobs", []))
        self.assertEqual(len(extra_jobs), 2)

        with patch(
            "src.services.hot_top10_service.run_hot_top10_analysis"
        ) as run_mock:
            for job in extra_jobs:
                job.job_func()
            scheduler._join_extra_daily_job_workers(timeout=30)

        # Both slots run the real service with scheduler semantics (via the
        # background worker dispatch, OR-COR-f3a76b12).
        self.assertEqual(run_mock.call_count, 2)
        for call in run_mock.call_args_list:
            runtime_config = call.args[0]
            self.assertIs(runtime_config.hot_top10_enabled, True)
            kwargs = call.kwargs
            # Scheduled occurrences keep the trading-day gate and daily dedup.
            self.assertTrue(kwargs["respect_dedup"])
            self.assertFalse(kwargs["force_run"])
            # Default runtime schedule args carry no_notify=False.
            self.assertIs(kwargs["send_notification"], True)

    def test_job_honors_no_notify_schedule_override(self) -> None:
        config = self._config(hot_top10_enabled=True)
        service = RuntimeSchedulerService(
            config_provider=lambda: config,
            schedule_args_overrides={"no_notify": True},
        )
        service._reload_config = lambda: config
        with patch(
            "src.services.runtime_scheduler.threading.Thread",
            _NoopThread,
        ):
            service.start()
        self.addCleanup(service.stop)

        scheduler = service._scheduler
        assert scheduler is not None
        extra_jobs = list(getattr(scheduler, "_extra_daily_jobs", []))
        self.assertEqual(len(extra_jobs), 2)

        with patch(
            "src.services.hot_top10_service.run_hot_top10_analysis"
        ) as run_mock:
            for job in extra_jobs:
                job.job_func()
            scheduler._join_extra_daily_job_workers(timeout=30)

        self.assertEqual(run_mock.call_count, 2)
        for call in run_mock.call_args_list:
            self.assertIs(call.kwargs["send_notification"], False)


class HotTop10RuntimeSameDaySecondRunTest(unittest.TestCase):
    """OR-COR-3e7f490e (narrowed): same-day second execution through the
    REAL RuntimeSchedulerService start() path.

    ``start()`` must register a data-ready follow-up occurrence (default
    15:35, after the 15:30 Tushare ranking cut) alongside the primary
    15:10 slot. When the primary slot delivered the previous trading day's
    list (stale, marker left open), the data-ready occurrence delivers
    today's list once the provider serves it; when the primary slot already
    delivered today's data, the data-ready occurrence idles (no duplicate
    push).
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _config(self) -> SimpleNamespace:
        return SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
            hot_top10_enabled=True,
            hot_top10_schedule_time="15:10",
            hot_top10_data_ready_schedule_time="15:35",
            hot_top10_count=10,
            report_language="zh",
            trading_day_check_enabled=True,
            database_path=str(Path(self._tmp.name) / "stock_analysis.db"),
        )

    def _payload(self, trade_date: str) -> dict:
        return {
            "status": "ok",
            "market": "cn",
            "trade_date": trade_date,
            "active_themes": [
                {
                    "name": "主题1",
                    "code": "BK0001",
                    "change_pct": 3.1,
                    "rank": 1,
                    "source": "industry",
                    "phase": "accelerating",
                    "reason": "industry ranking gain",
                }
            ],
            "leading_industries": [],
            "leading_concepts": [],
            "lagging_themes": [],
            "data_quality": {
                "status": "ok",
                "missing_fields": [],
                "sources": [],
                "errors": [],
            },
        }

    def _start_service(self, config: SimpleNamespace):
        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._reload_config = lambda: config
        with patch(
            "src.services.runtime_scheduler.threading.Thread",
            _NoopThread,
        ):
            service.start()
        self.addCleanup(service.stop)

        scheduler = service._scheduler
        assert scheduler is not None
        jobs_by_time = {
            f"{job.at_time.hour:02d}:{job.at_time.minute:02d}": job
            for job in scheduler._extra_daily_jobs
        }
        return jobs_by_time, scheduler

    def _patches(self, payload_holder, notifier):
        class _FakeHotspotService:
            def get_hotspots(self, **kwargs):
                return payload_holder["payload"]

        class _FakeNotificationService:
            def is_available(self) -> bool:
                return True

            def save_report_to_file(self, content, filename) -> str:
                return filename

            def send(self, content, **kwargs) -> bool:
                notifier.sent.append(content)
                return True

        class _FakeAnalyzer:
            def generate_text(self, prompt, **kwargs):
                return json.dumps(
                    {"summary": "概览", "items": []}, ensure_ascii=False
                )

        return [
            patch(
                "src.services.market_hotspot_service.MarketHotspotService",
                _FakeHotspotService,
            ),
            patch(
                "src.notification.NotificationService",
                _FakeNotificationService,
            ),
            patch(
                "src.services.hot_top10_service._build_analyzer",
                return_value=_FakeAnalyzer(),
            ),
            patch(
                "src.core.trading_calendar.get_open_markets_today",
                return_value={"cn"},
            ),
        ]

    def test_stale_primary_then_fresh_data_ready_slot_delivers_today(self) -> None:
        import contextlib
        from datetime import date as date_cls

        from src.services.hot_top10_service import hot_top10_marker_path

        today = date_cls.today().isoformat()
        yesterday = date_cls.fromordinal(date_cls.today().toordinal() - 1).isoformat()

        config = self._config()
        payload_holder = {"payload": self._payload(yesterday)}
        notifier = SimpleNamespace(sent=[])
        jobs_by_time, scheduler = self._start_service(config)
        self.assertEqual(set(jobs_by_time), {"15:10", "15:35"})

        with contextlib.ExitStack() as stack:
            for item in self._patches(payload_holder, notifier):
                stack.enter_context(item)

            # Primary 15:10 occurrence: previous-trading-day rankings (the
            # 15:30 cut has not happened) -> stale delivery, marker open.
            # The job dispatches on a background worker; join it before the
            # next occurrence (per-job-name guard).
            jobs_by_time["15:10"].job_func()
            scheduler._join_extra_daily_job_workers(timeout=30)
            self.assertEqual(len(notifier.sent), 1)

            # Data cut passes; the data-ready occurrence delivers today's
            # list through the same real service path.
            payload_holder["payload"] = self._payload(today)
            jobs_by_time["15:35"].job_func()
            scheduler._join_extra_daily_job_workers(timeout=30)
            self.assertEqual(len(notifier.sent), 2)

            marker = json.loads(
                hot_top10_marker_path(config).read_text(encoding="utf-8")
            )
            self.assertEqual(marker["run_date"], today)
            self.assertEqual(marker["data_date"], today)

    def test_fresh_primary_data_ready_slot_idles_without_second_push(self) -> None:
        import contextlib
        from datetime import date as date_cls

        today = date_cls.today().isoformat()

        config = self._config()
        payload_holder = {"payload": self._payload(today)}
        notifier = SimpleNamespace(sent=[])
        jobs_by_time, scheduler = self._start_service(config)

        with contextlib.ExitStack() as stack:
            for item in self._patches(payload_holder, notifier):
                stack.enter_context(item)

            jobs_by_time["15:10"].job_func()
            scheduler._join_extra_daily_job_workers(timeout=30)
            self.assertEqual(len(notifier.sent), 1)

            # Today's data was already delivered: the data-ready occurrence
            # skips via the daily marker (no duplicate push).
            jobs_by_time["15:35"].job_func()
            scheduler._join_extra_daily_job_workers(timeout=30)
            self.assertEqual(len(notifier.sent), 1)


class _AliveNoopThread(_NoopThread):
    """Loop-thread stub whose is_alive() reports True, mimicking a live
    scheduler loop for refresh-path checks."""

    def is_alive(self) -> bool:
        return True


class HotTop10ExtraJobRefreshTest(unittest.TestCase):
    """OR-COR-4b61e8f3: saving a hot-top10-only config change must refresh
    the auxiliary daily job registrations WITHOUT the full stop/start
    rebuild — stop() terminates the in-flight main analysis subprocess."""

    def _start(self, config: SimpleNamespace) -> RuntimeSchedulerService:
        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._reload_config = lambda: config
        with patch(
            "src.services.runtime_scheduler.threading.Thread",
            _AliveNoopThread,
        ):
            service.start()
        self.addCleanup(service.stop)
        return service

    @staticmethod
    def _config(**overrides) -> SimpleNamespace:
        base = dict(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
            hot_top10_enabled=True,
            hot_top10_schedule_time="15:10",
            hot_top10_data_ready_schedule_time="15:35",
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_refresh_preserves_running_analysis_and_live_scheduler(self) -> None:
        service = self._start(self._config())
        before_scheduler = service._scheduler
        before_thread = service._thread

        # Fabricate an in-flight main analysis subprocess, exactly what
        # stop() would terminate via _terminate_analysis_process_tree.
        fake_process = MagicMock()
        with service._analysis_process_lock:
            service._analysis_process = fake_process

        changed = service.refresh_extra_daily_jobs()

        self.assertTrue(changed)
        # No full rebuild: same scheduler instance, same loop thread, and
        # the running analysis process was NOT terminated.
        self.assertIs(service._scheduler, before_scheduler)
        self.assertIs(service._thread, before_thread)
        fake_process.terminate.assert_not_called()
        fake_process.kill.assert_not_called()
        # The two hot-top10 slots are still registered.
        extra_jobs = list(getattr(service._scheduler, "_extra_daily_jobs", []))
        self.assertEqual(len(extra_jobs), 2)

    def test_refresh_replaces_jobs_at_new_times(self) -> None:
        config = self._config()
        service = self._start(config)
        config.hot_top10_schedule_time = "15:20"
        config.hot_top10_data_ready_schedule_time = "16:05"

        changed = service.refresh_extra_daily_jobs()

        self.assertTrue(changed)
        extra_jobs = list(getattr(service._scheduler, "_extra_daily_jobs", []))
        self.assertEqual(len(extra_jobs), 2)
        at_times = {
            f"{job.at_time.hour:02d}:{job.at_time.minute:02d}"
            for job in extra_jobs
        }
        self.assertEqual(at_times, {"15:20", "16:05"})

    def test_refresh_unregisters_jobs_when_hot_top10_disabled(self) -> None:
        config = self._config()
        service = self._start(config)
        config.hot_top10_enabled = False

        changed = service.refresh_extra_daily_jobs()

        self.assertTrue(changed)
        self.assertEqual(
            list(getattr(service._scheduler, "_extra_daily_jobs", [])), []
        )

    def test_refresh_returns_false_without_live_scheduler(self) -> None:
        service = RuntimeSchedulerService(config_provider=lambda: self._config())

        self.assertFalse(service.refresh_extra_daily_jobs())


if __name__ == "__main__":
    unittest.main()
