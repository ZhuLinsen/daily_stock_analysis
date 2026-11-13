# -*- coding: utf-8 -*-
"""Aggregating fetcher for market sentiment snapshots (issue #1939 Wave 3).

Fetches every metric-group data source for one trade date and returns them
together with a per-group ``provider_trace``. Fail-open by design:

- every source call is wrapped in its own try/except — one failing source
  never affects the others and ``fetch_all`` never raises;
- pool APIs run through ``_akshare_call_with_timeout`` (the repo's
  subprocess-timeout convention) exactly like existing fetchers;
- each trace entry is ``{metric_group, provider, api, params, status,
  elapsed_ms, error, fetched_at}`` with status ok|timeout|error|empty;
- beyond-retention pool dates return a silent EMPTY DataFrame (W1 probe1b:
  T-15 and older) — judged by row count, recorded as ``empty`` and handed
  back as ``None`` so downstream metrics mark the group missing;
- an empty limit-down pool is a VALID market state (0 limit-down stocks,
  W1 probe2: T-1 had 5 rows, 0 is common) — passed through as an empty
  DataFrame with status ``ok``;
- reused calls (``get_market_stats`` / ``get_sector_rankings``) already
  swallow their own errors and return ``None`` on total failure; that is
  recorded as status ``error``.

Wave 4 orchestration calls this once per snapshot run; it performs no
metric computation and no persistence.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from data_provider.akshare_fetcher import (
    _akshare_call_with_timeout,
    AkshareFetcher,
)

logger = logging.getLogger(__name__)

DEFAULT_POOL_TIMEOUT_SECONDS = 45.0

TRACE_STATUS_OK = "ok"
TRACE_STATUS_TIMEOUT = "timeout"
TRACE_STATUS_ERROR = "error"
TRACE_STATUS_EMPTY = "empty"

API_ZT_POOL = "ak.stock_zt_pool_em"
API_DTGC_POOL = "ak.stock_zt_pool_dtgc_em"
API_ZBGC_POOL = "ak.stock_zt_pool_zbgc_em"
API_PREVIOUS_POOL = "ak.stock_zt_pool_previous_em"
API_MARKET_STATS = "AkshareFetcher.get_market_stats"
API_SECTOR_RANKINGS = "AkshareFetcher.get_sector_rankings"


def _trace_entry(
    metric_group: str,
    api: str,
    params: Dict[str, Any],
    status: str,
    elapsed_ms: int,
    error: Optional[str],
) -> Dict[str, Any]:
    return {
        "metric_group": metric_group,
        "provider": "akshare",
        "api": api,
        "params": params,
        "status": status,
        "elapsed_ms": int(elapsed_ms),
        "error": error,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


class MarketSentimentFetcher:
    """Aggregates all market-sentiment data sources for one trade date.

    ``trade_date`` / ``prev_trade_date`` use the akshare-native ``YYYYMMDD``
    format (pool APIs take it verbatim). ``prev_trade_date=None`` skips only
    the previous-day pool fetch; ``previous_em(date=trade_date)`` is
    self-contained (W1: it already returns T-1 limit-ups' day-T behaviour).
    """

    def __init__(
        self,
        akshare_fetcher: Optional[AkshareFetcher] = None,
        timeout: Optional[float] = None,
    ):
        self._ak = akshare_fetcher if akshare_fetcher is not None else AkshareFetcher()
        self.timeout_seconds = (
            float(timeout) if timeout is not None else DEFAULT_POOL_TIMEOUT_SECONDS
        )

    # -- public API ---------------------------------------------------------

    def fetch_all(
        self,
        trade_date: str,
        prev_trade_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch every group source; never raises (fail-open)."""
        trace: List[Dict[str, Any]] = []

        stats = self._fetch_reused(
            API_MARKET_STATS,
            lambda: self._ak.get_market_stats(),
            params={},
            metric_groups=("breadth", "turnover"),
            trace=trace,
        )

        sector_rankings = self._fetch_reused(
            API_SECTOR_RANKINGS,
            lambda: self._ak.get_sector_rankings(n=5),
            params={"n": 5},
            metric_groups=("sector",),
            trace=trace,
        )

        today_pool = self._fetch_pool(
            API_ZT_POOL, trade_date,
            metric_groups=("limit_up_pool", "broken_pool"),
            trace=trace,
        )
        limit_down_pool = self._fetch_pool(
            API_DTGC_POOL, trade_date,
            metric_groups=("limit_up_pool",),
            allow_empty=True,
            trace=trace,
        )
        broken_pool = self._fetch_pool(
            API_ZBGC_POOL, trade_date,
            metric_groups=("broken_pool",),
            trace=trace,
        )

        prev_pool: Optional[pd.DataFrame] = None
        if prev_trade_date:
            prev_pool = self._fetch_pool(
                API_ZT_POOL, prev_trade_date,
                metric_groups=("promotion", "prev_feedback"),
                trace=trace,
            )

        previous_pool = self._fetch_pool(
            API_PREVIOUS_POOL, trade_date,
            metric_groups=("prev_feedback",),
            trace=trace,
        )

        return {
            "stats": stats,
            "sector_rankings": sector_rankings,
            "today_pool": today_pool,
            "prev_pool": prev_pool,
            "broken_pool": broken_pool,
            "limit_down_pool": limit_down_pool,
            "previous_pool": previous_pool,
            "provider_trace": trace,
        }

    # -- internals ----------------------------------------------------------

    def _polite(self) -> None:
        """Reuse the AkshareFetcher rate-limit/UA conventions (no-ops in stubs)."""
        try:
            self._ak._set_random_user_agent()
            self._ak._enforce_rate_limit()
        except Exception:  # pragma: no cover - politeness must never break fetch
            logger.debug("[MarketSentiment] politeness hooks failed", exc_info=True)

    def _fetch_pool(
        self,
        api_name: str,
        date: str,
        metric_groups: Tuple[str, ...],
        trace: List[Dict[str, Any]],
        allow_empty: bool = False,
    ) -> Optional[pd.DataFrame]:
        """Fetch one pool API via the subprocess-timeout convention.

        Returns the DataFrame (empty DF preserved only when ``allow_empty``),
        or ``None`` on timeout / error / beyond-retention empty result.
        Appends one trace entry per serviced metric group.
        """
        import akshare as ak

        func = getattr(ak, api_name.split(".", 1)[1])
        params = {"date": date}
        started = time.monotonic()
        status = TRACE_STATUS_OK
        error: Optional[str] = None
        df: Optional[pd.DataFrame] = None
        try:
            self._polite()
            raw = _akshare_call_with_timeout(
                func,
                date=date,
                timeout=self.timeout_seconds,
                call_name=api_name,
            )
            if raw is None or (hasattr(raw, "empty") and raw.empty):
                if allow_empty:
                    df = raw if raw is not None else pd.DataFrame()
                else:
                    # W1 §3: beyond-retention dates silently return an empty
                    # DataFrame — judge by row count, mark empty, hand back None.
                    status = TRACE_STATUS_EMPTY
            else:
                df = raw
        except TimeoutError as exc:
            status = TRACE_STATUS_TIMEOUT
            error = f"TimeoutError: {exc}"
            logger.warning(
                "[MarketSentiment] api=%s date=%s status=timeout error=%s",
                api_name, date, exc,
            )
        except Exception as exc:
            status = TRACE_STATUS_ERROR
            error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "[MarketSentiment] api=%s date=%s status=error error=%s",
                api_name, date, exc,
            )
        elapsed_ms = (time.monotonic() - started) * 1000
        for group in metric_groups:
            trace.append(_trace_entry(group, api_name, params, status, elapsed_ms, error))
        return df

    def _fetch_reused(
        self,
        api_name: str,
        call,
        params: Dict[str, Any],
        metric_groups: Tuple[str, ...],
        trace: List[Dict[str, Any]],
    ) -> Any:
        """Wrap a reused AkshareFetcher call (internal fallbacks preserved).

        These helpers already swallow errors and return ``None`` on total
        failure, which is recorded as status ``error``.
        """
        started = time.monotonic()
        status = TRACE_STATUS_OK
        error: Optional[str] = None
        try:
            result = call()
            if result is None:
                status = TRACE_STATUS_ERROR
                error = "no data after internal fallbacks"
        except Exception as exc:  # reused helpers should not raise, but stay fail-open
            status = TRACE_STATUS_ERROR
            error = f"{type(exc).__name__}: {exc}"
            result = None
            logger.warning(
                "[MarketSentiment] api=%s status=error error=%s", api_name, exc,
            )
        elapsed_ms = (time.monotonic() - started) * 1000
        for group in metric_groups:
            trace.append(_trace_entry(group, api_name, params, status, elapsed_ms, error))
        return result
