# -*- coding: utf-8 -*-
"""Regression tests for RuntimeSchedulerService scheduling ownership."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.services.runtime_scheduler import (
    CLI_SCHEDULER_OWNER_ENV,
    RUNTIME_SCHEDULER_ARGS_ENV,
    RUNTIME_SCHEDULER_FORCE_ENABLED_ENV,
    RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV,
    RUNTIME_SCHEDULER_SUPPRESS_START_ENV,
    RuntimeSchedulerService,
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


class RuntimeSchedulerServiceTestCase(unittest.TestCase):
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
        seen_stock_codes = []

        def runner(config_arg, args, stock_codes):
            seen_stock_codes.append(stock_codes)
            return True

        service = RuntimeSchedulerService(
            config_provider=lambda: config,
            task_runner=runner,
        )
        service._reload_config = lambda: config

        with patch(
            "src.services.runtime_scheduler.threading.Thread",
            _SynchronousThread,
        ):
            result = service.run_now()

        self.assertTrue(result["accepted"])
        self.assertEqual(seen_stock_codes, [None])
        status = service.status()
        self.assertFalse(status["running"])
        self.assertIsNotNone(status["last_run_at"])
        self.assertIsNotNone(status["last_success_at"])
        self.assertIsNone(status["last_error"])

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

        with patch.dict(sys.modules, {"schedule": fake_schedule}), patch(
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

        with patch.dict(sys.modules, {"schedule": fake_schedule}), patch(
            "src.services.runtime_scheduler.threading.Thread",
            _NoopThread,
        ):
            service.reconcile_from_config(run_immediately=True)
            config.schedule_times = ["15:10"]
            service.reconcile_from_config()

        self.assertEqual(calls, ["run"])

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


if __name__ == "__main__":
    unittest.main()
