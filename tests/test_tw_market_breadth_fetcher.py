# -*- coding: utf-8 -*-
"""Offline unit tests for TwMarketBreadthFetcher (台股市场宽度 data-layer fetcher).

Fixtures are trimmed from the TWSE MI_INDEX (每日收盤行情) / TPEx OpenAPI
response shape. No network is touched — the parser is pinned to the actual
field layout (column names), date formats and units so a rename/reorder fails
open instead of silently shipping misaligned counts.
"""

import os
import sys
import copy
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.tw_market_breadth_fetcher import (  # noqa: E402
    TwMarketBreadthFetcher,
    _compute_breadth,
    _to_float,
)
from data_provider.base import DataFetcherManager  # noqa: E402

# --- TWSE MI_INDEX fixture: NEW format returns `tables` (not data/fields). The
#     per-stock close lives in the table titled 「每日收盤行情」; 漲跌(+/-) is an
#     HTML sign and 漲跌價差 is the UNSIGNED magnitude (sign in the separate column).
TWSE_MI_INDEX_FIXTURE = {
    "stat": "OK",
    "date": "20260813",
    "tables": [
        {
            "title": "115年08月13日 每日收盤行情(全部(不含權證、牛熊證、可展延牛熊證))",
            "fields": [
                "證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額",
                "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差",
                "最後揭示買價", "最後揭示買量", "最後揭示賣價", "最後揭示賣量", "本益比",
            ],
            "data": [
                # 2330 台積電：收盤 110、昨收 100 -> +10% 漲停
                ["2330", "台積電", "30,000,000", "120,000", "3,300,000,000",
                 "105.00", "110.00", "104.00", "110.00", "<p style='color:red'>+</p>", "10.00",
                 "110.00", "100", "110.50", "50", "0.00"],
                # 2317 鴻海：收盤 90、昨收 100 -> -10% 跌停
                ["2317", "鴻海", "20,000,000", "80,000", "1,800,000,000",
                 "95.00", "96.00", "90.00", "90.00", "<p style='color:green'>-</p>", "10.00",
                 "90.00", "80", "90.50", "40", "0.00"],
                # 2454 聯發科：收盤 102、昨收 100 -> +2% 上漲
                ["2454", "聯發科", "10,000,000", "50,000", "1,020,000,000",
                 "100.00", "103.00", "100.00", "102.00", "<p style='color:red'>+</p>", "2.00",
                 "102.00", "50", "102.50", "20", "0.00"],
                # 2881 富邦金：收盤 100、昨收 100 -> 0% 平盤（sign 为空）
                ["2881", "富邦金", "5,000,000", "20,000", "500,000,000",
                 "100.00", "100.50", "99.50", "100.00", "", "0.00",
                 "100.00", "20", "100.50", "10", "0.00"],
            ],
        },
    ],
}

# --- TPEx OpenAPI per-stock close fixture (verified live 2026-08-13: keys are
#     Close/Change/TransactionAmount, Date is 民國 YYYMMDD, Change is a signed
#     price difference NOT a percentage). ---
TPEX_FIXTURE = [
    {
        "Date": "1150813",
        "SecuritiesCompanyCode": "3105",
        "Close": "112.00",
        "Change": "+12.00",
        "TransactionAmount": "800000000",
    },
    {
        "Date": "1150813",
        "SecuritiesCompanyCode": "5347",
        "Close": "88.00",
        "Change": "-12.00",
        "TransactionAmount": "400000000",
    },
]


# --- TWSE 產業分類指數 fixture (OpenAPI MI_INDEX: 指數 + 漲跌百分比, list of dicts).
#     Industry indices end in 「類指數」; leverage/inverse/thematic are filtered out.
TWSE_SECTOR_FIXTURE = [
    {"指數": "水泥類指數", "漲跌百分比": "-0.50"},
    {"指數": "電子工業類指數", "漲跌百分比": "+1.01"},
    {"指數": "半導體類指數", "漲跌百分比": "+3.09"},
    {"指數": "金融保險類指數", "漲跌百分比": "+0.50"},
    {"指數": "塑膠類指數", "漲跌百分比": "-0.99"},
    {"指數": "航運類指數", "漲跌百分比": "-2.91"},
    # 非產業分類，应被过滤
    {"指數": "發行量加權股價指數", "漲跌百分比": "+1.11"},
    {"指數": "電子類兩倍槓桿指數", "漲跌百分比": "+2.00"},
]


def _resp(json_data):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def _fetcher():
    # min_request_interval=0 disables the throttle sleep in tests.
    return TwMarketBreadthFetcher(min_request_interval=0)


