# -*- coding: utf-8 -*-
"""Regression tests for effective trading date resolution."""

from datetime import date, datetime, time, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from src.core import trading_calendar


class _FakeCalendar:
    def __init__(self, sessions, close_hour: int, tz_name: str):
        self._sessions = sorted(sessions)
        self._close_hour = close_hour
        self._tz_name = tz_name

    def is_session(self, check_date: date) -> bool:
        return check_date in self._sessions

    def date_to_session(self, check_date: date, direction: str = "previous") -> pd.Timestamp:
        if direction == "previous":
            candidates = [d for d in self._sessions if d <= check_date]
        elif direction == "next":
            candidates = [d for d in self._sessions if d >= check_date]
        else:
            raise ValueError(f"unsupported direction: {direction}")

        if not candidates:
            raise ValueError(f"no session for {check_date} ({direction})")
        return pd.Timestamp(candidates[-1] if direction == "previous" else candidates[0])

    def previous_session(self, session: pd.Timestamp) -> pd.Timestamp:
        session_date = session.date()
        index = self._sessions.index(session_date)
        if index == 0:
            raise ValueError("no previous session")
        return pd.Timestamp(self._sessions[index - 1])

    def session_close(self, session: pd.Timestamp) -> pd.Timestamp:
        local_close = datetime.combine(
            session.date(),
            time(self._close_hour, 0),
            tzinfo=ZoneInfo(self._tz_name),
        )
        return pd.Timestamp(local_close).tz_convert("UTC")


class EffectiveTradingDateTestCase(unittest.TestCase):
    def test_weekend_returns_previous_session(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 26), date(2026, 3, 27)],
            close_hour=15,
            tz_name="Asia/Shanghai",
        )
        current_time = datetime(2026, 3, 28, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
            trading_calendar,
            "xcals",
            SimpleNamespace(get_calendar=lambda _ex: fake_calendar),
            create=True,
        ):
            result = trading_calendar.get_effective_trading_date("cn", current_time=current_time)

        self.assertEqual(result, date(2026, 3, 27))

    def test_holiday_returns_previous_session(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2025, 12, 31), date(2026, 1, 5)],
            close_hour=15,
            tz_name="Asia/Shanghai",
        )
        current_time = datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
            trading_calendar,
            "xcals",
            SimpleNamespace(get_calendar=lambda _ex: fake_calendar),
            create=True,
        ):
            result = trading_calendar.get_effective_trading_date("cn", current_time=current_time)

        self.assertEqual(result, date(2025, 12, 31))

    def test_intraday_returns_previous_completed_session(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 26), date(2026, 3, 27)],
            close_hour=16,
            tz_name="America/New_York",
        )
        current_time = datetime(
            2026,
            3,
            27,
            15,
            59,
            tzinfo=ZoneInfo("America/New_York"),
        )

        with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
            trading_calendar,
            "xcals",
            SimpleNamespace(get_calendar=lambda _ex: fake_calendar),
            create=True,
        ):
            result = trading_calendar.get_effective_trading_date("us", current_time=current_time)

        self.assertEqual(result, date(2026, 3, 26))

    def test_after_close_returns_current_session(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 26), date(2026, 3, 27)],
            close_hour=16,
            tz_name="America/New_York",
        )
        current_time = datetime(
            2026,
            3,
            27,
            16,
            1,
            tzinfo=ZoneInfo("America/New_York"),
        )

        with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
            trading_calendar,
            "xcals",
            SimpleNamespace(get_calendar=lambda _ex: fake_calendar),
            create=True,
        ):
            result = trading_calendar.get_effective_trading_date("us", current_time=current_time)

        self.assertEqual(result, date(2026, 3, 27))

    def test_market_timezone_controls_cross_timezone_resolution(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 25), date(2026, 3, 26), date(2026, 3, 27)],
            close_hour=16,
            tz_name="America/New_York",
        )
        current_time = datetime(2026, 3, 27, 1, 0, tzinfo=timezone.utc)

        with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
            trading_calendar,
            "xcals",
            SimpleNamespace(get_calendar=lambda _ex: fake_calendar),
            create=True,
        ):
            result = trading_calendar.get_effective_trading_date("us", current_time=current_time)

        self.assertEqual(result, date(2026, 3, 26))

    def test_calendar_error_falls_back_to_market_local_date(self):
        current_time = datetime(2026, 3, 27, 18, 0, tzinfo=timezone.utc)

        with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
            trading_calendar,
            "xcals",
            SimpleNamespace(get_calendar=lambda _ex: (_ for _ in ()).throw(RuntimeError("boom"))),
            create=True,
        ):
            result = trading_calendar.get_effective_trading_date("hk", current_time=current_time)

        self.assertEqual(result, date(2026, 3, 28))


if __name__ == "__main__":
    unittest.main()
