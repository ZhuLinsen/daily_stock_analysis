# -*- coding: utf-8 -*-
"""
FinnhubFetcher offline unit tests.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _make_mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


class TestFinnhubFetcherNormalize(unittest.TestCase):
    """Test _normalize_data with raw Finnhub candle response."""

    def setUp(self):
        from data_provider.finnhub_fetcher import FinnhubFetcher
        self.fetcher = FinnhubFetcher()

    def test_normalize_candle_data(self):
        import pandas as pd
        raw = pd.DataFrame({
            'c': [150.0, 152.0, 148.5],
            'h': [151.0, 153.0, 150.0],
            'l': [149.0, 150.0, 147.0],
            'o': [149.5, 151.0, 149.0],
            't': [1718000000, 1718086400, 1718172800],
            'v': [1000000, 1200000, 900000],
        })
        result = self.fetcher._normalize_data(raw, 'AAPL')
        self.assertIn('date', result.columns)
        self.assertIn('close', result.columns)
        self.assertAlmostEqual(result.iloc[0]['close'], 150.0)
        self.assertEqual(result.iloc[0]['code'], 'AAPL')

    def test_normalize_calculates_pct_chg(self):
        import pandas as pd
        raw = pd.DataFrame({
            'c': [150.0, 153.0],
            'h': [151.0, 154.0],
            'l': [149.0, 152.0],
            'o': [149.5, 152.0],
            't': [1718000000, 1718086400],
            'v': [1000000, 1200000],
        })
        result = self.fetcher._normalize_data(raw, 'AAPL')
        self.assertAlmostEqual(result.iloc[1]['pct_chg'], 2.0)

    def test_normalize_empty_df(self):
        import pandas as pd
        raw = pd.DataFrame()
        result = self.fetcher._normalize_data(raw, 'AAPL')
        self.assertTrue(result.empty)


class TestFinnhubFetcherFetchRaw(unittest.TestCase):
    """Test _fetch_raw_data with mocked HTTP."""

    def setUp(self):
        from data_provider.finnhub_fetcher import FinnhubFetcher
        self.fetcher = FinnhubFetcher()
        self.fetcher._api_key = "test_key"

    @patch('data_provider.finnhub_fetcher.requests.get')
    def test_fetch_raw_success(self, mock_get):
        mock_get.return_value = _make_mock_response({
            'c': [150.0],
            'h': [151.0],
            'l': [149.0],
            'o': [149.5],
            't': [1718000000],
            'v': [1000000],
            's': 'ok',
        })
        df = self.fetcher._fetch_raw_data('AAPL', '2024-06-10', '2024-06-11')
        self.assertFalse(df.empty)
        self.assertIn('c', df.columns)

    @patch('data_provider.finnhub_fetcher.requests.get')
    def test_fetch_raw_empty_response(self, mock_get):
        from data_provider.base import DataFetchError
        mock_get.return_value = _make_mock_response({
            'c': [], 'h': [], 'l': [], 'o': [], 't': [], 'v': [], 's': 'no_data',
        })
        with self.assertRaises(DataFetchError):
            self.fetcher._fetch_raw_data('INVALID', '2024-06-10', '2024-06-11')

    @patch('data_provider.finnhub_fetcher.requests.get')
    def test_fetch_raw_http_error(self, mock_get):
        from data_provider.base import DataFetchError
        mock_get.side_effect = Exception("connection timeout")
        with self.assertRaises(DataFetchError):
            self.fetcher._fetch_raw_data('AAPL', '2024-06-10', '2024-06-11')


class TestFinnhubFetcherRealtimeQuote(unittest.TestCase):
    """Test get_realtime_quote with mocked HTTP."""

    def setUp(self):
        from data_provider.finnhub_fetcher import FinnhubFetcher
        self.fetcher = FinnhubFetcher()
        self.fetcher._api_key = "test_key"

    @patch('data_provider.finnhub_fetcher.requests.get')
    def test_realtime_quote_us_stock(self, mock_get):
        mock_get.return_value = _make_mock_response({
            'c': 150.0,
            'd': 2.0,
            'dp': 1.35,
            'h': 151.0,
            'l': 148.0,
            'o': 149.0,
            'pc': 148.0,
            't': 1718172800,
            'v': 5000000,
        })
        quote = self.fetcher.get_realtime_quote('AAPL')
        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, 'AAPL')
        self.assertAlmostEqual(quote.price, 150.0)
        self.assertAlmostEqual(quote.change_pct, 1.35)

    def test_realtime_quote_non_us_stock(self):
        quote = self.fetcher.get_realtime_quote('600519')
        self.assertIsNone(quote)

    @patch('data_provider.finnhub_fetcher.requests.get')
    def test_realtime_quote_http_failure(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        quote = self.fetcher.get_realtime_quote('AAPL')
        self.assertIsNone(quote)


class TestFinnhubFetcherStockName(unittest.TestCase):
    """Test get_stock_name with mocked HTTP."""

    def setUp(self):
        from data_provider.finnhub_fetcher import FinnhubFetcher
        self.fetcher = FinnhubFetcher()
        self.fetcher._api_key = "test_key"

    @patch('data_provider.finnhub_fetcher.requests.get')
    def test_get_stock_name_found(self, mock_get):
        mock_get.return_value = _make_mock_response({
            'result': [{'description': 'APPLE INC', 'symbol': 'AAPL'}],
            'count': 1,
        })
        name = self.fetcher.get_stock_name('AAPL')
        self.assertEqual(name, 'APPLE INC')

    @patch('data_provider.finnhub_fetcher.requests.get')
    def test_get_stock_name_empty(self, mock_get):
        mock_get.return_value = _make_mock_response({'result': [], 'count': 0})
        name = self.fetcher.get_stock_name('NOTEXIST')
        self.assertIsNone(name)

    def test_get_stock_name_non_us(self):
        name = self.fetcher.get_stock_name('600519')
        self.assertIsNone(name)


class TestFinnhubFetcherInit(unittest.TestCase):
    """Test constructor / key handling."""

    @patch('src.config.get_config')
    def test_init_with_key(self, mock_config):
        mock_config.return_value = MagicMock(finnhub_api_key='sk-test-123')
        from data_provider.finnhub_fetcher import FinnhubFetcher
        f = FinnhubFetcher()
        self.assertEqual(f._api_key, 'sk-test-123')

    @patch.dict(os.environ, {}, clear=False)
    @patch('src.config.get_config')
    def test_init_without_key(self, mock_config):
        os.environ.pop('FINNHUB_API_KEY', None)
        mock_config.return_value = MagicMock(finnhub_api_key=None)
        from data_provider.finnhub_fetcher import FinnhubFetcher
        f = FinnhubFetcher()
        self.assertIsNone(f._api_key)


class TestFinnhubFetcherRegistration(unittest.TestCase):
    """Test that FinnhubFetcher is registered in DataFetcherManager when key is present."""

    @patch('src.config.get_config')
    def test_registered_with_key(self, mock_config):
        mock_config.return_value = MagicMock(
            finnhub_api_key='sk-test',
            alphavantage_api_key=None,
            tushare_token=None,
            longbridge_app_key=None,
            longbridge_app_secret=None,
            longbridge_access_token=None,
            tickflow_api_key=None,
        )
        from data_provider.base import DataFetcherManager
        mgr = DataFetcherManager()
        names = [f.name for f in mgr._get_fetchers_snapshot()]
        self.assertIn('FinnhubFetcher', names)

    @patch('src.config.get_config')
    def test_not_registered_without_key(self, mock_config):
        mock_config.return_value = MagicMock(
            finnhub_api_key=None,
            alphavantage_api_key=None,
            tushare_token=None,
            longbridge_app_key=None,
            longbridge_app_secret=None,
            longbridge_access_token=None,
            tickflow_api_key=None,
        )
        from data_provider.base import DataFetcherManager
        mgr = DataFetcherManager()
        names = [f.name for f in mgr._get_fetchers_snapshot()]
        self.assertNotIn('FinnhubFetcher', names)


class TestUSDailyRoutingFallback(unittest.TestCase):
    """Verify US daily routing includes Finnhub/AlphaVantage in the failover chain."""

    @patch('src.config.get_config')
    def test_us_routing_includes_new_fetchers(self, mock_config):
        """US stock get_daily_data source_order must contain Finnhub and AlphaVantage."""
        mock_config.return_value = MagicMock(
            finnhub_api_key='sk-test',
            alphavantage_api_key='av-test',
            tushare_token=None,
            longbridge_app_key=None,
            longbridge_app_secret=None,
            longbridge_access_token=None,
            tickflow_api_key=None,
        )
        from data_provider.base import DataFetcherManager
        mgr = DataFetcherManager()

        # Verify both fetchers are registered
        names = [f.name for f in mgr._get_fetchers_snapshot()]
        self.assertIn('FinnhubFetcher', names)
        self.assertIn('AlphaVantageFetcher', names)

        # Verify the US routing source_order by checking the code path
        # When Longbridge is not preferred, Finnhub should come before Yfinance
        finnhub_idx = names.index('FinnhubFetcher')
        yfinance_idx = names.index('YfinanceFetcher')
        self.assertLess(finnhub_idx, yfinance_idx,
                        "FinnhubFetcher should have higher priority (lower index) than YfinanceFetcher")


if __name__ == '__main__':
    unittest.main()
