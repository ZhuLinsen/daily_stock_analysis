# -*- coding: utf-8 -*-
"""Regression tests for YfinanceFetcher HK bare-code routing.

Covers issue #2091: 4-5 digit pure numeric codes (e.g. 02513, 00700, 0001)
must route to ``.HK`` rather than fall through to the ``.SZ`` default,
otherwise Yahoo Finance returns 404 and the daily-data chain breaks.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from data_provider.yfinance_fetcher import YfinanceFetcher


class TestHKPrefixStillRoutesToHK:
    """Existing HK-prefix behaviour must remain unchanged."""

    def test_hk_prefix_4digit(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("hk00700") == "0700.HK"

    def test_hk_prefix_5digit(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("HK02513") == "2513.HK"

    def test_hk_prefix_short(self) -> None:
        # 1-3 digit HK prefix (e.g. hk0001 -> 0001.HK)
        assert YfinanceFetcher()._convert_stock_code("hk0001") == "0001.HK"

    @patch("yfinance.Ticker")
    def test_hk_code_executes_realtime_route(self, ticker_factory: MagicMock) -> None:
        ticker = ticker_factory.return_value
        ticker.fast_info = SimpleNamespace(
            lastPrice=401.2,
            previousClose=398.0,
            open=399.0,
            dayHigh=403.0,
            dayLow=397.0,
            lastVolume=12_345,
            marketCap=3_800_000_000_000,
        )
        ticker.info = {"shortName": "Tencent", "currency": "HKD"}

        quote = YfinanceFetcher().get_realtime_quote("HK00700")

        ticker_factory.assert_called_once_with("0700.HK")
        assert quote is not None
        assert quote.code == "0700.HK"
        assert quote.market == "hk"
        assert quote.currency == "HKD"


class TestBareHKCodeRoutesToHK:
    """Regression for issue #2091: bare 4-5 digit numeric codes -> ``.HK``.

    Previously the bare 5-digit path fell through to the ``.SZ`` default and
    Yahoo Finance returned 404 for codes like ``02513``. The new routing
    shunts 4-5 digit pure numeric codes to ``.HK`` ahead of the .SZ fallback,
    because A-share codes are always 6 digits and BSE codes are 6 digits
    starting with 4 / 8 / 920 — there is no A-share / BSE ambiguity for
    4-5 digit numeric codes.
    """

    def test_bare_5digit_new_listing(self) -> None:
        # 智谱 02513 — the exact case from issue #2091
        assert YfinanceFetcher()._convert_stock_code("02513") == "2513.HK"

    def test_bare_5digit_tencent(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("00700") == "0700.HK"

    def test_bare_5digit_keeps_leading_zero_padding(self) -> None:
        # Alibaba 9988 -> padded to 9988 (already 4 digit, no extra padding)
        assert YfinanceFetcher()._convert_stock_code("09988") == "9988.HK"

    def test_bare_4digit_legacy_hk(self) -> None:
        # 长江和记 0001 — 4-digit legacy HK code (per maintainer note)
        assert YfinanceFetcher()._convert_stock_code("0001") == "0001.HK"

    def test_bare_4digitmobile_carrier(self) -> None:
        # 中国移动 0941 — 4-digit HK code from issue context
        assert YfinanceFetcher()._convert_stock_code("0941") == "0941.HK"


class TestAShareRoutingUnchanged:
    """A-share / BSE routing must remain unchanged after the HK bare fix."""

    def test_sh_600519(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("600519") == "600519.SS"

    def test_sz_000001(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("000001") == "000001.SZ"

    def test_sz_300750(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("300750") == "300750.SZ"

    def test_sz_002594(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("002594") == "002594.SZ"

    def test_kcb_688981(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("688981") == "688981.SS"

    def test_bse_920xxx(self) -> None:
        # BSE 920xxx is 6 digit — must NOT be caught by the 4-5 digit HK rule
        assert YfinanceFetcher()._convert_stock_code("920019") == "920019.BJ"

    def test_bse_8xxxxx(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("830799") == "830799.BJ"

    def test_bse_4xxxxx(self) -> None:
        # BSE 4xxxxx is 6 digit — must NOT match 4-digit HK rule
        assert YfinanceFetcher()._convert_stock_code("430047") == "430047.BJ"


class TestETFAndSuffixUnchanged:
    """ETF and suffix codes must route exactly as before."""

    def test_sh_etf_510300(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("510300") == "510300.SS"

    def test_sz_etf_159915(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("159915") == "159915.SZ"

    def test_us_ticker(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("AAPL") == "AAPL"

    def test_jp_suffix(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("7203.T") == "7203.T"

    def test_kr_suffix(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("005930.KS") == "005930.KS"

    def test_with_hk_suffix(self) -> None:
        # Already suffixed codes pass through verbatim
        assert YfinanceFetcher()._convert_stock_code("0700.HK") == "0700.HK"

    def test_with_ss_suffix(self) -> None:
        assert YfinanceFetcher()._convert_stock_code("600519.SS") == "600519.SS"
