# -*- coding: utf-8 -*-
"""Direct contract tests for coherent local daily-window resolution."""

from __future__ import annotations

from datetime import date, datetime, time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from data_provider.base import normalize_stock_code
from src.core import trading_calendar
from src.services.stock_daily_window_resolver import resolve_stock_daily_window


def _bar(day: date, close: float = 100.0):
    return SimpleNamespace(date=day, close=close)


class _FakeStockRepository:
    def __init__(self, starts, forwards):
        self.starts = starts
        self.forwards = forwards
        self.selected_start_dates = {}

    def get_daily_on_date(self, *, code, target_date):
        configured = self.starts.get(code)
        if configured is None:
            return None
        options = configured if isinstance(configured, list) else [configured]
        matching = [start for start in options if start.date == target_date]
        if not matching:
            return None
        start = matching[0]
        self.selected_start_dates[code] = start.date
        return start

    def get_forward_bars(self, *, code, analysis_date, eval_window_days):
        assert self.selected_start_dates[code] == analysis_date
        return list(self.forwards.get(code, ()))[:eval_window_days]


class _FakeExchangeCalendar:
    def __init__(self, sessions):
        self.sessions = sorted(sessions)

    def is_session(self, target_date):
        return target_date in self.sessions

    def date_to_session(self, target_date, direction="previous"):
        assert direction == "previous"
        sessions = [session for session in self.sessions if session <= target_date]
        if not sessions:
            raise ValueError("no previous session")
        return datetime.combine(sessions[-1], time.min)

    def previous_session(self, session):
        session_date = session.date()
        sessions = [candidate for candidate in self.sessions if candidate < session_date]
        if not sessions:
            raise ValueError("no previous session")
        return datetime.combine(sessions[-1], time.min)


def _expected_session(market, target_date, phase, sessions):
    fake_calendar = _FakeExchangeCalendar(sessions)
    with patch.object(trading_calendar, "_XCALS_AVAILABLE", True), patch.object(
        trading_calendar,
        "xcals",
        SimpleNamespace(get_calendar=lambda _exchange: fake_calendar),
        create=True,
    ):
        return trading_calendar.resolve_historical_daily_bar_date(
            market,
            target_date,
            phase,
        )


def _resolve(
    starts,
    forwards,
    candidates=("first", "second"),
    days=1,
    expected_start_date=date(2024, 1, 5),
):
    return resolve_stock_daily_window(
        stock_repo=_FakeStockRepository(starts, forwards),
        code_candidates=candidates,
        expected_start_date=expected_start_date,
        eval_window_days=days,
    )


def test_newer_partial_window_outranks_stale_complete_window() -> None:
    window = _resolve(
        starts={
            "first": _bar(date(2020, 1, 2), 50.0),
            "second": _bar(date(2024, 1, 5), 100.0),
        },
        forwards={
            "first": [_bar(date(2024, 1, 8), 55.0)],
            "second": [],
        },
    )

    assert window.code == "second"
    assert window.start_bar.date == date(2024, 1, 5)
    assert window.forward_bars == []


def test_newest_start_wins_when_multiple_windows_are_complete() -> None:
    window = _resolve(
        starts={
            "first": _bar(date(2024, 1, 4)),
            "second": _bar(date(2024, 1, 5)),
        },
        forwards={
            "first": [_bar(date(2024, 1, 8))],
            "second": [_bar(date(2024, 1, 8))],
        },
    )

    assert window.code == "second"


def test_all_stale_candidates_return_none() -> None:
    window = _resolve(
        starts={
            "first": _bar(date(2020, 1, 2), 50.0),
            "second": _bar(date(2021, 1, 4), 60.0),
        },
        forwards={
            "first": [_bar(date(2024, 1, 8), 55.0)],
            "second": [_bar(date(2024, 1, 8), 65.0)],
        },
    )

    assert window is None


def test_expected_session_is_not_hidden_by_a_later_partial_bar() -> None:
    window = _resolve(
        starts={
            "first": [
                _bar(date(2024, 1, 5), 100.0),
                _bar(date(2024, 1, 7), 101.0),
            ],
        },
        forwards={"first": [_bar(date(2024, 1, 8), 105.0)]},
        candidates=("first",),
    )

    assert window.start_bar.date == date(2024, 1, 5)
    assert window.start_bar.close == 100.0


