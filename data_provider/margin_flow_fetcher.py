# -*- coding: utf-8 -*-
"""Fetcher for extended Market Light dimension data.

Provides market-level inputs that feed the five extended Market Light
dimensions (margin_balance, northbound_flow, turnover_quantile,
limit_ratio, continuous_board).

Every function degrades gracefully: on any failure it returns ``None``,
so ``MarketAnalyzer._build_market_light_scores`` marks the corresponding
dimension as ``available=False`` and the snapshot remains valid.

Data sources (all via akshare, no token required):
- 融资融券余额: ``ak.stock_margin_sse`` + ``ak.stock_margin_szse``
- 北向资金净流入: ``ak.stock_hsgt_hist_em`` (T+1, may be NaN since 2024 reform)
- 成交额历史: ``ak.stock_zh_index_daily`` (上证 + 深证)
- 连板高度: ``ak.stock_zt_pool_strong_em``
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)

_MARGIN_LOOKBACK_DAYS = 12  # calendar days, to ensure >= 5 trading days
_NORTHBOUND_LOOKBACK_DAYS = 12
_TURNOVER_HISTORY_DAYS = 90  # calendar days, to ensure >= 60 trading days
_YI = 1e8  # 元 -> 亿元


def _to_date_str(dt: datetime, fmt: str = "%Y%m%d") -> str:
    return dt.strftime(fmt)


def fetch_margin_balance_recent(trading_days: int = 5) -> Optional[List[float]]:
    """Return total A-share margin balance for the recent N trading days.

    Each value is the combined SSE+SZSE 融资融券余额 in 亿元. Returns ``None``
    when both exchanges fail or fewer than 2 valid rows are available.
    """
    try:
        import akshare as ak
    except Exception as exc:  # pragma: no cover - import guard
        logger.debug("margin_balance: akshare import failed: %s", exc)
        return None

    end = datetime.now()
    start = end - timedelta(days=_MARGIN_LOOKBACK_DAYS)
    sse_values = _fetch_margin_sse(start, end)
    szse_values = _fetch_margin_szse(start, end)
    if sse_values is None and szse_values is None:
        logger.info("margin_balance: both exchanges returned no data")
        return None

    # Align by date (both lists are ordered oldest->newest with date+value tuples)
    merged = _merge_margin_by_date(sse_values, szse_values)
    if len(merged) < 2:
        logger.info("margin_balance: only %d aligned days, need >= 2", len(merged))
        return None
    return merged[-trading_days:]


def _fetch_margin_sse(start: datetime, end: datetime) -> Optional[List[tuple]]:
    try:
        import akshare as ak

        df = ak.stock_margin_sse(
            start_date=_to_date_str(start), end_date=_to_date_str(end)
        )
        if df is None or df.empty:
            return None
        col_date = "信用交易日期"
        col_balance = "融资融券余额"
        if col_date not in df.columns or col_balance not in df.columns:
            logger.warning("margin_sse: unexpected columns %s", list(df.columns))
            return None
        df = df[[col_date, col_balance]].dropna()
        result = [
            (str(row[col_date]), float(row[col_balance]) / _YI)
            for _, row in df.iterrows()
        ]
        result.sort(key=lambda x: x[0])
        return result
    except Exception as exc:
        logger.debug("margin_sse fetch failed: %s", exc)
        return None


def _fetch_margin_szse(start: datetime, end: datetime) -> Optional[List[tuple]]:
    try:
        import akshare as ak

        df = ak.stock_margin_szse(
            start_date=_to_date_str(start, "%Y-%m-%d"),
            end_date=_to_date_str(end, "%Y-%m-%d"),
        )
        if df is None or df.empty:
            return None
        # 深交所 columns: 信用交易日期, 融资余额, 融券余额, 融资融券余额
        col_date = "信用交易日期"
        col_balance = "融资融券余额"
        if col_date not in df.columns or col_balance not in df.columns:
            # fallback: 融资余额 + 融券余额
            if "融资余额" in df.columns and "融券余额" in df.columns:
                df = df[[col_date, "融资余额", "融券余额"]].dropna() if col_date in df.columns else None
                if df is None:
                    return None
                result = [
                    (str(row[col_date]), (float(row["融资余额"]) + float(row["融券余额"])) / _YI)
                    for _, row in df.iterrows()
                ]
                result.sort(key=lambda x: x[0])
                return result
            logger.warning("margin_szse: unexpected columns %s", list(df.columns))
            return None
        df = df[[col_date, col_balance]].dropna()
        result = [
            (str(row[col_date]), float(row[col_balance]) / _YI)
            for _, row in df.iterrows()
        ]
        result.sort(key=lambda x: x[0])
        return result
    except Exception as exc:
        logger.debug("margin_szse fetch failed: %s", exc)
        return None


def _merge_margin_by_date(
    sse: Optional[List[tuple]], szse: Optional[List[tuple]]
) -> List[float]:
    """Merge SSE + SZSE margin by aligned date, returning total balance list."""
    if sse is None and szse is None:
        return []
    if sse is None:
        return [v for _, v in szse]
    if szse is None:
        return [v for _, v in sse]
    szse_map = {d: v for d, v in szse}
    merged: List[float] = []
    for date, sse_val in sse:
        szse_val = szse_map.get(date)
        if szse_val is not None:
            merged.append(sse_val + szse_val)
    if not merged:
        # dates don't align; fall back to whichever is longer
        return [v for _, v in sse] if len(sse) >= len(szse) else [v for _, v in szse]
    return merged


def fetch_northbound_flow_recent(trading_days: int = 5) -> Optional[List[float]]:
    """Return recent N days of northbound net inflow (亿元).

    Returns ``None`` when the API fails or all recent values are NaN
    (northbound real-time data was restricted in 2024; only T+1 historical
    data is available, and even that may be NaN for recent days).
    """
    try:
        import akshare as ak

        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        if df is None or df.empty:
            return None
        col_flow = "当日成交净买额"
        if col_flow not in df.columns:
            logger.warning("northbound: unexpected columns %s", list(df.columns))
            return None
        df = df[["日期", col_flow]].dropna()
        if df.empty:
            return None
        values = [float(v) / _YI for v in df[col_flow].tolist()]
        if len(values) < 2:
            return None
        return values[-trading_days:]
    except Exception as exc:
        logger.debug("northbound fetch failed: %s", exc)
        return None


def fetch_turnover_history(trading_days: int = 60) -> Optional[List[float]]:
    """Return recent N trading days of total A-share turnover (亿元).

    Combines Shanghai (sh000001) and Shenzhen (sz399001) index turnover.
    """
    try:
        import akshare as ak

        sh = _fetch_index_turnover("sh000001")
        sz = _fetch_index_turnover("sz399001")
        if sh is None and sz is None:
            return None
        if sh is None:
            return sz[-trading_days:] if sz else None
        if sz is None:
            return sh[-trading_days:] if sh else None
        # align by length (both are oldest->newest)
        min_len = min(len(sh), len(sz))
        combined = [sh[-(min_len - i)] + sz[-(min_len - i)] for i in range(min_len)]
        return combined[-trading_days:]
    except Exception as exc:
        logger.debug("turnover_history fetch failed: %s", exc)
        return None


def _fetch_index_turnover(symbol: str) -> Optional[List[float]]:
    try:
        import akshare as ak

        df = ak.stock_zh_index_daily(symbol=symbol)
        if df is None or df.empty:
            return None
        # column name varies; prefer 成交额 then amount then volume
        col = None
        for candidate in ("成交额", "amount", "money"):
            if candidate in df.columns:
                col = candidate
                break
        if col is None:
            logger.warning("turnover %s: no amount column in %s", symbol, list(df.columns))
            return None
        df = df[[col]].dropna()
        values = [float(v) / _YI for v in df[col].tolist()]
        return values
    except Exception as exc:
        logger.debug("turnover %s fetch failed: %s", symbol, exc)
        return None


def fetch_continuous_board_height() -> Optional[int]:
    """Return today's max consecutive limit-up board height (连板高度).

    Parses the 涨停统计 column (e.g. ``"3/3"``) from the strong-stock pool
    and returns the maximum first number. Returns ``None`` on any failure.
    """
    try:
        import akshare as ak

        today = _to_date_str(datetime.now())
        df = ak.stock_zt_pool_strong_em(date=today)
        if df is None or df.empty:
            return None
        col = "涨停统计"
        if col not in df.columns:
            logger.warning("continuous_board: column %s missing in %s", col, list(df.columns))
            return None
        max_height = 0
        for raw in df[col].dropna():
            try:
                height = int(str(raw).split("/")[0])
                if height > max_height:
                    max_height = height
            except (ValueError, IndexError):
                continue
        return max_height if max_height > 0 else None
    except Exception as exc:
        logger.debug("continuous_board fetch failed: %s", exc)
        return None
