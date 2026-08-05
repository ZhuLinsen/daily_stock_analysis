# -*- coding: utf-8 -*-
"""Unit tests for JP/KR Yahoo Finance market-review index mappings."""

import os
import sys
import unittest
from unittest.mock import MagicMock

import pandas as pd

if 'fake_useragent' not in sys.modules:
    sys.modules['fake_useragent'] = MagicMock()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _make_mock_hist(close: float = 100.0, prev_close: float = 98.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            'Close': [prev_close, close],
            'Open': [prev_close - 1, close - 1],
            'High': [prev_close + 2, close + 2],
            'Low': [prev_close - 2, close - 2],
            'Volume': [1000.0, 1200.0],
        },
        index=pd.DatetimeIndex(['2026-03-26', '2026-03-27']),
    )


def _make_mock_yf(hist_df: pd.DataFrame):
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist_df
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker
    return mock_yf


class TestJpKrIndexMappings(unittest.TestCase):
    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    def test_jp_indices_use_expected_yahoo_symbols(self):
        mock_yf = _make_mock_yf(pd.DataFrame())

        self.fetcher._get_jp_main_indices(mock_yf)

        ticker_calls = [call.args[0] for call in mock_yf.Ticker.call_args_list]
        self.assertEqual(ticker_calls, ['^N225', '^TOPX'])

    def test_kr_indices_use_expected_yahoo_symbols(self):
        mock_yf = _make_mock_yf(pd.DataFrame())

        self.fetcher._get_kr_main_indices(mock_yf)

        ticker_calls = [call.args[0] for call in mock_yf.Ticker.call_args_list]
        self.assertEqual(ticker_calls, ['^KS11', '^KQ11'])

    def test_jp_indices_return_expected_codes_when_data_available(self):
        result = self.fetcher._get_jp_main_indices(_make_mock_yf(_make_mock_hist()))

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual([item['code'] for item in result], ['N225', 'TOPX'])
        self.assertEqual([item['name'] for item in result], ['日经225', '东证指数'])

    def test_kr_indices_return_expected_codes_when_data_available(self):
        result = self.fetcher._get_kr_main_indices(_make_mock_yf(_make_mock_hist()))

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual([item['code'] for item in result], ['KS11', 'KQ11'])
        self.assertEqual([item['name'] for item in result], ['KOSPI', 'KOSDAQ'])

    def test_jp_kr_indices_return_none_when_all_empty(self):
        mock_yf = _make_mock_yf(pd.DataFrame())

        self.assertIsNone(self.fetcher._get_jp_main_indices(mock_yf))
        self.assertIsNone(self.fetcher._get_kr_main_indices(mock_yf))


if __name__ == '__main__':
    unittest.main()
