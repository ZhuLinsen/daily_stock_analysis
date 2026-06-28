# -*- coding: utf-8 -*-
"""Regression tests for effective trading date resolution."""

import json
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from typing import Optional
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from src.core import trading_calendar


class _FakeCalendar:
    def __init__(
        self,
        sessions,
        close_hour: int,
        tz_name: str,
        open_time: time = time(9, 30),
        break_start: Optional[time] = None,
        break_end: Optional[time] = None,
    ):
        self._sessions = sorted(sessions)
        self._close_hour = close_hour
        self._tz_name = tz_name
        self._open_time = open_time
        self._break_start = break_start
        self._break_end = break_end

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

    def session_open(self, session: pd.Timestamp) -> pd.Timestamp:
        local_open = datetime.combine(
            session.date(),
            self._open_time,
            tzinfo=ZoneInfo(self._tz_name),
        )
        return pd.Timestamp(local_open).tz_convert("UTC")

    def session_break_start(self, session: pd.Timestamp) -> pd.Timestamp:
        if self._break_start is None:
            return pd.NaT
        local_break_start = datetime.combine(
            session.date(),
            self._break_start,
            tzinfo=ZoneInfo(self._tz_name),
        )
        return pd.Timestamp(local_break_start).tz_convert("UTC")

    def session_break_end(self, session: pd.Timestamp) -> pd.Timestamp:
        if self._break_end is None:
            return pd.NaT
        local_break_end = datetime.combine(
            session.date(),
            self._break_end,
            tzinfo=ZoneInfo(self._tz_name),
        )
        return pd.Timestamp(local_break_end).tz_convert("UTC")

    def session_has_break(self, session: pd.Timestamp) -> bool:
        return self._break_start is not None and self._break_end is not None

    def session_close(self, session: pd.Timestamp) -> pd.Timestamp:
        local_close = datetime.combine(
            session.date(),
            time(self._close_hour, 0),
            tzinfo=ZoneInfo(self._tz_name),
        )
        return pd.Timestamp(local_close).tz_convert("UTC")


def _calendar_namespace(fake_calendar: _FakeCalendar) -> SimpleNamespace:
    return SimpleNamespace(get_calendar=lambda _ex: fake_calendar)


class _InvalidOpenCalendar(_FakeCalendar):
    def session_open(self, session: pd.Timestamp):
        return object()


class _BreakProbeFailureCalendar(_FakeCalendar):
    def session_has_break(self, session: pd.Timestamp) -> bool:
        raise RuntimeError("break metadata failed")


class _NaiveTimestampCalendar(_FakeCalendar):
    def session_open(self, session: pd.Timestamp) -> pd.Timestamp:
        return pd.Timestamp(datetime.combine(session.date(), self._open_time))

    def session_close(self, session: pd.Timestamp) -> pd.Timestamp:
        return pd.Timestamp(datetime.combine(session.date(), time(self._close_hour, 0)))


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


