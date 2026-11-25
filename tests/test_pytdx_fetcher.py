# -*- coding: utf-8 -*-
"""Offline unit tests for PytdxFetcher routing, date filtering, retries, and cache safety."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from data_provider.base import DataFetchError
from data_provider.pytdx_fetcher import PytdxFetcher


class TestPytdxFetcher(unittest.TestCase):
    """Cover market routing, bar filtering, retry propagation, and stock-name cache."""

    def test_get_market_code_routes_shanghai_etfs_to_sh_and_shenzhen_etfs_to_sz(self) -> None:
        fetcher = PytdxFetcher(hosts=[])

        for sh_etf in ("510050", "510300", "520500", "560000", "588000"):
            self.assertEqual(fetcher._get_market_code(sh_etf), (1, sh_etf))

        for sz_etf in ("159919", "161005", "184801"):
            self.assertEqual(fetcher._get_market_code(sz_etf), (0, sz_etf))

        # Explicit exchange hints continue overriding prefix defaults.
        self.assertEqual(fetcher._get_market_code("SZ510300"), (0, "510300"))
        self.assertEqual(fetcher._get_market_code("510300.SH"), (1, "510300"))

    def test_fetch_raw_data_keeps_end_date_bars_with_15_00_timestamps(self) -> None:
        fetcher = PytdxFetcher(hosts=[("127.0.0.1", 7709)])
        api = MagicMock()
        bars = [
            {"datetime": "2026-03-16 15:00", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "vol": 100, "amount": 1010},
            {"datetime": "2026-03-17 15:00", "open": 10.1, "high": 10.5, "low": 10.0, "close": 10.4, "vol": 200, "amount": 2080},
            {"datetime": "2026-03-18 15:00", "open": 10.4, "high": 10.6, "low": 10.3, "close": 10.5, "vol": 150, "amount": 1575},
        ]
        api.get_security_bars.return_value = bars
        api.to_df.return_value = pd.DataFrame(bars)

        session = MagicMock()
        session.__enter__.return_value = api
        session.__exit__.return_value = False

        with patch.object(fetcher, "_pytdx_session", return_value=session):
            df = fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-17")

        self.assertEqual(len(df), 2)
        self.assertEqual(df["datetime"].dt.strftime("%Y-%m-%d").tolist(), ["2026-03-16", "2026-03-17"])

    def test_fetch_raw_data_retries_on_connection_error_and_raises_on_missing_datetime(self) -> None:
        fetcher = PytdxFetcher(hosts=[("127.0.0.1", 7709)])
        api = MagicMock()
        valid_bars = [
            {"datetime": "2026-03-17 15:00", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "vol": 100, "amount": 1010}
        ]
        api.get_security_bars.side_effect = [ConnectionError("reset"), valid_bars]
        api.to_df.return_value = pd.DataFrame(valid_bars)

        session = MagicMock()
        session.__enter__.return_value = api
        session.__exit__.return_value = False

        with patch.object(fetcher, "_pytdx_session", return_value=session), patch.object(
            PytdxFetcher._fetch_raw_data.retry, "sleep", side_effect=lambda _s: None
        ):
            df = fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-17")

        self.assertEqual(api.get_security_bars.call_count, 2)
        self.assertEqual(len(df), 1)

        # Missing 'datetime' column raises DataFetchError instead of KeyError.
        bad_api = MagicMock()
        bad_api.get_security_bars.return_value = [{"close": 10.0}]
        bad_api.to_df.return_value = pd.DataFrame([{"close": 10.0}])
        bad_session = MagicMock()
        bad_session.__enter__.return_value = bad_api
        bad_session.__exit__.return_value = False

        with patch.object(fetcher, "_pytdx_session", return_value=bad_session):
            with self.assertRaises(DataFetchError):
                fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-17")

    def test_fetch_raw_data_rejects_invalid_calendar_date_instead_of_dropping(self) -> None:
        """OR-COR-3a3faa1f / OR-COR-acab6b07: reject corrupt dates instead of delivering gapped bars."""
        fetcher = PytdxFetcher(hosts=[("127.0.0.1", 7709)])
        api = MagicMock()
        bars = [
            {"datetime": "2026-03-16 15:00", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "vol": 100, "amount": 1000},
            {"datetime": "2026-02-30 15:00", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "vol": 100, "amount": 1100},
            {"datetime": "2026-03-18 15:00", "open": 12.0, "high": 12.0, "low": 12.0, "close": 12.0, "vol": 100, "amount": 1200},
        ]
        api.get_security_bars.return_value = bars
        api.to_df.return_value = pd.DataFrame(bars)

        session = MagicMock()
        session.__enter__.return_value = api
        session.__exit__.return_value = False

        with patch.object(fetcher, "_pytdx_session", return_value=session):
            with self.assertRaises(DataFetchError):
                fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-18")

    def test_fetch_raw_data_retries_real_tdxhq_api_timeout_via_raise_exception(self) -> None:
        """OR-VER-fd19151b / OR-VER-47d05c28: real TdxHq_API must raise on timeout so tenacity retries."""
        from pytdx.hq import TdxHq_API
        from pytdx.parser.get_security_bars import GetSecurityBarsCmd

        fetcher = PytdxFetcher(hosts=[("127.0.0.1", 7709)])
        valid_bars = [
            {"datetime": "2026-03-17 15:00", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "vol": 100, "amount": 1010}
        ]
        call_count = 0

        def fake_connect(self_api, *args, **kwargs):
            self_api.client = MagicMock()
            return self_api

        def fake_call_api(self_cmd):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("read timed out")
            return valid_bars

        with patch.object(TdxHq_API, "connect", fake_connect), patch.object(
            TdxHq_API, "disconnect", lambda _self: None
        ), patch.object(
            GetSecurityBarsCmd, "_call_api", fake_call_api
        ), patch.object(
            PytdxFetcher._fetch_raw_data.retry, "sleep", side_effect=lambda _s: None
        ):
            df = fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-17")

        self.assertEqual(call_count, 2)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["close"], 10.1)

    def test_fetch_raw_data_retries_transient_connect_error_and_recovers_without_cooldown(self) -> None:
        """OR-COR-7c6d5d21: transient connect() TdxConnectionError on single host must trigger @retry."""
        from pytdx.errors import TdxConnectionError

        fetcher = PytdxFetcher(hosts=[("127.0.0.1", 7709)])
        valid_bars = [
            {"datetime": "2026-03-17 15:00", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "vol": 100, "amount": 1010}
        ]
        connect_calls = 0

        class _FlakyConnectApi:
            def __init__(self, raise_exception: bool = False):
                self.raise_exception = raise_exception

            def connect(self, host, port, time_out=5):
                nonlocal connect_calls
                connect_calls += 1
                if connect_calls == 1:
                    raise TdxConnectionError("connection reset by peer")
                return True

            def disconnect(self):
                return None

            def get_security_bars(self, **_kwargs):
                return valid_bars

            def to_df(self, data):
                return pd.DataFrame(data)

        with patch.object(fetcher, "_get_pytdx", return_value=_FlakyConnectApi), patch.object(
            PytdxFetcher._fetch_raw_data.retry, "sleep", side_effect=lambda _s: None
        ):
            df = fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-17")

        self.assertEqual(connect_calls, 2)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["close"], 10.1)
        self.assertTrue(fetcher.is_available_for_request("daily"))
        self.assertFalse(fetcher._is_in_connection_cooldown())

    def test_fetch_raw_data_marks_cooldown_once_after_connect_retries_exhausted(self) -> None:
        """OR-COR-7c6d5d21: persistent connect() outage retries 3 times, then enters cooldown."""
        from data_provider.base import DataSourceUnavailableError
        from pytdx.errors import TdxConnectionError

        fetcher = PytdxFetcher(hosts=[("127.0.0.1", 7709)])
        connect_calls = 0

        class _AlwaysFailConnectApi:
            def __init__(self, raise_exception: bool = False):
                self.raise_exception = raise_exception

            def connect(self, host, port, time_out=5):
                nonlocal connect_calls
                connect_calls += 1
                raise TdxConnectionError("host unreachable")

            def disconnect(self):
                return None

        with patch.object(fetcher, "_get_pytdx", return_value=_AlwaysFailConnectApi), patch.object(
            PytdxFetcher._fetch_raw_data.retry, "sleep", side_effect=lambda _s: None
        ), patch.object(
            fetcher, "_mark_connection_cooldown", wraps=fetcher._mark_connection_cooldown
        ) as mark_cooldown:
            with self.assertRaises(DataFetchError):
                fetcher.get_daily_data("600519", start_date="2026-03-16", end_date="2026-03-17")

            self.assertEqual(connect_calls, 3)
            self.assertEqual(mark_cooldown.call_count, 1)
            self.assertFalse(fetcher.is_available_for_request("daily"))
            self.assertTrue(fetcher._is_in_connection_cooldown())

            # Subsequent call during cooldown fails fast without retrying or re-connecting.
            with self.assertRaises(DataSourceUnavailableError):
                fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-17")
            self.assertEqual(connect_calls, 3)

    def test_non_retried_callers_still_enter_cooldown_immediately_on_connect_error(self) -> None:
        """Non-retried callers like get_realtime_quote keep immediate cooldown on connect failure."""
        from pytdx.errors import TdxConnectionError

        fetcher = PytdxFetcher(hosts=[("127.0.0.1", 7709)])
        connect_calls = 0

        class _AlwaysFailConnectApi:
            def __init__(self, raise_exception: bool = False):
                self.raise_exception = raise_exception

            def connect(self, host, port, time_out=5):
                nonlocal connect_calls
                connect_calls += 1
                raise TdxConnectionError("host unreachable")

            def disconnect(self):
                return None

        with patch.object(fetcher, "_get_pytdx", return_value=_AlwaysFailConnectApi):
            self.assertIsNone(fetcher.get_realtime_quote("000001"))
            self.assertEqual(connect_calls, 1)
            self.assertTrue(fetcher._is_in_connection_cooldown())
            self.assertIsNone(fetcher.get_realtime_quote("000001"))
            self.assertEqual(connect_calls, 1)

    def test_normalize_data_sorts_chronologically_coerces_numeric_and_computes_pct_chg(self) -> None:
        fetcher = PytdxFetcher(hosts=[])
        raw = pd.DataFrame(
            [
                {"datetime": pd.Timestamp("2026-03-17 15:00"), "open": "11.0", "high": "11.2", "low": "10.8", "close": "11.0", "vol": "200", "amount": "2200"},
                {"datetime": pd.Timestamp("2026-03-16 15:00"), "open": "10.0", "high": "10.1", "low": "9.9", "close": "10.0", "vol": "100", "amount": "1000"},
            ]
        )

        normalized = fetcher._normalize_data(raw, "600519")

        self.assertEqual(normalized["date"].dt.strftime("%Y-%m-%d").tolist(), ["2026-03-16", "2026-03-17"])
        self.assertEqual(normalized["close"].tolist(), [10.0, 11.0])
        self.assertEqual(normalized["volume"].tolist(), [100, 200])
        self.assertEqual(normalized["pct_chg"].tolist(), [0.0, 10.0])

    def test_get_stock_name_skips_us_hk_bse_strips_whitespace_and_shares_canonical_cache(self) -> None:
        fetcher = PytdxFetcher(hosts=[("127.0.0.1", 7709)])

        with patch.object(fetcher, "_pytdx_session") as session_mock:
            self.assertIsNone(fetcher.get_stock_name("AAPL"))
            self.assertIsNone(fetcher.get_stock_name("HK00700"))
            self.assertIsNone(fetcher.get_stock_name("430047"))
        session_mock.assert_not_called()

        api = MagicMock()
        api.get_security_list.side_effect = lambda market, start: (
            [{"code": "600519", "name": "  贵州茅台  "}, {"code": "600000", "name": "   "}]
            if market == 1 and start == 0
            else []
        )
        api.get_finance_info.return_value = None

        session = MagicMock()
        session.__enter__.return_value = api
        session.__exit__.return_value = False

        with patch.object(fetcher, "_pytdx_session", return_value=session):
            self.assertEqual(fetcher.get_stock_name("600519"), "贵州茅台")
            self.assertEqual(fetcher.get_stock_name("SH600519"), "贵州茅台")
            # Whitespace-only security list entries are ignored rather than cached as "".
            self.assertIsNone(fetcher.get_stock_name("600000"))

        self.assertNotIn("600000", fetcher._stock_list_cache)
        self.assertEqual(api.get_security_list.call_count, 2)  # Only built once across lookups

    def test_get_realtime_quote_skips_us_hk_and_strips_name(self) -> None:
        fetcher = PytdxFetcher(hosts=[("127.0.0.1", 7709)])

        with patch.object(fetcher, "_pytdx_session") as session_mock:
            self.assertIsNone(fetcher.get_realtime_quote("AAPL"))
            self.assertIsNone(fetcher.get_realtime_quote("HK00700"))
        session_mock.assert_not_called()

        api = MagicMock()
        api.get_security_quotes.return_value = [
            {
                "name": " 平安银行  ",
                "price": 10.94,
                "open": 10.9,
                "high": 11.0,
                "low": 10.8,
                "last_close": 10.88,
                "vol": 1000,
                "amount": 20000.0,
            }
        ]
        session = MagicMock()
        session.__enter__.return_value = api
        session.__exit__.return_value = False

        with patch.object(fetcher, "_pytdx_session", return_value=session):
            quote = fetcher.get_realtime_quote("000001")

        self.assertIsNotNone(quote)
        self.assertEqual(quote["name"], "平安银行")
        self.assertEqual(quote["code"], "000001")


if __name__ == "__main__":
    unittest.main()
