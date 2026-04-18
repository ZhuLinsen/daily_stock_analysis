# -*- coding: utf-8 -*-
"""Unit tests for TushareFetcher.get_stock_list(), _fetch_raw_data(), _normalize_data(), get_chip_distribution().

This test file is intentionally isolated from other test modules.
It loads repo-root `.env` and stubs optional runtime deps so it can run
in minimal CI environments without network calls.

Run (repo root):

- With pytest: ``python3 -m pytest tests/test_tushare_fetcher_get_stock_list.py``
  (install once: ``pip install -r requirements-dev.txt`` or ``pip install pytest``)
- Without pytest: ``python3 tests/test_tushare_fetcher_get_stock_list.py``
"""

import importlib.util
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

try:
    json_repair_available = importlib.util.find_spec("json_repair") is not None
except ValueError:
    json_repair_available = "json_repair" in sys.modules

if not json_repair_available and "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()

if "fake_useragent" not in sys.modules:
    sys.modules["fake_useragent"] = MagicMock()

from data_provider.base import DataFetchError, RateLimitError
from data_provider.tushare_fetcher import TushareFetcher

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
except ImportError:
    pass


class TestTushareFetcherGetStockList(unittest.TestCase):
    @staticmethod
    def _make_fetcher() -> TushareFetcher:
        # Avoid real API initialization; we inject a mocked _api below.
        with patch.object(TushareFetcher, "_init_api", return_value=None):
            fetcher = TushareFetcher()
        fetcher._api = MagicMock()
        fetcher.priority = 2
        return fetcher

    def test_get_stock_list_a_share_only(self) -> None:
        fetcher = self._make_fetcher()

        fetcher._api.stock_basic.return_value = pd.DataFrame(
            {
                "ts_code": ["600519.SH", "000001.SZ"],
                "name": ["贵州茅台", "平安银行"],
                "industry": ["白酒", "银行"],
                "area": ["贵州", "深圳"],
                "market": ["主板", "主板"],
            }
        )

        with patch.object(fetcher, "_check_rate_limit"):
            df = fetcher.get_stock_list()

        self.assertIsNotNone(df)
        assert df is not None
        self.assertEqual(
            set(df.columns.tolist()),
            {"code", "name", "industry", "area", "market"},
        )
        self.assertEqual(len(df), 2)
        self.assertEqual(set(df["code"].tolist()), {"600519", "000001"})
        self.assertEqual(fetcher._stock_name_cache.get("600519"), "贵州茅台")

        fetcher._api.stock_basic.assert_called_once()
        self.assertFalse(fetcher._api.hk_basic.called)

    def test_get_stock_list_returns_none_when_empty(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.stock_basic.return_value = pd.DataFrame()

        with patch.object(fetcher, "_check_rate_limit"):
            df = fetcher.get_stock_list()

        self.assertIsNone(df)


class TestTushareFetcherFetchRawData(unittest.TestCase):
    """TushareFetcher._fetch_raw_data: API routing and error handling."""

    @staticmethod
    def _make_fetcher() -> TushareFetcher:
        with patch.object(TushareFetcher, "_init_api", return_value=None):
            fetcher = TushareFetcher()
        fetcher._api = MagicMock()
        fetcher.priority = 2
        return fetcher

    def test_fetch_raw_data_a_share_uses_daily(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.daily.return_value = pd.DataFrame({"trade_date": ["20260101"]})

        with patch.object(fetcher, "_check_rate_limit"):
            out = fetcher._fetch_raw_data("600519", "2026-01-01", "2026-01-05")

        self.assertIsNotNone(out)
        fetcher._api.daily.assert_called_once_with(
            ts_code="600519.SH",
            start_date="20260101",
            end_date="20260105",
        )
        fetcher._api.fund_daily.assert_not_called()
        fetcher._api.hk_daily.assert_not_called()

    def test_fetch_raw_data_etf_uses_fund_daily(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.fund_daily.return_value = pd.DataFrame({"trade_date": ["20260101"]})

        with patch.object(fetcher, "_check_rate_limit"):
            out = fetcher._fetch_raw_data("510050", "20260101", "20260105")

        self.assertIsNotNone(out)
        fetcher._api.fund_daily.assert_called_once_with(
            ts_code="510050.SH",
            start_date="20260101",
            end_date="20260105",
        )
        fetcher._api.daily.assert_not_called()
        fetcher._api.hk_daily.assert_not_called()

    def test_fetch_raw_data_hk_uses_hk_daily(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.hk_daily.return_value = pd.DataFrame({"trade_date": ["20260102"]})

        with patch.object(fetcher, "_check_rate_limit"):
            out = fetcher._fetch_raw_data("HK00700", "2026-01-01", "2026-01-05")

        self.assertIsNotNone(out)
        fetcher._api.hk_daily.assert_called_once_with(
            ts_code="00700.HK",
            start_date="20260101",
            end_date="20260105",
        )
        fetcher._api.daily.assert_not_called()
        fetcher._api.fund_daily.assert_not_called()

    def test_fetch_raw_data_us_raises(self) -> None:
        fetcher = self._make_fetcher()
        with patch.object(fetcher, "_check_rate_limit"):
            with self.assertRaises(DataFetchError) as ctx:
                fetcher._fetch_raw_data("AAPL", "2026-01-01", "2026-01-05")
        self.assertIn("不支持美股", str(ctx.exception))
        fetcher._api.daily.assert_not_called()

    def test_fetch_raw_data_api_unconfigured_raises(self) -> None:
        with patch.object(TushareFetcher, "_init_api", return_value=None):
            fetcher = TushareFetcher()
        # __init__ leaves _api None when _init_api is a no-op mock
        self.assertIsNone(fetcher._api)
        with self.assertRaises(DataFetchError) as ctx:
            fetcher._fetch_raw_data("600519", "2026-01-01", "2026-01-05")
        self.assertIn("未初始化", str(ctx.exception))

    def test_fetch_raw_data_quota_exception_becomes_rate_limit(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.daily.side_effect = Exception("quota exceeded")

        with patch.object(fetcher, "_check_rate_limit"):
            with self.assertRaises(RateLimitError):
                fetcher._fetch_raw_data("600519", "20260101", "20260105")

    def test_convert_stock_code_normalizes(self) -> None:
        fetcher = self._make_fetcher()
        self.assertEqual(fetcher._convert_stock_code("HK00700"), "HK00700")
    

    def test_convert_stock_code_for_tushare_normalizes_hk(self) -> None:
        fetcher = self._make_fetcher()
        self.assertEqual(fetcher._convert_hk_stock_code_for_tushare("HK00700"), "00700.HK")
        self.assertEqual(fetcher._convert_hk_stock_code_for_tushare("00700.HK"), "00700.HK")
        self.assertEqual(fetcher._convert_hk_stock_code_for_tushare("600519"), "600519.SH")


class TestTushareFetcherNormalizeData(unittest.TestCase):
    """TushareFetcher._normalize_data: A-share vol/amount scaling vs HK passthrough."""

    @staticmethod
    def _make_fetcher() -> TushareFetcher:
        with patch.object(TushareFetcher, "_init_api", return_value=None):
            fetcher = TushareFetcher()
        fetcher._api = MagicMock()
        fetcher.priority = 2
        return fetcher

    @staticmethod
    def _sample_daily_frame() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": ["20260102"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.5],
                "close": [10.5],
                "vol": [100.0],
                "amount": [50.0],
                "pct_chg": [1.0],
            }
        )

    def test_normalize_data_a_share_multiplies_volume_and_amount(self) -> None:
        fetcher = self._make_fetcher()
        out = fetcher._normalize_data(self._sample_daily_frame(), "600519")
        self.assertEqual(out.iloc[0]["volume"], 10000.0)
        self.assertEqual(out.iloc[0]["amount"], 50000.0)
        self.assertEqual(out.iloc[0]["code"], "600519")

    def test_normalize_data_hk_skips_volume_amount_scaling(self) -> None:
        fetcher = self._make_fetcher()
        out = fetcher._normalize_data(self._sample_daily_frame(), "HK00700")
        self.assertEqual(out.iloc[0]["volume"], 100.0)
        self.assertEqual(out.iloc[0]["amount"], 50.0)
        self.assertEqual(out.iloc[0]["code"], "HK00700")

    def test_normalize_data_hk_suffix_skips_scaling(self) -> None:
        fetcher = self._make_fetcher()
        out = fetcher._normalize_data(self._sample_daily_frame(), "00700.HK")
        self.assertEqual(out.iloc[0]["volume"], 100.0)
        self.assertEqual(out.iloc[0]["amount"], 50.0)

    def test_normalize_data_etf_scales_like_a_share(self) -> None:
        fetcher = self._make_fetcher()
        out = fetcher._normalize_data(self._sample_daily_frame(), "510050")
        self.assertEqual(out.iloc[0]["volume"], 10000.0)
        self.assertEqual(out.iloc[0]["amount"], 50000.0)


class TestTushareFetcherChipDistribution(unittest.TestCase):
    """get_chip_distribution: HK early exit."""

    @staticmethod
    def _make_fetcher() -> TushareFetcher:
        with patch.object(TushareFetcher, "_init_api", return_value=None):
            fetcher = TushareFetcher()
        fetcher._api = MagicMock()
        fetcher.priority = 2
        return fetcher

    def test_get_chip_distribution_returns_none_for_hk_canonical(self) -> None:
        fetcher = self._make_fetcher()
        with patch.object(fetcher, "_call_api_with_rate_limit") as api_mock:
            self.assertIsNone(fetcher.get_chip_distribution("HK00700"))
        api_mock.assert_not_called()

    def test_get_chip_distribution_returns_none_for_hk_ts_suffix(self) -> None:
        fetcher = self._make_fetcher()
        with patch.object(fetcher, "_call_api_with_rate_limit") as api_mock:
            self.assertIsNone(fetcher.get_chip_distribution("00700.HK"))
        api_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

