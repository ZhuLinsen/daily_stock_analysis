# -*- coding: utf-8 -*-
"""
Regression tests for provider-side A-share stock code conversion.
"""

import unittest

import pandas as pd

from data_provider.base import DataFetcherManager, normalize_stock_code
from data_provider.baostock_fetcher import BaostockFetcher
from data_provider.pytdx_fetcher import PytdxFetcher
from data_provider.tushare_fetcher import TushareFetcher


class _RecordingDailyFetcher:
    name = "RecordingDailyFetcher"
    priority = 1

    def __init__(self) -> None:
        self.calls = []

    def get_daily_data(self, stock_code: str, *args, **kwargs) -> pd.DataFrame:
        self.calls.append(stock_code)
        return pd.DataFrame({"date": ["2026-05-22"], "close": [10.0]})


class TestDataFetcherManagerAShareCodes(unittest.TestCase):
    def test_get_daily_data_keeps_user_contract_as_bare_stock_code(self) -> None:
        fetcher = _RecordingDailyFetcher()
        manager = DataFetcherManager(fetchers=[fetcher])

        df, source = manager.get_daily_data("601888", days=1)

        self.assertFalse(df.empty)
        self.assertEqual(source, "RecordingDailyFetcher")
        self.assertEqual(fetcher.calls, ["601888"])


class TestBaostockAShareCodeConversion(unittest.TestCase):
    def test_convert_bare_stock_codes_to_baostock_format(self) -> None:
        fetcher = BaostockFetcher()

        self.assertEqual(fetcher._convert_stock_code("601888"), "sh.601888")
        self.assertEqual(fetcher._convert_stock_code("600519"), "sh.600519")
        self.assertEqual(fetcher._convert_stock_code("605499"), "sh.605499")
        self.assertEqual(fetcher._convert_stock_code("688981"), "sh.688981")
        self.assertEqual(fetcher._convert_stock_code("000001"), "sz.000001")
        self.assertEqual(fetcher._convert_stock_code("001979"), "sz.001979")
        self.assertEqual(fetcher._convert_stock_code("003816"), "sz.003816")
        self.assertEqual(fetcher._convert_stock_code("300750"), "sz.300750")
        self.assertEqual(fetcher._convert_stock_code("301012"), "sz.301012")

    def test_convert_bare_etf_codes_to_baostock_format(self) -> None:
        fetcher = BaostockFetcher()

        self.assertEqual(fetcher._convert_stock_code("510050"), "sh.510050")
        self.assertEqual(fetcher._convert_stock_code("159919"), "sz.159919")

    def test_convert_suffix_code_uses_internal_provider_format(self) -> None:
        fetcher = BaostockFetcher()

        self.assertEqual(fetcher._convert_stock_code("600519.SH"), "sh.600519")
        self.assertEqual(fetcher._convert_stock_code("000001.SZ"), "sz.000001")

    def test_convert_prefix_code_preserves_explicit_exchange_hint(self) -> None:
        fetcher = BaostockFetcher()

        self.assertEqual(fetcher._convert_stock_code("SH000001"), "sh.000001")
        self.assertEqual(fetcher._convert_stock_code("SH.000001"), "sh.000001")
        self.assertEqual(fetcher._convert_stock_code("SZ600519"), "sz.600519")
        self.assertEqual(fetcher._convert_stock_code("SZ.600519"), "sz.600519")
        self.assertEqual(fetcher._convert_stock_code("ss.600519"), "sh.600519")


class TestPytdxAShareCodeConversion(unittest.TestCase):
    def test_get_market_code_for_bare_stock_codes(self) -> None:
        fetcher = PytdxFetcher(hosts=[])

        self.assertEqual(fetcher._get_market_code("601888"), (1, "601888"))
        self.assertEqual(fetcher._get_market_code("688981"), (1, "688981"))
        self.assertEqual(fetcher._get_market_code("000001"), (0, "000001"))
        self.assertEqual(fetcher._get_market_code("300750"), (0, "300750"))

    def test_get_market_code_preserves_explicit_exchange_hint(self) -> None:
        fetcher = PytdxFetcher(hosts=[])

        self.assertEqual(fetcher._get_market_code("SH000001"), (1, "000001"))
        self.assertEqual(fetcher._get_market_code("SH.000001"), (1, "000001"))
        self.assertEqual(fetcher._get_market_code("SZ600519"), (0, "600519"))
        self.assertEqual(fetcher._get_market_code("SZ.600519"), (0, "600519"))
        self.assertEqual(fetcher._get_market_code("ss.600519"), (1, "600519"))


class TestTushareAShareCodeConversion(unittest.TestCase):
    def test_convert_bare_stock_codes_to_tushare_format(self) -> None:
        fetcher = TushareFetcher()

        self.assertEqual(fetcher._convert_stock_code("605499"), "605499.SH")
        self.assertEqual(fetcher._convert_stock_code("001979"), "001979.SZ")
        self.assertEqual(fetcher._convert_stock_code("003816"), "003816.SZ")
        self.assertEqual(fetcher._convert_stock_code("301012"), "301012.SZ")

    def test_convert_prefix_code_preserves_explicit_exchange_hint(self) -> None:
        fetcher = TushareFetcher()

        self.assertEqual(fetcher._convert_stock_code("SH000001"), "000001.SH")
        self.assertEqual(fetcher._convert_stock_code("SH.000001"), "000001.SH")
        self.assertEqual(fetcher._convert_stock_code("SZ600519"), "600519.SZ")
        self.assertEqual(fetcher._convert_stock_code("SZ.600519"), "600519.SZ")
        self.assertEqual(fetcher._convert_stock_code("ss.600519"), "600519.SH")


class TestNormalizeStockCode(unittest.TestCase):
    def test_normalize_prefixed_dot_code(self) -> None:
        self.assertEqual(normalize_stock_code("SH.600519"), "600519")
        self.assertEqual(normalize_stock_code("sh.600519"), "600519")
        self.assertEqual(normalize_stock_code("SZ.000001"), "000001")
        self.assertEqual(normalize_stock_code("sz.000001"), "000001")
        self.assertEqual(normalize_stock_code("SS600519"), "600519")
        self.assertEqual(normalize_stock_code("SS.600519"), "600519")
        self.assertEqual(normalize_stock_code("600519.SS"), "600519")
        self.assertEqual(normalize_stock_code("BJ.920748"), "920748")


if __name__ == "__main__":
    unittest.main()
