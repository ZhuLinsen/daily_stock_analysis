# -*- coding: utf-8 -*-
"""Tests for AkshareFetcher.get_belong_board fallback implementation."""

import os
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.akshare_fetcher import AkshareFetcher


class TestAkshareBelongBoard(unittest.TestCase):
    def test_returns_dataframe_when_stock_found_in_industry_boards(self):
        fetcher = AkshareFetcher()
        industry_names_df = pd.DataFrame({"板块名称": ["白酒", "新能源"]})
        industry_cons_df = pd.DataFrame(
            {"代码": ["600519", "000001"], "名称": ["贵州茅台", "平安银行"]}
        )
        concept_names_df = pd.DataFrame(columns=["板块名称"])
        concept_cons_df = pd.DataFrame(columns=["代码", "名称"])

        fake_ak = types.SimpleNamespace(
            stock_board_industry_name_em=lambda: industry_names_df,
            stock_board_industry_cons_em=lambda symbol: industry_cons_df,
            stock_board_concept_name_em=lambda: concept_names_df,
            stock_board_concept_cons_em=lambda symbol: concept_cons_df,
        )

        with patch.dict(sys.modules, {"akshare": fake_ak}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                df = fetcher.get_belong_board("600519")

        self.assertIsNotNone(df)
        self.assertGreaterEqual(len(df), 1)
        self.assertIn("name", df.columns)

    def test_returns_none_when_underlying_call_raises(self):
        fetcher = AkshareFetcher()
        fake_ak = types.SimpleNamespace(
            stock_board_industry_name_em=lambda: (_ for _ in ()).throw(
                RuntimeError("network down")
            ),
            stock_board_industry_cons_em=lambda symbol: pd.DataFrame(),
            stock_board_concept_name_em=lambda: pd.DataFrame(columns=["板块名称"]),
            stock_board_concept_cons_em=lambda symbol: pd.DataFrame(),
        )

        with patch.dict(sys.modules, {"akshare": fake_ak}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                df = fetcher.get_belong_board("600519")

        self.assertIsNone(df)


if __name__ == "__main__":
    unittest.main()