# -*- coding: utf-8 -*-
"""HiThink fundamentals, index data, and reference-list tests. HTTP is mocked."""

from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from data_provider.base import BaseFetcher, DataFetchError, DataFetcherManager, _hithink_index_thscode
from data_provider.hithink_fetcher import HiThinkFetcher, HiThinkRequestError
from data_provider.hithink_fundamentals import (
    HiThinkFundamentalAdapter,
    merge_fundamental_bundles,
    supplement_valuation,
)


def _ms(year: int, month: int, day: int) -> int:
    moment = datetime(year, month, day, tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(moment.timestamp() * 1000)


def _response(payload):
    class _Response:
        status_code = 200

        def json(self):
            return payload

    return _Response()


def _ok(data):
    return {"code": 0, "message": "success", "data": data}


class HiThinkExtensionTests(unittest.TestCase):
    def _fetcher(self) -> HiThinkFetcher:
        return HiThinkFetcher(api_key="hithink-test-key", retry_backoff=0)

    def test_fundamental_bundle_maps_statements_and_keeps_nulls(self) -> None:
        fetcher = self._fetcher()
        income = _ok({"item": [{
            "fiscal_year": 2024,
            "fiscal_period": "Q3",
            "period_end_ms": _ms(2024, 9, 30),
            "operating_income": 10,
            "parent_holder_net_profit": 4,
        }]})
        balance = _ok({"item": [{
            "period_end_ms": _ms(2024, 9, 30),
            "assets_total": 20,
            "total_debt": None,
        }]})
        cash = _ok({"item": [{
            "period_end_ms": _ms(2024, 9, 30),
            "act_cash_flow_net": 3,
        }]})
        indicators = _ok({
            "report": "2024-3",
            "abilities": [
                {"ability": "growth", "indicators": [
                    {"index_id": "operating_income_yoy_growth_ratio", "value": "12.5"},
                    {"index_id": "net_profit_yoy_growth_ratio", "value": None},
                ]},
                {"ability": "profitability", "indicators": [
                    {"index_id": "sale_gross_margin", "value": "89.12"},
                    {"index_id": "index_weighted_avg_roe", "value": "21"},
                ]},
            ],
        })
        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(income), _response(balance), _response(cash), _response(indicators)],
        ):
            bundle = HiThinkFundamentalAdapter(fetcher).get_fundamental_bundle("600519")

        self.assertEqual(bundle["status"], "partial")
        self.assertEqual(bundle["growth"]["revenue_yoy"], 12.5)
        self.assertIsNone(bundle["growth"]["net_profit_yoy"])
        self.assertEqual(bundle["growth"]["gross_margin"], 89.12)
        report = bundle["earnings"]["financial_report"]
        self.assertEqual(report["revenue"], 10)
        self.assertEqual(report["net_profit_parent"], 4)
        self.assertEqual(report["operating_cash_flow"], 3)
        self.assertEqual(report["roe"], 21)
        self.assertIsNone(bundle["earnings"]["balance_sheet"]["total_debt"])

    def test_statements_from_another_period_are_not_mixed(self) -> None:
        fetcher = self._fetcher()
        income = _ok({"item": [{
            "fiscal_year": 2024,
            "fiscal_period": "Q3",
            "period_end_ms": _ms(2024, 9, 30),
            "operating_income": 10,
            "parent_holder_net_profit": 4,
        }]})
        balance = _ok({"item": [{"period_end_ms": _ms(2024, 9, 30), "assets_total": 20}]})
        cash = _ok({"item": [{"period_end_ms": _ms(2024, 6, 30), "act_cash_flow_net": 3}]})
        indicators = _ok({"abilities": []})
        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(income), _response(balance), _response(cash), _response(indicators)],
        ):
            bundle = HiThinkFundamentalAdapter(fetcher).get_fundamental_bundle("600519")

        report = bundle["earnings"]["financial_report"]
        self.assertEqual(report["report_date"], "2024-09-30")
        self.assertEqual(report["revenue"], 10)
        self.assertIsNone(report["operating_cash_flow"])
        self.assertIn("balance_sheet", bundle["earnings"])
        self.assertNotIn("cash_flow", bundle["earnings"])
        self.assertIn("period_mismatch:cash_flow", bundle["errors"])

    def test_fundamental_budget_stops_later_statements(self) -> None:
        fetcher = self._fetcher()
        income = _ok({"item": [{
            "fiscal_year": 2024,
            "fiscal_period": "Q3",
            "period_end_ms": _ms(2024, 9, 30),
            "operating_income": 10,
        }]})
        calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append(url)
            from data_provider.hithink_fetcher import _request_budget

            _request_budget.deadline = time.monotonic() - 1
            return _response(income)

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=fake_get):
            bundle = HiThinkFundamentalAdapter(fetcher).get_fundamental_bundle(
                "600519",
                deadline=time.monotonic() + 5,
            )

        self.assertEqual(calls, ["https://fuyao.aicubes.cn/api/a-share/financials/income-statements"])
        self.assertIn("budget_exhausted", bundle["errors"])
        self.assertIn("income_statement", bundle["earnings"])
        self.assertNotIn("balance_sheet", bundle["earnings"])

    def test_expired_fundamental_budget_makes_no_request(self) -> None:
        fetcher = self._fetcher()
        with patch("data_provider.hithink_fetcher.requests.get", side_effect=AssertionError("request")):
            bundle = HiThinkFundamentalAdapter(fetcher).get_fundamental_bundle(
                "600519",
                deadline=time.monotonic() - 1,
            )
        self.assertEqual(bundle["errors"], ["budget_exhausted"])
        self.assertEqual(bundle["earnings"], {})

    def test_valuation_fills_only_missing_fields(self) -> None:
        fetcher = self._fetcher()
        payload = _ok({"item": [{
            "thscode": "600519.SH",
            "pe_ttm": 9,
            "pe_mrq": None,
            "pb_mrq": None,
            "ps_ttm": 2,
            "pcf_ttm": -1,
        }]})
        target = {"pe_ratio": 1.5, "pb_ratio": None}
        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(payload)):
            supplement_valuation(fetcher, "600519", target)
        self.assertEqual(target["pe_ratio"], 1.5)
        self.assertIsNone(target["pb_ratio"])
        self.assertEqual(target["ps_ttm"], 2)
        self.assertEqual(target["pcf_ttm"], -1)

    def test_fundamental_failure_falls_back_to_akshare(self) -> None:
        fetcher = self._fetcher()
        manager = DataFetcherManager(fetchers=[fetcher])
        manager._fundamental_adapter = type("Ak", (), {"get_fundamental_bundle": lambda self, code: {"status": "partial", "from": "ak"}})()
        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response({"code": 2004, "message": "denied", "data": None})) as request:
            payload, _error, _ms = manager._load_cn_fundamental_bundle("600519", 5)
        self.assertEqual(payload["from"], "ak")
        self.assertEqual(request.call_count, 1)
        self.assertFalse(fetcher.is_available("fundamental"))
        self.assertTrue(fetcher.is_available("daily_data"))

    def test_main_indices_and_rankings(self) -> None:
        fetcher = self._fetcher()
        snapshot = _ok({"item": [{
            "thscode": "000001.SH",
            "last_price": 3000,
            "price_change": 10,
            "price_change_ratio_pct": 0.3,
            "prev_price": 2990,
            "volume": 100,
            "turnover": 200,
        }]})
        catalog = _ok({"item": [
            {"thscode": "881101.TI", "name": "银行"},
            {"thscode": "881102.TI", "name": "软件"},
        ]})
        ranked = _ok({"item": [
            {"thscode": "881101.TI", "price_change_ratio_pct": -1.2},
            {"thscode": "881102.TI", "price_change_ratio_pct": 3.4},
        ]})
        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(snapshot), _response(catalog), _response(ranked)],
        ) as request:
            indices = fetcher.get_main_indices("cn")
            top, bottom = fetcher.get_sector_rankings(1)
        self.assertEqual(indices[0]["code"], "sh000001")
        self.assertEqual(indices[0]["name"], "上证指数")
        self.assertEqual(top[0]["name"], "软件")
        self.assertEqual(bottom[0]["name"], "银行")
        self.assertNotIn("hithink-test-key", request.call_args.args[0])

    def test_index_snapshot_permission_cools_only_index_snapshot(self) -> None:
        fetcher = self._fetcher()
        denied = {"code": 2004, "message": "forbidden", "request_id": "req-index-snapshot", "data": None}
        calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append(url)
            return _response(denied)

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=fake_get):
            with self.assertRaises(HiThinkRequestError):
                fetcher.get_main_indices("cn")
            self.assertIsNone(fetcher.get_main_indices("cn"))

        self.assertEqual(calls, ["https://fuyao.aicubes.cn/api/a-share-index/prices/snapshot"])
        self.assertFalse(fetcher.is_available("index_snapshot"))
        self.assertTrue(fetcher.is_available("index_daily"))
        self.assertTrue(fetcher.is_available("index_rankings"))
        self.assertTrue(fetcher.is_available("daily_data"))
        self.assertTrue(fetcher.is_available("realtime_quote"))

    def test_index_history_permission_cools_only_index_daily(self) -> None:
        fetcher = self._fetcher()
        denied = {"code": 2004, "message": "forbidden", "request_id": "req-index-daily", "data": None}
        calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append(url)
            return _response(denied)

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=fake_get):
            with self.assertRaises(HiThinkRequestError):
                fetcher.get_index_daily_data("000001.SH", start_date="2024-05-20", end_date="2024-05-21")
            with self.assertRaises(DataFetchError):
                fetcher.get_index_daily_data("000001.SH", start_date="2024-05-20", end_date="2024-05-21")

        self.assertEqual(calls, ["https://fuyao.aicubes.cn/api/a-share-index/prices/historical"])
        self.assertFalse(fetcher.is_available("index_daily"))
        self.assertTrue(fetcher.is_available("index_snapshot"))
        self.assertTrue(fetcher.is_available("index_rankings"))
        self.assertTrue(fetcher.is_available("daily_data"))
        self.assertTrue(fetcher.is_available("realtime_quote"))

    def test_index_history_rejects_unexpected_adjustment(self) -> None:
        fetcher = self._fetcher()
        payload = _ok({"adjust": "forward", "item": []})
        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response(payload)):
            with self.assertRaises(HiThinkRequestError):
                fetcher.get_index_daily_data("000001.SH", start_date="2024-05-20", end_date="2024-05-21")

    def test_names_directory_hot_stocks_and_limit_up_pool(self) -> None:
        fetcher = self._fetcher()
        search = _ok({"item": [{"ticker": "600519", "name": "贵州茅台", "asset_type": "a-share"}]})
        listing = _ok({"item": [{"ticker": "600519", "name": "贵州茅台", "asset_type": "a-share"}]})
        hot = _ok({"item": [{"ticker": "600519", "name": "贵州茅台", "rank": 1, "heat": "10"}]})
        quote = _ok({"item": [{"thscode": "600519.SH", "last_price": 1435.26, "price_change_ratio_pct": 1.77}]})
        pool = _ok({"item": [{
            "ticker": "603986",
            "name": "兆易创新",
            "last_price": 118.23,
            "price_change_ratio_pct": 10.0,
            "limit_up_time": "09:34",
            "continue_day_cnt": 2,
            "continue_day_text": "2连板",
            "seal_money": 100,
            "limit_up_reason": "存储芯片",
        }]})
        with patch(
            "data_provider.hithink_fetcher.requests.get",
            side_effect=[_response(search), _response(listing), _response(hot), _response(quote), _response(pool)],
        ) as request:
            self.assertEqual(fetcher.get_stock_name("600519"), "贵州茅台")
            frame = fetcher.get_stock_list()
            hot_rows = fetcher.get_hot_stocks(1)
            limit_rows = fetcher.get_limit_up_pool(date="20241113", n=1)
        self.assertEqual(frame.iloc[0]["code"], "600519")
        self.assertEqual(hot_rows[0]["source"], "HiThink热股榜")
        self.assertEqual(hot_rows[0]["price"], 1435.26)
        self.assertEqual(hot_rows[0]["change_pct"], 1.77)
        self.assertEqual(limit_rows[0]["consecutive_boards"], 2)
        self.assertEqual(limit_rows[0]["industry"], "")
        self.assertEqual(limit_rows[0]["limit_up_reason"], "存储芯片")
        self.assertEqual(limit_rows[0]["first_limit_time"], "")
        self.assertEqual(limit_rows[0]["limit_up_time"], "09:34")
        self.assertEqual(request.call_args_list[-1].kwargs["params"]["sort_field"], "continue_day_cnt")
        self.assertIn("date_ms", request.call_args_list[-1].kwargs["params"])


