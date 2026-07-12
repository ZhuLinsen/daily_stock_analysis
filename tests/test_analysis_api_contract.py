# -*- coding: utf-8 -*-
"""Regression tests for analysis API/report-type contracts."""

import asyncio
from concurrent.futures import Future
from datetime import datetime
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

_ORIGINAL_ENVIRON = dict(os.environ)
_MODULE_TEMP_DIR = tempfile.TemporaryDirectory()
_MODULE_ENV_FILE = Path(_MODULE_TEMP_DIR.name) / ".env"
_MODULE_ENV_FILE.write_text("STOCK_LIST=600519,000001\n", encoding="utf-8")
os.environ["ENV_FILE"] = str(_MODULE_ENV_FILE)

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

try:
    from api.app import create_app
    from api.v1.endpoints import analysis as analysis_endpoint_module
    from api.v1.endpoints.analysis import (
        trigger_analysis,
        trigger_market_review,
        _handle_sync_analysis,
        _build_analysis_report,
        _load_sync_fundamental_sources,
        get_analysis_status,
        get_task_list,
    )
except Exception:  # pragma: no cover - optional dependency environments
    create_app = None
    analysis_endpoint_module = None
    trigger_analysis = None
    trigger_market_review = None
    _handle_sync_analysis = None
    _build_analysis_report = None
    _load_sync_fundamental_sources = None
    get_analysis_status = None
    get_task_list = None

from src.enums import ReportType
from src.services.analysis_service import AnalysisService
from src.services.image_stock_extractor import _call_litellm_vision
from src.services.task_queue import AnalysisTaskQueue, TaskStatus


def tearDownModule() -> None:
    current_test = os.environ.get("PYTEST_CURRENT_TEST")
    for key in list(os.environ):
        if key == "PYTEST_CURRENT_TEST":
            continue
        if key not in _ORIGINAL_ENVIRON:
            os.environ.pop(key, None)
    os.environ.update(_ORIGINAL_ENVIRON)
    if current_test is not None:
        os.environ["PYTEST_CURRENT_TEST"] = current_test
    _MODULE_TEMP_DIR.cleanup()


def _analysis_context_pack_overview() -> dict:
    return {
        "pack_version": "1.0",
        "created_at": "2026-04-10T08:30:00+00:00",
        "subject": {
            "code": "600519",
            "stock_name": "贵州茅台",
            "market": "cn",
        },
        "blocks": [
            {
                "key": "quote",
                "label": "行情",
                "status": "available",
                "source": "mock",
                "warnings": [],
                "missing_reasons": [],
            },
            {
                "key": "news",
                "label": "新闻",
                "status": "missing",
                "source": None,
                "warnings": [],
                "missing_reasons": ["news_context_missing"],
            },
        ],
        "counts": {
            "available": 1,
            "missing": 1,
            "not_supported": 0,
            "fallback": 0,
            "stale": 0,
            "estimated": 0,
            "partial": 0,
            "fetch_failed": 0,
        },
        "data_quality": {
            "overall_score": 88,
            "level": "good",
            "block_scores": {
                "quote": 100,
                "daily_bars": 100,
                "technical": 100,
                "news": 35,
                "fundamentals": 100,
                "chip": 100,
            },
            "limitations": [],
        },
        "warnings": ["news_context_missing"],
        "metadata": {
            "trigger_source": "api",
            "news_result_count": 0,
        },
    }


def _market_structure_context() -> dict:
    return {
        "schema_version": "market-structure-v1",
        "status": "partial",
        "market": "cn",
        "market_theme_context": {
            "schema_version": "market-theme-v1",
            "status": "partial",
            "market": "cn",
            "active_themes": [{"name": "机器人概念"}],
        },
        "stock_market_position": {
            "schema_version": "stock-market-position-v1",
            "status": "partial",
            "stock_code": "300024",
            "market": "cn",
            "primary_theme": {"name": "机器人概念"},
        },
    }


def _market_phase_summary() -> dict:
    return {
        "market": "cn",
        "phase": "intraday",
        "market_local_time": "2026-03-27T10:00:00+08:00",
        "session_date": "2026-03-27",
        "effective_daily_bar_date": "2026-03-26",
        "is_trading_day": True,
        "is_market_open_now": True,
        "is_partial_bar": True,
        "minutes_to_open": None,
        "minutes_to_close": 300,
        "trigger_source": "api",
        "analysis_intent": "auto",
        "warnings": ["partial_bar"],
    }


