# -*- coding: utf-8 -*-
"""HiThink Finance provider tests. All HTTP calls are mocked."""

from __future__ import annotations

import os
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from data_provider.base import DataFetcherManager, DataFetchError
from data_provider.hithink_fetcher import HiThinkFetcher, HiThinkRequestError, request_budget
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

    def test_batch_snapshot_does_not_copy_the_response_timestamp_onto_every_quote(self) -> None:
        fetcher = self._fetcher()
        moment = _ms(2024, 5, 20)
        items = []
        for thscode in ("600519.SH", "000001.SZ"):
            items.append({
                "thscode": thscode,
                "last_price": 10,
                "price_change": 0.1,
                "price_change_ratio_pct": 1,
                "open_price": 9,
                "high_price": 11,
                "low_price": 9,
                "prev_price": 9.9,
                "volume": 100,
                "turnover": 1000,
            })
        payload = {"code": 0, "message": "success", "data": {"timestamp": moment, "item": items}}
        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(payload)):
            cached = fetcher.prefetch_realtime_quotes(["600519", "000001"])
            second = fetcher.get_realtime_quote("000001")
            single_payload = {
                "code": 0,
                "message": "success",
                "data": {"timestamp": moment, "item": [items[0]]},
            }
        self.assertEqual(cached, 2)
        self.assertIsNone(second.provider_timestamp)
        self.assertIsNone(getattr(second, "quote_date", None))
        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(single_payload)):
            single = HiThinkFetcher(api_key="hithink-test-key", retry_backoff=0).get_realtime_quote("600519")
        self.assertIsNotNone(single.provider_timestamp)

    def test_http_429_cools_realtime_without_splitting_the_batch(self) -> None:
        fetcher = self._fetcher()
        calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append((params or {}).get("thscodes"))
            return _response({}, status_code=429)

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=fake_get):
            self.assertEqual(fetcher.prefetch_realtime_quotes(["600519", "000001"]), 0)

        self.assertTrue(calls)
        self.assertTrue(all(value and "," in value for value in calls))
        self.assertFalse(fetcher.is_available("realtime_quote"))

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

    def test_repeated_prefetch_keeps_the_newer_close_and_change(self) -> None:
        fetcher = self._fetcher()
        first = {
            "code": 0,
            "message": "success",
            "data": {
                "interval": "1d",
                "adjust": "none",
                "item": [
                    {
                        "thscode": "600519.SH",
                        "timestamp": _ms(2024, 5, 21),
                        "item": [_bar(2024, 5, 20, 10), _bar(2024, 5, 21, 11)],
                    }
                ],
            },
        }
        second = {
            "code": 0,
            "message": "success",
            "data": {
                "interval": "1d",
                "adjust": "none",
                "item": [
                    {
                        "thscode": "600519.SH",
                        "timestamp": _ms(2024, 5, 21),
                        "item": [_bar(2024, 5, 20, 10), _bar(2024, 5, 21, 12)],
                    }
                ],
            },
        }
        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(first), _response(second)],
        ) as request:
            self.assertEqual(
                fetcher.prefetch_daily_klines(["600519"], start_date="2024-05-20", end_date="2024-05-21"),
                1,
            )
            self.assertEqual(
                fetcher.prefetch_daily_klines(["600519"], start_date="2024-05-20", end_date="2024-05-21"),
                1,
            )
            frame = fetcher.get_daily_data("600519", start_date="2024-05-20", end_date="2024-05-21")

        self.assertEqual(request.call_count, 2)
        self.assertEqual(list(frame["close"]), [10, 12])
        self.assertAlmostEqual(frame.iloc[1]["pct_chg"], 20.0)

    def test_historical_permission_does_not_repeat_or_block_snapshot(self) -> None:
        fetcher = self._fetcher()
        denied = {"code": 2004, "message": "forbidden", "request_id": "req-denied", "data": None}
        snapshot = {
            "code": 0,
            "message": "success",
            "data": {
                "timestamp": _ms(2024, 5, 20),
                "item": [{
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
                }],
            },
        }
        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(denied), _response(snapshot)],
        ) as request:
            with self.assertRaises(DataFetchError):
                fetcher.get_daily_data("600519", start_date="2024-05-20", end_date="2024-05-21")
            with self.assertRaises(DataFetchError):
                fetcher.get_daily_data("600519", start_date="2024-05-20", end_date="2024-05-21")
            quote = fetcher.get_realtime_quote("600519")

        self.assertEqual(request.call_count, 2)
        self.assertIn("snapshot", request.call_args.args[0])
        self.assertEqual(quote.price, 10)
        self.assertFalse(fetcher.is_available_for_request("daily_data"))
        self.assertTrue(fetcher.is_available_for_request("realtime_quote"))

    def test_snapshot_permission_does_not_repeat_or_block_history(self) -> None:
        fetcher = self._fetcher()
        denied = {"code": 2004, "message": "forbidden", "request_id": "req-denied", "data": None}
        history = _history(_bar(2024, 5, 20, 10), _bar(2024, 5, 21, 11))
        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(denied), _response(history)],
        ) as request:
            with self.assertRaises(HiThinkRequestError):
                fetcher.get_realtime_quote("600519")
            with self.assertRaises(DataFetchError):
                fetcher.get_realtime_quote("600519")
            frame = fetcher.get_daily_data("600519", start_date="2024-05-20", end_date="2024-05-21")

        self.assertEqual(request.call_count, 2)
        self.assertIn("historical", request.call_args.args[0])
        self.assertEqual(len(frame), 2)
        self.assertFalse(fetcher.is_available_for_request("realtime_quote"))
        self.assertTrue(fetcher.is_available_for_request("daily_data"))

    def test_snapshot_permission_does_not_split_into_single_requests(self) -> None:
        fetcher = self._fetcher()
        denied = {"code": 2004, "message": "forbidden", "request_id": "req-denied", "data": None}
        with patch(
            "data_provider.hithink_fetcher.requests.get",
            return_value=_response(denied),
        ) as request:
            with self.assertRaises(HiThinkRequestError):
                fetcher._load_quotes([("600519.SH", "600519"), ("000001.SZ", "000001")])

        self.assertEqual(request.call_count, 1)
        self.assertIn("600519.SH,000001.SZ", request.call_args.kwargs["params"]["thscodes"])
        self.assertFalse(fetcher.is_available_for_request("realtime_quote"))

    def test_batch_prefetch_caches_every_window_beyond_ten_years(self) -> None:
        fetcher = self._fetcher()
        start_date = "2014-01-01"
        end_date = (datetime(2014, 1, 1) + timedelta(days=3601)).strftime("%Y-%m-%d")
        windows = fetcher._windows(start_date, end_date)
        self.assertEqual(len(windows), 2)

        def _batch_payload(window_start: str) -> dict:
            year, month, day = (int(part) for part in window_start.split("-"))
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "interval": "1d",
                    "adjust": "none",
                    "item": [
                        {
                            "thscode": "600519.SH",
                            "timestamp": _ms(year, month, day),
                            "item": [_bar(year, month, day, 10)],
                        }
                    ],
                },
            }

        def _batch_response(url, **kwargs):
            start_ms = kwargs["params"]["start"]
            moment = datetime.fromtimestamp(start_ms / 1000, tz=ZoneInfo("Asia/Shanghai"))
            day = moment.strftime("%Y-%m-%d")
            if "historical-batch" in url:
                return _response(_batch_payload(day))
            year, month, day_number = (int(part) for part in day.split("-"))
            return _response(_history(_bar(year, month, day_number, 10)))

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=_batch_response) as request:
            cached = fetcher.prefetch_daily_klines(["600519"], start_date=start_date, end_date=end_date)
            self.assertEqual(cached, 1)
            self.assertEqual(request.call_count, 2)
            for window_start, _window_end in windows:
                frame = fetcher.get_daily_data("600519", start_date=window_start, end_date=window_start)
                self.assertEqual(list(frame["date"].dt.strftime("%Y-%m-%d")), [window_start])
            self.assertEqual(request.call_count, 2)
            window_start, window_end = windows[0]
            refetch = fetcher.get_daily_data("600519", start_date=window_start, end_date=window_end)
            self.assertEqual(list(refetch["date"].dt.strftime("%Y-%m-%d")), [window_start])
            self.assertGreater(request.call_count, 2)

        requested_starts = [call.kwargs["params"]["start"] for call in request.call_args_list]
        self.assertEqual(len(set(requested_starts)), 2)

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
        first = _history(_bar(2024, 1, 2, 10), _bar(2024, 1, 3, 11), _bar(2024, 1, 4, 12), _bar(2024, 1, 5, 13))
        second = _history(_bar(2024, 1, 8, 14), _bar(2024, 1, 9, 15), _bar(2024, 1, 10, 16))

        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(first), _response(second)],
        ) as request:
            fetcher.get_daily_data("600519", start_date="2024-01-02", end_date="2024-01-05")
            fetcher.get_daily_data("600519", start_date="2024-01-06", end_date="2024-01-10")
            frame = fetcher.get_daily_data("600519", start_date="2024-01-02", end_date="2024-01-10")

        self.assertEqual(request.call_count, 2)
        self.assertEqual(
            list(frame["date"].dt.strftime("%Y-%m-%d")),
            ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10"],
        )

    def test_empty_daily_response_does_not_extend_coverage(self) -> None:
        fetcher = self._fetcher()
        january = _history(
            _bar(2024, 1, 2, 10),
            _bar(2024, 1, 3, 11),
            _bar(2024, 1, 4, 12),
            _bar(2024, 1, 5, 13),
            _bar(2024, 1, 8, 14),
            _bar(2024, 1, 9, 15),
            _bar(2024, 1, 10, 16),
        )
        empty = {"code": 0, "message": "success", "data": {"timestamp": None, "item": []}}

        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(january), _response(empty), _response(empty)],
        ) as request:
            cached = fetcher.get_daily_data("600519", start_date="2024-01-02", end_date="2024-01-10")
            with self.assertRaises(DataFetchError):
                fetcher.get_daily_data("600519", start_date="2024-02-01", end_date="2024-02-10")
            again = fetcher.get_daily_data("600519", start_date="2024-01-02", end_date="2024-01-10")
            with self.assertRaises(DataFetchError):
                fetcher.get_daily_data("600519", start_date="2024-02-01", end_date="2024-02-10")

        self.assertEqual(len(cached), 7)
        self.assertEqual(len(again), 7)
        self.assertEqual(request.call_count, 3)

    def test_partial_daily_response_does_not_cover_the_requested_window(self) -> None:
        fetcher = self._fetcher()
        one_bar = _history(_bar(2024, 1, 2, 10))
        ends_only = _history(_bar(2024, 1, 2, 10), _bar(2024, 12, 31, 20))

        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(one_bar), _response(one_bar), _response(one_bar), _response(ends_only), _response(ends_only)],
        ) as request:
            first = fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-12-31")
            same_day = fetcher.get_daily_data("600519", start_date="2024-01-02", end_date="2024-01-02")
            again = fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-12-31")
            fetcher.get_daily_data("600519", start_date="2024-06-01", end_date="2024-06-30")
            fetcher.get_daily_data("000001", start_date="2024-01-01", end_date="2024-12-31")
            fetcher.get_daily_data("000001", start_date="2024-06-01", end_date="2024-06-30")

        self.assertEqual(list(first["date"].dt.strftime("%Y-%m-%d")), ["2024-01-02"])
        self.assertEqual(list(same_day["date"].dt.strftime("%Y-%m-%d")), ["2024-01-02"])
        self.assertEqual(list(again["date"].dt.strftime("%Y-%m-%d")), ["2024-01-02"])
        self.assertEqual(request.call_count, 5)
        self.assertEqual(request.call_args_list[2].kwargs["params"]["thscode"], "600519.SH")
        self.assertEqual(request.call_args_list[2].kwargs["params"]["start"], _ms(2024, 6, 1))
        self.assertEqual(request.call_args_list[4].kwargs["params"]["thscode"], "000001.SZ")
        self.assertEqual(request.call_args_list[4].kwargs["params"]["start"], _ms(2024, 6, 1))

    def test_tuesday_to_friday_gap_is_not_treated_as_a_weekend(self) -> None:
        fetcher = self._fetcher()
        missing_two_sessions = _history(_bar(2024, 1, 2, 10), _bar(2024, 1, 5, 11))
        friday_to_monday = _history(_bar(2024, 1, 5, 13), _bar(2024, 1, 8, 14))

        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[
                _response(missing_two_sessions),
                _response(missing_two_sessions),
                _response(friday_to_monday),
            ],
        ) as request:
            first = fetcher.get_daily_data("600519", start_date="2024-01-02", end_date="2024-01-05")
            again = fetcher.get_daily_data("600519", start_date="2024-01-02", end_date="2024-01-05")
            weekend = fetcher.get_daily_data("600519", start_date="2024-01-05", end_date="2024-01-08")
            cached_weekend = fetcher.get_daily_data("600519", start_date="2024-01-05", end_date="2024-01-08")

        self.assertEqual(list(first["date"].dt.strftime("%Y-%m-%d")), ["2024-01-02", "2024-01-05"])
        self.assertEqual(list(again["date"].dt.strftime("%Y-%m-%d")), ["2024-01-02", "2024-01-05"])
        self.assertEqual(list(weekend["date"].dt.strftime("%Y-%m-%d")), ["2024-01-05", "2024-01-08"])
        self.assertEqual(list(cached_weekend["date"].dt.strftime("%Y-%m-%d")), ["2024-01-05", "2024-01-08"])
        self.assertEqual(request.call_count, 3)

    def test_zero_close_does_not_cover_the_prefetched_window(self) -> None:
        fetcher = self._fetcher()
        manager = DataFetcherManager(fetchers=[fetcher])
        batch = {
            "code": 0,
            "message": "success",
            "data": {
                "interval": "1d",
                "adjust": "none",
                "item": [{
                    "thscode": "600519.SH",
                    "timestamp": _ms(2024, 1, 4),
                    "item": [
                        _bar(2024, 1, 2, 10),
                        _bar(2024, 1, 3, 0),
                        _bar(2024, 1, 4, 12),
                    ],
                }],
            },
        }
        complete = _history(_bar(2024, 1, 2, 10), _bar(2024, 1, 3, 11), _bar(2024, 1, 4, 12))

        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(batch), _response(complete)],
        ) as request:
            cached = fetcher.prefetch_daily_klines(
                ["600519"],
                start_date="2024-01-02",
                end_date="2024-01-04",
            )
            frame, source = manager.get_daily_data(
                "600519",
                start_date="2024-01-02",
                end_date="2024-01-04",
            )

        self.assertEqual(cached, 1)
        self.assertEqual(source, "HiThinkFetcher")
        self.assertEqual(list(frame["date"].dt.strftime("%Y-%m-%d")), ["2024-01-02", "2024-01-03", "2024-01-04"])
        self.assertEqual(request.call_count, 2)
        self.assertIn("historical-batch", request.call_args_list[0].args[0])
        self.assertTrue(request.call_args_list[1].args[0].endswith("/historical"))

    def test_later_zero_close_does_not_keep_the_cached_window(self) -> None:
        fetcher = self._fetcher()
        manager = DataFetcherManager(fetchers=[fetcher])

        def batch(close: float) -> dict:
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "interval": "1d",
                    "adjust": "none",
                    "item": [{
                        "thscode": "600519.SH",
                        "timestamp": _ms(2024, 1, 4),
                        "item": [
                            _bar(2024, 1, 2, 10),
                            _bar(2024, 1, 3, close),
                            _bar(2024, 1, 4, 12),
                        ],
                    }],
                },
            }

        complete = _history(_bar(2024, 1, 2, 10), _bar(2024, 1, 3, 11), _bar(2024, 1, 4, 12))
        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(batch(11)), _response(batch(0)), _response(complete)],
        ) as request:
            self.assertEqual(
                fetcher.prefetch_daily_klines(["600519"], start_date="2024-01-02", end_date="2024-01-04"),
                1,
            )
            self.assertEqual(
                fetcher.prefetch_daily_klines(["600519"], start_date="2024-01-02", end_date="2024-01-04"),
                1,
            )
            frame, source = manager.get_daily_data(
                "600519",
                start_date="2024-01-02",
                end_date="2024-01-04",
            )

        self.assertEqual(source, "HiThinkFetcher")
        self.assertEqual(list(frame["date"].dt.strftime("%Y-%m-%d")), ["2024-01-02", "2024-01-03", "2024-01-04"])
        self.assertEqual(list(frame["close"]), [10, 11, 12])
        self.assertAlmostEqual(frame.iloc[2]["pct_chg"], (12 / 11 - 1) * 100)
        self.assertEqual(request.call_count, 3)
        self.assertIn("historical-batch", request.call_args_list[0].args[0])
        self.assertIn("historical-batch", request.call_args_list[1].args[0])
        self.assertTrue(request.call_args_list[2].args[0].endswith("/historical"))

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

    def test_capability_denied_does_not_cool_other_capabilities(self) -> None:
        fetcher = self._fetcher()
        denied = {"code": 2003, "message": "capability denied", "request_id": "req-cap", "data": None}
        quote = {
            "code": 0,
            "message": "success",
            "data": {"timestamp": _ms(2024, 5, 21), "item": [{
                "thscode": "600519.SH",
                "last_price": 10,
                "price_change": 1,
                "price_change_ratio_pct": 1,
                "volume": 100,
                "turnover": 1000,
            }]},
        }
        daily = {
            "code": 0,
            "message": "success",
            "data": {"timestamp": _ms(2024, 5, 21), "item": [_bar(2024, 5, 20, 10)]},
        }
        calls = []

        def fake_get(url, headers=None, params=None, timeout=None):
            calls.append(url)
            if url.endswith("/historical-batch"):
                return _response(denied)
            if url.endswith("/snapshot"):
                return _response(quote)
            return _response(daily)

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=fake_get):
            cached = fetcher.prefetch_daily_klines(["600519"], start_date="2024-05-20", end_date="2024-05-21")
            frame = fetcher.get_daily_data("600519", start_date="2024-05-20", end_date="2024-05-21")
            quote_result = fetcher.get_realtime_quote("600519")

        self.assertEqual(cached, 0)
        self.assertEqual(len(frame), 1)
        self.assertEqual(quote_result.price, 10)
        self.assertTrue(fetcher.is_available())
        self.assertFalse(fetcher.is_available_for_request("daily_batch"))
        self.assertTrue(fetcher.is_available_for_request("daily_data"))
        self.assertTrue(fetcher.is_available_for_request("realtime_quote"))
        self.assertEqual(sum(url.endswith("/historical-batch") for url in calls), 1)

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

    def test_rate_limit_inside_a_short_budget_still_cools_daily(self) -> None:
        from data_provider.hithink_fetcher import _request_budget
        from data_provider.hithink_fundamentals import HiThinkFundamentalAdapter

        payloads = [
            _response({}, status_code=429),
            _response({"code": 4001, "message": "rate limit", "data": None}),
        ]
        for payload in payloads:
            fetcher = HiThinkFetcher(api_key="hithink-test-key", retry_backoff=0.2)
            calls = []

            def fake_get(url, params=None, headers=None, timeout=None, payload=payload):
                calls.append(url)
                return payload

            def fake_sleep(_seconds):
                _request_budget.deadline = time.monotonic() - 1

            with patch("data_provider.hithink_fetcher.requests.get", side_effect=fake_get), \
                    patch("data_provider.hithink_fetcher.time.sleep", side_effect=fake_sleep):
                result = HiThinkFundamentalAdapter(fetcher).get_valuation(
                    "600519",
                    deadline=time.monotonic() + 1,
                )

            self.assertEqual(result, {})
            self.assertEqual(len(calls), 1)
            self.assertFalse(fetcher.is_available("daily_data"))
            with patch("data_provider.hithink_fetcher.requests.get") as daily:
                with self.assertRaises(DataFetchError):
                    fetcher.get_daily_data("600519", start_date="2024-01-02", end_date="2024-01-04")
            self.assertEqual(daily.call_count, 0)

    def test_retry_sleep_stays_inside_the_remaining_budget(self) -> None:
        fetcher = HiThinkFetcher(api_key="hithink-test-key", retry_backoff=5, timeout=15)
        server_error = {"code": 5001, "message": "upstream", "request_id": "req-up", "data": None}
        sleeps = []
        timeouts = []

        def fake_get(_url, params=None, headers=None, timeout=None):
            timeouts.append(timeout)
            return _response(server_error)

        def fake_sleep(seconds):
            sleeps.append(seconds)
            from data_provider.hithink_fetcher import _request_budget

            _request_budget.deadline = time.monotonic() - 1

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=fake_get), patch(
            "data_provider.hithink_fetcher.time.sleep", side_effect=fake_sleep
        ):
            with request_budget(time.monotonic() + 0.25):
                with self.assertRaises(DataFetchError) as caught:
                    fetcher._request("/api/a-share/prices/snapshot", {"thscodes": "600519.SH"})

        self.assertIn("budget exhausted", str(caught.exception))
        self.assertEqual(len(timeouts), 1)
        self.assertLessEqual(timeouts[0], 0.25)
        self.assertEqual(len(sleeps), 1)
        self.assertLessEqual(sleeps[0], 0.25)

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


