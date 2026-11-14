"""Validate historical market sessions for sentiment snapshot calculations."""

from datetime import date
from typing import Callable

from src.core.trading_calendar import get_trading_dates
from src.data.csmar_daily import CsmarDataset, CsmarDay, CsmarSourceError


class SentimentCalendarError(CsmarSourceError):
    """A reliable exchange calendar is required for sentiment snapshots."""


CalendarGetter = Callable[[str, date, date], object]


def trading_sessions(calendar_getter: CalendarGetter, start: date, end: date) -> set[date]:
    labels = calendar_getter("cn", start, end)
    if labels is None:
        raise SentimentCalendarError(f"CN exchange calendar unavailable for {start} through {end}")
    return {label.date() if hasattr(label, "date") else label for label in labels}


def validate_and_pad_history(
    dataset: CsmarDataset,
    target: date,
    calendar_getter: CalendarGetter = get_trading_dates,
) -> None:
    """Mark missing sessions without changing the v1 raw-data fingerprint."""
    first = min(dataset.days)
    expected = trading_sessions(calendar_getter, first, target)
    if target not in expected:
        raise CsmarSourceError(f"{target} is not a CN trading session")
    unexpected = set(dataset.days) - expected
    if unexpected:
        raise CsmarSourceError(f"CSMAR contains non-session dates through {target}: {sorted(unexpected)}")
    for missing in expected - set(dataset.days):
        pool = CsmarDay()
        pool.issues["missing_trading_date"] = 1
        pool.global_issues = True
        dataset.days[missing] = pool
