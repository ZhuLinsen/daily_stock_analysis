import os
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import data_provider.efinance_fetcher as efinance_fetcher
from data_provider.efinance_fetcher import EfinanceFetcher
from data_provider.realtime_types import get_realtime_circuit_breaker


class TestEfinanceMainIndices(unittest.TestCase):
    def setUp(self):
        self._saved_realtime_cache = dict(efinance_fetcher._realtime_cache)
        self._saved_etf_cache = dict(efinance_fetcher._etf_realtime_cache)
        efinance_fetcher._realtime_cache.update({"data": None, "timestamp": 0, "ttl": 600})
        efinance_fetcher._etf_realtime_cache.update({"data": None, "timestamp": 0, "ttl": 600})
        get_realtime_circuit_breaker().reset()

    def tearDown(self):
        efinance_fetcher._realtime_cache.update(self._saved_realtime_cache)
        efinance_fetcher._etf_realtime_cache.update(self._saved_etf_cache)
        get_realtime_circuit_breaker().reset()

    def test_get_main_indices_prefers_jinkai_column_for_open_price(self):
        fetcher = EfinanceFetcher()
        fake_df = pd.DataFrame(
            {
                "股票代码": ["000001"],
                "最新价": [3200.0],
                "涨跌幅": [0.63],
                "涨跌额": [20.0],
                "今开": [3188.0],
                "开盘": [0.0],
                "最高": [3215.0],
                "最低": [3170.0],
                "成交量": [123456789],
                "成交额": [9876543210.0],
                "振幅": [1.2],
            }
        )
        fake_efinance = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, **kwargs: fake_df)
        )

        with patch.dict(sys.modules, {"efinance": fake_efinance}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                data = fetcher.get_main_indices(region="cn")

        self.assertIsNotNone(data)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["code"], "sh000001")
        self.assertEqual(data[0]["name"], "上证指数")
        self.assertAlmostEqual(data[0]["open"], 3188.0)
        self.assertAlmostEqual(data[0]["current"], 3200.0)

    def test_get_main_indices_falls_back_to_kaipan_when_jinkai_is_missing(self):
        fetcher = EfinanceFetcher()
        fake_df = pd.DataFrame(
            {
                "股票代码": ["000001"],
                "最新价": [3200.0],
                "涨跌幅": [0.63],
                "涨跌额": [20.0],
                "今开": [""],
                "开盘": [3186.0],
                "最高": [3215.0],
                "最低": [3170.0],
                "成交量": [123456789],
                "成交额": [9876543210.0],
                "振幅": [1.2],
            }
        )
        fake_efinance = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, **kwargs: fake_df)
        )

        with patch.dict(sys.modules, {"efinance": fake_efinance}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                data = fetcher.get_main_indices(region="cn")

        self.assertIsNotNone(data)
        self.assertEqual(len(data), 1)
        self.assertAlmostEqual(data[0]["open"], 3186.0)

    def test_get_main_indices_handles_missing_dash_change_and_missing_code_col(self):
        from data_provider.base import DataFetcherManager

        fetcher = EfinanceFetcher()
        fake_df_valid_optional = pd.DataFrame(
            {
                "股票代码": ["000001"],
                "最新价": [3200.0],
                "涨跌幅": ["1.0"],
                "涨跌额": [31.68],
                "今开": ["-"],
                "最高": [float("nan")],
                "最低": [""],
                "成交量": [None],
                "成交额": [None],
                "振幅": [""],
            }
        )
        fake_efinance = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, **kwargs: fake_df_valid_optional)
        )

        with patch.dict(sys.modules, {"efinance": fake_efinance}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                data = fetcher.get_main_indices(region="cn")

        self.assertIsNotNone(data)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["current"], 3200.0)
        self.assertAlmostEqual(data[0]["change"], 31.68)
        self.assertAlmostEqual(data[0]["change_pct"], 1.0)
        self.assertAlmostEqual(data[0]["prev_close"], 3168.32)
        self.assertEqual(data[0]["amount"], 0.0)
        self.assertEqual(data[0]["amplitude"], 0.0)

        for dash_df in (
            pd.DataFrame(
                {
                    "股票代码": ["000001"],
                    "最新价": [3200.0],
                    "涨跌幅": ["-"],
                    "涨跌额": ["-"],
                }
            ),
            pd.DataFrame(
                {
                    "股票代码": ["000001"],
                    "最新价": ["-"],
                    "涨跌幅": ["1.0"],
                    "涨跌额": [31.68],
                }
            ),
        ):
            fake_efinance_dash = types.SimpleNamespace(
                stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, _df=dash_df, **kwargs: _df)
            )
            backup_fetcher = types.SimpleNamespace(
                name="BackupFetcher",
                priority=2,
                get_main_indices=lambda region="cn": [{"code": "sh000001", "current": 3200.0, "change_pct": 1.0}],
            )
            manager = DataFetcherManager(fetchers=[fetcher, backup_fetcher])
            with patch.dict(sys.modules, {"efinance": fake_efinance_dash}):
                with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                    fetcher, "_enforce_rate_limit", return_value=None
                ):
                    self.assertIsNone(fetcher.get_main_indices(region="cn"))
                    fallback_data = manager.get_main_indices(region="cn")
            self.assertEqual(fallback_data[0]["change_pct"], 1.0)

        bad_df = pd.DataFrame({"最新价": [3200.0]})
        fake_efinance_bad = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, **kwargs: bad_df)
        )
        with patch.dict(sys.modules, {"efinance": fake_efinance_bad}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                self.assertIsNone(fetcher.get_main_indices(region="cn"))

    def test_get_realtime_quote_normalizes_prefixed_code_sanitizes_nan_name_and_skips_empty_cache(self):
        fetcher = EfinanceFetcher(sleep_min=0, sleep_max=0)

        fake_empty = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, **kwargs: pd.DataFrame())
        )
        with patch.dict(sys.modules, {"efinance": fake_empty}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                self.assertIsNone(fetcher.get_realtime_quote("600519"))
        self.assertIsNone(efinance_fetcher._realtime_cache["data"])

        fake_df = pd.DataFrame(
            {
                "股票代码": ["600519"],
                "股票名称": [float("nan")],
                "最新价": [1500.0],
                "涨跌幅": [1.5],
                "涨跌额": [22.0],
                "成交量": [1000],
                "成交额": [1500000.0],
            }
        )
        fake_ok = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, **kwargs: fake_df)
        )
        with patch.dict(sys.modules, {"efinance": fake_ok}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                quote = fetcher.get_realtime_quote("SH600519")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, "600519")
        self.assertEqual(quote.name, "")
        self.assertEqual(quote.price, 1500.0)

    def test_get_etf_realtime_quote_does_not_cache_empty_response(self):
        fetcher = EfinanceFetcher(sleep_min=0, sleep_max=0)
        fake_empty = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, **kwargs: pd.DataFrame())
        )
        with patch.dict(sys.modules, {"efinance": fake_empty}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                self.assertIsNone(fetcher._get_etf_realtime_quote("510300"))
        self.assertIsNone(efinance_fetcher._etf_realtime_cache["data"])

    def test_get_market_stats_skips_empty_cache_and_handles_nan_names_and_blank_prices(self):
        fetcher = EfinanceFetcher(sleep_min=0, sleep_max=0)
        fake_empty = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, **kwargs: pd.DataFrame())
        )
        with patch.dict(sys.modules, {"efinance": fake_empty}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                self.assertIsNone(fetcher.get_market_stats())
        self.assertIsNone(efinance_fetcher._realtime_cache["data"])

        fake_df = pd.DataFrame(
            {
                "股票代码": ["600519", "300750", "000001"],
                "股票名称": [float("nan"), "宁德时代", "平安银行"],
                "最新价": [1520.0, "", 9.9],
                "昨日收盘": [1500.0, "--", 11.0],
                "成交额": [100_000_000.0, None, None],
            }
        )
        fake_ok = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, **kwargs: fake_df)
        )
        with patch.dict(sys.modules, {"efinance": fake_ok}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                stats = fetcher.get_market_stats()

        self.assertIsNotNone(stats)
        self.assertEqual(stats["up_count"], 1)
        self.assertEqual(stats["down_count"], 1)
        self.assertEqual(stats["limit_down_count"], 1)
        self.assertAlmostEqual(stats["total_amount"], 1.0)
        self.assertIsNone(fetcher._calc_market_stats(pd.DataFrame({"股票代码": ["600519"]})))

    def test_get_sector_rankings_returns_none_when_all_rows_invalid_and_preserves_caller_df(self):
        fetcher = EfinanceFetcher(sleep_min=0, sleep_max=0)
        all_invalid = pd.DataFrame({"股票名称": ["半导体", ""], "涨跌幅": ["-", float("nan")]})
        original = all_invalid.copy()
        fake_invalid = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, **kwargs: all_invalid)
        )
        with patch.dict(sys.modules, {"efinance": fake_invalid}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                self.assertIsNone(fetcher.get_sector_rankings(n=3))
        pd.testing.assert_frame_equal(all_invalid, original)

        mixed = pd.DataFrame(
            {
                "股票名称": [float("nan"), "   ", "AI"],
                "涨跌幅": ["5.0", "3.0", "2.4"],
            }
        )
        fake_mixed = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, **kwargs: mixed)
        )
        with patch.dict(sys.modules, {"efinance": fake_mixed}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                ranked = fetcher.get_sector_rankings(n=2)
        self.assertEqual(
            ranked,
            ([{"name": "AI", "change_pct": 2.4}], [{"name": "AI", "change_pct": 2.4}]),
        )

    def test_get_realtime_quote_skips_us_and_hk_without_ashare_collision(self):
        fetcher = EfinanceFetcher(sleep_min=0, sleep_max=0)
        efinance_fetcher._realtime_cache["data"] = None
        efinance_fetcher._realtime_cache["timestamp"] = 0

        calls = []
        ashare_df = pd.DataFrame(
            {
                "股票代码": ["000700", "600519"],
                "股票名称": ["模塑科技", "贵州茅台"],
                "最新价": [7.5, 1500.0],
                "涨跌幅": [1.2, 0.5],
            }
        )

        def fake_get_quotes(*args, **kwargs):
            calls.append((args, kwargs))
            return ashare_df

        fake_ef = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=fake_get_quotes)
        )
        with patch.dict(sys.modules, {"efinance": fake_ef}):
            self.assertIsNone(fetcher.get_realtime_quote("00700"))
            self.assertIsNone(fetcher.get_realtime_quote("HK00700"))
            self.assertIsNone(fetcher.get_realtime_quote("AAPL"))
        self.assertEqual(calls, [])

        # Warm A-share cache with 000700 must never match bare 5-digit HK code 00700
        _, empty_hk = fetcher._find_quote_row(ashare_df, "股票代码", "00700")
        self.assertTrue(empty_hk.empty)
        _, empty_hk_prefixed = fetcher._find_quote_row(ashare_df, "股票代码", "HK00700")
        self.assertTrue(empty_hk_prefixed.empty)
        _, empty_us = fetcher._find_quote_row(ashare_df, "股票代码", "AAPL")
        self.assertTrue(empty_us.empty)

    def test_get_market_stats_skips_unidentified_rows_and_falls_back_when_all_prices_invalid(self):
        from data_provider.base import DataFetcherManager

        fetcher = EfinanceFetcher(sleep_min=0, sleep_max=0)
        mixed_df = pd.DataFrame(
            {
                "股票代码": ["600519", float("nan")],
                "股票名称": ["贵州茅台", float("nan")],
                "最新价": [1500.0, 11.0],
                "昨收": [1500.0, 10.0],
                "成交额": [100_000_000.0, 50_000_000.0],
            }
        )
        stats = fetcher._calc_market_stats(mixed_df)
        self.assertIsNotNone(stats)
        self.assertEqual(stats["limit_up_count"], 0)
        self.assertEqual(stats["flat_count"], 1)
        self.assertEqual(stats["up_count"], 0)

        all_invalid_df = pd.DataFrame(
            {
                "股票代码": ["600519", "300750"],
                "股票名称": ["贵州茅台", "宁德时代"],
                "最新价": ["--", 11.0],
                "昨收": [1500.0, "--"],
                "成交额": [100_000_000.0, 100_000_000.0],
            }
        )
        fake_invalid = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=lambda *args, **kwargs: all_invalid_df)
        )
        backup_fetcher = types.SimpleNamespace(
            name="BackupFetcher",
            priority=2,
            get_market_stats=lambda **kwargs: {
                "up_count": 1,
                "down_count": 1,
                "flat_count": 0,
                "limit_up_count": 0,
                "limit_down_count": 0,
                "total_amount": 2.0,
            },
        )
        manager = DataFetcherManager(fetchers=[fetcher, backup_fetcher])
        with patch.dict(sys.modules, {"efinance": fake_invalid}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                self.assertIsNone(fetcher.get_market_stats(allow_cache=False))
                self.assertIsNone(efinance_fetcher._realtime_cache["data"])
                fallback_stats = manager.get_market_stats(allow_cache=False)

        self.assertEqual(fallback_stats["up_count"], 1)
        self.assertEqual(fallback_stats["down_count"], 1)


if __name__ == "__main__":
    unittest.main()
