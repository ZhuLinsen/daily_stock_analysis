# -*- coding: utf-8 -*-
"""
Regression tests for Hong Kong realtime quote routing.
"""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if "litellm" not in sys.modules:
    sys.modules["litellm"] = MagicMock()
if "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()

from data_provider.base import DataFetcherManager


class _DummyFetcher:
    def __init__(self, name: str, priority: int, result=None):
        self.name = name
        self.priority = priority
        self.result = result
        self.calls = []

    def get_realtime_quote(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class TestHKRealtimeRouting(unittest.TestCase):
    """Ensure HK realtime lookup does not fan out into A-share sources."""

    @patch("src.config.get_config")
    def test_manager_routes_hk_suffix_only_to_akshare_once(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="tencent,akshare_sina,efinance,akshare_em,tushare",
        )

        efinance = _DummyFetcher("EfinanceFetcher", 0, result={"should": "not be called"})
        akshare = _DummyFetcher("AkshareFetcher", 1, result=None)
        tushare = _DummyFetcher("TushareFetcher", 2, result={"should": "not be called"})

        manager = DataFetcherManager(fetchers=[efinance, akshare, tushare])
        quote = manager.get_realtime_quote("1810.HK")

        self.assertIsNone(quote)
        self.assertEqual(akshare.calls, [(("HK01810",), {"source": "hk"})])
        self.assertEqual(efinance.calls, [])
        self.assertEqual(tushare.calls, [])

    @patch("src.config.get_config")
    def test_manager_routes_hk_through_configured_futu_priority(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="tencent,akshare_sina,efinance,akshare_em,tushare",
            futu_hk_realtime_source_priority="futu,akshare,yfinance",
        )
        futu_quote = MagicMock()
        futu_quote.has_basic_data.return_value = True
        futu = _DummyFetcher("FutuFetcher", 0, result=futu_quote)
        akshare = _DummyFetcher("AkshareFetcher", 1, result=None)

        manager = DataFetcherManager(fetchers=[futu, akshare])
        quote = manager.get_realtime_quote("HK01810")

        self.assertIs(quote, futu_quote)
        self.assertEqual(len(futu.calls), 1)
        self.assertEqual(akshare.calls, [])

    @patch("src.config.get_config")
    def test_manager_falls_back_from_futu_to_akshare(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="tencent,akshare_sina,efinance,akshare_em,tushare",
            futu_hk_realtime_source_priority="futu,akshare,yfinance",
        )
        futu = _DummyFetcher("FutuFetcher", 0, result=None)
        akshare_quote = MagicMock()
        akshare_quote.has_basic_data.return_value = True
        akshare = _DummyFetcher("AkshareFetcher", 1, result=akshare_quote)

        manager = DataFetcherManager(fetchers=[futu, akshare])
        quote = manager.get_realtime_quote("HK01810")

        self.assertIs(quote, akshare_quote)
        self.assertEqual(len(futu.calls), 1)
        self.assertEqual(akshare.calls, [(("HK01810",), {"source": "hk"})])
