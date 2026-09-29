# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""US equity snapshot via yfinance.

US snapshot provider for the screening L1 pipeline. Fetches a configurable
equity universe and returns the standard snapshot DataFrame schema.

HK is not supported yet: there is no HK universe source or ticker
configuration path, so ``market="hk"`` is rejected at the pipeline level
rather than silently screening the US pool.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

logger = logging.getLogger(__name__)

_SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

_DEFAULT_US_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B",
    "AVGO", "JPM", "LLY", "V", "MA", "UNH", "XOM", "COST", "HD", "PG",
    "JNJ", "ABBV", "WMT", "NFLX", "BAC", "KO", "CRM", "CVX", "MRK",
    "PEP", "AMD", "TMO", "LIN", "ACN", "CSCO", "MCD", "ABT", "ADBE",
    "WFC", "GE", "DHR", "TXN", "PM", "ISRG", "MS", "NEE", "INTU",
    "DIS", "QCOM", "CAT", "NOW",
]


def fetch_us_universe(source: str = "auto") -> list[str]:
    """Return a list of US equity tickers.

    Sources:
        sp500   — scrape S&P 500 from Wikipedia
        env     — read SCREENING_US_TICKERS (comma-separated)
        default — hardcoded top-50 US large-caps
        auto    — try sp500 → env → default
    """
    src = source.lower()
    if src == "auto":
        for s in ("sp500", "env", "default"):
            try:
                tickers = fetch_us_universe(s)
                if tickers:
                    logger.info("US universe from %s: %d tickers", s, len(tickers))
                    return tickers
            except Exception as e:
                logger.debug("US universe source %s failed: %s", s, e)
        return list(_DEFAULT_US_UNIVERSE)

    if src == "sp500":
        return _fetch_sp500_tickers()
    elif src == "env":
        raw = os.getenv("SCREENING_US_TICKERS", "").strip()
        if not raw:
            raise ValueError("SCREENING_US_TICKERS not set")
        return [t.strip() for t in raw.split(",") if t.strip()]
    elif src == "default":
        return list(_DEFAULT_US_UNIVERSE)
    else:
        raise ValueError(f"Unknown US universe source: {source}")


def _fetch_sp500_tickers() -> list[str]:
    tables = pd.read_html(_SP500_WIKI_URL)
    for tbl in tables:
        if "Symbol" in tbl.columns:
            return sorted(tbl["Symbol"].dropna().str.strip().str.replace(".", "-", regex=False).tolist())
    raise RuntimeError("Could not find Symbol column in S&P 500 Wikipedia table")


def fetch_us_snapshot(
    tickers: list[str] | None = None,
    *,
    universe_source: str = "auto",
    max_workers: int = 8,
) -> pd.DataFrame:
    """Fetch a US equity snapshot in the screening schema.

    Uses yfinance to fetch current data for each ticker. Returns a
    DataFrame matching the standard snapshot columns: code, name, price,
    change_pct, amount, total_mv, pe_ratio, pb_ratio, volume_ratio,
    turnover_rate, industry.
    """
    import yfinance as yf

    if tickers is None:
        tickers = fetch_us_universe(universe_source)

    logger.info("Fetching US snapshot for %d tickers", len(tickers))

    hist_end = pd.Timestamp.now().normalize()
    hist_start = hist_end - pd.Timedelta(days=30)
    data = yf.download(
        tickers,
        start=hist_start.strftime("%Y-%m-%d"),
        end=hist_end.strftime("%Y-%m-%d"),
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    rows = []

    def _process_ticker(ticker: str) -> dict | None:
        try:
            if len(tickers) == 1:
                hist = data.copy()
                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = hist.columns.droplevel("Ticker")
            else:
                if ticker not in data.columns.get_level_values(0):
                    return None
                hist = data[ticker].copy()
            if hist.empty:
                return None

            hist = hist[hist["Close"].notna()]
            if len(hist) < 2:
                return None

            latest = hist.iloc[-1]
            prev = hist.iloc[-2]
            price = float(latest["Close"])
            prev_close = float(prev["Close"])
            volume = float(latest["Volume"])
            change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

            vol_20d = float(hist["Volume"].tail(20).mean())
            volume_ratio = (volume / vol_20d) if vol_20d > 0 else 1.0

            info = yf.Ticker(ticker).fast_info
            market_cap = getattr(info, "market_cap", None) or 0
            shares = getattr(info, "shares", None) or 0
            turnover_rate = (volume / shares * 100) if shares > 0 else 0.0

            return {
                "code": ticker,
                "name": ticker,
                "price": price,
                "change_pct": round(change_pct, 2),
                "amount": round(volume * price, 0),
                "total_mv": market_cap,
                "circ_mv": market_cap,
                "pe_ratio": None,
                "pb_ratio": None,
                "volume_ratio": round(volume_ratio, 2),
                "turnover_rate": round(turnover_rate, 4),
                "industry": "",
            }
        except Exception as e:
            logger.debug("Failed to process %s: %s", ticker, e)
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_process_ticker, t): t for t in tickers}
        for future in as_completed(futures):
            result = future.result()
            if result:
                rows.append(result)

    if not rows:
        raise RuntimeError("yfinance returned no valid data for any ticker")

    df = pd.DataFrame(rows)

    numeric_cols = [
        "price", "change_pct", "amount", "total_mv", "circ_mv",
        "pe_ratio", "pb_ratio", "volume_ratio", "turnover_rate",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["price"])
    df = df[df["price"] > 0]

    _enrich_info_fields(df)

    df.attrs["snapshot_source"] = "yfinance"
    logger.info("US snapshot: %d rows from yfinance", len(df))
    return df


def _enrich_info_fields(df: pd.DataFrame) -> None:
    """Best-effort enrichment of pe_ratio, pb_ratio, industry from yfinance info."""
    import yfinance as yf

    needs_pe = df["pe_ratio"].isna().sum() > len(df) * 0.5
    if not needs_pe:
        return

    for idx in df.index:
        ticker = df.at[idx, "code"]
        try:
            info = yf.Ticker(ticker).info
            if pd.isna(df.at[idx, "pe_ratio"]) or df.at[idx, "pe_ratio"] == 0:
                df.at[idx, "pe_ratio"] = info.get("trailingPE")
            if pd.isna(df.at[idx, "pb_ratio"]) or df.at[idx, "pb_ratio"] == 0:
                df.at[idx, "pb_ratio"] = info.get("priceToBook")
            if not df.at[idx, "industry"]:
                df.at[idx, "industry"] = info.get("industry", "")
            if not df.at[idx, "name"] or df.at[idx, "name"] == ticker:
                df.at[idx, "name"] = info.get("shortName", ticker)
        except Exception:
            pass


def fetch_daily_history_yfinance(
    ticker: str,
    *,
    lookback_days: int = 120,
) -> pd.DataFrame:
    """Fetch daily OHLCV history for a US ticker via yfinance.

    Returns a DataFrame with columns: date, open, high, low, close, volume
    matching the schema expected by the daily enrichment logic.
    """
    import yfinance as yf

    end = pd.Timestamp.now().normalize()
    start = end - pd.Timedelta(days=max(lookback_days * 2, 180))
    hist = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
    )
    if hist is None or hist.empty:
        raise RuntimeError(f"yfinance daily history empty for {ticker}")

    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.droplevel("Ticker")

    hist = hist.tail(max(lookback_days, 30)).copy()
    hist = hist.rename(columns={
        "Open": "开盘", "High": "最高", "Low": "最低",
        "Close": "收盘", "Volume": "成交量",
    })
    hist.index.name = "日期"
    hist = hist.reset_index()
    return hist
