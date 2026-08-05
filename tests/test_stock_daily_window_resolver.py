# -*- coding: utf-8 -*-
"""Direct contract tests for coherent local daily-window resolution."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

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


def test_candidates_without_exact_start_return_none() -> None:
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