class _IndexFake(BaseFetcher):
    def __init__(self, name: str, result):
        self.name = name
        self.priority = 1
        self.result = result
        self.calls = []

    def _fetch_raw_data(self, stock_code, start_date, end_date):
        raise NotImplementedError

    def _normalize_data(self, df, stock_code):
        raise NotImplementedError

    def is_available_for_request(self, _capability: str) -> bool:
        return True

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        self.calls.append(stock_code)
        return self.result


class _HiThinkIndexFake(_IndexFake):
    def __init__(self):
        super().__init__("HiThinkFetcher", pd.DataFrame())
        self.index_calls = []

    def get_index_daily_data(self, thscode, start_date=None, end_date=None, days=30):
        self.index_calls.append(thscode)
        frame = pd.DataFrame({
            "date": [pd.Timestamp("2024-05-21")],
            "open": [1], "high": [2], "low": [1], "close": [2],
            "volume": [10], "amount": [20], "pct_chg": [1],
        })
        return frame


class HiThinkIndexRouteTests(unittest.TestCase):
    def test_fixed_index_route_still_wins_before_hithink(self) -> None:
        tencent = _IndexFake("TencentFetcher", pd.DataFrame({
            "date": [pd.Timestamp("2024-05-21")],
            "open": [1], "high": [1], "low": [1], "close": [1],
            "volume": [1], "amount": [1], "pct_chg": [0],
        }))
        hithink = _HiThinkIndexFake()
        manager = DataFetcherManager(fetchers=[tencent, hithink])
        _frame, source = manager.get_daily_data("sh000001")
        self.assertEqual(source, "TencentFetcher")
        self.assertEqual(hithink.index_calls, [])

    def test_hithink_index_history_runs_after_the_fixed_route_fails(self) -> None:
        empty = pd.DataFrame()
        fetchers = [
            _IndexFake(name, empty)
            for name in ("TencentFetcher", "AkshareFetcher", "TickFlowFetcher", "YfinanceFetcher")
        ]
        hithink = _HiThinkIndexFake()
        manager = DataFetcherManager(fetchers=[*fetchers, hithink])
        _frame, source = manager.get_daily_data("sh000001")
        self.assertEqual(source, "HiThinkFetcher")
        self.assertEqual(hithink.index_calls, ["000001.SH"])

    def test_cooled_index_daily_is_not_called_after_the_fixed_route_fails(self) -> None:
        class _CooledHiThink(_HiThinkIndexFake):
            def is_available_for_request(self, capability=""):
                return capability != "index_daily"

        empty = pd.DataFrame()
        fetchers = [
            _IndexFake(name, empty)
            for name in ("TencentFetcher", "AkshareFetcher", "TickFlowFetcher", "YfinanceFetcher")
        ]
        hithink = _CooledHiThink()
        manager = DataFetcherManager(fetchers=[*fetchers, hithink])
        _frame, source = manager.get_daily_data("sh000001")
        self.assertNotEqual(source, "HiThinkFetcher")
        self.assertEqual(hithink.index_calls, [])

    def test_hithink_index_history_records_provider_runs(self) -> None:
        empty = pd.DataFrame()
        fetchers = [
            _IndexFake(name, empty)
            for name in ("TencentFetcher", "AkshareFetcher", "TickFlowFetcher", "YfinanceFetcher")
        ]
        hithink = _HiThinkIndexFake()
        manager = DataFetcherManager(fetchers=[*fetchers, hithink])
        with patch("data_provider.base.record_provider_run") as run, \
                patch("data_provider.base.record_provider_run_started") as started:
            _frame, source = manager.get_daily_data("sh000001")
        self.assertEqual(source, "HiThinkFetcher")
        self.assertTrue(any(
            call.kwargs.get("provider") == "HiThinkFetcher"
            and call.kwargs.get("operation") == "get_index_daily_data"
            for call in started.call_args_list
        ))
        self.assertTrue(any(
            call.kwargs.get("provider") == "HiThinkFetcher"
            and call.kwargs.get("success") is True
            for call in run.call_args_list
        ))

    def test_index_symbol_accepts_tonghuashun_suffix_and_skips_csi(self) -> None:
        self.assertEqual(
            _hithink_index_thscode(SimpleNamespace(exchange="TI", bare_code="886042")),
            "886042.TI",
        )
        self.assertEqual(
            _hithink_index_thscode(SimpleNamespace(exchange="SH", bare_code="000001")),
            "000001.SH",
        )
        self.assertIsNone(_hithink_index_thscode(SimpleNamespace(exchange="CSI", bare_code="930955")))
        self.assertNotIn("HiThinkFetcher", DataFetcherManager._CN_INDEX_DAILY_SOURCE_ORDER)


