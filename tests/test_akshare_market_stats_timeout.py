# -*- coding: utf-8 -*-
"""Regression tests for AkShare market statistics timeout handling."""

import sys
from types import SimpleNamespace

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider.akshare_fetcher import AkshareFetcher


def _market_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "代码": ["600000", "000001"],
            "名称": ["浦发银行", "平安银行"],
            "最新价": [11.0, 9.0],
            "昨收": [10.0, 10.0],
            "成交额": [100_000_000, 200_000_000],
        }
    )


def test_market_stats_eastmoney_call_uses_timeout_wrapper(monkeypatch) -> None:
    calls = []
    eastmoney_api = object()
    sina_api = object()

    def fake_call(func, *args, timeout=None, call_name="", **kwargs):
        calls.append((func, timeout, call_name))
        return _market_frame()

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_a_spot_em=eastmoney_api,
            stock_zh_a_spot=sina_api,
        ),
    )
    monkeypatch.setattr(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        fake_call,
    )

    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    fetcher._market_stats_call_timeout = 7

    stats = fetcher.get_market_stats()

    assert calls == [(eastmoney_api, 7, "ak.stock_zh_a_spot_em")]
    assert stats == {
        "up_count": 1,
        "down_count": 1,
        "flat_count": 0,
        "limit_up_count": 1,
        "limit_down_count": 1,
        "total_amount": 3.0,
    }


def test_market_stats_falls_back_to_sina_after_eastmoney_timeout(
    monkeypatch,
) -> None:
    calls = []
    eastmoney_api = object()
    sina_api = object()

    def fake_call(func, *args, timeout=None, call_name="", **kwargs):
        calls.append((func, timeout, call_name))
        if func is eastmoney_api:
            raise TimeoutError("eastmoney timeout")
        return _market_frame()

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_a_spot_em=eastmoney_api,
            stock_zh_a_spot=sina_api,
        ),
    )
    monkeypatch.setattr(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        fake_call,
    )

    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    fetcher._market_stats_call_timeout = 9

    stats = fetcher.get_market_stats()

    assert calls == [
        (eastmoney_api, 9, "ak.stock_zh_a_spot_em"),
        (sina_api, 9, "ak.stock_zh_a_spot"),
    ]
    assert stats is not None
    assert stats["total_amount"] == 3.0


def test_market_stats_returns_none_after_both_calls_timeout(monkeypatch) -> None:
    calls = []
    eastmoney_api = object()
    sina_api = object()

    def fake_call(func, *args, timeout=None, call_name="", **kwargs):
        calls.append((func, timeout, call_name))
        raise TimeoutError(f"{call_name} timeout")

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_zh_a_spot_em=eastmoney_api,
            stock_zh_a_spot=sina_api,
        ),
    )
    monkeypatch.setattr(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        fake_call,
    )

    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    fetcher._market_stats_call_timeout = 5

    assert fetcher.get_market_stats() is None
    assert calls == [
        (eastmoney_api, 5, "ak.stock_zh_a_spot_em"),
        (sina_api, 5, "ak.stock_zh_a_spot"),
    ]
