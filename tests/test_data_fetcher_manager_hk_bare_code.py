# -*- coding: utf-8 -*-
"""Regression tests for ``DataFetcherManager`` HK bare-code routing.

Closes review blocker ``OR-COR-bfddfd66`` on PR #2097 / issue #2091:
the previous fix only patched ``YfinanceFetcher._convert_stock_code`` so
``0001`` / ``0941`` round-tripped to ``.HK`` at the helper layer, but
``data_provider/base.py::_is_hk_market()`` still only treated 5-digit
bare numeric codes as HK. The manager layer therefore kept routing
4-digit bare codes through the A-share provider chain
(``AkshareFetcher`` → ``stock_zh_a_hist``, ``BaostockFetcher`` →
``sz.0001``, ``TushareFetcher`` → ``0001.SZ``), so issue #2091 was not
actually closed on the main call path.

These tests pin the manager-level contract: 4-digit bare HK codes must
be detected as HK at the routing layer and only fan out to HK-capable
daily fetchers (``YfinanceFetcher`` / ``AkshareFetcher`` /
``TushareFetcher`` / ``LongbridgeFetcher``), never to CN-only fetchers.
"""

from unittest.mock import patch

import pandas as pd

from data_provider.base import (
    BaseFetcher,
    DataFetchError,
    DataFetcherManager,
    _is_hk_market,
)


class _FakeFetcher(BaseFetcher):
    """Lightweight fetcher stub matching the real daily-data contract."""

    def __init__(self, name: str, should_fail: bool = False) -> None:
        self.name = name
        # Priority only matters for the manager's stable ordering; keep
        # CN-only fetchers at lower numeric priority so the HK filter is
        # the only thing keeping them out of the HK chain.
        self.priority = {"YfinanceFetcher": 4, "AkshareFetcher": 1,
                         "TushareFetcher": 2, "BaostockFetcher": 3,
                         "EfinanceFetcher": 0, "TencentFetcher": 0}.get(name, 5)
        self.calls: list[str] = []
        self.should_fail = should_fail

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise NotImplementedError

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        self.calls.append(stock_code)
        if self.should_fail:
            raise DataFetchError(f"{self.name} should not be called for {stock_code}")
        return pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-07-25")],
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [1.0],
                "volume": [100],
                "amount": [100.0],
                "pct_chg": [0.0],
            }
        )


class TestIsHkMarketAcceptsFourDigitBareCodes:
    """``_is_hk_market`` must accept 4-digit bare numeric codes as HK."""

    def test_four_digit_bare_hk(self) -> None:
        # 长和 0001 / 中国移动 0941 — issue #2091 core examples
        assert _is_hk_market("0001") is True
        assert _is_hk_market("0941") is True

    def test_four_digit_with_padding_preserved(self) -> None:
        # 0078 -> 78 — still HK (4 leading-zero-padded digit)
        assert _is_hk_market("0078") is True

    def test_five_digit_bare_hk_unchanged(self) -> None:
        assert _is_hk_market("00700") is True
        assert _is_hk_market("02513") is True

    def test_six_digit_a_share_not_hk(self) -> None:
        # A股 / BSE 6 位数字仍必须判为非港股
        assert _is_hk_market("600519") is False
        assert _is_hk_market("000001") is False
        assert _is_hk_market("300750") is False
        assert _is_hk_market("920019") is False
        assert _is_hk_market("159915") is False

    def test_hk_prefix_four_digit_unchanged(self) -> None:
        assert _is_hk_market("HK0001") is True
        assert _is_hk_market("hk00700") is True

    def test_hk_suffix_four_digit_unchanged(self) -> None:
        assert _is_hk_market("0001.HK") is True
        assert _is_hk_market("0700.HK") is True