def _bundle(**overrides):
    payload = {
        "status": "partial",
        "growth": {},
        "earnings": {},
        "institution": {},
        "source_chain": [],
        "errors": [],
    }
    payload.update(overrides)
    return payload


class HiThinkFundamentalMergeTests(unittest.TestCase):
    def _fetcher(self) -> HiThinkFetcher:
        return HiThinkFetcher(api_key="hithink-test-key", retry_backoff=0)

    def test_different_report_period_does_not_overwrite_akshare_blocks(self) -> None:
        merged = merge_fundamental_bundles(
            _bundle(
                growth={"revenue_yoy": 1.0, "net_profit_yoy": None},
                earnings={
                    "financial_report": {"report_date": "2024-12-31", "revenue": 1, "roe": None},
                    "forecast_summary": {"text": "预增"},
                    "quick_report_summary": {"text": "快报"},
                    "dividend": {"amount": 3},
                },
                institution={"institution_holding_change": {"pct": 1}},
                source_chain=["earnings:akshare"],
            ),
            _bundle(
                growth={"revenue_yoy": 9.0, "net_profit_yoy": 8.0, "roe": 7.0},
                earnings={
                    "financial_report": {"report_date": "2024-09-30", "revenue": 9, "roe": 7.0},
                    "income_statement": {"operating_income": 9},
                },
                source_chain=["growth:hithink"],
            ),
        )
        self.assertEqual(merged["growth"]["revenue_yoy"], 1.0)
        self.assertIsNone(merged["growth"]["net_profit_yoy"])
        self.assertEqual(merged["earnings"]["financial_report"]["revenue"], 1)
        self.assertNotIn("income_statement", merged["earnings"])
        self.assertEqual(merged["earnings"]["forecast_summary"]["text"], "预增")
        self.assertEqual(merged["earnings"]["quick_report_summary"]["text"], "快报")
        self.assertEqual(merged["earnings"]["dividend"]["amount"], 3)
        self.assertEqual(merged["institution"]["institution_holding_change"]["pct"], 1)

    def test_same_report_period_fills_only_missing_fields(self) -> None:
        merged = merge_fundamental_bundles(
            _bundle(
                growth={"revenue_yoy": 1.0, "net_profit_yoy": None},
                earnings={"financial_report": {"report_date": "2024-09-30", "revenue": 1, "roe": None}},
            ),
            _bundle(
                growth={"revenue_yoy": 9.0, "net_profit_yoy": 8.0},
                earnings={
                    "financial_report": {"report_date": "2024-09-30", "revenue": 9, "roe": 7.0},
                    "income_statement": {"operating_income": 9},
                },
            ),
        )
        self.assertEqual(merged["growth"]["revenue_yoy"], 1.0)
        self.assertEqual(merged["growth"]["net_profit_yoy"], 8.0)
        self.assertEqual(merged["earnings"]["financial_report"]["revenue"], 1)
        self.assertEqual(merged["earnings"]["financial_report"]["roe"], 7.0)
        self.assertEqual(merged["earnings"]["income_statement"]["operating_income"], 9)

    def test_missing_akshare_report_can_take_the_hithink_period(self) -> None:
        merged = merge_fundamental_bundles(
            _bundle(earnings={"dividend": {"amount": 3}}),
            _bundle(
                growth={"revenue_yoy": 9.0},
                earnings={"financial_report": {"report_date": "2024-09-30", "revenue": 9}},
            ),
        )
        self.assertEqual(merged["earnings"]["dividend"]["amount"], 3)
        self.assertEqual(merged["earnings"]["financial_report"]["revenue"], 9)
        self.assertEqual(merged["growth"]["revenue_yoy"], 9.0)

    def test_hithink_timeout_does_not_quarantine_akshare(self) -> None:
        fetcher = self._fetcher()
        manager = DataFetcherManager(fetchers=[fetcher])
        manager._fundamental_adapter.get_fundamental_bundle = lambda code: _bundle(
            earnings={"dividend": {"amount": 3}},
        )

        stop = threading.Event()

        def slow_bundle(_self, _code, deadline=None):
            stop.wait(2)
            return _bundle()

        with patch.object(HiThinkFundamentalAdapter, "get_fundamental_bundle", slow_bundle):
            payload, error, _ms = manager._load_cn_fundamental_bundle("600519", 0.4)
            follow_up, follow_error, _follow_ms = manager._run_with_retry(
                lambda: "akshare-ready",
                1,
                "fundamental_bundle_akshare",
                quarantine_key=("akshare", "fundamental_bundle"),
            )
            stop.set()
        self.assertEqual(payload["earnings"]["dividend"]["amount"], 3)
        self.assertIn("timeout", error or "")
        self.assertEqual(follow_up, "akshare-ready")
        self.assertIsNone(follow_error)

    def test_valuation_supplement_stays_inside_the_stage_budget(self) -> None:
        fetcher = self._fetcher()
        manager = DataFetcherManager(fetchers=[fetcher])
        manager._fundamental_adapter.get_fundamental_bundle = lambda code: _bundle()

        stop = threading.Event()

        def slow_valuation(_self, _code, deadline=None):
            stop.wait(2)
            return {"pe_ratio": 9}

        with patch.object(HiThinkFundamentalAdapter, "get_valuation", side_effect=AssertionError("no budget")):
            manager.get_fundamental_context("600519", budget_seconds=0, realtime_quote=None)

        with patch.object(HiThinkFundamentalAdapter, "get_valuation", slow_valuation), \
                patch.object(HiThinkFundamentalAdapter, "get_fundamental_bundle", return_value=_bundle()):
            started = time.perf_counter()
            manager.get_fundamental_context("600519", budget_seconds=0.4, realtime_quote=None)
            elapsed = time.perf_counter() - started
            stop.set()
        self.assertLess(elapsed, 1.5)

    def test_concept_ranking_includes_the_full_catalog(self) -> None:
        fetcher = self._fetcher()
        items = [{"thscode": f"881{i:03d}.TI", "name": f"概念{i}"} for i in range(11)]
        snapshots = []
        catalogs = []

        def request(path, params, capability=None):
            if path.endswith("ths-index-list"):
                catalogs.append(path)
                return {"code": 0, "data": {"item": items}}
            snapshots.append(params["thscodes"])
            return {"code": 0, "data": {"item": [
                {
                    "thscode": symbol,
                    "price_change_ratio_pct": 99 if symbol == "881010.TI" else 1,
                }
                for symbol in params["thscodes"].split(",")
            ]}}

        fetcher._request = request
        top, _bottom = fetcher.get_concept_rankings(1)
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(top[0]["name"], "概念10")
        self.assertNotIn("coverage", top[0])
        fetcher.get_concept_rankings(1)
        self.assertEqual(catalogs, [catalogs[0]])
        self.assertEqual(len(snapshots), 4)

    def test_missing_ranking_quotes_are_partial(self) -> None:
        fetcher = self._fetcher()
        items = [
            {"thscode": "881001.TI", "name": "银行"},
            {"thscode": "881002.TI", "name": "软件"},
        ]

        def request(path, params, capability=None):
            if path.endswith("ths-index-list"):
                return {"code": 0, "data": {"item": items}}
            return {"code": 0, "data": {"item": [
                {"thscode": "881001.TI", "price_change_ratio_pct": 1.2},
                {"thscode": "881002.TI", "price_change_ratio_pct": None},
            ]}}

        fetcher._request = request
        top, _bottom = fetcher.get_sector_rankings(2)
        self.assertEqual(top[0]["coverage"], "partial")
        self.assertEqual([row["name"] for row in top], ["银行"])

    def test_ranking_permission_stops_later_batches(self) -> None:
        fetcher = self._fetcher()
        items = [{"thscode": f"881{i:03d}.TI", "name": f"概念{i}"} for i in range(11)]
        snapshots = []

        def request(path, params, capability=None):
            if path.endswith("ths-index-list"):
                return {"code": 0, "data": {"item": items}}
            snapshots.append(params["thscodes"])
            if len(snapshots) == 2:
                raise HiThinkRequestError("denied", code=2004, permission=True)
            return {"code": 0, "data": {"item": [
                {"thscode": symbol, "price_change_ratio_pct": 1}
                for symbol in params["thscodes"].split(",")
            ]}}

        fetcher._request = request
        top, _bottom = fetcher.get_concept_rankings(1)
        self.assertEqual(top[0]["coverage"], "partial")
        self.assertEqual(len(snapshots), 2)
        self.assertFalse(fetcher.is_available("index_rankings"))
        self.assertTrue(fetcher.is_available("daily_data"))
        self.assertIsNone(fetcher.get_concept_rankings(1))
        self.assertEqual(len(snapshots), 2)

    def test_catalog_permission_cools_rankings_without_blocking_quotes(self) -> None:
        fetcher = self._fetcher()
        denied = {"code": 2004, "message": "forbidden", "request_id": "req-catalog", "data": None}
        calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append(url)
            return _response(denied)

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=fake_get):
            self.assertIsNone(fetcher.get_concept_rankings(1))
            self.assertIsNone(fetcher.get_sector_rankings(1))

        self.assertEqual(calls, ["https://fuyao.aicubes.cn/api/a-share-index/catalog/ths-index-list"])
        self.assertFalse(fetcher.is_available("index_rankings"))
        self.assertTrue(fetcher.is_available("daily_data"))
        self.assertTrue(fetcher.is_available("realtime_quote"))
        self.assertEqual(fetcher._index_catalog_cache, {})

    def test_ranking_snapshot_permission_does_not_block_realtime_quotes(self) -> None:
        fetcher = self._fetcher()
        denied = {"code": 2004, "message": "forbidden", "request_id": "req-rank", "data": None}
        catalog = _ok({"item": [{"thscode": "881001.TI", "name": "软件"}]})
        quote = _ok({"item": [{
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
        }]})
        calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append(url)
            if url.endswith("ths-index-list"):
                return _response(catalog)
            if url.endswith("/api/a-share-index/prices/snapshot"):
                return _response(denied)
            return _response(quote)

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=fake_get):
            self.assertIsNone(fetcher.get_concept_rankings(1))
            realtime = fetcher.get_realtime_quote("600519")

        self.assertEqual(realtime.price, 10)
        self.assertFalse(fetcher.is_available("index_rankings"))
        self.assertTrue(fetcher.is_available("realtime_quote"))
        self.assertEqual(sum(url.endswith("/api/a-share/prices/snapshot") for url in calls), 1)

    def test_realtime_permission_does_not_block_rankings(self) -> None:
        fetcher = self._fetcher()
        denied = {"code": 2004, "message": "forbidden", "request_id": "req-quote", "data": None}
        catalog = _ok({"item": [{"thscode": "881001.TI", "name": "软件"}]})
        ranked = _ok({"item": [{"thscode": "881001.TI", "price_change_ratio_pct": 1.2}]})
        calls = []

        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append(url)
            if url.endswith("/api/a-share/prices/snapshot"):
                return _response(denied)
            if url.endswith("ths-index-list"):
                return _response(catalog)
            return _response(ranked)

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=fake_get):
            with self.assertRaises(HiThinkRequestError):
                fetcher.get_realtime_quote("600519")
            top, _bottom = fetcher.get_concept_rankings(1)

        self.assertEqual(top[0]["name"], "软件")
        self.assertNotIn("coverage", top[0])
        self.assertFalse(fetcher.is_available("realtime_quote"))
        self.assertTrue(fetcher.is_available("index_rankings"))
        self.assertEqual(sum(url.endswith("ths-index-list") for url in calls), 1)
        self.assertEqual(sum(url.endswith("/api/a-share-index/prices/snapshot") for url in calls), 1)

    def test_directory_permission_does_not_repeat(self) -> None:
        fetcher = self._fetcher()
        calls = []

        def request(_path, params, capability=None):
            calls.append(params["offset"])
            self.assertEqual(capability, "stock_list")
            raise HiThinkRequestError("denied", code=2004, permission=True)

        fetcher._request = request
        frame = fetcher.get_stock_list()
        self.assertTrue(frame.empty)
        self.assertTrue(frame.attrs["truncated"])
        self.assertFalse(frame.attrs["complete"])
        self.assertEqual(calls, [0])
        self.assertFalse(fetcher.is_available("stock_list"))
        self.assertTrue(fetcher.is_available())
        fetcher.get_stock_list()
        self.assertEqual(calls, [0])

    def test_ticker_search_uses_the_directory_cooldown(self) -> None:
        fetcher = self._fetcher()
        denied = {"code": 2003, "message": "capability denied", "request_id": "req-search", "data": None}
        calls = []

        def fake_get(url, headers=None, params=None, timeout=None):
            calls.append(url)
            return _response(denied)

        with patch("data_provider.hithink_fetcher.requests.get", side_effect=fake_get):
            with self.assertRaises(HiThinkRequestError):
                fetcher.get_stock_name("600519")
            with self.assertRaises(DataFetchError):
                fetcher.get_stock_name("000001")
            frame = fetcher.get_stock_list()

        self.assertEqual(calls, ["https://fuyao.aicubes.cn/api/meta/tickers/search"])
        self.assertTrue(frame.empty)
        self.assertFalse(fetcher.is_available("stock_list"))
        self.assertFalse(fetcher.is_available("stock_name"))
        self.assertTrue(fetcher.is_available("realtime_quote"))
        self.assertTrue(fetcher.is_available("daily_data"))

    def test_batch_name_lookup_uses_hithink_directory_after_earlier_providers(self) -> None:
        primary = _DirectoryFetcher()
        fetcher = self._fetcher()
        fetcher.priority = 7
        calls = []

        def listing():
            calls.append("hithink")
            return pd.DataFrame([
                {"code": "600519", "name": "贵州茅台"},
                {"code": "000001", "name": "不应覆盖"},
            ])

        fetcher.get_stock_list = listing
        manager = DataFetcherManager(fetchers=[fetcher, primary])
        names = manager.batch_get_stock_names(["600519", "000001"])
        self.assertEqual(names["000001"], "平安银行")
        self.assertEqual(names["600519"], "贵州茅台")
        self.assertEqual(calls, ["hithink"])
        self.assertEqual(primary.list_calls, 1)

    def test_name_prefetch_does_not_download_the_full_directory(self) -> None:
        fetcher = self._fetcher()

        def listing():
            raise AssertionError("full directory")

        fetcher.get_stock_list = listing
        fetcher.get_stock_name = lambda code: "贵州茅台"
        manager = DataFetcherManager(fetchers=[fetcher])
        manager.prefetch_stock_names(["600519"], use_bulk=False)
        self.assertEqual(manager._stock_name_cache["600519"], "贵州茅台")


    def test_stock_list_marks_a_short_page_complete(self) -> None:
        fetcher = self._fetcher()

        def request(_path, params, capability=None):
            self.assertEqual(capability, "stock_list")
            self.assertEqual(params["limit"], 2)
            return _ok({"item": [{"ticker": "600519", "name": "贵州茅台", "asset_type": "a-share"}]})

        fetcher._request = request
        with patch("data_provider.hithink_reference._LIST_PAGE_SIZE", 2):
            frame = fetcher.get_stock_list()
        self.assertEqual(len(frame), 1)
        self.assertTrue(frame.attrs["complete"])
        self.assertFalse(frame.attrs["truncated"])

    def test_stock_list_marks_the_page_cap_as_truncated(self) -> None:
        fetcher = self._fetcher()
        offsets = []

        def request(_path, params, capability=None):
            self.assertEqual(capability, "stock_list")
            offsets.append(params["offset"])
            code = f"{600000 + params['offset']:06d}"
            return _ok({"item": [{"ticker": code, "name": "名称", "asset_type": "a-share"}]})

        fetcher._request = request
        with patch("data_provider.hithink_reference._LIST_PAGE_SIZE", 1), patch(
            "data_provider.hithink_reference._LIST_MAX_PAGES", 2
        ):
            frame = fetcher.get_stock_list()
        self.assertEqual(offsets, [0, 1])
        self.assertEqual(len(frame), 2)
        self.assertTrue(frame.attrs["truncated"])
        self.assertFalse(frame.attrs["complete"])

    def test_partial_concept_ranking_keeps_searching_and_uses_the_short_cache(self) -> None:
        DataFetcherManager.clear_concept_rankings_cache_for_tests()

        class _PartialRank:
            name = "HiThinkFetcher"
            priority = 1
            calls = 0

            def get_concept_rankings(self, n=5):
                type(self).calls += 1
                return ([{"name": "部分概念", "change_pct": 1, "coverage": "partial"}], [])

        class _CompleteRank:
            name = "AkshareFetcher"
            priority = 2
            calls = 0

            def get_concept_rankings(self, n=5):
                type(self).calls += 1
                return ([{"name": "完整概念", "change_pct": 2}], [])

        try:
            manager = DataFetcherManager(fetchers=[_PartialRank(), _CompleteRank()])
            top, _bottom = manager.get_concept_rankings(1)
            self.assertEqual(top[0]["name"], "完整概念")
            self.assertEqual(_PartialRank.calls, 1)
            self.assertEqual(_CompleteRank.calls, 1)

            _CompleteRank.calls = 0
            only_partial = DataFetcherManager(fetchers=[_PartialRank()])
            with patch.object(DataFetcherManager, "_CONCEPT_RANKINGS_CACHE_TTL_SECONDS", 300), patch.object(
                DataFetcherManager, "_CONCEPT_RANKINGS_EMPTY_CACHE_TTL_SECONDS", 0
            ):
                DataFetcherManager.clear_concept_rankings_cache_for_tests()
                first, _bottom = only_partial.get_concept_rankings(3)
                second, _bottom = only_partial.get_concept_rankings(3)
            self.assertEqual(first[0]["coverage"], "partial")
            self.assertEqual(second[0]["coverage"], "partial")
            self.assertEqual(_PartialRank.calls, 3)
        finally:
            DataFetcherManager.clear_concept_rankings_cache_for_tests()

    def test_partial_sector_ranking_keeps_later_provider_attempts(self) -> None:
        class _PartialSector:
            name = "HiThinkFetcher"
            priority = 1

            def get_sector_rankings(self, n=5):
                return (
                    [{"name": "部分行业", "coverage": "partial"}],
                    [{"name": "落后行业", "coverage": "partial"}],
                )

        class _EmptySector:
            name = "AkshareFetcher"
            priority = 2

            def get_sector_rankings(self, n=5):
                return ([], [])

        class _FailedSector:
            name = "TushareFetcher"
            priority = 3

            def get_sector_rankings(self, n=5):
                raise RuntimeError("sector down")

        manager = DataFetcherManager(fetchers=[_FailedSector(), _PartialSector(), _EmptySector()])
        top, _bottom, chain, error = manager._get_sector_rankings_with_meta(5)

        self.assertEqual(error, "")
        self.assertEqual(top[0]["name"], "部分行业")
        self.assertEqual(
            [(item["provider"], item["result"]) for item in chain],
            [
                ("HiThinkFetcher", "partial"),
                ("AkshareFetcher", "empty"),
                ("TushareFetcher", "failed"),
            ],
        )


class _DirectoryFetcher(BaseFetcher):
    def __init__(self):
        self.name = "TushareFetcher"
        self.priority = 1
        self.list_calls = 0

    def _fetch_raw_data(self, stock_code, start_date, end_date):
        raise NotImplementedError

    def _normalize_data(self, df, stock_code):
        raise NotImplementedError

    def get_stock_list(self):
        self.list_calls += 1
        return pd.DataFrame([{"code": "000001", "name": "平安银行"}])
