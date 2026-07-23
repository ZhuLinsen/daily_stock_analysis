# -*- coding: utf-8 -*-
"""Tests for AkshareFetcher.get_stock_list bulk stock-list fallback."""

import os
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.akshare_fetcher import AkshareFetcher


class TestAkshareStockList(unittest.TestCase):
    def test_returns_dataframe_with_code_and_name_columns(self):
        fetcher = AkshareFetcher()
        df = pd.DataFrame(
            {
                "code": ["600519", "000001", "300750"],
                "name": ["贵州茅台", "平安银行", "宁德时代"],
            }
        )
        fake_ak = types.SimpleNamespace(stock_info_a_code_name=lambda: df)

        with patch.dict(sys.modules, {"akshare": fake_ak}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                result = fetcher.get_stock_list()

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 3)
        self.assertIn("code", result.columns)
        self.assertIn("name", result.columns)

    def test_returns_none_when_underlying_call_raises(self):
        fetcher = AkshareFetcher()

        def boom():
            raise RuntimeError("network down")

        fake_ak = types.SimpleNamespace(stock_info_a_code_name=boom)

        with patch.dict(sys.modules, {"akshare": fake_ak}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                result = fetcher.get_stock_list()

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()