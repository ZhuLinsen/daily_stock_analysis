# -*- coding: utf-8 -*-
"""Regression tests for post-merge Tushare follow-up fixes."""

import importlib.util
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

try:
    json_repair_available = importlib.util.find_spec("json_repair") is not None
except ValueError:
    json_repair_available = "json_repair" in sys.modules

if not json_repair_available and "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()

from data_provider.tushare_fetcher import TushareFetcher


class TestTushareFetcherFollowUps(unittest.TestCase):
    """Cover rate limiting and cross-day trade-calendar refresh behavior."""

    @staticmethod
    def _make_fetcher() -> TushareFetcher:
        with patch.object(TushareFetcher, "_init_api", return_value=None):
            fetcher = TushareFetcher()
        fetcher._api = MagicMock()
        fetcher.priority = 2
        return fetcher

    def test_get_trade_time_refreshes_trade_calendar_when_day_changes(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.side_effect = [
            pd.DataFrame({"cal_date": ["20260317", "20260314"], "is_open": [1, 1]}),
            pd.DataFrame({"cal_date": ["20260318", "20260317"], "is_open": [1, 1]}),
        ]

        with patch.object(
            fetcher,
            "_get_china_now",
            side_effect=[
                datetime(2026, 3, 17, 20, 0),
                datetime(2026, 3, 17, 20, 0),
                datetime(2026, 3, 18, 20, 0),
                datetime(2026, 3, 18, 20, 0),
            ],
        ), patch.object(fetcher, "_check_rate_limit") as rate_limit_mock:
            self.assertEqual(fetcher.get_trade_time(early_time="00:00", late_time="19:00"), "20260317")
            self.assertEqual(fetcher.get_trade_time(early_time="00:00", late_time="19:00"), "20260318")

        self.assertEqual(fetcher._api.trade_cal.call_count, 2)
        self.assertEqual(rate_limit_mock.call_count, 2)

    def test_get_sector_rankings_rate_limits_calendar_and_rankings_api(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {"cal_date": ["20260317", "20260314"], "is_open": [1, 1]}
        )
        fetcher._api.moneyflow_ind_ths.return_value = pd.DataFrame(
            {
                "industry": ["AI", "消费"],
                "pct_change": [1.8, -0.6],
            }
        )

        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 16, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ) as rate_limit_mock:
            top, bottom = fetcher.get_sector_rankings(n=1)

        self.assertEqual(top, [{"name": "AI", "change_pct": 1.8}])
        self.assertEqual(bottom, [{"name": "消费", "change_pct": -0.6}])
        self.assertEqual(rate_limit_mock.call_count, 2)

    def test_get_chip_distribution_rate_limits_all_tushare_calls(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {"cal_date": ["20260317", "20260314"], "is_open": [1, 1]}
        )
        fetcher._api.cyq_chips.return_value = pd.DataFrame(
            {
                "price": [9.0, 10.0, 11.0],
                "percent": [20.0, 50.0, 30.0],
            }
        )
        fetcher._api.daily.return_value = pd.DataFrame({"close": [10.5]})

        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ) as rate_limit_mock:
            chip = fetcher.get_chip_distribution("600519")

        self.assertIsNotNone(chip)
        if chip is None:
            self.fail("expected chip distribution data")
        self.assertEqual(chip.date, "2026-03-17")
        self.assertAlmostEqual(chip.profit_ratio, 0.7)
        self.assertAlmostEqual(chip.avg_cost, 10.1)
        self.assertAlmostEqual(chip.concentration_90, 0.1)
        self.assertAlmostEqual(chip.concentration_70, 0.1)
        self.assertEqual(rate_limit_mock.call_count, 3)
