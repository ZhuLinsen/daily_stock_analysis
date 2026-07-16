from __future__ import annotations

import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, call, patch

import main
from src.services.runtime_scheduler import RuntimeSchedulerService


class MainPortfolioTest(unittest.TestCase):
    def test_parse_arguments_accepts_futu_portfolio(self):
        with patch.object(sys, "argv", ["main.py", "--portfolio", "FUTU"]):
            args = main.parse_arguments()

        self.assertEqual(args.portfolio, "futu")

    def test_resolve_portfolio_stock_codes_uses_futu_loader(self):
        args = SimpleNamespace(portfolio="futu")
        with patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=["aapl", "HK01810"],
        ) as loader:
            result = main._resolve_portfolio_stock_codes(args)

        self.assertEqual(result, ["AAPL", "HK01810"])
        loader.assert_called_once_with()

    def test_resolve_portfolio_stock_codes_returns_none_when_disabled(self):
        self.assertIsNone(main._resolve_portfolio_stock_codes(SimpleNamespace()))

    def test_run_full_analysis_uses_futu_holdings_and_reloads_each_run(self):
        args = SimpleNamespace(
            portfolio="futu",
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=True,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=False,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []
        trading_day_filter = MagicMock(
            return_value=(["AAPL", "HK00700"], "us,hk", False)
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            trading_day_filter,
        ), patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=["AAPL", "HK00700"],
        ) as loader, patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager:
            feishu_manager.return_value.is_configured.return_value = False
            first_result = main.run_full_analysis(config, args, ["600519"])
            second_result = main.run_full_analysis(config, args, ["600519"])

        self.assertTrue(first_result)
        self.assertTrue(second_result)
        self.assertEqual(loader.call_count, 2)
        config.refresh_stock_list.assert_not_called()
        self.assertEqual(trading_day_filter.call_count, 2)
        trading_day_filter.assert_has_calls(
            [
                call(config, args, ["AAPL", "HK00700"]),
                call(config, args, ["AAPL", "HK00700"]),
            ]
        )
        self.assertEqual(pipeline.run.call_count, 2)
        for invocation in pipeline.run.call_args_list:
            self.assertEqual(invocation.kwargs["stock_codes"], ["AAPL", "HK00700"])

    def test_runtime_scheduler_preserves_futu_portfolio_override(self):
        scheduler = RuntimeSchedulerService(
            owns_schedule=False,
            schedule_args_overrides={"portfolio": "futu"},
        )

        self.assertEqual(scheduler._make_schedule_args().portfolio, "futu")


if __name__ == "__main__":
    unittest.main()
