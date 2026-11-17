# -*- coding: utf-8 -*-
"""消息面汇总 · 去重与时间窗层（issue #2184）：窗口判定（[start, end)）、
每日一份持久化 claim（发送失败释放后窗口内可补发）与条目去重合并。"""

from __future__ import annotations

import logging
import sqlite3
import time as time_module
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time as time_of_day
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from src.services.news_digest_sources import NewsDigestEntry, normalize_url

logger = logging.getLogger(__name__)

DEFAULT_NEWS_DIGEST_PREMARKET_WINDOW = "08:00-09:15"
DEFAULT_NEWS_DIGEST_OFFDAY_WINDOW = "09:00-18:00"


@dataclass
class NewsDigestContext:
    """一次汇总的时段上下文（窗口语义 [start, end)，按进程本地时区解释）。"""

    kind: str  # premarket | weekend | holiday
    date: date
    window_start: time_of_day
    window_end: time_of_day
    region: str = "cn"


def _resolve_window(raw: Any, default_raw: str, label: str) -> Tuple[time_of_day, time_of_day]:
    """解析 "HH:MM-HH:MM"（非法或 start>=end 含跨午夜视为非法），fail-open 回退默认窗口。"""
    def _parse(text: Any) -> Optional[Tuple[time_of_day, time_of_day]]:
        raw_text = str(text or "").strip()
        if "-" not in raw_text:
            return None
        start_text, _, end_text = raw_text.partition("-")
        try:
            h1, m1 = str(start_text).strip().split(":")
            h2, m2 = str(end_text).strip().split(":")
            start, end = time_of_day(int(h1), int(m1)), time_of_day(int(h2), int(m2))
        except (ValueError, TypeError):
            return None
        return (start, end) if start < end else None

    window = _parse(raw)
    if window is None:
        logger.warning("NEWS_DIGEST %s窗口配置非法(%r)，回退默认窗口 %s", label, raw, default_raw)
        window = _parse(default_raw)
    return window  # 默认窗口串由常量保证合法


def _default_is_trading_day(check_date: date) -> bool:
    """默认交易日判定：交易日历不可用时按交易日处理（fail-open）。"""
    try:
        from src.core.trading_calendar import is_market_open

        return bool(is_market_open("cn", check_date))
    except Exception as exc:  # noqa: BLE001 - 日历不可用按交易日处理
        logger.warning("NEWS_DIGEST 交易日历不可用，按交易日处理: %s", exc)
        return True


def resolve_news_digest_context(
    now: datetime,
    *,
    region: str = "cn",
    premarket_window: str = DEFAULT_NEWS_DIGEST_PREMARKET_WINDOW,
    offday_window: str = DEFAULT_NEWS_DIGEST_OFFDAY_WINDOW,
    is_trading_day: Optional[Callable[[date], bool]] = None,
) -> Optional[NewsDigestContext]:
    """判定 now 是否处于汇总窗口（周末 → 节假日 → 交易日盘前）；不在窗口返回 None。"""
    if now.weekday() >= 5:
        kind, window = "weekend", offday_window
        default_window, label = DEFAULT_NEWS_DIGEST_OFFDAY_WINDOW, "非交易日"
    else:
        trading = bool((is_trading_day or _default_is_trading_day)(now.date()))
        kind = "premarket" if trading else "holiday"
        window = premarket_window if trading else offday_window
        default_window = DEFAULT_NEWS_DIGEST_PREMARKET_WINDOW if trading else DEFAULT_NEWS_DIGEST_OFFDAY_WINDOW
        label = "盘前" if trading else "非交易日"
    bounds = _resolve_window(window, default_window, label)
    if bounds[0] <= now.time() < bounds[1]:
        return NewsDigestContext(
            kind=kind, date=now.date(),
            window_start=bounds[0], window_end=bounds[1], region=region,
        )
    return None


def claim_news_digest_date(database_path: Any, date_key: str, region: str = "cn", context: str = "") -> bool:
    """按自然日原子占位（独立表 news_digest_claims）；已被占用返回 False。"""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path), timeout=10)) as connection:
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS news_digest_claims ("
                "date_key TEXT PRIMARY KEY, region TEXT NOT NULL, "
                "context TEXT NOT NULL, created_at REAL NOT NULL)"
            )
            cursor = connection.execute(
                "INSERT OR IGNORE INTO news_digest_claims "
                "(date_key, region, context, created_at) VALUES (?, ?, ?, ?)",
                (date_key, region, context, time_module.time()),
            )
            return cursor.rowcount == 1


def release_news_digest_date(database_path: Any, date_key: str, region: str = "cn", context: str = "") -> bool:
    """best-effort 释放当日 claim（失败补发用）；表/库不存在返回 False。"""
    path = Path(database_path)
    if not path.exists():
        return False
    try:
        with closing(sqlite3.connect(str(path), timeout=10)) as connection:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM news_digest_claims WHERE date_key = ?", (date_key,)
                )
                return int(cursor.rowcount or 0) >= 1
    except sqlite3.Error as exc:
        logger.warning("NEWS_DIGEST 释放 claim 失败 date_key=%s: %s", date_key, exc)
        return False


def merge_entries(entries: List[NewsDigestEntry], *, limit: int) -> List[NewsDigestEntry]:
    """去重合并：规范化 URL 为主键，总量截 limit（下限钳 1）。"""
    keep = max(1, int(limit))
    seen_urls: set = set()
    merged: List[NewsDigestEntry] = []
    for entry in entries:
        if len(merged) >= keep:
            break
        url_key = normalize_url(entry.url)
        if url_key is not None and url_key in seen_urls:
            continue
        if url_key is not None:
            seen_urls.add(url_key)
        merged.append(entry)
    return merged