def test_weekend_uses_previous_exchange_session() -> None:
    market = trading_calendar.get_market_for_stock(
        normalize_stock_code("600517.SH")
    )
    expected_start_date = _expected_session(
        market,
        date(2024, 1, 7),
        "non_trading",
        [date(2024, 1, 5), date(2024, 1, 8)],
    )

    window = _resolve(
        starts={"first": _bar(date(2024, 1, 5))},
        forwards={"first": [_bar(date(2024, 1, 8))]},
        candidates=("first",),
        expected_start_date=expected_start_date,
    )

    assert market == "cn"
    assert expected_start_date == date(2024, 1, 5)
    assert window.start_bar.date == date(2024, 1, 5)


def test_trading_day_uses_same_exchange_session() -> None:
    market = trading_calendar.get_market_for_stock(
        normalize_stock_code("600517.SH")
    )
    expected_start_date = _expected_session(
        market,
        date(2024, 1, 8),
        "postmarket",
        [date(2024, 1, 5), date(2024, 1, 8)],
    )

    window = _resolve(
        starts={"first": _bar(date(2024, 1, 8))},
        forwards={"first": [_bar(date(2024, 1, 9))]},
        candidates=("first",),
        expected_start_date=expected_start_date,
    )

    assert market == "cn"
    assert expected_start_date == date(2024, 1, 8)
    assert window.start_bar.date == date(2024, 1, 8)


@pytest.mark.parametrize(
    "phase",
    ["premarket", "intraday", "lunch_break", "closing_auction"],
)
def test_open_session_before_close_uses_previous_exchange_session(phase) -> None:
    expected_start_date = _expected_session(
        "cn",
        date(2024, 1, 8),
        phase,
        [date(2024, 1, 5), date(2024, 1, 8)],
    )

    assert expected_start_date == date(2024, 1, 5)


@pytest.mark.parametrize(
    ("target_date", "phase"),
    [
        (date(2024, 1, 8), "unknown"),
        (date(2024, 1, 8), None),
        (date(2024, 1, 8), "non_trading"),
        (date(2024, 1, 7), "premarket"),
        (date(2024, 1, 7), "postmarket"),
    ],
)
def test_unprovable_or_calendar_inconsistent_phase_fails_closed(
    target_date,
    phase,
) -> None:
    expected_start_date = _expected_session(
        "cn",
        target_date,
        phase,
        [date(2024, 1, 5), date(2024, 1, 8)],
    )

    assert expected_start_date is None


def test_same_date_complete_window_outranks_partial_window() -> None:
    window = _resolve(
        starts={
            "first": _bar(date(2024, 1, 5)),
            "second": _bar(date(2024, 1, 5)),
        },
        forwards={
            "first": [],
            "second": [_bar(date(2024, 1, 8))],
        },
    )

    assert window.code == "second"


def test_same_date_tie_preserves_candidate_order() -> None:
    window = _resolve(
        starts={
            "first": _bar(date(2024, 1, 5)),
            "second": _bar(date(2024, 1, 5)),
        },
        forwards={
            "first": [_bar(date(2024, 1, 8))],
            "second": [_bar(date(2024, 1, 8))],
        },
    )

    assert window.code == "first"


def test_partial_fallback_uses_more_bars_for_same_start_date() -> None:
    window = _resolve(
        starts={
            "first": _bar(date(2024, 1, 5)),
            "second": _bar(date(2024, 1, 5)),
        },
        forwards={
            "first": [_bar(date(2024, 1, 8))],
            "second": [
                _bar(date(2024, 1, 8)),
                _bar(date(2024, 1, 9)),
            ],
        },
        days=3,
    )

    assert window.code == "second"
    assert len(window.forward_bars) == 2


@pytest.mark.parametrize("days", [0, -1, 1.5, True, "1", "invalid"])
def test_invalid_window_length_fails_closed(days) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        _resolve(
            starts={"first": _bar(date(2024, 1, 5))},
            forwards={"first": []},
            candidates=("first",),
            days=days,
        )
