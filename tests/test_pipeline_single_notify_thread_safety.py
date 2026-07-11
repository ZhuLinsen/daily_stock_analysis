# -*- coding: utf-8 -*-
"""
Regression tests for single-stock notification thread safety.
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline


def _make_result(code: str) -> AnalysisResult:
    return AnalysisResult(
        code=code,
        name=f"股票{code}",
        sentiment_score=80,
        trend_prediction="看多",
        operation_advice="持有",
        analysis_summary="测试结果",
    )


class _CriticalSectionTrackingNotifier:
    def __init__(self):
        self._state_lock = threading.Lock()
        self._inflight = 0
        self.max_inflight = 0
        self.calls = []
        self.is_available = MagicMock(return_value=True)
        self.generate_single_stock_report = MagicMock(
            side_effect=self._generate_single_stock_report
        )
        self.send = MagicMock(side_effect=self._send)

    def _enter(self, stage: str, code: str) -> None:
        with self._state_lock:
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)

        self.calls.append((stage, code, threading.current_thread().name))
        time.sleep(0.02)

        with self._state_lock:
            self._inflight -= 1

    def _generate_single_stock_report(self, result: AnalysisResult) -> str:
        self._enter("generate", result.code)
        return f"single:{result.code}"

    def _send(
        self,
        content: str,
        email_stock_codes=None,
        route_type=None,
        severity=None,
        dedup_key=None,
        cooldown_key=None,
    ) -> bool:
        stock_code = (email_stock_codes or ["unknown"])[0]
        self._enter("send", stock_code)
        return True


class TestPipelineSingleNotifyThreadSafety(unittest.TestCase):
    def test_process_single_stock_serializes_direct_notification_path(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetch_and_save_stock_data = MagicMock(return_value=(True, None))
        pipeline.notifier = _CriticalSectionTrackingNotifier()

        notify_barrier = threading.Barrier(2)

        def _analyze(code, report_type, query_id):
            notify_barrier.wait(timeout=10)
            return _make_result(code)

        pipeline.analyze_stock = MagicMock(side_effect=_analyze)

        results = []
        result_lock = threading.Lock()

        def _worker(code: str) -> None:
            result = pipeline.process_single_stock(
                code=code,
                single_stock_notify=True,
                analysis_query_id=f"query-{code}",
            )
            with result_lock:
                results.append(result)

        threads = [
            threading.Thread(target=_worker, args=(code,), name=f"notify-{code}")
            for code in ("000001", "600519")
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result is not None for result in results))
        self.assertEqual(pipeline.notifier.generate_single_stock_report.call_count, 2)
        self.assertEqual(pipeline.notifier.send.call_count, 2)
        self.assertEqual(pipeline.notifier.max_inflight, 1)
        self.assertCountEqual(
            [(stage, code) for stage, code, _ in pipeline.notifier.calls],
            [
                ("generate", "000001"),
                ("send", "000001"),
                ("generate", "600519"),
                ("send", "600519"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
