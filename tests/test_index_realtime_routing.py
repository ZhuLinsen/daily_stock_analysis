# -*- coding: utf-8 -*-
"""Story 1.5 — index realtime quote routing regression tests.

Covers the smoke-found contract violations (2026-08-26 network smoke):
- ``get_realtime_quote`` must route registered index codes through a fixed
  index chain instead of stripping sh/sz prefixes into the stock path
  (``sh000016`` was resolved as *ST康佳A at 2.33).
- CSI indices use the Eastmoney single-stock secid endpoint only.
- ``prefetch_realtime_quotes`` must preserve explicit index identities.
- ``_to_sina_tx_symbol`` must preserve explicit sh/sz prefixes.
- history code candidates must keep the index canonical bucket.
- ``_augment_historical_with_realtime`` must use the caller-provided market.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from data_provider.akshare_fetcher import _to_sina_tx_symbol
from data_provider.base import DataFetcherManager
from data_provider.efinance_fetcher import EfinanceFetcher
from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from src.core.pipeline import StockAnalysisPipeline


def _quote(code: str, price: float = 3000.0) -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(
        code=code,
        name="上证50",
        price=price,
        change_pct=1.0,
        source=RealtimeSource.TENCENT,
    )


class _FakeAkshareFetcher:
    name = "AkshareFetcher"
    priority = 1

    def __init__(self, tencent_quote: bool = True):
        self.calls = []
        self.tencent_quote = tencent_quote

    def get_realtime_quote(self, stock_code, source="em"):
        self.calls.append((stock_code, source))
        if source == "tencent" and self.tencent_quote:
            return _quote(stock_code)
        return None


class _FakeEfinanceFetcher:
    name = "EfinanceFetcher"
    priority = 0

    def __init__(self):
        self.calls = []

    def get_realtime_quote(self, stock_code):
        self.calls.append(stock_code)
        return None

    def get_index_realtime_quote(self, stock_code):
        self.calls.append(stock_code)
        return None


class _FakeTickFlowFetcher:
    name = "TickFlowFetcher"
    priority = 2

    def __init__(self):
        self.calls = []
        self.prefetch_calls = []

    def get_realtime_quote(self, stock_code):
        self.calls.append(stock_code)
        return None

    def prefetch_realtime_quotes(self, stock_codes, batch_size=None):
        self.prefetch_calls.append((list(stock_codes), batch_size))
        return len(stock_codes)


class IndexRealtimeRoutingTestCase(unittest.TestCase):
    def _manager(self, fetchers):
        return DataFetcherManager(fetchers=fetchers)

    def _config(self, priority="tencent,akshare_sina,efinance,akshare_em"):
        return SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority=priority,
            realtime_cache_ttl=600,
        )

    def test_sh_index_routes_to_index_chain_with_prefix_preserved(self):
        akshare = _FakeAkshareFetcher()
        manager = self._manager(
            [_FakeEfinanceFetcher(), akshare, _FakeTickFlowFetcher()]
        )
        with patch("src.config.get_config", return_value=self._config()):
            quote = manager.get_realtime_quote("sh000016")
        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, "sh000016")
        # First chain step: Tencent via AkshareFetcher with the prefixed symbol.
        self.assertEqual(akshare.calls[0], ("sh000016", "tencent"))

    def test_sh_index_chain_falls_through_all_sources(self):
        akshare = _FakeAkshareFetcher(tencent_quote=False)
        efinance = _FakeEfinanceFetcher()
        tickflow = _FakeTickFlowFetcher()
        manager = self._manager([efinance, akshare, tickflow])
        with patch("src.config.get_config", return_value=self._config()):
            quote = manager.get_realtime_quote("sh000016")
        self.assertIsNone(quote)
        self.assertEqual(
            akshare.calls, [("sh000016", "tencent"), ("sh000016", "sina")]
        )
        self.assertEqual(efinance.calls, ["sh000016"])
        self.assertEqual(tickflow.calls, ["000016.SH"])

    def test_csi_index_uses_efinance_only(self):
        akshare = _FakeAkshareFetcher()
        efinance = _FakeEfinanceFetcher()
        manager = self._manager([efinance, akshare, _FakeTickFlowFetcher()])
        with patch("src.config.get_config", return_value=self._config()):
            quote = manager.get_realtime_quote("csi930955")
        self.assertIsNone(quote)
        self.assertEqual(efinance.calls, ["csi930955"])
        self.assertEqual(akshare.calls, [])

    def test_us_index_does_not_fallback_to_longbridge(self):
        yfinance = MagicMock()
        yfinance.name = "YfinanceFetcher"
        yfinance.priority = 4
        yfinance.is_available_for_request.return_value = True
        yfinance.get_realtime_quote.return_value = None

        longbridge = MagicMock()
        longbridge.name = "LongbridgeFetcher"
        longbridge.priority = 5
        longbridge.is_available_for_request.return_value = True
        longbridge.get_realtime_quote.return_value = _quote("SPX")

        manager = self._manager([yfinance, longbridge])
        with patch("src.config.get_config", return_value=self._config()):
            quote = manager.get_realtime_quote("SPX")

        self.assertIsNone(quote)
        yfinance.get_realtime_quote.assert_called_once_with("SPX")
        longbridge.get_realtime_quote.assert_not_called()

    def test_bare_code_stays_on_stock_path(self):
        akshare = _FakeAkshareFetcher()
        manager = self._manager([_FakeEfinanceFetcher(), akshare])
        with patch("src.config.get_config", return_value=self._config()):
            manager.get_realtime_quote("000016")
        # Bare 000016 is a stock: generic path normalizes and calls the
        # configured priority sources, never the index chain.
        self.assertNotIn(("sh000016", "tencent"), akshare.calls)
        self.assertTrue(any(code == "000016" for code, _ in akshare.calls))

    def test_prefetch_preserves_index_codes(self):
        tickflow = _FakeTickFlowFetcher()
        manager = self._manager([tickflow])
        with patch(
            "src.config.get_config", return_value=self._config("tickflow,tencent")
        ):
            manager.prefetch_realtime_quotes(
                ["sh000016", "600519", "000001", "AAPL", "hk00700"]
            )
        self.assertEqual(
            tickflow.prefetch_calls[0][0],
            ["sh000016", "600519", "000001", "AAPL", "HK00700"],
        )


class SinaTxSymbolPrefixTestCase(unittest.TestCase):
    def test_explicit_prefix_preserved(self):
        self.assertEqual(_to_sina_tx_symbol("sh000016"), "sh000016")
        self.assertEqual(_to_sina_tx_symbol("sz399001"), "sz399001")
        self.assertEqual(_to_sina_tx_symbol("SH000300"), "sh000300")
        self.assertEqual(_to_sina_tx_symbol("bj920748"), "bj920748")

    def test_bare_codes_unchanged(self):
        self.assertEqual(_to_sina_tx_symbol("600519"), "sh600519")
        self.assertEqual(_to_sina_tx_symbol("000001"), "sz000001")
        self.assertEqual(_to_sina_tx_symbol("920748"), "bj920748")
        self.assertEqual(_to_sina_tx_symbol("900901"), "sh900901")


class HistoryCodeCandidatesIndexTestCase(unittest.TestCase):
    def test_index_canonical_bucket_preserved(self):
        from src.services.history_loader import _history_code_candidates as hc

        candidates, normalized = hc("sh000016")
        self.assertEqual(normalized, "sh000016")
        self.assertIn("sh000016", candidates)

        candidates, normalized = hc("csi930955")
        self.assertEqual(normalized, "csi930955")
        self.assertIn("csi930955", candidates)

    def test_stock_candidates_unchanged(self):
        from src.services.history_loader import _history_code_candidates as hc

        _, normalized = hc("600519")
        self.assertEqual(normalized, "600519")
        _, normalized = hc("1810.HK")
        self.assertEqual(normalized, "HK01810")

    def test_data_tools_candidates_preserve_index_canonical(self):
        from src.agent.tools.data_tools import _history_code_candidates as dc

        _, normalized = dc("sh000016")
        self.assertEqual(normalized, "sh000016")
        _, normalized = dc("csi930955")
        self.assertEqual(normalized, "csi930955")


class EfinanceIndexQuoteTestCase(unittest.TestCase):
    def _fetcher(self):
        with patch(
            "data_provider.efinance_fetcher.get_config",
            return_value=SimpleNamespace(enable_eastmoney_patch=False),
        ):
            return EfinanceFetcher(sleep_min=0, sleep_max=0)

    @patch("data_provider.efinance_fetcher.requests.get")
    def test_sh_index_quote_parsed(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {
                        "f43": 2905.08,
                        "f44": 2914.18,
                        "f45": 2870.42,
                        "f46": 2871.89,
                        "f47": 45323454,
                        "f48": 140152858404.0,
                        "f57": "000016",
                        "f58": "上证50",
                        "f60": 2875.51,
                        "f168": 0.28,
                        "f169": 29.57,
                        "f170": 1.03,
                        "f171": 1.52,
                    }
                }
            ),
        )
        quote = self._fetcher().get_index_realtime_quote("sh000016")
        self.assertIsNotNone(quote)
        self.assertEqual(quote.code, "sh000016")
        self.assertEqual(quote.name, "上证50")
        self.assertEqual(quote.price, 2905.08)
        self.assertEqual(quote.source, RealtimeSource.EFINANCE)
        self.assertEqual(mock_get.call_args.kwargs["params"]["secid"], "1.000016")

    @patch("data_provider.efinance_fetcher.requests.get")
    def test_csi_index_secid(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"data": {"f43": 11365.47, "f58": "红利低波100"}}
            ),
        )
        quote = self._fetcher().get_index_realtime_quote("csi930955")
        self.assertIsNotNone(quote)
        self.assertEqual(quote.price, 11365.47)
        self.assertEqual(mock_get.call_args.kwargs["params"]["secid"], "2.930955")

    def test_non_index_returns_none(self):
        self.assertIsNone(self._fetcher().get_index_realtime_quote("600519"))

    def test_get_realtime_quote_delegates_index(self):
        fetcher = self._fetcher()
        with patch.object(
            fetcher, "get_index_realtime_quote", return_value=_quote("sh000016")
        ) as mock_idx:
            quote = fetcher.get_realtime_quote("sh000016")
        mock_idx.assert_called_once_with("sh000016")
        self.assertIsNotNone(quote)


class AugmentRealtimeIndexMarketTestCase(unittest.TestCase):
    def test_index_market_passed_avoids_market_for_stock(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = SimpleNamespace(enable_realtime_technical_indicators=True)
        df = pd.DataFrame(
            [
                {
                    "code": "csi930955",
                    "date": date(2026, 8, 25),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 100,
                    "amount": 0,
                    "pct_chg": 0,
                }
            ]
        )
        quote = SimpleNamespace(
            price=101.0,
            open_price=100.0,
            high=102.0,
            low=99.0,
            volume=200,
            amount=None,
            change_pct=1.0,
            pre_close=None,
        )
        with patch("src.core.pipeline.is_market_open", return_value=True), patch(
            "src.core.pipeline.get_market_now",
            return_value=datetime(2026, 8, 26, 15, 0),
        ) as mock_now, patch(
            "src.core.pipeline.get_market_for_stock", return_value=None
        ) as mock_market:
            result = pipeline._augment_historical_with_realtime(
                df, quote, "csi930955", market="cn"
            )
        self.assertEqual(len(result), 2)
        mock_market.assert_not_called()
        mock_now.assert_called_once_with("cn")


if __name__ == "__main__":
    unittest.main()
