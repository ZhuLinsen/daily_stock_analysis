# -*- coding: utf-8 -*-
"""
Offline tests for YfinanceFundamentalAdapter.

The adapter is fail-open; these tests confirm the bundle shape under realistic
mocked yfinance responses (typical AAPL / 9988.HK style payloads) and the
graceful degradation when yfinance is unavailable.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

import pandas as pd

from data_provider.yfinance_fundamental_adapter import (
    YfinanceFundamentalAdapter,
    _convert_to_yf_symbol,
)


def _build_mock_ticker(
    info: dict,
    income_stmt: pd.DataFrame | None = None,
    cashflow: pd.DataFrame | None = None,
    dividends: pd.Series | None = None,
) -> MagicMock:
    ticker = MagicMock()
    ticker.get_info.return_value = info
    ticker.info = info
    ticker.quarterly_income_stmt = income_stmt if income_stmt is not None else pd.DataFrame()
    ticker.quarterly_cashflow = cashflow if cashflow is not None else pd.DataFrame()
    ticker.dividends = dividends if dividends is not None else pd.Series(dtype="float64")
    return ticker


class TestYfinanceSymbolConversion(unittest.TestCase):
    def test_us_passthrough(self) -> None:
        self.assertEqual(_convert_to_yf_symbol("AAPL"), "AAPL")
        self.assertEqual(_convert_to_yf_symbol(" tsla "), "TSLA")

    def test_hk_prefix_strip(self) -> None:
        self.assertEqual(_convert_to_yf_symbol("HK09988"), "9988.HK")
        self.assertEqual(_convert_to_yf_symbol("HK00700"), "0700.HK")

    def test_already_suffixed(self) -> None:
        self.assertEqual(_convert_to_yf_symbol("0700.HK"), "0700.HK")
        self.assertEqual(_convert_to_yf_symbol("600519.SS"), "600519.SS")

    def test_empty(self) -> None:
        self.assertEqual(_convert_to_yf_symbol(""), "")


class TestYfinanceFundamentalAdapter(unittest.TestCase):
    def test_populates_growth_earnings_dividend_boards_for_us_stock(self) -> None:
        info = {
            "financialCurrency": "USD",
            "currency": "USD",
            "currentPrice": 210.0,
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "totalRevenue": 451442016256,
            "operatingCashflow": 140222005248,
            "returnOnEquity": 1.4147,
            "revenueGrowth": 0.166,
            "earningsGrowth": 0.193,
            "grossMargins": 0.479,
            "profitMargins": 0.272,
            "trailingAnnualDividendRate": 1.04,
            "dividendYield": 0.36,
        }
        income_df = pd.DataFrame(
            {
                pd.Timestamp("2026-03-31"): {"Total Revenue": 1.11e11, "Net Income": 2.95e10},
                pd.Timestamp("2025-12-31"): {"Total Revenue": 1.24e11, "Net Income": 3.62e10},
                pd.Timestamp("2025-09-30"): {"Total Revenue": 9.49e10, "Net Income": 2.49e10},
                pd.Timestamp("2025-06-30"): {"Total Revenue": 9.40e10, "Net Income": 2.34e10},
            }
        )
        # Need at least 5 columns to trigger statement-derived YoY.
        income_df_with_yoy = pd.DataFrame(
            {
                pd.Timestamp("2026-03-31"): {"Total Revenue": 1.11e11, "Net Income": 2.95e10},
                pd.Timestamp("2025-12-31"): {"Total Revenue": 1.24e11, "Net Income": 3.62e10},
                pd.Timestamp("2025-09-30"): {"Total Revenue": 9.49e10, "Net Income": 2.49e10},
                pd.Timestamp("2025-06-30"): {"Total Revenue": 9.40e10, "Net Income": 2.34e10},
                pd.Timestamp("2025-03-31"): {"Total Revenue": 9.52e10, "Net Income": 2.47e10},
            }
        )
        cashflow_df = pd.DataFrame(
            {
                pd.Timestamp("2026-03-31"): {"Operating Cash Flow": 2.87e10},
                pd.Timestamp("2025-12-31"): {"Operating Cash Flow": 3.5e10},
            }
        )
        dividends = pd.Series(
            [0.26, 0.26, 0.26, 0.27],
            index=pd.DatetimeIndex(
                ["2025-08-11", "2025-11-10", "2026-02-09", "2026-05-11"],
                tz="America/New_York",
            ),
            name="Dividends",
        )
        ticker = _build_mock_ticker(info, income_df_with_yoy, cashflow_df, dividends)

        with patch("yfinance.Ticker", return_value=ticker):
            bundle = YfinanceFundamentalAdapter().get_fundamental_bundle("AAPL")

        self.assertEqual(bundle["status"], "partial")
        growth = bundle["growth"]
        # Statement-derived YoY uses iloc[4] (2025-03-31). (1.11e11 - 9.52e10) / 9.52e10 ≈ 16.6%
        self.assertAlmostEqual(growth["revenue_yoy"], 16.5966, places=2)
        self.assertAlmostEqual(growth["roe"], 141.47, places=1)
        self.assertAlmostEqual(growth["gross_margin"], 47.9, places=1)

        fr = bundle["earnings"]["financial_report"]
        self.assertEqual(fr["report_date"], "2026-03-31")
        self.assertEqual(fr["revenue"], 1.11e11)
        self.assertEqual(fr["operating_cash_flow"], 2.87e10)
        self.assertEqual(fr["currency"], "USD")

        div = bundle["earnings"]["dividend"]
        self.assertEqual(div["ttm_event_count"], 4)
        self.assertAlmostEqual(div["ttm_cash_dividend_per_share"], 1.05, places=2)
        # Yield is recomputed: ttm_cash (1.05) / currentPrice (210) * 100 = 0.5%.
        # info.dividendYield (0.36) is intentionally ignored when TTM cash exists.
        self.assertAlmostEqual(div["ttm_dividend_yield_pct"], 0.5, places=2)
        self.assertEqual(div["currency"], "USD")
        self.assertEqual(div["events"][0]["ex_dividend_date"], "2026-05-11")

        self.assertEqual(
            bundle["belong_boards"],
            [
                {"name": "Technology", "type": "行业"},
                {"name": "Consumer Electronics", "type": "概念"},
            ],
        )

    def test_dividends_parsed_from_single_column_dataframe(self) -> None:
        # yfinance 1.2.x returns Ticker.dividends as a single-column DataFrame, not a
        # Series. Without coercion, `.items()` yields (column_name, Series), every event
        # is dropped, and TTM silently falls back to the annual-rate estimate — the real
        # bug seen on live US/HK/JP/KR/TW reports (24.0 / "0 次" instead of the true sum).
        idx = pd.DatetimeIndex(
            ["2025-08-11", "2025-11-10", "2026-02-09", "2026-05-11"],
            tz="America/New_York",
        )
        dividends_df = pd.DataFrame({"Dividends": [0.26, 0.26, 0.26, 0.27]}, index=idx)
        info = {
            "currency": "USD",
            "financialCurrency": "USD",
            "currentPrice": 210,
            "trailingAnnualDividendRate": 99.0,  # a WRONG fallback we must NOT fall back to
        }
        ticker = _build_mock_ticker(info, dividends=dividends_df)
        with patch("yfinance.Ticker", return_value=ticker):
            bundle = YfinanceFundamentalAdapter().get_fundamental_bundle("AAPL")

        div = bundle["earnings"]["dividend"]
        self.assertEqual(div["ttm_event_count"], 4)          # was 0 before the fix
        self.assertEqual(len(div["events"]), 4)
        # summed TTM (0.26*3 + 0.27 = 1.05), NOT the trailingAnnualDividendRate 99.0 fallback
        self.assertAlmostEqual(div["ttm_cash_dividend_per_share"], 1.05, places=2)

    def test_falls_back_to_info_when_statements_only_have_4_quarters(self) -> None:
        """yfinance default is 4 quarters → statement-derived YoY refuses to use QoQ.

        Growth should fall back to ``info.revenueGrowth`` rather than producing
        a misleading QoQ-as-YoY value.
        """
        info = {
            "financialCurrency": "USD",
            "totalRevenue": 1.11e11,
            "operatingCashflow": 2.87e10,
            "revenueGrowth": 0.166,
            "earningsGrowth": 0.193,
            "returnOnEquity": 1.4147,
            "grossMargins": 0.479,
        }
        only_four_quarters = pd.DataFrame(
            {
                pd.Timestamp("2026-03-31"): {"Total Revenue": 1.11e11, "Net Income": 2.95e10},
                pd.Timestamp("2025-12-31"): {"Total Revenue": 1.24e11, "Net Income": 3.62e10},
                pd.Timestamp("2025-09-30"): {"Total Revenue": 9.49e10, "Net Income": 2.49e10},
                pd.Timestamp("2025-06-30"): {"Total Revenue": 9.40e10, "Net Income": 2.34e10},
            }
        )
        ticker = _build_mock_ticker(info, only_four_quarters)

        with patch("yfinance.Ticker", return_value=ticker):
            bundle = YfinanceFundamentalAdapter().get_fundamental_bundle("AAPL")

        growth = bundle["growth"]
        self.assertAlmostEqual(growth["revenue_yoy"], 16.6, places=1)
        self.assertAlmostEqual(growth["net_profit_yoy"], 19.3, places=1)

    def test_hk_stock_splits_financial_vs_dividend_currency(self) -> None:
        """HK ADRs typically report financialCurrency=CNY but pay dividends in HKD."""
        info = {
            "financialCurrency": "CNY",
            "currency": "HKD",
            "currentPrice": 100.0,
            "sector": "Technology",
            "industry": "Internet Retail",
            "totalRevenue": 9.5e11,
            "operatingCashflow": 1.8e11,
            "returnOnEquity": 0.12,
            "revenueGrowth": 0.05,
            "earningsGrowth": 0.08,
            "grossMargins": 0.38,
        }
        dividends = pd.Series(
            [2.0],
            index=pd.DatetimeIndex(["2026-01-15"], tz="Asia/Hong_Kong"),
            name="Dividends",
        )
        ticker = _build_mock_ticker(info, dividends=dividends)

        with patch("yfinance.Ticker", return_value=ticker):
            bundle = YfinanceFundamentalAdapter().get_fundamental_bundle("HK09988")

        fr = bundle["earnings"]["financial_report"]
        self.assertEqual(fr["currency"], "CNY", "financial report must remain in financialCurrency")

        div = bundle["earnings"]["dividend"]
        self.assertEqual(div["currency"], "HKD", "dividends must use trading currency, not financialCurrency")
        # TTM yield computed in HKD: 2.0 / 100.0 * 100 = 2.0%; must NOT be cross-currency mix.
        self.assertAlmostEqual(div["ttm_dividend_yield_pct"], 2.0, places=4)
        self.assertAlmostEqual(div["ttm_cash_dividend_per_share"], 2.0, places=4)

    def test_ttm_yield_falls_back_to_info_when_ttm_cash_absent(self) -> None:
        """If no dividend events and no trailing rate, the only source is
        info.dividendYield — pass through as percent (do NOT multiply by 100)."""
        info = {
            "financialCurrency": "USD",
            "currency": "USD",
            "totalRevenue": 1e10,
            "dividendYield": 1.85,  # Already in % units in current yfinance.
            "trailingAnnualDividendRate": 0.5,  # Drives ttm_cash fallback.
        }
        ticker = _build_mock_ticker(info)

        with patch("yfinance.Ticker", return_value=ticker):
            bundle = YfinanceFundamentalAdapter().get_fundamental_bundle("AAPL")

        div = bundle["earnings"]["dividend"]
        # No latest_price means we cannot recompute, so we fall through.
        # trailingAnnualDividendYield is absent → final fallback is dividendYield as-is.
        self.assertAlmostEqual(div["ttm_dividend_yield_pct"], 1.85, places=4)
        self.assertAlmostEqual(div["ttm_cash_dividend_per_share"], 0.5, places=4)

    def test_ttm_yield_prefers_trailing_annual_dividend_yield_over_info_yield(self) -> None:
        """When no TTM cash + price pair, trailingAnnualDividendYield (decimal)
        beats info.dividendYield (percent) — they aren't redundant copies."""
        info = {
            "currency": "USD",
            "totalRevenue": 1e10,
            "trailingAnnualDividendYield": 0.0123,  # ratio, expect 1.23%
            "dividendYield": 5.0,
            "trailingAnnualDividendRate": 1.0,
        }
        ticker = _build_mock_ticker(info)

        with patch("yfinance.Ticker", return_value=ticker):
            bundle = YfinanceFundamentalAdapter().get_fundamental_bundle("AAPL")

        div = bundle["earnings"]["dividend"]
        self.assertAlmostEqual(div["ttm_dividend_yield_pct"], 1.23, places=2)

    def test_returns_not_supported_when_yfinance_import_fails(self) -> None:
        adapter = YfinanceFundamentalAdapter()
        with patch.dict("sys.modules", {"yfinance": None}):
            bundle = adapter.get_fundamental_bundle("AAPL")
        self.assertEqual(bundle["status"], "not_supported")
        self.assertTrue(any("import_yfinance" in e for e in bundle["errors"]))

    def test_returns_not_supported_when_info_empty(self) -> None:
        ticker = _build_mock_ticker(info={})
        with patch("yfinance.Ticker", return_value=ticker):
            bundle = YfinanceFundamentalAdapter().get_fundamental_bundle("AAPL")
        self.assertEqual(bundle["status"], "not_supported")
        self.assertEqual(bundle.get("growth"), {})
        self.assertEqual(bundle.get("belong_boards"), [])


if __name__ == "__main__":
    unittest.main()
