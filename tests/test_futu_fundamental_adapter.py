import unittest
from unittest.mock import Mock

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
        self.assertEqual(bundle["belong_boards"][0]["plate_name"], "测试行业")
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
