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


class _CapturingPipeline:
    """Records the final ``process_single_stock`` kwargs for target assertions."""

    calls = []  # class-level so tests can assert via the fake module attribute

    def __init__(self, *args, **kwargs):
        pass

    def process_single_stock(self, *args, **kwargs):
        type(self).calls.append(kwargs)
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

    def test_submit_analysis_passes_parser_canonical_to_executor(self):
        """Real task-layer regression: TaskService must hand the executor the
        parser canonical ``csi930955`` (not the raw alias ``930955.CSI`` or the
        old uppercase ``CSI930955``) so the analysis pipeline receives one
        consistent identity for the same registered CSI index."""
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

        # Use the real resolver (not a mock): ``930955.CSI`` is a registered CSI
        # explicit identity and must converge to the parser canonical
        # ``csi930955``, which is what gets handed to the executor.
        result = service.submit_analysis("930955.CSI", report_type="simple", query_source="cli")

        self.assertEqual(result["code"], "csi930955")
        self.assertIn("args", captured)
        # executor.submit(self._run_analysis, code, task_id, ...) — code is arg[1]
        self.assertEqual(captured["args"][1], "csi930955")

    def test_submit_analysis_with_index_target_skips_resolver_and_keeps_canonical(self):
        """PR2: when an INDEX ``AnalysisTarget`` is supplied, ``submit_analysis``
        must use ``target.canonical_id`` verbatim and skip the stock-code
        resolver — otherwise ``sh000016`` would be rewritten to ``SH000016``."""
        from src.services.stock_list_parser import AnalysisTarget, ParseStatus

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

        target = AnalysisTarget(
            raw_input="sh000016",
            asset_type=ParseStatus.INDEX,
            canonical_id="sh000016",
            display_code="上证50",
            exchange="SH",
        )

        with patch("src.services.task_service.resolve_index_stock_code_for_analysis") as mock_resolve:
            result = service.submit_analysis(
                "sh000016", report_type="simple", query_source="cli",
                analysis_target=target,
            )

        mock_resolve.assert_not_called()
        self.assertEqual(result["code"], "sh000016")
        self.assertIn("args", captured)
        # executor.submit(self._run_analysis, code, task_id, ...) — code is arg[1]
        self.assertEqual(captured["args"][1], "sh000016")
        # analysis_target is the last positional arg handed to _run_analysis
        self.assertIs(captured["args"][-1], target)

    def test_submit_analysis_rejects_non_index_target(self):
        from src.services.stock_list_parser import parse_analysis_target

        service = TaskService()
        service._executor = MagicMock()
        target = parse_analysis_target("600519")

        with self.assertRaisesRegex(ValueError, "must be an INDEX target"):
            service.submit_analysis("600519", analysis_target=target)
        service._executor.submit.assert_not_called()

    def test_run_analysis_passes_index_target_to_pipeline(self):
        """PR2: the background task must forward the same ``analysis_target``
        to ``process_single_stock`` so the pipeline receives canonical code and
        the structured INDEX target together."""
        from src.services.stock_list_parser import AnalysisTarget, ParseStatus

        service = TaskService()
        service._tasks = {}
        service._tasks_lock = threading.Lock()

        fake_main = ModuleType("main")
        fake_main.StockAnalysisPipeline = _CapturingPipeline

        target = AnalysisTarget(
            raw_input="930955.CSI",
            asset_type=ParseStatus.INDEX,
            canonical_id="csi930955",
            display_code="红利低波100",
            exchange="CSI",
        )

        _CapturingPipeline.calls = []
        with patch.dict("sys.modules", {"main": fake_main}), patch(
            "src.config.get_config", return_value=SimpleNamespace()
        ):
            result = service._run_analysis(
                code="csi930955", task_id="task-index-1", analysis_target=target
            )

        self.assertFalse(result["success"])  # _CapturingPipeline returns failure
        self.assertEqual(len(_CapturingPipeline.calls), 1)
        call = _CapturingPipeline.calls[0]
        self.assertEqual(call["code"], "csi930955")
        self.assertIs(call["analysis_target"], target)


if __name__ == "__main__":
    import unittest

    unittest.main()
