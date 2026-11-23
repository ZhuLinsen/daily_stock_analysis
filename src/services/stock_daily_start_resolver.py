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


_INTRADAY_EVAL_PHASES = frozenset({"intraday", "lunch_break", "closing_auction"})
_LEGACY_T_MINUS_1_VERSIONS = frozenset({
    "v1",
    "1",
    "1.0",
    "skill-opinion-outcome-v1",
    "decision-signal-v1",
})


def uses_intraday_session_start(engine_version: Optional[str]) -> bool:
    """Return False for explicit legacy v1 engines that preserve T-1 intraday anchor."""
    if engine_version is None:
        return True
    normalized = str(engine_version).strip().lower()
    if not normalized:
        return True
    return normalized not in _LEGACY_T_MINUS_1_VERSIONS


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
    engine_version: Optional[str] = None,
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

    phase = (
        str(phase_summary.get("phase") or "").strip().lower()
        if isinstance(phase_summary, dict)
        else ""
    )
    raw_session_date = (
        phase_summary.get("session_date")
        if isinstance(phase_summary, dict)
        else None
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
        use_intraday_t = uses_intraday_session_start(engine_version)
        # Intraday / lunch / closing-auction analyses already observed session T
        # price action; anchor evaluation at session T close instead of T-1 close
        # so the T-1 -> T intraday move is not counted as forward alpha.
        if use_intraday_t and phase in _INTRADAY_EVAL_PHASES:
            intraday_session = _parse_date(raw_session_date) if raw_session_date else analysis_date
            if (
                intraday_session is not None
                and intraday_session <= analysis_date
                and intraday_session > effective_date
                and resolve_historical_daily_bar_date(
                    identity.market,
                    intraday_session,
                    "postmarket",
                )
                == intraday_session
            ):
                return DailyStockStartResolution(identity, intraday_session, None)
        return DailyStockStartResolution(identity, effective_date, None)

    if uses_intraday_session_start(engine_version) and phase in _INTRADAY_EVAL_PHASES:
        intraday_session = _parse_date(raw_session_date) if raw_session_date else analysis_date
        if intraday_session is None or intraday_session > analysis_date:
            return DailyStockStartResolution(
                identity,
                None,
                "unresolvable_expected_start_date",
            )
        expected_start_date = resolve_historical_daily_bar_date(
            identity.market,
            intraday_session,
            "postmarket",
        )
    else:
        expected_start_date = resolve_historical_daily_bar_date(
            identity.market,
            analysis_date,
            phase or None,
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
