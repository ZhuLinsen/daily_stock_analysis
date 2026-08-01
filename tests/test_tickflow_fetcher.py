# -*- coding: utf-8 -*-
"""Unit tests for the TickFlow fetcher."""

import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


from data_provider.base import DataFetchError
from data_provider.realtime_types import RealtimeSource
from data_provider.tickflow_fetcher import TickFlowFetcher


class _PermissionLikeError(Exception):
    def __init__(self, message="forbidden", *, status_code=403, code="FORBIDDEN"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class _FakeQuotesResource:
    def __init__(self, symbols_data=None, universe_data=None):
        self._symbols_data = symbols_data or []
        self._universe_data = universe_data or []
        self.calls = []

    def get(self, *, symbols=None, universes=None, as_dataframe=False):
        self.calls.append({"symbols": symbols, "universes": universes, "as_dataframe": as_dataframe})
        if symbols is not None:
            if isinstance(self._symbols_data, dict):
                return self._symbols_data.get(tuple(symbols), [])
            return self._symbols_data
        if universes is not None:
            if isinstance(self._universe_data, Exception):
                raise self._universe_data
            return self._universe_data
        return []


class _FakeKlinesResource:
    def __init__(self, daily_data=None, batch_data=None, batch_error=None, intraday_data=None, ex_factors_data=None):
        self.daily_data = daily_data if daily_data is not None else pd.DataFrame()
        self.batch_data = batch_data if batch_data is not None else {}
        self.batch_error = batch_error
        self.intraday_data = intraday_data if intraday_data is not None else pd.DataFrame()
        self.ex_factors_data = ex_factors_data if ex_factors_data is not None else pd.DataFrame()
        self.get_calls = []
        self.batch_calls = []
        self.intraday_calls = []
        self.ex_factors_calls = []

    def get(self, symbol, **kwargs):
        self.get_calls.append({"symbol": symbol, **kwargs})
        return self.daily_data

    def batch(self, symbols, **kwargs):
        symbols = list(symbols)
        self.batch_calls.append({"symbols": symbols, **kwargs})
        if self.batch_error:
            raise self.batch_error
        if isinstance(self.batch_data, dict):
            return {symbol: self.batch_data[symbol] for symbol in symbols if symbol in self.batch_data}
        return self.batch_data

    def intraday(self, symbol, **kwargs):
        self.intraday_calls.append({"symbol": symbol, **kwargs})
        return self.intraday_data

    def intraday_batch(self, symbols, **kwargs):
        return {symbol: self.intraday_data for symbol in symbols}

    def ex_factors(self, symbols, **kwargs):
        self.ex_factors_calls.append({"symbols": list(symbols), **kwargs})
        return self.ex_factors_data


class _FakeUniverseResource:
    def __init__(self, data=None, list_data=None, batch_data=None):
        self.data = data if data is not None else {"symbols": []}
        self.list_data = list_data or []
        self.batch_data = batch_data or {}
        self.calls = []

    def get(self, universe_id):
        self.calls.append(universe_id)
        if isinstance(self.data, Exception):
            raise self.data
        return self.data

    def list(self):
        return self.list_data

    def batch(self, ids):
        return {universe_id: self.batch_data[universe_id] for universe_id in ids}


class _FakeInstrumentsResource:
    def get(self, symbol):
        return {"symbol": symbol, "name": "InstrumentName"}


class _FakeClient:
    def __init__(self, symbols_data=None, universe_data=None, daily_data=None, batch_data=None, batch_error=None, universe_list=None, universe_batch=None):
        self.quotes = _FakeQuotesResource(symbols_data, universe_data)
        self.klines = _FakeKlinesResource(daily_data=daily_data, batch_data=batch_data, batch_error=batch_error)
        self.universes = _FakeUniverseResource(universe_data, universe_list, universe_batch)
        self.instruments = _FakeInstrumentsResource()
        self.closed = False

    def close(self):
        self.closed = True


def _daily_rows(symbol="600519.SH"):
    return pd.DataFrame(
        [
            {"symbol": symbol, "timestamp": 1704067200000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100, "amount": 1000},
            {"symbol": symbol, "timestamp": 1704153600000, "open": 10, "high": 12, "low": 10, "close": 11, "volume": 200, "amount": 2500},
        ]
    )


def _dated_daily_rows(start, periods, symbol="600519.SH"):
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "trade_date": day.strftime("%Y-%m-%d"),
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10 + index,
                "volume": 100 + index,
                "amount": 1000 + index,
            }
            for index, day in enumerate(pd.bdate_range(start, periods=periods))
        ]
    )


