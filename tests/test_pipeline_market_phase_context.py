# -*- coding: utf-8 -*-
"""Regression tests for Issue #1386 P1a market phase context plumbing."""

import os
import sys
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import AnalysisResult
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType
from src.services.run_diagnostics import activate_run_diagnostic_context, current_diagnostic_snapshot, reset_run_diagnostic_context


def _analysis_result() -> AnalysisResult:
    return AnalysisResult(
        code="600519",
        name="贵州茅台",
        sentiment_score=62,
        trend_prediction="震荡",
        operation_advice="持有",
        decision_type="hold",
    )


def _phase_payload() -> dict:
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
        "trigger_source": "system",
        "analysis_intent": "auto",
        "warnings": [],
    }


def _make_pipeline(*, agent_mode: bool = False, save_context_snapshot: bool = True) -> StockAnalysisPipeline:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        enable_realtime_quote=False,
        enable_chip_distribution=False,
        realtime_source_priority=[],
        agent_mode=agent_mode,
        agent_skills=[],
        save_context_snapshot=save_context_snapshot,
        report_language="zh",
        report_integrity_enabled=False,
        fundamental_stage_timeout_seconds=1,
    )
    pipeline.source_message = None
    pipeline.query_id = None
    pipeline.query_source = "system"
    pipeline.save_context_snapshot = save_context_snapshot
    pipeline.progress_callback = None
    pipeline.analysis_skills = None
    pipeline.analysis_phase = "auto"
    pipeline.social_sentiment_service = None

    pipeline.fetcher_manager = MagicMock()
    pipeline.fetcher_manager.get_stock_name.return_value = "贵州茅台"
    pipeline.fetcher_manager.get_realtime_quote.return_value = None
    pipeline.fetcher_manager.get_chip_distribution.return_value = None
    pipeline.fetcher_manager.get_fundamental_context.return_value = {
        "market": "cn",
        "coverage": {"boards": "not_supported"},
        "source_chain": [],
    }
    pipeline.fetcher_manager.build_failed_fundamental_context.return_value = {
        "market": "cn",
        "coverage": {"boards": "not_supported"},
        "source_chain": [],
    }

    pipeline.db = MagicMock()
    pipeline.db.get_data_range.return_value = []
    pipeline.db.get_analysis_context.return_value = {
        "code": "600519",
        "stock_name": "贵州茅台",
        "date": "2026-03-26",
        "today": {},
        "yesterday": {},
    }

    pipeline.trend_analyzer = MagicMock()
    pipeline.analyzer = MagicMock()
    pipeline.analyzer.analyze.return_value = _analysis_result()
    pipeline.search_service = MagicMock()
    pipeline.search_service.is_available = False
    pipeline.search_service.news_window_days = 3
    pipeline._emit_progress = MagicMock()
    return pipeline


