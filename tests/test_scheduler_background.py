# -*- coding: utf-8 -*-
"""Tests for Scheduler background task support."""

from datetime import datetime
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


class _FakeJob:
    def __init__(self, schedule_module):
        self._schedule_module = schedule_module
        self.next_run = datetime(2026, 1, 1, 18, 0, 0)
        self.at_time = None

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
        return None

    def cancel_job(self, job):
        self.jobs.remove(job)


def _join_extra_job_workers(scheduler, timeout: float = 5.0) -> None:
    """Wait for in-flight extra daily job workers (no-op pre-mechanism)."""
    workers_map = getattr(scheduler, "_extra_job_workers", None)
    if not workers_map:
        return
    workers = [info["thread"] for info in list(workers_map.values())]
    for worker in workers:
        worker.join(timeout=timeout)


class SchedulerExtraDailyJobDispatchTest(unittest.TestCase):
    """OR-COR-f3a76b12: auxiliary daily jobs must not block the scheduler loop.

    The hot-top10 daily job (a single LLM call plus save and push) used to run
    synchronously inside the ``schedule`` loop thread, freezing every other
    job — and the main loop itself — for the whole run. The dispatch must hand
    the task to a controlled background worker with an in-flight guard (no
    duplicate start) and a stale-run timeout.
    """

    def _make_scheduler(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(
                schedule_time="18:00", register_signals=False
            )
        self.addCleanup(_join_extra_job_workers, scheduler)
        return scheduler, fake_schedule

    def test_extra_daily_job_dispatch_does_not_block_caller(self):
        scheduler, _ = self._make_scheduler()
        entered = threading.Event()
        release = threading.Event()

        def slow_task():
            entered.set()
            release.wait(timeout=6)

        self.assertTrue(
            scheduler.add_daily_task(slow_task, "15:10", name="hot_top10")
        )
        job_func = scheduler._extra_daily_jobs[0].job_func

        started = time.perf_counter()
        job_func()
        elapsed = time.perf_counter() - started

        self.assertTrue(entered.wait(timeout=5))
        # The wrapper returned while the task was still running in the
        # background: the scheduler loop is never blocked by the job body.
        self.assertLess(
            elapsed,
            4.0,
            "add_daily_task wrapper blocked the caller for %.1fs" % elapsed,
        )
        release.set()
        _join_extra_job_workers(scheduler)

    def test_in_flight_extra_daily_job_skips_duplicate_start(self):
        scheduler, _ = self._make_scheduler()
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def slow_task():
            calls.append(1)
            entered.set()
            release.wait(timeout=6)

        scheduler.add_daily_task(slow_task, "15:10", name="hot_top10")
        job_func = scheduler._extra_daily_jobs[0].job_func

        job_func()
        self.assertTrue(entered.wait(timeout=5))
        # Second occurrence fires while the first run is still in flight:
        # it must not start a duplicate execution.
        job_func()
        release.set()
        _join_extra_job_workers(scheduler)

        self.assertEqual(
            len(calls), 1, "duplicate start while previous run still in flight"
        )

    def test_stale_in_flight_job_allows_redispatch_after_timeout(self):
        scheduler, _ = self._make_scheduler()
        release = threading.Event()
        calls = []

        def hung_task():
            calls.append(1)
            release.wait(timeout=10)

        scheduler.add_daily_task(
            hung_task, "15:10", name="hot_top10", run_timeout_seconds=0.2
        )
        job_func = scheduler._extra_daily_jobs[0].job_func

        job_func()
        time.sleep(0.35)  # exceed the in-flight timeout window
        job_func()  # stale slot must be released so the new occurrence runs
        release.set()
        _join_extra_job_workers(scheduler)

        self.assertEqual(len(calls), 2, "stale in-flight slot was never released")

    def test_extra_daily_job_skips_dispatch_after_stop(self):
        scheduler, _ = self._make_scheduler()
        ran = threading.Event()

        scheduler.add_daily_task(lambda: ran.set(), "15:10", name="x")
        job_func = scheduler._extra_daily_jobs[0].job_func
        scheduler.stop()
        job_func()
        _join_extra_job_workers(scheduler)

        self.assertFalse(ran.is_set(), "auxiliary job dispatched after stop()")


class SchedulerBackgroundTaskTestCase(unittest.TestCase):
    def test_background_task_runs_when_interval_elapsed(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(schedule_time="18:00")
            calls = []
            fake_thread = MagicMock()
            fake_thread.is_alive.return_value = False

            def _make_thread(target=None, **kwargs):
                fake_thread.start.side_effect = target
                return fake_thread

            with patch("src.scheduler.threading.Thread", side_effect=_make_thread):
                scheduler.add_background_task(lambda: calls.append("ran"), interval_seconds=1, run_immediately=True, name="test")

        self.assertEqual(calls, ["ran"])

    def test_background_task_waits_for_interval(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(schedule_time="18:00")
            calls = []
            scheduler.add_background_task(lambda: calls.append("ran"), interval_seconds=60, run_immediately=False, name="test")

            with patch("src.scheduler.time.time", return_value=scheduler._background_tasks[0]["last_run"] + 10):
                scheduler._run_background_tasks()

        self.assertEqual(calls, [])

    def test_run_with_schedule_registers_background_tasks_before_immediate_daily_task(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src import scheduler as scheduler_module

            order = []

            class FakeScheduler:
                def __init__(self, schedule_time="18:00", schedule_time_provider=None):
                    order.append(("init", schedule_time))
                    order.append(("provider", callable(schedule_time_provider)))

                def add_background_task(self, **kwargs):
                    order.append(("background", kwargs["name"]))

                def set_daily_task(self, task, run_immediately=True):
                    order.append(("daily", run_immediately))

                def run(self):
                    order.append(("run", None))

            with patch.object(scheduler_module, "Scheduler", FakeScheduler):
                scheduler_module.run_with_schedule(
                    task=lambda: None,
                    run_immediately=True,
                    background_tasks=[{
                        "task": lambda: None,
                        "interval_seconds": 60,
                        "run_immediately": True,
                        "name": "event_monitor",
                    }],
                )

        self.assertEqual(order[:4], [("init", "18:00"), ("provider", False), ("background", "event_monitor"), ("daily", True)])

    def test_scheduler_reloads_daily_job_when_schedule_time_changes(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(
                schedule_time="18:00",
                schedule_time_provider=lambda: "09:30",
            )
            scheduler.set_daily_task(lambda: None, run_immediately=False)

            self.assertEqual(len(fake_schedule.jobs), 1)
            self.assertEqual(fake_schedule.jobs[0].at_time, "18:00")

            scheduler._refresh_daily_schedule_if_needed()

        self.assertEqual(len(fake_schedule.jobs), 1)
        self.assertEqual(fake_schedule.jobs[0].at_time, "09:30")
        self.assertEqual(scheduler.schedule_time, "09:30")

    def test_scheduler_registers_multiple_daily_jobs(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(
                schedule_time="18:00",
                schedule_times=["15:10", "09:20", "15:10"],
            )
            scheduler.set_daily_task(lambda: None, run_immediately=False)

        self.assertEqual([job.at_time for job in fake_schedule.jobs], ["09:20", "15:10"])
        self.assertEqual(scheduler.schedule_times, ["09:20", "15:10"])

    def test_scheduler_stop_cancels_registered_daily_jobs(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(
                schedule_time="18:00",
                schedule_times=["09:20", "15:10"],
            )
            scheduler.set_daily_task(lambda: None, run_immediately=False)
            self.assertEqual(len(fake_schedule.jobs), 2)

            scheduler.stop()

        self.assertEqual(fake_schedule.jobs, [])
        self.assertEqual(scheduler._daily_jobs, [])
        self.assertIsNone(scheduler._daily_job)

    def test_stop_during_pending_jobs_prevents_new_background_dispatch(self):
        fake_schedule = _FakeScheduleModule()
        pending_jobs_entered = threading.Event()
        release_pending_jobs = threading.Event()
        background_started = threading.Event()

        def run_pending():
            pending_jobs_entered.set()
            release_pending_jobs.wait(timeout=1)

        fake_schedule.run_pending = run_pending
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(schedule_time="18:00")
            with patch("src.scheduler.time.time", return_value=0):
                scheduler.add_background_task(
                    background_started.set,
                    interval_seconds=30,
                    run_immediately=False,
                    name="test",
                )

            with patch("src.scheduler.time.time", return_value=30), patch(
                "src.scheduler.time.sleep",
                return_value=None,
            ):
                scheduler_thread = threading.Thread(target=scheduler.run, daemon=True)
                scheduler_thread.start()
                self.assertTrue(pending_jobs_entered.wait(timeout=1))

                scheduler.stop()
                release_pending_jobs.set()
                scheduler_thread.join(timeout=1)

        self.assertFalse(scheduler_thread.is_alive())
        self.assertFalse(background_started.wait(timeout=0.1))

    def test_stop_before_run_enters_prevents_scheduler_restart(self):
        fake_schedule = _FakeScheduleModule()
        background_started = threading.Event()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(schedule_time="18:00")
            with patch("src.scheduler.time.time", return_value=0):
                scheduler.add_background_task(
                    background_started.set,
                    interval_seconds=30,
                    run_immediately=False,
                    name="test",
                )

            scheduler.stop()

            def stop_after_pending_jobs():
                scheduler.shutdown_handler.shutdown_requested = True

            fake_schedule.run_pending = stop_after_pending_jobs
            with patch("src.scheduler.time.time", return_value=30), patch(
                "src.scheduler.time.sleep",
                return_value=None,
            ):
                scheduler_thread = threading.Thread(target=scheduler.run, daemon=True)
                scheduler_thread.start()
                scheduler_thread.join(timeout=1)

        self.assertFalse(scheduler_thread.is_alive())
        self.assertFalse(background_started.wait(timeout=0.1))

    def test_shutdown_during_pending_jobs_prevents_new_background_dispatch(self):
        fake_schedule = _FakeScheduleModule()
        pending_jobs_entered = threading.Event()
        release_pending_jobs = threading.Event()
        background_started = threading.Event()

        def run_pending():
            pending_jobs_entered.set()
            release_pending_jobs.wait(timeout=1)

        fake_schedule.run_pending = run_pending
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(schedule_time="18:00", register_signals=False)
            with patch("src.scheduler.time.time", return_value=0):
                scheduler.add_background_task(
                    background_started.set,
                    interval_seconds=30,
                    run_immediately=False,
                    name="test",
                )

            with patch("src.scheduler.time.time", return_value=30), patch(
                "src.scheduler.time.sleep",
                return_value=None,
            ):
                scheduler_thread = threading.Thread(target=scheduler.run, daemon=True)
                scheduler_thread.start()
                self.assertTrue(pending_jobs_entered.wait(timeout=1))

                scheduler.shutdown_handler.shutdown_requested = True
                release_pending_jobs.set()
                scheduler_thread.join(timeout=1)

        self.assertFalse(scheduler_thread.is_alive())
        self.assertFalse(background_started.wait(timeout=0.1))

    def test_scheduler_keeps_existing_daily_job_when_schedule_time_invalid(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(
                schedule_time="18:00",
                schedule_time_provider=lambda: "25:99",
            )
            scheduler.set_daily_task(lambda: None, run_immediately=False)

            scheduler._refresh_daily_schedule_if_needed()

        self.assertEqual(len(fake_schedule.jobs), 1)
        self.assertEqual(fake_schedule.jobs[0].at_time, "18:00")
        self.assertEqual(scheduler.schedule_time, "18:00")

    def test_scheduler_keeps_current_daily_job_when_schedule_time_provider_fails(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            provider_calls = {"count": 0}

            def provider():
                provider_calls["count"] += 1
                if provider_calls["count"] == 1:
                    return "09:30"
                raise RuntimeError("boom")

            scheduler = Scheduler(
                schedule_time="18:00",
                schedule_time_provider=provider,
            )
            scheduler.set_daily_task(lambda: None, run_immediately=False)

            scheduler._refresh_daily_schedule_if_needed()
            scheduler._refresh_daily_schedule_if_needed()

        self.assertEqual(len(fake_schedule.jobs), 1)
        self.assertEqual(fake_schedule.jobs[0].at_time, "09:30")
        self.assertEqual(scheduler.schedule_time, "09:30")

    def test_scheduler_rejects_invalid_initial_schedule_time(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(schedule_time="25:99")
            calls = []

            with self.assertRaisesRegex(ValueError, "25:99"):
                scheduler.set_daily_task(lambda: calls.append("ran"), run_immediately=True)

        self.assertEqual(calls, [])
        self.assertEqual(fake_schedule.jobs, [])


if __name__ == "__main__":
    unittest.main()
