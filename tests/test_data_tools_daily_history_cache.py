# -*- coding: utf-8 -*-
"""Tests for Agent get_daily_history DB cache reuse."""

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Optional
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from src.agent.tools.data_tools import _handle_get_daily_history
from src.services.history_loader import reset_frozen_target_date, set_frozen_target_date


class _DailyRow:
    def __init__(self, code: str, row_date: date, close: float) -> None:
        self.code = code
        self.date = row_date
        self.open = close - 1
        self.high = close + 1
        self.low = close - 2
        self.close = close
        self.volume = 1000
        self.amount = 10000
        self.pct_chg = 1.2
        self.ma5 = close - 0.5
        self.ma10 = close - 1
        self.ma20 = close - 2
        self.volume_ratio = 1.1
        self.data_source = "unit-test"

    def to_dict(self):
        return {
            "code": self.code,
            "date": self.date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "pct_chg": self.pct_chg,
            "ma5": self.ma5,
            "ma10": self.ma10,
            "ma20": self.ma20,
            "volume_ratio": self.volume_ratio,
            "data_source": self.data_source,
        }


def _rows(code: str, latest: date, count: int):
    return [
        _DailyRow(code, latest - timedelta(days=offset), close=100 + offset)
        for offset in range(count)
    ]


class _FakeDb:
    def __init__(self, rows_by_code=None, save_error: Optional[Exception] = None) -> None:
        self.rows_by_code = rows_by_code or {}
        self.save_error = save_error
        self.save_daily_data = MagicMock(side_effect=self._save_daily_data)

    def get_data_range(self, code: str, start_date: date, end_date: date):
        rows = [
            row
            for row in self.rows_by_code.get(code, [])
            if start_date <= row.date <= end_date
        ]
        return sorted(rows, key=lambda row: row.date)

    def _save_daily_data(self, df, code: str, source: str):
        if self.save_error:
            raise self.save_error
        return len(df)


