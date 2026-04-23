# -*- coding: utf-8 -*-
"""Regression tests for analysis API/report-type contracts."""

import asyncio
from concurrent.futures import Future
from datetime import datetime
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

try:
    from api.app import create_app
    from api.v1.endpoints.analysis import (
        trigger_analysis,
        _handle_sync_analysis,
        _build_analysis_report,
        _load_sync_fundamental_sources,
        get_analysis_status,
    )
except Exception:  # pragma: no cover - optional dependency environments
    create_app = None
    trigger_analysis = None
    _handle_sync_analysis = None
    _build_analysis_report = None
    _load_sync_fundamental_sources = None
    get_analysis_status = None

from src.enums import ReportType
from src.services.analysis_service import AnalysisService
from src.services.image_stock_extractor import _call_litellm_vision
from src.services.task_queue import AnalysisTaskQueue


class AnalysisApiContractTestCase(unittest.TestCase):
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
        mock_db.get_analysis_history.return_value = [SimpleNamespace(context_snapshot=None)]
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
            context_snapshot, fundamental_snapshot = _load_sync_fundamental_sources(
                query_id="q_sync_001",
                stock_code="600519",
            )

        self.assertIsNone(context_snapshot)
        self.assertEqual(fundamental_snapshot, fallback_payload)
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
            force_refresh=False,
            notify=True,
        )

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

    def test_batch_submit_deduplicates_equivalent_stock_code_shapes(self) -> None:
        queue = AnalysisTaskQueue(max_workers=1)
        queue._executor = type("ExecutorStub", (), {"submit": lambda self, *args, **kwargs: Future()})()

        accepted, duplicates = queue.submit_tasks_batch(["600519"], report_type="detailed")

        self.assertEqual(len(accepted), 1)
        self.assertEqual(duplicates, [])
        self.assertTrue(queue.is_analyzing("600519.SH"))
        self.assertEqual(queue.get_analyzing_task_id("600519.SH"), accepted[0].task_id)

        accepted_again, duplicates_again = queue.submit_tasks_batch(["600519.SH"], report_type="detailed")

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
