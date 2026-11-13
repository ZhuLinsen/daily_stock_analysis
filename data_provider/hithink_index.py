# -*- coding: utf-8 -*-
"""HiThink index quotes, index daily bars, and industry/concept rankings.

Index history is not part of the fixed A-share index route. Callers use it
only after Tencent, AkShare, TickFlow, and YFinance have failed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .base import STANDARD_COLUMNS, DataFetchError
from .hithink_fetcher import HiThinkFetcher, HiThinkRequestError

logger = logging.getLogger(__name__)

_SNAPSHOT_PATH = "/api/a-share-index/prices/snapshot"
_HISTORICAL_PATH = "/api/a-share-index/prices/historical"
_CATALOG_PATH = "/api/a-share-index/catalog/ths-index-list"
_RANK_BATCH = 10
_RANK_MAX_SYMBOLS = 120
_MAIN_INDICES = (
    ("000001.SH", "sh000001", "上证指数"),
    ("399001.SZ", "sz399001", "深证成指"),
    ("399006.SZ", "sz399006", "创业板指"),
    ("000688.SH", "sh000688", "科创50"),
    ("000016.SH", "sh000016", "上证50"),
    ("000300.SH", "sh000300", "沪深300"),
)


def main_indices(fetcher: HiThinkFetcher, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
    if region != "cn":
        return None
    payload = fetcher._request(_SNAPSHOT_PATH, {"thscodes": ",".join(item[0] for item in _MAIN_INDICES)})
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not isinstance(data.get("item"), list):
        raise HiThinkRequestError("HiThink index snapshot response is invalid")
    by_code = {
        str(item.get("thscode") or "").upper(): item
        for item in data["item"]
        if isinstance(item, dict)
    }
    rows: List[Dict[str, Any]] = []
    for thscode, code, name in _MAIN_INDICES:
        item = by_code.get(thscode)
        if item is None:
            continue
        price = fetcher_number(item.get("last_price"))
        if price is None or price <= 0:
            continue
        prev_close = fetcher_number(item.get("prev_price"))
        high = fetcher_number(item.get("high_price"))
        low = fetcher_number(item.get("low_price"))
        amplitude = None
        if prev_close and prev_close > 0 and high is not None and low is not None:
            amplitude = (high - low) / prev_close * 100
        rows.append({
            "code": code,
            "name": name,
            "current": price,
            "change": fetcher_number(item.get("price_change")),
            "change_pct": fetcher_number(item.get("price_change_ratio_pct")),
            "open": fetcher_number(item.get("open_price")),
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "volume": fetcher_number(item.get("volume")),
            "amount": fetcher_number(item.get("turnover")),
            "amplitude": amplitude,
        })
    return rows or None


def index_daily_data(
    fetcher: HiThinkFetcher,
    thscode: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    days: int = 30,
) -> pd.DataFrame:
    symbol = str(thscode or "").strip().upper()
    if not symbol or "," in symbol:
        raise DataFetchError("HiThink index history accepts one thscode")
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if start_date is None:
        start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    start_date = _clamp_five_year_start(start_date, end_date)
    payload = fetcher._request(
        _HISTORICAL_PATH,
        {
            "thscode": symbol,
            "interval": "1d",
            "start": fetcher._date_to_ms(start_date),
            "end": fetcher._date_to_ms(end_date, end_of_day=True),
        },
    )
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise HiThinkRequestError("HiThink index historical response is invalid")
    if "adjust" in data and data.get("adjust") is not None:
        raise HiThinkRequestError("HiThink index historical response has an unexpected adjustment")
    if "interval" in data and data.get("interval") not in (None, "1d"):
        raise HiThinkRequestError("HiThink index historical response is not daily")
    raw = fetcher._bars_frame(data.get("item"), thscode=symbol)
    return _normalize_index_bars(raw, symbol)


def rankings(fetcher: HiThinkFetcher, tag: str, n: int = 5) -> Optional[Tuple[List[Dict], List[Dict]]]:
    catalog = fetcher._request(_CATALOG_PATH, {"tag": tag})
    data = catalog.get("data") or {}
    if not isinstance(data, dict) or not isinstance(data.get("item"), list):
        raise HiThinkRequestError("HiThink index catalog response is invalid")
    symbols = [
        (str(item.get("thscode") or ""), str(item.get("name") or ""))
        for item in data["item"]
        if isinstance(item, dict) and item.get("thscode") and item.get("name")
    ]
    if len(symbols) > _RANK_MAX_SYMBOLS:
        logger.info(
            "[HiThinkFetcher] %s ranking scans the first %d of %d catalog entries",
            tag,
            _RANK_MAX_SYMBOLS,
            len(symbols),
        )
        symbols = symbols[:_RANK_MAX_SYMBOLS]
    quotes: List[Dict[str, Any]] = []
    names = {thscode: name for thscode, name in symbols}
    for offset in range(0, len(symbols), _RANK_BATCH):
        batch = [thscode for thscode, _name in symbols[offset:offset + _RANK_BATCH]]
        payload = fetcher._request(_SNAPSHOT_PATH, {"thscodes": ",".join(batch)})
        body = payload.get("data") or {}
        if not isinstance(body, dict) or not isinstance(body.get("item"), list):
            raise HiThinkRequestError("HiThink index snapshot response is invalid")
        for item in body["item"]:
            if not isinstance(item, dict):
                continue
            change_pct = fetcher_number(item.get("price_change_ratio_pct"))
            thscode = str(item.get("thscode") or "")
            if change_pct is None or thscode not in names:
                continue
            quotes.append({"name": names[thscode], "change_pct": change_pct})
    if not quotes:
        return None
    ordered = sorted(quotes, key=lambda row: row["change_pct"], reverse=True)
    limit = max(1, int(n))
    return ordered[:limit], list(reversed(ordered[-limit:]))


def fetcher_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _clamp_five_year_start(start_date: str, end_date: str) -> str:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    earliest = today.replace(year=today.year - 5)
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    if start < earliest:
        logger.info("[HiThinkFetcher] index history start clamped to the documented 5-year window")
        return earliest.strftime("%Y-%m-%d")
    return start_date


def _normalize_index_bars(raw: pd.DataFrame, thscode: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=["code", *STANDARD_COLUMNS])
    result = pd.DataFrame({
        "date": raw["date"],
        "open": pd.to_numeric(raw["open_price"], errors="coerce"),
        "high": pd.to_numeric(raw["high_price"], errors="coerce"),
        "low": pd.to_numeric(raw["low_price"], errors="coerce"),
        "close": pd.to_numeric(raw["close_price"], errors="coerce"),
        "volume": pd.to_numeric(raw["volume"], errors="coerce"),
        "amount": pd.to_numeric(raw["turnover"], errors="coerce"),
    })
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    result = result.dropna(subset=["date", "open", "high", "low", "close", "volume"])
    result = result[result["close"] > 0]
    result = result.sort_values("date").drop_duplicates("date")
    previous = result["close"].shift(1)
    result["pct_chg"] = ((result["close"] / previous.where(previous > 0)) - 1) * 100
    result["code"] = thscode
    return result[["code", *STANDARD_COLUMNS]].reset_index(drop=True)
