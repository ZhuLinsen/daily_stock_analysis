# -*- coding: utf-8 -*-
"""
Regression tests for prefetch behavior in StockAnalysisPipeline.run().
"""

import os
import sys
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, call

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.core.pipeline import StockAnalysisPipeline


class TestPipelinePrefetchBehavior(unittest.TestCase):
    @staticmethod
    def _build_pipeline(process_result):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.max_workers = 1
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        pipeline.db.has_today_data.return_value = False
        pipeline.process_single_stock = MagicMock(return_value=process_result)
        pipeline.config = SimpleNamespace(
            stock_list=["000001"],
            refresh_stock_list=lambda: None,
            single_stock_notify=False,
            report_type="simple",
            analysis_delay=0,
        )
        return pipeline

    def test_run_dry_run_skips_stock_name_prefetch(self):
        pipeline = self._build_pipeline(process_result=None)

        pipeline.run(stock_codes=["000001"], dry_run=True, send_notification=False)

        pipeline.fetcher_manager.prefetch_stock_names.assert_not_called()

    def test_run_non_dry_run_prefetches_stock_names(self):
        pipeline = self._build_pipeline(process_result=SimpleNamespace(code="000001"))

        pipeline.run(stock_codes=["000001"], dry_run=False, send_notification=False)

        pipeline.fetcher_manager.prefetch_stock_names.assert_called_once_with(
            ["000001"], use_bulk=False
        )

    def test_run_dry_run_counts_existing_data_by_effective_trading_date(self):
        pipeline = self._build_pipeline(process_result=None)
        pipeline._resolve_resume_target_date = MagicMock(
            side_effect=[date(2026, 3, 27), date(2026, 3, 26)]
        )
        pipeline.db.has_today_data.side_effect = [True, False]

        pipeline.run(
            stock_codes=["600519", "AAPL"],
            dry_run=True,
            send_notification=False,
        )

        self.assertEqual(
            pipeline.db.has_today_data.call_args_list,
            [
                call("600519", date(2026, 3, 27)),
                call("AAPL", date(2026, 3, 26)),
            ],
        )

    def test_run_uses_one_frozen_reference_time_for_tasks_and_dry_run_stats(self):
        pipeline = self._build_pipeline(process_result=None)
        pipeline._resolve_resume_target_date = MagicMock(
            side_effect=[date(2026, 3, 27), date(2026, 3, 26)]
        )
        pipeline.db.has_today_data.side_effect = [True, False]

        pipeline.run(
            stock_codes=["600519", "AAPL"],
            dry_run=True,
            send_notification=False,
        )

        task_reference_times = [
            call.kwargs["current_time"]
            for call in pipeline.process_single_stock.call_args_list
        ]
        stats_reference_times = [
            call.kwargs["current_time"]
            for call in pipeline._resolve_resume_target_date.call_args_list
        ]

        self.assertEqual(len(task_reference_times), 2)
        self.assertEqual(len(stats_reference_times), 2)
        self.assertEqual(len({id(value) for value in task_reference_times}), 1)
        self.assertEqual(len({id(value) for value in stats_reference_times}), 1)
        self.assertIs(task_reference_times[0], stats_reference_times[0])


if __name__ == "__main__":
    unittest.main()
