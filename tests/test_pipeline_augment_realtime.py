# -*- coding: utf-8 -*-
"""Tests that _augment_historical_with_realtime uses market-local date."""

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from src.core.pipeline import StockAnalysisPipeline


def _make_pipeline():
    p = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    p.config = SimpleNamespace(enable_realtime_technical_indicators=True)
    return p


def _make_df(dates_and_closes):
    rows = [
        {"code": "AAPL", "date": d, "open": c, "high": c, "low": c, "close": c, "volume": 100, "amount": 0, "pct_chg": 0}
        for d, c in dates_and_closes
    ]
    return pd.DataFrame(rows)


class AugmentRealtimeMarketDateTestCase(unittest.TestCase):
    """Verify _augment_historical_with_realtime uses market-local date, not server date."""

    @patch("src.core.pipeline.is_market_open", return_value=True)
    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="us")
    def test_appends_virtual_row_with_market_local_date(
        self, _mock_market, mock_now, _mock_open
    ):
        """When server is UTC and US market date differs, virtual row uses market date."""
        # Server UTC: 2026-03-28 01:00 => US ET: 2026-03-27 21:00
        us_market_now = datetime(2026, 3, 27, 21, 0)
        mock_now.return_value = us_market_now

        df = _make_df([(date(2026, 3, 26), 150.0)])
        quote = SimpleNamespace(price=155.0, open_price=151.0, high=156.0, low=149.0, volume=200, amount=None, change_pct=3.0, pre_close=None)

        pipeline = _make_pipeline()
        result = pipeline._augment_historical_with_realtime(df, quote, "AAPL")

        self.assertEqual(len(result), 2)
        appended_date = result.iloc[-1]["date"]
        if hasattr(appended_date, "date"):
            appended_date = appended_date.date()
        self.assertEqual(appended_date, date(2026, 3, 27))

    @patch("src.core.pipeline.is_market_open", return_value=True)
    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="us")
    def test_updates_existing_row_when_data_matches_market_date(
        self, _mock_market, mock_now, _mock_open
    ):
        """When latest bar date >= market_today, update in place instead of appending."""
        mock_now.return_value = datetime(2026, 3, 27, 17, 0)

        df = _make_df([(date(2026, 3, 26), 150.0), (date(2026, 3, 27), 152.0)])
        quote = SimpleNamespace(price=155.0, open_price=151.0, high=156.0, low=149.0, volume=200, amount=None, change_pct=3.0, pre_close=None)

        pipeline = _make_pipeline()
        result = pipeline._augment_historical_with_realtime(df, quote, "AAPL")

        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[-1]["close"], 155.0)

    @patch("src.core.pipeline.is_market_open", return_value=False)
    @patch("src.core.pipeline.get_market_now")
    @patch("src.core.pipeline.get_market_for_stock", return_value="cn")
    def test_skips_augmentation_on_non_trading_day(
        self, _mock_market, mock_now, _mock_open
    ):
        """Weekend/holiday: returns df unchanged."""
        mock_now.return_value = datetime(2026, 3, 28, 10, 0)

        df = _make_df([(date(2026, 3, 27), 30.0)])
        quote = SimpleNamespace(price=31.0, open_price=30.5, high=31.5, low=29.5, volume=100, amount=None, change_pct=1.0, pre_close=None)

        pipeline = _make_pipeline()
        result = pipeline._augment_historical_with_realtime(df, quote, "600519")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["close"], 30.0)


if __name__ == "__main__":
    unittest.main()
