# -*- coding: utf-8 -*-
"""Unit tests for TickFlow market-review-only fetcher."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.tickflow_fetcher import (
    TickFlowFetcher,
    _UNIVERSE_PERMISSION_NEGATIVE_CACHE_TTL_SECONDS,
)


class _FakeQuotesResource:
    def __init__(self, symbols_data=None, universe_data=None):
        self._symbols_data = symbols_data or []
        self._universe_data = universe_data or []
        self.calls = []

    def get(self, *, symbols=None, universes=None, as_dataframe=False):
        self.calls.append(
            {"symbols": symbols, "universes": universes, "as_dataframe": as_dataframe}
        )
        if symbols is not None:
            if isinstance(self._symbols_data, dict):
                return self._symbols_data.get(tuple(symbols), [])
            return self._symbols_data
        if universes is not None:
            if isinstance(self._universe_data, Exception):
                raise self._universe_data
            return self._universe_data
        return []


class _FakeClient:
    def __init__(self, symbols_data=None, universe_data=None):
        self.quotes = _FakeQuotesResource(symbols_data, universe_data)
        self.closed = False

    def close(self):
        self.closed = True
        return None


class _PermissionLikeError(Exception):
    def __init__(self, message, *, status_code=403, code="FORBIDDEN"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = None


def _quote(
    symbol,
    *,
    last_price,
    prev_close,
    amount,
    name="",
    change_pct=None,
    change_amount=None,
    amplitude=None,
):
    ext = {}
    if name:
        ext["name"] = name
    if change_pct is not None:
        ext["change_pct"] = change_pct
    if change_amount is not None:
        ext["change_amount"] = change_amount
    if amplitude is not None:
        ext["amplitude"] = amplitude
    return {
        "symbol": symbol,
        "last_price": last_price,
        "prev_close": prev_close,
        "open": last_price,
        "high": last_price,
        "low": last_price,
        "volume": 1000,
        "amount": amount,
        "timestamp": 0,
        "region": "CN",
        "ext": ext,
    }


class TestTickFlowFetcher(unittest.TestCase):
    def test_get_main_indices_maps_cn_quotes(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(
            symbols_data={
                (
                    "000001.SH",
                    "399001.SZ",
                    "399006.SZ",
                    "000688.SH",
                    "000016.SH",
                ): [
                    _quote(
                        "000001.SH",
                        last_price=3200.0,
                        prev_close=3180.0,
                        amount=1.2e11,
                        name="忽略远端名称",
                        change_pct=0.0063,
                        change_amount=20.0,
                        amplitude=0.014,
                    ),
                    _quote(
                        "399001.SZ",
                        last_price=10000.0,
                        prev_close=9900.0,
                        amount=9.5e10,
                        change_pct=0.0101,
                        change_amount=100.0,
                        amplitude=0.0200,
                    ),
                    _quote(
                        "399006.SZ",
                        last_price=2000.0,
                        prev_close=1980.0,
                        amount=5.0e10,
                        change_pct=0.0101,
                        change_amount=20.0,
                        amplitude=0.0150,
                    ),
                    _quote(
                        "000688.SH",
                        last_price=900.0,
                        prev_close=890.0,
                        amount=3.0e10,
                        change_pct=0.0112,
                        change_amount=10.0,
                        amplitude=0.0180,
                    ),
                    _quote(
                        "000016.SH",
                        last_price=2500.0,
                        prev_close=2480.0,
                        amount=4.0e10,
                        change_pct=0.0081,
                        change_amount=20.0,
                        amplitude=0.0130,
                    ),
                ],
                ("000300.SH",): [
                    _quote(
                        "000300.SH",
                        last_price=3800.0,
                        prev_close=3780.0,
                        amount=6.0e10,
                        change_pct=0.0053,
                        change_amount=20.0,
                        amplitude=0.0110,
                    )
                ],
            }
        )

        data = fetcher.get_main_indices(region="cn")

        self.assertEqual(
            fetcher._client.quotes.calls[0]["symbols"],
            [
                "000001.SH",
                "399001.SZ",
                "399006.SZ",
                "000688.SH",
                "000016.SH",
            ],
        )
        self.assertEqual(fetcher._client.quotes.calls[1]["symbols"], ["000300.SH"])
        self.assertEqual(data[0]["code"], "000001")
        self.assertEqual(data[0]["name"], "上证指数")
        self.assertAlmostEqual(data[0]["change_pct"], 0.63)
        self.assertAlmostEqual(data[0]["amplitude"], 1.4)
        self.assertEqual(data[1]["code"], "399001")

    def test_get_main_indices_returns_none_for_non_cn_region(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(symbols_data=[_quote("000001.SH", last_price=1, prev_close=1, amount=1)])

        self.assertIsNone(fetcher.get_main_indices(region="us"))
        self.assertEqual(fetcher._client.quotes.calls, [])

    def test_get_main_indices_returns_none_when_quotes_incomplete(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(
            symbols_data=[
                _quote("000001.SH", last_price=3200.0, prev_close=3180.0, amount=1.2e11),
                _quote("399001.SZ", last_price=10000.0, prev_close=9900.0, amount=9.5e10),
            ]
        )

        self.assertIsNone(fetcher.get_main_indices(region="cn"))

    def test_get_market_stats_calculates_a_share_rules(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(
            universe_data=[
                _quote("600000.SH", last_price=11.0, prev_close=10.0, amount=1e8, name="浦发银行"),
                _quote("300750.SZ", last_price=12.0, prev_close=10.0, amount=1e8, name="宁德时代"),
                _quote("688001.SH", last_price=8.0, prev_close=10.0, amount=1e8, name="科创测试"),
                _quote("920001.BJ", last_price=13.0, prev_close=10.0, amount=1e8, name="北交测试"),
                _quote("600001.SH", last_price=10.5, prev_close=10.0, amount=1e8, name="*ST示例"),
                _quote("600002.SH", last_price=10.0, prev_close=10.0, amount=1e8, name="平盘示例"),
                _quote("600003.SH", last_price=11.0, prev_close=10.0, amount=0.0, name="零成交额"),
                _quote("600004.SH", last_price=11.0, prev_close=None, amount=1e8, name="缺昨收"),
            ]
        )

        stats = fetcher.get_market_stats()

        self.assertEqual(fetcher._client.quotes.calls[0]["universes"], ["CN_Equity_A"])
        self.assertEqual(stats["up_count"], 4)
        self.assertEqual(stats["down_count"], 1)
        self.assertEqual(stats["flat_count"], 1)
        self.assertEqual(stats["limit_up_count"], 4)
        self.assertEqual(stats["limit_down_count"], 1)
        self.assertAlmostEqual(stats["total_amount"], 7.0)

    def test_get_market_stats_counts_amount_even_when_price_stats_skip_row(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(
            universe_data=[
                _quote("600000.SH", last_price=11.0, prev_close=10.0, amount=1e8, name="浦发银行"),
                _quote("600004.SH", last_price=11.0, prev_close=None, amount=1e8, name="缺昨收"),
            ]
        )

        stats = fetcher.get_market_stats()

        self.assertEqual(stats["up_count"], 1)
        self.assertEqual(stats["down_count"], 0)
        self.assertEqual(stats["flat_count"], 0)
        self.assertAlmostEqual(stats["total_amount"], 2.0)

    def test_get_market_stats_returns_none_for_empty_quotes(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(universe_data=[])

        self.assertIsNone(fetcher.get_market_stats())

    def test_get_market_stats_returns_none_when_universe_query_not_supported(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(
            universe_data=RuntimeError("当前套餐不支持标的池查询，请升级或使用 symbols 参数")
        )

        self.assertIsNone(fetcher.get_market_stats())
        self.assertFalse(fetcher._universe_query_supported)
        self.assertIsNone(fetcher.get_market_stats())
        self.assertEqual(len(fetcher._client.quotes.calls), 1)

    def test_get_market_stats_retries_permission_probe_after_negative_cache_ttl(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(
            universe_data=_PermissionLikeError("forbidden", status_code=403)
        )

        with patch(
            "data_provider.tickflow_fetcher.monotonic",
            side_effect=[
                100.0,
                100.0 + _UNIVERSE_PERMISSION_NEGATIVE_CACHE_TTL_SECONDS + 1,
            ],
        ):
            self.assertIsNone(fetcher.get_market_stats())
            self.assertIsNone(fetcher.get_market_stats())

        self.assertEqual(len(fetcher._client.quotes.calls), 2)

    def test_close_resets_client_and_universe_probe_state(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        client = _FakeClient(
            universe_data=_PermissionLikeError("forbidden", status_code=403)
        )
        fetcher._client = client

        self.assertIsNone(fetcher.get_market_stats())
        self.assertFalse(fetcher._universe_query_supported)

        fetcher.close()

        self.assertTrue(client.closed)
        self.assertIsNone(fetcher._client)
        self.assertIsNone(fetcher._universe_query_supported)
        self.assertIsNone(fetcher._universe_query_checked_at)

    def test_is_universe_permission_error_handles_multiple_error_shapes(self):
        cases = [
            (_PermissionLikeError("blocked", status_code=403, code=""), True),
            (
                _PermissionLikeError(
                    "denied", status_code=400, code="PERMISSION_DENIED"
                ),
                True,
            ),
            (RuntimeError("Universe permission is forbidden"), True),
            (RuntimeError("network timeout"), False),
        ]

        for exc, expected in cases:
            with self.subTest(exc=repr(exc), expected=expected):
                self.assertEqual(
                    TickFlowFetcher._is_universe_permission_error(exc), expected
                )


if __name__ == "__main__":
    unittest.main()
