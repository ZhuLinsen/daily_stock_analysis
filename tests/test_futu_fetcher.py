# -*- coding: utf-8 -*-
"""Tests for FutuFetcher timestamp normalization and OpenD connection handling."""

import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from data_provider import futu_fetcher
from data_provider.futu_fetcher import FutuFetcher, _hk_provider_timestamp


class TestFutuProviderTimestamp(unittest.TestCase):
    """Futu snapshot update_time is a naive Beijing-time string."""

    def test_naive_string_gets_beijing_offset(self):
        value = _hk_provider_timestamp("2026-08-24 10:30:00")
        self.assertEqual(value, "2026-08-24T10:30:00+08:00")

    def test_empty_and_none_return_none(self):
        self.assertIsNone(_hk_provider_timestamp(None))
        self.assertIsNone(_hk_provider_timestamp(""))
        self.assertIsNone(_hk_provider_timestamp("   "))

    def test_offset_string_is_preserved(self):
        value = _hk_provider_timestamp("2026-08-24T10:30:00+08:00")
        self.assertEqual(value, "2026-08-24T10:30:00+08:00")

    def test_unparsable_text_returns_original(self):
        value = _hk_provider_timestamp("not-a-date")
        self.assertEqual(value, "not-a-date")


class _FakeContextStatus:
    START = "START"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    READY = "READY"
    CLOSED = "CLOSED"
    WAIT_RECONNECT = "WAIT_RECONNECT"


def _fake_futu(statuses, error=None):
    """Build a fake futu module whose context walks through ``statuses``."""
    created = []

    class FakeQuoteContext:
        def __init__(self, host, port, is_async_connect=False):
            if error is not None:
                raise error
            self.host = host
            self.port = port
            self.is_async_connect = is_async_connect
            self.close = MagicMock()
            self._statuses = list(statuses)
            created.append(self)

        @property
        def status(self):
            if len(self._statuses) > 1:
                return self._statuses.pop(0)
            return self._statuses[0]

        def get_market_snapshot(self, codes):
            return 0, pd.DataFrame([{"name": "Tencent", "last_price": 400.0}])

    module = types.ModuleType("futu")
    module.ContextStatus = _FakeContextStatus
    module.OpenQuoteContext = FakeQuoteContext
    return module, created


