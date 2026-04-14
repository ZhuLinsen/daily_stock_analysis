# -*- coding: utf-8 -*-
"""
Regression tests for stock-name prefetch behavior.
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, call, patch
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.base import DataFetcherManager
from data_provider.pytdx_fetcher import PytdxFetcher
from src.core.pipeline import StockAnalysisPipeline


class _DummyFetcher:
    name = "DummyFetcher"

    @staticmethod
    def get_stock_name(_stock_code):
        return "测试股票"


class _ThreadUnsafeStockListFetcher:
    name = "ThreadUnsafeStockListFetcher"

    def __init__(self):
        self._active = False
        self.call_count = 0

    def get_stock_list(self):
        if self._active:
            raise AssertionError("concurrent get_stock_list access")
        self._active = True
        self.call_count += 1
        try:
            time.sleep(0.05)
            return pd.DataFrame(
                [
                    {"code": "600519", "name": "贵州茅台"},
                    {"code": "000001", "name": "平安银行"},
                ]
            )
        finally:
            self._active = False


class TestPrefetchStockNames(unittest.TestCase):
    def test_prefetch_stock_names_calls_get_stock_name_without_realtime(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager.get_stock_name = MagicMock(return_value="")

        DataFetcherManager.prefetch_stock_names(manager, ["SH600519", "000001"], use_bulk=False)

        manager.get_stock_name.assert_has_calls(
            [
                call("600519", allow_realtime=False),
                call("000001", allow_realtime=False),
            ]
        )

    def test_get_stock_name_skips_realtime_when_allow_realtime_false(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = [_DummyFetcher()]
        manager.get_realtime_quote = MagicMock(return_value=MagicMock(name="实时名称"))

        name = DataFetcherManager.get_stock_name(manager, "123456", allow_realtime=False)

        self.assertEqual(name, "测试股票")
        manager.get_realtime_quote.assert_not_called()

    def test_get_stock_name_prefers_static_mapping_before_remote_fetchers(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        remote_fetcher = MagicMock()
        remote_fetcher.name = "RemoteFetcher"
        remote_fetcher.get_stock_name.return_value = "远程名称"
        manager._fetchers = [remote_fetcher]
        manager.get_realtime_quote = MagicMock()

        with patch("data_provider.base.get_index_stock_name", return_value=None):
            name = DataFetcherManager.get_stock_name(manager, "600519", allow_realtime=False)

        self.assertEqual(name, "贵州茅台")
        manager.get_realtime_quote.assert_not_called()
        remote_fetcher.get_stock_name.assert_not_called()
        self.assertEqual(manager._stock_name_cache["600519"], "贵州茅台")

    def test_get_stock_name_prefers_index_mapping_before_remote_fetchers(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        remote_fetcher = MagicMock()
        remote_fetcher.name = "RemoteFetcher"
        remote_fetcher.get_stock_name.return_value = "远程名称"
        manager._fetchers = [remote_fetcher]
        manager.get_realtime_quote = MagicMock()

        with patch("data_provider.base.get_index_stock_name", return_value="索引名称"):
            name = DataFetcherManager.get_stock_name(manager, "123456", allow_realtime=False)

        self.assertEqual(name, "索引名称")
        manager.get_realtime_quote.assert_not_called()
        remote_fetcher.get_stock_name.assert_not_called()
        self.assertEqual(manager._stock_name_cache["123456"], "索引名称")

    def test_get_stock_name_prefers_static_mapping_before_index_hits(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = []
        manager.get_realtime_quote = MagicMock()

        with patch.dict("data_provider.base.STOCK_NAME_MAP", {"AAPL": "苹果"}, clear=True):
            with patch("data_provider.base.get_index_stock_name", return_value="APPLE"):
                name = DataFetcherManager.get_stock_name(manager, "AAPL")

        self.assertEqual(name, "苹果")
        manager.get_realtime_quote.assert_not_called()
        self.assertEqual(manager._stock_name_cache["AAPL"], "苹果")

    def test_get_stock_name_prefers_index_mapping_before_realtime_quote(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = []
        manager.get_realtime_quote = MagicMock(return_value=SimpleNamespace(name="实时名称"))

        with patch.dict("data_provider.base.STOCK_NAME_MAP", {}, clear=True):
            with patch("data_provider.base.get_index_stock_name", return_value="索引名称"):
                name = DataFetcherManager.get_stock_name(manager, "123456", allow_realtime=True)

        self.assertEqual(name, "索引名称")
        manager.get_realtime_quote.assert_not_called()
        self.assertEqual(manager._stock_name_cache["123456"], "索引名称")

    def test_get_stock_name_preserves_raw_exchange_hint_for_realtime_lookup(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = []
        manager.get_realtime_quote = MagicMock(return_value=SimpleNamespace(name="平安银行"))

        with patch.dict("data_provider.base.STOCK_NAME_MAP", {}, clear=True):
            with patch("data_provider.base.get_index_stock_name", return_value=None):
                name = DataFetcherManager.get_stock_name(manager, "000001.SZ")

        self.assertEqual(name, "平安银行")
        manager.get_realtime_quote.assert_called_once_with("000001.SZ", log_final_failure=False)

    def test_fetch_and_save_stock_data_uses_lightweight_name_lookup(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        pipeline.fetcher_manager.get_stock_name.return_value = "贵州茅台"
        pipeline.db.has_today_data.return_value = False
        pipeline.fetcher_manager.get_daily_data.return_value = (
            pd.DataFrame(
                [
                    {
                        "date": "2026-03-27",
                        "open": 1.0,
                        "high": 1.0,
                        "low": 1.0,
                        "close": 1.0,
                        "volume": 1,
                        "amount": 1.0,
                        "pct_chg": 0.0,
                    }
                ]
            ),
            "dummy",
        )
        pipeline.db.save_daily_data.return_value = 1

        success, error = StockAnalysisPipeline.fetch_and_save_stock_data(pipeline, "600519")

        self.assertTrue(success)
        self.assertIsNone(error)
        pipeline.fetcher_manager.get_stock_name.assert_called_once_with("600519", allow_realtime=False)

    def test_pytdx_get_stock_name_reads_all_security_list_pages(self):
        fetcher = PytdxFetcher(hosts=[])

        first_page = [
            {"code": f"{index:06d}", "name": f"股票{index:06d}"}
            for index in range(1000)
        ]
        second_page = [{"code": "300750", "name": "宁德时代"}]

        api = MagicMock()

        def fake_get_security_list(market, start):
            if market == 0 and start == 0:
                return first_page
            if market == 0 and start == 1000:
                return second_page
            return []

        api.get_security_list.side_effect = fake_get_security_list
        api.get_finance_info.return_value = None

        session = MagicMock()
        session.__enter__.return_value = api
        session.__exit__.return_value = False

        with patch.object(fetcher, "_pytdx_session", return_value=session):
            name = fetcher.get_stock_name("300750")

        self.assertEqual(name, "宁德时代")
        self.assertEqual(fetcher._stock_name_cache["300750"], "宁德时代")
        self.assertEqual(fetcher._stock_list_cache["300750"], "宁德时代")
        api.get_finance_info.assert_not_called()

    def test_batch_get_stock_names_serializes_shared_fetcher_access(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = [_ThreadUnsafeStockListFetcher()]

        barrier = threading.Barrier(2)
        errors = []
        results = []

        def worker():
            try:
                barrier.wait(timeout=1)
                result = DataFetcherManager.batch_get_stock_names(manager, ["600519", "000001"])
                results.append(result)
            except Exception as exc:  # pragma: no cover - thread collection
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertEqual(result["600519"], "贵州茅台")
            self.assertEqual(result["000001"], "平安银行")
        self.assertGreaterEqual(manager._fetchers[0].call_count, 1)
        self.assertEqual(manager._stock_name_cache["600519"], "贵州茅台")
        self.assertEqual(manager._stock_name_cache["000001"], "平安银行")


if __name__ == "__main__":
    unittest.main()