class InferMarketPhaseTestCase(unittest.TestCase):
    """Tests for the Issue #1386 P0 market phase baseline."""

    def _infer_with_calendar(
        self,
        market: str,
        current_time: datetime,
        fake_calendar: _FakeCalendar,
    ) -> trading_calendar.MarketPhase:
        with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
            trading_calendar,
            "xcals",
            _calendar_namespace(fake_calendar),
            create=True,
        ):
            return trading_calendar.infer_market_phase(market, current_time=current_time)

    def test_cn_phase_boundaries_include_lunch_and_closing_window(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 27)],
            close_hour=15,
            tz_name="Asia/Shanghai",
            open_time=time(9, 30),
            break_start=time(11, 30),
            break_end=time(13, 0),
        )

        cases = (
            (datetime(2026, 3, 27, 9, 29, tzinfo=ZoneInfo("Asia/Shanghai")), trading_calendar.MarketPhase.PREMARKET),
            (datetime(2026, 3, 27, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")), trading_calendar.MarketPhase.INTRADAY),
            (datetime(2026, 3, 27, 11, 29, tzinfo=ZoneInfo("Asia/Shanghai")), trading_calendar.MarketPhase.INTRADAY),
            (
                datetime(2026, 3, 27, 11, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
                trading_calendar.MarketPhase.LUNCH_BREAK,
            ),
            (
                datetime(2026, 3, 27, 12, 59, tzinfo=ZoneInfo("Asia/Shanghai")),
                trading_calendar.MarketPhase.LUNCH_BREAK,
            ),
            (datetime(2026, 3, 27, 13, 0, tzinfo=ZoneInfo("Asia/Shanghai")), trading_calendar.MarketPhase.INTRADAY),
            (datetime(2026, 3, 27, 14, 56, tzinfo=ZoneInfo("Asia/Shanghai")), trading_calendar.MarketPhase.INTRADAY),
            (
                datetime(2026, 3, 27, 14, 57, tzinfo=ZoneInfo("Asia/Shanghai")),
                trading_calendar.MarketPhase.CLOSING_AUCTION,
            ),
            (
                datetime(2026, 3, 27, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                trading_calendar.MarketPhase.POSTMARKET,
            ),
            (
                datetime(2026, 3, 27, 15, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
                trading_calendar.MarketPhase.POSTMARKET,
            ),
        )

        for current_time, expected in cases:
            with self.subTest(current_time=current_time):
                self.assertEqual(self._infer_with_calendar("cn", current_time, fake_calendar), expected)

    def test_cn_non_trading_day_returns_non_trading(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 27)],
            close_hour=15,
            tz_name="Asia/Shanghai",
            break_start=time(11, 30),
            break_end=time(13, 0),
        )
        current_time = datetime(2026, 3, 28, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        result = self._infer_with_calendar("cn", current_time, fake_calendar)

        self.assertEqual(result, trading_calendar.MarketPhase.NON_TRADING)

    def test_hk_phase_boundaries_include_lunch_and_ten_minute_closing_window(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 27)],
            close_hour=16,
            tz_name="Asia/Hong_Kong",
            open_time=time(9, 30),
            break_start=time(12, 0),
            break_end=time(13, 0),
        )

        cases = (
            (
                datetime(2026, 3, 27, 12, 0, tzinfo=ZoneInfo("Asia/Hong_Kong")),
                trading_calendar.MarketPhase.LUNCH_BREAK,
            ),
            (
                datetime(2026, 3, 27, 13, 0, tzinfo=ZoneInfo("Asia/Hong_Kong")),
                trading_calendar.MarketPhase.INTRADAY,
            ),
            (
                datetime(2026, 3, 27, 15, 49, tzinfo=ZoneInfo("Asia/Hong_Kong")),
                trading_calendar.MarketPhase.INTRADAY,
            ),
            (
                datetime(2026, 3, 27, 15, 50, tzinfo=ZoneInfo("Asia/Hong_Kong")),
                trading_calendar.MarketPhase.CLOSING_AUCTION,
            ),
            (
                datetime(2026, 3, 27, 16, 0, tzinfo=ZoneInfo("Asia/Hong_Kong")),
                trading_calendar.MarketPhase.POSTMARKET,
            ),
        )

        for current_time, expected in cases:
            with self.subTest(current_time=current_time):
                self.assertEqual(self._infer_with_calendar("hk", current_time, fake_calendar), expected)

    def test_us_phase_boundaries_skip_nat_lunch_break(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 27)],
            close_hour=16,
            tz_name="America/New_York",
            open_time=time(9, 30),
            break_start=None,
            break_end=None,
        )

        cases = (
            (
                datetime(2026, 3, 27, 9, 29, tzinfo=ZoneInfo("America/New_York")),
                trading_calendar.MarketPhase.PREMARKET,
            ),
            (
                datetime(2026, 3, 27, 9, 30, tzinfo=ZoneInfo("America/New_York")),
                trading_calendar.MarketPhase.INTRADAY,
            ),
            (
                datetime(2026, 3, 27, 12, 0, tzinfo=ZoneInfo("America/New_York")),
                trading_calendar.MarketPhase.INTRADAY,
            ),
            (
                datetime(2026, 3, 27, 15, 54, tzinfo=ZoneInfo("America/New_York")),
                trading_calendar.MarketPhase.INTRADAY,
            ),
            (
                datetime(2026, 3, 27, 15, 55, tzinfo=ZoneInfo("America/New_York")),
                trading_calendar.MarketPhase.CLOSING_AUCTION,
            ),
            (
                datetime(2026, 3, 27, 16, 0, tzinfo=ZoneInfo("America/New_York")),
                trading_calendar.MarketPhase.POSTMARKET,
            ),
        )

        for current_time, expected in cases:
            with self.subTest(current_time=current_time):
                self.assertEqual(self._infer_with_calendar("us", current_time, fake_calendar), expected)

    def test_unknown_market_and_calendar_failures_return_unknown(self):
        current_time = datetime(2026, 3, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        self.assertEqual(
            trading_calendar.infer_market_phase(None, current_time=current_time),
            trading_calendar.MarketPhase.UNKNOWN,
        )
        self.assertEqual(
            trading_calendar.infer_market_phase("", current_time=current_time),
            trading_calendar.MarketPhase.UNKNOWN,
        )
        self.assertEqual(
            trading_calendar.infer_market_phase("invalid", current_time=current_time),
            trading_calendar.MarketPhase.UNKNOWN,
        )
        with patch.object(trading_calendar, "_XCALS_AVAILABLE", False):
            self.assertEqual(
                trading_calendar.infer_market_phase("cn", current_time=current_time),
                trading_calendar.MarketPhase.UNKNOWN,
            )
        with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
            trading_calendar,
            "xcals",
            SimpleNamespace(get_calendar=lambda _ex: (_ for _ in ()).throw(RuntimeError("boom"))),
            create=True,
        ):
            self.assertEqual(
                trading_calendar.infer_market_phase("cn", current_time=current_time),
                trading_calendar.MarketPhase.UNKNOWN,
            )

    def test_invalid_session_open_returns_unknown(self):
        fake_calendar = _InvalidOpenCalendar(
            sessions=[date(2026, 3, 27)],
            close_hour=15,
            tz_name="Asia/Shanghai",
        )
        current_time = datetime(2026, 3, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        result = self._infer_with_calendar("cn", current_time, fake_calendar)

        self.assertEqual(result, trading_calendar.MarketPhase.UNKNOWN)

    def test_break_probe_failure_returns_unknown(self):
        fake_calendar = _BreakProbeFailureCalendar(
            sessions=[date(2026, 3, 27)],
            close_hour=15,
            tz_name="Asia/Shanghai",
            break_start=time(11, 30),
            break_end=time(13, 0),
        )
        current_time = datetime(2026, 3, 27, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        result = self._infer_with_calendar("cn", current_time, fake_calendar)

        self.assertEqual(result, trading_calendar.MarketPhase.UNKNOWN)

    def test_naive_current_time_is_interpreted_as_market_local_time(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 27)],
            close_hour=15,
            tz_name="Asia/Shanghai",
            open_time=time(9, 30),
            break_start=time(11, 30),
            break_end=time(13, 0),
        )

        result = self._infer_with_calendar("cn", datetime(2026, 3, 27, 9, 29), fake_calendar)

        self.assertEqual(result, trading_calendar.MarketPhase.PREMARKET)

    def test_naive_calendar_timestamps_are_interpreted_as_market_local_time(self):
        fake_calendar = _NaiveTimestampCalendar(
            sessions=[date(2026, 3, 27)],
            close_hour=15,
            tz_name="Asia/Shanghai",
            open_time=time(9, 30),
        )
        current_time = datetime(2026, 3, 27, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

        result = self._infer_with_calendar("cn", current_time, fake_calendar)

        self.assertEqual(result, trading_calendar.MarketPhase.INTRADAY)


class MarketPhaseContextTestCase(unittest.TestCase):
    """Tests for the Issue #1386 P1a runtime market phase context."""

    def _build_with_calendar(
        self,
        market: str,
        current_time: datetime,
        fake_calendar: _FakeCalendar,
    ) -> trading_calendar.MarketPhaseContext:
        with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
            trading_calendar,
            "xcals",
            _calendar_namespace(fake_calendar),
            create=True,
        ):
            return trading_calendar.build_market_phase_context(
                market=market,
                current_time=current_time,
                trigger_source="web",
                analysis_intent="auto",
            )

    def test_context_to_dict_is_json_safe_for_intraday(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 26), date(2026, 3, 27)],
            close_hour=15,
            tz_name="Asia/Shanghai",
            open_time=time(9, 30),
            break_start=time(11, 30),
            break_end=time(13, 0),
        )
        ctx = self._build_with_calendar(
            "cn",
            datetime(2026, 3, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            fake_calendar,
        )

        payload = ctx.to_dict()
        encoded = json.loads(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(encoded["market"], "cn")
        self.assertEqual(encoded["phase"], "intraday")
        self.assertEqual(encoded["market_local_time"], "2026-03-27T10:00:00+08:00")
        self.assertEqual(encoded["session_date"], "2026-03-27")
        self.assertEqual(encoded["effective_daily_bar_date"], "2026-03-26")
        self.assertEqual(encoded["is_trading_day"], True)
        self.assertEqual(encoded["is_market_open_now"], True)
        self.assertEqual(encoded["is_partial_bar"], True)
        self.assertIsNone(encoded["minutes_to_open"])
        self.assertEqual(encoded["minutes_to_close"], 300)
        self.assertEqual(encoded["trigger_source"], "web")
        self.assertEqual(encoded["analysis_intent"], "auto")
        self.assertEqual(encoded["warnings"], [])

    def test_context_derived_flags_for_regular_session_phases(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 26), date(2026, 3, 27)],
            close_hour=15,
            tz_name="Asia/Shanghai",
            open_time=time(9, 30),
            break_start=time(11, 30),
            break_end=time(13, 0),
        )
        cases = (
            (
                datetime(2026, 3, 27, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                "premarket",
                True,
                False,
                False,
                30,
                None,
                date(2026, 3, 26),
            ),
            (
                datetime(2026, 3, 27, 11, 45, tzinfo=ZoneInfo("Asia/Shanghai")),
                "lunch_break",
                True,
                False,
                True,
                None,
                195,
                date(2026, 3, 26),
            ),
            (
                datetime(2026, 3, 27, 14, 58, tzinfo=ZoneInfo("Asia/Shanghai")),
                "closing_auction",
                True,
                True,
                True,
                None,
                2,
                date(2026, 3, 26),
            ),
            (
                datetime(2026, 3, 27, 15, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
                "postmarket",
                True,
                False,
                False,
                None,
                None,
                date(2026, 3, 27),
            ),
            (
                datetime(2026, 3, 28, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                "non_trading",
                False,
                False,
                False,
                None,
                None,
                date(2026, 3, 27),
            ),
        )

        for (
            current_time,
            phase,
            is_trading_day,
            is_market_open_now,
            is_partial_bar,
            minutes_to_open,
            minutes_to_close,
            effective_date,
        ) in cases:
            with self.subTest(phase=phase):
                ctx = self._build_with_calendar("cn", current_time, fake_calendar)
                payload = ctx.to_dict()
                self.assertEqual(payload["phase"], phase)
                self.assertEqual(payload["is_trading_day"], is_trading_day)
                self.assertEqual(payload["is_market_open_now"], is_market_open_now)
                self.assertEqual(payload["is_partial_bar"], is_partial_bar)
                self.assertEqual(payload["minutes_to_open"], minutes_to_open)
                self.assertEqual(payload["minutes_to_close"], minutes_to_close)
                self.assertEqual(
                    payload["effective_daily_bar_date"],
                    effective_date.isoformat(),
                )

    def test_manual_analysis_phase_overrides_non_trading_day_without_rewriting_calendar_fields(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 26), date(2026, 3, 27)],
            close_hour=15,
            tz_name="Asia/Shanghai",
            open_time=time(9, 30),
            break_start=time(11, 30),
            break_end=time(13, 0),
        )

        with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
            trading_calendar,
            "xcals",
            _calendar_namespace(fake_calendar),
            create=True,
        ):
            ctx = trading_calendar.build_market_phase_context(
                market="cn",
                current_time=datetime(2026, 3, 28, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                trigger_source="api",
                analysis_phase="intraday",
            )

        payload = ctx.to_dict()
        self.assertEqual(payload["phase"], "intraday")
        self.assertEqual(payload["analysis_intent"], "intraday")
        self.assertEqual(payload["market_local_time"], "2026-03-28T10:00:00+08:00")
        self.assertEqual(payload["effective_daily_bar_date"], "2026-03-27")
        self.assertTrue(payload["is_trading_day"])
        self.assertTrue(payload["is_market_open_now"])
        self.assertTrue(payload["is_partial_bar"])
        self.assertIsNone(payload["minutes_to_open"])
        self.assertIsNone(payload["minutes_to_close"])

    def test_legacy_analysis_intent_alias_can_override_phase(self):
        fake_calendar = _FakeCalendar(
            sessions=[date(2026, 3, 26), date(2026, 3, 27)],
            close_hour=15,
            tz_name="Asia/Shanghai",
            open_time=time(9, 30),
        )

        with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
            trading_calendar,
            "xcals",
            _calendar_namespace(fake_calendar),
            create=True,
        ):
            ctx = trading_calendar.build_market_phase_context(
                market="cn",
                current_time=datetime(2026, 3, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                analysis_intent="postmarket",
            )

        self.assertEqual(ctx.phase, trading_calendar.MarketPhase.POSTMARKET)
        self.assertEqual(ctx.analysis_intent, "postmarket")

    def test_invalid_manual_analysis_phase_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "invalid analysis_phase"):
            trading_calendar.build_market_phase_context(
                market="cn",
                current_time=datetime(2026, 3, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                analysis_phase="lunch_break",
            )

    def test_unknown_market_uses_null_tristate_flags_and_warning_code(self):
        ctx = trading_calendar.build_market_phase_context(
            market=None,
            current_time=datetime(2026, 3, 27, 10, 0),
        )
        payload = json.loads(json.dumps(ctx.to_dict()))

        self.assertEqual(payload["phase"], "unknown")
        self.assertIn("unknown_market", payload["warnings"])
        self.assertIsNone(payload["is_trading_day"])
        self.assertIsNone(payload["is_market_open_now"])
        self.assertIsNone(payload["is_partial_bar"])
        self.assertIsNone(payload["minutes_to_open"])
        self.assertIsNone(payload["minutes_to_close"])

    def test_calendar_unavailable_warning_code(self):
        current_time = datetime(2026, 3, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        with patch.object(trading_calendar, "_XCALS_AVAILABLE", False):
            ctx = trading_calendar.build_market_phase_context(
                market="cn",
                current_time=current_time,
            )

        self.assertEqual(ctx.phase, trading_calendar.MarketPhase.UNKNOWN)
        self.assertIn("calendar_unavailable", ctx.warnings)

    def test_calendar_error_warning_code(self):
        current_time = datetime(2026, 3, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
            trading_calendar,
            "xcals",
            SimpleNamespace(get_calendar=lambda _ex: (_ for _ in ()).throw(RuntimeError("boom"))),
            create=True,
        ):
            ctx = trading_calendar.build_market_phase_context(
                market="cn",
                current_time=current_time,
            )

        self.assertEqual(ctx.phase, trading_calendar.MarketPhase.UNKNOWN)
        self.assertIn("calendar_error", ctx.warnings)


class ComputeEffectiveRegionTestCase(unittest.TestCase):
    """Regression tests for compute_effective_region subset logic."""

    def test_both_all_open_returns_comma_joined_three(self):
        result = trading_calendar.compute_effective_region("both", {"cn", "hk", "us"})
        self.assertEqual(result, "cn,hk,us")

    def test_both_cn_us_open_returns_comma_joined_two(self):
        result = trading_calendar.compute_effective_region("both", {"cn", "us"})
        self.assertEqual(result, "cn,us")

    def test_both_cn_hk_open_returns_comma_joined_two(self):
        result = trading_calendar.compute_effective_region("both", {"cn", "hk"})
        self.assertEqual(result, "cn,hk")

    def test_both_single_market_open_returns_single(self):
        result = trading_calendar.compute_effective_region("both", {"us"})
        self.assertEqual(result, "us")

    def test_both_no_market_open_returns_empty(self):
        result = trading_calendar.compute_effective_region("both", set())
        self.assertEqual(result, "")

    def test_single_region_open(self):
        self.assertEqual(trading_calendar.compute_effective_region("hk", {"cn", "hk", "us"}), "hk")

    def test_single_region_closed(self):
        self.assertEqual(trading_calendar.compute_effective_region("hk", {"cn", "us"}), "")

    def test_invalid_region_defaults_to_cn(self):
        result = trading_calendar.compute_effective_region("invalid", {"cn"})
        self.assertEqual(result, "cn")


if __name__ == "__main__":
    unittest.main()