class AnalysisApiContractTestCase(unittest.TestCase):
    def test_trigger_market_review_accepts_background_task(self) -> None:
        if trigger_market_review is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")
        task_queue = MagicMock()
        task_queue.submit_background_task.return_value = SimpleNamespace(task_id="market-task-1")
        request = SimpleNamespace(send_notification=False)
        config = SimpleNamespace(trading_day_check_enabled=False)
        lock_token = object()

        with patch.object(
            analysis_endpoint_module,
            "_try_acquire_market_review_lock",
            return_value=lock_token,
        ), patch("api.v1.endpoints.analysis.get_task_queue", return_value=task_queue):
            response = trigger_market_review(
                request=request,
                config=config,
            )

        self.assertEqual(response.status, "accepted")
        self.assertFalse(response.send_notification)
        self.assertEqual(response.task_id, "market-task-1")
        task_queue.submit_background_task.assert_called_once()
        args, kwargs = task_queue.submit_background_task.call_args
        self.assertTrue(callable(args[0]))
        self.assertEqual(kwargs["stock_code"], "market_review")
        self.assertEqual(kwargs["stock_name"], "大盘复盘")
        self.assertEqual(kwargs["message"], "大盘复盘任务已提交")

    def test_trigger_market_review_accepts_request_level_report_language(self) -> None:
        if trigger_market_review is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        request = SimpleNamespace(send_notification=True, report_language="en")
        config = SimpleNamespace(trading_day_check_enabled=False, report_language="zh", market_review_region="cn")
        lock_token = object()
        task_payload: dict[str, object] = {}

        runtime_notifier = MagicMock()
        runtime_search = MagicMock()
        runtime_analyzer = MagicMock()

        task_queue = MagicMock()

        def _capture_background_task(task_fn, **kwargs):
            task_payload["background_task"] = task_fn
            return SimpleNamespace(task_id="market-task-1")

        task_queue.submit_background_task.side_effect = _capture_background_task

        with patch.object(
            analysis_endpoint_module,
            "_try_acquire_market_review_lock",
            return_value=lock_token,
        ), patch.object(
            analysis_endpoint_module,
            "_build_market_review_runtime",
            return_value=(runtime_notifier, runtime_analyzer, runtime_search),
        ), patch("src.core.market_review.run_market_review") as run_market_review, patch(
            "api.v1.endpoints.analysis.get_task_queue",
            return_value=task_queue,
        ), patch.object(
            analysis_endpoint_module,
            "_release_market_review_lock",
            return_value=None,
        ):
            trigger_market_review(request=request, config=config)
            self.assertIn("background_task", task_payload)
            task_payload["background_task"]()

        call_kwargs = run_market_review.call_args.kwargs
        self.assertEqual(call_kwargs["send_notification"], True)
        self.assertIsNone(call_kwargs["override_region"])
        self.assertEqual(call_kwargs["trigger_source"], "api")
        runtime_config = call_kwargs.get("config")
        self.assertIsNotNone(runtime_config)
        self.assertEqual(getattr(runtime_config, "report_language", None), "en")
        self.assertIsNot(runtime_config, config)

    def test_trigger_market_review_accepts_camel_case_report_language_alias(self) -> None:
        if trigger_market_review is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        request = analysis_endpoint_module.MarketReviewRequest.model_validate({
            "send_notification": True,
            "reportLanguage": "en",
        })
        config = SimpleNamespace(trading_day_check_enabled=False, report_language="zh", market_review_region="cn")
        task_payload: dict[str, object] = {}

        runtime_notifier = MagicMock()
        runtime_search = MagicMock()
        runtime_analyzer = MagicMock()

        task_queue = MagicMock()

        def _capture_background_task(task_fn, **kwargs):
            task_payload["background_task"] = task_fn
            return SimpleNamespace(task_id="market-task-1")

        task_queue.submit_background_task.side_effect = _capture_background_task

        with patch.object(
            analysis_endpoint_module,
            "_try_acquire_market_review_lock",
            return_value=object(),
        ), patch.object(
            analysis_endpoint_module,
            "_build_market_review_runtime",
            return_value=(runtime_notifier, runtime_analyzer, runtime_search),
        ), patch("src.core.market_review.run_market_review") as run_market_review, patch(
            "api.v1.endpoints.analysis.get_task_queue",
            return_value=task_queue,
        ), patch.object(
            analysis_endpoint_module,
            "_release_market_review_lock",
            return_value=None,
        ):
            response = trigger_market_review(request=request, config=config)
            self.assertEqual(response.status, "accepted")
            self.assertIn("background_task", task_payload)
            task_payload["background_task"]()

        call_kwargs = run_market_review.call_args.kwargs
        runtime_config = call_kwargs.get("config")
        self.assertEqual(getattr(runtime_config, "report_language", None), "en")
        self.assertEqual(call_kwargs["trigger_source"], "api")

    def test_trigger_market_review_rejects_duplicate_submission(self) -> None:
        if trigger_market_review is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        task_queue = MagicMock()
        request = SimpleNamespace(send_notification=True)
        config = SimpleNamespace(trading_day_check_enabled=False)

        with patch.object(
            analysis_endpoint_module,
            "_try_acquire_market_review_lock",
            return_value=None,
        ), patch("api.v1.endpoints.analysis.get_task_queue", return_value=task_queue):
            with self.assertRaises(Exception) as ctx:
                trigger_market_review(
                    request=request,
                    config=config,
                )

        self.assertEqual(getattr(ctx.exception, "status_code", None), 409)
        task_queue.submit_background_task.assert_not_called()

    def test_trigger_market_review_rejects_when_shared_lock_is_held(self) -> None:
        if trigger_market_review is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        from src.core.market_review_lock import (
            release_market_review_lock,
            try_acquire_market_review_lock,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            config = SimpleNamespace(
                trading_day_check_enabled=False,
                database_path=str(Path(temp_dir) / "stock_analysis.db"),
            )
            lock_token = try_acquire_market_review_lock(config)
            self.assertIsNotNone(lock_token)

            task_queue = MagicMock()
            try:
                with patch("api.v1.endpoints.analysis.get_task_queue", return_value=task_queue):
                    with self.assertRaises(Exception) as ctx:
                        trigger_market_review(
                            request=SimpleNamespace(send_notification=True),
                            config=config,
                        )
            finally:
                release_market_review_lock(lock_token)

        self.assertEqual(getattr(ctx.exception, "status_code", None), 409)
        task_queue.submit_background_task.assert_not_called()

    def test_trigger_market_review_submits_even_when_configured_markets_closed(self) -> None:
        if trigger_market_review is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        task_queue = MagicMock()
        task_queue.submit_background_task.return_value = SimpleNamespace(task_id="market-task-manual")
        request = SimpleNamespace(send_notification=True)
        config = SimpleNamespace(trading_day_check_enabled=True, market_review_region="cn")
        lock_token = object()

        with patch(
            "src.core.trading_calendar.get_open_markets_today",
            return_value=set(),
        ) as get_open_markets_today, patch(
            "src.core.trading_calendar.compute_effective_region",
            return_value="",
        ) as compute_effective_region, patch.object(
            analysis_endpoint_module,
            "_try_acquire_market_review_lock",
            return_value=lock_token,
        ) as acquire, patch("api.v1.endpoints.analysis.get_task_queue", return_value=task_queue):
            response = trigger_market_review(
                request=request,
                config=config,
            )

        self.assertEqual(response.status, "accepted")
        self.assertEqual(response.task_id, "market-task-manual")
        get_open_markets_today.assert_not_called()
        compute_effective_region.assert_not_called()
        acquire.assert_called_once_with(config)
        task_queue.submit_background_task.assert_called_once()

    def test_run_market_review_background_uses_configured_pipeline(self) -> None:
        if analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        config = SimpleNamespace(
            has_search_capability_enabled=lambda: True,
            bocha_api_keys=["bocha"],
            tavily_api_keys=["tavily"],
            anspire_api_keys=["anspire"],
            brave_api_keys=["brave"],
            serpapi_keys=["serpapi"],
            minimax_api_keys=["minimax"],
            searxng_base_urls=["http://searxng.local"],
            searxng_public_instances_enabled=False,
            news_max_age_days=5,
            news_strategy_profile="balanced",
            gemini_api_key="gemini-key",
            openai_api_key=None,
        )

        runtime_notifier = MagicMock()
        runtime_search = MagicMock()
        runtime_analyzer = MagicMock()
        with patch.object(
            analysis_endpoint_module,
            "_build_market_review_runtime",
            return_value=(runtime_notifier, runtime_analyzer, runtime_search),
        ), patch("src.core.market_review.run_market_review") as run_market_review:
            analysis_endpoint_module._run_market_review_background(
                send_notification=False,
                override_region="cn,us",
                lock_token=None,
                config=config,
            )

        run_market_review.assert_called_once_with(
            notifier=runtime_notifier,
            analyzer=runtime_analyzer,
            search_service=runtime_search,
            config=config,
            send_notification=False,
            override_region="cn,us",
            return_structured=True,
            trigger_source="api",
        )

    def test_market_review_runtime_initializes_analyzer_for_litellm_provider(self) -> None:
        if analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        config = SimpleNamespace(
            has_search_capability_enabled=lambda: False,
            gemini_api_key=None,
            openai_api_key=None,
            litellm_model="anthropic/claude-sonnet-4-6",
            llm_model_list=[],
            anthropic_api_keys=["sk-ant-test-value"],
        )

        with patch("src.notification.NotificationService"), \
             patch("src.analyzer.GeminiAnalyzer") as analyzer_cls:
            analyzer_cls.return_value.is_available.return_value = True

            _, analyzer, search_service = analysis_endpoint_module._build_market_review_runtime(config)

        analyzer_cls.assert_called_once_with(config=config)
        self.assertIs(analyzer, analyzer_cls.return_value)
        self.assertIsNone(search_service)

    def test_run_market_review_background_returns_non_empty_result_payload(self) -> None:
        if analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        runtime_notifier = MagicMock()
        runtime_search = MagicMock()
        runtime_analyzer = MagicMock()
        market_review_config = SimpleNamespace()
        with patch.object(
            analysis_endpoint_module,
            "_build_market_review_runtime",
            return_value=(runtime_notifier, runtime_analyzer, runtime_search),
        ), patch("src.core.market_review.run_market_review", return_value="report") as run_market_review:
            result = analysis_endpoint_module._run_market_review_background(
                send_notification=False,
                override_region="cn",
                lock_token=None,
                config=market_review_config,
            )

        self.assertEqual(result, {"result": "report"})
        run_market_review.assert_called_once_with(
            notifier=runtime_notifier,
            analyzer=runtime_analyzer,
            search_service=runtime_search,
            config=market_review_config,
            send_notification=False,
            override_region="cn",
            return_structured=True,
            trigger_source="api",
        )

    def test_run_market_review_uses_request_scoped_config_language(self) -> None:
        from src.core.market_review import run_market_review

        global_config = SimpleNamespace(report_language="zh", market_review_region="cn")
        scoped_config = SimpleNamespace(report_language="en", market_review_region="cn")
        notifier = MagicMock()
        notifier.save_report_to_file.return_value = "market_review.md"
        notifier.is_available.return_value = False
        review_result = SimpleNamespace(
            report="Market review body",
            market_light_snapshot={},
            structured_payload={
                "kind": "market_review",
                "language": "en",
                "sections": [{"key": "summary", "title": "Summary", "markdown": "Market review body"}],
            },
        )
        market_analyzer = MagicMock()
        market_analyzer.run_daily_review_with_snapshot.return_value = review_result

        with patch("src.core.market_review.get_config", return_value=global_config) as get_config_mock, \
             patch("src.core.market_review.MarketAnalyzer", return_value=market_analyzer) as market_analyzer_cls, \
             patch("src.core.market_review._persist_market_review_history") as persist:
            result = run_market_review(
                notifier=notifier,
                search_service=MagicMock(),
                send_notification=False,
                return_structured=True,
                config=scoped_config,
            )

        get_config_mock.assert_not_called()
        market_analyzer_cls.assert_called_once()
        self.assertIs(market_analyzer_cls.call_args.kwargs["config"], scoped_config)
        self.assertEqual(result.market_review_payload["language"], "en")
        self.assertEqual(persist.call_args.kwargs["config"].report_language, "en")

    def test_get_analysis_status_returns_market_review_report_from_queue(self) -> None:
        if get_analysis_status is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        queue = MagicMock()
        queue.get_task.return_value = SimpleNamespace(
            task_id="market-task-1",
            stock_code="market_review",
            stock_name="大盘复盘",
            status=analysis_endpoint_module.TaskStatusEnum.COMPLETED,
            progress=100,
            result={
                "result": "市场复盘报告示例文本",
                "market_review_payload": {"kind": "market_review", "sections": []},
            },
            error=None,
            original_query=None,
            selection_source=None,
            analysis_phase="auto",
        )

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
            status = get_analysis_status("market-task-1")

        self.assertEqual(status.status, "completed")
        self.assertEqual(status.market_review_report, "市场复盘报告示例文本")
        self.assertEqual(status.market_review_payload["kind"], "market_review")
        self.assertIsNone(status.result)

    def test_get_analysis_status_accepts_cancel_states_from_queue(self) -> None:
        if get_analysis_status is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        for task_status in (
            analysis_endpoint_module.TaskStatusEnum.CANCEL_REQUESTED,
            analysis_endpoint_module.TaskStatusEnum.CANCELLED,
        ):
            with self.subTest(task_status=task_status.value):
                queue = MagicMock()
                queue.get_task.return_value = SimpleNamespace(
                    task_id=f"task-{task_status.value}",
                    trace_id=f"trace-{task_status.value}",
                    stock_code="600519",
                    stock_name="贵州茅台",
                    status=task_status,
                    progress=42,
                    result=None,
                    error=None,
                    original_query=None,
                    selection_source=None,
                    analysis_phase="auto",
                    skills=[],
                )

                with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
                    status = get_analysis_status(f"task-{task_status.value}")

                self.assertEqual(status.status, task_status.value)
                self.assertEqual(status.progress, 42)
                self.assertIsNone(status.result)

    def test_get_analysis_status_normalizes_completed_queue_result_contract(self) -> None:
        if get_analysis_status is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        created_at = datetime(2026, 5, 21, 17, 40, 0)
        queue = MagicMock()
        queue.get_task.return_value = SimpleNamespace(
            task_id="task-queue-1",
            stock_code="600519",
            stock_name="贵州茅台",
            status=analysis_endpoint_module.TaskStatusEnum.COMPLETED,
            progress=100,
            result={
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report": {
                    "meta": {"query_id": "task-queue-1", "stock_code": "600519"},
                    "summary": {"analysis_summary": "summary", "operation_advice": "不建议买入"},
                },
            },
            error=None,
            original_query=None,
            selection_source=None,
            analysis_phase="auto",
            created_at=created_at,
            completed_at=datetime(2026, 5, 21, 17, 45, 0),
        )

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
            status = get_analysis_status("task-queue-1")

        self.assertEqual(status.status, "completed")
        self.assertIsNotNone(status.result)
        self.assertEqual(status.result.query_id, "task-queue-1")
        self.assertEqual(status.result.stock_code, "600519")
        self.assertEqual(status.result.stock_name, "贵州茅台")
        self.assertEqual(status.result.created_at, created_at.isoformat())
        self.assertEqual(
            status.result.report["summary"]["analysis_summary"],
            "summary",
        )
        self.assertEqual(status.result.report["summary"]["operation_advice"], "不建议买入")
        self.assertEqual(status.result.report["summary"]["action"], "avoid")
        self.assertEqual(status.result.report["summary"]["action_label"], "回避")

    def test_get_analysis_status_prefers_raw_result_action_over_summary_action(self) -> None:
        if get_analysis_status is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        created_at = datetime(2026, 5, 21, 17, 40, 0)
        queue = MagicMock()
        queue.get_task.return_value = SimpleNamespace(
            task_id="task-queue-action-conflict",
            stock_code="600519",
            stock_name="贵州茅台",
            status=analysis_endpoint_module.TaskStatusEnum.COMPLETED,
            progress=100,
            result={
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report": {
                    "meta": {
                        "query_id": "task-queue-action-conflict",
                        "stock_code": "600519",
                        "report_type": "detailed",
                        "report_language": "zh",
                    },
                    "summary": {
                        "analysis_summary": "summary",
                        "operation_advice": "持有观察",
                        "action": "buy",
                    },
                    "details": {
                        "raw_result": {
                            "operation_advice": "持有观察",
                            "action": "watch",
                            "report_language": "zh",
                        },
                    },
                },
            },
            error=None,
            original_query=None,
            selection_source=None,
            analysis_phase="auto",
            created_at=created_at,
            completed_at=datetime(2026, 5, 21, 17, 45, 0),
        )

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
            status = get_analysis_status("task-queue-action-conflict")

        self.assertEqual(status.status, "completed")
        self.assertIsNotNone(status.result)
        self.assertEqual(status.result.report["summary"]["action"], "watch")
        self.assertEqual(status.result.report["summary"]["action_label"], "观望")

    def test_get_analysis_status_preserves_zero_sentiment_score_when_aligning_action(self) -> None:
        if get_analysis_status is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        created_at = datetime(2026, 5, 21, 17, 40, 0)
        queue = MagicMock()
        queue.get_task.return_value = SimpleNamespace(
            task_id="task-queue-zero-score",
            stock_code="600519",
            stock_name="贵州茅台",
            status=analysis_endpoint_module.TaskStatusEnum.COMPLETED,
            progress=100,
            result={
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report": {
                    "meta": {
                        "query_id": "task-queue-zero-score",
                        "stock_code": "600519",
                        "report_type": "detailed",
                        "report_language": "zh",
                    },
                    "summary": {
                        "analysis_summary": "趋势显著恶化",
                        "operation_advice": "持有",
                        "sentiment_score": 0,
                    },
                    "details": {
                        "raw_result": {
                            "operation_advice": "持有",
                            "report_language": "zh",
                        },
                    },
                },
            },
            error=None,
            original_query=None,
            selection_source=None,
            analysis_phase="auto",
            created_at=created_at,
            completed_at=datetime(2026, 5, 21, 17, 45, 0),
        )

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
            status = get_analysis_status("task-queue-zero-score")

        self.assertEqual(status.status, "completed")
        self.assertIsNotNone(status.result)
        self.assertEqual(status.result.report["summary"]["sentiment_score"], 0)
        self.assertEqual(status.result.report["summary"]["action"], "sell")
        self.assertEqual(status.result.report["summary"]["action_label"], "卖出")

    def test_get_analysis_status_preserves_zero_sentiment_score_when_enriching_report(self) -> None:
        if get_analysis_status is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        created_at = datetime(2026, 5, 21, 17, 40, 0)
        queue = MagicMock()
        queue.get_task.return_value = SimpleNamespace(
            task_id="task-queue-zero-score-enriched",
            stock_code="600519",
            stock_name="贵州茅台",
            status=analysis_endpoint_module.TaskStatusEnum.COMPLETED,
            progress=100,
            result={
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report": {
                    "meta": {
                        "query_id": "task-queue-zero-score-enriched",
                        "stock_code": "600519",
                        "report_type": "detailed",
                        "report_language": "zh",
                    },
                    "summary": {
                        "analysis_summary": "趋势显著恶化",
                        "operation_advice": "持有",
                        "sentiment_score": 0,
                    },
                    "details": {
                        "raw_result": {
                            "operation_advice": "持有",
                            "report_language": "zh",
                        },
                    },
                },
            },
            error=None,
            original_query=None,
            selection_source=None,
            analysis_phase="auto",
            created_at=created_at,
            completed_at=datetime(2026, 5, 21, 17, 45, 0),
        )

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), \
             patch(
                 "api.v1.endpoints.analysis._load_sync_fundamental_sources",
                 return_value=({}, None, None),
             ):
            status = get_analysis_status("task-queue-zero-score-enriched")

        self.assertEqual(status.status, "completed")
        self.assertIsNotNone(status.result)
        self.assertEqual(status.result.report["summary"]["sentiment_score"], 0)
        self.assertEqual(status.result.report["summary"]["action"], "sell")
        self.assertEqual(status.result.report["summary"]["action_label"], "卖出")

    def test_get_analysis_status_enriches_in_memory_market_structure_from_raw_result(self) -> None:
        if get_analysis_status is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        market_structure = _market_structure_context()
        created_at = datetime(2026, 5, 21, 17, 40, 0)
        queue = MagicMock()
        queue.get_task.return_value = SimpleNamespace(
            task_id="task-queue-market-structure-raw",
            stock_code="300024",
            stock_name="机器人",
            status=analysis_endpoint_module.TaskStatusEnum.COMPLETED,
            progress=100,
            result={
                "stock_code": "300024",
                "stock_name": "机器人",
                "report": {
                    "meta": {
                        "query_id": "task-queue-market-structure-raw",
                        "stock_code": "300024",
                        "report_type": "detailed",
                        "report_language": "zh",
                    },
                    "summary": {"analysis_summary": "summary"},
                    "details": {"news_summary": "news"},
                },
            },
            error=None,
            original_query=None,
            selection_source=None,
            analysis_phase="auto",
            created_at=created_at,
            completed_at=datetime(2026, 5, 21, 17, 45, 0),
        )

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), \
             patch(
                 "api.v1.endpoints.analysis._load_sync_fundamental_sources",
                 return_value=(
                     None,
                     None,
                     {
                         "model_used": "test-model",
                         "report_language": "zh",
                         "market_structure_context": market_structure,
                     },
                 ),
             ) as load_sources:
            status = get_analysis_status("task-queue-market-structure-raw")

        self.assertEqual(status.status, "completed")
        self.assertIsNotNone(status.result)
        self.assertEqual(
            status.result.report["details"]["market_structure"]["market_theme_context"]["active_themes"][0]["name"],
            "机器人概念",
        )
        self.assertEqual(
            status.result.report["details"]["raw_result"]["market_structure_context"]["market_theme_context"]["active_themes"][0]["name"],
            "机器人概念",
        )
        self.assertNotIn(
            "raw_result",
            status.result.report["details"]["raw_result"],
        )
        load_sources.assert_called_once_with(
            query_id="task-queue-market-structure-raw",
            stock_code="300024",
        )

    def test_get_analysis_status_enriches_in_memory_market_structure_without_history_snapshot(self) -> None:
        if get_analysis_status is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        market_structure = _market_structure_context()
        service = AnalysisService()
        task_result = service._build_analysis_response(
            SimpleNamespace(
                code="300024",
                name="机器人",
                current_price=999.9,
                change_pct=1.1,
                model_used="test-model",
                analysis_summary="summary",
                operation_advice="持有",
                trend_prediction="震荡",
                sentiment_score=80,
                news_summary="news",
                technical_analysis="tech",
                fundamental_analysis="fundamental",
                risk_warning="risk",
                market_structure_context=market_structure,
                to_dict=lambda: {
                    "analysis_summary": "summary",
                    "operation_advice": "持有",
                    "trend_prediction": "震荡",
                    "sentiment_score": 80,
                    "report_language": "zh",
                    "news_summary": "news",
                    "technical_analysis": "tech",
                    "fundamental_analysis": "fundamental",
                    "risk_warning": "risk",
                    "market_structure_context": market_structure,
                },
            ),
            "task-in-memory-no-history",
            report_type="detailed",
        )
        created_at = datetime(2026, 5, 21, 17, 40, 0)
        queue = MagicMock()
        queue.get_task.return_value = SimpleNamespace(
            task_id="task-in-memory-no-history",
            stock_code="300024",
            stock_name="机器人",
            status=analysis_endpoint_module.TaskStatusEnum.COMPLETED,
            progress=100,
            result=task_result,
            error=None,
            original_query=None,
            selection_source=None,
            analysis_phase="auto",
            created_at=created_at,
            completed_at=datetime(2026, 5, 21, 17, 45, 0),
        )

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), \
             patch(
                 "api.v1.endpoints.analysis._load_sync_fundamental_sources",
                 return_value=(None, None, None),
             ):
            status = get_analysis_status("task-in-memory-no-history")

        self.assertEqual(status.status, "completed")
        self.assertIsNotNone(status.result)
        self.assertEqual(
            status.result.report["details"]["market_structure"]["market_theme_context"]["active_themes"][0]["name"],
            "机器人概念",
        )

    def test_get_analysis_status_preserves_queue_report_created_at_when_enriching(self) -> None:
        if get_analysis_status is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        created_at = datetime(2026, 5, 21, 17, 40, 0)
        queue = MagicMock()
        queue.get_task.return_value = SimpleNamespace(
            task_id="task-queue-2",
            stock_code="600519",
            stock_name="贵州茅台",
            status=analysis_endpoint_module.TaskStatusEnum.COMPLETED,
            progress=100,
            result={
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report": {
                    "meta": {"query_id": "task-queue-2", "stock_code": "600519"},
                    "summary": {"analysis_summary": "summary"},
                },
            },
            error=None,
            original_query=None,
            selection_source=None,
            analysis_phase="auto",
            created_at=created_at,
            completed_at=datetime(2026, 5, 21, 17, 45, 0),
        )

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), \
             patch(
                 "api.v1.endpoints.analysis._load_sync_fundamental_sources",
                 return_value=({}, None, None),
             ):
            status = get_analysis_status("task-queue-2")

        self.assertEqual(status.status, "completed")
        self.assertIsNotNone(status.result)
        self.assertEqual(status.result.created_at, created_at.isoformat())
        self.assertEqual(
            status.result.report["meta"]["created_at"],
            created_at.isoformat(),
        )

    def test_run_market_review_background_raises_when_report_is_empty(self) -> None:
        if analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        runtime_notifier = MagicMock()
        runtime_search = MagicMock()
        runtime_analyzer = MagicMock()
        with patch.object(
            analysis_endpoint_module,
            "_build_market_review_runtime",
            return_value=(runtime_notifier, runtime_analyzer, runtime_search),
        ), patch("src.core.market_review.run_market_review", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "大盘复盘未返回可持久化报告"):
                analysis_endpoint_module._run_market_review_background(
                    send_notification=False,
                    override_region="cn",
                    lock_token=None,
                    config=SimpleNamespace(),
                )

    def test_run_market_review_background_releases_lock_on_runtime_build_failure(self) -> None:
        if analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        lock_token = object()
        with patch.object(
            analysis_endpoint_module,
            "_build_market_review_runtime",
            side_effect=RuntimeError("runtime init failed"),
        ), patch.object(
            analysis_endpoint_module,
            "_release_market_review_lock",
        ) as release_market_review_lock:
            with self.assertRaises(RuntimeError):
                analysis_endpoint_module._run_market_review_background(
                    send_notification=False,
                    override_region="cn",
                    lock_token=lock_token,
                    config=SimpleNamespace(),
                )

        release_market_review_lock.assert_called_once_with(lock_token)

    def test_run_market_review_background_runtime_build_failure_marks_task_failed(self) -> None:
        if analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        class _SyncExecutor:
            def submit(self, fn, *args, **kwargs):
                future = Future()
                try:
                    future.set_result(fn(*args, **kwargs))
                except Exception as exc:  # pragma: no cover - exercised via assert below
                    future.set_exception(exc)
                return future

        queue = AnalysisTaskQueue(max_workers=1)
        queue._executor = _SyncExecutor()
        with patch.object(
            analysis_endpoint_module,
            "_build_market_review_runtime",
            side_effect=RuntimeError("runtime init failed"),
        ), patch.object(analysis_endpoint_module, "_release_market_review_lock") as release_market_review_lock:
            task = queue.submit_background_task(
                lambda: analysis_endpoint_module._run_market_review_background(
                    send_notification=False,
                    override_region="cn",
                    lock_token=object(),
                    config=SimpleNamespace(),
                ),
                stock_code="market_review",
                stock_name="大盘复盘",
                message="大盘复盘任务已提交",
            )

        task_info = queue.get_task(task.task_id)
        self.assertIsNotNone(task_info)
        self.assertEqual(task_info.status, TaskStatus.FAILED)
        self.assertEqual(task_info.error, "runtime init failed")
        self.assertEqual(task_info.message, "任务失败: runtime init failed")
        release_market_review_lock.assert_called_once()

    def test_get_analysis_status_completed_db_snapshot_preserves_zero_change_pct(self) -> None:
        if get_analysis_status is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        mock_queue = MagicMock()
        mock_queue.get_task.return_value = None
        mock_db = MagicMock()
        mock_db.get_analysis_history.return_value = [
            SimpleNamespace(
                id=1,
                code="600519",
                name="贵州茅台",
                report_type="detailed",
                raw_result={"report_language": "zh", "model_used": "test-model"},
                context_snapshot={
                    "enhanced_context": {
                        "realtime": {
                            "price": 1234.5,
                            "change_pct": 0.0,
                            "change_60d": 12.3,
                        }
                    },
                    "realtime_quote_raw": {"price": 1234.5, "change_pct": 9.9},
                },
                sentiment_score=80,
                operation_advice="持有",
                trend_prediction="看多",
                analysis_summary="summary",
                ideal_buy=None,
                secondary_buy=None,
                stop_loss=None,
                take_profit=None,
                created_at=None,
            )
        ]

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=mock_queue), \
             patch("src.storage.DatabaseManager.get_instance", return_value=mock_db):
            result = get_analysis_status("task-1")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result.report["meta"]["current_price"], 1234.5)
        self.assertEqual(result.result.report["meta"]["change_pct"], 0.0)

    def test_get_analysis_status_returns_market_review_report_from_db(self) -> None:
        if get_analysis_status is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        mock_queue = MagicMock()
        mock_queue.get_task.return_value = None
        mock_db = MagicMock()
        mock_db.get_analysis_history.return_value = [
            SimpleNamespace(
                id=10,
                code="MARKET",
                name="大盘复盘",
                report_type="market_review",
                raw_result={"raw_response": "# 🎯 大盘复盘\n\n复盘正文"},
                news_content="复盘正文",
                created_at=None,
            )
        ]

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=mock_queue), \
             patch("src.storage.DatabaseManager.get_instance", return_value=mock_db):
            result = get_analysis_status("market-task-1")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.market_review_report, "# 🎯 大盘复盘\n\n复盘正文")
        self.assertIsNone(result.result)

    def test_get_analysis_status_completed_db_snapshot_reads_change_pct_from_raw_when_price_present(self) -> None:
        if get_analysis_status is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        mock_queue = MagicMock()
        mock_queue.get_task.return_value = None
        mock_db = MagicMock()
        mock_db.get_analysis_history.return_value = [
            SimpleNamespace(
                id=2,
                code="AAPL",
                name="Apple",
                report_type="detailed",
                raw_result={"report_language": "en", "model_used": "test-model"},
                context_snapshot={
                    "enhanced_context": {
                        "realtime": {
                            "price": 180.35,
                            "change_pct": None,
                            "change_60d": None,
                        }
                    },
                    "realtime_quote_raw": {"price": 180.35, "pct_chg": -1.25},
                },
                sentiment_score=72,
                operation_advice="Hold",
                trend_prediction="Neutral",
                analysis_summary="summary",
                ideal_buy=None,
                secondary_buy=None,
                stop_loss=None,
                take_profit=None,
                created_at=None,
            )
        ]

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=mock_queue), \
             patch("src.storage.DatabaseManager.get_instance", return_value=mock_db):
            result = get_analysis_status("task-2")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result.report["meta"]["current_price"], 180.35)
        self.assertEqual(result.result.report["meta"]["change_pct"], -1.25)

    def test_get_analysis_status_completed_db_snapshot_does_not_use_change_60d_as_intraday_change(self) -> None:
        if get_analysis_status is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        mock_queue = MagicMock()
        mock_queue.get_task.return_value = None
        mock_db = MagicMock()
        mock_db.get_analysis_history.return_value = [
            SimpleNamespace(
                id=3,
                code="MSFT",
                name="Microsoft",
                report_type="detailed",
                raw_result={"report_language": "en", "model_used": "test-model"},
                context_snapshot={
                    "enhanced_context": {
                        "realtime": {
                            "price": 412.6,
                            "change_pct": None,
                            "change_60d": 14.8,
                        }
                    },
                    "realtime_quote_raw": {"price": 412.6},
                },
                sentiment_score=70,
                operation_advice="Hold",
                trend_prediction="Neutral",
                analysis_summary="summary",
                ideal_buy=None,
                secondary_buy=None,
                stop_loss=None,
                take_profit=None,
                created_at=None,
            )
        ]

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=mock_queue), \
             patch("src.storage.DatabaseManager.get_instance", return_value=mock_db):
            result = get_analysis_status("task-3")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result.report["meta"]["current_price"], 412.6)
        self.assertIsNone(result.result.report["meta"]["change_pct"])

    def test_report_type_full_maps_to_full_pipeline_mode(self) -> None:
        service = object.__new__(AnalysisService)
        pipeline_instance = MagicMock()
        pipeline_instance.process_single_stock.return_value = object()

        with patch("src.config.get_config", return_value=SimpleNamespace()), \
             patch("src.core.pipeline.StockAnalysisPipeline", return_value=pipeline_instance), \
             patch.object(AnalysisService, "_build_analysis_response", return_value={"stock_code": "600519"}):
            result = AnalysisService.analyze_stock(service, "600519", report_type="full", query_id="q1")

        self.assertEqual(result, {"stock_code": "600519"})
        self.assertEqual(
            pipeline_instance.process_single_stock.call_args.kwargs["report_type"],
            ReportType.FULL,

        )

    def test_analysis_service_passes_request_skills_to_pipeline(self) -> None:
        service = object.__new__(AnalysisService)
        pipeline_instance = MagicMock()
        pipeline_instance.process_single_stock.return_value = object()
        request_skills = ["growth_quality"]

        with patch("src.config.get_config", return_value=SimpleNamespace()), \
             patch("src.core.pipeline.StockAnalysisPipeline", return_value=pipeline_instance) as pipeline_cls, \
             patch.object(AnalysisService, "_build_analysis_response", return_value={"stock_code": "600519"}):
            result = AnalysisService.analyze_stock(
                service,
                "600519",
                report_type="full",
                query_id="q1",
                skills=request_skills,
            )

        self.assertEqual(result, {"stock_code": "600519"})
        self.assertEqual(pipeline_cls.call_args.kwargs["analysis_skills"], request_skills)

    def test_report_type_full_is_preserved_in_response_metadata(self) -> None:
        service = AnalysisService()
        pipeline_instance = MagicMock()
        pipeline_instance.process_single_stock.return_value = SimpleNamespace(
            code="600519",
            name="贵州茅台",
            current_price=1234.56,
            change_pct=1.23,
            model_used="test-model",
            analysis_summary="summary",
            operation_advice="hold",
            trend_prediction="up",
            sentiment_score=80,
            news_summary="news",
            technical_analysis="tech",
            fundamental_analysis="fundamental",
            risk_warning="risk",
            get_sniper_points=lambda: {},
        )

        with patch("src.config.get_config", return_value=SimpleNamespace()), \
             patch("src.core.pipeline.StockAnalysisPipeline", return_value=pipeline_instance):
            result = service.analyze_stock("600519", report_type="full", query_id="q1", send_notification=False)

        self.assertEqual(result["report"]["meta"]["report_type"], "full")

    def test_analysis_service_returns_none_and_records_last_error_for_unsuccessful_pipeline_result(self) -> None:
        service = AnalysisService()
        pipeline_instance = MagicMock()
        pipeline_instance.process_single_stock.return_value = SimpleNamespace(
            success=False,
            error_message="LLM stream interrupted",
        )

        with patch("src.config.get_config", return_value=SimpleNamespace()), \
             patch("src.core.pipeline.StockAnalysisPipeline", return_value=pipeline_instance):
            result = service.analyze_stock("600519", report_type="detailed", query_id="q1", send_notification=False)

        self.assertIsNone(result)
        self.assertEqual(service.last_error, "LLM stream interrupted")

    def test_handle_sync_analysis_uses_service_last_error_for_failed_pipeline_result(self) -> None:
        if _handle_sync_analysis is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        service_instance = MagicMock()
        service_instance.analyze_stock.return_value = None
        service_instance.last_error = "LLM stream interrupted"

        with patch("src.services.analysis_service.AnalysisService", return_value=service_instance):
            with self.assertRaises(Exception) as ctx:
                _handle_sync_analysis(
                    "600519",
                    SimpleNamespace(
                        report_type="detailed",
                        force_refresh=False,
                        notify=True,
                        analysis_phase="auto",
                    ),
                )

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(
            ctx.exception.detail,
            {
                "error": "analysis_failed",
                "message": "LLM stream interrupted",
            },
        )

    def test_handle_sync_analysis_response_exposes_overview(self) -> None:
        if _handle_sync_analysis is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        overview = _analysis_context_pack_overview()
        phase_summary = _market_phase_summary()
        service_instance = MagicMock()
        service_instance.analyze_stock.return_value = {
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "report": {
                "meta": {"stock_code": "600519", "report_language": "zh"},
                "summary": {"analysis_summary": "summary"},
                "strategy": {},
                "details": {"news_summary": "news"},
            },
        }

        with patch("uuid.uuid4", return_value=SimpleNamespace(hex="q-sync-overview")), \
             patch("src.services.analysis_service.AnalysisService", return_value=service_instance), \
             patch(
                 "api.v1.endpoints.analysis._load_sync_fundamental_sources",
                 return_value=(
                     {
                         "enhanced_context": {"code": "600519"},
                         "analysis_context_pack_overview": overview,
                         "market_phase_summary": phase_summary,
                     },
                     None,
                     None,
                 ),
             ):
            result = _handle_sync_analysis(
                "600519",
                SimpleNamespace(
                    report_type="detailed",
                    force_refresh=False,
                    notify=True,
                    skills=None,
                    analysis_phase="intraday",
                ),
            )

        self.assertEqual(
            service_instance.analyze_stock.call_args.kwargs["analysis_phase"],
            "intraday",
        )
        details = result.report["details"]
        self.assertEqual(result.report["meta"]["market_phase_summary"]["phase"], "intraday")
        self.assertEqual(
            details["analysis_context_pack_overview"]["metadata"]["trigger_source"],
            "api",
        )
        self.assertEqual(
            details["analysis_context_pack_overview"]["data_quality"]["overall_score"],
            88,
        )
        self.assertNotIn("analysis_context_pack_overview", details["context_snapshot"])
        self.assertNotIn("market_phase_summary", details["context_snapshot"])

    def test_handle_sync_analysis_restores_market_structure_from_raw_result_snapshot(self) -> None:
        if _handle_sync_analysis is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        market_structure = _market_structure_context()
        service_instance = MagicMock()
        service_instance.analyze_stock.return_value = {
            "stock_code": "300024",
            "stock_name": "机器人",
            "report": {
                "meta": {"stock_code": "300024", "report_language": "zh"},
                "summary": {"analysis_summary": "summary"},
                "strategy": {},
                "details": {"news_summary": "news"},
            },
        }

        with patch("uuid.uuid4", return_value=SimpleNamespace(hex="q-sync-market-structure")), \
             patch("src.services.analysis_service.AnalysisService", return_value=service_instance), \
             patch(
                 "api.v1.endpoints.analysis._load_sync_fundamental_sources",
                 return_value=(
                     None,
                     None,
                     {
                         "model_used": "test-model",
                         "report_language": "zh",
                         "market_structure_context": market_structure,
                     },
                 ),
             ):
            result = _handle_sync_analysis(
                "300024",
                SimpleNamespace(
                    report_type="detailed",
                    force_refresh=False,
                    notify=True,
                    skills=None,
                    analysis_phase="intraday",
                ),
            )

        self.assertEqual(
            result.report["details"]["market_structure"]["market_theme_context"]["active_themes"][0]["name"],
            "机器人概念",
        )

    def test_handle_sync_analysis_carries_market_structure_from_service_without_fallback(self) -> None:
        if _handle_sync_analysis is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        market_structure = _market_structure_context()
        service = AnalysisService()
        service_result = service._build_analysis_response(
            SimpleNamespace(
                code="300024",
                name="机器人",
                current_price=999.9,
                change_pct=1.1,
                model_used="test-model",
                analysis_summary="summary",
                operation_advice="持有",
                trend_prediction="震荡",
                sentiment_score=80,
                news_summary="news",
                technical_analysis="tech",
                fundamental_analysis="fundamental",
                risk_warning="risk",
                market_structure_context=market_structure,
                to_dict=lambda: {
                    "analysis_summary": "summary",
                    "operation_advice": "持有",
                    "trend_prediction": "震荡",
                    "sentiment_score": 80,
                    "report_language": "zh",
                    "news_summary": "news",
                    "technical_analysis": "tech",
                    "fundamental_analysis": "fundamental",
                    "risk_warning": "risk",
                    "market_structure_context": market_structure,
                },
            ),
            "q-sync-no-history",
            report_type="detailed",
        )
        service_instance = MagicMock()
        service_instance.analyze_stock.return_value = service_result

        with patch("uuid.uuid4", return_value=SimpleNamespace(hex="q-sync-no-history")), \
             patch("src.services.analysis_service.AnalysisService", return_value=service_instance), \
             patch(
                 "api.v1.endpoints.analysis._load_sync_fundamental_sources",
                 return_value=(None, None, None),
             ):
            result = _handle_sync_analysis(
                "300024",
                SimpleNamespace(
                    report_type="detailed",
                    force_refresh=False,
                    notify=True,
                    skills=None,
                    analysis_phase="intraday",
                ),
            )

        self.assertIsNotNone(result)
        self.assertEqual(
            result.report["details"]["market_structure"]["market_theme_context"]["active_themes"][0]["name"],
            "机器人概念",
        )
        self.assertEqual(
            result.report["details"]["raw_result"]["market_structure_context"]["market_theme_context"]["active_themes"][0]["name"],
            "机器人概念",
        )
        self.assertNotIn(
            "raw_result",
            result.report["details"]["raw_result"],
        )

    def test_build_analysis_response_localizes_placeholder_stock_name_for_english(self) -> None:
        service = AnalysisService()
        result = service._build_analysis_response(
            SimpleNamespace(
                code="AAPL",
                name="股票AAPL",
                current_price=180.35,
                change_pct=1.04,
                model_used="test-model",
                analysis_summary="Momentum remains constructive.",
                operation_advice="Buy",
                trend_prediction="Bullish",
                sentiment_score=78,
                news_summary="news",
                technical_analysis="tech",
                fundamental_analysis="fundamental",
                risk_warning="risk",
                report_language="en",
                get_sniper_points=lambda: {},
            ),
            "q1",
            report_type="full",
        )

        self.assertEqual(result["stock_name"], "Unnamed Stock")
        self.assertEqual(result["report"]["meta"]["stock_name"], "Unnamed Stock")

    def test_build_analysis_response_does_not_use_model_news_summary_as_retrieval_evidence(self) -> None:
        service = AnalysisService()
        result = service._build_analysis_response(
            SimpleNamespace(
                code="600519",
                name="贵州茅台",
                current_price=1234.56,
                change_pct=1.23,
                model_used="test-model",
                analysis_summary="summary",
                operation_advice="hold",
                trend_prediction="up",
                sentiment_score=80,
                news_summary="model generated news summary",
                technical_analysis="tech",
                fundamental_analysis="fundamental",
                risk_warning="risk",
                get_sniper_points=lambda: {},
            ),
            "q1",
            report_type="full",
        )

        news_component = result["diagnostic_summary"]["components"]["news"]
        self.assertEqual(news_component["status"], "unknown")

    def test_build_analysis_response_includes_market_phase_summary_from_result_snapshot(self) -> None:
        service = AnalysisService()
        phase_summary = _market_phase_summary()

        result = service._build_analysis_response(
            SimpleNamespace(
                code="600519",
                name="贵州茅台",
                current_price=1234.56,
                change_pct=1.23,
                model_used="test-model",
                analysis_summary="summary",
                operation_advice="hold",
                trend_prediction="up",
                sentiment_score=80,
                news_summary="news",
                technical_analysis="tech",
                fundamental_analysis="fundamental",
                risk_warning="risk",
                diagnostic_context_snapshot={"market_phase_summary": phase_summary},
                get_sniper_points=lambda: {},
            ),
            "q1",
            report_type="full",
        )

        self.assertEqual(
            result["report"]["meta"]["market_phase_summary"]["phase"],
            "intraday",
        )

    def test_build_analysis_response_includes_market_structure_in_raw_result(self) -> None:
        service = AnalysisService()
        market_structure = _market_structure_context()

        def _raw_result() -> dict:
            return {
                "analysis_summary": "summary",
                "operation_advice": "持有",
                "trend_prediction": "震荡",
                "sentiment_score": 80,
                "report_language": "zh",
                "news_summary": "news",
                "technical_analysis": "tech",
                "fundamental_analysis": "fundamental",
                "risk_warning": "risk",
                "market_structure_context": market_structure,
            }

        result = service._build_analysis_response(
            SimpleNamespace(
                code="300024",
                name="机器人",
                current_price=999.9,
                change_pct=1.01,
                model_used="test-model",
                analysis_summary="summary",
                operation_advice="持有",
                trend_prediction="震荡",
                sentiment_score=80,
                news_summary="news",
                technical_analysis="tech",
                fundamental_analysis="fundamental",
                risk_warning="risk",
                market_structure_context=market_structure,
                to_dict=_raw_result,
            ),
            "q-build-response",
            report_type="detailed",
        )

        self.assertEqual(
            result["report"]["details"]["raw_result"]["market_structure_context"]["market_theme_context"]["active_themes"][0]["name"],
            "机器人概念",
        )

    def test_analysis_service_passes_analysis_phase_to_pipeline(self) -> None:
        service = AnalysisService()
        pipeline_instance = MagicMock()
        pipeline_instance.process_single_stock.return_value = SimpleNamespace(
            success=True,
            code="600519",
            name="贵州茅台",
            current_price=1234.56,
            change_pct=1.23,
            model_used="test-model",
            analysis_summary="summary",
            operation_advice="hold",
            trend_prediction="up",
            sentiment_score=80,
            news_summary="news",
            technical_analysis="tech",
            fundamental_analysis="fundamental",
            risk_warning="risk",
            get_sniper_points=lambda: {},
        )

        with patch("src.config.get_config", return_value=SimpleNamespace()), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline_instance,
        ) as pipeline_cls:
            result = service.analyze_stock(
                "600519",
                report_type="detailed",
                send_notification=False,
                analysis_phase="postmarket",
            )

        self.assertIsNotNone(result)
        self.assertEqual(pipeline_cls.call_args.kwargs["analysis_phase"], "postmarket")

    def test_build_analysis_report_extracts_fundamental_fields_from_snapshot(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        report = _build_analysis_report(
            report_data={
                "meta": {},
                "summary": {},
                "strategy": {},
                "details": {"news_summary": "news"},
            },
            query_id="q1",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot={
                "enhanced_context": {
                    "fundamental_context": {
                        "earnings": {
                            "data": {
                                "financial_report": {"report_date": "2025-12-31", "revenue": 1000},
                                "dividend": {"ttm_dividend_yield_pct": 2.5},
                            }
                        }
                    }
                }
            },
            fallback_fundamental_payload=None,
        )

        self.assertEqual(report.details.financial_report["report_date"], "2025-12-31")
        self.assertEqual(report.details.dividend_metrics["ttm_dividend_yield_pct"], 2.5)

    def test_build_analysis_report_derives_decision_action_fields(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        report = _build_analysis_report(
            report_data={
                "meta": {"report_type": "detailed", "report_language": "zh"},
                "summary": {
                    "analysis_summary": "等待确认",
                    "operation_advice": "不建议买入",
                    "trend_prediction": "震荡",
                    "sentiment_score": 45,
                },
                "strategy": {},
                "details": {"decision_type": "buy"},
            },
            query_id="q1",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot=None,
            fallback_fundamental_payload=None,
        )

        self.assertEqual(report.summary.operation_advice, "不建议买入")
        self.assertEqual(report.summary.action, "avoid")
        self.assertEqual(report.summary.action_label, "回避")

    def test_build_analysis_report_aligns_score_and_legacy_advice(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        report = _build_analysis_report(
            report_data={
                "meta": {"report_type": "detailed", "report_language": "zh"},
                "summary": {
                    "analysis_summary": "等待确认",
                    "operation_advice": "持有",
                    "sentiment_score": 72,
                },
                "strategy": {},
                "details": {},
            },
            query_id="q2",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot=None,
            fallback_fundamental_payload=None,
        )

        self.assertEqual(report.summary.action, "buy")
        self.assertEqual(report.summary.action_label, "买入")

    def test_build_analysis_report_reads_decision_action_from_raw_result(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        report = _build_analysis_report(
            report_data={
                "meta": {"report_type": "detailed", "report_language": "zh"},
                "summary": {
                    "analysis_summary": "等待确认",
                    "operation_advice": "持有观察",
                    "action": "buy",
                    "trend_prediction": "震荡",
                    "sentiment_score": 45,
                },
                "strategy": {},
                "details": {
                    "action": "sell",
                    "raw_result": {
                        "operation_advice": "持有观察",
                        "action": "watch",
                        "report_language": "zh",
                    },
                },
            },
            query_id="q1",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot=None,
            fallback_fundamental_payload=None,
        )

        self.assertEqual(report.summary.action, "watch")
        self.assertEqual(report.summary.action_label, "观望")

    def test_build_analysis_report_stringifies_strategy_price_fields(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        report = _build_analysis_report(
            report_data={
                "meta": {},
                "summary": {},
                "strategy": {
                    "ideal_buy": 10.0,
                    "secondary_buy": None,
                    "stop_loss": 9.5,
                    "take_profit": 11.6,
                },
                "details": {},
            },
            query_id="q1",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot=None,
            fallback_fundamental_payload=None,
        )

        self.assertEqual(report.strategy.ideal_buy, "10.0")
        self.assertIsNone(report.strategy.secondary_buy)
        self.assertEqual(report.strategy.stop_loss, "9.5")
        self.assertEqual(report.strategy.take_profit, "11.6")

    def test_build_analysis_report_extracts_related_board_fields_from_snapshot(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        report = _build_analysis_report(
            report_data={
                "meta": {},
                "summary": {},
                "strategy": {},
                "details": {},
            },
            query_id="q1",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot={
                "enhanced_context": {
                    "fundamental_context": {
                        "belong_boards": [{"name": "白酒", "type": "行业"}],
                        "boards": {
                            "data": {
                                "top": [{"name": "白酒", "change_pct": 2.5}],
                                "bottom": [],
                            }
                        },
                    }
                }
            },
            fallback_fundamental_payload=None,
        )

        self.assertEqual(report.details.belong_boards, [{"name": "白酒", "type": "行业"}])
        self.assertEqual(report.details.sector_rankings["top"][0]["name"], "白酒")
        self.assertEqual(report.details.sector_rankings["top"][0]["change_pct"], 2.5)

    def test_build_analysis_report_exposes_overview_but_sanitizes_snapshot(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        overview = _analysis_context_pack_overview()
        phase_summary = _market_phase_summary()
        report = _build_analysis_report(
            report_data={
                "meta": {},
                "summary": {},
                "strategy": {},
                "details": {"news_summary": "news"},
            },
            query_id="q1",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot={
                "enhanced_context": {
                    "code": "600519",
                    "portfolio_context": {
                        "quantity": 100,
                        "avg_cost": 1800,
                        "unrealized_pnl_base": 5000,
                    },
                },
                "portfolio_context": {"total_cost": 180000},
                "analysis_context_pack_overview": overview,
                "market_phase_summary": {
                    **phase_summary,
                    "market_phase_context": {"raw": True},
                },
            },
            fallback_fundamental_payload=None,
        )

        self.assertIsNotNone(report.meta.market_phase_summary)
        self.assertEqual(report.meta.market_phase_summary.phase, "intraday")
        self.assertEqual(
            report.details.analysis_context_pack_overview.metadata.trigger_source,
            "api",
        )
        self.assertEqual(
            report.details.analysis_context_pack_overview.data_quality.overall_score,
            88,
        )
        self.assertEqual(
            report.details.analysis_context_pack_overview.blocks[1].missing_reasons,
            ["news_context_missing"],
        )
        self.assertNotIn(
            "analysis_context_pack_overview",
            report.details.context_snapshot,
        )
        self.assertNotIn(
            "market_phase_summary",
            report.details.context_snapshot,
        )
        self.assertNotIn(
            "portfolio_context",
            report.details.context_snapshot,
        )
        self.assertNotIn(
            "portfolio_context",
            report.details.context_snapshot["enhanced_context"],
        )
        self.assertNotIn("avg_cost", str(report.details.context_snapshot))

    def test_build_analysis_report_falls_back_to_sanitized_report_meta_phase_summary(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        phase_summary = {
            **_market_phase_summary(),
            "warnings": ["api_key=secret"],
            "market_phase_context": {"raw": True},
        }

        report = _build_analysis_report(
            report_data={
                "meta": {"market_phase_summary": phase_summary},
                "summary": {},
                "strategy": {},
                "details": {},
            },
            query_id="q-meta-phase",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot=None,
            fallback_fundamental_payload=None,
        )

        self.assertIsNotNone(report.meta.market_phase_summary)
        self.assertEqual(report.meta.market_phase_summary.phase, "intraday")
        self.assertEqual(report.meta.market_phase_summary.warnings, ["[REDACTED]"])

    def test_build_analysis_report_prefers_snapshot_phase_summary_over_report_meta(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        snapshot_summary = _market_phase_summary()
        report = _build_analysis_report(
            report_data={
                "meta": {
                    "market_phase_summary": {
                        **snapshot_summary,
                        "phase": "postmarket",
                    },
                },
                "summary": {},
                "strategy": {},
                "details": {},
            },
            query_id="q-snapshot-phase",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot={"market_phase_summary": snapshot_summary},
            fallback_fundamental_payload=None,
        )

        self.assertIsNotNone(report.meta.market_phase_summary)
        self.assertEqual(report.meta.market_phase_summary.phase, "intraday")

    def test_build_analysis_report_repairs_bare_kr_code_and_phase_summary(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        persisted_phase_summary = {
            **_market_phase_summary(),
            "phase": "postmarket",
            "market_local_time": "2025-01-02T16:10:00+09:00",
            "session_date": "2025-01-02",
            "effective_daily_bar_date": "2025-01-02",
            "is_market_open_now": False,
            "is_partial_bar": False,
            "minutes_to_open": 900,
            "minutes_to_close": None,
            "trigger_source": "scheduled_job",
            "analysis_intent": "postmarket",
            "warnings": ["legacy_snapshot"],
        }

        with patch("api.v1.endpoints.analysis.resolve_index_stock_code", return_value="005930.KS"):
            report = _build_analysis_report(
                report_data={
                    "meta": {"stock_code": "005930"},
                    "summary": {},
                    "strategy": {},
                    "details": {},
                },
                query_id="q-kr-phase",
                stock_code="005930",
                stock_name="三星电子",
                context_snapshot={"market_phase_summary": persisted_phase_summary},
                fallback_fundamental_payload=None,
            )

        self.assertEqual(report.meta.stock_code, "005930.KS")
        self.assertIsNotNone(report.meta.market_phase_summary)
        self.assertEqual(report.meta.market_phase_summary.market, "kr")
        self.assertEqual(report.meta.market_phase_summary.phase, "postmarket")
        self.assertEqual(
            report.meta.market_phase_summary.market_local_time,
            "2025-01-02T16:10:00+09:00",
        )
        self.assertEqual(report.meta.market_phase_summary.session_date, "2025-01-02")
        self.assertEqual(
            report.meta.market_phase_summary.effective_daily_bar_date,
            "2025-01-02",
        )
        self.assertEqual(report.meta.market_phase_summary.trigger_source, "scheduled_job")
        self.assertEqual(report.meta.market_phase_summary.analysis_intent, "postmarket")

    def test_build_analysis_report_rebuilds_legacy_cn_market_summary_for_kr_code(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        legacy_cn_summary = {
            **_market_phase_summary(),
            "market": "cn",
            "phase": "intraday",
            "market_local_time": "2026-03-27T10:00:00+08:00",
            "session_date": "2026-03-27",
            "effective_daily_bar_date": "2026-03-26",
            "analysis_intent": "intraday",
            "trigger_source": "history_snapshot",
            "warnings": ["legacy_cn_snapshot"],
        }

        with patch("api.v1.endpoints.analysis.resolve_index_stock_code", return_value="005930.KS"):
            report = _build_analysis_report(
                report_data={
                    "meta": {"stock_code": "005930"},
                    "summary": {},
                    "strategy": {},
                    "details": {},
                },
                query_id="q-kr-legacy-cn",
                stock_code="005930",
                stock_name="三星电子",
                context_snapshot={"market_phase_summary": legacy_cn_summary},
                fallback_fundamental_payload=None,
            )

        self.assertIsNotNone(report.meta.market_phase_summary)
        self.assertEqual(report.meta.stock_code, "005930.KS")
        self.assertEqual(report.meta.market_phase_summary.market, "kr")
        self.assertTrue(report.meta.market_phase_summary.market_local_time.endswith("+09:00"))
        self.assertIn("legacy_cn_snapshot", report.meta.market_phase_summary.warnings)

    def test_build_analysis_report_merges_partial_top_level_context_with_fallback(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        report = _build_analysis_report(
            report_data={
                "meta": {},
                "summary": {},
                "strategy": {},
                "details": {},
            },
            query_id="q1",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot={
                "fundamental_context": {
                    "belong_boards": [{"name": "白酒", "type": "行业"}],
                    "boards": {
                        "data": {
                            "top": [{"name": "白酒", "change_pct": 2.5}],
                            "bottom": [],
                        }
                    },
                }
            },
            fallback_fundamental_payload={
                "earnings": {
                    "data": {
                        "financial_report": {"report_date": "2025-12-31", "revenue": 1000},
                        "dividend": {"ttm_dividend_yield_pct": 2.6},
                    }
                }
            },
        )

        self.assertEqual(report.details.belong_boards, [{"name": "白酒", "type": "行业"}])
        self.assertEqual(report.details.sector_rankings["top"][0]["name"], "白酒")
        self.assertEqual(report.details.financial_report["report_date"], "2025-12-31")
        self.assertEqual(report.details.dividend_metrics["ttm_dividend_yield_pct"], 2.6)

    def test_build_analysis_report_keeps_fallback_when_snapshot_has_empty_placeholders(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        report = _build_analysis_report(
            report_data={
                "meta": {},
                "summary": {},
                "strategy": {},
                "details": {},
            },
            query_id="q1",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot={
                "fundamental_context": {
                    "belong_boards": [],
                    "boards": {},
                    "earnings": {},
                },
                "enhanced_context": {
                    "fundamental_context": {
                        "earnings": {"data": {}},
                    }
                },
            },
            fallback_fundamental_payload={
                "belong_boards": [{"name": "白酒", "type": "行业"}],
                "boards": {
                    "data": {
                        "top": [{"name": "白酒", "change_pct": 2.5}],
                        "bottom": [],
                    }
                },
                "earnings": {
                    "data": {
                        "financial_report": {"report_date": "2025-12-31", "revenue": 1000},
                        "dividend": {"ttm_dividend_yield_pct": 2.6},
                    }
                },
            },
        )

        self.assertEqual(report.details.belong_boards, [{"name": "白酒", "type": "行业"}])
        self.assertEqual(report.details.sector_rankings["top"][0]["name"], "白酒")
        self.assertEqual(report.details.financial_report["report_date"], "2025-12-31")
        self.assertEqual(report.details.dividend_metrics["ttm_dividend_yield_pct"], 2.6)

    def test_build_analysis_report_normalizes_related_board_payloads(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        report = _build_analysis_report(
            report_data={
                "meta": {},
                "summary": {},
                "strategy": {},
                "details": {},
            },
            query_id="q1",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot={
                "enhanced_context": {
                    "fundamental_context": {
                        "belong_boards": [
                            {"name": " 白酒 ", "type": " 行业 ", "code": " BK0815 "},
                            {"name": "   "},
                            "bad-item",
                        ],
                        "boards": {
                            "data": {
                                "top": {"name": "坏数据"},
                                "bottom": [
                                    {"name": " 消费 ", "change_pct": "-1.2%"},
                                    {"name": None, "change_pct": 1},
                                    "bad-item",
                                ],
                            }
                        },
                    }
                }
            },
            fallback_fundamental_payload=None,
        )

        self.assertEqual(
            report.details.belong_boards,
            [{"name": "白酒", "type": "行业", "code": "BK0815"}],
        )
        self.assertEqual(
            report.details.sector_rankings,
            {
                "top": [],
                "bottom": [{"name": "消费", "change_pct": -1.2}],
            },
        )

    def test_build_analysis_report_keeps_failed_board_rankings_unavailable(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        report = _build_analysis_report(
            report_data={
                "meta": {},
                "summary": {},
                "strategy": {},
                "details": {},
            },
            query_id="q1",
            stock_code="600519",
            stock_name="贵州茅台",
            context_snapshot={
                "enhanced_context": {
                    "fundamental_context": {
                        "belong_boards": [{"name": "白酒"}],
                        "boards": {
                            "status": "failed",
                            "data": {},
                        },
                    }
                }
            },
            fallback_fundamental_payload=None,
        )

        self.assertEqual(report.details.belong_boards, [{"name": "白酒"}])
        self.assertIsNone(report.details.sector_rankings)

    def test_build_analysis_report_preserves_report_language(self) -> None:
        if _build_analysis_report is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        report = _build_analysis_report(
            report_data={
                "meta": {"report_language": "en"},
                "summary": {"analysis_summary": "English output"},
                "strategy": {},
                "details": {},
            },
            query_id="q1",
            stock_code="AAPL",
            stock_name="Apple",
            context_snapshot={"report_language": "zh"},
            fallback_fundamental_payload=None,
        )

        self.assertEqual(report.meta.report_language, "en")

    def test_load_sync_fundamental_sources_uses_query_and_code_for_fallback(self) -> None:
        if _load_sync_fundamental_sources is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        mock_db = MagicMock()
        raw_result_payload = {
            "model_used": "test-model",
            "report_language": "zh",
            "market_structure_context": _market_structure_context(),
        }
        mock_db.get_analysis_history.return_value = [
            SimpleNamespace(
                context_snapshot=None,
                raw_result=json.dumps(raw_result_payload, ensure_ascii=False),
            )
        ]
        fallback_payload = {
            "earnings": {
                "data": {
                    "financial_report": {"report_date": "2025-12-31"},
                    "dividend": {"ttm_dividend_yield_pct": 2.1},
                }
            }
        }
        mock_db.get_latest_fundamental_snapshot.return_value = fallback_payload

        with patch("src.storage.DatabaseManager.get_instance", return_value=mock_db):
            context_snapshot, fundamental_snapshot, raw_result_snapshot = _load_sync_fundamental_sources(
                query_id="q_sync_001",
                stock_code="600519",
            )

        self.assertIsNone(context_snapshot)
        self.assertEqual(fundamental_snapshot, fallback_payload)
        self.assertEqual(raw_result_snapshot, raw_result_payload)
        mock_db.get_analysis_history.assert_called_once_with(
            query_id="q_sync_001",
            code="600519",
            limit=1,
        )
        mock_db.get_latest_fundamental_snapshot.assert_called_once_with(
            query_id="q_sync_001",
            code="600519",
        )

    def test_get_analysis_status_reads_price_fields_from_context_snapshot_preserving_zero_change_pct(self) -> None:
        if get_analysis_status is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        record = SimpleNamespace(
            id=1,
            code="600519",
            name="贵州茅台",
            report_type="detailed",
            created_at=datetime(2026, 4, 10, 12, 0, 0),
            raw_result=json.dumps({"model_used": "test-model", "report_language": "zh"}),
            context_snapshot=json.dumps(
                {
                    "enhanced_context": {
                        "realtime": {
                            "price": 1234.5,
                            "change_pct": 0.0,
                            "change_60d": 9.99,
                        }
                    },
                    "realtime_quote_raw": {
                        "price": 999.9,
                        "change_pct": 8.88,
                        "pct_chg": 7.77,
                    },
                }
            ),
            sentiment_score=80,
            operation_advice="持有",
            trend_prediction="震荡上行",
            analysis_summary="summary",
            ideal_buy=None,
            secondary_buy=None,
            stop_loss=None,
            take_profit=None,
        )
        mock_db = MagicMock()
        mock_db.get_analysis_history.return_value = [record]

        with patch("api.v1.endpoints.analysis.get_task_queue") as queue_mock, \
             patch("src.storage.DatabaseManager.get_instance", return_value=mock_db):
            queue_mock.return_value.get_task.return_value = None
            status = get_analysis_status("task_123")

        self.assertEqual(status.status, "completed")
        self.assertEqual(status.result.report["meta"]["current_price"], 1234.5)
        self.assertEqual(status.result.report["meta"]["change_pct"], 0.0)
        self.assertEqual(status.result.report["meta"]["model_used"], "test-model")

    def test_get_analysis_status_restores_market_structure_from_raw_result_without_snapshot(self) -> None:
        if get_analysis_status is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        market_structure = {
            "schema_version": "market-structure-v1",
            "status": "partial",
            "market": "cn",
            "market_theme_context": {
                "schema_version": "market-theme-v1",
                "status": "partial",
                "market": "cn",
                "active_themes": [{"name": "机器人概念"}],
            },
            "stock_market_position": {
                "schema_version": "stock-market-position-v1",
                "status": "partial",
                "stock_code": "300024",
                "market": "cn",
                "primary_theme": {"name": "机器人概念"},
            },
        }
        record = SimpleNamespace(
            id=1,
            code="300024",
            name="机器人",
            report_type="detailed",
            created_at=datetime(2026, 4, 10, 12, 0, 0),
            raw_result=json.dumps(
                {
                    "model_used": "test-model",
                    "report_language": "zh",
                    "market_structure_context": market_structure,
                }
            ),
            context_snapshot=None,
            sentiment_score=80,
            operation_advice="持有",
            trend_prediction="震荡上行",
            analysis_summary="summary",
            ideal_buy=None,
            secondary_buy=None,
            stop_loss=None,
            take_profit=None,
        )
        mock_db = MagicMock()
        mock_db.get_analysis_history.return_value = [record]
        mock_db.get_latest_fundamental_snapshot.return_value = None

        with patch("api.v1.endpoints.analysis.get_task_queue") as queue_mock, \
             patch("src.storage.DatabaseManager.get_instance", return_value=mock_db):
            queue_mock.return_value.get_task.return_value = None
            status = get_analysis_status("task_market_structure_raw_1")

        self.assertEqual(status.status, "completed")
        self.assertEqual(
            status.result.report["details"]["market_structure"]["market_theme_context"]["active_themes"][0]["name"],
            "机器人概念",
        )

    def test_get_analysis_status_completed_db_snapshot_includes_agent_snapshot_board_details(self) -> None:
        if get_analysis_status is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        overview = _analysis_context_pack_overview()
        phase_summary = _market_phase_summary()
        record = SimpleNamespace(
            id=1,
            code="600519",
            name="贵州茅台",
            report_type="detailed",
            created_at=datetime(2026, 4, 10, 12, 0, 0),
            raw_result=json.dumps({"model_used": "test-model", "report_language": "zh"}),
            context_snapshot=json.dumps(
                {
                    "fundamental_context": {
                        "belong_boards": [{"name": "白酒", "type": "行业"}],
                        "boards": {
                            "data": {
                                "top": [{"name": "白酒", "change_pct": 2.8}],
                                "bottom": [],
                            }
                        },
                    },
                    "realtime_quote": {
                        "price": 1888.0,
                        "change_pct": 1.56,
                    },
                    "analysis_context_pack_overview": overview,
                    "market_phase_summary": {
                        **phase_summary,
                        "quote_timestamp": "not-public",
                    },
                }
            ),
            news_content="news",
            sentiment_score=80,
            operation_advice="持有",
            trend_prediction="震荡上行",
            analysis_summary="summary",
            ideal_buy=None,
            secondary_buy=None,
            stop_loss=None,
            take_profit=None,
        )
        mock_db = MagicMock()
        mock_db.get_analysis_history.return_value = [record]
        mock_db.get_latest_fundamental_snapshot.return_value = None

        with patch("api.v1.endpoints.analysis.get_task_queue") as queue_mock, \
             patch("src.storage.DatabaseManager.get_instance", return_value=mock_db):
            queue_mock.return_value.get_task.return_value = None
            status = get_analysis_status("task_agent_snapshot_1")

        self.assertEqual(status.status, "completed")
        self.assertEqual(status.result.report["meta"]["current_price"], 1888.0)
        self.assertEqual(status.result.report["meta"]["change_pct"], 1.56)
        self.assertIsNone(status.analysis_phase)
        self.assertEqual(
            status.result.report["meta"]["market_phase_summary"]["phase"],
            "intraday",
        )
        self.assertEqual(
            status.result.report["details"]["belong_boards"],
            [{"name": "白酒", "type": "行业"}],
        )
        self.assertEqual(
            status.result.report["details"]["sector_rankings"]["top"][0]["name"],
            "白酒",
        )
        self.assertEqual(
            status.result.report["details"]["analysis_context_pack_overview"]["metadata"]["trigger_source"],
            "api",
        )
        self.assertEqual(
            status.result.report["details"]["analysis_context_pack_overview"]["data_quality"]["overall_score"],
            88,
        )
        self.assertNotIn(
            "analysis_context_pack_overview",
            status.result.report["details"]["context_snapshot"],
        )
        self.assertNotIn(
            "market_phase_summary",
            status.result.report["details"]["context_snapshot"],
        )

    def test_get_analysis_status_in_memory_task_enriches_agent_snapshot_board_details(self) -> None:
        if get_analysis_status is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        overview = _analysis_context_pack_overview()
        phase_summary = _market_phase_summary()
        context_snapshot = {
            "fundamental_context": {
                "belong_boards": [{"name": "白酒", "type": "行业"}],
                "boards": {
                    "data": {
                        "top": [{"name": "白酒", "change_pct": 2.8}],
                        "bottom": [],
                    }
                },
            },
            "realtime_quote": {
                "price": 1888.0,
                "change_pct": 1.56,
            },
            "analysis_context_pack_overview": overview,
            "market_phase_summary": phase_summary,
        }
        task = SimpleNamespace(
            task_id="task_agent_snapshot_in_memory_1",
            stock_code="600519",
            stock_name="贵州茅台",
            status=TaskStatus.COMPLETED,
            progress=100,
            result={
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report": {
                    "meta": {
                        "query_id": "task_agent_snapshot_in_memory_1",
                        "stock_code": "600519",
                        "stock_name": "贵州茅台",
                        "report_type": "detailed",
                        "report_language": "zh",
                        "created_at": "2026-04-10T12:00:00",
                        "model_used": "test-model",
                    },
                    "summary": {"analysis_summary": "summary"},
                    "details": {"news_summary": "news"},
                },
            },
            error=None,
            original_query=None,
            selection_source=None,
            analysis_phase="auto",
            skills=None,
            created_at=datetime(2026, 4, 10, 12, 0, 0),
            completed_at=datetime(2026, 4, 10, 12, 1, 0),
        )
        record = SimpleNamespace(context_snapshot=json.dumps(context_snapshot))
        mock_db = MagicMock()
        mock_db.get_analysis_history.return_value = [record]
        mock_db.get_latest_fundamental_snapshot.return_value = None

        with patch("api.v1.endpoints.analysis.get_task_queue") as queue_mock, \
             patch("src.storage.DatabaseManager.get_instance", return_value=mock_db):
            queue_mock.return_value.get_task.return_value = task
            status = get_analysis_status("task_agent_snapshot_in_memory_1")

        self.assertEqual(status.status, "completed")
        self.assertEqual(status.result.report["meta"]["current_price"], 1888.0)
        self.assertEqual(status.result.report["meta"]["change_pct"], 1.56)
        self.assertEqual(
            status.result.report["meta"]["market_phase_summary"]["phase"],
            "intraday",
        )
        self.assertEqual(
            status.result.report["details"]["belong_boards"],
            [{"name": "白酒", "type": "行业"}],
        )
        self.assertEqual(
            status.result.report["details"]["sector_rankings"]["top"][0]["name"],
            "白酒",
        )
        self.assertEqual(
            status.result.report["details"]["analysis_context_pack_overview"]["metadata"]["trigger_source"],
            "api",
        )
        self.assertEqual(
            status.result.report["details"]["analysis_context_pack_overview"]["data_quality"]["overall_score"],
            88,
        )
        self.assertNotIn(
            "analysis_context_pack_overview",
            status.result.report["details"]["context_snapshot"],
        )
        self.assertNotIn(
            "market_phase_summary",
            status.result.report["details"]["context_snapshot"],
        )
        mock_db.get_analysis_history.assert_called_once_with(
            query_id="task_agent_snapshot_in_memory_1",
            code="600519",
            limit=1,
        )

    def test_get_analysis_status_in_memory_task_without_db_snapshot_preserves_service_phase_summary(self) -> None:
        if get_analysis_status is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        phase_summary = _market_phase_summary()
        task = SimpleNamespace(
            task_id="task_no_snapshot_in_memory_1",
            stock_code="600519",
            stock_name="贵州茅台",
            status=TaskStatus.COMPLETED,
            progress=100,
            analysis_phase="intraday",
            result={
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report": {
                    "meta": {
                        "query_id": "task_no_snapshot_in_memory_1",
                        "stock_code": "600519",
                        "stock_name": "贵州茅台",
                        "market_phase_summary": phase_summary,
                    },
                    "summary": {"analysis_summary": "summary"},
                },
            },
            error=None,
            original_query=None,
            selection_source=None,
            skills=None,
            created_at=datetime(2026, 4, 10, 12, 0, 0),
            completed_at=datetime(2026, 4, 10, 12, 1, 0),
        )

        with patch("api.v1.endpoints.analysis.get_task_queue") as queue_mock, \
             patch(
                 "api.v1.endpoints.analysis._load_sync_fundamental_sources",
                 return_value=(None, None, None),
             ) as load_sources:
            queue_mock.return_value.get_task.return_value = task
            status = get_analysis_status("task_no_snapshot_in_memory_1")

        self.assertEqual(status.status, "completed")
        self.assertEqual(status.analysis_phase, "intraday")
        self.assertIsNotNone(status.result)
        self.assertEqual(
            status.result.report["meta"]["market_phase_summary"]["phase"],
            "intraday",
        )
        load_sources.assert_called_once_with(
            query_id="task_no_snapshot_in_memory_1",
            stock_code="600519",
        )

    def test_openapi_declares_single_and_batch_async_202_payloads(self) -> None:
        if create_app is None:
            self.skipTest("fastapi is not installed in this test environment")

        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(static_dir=Path(temp_dir))
            schema = app.openapi()["paths"]["/api/v1/analysis/analyze"]["post"]["responses"]["202"][
                "content"
            ]["application/json"]["schema"]

        refs = {item["$ref"] for item in schema["anyOf"]}
        self.assertEqual(
            refs,
            {
                "#/components/schemas/TaskAccepted",
                "#/components/schemas/BatchTaskAcceptedResponse",
            },
        )

    def test_openapi_declares_backtest_phase_filter_enum_and_400(self) -> None:
        if create_app is None:
            self.skipTest("fastapi is not installed in this test environment")

        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(static_dir=Path(temp_dir))
            paths = app.openapi()["paths"]

        for path in (
            "/api/v1/backtest/results",
            "/api/v1/backtest/performance",
            "/api/v1/backtest/performance/{code}",
        ):
            operation = paths[path]["get"]
            self.assertIn("400", operation["responses"])
            params = {param["name"]: param for param in operation["parameters"]}
            schema = params["analysis_phase"]["schema"]
            enum_values = set()
            stack = [schema]
            while stack:
                current = stack.pop()
                if not isinstance(current, dict):
                    continue
                enum_values.update(current.get("enum") or [])
                stack.extend(current.get("anyOf") or [])
                stack.extend(current.get("oneOf") or [])

            self.assertEqual(enum_values, {"premarket", "intraday", "postmarket", "unknown"})

    def test_market_review_endpoint_accepts_omitted_body(self) -> None:
        if create_app is None or analysis_endpoint_module is None:
            self.skipTest("fastapi is not installed in this test environment")

        config = SimpleNamespace(trading_day_check_enabled=True, market_review_region="cn")

        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(static_dir=Path(temp_dir))
            request_body = app.openapi()["paths"]["/api/v1/analysis/market-review"]["post"][
                "requestBody"
            ]

        self.assertNotIn("required", request_body)

        task_queue = MagicMock()
        task_queue.submit_background_task.return_value = SimpleNamespace(task_id="market-task-omitted")

        with patch.object(
            analysis_endpoint_module,
            "_try_acquire_market_review_lock",
            return_value=object(),
        ), patch("api.v1.endpoints.analysis.get_task_queue", return_value=task_queue):
            response = trigger_market_review(
                request=None,
                config=config,
            )

        self.assertTrue(response.send_notification)
        self.assertEqual(response.task_id, "market-task-omitted")
        task_queue.submit_background_task.assert_called_once()

    def test_trigger_analysis_rejects_blank_only_stock_inputs(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        with self.assertRaises(Exception) as ctx:
            trigger_analysis(
                request=SimpleNamespace(
                    stock_code="   ",
                    stock_codes=None,
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=False,
                    analysis_phase="auto",
                ),
                config=SimpleNamespace(),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(
            ctx.exception.detail["message"],
            "股票代码不能为空或仅包含空白字符",
        )

    def test_trigger_analysis_rejects_obviously_invalid_mixed_input_before_resolution(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        with patch("api.v1.endpoints.analysis.resolve_name_to_code") as resolve_mock:
            with self.assertRaises(Exception) as ctx:
                trigger_analysis(
                    request=SimpleNamespace(
                        stock_code="00AAAAA",
                        stock_codes=None,
                        report_type="detailed",
                        force_refresh=False,
                        async_mode=True,
                        analysis_phase="auto",
                    ),
                    config=SimpleNamespace(),
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["message"], "请输入有效的股票代码或股票名称")
        resolve_mock.assert_not_called()

    def test_trigger_analysis_rejects_unresolvable_alpha_garbage(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        with patch("api.v1.endpoints.analysis.resolve_name_to_code", return_value=None), \
             patch("api.v1.endpoints.analysis.get_task_queue") as queue_mock:
            with self.assertRaises(Exception) as ctx:
                trigger_analysis(
                    request=SimpleNamespace(
                        stock_code="aaaaaaa",
                        stock_codes=None,
                        report_type="detailed",
                        force_refresh=False,
                        async_mode=True,
                        analysis_phase="auto",
                    ),
                    config=SimpleNamespace(),
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["message"], "请输入有效的股票代码或股票名称")
        queue_mock.assert_not_called()

    def test_trigger_analysis_accepts_us_suffix_code(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([], [])

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), \
             patch("api.v1.endpoints.analysis.resolve_name_to_code") as resolve_mock:
            response = trigger_analysis(
                request=SimpleNamespace(
                    stock_code="AAPL.US",
                    stock_codes=None,
                    stock_name=None,
                    original_query="AAPL.US",
                    selection_source="manual",
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=True,
                    notify=True,
                    analysis_phase="auto",
                ),
                config=SimpleNamespace(),
            )

        self.assertEqual(response.status_code, 202)
        resolve_mock.assert_not_called()
        queue.submit_tasks_batch.assert_called_once_with(
            stock_codes=["AAPL.US"],
            stock_name=None,
            original_query="AAPL.US",
            selection_source="manual",
            report_type="detailed",
            analysis_phase="auto",
            force_refresh=False,
            notify=True,
        )

    def test_trigger_analysis_resolves_bare_code_from_stock_index_before_default_market(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([], [])

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), \
             patch("api.v1.endpoints.analysis.resolve_index_stock_code", return_value="005930.KS"), \
             patch("api.v1.endpoints.analysis.resolve_name_to_code") as resolve_mock:
            response = trigger_analysis(
                request=SimpleNamespace(
                    stock_code="005930",
                    stock_codes=None,
                    stock_name=None,
                    original_query="005930",
                    selection_source="manual",
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=True,
                    notify=True,
                    analysis_phase="auto",
                ),
                config=SimpleNamespace(),
            )

        self.assertEqual(response.status_code, 202)
        resolve_mock.assert_not_called()
        queue.submit_tasks_batch.assert_called_once_with(
            stock_codes=["005930.KS"],
            stock_name=None,
            original_query="005930",
            selection_source="manual",
            report_type="detailed",
            analysis_phase="auto",
            force_refresh=False,
            notify=True,
        )

    def test_trigger_analysis_resolves_bare_4_digit_jp_code_before_name_resolution(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([], [])

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), \
             patch("api.v1.endpoints.analysis.resolve_index_stock_code_for_analysis", return_value="7203.T") as resolve_index_mock, \
             patch("api.v1.endpoints.analysis.resolve_name_to_code") as resolve_mock:
            response = trigger_analysis(
                request=SimpleNamespace(
                    stock_code="7203",
                    stock_codes=None,
                    stock_name=None,
                    original_query="7203",
                    selection_source="manual",
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=True,
                    notify=True,
                    analysis_phase="auto",
                ),
                config=SimpleNamespace(),
            )

        self.assertEqual(response.status_code, 202)
        resolve_index_mock.assert_called_once_with("7203")
        resolve_mock.assert_not_called()
        queue.submit_tasks_batch.assert_called_once_with(
            stock_codes=["7203.T"],
            stock_name=None,
            original_query="7203",
            selection_source="manual",
            report_type="detailed",
            analysis_phase="auto",
            force_refresh=False,
            notify=True,
        )

    def test_trigger_analysis_accepts_camel_case_report_language_alias(self) -> None:
        if trigger_analysis is None or analysis_endpoint_module is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        task = SimpleNamespace(
            task_id="task-report-language-1",
            trace_id="trace-report-language-1",
            stock_code="600519",
            analysis_phase="auto",
        )
        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([task], [])

        request = analysis_endpoint_module.AnalyzeRequest.model_validate({
            "stock_code": "600519",
            "async_mode": True,
            "reportLanguage": "en",
        })

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
            response = trigger_analysis(request=request, config=SimpleNamespace())

        self.assertEqual(response.status_code, 202)
        queue.submit_tasks_batch.assert_called_once_with(
            stock_codes=["600519"],
            stock_name=None,
            original_query=None,
            selection_source=None,
            report_type="detailed",
            analysis_phase="auto",
            force_refresh=False,
            notify=True,
            report_language="en",
        )

    def test_trigger_analysis_async_passes_and_returns_analysis_phase(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        task = SimpleNamespace(
            task_id="task-phase-1",
            trace_id="trace-phase-1",
            stock_code="600519",
            analysis_phase="intraday",
        )
        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([task], [])

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
            response = trigger_analysis(
                request=SimpleNamespace(
                    stock_code="600519",
                    stock_codes=None,
                    stock_name=None,
                    original_query=None,
                    selection_source=None,
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=True,
                    notify=True,
                    analysis_phase="intraday",
                ),
                config=SimpleNamespace(),
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(json.loads(response.body)["analysis_phase"], "intraday")
        queue.submit_tasks_batch.assert_called_once_with(
            stock_codes=["600519"],
            stock_name=None,
            original_query=None,
            selection_source=None,
            report_type="detailed",
            analysis_phase="intraday",
            force_refresh=False,
            notify=True,
        )

    def test_trigger_analysis_accepts_hk_suffix_code_from_autocomplete(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([], [])

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), \
             patch("api.v1.endpoints.analysis.resolve_name_to_code") as resolve_mock:
            response = trigger_analysis(
                request=SimpleNamespace(
                    stock_code="00700.HK",
                    stock_codes=None,
                    stock_name="腾讯控股",
                    original_query="00700",
                    selection_source="autocomplete",
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=True,
                    analysis_phase="auto",
                ),
                config=SimpleNamespace(),
            )

        self.assertEqual(response.status_code, 202)
        resolve_mock.assert_not_called()
        queue.submit_tasks_batch.assert_called_once_with(
            stock_codes=["00700.HK"],
            stock_name="腾讯控股",
            original_query="00700",
            selection_source="autocomplete",
            report_type="detailed",
            analysis_phase="auto",
            force_refresh=False,
            notify=True,
        )

    def test_trigger_analysis_accepts_bse_suffix_code_from_autocomplete(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([], [])

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), \
             patch("api.v1.endpoints.analysis.resolve_name_to_code") as resolve_mock:
            response = trigger_analysis(
                request=SimpleNamespace(
                    stock_code="920493.BJ",
                    stock_codes=None,
                    stock_name="示例北交所股票",
                    original_query="920493",
                    selection_source="autocomplete",
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=True,
                    notify=True,
                    analysis_phase="auto",
                ),
                config=SimpleNamespace(),
            )

        self.assertEqual(response.status_code, 202)
        resolve_mock.assert_not_called()
        queue.submit_tasks_batch.assert_called_once_with(
            stock_codes=["920493.BJ"],
            stock_name="示例北交所股票",
            original_query="920493",
            selection_source="autocomplete",
            report_type="detailed",
            analysis_phase="auto",
            force_refresh=False,
            notify=True,
        )

    def test_trigger_analysis_rejects_non_bse_code_with_bj_exchange_hint(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        for bad_code in ("600519.BJ", "BJ600519"):
            with self.subTest(bad_code=bad_code):
                queue = MagicMock()

                with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), \
                     patch("api.v1.endpoints.analysis.resolve_name_to_code") as resolve_mock:
                    with self.assertRaises(Exception) as exc:
                        trigger_analysis(
                            request=SimpleNamespace(
                                stock_code=bad_code,
                                stock_codes=None,
                                stock_name=None,
                                original_query=bad_code,
                                selection_source="manual",
                                report_type="detailed",
                                force_refresh=False,
                                async_mode=True,
                                notify=True,
                                analysis_phase="auto",
                            ),
                            config=SimpleNamespace(),
                        )

                self.assertEqual(exc.exception.status_code, 400)
                self.assertEqual(exc.exception.detail["error"], "validation_error")
                resolve_mock.assert_not_called()
                queue.submit_tasks_batch.assert_not_called()

    def test_trigger_analysis_accepts_hk_prefixed_code(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([], [])

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), \
             patch("api.v1.endpoints.analysis.resolve_name_to_code") as resolve_mock:
            response = trigger_analysis(
                request=SimpleNamespace(
                    stock_code="HK00700",
                    stock_codes=None,
                    stock_name=None,
                    original_query="HK00700",
                    selection_source="manual",
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=True,
                    analysis_phase="auto",
                ),
                config=SimpleNamespace(),
            )

        self.assertEqual(response.status_code, 202)
        resolve_mock.assert_not_called()
        queue.submit_tasks_batch.assert_called_once_with(
            stock_codes=["HK00700"],
            stock_name=None,
            original_query="HK00700",
            selection_source="manual",
            report_type="detailed",
            analysis_phase="auto",
            force_refresh=False,
            notify=True,
        )

    def test_trigger_analysis_allows_stock_names_with_star_and_hyphen(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([], [])

        with patch("api.v1.endpoints.analysis.resolve_name_to_code", return_value="688783"), \
             patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
            response = trigger_analysis(
                request=SimpleNamespace(
                    stock_code="西安奕材-U",
                    stock_codes=None,
                    stock_name=None,
                    original_query="西安奕材-U",
                    selection_source="manual",
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=True,
                    notify=True,
                    analysis_phase="auto",
                ),
                config=SimpleNamespace(),
            )

        self.assertEqual(response.status_code, 202)
        queue.submit_tasks_batch.assert_called_once_with(
            stock_codes=["688783"],
            stock_name=None,
            original_query="西安奕材-U",
            selection_source="manual",
            report_type="detailed",
            analysis_phase="auto",
            force_refresh=False,
            notify=True,
        )

    def test_trigger_analysis_accepts_resolvable_free_text_input(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([], [])

        with patch("api.v1.endpoints.analysis.resolve_name_to_code", return_value="600519"), \
             patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
            response = trigger_analysis(
                request=SimpleNamespace(
                    stock_code="贵州茅台",
                    stock_codes=None,
                    stock_name=None,
                    original_query="贵州茅台",
                    selection_source="manual",
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=True,
                    notify=True,
                    analysis_phase="auto",
                ),
                config=SimpleNamespace(),
            )

        self.assertEqual(response.status_code, 202)
        queue.submit_tasks_batch.assert_called_once_with(
            stock_codes=["600519"],
            stock_name=None,
            original_query="贵州茅台",
            selection_source="manual",
            report_type="detailed",
            analysis_phase="auto",
            force_refresh=False,
            notify=True,
        )

    def test_trigger_analysis_preserves_batch_metadata(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([], [])

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
            response = trigger_analysis(
                request=SimpleNamespace(
                    stock_code=None,
                    stock_codes=["600519", "000001"],
                    stock_name=None,
                    original_query="uploaded.csv",
                    selection_source="import",
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=True,
                    notify=True,
                    analysis_phase="auto",
                ),
                config=SimpleNamespace(),
            )

        self.assertEqual(response.status_code, 202)
        queue.submit_tasks_batch.assert_called_once_with(
            stock_codes=["600519", "000001"],
            stock_name=None,
            original_query="uploaded.csv",
            selection_source="import",
            report_type="detailed",
            analysis_phase="auto",
            force_refresh=False,
            notify=True,
        )

    def test_trigger_analysis_rejects_cross_request_duplicate_for_equivalent_code_shapes(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        original_instance = AnalysisTaskQueue._instance
        AnalysisTaskQueue._instance = None
        try:
            queue = AnalysisTaskQueue(max_workers=1)
            queue._executor = type("ExecutorStub", (), {"submit": lambda self, *args, **kwargs: Future()})()

            with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
                first = trigger_analysis(
                    request=SimpleNamespace(
                        stock_code="600519",
                        stock_codes=None,
                        stock_name=None,
                        original_query=None,
                        selection_source=None,
                        report_type="detailed",
                        force_refresh=False,
                        async_mode=True,
                        notify=True,
                        analysis_phase="auto",
                    ),
                    config=SimpleNamespace(),
                )
                second = trigger_analysis(
                    request=SimpleNamespace(
                        stock_code="600519.SH",
                        stock_codes=None,
                        stock_name=None,
                        original_query=None,
                        selection_source=None,
                        report_type="detailed",
                        force_refresh=False,
                        async_mode=True,
                        notify=True,
                        analysis_phase="auto",
                    ),
                    config=SimpleNamespace(),
                )

            self.assertEqual(first.status_code, 202)
            self.assertEqual(second.status_code, 409)
            self.assertEqual(json.loads(second.body)["error"], "duplicate_task")
            self.assertEqual(json.loads(second.body)["stock_code"], "600519.SH")
            self.assertEqual(
                json.loads(second.body)["existing_task_id"],
                json.loads(first.body)["task_id"],
            )
        finally:
            queue = AnalysisTaskQueue._instance
            if queue is not None and queue is not original_instance:
                executor = getattr(queue, "_executor", None)
                if executor is not None and hasattr(executor, "shutdown"):
                    executor.shutdown(wait=False, cancel_futures=True)
            AnalysisTaskQueue._instance = original_instance

    def test_trigger_analysis_batch_does_not_apply_single_stock_name_to_all_tasks(self) -> None:
        if trigger_analysis is None:
            self.skipTest("fastapi is not installed in this test environment")

        queue = MagicMock()
        queue.submit_tasks_batch.return_value = ([], [])

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
            response = trigger_analysis(
                request=SimpleNamespace(
                    stock_code=None,
                    stock_codes=["600519", "000001"],
                    stock_name="贵州茅台",
                    original_query="茅台,平安银行",
                    selection_source="import",
                    report_type="detailed",
                    force_refresh=False,
                    async_mode=True,
                    notify=True,
                    analysis_phase="auto",
                ),
                config=SimpleNamespace(),
            )

        self.assertEqual(response.status_code, 202)
        queue.submit_tasks_batch.assert_called_once_with(
            stock_codes=["600519", "000001"],
            stock_name=None,
            original_query="茅台,平安银行",
            selection_source="import",
            report_type="detailed",
            analysis_phase="auto",
            force_refresh=False,
            notify=True,
        )

    def test_spa_fallback_returns_json_404_for_bare_api_path(self) -> None:
        if create_app is None:
            self.skipTest("fastapi is not installed in this test environment")

        with tempfile.TemporaryDirectory() as temp_dir:
            static_dir = Path(temp_dir)
            (static_dir / "index.html").write_text("<html>spa</html>", encoding="utf-8")
            app = create_app(static_dir=static_dir)

            serve_spa = next(
                route.endpoint for route in app.routes
                if getattr(route, "path", None) == "/{full_path:path}"
            )

            response = asyncio.run(serve_spa(None, "api"))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            json.loads(response.body),
            {"error": "not_found", "message": "API endpoint /api not found"},
        )

    def test_spa_fallback_blocks_path_traversal(self) -> None:
        """SPA fallback must not serve files outside static_dir.

        Starlette's :path converter does not normalize `..` segments, so
        without an explicit containment check `static_dir / full_path` can
        resolve to arbitrary files on disk (CVE-class path traversal).
        """
        if create_app is None:
            self.skipTest("fastapi is not installed in this test environment")

        from fastapi.responses import FileResponse

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            static_dir = root / "static"
            static_dir.mkdir()
            (static_dir / "index.html").write_text("<html>spa</html>", encoding="utf-8")
            secret = root / "secret.txt"
            secret.write_text("TOPSECRET", encoding="utf-8")

            app = create_app(static_dir=static_dir)
            serve_spa = next(
                route.endpoint for route in app.routes
                if getattr(route, "path", None) == "/{full_path:path}"
            )

            for traversal in ("../secret.txt", "../../secret.txt", "foo/../../secret.txt"):
                with self.subTest(traversal=traversal):
                    response = asyncio.run(serve_spa(None, traversal))
                    self.assertIsInstance(response, FileResponse)
                    self.assertEqual(Path(response.path).resolve(), (static_dir / "index.html").resolve())

    def test_sse_generator_reraises_cancelled_error(self) -> None:
        """CancelledError must propagate (not be swallowed) from the SSE event generator."""
        try:
            from api.v1.endpoints.analysis import task_stream
        except Exception:  # pragma: no cover - optional dependency environments
            self.skipTest("api.v1.endpoints.analysis not importable")

        class _NeverQueue:
            """Queue that never returns from get(), used to exercise cancellation."""
            async def get(self):
                await asyncio.sleep(3600)

        never_queue = _NeverQueue()
        mock_task_queue = MagicMock()
        mock_task_queue.list_pending_tasks.return_value = []

        async def run():
            with patch("api.v1.endpoints.analysis.get_task_queue", return_value=mock_task_queue), \
                 patch("asyncio.Queue", return_value=never_queue):
                response = await task_stream()
                gen = response.body_iterator

                async def consume():
                    async for _ in gen:
                        pass

                task = asyncio.create_task(consume())
                await asyncio.sleep(0)  # let generator start and reach wait_for
                task.cancel()
                await task  # should re-raise CancelledError

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(run())

        mock_task_queue.unsubscribe.assert_called_once_with(never_queue)

    def test_get_task_list_includes_analysis_phase_and_skills(self) -> None:
        if get_task_list is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        task = SimpleNamespace(
            task_id="task-list-phase",
            trace_id="trace-list-phase",
            stock_code="600519",
            stock_name="贵州茅台",
            status=TaskStatus.PROCESSING,
            progress=42,
            message="running",
            report_type="detailed",
            created_at=datetime(2026, 4, 10, 12, 0, 0),
            started_at=datetime(2026, 4, 10, 12, 0, 1),
            completed_at=None,
            error=None,
            original_query="茅台",
            selection_source="manual",
            analysis_phase="postmarket",
            skills=["growth_quality"],
        )
        queue = MagicMock()
        queue.list_all_tasks.return_value = [task]
        queue.get_task_stats.return_value = {
            "total": 1,
            "pending": 0,
            "processing": 1,
            "completed": 0,
            "failed": 0,
        }

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
            response = get_task_list(status=None, limit=20)

        self.assertEqual(response.tasks[0].analysis_phase, "postmarket")
        self.assertEqual(response.tasks[0].skills, ["growth_quality"])


class BatchTaskQueueContractTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._original_instance = AnalysisTaskQueue._instance
        AnalysisTaskQueue._instance = None

    def tearDown(self) -> None:
        queue = AnalysisTaskQueue._instance
        if queue is not None and queue is not self._original_instance:
            executor = getattr(queue, "_executor", None)
            if executor is not None and hasattr(executor, "shutdown"):
                executor.shutdown(wait=False, cancel_futures=True)
        AnalysisTaskQueue._instance = self._original_instance

    def test_batch_submit_rolls_back_when_executor_submit_fails(self) -> None:
        class FailingExecutor:
            def __init__(self) -> None:
                self.submit_count = 0

            def submit(self, *args, **kwargs):
                self.submit_count += 1
                if self.submit_count == 2:
                    raise RuntimeError("executor down")
                return Future()

        queue = AnalysisTaskQueue(max_workers=1)
        queue._executor = FailingExecutor()

        with self.assertRaisesRegex(RuntimeError, "executor down"):
            queue.submit_tasks_batch(["600519", "000858"], report_type="detailed")

        self.assertEqual(queue._tasks, {})
        self.assertEqual(queue._analyzing_stocks, {})
        self.assertEqual(queue._futures, {})

    def test_batch_submit_ignores_blank_stock_codes(self) -> None:
        queue = AnalysisTaskQueue(max_workers=1)
        queue._executor = type("ExecutorStub", (), {"submit": lambda self, *args, **kwargs: Future()})()

        accepted, duplicates = queue.submit_tasks_batch(["600519", "   "], report_type="detailed")

        self.assertEqual([task.stock_code for task in accepted], ["600519"])
        self.assertEqual(duplicates, [])
        self.assertEqual(sorted(task.stock_code for task in queue._tasks.values()), ["600519"])

    def test_batch_submit_and_worker_use_copied_request_skills(self) -> None:
        class CapturingExecutor:
            def __init__(self) -> None:
                self.calls = []

            def submit(self, fn, *args, **kwargs):
                self.calls.append((fn, args, kwargs))
                return Future()

        queue = AnalysisTaskQueue(max_workers=1)
        executor = CapturingExecutor()
        queue._executor = executor
        broadcast_events = []
        queue._broadcast_event = lambda event_type, data: broadcast_events.append((event_type, data))
        request_skills = ["growth_quality"]
        portfolio_context = {
            "account_id": 7,
            "account_name": "Main",
            "symbol": "600519",
            "quantity": 100,
        }

        accepted, duplicates = queue.submit_tasks_batch(
            ["600519"],
            report_type="detailed",
            analysis_phase="intraday",
            query_source="portfolio",
            portfolio_context=portfolio_context,
            skills=request_skills,
        )
        request_skills.append("mutated_after_submit")
        portfolio_context["quantity"] = 999

        self.assertEqual(duplicates, [])
        self.assertEqual(accepted[0].analysis_phase, "intraday")
        self.assertEqual(accepted[0].to_dict()["analysis_phase"], "intraday")
        self.assertNotIn("portfolio_context", accepted[0].to_dict())
        self.assertNotIn("query_source", accepted[0].to_dict())
        self.assertNotIn("portfolio_context", broadcast_events[0][1])
        self.assertNotIn("query_source", broadcast_events[0][1])
        self.assertEqual(accepted[0].copy().analysis_phase, "intraday")
        self.assertEqual(accepted[0].query_source, "portfolio")
        self.assertEqual(accepted[0].portfolio_context["quantity"], 100)
        self.assertEqual(accepted[0].copy().portfolio_context["quantity"], 100)
        self.assertEqual(accepted[0].skills, ["growth_quality"])
        self.assertIs(executor.calls[0][1][5], accepted[0].skills)
        self.assertIsNone(executor.calls[0][1][6])

        service_instance = MagicMock()
        service_instance.analyze_stock.return_value = {"stock_name": "贵州茅台"}
        with patch("src.services.analysis_service.AnalysisService", return_value=service_instance):
            executor.calls[0][0](*executor.calls[0][1])

        self.assertIs(
            service_instance.analyze_stock.call_args.kwargs["skills"],
            accepted[0].skills,
        )
        self.assertEqual(service_instance.analyze_stock.call_args.kwargs["skills"], ["growth_quality"])
        self.assertEqual(service_instance.analyze_stock.call_args.kwargs["analysis_phase"], "intraday")
        self.assertEqual(service_instance.analyze_stock.call_args.kwargs["query_source"], "portfolio")
        self.assertEqual(
            service_instance.analyze_stock.call_args.kwargs["portfolio_context"]["quantity"],
            100,
        )

    def test_batch_submit_deduplicates_equivalent_stock_code_shapes(self) -> None:
        queue = AnalysisTaskQueue(max_workers=1)
        queue._executor = type("ExecutorStub", (), {"submit": lambda self, *args, **kwargs: Future()})()

        accepted, duplicates = queue.submit_tasks_batch(["600519"], report_type="detailed")

        self.assertEqual(len(accepted), 1)
        self.assertEqual(duplicates, [])
        self.assertTrue(queue.is_analyzing("600519.SH"))
        self.assertEqual(queue.get_analyzing_task_id("600519.SH"), accepted[0].task_id)

        accepted_again, duplicates_again = queue.submit_tasks_batch(
            ["600519.SH"],
            report_type="detailed",
            analysis_phase="intraday",
        )

        self.assertEqual(accepted_again, [])
        self.assertEqual(len(duplicates_again), 1)
        self.assertEqual(duplicates_again[0].stock_code, "600519.SH")
        self.assertEqual(duplicates_again[0].existing_task_id, accepted[0].task_id)

    def test_submit_task_rejects_blank_stock_code(self) -> None:
        queue = AnalysisTaskQueue(max_workers=1)
        queue._executor = type("ExecutorStub", (), {"submit": lambda self, *args, **kwargs: Future()})()

        with self.assertRaisesRegex(ValueError, "股票代码不能为空或仅包含空白字符"):
            queue.submit_task("   ", report_type="detailed")

        self.assertEqual(queue._tasks, {})
        self.assertEqual(queue._analyzing_stocks, {})
        self.assertEqual(queue._futures, {})

    def test_batch_submit_broadcasts_task_created_while_queue_lock_is_held(self) -> None:
        queue = AnalysisTaskQueue(max_workers=1)
        queue._executor = type("ExecutorStub", (), {"submit": lambda self, *args, **kwargs: Future()})()
        lock_states = []

        def record_broadcast(event_type, data):
            if event_type == "task_created":
                lock_states.append(queue._data_lock._is_owned())

        queue._broadcast_event = record_broadcast

        accepted, duplicates = queue.submit_tasks_batch(["600519", "000858"], report_type="detailed")

        self.assertEqual(len(accepted), 2)
        self.assertEqual(duplicates, [])
        self.assertEqual(lock_states, [True, True])

    def test_update_task_progress_broadcasts_task_progress_event(self) -> None:
        queue = AnalysisTaskQueue(max_workers=1)
        queue._executor = type("ExecutorStub", (), {"submit": lambda self, *args, **kwargs: Future()})()
        accepted, _ = queue.submit_tasks_batch(["600519"], report_type="detailed")

        events = []
        queue._broadcast_event = lambda event_type, data: events.append((event_type, data))

        updated = queue.update_task_progress(
            accepted[0].task_id,
            62,
            "LLM 正在生成分析结果",
        )

        self.assertIsNotNone(updated)
        self.assertEqual(updated.progress, 62)
        self.assertEqual(updated.message, "LLM 正在生成分析结果")
        self.assertEqual(events, [("task_progress", updated.to_dict())])


class ImageStockExtractorContractTestCase(unittest.TestCase):
    def test_litellm_completion_patch_target_remains_available(self) -> None:
        cfg = SimpleNamespace(
            vision_model="",
            openai_vision_model=None,
            litellm_model="",
            gemini_api_keys=["sk-gemini-testkey-1234"],
            gemini_model="gemini-2.0-flash",
            anthropic_api_keys=[],
            anthropic_model="claude-3-5-sonnet-20241022",
            openai_api_keys=[],
            openai_model="gpt-4o-mini",
            openai_base_url=None,
        )
        msg = MagicMock()
        msg.content = '["600519"]'
        choice = MagicMock()
        choice.message = msg
        response = MagicMock()
        response.choices = [choice]

        with patch("src.services.image_stock_extractor.get_config", return_value=cfg), \
             patch("src.services.image_stock_extractor.litellm.completion", return_value=response) as mock_completion:
            result = _call_litellm_vision("base64data", "image/jpeg")

        self.assertEqual(result, '["600519"]')
        mock_completion.assert_called_once()


if __name__ == "__main__":
    unittest.main()
