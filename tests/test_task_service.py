# -*- coding: utf-8 -*-
"""
Regression tests for TaskService failure handling.
"""

import os
import sys
import unittest
import threading
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import AnalysisResult
from src.services.task_service import TaskService


def _make_failed_result(code: str) -> AnalysisResult:
    return AnalysisResult(
        code=code,
        name=f"股票{code}",
        sentiment_score=80,
        trend_prediction="看多",
        operation_advice="持有",
        analysis_summary="解析失败",
        success=False,
        error_message="JSON 解析失败",
    )


class _FakePipeline:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def process_single_stock(self, *args, **kwargs):
        return _make_failed_result(kwargs["code"])


class TestTaskService(unittest.TestCase):
    def test_run_analysis_marks_failed_for_unsuccessful_result(self):
        service = TaskService()
        service._tasks = {}
        service._tasks_lock = threading.Lock()

        fake_main = ModuleType("main")
        fake_main.StockAnalysisPipeline = _FakePipeline

        with patch.dict("sys.modules", {"main": fake_main}), patch(
            "src.config.get_config", return_value=SimpleNamespace()
        ):
            result = service._run_analysis(code="600519", task_id="task-1")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "JSON 解析失败")
        task = service.get_task_status("task-1")
        self.assertIsNotNone(task)
        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["error"], "JSON 解析失败")
        self.assertIsNone(task["result"])

    def test_submit_analysis_resolves_bare_jp_kr_code_before_submit(self):
        service = TaskService()
        service._tasks = {}
        service._tasks_lock = threading.Lock()
        captured = {}

        executor = MagicMock()

        def capture_submit(*args, **kwargs):
            captured["args"] = args
            return "future"

        executor.submit.side_effect = capture_submit
        service._executor = executor

        with patch("src.services.task_service.resolve_index_stock_code_for_analysis", return_value="005930.KS"):
            result = service.submit_analysis("005930", report_type="simple", query_source="cli")

        self.assertEqual(result["code"], "005930.KS")
        self.assertIn("args", captured)
        self.assertEqual(captured["args"][1], "005930.KS")


if __name__ == "__main__":
    import unittest

    unittest.main()
