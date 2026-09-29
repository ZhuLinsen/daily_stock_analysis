import unittest
from unittest.mock import Mock, patch

import pandas as pd

from data_provider.futu_fundamental_adapter import FutuFundamentalAdapter


class TestFutuFundamentalAdapter(unittest.TestCase):
    def _fetcher(self):
        fetcher = Mock()
        fetcher.get_stock_basicinfo.return_value = pd.DataFrame(
            [["HK.01810", "测试公司-W", 200, False, "2018-07-09", "HK_MAINBOARD"]],
            columns=["code", "name", "lot_size", "suspension", "listing_date", "exchange_type"],
        )
        fetcher.get_company_profile.return_value = pd.DataFrame(
            [["公司名称", "测试公司", 0]],
            columns=["name", "value", "field_type"],
        )
        fetcher.get_financials_statements.return_value = {
            "report_list": [
                {
                    "date_time_str": "2026-06-30",
                    "period_text": "2026/Q2",
                    "currency_code": "CNY",
                    "item_list": [
                        {"display_name": "营业总收入", "data": 1000.0, "yoy": 10.0},
                        {"display_name": "归属母公司净利润", "data": 200.0, "yoy": 20.0},
                        {"display_name": "毛利", "data": 400.0, "yoy": 15.0},
                        {"display_name": "基本每股收益", "data": 0.2},
                    ],
                }
            ]
        }
        fetcher.get_corporate_actions_dividends.return_value = {"dividend_list": []}
        fetcher.get_corporate_actions_stock_splits.return_value = {"split_list": []}
        fetcher.get_capital_flow.return_value = pd.DataFrame(
            [{"capital_flow_item_time": "2026-08-21", "main_in_flow": 10.0}]
        )
        fetcher.get_owner_plate.return_value = pd.DataFrame(
            [{"plate_code": "HK.TEST", "plate_name": "测试行业", "plate_type": "INDUSTRY"}]
        )
        return fetcher

    def test_normalizes_all_supported_blocks(self):
        fetcher = self._fetcher()
        bundle = FutuFundamentalAdapter(fetcher).get_fundamental_bundle("HK01810")

        self.assertEqual(bundle["status"], "partial")
        self.assertEqual(bundle["growth"]["revenue_yoy"], 10.0)
        self.assertEqual(bundle["growth"]["gross_margin"], 40.0)
        self.assertEqual(bundle["earnings"]["financial_report"]["net_profit_parent"], 200.0)
        self.assertEqual(bundle["institution"]["company_profile"]["公司名称"], "测试公司")
        self.assertEqual(bundle["capital_flow"]["latest"]["main_in_flow"], 10.0)
        self.assertEqual(bundle["belong_boards"][0]["name"], "测试行业")
        self.assertEqual(bundle["belong_boards"][0]["code"], "HK.TEST")
        self.assertEqual(bundle["belong_boards"][0]["type"], "INDUSTRY")
        self.assertEqual(bundle["institution"]["static_info"]["lot_size"], 200)
        self.assertFalse(bundle["institution"]["static_info"]["suspension"])
        self.assertEqual(bundle["institution"]["company_profile"]["公司名称"], "测试公司")
        self.assertEqual(fetcher.get_financials_statements.call_count, 4)
        called_types = {
            call.kwargs["statement_type"]
            for call in fetcher.get_financials_statements.call_args_list
        }
        self.assertEqual(called_types, {1, 2, 3, 4})

    def test_empty_corporate_actions_are_supported_empty_data(self):
        fetcher = self._fetcher()
        fetcher.request_trading_days.return_value = [
            {"time": "2026-08-24", "trade_date_type": "WHOLE"}
        ]
        bundle = FutuFundamentalAdapter(fetcher).get_fundamental_bundle("HK01810")

        self.assertEqual(bundle["earnings"]["dividend"]["events"], [])
        self.assertEqual(bundle["earnings"]["stock_splits"], [])
        self.assertNotIn("dividends:", " ".join(bundle["errors"]))
        self.assertNotIn("splits:", " ".join(bundle["errors"]))

    def test_normalizes_trading_days(self):
        from data_provider.futu_fetcher import FutuFetcher

        fetcher = FutuFetcher()
        fetcher.request_trading_days = Mock(
            return_value=[
                {"time": "2026-08-24", "trade_date_type": "WHOLE"},
                {"time": "", "trade_date_type": "WHOLE"},
                {"bad": True},
            ]
        )
        self.assertEqual(
            fetcher.get_trading_days("2026-08-24", "2026-08-24"),
            [{"date": "2026-08-24", "trade_date_type": "WHOLE"}],
        )

    def test_one_endpoint_failure_does_not_discard_other_blocks(self):
        fetcher = self._fetcher()
        fetcher.get_financials_statements.return_value = None
        bundle = FutuFundamentalAdapter(fetcher).get_fundamental_bundle("HK01810")

        self.assertEqual(bundle["institution"]["company_profile"]["公司名称"], "测试公司")
        self.assertTrue(any(error.startswith("financials_") for error in bundle["errors"]))
        self.assertEqual(bundle["status"], "partial")


