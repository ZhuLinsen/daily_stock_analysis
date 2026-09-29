# -*- coding: utf-8 -*-
"""Pipeline-level regression tests for TickFlow batch prefetch wiring."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline


def _make_result(code: str) -> AnalysisResult:
    return AnalysisResult(
        code=code,
        name=f"Stock{code}",
        sentiment_score=80,
        trend_prediction="bullish",
        operation_advice="hold",
        analysis_summary="ok",
        success=True,
    )


class _TrackingFetcherManager:
    def __init__(self, events):
        self.events = events

    def prefetch_daily_klines(self, stock_codes, days=30):
        self.events.append(("daily_prefetch", list(stock_codes), days))
        return len(stock_codes)

    def prefetch_realtime_quotes(self, stock_codes):
        self.events.append(("realtime_prefetch", list(stock_codes)))
        return len(stock_codes)

    def prefetch_stock_names(self, stock_codes, use_bulk=False):
        self.events.append(("name_prefetch", list(stock_codes), use_bulk))
        return len(stock_codes)


class TestTickFlowPipelinePrefetch(unittest.TestCase):
    def test_run_prefetches_daily_klines_before_realtime_and_stock_processing(self):
        events = []
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.max_workers = 1
        pipeline.fetcher_manager = _TrackingFetcherManager(events)
        pipeline._save_local_report = MagicMock()
        pipeline._send_notifications = MagicMock()
        pipeline.config = SimpleNamespace(
            stock_list=[],
            refresh_stock_list=lambda: None,
            single_stock_notify=False,
            report_type="simple",
            analysis_delay=0,
        )

        def _process(code, skip_analysis=False, single_stock_notify=False, report_type=None, analysis_query_id=None, current_time=None):
            events.append(("process", code))
            return _make_result(code)

        pipeline.process_single_stock = MagicMock(side_effect=_process)

        results = pipeline.run(
            stock_codes=["600519", "000001", "300750", "000858", "601318"],
            dry_run=False,
            send_notification=False,
        )

        self.assertEqual(len(results), 5)
        self.assertEqual(events[0][0], "daily_prefetch")
        self.assertEqual(events[0][2], 30)
        self.assertEqual(events[1][0], "realtime_prefetch")
        self.assertEqual(events[2][0], "name_prefetch")
        self.assertTrue(all(event[0] != "process" for event in events[:3]))
        self.assertEqual([event[0] for event in events[3:]], ["process"] * 5)


if __name__ == "__main__":
    unittest.main()
