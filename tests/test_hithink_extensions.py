# -*- coding: utf-8 -*-
"""HiThink fundamentals, index data, and reference-list tests. HTTP is mocked."""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from data_provider.base import BaseFetcher, DataFetcherManager
from data_provider.hithink_fetcher import HiThinkFetcher, HiThinkRequestError
from data_provider.hithink_fundamentals import HiThinkFundamentalAdapter, supplement_valuation


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
        balance = _ok({"item": [{"assets_total": 20, "total_debt": None}]})
        cash = _ok({"item": [{"act_cash_flow_net": 3}]})
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
        with patch("data_provider.hithink_fetcher.requests.get", return_value=_response({"code": 2004, "message": "denied", "data": None})):
            payload = manager._load_cn_fundamental_bundle("600519")
        self.assertEqual(payload["from"], "ak")

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
            side_effect=[_response(search), _response(listing), _response(hot), _response(pool)],
        ) as request:
            self.assertEqual(fetcher.get_stock_name("600519"), "贵州茅台")
            frame = fetcher.get_stock_list()
            hot_rows = fetcher.get_hot_stocks(1)
            limit_rows = fetcher.get_limit_up_pool(date="20241113", n=1)
        self.assertEqual(frame.iloc[0]["code"], "600519")
        self.assertEqual(hot_rows[0]["source"], "HiThink热股榜")
        self.assertEqual(limit_rows[0]["consecutive_boards"], 2)
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
