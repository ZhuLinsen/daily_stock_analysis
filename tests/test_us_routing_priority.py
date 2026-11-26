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


class TestUSRoutingWithFutu:
    """Futu joins the US chain by numeric priority instead of stealing the pinned slot."""

    def test_default_futu_priority_sits_after_equal_priority_sources(self):
        manager = _manager(_defaults() + [_F("FutuFetcher", 2)])
        order = manager._order_us_sources_by_priority(DEFAULT_US_ORDER + ["FutuFetcher"], pin_first=False)
        assert order == ["FinnhubFetcher", "FutuFetcher", "AlphaVantageFetcher", "YfinanceFetcher", "LongbridgeFetcher"]

    def test_longbridge_preferred_keeps_futu_out_of_first_slot(self):
        manager = _manager(_defaults() + [_F("FutuFetcher", 2)])
        order = manager._order_us_sources_by_priority(
            ["LongbridgeFetcher", "FinnhubFetcher", "AlphaVantageFetcher", "YfinanceFetcher", "FutuFetcher"],
            pin_first=True,
        )
        assert order[0] == "LongbridgeFetcher"
        assert "FutuFetcher" in order[1:]

    def test_high_futu_priority_moves_it_last(self):
        manager = _manager(_defaults() + [_F("FutuFetcher", 99)])
        order = manager._order_us_sources_by_priority(DEFAULT_US_ORDER + ["FutuFetcher"], pin_first=False)
        assert order[-1] == "FutuFetcher"


def test_env_example_has_no_conflict_markers() -> None:
    """配置模板不得包含未解决的 git 冲突标记。"""
    content = Path(".env.example").read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("<<<<<<<"), f"conflict marker: {line!r}"
        assert not stripped.startswith(">>>>>>>"), f"conflict marker: {line!r}"
        assert stripped != "=======", f"conflict marker: {line!r}"


class TestUSRealtimeRoutingByPriority:
    """美股实时链必须与日 K 共用同一套数值优先级语义（FUTU_PRIORITY）。"""

    def _realtime_order(self, fetchers, *, prefer_lb=False, is_us_index=False, futu_enabled=True):
        manager = _manager(fetchers)
        manager._futu_realtime_enabled = lambda: futu_enabled
        return manager._us_realtime_source_order(prefer_lb=prefer_lb, is_us_index=is_us_index)

    def test_default_priority_lets_futu_lead_without_longbridge(self):
        order = self._realtime_order(_defaults() + [_F("FutuFetcher", 2)])
        assert order == ["FutuFetcher", "YfinanceFetcher", "LongbridgeFetcher"]

    def test_raised_futu_priority_demotes_it_in_realtime(self):
        """FUTU_PRIORITY=99 时，实时也必须先走 YFinance（blocker OR-COM-cfe2098f）。"""
        order = self._realtime_order(_defaults() + [_F("FutuFetcher", 99)])
        assert order == ["YfinanceFetcher", "LongbridgeFetcher", "FutuFetcher"]

    def test_longbridge_preferred_keeps_anchor_and_demotes_futu(self):
        order = self._realtime_order(
            _defaults() + [_F("FutuFetcher", 99)], prefer_lb=True
        )
        assert order == ["LongbridgeFetcher", "YfinanceFetcher", "FutuFetcher"]

    def test_unconfigured_futu_is_not_in_realtime_chain(self):
        order = self._realtime_order(_defaults() + [_F("FutuFetcher", 2)], futu_enabled=False)
        assert order == ["YfinanceFetcher", "LongbridgeFetcher"]

    def test_us_index_realtime_is_yfinance_only(self):
        order = self._realtime_order(
            _defaults() + [_F("FutuFetcher", 2)], is_us_index=True
        )
        assert order == ["YfinanceFetcher"]
