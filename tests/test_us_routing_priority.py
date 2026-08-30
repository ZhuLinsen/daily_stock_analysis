# -*- coding: utf-8 -*-
"""Tests: US daily routing consumes per-source fetcher priorities."""

from __future__ import annotations

import threading
from pathlib import Path

from data_provider.base import DataFetcherManager

DEFAULT_US_ORDER = ["FinnhubFetcher", "AlphaVantageFetcher", "YfinanceFetcher", "LongbridgeFetcher"]


class _F:
    def __init__(self, name, priority):
        self.name, self.priority = name, priority


def _manager(fetchers):
    manager = DataFetcherManager.__new__(DataFetcherManager)
    manager._fetchers = list(fetchers)
    manager._fetchers_lock = threading.RLock()
    manager._fetchers_by_name = {f.name: f for f in fetchers}
    manager._fetcher_call_locks = {}
    manager._fetcher_call_locks_lock = manager._fetchers_lock
    manager._stock_name_cache = {}
    manager._stock_name_cache_lock = manager._fetchers_lock
    return manager


def _defaults():
    return [
        _F("FinnhubFetcher", 2),
        _F("AlphaVantageFetcher", 3),
        _F("YfinanceFetcher", 4),
        _F("LongbridgeFetcher", 5),
    ]


class TestUSRoutingByPriority:
    def test_default_priorities_keep_builtin_order(self):
        manager = _manager(_defaults())
        order = manager._order_us_sources_by_priority(list(DEFAULT_US_ORDER), pin_first=False)
        assert order == DEFAULT_US_ORDER

    def test_yfinance_priority_zero_promotes_it_first(self):
        fetchers = _defaults()
        fetchers[2] = _F("YfinanceFetcher", 0)  # YFINANCE_PRIORITY=0
        manager = _manager(fetchers)
        order = manager._order_us_sources_by_priority(list(DEFAULT_US_ORDER), pin_first=False)
        assert order[0] == "YfinanceFetcher"
        assert order[1:] == ["FinnhubFetcher", "AlphaVantageFetcher", "LongbridgeFetcher"]

    def test_longbridge_preferred_stays_pinned_first(self):
        manager = _manager(_defaults())
        order = manager._order_us_sources_by_priority(
            ["LongbridgeFetcher", "FinnhubFetcher", "AlphaVantageFetcher", "YfinanceFetcher"],
            pin_first=True,
        )
        assert order[0] == "LongbridgeFetcher"
        assert order[1:] == ["FinnhubFetcher", "AlphaVantageFetcher", "YfinanceFetcher"]

    def test_us_index_keeps_yfinance_pinned(self):
        manager = _manager(_defaults())
        order = manager._order_us_sources_by_priority(["YfinanceFetcher", "FinnhubFetcher"], pin_first=True)
        assert order == ["YfinanceFetcher", "FinnhubFetcher"]


def test_env_example_has_no_conflict_markers() -> None:
    """配置模板不得包含未解决的 git 冲突标记。"""
    content = Path(".env.example").read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("<<<<<<<"), f"conflict marker: {line!r}"
        assert not stripped.startswith(">>>>>>>"), f"conflict marker: {line!r}"
        assert stripped != "=======", f"conflict marker: {line!r}"
