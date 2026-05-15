# -*- coding: utf-8 -*-
"""Regression tests for fetcher routing and optional-source pruning."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

if "litellm" not in sys.modules:
    sys.modules["litellm"] = MagicMock()
if "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()

from data_provider.base import DataFetcherManager
from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote


class _StubFetcher:
    def __init__(self, name: str, priority: int):
        self.name = name
        self.priority = priority


def _make_quote(code: str = "AAPL") -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(
        code=code,
        name="Apple",
        source=RealtimeSource.FALLBACK,
        price=188.8,
        change_pct=1.2,
        volume_ratio=1.0,
        turnover_rate=0.2,
        pe_ratio=20.0,
        pb_ratio=3.0,
        total_mv=1000.0,
        circ_mv=900.0,
        amplitude=2.0,
    )


def _make_daily_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-05-01",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1000,
                "amount": 101000.0,
                "pct_chg": 1.0,
            }
        ]
    )


class TestFetcherSourceOptimization(unittest.TestCase):
    @patch("src.config.get_config")
    def test_manager_skips_unconfigured_optional_fetchers(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            tushare_token="",
            longbridge_app_key="",
            longbridge_app_secret="",
            longbridge_access_token="",
        )

        with patch("data_provider.efinance_fetcher.EfinanceFetcher", return_value=_StubFetcher("EfinanceFetcher", 0)), patch(
            "data_provider.akshare_fetcher.AkshareFetcher",
            return_value=_StubFetcher("AkshareFetcher", 1),
        ), patch(
            "data_provider.pytdx_fetcher.PytdxFetcher",
            return_value=_StubFetcher("PytdxFetcher", 2),
        ), patch(
            "data_provider.baostock_fetcher.BaostockFetcher",
            return_value=_StubFetcher("BaostockFetcher", 3),
        ), patch(
            "data_provider.yfinance_fetcher.YfinanceFetcher",
            return_value=_StubFetcher("YfinanceFetcher", 4),
        ), patch(
            "data_provider.tushare_fetcher.TushareFetcher",
            return_value=_StubFetcher("TushareFetcher", -1),
        ) as mock_tushare, patch(
            "data_provider.longbridge_fetcher.LongbridgeFetcher",
            return_value=_StubFetcher("LongbridgeFetcher", 5),
        ) as mock_longbridge:
            manager = DataFetcherManager()

        self.assertEqual(
            manager.available_fetchers,
            [
                "EfinanceFetcher",
                "AkshareFetcher",
                "PytdxFetcher",
                "BaostockFetcher",
                "YfinanceFetcher",
            ],
        )
        mock_tushare.assert_not_called()
        mock_longbridge.assert_not_called()

    @patch("src.config.get_config")
    def test_us_realtime_route_skips_temporarily_unavailable_longbridge(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="efinance,akshare_em,tushare",
        )

        longbridge = MagicMock()
        longbridge.name = "LongbridgeFetcher"
        longbridge.priority = 5
        longbridge.is_available_for_request.return_value = False

        yfinance = MagicMock()
        yfinance.name = "YfinanceFetcher"
        yfinance.priority = 4
        yfinance.get_realtime_quote.return_value = _make_quote("AAPL")

        manager = DataFetcherManager(fetchers=[longbridge, yfinance])

        quote = manager.get_realtime_quote("AAPL")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, "AAPL")
        yfinance.get_realtime_quote.assert_called_once_with("AAPL")
        longbridge.get_realtime_quote.assert_not_called()

    @patch("src.config.get_config")
    def test_us_daily_route_skips_temporarily_unavailable_longbridge(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            longbridge_app_key="app-key",
            longbridge_app_secret="app-secret",
            longbridge_access_token="access-token",
        )

        longbridge = MagicMock()
        longbridge.name = "LongbridgeFetcher"
        longbridge.priority = 5
        longbridge.is_available_for_request.return_value = False

        yfinance = MagicMock()
        yfinance.name = "YfinanceFetcher"
        yfinance.priority = 4
        yfinance.get_daily_data.return_value = _make_daily_df()

        manager = DataFetcherManager(fetchers=[longbridge, yfinance])

        df, source = manager.get_daily_data("AAPL", start_date="2026-05-01", end_date="2026-05-08")

        self.assertFalse(df.empty)
        self.assertEqual(source, "YfinanceFetcher")
        yfinance.get_daily_data.assert_called_once()
        longbridge.get_daily_data.assert_not_called()

    @patch("src.config.get_config")
    def test_hk_daily_route_skips_temporarily_unavailable_longbridge(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            longbridge_app_key="app-key",
            longbridge_app_secret="app-secret",
            longbridge_access_token="access-token",
        )

        longbridge = MagicMock()
        longbridge.name = "LongbridgeFetcher"
        longbridge.priority = 5
        longbridge.is_available_for_request.return_value = False

        akshare = MagicMock()
        akshare.name = "AkshareFetcher"
        akshare.priority = 1
        akshare.get_daily_data.return_value = _make_daily_df()

        manager = DataFetcherManager(fetchers=[longbridge, akshare])

        df, source = manager.get_daily_data("HK00700", start_date="2026-05-01", end_date="2026-05-08")

        self.assertFalse(df.empty)
        self.assertEqual(source, "AkshareFetcher")
        akshare.get_daily_data.assert_called_once()
        longbridge.get_daily_data.assert_not_called()


if __name__ == "__main__":
    unittest.main()
