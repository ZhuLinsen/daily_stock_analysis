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
import re
import signal
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


class GracefulShutdown:
    """
    优雅退出处理器

    捕获 SIGTERM/SIGINT 信号，确保任务完成后再退出
    """

    def __init__(self, register_signals: bool = True):
        self.shutdown_requested = False
        self._lock = threading.Lock()
        if not register_signals:
            return

        # 注册信号处理器
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """信号处理函数"""
        with self._lock:
            if not self.shutdown_requested:
                logger.info(f"收到退出信号 ({signum})，等待当前任务完成...")
                self.shutdown_requested = True

    @property
    def should_shutdown(self) -> bool:
        """检查是否应该退出"""
        with self._lock:
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
    ):
        """
        初始化调度器

        Args:
            schedule_time: 每日执行时间，格式 "HH:MM"
        """
        try:
            import schedule
            self.schedule = schedule
        except ImportError:
            logger.error("schedule 库未安装，请执行: pip install schedule")
            raise ImportError("请安装 schedule 库: pip install schedule")

        self.schedule_time = schedule_time
        self.schedule_times = (
            normalize_schedule_times(schedule_times, fallback_time=schedule_time)
            if schedule_times is not None
            else [(schedule_time or "").strip()]
        )
        self._schedule_time_provider = schedule_time_provider
        self._schedule_times_provider = schedule_times_provider
        self.shutdown_handler = GracefulShutdown(register_signals=register_signals)
        self._task_callback: Optional[Callable] = None
        self._daily_job: Optional[Any] = None
        self._daily_jobs: List[Any] = []
        self._background_tasks: List[Dict[str, Any]] = []
        self._running = False

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
            logger.info("立即执行一次任务...")
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

    def _configure_daily_task(self, schedule_time: str) -> bool:
        """(Re)register the daily job at the requested time."""
        candidate = (schedule_time or "").strip()
        if not self._is_valid_schedule_time(candidate):
            logger.warning(
                "检测到无效的定时执行时间 %r，继续沿用当前时间 %s",
                schedule_time,
                self.schedule_time,
            )
            return False

        previous_time = self.schedule_time
        self._cancel_daily_job()
        self._daily_job = self.schedule.every().day.at(candidate).do(self._safe_run_task)
        self.schedule_time = candidate

        if previous_time == candidate:
            logger.info("已设置每日定时任务，执行时间: %s", self.schedule_time)
        else:
            logger.info(
                "检测到 SCHEDULE_TIME 变更，已将每日定时任务从 %s 更新为 %s",
                previous_time,
                self.schedule_time,
            )
        return True

    def _refresh_daily_schedule_if_needed(self) -> None:
        """Reload daily schedule time from the latest runtime config if needed."""
        if self._task_callback is None or self._schedule_time_provider is None:
            return

        try:
            latest_schedule_time = (self._schedule_time_provider() or "").strip()
        except Exception as exc:  # pragma: no cover - defensive branch
            logger.warning("读取最新 SCHEDULE_TIME 失败，继续沿用 %s: %s", self.schedule_time, exc)
            return

        if not latest_schedule_time or latest_schedule_time == self.schedule_time:
            return

        if self._configure_daily_task(latest_schedule_time):
            logger.info("更新后的下次执行时间: %s", self._get_next_run_time())

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
            self.schedule.every().day.at(candidate).do(self._safe_run_task)
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

        latest = normalize_schedule_times(latest_schedule_times, fallback_time=self.schedule_time)
        if latest == self.schedule_times:
            return

        if self._configure_daily_tasks(latest):
            logger.info("Schedule refreshed; next run: %s", self._get_next_run_time())

    def refresh_daily_schedule_if_needed(self) -> None:
        """Public wrapper for runtime scheduler reconciliation."""
        self._refresh_daily_schedule_if_needed()

    def _safe_run_task(self):
        """安全执行任务（带异常捕获）"""
        if self._task_callback is None:
            return

        try:
            logger.info("=" * 50)
            logger.info(f"定时任务开始执行 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 50)

            self._task_callback()

            logger.info(f"定时任务执行完成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        except Exception as e:
            logger.exception(f"定时任务执行失败: {e}")

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
                "后台任务 %s 请求间隔 %ds，但调度循环每 30s 轮询一次，已自动调整为 30s",
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
            "已注册后台任务: %s（间隔 %s 秒，立即执行=%s）",
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
                logger.info("后台任务开始执行: %s", entry["name"])
                entry["task"]()
            except Exception as exc:
                logger.exception("后台任务执行失败 [%s]: %s", entry["name"], exc)
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

    def run(self):
        """
        运行调度器主循环

        阻塞运行，直到收到退出信号
        """
        self._running = True
        logger.info("调度器开始运行...")
        logger.info(f"下次执行时间: {self._get_next_run_time()}")

        while self._running and not self.shutdown_handler.should_shutdown:
            self._refresh_daily_schedule_if_needed()
            self.schedule.run_pending()
            self._run_background_tasks()
            time.sleep(30)  # 每30秒检查一次

            # 每小时打印一次心跳
            if datetime.now().minute == 0 and datetime.now().second < 30:
                logger.info(f"调度器运行中... 下次执行: {self._get_next_run_time()}")

        logger.info("调度器已停止")

    def _get_next_run_time(self) -> str:
        """获取下次执行时间"""
        jobs = self.schedule.get_jobs()
        if jobs:
            next_run = min(job.next_run for job in jobs)
            return next_run.strftime('%Y-%m-%d %H:%M:%S')
        return "未设置"

    def stop(self):
        """停止调度器"""
        self._running = False
        self._cancel_daily_job()


def run_with_schedule(
    task: Callable,
    schedule_time: str = "18:00",
    run_immediately: bool = True,
    background_tasks: Optional[List[Dict[str, Any]]] = None,
    schedule_time_provider: Optional[Callable[[], str]] = None,
    schedule_times: Optional[Sequence[str]] = None,
    schedule_times_provider: Optional[Callable[[], Union[Sequence[str], str]]] = None,
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
    scheduler = Scheduler(**scheduler_kwargs)
    for entry in background_tasks or []:
        scheduler.add_background_task(
            task=entry["task"],
            interval_seconds=entry["interval_seconds"],
            run_immediately=entry.get("run_immediately", False),
            name=entry.get("name"),
        )
    scheduler.set_daily_task(task, run_immediately=run_immediately)
    scheduler.run()


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
