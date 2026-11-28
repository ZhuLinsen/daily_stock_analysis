# -*- coding: utf-8 -*-
"""Offline unit tests for BaostockFetcher session safety, retries, routing, and caches."""

from __future__ import annotations

import threading
import time
import types
import unittest
from concurrent.futures import CancelledError
from unittest.mock import MagicMock, patch

import pandas as pd

import src.services.screening.daily as screening_daily
from data_provider.base import DataFetchError
from data_provider.baostock_fetcher import BAOSTOCK_SESSION_LOCK, BaostockFetcher
from src.core.stock_execution_context import StockCancellationToken, set_current_stock_cancellation


class TestBaostockFetcher(unittest.TestCase):
    """Cover STAR 689 routing, session locking, retry propagation, normalization, and caches."""

    def test_convert_stock_code_routes_689_star_market_to_sh(self) -> None:
        fetcher = BaostockFetcher()

        self.assertEqual(fetcher._convert_stock_code("689009"), "sh.689009")
        self.assertEqual(fetcher._convert_stock_code("688981"), "sh.688981")

    def test_baostock_session_serializes_concurrent_calls_and_skips_logout_on_login_failure(self) -> None:
        state_lock = threading.Lock()
        active_sessions = 0
        max_concurrent = 0
        logout_calls = 0

        def fake_login():
            nonlocal active_sessions, max_concurrent
            with state_lock:
                active_sessions += 1
                max_concurrent = max(max_concurrent, active_sessions)
            return types.SimpleNamespace(error_code="0", error_msg="ok")

        def fake_logout():
            nonlocal active_sessions, logout_calls
            with state_lock:
                logout_calls += 1
                active_sessions -= 1
            return types.SimpleNamespace(error_code="0", error_msg="ok")

        fake_bs = types.SimpleNamespace(login=fake_login, logout=fake_logout)
        fetcher = BaostockFetcher()

        errors = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                barrier.wait(timeout=1)
                with fetcher._baostock_session():
                    time.sleep(0.03)
            except Exception as exc:  # pragma: no cover - collected into errors
                errors.append(exc)

        with patch.object(fetcher, "_get_baostock", return_value=fake_bs):
            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start()
            t2.start()
            t1.join(timeout=2)
            t2.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertEqual(max_concurrent, 1)
        self.assertEqual(logout_calls, 2)

        # Failed login must raise DataFetchError without calling logout.
        fail_logout_calls = 0

        def fail_login():
            return types.SimpleNamespace(error_code="1", error_msg="bad auth")

        def unexpected_logout():
            nonlocal fail_logout_calls
            fail_logout_calls += 1
            return types.SimpleNamespace(error_code="0", error_msg="ok")

        fail_bs = types.SimpleNamespace(login=fail_login, logout=unexpected_logout)
        with patch.object(fetcher, "_get_baostock", return_value=fail_bs):
            with self.assertRaises(DataFetchError):
                with fetcher._baostock_session():
                    pass
        self.assertEqual(fail_logout_calls, 0)

    def test_fetch_raw_data_retries_on_connection_error(self) -> None:
        fetcher = BaostockFetcher()
        ok_result = types.SimpleNamespace(
            error_code="0",
            error_msg="ok",
            fields=["date", "open", "high", "low", "close", "volume", "amount", "pctChg"],
            _rows=[["2026-03-17", "10.0", "10.5", "9.9", "10.4", "1000", "10400", "4.0"]],
            _idx=0,
        )

        def _next(self_rs):
            if self_rs._idx < len(self_rs._rows):
                self_rs._current = self_rs._rows[self_rs._idx]
                self_rs._idx += 1
                return True
            return False

        ok_result.next = types.MethodType(_next, ok_result)
        ok_result.get_row_data = types.MethodType(lambda self_rs: self_rs._current, ok_result)

        bs_mock = MagicMock()
        bs_mock.query_history_k_data_plus.side_effect = [
            ConnectionError("dropped"),
            ok_result,
        ]

        session = MagicMock()
        session.__enter__.return_value = bs_mock
        session.__exit__.return_value = False

        with patch.object(fetcher, "_baostock_session", return_value=session), patch.object(
            BaostockFetcher._fetch_raw_data.retry, "sleep", side_effect=lambda _s: None
        ):
            df = fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-17")

        self.assertEqual(bs_mock.query_history_k_data_plus.call_count, 2)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["close"], "10.4")

    def test_normalize_data_sorts_chronologically_drops_blank_dates_and_coerces_numeric(self) -> None:
        fetcher = BaostockFetcher()
        raw = pd.DataFrame(
            [
                {"date": "2026-03-17", "open": "10.5", "high": "10.8", "low": "10.4", "close": "10.7", "volume": "200", "amount": "2140", "pctChg": "1.9"},
                {"date": "   ", "open": "10.0", "high": "10.0", "low": "10.0", "close": "10.0", "volume": "0", "amount": "0", "pctChg": "0"},
                {"date": "2026-03-16", "open": "10.0", "high": "10.5", "low": "9.9", "close": "10.5", "volume": "100", "amount": "1050", "pctChg": "5.0"},
            ]
        )

        normalized = fetcher._normalize_data(raw, "600519")

        self.assertEqual(normalized["date"].tolist(), ["2026-03-16", "2026-03-17"])
        self.assertEqual(normalized["close"].tolist(), [10.5, 10.7])
        self.assertEqual(normalized["pct_chg"].tolist(), [5.0, 1.9])

    def test_get_stock_name_skips_unsupported_markets_strips_names_and_shares_canonical_cache(self) -> None:
        fetcher = BaostockFetcher()

        with patch.object(fetcher, "_baostock_session") as session_mock:
            self.assertIsNone(fetcher.get_stock_name("AAPL"))
            self.assertIsNone(fetcher.get_stock_name("HK00700"))
            self.assertIsNone(fetcher.get_stock_name("430047"))
        session_mock.assert_not_called()

        def make_basic_result(rows):
            rs = types.SimpleNamespace(
                error_code="0",
                fields=["code", "code_name"],
                _rows=rows,
                _idx=0,
            )

            def _next(self_rs):
                if self_rs._idx < len(self_rs._rows):
                    self_rs._current = self_rs._rows[self_rs._idx]
                    self_rs._idx += 1
                    return True
                return False

            rs.next = types.MethodType(_next, rs)
            rs.get_row_data = types.MethodType(lambda self_rs: self_rs._current, rs)
            return rs

        bs_mock = MagicMock()
        bs_mock.query_stock_basic.side_effect = [
            make_basic_result([["sh.600000", "   "]]),
            make_basic_result([["sh.600519", " 贵州茅台  "]]),
        ]
        session = MagicMock()
        session.__enter__.return_value = bs_mock
        session.__exit__.return_value = False

        with patch.object(fetcher, "_baostock_session", return_value=session):
            # Whitespace-only names must not be returned or cached.
            self.assertIsNone(fetcher.get_stock_name("600000"))
            self.assertEqual(fetcher.get_stock_name("600519"), "贵州茅台")
            self.assertEqual(fetcher.get_stock_name("SH600519"), "贵州茅台")

        self.assertNotIn("600000", fetcher._stock_name_cache)
        self.assertEqual(bs_mock.query_stock_basic.call_count, 2)

    def test_get_stock_list_strips_codes_filters_blank_names_and_populates_cache(self) -> None:
        fetcher = BaostockFetcher()
        rs = types.SimpleNamespace(
            error_code="0",
            fields=["code", "code_name"],
            _rows=[
                ["sh.600519 ", " 贵州茅台 "],
                ["sz.000001", "   "],
            ],
            _idx=0,
        )

        def _next(self_rs):
            if self_rs._idx < len(self_rs._rows):
                self_rs._current = self_rs._rows[self_rs._idx]
                self_rs._idx += 1
                return True
            return False

        rs.next = types.MethodType(_next, rs)
        rs.get_row_data = types.MethodType(lambda self_rs: self_rs._current, rs)

        bs_mock = MagicMock()
        bs_mock.query_stock_basic.return_value = rs
        session = MagicMock()
        session.__enter__.return_value = bs_mock
        session.__exit__.return_value = False

        with patch.object(fetcher, "_baostock_session", return_value=session):
            df = fetcher.get_stock_list()

        self.assertIsNotNone(df)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["code"], "600519")
        self.assertEqual(df.iloc[0]["name"], "贵州茅台")
        self.assertEqual(fetcher._stock_name_cache["sh.600519"], "贵州茅台")
        self.assertNotIn("600519", fetcher._stock_name_cache)
        self.assertNotIn("000001", fetcher._stock_name_cache)
        self.assertNotIn("sz.000001", fetcher._stock_name_cache)

    def test_fetch_raw_data_retries_on_sdk_network_error_10002007_with_real_session(self) -> None:
        """OR-VER-fe336804 / OR-VER-27b2c974: real SDK error_code=10002007 triggers retry via real session."""
        fetcher = BaostockFetcher()

        def _make_query_result(error_code: str, error_msg: str, rows):
            rs = types.SimpleNamespace(
                error_code=error_code,
                error_msg=error_msg,
                fields=["date", "open", "high", "low", "close", "volume", "amount", "pctChg"],
                _rows=rows,
                _idx=0,
            )

            def _next(self_rs):
                if self_rs._idx < len(self_rs._rows):
                    self_rs._current = self_rs._rows[self_rs._idx]
                    self_rs._idx += 1
                    return True
                return False

            rs.next = types.MethodType(_next, rs)
            rs.get_row_data = types.MethodType(lambda self_rs: self_rs._current, rs)
            return rs

        login_results = [
            types.SimpleNamespace(error_code="0", error_msg="ok"),
            types.SimpleNamespace(error_code="0", error_msg="ok"),
            types.SimpleNamespace(error_code="10002007", error_msg="网络接收错误"),
            types.SimpleNamespace(error_code="0", error_msg="ok"),
        ]
        query_results = [
            _make_query_result("10002007", "网络接收错误", []),
            _make_query_result("0", "ok", [["2026-03-17", "10.0", "10.5", "9.9", "10.4", "1000", "10400", "4.0"]]),
            _make_query_result("0", "ok", [["2026-03-18", "10.4", "10.8", "10.3", "10.7", "1200", "12840", "2.9"]]),
        ]
        logout_calls = 0

        def fake_login():
            return login_results.pop(0)

        def fake_logout():
            nonlocal logout_calls
            logout_calls += 1
            return types.SimpleNamespace(error_code="0", error_msg="ok")

        def fake_query(*args, **kwargs):
            return query_results.pop(0)

        fake_bs = types.SimpleNamespace(
            login=fake_login,
            logout=fake_logout,
            query_history_k_data_plus=fake_query,
        )

        with patch.object(fetcher, "_get_baostock", return_value=fake_bs), patch.object(
            BaostockFetcher._fetch_raw_data.retry, "sleep", side_effect=lambda _s: None
        ):
            df1 = fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-17")
            df2 = fetcher._fetch_raw_data("600519", "2026-03-17", "2026-03-18")

        self.assertEqual(df1.iloc[0]["close"], "10.4")
        self.assertEqual(df2.iloc[0]["close"], "10.7")
        # 2 successful logins for df1 + 0 (failed login) + 1 successful login for df2 = 3 logouts
        self.assertEqual(logout_calls, 3)

    def test_baostock_session_cancellation_while_waiting_on_shared_lock_skips_login(self) -> None:
        """OR-COR-1dd27bd0 / OR-COR-c00d3864: shared lock across fetcher and screening respects cancellation."""
        self.assertIs(screening_daily._BAOSTOCK_LOCK, BAOSTOCK_SESSION_LOCK)

        fetcher = BaostockFetcher()
        login_calls = 0
        worker_entered = threading.Event()
        release_holder = threading.Event()
        worker_error: list[BaseException] = []

        def fake_login():
            nonlocal login_calls
            login_calls += 1
            return types.SimpleNamespace(error_code="0", error_msg="ok")

        fake_bs = types.SimpleNamespace(
            login=fake_login,
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
        )
        token = StockCancellationToken()

        def holder():
            with BAOSTOCK_SESSION_LOCK:
                worker_entered.set()
                release_holder.wait(timeout=2)

        def worker():
            prev = set_current_stock_cancellation(token)
            try:
                with fetcher._baostock_session():
                    pass
            except BaseException as exc:
                worker_error.append(exc)
            finally:
                set_current_stock_cancellation(prev)

        holder_thread = threading.Thread(target=holder)
        holder_thread.start()
        try:
            self.assertTrue(worker_entered.wait(timeout=1))
            with patch.object(fetcher, "_get_baostock", return_value=fake_bs):
                worker_thread = threading.Thread(target=worker)
                worker_thread.start()
                time.sleep(0.08)
                token.cancel()
                worker_thread.join(timeout=2)
                self.assertFalse(worker_thread.is_alive())
        finally:
            release_holder.set()
            holder_thread.join(timeout=2)

        self.assertEqual(len(worker_error), 1)
        self.assertIsInstance(worker_error[0], CancelledError)
        self.assertEqual(login_calls, 0)

    def test_stock_name_cache_preserves_exchange_prefix_for_sh_and_sz_000001(self) -> None:
        """OR-COR-6de66f4b / OR-COR-57b61371: sh.000001 index and sz.000001 stock never collide."""
        fetcher = BaostockFetcher()

        def make_basic_result(rows):
            rs = types.SimpleNamespace(
                error_code="0",
                fields=["code", "code_name"],
                _rows=rows,
                _idx=0,
            )

            def _next(self_rs):
                if self_rs._idx < len(self_rs._rows):
                    self_rs._current = self_rs._rows[self_rs._idx]
                    self_rs._idx += 1
                    return True
                return False

            rs.next = types.MethodType(_next, rs)
            rs.get_row_data = types.MethodType(lambda self_rs: self_rs._current, rs)
            return rs

        bs_mock = MagicMock()
        bs_mock.query_stock_basic.side_effect = [
            make_basic_result([["sh.000001", "上证指数"]]),
            make_basic_result([["sz.000001", "平安银行"]]),
        ]
        session = MagicMock()
        session.__enter__.return_value = bs_mock
        session.__exit__.return_value = False

        with patch.object(fetcher, "_baostock_session", return_value=session):
            self.assertEqual(fetcher.get_stock_name("SH.000001"), "上证指数")
            self.assertEqual(fetcher.get_stock_name("000001"), "平安银行")
            self.assertEqual(fetcher.get_stock_name("SZ000001"), "平安银行")

        self.assertEqual(bs_mock.query_stock_basic.call_count, 2)

        fetcher_from_list = BaostockFetcher()
        list_rs = make_basic_result([["sh.000001", "上证指数"], ["sz.000001", "平安银行"]])
        bs_list_mock = MagicMock()
        bs_list_mock.query_stock_basic.return_value = list_rs
        list_session = MagicMock()
        list_session.__enter__.return_value = bs_list_mock
        list_session.__exit__.return_value = False

        with patch.object(fetcher_from_list, "_baostock_session", return_value=list_session):
            df = fetcher_from_list.get_stock_list()
            self.assertIsNotNone(df)
            self.assertEqual(fetcher_from_list.get_stock_name("SH.000001"), "上证指数")
            self.assertEqual(fetcher_from_list.get_stock_name("000001"), "平安银行")

    def test_screening_baostock_timeout_while_waiting_for_lock_skips_login_and_query(self) -> None:
        """OR-COR-1dd27bd0: timed-out screening wrapper must abort before login/query once lock frees."""
        import os
        import sys
        from src.services.screening.source_guard import SourceCallTimeout

        login_calls = 0
        query_calls = 0
        holder_acquired = threading.Event()
        release_holder = threading.Event()

        def fake_login():
            nonlocal login_calls
            login_calls += 1
            return types.SimpleNamespace(error_code="0", error_msg="ok")

        def fake_query(*args, **kwargs):
            nonlocal query_calls
            query_calls += 1
            return types.SimpleNamespace(error_code="0", error_msg="ok", next=lambda: False)

        fake_bs = types.SimpleNamespace(
            login=fake_login,
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            query_history_k_data_plus=fake_query,
        )

        def holder():
            with BAOSTOCK_SESSION_LOCK:
                holder_acquired.set()
                release_holder.wait(timeout=2)

        holder_thread = threading.Thread(target=holder)
        holder_thread.start()
        try:
            self.assertTrue(holder_acquired.wait(timeout=1))
            with patch.dict(sys.modules, {"baostock": fake_bs}), patch.dict(
                os.environ, {"SCREENING_DAILY_CALL_TIMEOUT_SEC": "0.08"}
            ):
                with self.assertRaises(SourceCallTimeout):
                    screening_daily._call_daily_wrapper(
                        screening_daily._fetch_daily_baostock,
                        "baostock",
                        "600519",
                        lookback_days=30,
                    )
        finally:
            release_holder.set()
            holder_thread.join(timeout=2)

        # Give the background screening thread a moment to observe the freed lock + cancel event.
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline and (login_calls == 0 and query_calls == 0):
            time.sleep(0.02)

        self.assertEqual(login_calls, 0)
        self.assertEqual(query_calls, 0)

    def test_baostock_cancellation_during_login_skips_query_and_logs_out(self) -> None:
        """OR-COR-983e6399: token cancelled while login() is in flight must not start query or pagination."""
        fetcher = BaostockFetcher()
        token = StockCancellationToken()
        query_calls = 0
        logout_calls = 0

        def fake_login():
            token.cancel()
            return types.SimpleNamespace(error_code="0", error_msg="ok")

        def fake_logout():
            nonlocal logout_calls
            logout_calls += 1
            return types.SimpleNamespace(error_code="0", error_msg="ok")

        def fake_query(*args, **kwargs):
            nonlocal query_calls
            query_calls += 1
            return types.SimpleNamespace(error_code="0", error_msg="ok", next=lambda: False)

        fake_bs = types.SimpleNamespace(
            login=fake_login,
            logout=fake_logout,
            query_history_k_data_plus=fake_query,
        )

        prev = set_current_stock_cancellation(token)
        try:
            with patch.object(fetcher, "_get_baostock", return_value=fake_bs):
                with self.assertRaises(CancelledError):
                    fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-18")
        finally:
            set_current_stock_cancellation(prev)

        self.assertEqual(query_calls, 0)
        self.assertEqual(logout_calls, 1)

    def test_baostock_pagination_error_and_empty_response_trigger_retry_and_reject_partial_data(self) -> None:
        """OR-COR-17e79df8: real ResultData mid-pagination error or dropped response rejects partial rows."""
        import json
        import sys
        import baostock.common.contants as bs_cons
        import baostock.util.socketutil as bs_sock
        from baostock.data.resultset import ResultData
        from tenacity import RetryError

        def _encode_page(error_code: str, error_msg: str, page: int, rows: list[list[str]]) -> str:
            payload = json.dumps({"record": rows})
            body = bs_cons.MESSAGE_SPLIT.join(
                [error_code, error_msg, "query_history_k_data_plus", "uid", str(page), "1", payload]
            )
            header = bs_cons.MESSAGE_SPLIT.join(
                [bs_cons.BAOSTOCK_CLIENT_VERSION, "20", str(len(body)).zfill(10)]
            )
            return f"{header}{body}\n"

        def _make_first_page_rs() -> ResultData:
            rs = ResultData()
            rs.msg_type = "20"
            rs.msg_body = bs_cons.MESSAGE_SPLIT.join(["uid", "1", "1", "sh.600519"])
            rs.error_code = "0"
            rs.error_msg = "success"
            rs.cur_page_num = "1"
            rs.fields = ["date", "open", "high", "low", "close", "volume", "amount", "pctChg"]
            rs.data = [["2026-03-16", "10.0", "10.2", "9.9", "10.1", "100", "1010", "1.0"]]
            rs.cur_row_num = 0
            return rs

        # Case 1: subsequent page returns 10002007 -> retries and rejects partial data if exhausted
        fetcher = BaostockFetcher()
        send_calls = 0

        def fake_send_msg_10002007(_msg):
            nonlocal send_calls
            send_calls += 1
            return _encode_page("10002007", "网络接收错误", 2, [])

        fake_bs_err = types.SimpleNamespace(
            login=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            query_history_k_data_plus=lambda *a, **kw: _make_first_page_rs(),
        )
        with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 1), patch.object(
            fetcher, "_get_baostock", return_value=fake_bs_err
        ), patch.object(
            bs_sock, "send_msg", side_effect=fake_send_msg_10002007
        ), patch.object(
            BaostockFetcher._fetch_raw_data.retry, "sleep", side_effect=lambda _s: None
        ):
            with self.assertRaises(RetryError) as err_ctx:
                fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-18")
        self.assertIsInstance(err_ctx.exception.last_attempt.exception(), ConnectionError)
        self.assertIn("10002007", str(err_ctx.exception.last_attempt.exception()))
        self.assertEqual(send_calls, 3)

        # Case 2: subsequent page returns None (error_code stays '0') -> rejected in both fetcher and screening
        def _make_screening_first_page_rs() -> ResultData:
            rs = ResultData()
            rs.msg_type = "20"
            rs.msg_body = bs_cons.MESSAGE_SPLIT.join(["uid", "1", "1", "sh.600519"])
            rs.error_code = "0"
            rs.error_msg = "success"
            rs.cur_page_num = "1"
            rs.fields = ["date", "open", "high", "low", "close", "volume", "amount"]
            rs.data = [["2026-03-16", "10.0", "10.2", "9.9", "10.1", "100", "1010"]]
            rs.cur_row_num = 0
            return rs

        drop_calls = 0

        def fake_send_msg_none(_msg):
            nonlocal drop_calls
            drop_calls += 1
            return None

        with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 1), patch.object(
            fetcher, "_get_baostock", return_value=fake_bs_err
        ), patch.object(
            bs_sock, "send_msg", side_effect=fake_send_msg_none
        ), patch.object(
            BaostockFetcher._fetch_raw_data.retry, "sleep", side_effect=lambda _s: None
        ):
            with self.assertRaises(RetryError) as drop_ctx:
                fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-18")
        self.assertIsInstance(drop_ctx.exception.last_attempt.exception(), ConnectionError)
        self.assertEqual(drop_calls, 3)

        fake_bs_screening = types.SimpleNamespace(
            login=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            query_history_k_data_plus=lambda *a, **kw: _make_screening_first_page_rs(),
        )
        with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 1), patch.dict(
            sys.modules, {"baostock": fake_bs_screening}
        ), patch.object(bs_sock, "send_msg", return_value=None):
            with self.assertRaises(RuntimeError):
                screening_daily._fetch_daily_baostock("600519", lookback_days=30)

        # Case 3: clean EOF succeeds in both 0.8.9-style server EOF and 0.9.4-style short-page EOF
        def _encode_eof_page() -> str:
            body = bs_cons.MESSAGE_SPLIT.join(
                ["0", "success", "query_history_k_data_plus", "uid", "2", "1", ""]
            )
            header = bs_cons.MESSAGE_SPLIT.join(
                [bs_cons.BAOSTOCK_CLIENT_VERSION, "20", str(len(body)).zfill(10)]
            )
            return f"{header}{body}\n"

        with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 1), patch.object(
            fetcher, "_get_baostock", return_value=fake_bs_err
        ), patch.object(bs_sock, "send_msg", return_value=_encode_eof_page()), patch.object(
            BaostockFetcher._fetch_raw_data.retry, "sleep", side_effect=lambda _s: None
        ):
            df_eof = fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-18")
        self.assertEqual(len(df_eof), 1)

        class _ShortPageResultData(ResultData):
            def next(self):
                if (
                    self.cur_row_num >= len(self.data)
                    and len(self.data) != bs_cons.BAOSTOCK_PER_PAGE_COUNT
                ):
                    return False
                return super().next()

        def _make_short_page_rs() -> _ShortPageResultData:
            rs = _ShortPageResultData()
            rs.msg_type = "20"
            rs.msg_body = bs_cons.MESSAGE_SPLIT.join(["uid", "1", "1", "sh.600519"])
            rs.error_code = "0"
            rs.error_msg = "success"
            rs.cur_page_num = "1"
            rs.fields = ["date", "open", "high", "low", "close", "volume", "amount", "pctChg"]
            rs.data = [["2026-03-16", "10.0", "10.2", "9.9", "10.1", "100", "1010", "1.0"]]
            rs.cur_row_num = 0
            return rs

        fake_bs_short = types.SimpleNamespace(
            login=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            query_history_k_data_plus=lambda *a, **kw: _make_short_page_rs(),
        )
        with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 10000), patch.object(
            fetcher, "_get_baostock", return_value=fake_bs_short
        ):
            df_short = fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-18")
        self.assertEqual(len(df_short), 1)

    def test_short_page_cursor_succeeds_when_inspect_getsource_raises_oserror_in_frozen_build(self) -> None:
        """OR-COR-cc9cb4e5: frozen PyInstaller bytecode without .py source files handles short pages cleanly."""
        import sys
        import baostock.common.contants as bs_cons
        from baostock.data.resultset import ResultData
        import data_provider.baostock_fetcher as baostock_fetcher
        from tenacity import RetryError

        def _make_short_rs(fields: list[str], row: list[str]) -> ResultData:
            rs = ResultData()
            rs.msg_type = "20"
            rs.msg_body = bs_cons.MESSAGE_SPLIT.join(["uid", "1", "1", "sh.600519"])
            rs.error_code = "0"
            rs.error_msg = "success"
            rs.cur_page_num = "1"
            rs.fields = fields
            rs.data = [row]
            rs.cur_row_num = 0
            return rs

        fetcher = BaostockFetcher()
        fake_bs = types.SimpleNamespace(
            login=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            query_history_k_data_plus=lambda *a, **kw: _make_short_rs(
                ["date", "open", "high", "low", "close", "volume", "amount", "pctChg"],
                ["2026-03-16", "10.0", "10.2", "9.9", "10.1", "100", "1010", "1.0"],
            ),
        )
        fake_bs_screening = types.SimpleNamespace(
            login=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            query_history_k_data_plus=lambda *a, **kw: _make_short_rs(
                ["date", "open", "high", "low", "close", "volume", "amount"],
                ["2026-03-16", "10.0", "10.2", "9.9", "10.1", "100", "1010"],
            ),
        )

        # Case 1: real ResultData with inspect.getsource raising OSError (PyInstaller bytecode-only)
        baostock_fetcher._BAOSTOCK_RESULT_SKIPS_NON_FULL_PAGE.clear()
        with patch("inspect.getsource", side_effect=OSError("source code not available")), patch.object(
            bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 500
        ), patch.object(fetcher, "_get_baostock", return_value=fake_bs), patch.dict(
            sys.modules, {"baostock": fake_bs_screening}
        ):
            df_fetcher = fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-18")
            df_screening = screening_daily._fetch_daily_baostock("600519", lookback_days=30)

        self.assertEqual(len(df_fetcher), 1)
        self.assertEqual(len(df_screening), 1)

        # Case 2: bytecode-only compiled classes (genuinely no source file on disk)
        ns: dict[str, object] = {"bs_cons": bs_cons}
        exec(
            compile(
                (
                    "class FrozenShortPageCursor:\n"
                    "    def __init__(self, rows):\n"
                    "        self.error_code = '0'\n"
                    "        self.error_msg = 'success'\n"
                    "        self.fields = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg']\n"
                    "        self.data = rows\n"
                    "        self.cur_row_num = 0\n"
                    "    def next(self):\n"
                    "        if len(self.data) == 0:\n"
                    "            return False\n"
                    "        if self.cur_row_num < len(self.data):\n"
                    "            return True\n"
                    "        if len(self.data) < bs_cons.BAOSTOCK_PER_PAGE_COUNT:\n"
                    "            return False\n"
                    "        return False\n"
                    "    def get_row_data(self):\n"
                    "        row = self.data[self.cur_row_num]\n"
                    "        self.cur_row_num += 1\n"
                    "        return row\n"
                    "\n"
                    "class FrozenLegacyCursor:\n"
                    "    def __init__(self, rows):\n"
                    "        self.error_code = '0'\n"
                    "        self.error_msg = 'success'\n"
                    "        self.fields = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg']\n"
                    "        self.data = rows\n"
                    "        self.cur_row_num = 0\n"
                    "    def next(self):\n"
                    "        if len(self.data) == 0:\n"
                    "            return False\n"
                    "        if self.cur_row_num < len(self.data):\n"
                    "            return True\n"
                    "        return False\n"
                    "    def get_row_data(self):\n"
                    "        row = self.data[self.cur_row_num]\n"
                    "        self.cur_row_num += 1\n"
                    "        return row\n"
                ),
                "<frozen baostock.data.resultset>",
                "exec",
            ),
            ns,
        )
        frozen_short_cls = ns["FrozenShortPageCursor"]
        frozen_legacy_cls = ns["FrozenLegacyCursor"]
        sample_row = ["2026-03-16", "10.0", "10.2", "9.9", "10.1", "100", "1010", "1.0"]

        fake_bs_frozen_short = types.SimpleNamespace(
            login=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            query_history_k_data_plus=lambda *a, **kw: frozen_short_cls([sample_row]),
        )
        with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 500), patch.object(
            fetcher, "_get_baostock", return_value=fake_bs_frozen_short
        ):
            df_frozen = fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-18")
        self.assertEqual(len(df_frozen), 1)

        # Full-page drop on frozen short-page cursor and legacy 0.8.9 drop must still raise ConnectionError
        with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 1), patch.object(
            fetcher, "_get_baostock", return_value=fake_bs_frozen_short
        ), patch.object(
            BaostockFetcher._fetch_raw_data.retry, "sleep", side_effect=lambda _s: None
        ):
            with self.assertRaises(RetryError) as full_drop_ctx:
                fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-18")
        self.assertIsInstance(full_drop_ctx.exception.last_attempt.exception(), ConnectionError)

        fake_bs_frozen_legacy = types.SimpleNamespace(
            login=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            query_history_k_data_plus=lambda *a, **kw: frozen_legacy_cls([sample_row]),
        )
        with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 500), patch.object(
            fetcher, "_get_baostock", return_value=fake_bs_frozen_legacy
        ), patch.object(
            BaostockFetcher._fetch_raw_data.retry, "sleep", side_effect=lambda _s: None
        ):
            with self.assertRaises(RetryError) as legacy_drop_ctx:
                fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-18")
        self.assertIsInstance(legacy_drop_ctx.exception.last_attempt.exception(), ConnectionError)

    def test_screening_transient_10002007_does_not_permanently_poison_baostock(self) -> None:
        """OR-COR-7abae19d: transient pagination/initial 10002007 errors remain retryable and recoverable."""
        import json
        import sys
        import baostock.common.contants as bs_cons
        import baostock.util.socketutil as bs_sock
        from baostock.data.resultset import ResultData

        def _encode_page(error_code: str, error_msg: str, page: int, rows: list[list[str]]) -> str:
            payload = json.dumps({"record": rows}) if rows else ""
            body = bs_cons.MESSAGE_SPLIT.join(
                [error_code, error_msg, "query_history_k_data_plus", "uid", str(page), "1", payload]
            )
            header = bs_cons.MESSAGE_SPLIT.join(
                [bs_cons.BAOSTOCK_CLIENT_VERSION, "20", str(len(body)).zfill(10)]
            )
            return f"{header}{body}\n"

        def _make_page_rs(error_code: str = "0", error_msg: str = "success", row_date: str = "2026-03-16") -> ResultData:
            rs = ResultData()
            rs.msg_type = "20"
            rs.msg_body = bs_cons.MESSAGE_SPLIT.join(["uid", "1", "1", "sh.600519"])
            rs.error_code = error_code
            rs.error_msg = error_msg
            rs.cur_page_num = "1"
            rs.fields = ["date", "open", "high", "low", "close", "volume", "amount"]
            rs.data = (
                [[row_date, "10.0", "10.2", "9.9", "10.1", "100", "1010"]]
                if error_code == "0"
                else []
            )
            rs.cur_row_num = 0
            return rs

        saved_health = dict(screening_daily._SOURCE_HEALTH)
        try:
            screening_daily._SOURCE_HEALTH.clear()

            # Case 1: transient pagination 10002007 on attempt 1 recovers on retry attempt 2
            send_responses = [
                _encode_page("10002007", "网络接收错误", 2, []),
                _encode_page("0", "success", 2, []),
            ]
            fake_bs_retry = types.SimpleNamespace(
                login=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
                logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
                query_history_k_data_plus=lambda *a, **kw: _make_page_rs(),
            )
            with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 1), patch.dict(
                sys.modules, {"baostock": fake_bs_retry}
            ), patch.object(
                bs_sock, "send_msg", side_effect=lambda _msg: send_responses.pop(0)
            ), patch.object(
                screening_daily.time, "sleep", side_effect=lambda _s: None
            ), patch.object(
                screening_daily, "daily_history_is_stale", return_value=False
            ):
                df_recovered = screening_daily.fetch_daily_history(
                    "600519",
                    lookback_days=30,
                    source="baostock",
                    retries=1,
                )
            self.assertEqual(len(df_recovered), 1)
            self.assertEqual(send_responses, [])

            # Case 2: exhausted pagination 10002007 + initial-page 10002007 do not permanently block later stocks
            screening_daily._SOURCE_HEALTH.clear()
            query_plan = [
                _make_page_rs("0", "success", "2026-03-16"),
                _make_page_rs("10002007", "网络接收错误"),
                _make_page_rs("0", "success", "2026-03-17"),
            ]
            page2_plan = [
                _encode_page("10002007", "网络接收错误", 2, []),
                _encode_page("0", "success", 2, []),
            ]
            fake_bs_multi = types.SimpleNamespace(
                login=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
                logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
                query_history_k_data_plus=lambda *a, **kw: query_plan.pop(0),
            )
            with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 1), patch.dict(
                sys.modules, {"baostock": fake_bs_multi}
            ), patch.object(
                bs_sock, "send_msg", side_effect=lambda _msg: page2_plan.pop(0)
            ), patch.object(
                screening_daily, "daily_history_is_stale", return_value=False
            ):
                with self.assertRaises(RuntimeError) as pag_err:
                    screening_daily.fetch_daily_history("600519", lookback_days=30, source="baostock", retries=0)
                self.assertIn("10002007", str(pag_err.exception))

                with self.assertRaises(RuntimeError) as init_err:
                    screening_daily.fetch_daily_history("600000", lookback_days=30, source="baostock", retries=0)
                self.assertIn("10002007", str(init_err.exception))

                df_next_stock = screening_daily.fetch_daily_history(
                    "000001", lookback_days=30, source="baostock", retries=0
                )
            self.assertEqual(len(df_next_stock), 1)
            self.assertEqual(df_next_stock.iloc[0]["date"], "2026-03-17")
            self.assertFalse(hasattr(screening_daily, "_BAOSTOCK_OUTAGE_ERROR"))
        finally:
            screening_daily._SOURCE_HEALTH.clear()
            screening_daily._SOURCE_HEALTH.update(saved_health)

    def test_real_send_msg_peer_eof_breaks_infinite_recv_loop_and_releases_shared_lock(self) -> None:
        """OR-COR-53ac80e6: real ResultData.next()/send_msg breaks immediately on peer EOF b'' and frees lock."""
        import os
        import sys
        import baostock.common.contants as bs_cons
        import baostock.common.context as bs_context
        from baostock.data.resultset import ResultData
        from tenacity import RetryError

        class _FakeEOFSocket:
            def __init__(self) -> None:
                self.sent: list[bytes] = []
                self.recv_calls = 0
                self.closed = False

            def send(self, data: bytes) -> int:
                self.sent.append(data)
                return len(data)

            def recv(self, _bufsize: int) -> bytes:
                self.recv_calls += 1
                return b""

            def close(self) -> None:
                self.closed = True

        def _make_first_page_rs(fields: list[str], row: list[str]) -> ResultData:
            rs = ResultData()
            rs.msg_type = "20"
            rs.msg_body = bs_cons.MESSAGE_SPLIT.join(["uid", "1", "1", "sh.600519"])
            rs.error_code = "0"
            rs.error_msg = "success"
            rs.cur_page_num = "1"
            rs.fields = fields
            rs.data = [row]
            rs.cur_row_num = 0
            return rs

        # Case 1: screening call hits real ResultData.next() -> real send_msg() -> fake socket returning b""
        eof_sock = _FakeEOFSocket()
        fake_bs_screening = types.SimpleNamespace(
            login=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            query_history_k_data_plus=lambda *a, **kw: _make_first_page_rs(
                ["date", "open", "high", "low", "close", "volume", "amount"],
                ["2026-03-16", "10.0", "10.2", "9.9", "10.1", "100", "1010"],
            ),
        )
        with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 1), patch.object(
            bs_context, "default_socket", eof_sock, create=True
        ), patch.dict(sys.modules, {"baostock": fake_bs_screening}), patch.dict(
            os.environ, {"SCREENING_DAILY_CALL_TIMEOUT_SEC": "2.0"}
        ):
            started = time.monotonic()
            with self.assertRaises(RuntimeError) as screen_err:
                screening_daily._call_daily_wrapper(
                    screening_daily._fetch_daily_baostock,
                    "baostock",
                    "600519",
                    lookback_days=30,
                )
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 1.0)
        self.assertEqual(eof_sock.recv_calls, 1)
        self.assertTrue(eof_sock.closed)
        self.assertIn("EOF", str(screen_err.exception))

        # Regular BaostockFetcher caller without a cancel token acquires shared lock cleanly afterwards
        fetcher = BaostockFetcher()
        ok_rs = _make_first_page_rs(
            ["date", "open", "high", "low", "close", "volume", "amount", "pctChg"],
            ["2026-03-16", "10.0", "10.2", "9.9", "10.1", "100", "1010", "1.0"],
        )
        fake_bs_ok = types.SimpleNamespace(
            login=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            query_history_k_data_plus=lambda *a, **kw: ok_rs,
        )
        with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 500), patch.object(
            fetcher, "_get_baostock", return_value=fake_bs_ok
        ):
            df_ok = fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-18")
        self.assertEqual(len(df_ok), 1)

        # Case 2: BaostockFetcher itself also breaks out of real send_msg EOF loop and retries cleanly
        fetcher_eof_socks: list[_FakeEOFSocket] = []

        def _fresh_eof_login():
            sock = _FakeEOFSocket()
            fetcher_eof_socks.append(sock)
            setattr(bs_context, "default_socket", sock)
            return types.SimpleNamespace(error_code="0", error_msg="ok")

        fake_bs_eof = types.SimpleNamespace(
            login=_fresh_eof_login,
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            query_history_k_data_plus=lambda *a, **kw: _make_first_page_rs(
                ["date", "open", "high", "low", "close", "volume", "amount", "pctChg"],
                ["2026-03-16", "10.0", "10.2", "9.9", "10.1", "100", "1010", "1.0"],
            ),
        )
        with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 1), patch.object(
            bs_context, "default_socket", None, create=True
        ), patch.object(fetcher, "_get_baostock", return_value=fake_bs_eof), patch.object(
            BaostockFetcher._fetch_raw_data.retry, "sleep", side_effect=lambda _s: None
        ):
            with self.assertRaises(RetryError) as fetch_eof_ctx:
                fetcher._fetch_raw_data("600519", "2026-03-16", "2026-03-18")

        self.assertIsInstance(fetch_eof_ctx.exception.last_attempt.exception(), ConnectionError)
        self.assertEqual(len(fetcher_eof_socks), 3)
        self.assertTrue(all(s.recv_calls == 1 and s.closed for s in fetcher_eof_socks))

    def test_source_guard_timeout_force_closes_blocking_socket_and_frees_shared_lock(self) -> None:
        """OR-COR-53ac80e6: source_guard timeout closes blocked Baostock socket so lock is released."""
        import os
        import sys
        import baostock.common.contants as bs_cons
        import baostock.common.context as bs_context
        from baostock.data.resultset import ResultData
        from src.services.screening.source_guard import SourceCallTimeout

        class _FakeBlockingSocket:
            def __init__(self) -> None:
                self.entered_recv = threading.Event()
                self.closed_event = threading.Event()

            def send(self, data: bytes) -> int:
                return len(data)

            def recv(self, _bufsize: int) -> bytes:
                self.entered_recv.set()
                self.closed_event.wait(timeout=5.0)
                return b""

            def close(self) -> None:
                self.closed_event.set()

        blocking_sock = _FakeBlockingSocket()

        def _make_first_page_rs() -> ResultData:
            rs = ResultData()
            rs.msg_type = "20"
            rs.msg_body = bs_cons.MESSAGE_SPLIT.join(["uid", "1", "1", "sh.600519"])
            rs.error_code = "0"
            rs.error_msg = "success"
            rs.cur_page_num = "1"
            rs.fields = ["date", "open", "high", "low", "close", "volume", "amount"]
            rs.data = [["2026-03-16", "10.0", "10.2", "9.9", "10.1", "100", "1010"]]
            rs.cur_row_num = 0
            return rs

        fake_bs = types.SimpleNamespace(
            login=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
            query_history_k_data_plus=lambda *a, **kw: _make_first_page_rs(),
        )
        with patch.object(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 1), patch.object(
            bs_context, "default_socket", blocking_sock, create=True
        ), patch.dict(sys.modules, {"baostock": fake_bs}), patch.dict(
            os.environ, {"SCREENING_DAILY_CALL_TIMEOUT_SEC": "0.08"}
        ):
            with self.assertRaises(SourceCallTimeout):
                screening_daily._call_daily_wrapper(
                    screening_daily._fetch_daily_baostock,
                    "baostock",
                    "600519",
                    lookback_days=30,
                )

        self.assertTrue(blocking_sock.entered_recv.is_set())
        self.assertTrue(blocking_sock.closed_event.is_set())

        # Shared lock must become available quickly for a regular caller without a cancel token
        acquired = BAOSTOCK_SESSION_LOCK.acquire(timeout=1.0)
        try:
            self.assertTrue(acquired)
        finally:
            if acquired:
                BAOSTOCK_SESSION_LOCK.release()

    def test_regular_baostock_caller_without_cancel_token_times_out_if_lock_stuck(self) -> None:
        """OR-COR-53ac80e6: non-cancelled caller raises TimeoutError instead of hanging forever on lock."""
        import data_provider.baostock_fetcher as baostock_fetcher

        fetcher = BaostockFetcher()
        login_calls = 0
        holder_acquired = threading.Event()
        release_holder = threading.Event()

        def fake_login():
            nonlocal login_calls
            login_calls += 1
            return types.SimpleNamespace(error_code="0", error_msg="ok")

        fake_bs = types.SimpleNamespace(
            login=fake_login,
            logout=lambda: types.SimpleNamespace(error_code="0", error_msg="ok"),
        )

        def holder():
            with BAOSTOCK_SESSION_LOCK:
                holder_acquired.set()
                release_holder.wait(timeout=2.0)

        holder_thread = threading.Thread(target=holder)
        holder_thread.start()
        try:
            self.assertTrue(holder_acquired.wait(timeout=1.0))
            with patch.object(baostock_fetcher, "_BAOSTOCK_LOCK_TIMEOUT_SECONDS", 0.08), patch.object(
                fetcher, "_get_baostock", return_value=fake_bs
            ):
                started = time.monotonic()
                with self.assertRaises(TimeoutError):
                    with fetcher._baostock_session():
                        pass
                elapsed = time.monotonic() - started
        finally:
            release_holder.set()
            holder_thread.join(timeout=2.0)

        self.assertLess(elapsed, 0.8)
        self.assertEqual(login_calls, 0)


if __name__ == "__main__":
    unittest.main()