class _PriorityDailyFetcher:
    def __init__(self, name: str, priority: int, prefetch_result: int | None = None) -> None:
        self.name = name
        self.priority = priority
        self.prefetch_calls = 0
        if prefetch_result is not None:
            self.prefetch_daily_klines = self._prefetch
            self._prefetch_result = prefetch_result

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        return pd.DataFrame([{"date": "2024-05-21", "close": 1}])

    def _prefetch(self, stock_codes, days=30):
        self.prefetch_calls += 1
        return self._prefetch_result


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

    def test_daily_prefetch_still_warms_hithink_when_an_earlier_source_cannot_prefetch(self) -> None:
        earlier = _PriorityDailyFetcher(name="AkshareFetcher", priority=1)
        hithink = HiThinkFetcher(api_key="manager-key", priority=7, retry_backoff=0)
        warmed = []
        hithink.prefetch_daily_klines = lambda stock_codes, days=30: warmed.append(list(stock_codes)) or 1
        manager = DataFetcherManager(fetchers=[hithink, earlier])

        self.assertEqual(manager.prefetch_daily_klines(["600519"], days=30), 1)
        self.assertEqual(warmed, [["600519"]])

    def test_daily_prefetch_continues_when_the_first_prefetch_caches_nothing(self) -> None:
        earlier = _PriorityDailyFetcher(name="TickFlowFetcher", priority=1, prefetch_result=0)
        hithink = HiThinkFetcher(api_key="manager-key", priority=7, retry_backoff=0)
        warmed = []
        hithink.prefetch_daily_klines = lambda stock_codes, days=30: warmed.append(list(stock_codes)) or 2
        manager = DataFetcherManager(fetchers=[earlier, hithink])

        self.assertEqual(manager.prefetch_daily_klines(["600519"], days=30), 2)
        self.assertEqual(earlier.prefetch_calls, 1)
        self.assertEqual(warmed, [["600519"]])

    def test_historical_permission_skips_hithink_on_the_next_manager_request(self) -> None:
        hithink = HiThinkFetcher(api_key="manager-key", priority=0, retry_backoff=0)
        fallback = _FallbackFetcher()
        manager = DataFetcherManager(fetchers=[hithink, fallback])
        denied = {"code": 2004, "message": "forbidden", "request_id": "req-denied", "data": None}

        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(denied)) as request:
            first, first_source = manager.get_daily_data("600519", start_date="2024-05-20", end_date="2024-05-21")
            second, second_source = manager.get_daily_data("000001", start_date="2024-05-20", end_date="2024-05-21")

        self.assertEqual(first_source, "FallbackFetcher")
        self.assertEqual(second_source, "FallbackFetcher")
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(fallback.calls, ["600519", "000001"])
        self.assertIsNone(manager._get_fetcher_by_name("HiThinkFetcher", capability="daily_data"))

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
