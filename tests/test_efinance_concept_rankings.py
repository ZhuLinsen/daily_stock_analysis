# -*- coding: utf-8 -*-
"""Tests for EfinanceFetcher.get_concept_rankings fallback implementation."""

import os
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.efinance_fetcher import EfinanceFetcher


class TestEfinanceConceptRankings(unittest.TestCase):
    def test_returns_top_and_bottom_lists(self):
        fetcher = EfinanceFetcher()
        df = pd.DataFrame(
            {
                "板块名称": ["A", "B", "C", "D", "E", "F"],
                "涨跌幅": [5.1, 3.2, 1.0, -1.0, -3.2, -5.1],
            }
        )
        captured = {}

        def fake_realtime_quotes(fs, **kwargs):
            captured["fs"] = fs
            return df

        fake_ef = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=fake_realtime_quotes)
        )

        with patch.dict(sys.modules, {"efinance": fake_ef}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                top, bottom = fetcher.get_concept_rankings(n=3)

        self.assertEqual(captured["fs"], ["概念板块"])
        self.assertEqual(len(top), 3)
        self.assertEqual(len(bottom), 3)
        self.assertEqual(top[0]["name"], "A")
        self.assertEqual(bottom[0]["name"], "F")

    def test_returns_none_when_underlying_call_raises(self):
        fetcher = EfinanceFetcher()

        def boom(fs, **kwargs):
            raise RuntimeError("network down")

        fake_ef = types.SimpleNamespace(
            stock=types.SimpleNamespace(get_realtime_quotes=boom)
        )

        with patch.dict(sys.modules, {"efinance": fake_ef}):
            with patch.object(fetcher, "_set_random_user_agent", return_value=None), patch.object(
                fetcher, "_enforce_rate_limit", return_value=None
            ):
                result = fetcher.get_concept_rankings(n=3)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()