class TestPureHelpers(unittest.TestCase):
    def test_to_float_parses_signed_and_comma_grouped(self):
        self.assertEqual(_to_float("+10.00"), 10.0)
        self.assertEqual(_to_float("-10.00"), -10.0)
        self.assertEqual(_to_float("0.00"), 0.0)
        self.assertEqual(_to_float("3,300,000,000"), 3300000000.0)
        for blank in ("", "--", "-", "—", None, "n/a"):
            self.assertIsNone(_to_float(blank), blank)

    def test_compute_breadth_counts_up_down_flat_and_limits(self):
        records = [
            {"change_pct": 10.0, "amount": 100.0},   # 涨停
            {"change_pct": -10.0, "amount": 200.0},  # 跌停
            {"change_pct": 2.0, "amount": 300.0},    # 上涨
            {"change_pct": 0.0, "amount": 400.0},    # 平盘
        ]
        stats = _compute_breadth(records)

        self.assertEqual(stats["up_count"], 2)
        self.assertEqual(stats["down_count"], 1)
        self.assertEqual(stats["flat_count"], 1)
        self.assertEqual(stats["limit_up_count"], 1)
        self.assertEqual(stats["limit_down_count"], 1)
        self.assertEqual(stats["total_amount"], 1000.0)


class TestTwseBreadthParsing(unittest.TestCase):
    def test_twse_mi_index_width(self):
        with patch(
            "data_provider.tw_market_breadth_fetcher.requests.get",
            side_effect=[_resp(TWSE_MI_INDEX_FIXTURE), _resp([])],
        ):
            stats = _fetcher().get_market_stats()

        self.assertIsNotNone(stats)
        self.assertEqual(stats["up_count"], 2)        # +10% 涨停 / +2% 上涨
        self.assertEqual(stats["down_count"], 1)      # -10% 跌停
        self.assertEqual(stats["flat_count"], 1)      # 0% 平盘
        self.assertEqual(stats["limit_up_count"], 1)  # 2330 +10%
        self.assertEqual(stats["limit_down_count"], 1)  # 2317 -10%
        # 成交金额 = 3.3B + 1.8B + 1.02B + 0.5B = 6.62B TWD（原始元，不预除 1e8）
        self.assertEqual(stats["total_amount"], 6_620_000_000.0)

    def test_twse_field_rename_fails_open(self):
        bad = copy.deepcopy(TWSE_MI_INDEX_FIXTURE)
        bad["tables"][0]["fields"] = [f.replace("收盤價", "收盘价") for f in bad["tables"][0]["fields"]]
        with patch(
            "data_provider.tw_market_breadth_fetcher.requests.get",
            side_effect=[_resp(bad), _resp([])],
        ):
            self.assertIsNone(_fetcher().get_market_stats())

    def test_twse_missing_field_fails_open(self):
        bad = copy.deepcopy(TWSE_MI_INDEX_FIXTURE)
        bad["tables"][0]["fields"] = [f for f in bad["tables"][0]["fields"] if f != "成交金額"]
        with patch(
            "data_provider.tw_market_breadth_fetcher.requests.get",
            side_effect=[_resp(bad), _resp([])],
        ):
            self.assertIsNone(_fetcher().get_market_stats())


class TestTpexBreadthParsing(unittest.TestCase):
    def test_tpex_close_width(self):
        with patch(
            "data_provider.tw_market_breadth_fetcher.requests.get",
            side_effect=[_resp([]), _resp(TPEX_FIXTURE)],
        ):
            stats = _fetcher().get_market_stats()

        self.assertIsNotNone(stats)
        self.assertEqual(stats["up_count"], 1)        # 3105 +12% 涨停
        self.assertEqual(stats["down_count"], 1)      # 5347 -12% 跌停
        self.assertEqual(stats["limit_up_count"], 1)
        self.assertEqual(stats["limit_down_count"], 1)
        self.assertEqual(stats["total_amount"], 1_200_000_000.0)

    def test_tpex_date_mismatch_skips_tpex(self):
        # TPEx serves latest day only. A specific-date request whose TPEx date
        # (民國 1150812 = 西元 20260812) does not match must skip TPEx, not mix dates.
        tpex_mismatch = [
            {"Date": "1150812", "SecuritiesCompanyCode": "3105",
             "Close": "112.00", "Change": "+12.00", "TransactionAmount": "800000000"},
        ]
        with patch(
            "data_provider.tw_market_breadth_fetcher.requests.get",
            side_effect=[_resp(TWSE_MI_INDEX_FIXTURE), _resp(tpex_mismatch)],
        ):
            stats = _fetcher().get_market_stats(date="20260813")

        self.assertIsNotNone(stats)
        # TWSE only: 2330 +10% 涨停 / 2454 +2% 上涨 = up 2, down 1, flat 1
        self.assertEqual(stats["up_count"], 2)
        self.assertEqual(stats["down_count"], 1)
        self.assertEqual(stats["flat_count"], 1)

    def test_single_market_partial_data_quality(self):
        # TWSE 有数据、TPEx 空 → data_quality=partial（只覆盖单一交易所）
        with patch(
            "data_provider.tw_market_breadth_fetcher.requests.get",
            side_effect=[_resp(TWSE_MI_INDEX_FIXTURE), _resp([])],
        ):
            stats = _fetcher().get_market_stats()
        self.assertEqual(stats["data_quality"], "partial")

    def test_both_markets_ok_data_quality(self):
        with patch(
            "data_provider.tw_market_breadth_fetcher.requests.get",
            side_effect=[_resp(TWSE_MI_INDEX_FIXTURE), _resp(TPEX_FIXTURE)],
        ):
            stats = _fetcher().get_market_stats()
        self.assertEqual(stats["data_quality"], "ok")