class TestFutuBoundedConnect(unittest.TestCase):
    """OpenD down must not hang the run; Futu is skipped for a cooldown."""

    def setUp(self):
        patches = [
            patch.object(futu_fetcher, "_CONNECT_TIMEOUT_SECONDS", 0.2),
            patch.object(futu_fetcher, "_CONNECT_POLL_SECONDS", 0.01),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _make_fetcher(self, module):
        patches = [
            patch.dict(sys.modules, {"futu": module}),
            patch.dict(os.environ, {"FUTU_OPEND_HOST": "127.0.0.1", "FUTU_OPEND_PORT": "11111"}),
            patch("src.config.get_config", side_effect=RuntimeError("no config")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return FutuFetcher()

    def test_unready_opend_returns_none_closes_context_and_logs_once(self):
        # WAIT_RECONNECT: port refused; CONNECTED: port open but InitConnect never answered.
        for status in (_FakeContextStatus.WAIT_RECONNECT, _FakeContextStatus.CONNECTED):
            with self.subTest(status=status):
                module, created = _fake_futu([status])
                fetcher = self._make_fetcher(module)

                with self.assertLogs("data_provider.futu_fetcher", level="WARNING") as logs:
                    started = time.monotonic()
                    self.assertIsNone(fetcher._get_ctx())
                    self.assertLess(time.monotonic() - started, 2)
                    self.assertIsNone(fetcher.get_realtime_quote("hk00700"))
                    self.assertIsNone(fetcher.get_stock_name("00700"))

                self.assertEqual(len(created), 1)
                self.assertTrue(created[0].is_async_connect)
                created[0].close.assert_called_once_with()
                self.assertEqual(len(logs.records), 1)
                self.assertFalse(fetcher.is_available_for_request("realtime"))

    def test_constructor_error_enters_cooldown(self):
        module, created = _fake_futu([], error=OSError("boom"))
        fetcher = self._make_fetcher(module)

        with self.assertLogs("data_provider.futu_fetcher", level="WARNING"):
            self.assertIsNone(fetcher._get_ctx())

        self.assertEqual(created, [])
        self.assertFalse(fetcher.is_available_for_request())

    def test_recovers_after_cooldown(self):
        module, created = _fake_futu([_FakeContextStatus.WAIT_RECONNECT])
        fetcher = self._make_fetcher(module)
        with self.assertLogs("data_provider.futu_fetcher", level="WARNING"):
            self.assertIsNone(fetcher._get_ctx())

        # Still cooling down: no new connection attempt.
        self.assertIsNone(fetcher._get_ctx())
        self.assertEqual(len(created), 1)

        # OpenD came back and the cooldown elapsed.
        module.OpenQuoteContext = _fake_futu(
            [_FakeContextStatus.CONNECTING, _FakeContextStatus.READY]
        )[0].OpenQuoteContext
        fetcher._retry_after = time.monotonic() - 1
        self.assertTrue(fetcher.is_available_for_request())

        ctx = fetcher._get_ctx()
        self.assertIsNotNone(ctx)
        ctx.close.assert_not_called()
        self.assertIs(fetcher._get_ctx(), ctx)
        quote = fetcher.get_realtime_quote("hk00700")
        self.assertEqual(quote.price, 400.0)

    def test_concurrent_requests_connect_once(self):
        module, created = _fake_futu([_FakeContextStatus.WAIT_RECONNECT])
        fetcher = self._make_fetcher(module)
        results = []

        def worker():
            results.append(fetcher._get_ctx())

        with self.assertLogs("data_provider.futu_fetcher", level="WARNING") as logs:
            threads = [threading.Thread(target=worker) for _ in range(5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

        self.assertEqual(results, [None] * 5)
        self.assertEqual(len(created), 1)
        self.assertEqual(len(logs.records), 1)


class TestFutuMultiMarketSymbolMapping(unittest.TestCase):
    """Futu OpenD covers HK, A-share and US symbols."""

    def test_hk_symbols(self):
        for code in ("09618.HK", "09618", "HK09618", "700"):
            self.assertEqual(futu_fetcher._futu_market(code), "hk")
        self.assertEqual(futu_fetcher._futu_symbol("700"), "HK.00700")
        self.assertEqual(futu_fetcher._futu_symbol("09618.HK"), "HK.09618")

    def test_cn_symbols(self):
        self.assertEqual(futu_fetcher._futu_market("600519"), "cn")
        self.assertEqual(futu_fetcher._futu_symbol("600519"), "SH.600519")
        self.assertEqual(futu_fetcher._futu_symbol("300750"), "SZ.300750")
        self.assertEqual(futu_fetcher._futu_symbol("600519.SH"), "SH.600519")
        self.assertEqual(futu_fetcher._futu_symbol("SZ.000001"), "SZ.000001")

    def test_unsupported_cn_prefix_returns_none(self):
        self.assertIsNone(futu_fetcher._futu_symbol("830799"))

    def test_us_symbols(self):
        for code in ("AAPL", "US.AAPL", "aapl.us"):
            self.assertEqual(futu_fetcher._futu_market(code), "us")
        self.assertEqual(futu_fetcher._futu_symbol("AAPL"), "US.AAPL")
        self.assertEqual(futu_fetcher._futu_symbol("US.AAPL"), "US.AAPL")
        self.assertEqual(futu_fetcher._futu_symbol("aalb.us"), "US.AALB")
        self.assertEqual(futu_fetcher._futu_symbol("BRK.B"), "US.BRK.B")

    def test_unknown_code_returns_none(self):
        self.assertIsNone(futu_fetcher._futu_market(""))
        self.assertIsNone(futu_fetcher._futu_symbol("   "))

    def test_cn_alias_symbols_match_daily_path(self):
        for code in ("600519", "SH600519", "sh600519", "600519.SH", "600519.SS", "600519.ss"):
            self.assertEqual(futu_fetcher._futu_market(code), "cn", code)
            self.assertEqual(futu_fetcher._futu_symbol(code), "SH.600519", code)
        for code in ("300750", "SZ300750", "300750.SZ"):
            self.assertEqual(futu_fetcher._futu_market(code), "cn", code)
            self.assertEqual(futu_fetcher._futu_symbol(code), "SZ.300750", code)


class TestFutuDailyAdjustmentType(unittest.TestCase):
    """US/A daily candles must be front-adjusted; HK stays unadjusted."""

    def _fetch(self, stock_code):
        captured = {}

        class _Ctx:
            def request_history_kline(self, symbol, **kwargs):
                captured["symbol"] = symbol
                captured["autype"] = kwargs.get("autype")
                frame = pd.DataFrame({
                    "time_key": ["2026-11-20"],
                    "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0],
                    "volume": [10], "turnover": [10.0],
                })
                return 0, frame, None

        fake_futu = types.SimpleNamespace(
            RET_OK=0,
            AuType=types.SimpleNamespace(NONE="none", QFQ="qfq"),
            KLType=types.SimpleNamespace(K_DAY="k_day"),
        )
        fetcher = FutuFetcher.__new__(FutuFetcher)
        with patch.dict(sys.modules, {"futu": fake_futu}), patch.object(
            FutuFetcher, "_get_ctx", return_value=_Ctx()
        ):
            data = fetcher._fetch_raw_data(stock_code, "2026-09-01", "2026-11-20")
        return captured, data

    def test_us_daily_uses_front_adjustment(self):
        captured, data = self._fetch("AAPL")
        self.assertEqual(captured["symbol"], "US.AAPL")
        self.assertEqual(captured["autype"], "qfq")
        self.assertFalse(data.empty)

    def test_cn_alias_daily_uses_front_adjustment(self):
        captured, _ = self._fetch("SH600519")
        self.assertEqual(captured["symbol"], "SH.600519")
        self.assertEqual(captured["autype"], "qfq")

    def test_hk_daily_keeps_unadjusted(self):
        captured, _ = self._fetch("00700")
        self.assertEqual(captured["symbol"], "HK.00700")
        self.assertEqual(captured["autype"], "none")


class TestFutuMarketAwareTimestamp(unittest.TestCase):
    def test_us_quote_uses_new_york_time(self):
        value = futu_fetcher._provider_timestamp("2026-11-25 09:30:00", "us")
        self.assertEqual(value, "2026-11-25T09:30:00-05:00")

    def test_us_quote_uses_dst_offset_in_summer(self):
        value = futu_fetcher._provider_timestamp("2026-08-24 09:30:00", "us")
        self.assertEqual(value, "2026-08-24T09:30:00-04:00")
