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

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("src.config.get_config")
    def test_manager_routes_hk_through_configured_futu_priority(self, mock_get_config, mock_has_ep):
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

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("src.config.get_config")
    def test_manager_falls_back_from_futu_to_akshare(self, mock_get_config, mock_has_ep):
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
        self.assertEqual(akshare.calls, [((("HK01810",), {"source": "hk"}))])
        # 首选源 Futu 失败、次源 AkShare 接管时，应保留 fallback_from 元数据。
        self.assertEqual(getattr(quote, "fallback_from", None), "futu")

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=False)
    @patch("src.config.get_config")
    def test_manager_skips_unconfigured_futu_without_fallback_from(self, mock_get_config, mock_has_ep):
        """An unconfigured Futu source must be skipped, not recorded as the failed primary.

        With FUTU_OPEND_HOST unset, the default HK priority
        (futu,longbridge,akshare,yfinance) must not treat the never-enabled
        futu source as a failed primary: the first successfully enabled
        source's quote should carry no fallback_from at all.
        """
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
        enrich = MagicMock(return_value=akshare_quote)
        manager._enrich_realtime_quote = enrich
        quote = manager.get_realtime_quote("HK01810")

        self.assertIs(quote, akshare_quote)
        # futu is skipped entirely: never called, never recorded as fallback.
        self.assertEqual(futu.calls, [])
        self.assertEqual(akshare.calls, [((("HK01810",), {"source": "hk"}))])
        self.assertEqual(enrich.call_args.kwargs.get("fallback_from"), None)

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("src.config.get_config")
    def test_manager_supplements_partial_futu_quote_from_akshare(self, mock_get_config, mock_has_ep):
        """A partial first-source quote should be supplemented by later sources."""
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="tencent,akshare_sina,efinance,akshare_em,tushare",
            futu_hk_realtime_source_priority="futu,akshare,yfinance",
            realtime_cache_ttl=None,
        )
        futu_quote = MagicMock()
        futu_quote.has_basic_data.return_value = True
        for field in DataFetcherManager._SUPPLEMENT_FIELDS:
            setattr(futu_quote, field, None)
        futu = _DummyFetcher("FutuFetcher", 0, result=futu_quote)

        akshare_quote = MagicMock()
        akshare_quote.has_basic_data.return_value = True
        for field in DataFetcherManager._SUPPLEMENT_FIELDS:
            setattr(akshare_quote, field, 1.86)
        akshare = _DummyFetcher("AkshareFetcher", 1, result=akshare_quote)

        manager = DataFetcherManager(fetchers=[futu, akshare])
        quote = manager.get_realtime_quote("HK00700")

        self.assertIs(quote, futu_quote)
        for field in DataFetcherManager._SUPPLEMENT_FIELDS:
            self.assertEqual(getattr(quote, field), 1.86, field)
        self.assertEqual(len(futu.calls), 1)
        self.assertEqual(akshare.calls, [(("HK00700",), {"source": "hk"})])

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("src.config.get_config")
    def test_manager_does_not_supplement_when_primary_is_complete(self, mock_get_config, mock_has_ep):
        """A complete first-source quote should not trigger extra source calls."""
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="tencent,akshare_sina,efinance,akshare_em,tushare",
            futu_hk_realtime_source_priority="futu,akshare,yfinance",
            realtime_cache_ttl=None,
        )
        futu_quote = MagicMock()
        futu_quote.has_basic_data.return_value = True
        for field in DataFetcherManager._SUPPLEMENT_FIELDS:
            setattr(futu_quote, field, 1.0)
        futu = _DummyFetcher("FutuFetcher", 0, result=futu_quote)
        akshare = _DummyFetcher("AkshareFetcher", 1, result=None)

        manager = DataFetcherManager(fetchers=[futu, akshare])
        quote = manager.get_realtime_quote("HK00700")

        self.assertIs(quote, futu_quote)
        self.assertEqual(len(futu.calls), 1)
        self.assertEqual(akshare.calls, [])
