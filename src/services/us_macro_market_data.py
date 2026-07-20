"""US macro market snapshot built on the existing Yahoo Finance fetcher."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from data_provider.yfinance_fetcher import YfinanceFetcher

US_MACRO_MARKETS = {
    "sp500": ("^GSPC", "标普500"), "nasdaq_100": ("^NDX", "纳斯达克100"),
    "dow_jones": ("^DJI", "道琼斯工业指数"), "russell_2000": ("^RUT", "罗素2000"),
    "vix": ("^VIX", "VIX"), "dollar_index": ("DX-Y.NYB", "美元指数"),
    "gold": ("GC=F", "黄金"), "crude_oil": ("CL=F", "WTI原油"), "copper": ("HG=F", "铜"),
}


def _pct_change(values: pd.Series, sessions: int) -> float | None:
    if len(values) <= sessions or not values.iloc[-sessions - 1]:
        return None
    return round((float(values.iloc[-1]) / float(values.iloc[-sessions - 1]) - 1) * 100, 3)


def summarize_history(name: str, symbol: str, history: pd.DataFrame) -> dict[str, Any] | None:
    if history.empty or "close" not in history:
        return None
    closes = history["close"].dropna()
    if closes.empty:
        return None
    latest = float(closes.iloc[-1])
    result = {"indicator": name, "symbol": symbol, "value": latest, "observation_date": str(closes.index[-1].date()), "change_1d": _pct_change(closes, 1), "change_5d": _pct_change(closes, 5), "change_20d": _pct_change(closes, 20), "source_name": "Yahoo Finance", "is_delayed": True}
    for period in (20, 50, 200):
        if len(closes) >= period:
            average = float(closes.tail(period).mean())
            result[f"ma_{period}"] = average
            result[f"above_ma_{period}"] = latest >= average
    return result


class USMacroMarketDataService:
    def __init__(self, fetcher: YfinanceFetcher | None = None):
        self.fetcher = fetcher or YfinanceFetcher()

    def fetch(self) -> tuple[list[dict[str, Any]], list[str]]:
        start = (date.today() - timedelta(days=330)).isoformat()
        end = (date.today() + timedelta(days=1)).isoformat()
        data, missing = [], []
        for key, (symbol, _label) in US_MACRO_MARKETS.items():
            try:
                raw = self.fetcher._fetch_raw_data(symbol, start, end)
                item = summarize_history(key, symbol, self.fetcher._normalize_data(raw, symbol))
                if item: data.append(item)
                else: missing.append(key)
            except Exception:
                missing.append(key)
        return data, missing
