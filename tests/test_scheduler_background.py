# -*- coding: utf-8 -*-
"""Tests for Scheduler background task support."""

from datetime import datetime
import gc
import os
import signal
import socket
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import weakref


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

    def test_stop_wakes_sleeping_scheduler_immediately(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(schedule_time="18:00", register_signals=False)
            entered_wait = threading.Event()
            real_wait = scheduler._wait_for_stop

            def tracked_wait(timeout=30.0):
                entered_wait.set()
                return real_wait(timeout=timeout)

            scheduler._wait_for_stop = tracked_wait
            scheduler_thread = threading.Thread(target=scheduler.run, daemon=True)
            started_at = time.monotonic()
            scheduler_thread.start()
            self.assertTrue(entered_wait.wait(timeout=1.0))

            scheduler.stop()
            scheduler_thread.join(timeout=1.0)
            elapsed = time.monotonic() - started_at

        self.assertFalse(scheduler_thread.is_alive())
        self.assertLess(elapsed, 2.0)

    def test_signal_handler_wakes_sleeping_scheduler_immediately(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(schedule_time="18:00", register_signals=False)
            entered_wait = threading.Event()
            real_wait = scheduler._wait_for_stop

            def tracked_wait(timeout=30.0):
                entered_wait.set()
                return real_wait(timeout=timeout)

            scheduler._wait_for_stop = tracked_wait
            scheduler_thread = threading.Thread(target=scheduler.run, daemon=True)
            started_at = time.monotonic()
            scheduler_thread.start()
            self.assertTrue(entered_wait.wait(timeout=1.0))

            scheduler.shutdown_handler._signal_handler(signal.SIGTERM, None)
            scheduler_thread.join(timeout=1.0)
            elapsed = time.monotonic() - started_at

        self.assertFalse(scheduler_thread.is_alive())
        self.assertLess(elapsed, 2.0)

    @unittest.skipIf(os.name == "nt", "POSIX signal delivery test")
    def test_main_thread_sigterm_exits_wait_without_deadlock(self):
        fake_schedule = _FakeScheduleModule()
        prev_sigint = signal.getsignal(signal.SIGINT)
        prev_sigterm = signal.getsignal(signal.SIGTERM)
        sender_thread = None
        try:
            with patch.dict(sys.modules, {"schedule": fake_schedule}):
                from src.scheduler import Scheduler

                scheduler = Scheduler(schedule_time="23:59", register_signals=True)
                try:
                    scheduler.set_daily_task(lambda: None, run_immediately=False)
                    real_wait = scheduler._wait_for_stop
                    pid = os.getpid()

                    def wait_then_send_sigterm(timeout=30.0):
                        nonlocal sender_thread

                        def _send_signal() -> None:
                            time.sleep(0.05)
                            os.kill(pid, signal.SIGTERM)

                        sender_thread = threading.Thread(target=_send_signal, daemon=True)
                        sender_thread.start()
                        return real_wait(timeout=timeout)

                    scheduler._wait_for_stop = wait_then_send_sigterm
                    started_at = time.monotonic()
                    scheduler.run()
                    elapsed = time.monotonic() - started_at
                finally:
                    scheduler.close()
        finally:
            if sender_thread is not None:
                sender_thread.join(timeout=1.0)
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)

        self.assertTrue(scheduler.shutdown_handler.should_shutdown)
        self.assertEqual(scheduler.shutdown_handler.shutdown_signal, signal.SIGTERM)
        self.assertLess(elapsed, 2.0)

    def test_refresh_invalid_runtime_times_preserves_multi_time_schedule(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            responses = iter(["09:30,25:99", "bad", ""])
            scheduler = Scheduler(
                schedule_time="18:00",
                schedule_times=["09:30", "18:00"],
                schedule_times_provider=lambda: next(responses),
                register_signals=False,
            )
            scheduler.set_daily_task(lambda: None, run_immediately=False)

            with self.assertLogs("src.scheduler", level="WARNING"):
                scheduler._refresh_daily_schedule_if_needed()
                scheduler._refresh_daily_schedule_if_needed()
            scheduler._refresh_daily_schedule_if_needed()

        self.assertEqual(scheduler.schedule_times, ["09:30", "18:00"])
        self.assertEqual([job.at_time for job in fake_schedule.jobs], ["09:30", "18:00"])

    def test_scheduler_uses_isolated_schedule_instances(self):
        import schedule
        from src.scheduler import Scheduler

        global_jobs_before = len(schedule.get_jobs())
        scheduler_a = Scheduler(schedule_time="09:30", register_signals=False)
        scheduler_b = Scheduler(schedule_time="15:00", register_signals=False)
        try:
            scheduler_a.set_daily_task(lambda: None, run_immediately=False)
            scheduler_b.set_daily_task(lambda: None, run_immediately=False)

            self.assertIsNot(scheduler_a.schedule, scheduler_b.schedule)
            self.assertEqual(len(scheduler_a.schedule.get_jobs()), 1)
            self.assertEqual(len(scheduler_b.schedule.get_jobs()), 1)
            self.assertEqual(len(schedule.get_jobs()), global_jobs_before)

            scheduler_a.stop()
            self.assertEqual(len(scheduler_a.schedule.get_jobs()), 0)
            self.assertEqual(len(scheduler_b.schedule.get_jobs()), 1)
        finally:
            scheduler_a.close()
            scheduler_b.close()

    def test_get_next_run_time_ignores_jobs_without_next_run(self):
        fake_schedule = _FakeScheduleModule()
        with patch.dict(sys.modules, {"schedule": fake_schedule}):
            from src.scheduler import Scheduler

            scheduler = Scheduler(schedule_time="18:00", register_signals=False)
            try:
                job_without_next_run = _FakeJob(fake_schedule)
                job_without_next_run.next_run = None
                fake_schedule.jobs.append(job_without_next_run)

                self.assertEqual(scheduler._get_next_run_time(), "not set")
            finally:
                scheduler.close()

    def test_wakeup_channel_high_fd_uses_poll_without_busy_spin(self):
        try:
            import resource
        except ImportError:
            self.skipTest("POSIX resource module required")

        from src.scheduler import _WakeupChannel

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        raised_limit = False
        if soft < 1200 and hard >= 1200:
            resource.setrlimit(resource.RLIMIT_NOFILE, (1200, hard))
            raised_limit = True

        channel = _WakeupChannel()
        high_r_fd = None
        try:
            if channel._mode != "pipe" or channel._r_fd is None or not hasattr(fcntl := __import__("fcntl"), "F_DUPFD"):
                self.skipTest("POSIX pipe + F_DUPFD required")
            # Duplicate the read FD above FD_SETSIZE (1024) where select.select would raise ValueError.
            try:
                high_r_fd = fcntl.fcntl(channel._r_fd, fcntl.F_DUPFD, 1050)
            except OSError:
                self.skipTest("FD limit below 1050 in test environment")

            os.set_blocking(high_r_fd, False)
            old_r_fd = channel._r_fd
            channel._r_fd = high_r_fd
            os.close(old_r_fd)

            with patch("src.scheduler.select.select", side_effect=AssertionError("select.select must not be used")):
                start = time.monotonic()
                signaled = channel.wait(timeout=0.08)
                elapsed = time.monotonic() - start
                self.assertFalse(signaled)
                self.assertGreaterEqual(elapsed, 0.05)

                notifier = threading.Timer(0.02, channel.notify)
                notifier.start()
                try:
                    start = time.monotonic()
                    woken = channel.wait(timeout=1.0)
                    woke_elapsed = time.monotonic() - start
                finally:
                    notifier.join(timeout=1.0)

                self.assertTrue(woken)
                self.assertLess(woke_elapsed, 0.5)
        finally:
            channel.close()
            if raised_limit:
                resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))

    def test_wakeup_channel_windows_socketpair_slices_wait_for_sigint_wakeup(self):
        from src.scheduler import _WakeupChannel

        r_sock, w_sock = socket.socketpair()
        r_sock.setblocking(False)
        w_sock.setblocking(False)
        channel = _WakeupChannel.__new__(_WakeupChannel)
        channel._signaled = False
        channel._closed = False
        channel._mode = "socketpair"
        channel._r_fd = None
        channel._w_fd = None
        channel._r_sock = r_sock
        channel._w_sock = w_sock

        recorded_timeouts = []

        def fake_select(rlist, wlist, xlist, timeout):
            recorded_timeouts.append(timeout)
            channel._signaled = True
            return ([], [], [])

        try:
            with patch("src.scheduler.os.name", "nt"), patch("src.scheduler.select.select", side_effect=fake_select):
                result = channel.wait(timeout=30.0)
            self.assertTrue(result)
            self.assertEqual(recorded_timeouts, [0.25])
        finally:
            channel.close()

    def test_wakeup_channel_high_fd_socketpair_fallback_uses_poll_without_busy_spin(self):
        """OR-COR-076f0d13: POSIX socketpair fallback with FD >= 1024 must use poll() without spinning."""
        try:
            import fcntl
            import resource
        except ImportError:
            self.skipTest("POSIX fcntl and resource modules required")

        from src.scheduler import _WakeupChannel

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        raised_limit = False
        if soft < 1200 and hard >= 1200:
            resource.setrlimit(resource.RLIMIT_NOFILE, (1200, hard))
            raised_limit = True

        channel = None
        try:
            with patch("src.scheduler.os.pipe", side_effect=OSError("ENFILE")):
                channel = _WakeupChannel()

            if channel._mode != "socketpair" or channel._r_sock is None or not hasattr(fcntl, "F_DUPFD"):
                self.skipTest("POSIX socketpair fallback + F_DUPFD required")

            orig_r_sock = channel._r_sock
            try:
                high_r_fd = fcntl.fcntl(orig_r_sock.fileno(), fcntl.F_DUPFD, 1050)
            except OSError:
                self.skipTest("FD limit below 1050 in test environment")

            try:
                high_r_sock = socket.socket(
                    orig_r_sock.family,
                    orig_r_sock.type,
                    orig_r_sock.proto,
                    fileno=high_r_fd,
                )
            except Exception:
                os.close(high_r_fd)
                raise

            high_r_sock.setblocking(False)
            channel._r_sock = high_r_sock
            orig_r_sock.close()
            self.assertGreaterEqual(high_r_sock.fileno(), 1024)

            with patch("src.scheduler.select.select", side_effect=AssertionError("select.select must not be used")):
                start = time.monotonic()
                signaled = channel.wait(timeout=0.08)
                elapsed = time.monotonic() - start
                self.assertFalse(signaled)
                self.assertGreaterEqual(elapsed, 0.05)

                notifier = threading.Timer(0.02, channel.notify)
                notifier.start()
                try:
                    start = time.monotonic()
                    woken = channel.wait(timeout=1.0)
                    woke_elapsed = time.monotonic() - start
                finally:
                    notifier.join(timeout=1.0)

                self.assertTrue(woken)
                self.assertLess(woke_elapsed, 0.5)
        finally:
            if channel is not None:
                channel.close()
            if raised_limit:
                resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))

    def test_wakeup_channel_socketpair_poll_dispatch_and_select_value_error_backoff(self):
        """OR-COR-076f0d13: socketpair uses poll() on POSIX and backs off instead of spinning on select() ValueError."""
        from src.scheduler import _WakeupChannel

        registered = []
        poll_timeouts = []

        class _FakePoller:
            def register(self, fd, eventmask):
                registered.append((fd, eventmask))

            def poll(self, timeout_ms):
                poll_timeouts.append(timeout_ms)
                channel._signaled = True
                return [(channel._r_sock, 1)]

        class _FakePosixSelect:
            POLLIN = 1
            POLLERR = 8
            POLLHUP = 16
            POLLNVAL = 32

            @staticmethod
            def poll():
                return _FakePoller()

            @staticmethod
            def select(*args, **kwargs):
                raise AssertionError("select.select must not be used when POSIX poll() is available")

        with patch("src.scheduler.os.name", "posix"), patch(
            "src.scheduler.os.pipe",
            side_effect=OSError("ENFILE"),
        ):
            channel = _WakeupChannel()

        try:
            self.assertEqual(channel._mode, "socketpair")
            self.assertIsNotNone(channel._r_sock)
            with patch("src.scheduler.os.name", "posix"), patch("src.scheduler.select", _FakePosixSelect):
                result = channel.wait(timeout=1.5)
            self.assertTrue(result)
            self.assertEqual(registered, [(channel._r_sock, _FakePosixSelect.POLLIN)])
            self.assertEqual(len(poll_timeouts), 1)
            self.assertGreater(poll_timeouts[0], 0)

            # When select.poll() is unavailable and select.select() raises ValueError on an open socket
            # (e.g. FD >= FD_SETSIZE), wait() must sleep instead of returning immediately and spinning.
            channel._signaled = False

            class _FakeSelectOnly:
                @staticmethod
                def select(*args, **kwargs):
                    raise ValueError("file descriptor out of range in select()")

            with patch("src.scheduler.select", _FakeSelectOnly):
                start = time.monotonic()
                signaled = channel.wait(timeout=0.08)
                elapsed = time.monotonic() - start
            self.assertFalse(signaled)
            self.assertGreaterEqual(elapsed, 0.05)

            # Once closed, wait() must return immediately rather than sleeping.
            channel.close()
            with patch("src.scheduler.select", _FakeSelectOnly):
                start = time.monotonic()
                signaled = channel.wait(timeout=1.0)
                elapsed = time.monotonic() - start
            self.assertFalse(signaled)
            self.assertLess(elapsed, 0.1)
        finally:
            channel.close()

    def test_pthread_kill_sigterm_wakes_scheduler_via_wakeup_fd(self):
        if os.name == "nt" or not hasattr(signal, "pthread_kill"):
            self.skipTest("POSIX signal.pthread_kill required")
        if threading.current_thread() is not threading.main_thread():
            self.skipTest("Main thread required for signal.set_wakeup_fd")

        fake_schedule = _FakeScheduleModule()
        prev_sigint = signal.getsignal(signal.SIGINT)
        prev_sigterm = signal.getsignal(signal.SIGTERM)
        sender_thread = None
        try:
            with patch.dict(sys.modules, {"schedule": fake_schedule}):
                from src.scheduler import Scheduler

                scheduler = Scheduler(schedule_time="18:00", register_signals=True)
                try:
                    scheduler.set_daily_task(lambda: None, run_immediately=False)
                    orig_wait = scheduler._wait_for_stop

                    def _send_thread_sigterm_during_wait(timeout=30.0):
                        nonlocal sender_thread
                        if sender_thread is None:
                            target_ident = threading.main_thread().ident

                            def _send():
                                time.sleep(0.05)
                                signal.pthread_kill(target_ident, signal.SIGTERM)

                            sender_thread = threading.Thread(target=_send, daemon=True)
                            sender_thread.start()
                        return orig_wait(timeout=2.0)

                    scheduler._wait_for_stop = _send_thread_sigterm_during_wait
                    started_at = time.monotonic()
                    scheduler.run()
                    elapsed = time.monotonic() - started_at
                finally:
                    scheduler.close()
        finally:
            if sender_thread is not None:
                sender_thread.join(timeout=1.0)
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)

        self.assertTrue(scheduler.shutdown_handler.should_shutdown)
        self.assertEqual(scheduler.shutdown_handler.shutdown_signal, signal.SIGTERM)
        self.assertLess(elapsed, 0.5)
        self.assertEqual(signal.set_wakeup_fd(-1), -1)

    def test_scheduler_preserves_existing_signal_wakeup_fd(self):
        if os.name == "nt" or not hasattr(os, "pipe") or not hasattr(signal, "set_wakeup_fd"):
            self.skipTest("POSIX pipe + signal.set_wakeup_fd required")
        if threading.current_thread() is not threading.main_thread():
            self.skipTest("Main thread required for signal.set_wakeup_fd")

        r_fd, w_fd = os.pipe()
        os.set_blocking(r_fd, False)
        os.set_blocking(w_fd, False)
        prev_sigint = signal.getsignal(signal.SIGINT)
        prev_sigterm = signal.getsignal(signal.SIGTERM)
        prior_fd = signal.set_wakeup_fd(w_fd, warn_on_full_buffer=False)
        scheduler = None
        try:
            fake_schedule = _FakeScheduleModule()
            with patch.dict(sys.modules, {"schedule": fake_schedule}):
                from src.scheduler import Scheduler

                scheduler = Scheduler(schedule_time="18:00", register_signals=True)
                self.assertFalse(scheduler.shutdown_handler.install_wakeup_fd(scheduler._wakeup.fileno()))
                current_fd = signal.set_wakeup_fd(w_fd, warn_on_full_buffer=False)
                self.assertEqual(current_fd, w_fd)
                self.assertIsNone(scheduler.shutdown_handler._installed_wakeup_fd)
                scheduler.close()
                after_close_fd = signal.set_wakeup_fd(-1)
                self.assertEqual(after_close_fd, w_fd)
        finally:
            if scheduler is not None:
                scheduler.close()
            signal.set_wakeup_fd(prior_fd if prior_fd != -1 else -1)
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)
            for fd in (r_fd, w_fd):
                try:
                    os.close(fd)
                except OSError:
                    pass

    def test_worker_thread_run_and_drop_without_close_closes_wakeup_and_leaves_no_fd(self):
        """OR-COR-173ecd3e: worker-thread scheduler drop without close() must not leak FDs or leave wakeup_fd set."""
        if not hasattr(signal, "set_wakeup_fd"):
            self.skipTest("signal.set_wakeup_fd required")
        if threading.current_thread() is not threading.main_thread():
            self.skipTest("Main thread required for signal.set_wakeup_fd")

        prev_sigint = signal.getsignal(signal.SIGINT)
        prev_sigterm = signal.getsignal(signal.SIGTERM)
        # Isolate from earlier Scheduler tests that construct Scheduler() without close().
        prior_fd = signal.set_wakeup_fd(-1)
        try:
            for force_socketpair in (False, True):
                fake_schedule = _FakeScheduleModule()
                pipe_ctx = (
                    patch.object(os, "pipe", side_effect=OSError)
                    if force_socketpair
                    else patch.dict(sys.modules, {"schedule": fake_schedule})
                )
                with patch.dict(sys.modules, {"schedule": fake_schedule}), pipe_ctx:
                    from src.scheduler import Scheduler

                    scheduler = Scheduler(schedule_time="23:59", register_signals=True)
                    expected_mode = "socketpair" if force_socketpair else "pipe"
                    if os.name == "nt":
                        expected_mode = "socketpair"
                    if scheduler._wakeup._mode != expected_mode:
                        scheduler.close()
                        self.skipTest(f"Wakeup mode {expected_mode} unavailable")

                    mode = scheduler._wakeup._mode
                    r_sock = scheduler._wakeup._r_sock
                    w_sock = scheduler._wakeup._w_sock
                    pipe_fds = (scheduler._wakeup._r_fd, scheduler._wakeup._w_fd)
                    wakeup_fd = scheduler._wakeup.fileno()
                    try:
                        self.assertIsNotNone(wakeup_fd)
                        if mode == "socketpair":
                            self.assertIsNotNone(r_sock)
                            self.assertIsNotNone(w_sock)
                            self.assertNotEqual(r_sock.fileno(), -1)
                            self.assertNotEqual(w_sock.fileno(), -1)
                        self.assertIsNone(scheduler.shutdown_handler._installed_wakeup_fd)
                        self.assertEqual(signal.set_wakeup_fd(-1), -1)

                        ref = weakref.ref(scheduler)
                        scheduler.set_daily_task(lambda: None, run_immediately=False)
                        worker = threading.Thread(target=scheduler.run, daemon=True)
                        worker.start()
                        time.sleep(0.05)
                        scheduler.stop()
                        # Drop the last main-thread reference without calling close().
                        del scheduler
                        worker.join(timeout=2.0)
                        self.assertFalse(worker.is_alive())
                        del worker
                        gc.collect()

                        self.assertIsNone(ref())
                        self.assertEqual(signal.set_wakeup_fd(-1), -1)
                        if mode == "socketpair":
                            self.assertEqual(r_sock.fileno(), -1)
                            self.assertEqual(w_sock.fileno(), -1)
                        else:
                            for fd in pipe_fds:
                                self.assertIsNotNone(fd)
                                with self.assertRaises(OSError):
                                    os.fstat(fd)
                        if os.name != "nt":
                            with self.assertRaises(OSError):
                                os.fstat(wakeup_fd)
                    finally:
                        for sock in (r_sock, w_sock):
                            if sock is not None:
                                sock.close()
        finally:
            signal.set_wakeup_fd(prior_fd if prior_fd != -1 else -1)
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)

    def test_module_imports_without_posix_resource_module(self):
        with patch.dict(sys.modules, {"resource": None}):
            import importlib.util

            spec = importlib.util.spec_from_file_location("_test_scheduler_bg_no_resource", __file__)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, "SchedulerBackgroundTaskTestCase"))


if __name__ == "__main__":
    unittest.main()