class PipelineMarketPhaseContextTestCase(unittest.TestCase):
    def test_process_single_stock_propagates_current_time_to_analyze_stock(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.query_id = None
        pipeline._emit_progress = MagicMock()
        pipeline._resolve_resume_target_date = MagicMock(return_value=date(2026, 3, 26))
        pipeline.fetch_and_save_stock_data = MagicMock(return_value=(True, None))
        pipeline.analyze_stock = MagicMock(
            return_value=SimpleNamespace(
                success=True,
                operation_advice="持有",
                sentiment_score=60,
            )
        )
        frozen_time = datetime(2026, 3, 27, 10, 0)

        pipeline.process_single_stock(
            "600519",
            report_type=ReportType.SIMPLE,
            analysis_query_id="q-frozen",
            current_time=frozen_time,
        )

        pipeline.analyze_stock.assert_called_once_with(
            "600519",
            ReportType.SIMPLE,
            query_id="q-frozen",
            current_time=frozen_time,
        )

    def test_legacy_analysis_artifacts_helper_maps_full_pipeline_fields(self):
        pipeline = _make_pipeline(agent_mode=False, save_context_snapshot=True)
        pipeline.query_source = "api"
        phase = _phase_payload()
        context = {"code": "600519", "today": {"close": 1800.0}, "yesterday": {}}
        enhanced_context = {"realtime": {"price": 1888.0}, "stock_name": "贵州茅台"}
        realtime_quote = {"price": 1888.0, "source": "test"}
        trend_result = {"ma_trend": "up"}
        chip_data = {"concentration": "medium"}
        fundamental_context = {"market": "cn", "pe": 28}
        news_context = "news summary"

        artifacts = pipeline._build_legacy_analysis_artifacts(
            code="600519",
            stock_name="贵州茅台",
            market="cn",
            phase=phase,
            context=context,
            enhanced_context=enhanced_context,
            realtime_quote=realtime_quote,
            trend_result=trend_result,
            chip_data=chip_data,
            fundamental_context=fundamental_context,
            news_context=news_context,
            news_result_count=3,
            query_id="q-legacy",
        )

        self.assertEqual(artifacts.code, "600519")
        self.assertEqual(artifacts.stock_name, "贵州茅台")
        self.assertEqual(artifacts.market, "cn")
        self.assertIs(artifacts.phase, phase)
        self.assertIs(artifacts.base_context, context)
        self.assertIs(artifacts.enhanced_context, enhanced_context)
        self.assertIs(artifacts.realtime_quote, realtime_quote)
        self.assertIs(artifacts.trend_result, trend_result)
        self.assertIs(artifacts.chip_data, chip_data)
        self.assertIs(artifacts.fundamental_context, fundamental_context)
        self.assertEqual(artifacts.news_context, news_context)
        self.assertEqual(artifacts.news_result_count, 3)
        self.assertEqual(
            artifacts.metadata,
            {"query_id": "q-legacy", "trigger_source": "api"},
        )

    def test_context_snapshot_strips_runtime_portfolio_context(self):
        pipeline = _make_pipeline(agent_mode=False, save_context_snapshot=True)

        snapshot = pipeline._build_context_snapshot(
            enhanced_context={
                "code": "600519",
                "daily_market_context_summary": "仅供prompt注入，不应入库存档",
                "market_phase_context": _phase_payload(),
                "portfolio_context": {
                    "quantity": 100,
                    "avg_cost": 1800,
                    "unrealized_pnl_base": 5000,
                },
            },
            news_content=None,
            realtime_quote=None,
            chip_data=None,
        )

        self.assertNotIn("market_phase_context", snapshot["enhanced_context"])
        self.assertNotIn("portfolio_context", snapshot["enhanced_context"])
        self.assertNotIn("daily_market_context_summary", snapshot["enhanced_context"])
        self.assertNotIn("avg_cost", str(snapshot))

    def test_agent_analysis_artifacts_helper_maps_initial_context_zero_fetch(self):
        pipeline = _make_pipeline(agent_mode=True, save_context_snapshot=True)
        pipeline.query_source = "system"
        phase = _phase_payload()
        realtime_quote = {"price": 1888.0, "source": "test"}
        trend_result = {"ma_trend": "up"}
        chip_distribution = {"concentration": "medium"}
        fundamental_context = {"market": "cn", "pe": 28}
        initial_context = {
            "realtime_quote": realtime_quote,
            "trend_result": trend_result,
            "chip_distribution": chip_distribution,
            "news_context": "prefetched news",
        }

        artifacts = pipeline._build_agent_analysis_artifacts(
            code="600519",
            stock_name="贵州茅台",
            market="cn",
            phase=phase,
            initial_context=initial_context,
            fundamental_context=fundamental_context,
            query_id="q-agent",
        )

        self.assertEqual(artifacts.code, "600519")
        self.assertEqual(artifacts.stock_name, "贵州茅台")
        self.assertEqual(artifacts.market, "cn")
        self.assertIs(artifacts.phase, phase)
        self.assertEqual(
            artifacts.base_context,
            {
                "code": "600519",
                "stock_name": "贵州茅台",
                "data_missing": True,
                "today": {},
                "yesterday": {},
            },
        )
        self.assertNotIn("date", artifacts.base_context)
        self.assertEqual(artifacts.enhanced_context, {})
        self.assertIs(artifacts.realtime_quote, realtime_quote)
        self.assertIs(artifacts.trend_result, trend_result)
        self.assertIs(artifacts.chip_data, chip_distribution)
        self.assertIs(artifacts.fundamental_context, fundamental_context)
        self.assertEqual(artifacts.news_context, "prefetched news")
        self.assertIsNone(artifacts.news_result_count)
        self.assertEqual(
            artifacts.metadata,
            {"query_id": "q-agent", "trigger_source": "system"},
        )

        daily_context = {
            "code": "600519",
            "date": "2026-03-26",
            "today": {"date": "2026-03-26", "close": 1888.0},
            "yesterday": {"date": "2026-03-25", "close": 1860.0},
        }
        artifacts_with_daily = pipeline._build_agent_analysis_artifacts(
            code="600519",
            stock_name="贵州茅台",
            market="cn",
            phase=phase,
            initial_context=initial_context,
            fundamental_context=fundamental_context,
            query_id="q-agent",
            base_context=daily_context,
        )
        self.assertEqual(artifacts_with_daily.base_context["today"]["close"], 1888.0)
        self.assertEqual(artifacts_with_daily.base_context["yesterday"]["close"], 1860.0)
        self.assertNotIn("data_missing", artifacts_with_daily.base_context)

        artifacts_without_chip = pipeline._build_agent_analysis_artifacts(
            code="600519",
            stock_name="贵州茅台",
            market="cn",
            phase=phase,
            initial_context={},
            fundamental_context=fundamental_context,
            query_id="q-agent-no-chip",
        )
        self.assertIsNone(artifacts_without_chip.chip_data)

    def test_legacy_pipeline_passes_market_phase_context_to_analyzer_only(self):
        pipeline = _make_pipeline(agent_mode=False, save_context_snapshot=True)
        phase_payload = _phase_payload()
        phase_context = SimpleNamespace(to_dict=MagicMock(return_value=phase_payload))

        with patch("src.core.pipeline.build_market_phase_context", return_value=phase_context) as mock_build:
            result = pipeline.analyze_stock(
                "600519",
                ReportType.SIMPLE,
                "q-runtime",
                current_time=datetime(2026, 3, 27, 10, 0),
            )

        self.assertIsNotNone(result)
        mock_build.assert_called_once()
        enhanced_context = pipeline.analyzer.analyze.call_args.args[0]
        self.assertEqual(enhanced_context["market_phase_context"], phase_payload)
        analyze_kwargs = pipeline.analyzer.analyze.call_args.kwargs
        self.assertIn("分析上下文包摘要", analyze_kwargs["analysis_context_pack_summary"])
        self.assertIn("日线: missing", analyze_kwargs["analysis_context_pack_summary"])
        self.assertIn("盘中判断受", analyze_kwargs["analysis_context_pack_summary"])
        self.assertIn("数据质量限制", analyze_kwargs["analysis_context_pack_summary"])

        save_kwargs = pipeline.db.save_analysis_history.call_args.kwargs
        self.assertTrue(save_kwargs["save_snapshot"])
        snapshot = save_kwargs["context_snapshot"]
        self.assertNotIn("market_phase_context", snapshot["enhanced_context"])
        self.assertNotIn("analysis_context_pack_summary", snapshot["enhanced_context"])
        self.assertEqual(snapshot["market_phase_summary"]["phase"], "intraday")
        self.assertEqual(snapshot["market_phase_summary"]["market"], "cn")
        self.assertIn("analysis_context_pack_overview", snapshot)
        self.assertEqual(snapshot["analysis_context_pack_overview"]["subject"]["code"], "600519")
        self.assertTrue(snapshot["analysis_context_pack_overview"]["blocks"])
        self.assertNotIn("items", str(snapshot["analysis_context_pack_overview"]))
        self.assertNotIn("分析上下文包摘要", str(snapshot))
        self.assertEqual(result.dashboard["phase_decision"]["phase_context"]["phase"], "intraday")
        self.assertIsInstance(result.dashboard["phase_decision"]["watch_conditions"], list)
        self.assertIn("daily_bars: missing", result.dashboard["phase_decision"]["data_limitations"])

    def test_pipeline_passes_configured_analysis_phase_to_market_context(self):
        pipeline = _make_pipeline(agent_mode=False, save_context_snapshot=True)
        pipeline.analysis_phase = "postmarket"
        phase_payload = {
            **_phase_payload(),
            "phase": "postmarket",
            "analysis_intent": "postmarket",
            "is_market_open_now": False,
            "is_partial_bar": False,
            "minutes_to_close": None,
        }
        phase_context = SimpleNamespace(to_dict=MagicMock(return_value=phase_payload))

        with patch("src.core.pipeline.build_market_phase_context", return_value=phase_context) as mock_build:
            result = pipeline.analyze_stock(
                "600519",
                ReportType.SIMPLE,
                "q-runtime-phase",
                current_time=datetime(2026, 3, 27, 16, 0),
            )

        self.assertIsNotNone(result)
        self.assertEqual(mock_build.call_args.kwargs["analysis_phase"], "postmarket")

    def test_legacy_pipeline_fail_open_when_pack_summary_generation_fails(self):
        pipeline = _make_pipeline(agent_mode=False, save_context_snapshot=True)
        phase_payload = _phase_payload()
        phase_context = SimpleNamespace(to_dict=MagicMock(return_value=phase_payload))

        with (
            patch("src.core.pipeline.build_market_phase_context", return_value=phase_context),
            patch(
                "src.core.pipeline.AnalysisContextBuilder.build",
                side_effect=RuntimeError("pack builder unavailable"),
            ),
            self.assertLogs("src.core.pipeline", level="WARNING") as logs,
        ):
            result = pipeline.analyze_stock(
                "600519",
                ReportType.SIMPLE,
                "q-runtime",
                current_time=datetime(2026, 3, 27, 10, 0),
            )

        self.assertIsNotNone(result)
        analyze_kwargs = pipeline.analyzer.analyze.call_args.kwargs
        self.assertEqual(analyze_kwargs["analysis_context_pack_summary"], "")
        self.assertIn(
            "AnalysisContextPack output generation failed for 600519 query_id=q-runtime",
            "\n".join(logs.output),
        )
        save_kwargs = pipeline.db.save_analysis_history.call_args.kwargs
        self.assertEqual(save_kwargs["context_snapshot"]["market_phase_summary"]["phase"], "intraday")
        self.assertNotIn("analysis_context_pack_overview", save_kwargs["context_snapshot"])

    def test_agent_legacy_context_gets_runtime_key_but_history_snapshot_strips_it(self):
        pipeline = _make_pipeline(agent_mode=True, save_context_snapshot=True)
        pipeline._ensure_agent_history = MagicMock()
        phase_payload = _phase_payload()

        from src.agent.executor import AgentResult

        agent_result = AgentResult(
            success=True,
            content="{}",
            dashboard={
                "stock_name": "贵州茅台",
                "sentiment_score": 66,
                "trend_prediction": "震荡",
                "operation_advice": "持有",
                "decision_type": "hold",
            },
            provider="test",
        )
        executor = MagicMock()
        executor.run.return_value = agent_result

        with patch("src.agent.factory.build_agent_executor", return_value=executor):
            result = pipeline._analyze_with_agent(
                code="600519",
                report_type=ReportType.SIMPLE,
                query_id="q-agent",
                stock_name="贵州茅台",
                realtime_quote=None,
                chip_data=None,
                fundamental_context={"market": "cn"},
                trend_result=None,
                market_phase_context=phase_payload,
                market_phase_summary=phase_payload,
            )

        self.assertIsNotNone(result)
        run_context = executor.run.call_args.kwargs["context"]
        self.assertEqual(run_context["market_phase_context"], phase_payload)
        self.assertIn("analysis_context_pack_summary", run_context)
        self.assertIn("分析上下文包摘要", run_context["analysis_context_pack_summary"])
        self.assertIn("新闻: missing", run_context["analysis_context_pack_summary"])
        self.assertIn("盘中判断受", run_context["analysis_context_pack_summary"])
        self.assertIn("数据质量限制", run_context["analysis_context_pack_summary"])

        save_kwargs = pipeline.db.save_analysis_history.call_args.kwargs
        self.assertTrue(save_kwargs["save_snapshot"])
        self.assertNotIn("market_phase_context", save_kwargs["context_snapshot"])
        self.assertNotIn("analysis_context_pack_summary", save_kwargs["context_snapshot"])
        self.assertEqual(save_kwargs["context_snapshot"]["market_phase_summary"]["phase"], "intraday")
        self.assertIn("analysis_context_pack_overview", save_kwargs["context_snapshot"])
        self.assertEqual(
            save_kwargs["context_snapshot"]["analysis_context_pack_overview"]["subject"]["code"],
            "600519",
        )
        self.assertTrue(save_kwargs["context_snapshot"]["analysis_context_pack_overview"]["blocks"])
        self.assertNotIn(
            "items",
            str(save_kwargs["context_snapshot"]["analysis_context_pack_overview"]),
        )
        self.assertNotIn("分析上下文包摘要", str(save_kwargs["context_snapshot"]))
        enhanced_context = save_kwargs["context_snapshot"]["enhanced_context"]
        self.assertEqual(enhanced_context["stock_name"], "贵州茅台")
        self.assertEqual(result.dashboard["phase_decision"]["phase_context"]["phase"], "intraday")
        self.assertIsInstance(result.dashboard["phase_decision"]["watch_conditions"], list)

    def test_agent_pack_summary_uses_prefetched_news_context_when_present(self):
        pipeline = _make_pipeline(agent_mode=True, save_context_snapshot=True)
        pipeline._ensure_agent_history = MagicMock()
        pipeline.social_sentiment_service = MagicMock()
        pipeline.social_sentiment_service.is_available = True
        pipeline.social_sentiment_service.get_social_context.return_value = (
            "Social sentiment raw payload should stay in legacy news_context only."
        )

        from src.agent.executor import AgentResult

        executor = MagicMock()
        executor.run.return_value = AgentResult(
            success=True,
            content="{}",
            dashboard={
                "stock_name": "Apple",
                "sentiment_score": 66,
                "trend_prediction": "震荡",
                "operation_advice": "持有",
                "decision_type": "hold",
            },
            provider="test",
        )

        with patch("src.agent.factory.build_agent_executor", return_value=executor):
            result = pipeline._analyze_with_agent(
                code="AAPL",
                report_type=ReportType.SIMPLE,
                query_id="q-agent-news",
                stock_name="Apple",
                realtime_quote=None,
                chip_data=None,
                fundamental_context={"market": "us"},
                trend_result=None,
                market_phase_context=_phase_payload(),
            )

        self.assertIsNotNone(result)
        run_context = executor.run.call_args.kwargs["context"]
        self.assertIn("Social sentiment raw payload", run_context["news_context"])
        summary = run_context["analysis_context_pack_summary"]
        self.assertIn("新闻: available", summary)
        self.assertNotIn("新闻: missing", summary)
        self.assertNotIn("Social sentiment raw payload", summary)

        save_kwargs = pipeline.db.save_analysis_history.call_args.kwargs
        self.assertNotIn("analysis_context_pack_summary", save_kwargs["context_snapshot"])
        self.assertIn("analysis_context_pack_overview", save_kwargs["context_snapshot"])
        self.assertNotIn(
            "items",
            str(save_kwargs["context_snapshot"]["analysis_context_pack_overview"]),
        )

    def test_agent_pack_summary_uses_db_daily_context_after_history_prefetch(self):
        pipeline = _make_pipeline(agent_mode=True, save_context_snapshot=True)
        pipeline._ensure_agent_history = MagicMock()
        pipeline.db.get_analysis_context.return_value = {
            "code": "600519",
            "stock_name": "贵州茅台",
            "date": "2026-06-02",
            "today": {"date": "2026-06-02", "close": 6.67, "volume": 1000.0},
            "yesterday": {"date": "2026-06-01", "close": 6.78, "volume": 900.0},
        }

        from src.agent.executor import AgentResult

        executor = MagicMock()
        executor.run.return_value = AgentResult(
            success=True,
            content="{}",
            dashboard={
                "stock_name": "贵州茅台",
                "sentiment_score": 66,
                "trend_prediction": "震荡",
                "operation_advice": "持有",
                "decision_type": "hold",
            },
            provider="test",
        )

        with patch("src.agent.factory.build_agent_executor", return_value=executor):
            result = pipeline._analyze_with_agent(
                code="600519",
                report_type=ReportType.SIMPLE,
                query_id="q-agent-daily",
                stock_name="贵州茅台",
                realtime_quote=None,
                chip_data=None,
                fundamental_context={"market": "cn"},
                trend_result=None,
                market_phase_context=_phase_payload(),
                market_phase_summary=_phase_payload(),
            )

        self.assertIsNotNone(result)
        pipeline._ensure_agent_history.assert_called_once_with("600519")
        pipeline.db.get_analysis_context.assert_called_with("600519")

        run_context = executor.run.call_args.kwargs["context"]
        self.assertIn("日线: available", run_context["analysis_context_pack_summary"])
        self.assertNotIn("daily_bars_missing", run_context["analysis_context_pack_summary"])

        save_kwargs = pipeline.db.save_analysis_history.call_args.kwargs
        overview = save_kwargs["context_snapshot"]["analysis_context_pack_overview"]
        daily_block = next(
            block for block in overview["blocks"] if block["key"] == "daily_bars"
        )
        self.assertEqual(daily_block["status"], "available")
        self.assertEqual(daily_block["source"], "storage.get_analysis_context")
        self.assertEqual(daily_block["missing_reasons"], [])
        self.assertEqual(save_kwargs["context_snapshot"]["market_phase_summary"]["phase"], "intraday")

    def test_agent_pipeline_fail_open_when_pack_summary_generation_fails(self):
        pipeline = _make_pipeline(agent_mode=True, save_context_snapshot=True)
        pipeline._ensure_agent_history = MagicMock()
        phase_payload = _phase_payload()

        from src.agent.executor import AgentResult

        executor = MagicMock()
        executor.run.return_value = AgentResult(
            success=True,
            content="{}",
            dashboard={
                "stock_name": "贵州茅台",
                "sentiment_score": 66,
                "trend_prediction": "震荡",
                "operation_advice": "持有",
                "decision_type": "hold",
            },
            provider="test",
        )

        with (
            patch("src.agent.factory.build_agent_executor", return_value=executor),
            patch(
                "src.core.pipeline.AnalysisContextBuilder.build",
                side_effect=RuntimeError("pack builder unavailable"),
            ),
            self.assertLogs("src.core.pipeline", level="WARNING") as logs,
        ):
            result = pipeline._analyze_with_agent(
                code="600519",
                report_type=ReportType.SIMPLE,
                query_id="q-agent",
                stock_name="贵州茅台",
                realtime_quote=None,
                chip_data=None,
                fundamental_context={"market": "cn"},
                trend_result=None,
                market_phase_context=phase_payload,
                market_phase_summary=phase_payload,
            )

        self.assertIsNotNone(result)
        run_context = executor.run.call_args.kwargs["context"]
        self.assertNotIn("analysis_context_pack_summary", run_context)
        self.assertIn(
            "AnalysisContextPack output generation failed for 600519 query_id=q-agent",
            "\n".join(logs.output),
        )
        save_kwargs = pipeline.db.save_analysis_history.call_args.kwargs
        self.assertEqual(save_kwargs["context_snapshot"]["market_phase_summary"]["phase"], "intraday")
        self.assertNotIn("analysis_context_pack_overview", save_kwargs["context_snapshot"])

    def test_agent_history_snapshot_contains_diagnostics_context_when_active(self):
        pipeline = _make_pipeline(agent_mode=True, save_context_snapshot=True)
        pipeline._ensure_agent_history = MagicMock()
        phase_payload = _phase_payload()
        token = activate_run_diagnostic_context(
            trace_id="trace-agent",
            query_id="q-agent",
            stock_code="600519",
            trigger_source="api",
        )
        try:
            from src.agent.executor import AgentResult

            agent_result = AgentResult(
                success=True,
                content="{}",
                dashboard={
                    "stock_name": "贵州茅台",
                    "sentiment_score": 70,
                    "trend_prediction": "震荡",
                    "operation_advice": "持有",
                    "decision_type": "hold",
                },
                provider="test",
            )
            executor = MagicMock()
            executor.run.return_value = agent_result

            with patch("src.agent.factory.build_agent_executor", return_value=executor):
                result = pipeline._analyze_with_agent(
                    code="600519",
                    report_type=ReportType.SIMPLE,
                    query_id="q-agent",
                    stock_name="贵州茅台",
                    realtime_quote=None,
                    chip_data=None,
                    fundamental_context={"market": "cn"},
                    trend_result=None,
                    market_phase_context=phase_payload,
                )

            self.assertIsNotNone(result)
            save_kwargs = pipeline.db.save_analysis_history.call_args.kwargs
            self.assertTrue(save_kwargs["save_snapshot"])
            snapshot = save_kwargs["context_snapshot"]
            self.assertIn("diagnostics", snapshot)
            self.assertNotIn("analysis_context_pack_summary", snapshot)
            self.assertIn("analysis_context_pack_overview", snapshot)
            diagnostics = snapshot["diagnostics"]
            self.assertIsNotNone(diagnostics)
            self.assertEqual(diagnostics["trace_id"], "trace-agent")
            self.assertEqual(diagnostics["query_id"], "q-agent")
            self.assertEqual(diagnostics["provider_runs"], [])
            # history_runs will be populated after save_analysis_history callback, so compare core fields only
            current_snapshot = current_diagnostic_snapshot()
            self.assertEqual(current_snapshot["trace_id"], diagnostics["trace_id"])
            self.assertEqual(current_snapshot["query_id"], diagnostics["query_id"])
            self.assertEqual(current_snapshot["provider_runs"], diagnostics["provider_runs"])
        finally:
            reset_run_diagnostic_context(token)

    def test_agent_history_snapshot_includes_diagnostic_summary(self):
        pipeline = _make_pipeline(agent_mode=True, save_context_snapshot=True)
        pipeline._ensure_agent_history = MagicMock()

        from src.agent.executor import AgentResult
        executor = MagicMock()
        executor.run.return_value = AgentResult(
            success=True,
            content="{}",
            dashboard={
                "stock_name": "贵州茅台",
                "sentiment_score": 66,
                "trend_prediction": "震荡",
                "operation_advice": "持有",
                "decision_type": "hold",
            },
            provider="test",
        )

        token = activate_run_diagnostic_context(
            trace_id="trace-agent",
            query_id="q-agent",
            stock_code="600519",
            trigger_source="system",
        )
        try:
            with patch("src.agent.factory.build_agent_executor", return_value=executor):
                result = pipeline._analyze_with_agent(
                    code="600519",
                    report_type=ReportType.SIMPLE,
                    query_id="q-agent",
                    stock_name="贵州茅台",
                    realtime_quote=None,
                    chip_data=None,
                )

            self.assertIsNotNone(result)
            save_kwargs = pipeline.db.save_analysis_history.call_args.kwargs
            context_snapshot = save_kwargs["context_snapshot"]
            diagnostics = context_snapshot.get("diagnostics")
            self.assertIsNotNone(diagnostics)
            self.assertEqual(diagnostics["trace_id"], "trace-agent")
            self.assertTrue(any(run.get("call_type") == "agent_analysis" for run in diagnostics["llm_runs"]))
        finally:
            reset_run_diagnostic_context(token)


if __name__ == "__main__":
    unittest.main()