if __name__ == "__main__":
    unittest.main()


class TestFutuFundamentalIntegration(unittest.TestCase):
    """Ensure get_fundamental_context() hits the Futu bundle for HK when configured."""

    def _make_manager(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        if "litellm" not in sys.modules:
            sys.modules["litellm"] = MagicMock()
        if "json_repair" not in sys.modules:
            sys.modules["json_repair"] = MagicMock()

        from data_provider.base import DataFetcherManager

        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._futu_fundamental_fetcher = None
        manager._yfinance_fundamental_adapter = Mock()
        manager._yfinance_fundamental_adapter.get_fundamental_bundle.return_value = {
            "status": "not_supported", "growth": {}, "earnings": {},
            "belong_boards": [], "source_chain": [], "errors": [],
        }
        manager._fundamental_adapter = Mock()
        manager._fundamental_cache = {}
        manager._fundamental_cache_lock = __import__("threading").RLock()
        manager._fundamental_timeout_worker_limit = 8
        manager._fundamental_timeout_slots = __import__("threading").BoundedSemaphore(8)
        manager._run_with_retry = Mock(side_effect=lambda task, timeout, name: (task(), None, 10))
        return manager

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("data_provider.futu_fundamental_adapter.FutuFundamentalAdapter")
    @patch("src.config.get_config")
    def test_fetch_offshore_bundle_prefers_futu_for_hk(self, mock_get_config, mock_adapter, mock_has_ep):
        from types import SimpleNamespace

        mock_get_config.return_value = SimpleNamespace()
        futu_bundle = {
            "status": "partial",
            "growth": {"revenue_yoy": 10.0, "net_profit_yoy": 12.0, "gross_margin": 40.0},
            "earnings": {
                "financial_report": {
                    "revenue": 1.0e10,
                    "net_profit_parent": 200.0,
                    "basic_eps": 1.2,
                    "gross_profit": 4.0e9,
                },
                "dividend": {
                    "events": [{"event_date": "2026-01-15", "ex_dividend_date": "2026-01-15", "cash_dividend_per_share": 3.5}],
                    "ttm_event_count": 2,
                    "ttm_cash_dividend_per_share": 7.0,
                    "ttm_dividend_yield_pct": 3.2,
                    "source": "futu",
                },
            },
            "institution": {"company_profile": {"公司名称": "测试公司"}},
            "capital_flow": {"latest": {"main_in_flow": 10.0}},
            "belong_boards": [{"name": "测试行业", "code": "HK.TEST", "type": "INDUSTRY"}],
            "source_chain": [{"provider": "futu.financials", "result": "ok", "duration_ms": 1}],
            "errors": [],
        }
        mock_adapter.return_value.get_fundamental_bundle.return_value = futu_bundle
        manager = self._make_manager()

        payload, err, ms, provider = manager._fetch_offshore_fundamental_bundle("HK00700", "hk", 10.0)

        self.assertIsNone(err)
        self.assertEqual(provider, "fundamental_bundle_futu")
        self.assertIs(payload, futu_bundle)
        # All core growth/earnings fields present -> no field gaps -> no yfinance call.
        self.assertEqual(manager._yfinance_fundamental_adapter.get_fundamental_bundle.call_count, 0)

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=False)
    @patch("src.config.get_config")
    def test_fetch_offshore_bundle_uses_yfinance_without_futu(self, mock_get_config, mock_has_ep):
        from types import SimpleNamespace

        mock_get_config.return_value = SimpleNamespace()
        manager = self._make_manager()
        manager._yfinance_fundamental_adapter.get_fundamental_bundle.return_value = {
            "status": "not_supported", "growth": {}, "earnings": {},
            "belong_boards": [], "source_chain": [], "errors": [],
        }

        payload, err, ms, provider = manager._fetch_offshore_fundamental_bundle("HK00700", "hk", 10.0)

        self.assertEqual(provider, "fundamental_bundle_yfinance")
        self.assertEqual(manager._yfinance_fundamental_adapter.get_fundamental_bundle.call_count, 1)

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("data_provider.futu_fundamental_adapter.FutuFundamentalAdapter")
    @patch("src.config.get_config")
    def test_fetch_offshore_bundle_falls_back_to_yfinance_when_futu_empty(self, mock_get_config, mock_adapter, mock_has_ep):
        from types import SimpleNamespace

        mock_get_config.return_value = SimpleNamespace()
        mock_adapter.return_value.get_fundamental_bundle.return_value = {
            "status": "not_supported", "growth": {}, "earnings": {},
            "institution": {}, "capital_flow": {}, "belong_boards": [],
            "source_chain": [], "errors": [],
        }
        manager = self._make_manager()
        manager._yfinance_fundamental_adapter.get_fundamental_bundle.return_value = {
            "status": "ok", "growth": {"revenue_yoy": 5.0}, "earnings": {},
            "belong_boards": [], "source_chain": [], "errors": [],
        }

        payload, err, ms, provider = manager._fetch_offshore_fundamental_bundle("HK00700", "hk", 10.0)

        self.assertEqual(provider, "fundamental_bundle_yfinance")
        self.assertEqual(payload["growth"]["revenue_yoy"], 5.0)

    def test_futu_boards_normalize_to_name_code_type_contract(self):
        """Futu OpenD plate_* fields must map to DSA's name/type/code contract."""
        from unittest.mock import Mock

        import pandas as pd

        fetcher = Mock()
        fetcher.get_owner_plate.return_value = pd.DataFrame(
            [{"plate_code": "HK.TEST", "plate_name": "测试行业", "plate_type": "INDUSTRY"}]
        )
        bundle = FutuFundamentalAdapter(fetcher).get_fundamental_bundle("HK01810")

        boards = bundle["belong_boards"]
        self.assertEqual(len(boards), 1)
        self.assertEqual(boards[0]["name"], "测试行业")
        self.assertEqual(boards[0]["code"], "HK.TEST")
        self.assertEqual(boards[0]["type"], "INDUSTRY")
        self.assertNotIn("plate_name", boards[0])
        self.assertNotIn("plate_code", boards[0])
        self.assertNotIn("plate_type", boards[0])

    def test_futu_boards_survive_extract_board_detail_fields(self):
        """HK Futu belong_boards must be consumable by the board-detail helper."""
        from src.utils.data_processing import extract_board_detail_fields

        snapshot = {
            "fundamental_context": {
                "market": "hk",
                "belong_boards": [{"name": "测试行业", "code": "HK.TEST", "type": "INDUSTRY"}],
            },
        }
        extracted = extract_board_detail_fields(snapshot)
        self.assertEqual(extracted["belong_boards"][0]["name"], "测试行业")
        self.assertEqual(extracted["belong_boards"][0]["code"], "HK.TEST")
        self.assertEqual(extracted["belong_boards"][0]["type"], "INDUSTRY")

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("data_provider.futu_fundamental_adapter.FutuFundamentalAdapter")
    @patch("src.config.get_config")
    def test_fetch_offshore_bundle_merges_yfinance_when_futu_missing_growth_earnings(
        self, mock_get_config, mock_adapter, mock_has_ep
    ):
        """Futu partial success must not drop growth/earnings that yfinance still provides."""
        from types import SimpleNamespace

        mock_get_config.return_value = SimpleNamespace()
        # Futu only has static info / capital flow / boards; statements failed.
        mock_adapter.return_value.get_fundamental_bundle.return_value = {
            "status": "partial",
            "growth": {},
            "earnings": {},
            "institution": {"company_profile": {"公司名称": "测试公司"}},
            "capital_flow": {"latest": {"main_in_flow": 10.0}},
            "belong_boards": [{"name": "测试行业", "code": "HK.TEST", "type": "INDUSTRY"}],
            "source_chain": [{"provider": "futu.financials", "result": "ok", "duration_ms": 1}],
            "errors": [],
        }
        manager = self._make_manager()
        manager._yfinance_fundamental_adapter.get_fundamental_bundle.return_value = {
            "status": "ok",
            "growth": {"revenue_yoy": 16.5, "net_profit_yoy": 19.3},
            "earnings": {"financial_report": {"net_profit_parent": 2.95e10}},
            "belong_boards": [],
            "source_chain": [{"provider": "yfinance.info", "result": "ok", "duration_ms": 1}],
            "errors": [],
        }

        payload, err, ms, provider = manager._fetch_offshore_fundamental_bundle("HK00700", "hk", 10.0)

        self.assertEqual(provider, "fundamental_bundle_futu")
        # yfinance growth/earnings merged in; Futu blocks kept.
        self.assertEqual(payload["growth"]["revenue_yoy"], 16.5)
        self.assertEqual(payload["growth"]["net_profit_yoy"], 19.3)
        self.assertEqual(payload["earnings"]["financial_report"]["net_profit_parent"], 2.95e10)
        self.assertEqual(payload["institution"]["company_profile"]["公司名称"], "测试公司")
        self.assertEqual(payload["belong_boards"][0]["name"], "测试行业")
        self.assertEqual(payload["status"], "partial")
        providers = [s.get("provider") for s in payload["source_chain"]]
        self.assertIn("futu.financials", providers)
        self.assertIn("yfinance.info", providers)

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("data_provider.futu_fundamental_adapter.FutuFundamentalAdapter")
    @patch("src.config.get_config")
    def test_fetch_offshore_bundle_merges_yfinance_when_futu_growth_is_all_none(
        self, mock_get_config, mock_adapter, mock_has_ep
    ):
        """Truthy but value-less growth/earnings (all-None) must still pull yfinance."""
        from types import SimpleNamespace

        mock_get_config.return_value = SimpleNamespace()
        # Futu _financials() writes the fixed key set even when every value is
        # None or display_name did not match the adapter aliases.
        mock_adapter.return_value.get_fundamental_bundle.return_value = {
            "status": "partial",
            "growth": {"revenue_yoy": None, "net_profit_yoy": None, "gross_margin": None},
            "earnings": {
                "financial_report": {"report_date": None, "period": "FY2025", "currency": None},
                "dividend": {},
            },
            "institution": {"company_profile": {"公司名称": "测试公司"}},
            "capital_flow": {"latest": {"main_in_flow": 10.0}},
            "belong_boards": [{"name": "测试行业", "code": "HK.TEST", "type": "INDUSTRY"}],
            "source_chain": [{"provider": "futu.financials", "result": "ok", "duration_ms": 1}],
            "errors": [],
        }
        manager = self._make_manager()
        manager._yfinance_fundamental_adapter.get_fundamental_bundle.return_value = {
            "status": "ok",
            "growth": {"revenue_yoy": 16.5, "net_profit_yoy": 19.3},
            "earnings": {"financial_report": {"net_profit_parent": 2.95e10}},
            "belong_boards": [],
            "source_chain": [{"provider": "yfinance.info", "result": "ok", "duration_ms": 1}],
            "errors": [],
        }

        payload, err, ms, provider = manager._fetch_offshore_fundamental_bundle("HK00700", "hk", 10.0)

        self.assertEqual(provider, "fundamental_bundle_futu")
        # All-None Futu growth replaced by meaningful yfinance values.
        self.assertEqual(payload["growth"]["revenue_yoy"], 16.5)
        self.assertEqual(payload["growth"]["net_profit_yoy"], 19.3)
        self.assertEqual(payload["earnings"]["financial_report"]["net_profit_parent"], 2.95e10)
        self.assertEqual(payload["institution"]["company_profile"]["公司名称"], "测试公司")
        providers = [s.get("provider") for s in payload["source_chain"]]
        self.assertIn("yfinance.info", providers)

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("data_provider.futu_fundamental_adapter.FutuFundamentalAdapter")
    @patch("src.config.get_config")
    def test_fetch_offshore_bundle_fills_partial_futu_fields_from_yfinance(
        self, mock_get_config, mock_adapter, mock_has_ep
    ):
        """Partial Futu hits (some core fields present) must not drop the rest."""
        from types import SimpleNamespace

        mock_get_config.return_value = SimpleNamespace()
        # Futu matched only some aliases: growth has revenue_yoy but net_profit_yoy
        # / gross_margin are None; earnings only has basic_eps.
        mock_adapter.return_value.get_fundamental_bundle.return_value = {
            "status": "partial",
            "growth": {"revenue_yoy": 10.0, "net_profit_yoy": None, "gross_margin": 40.0},
            "earnings": {"financial_report": {"basic_eps": 0.2}},
            "institution": {"company_profile": {"公司名称": "测试公司"}},
            "capital_flow": {},
            "belong_boards": [],
            "source_chain": [{"provider": "futu.financials", "result": "ok", "duration_ms": 1}],
            "errors": [],
        }
        manager = self._make_manager()
        manager._yfinance_fundamental_adapter.get_fundamental_bundle.return_value = {
            "status": "ok",
            "growth": {"revenue_yoy": 16.5, "net_profit_yoy": 19.3, "gross_margin": 47.8},
            "earnings": {
                "financial_report": {
                    "revenue": 1.11e11,
                    "net_profit_parent": 2.95e10,
                    "basic_eps": 1.9,
                }
            },
            "belong_boards": [],
            "source_chain": [{"provider": "yfinance.info", "result": "ok", "duration_ms": 1}],
            "errors": [],
        }

        payload, err, ms, provider = manager._fetch_offshore_fundamental_bundle("HK00700", "hk", 10.0)

        self.assertEqual(provider, "fundamental_bundle_futu")
        self.assertEqual(manager._yfinance_fundamental_adapter.get_fundamental_bundle.call_count, 1)
        # Futu-present fields stay; missing fields filled from yfinance.
        self.assertEqual(payload["growth"]["revenue_yoy"], 10.0)
        self.assertEqual(payload["growth"]["net_profit_yoy"], 19.3)
        self.assertEqual(payload["growth"]["gross_margin"], 40.0)
        self.assertEqual(payload["earnings"]["financial_report"]["basic_eps"], 0.2)
        self.assertEqual(payload["earnings"]["financial_report"]["revenue"], 1.11e11)
        self.assertEqual(payload["earnings"]["financial_report"]["net_profit_parent"], 2.95e10)
        providers = [s.get("provider") for s in payload["source_chain"]]
        self.assertIn("futu.financials", providers)
        self.assertIn("yfinance.info", providers)

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("data_provider.futu_fundamental_adapter.FutuFundamentalAdapter")
    @patch("src.config.get_config")
    def test_fetch_offshore_bundle_pulls_yfinance_when_futu_dividend_empty(
        self, mock_get_config, mock_adapter, mock_has_ep
    ):
        """Complete Futu growth/financial_report but empty dividend must still pull yfinance."""
        from types import SimpleNamespace

        mock_get_config.return_value = SimpleNamespace()
        mock_adapter.return_value.get_fundamental_bundle.return_value = {
            "status": "partial",
            "growth": {"revenue_yoy": 10.0, "net_profit_yoy": 12.0, "gross_margin": 40.0},
            "earnings": {
                "financial_report": {
                    "revenue": 1.0e10,
                    "net_profit_parent": 200.0,
                    "basic_eps": 1.2,
                    "gross_profit": 4.0e9,
                },
                "dividend": {"events": [], "source": "futu"},
            },
            "institution": {"company_profile": {"公司名称": "测试公司"}},
            "capital_flow": {"latest": {"main_in_flow": 10.0}},
            "belong_boards": [],
            "source_chain": [{"provider": "futu.financials", "result": "ok", "duration_ms": 1}],
            "errors": [],
        }
        manager = self._make_manager()
        manager._yfinance_fundamental_adapter.get_fundamental_bundle.return_value = {
            "status": "ok",
            "growth": {"revenue_yoy": 16.5},
            "earnings": {
                "financial_report": {"revenue": 1.11e11},
                "dividend": {
                    "events": [{"event_date": "2026-01-15", "ex_dividend_date": "2026-01-15", "cash_dividend_per_share": 3.5}],
                    "ttm_event_count": 2,
                    "ttm_cash_dividend_per_share": 7.0,
                    "ttm_dividend_yield_pct": 3.2,
                },
            },
            "belong_boards": [],
            "source_chain": [{"provider": "yfinance.info", "result": "ok", "duration_ms": 1}],
            "errors": [],
        }

        payload, err, ms, provider = manager._fetch_offshore_fundamental_bundle("HK00700", "hk", 10.0)

        self.assertEqual(provider, "fundamental_bundle_futu")
        self.assertEqual(manager._yfinance_fundamental_adapter.get_fundamental_bundle.call_count, 1)
        # Futu growth/earnings kept, dividend contract filled from yfinance.
        self.assertEqual(payload["growth"]["revenue_yoy"], 10.0)
        self.assertEqual(payload["earnings"]["financial_report"]["net_profit_parent"], 200.0)
        self.assertEqual(payload["earnings"]["dividend"]["ttm_cash_dividend_per_share"], 7.0)
        self.assertEqual(payload["earnings"]["dividend"]["ttm_dividend_yield_pct"], 3.2)
        self.assertEqual(payload["earnings"]["dividend"]["events"][0]["cash_dividend_per_share"], 3.5)
        providers = [s.get("provider") for s in payload["source_chain"]]
        self.assertIn("yfinance.info", providers)

    def test_dividends_normalize_opend_fields_to_repo_contract(self):
        """OpenD raw dividend fields (ex_date/record_date/statement) must map to the repo contract."""
        from unittest.mock import Mock

        fetcher = Mock()
        fetcher.get_financials_statements.return_value = {"report_list": []}
        fetcher.get_stock_basicinfo.return_value = {
            "static_info": {"lot_size": 200, "suspension": False},
            "company_profile": {"公司名称": "测试公司"},
        }
        fetcher.get_corporate_actions_dividends.return_value = {
            "dividend_list": [
                {
                    "ex_date": "2026-06-30",
                    "record_date": "2026-07-02",
                    "statement": "FY2025",
                    "dividend_per_share": 1.25,
                    "currency": "HKD",
                    "description": "Final dividend",
                },
                {
                    "ex_date": "2026-01-15",
                    "record_date": "2026-01-16",
                    "statement": "FY2024",
                    "dividend_per_share": 1.1,
                    "currency": "HKD",
                },
            ]
        }
        fetcher.get_corporate_actions_stock_splits.return_value = {"split_list": []}
        fetcher.get_capital_flow.return_value = None
        fetcher.get_owner_plate.return_value = None
        fetcher.get_realtime_quote.return_value = {"price": 50.0}

        bundle = FutuFundamentalAdapter(fetcher).get_fundamental_bundle("HK00700")

        dividend = bundle["earnings"]["dividend"]
        self.assertEqual(dividend["source"], "futu")
        self.assertEqual(dividend["events"][0]["event_date"], "2026-06-30")
        self.assertEqual(dividend["events"][0]["ex_dividend_date"], "2026-06-30")
        self.assertEqual(dividend["events"][0]["record_date"], "2026-07-02")
        self.assertEqual(dividend["events"][0]["cash_dividend_per_share"], 1.25)
        self.assertEqual(dividend["events"][0]["statement"], "FY2025")
        # TTM cash = 1.25 + 1.1, yield = ttm / price.
        self.assertEqual(dividend["ttm_event_count"], 2)
        self.assertEqual(dividend["ttm_cash_dividend_per_share"], 2.35)
        self.assertEqual(dividend["ttm_dividend_yield_pct"], round(2.35 / 50.0 * 100.0, 4))
        self.assertNotIn("ex_date", dividend["events"][0])

    def test_dividends_compute_yield_from_unified_quote_object(self):
        """Yield must be computed when get_realtime_quote returns a UnifiedRealtimeQuote dataclass."""
        from unittest.mock import Mock

        from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote

        fetcher = Mock()
        fetcher.get_financials_statements.return_value = {"report_list": []}
        fetcher.get_stock_basicinfo.return_value = {
            "static_info": {"lot_size": 200, "suspension": False},
            "company_profile": {"公司名称": "测试公司"},
        }
        fetcher.get_corporate_actions_dividends.return_value = {
            "dividend_list": [
                {"ex_date": "2026-06-30", "dividend_per_share": 1.25, "currency": "HKD"},
            ]
        }
        fetcher.get_corporate_actions_stock_splits.return_value = {"split_list": []}
        fetcher.get_capital_flow.return_value = None
        fetcher.get_owner_plate.return_value = None
        # Real FutuFetcher shape: UnifiedRealtimeQuote, not dict.
        fetcher.get_realtime_quote.return_value = UnifiedRealtimeQuote(
            code="HK00700", name="Tencent", price=50.0, source=RealtimeSource.FUTU
        )

        bundle = FutuFundamentalAdapter(fetcher).get_fundamental_bundle("HK00700")

        dividend = bundle["earnings"]["dividend"]
        self.assertEqual(dividend["ttm_cash_dividend_per_share"], 1.25)
        self.assertEqual(dividend["ttm_dividend_yield_pct"], round(1.25 / 50.0 * 100.0, 4))

    def test_dividends_missing_yield_when_quote_unavailable(self):
        """A failed/no-price realtime quote must leave a contract gap, not a complete block.

        The dividend block keeps events and TTM cash, but without a price the
        repo contract field ttm_dividend_yield_pct cannot be computed. This is
        the exact shape the manager's supplement logic must detect as a gap.
        """
        from unittest.mock import Mock

        fetcher = Mock()
        fetcher.get_financials_statements.return_value = {"report_list": []}
        fetcher.get_stock_basicinfo.return_value = {
            "static_info": {"lot_size": 200, "suspension": False},
            "company_profile": {"公司名称": "测试公司"},
        }
        fetcher.get_corporate_actions_dividends.return_value = {
            "dividend_list": [
                {"ex_date": "2026-06-30", "dividend_per_share": 1.25, "currency": "HKD"},
            ]
        }
        fetcher.get_corporate_actions_stock_splits.return_value = {"split_list": []}
        fetcher.get_capital_flow.return_value = None
        fetcher.get_owner_plate.return_value = None
        # OpenD quote snapshot unavailable / no price -> yield cannot be computed.
        fetcher.get_realtime_quote.return_value = None

        bundle = FutuFundamentalAdapter(fetcher).get_fundamental_bundle("HK00700")

        dividend = bundle["earnings"]["dividend"]
        self.assertEqual(dividend["ttm_cash_dividend_per_share"], 1.25)
        self.assertNotIn("ttm_dividend_yield_pct", dividend)
        self.assertEqual(dividend["events"][0]["cash_dividend_per_share"], 1.25)

    @patch("data_provider.futu_fetcher.FutuFetcher.has_configured_endpoint", return_value=True)
    @patch("data_provider.futu_fundamental_adapter.FutuFundamentalAdapter")
    @patch("src.config.get_config")
    def test_fetch_offshore_bundle_pulls_yfinance_when_futu_dividend_missing_yield(
        self, mock_get_config, mock_adapter, mock_has_ep
    ):
        """Futu dividend with TTM cash but no yield (quote price unavailable) must pull yfinance.

        The repo contract consumes ttm_cash_dividend_per_share and
        ttm_dividend_yield_pct together. When Futu keeps events + TTM cash but
        the extra realtime quote failed (no price -> no yield), the block must
        still count as a gap so yfinance can fill the missing yield instead of
        the notification rendering N/A.
        """
        from types import SimpleNamespace

        mock_get_config.return_value = SimpleNamespace()
        mock_adapter.return_value.get_fundamental_bundle.return_value = {
            "status": "partial",
            "growth": {"revenue_yoy": 10.0, "net_profit_yoy": 12.0, "gross_margin": 40.0},
            "earnings": {
                "financial_report": {
                    "revenue": 1.0e10,
                    "net_profit_parent": 200.0,
                    "basic_eps": 1.2,
                    "gross_profit": 4.0e9,
                },
                # Realistic shape after get_realtime_quote() returned None/0:
                # events + TTM cash are present, but yield is missing.
                "dividend": {
                    "events": [
                        {
                            "event_date": "2026-01-15",
                            "ex_dividend_date": "2026-01-15",
                            "cash_dividend_per_share": 3.5,
                        }
                    ],
                    "ttm_event_count": 2,
                    "ttm_cash_dividend_per_share": 7.0,
                    "source": "futu",
                },
            },
            "institution": {"company_profile": {"公司名称": "测试公司"}},
            "capital_flow": {"latest": {"main_in_flow": 10.0}},
            "belong_boards": [],
            "source_chain": [{"provider": "futu.financials", "result": "ok", "duration_ms": 1}],
            "errors": [],
        }
        manager = self._make_manager()
        manager._yfinance_fundamental_adapter.get_fundamental_bundle.return_value = {
            "status": "ok",
            "growth": {"revenue_yoy": 16.5},
            "earnings": {
                "financial_report": {"revenue": 1.11e11},
                "dividend": {
                    "events": [
                        {
                            "event_date": "2026-01-15",
                            "ex_dividend_date": "2026-01-15",
                            "cash_dividend_per_share": 3.5,
                        }
                    ],
                    "ttm_event_count": 2,
                    "ttm_cash_dividend_per_share": 7.0,
                    "ttm_dividend_yield_pct": 3.2,
                },
            },
            "belong_boards": [],
            "source_chain": [{"provider": "yfinance.info", "result": "ok", "duration_ms": 1}],
            "errors": [],
        }

        payload, err, ms, provider = manager._fetch_offshore_fundamental_bundle("HK00700", "hk", 10.0)

        self.assertEqual(provider, "fundamental_bundle_futu")
        self.assertEqual(manager._yfinance_fundamental_adapter.get_fundamental_bundle.call_count, 1)
        # Futu growth/earnings kept; the missing yield is filled from yfinance.
        self.assertEqual(payload["earnings"]["dividend"]["ttm_cash_dividend_per_share"], 7.0)
        self.assertEqual(payload["earnings"]["dividend"]["ttm_dividend_yield_pct"], 3.2)
        providers = [s.get("provider") for s in payload["source_chain"]]
        self.assertIn("yfinance.info", providers)

    def test_close_releases_futu_fundamental_fetcher(self):
        """DataFetcherManager.close() must close the cached HK Futu fundamental fetcher.

        The HK Futu fundamental path lazily caches its own FutuFetcher (an
        OpenQuoteContext-backed connection) on _futu_fundamental_fetcher.
        Explicit close / reload paths must release it, otherwise the OpenD
        connection stays open after manager cleanup.
        """
        from unittest.mock import Mock

        manager = self._make_manager()
        futu_fetcher = Mock()
        manager._futu_fundamental_fetcher = futu_fetcher

        manager.close()

        futu_fetcher.close.assert_called_once_with()
        self.assertIsNone(manager._futu_fundamental_fetcher)