class DailyHistoryCacheToolTest(unittest.TestCase):
    def _run_with_frozen_date(self, target: date, stock_code: str, days: int):
        token = set_frozen_target_date(target)
        try:
            return _handle_get_daily_history(stock_code, days=days)
        finally:
            reset_frozen_target_date(token)

    def test_uses_fresh_partial_db_cache_without_fetching(self) -> None:
        target = date(2026, 4, 24)
        db = _FakeDb({"600519": _rows("600519", target, 30)})
        manager = SimpleNamespace(get_daily_data=MagicMock())

        with patch("src.storage.get_db", return_value=db), \
             patch("src.services.history_loader._get_fetcher_manager", return_value=manager):
            result = self._run_with_frozen_date(target, "600519", days=60)

        self.assertEqual(result["source"], "db_cache")
        self.assertTrue(result["cache_hit"])
        self.assertTrue(result["partial_cache"])
        self.assertEqual(result["actual_records"], 30)
        self.assertEqual(result["requested_days"], 60)
        self.assertEqual(result["data"][0]["date"], str(target - timedelta(days=29)))
        self.assertEqual(result["data"][-1]["date"], str(target))
        manager.get_daily_data.assert_not_called()

    def test_prefers_fuller_candidate_when_dates_tie(self) -> None:
        target = date(2026, 4, 24)
        db = _FakeDb(
            {
                "1810.HK": _rows("1810.HK", target, 40),
                "HK01810": _rows("HK01810", target, 30),
            }
        )
        manager = SimpleNamespace(get_daily_data=MagicMock())

        with patch("src.storage.get_db", return_value=db), \
             patch("src.services.history_loader._get_fetcher_manager", return_value=manager):
            result = self._run_with_frozen_date(target, "1810.HK", days=60)

        self.assertEqual(result["code"], "1810.HK")
        self.assertEqual(result["actual_records"], 40)
        manager.get_daily_data.assert_not_called()

    def test_prefers_normalized_candidate_when_dates_and_counts_tie(self) -> None:
        target = date(2026, 4, 24)
        db = _FakeDb(
            {
                "1810.HK": _rows("1810.HK", target, 30),
                "HK01810": _rows("HK01810", target, 30),
            }
        )
        manager = SimpleNamespace(get_daily_data=MagicMock())

        with patch("src.storage.get_db", return_value=db), \
             patch("src.services.history_loader._get_fetcher_manager", return_value=manager):
            result = self._run_with_frozen_date(target, "1810.HK", days=60)

        self.assertEqual(result["code"], "HK01810")
        self.assertEqual(result["actual_records"], 30)
        manager.get_daily_data.assert_not_called()

    def test_fetches_and_persists_when_cache_is_stale(self) -> None:
        target = date(2026, 4, 24)
        db = _FakeDb({"600519": _rows("600519", target - timedelta(days=1), 30)})
        df = pd.DataFrame(
            [
                {"date": target, "open": 1, "high": 2, "low": 0.5, "close": 1.5},
            ]
        )
        manager = SimpleNamespace(get_daily_data=MagicMock(return_value=(df, "Fetcher")))

        with patch("src.storage.get_db", return_value=db), \
             patch("src.agent.tools.data_tools._get_db", return_value=db), \
             patch("src.services.history_loader._get_fetcher_manager", return_value=manager):
            result = self._run_with_frozen_date(target, "600519", days=60)

        manager.get_daily_data.assert_called_once_with("600519", days=60)
        db.save_daily_data.assert_called_once_with(df, "600519", "Fetcher")
        self.assertFalse(result["cache_hit"])
        self.assertEqual(result["source"], "Fetcher")

    def test_save_failure_does_not_hide_fetched_data(self) -> None:
        target = date(2026, 4, 24)
        db = _FakeDb(save_error=RuntimeError("db locked"))
        df = pd.DataFrame(
            [
                {"date": target, "open": 1, "high": 2, "low": 0.5, "close": 1.5},
            ]
        )
        manager = SimpleNamespace(get_daily_data=MagicMock(return_value=(df, "Fetcher")))

        with patch("src.storage.get_db", return_value=db), \
             patch("src.agent.tools.data_tools._get_db", return_value=db), \
             patch("src.services.history_loader._get_fetcher_manager", return_value=manager):
            result = self._run_with_frozen_date(target, "600519", days=60)

        self.assertEqual(result["total_records"], 1)
        self.assertEqual(result["data"][0]["date"], str(target))

    def test_db_read_exception_falls_back_to_fetch(self) -> None:
        target = date(2026, 4, 24)
        df = pd.DataFrame(
            [{"date": target, "open": 1, "high": 2, "low": 0.5, "close": 1.5}]
        )
        manager = SimpleNamespace(get_daily_data=MagicMock(return_value=(df, "Fetcher")))
        broken_db = MagicMock()
        broken_db.get_data_range.side_effect = RuntimeError("db corrupted")
        broken_db.save_daily_data.return_value = 1

        with patch("src.storage.get_db", return_value=broken_db), \
             patch("src.agent.tools.data_tools._get_db", return_value=broken_db), \
             patch("src.services.history_loader._get_fetcher_manager", return_value=manager):
            result = self._run_with_frozen_date(target, "600519", days=60)

        manager.get_daily_data.assert_called_once_with("600519", days=60)
        self.assertFalse(result["cache_hit"])
        self.assertEqual(result["source"], "Fetcher")

    def test_days_one_cache_hit_with_single_fresh_record(self) -> None:
        target = date(2026, 4, 24)
        db = _FakeDb({"600519": _rows("600519", target, 1)})
        manager = SimpleNamespace(get_daily_data=MagicMock())

        with patch("src.storage.get_db", return_value=db), \
             patch("src.services.history_loader._get_fetcher_manager", return_value=manager):
            result = self._run_with_frozen_date(target, "600519", days=1)

        self.assertTrue(result["cache_hit"])
        self.assertEqual(result["actual_records"], 1)
        self.assertFalse(result["partial_cache"])
        manager.get_daily_data.assert_not_called()

    def test_days_are_normalized_with_warning(self) -> None:
        target = date(2026, 4, 24)
        db = _FakeDb()
        df = pd.DataFrame([{"date": target, "close": 1.5}])
        manager = SimpleNamespace(get_daily_data=MagicMock(return_value=(df, "Fetcher")))

        with patch("src.storage.get_db", return_value=db), \
             patch("src.agent.tools.data_tools._get_db", return_value=db), \
             patch("src.services.history_loader._get_fetcher_manager", return_value=manager):
            result = self._run_with_frozen_date(target, "600519", days=999)

        manager.get_daily_data.assert_called_once_with("600519", days=365)
        self.assertEqual(result["requested_days"], 999)
        self.assertEqual(result["effective_days"], 365)
        self.assertIn("warning", result)


if __name__ == "__main__":
    unittest.main()
