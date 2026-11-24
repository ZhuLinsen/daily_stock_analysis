# -*- coding: utf-8 -*-
"""Regression tests for foreign/HK stock name lookup and market routing."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from data_provider.base import DataFetcherManager
from data_provider.yfinance_fetcher import YfinanceFetcher
from src.analyzer import get_stock_name_multi_source
from src.data.stock_mapping import lookup_static_stock_name


class TestLookupStaticStockName:
    def test_hk_and_us_variant_forms_resolve(self) -> None:
        assert lookup_static_stock_name("HK00700") == "腾讯控股"
        assert lookup_static_stock_name("hk00700") == "腾讯控股"
        assert lookup_static_stock_name("HK700") == "腾讯控股"
        assert lookup_static_stock_name("00700.HK") == "腾讯控股"
        assert lookup_static_stock_name("0700.HK") == "腾讯控股"
        assert lookup_static_stock_name("700.HK") == "腾讯控股"
        assert lookup_static_stock_name("0700") == "腾讯控股"
        assert lookup_static_stock_name("00700") == "腾讯控股"
        assert lookup_static_stock_name("AAPL.US") == "苹果"
        assert lookup_static_stock_name("AAPL.O") == "苹果"
        assert lookup_static_stock_name("AAPL.NASDAQ") == "苹果"
        assert lookup_static_stock_name("NVDA.NASDAQ") == "英伟达"
        custom_suffix_map = {"MSFT": "微软", "IBM": "IBM公司"}
        assert lookup_static_stock_name("MSFT.NYSE", custom_suffix_map) == "微软"
        assert lookup_static_stock_name("IBM.AMEX", custom_suffix_map) == "IBM公司"
        assert lookup_static_stock_name("IBM.ARCA", custom_suffix_map) == "IBM公司"
        assert lookup_static_stock_name("aapl") == "苹果"
        assert lookup_static_stock_name("600519") == "贵州茅台"

    def test_does_not_conflate_cn_index_suffix_and_rejects_placeholders(self) -> None:
        # 000001 in STOCK_NAME_MAP is Ping An Bank; 000001.SH must not resolve to Ping An Bank.
        assert lookup_static_stock_name("000001.SH") is None
        custom_map = {
            "00700": "N/A",
            "01810": "HK01810",
            "09988": "00700",
            "AAPL": "股票AAPL",
            "MSFT": "微软",
        }
        assert lookup_static_stock_name("HK00700", custom_map) is None
        assert lookup_static_stock_name("HK01810", custom_map) is None
        assert lookup_static_stock_name("MSFT", custom_map) == "微软"
        assert lookup_static_stock_name("AAPL.US", custom_map) is None
        assert lookup_static_stock_name("TSLA", custom_map) is None


class TestDataFetcherManagerStockNameRouting:
    def _build_manager(self, fetchers: list) -> DataFetcherManager:
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = fetchers
        manager._stock_name_cache = {}
        manager.get_realtime_quote = MagicMock()
        return manager

    def test_static_map_resolves_hk_and_us_variants_without_fetchers(self) -> None:
        remote_fetcher = MagicMock()
        remote_fetcher.name = "YfinanceFetcher"
        manager = self._build_manager([remote_fetcher])

        for code, expected in (
            ("HK00700", "腾讯控股"),
            ("00700.HK", "腾讯控股"),
            ("hk700", "腾讯控股"),
            ("AAPL.US", "苹果"),
        ):
            with patch("data_provider.base.get_index_stock_name", return_value=None):
                name = manager.get_stock_name(code, allow_realtime=False)
            assert name == expected

        manager.get_realtime_quote.assert_not_called()
        remote_fetcher.get_stock_name.assert_not_called()

    def test_unindexed_hk_skips_cn_fetchers_and_uses_yfinance(self) -> None:
        baostock = MagicMock()
        baostock.name = "BaostockFetcher"
        pytdx = MagicMock()
        pytdx.name = "PytdxFetcher"
        tencent = MagicMock()
        tencent.name = "TencentFetcher"
        yf_fetcher = MagicMock()
        yf_fetcher.name = "YfinanceFetcher"
        yf_fetcher.get_stock_name.return_value = "Harbour BioMed"

        manager = self._build_manager([tencent, pytdx, baostock, yf_fetcher])
        with patch("data_provider.base.get_index_stock_name", return_value=None):
            name = manager.get_stock_name("HK02142", allow_realtime=False)

        assert name == "Harbour BioMed"
        tencent.get_stock_name.assert_not_called()
        pytdx.get_stock_name.assert_not_called()
        baostock.get_stock_name.assert_not_called()
        yf_fetcher.get_stock_name.assert_called_once_with("HK02142")

    def test_jp_kr_tw_skip_cn_fetchers_and_route_to_yfinance(self) -> None:
        for code, expected_name in (
            ("7203.T", "Toyota Motor"),
            ("005930.KS", "Samsung Electronics"),
            ("2330.TW", "TSMC"),
        ):
            baostock = MagicMock()
            baostock.name = "BaostockFetcher"
            pytdx = MagicMock()
            pytdx.name = "PytdxFetcher"
            yf_fetcher = MagicMock()
            yf_fetcher.name = "YfinanceFetcher"
            yf_fetcher.get_stock_name.return_value = expected_name

            manager = self._build_manager([pytdx, baostock, yf_fetcher])
            with patch("data_provider.base.get_index_stock_name", return_value=None):
                name = manager.get_stock_name(code, allow_realtime=False)

            assert name == expected_name
            pytdx.get_stock_name.assert_not_called()
            baostock.get_stock_name.assert_not_called()
            yf_fetcher.get_stock_name.assert_called_once_with(code)

    def test_us_index_skips_cn_fetchers_and_resolves_via_yfinance(self) -> None:
        baostock = MagicMock()
        baostock.name = "BaostockFetcher"
        yf_fetcher = YfinanceFetcher()
        manager = self._build_manager([baostock, yf_fetcher])

        with patch("data_provider.base.get_index_stock_name", return_value=None):
            name = manager.get_stock_name("SPX", allow_realtime=False)

        assert name == "标普500指数"
        baostock.get_stock_name.assert_not_called()


class TestYfinanceFetcherGetStockName:
    @patch("yfinance.Ticker")
    def test_hk_lookup_caches_and_falls_back_from_symbol_echo_to_long_name(
        self, ticker_factory: MagicMock
    ) -> None:
        ticker = ticker_factory.return_value
        ticker.info = {"shortName": "2142.HK", "longName": "HBM Holdings Limited"}

        fetcher = YfinanceFetcher()
        first = fetcher.get_stock_name("HK02142")
        second = fetcher.get_stock_name("HK02142")

        assert first == "HBM Holdings Limited"
        assert second == "HBM Holdings Limited"
        ticker_factory.assert_called_once_with("2142.HK")

    @patch("yfinance.Ticker")
    def test_cn_ashare_skips_yfinance(self, ticker_factory: MagicMock) -> None:
        fetcher = YfinanceFetcher()
        assert fetcher.get_stock_name("600519") is None
        ticker_factory.assert_not_called()

    @patch("yfinance.Ticker")
    def test_supports_us_suffix_and_jp_kr_tw(self, ticker_factory: MagicMock) -> None:
        ticker_factory.return_value.info = {"shortName": "Example Corp"}
        fetcher = YfinanceFetcher()

        assert fetcher.get_stock_name("SPX") == "标普500指数"
        ticker_factory.assert_not_called()

        for code, yf_symbol in (
            ("AAPL", "AAPL"),
            ("AAPL.US", "AAPL"),
            ("7203.T", "7203.T"),
            ("005930.KS", "005930.KS"),
            ("2330.TW", "2330.TW"),
        ):
            ticker_factory.reset_mock()
            assert fetcher.get_stock_name(code) == "Example Corp"
            ticker_factory.assert_called_once_with(yf_symbol)

    @patch("yfinance.Ticker")
    def test_realtime_quote_falls_back_to_canonical_static_name(
        self, ticker_factory: MagicMock
    ) -> None:
        ticker = ticker_factory.return_value
        ticker.fast_info = SimpleNamespace(
            lastPrice=400.0,
            previousClose=395.0,
            open=396.0,
            dayHigh=402.0,
            dayLow=394.0,
            lastVolume=10000,
            marketCap=3_000_000_000_000,
        )
        ticker.history.side_effect = RuntimeError("history unavailable")
        ticker.info = {}

        quote = YfinanceFetcher().get_realtime_quote("HK00700")
        assert quote is not None
        assert quote.name == "腾讯控股"


class TestAnalyzerStaticNameLookup:
    def test_get_stock_name_multi_source_resolves_hk_without_data_manager(self) -> None:
        with patch("data_provider.base.DataFetcherManager") as manager_cls:
            assert get_stock_name_multi_source("HK00700") == "腾讯控股"
            assert get_stock_name_multi_source("00700.HK") == "腾讯控股"
            manager_cls.assert_not_called()


class TestOpenReviewCounterexamplesStockName:
    @patch("yfinance.Ticker")
    def test_us_exchange_suffixes_strip_for_yahoo_while_preserving_class_shares(
        self, ticker_factory: MagicMock
    ) -> None:
        ticker_factory.return_value.info = {"shortName": "Example Name"}
        fetcher = YfinanceFetcher()

        for code, expected_yf in (
            ("ZM.O", "ZM"),
            ("ZM.NASDAQ", "ZM"),
            ("IBM.N", "IBM"),
            ("IBM.NYSE", "IBM"),
            ("SPY.AMEX", "SPY"),
            ("SPY.ARCA", "SPY"),
            ("BRK.A", "BRK-A"),
        ):
            ticker_factory.reset_mock()
            assert fetcher.get_stock_name(code) == "Example Name"
            ticker_factory.assert_called_once_with(expected_yf)

    @patch("yfinance.Ticker")
    def test_numeric_us_suffixed_code_does_not_misresolve_cn_or_call_yahoo(
        self, ticker_factory: MagicMock
    ) -> None:
        assert lookup_static_stock_name("600519.US") is None
        assert lookup_static_stock_name("600519.NASDAQ") is None
        fetcher = YfinanceFetcher()
        assert fetcher.get_stock_name("600519.US") is None
        assert fetcher.get_stock_name("600519.NASDAQ") is None
        ticker_factory.assert_not_called()

        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = [fetcher]
        manager._stock_name_cache = {}
        manager.get_realtime_quote = MagicMock()
        with patch("data_provider.base.get_index_stock_name", return_value=None):
            assert manager.get_stock_name("600519.US", allow_realtime=False) == ""

    @patch("yfinance.Ticker")
    def test_hk_equivalent_alias_short_name_falls_back_to_long_name(
        self, ticker_factory: MagicMock
    ) -> None:
        ticker = ticker_factory.return_value
        ticker.info = {"shortName": "02142.HK", "longName": "HBM Holdings Limited"}
        ticker.fast_info = SimpleNamespace(
            lastPrice=25.0,
            previousClose=24.0,
            open=24.5,
            dayHigh=25.2,
            dayLow=24.3,
            lastVolume=5000,
            marketCap=2_000_000_000,
        )
        ticker.history.side_effect = RuntimeError("history unavailable")

        fetcher = YfinanceFetcher()
        assert fetcher.get_stock_name("HK02142") == "HBM Holdings Limited"
        quote = fetcher.get_realtime_quote("HK02142")
        assert quote is not None
        assert quote.name == "HBM Holdings Limited"

    @patch("yfinance.Ticker")
    def test_prefetch_stock_names_skips_slow_yfinance_network_lookup(
        self, ticker_factory: MagicMock
    ) -> None:
        fetcher = YfinanceFetcher()
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = [fetcher]
        manager._stock_name_cache = {}
        manager.get_realtime_quote = MagicMock()

        with patch("data_provider.base.get_index_stock_name", return_value=None):
            manager.prefetch_stock_names(["HK02142", "600519"], use_bulk=False)

        ticker_factory.assert_not_called()
        assert manager._stock_name_cache["600519"] == "贵州茅台"

    @patch("yfinance.Ticker")
    def test_data_fetcher_manager_routes_all_us_exchange_suffixes_to_us_fetchers_only(
        self, ticker_factory: MagicMock
    ) -> None:
        """OR-COR-b9c421d0: .NASDAQ/.NYSE/.AMEX/.ARCA must skip CN fetchers in DataFetcherManager."""
        from data_provider.base import _is_non_cn_request

        for sym in ("ZM.NASDAQ", "IBM.NYSE", "SPY.AMEX", "SPY.ARCA", "600519.NASDAQ"):
            assert _is_non_cn_request(sym) is True

        ticker_factory.return_value.info = {"shortName": "Zoom Video"}
        tencent_stub = MagicMock()
        tencent_stub.name = "TencentFetcher"
        tencent_stub.get_stock_name = MagicMock(return_value="wrong-cn-name")
        yf_fetcher = YfinanceFetcher()

        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = [tencent_stub, yf_fetcher]
        manager._stock_name_cache = {}
        manager.get_realtime_quote = MagicMock()

        with patch("data_provider.base.get_index_stock_name", return_value=None):
            assert manager.get_stock_name("ZM.NASDAQ", allow_realtime=False) == "Zoom Video"
            assert manager.get_stock_name("600519.NASDAQ", allow_realtime=False) == ""

        tencent_stub.get_stock_name.assert_not_called()
        ticker_factory.assert_called_once_with("ZM")
