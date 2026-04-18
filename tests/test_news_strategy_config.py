# -*- coding: utf-8 -*-
"""Tests for NEWS_STRATEGY_PROFILE parsing and effective window calculation."""

import unittest

from src.config import Config, resolve_news_window_days


class NewsStrategyConfigTestCase(unittest.TestCase):
    def test_invalid_profile_fallback_to_short(self) -> None:
        self.assertEqual(Config._parse_news_strategy_profile("bad_value"), "short")

    def test_window_respects_news_max_age_days(self) -> None:
        # medium=7 but max-age=3 -> effective=3
        self.assertEqual(resolve_news_window_days(3, "medium"), 3)
        # long=30 with max-age=30 -> effective=30
        self.assertEqual(resolve_news_window_days(30, "long"), 30)
        # ultra_short=1 with max-age=30 -> effective=1
        self.assertEqual(resolve_news_window_days(30, "ultra_short"), 1)


if __name__ == "__main__":
    unittest.main()
