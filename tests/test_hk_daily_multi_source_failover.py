# -*- coding: utf-8 -*-
"""HK daily data multi-source failover integration drill.

Exercises DataFetcherManager.get_daily_data end-to-end (not just the
routing helper in isolation) for the scenario where the preferred
front-复权 HK sources (AkShare, YFinance) fail and the manager falls
back to the demoted TencentFetcher.
"""

from __future__ import annotations

import unittest

import pandas as pd

from data_provider.base import BaseFetcher, DataFetchError, DataFetcherManager, STANDARD_COLUMNS


class _AlwaysFailFetcher(BaseFetcher):
    """Fetcher stub that always raises, mimicking an upstream outage."""

    allow_empty_daily_data = True

    def __init__(self, name: str, priority: int):
        self.name = name
        self.priority = priority
        self.call_count = 0

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.call_count += 1
        raise DataFetchError(f"[{self.name}] simulated outage for {stock_code}")

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        return df


class _AlwaysEmptyFetcher(BaseFetcher):
    """Fetcher stub that returns no rows, mimicking an unsupported symbol."""

    allow_empty_daily_data = True

    def __init__(self, name: str, priority: int):
        self.name = name
        self.priority = priority

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        return df


class _SucceedingTencentStub(BaseFetcher):
    """Minimal successful stand-in for TencentFetcher's HK response shape."""

    name = "TencentFetcher"
    priority = 0
    allow_empty_daily_data = True

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": ["2026-07-22", "2026-07-23"],
                "open": [468.0, 440.0],
                "high": [468.0, 450.8],
                "low": [440.6, 439.0],
                "close": [440.6, 445.2],
                "volume": [66379871.0, 22888528.0],
                "amount": [None, None],
            }
        )

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        normalized = df.copy()
        normalized["pct_chg"] = normalized["close"].pct_change().fillna(0.0) * 100
        return normalized[STANDARD_COLUMNS]


class HkDailyMultiSourceFailoverTestCase(unittest.TestCase):
    """Real DataFetcherManager.get_daily_data routing, not the isolated filter helper."""

    def test_all_preferred_hk_sources_fail_and_falls_back_to_demoted_tencent(self):
        akshare = _AlwaysFailFetcher("AkshareFetcher", priority=1)
        yfinance = _AlwaysFailFetcher("YfinanceFetcher", priority=4)
        tencent = _SucceedingTencentStub()

        manager = DataFetcherManager(fetchers=[tencent, akshare, yfinance])
        DataFetcherManager._daily_source_health.reset()

        df, source = manager.get_daily_data("hk00700", start_date="2026-07-20", end_date="2026-07-23")

        self.assertEqual(source, "TencentFetcher")
        self.assertFalse(df.empty)
        self.assertTrue(set(STANDARD_COLUMNS).issubset(df.columns))
        self.assertAlmostEqual(float(df.iloc[-1]["close"]), 445.2)

    def test_all_preferred_hk_sources_empty_and_falls_back_to_demoted_tencent(self):
        akshare = _AlwaysEmptyFetcher("AkshareFetcher", priority=1)
        yfinance = _AlwaysEmptyFetcher("YfinanceFetcher", priority=4)
        tencent = _SucceedingTencentStub()

        manager = DataFetcherManager(fetchers=[tencent, akshare, yfinance])
        DataFetcherManager._daily_source_health.reset()

        df, source = manager.get_daily_data("hk00700", start_date="2026-07-20", end_date="2026-07-23")

        self.assertEqual(source, "TencentFetcher")
        self.assertFalse(df.empty)

    def test_all_hk_sources_fail_raises_with_aggregated_errors(self):
        akshare = _AlwaysFailFetcher("AkshareFetcher", priority=1)
        yfinance = _AlwaysFailFetcher("YfinanceFetcher", priority=4)
        tencent = _AlwaysFailFetcher("TencentFetcher", priority=0)

        manager = DataFetcherManager(fetchers=[tencent, akshare, yfinance])
        DataFetcherManager._daily_source_health.reset()

        with self.assertRaises(DataFetchError) as ctx:
            manager.get_daily_data("hk00700", start_date="2026-07-20", end_date="2026-07-23")

        message = str(ctx.exception)
        self.assertIn("AkshareFetcher", message)
        self.assertIn("YfinanceFetcher", message)
        self.assertIn("TencentFetcher", message)

    def test_preferred_source_success_does_not_reach_demoted_tencent(self):
        class _SucceedingAkshareStub(BaseFetcher):
            name = "AkshareFetcher"
            priority = 1
            allow_empty_daily_data = True

            def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
                return pd.DataFrame(
                    {
                        "date": ["2026-07-23"],
                        "open": [440.0],
                        "high": [450.8],
                        "low": [439.0],
                        "close": [445.2],
                        "volume": [22888528.0],
                        "amount": [10182005933.0],
                    }
                )

            def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
                normalized = df.copy()
                normalized["pct_chg"] = 0.0
                return normalized[STANDARD_COLUMNS]

        tencent_should_not_be_called = _AlwaysFailFetcher("TencentFetcher", priority=0)
        akshare = _SucceedingAkshareStub()

        manager = DataFetcherManager(fetchers=[tencent_should_not_be_called, akshare])
        DataFetcherManager._daily_source_health.reset()

        df, source = manager.get_daily_data("hk00700", start_date="2026-07-23", end_date="2026-07-23")

        self.assertEqual(source, "AkshareFetcher")
        self.assertFalse(df.empty)
        self.assertEqual(tencent_should_not_be_called.call_count, 0)


if __name__ == "__main__":
    unittest.main()
