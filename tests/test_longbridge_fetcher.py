# -*- coding: utf-8 -*-
"""
Unit tests for LongbridgeFetcher integration.

Real API / credentials: use ``tests/longbridge_live_smoke.py`` (not this file).

Verifies:
1. Symbol conversion logic (AAPL -> AAPL.US, HK00700 -> 0700.HK)
2. get_realtime_quote builds correct UnifiedRealtimeQuote with computed fields
3. _supplement_from_longbridge merges missing fields into yfinance quote
4. Graceful degradation when credentials are missing
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock, PropertyMock
from dataclasses import dataclass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.longbridge_fetcher import (
    LongbridgeFetcher,
    _to_longbridge_symbol,
    _is_us_code,
    _is_hk_code,
)
from data_provider.realtime_types import UnifiedRealtimeQuote, RealtimeSource


class TestSymbolConversion(unittest.TestCase):
    """Test internal stock code -> Longbridge symbol conversion."""

    def test_us_stock(self):
        self.assertEqual(_to_longbridge_symbol("AAPL"), "AAPL.US")
        self.assertEqual(_to_longbridge_symbol("TSLA"), "TSLA.US")
        self.assertEqual(_to_longbridge_symbol("NVDA"), "NVDA.US")
        self.assertEqual(_to_longbridge_symbol("GLD"), "GLD.US")

    def test_us_stock_already_suffixed(self):
        self.assertEqual(_to_longbridge_symbol("AAPL.US"), "AAPL.US")

    def test_hk_stock_with_prefix(self):
        self.assertEqual(_to_longbridge_symbol("HK00700"), "0700.HK")
        self.assertEqual(_to_longbridge_symbol("HK09988"), "9988.HK")
        self.assertEqual(_to_longbridge_symbol("HK01810"), "1810.HK")

    def test_hk_stock_pure_digits(self):
        self.assertEqual(_to_longbridge_symbol("00700"), "0700.HK")
        self.assertEqual(_to_longbridge_symbol("09988"), "9988.HK")

    def test_hk_stock_already_suffixed(self):
        self.assertEqual(_to_longbridge_symbol("0700.HK"), "0700.HK")

    def test_a_share_returns_none(self):
        self.assertIsNone(_to_longbridge_symbol("600519"))
        self.assertIsNone(_to_longbridge_symbol("000001"))

    def test_code_detection(self):
        self.assertTrue(_is_us_code("AAPL"))
        self.assertTrue(_is_us_code("TSLA"))
        self.assertFalse(_is_us_code("600519"))
        self.assertTrue(_is_hk_code("HK00700"))
        self.assertTrue(_is_hk_code("00700"))
        self.assertFalse(_is_hk_code("AAPL"))


class TestLongbridgeFetcherNoCredentials(unittest.TestCase):
    """Verify graceful degradation when credentials are absent."""

    def setUp(self):
        self.fetcher = LongbridgeFetcher()
        self.fetcher._available = False

    def test_returns_none_without_creds(self):
        result = self.fetcher.get_realtime_quote("AAPL")
        self.assertIsNone(result)

    def test_is_available_false(self):
        self.assertFalse(self.fetcher._is_available())


class TestLongbridgeFetcherMocked(unittest.TestCase):
    """Test get_realtime_quote with mocked Longbridge SDK."""

    def _make_fetcher_with_mock_ctx(self):
        fetcher = LongbridgeFetcher()
        fetcher._available = True
        mock_ctx = MagicMock()
        fetcher._ctx = mock_ctx
        return fetcher, mock_ctx

    def _make_mock_quote(self, **kwargs):
        q = MagicMock()
        defaults = {
            "last_done": "253.79",
            "prev_close": "246.63",
            "open": "247.91",
            "high": "255.48",
            "low": "247.10",
            "volume": 49549600,
            "turnover": "12575000000",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(q, k, v)
        return q

    def _make_mock_static(self, **kwargs):
        s = MagicMock()
        defaults = {
            "name_cn": "苹果",
            "name_en": "Apple Inc.",
            "circulating_shares": 15000000000,
            "total_shares": 16000000000,
            "eps_ttm": "6.08",
            "bps": "4.40",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(s, k, v)
        return s

    def test_realtime_quote_basic(self):
        """Verify computed fields: turnover_rate, pe_ratio, etc."""
        fetcher, ctx = self._make_fetcher_with_mock_ctx()
        ctx.quote.return_value = [self._make_mock_quote()]
        ctx.static_info.return_value = [self._make_mock_static()]
        ctx.history_candlesticks_by_offset.return_value = []

        quote = fetcher.get_realtime_quote("AAPL")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, "AAPL")
        self.assertEqual(quote.source, RealtimeSource.LONGBRIDGE)
        self.assertAlmostEqual(quote.price, 253.79, places=2)
        self.assertAlmostEqual(quote.change_pct, 2.90, places=0)
        self.assertEqual(quote.name, "苹果")

        # turnover_rate = volume / circulating_shares * 100
        expected_turnover = 49549600 / 15000000000 * 100
        self.assertAlmostEqual(quote.turnover_rate, expected_turnover, places=3)

        # pe_ratio = price / eps_ttm
        self.assertAlmostEqual(quote.pe_ratio, 253.79 / 6.08, places=1)

        # pb_ratio = price / bps
        self.assertAlmostEqual(quote.pb_ratio, 253.79 / 4.40, places=1)

        # total_mv
        self.assertAlmostEqual(quote.total_mv, 253.79 * 16000000000, places=0)

    def test_turnover_falls_back_to_total_shares_when_circulating_zero(self):
        """US API often reports circulating_shares=0; use total_shares for turnover."""
        fetcher, ctx = self._make_fetcher_with_mock_ctx()
        ctx.quote.return_value = [self._make_mock_quote()]
        static = self._make_mock_static()
        static.circulating_shares = 0
        static.total_shares = 16000000000
        ctx.static_info.return_value = [static]
        ctx.history_candlesticks_by_offset.return_value = []

        quote = fetcher.get_realtime_quote("AAPL")

        self.assertIsNotNone(quote)
        vol = 49549600
        self.assertAlmostEqual(quote.turnover_rate, vol / 16000000000 * 100, places=3)

    def test_realtime_quote_with_volume_ratio(self):
        """Verify volume_ratio calculation from history."""
        import types
        from datetime import date as dt_date, timedelta

        # Mock longbridge.openapi module so the internal import succeeds
        mock_lb_module = types.ModuleType("longbridge")
        mock_lb_openapi = types.ModuleType("longbridge.openapi")
        mock_lb_openapi.Period = MagicMock()
        mock_lb_openapi.AdjustType = MagicMock()
        with patch.dict("sys.modules", {
            "longbridge": mock_lb_module,
            "longbridge.openapi": mock_lb_openapi,
        }):
            fetcher, ctx = self._make_fetcher_with_mock_ctx()
            ctx.quote.return_value = [self._make_mock_quote(volume=50000000)]
            ctx.static_info.return_value = [self._make_mock_static()]

            base = dt_date.today() - timedelta(days=6)
            mock_candles = []
            for i, vol in enumerate([40000000, 38000000, 42000000, 41000000, 39000000]):
                c = MagicMock()
                c.volume = vol
                past_date = base + timedelta(days=i)
                c.timestamp = MagicMock()
                c.timestamp.date.return_value = past_date
                mock_candles.append(c)
            ctx.history_candlesticks_by_offset.return_value = mock_candles

            quote = fetcher.get_realtime_quote("AAPL")

        self.assertIsNotNone(quote)
        avg_vol = (40000000 + 38000000 + 42000000 + 41000000 + 39000000) / 5
        expected_ratio = round(50000000 / avg_vol, 2)
        self.assertEqual(quote.volume_ratio, expected_ratio)

    def test_quote_api_failure_returns_none(self):
        """If ctx.quote() raises, return None gracefully."""
        fetcher, ctx = self._make_fetcher_with_mock_ctx()
        ctx.quote.side_effect = Exception("network error")

        result = fetcher.get_realtime_quote("AAPL")
        self.assertIsNone(result)

    def test_hk_stock_symbol(self):
        """HK stock should use .HK suffix."""
        fetcher, ctx = self._make_fetcher_with_mock_ctx()
        ctx.quote.return_value = [self._make_mock_quote()]
        ctx.static_info.return_value = [self._make_mock_static(name_cn="腾讯控股")]
        ctx.history_candlesticks_by_offset.return_value = []

        quote = fetcher.get_realtime_quote("HK00700")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, "HK00700")
        ctx.quote.assert_called_with(["0700.HK"])


class TestSupplementFromLongbridge(unittest.TestCase):
    """Test the _supplement_from_longbridge method in DataFetcherManager."""

    def test_merge_fills_missing_fields(self):
        """When yfinance quote is missing volume_ratio/turnover_rate, LB fills them."""
        from data_provider.base import DataFetcherManager

        yf_quote = UnifiedRealtimeQuote(
            code="AAPL",
            name="Apple",
            source=RealtimeSource.FALLBACK,
            price=253.79,
            change_pct=2.9,
            volume=49549600,
            volume_ratio=None,
            turnover_rate=None,
            pe_ratio=None,
        )

        lb_quote = UnifiedRealtimeQuote(
            code="AAPL",
            name="苹果",
            source=RealtimeSource.LONGBRIDGE,
            price=253.79,
            volume_ratio=1.25,
            turnover_rate=0.33,
            pe_ratio=41.7,
            pb_ratio=57.7,
            total_mv=4060640000000.0,
        )

        mock_lb_fetcher = MagicMock()
        mock_lb_fetcher.name = "LongbridgeFetcher"
        mock_lb_fetcher.get_realtime_quote.return_value = lb_quote

        manager = DataFetcherManager(fetchers=[mock_lb_fetcher])

        result = manager._supplement_from_longbridge("AAPL", yf_quote)

        self.assertIsNotNone(result)
        self.assertEqual(result.volume_ratio, 1.25)
        self.assertEqual(result.turnover_rate, 0.33)
        self.assertEqual(result.pe_ratio, 41.7)
        # source should stay as original (yfinance/FALLBACK)
        self.assertEqual(result.source, RealtimeSource.FALLBACK)

    def test_sole_source_when_yfinance_fails(self):
        """When yfinance returns None, LB acts as sole source."""
        from data_provider.base import DataFetcherManager

        lb_quote = UnifiedRealtimeQuote(
            code="AAPL",
            source=RealtimeSource.LONGBRIDGE,
            price=253.79,
            volume_ratio=1.25,
            turnover_rate=0.33,
        )

        mock_lb_fetcher = MagicMock()
        mock_lb_fetcher.name = "LongbridgeFetcher"
        mock_lb_fetcher.get_realtime_quote.return_value = lb_quote

        manager = DataFetcherManager(fetchers=[mock_lb_fetcher])

        result = manager._supplement_from_longbridge("AAPL", None)

        self.assertIsNotNone(result)
        self.assertEqual(result.source, RealtimeSource.LONGBRIDGE)
        self.assertEqual(result.price, 253.79)


if __name__ == "__main__":
    unittest.main()
