# -*- coding: utf-8 -*-
"""Tests for EfinanceFetcher.get_stock_name fallback implementation."""

import os
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.efinance_fetcher import EfinanceFetcher


class TestEfinanceStockName(unittest.TestCase):
    def test_returns_name_string_when_base_info_has_name(self):
        fetcher = EfinanceFetcher()
        fake_series = pd.Series(
            {"股票代码": "600519", "股票名称": "贵州茅台", "市盈率": 25.0}
        )
        fake_ef = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_base_info=lambda code: fake_series)
        )

        with patch.dict(sys.modules, {"efinance": fake_ef}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                name = fetcher.get_stock_name("600519")

        self.assertEqual(name, "贵州茅台")

    def test_returns_none_when_underlying_call_raises(self):
        fetcher = EfinanceFetcher()

        def boom(code):
            raise RuntimeError("network down")

        fake_ef = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_base_info=boom)
        )

        with patch.dict(sys.modules, {"efinance": fake_ef}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                name = fetcher.get_stock_name("600519")

        self.assertIsNone(name)


if __name__ == "__main__":
    unittest.main()