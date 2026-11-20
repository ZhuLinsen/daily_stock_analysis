# -*- coding: utf-8 -*-
"""Hot-top10 data-source adapter: fetch/normalize the theme hot list through
the existing ``MarketHotspotService``. Selection is unified across buckets
(active themes / leading industries / leading concepts): candidates are
de-duplicated by name, sorted by change percentage (missing values last) and
only then truncated (r1 OR-COR-a7e7c3a3: sequential per-bucket fill could
evict higher-ranked concepts on negative-industry days)."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

CN_MARKET_TIMEZONE = "Asia/Shanghai"


def shanghai_now() -> datetime:
    """Current wall clock in ``Asia/Shanghai`` — the CN market data domain
    clock (Tushare's 15:30 cut-off runs on it, ``trading_calendar`` and
    ``tushare_fetcher`` key their dates on it). All hot-top10 day decisions
    (schedule gate, dedup marker, report file names) key on this clock so a
    host in another timezone cannot fire the tick at its local 15:35 — i.e.
    before the Shanghai data cut-off — and book the previous trading day's
    list as today's delivery (OR-COR-3e7f490e)."""
    try:
        return datetime.now(ZoneInfo(CN_MARKET_TIMEZONE))
    except Exception as exc:  # noqa: BLE001 - tz problems must not break the run
        logger.warning("[HotTop10] 上海时区不可用，回退主机时钟: %s", exc)
        return datetime.now()


def hot_top10_data_date() -> str:
    """The hot-list data date (``YYYY-MM-DD``) per the CN market clock."""
    return shanghai_now().date().isoformat()


def is_cn_trading_day_today() -> bool:
    """Whether the CN market is open today (fail-open when unsure)."""
    try:
        from src.core.trading_calendar import get_open_markets_today

        return "cn" in get_open_markets_today()
    except Exception as exc:  # noqa: BLE001 - calendar problems must not break the run
        logger.warning("[HotTop10] 交易日判断失败，fail-open 视为交易日: %s", exc)
        return True


def collect_hot_list_items(
    count: int,
    hotspot_service: Any = None,
) -> Optional[List[Dict[str, Any]]]:
    """Fetch and normalize the hot list; ``None`` when unusable."""
    if hotspot_service is None:
        from src.services.market_hotspot_service import MarketHotspotService

        hotspot_service = MarketHotspotService()

    try:
        payload = hotspot_service.get_hotspots(market="cn", limit=count)
    except Exception as exc:  # noqa: BLE001 - provider failures fail open
        logger.warning("[HotTop10] 热榜数据获取异常: %s", exc)
        return None
    if not isinstance(payload, dict):
        return None

    candidates: List[Dict[str, Any]] = []
    seen_names = set()
    for bucket, default_kind in (
        ("active_themes", None),
        ("leading_industries", "industry"),
        ("leading_concepts", "concept"),
    ):
        raw_items = payload.get(bucket)
        if not isinstance(raw_items, list):
            continue
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            candidates.append({
                "name": name,
                "code": str(entry.get("code") or "").strip(),
                "change_pct": entry.get("change_pct"),
                "kind": str(entry.get("source") or default_kind or "theme"),
                "phase": str(entry.get("phase") or "unknown"),
                "reason": str(entry.get("reason") or "").strip(),
            })
    if not candidates:
        return None
    candidates.sort(key=lambda item: (
        (0, -float(item["change_pct"])) if isinstance(item.get("change_pct"), (int, float)) else (1, 0.0)
    ))
    items = candidates[:max(1, int(count))]
    for index, item in enumerate(items, 1):
        item["rank"] = index
    return items


def format_change_pct(value: Any) -> str:
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "无数据"
