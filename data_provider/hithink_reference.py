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
    rows: List[Dict[str, str]] = []
    for page in range(_LIST_MAX_PAGES):
        payload = fetcher._request(
            _LIST_PATH,
            {"asset_type": "a-share", "limit": _LIST_PAGE_SIZE, "offset": page * _LIST_PAGE_SIZE},
        )
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
            break
    return pd.DataFrame(rows, columns=["code", "name"])


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
    return rows[:limit] or None


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
            "first_limit_time": item.get("limit_up_time") or "",
            "last_limit_time": "",
            "break_count": None,
            "limit_stat": item.get("continue_day_text") or "",
            "consecutive_boards": item.get("continue_day_cnt"),
            "industry": item.get("limit_up_reason") or "",
        })
    return rows[:size] or None


def log_reference_failure(path: str, exc: Exception) -> None:
    code = getattr(exc, "code", None)
    logger.warning("[HiThinkFetcher] reference request failed: path=%s code=%s", path, code)
