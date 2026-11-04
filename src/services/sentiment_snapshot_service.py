"""Deterministic, CSMAR-backed A-share close sentiment snapshots."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.data.csmar_daily import CsmarDataset, CsmarSourceError, read_csmar_daily
from src.repositories.sentiment_repo import SentimentRepository


MARKET = "CN_A_MAIN_NORMAL_LIMITED_CSMAR"
DEFINITION_VERSION = "csmar-daily-v1-market-day-streak"


def compute_snapshot(dataset: CsmarDataset, trade_date: date) -> dict[str, Any]:
    """Calculate a target day from its own and earlier market days only."""
    dates = sorted(day for day in dataset.days if day <= trade_date)
    if trade_date not in dataset.days:
        raise CsmarSourceError(f"CSMAR export has no records for {trade_date.isoformat()}")
    if len(dates) < 3:
        raise CsmarSourceError("two earlier market trading dates are required for 1-to-2")
    prior, prior_prior = dates[-2], dates[-3]
    today = dataset.days[trade_date]
    first_board = dataset.days[prior].closed - dataset.days[prior_prior].closed
    promoted = first_board & today.closed

    streak: dict[str, int] = {}
    for day in dates:
        streak = {code: streak.get(code, 0) + 1 for code in dataset.days[day].closed}
    highest = max(streak.values(), default=0)
    highest_codes = sorted(code for code, length in streak.items() if length == highest)
    touched_count = len(today.touched)
    first_count = len(first_board)
    source_issues = {
        day.isoformat(): dict(dataset.days[day].issues)
        for day in dates if dataset.days[day].issues
    }
    target_bad = bool(today.issues)
    promotion_bad = target_bad or bool(dataset.days[prior].issues) or bool(dataset.days[prior_prior].issues)
    streak_truncated = highest >= len(dates)
    closed_plus_broken = touched_count == len(today.closed) + len(today.broken)
    all_checks_pass = not source_issues and not streak_truncated and closed_plus_broken

    metrics = {
        "limit_up_count": None if target_bad else len(today.closed),
        "break_rate": (
            None if target_bad or touched_count == 0
            else len(today.broken) / touched_count
        ),
        "max_consecutive": None if source_issues or streak_truncated else highest,
        "promotion_1_to_2": (
            None if promotion_bad or first_count == 0
            else len(promoted) / first_count
        ),
    }
    components = {
        "limit_up_codes": sorted(today.closed),
        "broken_codes": sorted(today.broken),
        "touched_codes": sorted(today.touched),
        "max_consecutive_codes": highest_codes,
        "prior_first_board_codes": sorted(first_board),
        "promoted_codes": sorted(promoted),
        "break_numerator": None if target_bad else len(today.broken),
        "break_denominator": None if target_bad else touched_count,
        "promotion_numerator": None if promotion_bad else len(promoted),
        "promotion_denominator": None if promotion_bad else first_count,
    }
    return {
        "market": MARKET,
        "trade_date": trade_date,
        "previous_trade_date": prior,
        "definition_version": DEFINITION_VERSION,
        "quality_status": "complete" if all_checks_pass else "partial",
        "metrics": metrics,
        "components": components,
        "provider_trace": {
            "provider": "CSMAR",
            "table": "TRD_Dalyr",
            "source_file": dataset.source_file,
            "as_of_sha256": dataset.as_of_sha256,
            "row_count_as_of": dataset.row_count_as_of,
            "sheet": dataset.sheet_name,
            "dimension_repaired": dataset.advertised_dimension.startswith("A1:A"),
            "actual_columns": dataset.actual_columns,
        },
        "completeness": {
            "scope": "Markettype in (1,4); Trdsta=1; positive volume and LimitUp",
            "streak_rule": "consecutive market trading dates; absence breaks the streak",
            "date_min": dates[0].isoformat(),
            "date_max": trade_date.isoformat(),
            "date_count": len(dates),
            "target_row_count": today.row_count,
            "target_normal_main_count": today.normal_main_count,
            "target_eligible_count": today.eligible_count,
            "target_no_price_limit_excluded": today.no_price_limit_count,
            "no_price_limit_excluded_through_target": sum(
                dataset.days[day].no_price_limit_count for day in dates
            ),
            "source_issues_through_target": source_issues,
            "streak_not_cut_by_source_start": not streak_truncated,
            "closed_plus_broken_equals_touched": closed_plus_broken,
        },
    }


def generate_snapshot(
    session: Session, *, source_zip: Path, trade_date: date,
) -> tuple[str, Any]:
    dataset = read_csmar_daily(source_zip, as_of=trade_date)
    snapshot = compute_snapshot(dataset, trade_date)
    return SentimentRepository(session).save(snapshot)