class TestManagerRoutesFourDigitBareHkAwayFromCnOnlyFetchers:
    """``DataFetcherManager.get_daily_data("0001")`` must skip CN-only fetchers."""

    @patch("data_provider.base.record_provider_run_started")
    @patch("data_provider.base.record_provider_run")
    def test_four_digit_bare_hk_does_not_hit_cn_only_fetchers(
        self, _record_run, _record_started
    ) -> None:
        # CN-only fetchers — they MUST NOT receive the call once the manager
        # routes by market. Use should_fail=True so any leak raises loudly.
        efinance = _FakeFetcher("EfinanceFetcher", should_fail=True)
        tencent = _FakeFetcher("TencentFetcher", should_fail=True)
        tickflow = _FakeFetcher("TickFlowFetcher", should_fail=True)
        pytdx = _FakeFetcher("PytdxFetcher", should_fail=True)
        baostock = _FakeFetcher("BaostockFetcher", should_fail=True)
        # HK-capable fetchers
        akshare = _FakeFetcher("AkshareFetcher")
        tushare = _FakeFetcher("TushareFetcher")
        yfinance = _FakeFetcher("YfinanceFetcher")

        manager = DataFetcherManager(
            fetchers=[efinance, tencent, tickflow, pytdx, baostock,
                     akshare, tushare, yfinance]
        )

        df, source = manager.get_daily_data("0001")

        assert not df.empty
        # Either Akshare / Tushare / Yfinance is acceptable as the HK-capable
        # primary; the contract under test is "NOT Efinance/Tencent/...". Pick
        # the first HK-capable fetcher in the manager's stable order.
        assert source in {"AkshareFetcher", "TushareFetcher", "YfinanceFetcher"}
        # CN-only fetchers must never be called for a 4-digit bare HK code
        assert efinance.calls == []
        assert tencent.calls == []
        assert tickflow.calls == []
        assert pytdx.calls == []
        assert baostock.calls == []
        # HK-capable fetcher actually received the call
        hk_capable_calls = akshare.calls + tushare.calls + yfinance.calls
        assert hk_capable_calls == ["0001"]

    @patch("data_provider.base.record_provider_run_started")
    @patch("data_provider.base.record_provider_run")
    def test_four_digit_bare_hk_uses_yfinance_when_akshare_tushare_unavailable(
        self, _record_run, _record_started
    ) -> None:
        # When only YfinanceFetcher is available (Akshare/Tushare missing),
        # the manager still routes 4-digit bare HK to it instead of falling
        # back to CN-only fetchers.
        efinance = _FakeFetcher("EfinanceFetcher", should_fail=True)
        baostock = _FakeFetcher("BaostockFetcher", should_fail=True)
        yfinance = _FakeFetcher("YfinanceFetcher")

        manager = DataFetcherManager(fetchers=[efinance, baostock, yfinance])

        df, source = manager.get_daily_data("0941")

        assert source == "YfinanceFetcher"
        assert not df.empty
        assert yfinance.calls == ["0941"]
        assert efinance.calls == []
        assert baostock.calls == []


class TestManagerRoutesFiveDigitBareHkUnchanged:
    """5-digit bare HK codes must keep their pre-fix behavior (regression)."""

    @patch("data_provider.base.record_provider_run_started")
    @patch("data_provider.base.record_provider_run")
    def test_five_digit_bare_hk_still_skips_cn_only_fetchers(
        self, _record_run, _record_started
    ) -> None:
        efinance = _FakeFetcher("EfinanceFetcher", should_fail=True)
        baostock = _FakeFetcher("BaostockFetcher", should_fail=True)
        yfinance = _FakeFetcher("YfinanceFetcher")

        manager = DataFetcherManager(fetchers=[efinance, baostock, yfinance])

        df, source = manager.get_daily_data("00700")

        assert source == "YfinanceFetcher"
        assert not df.empty
        assert yfinance.calls == ["00700"]
        assert efinance.calls == []
        assert baostock.calls == []


class TestManagerStillRoutesSixDigitToCn:
    """6-digit numeric codes must continue routing to the A-share chain."""

    @patch("data_provider.base.record_provider_run_started")
    @patch("data_provider.base.record_provider_run")
    def test_six_digit_a_share_goes_to_cn_only_fetchers(
        self, _record_run, _record_started
    ) -> None:
        # For a 6-digit A-share code, CN-only fetchers MUST be reached (not
        # Yfinance). We invert the assertion: Yfinance must NOT be called
        # because Efinance/Tencent/Baostock should succeed first.
        efinance = _FakeFetcher("EfinanceFetcher")
        tencent = _FakeFetcher("TencentFetcher")
        baostock = _FakeFetcher("BaostockFetcher")
        yfinance = _FakeFetcher("YfinanceFetcher", should_fail=True)

        manager = DataFetcherManager(
            fetchers=[efinance, tencent, baostock, yfinance]
        )

        df, source = manager.get_daily_data("600519")

        assert not df.empty
        # 6-digit A-share goes to a CN-only fetcher, never Yfinance
        assert source in {"EfinanceFetcher", "TencentFetcher", "BaostockFetcher"}
        assert yfinance.calls == []
        # The CN-only fetcher that won the route was actually called
        cn_capable_calls = efinance.calls + tencent.calls + baostock.calls
        assert cn_capable_calls == ["600519"]
