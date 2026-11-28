# -*- coding: utf-8 -*-
"""Unit tests for src.services.history_loader (Issue #1066)."""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd


class HistoryLoaderTestCase(unittest.TestCase):
    """Tests for load_history_df and frozen target date ContextVar."""

    # ------------------------------------------------------------------
    # ContextVar lifecycle
    # ------------------------------------------------------------------
    def test_frozen_target_date_lifecycle(self):
        from src.services.history_loader import (
            get_frozen_target_date,
            reset_frozen_target_date,
            set_frozen_target_date,
        )

        self.assertIsNone(get_frozen_target_date())
        d = date(2026, 4, 18)
        token = set_frozen_target_date(d)
        self.assertEqual(get_frozen_target_date(), d)
        reset_frozen_target_date(token)
        self.assertIsNone(get_frozen_target_date())

    # ------------------------------------------------------------------
    # DB hit path
    # ------------------------------------------------------------------
    @patch("src.storage.get_db")
    def test_returns_db_data_when_sufficient(self, mock_get_db):
        from src.services.history_loader import load_history_df

        fake_bar = MagicMock()
        fake_bar.to_dict.return_value = {
            "date": "2026-04-18",
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10.5,
            "volume": 100,
        }
        mock_db = MagicMock()
        mock_db.get_data_range.return_value = [fake_bar] * 40
        mock_get_db.return_value = mock_db

        df, source = load_history_df("600519", days=60, target_date=date(2026, 4, 18))

        self.assertIsNotNone(df)
        self.assertEqual(source, "db_cache")
        self.assertEqual(len(df), 40)
        mock_db.get_data_range.assert_called_once()

    # ------------------------------------------------------------------
    # DB miss → DFM fallback
    # ------------------------------------------------------------------
    @patch("src.services.history_loader._get_fetcher_manager")
    @patch("src.storage.get_db")
    def test_falls_back_to_dfm_when_db_empty(self, mock_get_db, mock_get_fm):
        from src.services.history_loader import load_history_df

        mock_db = MagicMock()
        mock_db.get_data_range.return_value = []
        mock_get_db.return_value = mock_db

        fake_df = pd.DataFrame({"close": [1, 2, 3]})
        mock_fm = MagicMock()
        mock_fm.get_daily_data.return_value = (fake_df, "eastmoney")
        mock_get_fm.return_value = mock_fm

        df, source = load_history_df("600519", days=60, target_date=date(2026, 4, 18))

        self.assertIsNotNone(df)
        self.assertEqual(source, "eastmoney")
        mock_fm.get_daily_data.assert_called_once_with(
            "600519",
            end_date="2026-04-18",
            days=60,
        )

    @patch("src.services.history_loader._get_fetcher_manager")
    @patch("src.storage.get_db")
    def test_fallback_drops_post_freeze_rows_when_cache_misses(self, mock_get_db, mock_get_fm):
        from src.services.history_loader import (
            load_history_df,
            reset_frozen_target_date,
            set_frozen_target_date,
        )

        frozen_date = date(2026, 4, 15)
        token = set_frozen_target_date(frozen_date)
        try:
            mock_db = MagicMock()
            mock_db.get_data_range.return_value = []
            mock_get_db.return_value = mock_db

            provider_df = pd.DataFrame([
                {"date": "2026-04-14", "close": 99.0},
                {"date": "2026-04-15", "close": 100.0},
                {"date": "2026-04-16", "close": 130.0},
            ])
            mock_fm = MagicMock()
            mock_fm.get_daily_data.return_value = (provider_df, "akshare")
            mock_get_fm.return_value = mock_fm

            df, source = load_history_df("600519", days=60, min_records=60)
            self.assertEqual(source, "akshare")
            mock_fm.get_daily_data.assert_called_once_with(
                "600519",
                end_date="2026-04-15",
                days=60,
            )
            self.assertEqual(list(df["date"]), ["2026-04-14", "2026-04-15"])
        finally:
            reset_frozen_target_date(token)

    @patch("src.services.history_loader._get_fetcher_manager")
    @patch("src.storage.get_db")
    def test_prefers_fresher_fallback_over_stale_cache_and_fuller_fresh_db_when_dates_tie(
        self, mock_get_db, mock_get_fm
    ):
        from datetime import timedelta
        from src.services.history_loader import load_history_df

        target = date(2026, 4, 24)
        stale_bars = []
        for idx in range(30):
            bar = MagicMock()
            bar.to_dict.return_value = {
                "date": (target - timedelta(days=1 + idx)).isoformat(),
                "close": 100.0 + idx,
            }
            bar.date = target - timedelta(days=1 + idx)
            stale_bars.append(bar)

        mock_db = MagicMock()
        mock_db.get_data_range.return_value = stale_bars
        mock_get_db.return_value = mock_db

        fresher_small_df = pd.DataFrame([{"date": target.isoformat(), "close": 150.0}])
        mock_fm = MagicMock()
        mock_fm.get_daily_data.return_value = (fresher_small_df, "Fetcher")
        mock_get_fm.return_value = mock_fm

        df, source = load_history_df("600519", days=60, target_date=target)
        self.assertEqual(source, "Fetcher")
        self.assertIs(df, fresher_small_df)

        fresh_bars = []
        for idx in range(30):
            bar = MagicMock()
            bar.to_dict.return_value = {
                "date": (target - timedelta(days=idx)).isoformat(),
                "close": 100.0 + idx,
            }
            bar.date = target - timedelta(days=idx)
            fresh_bars.append(bar)
        mock_db.get_data_range.return_value = fresh_bars

        smaller_same_date_df = pd.DataFrame([
            {"date": (target - timedelta(days=idx)).isoformat(), "close": 110.0 + idx}
            for idx in range(5)
        ])
        mock_fm.get_daily_data.return_value = (smaller_same_date_df, "Fetcher")

        df_retained, source_retained = load_history_df(
            "600519", days=60, target_date=target, min_records=60
        )
        self.assertEqual(source_retained, "db_cache")
        self.assertEqual(len(df_retained), 30)

    # ------------------------------------------------------------------
    # ContextVar integration
    # ------------------------------------------------------------------
    @patch("src.storage.get_db")
    def test_uses_frozen_target_date_from_contextvar(self, mock_get_db):
        from src.services.history_loader import (
            load_history_df,
            reset_frozen_target_date,
            set_frozen_target_date,
        )

        frozen_date = date(2026, 4, 15)
        token = set_frozen_target_date(frozen_date)
        try:
            mock_db = MagicMock()
            fake_bar = MagicMock()
            fake_bar.to_dict.return_value = {"date": "2026-04-15", "close": 10}
            mock_db.get_data_range.return_value = [fake_bar] * 30
            mock_get_db.return_value = mock_db

            df, source = load_history_df("600519", days=30)

            self.assertEqual(source, "db_cache")
            call_args = mock_db.get_data_range.call_args
            _code, _start, end = call_args[0]
            self.assertEqual(end, frozen_date)
        finally:
            reset_frozen_target_date(token)

    # ------------------------------------------------------------------
    # normalize_stock_code fallback for prefixed codes
    # ------------------------------------------------------------------
    @patch("src.storage.get_db")
    def test_uses_normalize_fallback_for_prefixed_code(self, mock_get_db):
        from src.services.history_loader import load_history_df

        fake_bar = MagicMock()
        fake_bar.to_dict.return_value = {"date": "2026-04-18", "close": 10}

        mock_db = MagicMock()

        def side_effect(code, start, end):
            if code == "SH600519":
                return []
            return [fake_bar] * 30

        mock_db.get_data_range.side_effect = side_effect
        mock_get_db.return_value = mock_db

        df, source = load_history_df("SH600519", days=30, target_date=date(2026, 4, 18))

        self.assertEqual(source, "db_cache")
        self.assertEqual(mock_db.get_data_range.call_count, 2)

    # ------------------------------------------------------------------
    # Both paths fail gracefully
    # ------------------------------------------------------------------
    @patch("src.services.history_loader._get_fetcher_manager")
    @patch("src.storage.get_db")
    def test_graceful_when_both_fail(self, mock_get_db, mock_get_fm):
        from src.services.history_loader import load_history_df

        mock_db = MagicMock()
        mock_db.get_data_range.side_effect = Exception("DB down")
        mock_get_db.return_value = mock_db

        mock_fm = MagicMock()
        mock_fm.get_daily_data.side_effect = Exception("API down")
        mock_get_fm.return_value = mock_fm

        df, source = load_history_df("600519", days=60, target_date=date(2026, 4, 18))

        self.assertIsNone(df)
        self.assertEqual(source, "none")


if __name__ == "__main__":
    unittest.main()
