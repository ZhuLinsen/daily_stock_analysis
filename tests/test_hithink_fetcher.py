# -*- coding: utf-8 -*-
"""HiThink Finance provider tests. All HTTP calls are mocked."""

from __future__ import annotations

import os
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from data_provider.base import DataFetcherManager, DataFetchError
from data_provider.hithink_fetcher import HiThinkFetcher, HiThinkRequestError
from data_provider.realtime_types import RealtimeSource
from src.config import Config


def _ms(year: int, month: int, day: int) -> int:
    moment = datetime(year, month, day, tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(moment.timestamp() * 1000)


def _response(payload, status_code: int = 200):
    class _Response:
        def __init__(self) -> None:
            self.status_code = status_code

        def json(self):
            if isinstance(payload, Exception):
                raise payload
            return payload

    return _Response()


def _history(*bars: dict) -> dict:
    return {"code": 0, "message": "success", "data": {"timestamp": bars[-1]["date_ms"], "item": list(bars)}}


def _bar(year: int, month: int, day: int, close: float) -> dict:
    return {
        "date_ms": _ms(year, month, day),
        "open_price": close - 0.2,
        "high_price": close + 0.3,
        "low_price": close - 0.4,
        "close_price": close,
        "volume": 3142572,
        "turnover": 5401389334.87,
    }


class HiThinkFetcherTests(unittest.TestCase):
    def _fetcher(self, api_key: str = "hithink-test-key") -> HiThinkFetcher:
        return HiThinkFetcher(api_key=api_key, retry_backoff=0)

    def test_initialization_uses_optional_defaults(self) -> None:
        fetcher = self._fetcher()

        self.assertEqual(fetcher.name, "HiThinkFetcher")
        self.assertEqual(fetcher.priority, 7)
        self.assertEqual(fetcher.kline_adjust, "none")
        self.assertEqual(fetcher.batch_size, 10)
        self.assertTrue(fetcher.is_available())
        self.assertEqual(fetcher.runtime_status, "unknown")

    def test_missing_api_key_disables_fetcher_without_requests(self) -> None:
        fetcher = HiThinkFetcher(api_key="")

        self.assertFalse(fetcher.is_available())
        with patch("data_provider.hithink_fetcher.requests.get") as request:
            with self.assertRaises(DataFetchError):
                fetcher.get_realtime_quote("600519")
        request.assert_not_called()

    def test_successful_snapshot_authenticates_and_normalizes_quote(self) -> None:
        fetcher = self._fetcher()
        payload = {
            "code": 0,
            "message": "success",
            "request_id": "req-1",
            "data": {
                "timestamp": _ms(2024, 5, 20),
                "total": 1,
                "item": [
                    {
                        "thscode": "600519.SH",
                        "ticker": "600519",
                        "volume": 3098875,
                        "turnover": 3937375200,
                        "last_price": 1277.8,
                        "price_change": 21.8,
                        "price_change_ratio_pct": 1.735669,
                        "open_price": 1252.08,
                        "high_price": 1282,
                        "low_price": 1250.21,
                        "prev_price": 1256,
                    }
                ],
            },
        }
        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(payload)) as request:
            quote = fetcher.get_realtime_quote("600519")

        self.assertEqual(quote.source, RealtimeSource.HITHINK)
        self.assertEqual(quote.code, "600519")
        self.assertEqual(quote.price, 1277.8)
        self.assertEqual(quote.change_pct, 1.735669)
        self.assertEqual(quote.volume, 3098875)
        self.assertEqual(quote.amount, 3937375200)
        self.assertEqual(quote.currency, "CNY")
        self.assertEqual(fetcher.runtime_status, "ok")
        headers = request.call_args.kwargs["headers"]
        self.assertEqual(headers["X-api-key"], "hithink-test-key")
        self.assertNotIn("hithink-test-key", request.call_args.args[0])
        self.assertNotIn("hithink-test-key", str(quote))

    def test_empty_snapshot_is_an_error(self) -> None:
        fetcher = self._fetcher()
        payload = {"code": 0, "message": "success", "data": {"timestamp": None, "total": 0, "item": []}}

        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(payload)):
            with self.assertRaises(DataFetchError):
                fetcher.get_realtime_quote("600519")

    def test_historical_bars_use_share_and_yuan_units(self) -> None:
        fetcher = self._fetcher()
        payload = {
            "code": 0,
            "message": "success",
            "data": {"timestamp": _ms(2024, 5, 21), "item": [_bar(2024, 5, 20, 10), _bar(2024, 5, 21, 11)]},
        }

        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(payload)) as request:
            frame = fetcher.get_daily_data("600519", start_date="2024-05-20", end_date="2024-05-21")

        self.assertEqual(list(frame["date"].dt.strftime("%Y-%m-%d")), ["2024-05-20", "2024-05-21"])
        self.assertEqual(frame.iloc[1]["close"], 11)
        self.assertEqual(frame.iloc[1]["volume"], 3142572)
        self.assertEqual(frame.iloc[1]["amount"], 5401389334.87)
        self.assertAlmostEqual(frame.iloc[1]["pct_chg"], 10.0)
        self.assertEqual(frame.attrs["price_adjustment"], "none")
        self.assertEqual(request.call_args.kwargs["params"]["adjust"], "none")
        self.assertEqual(request.call_args.kwargs["params"]["thscode"], "600519.SH")
        self.assertEqual(request.call_args.kwargs["params"]["interval"], "1d")

    def test_batch_historical_caches_each_symbol(self) -> None:
        fetcher = self._fetcher()
        payload = {
            "code": 0,
            "message": "success",
            "data": {
                "interval": "1d",
                "adjust": "none",
                "item": [
                    {"thscode": "600519.SH", "timestamp": _ms(2024, 5, 21), "item": [_bar(2024, 5, 20, 10), _bar(2024, 5, 21, 11)]},
                    {"thscode": "000001.SZ", "timestamp": None, "item": []},
                ],
            },
        }

        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(payload)) as request:
            cached = fetcher.prefetch_daily_klines(["600519", "000001"], start_date="2024-05-20", end_date="2024-05-21")
            self.assertEqual(cached, 1)
            frame = fetcher.get_daily_data("600519", start_date="2024-05-20", end_date="2024-05-21")

        self.assertEqual(request.call_count, 1)
        self.assertIn("historical-batch", request.call_args.args[0])
        self.assertEqual(len(frame), 2)

    def test_disjoint_daily_cache_does_not_cover_the_gap(self) -> None:
        fetcher = self._fetcher()
        january = _history(_bar(2024, 1, 2, 10), _bar(2024, 1, 10, 11))
        february = _history(_bar(2024, 2, 1, 12), _bar(2024, 2, 8, 13))
        span = _history(_bar(2024, 1, 2, 10), _bar(2024, 2, 8, 13))

        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(january), _response(february), _response(span)],
        ) as request:
            fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-01-10")
            fetcher.get_daily_data("600519", start_date="2024-02-01", end_date="2024-02-10")
            fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-02-10")

        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args_list[2].kwargs["params"]["thscode"], "600519.SH")

    def test_adjacent_daily_cache_ranges_cover_the_joined_request(self) -> None:
        fetcher = self._fetcher()
        first = _history(_bar(2024, 1, 2, 10))
        second = _history(_bar(2024, 1, 11, 12))

        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(first), _response(second)],
        ) as request:
            fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-01-10")
            fetcher.get_daily_data("600519", start_date="2024-01-11", end_date="2024-01-20")
            frame = fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-01-20")

        self.assertEqual(request.call_count, 2)
        self.assertEqual(list(frame["date"].dt.strftime("%Y-%m-%d")), ["2024-01-02", "2024-01-11"])

    def test_empty_daily_response_does_not_extend_coverage(self) -> None:
        fetcher = self._fetcher()
        january = _history(_bar(2024, 1, 2, 10))
        empty = {"code": 0, "message": "success", "data": {"timestamp": None, "item": []}}

        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(january), _response(empty), _response(empty)],
        ) as request:
            cached = fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-01-10")
            with self.assertRaises(DataFetchError):
                fetcher.get_daily_data("600519", start_date="2024-02-01", end_date="2024-02-10")
            again = fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-01-10")
            with self.assertRaises(DataFetchError):
                fetcher.get_daily_data("600519", start_date="2024-02-01", end_date="2024-02-10")

        self.assertEqual(len(cached), 1)
        self.assertEqual(len(again), 1)
        self.assertEqual(request.call_count, 3)

    def test_batch_adjustment_or_interval_mismatch_is_not_cached(self) -> None:
        mismatched = {
            "code": 0,
            "message": "success",
            "data": {
                "interval": "1d",
                "adjust": "forward",
                "item": [
                    {"thscode": "600519.SH", "timestamp": _ms(2024, 5, 21), "item": [_bar(2024, 5, 20, 10)]},
                ],
            },
        }
        single = _history(_bar(2024, 5, 20, 10), _bar(2024, 5, 21, 11))
        fetcher = self._fetcher()

        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(mismatched), _response(single)],
        ) as request:
            cached = fetcher.prefetch_daily_klines(["600519"], start_date="2024-05-20", end_date="2024-05-21")
            frame = fetcher.get_daily_data("600519", start_date="2024-05-20", end_date="2024-05-21")

        self.assertEqual(cached, 0)
        self.assertEqual(request.call_count, 2)
        self.assertIn("historical-batch", request.call_args_list[0].args[0])
        self.assertIn("/historical", request.call_args_list[1].args[0])
        self.assertNotIn("historical-batch", request.call_args_list[1].args[0])
        self.assertEqual(len(frame), 2)

        weekly = {
            "code": 0,
            "message": "success",
            "data": {
                "interval": "1w",
                "adjust": "none",
                "item": [
                    {"thscode": "600519.SH", "timestamp": _ms(2024, 5, 21), "item": [_bar(2024, 5, 20, 10)]},
                ],
            },
        }
        weekly_fetcher = self._fetcher()
        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(weekly)) as request:
            cached = weekly_fetcher.prefetch_daily_klines(["600519"], start_date="2024-05-20", end_date="2024-05-21")

        self.assertEqual(cached, 0)
        self.assertEqual(weekly_fetcher._daily_coverage, {})
        self.assertEqual(request.call_count, 1)

    def test_batch_permission_failure_falls_open_to_single_requests(self) -> None:
        fetcher = self._fetcher()
        denied = {"code": 2004, "message": "forbidden", "request_id": "req-denied", "data": None}
        single = {
            "code": 0,
            "message": "success",
            "data": {"timestamp": _ms(2024, 5, 21), "item": [_bar(2024, 5, 20, 10), _bar(2024, 5, 21, 11)]},
        }
        responses = [_response(denied), _response(single)]

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=responses):
            cached = fetcher.prefetch_daily_klines(["600519"], start_date="2024-05-20", end_date="2024-05-21")
            frame = fetcher.get_daily_data("600519", start_date="2024-05-20", end_date="2024-05-21")

        self.assertEqual(cached, 0)
        self.assertEqual(len(frame), 2)
        self.assertTrue(fetcher.is_available("daily_data"))

    def test_timeout_is_bounded_and_reported_without_the_key(self) -> None:
        fetcher = self._fetcher()

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=requests.Timeout("slow")):
            with self.assertLogs("data_provider.hithink_fetcher", level="DEBUG") as logs:
                with self.assertRaises(HiThinkRequestError) as caught:
                    fetcher.get_realtime_quote("600519")

        self.assertIn("timed out", str(caught.exception))
        self.assertNotIn("hithink-test-key", str(caught.exception))
        self.assertNotIn("hithink-test-key", "\n".join(logs.output))

    def test_rate_limit_retries_then_cools_down(self) -> None:
        fetcher = self._fetcher()
        limited = {"code": 4001, "message": "rate limit", "request_id": "req-limit", "data": None}

        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(limited)) as request:
            with self.assertRaises(HiThinkRequestError):
                fetcher.get_realtime_quote("600519")

        self.assertEqual(request.call_count, 3)
        self.assertFalse(fetcher.is_available("realtime_quote"))

    def test_invalid_payload_is_rejected(self) -> None:
        fetcher = self._fetcher()

        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(["not-an-object"])):
            with self.assertRaises(HiThinkRequestError):
                fetcher.get_realtime_quote("600519")

    def test_non_a_share_targets_are_not_sent(self) -> None:
        fetcher = self._fetcher()

        with patch("data_provider.hithink_fetcher.requests.get") as request:
            for code in ("AAPL", "hk00700", "sh000016", "510300"):
                with self.assertRaises(DataFetchError):
                    fetcher.get_realtime_quote(code)
        request.assert_not_called()


