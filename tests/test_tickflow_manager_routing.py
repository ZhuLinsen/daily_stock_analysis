# -*- coding: utf-8 -*-
"""Manager-level routing tests for TickFlow integration."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_tickflow_api_key_does_not_auto_inject_realtime_priority(self):
        with patch.dict(os.environ, {"TICKFLOW_API_KEY": "tk-test"}, clear=True):
            self.assertEqual(
                Config._resolve_realtime_source_priority(),
                "tencent,akshare_sina,efinance,akshare_em",
            )


if __name__ == "__main__":
    unittest.main()
