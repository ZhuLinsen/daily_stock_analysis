# -*- coding: utf-8 -*-
"""HiThink names, ticker directory, hot-stock list, and limit-up pool."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from .hithink_fetcher import HiThinkFetcher, HiThinkRequestError

logger = logging.getLogger(__name__)

_SEARCH_PATH = "/api/meta/tickers/search"
_LIST_PATH = "/api/meta/tickers/list"
_HOT_PATH = "/api/a-share/special-data/hot-stock-list"
_LIMIT_UP_PATH = "/api/a-share/special-data/limit-up-pool"
_LIST_PAGE_SIZE = 1000
_LIST_MAX_PAGES = 6
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def stock_name(fetcher: HiThinkFetcher, stock_code: str) -> Optional[str]:
    try:
        thscode, code = fetcher._thscode(stock_code)
    except Exception:
        return None
    payload = fetcher._request(
        _SEARCH_PATH,
        {"q": thscode, "asset_type": "a-share", "limit": 5},
        capability="stock_list",
    )
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not isinstance(data.get("item"), list):
        raise HiThinkRequestError("HiThink ticker search response is invalid")
    for item in data["item"]:
        if not isinstance(item, dict):
            continue
        if str(item.get("ticker") or "") == code and str(item.get("asset_type") or "") == "a-share":
            name = str(item.get("name") or "").strip()
            return name or None
    return None


def stock_list(fetcher: HiThinkFetcher) -> pd.DataFrame:
    """A-share directory used by ``DataFetcherManager.batch_get_stock_names``.

    The analysis prefetch calls ``get_stock_name`` per code and does not load
    this full directory. A missing list entitlement disables only later
    directory pages, not quotes or financials.
    """
    rows: List[Dict[str, str]] = []
    complete = False
    truncated = False
    for page in range(_LIST_MAX_PAGES):
        if not fetcher.is_available("stock_list"):
            truncated = True
            break
        try:
            payload = fetcher._request(
                _LIST_PATH,
                {"asset_type": "a-share", "limit": _LIST_PAGE_SIZE, "offset": page * _LIST_PAGE_SIZE},
                capability="stock_list",
            )
        except HiThinkRequestError as exc:
            if exc.permission:
                fetcher._remember_error(str(exc), directory_only=True)
                truncated = True
                break
            raise
        data = payload.get("data") or {}
        if not isinstance(data, dict) or not isinstance(data.get("item"), list):
            raise HiThinkRequestError("HiThink ticker list response is invalid")
        items = data["item"]
        for item in items:
            if not isinstance(item, dict):
                continue
            code = str(item.get("ticker") or "").strip()
            name = str(item.get("name") or "").strip()
            if code and name and str(item.get("asset_type") or "") == "a-share":
                rows.append({"code": code, "name": name})
        if len(items) < _LIST_PAGE_SIZE:
            complete = True
            break
    else:
        truncated = True
        logger.warning(
            "[HiThinkFetcher] stock list stopped at the page cap: pages=%s page_size=%s",
            _LIST_MAX_PAGES,
            _LIST_PAGE_SIZE,
        )
    frame = pd.DataFrame(rows, columns=["code", "name"])
    frame.attrs["complete"] = complete and not truncated
    frame.attrs["truncated"] = truncated
    return frame


def hot_stocks(fetcher: HiThinkFetcher, n: int = 10) -> Optional[List[Dict[str, Any]]]:
    limit = min(max(int(n), 1), 100)
    payload = fetcher._request(_HOT_PATH, {"period": "day", "limit": limit})
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not isinstance(data.get("item"), list):
        raise HiThinkRequestError("HiThink hot stock response is invalid")
    rows: List[Dict[str, Any]] = []
    for item in data["item"]:
        if not isinstance(item, dict):
            continue
        rows.append({
            "rank": item.get("rank"),
            "code": str(item.get("ticker") or "").strip(),
            "name": str(item.get("name") or "").strip(),
            "price": None,
            "change_pct": None,
            "heat": item.get("heat"),
            "source": "HiThink热股榜",
        })
    _fill_hot_prices(fetcher, rows)
    return rows[:limit] or None


def _fill_hot_prices(fetcher: HiThinkFetcher, rows: List[Dict[str, Any]]) -> None:
    """The hot-stock endpoint has no price. Fill it from the A-share snapshot."""
    pending = [row for row in rows if row.get("code")]
    for offset in range(0, len(pending), 10):
        batch = pending[offset:offset + 10]
        by_code: Dict[str, Dict[str, Any]] = {}
        symbols: List[str] = []
        for row in batch:
            try:
                thscode, _code = fetcher._thscode(str(row["code"]))
            except Exception:
                continue
            symbols.append(thscode)
            by_code[thscode.upper()] = row
        if not symbols:
            continue
        try:
            payload = fetcher._request("/api/a-share/prices/snapshot", {"thscodes": ",".join(symbols)})
        except HiThinkRequestError as exc:
            logger.info("[HiThinkFetcher] hot-stock snapshot skipped: %s", exc)
            return
        data = payload.get("data") or {}
        if not isinstance(data, dict) or not isinstance(data.get("item"), list):
            return
        for item in data["item"]:
            if not isinstance(item, dict):
                continue
            row = by_code.get(str(item.get("thscode") or "").upper())
            if row is None:
                continue
            price = _number(item.get("last_price"))
            change_pct = _number(item.get("price_change_ratio_pct"))
            if price is not None:
                row["price"] = price
            if change_pct is not None:
                row["change_pct"] = change_pct


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def limit_up_pool(
    fetcher: HiThinkFetcher,
    date: Optional[str] = None,
    n: int = 20,
) -> Optional[List[Dict[str, Any]]]:
    size = min(max(int(n), 1), 200)
    params: Dict[str, Any] = {
        "page": 1,
        "size": size,
        "sort_field": "continue_day_cnt",
        "sort_dir": "desc",
    }
    if date:
        moment = datetime.strptime(date, "%Y%m%d").replace(tzinfo=_SHANGHAI)
        params["date_ms"] = int(moment.timestamp() * 1000)
    payload = fetcher._request(_LIMIT_UP_PATH, params)
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not isinstance(data.get("item"), list):
        raise HiThinkRequestError("HiThink limit-up pool response is invalid")
    rows: List[Dict[str, Any]] = []
    for item in data["item"]:
        if not isinstance(item, dict):
            continue
        rows.append({
            "code": str(item.get("ticker") or "").strip(),
            "name": str(item.get("name") or "").strip(),
            "change_pct": item.get("price_change_ratio_pct"),
            "price": item.get("last_price"),
            "amount": None,
            "turnover_rate": None,
            "seal_amount": item.get("seal_money"),
            "first_limit_time": "",
            "last_limit_time": "",
            "limit_up_time": item.get("limit_up_time") or "",
            "break_count": None,
            "limit_stat": item.get("continue_day_text") or "",
            "consecutive_boards": item.get("continue_day_cnt"),
            "industry": "",
            "limit_up_reason": item.get("limit_up_reason") or "",
        })
    return rows[:size] or None


def log_reference_failure(path: str, exc: Exception) -> None:
    code = getattr(exc, "code", None)
    logger.warning("[HiThinkFetcher] reference request failed: path=%s code=%s", path, code)
