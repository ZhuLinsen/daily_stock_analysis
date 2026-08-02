# -*- coding: utf-8 -*-
"""Regression tests for low-noise market-review data routing."""

import os
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestMarketLowNoiseMode(unittest.TestCase):
    def _fetcher(self):
        from data_provider.akshare_fetcher import AkshareFetcher

        fetcher = AkshareFetcher.__new__(AkshareFetcher)
        fetcher._set_random_user_agent = lambda: None
        fetcher._enforce_rate_limit = lambda: None
        return fetcher

    def test_market_stats_prefers_sina_and_skips_eastmoney(self):
        calls = {"eastmoney": 0, "sina": 0}

        fake_ak = types.SimpleNamespace()

        def stock_zh_a_spot_em():
            calls["eastmoney"] += 1
            raise AssertionError("Eastmoney should be skipped in low-noise mode")

        def stock_zh_a_spot():
            calls["sina"] += 1
            return pd.DataFrame(
                [
                    {"代码": "600000", "名称": "A", "最新价": 11.0, "昨收": 10.0, "成交额": 1000},
                    {"代码": "000001", "名称": "B", "最新价": 9.0, "昨收": 10.0, "成交额": 1000},
                ]
            )

        fake_ak.stock_zh_a_spot_em = stock_zh_a_spot_em
        fake_ak.stock_zh_a_spot = stock_zh_a_spot

        with patch.dict(os.environ, {"FREE_A_STOCK_LOW_NOISE_MODE": "true"}), patch.dict(
            sys.modules, {"akshare": fake_ak}
        ):
            stats = self._fetcher().get_market_stats()

        self.assertEqual(calls["eastmoney"], 0)
        self.assertEqual(calls["sina"], 1)
        self.assertEqual(stats["up_count"], 1)
        self.assertEqual(stats["down_count"], 1)

    def test_sector_rankings_prefers_sina_and_skips_eastmoney(self):
        calls = {"eastmoney": 0, "sina": 0}

        fake_ak = types.SimpleNamespace()

        def stock_board_industry_name_em():
            calls["eastmoney"] += 1
            raise AssertionError("Eastmoney should be skipped in low-noise mode")

        def stock_sector_spot(indicator="行业"):
            calls["sina"] += 1
            return pd.DataFrame(
                [
                    {"板块": "行业A", "涨跌幅": 2.0},
                    {"板块": "行业B", "涨跌幅": -1.0},
                    {"板块": "行业C", "涨跌幅": 0.5},
                ]
            )

        fake_ak.stock_board_industry_name_em = stock_board_industry_name_em
        fake_ak.stock_sector_spot = stock_sector_spot

        with patch.dict(os.environ, {"FREE_A_STOCK_LOW_NOISE_MODE": "true"}), patch.dict(
            sys.modules, {"akshare": fake_ak}
        ):
            top, bottom = self._fetcher().get_sector_rankings(1)

        self.assertEqual(calls["eastmoney"], 0)
        self.assertEqual(calls["sina"], 1)
        self.assertEqual(top[0]["name"], "行业A")
        self.assertEqual(bottom[0]["name"], "行业B")

    def test_chip_distribution_skips_eastmoney_in_low_noise_mode(self):
        calls = {"cyq": 0}

        fake_ak = types.SimpleNamespace()

        def stock_cyq_em(symbol):
            calls["cyq"] += 1
            raise AssertionError("Eastmoney chip distribution should be skipped in low-noise mode")

        fake_ak.stock_cyq_em = stock_cyq_em

        with patch.dict(os.environ, {"FREE_A_STOCK_LOW_NOISE_MODE": "true"}), patch.dict(
            sys.modules, {"akshare": fake_ak}
        ):
            chip = self._fetcher().get_chip_distribution("600000")

        self.assertIsNone(chip)
        self.assertEqual(calls["cyq"], 0)

    def test_data_fetcher_manager_skips_chip_distribution_in_low_noise_mode(self):
        from data_provider.base import DataFetcherManager

        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._get_fetchers_snapshot = lambda: (_ for _ in ()).throw(
            AssertionError("fetcher loop should not run in low-noise mode")
        )

        with patch.dict(os.environ, {"FREE_A_STOCK_LOW_NOISE_MODE": "true"}):
            chip = manager.get_chip_distribution("600000")

        self.assertIsNone(chip)

    def test_data_fetcher_manager_skips_concept_rankings_in_low_noise_mode(self):
        from data_provider.base import DataFetcherManager

        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._get_fetchers_snapshot = lambda: (_ for _ in ()).throw(
            AssertionError("fetcher loop should not run in low-noise mode")
        )

        with patch.dict(os.environ, {"FREE_A_STOCK_LOW_NOISE_MODE": "true"}):
            top, bottom = manager.get_concept_rankings(5)

        self.assertEqual(top, [])
        self.assertEqual(bottom, [])


if __name__ == "__main__":
    unittest.main()
