"""Fail-closed, date-by-date CSMAR sentiment snapshot backfill."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterator

from sqlalchemy.orm import Session

from src.core.trading_calendar import get_trading_dates
from src.data.csmar_daily import CsmarSourceError, read_csmar_daily
from src.repositories.sentiment_repo import SentimentRepository, SentimentSnapshotConflict
from src.services.sentiment_calendar import (
    CalendarGetter, SentimentCalendarError as BackfillCalendarError,
    trading_sessions as _sessions, validate_and_pad_history as _validate_and_pad_history,
)
from src.services.sentiment_snapshot_service import compute_snapshot


@dataclass(frozen=True)
class BackfillResult:
    trade_date: date
    status: str
    quality_status: str | None = None
    save_action: str | None = None
    message: str | None = None


SessionFactory = Callable[[], Session]


def iter_backfill(
    source_zip: Path,
    *,
    start_date: date,
    end_date: date,
    dry_run: bool,
    session_factory: SessionFactory | None = None,
    calendar_getter: CalendarGetter = get_trading_dates,
) -> Iterator[BackfillResult]:
    """Yield one result per exchange session; never use rows after that session."""
    if start_date > end_date:
        raise ValueError("start-date must not be after end-date")
    if not dry_run and session_factory is None:
        raise ValueError("session_factory is required unless dry-run is enabled")
    target_days = sorted(_sessions(calendar_getter, start_date, end_date))
    for target in target_days:
        try:
            # Deliberately retain the v1 per-day reader and cumulative SHA-256.
            # A shared scan would need an equivalence proof before replacing it.
            dataset = read_csmar_daily(source_zip, as_of=target)
            _validate_and_pad_history(dataset, target, calendar_getter)
            snapshot = compute_snapshot(dataset, target)
            quality = snapshot["quality_status"]
            if dry_run:
                yield BackfillResult(target, "partial" if quality == "partial" else "dry-run", quality)
                continue
            with session_factory() as session:
                action, _ = SentimentRepository(session).save(snapshot)
            yield BackfillResult(
                target, "partial" if quality == "partial" else action,
                quality_status=quality, save_action=action,
            )
        except SentimentSnapshotConflict as exc:
            yield BackfillResult(target, "conflict", message=str(exc))
        except BackfillCalendarError:
            raise
        except CsmarSourceError as exc:
            yield BackfillResult(target, "failed", message=str(exc))
        except Exception as exc:
            # Driver exceptions can contain absolute paths and licensed stock rows.
            yield BackfillResult(target, "failed", message=f"unexpected error ({type(exc).__name__})")


def iter_eastmoney_backfill(
    *, start_date: date, end_date: date, dry_run: bool,
    session_factory: SessionFactory | None = None,
    calendar_getter: CalendarGetter = get_trading_dates,
) -> Iterator[BackfillResult]:
    """Fetch each requested trading session independently from Eastmoney."""
    from src.services.eastmoney_sentiment import build_eastmoney_snapshot

    if start_date > end_date:
        raise ValueError("start-date must not be after end-date")
    if not dry_run and session_factory is None:
        raise ValueError("session_factory is required unless dry-run is enabled")
    for target in sorted(_sessions(calendar_getter, start_date, end_date)):
        try:
            snapshot = build_eastmoney_snapshot(target)
            quality = snapshot["quality_status"]
            if dry_run:
                yield BackfillResult(target, "partial" if quality == "partial" else "dry-run", quality)
                continue
            with session_factory() as session:
                action, _ = SentimentRepository(session).save(snapshot)
            yield BackfillResult(target, "partial" if quality == "partial" else action,
                                 quality_status=quality, save_action=action)
        except SentimentSnapshotConflict as exc:
            yield BackfillResult(target, "conflict", message=str(exc))
        except BackfillCalendarError:
            raise
        except CsmarSourceError as exc:
            yield BackfillResult(target, "failed", message=str(exc))
        except Exception as exc:
            yield BackfillResult(target, "failed", message=f"unexpected error ({type(exc).__name__})")
