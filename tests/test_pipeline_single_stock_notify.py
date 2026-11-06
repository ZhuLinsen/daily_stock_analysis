# -*- coding: utf-8 -*-
"""
Regression tests for single-stock notification behavior in StockAnalysisPipeline.
"""

import os
import tempfile
import sys
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

import src.notification as notification_module
from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType


class _TrackingNotifier:
    def __init__(self):
        self.thread_names = []
        self.email_stock_codes = []
        self.sent_reports = []
        self.saved_reports = []
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
        self.save_report_to_file = MagicMock(side_effect=self._save_report_to_file)
        self.send = MagicMock(side_effect=self._send)

    def _save_report_to_file(self, content, filename=None):
        self.saved_reports.append((content, filename))
        return f"/tmp/{filename or 'report.md'}"

    def _send(
        self,
        content,
        email_stock_codes=None,
        route_type=None,
        severity=None,
        dedup_key=None,
        cooldown_key=None,
    ):
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
    _FROZEN_REPORT_TIME = datetime(2030, 1, 2, 12, 0, 0)

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

        with patch("src.core.pipeline.datetime") as mock_datetime:
            mock_datetime.now.return_value = self._FROZEN_REPORT_TIME
            result = pipeline.process_single_stock(
                code="600519",
                skip_analysis=False,
                single_stock_notify=True,
                report_type=ReportType.BRIEF,
                analysis_query_id="query-1",
            )

        self.assertIsNotNone(result)
        pipeline.notifier.generate_brief_report.assert_called_once_with([result])
        save_call = pipeline.notifier.save_report_to_file.call_args
        self.assertEqual(save_call.args[0], "brief:600519")
        self.assertEqual(save_call.kwargs["filename"], "report_20300102_600519.md")
        pipeline.notifier.send.assert_called_once_with(
            "brief:600519",
            email_stock_codes=["600519"],
            route_type="report",
            severity="info",
            dedup_key="report:single:600519:brief",
            cooldown_key="report:single:600519:brief",
        )

    def test_process_single_stock_saves_report_even_when_notifier_is_unavailable(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetch_and_save_stock_data = MagicMock(return_value=(True, None))
        pipeline.analyze_stock = MagicMock(return_value=_make_result("600519"))
        pipeline.notifier = _TrackingNotifier()
        pipeline.notifier.is_available.return_value = False

        with patch("src.core.pipeline.datetime") as mock_datetime:
            mock_datetime.now.return_value = self._FROZEN_REPORT_TIME
            result = pipeline.process_single_stock(
                code="600519",
                skip_analysis=False,
                single_stock_notify=True,
                report_type=ReportType.SIMPLE,
                analysis_query_id="query-1",
            )

        self.assertIsNotNone(result)
        save_call = pipeline.notifier.save_report_to_file.call_args
        self.assertEqual(save_call.args[0], "single:600519")
        self.assertEqual(save_call.kwargs["filename"], "report_20300102_600519.md")
        pipeline.notifier.send.assert_not_called()

    def test_process_single_stock_updates_saved_diagnostics_after_notification(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetch_and_save_stock_data = MagicMock(return_value=(True, None))
        pipeline.analyze_stock = MagicMock(return_value=_make_result("600519"))
        pipeline.notifier = _TrackingNotifier()
        pipeline.db = MagicMock()
        pipeline.save_context_snapshot = True

        pipeline.process_single_stock(
            code="600519",
            skip_analysis=False,
            single_stock_notify=True,
            report_type=ReportType.SIMPLE,
            analysis_query_id="query-1",
        )

        pipeline.db.update_analysis_history_diagnostics.assert_called_once()
        kwargs = pipeline.db.update_analysis_history_diagnostics.call_args.kwargs
        self.assertEqual(kwargs["query_id"], "query-1")
        self.assertEqual(kwargs["code"], "600519")
        self.assertEqual(kwargs["diagnostics"]["query_id"], "query-1")
        self.assertEqual(kwargs["diagnostics"]["notification_runs"][-1]["status"], "success")

    def test_send_notifications_patches_saved_diagnostics_when_push_is_skipped(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.save_context_snapshot = True
        pipeline.db = MagicMock()
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        pipeline.notifier = MagicMock()
        pipeline.notifier.generate_aggregate_report.return_value = "report"
        results = [_make_result("000001"), _make_result("600519")]
        for index, result in enumerate(results):
            result.query_id = f"query-{index}"

        pipeline._send_notifications(results, ReportType.SIMPLE, skip_push=True)

        self.assertEqual(pipeline.db.update_analysis_history_diagnostics.call_count, 2)
        calls = pipeline.db.update_analysis_history_diagnostics.call_args_list
        self.assertEqual(calls[0].kwargs["query_id"], "query-0")
        self.assertEqual(calls[0].kwargs["code"], "000001")
        self.assertEqual(calls[0].kwargs["notification_runs"][0]["status"], "skipped")
        self.assertEqual(calls[1].kwargs["query_id"], "query-1")
        self.assertEqual(calls[1].kwargs["code"], "600519")

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
        pipeline.notifier.save_report_to_file.assert_not_called()
        pipeline.notifier.send.assert_not_called()

    def test_save_local_report_falls_back_when_notifier_save_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
            pipeline.notifier = MagicMock()
            pipeline.notifier.save_report_to_file = MagicMock(side_effect=OSError("permission denied"))
            pipeline.notifier.generate_aggregate_report = MagicMock(return_value="dashboard")
            pipeline.notifier.generate_dashboard_report = MagicMock(return_value="dashboard")

            with patch.object(
                StockAnalysisPipeline,
                "_report_output_dir",
                return_value=Path(temp_dir),
            ):
                result_path = pipeline._save_local_report([_make_result("600519")], ReportType.SIMPLE)

            self.assertIsNotNone(result_path)
            self.assertTrue(result_path.startswith(temp_dir))
            self.assertEqual(pipeline._last_local_report_path, result_path)
            self.assertIsNone(pipeline._last_local_report_error)
            pipeline.notifier.save_report_to_file.assert_called_once()
            self.assertTrue(Path(result_path).exists())

    def test_save_local_report_records_explicit_error_when_notifier_returns_empty_path(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = MagicMock()
        pipeline.notifier.save_report_to_file = MagicMock(return_value=None)
        pipeline.notifier.generate_aggregate_report = MagicMock(return_value="dashboard")
        pipeline.notifier.generate_dashboard_report = MagicMock(return_value="dashboard")

        with patch.object(
            StockAnalysisPipeline,
            "_fallback_save_report_to_file",
            return_value=None,
        ):
            result_path = pipeline._save_local_report([_make_result("600519")], ReportType.SIMPLE)

        self.assertIsNone(result_path)
        self.assertIsNone(pipeline._last_local_report_path)
        self.assertEqual(
            pipeline._last_local_report_error,
            "notifier returned empty report path",
        )

    def test_fallback_report_output_dir_matches_notification_service(self):
        self.assertEqual(
            StockAnalysisPipeline._report_output_dir(),
            Path(notification_module.__file__).resolve().parent.parent / "reports",
        )


if __name__ == "__main__":
    unittest.main()
