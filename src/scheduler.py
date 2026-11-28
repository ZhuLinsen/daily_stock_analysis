# -*- coding: utf-8 -*-
"""
===================================
定时调度模块
===================================

职责：
1. 支持每日定时执行股票分析
2. 支持定时执行大盘复盘
3. 优雅处理信号，确保可靠退出

依赖：
- schedule: 轻量级定时任务库
"""

import logging
import math
import os
import re
import select
import signal
import socket
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

logger = logging.getLogger(__name__)


def normalize_schedule_times(
    schedule_times: Optional[Union[Sequence[str], str]],
    *,
    fallback_time: str = "18:00",
) -> List[str]:
    """Return sorted unique HH:MM schedule times with SCHEDULE_TIME fallback."""
    if isinstance(schedule_times, str):
        raw_items = [item.strip() for item in schedule_times.split(",")]
    elif schedule_times is None:
        raw_items = []
    else:
        raw_items = [str(item).strip() for item in schedule_times]

    valid = {
        item
        for item in raw_items
        if item and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", item)
    }
    if not valid:
        fallback = (fallback_time or "18:00").strip() or "18:00"
        valid.add(fallback if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", fallback) else "18:00")
    return sorted(valid)


class _WakeupChannel:
    """Async-signal-safe wakeup pipe/socketpair for waiting without lock reentrancy."""

    def __init__(self) -> None:
        self._signaled = False
        self._closed = False
        self._mode = "poll"
        self._r_fd: Optional[int] = None
        self._w_fd: Optional[int] = None
        self._r_sock: Optional[socket.socket] = None
        self._w_sock: Optional[socket.socket] = None

        if os.name != "nt" and hasattr(os, "pipe"):
            try:
                self._r_fd, self._w_fd = os.pipe()
                os.set_blocking(self._r_fd, False)
                os.set_blocking(self._w_fd, False)
                self._mode = "pipe"
                return
            except OSError:
                self._close_pipe_fds()

        if hasattr(socket, "socketpair"):
            try:
                self._r_sock, self._w_sock = socket.socketpair()
                self._r_sock.setblocking(False)
                self._w_sock.setblocking(False)
                self._mode = "socketpair"
            except OSError:
                self._close_sockets()

    def _close_pipe_fds(self) -> None:
        r_fd, self._r_fd = self._r_fd, None
        w_fd, self._w_fd = self._w_fd, None
        for fd in (r_fd, w_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _close_sockets(self) -> None:
        r_sock, self._r_sock = self._r_sock, None
        w_sock, self._w_sock = self._w_sock, None
        for sock in (r_sock, w_sock):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def notify(self) -> None:
        """Wake any sleeper without acquiring locks (safe inside signal handlers)."""
        self._signaled = True
        if self._closed:
            return
        if self._mode == "pipe":
            w_fd = self._w_fd
            if w_fd is not None:
                try:
                    os.write(w_fd, b"\x01")
                except (BlockingIOError, InterruptedError, OSError):
                    pass
        elif self._mode == "socketpair":
            w_sock = self._w_sock
            if w_sock is not None:
                try:
                    w_sock.send(b"\x01")
                except (BlockingIOError, InterruptedError, OSError):
                    pass

    @staticmethod
    def _drain_pipe(r_fd: int) -> None:
        try:
            os.read(r_fd, 64)
        except (BlockingIOError, InterruptedError, OSError):
            pass

    @staticmethod
    def _drain_socket(r_sock: socket.socket) -> None:
        try:
            r_sock.recv(64)
        except (BlockingIOError, InterruptedError, OSError):
            pass

    @staticmethod
    def _is_closed_target(target: Union[int, socket.socket]) -> bool:
        if isinstance(target, int):
            return target < 0
        try:
            return target.fileno() < 0
        except OSError:
            return True

    def _wait_readable_once(
        self,
        target: Union[int, socket.socket],
        wait_slice: float,
        drain: Callable[[], None],
    ) -> bool:
        """Wait for descriptor readability without select()'s 1024 FD cap on POSIX.

        Returns False only when the descriptor is closed/invalid so wait() can
        abort when closed or fall back to bounded sleep instead of spinning.
        """
        if os.name != "nt" and hasattr(select, "poll"):
            poller = select.poll()
            try:
                poller.register(target, select.POLLIN)
            except ValueError:
                return False
            timeout_ms = max(1, int(math.ceil(wait_slice * 1000)))
            events = poller.poll(timeout_ms)
            poll_abort_mask = select.POLLERR | select.POLLNVAL | getattr(select, "POLLHUP", 0)
            for _, event in events:
                if event & select.POLLIN:
                    drain()
                if event & poll_abort_mask:
                    return False
            return True

        try:
            readable, _, _ = select.select([target], [], [], wait_slice)
        except ValueError:
            if self._closed or self._is_closed_target(target):
                return False
            # Fallback when select() cannot handle FDs >= FD_SETSIZE on platforms without poll().
            time.sleep(min(0.1, wait_slice))
            return True
        if readable:
            drain()
        return True

    def wait(self, timeout: float = 30.0) -> bool:
        """Block until signaled or timeout expires."""
        if self._signaled:
            return True
        deadline = time.monotonic() + max(0.0, float(timeout))
        while not self._signaled:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self._closed:
                return self._signaled
            if self._mode == "pipe":
                r_fd = self._r_fd
                if r_fd is None:
                    return self._signaled
                try:
                    ok = self._wait_readable_once(
                        r_fd,
                        remaining,
                        lambda: self._drain_pipe(r_fd),
                    )
                except InterruptedError:
                    continue
                except OSError:
                    ok = False
                if not ok:
                    if self._closed or self._signaled:
                        return self._signaled
                    time.sleep(min(0.1, remaining))
            elif self._mode == "socketpair":
                r_sock = self._r_sock
                if r_sock is None:
                    return self._signaled
                # On Windows, console Ctrl+C runs Python handlers only between C waits,
                # so bound socketpair waits to 0.25s while stop() still wakes immediately.
                wait_slice = min(0.25, remaining) if os.name == "nt" else remaining
                try:
                    ok = self._wait_readable_once(
                        r_sock,
                        wait_slice,
                        lambda: self._drain_socket(r_sock),
                    )
                except InterruptedError:
                    continue
                except OSError:
                    ok = False
                if not ok:
                    if self._closed or self._signaled:
                        return self._signaled
                    time.sleep(min(0.1, wait_slice))
            else:
                time.sleep(min(0.1, remaining))
        return self._signaled

    def close(self) -> None:
        """Release wakeup descriptors."""
        self._closed = True
        self._close_pipe_fds()
        self._close_sockets()

    def fileno(self) -> Optional[int]:
        """Return writable descriptor usable with signal.set_wakeup_fd(), if any."""
        if self._closed:
            return None
        if self._mode == "pipe":
            return self._w_fd
        if self._mode == "socketpair" and self._w_sock is not None:
            try:
                return self._w_sock.fileno()
            except OSError:
                return None
        return None


class GracefulShutdown:
    """
    优雅退出处理器

    捕获 SIGTERM/SIGINT 信号，确保任务完成后再退出
    """

    def __init__(
        self,
        register_signals: bool = True,
        on_shutdown: Optional[Callable[[], None]] = None,
        wakeup_fd: Optional[int] = None,
    ):
        self.shutdown_requested = False
        self.shutdown_signal: Optional[int] = None
        self._on_shutdown = on_shutdown
        self._register_signals = bool(register_signals)
        self._installed_wakeup_fd: Optional[int] = None
        if not register_signals:
            return

        # 注册信号处理器
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        if wakeup_fd is not None:
            self.install_wakeup_fd(wakeup_fd)

    def install_wakeup_fd(self, wakeup_fd: Optional[int]) -> bool:
        """Install wakeup FD on the main thread when signals are registered."""
        if not self._register_signals or wakeup_fd is None:
            return self._installed_wakeup_fd is not None
        if self._installed_wakeup_fd is not None:
            return True
        if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "set_wakeup_fd"):
            return False
        try:
            prev_fd = signal.set_wakeup_fd(wakeup_fd, warn_on_full_buffer=False)
            if prev_fd != -1:
                # Preserve an existing caller/event-loop wakeup FD (e.g. uvicorn/asyncio).
                signal.set_wakeup_fd(prev_fd, warn_on_full_buffer=False)
                return False
            self._installed_wakeup_fd = wakeup_fd
            return True
        except (OSError, ValueError):
            return False

    def _signal_handler(self, signum, frame):
        """信号处理函数（保持无锁且 async-signal-safe，避免与主线程 wait 自锁）"""
        if not self.shutdown_requested:
            self.shutdown_signal = signum
            self.shutdown_requested = True
            callback = self._on_shutdown
            if callback is not None:
                try:
                    callback()
                except Exception:  # pragma: no cover - defensive guard inside signal handler
                    pass

    def uninstall_wakeup_fd(self) -> bool:
        """Restore signal wakeup FD if this handler installed it.

        Returns True when no wakeup FD remains installed by this handler;
        returns False when called off the main thread so callers defer closing
        the wakeup descriptor while ``signal.set_wakeup_fd`` still targets it.
        """
        fd = self._installed_wakeup_fd
        if fd is None:
            return True
        if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "set_wakeup_fd"):
            return False
        self._installed_wakeup_fd = None
        try:
            current = signal.set_wakeup_fd(-1)
            if current not in (-1, fd):
                signal.set_wakeup_fd(current, warn_on_full_buffer=False)
        except (OSError, ValueError):
            pass
        return True

    def clear_callback(self) -> bool:
        """Detach wakeup callback and restore wakeup FD once scheduler loop tears down."""
        self._on_shutdown = None
        return self.uninstall_wakeup_fd()

    @property
    def should_shutdown(self) -> bool:
        """检查是否应该退出"""
        return self.shutdown_requested


