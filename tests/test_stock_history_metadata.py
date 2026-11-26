# -*- coding: utf-8 -*-
"""Offline tests for stock history ohlc_synthesized and price_adjustment metadata."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pandas as pd

from api.v1.endpoints.stocks import router as stocks_router
from data_provider.alphavantage_fetcher import AlphaVantageFetcher
from data_provider.efinance_fetcher import EfinanceFetcher
from data_provider.pytdx_fetcher import PytdxFetcher
from data_provider.tickflow_fetcher import TickFlowFetcher
from data_provider.tushare_fetcher import TushareFetcher
from src.services.stock_service import StockService


class _StubFetcherManager:
    def __init__(self, df: pd.DataFrame, source_name: str, stock_name: str = "Test Stock") -> None:
        self._df = df
        self._source_name = source_name
        self._stock_name = stock_name

    def get_daily_data(self, stock_code: str, days: int = 30):
        return self._df, self._source_name

    def get_stock_name(self, stock_code: str):
        return self._stock_name


def _create_stocks_client() -> TestClient:
    app = FastAPI()
    app.include_router(stocks_router, prefix="/api/v1/stocks")
    return TestClient(app)


class TestStockHistoryMetadata(unittest.TestCase):
    def test_efinance_close_only_sets_ohlc_synthesized_end_to_end(self) -> None:
        dates = pd.bdate_range("2026-10-01", periods=15).strftime("%Y-%m-%d").tolist()
        raw_df = pd.DataFrame(
            {
                "日期": dates,
                "收盘": [100.0] * 15,
                "成交量": [1000] * 15,
            }
        )
        fetcher = EfinanceFetcher()
        with patch.object(fetcher, "_fetch_raw_data", return_value=raw_df):
            df = fetcher.get_daily_data("600519", start_date=dates[0], end_date=dates[-1])

        self.assertTrue(df.attrs.get("ohlc_synthesized"))
        self.assertEqual(df.attrs.get("price_adjustment"), "forward")

        stub_manager = _StubFetcherManager(df, "EfinanceFetcher", "贵州茅台")
        with patch("data_provider.base.DataFetcherManager", return_value=stub_manager):
            service_result = StockService().get_history_data("600519", days=15)
            client = _create_stocks_client()
            resp = client.get("/api/v1/stocks/600519/history?period=daily&days=15")

        self.assertTrue(service_result["ohlc_synthesized"])
        self.assertEqual(service_result["price_adjustment"], "forward")
        self.assertEqual(len(service_result["data"]), 15)
        self.assertEqual(service_result["data"][-1]["open"], 0.0)
        self.assertEqual(service_result["data"][-1]["high"], 0.0)
        self.assertEqual(service_result["data"][-1]["low"], 0.0)
        self.assertEqual(service_result["data"][-1]["close"], 100.0)

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIs(payload["ohlc_synthesized"], True)
        self.assertEqual(payload["price_adjustment"], "forward")
        self.assertEqual(payload["data"][0]["open"], 0.0)
        self.assertEqual(payload["data"][0]["high"], 0.0)
        self.assertEqual(payload["data"][0]["low"], 0.0)
        self.assertEqual(payload["data"][0]["close"], 100.0)

    def test_efinance_full_ohlc_preserves_measured_range_and_false_flag(self) -> None:
        dates = pd.bdate_range("2026-10-01", periods=15).strftime("%Y-%m-%d").tolist()
        raw_df = pd.DataFrame(
            {
                "日期": dates,
                "开盘": [99.0] * 15,
                "最高": [102.0] * 15,
                "最低": [98.0] * 15,
                "收盘": [100.0] * 15,
                "成交量": [1000] * 15,
            }
        )
        fetcher = EfinanceFetcher()
        with patch.object(fetcher, "_fetch_raw_data", return_value=raw_df):
            df = fetcher.get_daily_data("600519", start_date=dates[0], end_date=dates[-1])

        self.assertFalse(df.attrs.get("ohlc_synthesized", False))
        self.assertEqual(df.attrs.get("price_adjustment"), "forward")

        stub_manager = _StubFetcherManager(df, "EfinanceFetcher", "贵州茅台")
        with patch("data_provider.base.DataFetcherManager", return_value=stub_manager):
            resp = _create_stocks_client().get("/api/v1/stocks/600519/history?period=daily&days=15")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIs(payload["ohlc_synthesized"], False)
        self.assertEqual(payload["price_adjustment"], "forward")
        self.assertEqual(payload["data"][-1]["open"], 99.0)
        self.assertEqual(payload["data"][-1]["high"], 102.0)
        self.assertEqual(payload["data"][-1]["low"], 98.0)

    def test_alphavantage_marks_unadjusted_and_propagates_to_history_api(self) -> None:
        dates = pd.bdate_range("2026-08-01", periods=60)
        closes = [100.0] * 59 + [50.0]
        raw_df = pd.DataFrame(
            {
                "1. open": closes,
                "2. high": closes,
                "3. low": closes,
                "4. close": closes,
                "5. volume": [100000.0] * 60,
            },
            index=dates,
        )
        fetcher = AlphaVantageFetcher()
        fetcher._api_key = "test_key"
        with patch.object(fetcher, "_fetch_raw_data", return_value=raw_df):
            df = fetcher.get_daily_data("AAPL", start_date="2026-08-01", end_date="2026-11-30")

        self.assertEqual(df.attrs.get("price_adjustment"), "unadjusted")

        stub_manager = _StubFetcherManager(df, "AlphaVantageFetcher", "Apple Inc.")
        with patch("data_provider.base.DataFetcherManager", return_value=stub_manager):
            resp = _create_stocks_client().get("/api/v1/stocks/AAPL/history?period=daily&days=60")

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["price_adjustment"], "unadjusted")
        self.assertIs(payload["ohlc_synthesized"], False)
        self.assertEqual(len(payload["data"]), 60)

    def test_tushare_pytdx_and_tickflow_normalize_set_adjustment_attrs(self) -> None:
        ts_raw = pd.DataFrame(
            {
                "trade_date": ["20261119", "20261120"],
                "open": [10.0, 10.5],
                "high": [10.6, 10.8],
                "low": [9.9, 10.2],
                "close": [10.4, 10.7],
                "vol": [100.0, 120.0],
                "amount": [104.0, 128.0],
                "pct_chg": [1.0, 2.88],
            }
        )
        ts_df = TushareFetcher.__new__(TushareFetcher)._normalize_data(ts_raw, "600519")
        self.assertEqual(ts_df.attrs.get("price_adjustment"), "unadjusted")

        tdx_raw = pd.DataFrame(
            {
                "datetime": ["2026-11-19", "2026-11-20"],
                "open": [10.0, 10.5],
                "high": [10.6, 10.8],
                "low": [9.9, 10.2],
                "close": [10.4, 10.7],
                "vol": [10000.0, 12000.0],
                "amount": [104000.0, 128000.0],
            }
        )
        tdx_df = PytdxFetcher.__new__(PytdxFetcher)._normalize_data(tdx_raw, "600519")
        self.assertEqual(tdx_df.attrs.get("price_adjustment"), "unadjusted")

        tf_raw = pd.DataFrame(
            {
                "trade_date": ["2026-11-19", "2026-11-20"],
                "open": [10.0, 10.5],
                "high": [10.6, 10.8],
                "low": [9.9, 10.2],
                "close": [10.4, 10.7],
                "volume": [100.0, 120.0],
                "amount": [104000.0, 128000.0],
            }
        )
        tf_unadj = TickFlowFetcher(api_key="test-key", kline_adjust="none")._normalize_data(tf_raw, "600519")
        self.assertEqual(tf_unadj.attrs.get("price_adjustment"), "unadjusted")
        tf_fwd = TickFlowFetcher(api_key="test-key", kline_adjust="forward")._normalize_data(tf_raw, "600519")
        self.assertEqual(tf_fwd.attrs.get("price_adjustment"), "forward")