class _FallbackFetcher:
    name = "FallbackFetcher"
    priority = 8

    def __init__(self) -> None:
        self.calls = []

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        self.calls.append(stock_code)
        return pd.DataFrame(
            [
                {
                    "date": "2024-05-21",
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 1,
                    "volume": 1,
                    "amount": 1,
                    "pct_chg": 0,
                }
            ]
        )


class HiThinkManagerTests(unittest.TestCase):
    def tearDown(self) -> None:
        Config.reset_instance()

    def test_manager_registers_hithink_only_when_key_is_configured(self) -> None:
        with patch.dict(os.environ, {"HITHINK_FINANCE_API_KEY": ""}, clear=False):
            Config.reset_instance()
            without_key = DataFetcherManager()
        self.assertNotIn("HiThinkFetcher", without_key.available_fetchers)

        with patch.dict(os.environ, {"HITHINK_FINANCE_API_KEY": "manager-key", "HITHINK_PRIORITY": "7"}, clear=False):
            Config.reset_instance()
            with_key = DataFetcherManager()
        self.assertIn("HiThinkFetcher", with_key.available_fetchers)
        fetcher = with_key._get_fetcher_by_name("HiThinkFetcher")
        self.assertIsNotNone(fetcher)
        self.assertEqual(fetcher.priority, 7)

    def test_failed_hithink_daily_falls_back_to_next_provider(self) -> None:
        hithink = HiThinkFetcher(api_key="manager-key", priority=0, retry_backoff=0)
        fallback = _FallbackFetcher()
        manager = DataFetcherManager(fetchers=[hithink, fallback])
        denied = {"code": 5001, "message": "upstream", "request_id": "req-up", "data": None}

        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(denied)):
            frame, source = manager.get_daily_data("600519", start_date="2024-05-20", end_date="2024-05-21")

        self.assertEqual(source, "FallbackFetcher")
        self.assertEqual(len(frame), 1)
        self.assertEqual(fallback.calls, ["600519"])

    def test_configured_key_does_not_change_default_realtime_priority(self) -> None:
        env = {
            "HITHINK_FINANCE_API_KEY": "manager-key",
            "TICKPLUS_API_KEY": "",
            "TUSHARE_TOKEN": "",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("REALTIME_SOURCE_PRIORITY", None)
            self.assertEqual(
                Config._resolve_realtime_source_priority(),
                "tencent,akshare_sina,efinance,akshare_em",
            )

    def test_realtime_priority_can_select_hithink_explicitly(self) -> None:
        hithink = HiThinkFetcher(api_key="manager-key", priority=7, retry_backoff=0)
        manager = DataFetcherManager(fetchers=[hithink])
        payload = {
            "code": 0,
            "message": "success",
            "data": {
                "timestamp": _ms(2024, 5, 20),
                "item": [
                    {
                        "thscode": "600519.SH",
                        "last_price": 10,
                        "price_change": 1,
                        "price_change_ratio_pct": 1,
                        "volume": 100,
                        "turnover": 1000,
                        "open_price": 9,
                        "high_price": 11,
                        "low_price": 8,
                        "prev_price": 9,
                    }
                ],
            },
        }
        config = type("Config", (), {})()
        config.enable_realtime_quote = True
        config.realtime_source_priority = "hithink,tencent"
        config.realtime_cache_ttl = 600

        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(payload)):
            with patch("src.config.get_config", return_value=config):
                quote = manager.get_realtime_quote("600519")

        self.assertEqual(quote.source, RealtimeSource.HITHINK)
        self.assertEqual(quote.price, 10)


if __name__ == "__main__":
    unittest.main()
