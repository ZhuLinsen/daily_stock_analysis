# -*- coding: utf-8 -*-
"""Manager-level routing tests for TickFlow integration."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


from data_provider.base import DataFetcherManager
from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from src.config import Config


class _FakeTickFlowFetcher:
    name = "TickFlowFetcher"
    priority = 2

    def __init__(self):
        self.quote_calls = []
        self.prefetch_quote_calls = []
        self.prefetch_daily_calls = []

    def get_realtime_quote(self, stock_code):
        self.quote_calls.append(stock_code)
        return UnifiedRealtimeQuote(
            code="600519",
            name="TickFlowName",
            price=10.0,
            change_pct=1.0,
            source=RealtimeSource.TICKFLOW,
        )

    def prefetch_realtime_quotes(self, stock_codes, batch_size=None):
        self.prefetch_quote_calls.append((list(stock_codes), batch_size))
        return len(stock_codes)

    def prefetch_daily_klines(self, stock_codes, days=30):
        self.prefetch_daily_calls.append((list(stock_codes), days))
        return len(stock_codes)


class _FailingDailyFetcher:
    name = "TickFlowFetcher"
    priority = 0

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        from data_provider.base import DataFetchError

        raise DataFetchError("TickFlow daily K-line response may be truncated by count")


class _FallbackDailyFetcher:
    name = "FallbackFetcher"
    priority = 1

    def __init__(self):
        self.calls = []

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        self.calls.append((stock_code, start_date, end_date, days))
        return pd.DataFrame(
            [
                {
                    "code": stock_code,
                    "date": "2024-01-02",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.5,
                    "volume": 1000.0,
                    "amount": 10000.0,
                    "pct_chg": 0.0,
                }
            ]
        )


class TestTickFlowManagerRouting(unittest.TestCase):
    def _manager(self, fetcher):
        return DataFetcherManager(fetchers=[fetcher])

    def test_realtime_priority_tickflow_routes_to_tickflow_fetcher(self):
        fetcher = _FakeTickFlowFetcher()
        manager = self._manager(fetcher)
        config = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="tickflow,tencent",
            realtime_cache_ttl=600,
        )

        with patch("src.config.get_config", return_value=config):
            quote = manager.get_realtime_quote("600519")

        self.assertEqual(quote.source, RealtimeSource.TICKFLOW)
        self.assertEqual(fetcher.quote_calls, ["600519"])

    def test_realtime_prefetch_uses_tickflow_only_when_early_priority(self):
        fetcher = _FakeTickFlowFetcher()
        manager = self._manager(fetcher)
        config = SimpleNamespace(
            prefetch_realtime_quotes=True,
            enable_realtime_quote=True,
            realtime_source_priority="tickflow,tencent,akshare_sina",
            tickflow_batch_size=50,
        )

        with patch("src.config.get_config", return_value=config):
            count = manager.prefetch_realtime_quotes(["600519", "000001", "300750", "000858", "601318"])

        self.assertEqual(count, 5)
        self.assertEqual(fetcher.prefetch_quote_calls[0][1], 50)

    def test_daily_prefetch_delegates_to_tickflow_fetcher(self):
        fetcher = _FakeTickFlowFetcher()
        manager = self._manager(fetcher)

        count = manager.prefetch_daily_klines(["600519", "000001"], days=30)

        self.assertEqual(count, 2)
        self.assertEqual(fetcher.prefetch_daily_calls, [(["600519", "000001"], 30)])

    def test_daily_data_falls_back_when_tickflow_reports_incomplete_nonempty_data(self):
        tickflow = _FailingDailyFetcher()
        fallback = _FallbackDailyFetcher()
        manager = DataFetcherManager(fetchers=[tickflow, fallback])

        df, source = manager.get_daily_data("600519", start_date="2020-01-01", end_date="2026-05-10")

        self.assertEqual(source, "FallbackFetcher")
        self.assertEqual(len(df), 1)
        self.assertEqual(len(fallback.calls), 1)

    def test_tickflow_priority_is_read_for_new_instances_after_module_import(self):
        from data_provider.tickflow_fetcher import TickFlowFetcher

        with patch.dict(os.environ, {"TICKFLOW_PRIORITY": "7"}, clear=False):
            first = TickFlowFetcher(api_key="sk-test")
        with patch.dict(os.environ, {"TICKFLOW_PRIORITY": "1"}, clear=False):
            second = TickFlowFetcher(api_key="sk-test")

        self.assertEqual(first.priority, 7)
        self.assertEqual(second.priority, 1)

    def test_config_loads_tickflow_priority(self):
        with patch.dict(os.environ, {"TICKFLOW_PRIORITY": "0"}, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.tickflow_priority, 0)

    def test_tickflow_api_key_does_not_auto_inject_realtime_priority(self):
        with patch.dict(os.environ, {"TICKFLOW_API_KEY": "tk-test"}, clear=True):
            self.assertEqual(
                Config._resolve_realtime_source_priority(),
                "tencent,akshare_sina,efinance,akshare_em",
            )


if __name__ == "__main__":
    unittest.main()