class TestSectorRankings(unittest.TestCase):
    def test_sector_rankings_top_bottom(self):
        with patch(
            "data_provider.tw_market_breadth_fetcher.requests.get",
            return_value=_resp(TWSE_SECTOR_FIXTURE),
        ):
            top, bottom = _fetcher().get_sector_rankings(3)

        self.assertEqual([s["name"] for s in top], ["半導體類指數", "電子工業類指數", "金融保險類指數"])
        self.assertEqual([s["name"] for s in bottom], ["航運類指數", "塑膠類指數", "水泥類指數"])
        self.assertEqual(top[0]["change_pct"], 3.09)
        self.assertEqual(bottom[0]["change_pct"], -2.91)
        # 非產業分類指数（發行量加權/兩倍槓桿）被过滤，不出现在结果里
        self.assertNotIn("發行量加權股價指數", [s["name"] for s in top] + [s["name"] for s in bottom])

    def test_sector_rankings_fail_open_returns_empty(self):
        with patch(
            "data_provider.tw_market_breadth_fetcher.requests.get",
            side_effect=RuntimeError("boom"),
        ):
            top, bottom = _fetcher().get_sector_rankings(3)
        self.assertEqual(top, [])
        self.assertEqual(bottom, [])


class TestRoutingToTwBreadth(unittest.TestCase):
    def test_get_market_stats_tw_routes_to_tw_breadth(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = []
        mock_fetcher = MagicMock()
        mock_fetcher.get_market_stats.return_value = {
            "up_count": 100, "down_count": 50, "flat_count": 10,
            "limit_up_count": 5, "limit_down_count": 3, "total_amount": 123.0,
        }
        with patch(
            "data_provider.tw_market_breadth_fetcher.TwMarketBreadthFetcher",
            return_value=mock_fetcher,
        ):
            result = DataFetcherManager.get_market_stats(manager, market="tw")

        self.assertEqual(result["up_count"], 100)
        mock_fetcher.get_market_stats.assert_called_once()

    def test_get_sector_rankings_tw_routes_to_tw_breadth(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = []
        mock_fetcher = MagicMock()
        mock_fetcher.get_sector_rankings.return_value = (
            [{"name": "電子類", "change_pct": 1.0}],
            [{"name": "航運類", "change_pct": -2.0}],
        )
        with patch(
            "data_provider.tw_market_breadth_fetcher.TwMarketBreadthFetcher",
            return_value=mock_fetcher,
        ):
            top, bottom = DataFetcherManager.get_sector_rankings(manager, 5, market="tw")

        self.assertEqual(top[0]["name"], "電子類")
        self.assertEqual(bottom[0]["name"], "航運類")
        mock_fetcher.get_sector_rankings.assert_called_once_with(5)


class TestFailOpen(unittest.TestCase):
    def test_network_error_returns_none(self):
        with patch(
            "data_provider.tw_market_breadth_fetcher.requests.get",
            side_effect=RuntimeError("boom"),
        ):
            self.assertIsNone(_fetcher().get_market_stats())

    def test_empty_response_returns_none(self):
        with patch(
            "data_provider.tw_market_breadth_fetcher.requests.get",
            side_effect=[
                _resp({"stat": "OK", "date": "20260306", "fields": [], "data": []}),
                _resp([]),
            ],
        ):
            self.assertIsNone(_fetcher().get_market_stats())


if __name__ == "__main__":
    unittest.main()