class Scheduler:
    """
    定时任务调度器

    基于 schedule 库实现，支持：
    - 每日定时执行
    - 启动时立即执行
    - 优雅退出
    """

    def __init__(
        self,
        schedule_time: str = "18:00",
        schedule_time_provider: Optional[Callable[[], str]] = None,
        schedule_times: Optional[Sequence[str]] = None,
        schedule_times_provider: Optional[Callable[[], Union[Sequence[str], str]]] = None,
        register_signals: bool = True,
        pass_scheduled_for: bool = False,
    ):
        """
        初始化调度器

        Args:
            schedule_time: 每日执行时间，格式 "HH:MM"
        """
        try:
            import schedule
            self.schedule = schedule.Scheduler() if hasattr(schedule, "Scheduler") else schedule
        except ImportError:
            logger.error("schedule library is not installed; please run: pip install schedule")
            raise ImportError("请安装 schedule 库: pip install schedule")

        self.schedule_time = schedule_time
        self.schedule_times = (
            normalize_schedule_times(schedule_times, fallback_time=schedule_time)
            if schedule_times is not None
            else [(schedule_time or "").strip()]
        )
        self._schedule_time_provider = schedule_time_provider
        self._schedule_times_provider = schedule_times_provider
        self._wakeup = _WakeupChannel()
        self.shutdown_handler = GracefulShutdown(
            register_signals=register_signals,
            on_shutdown=self._wakeup.notify,
        )
        self._task_callback: Optional[Callable] = None
        self._pass_scheduled_for = pass_scheduled_for
        self._daily_job: Optional[Any] = None
        self._daily_jobs: List[Any] = []
        self._background_tasks: List[Dict[str, Any]] = []
        self._lifecycle_lock = threading.Lock()
        self._running = False
        self._stop_requested = False

    def set_daily_task(self, task: Callable, run_immediately: bool = True):
        """
        设置每日定时任务

        Args:
            task: 要执行的任务函数（无参数）
            run_immediately: 是否在设置后立即执行一次
        """
        self._task_callback = task
        if not self._configure_daily_tasks(self.schedule_times):
            raise ValueError(f"无效的定时执行时间: {self.schedule_time!r}")

        if run_immediately:
            logger.info("Running task immediately...")
            self._safe_run_task()

    @staticmethod
    def _is_valid_schedule_time(schedule_time: str) -> bool:
        """Validate time string in HH:MM 24-hour format."""
        candidate = (schedule_time or "").strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", candidate):
            return False
        return True

    def _cancel_daily_job(self) -> None:
        """Remove the currently registered daily job if one exists."""
        if self._daily_job is None and not self._daily_jobs:
            return

        for job in list(self._daily_jobs or [self._daily_job]):
            if job is None:
                continue
            if hasattr(self.schedule, "cancel_job"):
                self.schedule.cancel_job(job)
            else:  # pragma: no cover - compatibility fallback
                jobs = getattr(self.schedule, "jobs", None)
                if isinstance(jobs, list) and job in jobs:
                    jobs.remove(job)

        self._daily_job = None
        self._daily_jobs = []

    def _register_daily_job(self, schedule_time: str) -> Any:
        job = self.schedule.every().day.at(schedule_time)
        # schedule updates next_run after the callback, so preserve the original
        # due date/time through delayed polling and asynchronous dispatch.
        return job.do(lambda: self._safe_run_task(scheduled_for=job.next_run))

    def _configure_daily_tasks(self, schedule_times: Union[Sequence[str], str]) -> bool:
        """(Re)register daily jobs at the requested times."""
        raw_items = (
            [item.strip() for item in schedule_times.split(",")]
            if isinstance(schedule_times, str)
            else [str(item).strip() for item in schedule_times]
        )
        invalid_items = [item for item in raw_items if item and not self._is_valid_schedule_time(item)]
        if invalid_items:
            logger.warning(
                "Invalid schedule time values %r; keeping current times %s",
                invalid_items,
                ",".join(self.schedule_times),
            )
            return False

        candidates = normalize_schedule_times(raw_items, fallback_time=self.schedule_time)
        previous_times = list(self.schedule_times)
        self._cancel_daily_job()
        self._daily_jobs = [
            self._register_daily_job(candidate)
            for candidate in candidates
        ]
        self._daily_job = self._daily_jobs[0] if self._daily_jobs else None
        self.schedule_times = candidates
        self.schedule_time = candidates[0] if candidates else "18:00"

        if previous_times == candidates:
            logger.info("Daily scheduled jobs configured at: %s", ",".join(self.schedule_times))
        else:
            logger.info(
                "Schedule times changed from %s to %s",
                ",".join(previous_times),
                ",".join(self.schedule_times),
            )
        return True

    def _refresh_daily_schedule_if_needed(self) -> None:
        """Reload daily schedule times from the latest runtime config if needed."""
        if self._task_callback is None:
            return

        try:
            if self._schedule_times_provider is not None:
                latest_schedule_times = self._schedule_times_provider()
            elif self._schedule_time_provider is not None:
                latest_schedule_times = [(self._schedule_time_provider() or "").strip()]
            else:
                return
        except Exception as exc:  # pragma: no cover - defensive branch
            logger.warning(
                "Failed to read latest schedule times; keeping %s: %s",
                ",".join(self.schedule_times),
                exc,
            )
            return

        if latest_schedule_times is None:
            return
        if isinstance(latest_schedule_times, str):
            raw_items = [item.strip() for item in latest_schedule_times.split(",")]
        else:
            raw_items = [str(item).strip() for item in latest_schedule_times]

        non_empty = [item for item in raw_items if item]
        if not non_empty:
            return

        invalid_items = [item for item in non_empty if not self._is_valid_schedule_time(item)]
        if invalid_items:
            logger.warning(
                "Invalid schedule time values %r; keeping current times %s",
                invalid_items,
                ",".join(self.schedule_times),
            )
            return

        latest = sorted(set(non_empty))
        if latest == self.schedule_times:
            return

        if self._configure_daily_tasks(latest):
            logger.info("Schedule refreshed; next run: %s", self._get_next_run_time())

    def refresh_daily_schedule_if_needed(self) -> None:
        """Public wrapper for runtime scheduler reconciliation."""
        self._refresh_daily_schedule_if_needed()

    def _safe_run_task(self, scheduled_for: Optional[datetime] = None):
        """安全执行任务（带异常捕获）"""
        if self._task_callback is None:
            return

        try:
            logger.info("=" * 50)
            logger.info(f"Scheduled task started - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 50)

            if self._pass_scheduled_for:
                self._task_callback(scheduled_for=scheduled_for)
            else:
                self._task_callback()

            logger.info(f"Scheduled task completed - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        except Exception as e:
            logger.exception(f"Scheduled task failed: {e}")

    def add_background_task(
        self,
        task: Callable,
        interval_seconds: int,
        run_immediately: bool = False,
        name: Optional[str] = None,
    ) -> None:
        """Register a periodic background task executed inside the scheduler loop.

        Note: The scheduler loop polls every 30 seconds, so *interval_seconds*
        below 30 will be clamped to 30 to avoid promising unreachable precision.
        """
        clamped_interval = max(30, int(interval_seconds))
        if int(interval_seconds) < 30:
            logger.warning(
                "Background task %s requested %ds interval, "
                "but scheduler loop polls every 30s; clamped to 30s",
                name or getattr(task, "__name__", "background_task"),
                interval_seconds,
            )
        entry = {
            "task": task,
            "interval_seconds": clamped_interval,
            "last_run": 0.0,
            "name": name or getattr(task, "__name__", "background_task"),
            "thread": None,
            "running": False,
        }
        if not run_immediately:
            entry["last_run"] = time.time()
        self._background_tasks.append(entry)
        logger.info(
            "Registered background task: %s (interval=%ss, run_immediately=%s)",
            entry["name"],
            entry["interval_seconds"],
            run_immediately,
        )
        if run_immediately:
            self._start_background_task(entry)

    def _start_background_task(self, entry: Dict[str, Any]) -> bool:
        """Start one background task in a dedicated daemon thread."""
        worker = entry.get("thread")
        if worker is not None and worker.is_alive():
            return False

        def _runner() -> None:
            try:
                logger.info("Background task started: %s", entry["name"])
                entry["task"]()
            except Exception as exc:
                logger.exception("Background task failed [%s]: %s", entry["name"], exc)
            finally:
                entry["running"] = False
                entry["thread"] = None

        entry["last_run"] = time.time()
        entry["running"] = True
        worker = threading.Thread(
            target=_runner,
            daemon=True,
            name=f"scheduler-bg-{entry['name']}",
        )
        entry["thread"] = worker
        worker.start()
        return True

    def _run_background_tasks(self) -> None:
        """Execute any background tasks whose interval has elapsed."""
        if not self._background_tasks:
            return

        now = time.time()
        for entry in self._background_tasks:
            worker = entry.get("thread")
            if worker is not None and worker.is_alive():
                continue
            if entry.get("running"):
                entry["running"] = False
                entry["thread"] = None
            if now - entry["last_run"] < entry["interval_seconds"]:
                continue
            self._start_background_task(entry)

    def _dispatch_background_tasks_if_running(self) -> bool:
        """Dispatch due background tasks before a concurrent stop can return."""
        with self._lifecycle_lock:
            if not self._running or self.shutdown_handler.should_shutdown:
                return False
            self._run_background_tasks()
            return True

    def _wait_for_stop(self, timeout: float = 30.0) -> bool:
        """Wait for stop/shutdown wakeup without holding thread locks."""
        return self._wakeup.wait(timeout)

    def run(self):
        """
        运行调度器主循环

        阻塞运行，直到收到退出信号
        """
        with self._lifecycle_lock:
            if self._stop_requested:
                logger.info("Scheduler already stopped; ignoring late start request")
                return
            self._running = True
            self.shutdown_handler.install_wakeup_fd(self._wakeup.fileno())
        logger.info("Scheduler starting...")
        logger.info(f"Next run time: {self._get_next_run_time()}")

        try:
            while self._running and not self.shutdown_handler.should_shutdown:
                self._refresh_daily_schedule_if_needed()
                self.schedule.run_pending()
                if not self._dispatch_background_tasks_if_running():
                    break
                if self._wait_for_stop(timeout=30):
                    break

                # 每小时打印一次心跳
                if datetime.now().minute == 0 and datetime.now().second < 30:
                    logger.info(f"Scheduler running... next run: {self._get_next_run_time()}")
        finally:
            with self._lifecycle_lock:
                self._running = False
                if self.shutdown_handler.clear_callback():
                    self._wakeup.close()

        if self.shutdown_handler.should_shutdown and self.shutdown_handler.shutdown_signal is not None:
            logger.info(
                "Received exit signal (%s); stopping scheduler...",
                self.shutdown_handler.shutdown_signal,
            )

        logger.info("Scheduler stopped")

    def _get_next_run_time(self) -> str:
        """Return formatted next scheduled run time."""
        jobs = self.schedule.get_jobs()
        next_runs = [job.next_run for job in jobs if getattr(job, "next_run", None) is not None]
        if next_runs:
            return min(next_runs).strftime('%Y-%m-%d %H:%M:%S')
        return "not set"

    def stop(self):
        """停止调度器"""
        with self._lifecycle_lock:
            self._stop_requested = True
            self._running = False
            self._wakeup.notify()
        self._cancel_daily_job()

    def close(self) -> None:
        """Stop scheduler and release wakeup descriptors."""
        self.stop()
        with self._lifecycle_lock:
            if self.shutdown_handler.clear_callback():
                self._wakeup.close()

    def __del__(self) -> None:
        handler = getattr(self, "shutdown_handler", None)
        wakeup_uninstalled = True if handler is None else handler.clear_callback()
        wakeup = getattr(self, "_wakeup", None)
        if wakeup is not None and wakeup_uninstalled:
            wakeup.close()


def run_with_schedule(
    task: Callable,
    schedule_time: str = "18:00",
    run_immediately: bool = True,
    background_tasks: Optional[List[Dict[str, Any]]] = None,
    schedule_time_provider: Optional[Callable[[], str]] = None,
    schedule_times: Optional[Sequence[str]] = None,
    schedule_times_provider: Optional[Callable[[], Union[Sequence[str], str]]] = None,
    pass_scheduled_for: bool = False,
):
    """
    便捷函数：使用定时调度运行任务

    Args:
        task: 要执行的任务函数
        schedule_time: 每日执行时间
        run_immediately: 是否立即执行一次
        background_tasks: 可选的后台任务定义列表。每项为一个字典，
            需包含 `task` 与 `interval_seconds`，可选包含 `name`
            和 `run_immediately`。`interval_seconds` 单位为秒。
        schedule_time_provider: 可选的时间提供器；调度器每轮检查前会读取，
            当返回值变化时自动重建 daily job。
    """
    scheduler_kwargs: Dict[str, Any] = {
        "schedule_time": schedule_time,
        "schedule_time_provider": schedule_time_provider,
    }
    if schedule_times is not None:
        scheduler_kwargs["schedule_times"] = schedule_times
    if schedule_times_provider is not None:
        scheduler_kwargs["schedule_times_provider"] = schedule_times_provider
    if pass_scheduled_for:
        scheduler_kwargs["pass_scheduled_for"] = True
    scheduler = Scheduler(**scheduler_kwargs)
    try:
        for entry in background_tasks or []:
            scheduler.add_background_task(
                task=entry["task"],
                interval_seconds=entry["interval_seconds"],
                run_immediately=entry.get("run_immediately", False),
                name=entry.get("name"),
            )
        scheduler.set_daily_task(task, run_immediately=run_immediately)
        scheduler.run()
    finally:
        close_fn = getattr(scheduler, "close", None)
        if callable(close_fn):
            close_fn()


if __name__ == "__main__":
    # 测试定时调度
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    )

    def test_task():
        print(f"任务执行中... {datetime.now()}")
        time.sleep(2)
        print("任务完成!")

    print("启动测试调度器（按 Ctrl+C 退出）")
    run_with_schedule(test_task, schedule_time="23:59", run_immediately=True)
