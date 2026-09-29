# -*- coding: utf-8 -*-
"""Resolve one authoritative stock identity and local-daily start date."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from src.core.trading_calendar import resolve_historical_daily_bar_date
from src.market_phase_summary import (
    extract_market_phase_summary,
    rebuild_market_phase_summary_for_stock_code,
)
from src.services.stock_code_utils import (
    DailyStockIdentity,
    resolve_daily_stock_identity,
)


@dataclass(frozen=True)
class DailyStockStartResolution:
    """Authoritative identity and start date before local bars are queried."""

    identity: Optional[DailyStockIdentity]
    expected_start_date: Optional[date]
    failure_reason: Optional[str]
    legacy_backtest_start_date: Optional[date] = None

    @property
    def backtest_start_date(self) -> Optional[date]:
        """Return the authoritative start or Backtest-only legacy fallback."""

        return self.expected_start_date or self.legacy_backtest_start_date


def resolve_stock_daily_start(
    *,
    stock_code: Optional[str],
    context_snapshot: Any,
    analysis_date: Optional[date],
) -> DailyStockStartResolution:
    """Resolve stock identity, validated phase context, and expected start."""

    phase_summary = extract_market_phase_summary(context_snapshot)
    persisted_market = (
        str(phase_summary.get("market") or "").strip().lower()
        if isinstance(phase_summary, dict)
        else ""
    )
    identity = resolve_daily_stock_identity(
        stock_code,
        market_hint=persisted_market or None,
    )
    if identity is None:
        return DailyStockStartResolution(None, None, "invalid_stock_code")
    if analysis_date is None:
        return DailyStockStartResolution(identity, None, "missing_analysis_date")

    if persisted_market != identity.market:
        phase_summary = rebuild_market_phase_summary_for_stock_code(
            identity.normalized_code,
            context_snapshot,
        )
        persisted_market = (
            str(phase_summary.get("market") or "").strip().lower()
            if isinstance(phase_summary, dict)
            else ""
        )
        if persisted_market != identity.market:
            return DailyStockStartResolution(
                identity,
                None,
                "invalid_market_phase_context",
            )

    effective_date_value = (
        phase_summary.get("effective_daily_bar_date")
        if isinstance(phase_summary, dict)
        else None
    )
    if effective_date_value:
        effective_date = _parse_date(effective_date_value)
        if effective_date is None:
            return DailyStockStartResolution(
                identity,
                None,
                "invalid_effective_daily_bar_date",
            )
        if effective_date > analysis_date:
            return DailyStockStartResolution(
                identity,
                None,
                "future_effective_daily_bar_date",
            )
        if (
            resolve_historical_daily_bar_date(
                identity.market,
                effective_date,
                "postmarket",
            )
            != effective_date
        ):
            return DailyStockStartResolution(
                identity,
                None,
                "invalid_effective_daily_bar_date",
                legacy_backtest_start_date=effective_date,
            )
        return DailyStockStartResolution(identity, effective_date, None)

    phase = (
        phase_summary.get("phase")
        if isinstance(phase_summary, dict)
        else None
    )
    expected_start_date = resolve_historical_daily_bar_date(
        identity.market,
        analysis_date,
        phase,
    )
    if expected_start_date is None:
        return DailyStockStartResolution(
            identity,
            None,
            "unresolvable_expected_start_date",
        )
    return DailyStockStartResolution(identity, expected_start_date, None)


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None
