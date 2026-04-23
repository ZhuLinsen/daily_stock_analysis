# -*- coding: utf-8 -*-
"""
Regression tests for HK stock name fallback when stock_hk_spot_em fails.

Covers: data_provider/akshare_fetcher.py _get_hk_realtime_quote
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()
try:
    import json_repair  # noqa: F401
except ImportError:
    if "json_repair" not in sys.modules:
        sys.modules["json_repair"] = MagicMock()

from data_provider.akshare_fetcher import AkshareFetcher


class _DummyCircuitBreaker:
    def __init__(self):
        self.failures = []
        self.successes = []

    def is_available(self, source: str) -> bool:
        return True

    def record_success(self, source: str) -> None:
        self.successes.append(source)

    def record_failure(self, source: str, error=None) -> None:
        self.failures.append((source, error))


def _make_spot_em_df():
    """Simulate stock_hk_spot_em() return value."""
    return pd.DataFrame([{
        '代码': '00700',
        '名称': '腾讯控股',
        '最新价': 370.0,
        '涨跌幅': 1.5,
        '涨跌额': 5.5,
        '成交量': 10000,
        '成交额': 3700000.0,
        '量比': 1.2,
        '换手率': 0.3,
        '振幅': 2.0,
        '市盈率': 20.0,
        '市净率': 3.5,
        '总市值': 3.5e12,
        '流通市值': 3.5e12,
        '52周最高': 400.0,
        '52周最低': 280.0,
    }])


def _make_spot_df():
    """Simulate stock_hk_spot() return value (sina source)."""
    return pd.DataFrame([{
        '代码': '00700',
        '名称': '腾讯控股',
        '最新价': 368.0,
        '涨跌额': 3.5,
        '涨跌幅': 0.96,
        '买入': 367.8,
        '卖出': 368.2,
        '昨收': 364.5,
        '今开': 365.0,
        '最高': 370.0,
        '最低': 364.0,
        '成交量': 9800,
        '成交额': 3606400.0,
    }])


class TestHKRealtimeFallback(unittest.TestCase):
    """stock_hk_spot_em 失败时应 fallback 到 stock_hk_spot。"""

    def setUp(self):
        self.fetcher = AkshareFetcher()
        # Bypass rate limiting
        self.fetcher._enforce_rate_limit = lambda: None
        self.fetcher._set_random_user_agent = lambda: None

    @patch("data_provider.akshare_fetcher.get_realtime_circuit_breaker")
    def test_em_success_returns_quote_with_name(self, mock_cb):
        """stock_hk_spot_em 成功时直接返回含名称的 quote。"""
        mock_cb.return_value = _DummyCircuitBreaker()
        ak_mock = MagicMock()
        ak_mock.stock_hk_spot_em.return_value = _make_spot_em_df()

        with patch.dict(sys.modules, {"akshare": ak_mock}):
            quote = self.fetcher._get_hk_realtime_quote("HK00700")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.name, "腾讯控股")
        self.assertAlmostEqual(quote.price, 370.0)

    @patch("data_provider.akshare_fetcher.get_realtime_circuit_breaker")
    def test_em_failure_falls_back_to_spot(self, mock_cb):
        """stock_hk_spot_em 抛异常时应 fallback 到 stock_hk_spot 并返回名称。"""
        mock_cb.return_value = _DummyCircuitBreaker()
        ak_mock = MagicMock()
        ak_mock.stock_hk_spot_em.side_effect = Exception("接口异常：数据源不可用")
        ak_mock.stock_hk_spot.return_value = _make_spot_df()

        with patch.dict(sys.modules, {"akshare": ak_mock}):
            quote = self.fetcher._get_hk_realtime_quote("HK00700")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.name, "腾讯控股")
        self.assertAlmostEqual(quote.price, 368.0)
        ak_mock.stock_hk_spot.assert_called_once()

    @patch("data_provider.akshare_fetcher.get_realtime_circuit_breaker")
    def test_both_fail_returns_none(self, mock_cb):
        """stock_hk_spot_em 和 stock_hk_spot 都失败时返回 None，不抛异常。"""
        mock_cb.return_value = _DummyCircuitBreaker()
        ak_mock = MagicMock()
        ak_mock.stock_hk_spot_em.side_effect = Exception("东方财富接口超时")
        ak_mock.stock_hk_spot.side_effect = Exception("新浪接口超时")

        with patch.dict(sys.modules, {"akshare": ak_mock}):
            quote = self.fetcher._get_hk_realtime_quote("HK00700")

        self.assertIsNone(quote)

    @patch("data_provider.akshare_fetcher.get_realtime_circuit_breaker")
    def test_em_returns_empty_df_falls_back_to_spot(self, mock_cb):
        """stock_hk_spot_em 返回空 DataFrame 时应 fallback 到 stock_hk_spot。"""
        mock_cb.return_value = _DummyCircuitBreaker()
        ak_mock = MagicMock()
        ak_mock.stock_hk_spot_em.return_value = pd.DataFrame(columns=['代码', '名称', '最新价'])
        ak_mock.stock_hk_spot.return_value = _make_spot_df()

        with patch.dict(sys.modules, {"akshare": ak_mock}):
            quote = self.fetcher._get_hk_realtime_quote("HK00700")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.name, "腾讯控股")

    @patch("data_provider.akshare_fetcher.get_realtime_circuit_breaker")
    def test_circuit_breaker_open_returns_none(self, mock_cb):
        """熔断状态下直接返回 None。"""
        cb = _DummyCircuitBreaker()
        cb.is_available = lambda source: False
        mock_cb.return_value = cb
        ak_mock = MagicMock()

        with patch.dict(sys.modules, {"akshare": ak_mock}):
            quote = self.fetcher._get_hk_realtime_quote("HK00700")

        self.assertIsNone(quote)
        ak_mock.stock_hk_spot_em.assert_not_called()


if __name__ == "__main__":
    unittest.main()
