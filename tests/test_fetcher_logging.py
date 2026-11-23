import logging
import os
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.base import BaseFetcher, DataFetchError, DataFetcherManager
from data_provider.efinance_fetcher import EfinanceFetcher
from scripts.check_english_logs import CJK_RE


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-03-06", "2026-03-07"],
            "open": [10.0, 10.2],
            "high": [10.5, 10.4],
            "low": [9.8, 10.1],
            "close": [10.3, 10.35],
            "volume": [1000, 1200],
            "amount": [10300, 12420],
            "pct_chg": [1.0, 0.49],
        }
    )


class _SuccessFetcher(BaseFetcher):
    name = "SuccessFetcher"
    priority = 1

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return _sample_df()

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        return df


class _FailureFetcher(BaseFetcher):
    name = "FailureFetcher"
    priority = 0

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise DataFetchError(
            "Eastmoney 历史K线接口失败: "
            "endpoint=push2his.eastmoney.com/api/qt/stock/kline/get, "
            "category=remote_disconnect"
        )

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        return df


class _RecordingFetcher(BaseFetcher):
    def __init__(self, name: str, priority: int):
        self.name = name
        self.priority = priority
        self.calls = []

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.calls.append(stock_code)
        return _sample_df()

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        return df


class TestFetcherLogging(unittest.TestCase):
    def test_base_fetcher_logs_start_and_success(self):
        fetcher = _SuccessFetcher()

        with self.assertLogs("data_provider.base", level="INFO") as captured:
            df = fetcher.get_daily_data("600519", start_date="2026-03-01", end_date="2026-03-08")

        log_text = "\n".join(captured.output)
        self.assertFalse(df.empty)
        self.assertIn("[SuccessFetcher] Fetching 600519 daily data", log_text)
        self.assertIn("[SuccessFetcher] 600519 fetch succeeded:", log_text)
        self.assertIn("rows=2", log_text)

    def test_manager_logs_fallback_and_final_success(self):
        manager = DataFetcherManager(fetchers=[_FailureFetcher(), _SuccessFetcher()])

        with self.assertLogs("data_provider.base", level="INFO") as captured:
            df, source = manager.get_daily_data("601006", start_date="2026-01-07", end_date="2026-03-08")

        log_text = "\n".join(captured.output)
        self.assertFalse(df.empty)
        self.assertEqual(source, "SuccessFetcher")
        self.assertIn("[data source attempt 1/2] [FailureFetcher] fetching 601006...", log_text)
        self.assertIn("[data source failed 1/2] [FailureFetcher] 601006:", log_text)
        self.assertIn("[data source switch] 601006: [FailureFetcher] -> [SuccessFetcher]", log_text)
        self.assertIn("[data source complete] 601006 fetched via [SuccessFetcher]:", log_text)

    def test_manager_logs_terminal_failure_as_error(self):
        manager = DataFetcherManager(fetchers=[_FailureFetcher()])

        with self.assertLogs("data_provider.base", level="INFO") as captured:
            with self.assertRaises(DataFetchError) as raised:
                manager.get_daily_data("601006", start_date="2026-01-07", end_date="2026-03-08")

        log_text = "\n".join(captured.output)
        self.assertIn("ERROR:data_provider.base:[data source exhausted] 601006 fetch failed:", log_text)
        self.assertNotIn("所有数据源获取 601006 失败", log_text)
        self.assertIn("所有数据源获取 601006 失败", str(raised.exception))

    def test_us_terminal_failure_keeps_localized_error_out_of_log(self):
        fetcher = _FailureFetcher()
        fetcher.name = "FinnhubFetcher"
        manager = DataFetcherManager(fetchers=[fetcher])

        with (
            patch.object(DataFetcherManager, "_is_daily_source_available", return_value=True),
            self.assertLogs("data_provider.base", level="INFO") as captured,
            self.assertRaises(DataFetchError) as raised,
        ):
            manager.get_daily_data("AAPL", start_date="2026-05-01", end_date="2026-05-08")

        log_text = "\n".join(captured.output)
        self.assertNotIn("美股 AAPL 获取失败", log_text)
        self.assertIn("美股 AAPL 获取失败", str(raised.exception))

    def test_no_available_source_keeps_localized_error_out_of_log(self):
        manager = DataFetcherManager(fetchers=[_SuccessFetcher()])

        with (
            patch.object(manager, "_get_fetchers_snapshot", return_value=[]),
            self.assertLogs("data_provider.base", level="INFO") as captured,
            self.assertRaises(DataFetchError) as raised,
        ):
            manager.get_daily_data("AAPL", start_date="2026-05-01", end_date="2026-05-08")

        log_text = "\n".join(captured.output)
        self.assertIn("no available data source", log_text)
        self.assertNotIn("美股 AAPL 获取失败", log_text)
        self.assertIn("美股 AAPL 获取失败", str(raised.exception))

    def test_manager_skips_builtin_fetchers_that_do_not_support_hk_daily(self):
        efinance = _RecordingFetcher("EfinanceFetcher", 0)
        pytdx = _RecordingFetcher("PytdxFetcher", 1)
        akshare = _RecordingFetcher("AkshareFetcher", 2)
        yfinance = _RecordingFetcher("YfinanceFetcher", 3)

        manager = DataFetcherManager(fetchers=[efinance, pytdx, akshare, yfinance])
        df, source = manager.get_daily_data("1211.HK", start_date="2026-05-01", end_date="2026-05-08")

        self.assertFalse(df.empty)
        self.assertEqual(source, "AkshareFetcher")
        self.assertEqual(efinance.calls, [])
        self.assertEqual(pytdx.calls, [])
        self.assertEqual(akshare.calls, ["HK01211"])
        self.assertEqual(yfinance.calls, [])

    @patch("data_provider.efinance_fetcher.get_config")
    def test_efinance_rejects_hk_daily_without_calling_eastmoney(self, mock_get_config):
        mock_get_config.return_value = types.SimpleNamespace(enable_eastmoney_patch=False)
        fetcher = EfinanceFetcher(sleep_min=0, sleep_max=0)

        with patch.object(fetcher, "_fetch_stock_data") as mock_fetch_stock_data:
            with self.assertRaises(DataFetchError) as captured:
                fetcher.get_daily_data("1211.HK", start_date="2026-05-01", end_date="2026-05-08")

        mock_fetch_stock_data.assert_not_called()
        self.assertIn("不支持港股日线", str(captured.exception))

    def test_efinance_remote_disconnect_then_fallback_has_no_error_logs(self):
        fetcher = EfinanceFetcher()
        fake_efinance = types.SimpleNamespace(
            stock=types.SimpleNamespace(
                get_quote_history=lambda **kwargs: (_ for _ in ()).throw(
                    requests.exceptions.ConnectionError("Remote end closed connection without response")
                )
            )
        )

        with patch.dict(sys.modules, {"efinance": fake_efinance}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                for code in ("601006", "510300"):
                    with self.subTest(code=code):
                        manager = DataFetcherManager(fetchers=[fetcher, _SuccessFetcher()])
                        with self.assertLogs(level="INFO") as captured:
                            df, source = manager.get_daily_data(
                                code, start_date="2026-01-07", end_date="2026-03-08",
                            )

                        self.assertFalse(df.empty)
                        self.assertEqual(source, "SuccessFetcher")
                        self.assertTrue(all(record.levelno < logging.ERROR for record in captured.records))
                        log_text = "\n".join(captured.output)
                        self.assertIn("Eastmoney historical K-line request failed:", log_text)
                        self.assertIn("endpoint=push2his.eastmoney.com/api/qt/stock/kline/get", log_text)
                        self.assertIn("category=remote_disconnect", log_text)
                        self.assertIn(f"WARNING:data_provider.base:[EfinanceFetcher] {code} fetch failed:", log_text)
                        self.assertIn(f"[data source complete] {code} fetched via [SuccessFetcher]:", log_text)

    def test_us_daily_routing_logs_english_primary_and_fallback_without_cjk(self):
        finnhub = _FailureFetcher()
        finnhub.name = "FinnhubFetcher"
        finnhub.priority = 2
        yfinance = _SuccessFetcher()
        yfinance.name = "YfinanceFetcher"
        yfinance.priority = 4

        manager = DataFetcherManager(fetchers=[finnhub, yfinance])
        with (
            patch.object(DataFetcherManager, "_is_daily_source_available", return_value=True),
            patch.object(DataFetcherManager, "_record_daily_source_failure"),
            patch.object(DataFetcherManager, "_record_daily_source_success"),
            self.assertLogs("data_provider.base", level="INFO") as captured,
        ):
            df, source = manager.get_daily_data("AAPL", start_date="2026-05-01", end_date="2026-05-08")

        self.assertFalse(df.empty)
        self.assertEqual(source, "YfinanceFetcher")
        route_messages = [record.getMessage() for record in captured.records if "route..." in record.getMessage()]
        self.assertIn("[data source attempt 1/2] [FinnhubFetcher] US AAPL primary route...", route_messages)
        self.assertIn("[data source attempt 2/2] [YfinanceFetcher] US AAPL fallback route...", route_messages)
        for msg in route_messages:
            self.assertIsNone(CJK_RE.search(msg), f"Unexpected CJK text in log: {msg}")

    def test_cn_index_exhausted_logs_english_without_cjk(self):
        manager = DataFetcherManager(fetchers=[_FailureFetcher()])
        with (
            patch("data_provider.base.record_provider_run") as record_run,
            self.assertLogs("data_provider.base", level="WARNING") as captured,
        ):
            df, source = manager.get_daily_data("sh000688")
            quote = manager.get_realtime_quote("sh000688")

        self.assertTrue(df.empty)
        self.assertEqual(source, "")
        self.assertIsNone(quote)
        log_messages = [record.getMessage() for record in captured.records]
        self.assertTrue(any("[index source exhausted]" in m for m in log_messages))
        self.assertTrue(any("[index realtime exhausted]" in m for m in log_messages))
        for msg in log_messages:
            self.assertIsNone(CJK_RE.search(msg), f"Unexpected CJK text in CN index log: {msg}")
        self.assertTrue(
            any(call.kwargs.get("error_message") == "数据源未配置或暂不可用" for call in record_run.call_args_list)
        )

    def test_sector_rankings_empty_result_logs_english_and_preserves_source_chain(self):
        class _EmptySectorFetcher(BaseFetcher):
            name = "EmptySectorFetcher"
            priority = 1

            def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str):
                return None

            def _normalize_data(self, df, stock_code: str):
                return df

            def get_sector_rankings(self, n: int = 5):
                return None

        manager = DataFetcherManager(fetchers=[_EmptySectorFetcher()])
        top, bottom, source_chain, raw_last_error = manager._get_sector_rankings_with_meta(5)
        self.assertEqual((top, bottom), ([], []))
        self.assertEqual(raw_last_error, "EmptySectorFetcher返回空结果")
        self.assertEqual(len(source_chain), 1)
        self.assertEqual(source_chain[0]["result"], "empty")
        self.assertEqual(source_chain[0]["error"], "EmptySectorFetcher返回空结果")

        with self.assertLogs("data_provider.base", level="WARNING") as captured:
            res_top, res_bottom = manager.get_sector_rankings(5)

        self.assertEqual((res_top, res_bottom), ([], []))
        log_messages = [record.getMessage() for record in captured.records]
        self.assertIn(
            "[sector rankings] all sources failed, last error: EmptySectorFetcher returned empty result",
            log_messages,
        )
        for msg in log_messages:
            self.assertIsNone(CJK_RE.search(msg), f"Unexpected CJK text in sector rankings log: {msg}")


if __name__ == "__main__":
    unittest.main()
