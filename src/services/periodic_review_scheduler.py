#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Periodic review scheduler.

Schedules weekly (every Friday) and monthly (last weekday of month)
review tasks. The scheduler runs both in a single loop and checks
whether the current day matches the trigger condition.

Usage:
    PERIODIC_REVIEW_ENABLED=true venv/bin/python -c \\
        "from src.services.periodic_review_scheduler import PeriodicReviewScheduler; \\
         PeriodicReviewScheduler().run_task()"
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime
from typing import Optional

from src.config import Config, get_config
from src.services.periodic_review_report_sender import (
    PeriodicReviewReportSender,
    create_periodic_review_report_sender,
)
from src.services.periodic_review_service import PeriodicReviewService

logger = logging.getLogger(__name__)


def is_last_weekday_of_month(target: Optional[date] = None) -> bool:
    """Return True if *target* is the last weekday (Mon-Fri) of its month."""
    target = target or date.today()
    if target.weekday() >= 5:  # Sat/Sun
        return False
    _, last_day = calendar.monthrange(target.year, target.month)
    for day in range(target.day + 1, last_day + 1):
        if date(target.year, target.month, day).weekday() < 5:
            return False
    return True


class PeriodicReviewScheduler:
    """Schedule and run weekly/monthly review tasks."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.report_sender: PeriodicReviewReportSender = create_periodic_review_report_sender()
        logger.info("周期复盘调度器初始化完成")

    def run_task(self) -> bool:
        """Run the appropriate review task based on the current date.

        - On the last weekday of the month: run monthly review (if enabled).
        - On Fridays: run weekly review (if enabled).
        - If both conditions match (last weekday of month is a Friday),
          only the monthly review runs to avoid duplicate reports.
        """
        today = date.today()
        is_month_end = is_last_weekday_of_month(today)
        is_friday = today.weekday() == 4  # Monday=0, Friday=4

        monthly_enabled = getattr(self.config, "periodic_review_monthly_enabled", True)
        weekly_enabled = True  # weekly is always enabled when feature is on

        ran = False

        if is_month_end and monthly_enabled:
            logger.info("今日为月末交易日，执行月报")
            ran = self._execute_review("monthly")
        elif is_friday and weekly_enabled:
            logger.info("今日为周五，执行周报")
            ran = self._execute_review("weekly")
        else:
            logger.info("今日无需执行周期复盘 (friday=%s, month_end=%s)", is_friday, is_month_end)

        return ran

    def run_weekly(self) -> bool:
        """Force-run the weekly review (for manual/dry-run invocation)."""
        return self._execute_review("weekly")

    def run_monthly(self) -> bool:
        """Force-run the monthly review (for manual/dry-run invocation)."""
        return self._execute_review("monthly")

    def _execute_review(self, review_type: str) -> bool:
        """Execute a single review task and send the report."""
        try:
            service = PeriodicReviewService(region="cn")
            if review_type == "monthly":
                report = service.run_monthly_review()
            else:
                report = service.run_weekly_review()

            if not report:
                logger.info("周期复盘未生成报告 (%s)", review_type)
                return True

            send_report = getattr(self.config, "periodic_review_send_report", True)
            if send_report:
                success = self.report_sender.send_report(report)
                if success:
                    logger.info("周期复盘报告发送成功 (%s)", review_type)
                else:
                    logger.error("周期复盘报告发送失败 (%s)", review_type)
            else:
                logger.info("周期复盘报告已生成（未发送，send_report=false）")
                # Still log a snippet for dry-run verification
                logger.info("报告摘要:\n%s", report[:500])
            return True

        except Exception as exc:
            logger.error("周期复盘任务失败 (%s): %s", review_type, exc, exc_info=True)
            return False


def create_periodic_review_scheduler() -> PeriodicReviewScheduler:
    return PeriodicReviewScheduler(get_config())
