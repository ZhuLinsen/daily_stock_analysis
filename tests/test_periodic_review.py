# -*- coding: utf-8 -*-
"""Tests for periodic (weekly/monthly) review service and scheduler."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from src.schemas.periodic_review import (
    IndexPerformance,
    MarketLightTrendPoint,
    PeriodicReviewData,
    PeriodicReviewType,
)
from src.services.periodic_review_scheduler import (
    PeriodicReviewScheduler,
    is_last_weekday_of_month,
)
from src.services.periodic_review_service import PeriodicReviewService


class IsLastWeekdayOfMonthTestCase(unittest.TestCase):
    """Test the month-end detection logic."""

    def test_last_friday_of_month(self) -> None:
        # 2026-07-31 is a Friday — last weekday of July 2026
        self.assertTrue(is_last_weekday_of_month(date(2026, 7, 31)))

    def test_last_monday_of_month(self) -> None:
        # 2026-08-31 is a Monday — last weekday of August 2026
        self.assertTrue(is_last_weekday_of_month(date(2026, 8, 31)))

    def test_not_last_weekday_mid_month(self) -> None:
        self.assertFalse(is_last_weekday_of_month(date(2026, 7, 15)))

    def test_not_last_weekday_when_weekday_remains(self) -> None:
        # 2026-07-30 is a Thursday, but 2026-07-31 (Friday) remains
        self.assertFalse(is_last_weekday_of_month(date(2026, 7, 30)))

    def test_weekend_is_not_last_weekday(self) -> None:
        # Saturday — never considered a trading day
        self.assertFalse(is_last_weekday_of_month(date(2026, 7, 25)))

    def test_december_31_last_weekday(self) -> None:
        # 2026-12-31 is a Thursday — last weekday of December 2026
        self.assertTrue(is_last_weekday_of_month(date(2026, 12, 31)))


class HighlightsTestCase(unittest.TestCase):
    """Test the deterministic highlights builder (no LLM dependency)."""

    def test_all_indices_up(self) -> None:
        indices = [
            IndexPerformance(name="上证指数", code="000001", start_close=3000, end_close=3100, change_pct=3.33),
            IndexPerformance(name="深证成指", code="399001", start_close=10000, end_close=10500, change_pct=5.0),
        ]
        text = PeriodicReviewService._build_highlights(PeriodicReviewType.WEEKLY, indices, [])
        self.assertIn("全线上涨", text)
        self.assertIn("上证指数+3.33%", text)

    def test_all_indices_down(self) -> None:
        indices = [
            IndexPerformance(name="上证指数", code="000001", start_close=3100, end_close=3000, change_pct=-3.23),
        ]
        text = PeriodicReviewService._build_highlights(PeriodicReviewType.MONTHLY, indices, [])
        self.assertIn("全线下跌", text)
        self.assertIn("本月", text)

    def test_mixed_indices(self) -> None:
        indices = [
            IndexPerformance(name="上证指数", code="000001", start_close=3000, end_close=3100, change_pct=3.33),
            IndexPerformance(name="深证成指", code="399001", start_close=10500, end_close=10000, change_pct=-4.76),
        ]
        text = PeriodicReviewService._build_highlights(PeriodicReviewType.WEEKLY, indices, [])
        self.assertIn("分化", text)

    def test_empty_inputs(self) -> None:
        text = PeriodicReviewService._build_highlights(PeriodicReviewType.WEEKLY, [], [])
        self.assertEqual(text, "")


class SectorRotationTestCase(unittest.TestCase):
    """Test the sentiment rotation detection."""

    def test_warming(self) -> None:
        trend = [
            MarketLightTrendPoint(trade_date="2026-07-01", score=40, status="yellow"),
            MarketLightTrendPoint(trade_date="2026-07-05", score=60, status="green"),
        ]
        rotation = PeriodicReviewService._detect_sector_rotation(trend)
        self.assertIsNotNone(rotation)
        self.assertIn("升温", rotation)

    def test_cooling(self) -> None:
        trend = [
            MarketLightTrendPoint(trade_date="2026-07-01", score=60, status="green"),
            MarketLightTrendPoint(trade_date="2026-07-05", score=40, status="red"),
        ]
        rotation = PeriodicReviewService._detect_sector_rotation(trend)
        self.assertIsNotNone(rotation)
        self.assertIn("降温", rotation)

    def test_stable(self) -> None:
        trend = [
            MarketLightTrendPoint(trade_date="2026-07-01", score=50, status="yellow"),
            MarketLightTrendPoint(trade_date="2026-07-05", score=52, status="yellow"),
        ]
        rotation = PeriodicReviewService._detect_sector_rotation(trend)
        self.assertIsNotNone(rotation)
        self.assertIn("平稳", rotation)

    def test_insufficient_data(self) -> None:
        rotation = PeriodicReviewService._detect_sector_rotation([])
        self.assertIsNone(rotation)


class ReportRenderingTestCase(unittest.TestCase):
    """Test the Jinja2 template rendering."""

    def test_render_weekly_report(self) -> None:
        data = PeriodicReviewData(
            review_type=PeriodicReviewType.WEEKLY,
            region="cn",
            period_start="2026-06-27",
            period_end="2026-07-03",
            trade_days=5,
            indices=[
                IndexPerformance(
                    name="上证指数", code="000001",
                    start_close=3000, end_close=3100, change_pct=3.33, avg_amount=12000,
                ),
            ],
            top_sectors=[],
            bottom_sectors=[],
            market_light_trend=[
                MarketLightTrendPoint(trade_date="2026-06-27", score=45, status="yellow"),
                MarketLightTrendPoint(trade_date="2026-06-30", score=55, status="yellow"),
                MarketLightTrendPoint(trade_date="2026-07-03", score=62, status="green"),
            ],
            avg_amount=12000,
            sector_rotation="情绪升温（score +17）",
            highlights="本周主要指数全线上涨。",
        )
        service = PeriodicReviewService.__new__(PeriodicReviewService)
        report = service._render_report(data)
        self.assertIsNotNone(report)
        self.assertIn("周度市场复盘报告", report)
        self.assertIn("上证指数", report)
        self.assertIn("情绪升温", report)

    def test_render_monthly_report(self) -> None:
        data = PeriodicReviewData(
            review_type=PeriodicReviewType.MONTHLY,
            region="cn",
            period_start="2026-06-01",
            period_end="2026-06-30",
            trade_days=20,
            indices=[],
            top_sectors=[],
            bottom_sectors=[],
            market_light_trend=[],
            avg_amount=0,
            sector_rotation=None,
            highlights="",
        )
        service = PeriodicReviewService.__new__(PeriodicReviewService)
        report = service._render_report(data)
        self.assertIsNotNone(report)
        self.assertIn("月度市场复盘报告", report)
        self.assertIn("暂无指数数据", report)


class SchedulerRunTaskTestCase(unittest.TestCase):
    """Test the scheduler's run_task day-based dispatching."""

    def setUp(self) -> None:
        self.scheduler = PeriodicReviewScheduler.__new__(PeriodicReviewScheduler)

    def test_friday_triggers_weekly(self) -> None:
        with patch("src.services.periodic_review_scheduler.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 10)  # Friday
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            with patch.object(self.scheduler, "_execute_review") as mock_exec:
                self.scheduler.config = type("C", (), {"periodic_review_monthly_enabled": True})()
                self.scheduler.run_task()
                mock_exec.assert_called_once_with("weekly")

    def test_month_end_triggers_monthly(self) -> None:
        with patch("src.services.periodic_review_scheduler.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 31)  # Friday + month-end
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            with patch.object(self.scheduler, "_execute_review") as mock_exec:
                self.scheduler.config = type("C", (), {"periodic_review_monthly_enabled": True})()
                self.scheduler.run_task()
                # Month-end takes priority over Friday
                mock_exec.assert_called_once_with("monthly")

    def test_monday_does_nothing(self) -> None:
        with patch("src.services.periodic_review_scheduler.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 6)  # Monday
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            with patch.object(self.scheduler, "_execute_review") as mock_exec:
                self.scheduler.config = type("C", (), {"periodic_review_monthly_enabled": True})()
                self.scheduler.run_task()
                mock_exec.assert_not_called()

    def test_monthly_disabled_falls_back_to_weekly_on_friday(self) -> None:
        with patch("src.services.periodic_review_scheduler.date") as mock_date:
            mock_date.today.return_value = date(2026, 7, 31)  # Friday + month-end
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
            with patch.object(self.scheduler, "_execute_review") as mock_exec:
                self.scheduler.config = type("C", (), {"periodic_review_monthly_enabled": False})()
                self.scheduler.run_task()
                # Monthly disabled, but it's still Friday -> weekly
                mock_exec.assert_called_once_with("weekly")


if __name__ == "__main__":
    unittest.main()
