# -*- coding: utf-8 -*-
"""
Regression tests for single-stock notification behavior in StockAnalysisPipeline.
"""

import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType


class _TrackingNotifier:
    def __init__(self):
        self.thread_names = []
        self.email_stock_codes = []
        self.sent_reports = []
        self._lock = threading.Lock()
        self._inflight = 0
        self.max_inflight = 0
        self.is_available = MagicMock(return_value=True)
        self.generate_dashboard_report = MagicMock(
            side_effect=lambda results: "dashboard:" + ",".join(r.code for r in results)
        )
        self.generate_brief_report = MagicMock(
            side_effect=lambda results: "brief:" + ",".join(r.code for r in results)
        )
        self.generate_single_stock_report = MagicMock(
            side_effect=lambda result: f"single:{result.code}"
        )
        self.send = MagicMock(side_effect=self._send)

    def _send(self, content, email_stock_codes=None):
        with self._lock:
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)

        self.thread_names.append(threading.current_thread().name)
        self.email_stock_codes.append(email_stock_codes)
        self.sent_reports.append(content)
        time.sleep(0.01)

        with self._lock:
            self._inflight -= 1

        return True


def _make_result(code: str, success: bool = True) -> AnalysisResult:
    return AnalysisResult(
        code=code,
        name=f"股票{code}",
        sentiment_score=80,
        trend_prediction="看多",
        operation_advice="持有",
        analysis_summary="测试结果",
        success=success,
        error_message=None if success else "JSON解析失败",
    )


class TestPipelineSingleStockNotify(unittest.TestCase):
    @staticmethod
    def _build_batch_pipeline() -> StockAnalysisPipeline:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.max_workers = 2
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        pipeline.db.has_today_data.return_value = False
        pipeline.notifier = _TrackingNotifier()
        pipeline._save_local_report = MagicMock()
        pipeline._send_notifications = MagicMock()
        pipeline.config = SimpleNamespace(
            stock_list=["000001", "600519"],
            refresh_stock_list=lambda: None,
            single_stock_notify=True,
            report_type="simple",
            analysis_delay=0,
        )
        return pipeline

    def test_run_single_stock_notify_serializes_notifications_on_main_thread(self):
        pipeline = self._build_batch_pipeline()
        worker_calls = []

        def _process(code, skip_analysis=False, single_stock_notify=False, report_type=None, analysis_query_id=None, current_time=None):
            worker_calls.append((code, single_stock_notify, threading.current_thread().name))
            if single_stock_notify:
                pipeline.notifier.send(f"worker:{code}", email_stock_codes=[code])
            return _make_result(code)

        pipeline.process_single_stock = MagicMock(side_effect=_process)

        results = pipeline.run(
            stock_codes=["000001", "600519"],
            dry_run=False,
            send_notification=True,
        )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(not single_stock_notify for _, single_stock_notify, _ in worker_calls))
        self.assertEqual(
            pipeline.notifier.thread_names,
            [threading.current_thread().name, threading.current_thread().name],
        )
        self.assertEqual(pipeline.notifier.max_inflight, 1)
        self.assertCountEqual(pipeline.notifier.sent_reports, ["single:000001", "single:600519"])
        self.assertCountEqual(pipeline.notifier.email_stock_codes, [["000001"], ["600519"]])
        pipeline._save_local_report.assert_called_once()
        pipeline._send_notifications.assert_called_once()
        _, kwargs = pipeline._send_notifications.call_args
        self.assertTrue(kwargs["skip_push"])

    def test_process_single_stock_direct_path_keeps_notify_compatibility(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetch_and_save_stock_data = MagicMock(return_value=(True, None))
        pipeline.analyze_stock = MagicMock(return_value=_make_result("600519"))
        pipeline.notifier = _TrackingNotifier()

        result = pipeline.process_single_stock(
            code="600519",
            skip_analysis=False,
            single_stock_notify=True,
            report_type=ReportType.BRIEF,
            analysis_query_id="query-1",
        )

        self.assertIsNotNone(result)
        pipeline.notifier.generate_brief_report.assert_called_once_with([result])
        pipeline.notifier.send.assert_called_once_with(
            "brief:600519",
            email_stock_codes=["600519"],
        )

    def test_process_single_stock_direct_path_does_not_notify_when_failed(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetch_and_save_stock_data = MagicMock(return_value=(True, None))
        pipeline.analyze_stock = MagicMock(return_value=_make_result("600519", success=False))
        pipeline.notifier = _TrackingNotifier()

        result = pipeline.process_single_stock(
            code="600519",
            skip_analysis=False,
            single_stock_notify=True,
            report_type=ReportType.BRIEF,
            analysis_query_id="query-1",
        )

        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        pipeline.notifier.generate_brief_report.assert_not_called()
        pipeline.notifier.send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
