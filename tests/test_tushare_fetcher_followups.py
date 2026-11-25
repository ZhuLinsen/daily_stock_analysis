# -*- coding: utf-8 -*-
"""Regression tests for post-merge Tushare follow-up fixes."""

import importlib.util
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

try:
    json_repair_available = importlib.util.find_spec("json_repair") is not None
except ValueError:
    json_repair_available = "json_repair" in sys.modules

if not json_repair_available and "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()

from data_provider.tushare_fetcher import TushareFetcher


class TestTushareFetcherFollowUps(unittest.TestCase):
    """Cover rate limiting and cross-day trade-calendar refresh behavior."""

    @staticmethod
    def _make_fetcher() -> TushareFetcher:
        with patch.object(TushareFetcher, "_init_api", return_value=None):
            fetcher = TushareFetcher()
        fetcher._api = MagicMock()
        fetcher.priority = 2
        return fetcher

    def test_get_trade_time_refreshes_trade_calendar_when_day_changes(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.side_effect = [
            pd.DataFrame({"cal_date": ["20260317", "20260314"], "is_open": [1, 1]}),
            pd.DataFrame({"cal_date": ["20260318", "20260317"], "is_open": [1, 1]}),
        ]

        with patch.object(
            fetcher,
            "_get_china_now",
            side_effect=[
                datetime(2026, 3, 17, 20, 0),
                datetime(2026, 3, 17, 20, 0),
                datetime(2026, 3, 18, 20, 0),
                datetime(2026, 3, 18, 20, 0),
            ],
        ), patch.object(fetcher, "_check_rate_limit") as rate_limit_mock:
            self.assertEqual(fetcher.get_trade_time(early_time="00:00", late_time="19:00"), "20260317")
            self.assertEqual(fetcher.get_trade_time(early_time="00:00", late_time="19:00"), "20260318")

        self.assertEqual(fetcher._api.trade_cal.call_count, 2)
        self.assertEqual(rate_limit_mock.call_count, 2)
    def test_get_trade_time_returns_latest_trade_date_on_non_trade_day(self) -> None:
        """Non-trade day (e.g. Saturday) should return the most recent trade
        date (Friday), not the one before it (Thursday).  Fixes #1009."""
        fetcher = self._make_fetcher()
        # 2026-03-21 is Saturday; Friday 20 and Thursday 19 are trade dates
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {
                "cal_date": ["20260314", "20260315", "20260316",
                             "20260317", "20260318", "20260319",
                             "20260320", "20260321"],
                "is_open": [0, 0, 1, 1, 1, 1, 1, 0],
            }
        )

        with patch.object(
            fetcher,
            "_get_china_now",
            # called twice: once by get_trade_time, once by _get_trade_dates
            side_effect=[datetime(2026, 3, 21, 10, 0)] * 2,
        ), patch.object(fetcher, "_check_rate_limit"):
            result = fetcher.get_trade_time(early_time="00:00", late_time="19:00")

        # Should be Friday (20th), NOT Thursday (19th)
        self.assertEqual(result, "20260320")

    def test_get_trade_time_trade_day_before_data_ready_returns_previous(self) -> None:
        """On a trade day within the early-late window, should return the
        previous trade date (data not ready yet for today)."""
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {
                "cal_date": ["20260319", "20260320"],
                "is_open": [1, 1],
            }
        )

        with patch.object(
            fetcher,
            "_get_china_now",
            # Friday 10:00 AM - within 00:00~19:00 window, data not ready
            side_effect=[datetime(2026, 3, 20, 10, 0)] * 2,
        ), patch.object(fetcher, "_check_rate_limit"):
            result = fetcher.get_trade_time(early_time="00:00", late_time="19:00")

        # Data not ready, should fall back to Thursday (19th)
        self.assertEqual(result, "20260319")
        
          
    def test_get_sector_rankings_rate_limits_calendar_and_rankings_api(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {"cal_date": ["20260317", "20260314"], "is_open": [1, 1]}
        )
        fetcher._api.moneyflow_ind_ths.return_value = pd.DataFrame(
            {
                "industry": ["AI", "消费"],
                "pct_change": [1.8, -0.6],
            }
        )

        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 16, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ) as rate_limit_mock:
            top, bottom = fetcher.get_sector_rankings(n=1)

        self.assertEqual(top, [{"name": "AI", "change_pct": 1.8}])
        self.assertEqual(bottom, [{"name": "消费", "change_pct": -0.6}])
        self.assertEqual(rate_limit_mock.call_count, 2)

    def test_get_chip_distribution_rate_limits_all_tushare_calls(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {"cal_date": ["20260317", "20260314"], "is_open": [1, 1]}
        )
        fetcher._api.cyq_chips.return_value = pd.DataFrame(
            {
                "price": [9.0, 10.0, 11.0],
                "percent": [20.0, 50.0, 30.0],
            }
        )
        fetcher._api.daily.return_value = pd.DataFrame({"close": [10.5]})

        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ) as rate_limit_mock:
            chip = fetcher.get_chip_distribution("600519")

        self.assertIsNotNone(chip)
        if chip is None:
            self.fail("expected chip distribution data")
        self.assertEqual(chip.date, "2026-03-17")
        self.assertAlmostEqual(chip.profit_ratio, 0.7)
        self.assertAlmostEqual(chip.avg_cost, 10.1)
        self.assertAlmostEqual(chip.concentration_90, 0.1)
        self.assertAlmostEqual(chip.concentration_70, 0.1)
        self.assertEqual(rate_limit_mock.call_count, 3)

    def test_convert_stock_code_accepts_exchange_prefixed_a_share(self) -> None:
        fetcher = self._make_fetcher()

        self.assertEqual(fetcher._convert_stock_code("SZ000001"), "000001.SZ")
        self.assertEqual(fetcher._convert_stock_code("SH600519"), "600519.SH")
        self.assertEqual(fetcher._convert_stock_code("605218"), "605218.SH")
        self.assertEqual(fetcher._convert_stock_code("600519.SS"), "600519.SH")

    @patch.dict(sys.modules, {"tushare": MagicMock()})
    def test_legacy_realtime_quote_keeps_sz_hint_as_stock_symbol(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.quotation.side_effect = Exception("quota")

        tushare_module = sys.modules["tushare"]
        tushare_module.get_realtime_quotes.return_value = pd.DataFrame(
            [
                {
                    "name": "平安银行",
                    "price": "10.94",
                    "pre_close": "10.88",
                    "volume": "1000",
                    "amount": "2000",
                    "high": "11.00",
                    "low": "10.80",
                    "open": "10.90",
                }
            ]
        )

        quote = fetcher.get_realtime_quote("SZ000001")

        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, "000001")
        self.assertEqual(quote.name, "平安银行")
        tushare_module.get_realtime_quotes.assert_called_once_with("000001")

    @patch.dict(sys.modules, {"tushare": MagicMock()})
    def test_legacy_realtime_quote_handles_missing_volume_without_crashing(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.quotation.side_effect = Exception("quota")

        tushare_module = sys.modules["tushare"]
        tushare_module.get_realtime_quotes.return_value = pd.DataFrame(
            [
                {
                    "name": float("nan"),
                    "price": "10.94",
                    "pre_close": "10.88",
                    "volume": "-",
                    "amount": None,
                    "high": "11.00",
                    "low": "10.80",
                    "open": "10.90",
                }
            ]
        )

        quote = fetcher.get_realtime_quote("000001")

        self.assertIsNotNone(quote)
        if quote is None:
            self.fail("expected legacy quote")
        self.assertIsNone(quote.volume)
        self.assertIsNone(quote.amount)
        self.assertEqual(quote.name, "")

    def test_get_main_indices_uses_20_day_window_latest_row_and_nullable_amount(self) -> None:
        fetcher = self._make_fetcher()

        def index_daily_side_effect(*, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
            self.assertEqual(start_date, "20260918")
            self.assertEqual(end_date, "20261008")
            if ts_code != "000001.SH":
                return pd.DataFrame()
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20260929",
                        "close": 3100.0,
                        "pre_close": 3080.0,
                        "change": 20.0,
                        "pct_chg": 0.65,
                        "open": 3085.0,
                        "high": 3110.0,
                        "low": 3080.0,
                        "vol": 100.0,
                        "amount": 50.0,
                    },
                    {
                        "trade_date": "20260930",
                        "close": 3336.5,
                        "pre_close": 3100.0,
                        "change": 236.5,
                        "pct_chg": 7.63,
                        "open": 3200.0,
                        "high": 3350.0,
                        "low": 3190.0,
                        "vol": 200.0,
                        "amount": None,
                    },
                ]
            )

        fetcher._api.index_daily.side_effect = index_daily_side_effect

        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 10, 8, 10, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            indices = fetcher.get_main_indices("cn")

        self.assertIsNotNone(indices)
        if indices is None:
            self.fail("expected index results")
        self.assertEqual(len(indices), 1)
        self.assertEqual(indices[0]["code"], "000001")
        self.assertEqual(indices[0]["current"], 3336.5)
        self.assertEqual(indices[0]["amount"], 0.0)

    def test_get_market_stats_handles_empty_daily_missing_basic_and_nan_names(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {"cal_date": ["20260317", "20260316"], "is_open": [1, 1]}
        )

        # Case 1: empty daily returns None without querying stock_basic
        fetcher._api.daily.return_value = pd.DataFrame()
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_market_stats())
        self.assertEqual(fetcher._api.stock_basic.call_count, 0)

        # Case 2: genuinely suspended rows (amount == 0 or blank price with missing amount) are skipped while valid rows count
        fetcher._api.daily.return_value = pd.DataFrame(
            [
                {"ts_code": "600519.SH", "close": 1520.0, "pre_close": 1500.0, "amount": 1000.0},
                {"ts_code": "300750.SZ", "close": "", "pre_close": "-", "amount": 0.0},
                {"ts_code": "000002.SZ", "close": "", "pre_close": "", "amount": None},
                {"ts_code": "000001.SZ", "close": 9.9, "pre_close": 11.0, "amount": 500.0},
            ]
        )
        fetcher._api.stock_basic.return_value = pd.DataFrame(
            [
                {"ts_code": "600519.SH", "name": "贵州茅台"},
                {"ts_code": "000001.SZ", "name": "平安银行"},
                {"ts_code": "000002.SZ", "name": "万科A"},
                {"ts_code": "300750.SZ", "name": "宁德时代"},
            ]
        )
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            stats = fetcher.get_market_stats()

        self.assertIsNotNone(stats)
        if stats is None:
            self.fail("expected market stats")
        self.assertEqual(stats["up_count"], 1)
        self.assertEqual(stats["down_count"], 1)
        self.assertEqual(stats["limit_down_count"], 1)
        self.assertAlmostEqual(stats["total_amount"], 1500.0 * 1000 / 1e8)

        # Case 2b: active traded stock (amount > 0) missing from partial stock_basic must fail closed (OR-COR-63ba8fc3)
        fetcher._api.daily.return_value = pd.DataFrame(
            [
                {"ts_code": "600519.SH", "close": 1520.0, "pre_close": 1500.0, "amount": 1000.0},
                {"ts_code": "000002.SZ", "close": 9.0, "pre_close": 10.0, "amount": 200.0},
            ]
        )
        fetcher._api.stock_basic.return_value = pd.DataFrame(
            [{"ts_code": "600519.SH", "name": "贵州茅台"}]
        )
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_market_stats())

        # Case 2c: mixed batch containing active stock with corrupt close ('--') must fail closed (OR-COR-81bff490)
        fetcher._api.daily.return_value = pd.DataFrame(
            [
                {"ts_code": "600519.SH", "close": 1520.0, "pre_close": 1500.0, "amount": 1000.0},
                {"ts_code": "300750.SZ", "close": "--", "pre_close": 200.0, "amount": 500.0},
            ]
        )
        fetcher._api.stock_basic.return_value = pd.DataFrame(
            [
                {"ts_code": "600519.SH", "name": "贵州茅台"},
                {"ts_code": "300750.SZ", "name": "宁德时代"},
            ]
        )
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_market_stats())

        # Case 3: empty stock_basic must fail open (return None) so backup source runs (OR-COR-63ba8fc3)
        fetcher._api.stock_basic.return_value = pd.DataFrame()
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_market_stats())

        # Case 4: all invalid prices with non-empty amount must return None (OR-COR-81bff490)
        fetcher._api.daily.return_value = pd.DataFrame(
            [{"ts_code": "300750.SZ", "close": "", "pre_close": "--", "amount": 500.0}]
        )
        fetcher._api.stock_basic.return_value = pd.DataFrame(
            [{"ts_code": "300750.SZ", "name": "宁德时代"}]
        )
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_market_stats())

        # Case 5: missing/all-NaN amount column must return None
        fetcher._api.daily.return_value = pd.DataFrame(
            [{"ts_code": "600519.SH", "close": 1520.0, "pre_close": 1500.0}]
        )
        fetcher._api.stock_basic.return_value = pd.DataFrame(
            [{"ts_code": "600519.SH", "name": "贵州茅台"}]
        )
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_market_stats())

    def test_get_sector_rankings_falls_back_when_ths_empty_and_returns_none_when_dc_filtered_empty(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {"cal_date": ["20260317", "20260316"], "is_open": [1, 1]}
        )

        # THS returns only invalid NaN pct_change -> must fall back to EastMoney dc
        fetcher._api.moneyflow_ind_ths.return_value = pd.DataFrame(
            {"industry": ["AI"], "pct_change": [None]}
        )
        fetcher._api.moneyflow_ind_dc.return_value = pd.DataFrame(
            {
                "content_type": ["行业", "概念"],
                "name": ["半导体", "忽略概念"],
                "pct_change": [2.4, 9.9],
            }
        )
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 16, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            ranked = fetcher.get_sector_rankings(n=1)

        self.assertEqual(
            ranked,
            ([{"name": "半导体", "change_pct": 2.4}], [{"name": "半导体", "change_pct": 2.4}]),
        )

        # If dc also has zero matching industry rows, return None instead of ([], [])
        fetcher._api.moneyflow_ind_dc.return_value = pd.DataFrame(
            {"content_type": ["概念"], "name": ["忽略概念"], "pct_change": [5.0]}
        )
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 16, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_sector_rankings(n=1))

    def test_get_chip_distribution_parses_hyphen_date_and_rejects_zero_percent_or_nan_close(self) -> None:
        fetcher = self._make_fetcher()
        fetcher._api.cyq_chips.return_value = pd.DataFrame(
            {"price": [9.0, 10.0, 11.0], "percent": [20.0, 50.0, 30.0]}
        )
        fetcher._api.daily.return_value = pd.DataFrame({"close": [10.5]})

        with patch.object(fetcher, "get_trade_time", return_value="2026-03-17"), patch.object(
            fetcher, "_check_rate_limit"
        ):
            chip = fetcher.get_chip_distribution("600519")

        self.assertIsNotNone(chip)
        if chip is None:
            self.fail("expected chip distribution")
        self.assertEqual(chip.date, "2026-03-17")

        # Zero-sum percent must not produce NaN chip
        fetcher._api.cyq_chips.return_value = pd.DataFrame({"price": [10.0], "percent": [0.0]})
        with patch.object(fetcher, "get_trade_time", return_value="20260317"), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_chip_distribution("600519"))

        # Partial missing price rows must not renormalize subset to 100% (OR-COR-4bf61805)
        fetcher._api.cyq_chips.return_value = pd.DataFrame(
            {"price": [10.0, None], "percent": [5.0, 95.0]}
        )
        fetcher._api.daily.return_value = pd.DataFrame({"close": [10.5]})
        with patch.object(fetcher, "get_trade_time", return_value="20260317"), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_chip_distribution("600519"))

    @patch.dict(sys.modules, {"tushare": MagicMock()})
    def test_legacy_realtime_quote_returns_none_when_pre_close_missing(self) -> None:
        """OR-COR-47bae37a / OR-COR-d82ff870: do not fabricate 0% change when pre_close is missing."""
        fetcher = self._make_fetcher()
        fetcher._api.quotation.side_effect = Exception("quota")

        tushare_module = sys.modules["tushare"]
        tushare_module.get_realtime_quotes.return_value = pd.DataFrame(
            [
                {
                    "name": "平安银行",
                    "price": "10.94",
                    "pre_close": "-",
                    "volume": "-",
                    "amount": None,
                    "high": "11.00",
                    "low": "10.80",
                    "open": "10.90",
                }
            ]
        )

        self.assertIsNone(fetcher.get_realtime_quote("000001"))

    def test_get_main_indices_skips_missing_close_and_stale_trade_date(self) -> None:
        """OR-COR-a6351083 / OR-COR-1b635117 / OR-COR-65e18b64."""
        fetcher = self._make_fetcher()

        # Case 1: missing close column must return None instead of 0.0
        def missing_close_side_effect(*, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
            if ts_code != "000001.SH":
                return pd.DataFrame()
            return pd.DataFrame([{"trade_date": "20261125", "pre_close": 3000.0}])

        fetcher._api.index_daily.side_effect = missing_close_side_effect
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 11, 25, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_main_indices("cn"))

        # Case 2: stale trade_date (20261113 on 2026-11-25 20:00) must not mask fresher backup sources
        def stale_side_effect(*, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
            if ts_code != "000001.SH":
                return pd.DataFrame()
            return pd.DataFrame(
                [{"trade_date": "20261113", "close": 3100.0, "pre_close": 3080.0, "pct_chg": 0.65}]
            )

        fetcher._api.index_daily.side_effect = stale_side_effect
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 11, 25, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_main_indices("cn"))

    def test_get_main_indices_rejects_missing_pct_chg_and_survives_calendar_out_of_range(self) -> None:
        """OR-COR-12caffd3 & OR-COR-202c5b45: missing pct_chg triggers fallback; out-of-range calendar keeps valid Dec 31 close."""
        # Case 1 (OR-COR-12caffd3): missing pct_chg must not fabricate 0.0%
        fetcher = self._make_fetcher()

        def missing_pct_chg_side_effect(*, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
            if ts_code != "000001.SH":
                return pd.DataFrame()
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20261125",
                        "close": 3100.0,
                        "pre_close": 3000.0,
                        "change": 100.0,
                    }
                ]
            )

        fetcher._api.index_daily.side_effect = missing_pct_chg_side_effect
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 11, 25, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_main_indices("cn"))

        # Explicit 0.0 pct_chg IS preserved on a flat day
        fetcher._api.index_daily.side_effect = lambda **kw: (
            pd.DataFrame(
                [
                    {
                        "trade_date": "20261125",
                        "close": 3000.0,
                        "pre_close": 3000.0,
                        "change": 0.0,
                        "pct_chg": 0.0,
                    }
                ]
            )
            if kw["ts_code"] == "000001.SH"
            else pd.DataFrame()
        )
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 11, 25, 20, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            flat_indices = fetcher.get_main_indices("cn")
        self.assertIsNotNone(flat_indices)
        self.assertEqual(flat_indices[0]["change_pct"], 0.0)

        # Case 2 (OR-COR-202c5b45): on 2027-01-02 (outside exchange-calendars 4.13.2 range) with empty trade_cal, keep 2026-12-31 bar
        fetcher._api.trade_cal.return_value = pd.DataFrame()
        fetcher._api.index_daily.side_effect = lambda **kw: (
            pd.DataFrame(
                [
                    {
                        "trade_date": "20261231",
                        "close": 3100.0,
                        "pre_close": 3080.0,
                        "change": 20.0,
                        "pct_chg": 0.65,
                    }
                ]
            )
            if kw["ts_code"] == "000001.SH"
            else pd.DataFrame()
        )
        with patch.object(fetcher, "_get_china_now", return_value=datetime(2027, 1, 2, 16, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            out_of_range_indices = fetcher.get_main_indices("cn")

        self.assertIsNotNone(out_of_range_indices)
        self.assertEqual(len(out_of_range_indices), 1)
        self.assertEqual(out_of_range_indices[0]["current"], 3100.0)
        self.assertEqual(out_of_range_indices[0]["change_pct"], 0.65)

    def test_get_sector_rankings_returns_none_when_eastmoney_dc_lacks_content_type(self) -> None:
        """OR-COR-943237f1 / OR-COR-7566034b: refuse mixed boards if content_type column is absent."""
        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {"cal_date": ["20260317", "20260316"], "is_open": [1, 1]}
        )
        fetcher._api.moneyflow_ind_ths.return_value = pd.DataFrame()
        fetcher._api.moneyflow_ind_dc.return_value = pd.DataFrame(
            {"name": ["AI概念", "半导体"], "pct_change": [9.9, 2.4]}
        )

        with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 16, 0)), patch.object(
            fetcher, "_check_rate_limit"
        ):
            self.assertIsNone(fetcher.get_sector_rankings(n=1))

    def test_get_market_stats_fails_closed_on_missing_or_nonfinite_amount_and_falls_back(self) -> None:
        """OR-COR-91ef0fcb: active rows with missing/unparseable/non-finite amount must return None so backup runs."""
        from data_provider.base import BaseFetcher, DataFetcherManager

        fetcher = self._make_fetcher()
        fetcher._api.trade_cal.return_value = pd.DataFrame(
            {"cal_date": ["20260317", "20260316"], "is_open": [1, 1]}
        )
        fetcher._api.stock_basic.return_value = pd.DataFrame(
            [
                {"ts_code": "600519.SH", "name": "贵州茅台"},
                {"ts_code": "000001.SZ", "name": "平安银行"},
                {"ts_code": "300750.SZ", "name": "宁德时代"},
            ]
        )

        corrupt_active_amounts = [
            None,
            float("nan"),
            "--",
            "bad",
            float("inf"),
            float("-inf"),
            "inf",
            "-inf",
            -10.0,
        ]
        for bad_amount in corrupt_active_amounts:
            with self.subTest(bad_amount=bad_amount):
                fetcher._api.daily.return_value = pd.DataFrame(
                    [
                        {"ts_code": "600519.SH", "close": 1520.0, "pre_close": 1500.0, "amount": 1000.0},
                        {"ts_code": "000001.SZ", "close": 9.9, "pre_close": 11.0, "amount": bad_amount},
                    ]
                )
                with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)), patch.object(
                    fetcher, "_check_rate_limit"
                ):
                    self.assertIsNone(fetcher.get_market_stats())

                # Realtime (_calc_market_stats direct) path must also reject the same corrupt values.
                rt_df = pd.DataFrame(
                    [
                        {"ts_code": "600519.SH", "name": "贵州茅台", "close": 1520.0, "pre_close": 1500.0, "amount": 1e6},
                        {"ts_code": "000001.SZ", "name": "平安银行", "close": 9.9, "pre_close": 11.0, "amount": bad_amount},
                    ]
                )
                self.assertIsNone(fetcher._calc_market_stats(rt_df))

        # Non-finite or corrupt amount even on a blank-price row must fail closed.
        for bad_suspended_amount in (float("inf"), float("-inf"), "inf", "-inf", "--"):
            with self.subTest(bad_suspended_amount=bad_suspended_amount):
                fetcher._api.daily.return_value = pd.DataFrame(
                    [
                        {"ts_code": "600519.SH", "close": 1520.0, "pre_close": 1500.0, "amount": 1000.0},
                        {"ts_code": "300750.SZ", "close": "", "pre_close": "-", "amount": bad_suspended_amount},
                    ]
                )
                with patch.object(fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)), patch.object(
                    fetcher, "_check_rate_limit"
                ):
                    self.assertIsNone(fetcher.get_market_stats())

        # DataFetcherManager must fall back to a complete backup source when Tushare fails closed.
        class _BackupMarketStatsFetcher(BaseFetcher):
            name = "BackupFetcher"
            priority = 3

            def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
                return pd.DataFrame()

            def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
                return df

            def get_market_stats(self, *, allow_cache: bool = True):
                return {
                    "up_count": 3000,
                    "down_count": 2000,
                    "flat_count": 100,
                    "limit_up_count": 50,
                    "limit_down_count": 10,
                    "total_amount": 9500.5,
                }

        fetcher._api.daily.return_value = pd.DataFrame(
            [
                {"ts_code": "600519.SH", "close": 1520.0, "pre_close": 1500.0, "amount": 1000.0},
                {"ts_code": "000001.SZ", "close": 9.9, "pre_close": 11.0, "amount": None},
            ]
        )
        manager = DataFetcherManager(fetchers=[fetcher, _BackupMarketStatsFetcher()])
        with patch.object(manager, "_get_tickflow_fetcher", return_value=None), patch.object(
            fetcher, "_get_china_now", return_value=datetime(2026, 3, 17, 20, 0)
        ), patch.object(fetcher, "_check_rate_limit"):
            resolved = manager.get_market_stats(include_provider=True)

        self.assertEqual(resolved.get("provider"), "BackupFetcher")
        self.assertEqual(resolved.get("up_count"), 3000)
        self.assertAlmostEqual(resolved.get("total_amount"), 9500.5)
