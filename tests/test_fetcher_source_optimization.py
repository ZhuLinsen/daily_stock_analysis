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

from data_provider.base import (
    BaseFetcher,
    DataFetchError,
    DataFetcherManager,
    STANDARD_COLUMNS,
)
from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote


class _StubFetcher:
    def __init__(self, name: str, priority: int):
        self.name = name
        self.priority = priority


class _EmptyRawFetcher(BaseFetcher):
    name = "EmptyRawFetcher"
    priority = 0
    allow_empty_daily_data = True

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise AssertionError("empty raw daily data should not be normalized")


class _DefaultEmptyRawFetcher(_EmptyRawFetcher):
    name = "DefaultEmptyRawFetcher"
    allow_empty_daily_data = False


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
    def test_base_fetcher_returns_opt_in_empty_daily_data_without_error(self):
        df = _EmptyRawFetcher().get_daily_data(
            "000001",
            start_date="2026-05-01",
            end_date="2026-05-08",
        )

        self.assertTrue(df.empty)
        self.assertEqual(list(df.columns), STANDARD_COLUMNS)

    def test_base_fetcher_rejects_empty_daily_data_by_default(self):
        with self.assertRaises(DataFetchError):
            _DefaultEmptyRawFetcher().get_daily_data(
                "000001",
                start_date="2026-05-01",
                end_date="2026-05-08",
            )

    @patch("src.config.get_config")
    def test_manager_skips_unconfigured_optional_fetchers(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            tushare_token="",
            longbridge_app_key="",
            longbridge_app_secret="",
            longbridge_access_token="",
            longbridge_oauth_client_id="",
        )

        with patch.dict(
            "os.environ",
            {
                "LONGBRIDGE_OAUTH_CLIENT_ID": "",
                "LONGBRIDGE_APP_KEY": "",
                "LONGBRIDGE_APP_SECRET": "",
                "LONGBRIDGE_ACCESS_TOKEN": "",
            },
        ), patch("data_provider.efinance_fetcher.EfinanceFetcher", return_value=_StubFetcher("EfinanceFetcher", 0)), patch(
            "data_provider.tencent_fetcher.TencentFetcher",
            return_value=_StubFetcher("TencentFetcher", 0),
        ), patch(
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
            mock_longbridge.has_configured_credentials.return_value = False
            manager = DataFetcherManager()

        self.assertEqual(
            manager.available_fetchers,
            [
                "EfinanceFetcher",
                "TencentFetcher",
                "AkshareFetcher",
                "PytdxFetcher",
                "BaostockFetcher",
                "YfinanceFetcher",
            ],
        )
        mock_tushare.assert_not_called()
        mock_longbridge.assert_not_called()

    @patch("src.config.get_config")
    def test_manager_enables_longbridge_with_oauth_client_id(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            tushare_token="",
            longbridge_app_key="",
            longbridge_app_secret="",
            longbridge_access_token="",
            longbridge_oauth_client_id="client-1",
        )

        with patch("data_provider.efinance_fetcher.EfinanceFetcher", return_value=_StubFetcher("EfinanceFetcher", 0)), patch(
            "data_provider.tencent_fetcher.TencentFetcher",
            return_value=_StubFetcher("TencentFetcher", 0),
        ), patch(
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
        ), patch(
            "data_provider.longbridge_fetcher.LongbridgeFetcher",
            return_value=_StubFetcher("LongbridgeFetcher", 5),
        ) as mock_longbridge:
            mock_longbridge.has_configured_credentials.return_value = True
            manager = DataFetcherManager()

        self.assertIn("LongbridgeFetcher", manager.available_fetchers)
        self.assertIn("TencentFetcher", manager.available_fetchers)
        mock_longbridge.assert_called_once()

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
    def test_us_realtime_route_marks_longbridge_fallback_when_secondary_succeeds(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="efinance,akshare_em,tushare",
            realtime_cache_ttl=600,
        )

        longbridge = MagicMock()
        longbridge.name = "LongbridgeFetcher"
        longbridge.priority = 5
        longbridge.is_available_for_request.return_value = True
        longbridge.get_realtime_quote.return_value = None

        yfinance_quote = _make_quote("AAPL")
        yfinance = MagicMock()
        yfinance.name = "YfinanceFetcher"
        yfinance.priority = 4
        yfinance.get_realtime_quote.return_value = yfinance_quote

        manager = DataFetcherManager(fetchers=[longbridge, yfinance])

        quote = manager.get_realtime_quote("AAPL")

        self.assertIs(quote, yfinance_quote)
        self.assertEqual(quote.fallback_from, "longbridge")
        self.assertIsNotNone(quote.fetched_at)
        longbridge.get_realtime_quote.assert_called_once_with("AAPL")
        yfinance.get_realtime_quote.assert_called_once_with("AAPL")

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


    @patch("src.config.get_config")
    def test_daily_source_health_skips_repeatedly_failing_source(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace()
        DataFetcherManager.reset_daily_source_health()
        try:
            flaky = MagicMock()
            flaky.name = "EfinanceFetcher"
            flaky.priority = 0
            flaky.get_daily_data.side_effect = RuntimeError("timeout")

            backup = MagicMock()
            backup.name = "TencentFetcher"
            backup.priority = 1
            backup.get_daily_data.return_value = _make_daily_df()

            manager = DataFetcherManager(fetchers=[flaky, backup])

            for _ in range(3):
                df, source = manager.get_daily_data("000001", start_date="2026-05-01", end_date="2026-05-08")
                self.assertFalse(df.empty)
                self.assertEqual(source, "TencentFetcher")

            flaky.get_daily_data.reset_mock(side_effect=True)
            flaky.get_daily_data.side_effect = RuntimeError("should be skipped")

            df, source = manager.get_daily_data("000001", start_date="2026-05-01", end_date="2026-05-08")

            self.assertFalse(df.empty)
            self.assertEqual(source, "TencentFetcher")
            flaky.get_daily_data.assert_not_called()
        finally:
            DataFetcherManager.reset_daily_source_health()

    @patch("src.config.get_config")
    def test_daily_source_health_does_not_skip_source_after_empty_results(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace()
        DataFetcherManager.reset_daily_source_health()
        try:
            primary = MagicMock()
            primary.name = "EfinanceFetcher"
            primary.priority = 0
            primary.get_daily_data.return_value = pd.DataFrame()

            backup = MagicMock()
            backup.name = "TencentFetcher"
            backup.priority = 1
            backup.get_daily_data.return_value = _make_daily_df()

            manager = DataFetcherManager(fetchers=[primary, backup])

            for _ in range(3):
                df, source = manager.get_daily_data("000001", start_date="2026-05-01", end_date="2026-05-08")
                self.assertFalse(df.empty)
                self.assertEqual(source, "TencentFetcher")

            primary.get_daily_data.reset_mock()
            primary.get_daily_data.return_value = _make_daily_df()

            df, source = manager.get_daily_data("000001", start_date="2026-05-01", end_date="2026-05-08")

            self.assertFalse(df.empty)
            self.assertEqual(source, "EfinanceFetcher")
            primary.get_daily_data.assert_called_once()
        finally:
            DataFetcherManager.reset_daily_source_health()

    @patch("src.config.get_config")
    def test_daily_source_health_does_not_preconsume_half_open_fallback(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace()
        DataFetcherManager.reset_daily_source_health()
        try:
            primary = MagicMock()
            primary.name = "EfinanceFetcher"
            primary.priority = 0
            primary.get_daily_data.return_value = _make_daily_df()

            backup = MagicMock()
            backup.name = "TencentFetcher"
            backup.priority = 1
            backup.get_daily_data.return_value = _make_daily_df()

            manager = DataFetcherManager(fetchers=[primary, backup])
            health_key = DataFetcherManager._daily_health_key(backup, "cn")
            breaker = DataFetcherManager._daily_source_health
            for _ in range(breaker.failure_threshold):
                breaker.record_failure(health_key, error="timeout")
            with breaker._lock:
                breaker._states[health_key]["last_failure_time"] -= breaker.cooldown_seconds + 1

            df, source = manager.get_daily_data("000001", start_date="2026-05-01", end_date="2026-05-08")

            self.assertFalse(df.empty)
            self.assertEqual(source, "EfinanceFetcher")
            backup.get_daily_data.assert_not_called()

            primary.get_daily_data.reset_mock()
            primary.get_daily_data.side_effect = RuntimeError("primary down")

            df, source = manager.get_daily_data("000001", start_date="2026-05-01", end_date="2026-05-08")

            self.assertFalse(df.empty)
            self.assertEqual(source, "TencentFetcher")
            backup.get_daily_data.assert_called_once()
        finally:
            DataFetcherManager.reset_daily_source_health()

    @patch("src.config.get_config")
    def test_daily_source_health_releases_half_open_probe_after_empty_result(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace()
        DataFetcherManager.reset_daily_source_health()
        try:
            primary = MagicMock()
            primary.name = "EfinanceFetcher"
            primary.priority = 0
            primary.get_daily_data.side_effect = RuntimeError("primary down")

            half_open = MagicMock()
            half_open.name = "TencentFetcher"
            half_open.priority = 1
            half_open.get_daily_data.return_value = pd.DataFrame()

            backup = MagicMock()
            backup.name = "AkshareFetcher"
            backup.priority = 2
            backup.get_daily_data.return_value = _make_daily_df()

            manager = DataFetcherManager(fetchers=[primary, half_open, backup])
            health_key = DataFetcherManager._daily_health_key(half_open, "cn")
            breaker = DataFetcherManager._daily_source_health
            for _ in range(breaker.failure_threshold):
                breaker.record_failure(health_key, error="timeout")
            with breaker._lock:
                breaker._states[health_key]["last_failure_time"] -= breaker.cooldown_seconds + 1

            df, source = manager.get_daily_data("000001", start_date="2026-05-01", end_date="2026-05-08")

            self.assertFalse(df.empty)
            self.assertEqual(source, "AkshareFetcher")
            half_open.get_daily_data.assert_called_once()

            half_open.get_daily_data.reset_mock()
            half_open.get_daily_data.return_value = _make_daily_df()

            df, source = manager.get_daily_data("000001", start_date="2026-05-01", end_date="2026-05-08")

            self.assertFalse(df.empty)
            self.assertEqual(source, "TencentFetcher")
            half_open.get_daily_data.assert_called_once()
        finally:
            DataFetcherManager.reset_daily_source_health()


if __name__ == "__main__":
    unittest.main()
