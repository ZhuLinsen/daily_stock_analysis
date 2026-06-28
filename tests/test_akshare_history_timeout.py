# -*- coding: utf-8 -*-
"""Regression tests for Akshare historical fallback timeout handling."""

import multiprocessing
import sys
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from data_provider.akshare_fetcher import AkshareFetcher, _akshare_call_with_timeout


def _sleep_for(seconds: float) -> None:
    time.sleep(seconds)


def _return_value(value):
    return value


def test_akshare_call_with_timeout_uses_spawn_context(monkeypatch) -> None:
    requested_methods = []
    call_order = []

    class FakeConnection:
        def __init__(self, messages):
            self.messages = messages

        def send(self, value):
            self.messages.append(value)

        def poll(self, timeout):
            return bool(self.messages)

        def recv(self):
            if not self.messages:
                raise EOFError
            return self.messages.pop(0)

        def close(self):
            pass

    class FakeProcess:
        def __init__(self, target, args, name, daemon):
            self.target = target
            self.args = args
            self.name = name
            self.daemon = daemon

        def start(self):
            self.target(*self.args)

        def join(self, timeout=None):
            pass

        def is_alive(self):
            return False

        def terminate(self):
            pass

        def kill(self):
            pass

    class FakeContext:
        def Pipe(self, duplex=False):
            messages = []
            return FakeConnection(messages), FakeConnection(messages)

        Process = FakeProcess

    def fake_get_context(method=None):
        call_order.append("get_context")
        requested_methods.append(method)
        return FakeContext()

    def fake_freeze_support():
        call_order.append("freeze_support")

    monkeypatch.setattr(
        "data_provider.akshare_fetcher.multiprocessing.get_context",
        fake_get_context,
    )
    monkeypatch.setattr(
        "data_provider.akshare_fetcher.multiprocessing.freeze_support",
        fake_freeze_support,
    )

    result = _akshare_call_with_timeout(
        _return_value,
        "ok",
        timeout=1,
        call_name="unit-default-context",
    )

    assert result == "ok"
    assert requested_methods == ["spawn"]
    assert call_order == ["freeze_support", "get_context"]


def test_akshare_call_with_timeout_returns_promptly() -> None:
    started = time.monotonic()

    with pytest.raises(TimeoutError, match="unit-hang"):
        _akshare_call_with_timeout(
            _sleep_for,
            0.2,
            timeout=0.01,
            call_name="unit-hang",
        )

    assert time.monotonic() - started < 0.5


def test_akshare_call_with_timeout_reaps_timed_out_worker_process() -> None:
    call_name = "unit-hang-reap"

    with pytest.raises(TimeoutError, match=call_name):
        _akshare_call_with_timeout(
            _sleep_for,
            5,
            timeout=0.01,
            call_name=call_name,
        )

    leaked = [
        process
        for process in multiprocessing.active_children()
        if process.name == f"akshare-{call_name}"
    ]
    assert leaked == []


@pytest.mark.parametrize(
    ("method_name", "api_name", "call_name"),
    [
        ("_fetch_stock_data_sina", "stock_zh_a_daily", "ak.stock_zh_a_daily"),
        ("_fetch_stock_data_tx", "stock_zh_a_hist_tx", "ak.stock_zh_a_hist_tx"),
    ],
)
def test_sina_and_tencent_history_calls_use_timeout_wrapper(
    monkeypatch,
    method_name: str,
    api_name: str,
    call_name: str,
) -> None:
    captured = {}

    def fake_call(func, *args, timeout=None, call_name="", **kwargs):
        captured["func"] = func
        captured["timeout"] = timeout
        captured["call_name"] = call_name
        captured["kwargs"] = kwargs
        return pd.DataFrame(
            {
                "date": ["2026-05-25"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.2],
                "volume": [1000],
                "amount": [20000],
            }
        )

    fake_api_func = object()
    fake_akshare = SimpleNamespace(**{api_name: fake_api_func})
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    monkeypatch.setattr("data_provider.akshare_fetcher._akshare_call_with_timeout", fake_call)

    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    fetcher._history_call_timeout = 7

    method = getattr(fetcher, method_name)
    df = method("605218", "2026-05-01", "2026-05-25")

    assert captured["func"] is fake_api_func
    assert captured["timeout"] == 7
    assert captured["call_name"] == call_name
    assert captured["kwargs"]["symbol"] == "sh605218"
    assert captured["kwargs"]["start_date"] == "20260501"
    assert captured["kwargs"]["end_date"] == "20260525"
    assert captured["kwargs"]["adjust"] == "qfq"
    assert list(df.columns)[:7] == ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"]


def test_stock_data_falls_back_after_sina_timeout(monkeypatch) -> None:
    fetcher = AkshareFetcher(sleep_min=0, sleep_max=0)
    tx_df = pd.DataFrame({"日期": ["2026-05-25"], "收盘": [10.2]})

    monkeypatch.setattr(fetcher, "_fetch_stock_data_em", lambda *args: pd.DataFrame())
    monkeypatch.setattr(
        fetcher,
        "_fetch_stock_data_sina",
        lambda *args: (_ for _ in ()).throw(TimeoutError("sina timeout")),
    )
    monkeypatch.setattr(fetcher, "_fetch_stock_data_tx", lambda *args: tx_df)

    result = fetcher._fetch_stock_data("605218", "2026-05-01", "2026-05-25")

    assert result is tx_df
