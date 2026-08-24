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
            "growth": {"revenue_yoy": 10.0},
            "earnings": {"financial_report": {"net_profit_parent": 200.0}},
            "institution": {"company_profile": {"公司名称": "测试公司"}},
            "capital_flow": {"latest": {"main_in_flow": 10.0}},
            "belong_boards": [{"plate_code": "HK.TEST", "plate_name": "测试行业", "plate_type": "INDUSTRY"}],
            "source_chain": [{"provider": "futu.financials", "result": "ok", "duration_ms": 1}],
            "errors": [],
        }
        mock_adapter.return_value.get_fundamental_bundle.return_value = futu_bundle
        manager = self._make_manager()

        payload, err, ms, provider = manager._fetch_offshore_fundamental_bundle("HK00700", "hk", 10.0)

        self.assertIsNone(err)
        self.assertEqual(provider, "fundamental_bundle_futu")
        self.assertIs(payload, futu_bundle)
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
