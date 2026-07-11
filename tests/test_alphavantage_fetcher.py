# -*- coding: utf-8 -*-
"""
AlphaVantageFetcher offline unit tests.
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


class TestAlphaVantageFetcherNormalize(unittest.TestCase):
    """Test _normalize_data with raw AlphaVantage TIME_SERIES_DAILY response."""

    def setUp(self):
        from data_provider.alphavantage_fetcher import AlphaVantageFetcher
        self.fetcher = AlphaVantageFetcher()

    def test_normalize_daily_data(self):
        import pandas as pd
        raw = pd.DataFrame({
            '1. open': [149.5, 151.0],
            '2. high': [151.0, 153.0],
            '3. low': [149.0, 150.0],
            '4. close': [150.0, 152.0],
            '5. volume': [1000000, 1200000],
        }, index=pd.to_datetime(['2024-06-10', '2024-06-11']))
        result = self.fetcher._normalize_data(raw, 'AAPL')
        self.assertIn('date', result.columns)
        self.assertIn('close', result.columns)
        self.assertAlmostEqual(result.iloc[0]['close'], 150.0)
        self.assertEqual(result.iloc[0]['code'], 'AAPL')

    def test_normalize_calculates_pct_chg(self):
        import pandas as pd
        raw = pd.DataFrame({
            '1. open': [149.5, 152.0],
            '2. high': [151.0, 154.0],
            '3. low': [149.0, 152.0],
            '4. close': [150.0, 153.0],
            '5. volume': [1000000, 1200000],
        }, index=pd.to_datetime(['2024-06-10', '2024-06-11']))
        result = self.fetcher._normalize_data(raw, 'AAPL')
        self.assertAlmostEqual(result.iloc[1]['pct_chg'], 2.0)

    def test_normalize_empty_df(self):
        import pandas as pd
        raw = pd.DataFrame()
        result = self.fetcher._normalize_data(raw, 'AAPL')
        self.assertTrue(result.empty)


class TestAlphaVantageFetcherFetchRaw(unittest.TestCase):
    """Test _fetch_raw_data with mocked HTTP."""

    def setUp(self):
        from data_provider.alphavantage_fetcher import AlphaVantageFetcher
        self.fetcher = AlphaVantageFetcher()
        self.fetcher._api_key = "test_key"

    @patch('data_provider.alphavantage_fetcher.requests.get')
    def test_fetch_raw_success(self, mock_get):
        mock_get.return_value = _make_mock_response({
            'Time Series (Daily)': {
                '2024-06-11': {
                    '1. open': '151.0', '2. high': '153.0',
                    '3. low': '150.0', '4. close': '152.0',
                    '5. volume': '1200000',
                },
                '2024-06-10': {
                    '1. open': '149.5', '2. high': '151.0',
                    '3. low': '149.0', '4. close': '150.0',
                    '5. volume': '1000000',
                },
            },
        })
        df = self.fetcher._fetch_raw_data('AAPL', '2024-06-10', '2024-06-11')
        self.assertFalse(df.empty)
        self.assertIn('4. close', df.columns)

    @patch('data_provider.alphavantage_fetcher.requests.get')
    def test_fetch_raw_rate_limit(self, mock_get):
        from data_provider.base import DataFetchError
        mock_get.return_value = _make_mock_response({
            'Note': 'Thank you for using Alpha Vantage! Our standard API call frequency is 25 calls per day.',
        })
        with self.assertRaises(DataFetchError):
            self.fetcher._fetch_raw_data('AAPL', '2024-06-10', '2024-06-11')

    @patch('data_provider.alphavantage_fetcher.requests.get')
    def test_fetch_raw_error_response(self, mock_get):
        from data_provider.base import DataFetchError
        mock_get.return_value = _make_mock_response({
            'Error Message': 'Invalid API call.',
        })
        with self.assertRaises(DataFetchError):
            self.fetcher._fetch_raw_data('INVALID', '2024-06-10', '2024-06-11')

    @patch('data_provider.alphavantage_fetcher.requests.get')
    def test_fetch_raw_http_error(self, mock_get):
        from data_provider.base import DataFetchError
        mock_get.side_effect = Exception("connection timeout")
        with self.assertRaises(DataFetchError):
            self.fetcher._fetch_raw_data('AAPL', '2024-06-10', '2024-06-11')


class TestAlphaVantageFetcherRealtimeQuote(unittest.TestCase):
    """Test get_realtime_quote with mocked HTTP."""

    def setUp(self):
        from data_provider.alphavantage_fetcher import AlphaVantageFetcher
        self.fetcher = AlphaVantageFetcher()
        self.fetcher._api_key = "test_key"

    @patch('data_provider.alphavantage_fetcher.requests.get')
    def test_realtime_quote_us_stock(self, mock_get):
        mock_get.return_value = _make_mock_response({
            'Global Quote': {
                '01. symbol': 'AAPL',
                '02. open': '149.0',
                '03. high': '151.0',
                '04. low': '148.0',
                '05. price': '150.0',
                '06. volume': '5000000',
                '08. previous close': '148.0',
                '09. change': '2.0',
                '10. change percent': '1.3514%',
            },
        })
        quote = self.fetcher.get_realtime_quote('AAPL')
        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, 'AAPL')
        self.assertAlmostEqual(quote.price, 150.0)

    def test_realtime_quote_non_us_stock(self):
        quote = self.fetcher.get_realtime_quote('600519')
        self.assertIsNone(quote)


class TestAlphaVantageFetcherStockName(unittest.TestCase):
    """Test get_stock_name with mocked HTTP."""

    def setUp(self):
        from data_provider.alphavantage_fetcher import AlphaVantageFetcher
        self.fetcher = AlphaVantageFetcher()
        self.fetcher._api_key = "test_key"

    @patch('data_provider.alphavantage_fetcher.requests.get')
    def test_get_stock_name_found(self, mock_get):
        mock_get.return_value = _make_mock_response({
            'bestMatches': [
                {'1. symbol': 'AAPL', '2. name': 'Apple Inc', '3. type': 'Equity', '4. region': 'United States'},
            ],
        })
        name = self.fetcher.get_stock_name('AAPL')
        self.assertEqual(name, 'Apple Inc')

    @patch('data_provider.alphavantage_fetcher.requests.get')
    def test_get_stock_name_empty(self, mock_get):
        mock_get.return_value = _make_mock_response({'bestMatches': []})
        name = self.fetcher.get_stock_name('NOTEXIST')
        self.assertIsNone(name)


class TestAlphaVantageFetcherInit(unittest.TestCase):
    """Test constructor / key handling."""

    @patch('src.config.get_config')
    def test_init_with_key(self, mock_config):
        mock_config.return_value = MagicMock(alphavantage_api_key='AVTEST123')
        from data_provider.alphavantage_fetcher import AlphaVantageFetcher
        f = AlphaVantageFetcher()
        self.assertEqual(f._api_key, 'AVTEST123')

    @patch.dict(os.environ, {}, clear=False)
    @patch('src.config.get_config')
    def test_init_without_key(self, mock_config):
        os.environ.pop('ALPHAVANTAGE_API_KEY', None)
        mock_config.return_value = MagicMock(alphavantage_api_key=None)
        from data_provider.alphavantage_fetcher import AlphaVantageFetcher
        f = AlphaVantageFetcher()
        self.assertIsNone(f._api_key)


class TestAlphaVantageFetcherNewestFirst(unittest.TestCase):
    """Verify pct_chg is correct when API returns newest-first data."""

    def setUp(self):
        from data_provider.alphavantage_fetcher import AlphaVantageFetcher
        self.fetcher = AlphaVantageFetcher()

    def test_pct_chg_correct_newest_first(self):
        """AlphaVantage returns newest date first; pct_chg must still be correct."""
        import pandas as pd
        # Simulate newest-first raw data: 2024-06-12 (close=156) before 2024-06-10 (close=150)
        raw = pd.DataFrame({
            '1. open': [155.0, 152.0, 149.5],
            '2. high': [157.0, 154.0, 151.0],
            '3. low': [154.0, 151.0, 149.0],
            '4. close': [156.0, 153.0, 150.0],
            '5. volume': [1100000, 1200000, 1000000],
        }, index=pd.to_datetime(['2024-06-12', '2024-06-11', '2024-06-10']))
        result = self.fetcher._normalize_data(raw, 'AAPL')

        # After sorting ascending: row0=2024-06-10(150), row1=2024-06-11(153), row2=2024-06-12(156)
        self.assertAlmostEqual(result.iloc[0]['pct_chg'], 0.0)  # first row = 0
        self.assertAlmostEqual(result.iloc[1]['pct_chg'], 2.0, places=1)  # (153-150)/150
        self.assertAlmostEqual(result.iloc[2]['pct_chg'], round((156 - 153) / 153 * 100, 2), places=1)


if __name__ == '__main__':
    unittest.main()