def _quote(symbol, *, last_price=11.0, prev_close=10.0, amount=1000.0, volume=100, name="", change_pct=0.1, amplitude=0.2, turnover_rate=0.03):
    ext = {"change_pct": change_pct, "amplitude": amplitude, "turnover_rate": turnover_rate}
    if name:
        ext["name"] = name
    return {
        "symbol": symbol,
        "last_price": last_price,
        "prev_close": prev_close,
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "volume": volume,
        "amount": amount,
        "timestamp": 1704153600000,
        "ext": ext,
    }


class TestTickFlowFetcher(unittest.TestCase):
    def test_daily_kline_normalizes_units_and_pct_change(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(daily_data=_daily_rows())

        df = fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-01-03")

        self.assertEqual(fetcher._client.klines.get_calls[0]["symbol"], "600519.SH")
        self.assertEqual(fetcher._client.klines.get_calls[0]["period"], "1d")
        self.assertEqual(fetcher._client.klines.get_calls[0]["count"], 30)
        self.assertEqual(fetcher._client.klines.get_calls[0]["adjust"], "none")
        self.assertEqual(df.iloc[0]["volume"], 10000)
        self.assertEqual(df.iloc[1]["volume"], 20000)
        self.assertEqual(df.iloc[1]["amount"], 2500)
        self.assertAlmostEqual(df.iloc[1]["pct_chg"], 10.0)

    def test_daily_pct_chg_column_keeps_percent_values_below_one(self):
        rows = _daily_rows()
        rows["pct_chg"] = [0.0, 0.5]
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(daily_data=rows)

        df = fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-01-03")

        self.assertAlmostEqual(df.iloc[1]["pct_chg"], 0.5)

    def test_daily_change_pct_column_is_treated_as_ratio(self):
        rows = _daily_rows()
        rows["change_pct"] = [0.0, 0.005]
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(daily_data=rows)

        df = fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-01-03")

        self.assertAlmostEqual(df.iloc[1]["pct_chg"], 0.5)

    def test_coerce_frame_wraps_scalar_dict_as_one_row(self):
        df = TickFlowFetcher._coerce_frame({"symbol": "600519.SH", "revenue": 1.0})

        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["symbol"], "600519.SH")
        self.assertEqual(df.iloc[0]["revenue"], 1.0)

    def test_realtime_quote_maps_ratios_to_percent_and_lots_to_shares(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(symbols_data=[_quote("600519.SH", name="Kweichow")])

        quote = fetcher.get_realtime_quote("600519")

        self.assertEqual(quote.source, RealtimeSource.TICKFLOW)
        self.assertEqual(quote.code, "600519")
        self.assertEqual(quote.name, "Kweichow")
        self.assertEqual(quote.volume, 10000)
        self.assertAlmostEqual(quote.change_pct, 10.0)
        self.assertAlmostEqual(quote.amplitude, 20.0)
        self.assertAlmostEqual(quote.turnover_rate, 3.0)

    def test_batch_daily_prefetch_warms_cache_for_followup_single_call(self):
        batch_data = {"600519.SH": _daily_rows("600519.SH")}
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(daily_data=pd.DataFrame(), batch_data=batch_data)

        cached = fetcher.prefetch_daily_klines(["600519"], start_date="2024-01-01", end_date="2024-01-03")
        df = fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-01-03")

        self.assertEqual(cached, 1)
        self.assertEqual(len(fetcher._client.klines.batch_calls), 1)
        self.assertEqual(fetcher._client.klines.get_calls, [])
        self.assertEqual(len(df), 2)

    def test_daily_kline_request_passes_count_and_rejects_capped_incomplete_history(self):
        request_count = TickFlowFetcher._daily_kline_count("2020-01-01", "2026-05-10")
        rows = _dated_daily_rows("2023-01-03", request_count)
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(daily_data=rows)

        with self.assertRaises(DataFetchError):
            fetcher.get_daily_data("600519", start_date="2020-01-01", end_date="2026-05-10")

        call = fetcher._client.klines.get_calls[0]
        self.assertEqual(call["count"], request_count)
        self.assertEqual(call["period"], "1d")
        self.assertIn("start_time", call)
        self.assertIn("end_time", call)

    def test_daily_kline_keeps_short_history_when_count_cap_not_hit(self):
        request_count = TickFlowFetcher._daily_kline_count("2020-01-01", "2026-05-10")
        rows = _dated_daily_rows("2023-01-03", 2)
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(daily_data=rows)

        df = fetcher.get_daily_data("600519", start_date="2020-01-01", end_date="2026-05-10")

        self.assertEqual(len(df), 2)
        self.assertEqual(fetcher._client.klines.get_calls[0]["count"], request_count)

    def test_daily_kline_keeps_capped_history_when_requested_start_is_weekend(self):
        request_count = TickFlowFetcher._daily_kline_count("2024-03-02", "2027-05-10")
        rows = _dated_daily_rows("2024-03-04", request_count)
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(daily_data=rows)

        df = fetcher.get_daily_data("600519", start_date="2024-03-02", end_date="2027-05-10")

        self.assertGreater(len(df), 0)
        self.assertEqual(pd.Timestamp(df.iloc[0]["date"]).strftime("%Y-%m-%d"), "2024-03-04")
        self.assertLessEqual(pd.Timestamp(df.iloc[-1]["date"]).strftime("%Y-%m-%d"), "2027-05-10")

    def test_batch_daily_prefetch_passes_count_and_skips_truncated_cache(self):
        request_count = TickFlowFetcher._daily_kline_count("2020-01-01", "2026-05-10")
        batch_data = {"600519.SH": _dated_daily_rows("2023-01-03", request_count, "600519.SH")}
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(daily_data=_daily_rows(), batch_data=batch_data)

        cached = fetcher.prefetch_daily_klines(["600519"], start_date="2020-01-01", end_date="2026-05-10")
        df = fetcher.get_daily_data("600519", start_date="2020-01-01", end_date="2026-05-10")

        self.assertEqual(cached, 0)
        batch_call = fetcher._client.klines.batch_calls[0]
        self.assertEqual(batch_call["count"], request_count)
        self.assertEqual(len(fetcher._client.klines.get_calls), 1)
        self.assertEqual(len(df), 2)

    def test_batch_daily_prefetch_batches_and_logs_summary(self):
        batch_data = {
            "600519.SH": _daily_rows("600519.SH"),
            "000001.SZ": _daily_rows("000001.SZ"),
        }
        fetcher = TickFlowFetcher(api_key="sk-test", batch_size=1)
        fetcher._client = _FakeClient(daily_data=pd.DataFrame(), batch_data=batch_data)

        with self.assertLogs("data_provider.tickflow_fetcher", level="INFO") as logs:
            cached = fetcher.prefetch_daily_klines(
                ["600519", "000001"],
                start_date="2024-01-01",
                end_date="2024-01-03",
            )

        self.assertEqual(cached, 2)
        self.assertEqual(
            [call["symbols"] for call in fetcher._client.klines.batch_calls],
            [["600519.SH"], ["000001.SZ"]],
        )
        self.assertEqual([call["count"] for call in fetcher._client.klines.batch_calls], [30, 30])
        self.assertIn("cached=2 total=2 batches=2", "\n".join(logs.output))

    def test_batch_daily_permission_failure_negative_caches_and_single_fallback_still_works(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(
            daily_data=_daily_rows(),
            batch_error=_PermissionLikeError("batch permission denied"),
        )

        self.assertEqual(fetcher.prefetch_daily_klines(["600519"], start_date="2024-01-01", end_date="2024-01-03"), 0)
        self.assertEqual(fetcher.prefetch_daily_klines(["600519"], start_date="2024-01-01", end_date="2024-01-03"), 0)
        self.assertEqual(len(fetcher._client.klines.batch_calls), 1)

        df = fetcher.get_daily_data("600519", start_date="2024-01-01", end_date="2024-01-03")
        self.assertEqual(len(df), 2)
        self.assertEqual(len(fetcher._client.klines.get_calls), 1)

    def test_realtime_prefetch_uses_quote_cache(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(symbols_data=[_quote("600519.SH")])

        self.assertEqual(fetcher.prefetch_realtime_quotes(["600519"]), 1)
        quote = fetcher.get_realtime_quote("600519")

        self.assertIsNotNone(quote)
        self.assertEqual(len(fetcher._client.quotes.calls), 1)

    def test_stock_list_uses_universe_and_keeps_missing_optional_fields_blank(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(universe_data={"symbols": [{"symbol": "600519.SH", "name": "\u8d35\u5dde\u8305\u53f0"}, {"code": "000001.SZ", "short_name": "\u5e73\u5b89\u94f6\u884c"}, "AAPL"]})

        df = fetcher.get_stock_list()

        self.assertEqual(list(df["code"]), ["600519", "000001"])
        self.assertEqual(list(df["name"]), ["\u8d35\u5dde\u8305\u53f0", "\u5e73\u5b89\u94f6\u884c"])
        self.assertEqual(list(df["industry"]), ["", ""])
        self.assertEqual(list(df["area"]), ["", ""])

    def test_get_main_indices_maps_cn_quotes(self):
        symbols = ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH", "000016.SH", "000300.SH"]
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(symbols_data=[_quote(symbol, last_price=10, prev_close=9) for symbol in symbols])

        data = fetcher.get_main_indices(region="cn")

        self.assertEqual(data[0]["code"], "000001")
        self.assertEqual(data[0]["name"], "\u4e0a\u8bc1\u6307\u6570")
        self.assertAlmostEqual(data[0]["change_pct"], 10.0)

    def test_get_market_stats_permission_failure_is_negative_cached(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(universe_data=_PermissionLikeError("universe forbidden"))

        self.assertIsNone(fetcher.get_market_stats())
        self.assertIsNone(fetcher.get_market_stats())
        self.assertEqual(len(fetcher._client.quotes.calls), 1)

    def test_get_sector_rankings_aggregates_sw1_universes_and_caches(self):
        universe_list = [
            {"id": "CN_Equity_SW1_A", "name": "SW1轻工制造"},
            {"id": "CN_Equity_SW1_B", "name": "SW1轻工制造"},
            {"id": "CN_Equity_SW1_C", "name": "SW1银行"},
            {"id": "CN_Equity_SW2_D", "name": "SW2造纸"},
        ]
        universe_batch = {
            "CN_Equity_SW1_A": {"symbols": ["600103.SH"]},
            "CN_Equity_SW1_B": {"symbols": ["600103.SH", "002078.SZ"]},
            "CN_Equity_SW1_C": {"symbols": ["000001.SZ"]},
        }
        quotes = [
            _quote("600103.SH", change_pct=0.02),
            _quote("002078.SZ", change_pct=0.04),
            _quote("000001.SZ", change_pct=-0.01),
        ]
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(
            universe_data=quotes,
            universe_list=universe_list,
            universe_batch=universe_batch,
        )

        top, bottom = fetcher.get_sector_rankings(1)
        cached_top, cached_bottom = fetcher.get_sector_rankings(1)

        self.assertEqual(top[0]["name"], "轻工制造")
        self.assertAlmostEqual(top[0]["change_pct"], 3.0)
        self.assertEqual(top[0]["constituent_count"], 2)
        self.assertEqual(bottom[0]["name"], "银行")
        self.assertAlmostEqual(bottom[0]["change_pct"], -1.0)
        self.assertEqual(cached_top, top)
        self.assertEqual(cached_bottom, bottom)
        self.assertEqual(len(fetcher._client.quotes.calls), 1)

    def test_capability_negative_cache_retries_after_ttl(self):
        fetcher = TickFlowFetcher(api_key="sk-test")
        fetcher._client = _FakeClient(universe_data=_PermissionLikeError("universe forbidden"))

        with patch("data_provider.tickflow_fetcher.monotonic", side_effect=[100.0, 100.0, 1001.0, 1001.0]):
            self.assertIsNone(fetcher.get_market_stats())
            self.assertIsNone(fetcher.get_market_stats())

        self.assertEqual(len(fetcher._client.quotes.calls), 2)


if __name__ == "__main__":
    unittest.main()
