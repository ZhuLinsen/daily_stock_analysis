# -*- coding: utf-8 -*-
"""Story 1.5 — focused Pipeline/CLI index integration tests.

Covers the deterministic acceptance matrix from
``_bmad-output/specs/spec-pipeline-cli-integration/verification.md``:
- V1  CLI target construction
- V2  Unsupported boundary (reject before provider calls, batch continues)
- V3  Canonical batch identity (alias dedupe, stock/index isolation)
- V4  Market/date propagation (SH/SZ/CSI -> cn)
- V5  Traditional capability matrix (skip modules zero bottom-layer calls)
- V6  Agent capability matrix (same negative/positive assertions)
- V7  Search semantics (name-only query subject for indices)
- V10 Daily data-source attribution (report/history wiring and fail-open cases)
- V11 Dry-run target/date propagation

Cross-layer V8-V9/V11-V12 compatibility remains covered by the existing history,
data-routing, task-service, schedule, and stock-regression suites.
"""

from __future__ import annotations

import re
import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from src.analyzer import AnalysisResult
from src.config import Config
from src.core.pipeline import StockAnalysisPipeline, INDEX_SKIP_MODULES
from src.enums import ReportType
from src.notification import NotificationService
from src.search_service import SearchResponse, SearchService
from src.services.stock_list_parser import (
    AnalysisTarget,
    ParseStatus,
    parse_analysis_target,
)


def _index_target(raw: str) -> AnalysisTarget:
    target = parse_analysis_target(raw)
    assert target.asset_type == ParseStatus.INDEX, f"{raw} should be index"
    return target


def _stock_target(raw: str) -> AnalysisTarget:
    target = parse_analysis_target(raw)
    assert target.asset_type == ParseStatus.STOCK, f"{raw} should be stock"
    return target


def _analysis_result(
    code: str, name: str, data_sources: str | None
) -> AnalysisResult:
    result = AnalysisResult(
        code=code,
        name=name,
        sentiment_score=60,
        trend_prediction="震荡",
        operation_advice="观望",
        data_sources=data_sources or "",
    )
    if data_sources is None:
        setattr(result, "data_sources", None)
    return result


def _render_aggregate_report(
    result: AnalysisResult,
    report_type: ReportType = ReportType.SIMPLE,
) -> str:
    with patch(
        "src.notification.get_config",
        return_value=Config(stock_list=[], report_renderer_enabled=False),
    ):
        service = NotificationService()
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = service
        return pipeline._generate_aggregate_report([result], report_type)


def _analysis_pipeline(
    code: str,
    name: str,
    *,
    enable_search: bool = False,
    realtime_name: str | None = None,
) -> StockAnalysisPipeline:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.fetcher_manager = MagicMock()
    pipeline.fetcher_manager.build_not_supported_fundamental_context.return_value = {
        "status": "not_supported",
        "coverage": {},
        "source_chain": [],
        "belong_boards": [],
    }
    pipeline.db = MagicMock()
    pipeline.config = MagicMock()
    pipeline.config.enable_realtime_quote = realtime_name is not None
    pipeline.config.agent_mode = False
    pipeline.config.agent_skills = []
    pipeline.config.report_language = "zh"
    pipeline.config.fundamental_stage_timeout_seconds = 5.0
    pipeline.config.market_review_enabled = False
    pipeline.config.daily_market_context_enabled = False
    pipeline.config.report_type = "simple"
    pipeline.search_service = MagicMock() if enable_search else None
    if pipeline.search_service is not None:
        pipeline.search_service.is_available = True
        pipeline.search_service.search_comprehensive_intel.return_value = {}
    pipeline.social_sentiment_service = None
    pipeline.trend_analyzer = MagicMock()
    pipeline.analyzer = MagicMock()
    pipeline.analysis_skills = None
    pipeline.query_source = "cli"
    pipeline.save_context_snapshot = False
    pipeline.progress_callback = None
    pipeline.portfolio_context = None
    pipeline.analysis_phase = "auto"
    pipeline._emit_progress = MagicMock()
    pipeline._load_daily_market_context = MagicMock(return_value=None)
    pipeline._build_market_structure_context = MagicMock(return_value=None)
    pipeline._load_persisted_intelligence_context = MagicMock(return_value=None)
    pipeline._get_analysis_context_with_market_fallback = MagicMock(
        return_value={"code": code, "stock_name": name}
    )
    pipeline._enhance_context = MagicMock(
        return_value={"code": code, "stock_name": name}
    )
    pipeline._build_analysis_context_pack_outputs = MagicMock(
        return_value=("", None)
    )
    pipeline._build_legacy_analysis_artifacts = MagicMock()
    pipeline._refresh_decision_action_for_final_result = MagicMock()
    pipeline._build_query_context = MagicMock(return_value={})
    pipeline._build_context_snapshot = MagicMock(return_value={})
    pipeline._extract_decision_signal_after_history_save = MagicMock()
    pipeline.db.save_analysis_history.return_value = 1
    pipeline.db.save_fundamental_snapshot = MagicMock()
    pipeline.db.get_data_range.return_value = []
    pipeline.db.get_analysis_context.return_value = None
    pipeline.analyzer.analyze.return_value = MagicMock(
        success=True,
        code=code,
        name=name,
        sentiment_score=60,
        operation_advice="观望",
        decision_type="hold",
        confidence_level="中",
        report_language="zh",
        dashboard={},
    )
    if realtime_name is not None:
        realtime_quote = MagicMock()
        realtime_quote.name = realtime_name
        realtime_quote.price = 3000.0
        realtime_quote.volume_ratio = 1.0
        realtime_quote.turnover_rate = 0.0
        realtime_quote.pe_ratio = None
        realtime_quote.pb_ratio = None
        realtime_quote.total_mv = None
        realtime_quote.circ_mv = None
        pipeline.fetcher_manager.get_realtime_quote.return_value = realtime_quote
    return pipeline


class PipelineIndexTargetsTestCase(unittest.TestCase):
    """V1 — CLI target construction produces expected type + canonical identity."""

    def test_v1_sh_sz_csi_and_bare_stock_construct(self) -> None:
        cases = [
            ("sh000016", ParseStatus.INDEX, "sh000016"),
            ("000300.CSI", ParseStatus.INDEX, "sh000300"),
            ("930955.CSI", ParseStatus.INDEX, "csi930955"),
            ("000016", ParseStatus.STOCK, "sz000016"),
            ("600519", ParseStatus.STOCK, "sh600519"),
        ]
        for raw, expected_type, expected_canonical in cases:
            target = parse_analysis_target(raw)
            self.assertEqual(target.asset_type, expected_type, raw)
            self.assertEqual(target.canonical_id, expected_canonical, raw)

    def test_v1_index_display_name_is_chinese(self) -> None:
        target = _index_target("sh000016")
        self.assertEqual(target.display_code, "上证50")
        self.assertIsNotNone(target.matched_index)
        self.assertEqual(target.matched_index.display_name, "上证50")

    def test_v2_unregistered_csi_is_unsupported(self) -> None:
        target = parse_analysis_target("930956.CSI")
        self.assertEqual(target.asset_type, ParseStatus.UNSUPPORTED)
        self.assertIsNotNone(target.unsupported_reason)

    def test_v3_alias_dedupe_by_canonical_id(self) -> None:
        # Equivalent explicit aliases share one canonical scheduling key.
        a = _index_target("sh000300")
        b = _index_target("000300.CSI")
        self.assertEqual(a.canonical_id, b.canonical_id)
        self.assertEqual(a.canonical_id, "sh000300")

        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = MagicMock()
        pipeline.config.single_stock_notify = False
        pipeline.config.report_type = "simple"
        pipeline.config.analysis_delay = 0
        pipeline.max_workers = 1
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        pipeline.db.has_today_data.return_value = True
        pipeline._save_local_report = MagicMock()
        pipeline._send_notifications = MagicMock()
        pipeline.process_single_stock = MagicMock(return_value=None)

        pipeline.run(
            stock_codes=[a.canonical_id, b.canonical_id],
            analysis_targets=[a, b],
            dry_run=True,
            send_notification=False,
        )

        self.assertEqual(pipeline.process_single_stock.call_count, 1)
        submitted = pipeline.process_single_stock.call_args
        self.assertEqual(submitted.args[0], "sh000300")
        self.assertIs(submitted.kwargs["analysis_target"], a)

    def test_v3_stock_and_index_do_not_collapse(self) -> None:
        # sh000016 (index) and bare 000016 (stock) are distinct identities.
        index = _index_target("sh000016")
        stock = _stock_target("000016")
        self.assertEqual(index.canonical_id, "sh000016")
        self.assertEqual(stock.canonical_id, "sz000016")
        self.assertNotEqual(index.canonical_id, stock.canonical_id)


class PipelineMarketDatePropagationTestCase(unittest.TestCase):
    """V4 — SH/SZ/CSI indices all use cn for market/date semantics."""

    def _pipeline(self) -> StockAnalysisPipeline:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        return pipeline

    def test_v4_resume_target_date_uses_cn_for_csi_index(self) -> None:
        target = _index_target("930955.CSI")
        with patch(
            "src.core.pipeline.get_effective_trading_date",
            return_value=date(2026, 8, 26),
        ) as mock_target, patch(
            "src.core.pipeline.get_market_for_stock", return_value=None
        ) as mock_market:
            result = StockAnalysisPipeline._resolve_resume_target_date(
                "csi930955", analysis_target=target
            )
        self.assertEqual(result, date(2026, 8, 26))
        # market=cn must be passed to get_effective_trading_date, not None.
        self.assertEqual(mock_target.call_args.args[0], "cn")
        # get_market_for_stock must NOT be consulted for index targets.
        mock_market.assert_not_called()

    def test_v4_resume_target_date_uses_cn_for_sh_index(self) -> None:
        target = _index_target("sh000016")
        with patch(
            "src.core.pipeline.get_effective_trading_date",
            return_value=date(2026, 8, 26),
        ) as mock_target, patch(
            "src.core.pipeline.get_market_for_stock", return_value=None
        ) as mock_market:
            StockAnalysisPipeline._resolve_resume_target_date(
                "sh000016", analysis_target=target
            )
        self.assertEqual(mock_target.call_args.args[0], "cn")
        mock_market.assert_not_called()

    def test_v4_stock_still_uses_market_for_stock(self) -> None:
        with patch(
            "src.core.pipeline.get_effective_trading_date",
            return_value=date(2026, 8, 26),
        ), patch(
            "src.core.pipeline.get_market_for_stock", return_value="cn"
        ) as mock_market:
            StockAnalysisPipeline._resolve_resume_target_date("600519")
        mock_market.assert_called_once_with("600519")

    def test_v4_analysis_context_fallback_uses_cn_for_index(self) -> None:
        pipeline = self._pipeline()
        pipeline.db.get_analysis_context.return_value = None
        target = _index_target("930955.CSI")
        with patch(
            "src.core.pipeline.get_market_for_stock", return_value=None
        ) as mock_market:
            result = pipeline._get_analysis_context_with_market_fallback(
                "csi930955", analysis_target=target
            )
        self.assertIsNone(result)
        # For index targets the market is derived as cn, so the JP/KR/TW
        # fallback branch is not entered and get_market_for_stock is not called.
        mock_market.assert_not_called()


class PipelineCapabilityMatrixTestCase(unittest.TestCase):
    """V5/V6 — INDEX_SKIP_MODULES zero bottom-layer calls for index targets."""

    def test_index_skip_modules_contains_all_six(self) -> None:
        self.assertEqual(
            INDEX_SKIP_MODULES,
            frozenset({
                "chip_distribution",
                "fundamental",
                "belong_boards",
                "capital_flow",
                "lhb",
                "corporate_events",
            }),
        )

    def test_v5_traditional_branch_skips_chip_and_fundamental(self) -> None:
        pipeline = _analysis_pipeline("sh000016", "上证50")

        target = _index_target("sh000016")
        result = pipeline.analyze_stock(
            "sh000016", MagicMock(), "q1", analysis_target=target
        )

        # Bottom-layer provider calls for skipped modules must be zero.
        pipeline.fetcher_manager.get_chip_distribution.assert_not_called()
        pipeline.fetcher_manager.get_fundamental_context.assert_not_called()
        pipeline.fetcher_manager.build_not_supported_fundamental_context.assert_called_once_with(
            "sh000016", "index target: fundamental modules skipped"
        )
        pipeline.fetcher_manager.build_failed_fundamental_context.assert_not_called()
        pipeline.fetcher_manager.get_belong_boards.assert_not_called()
        pipeline.db.save_fundamental_snapshot.assert_not_called()
        # Supported modules still execute.
        pipeline.analyzer.analyze.assert_called_once()

    def test_v6_agent_tool_filter_removes_index_incompatible_tools(self) -> None:
        from src.agent.tools.registry import ToolRegistry, ToolDefinition, ToolParameter

        registry = ToolRegistry()
        for name in (
            "get_realtime_quote",
            "get_daily_history",
            "get_chip_distribution",
            "get_stock_info",
            "get_capital_flow",
            "get_analysis_context",
        ):
            registry.register(
                ToolDefinition(
                    name=name,
                    description=name,
                    parameters=[
                        ToolParameter(
                            name="stock_code",
                            type="string",
                            description="stock code",
                        )
                    ],
                    handler=lambda **kw: {},
                )
            )

        executor = MagicMock()
        executor.tool_registry = registry
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        filtered = pipeline._filter_agent_tools_for_index(executor)

        names = set(filtered.tool_registry.list_names())
        self.assertIn("get_realtime_quote", names)
        self.assertIn("get_daily_history", names)
        self.assertIn("get_analysis_context", names)
        self.assertNotIn("get_chip_distribution", names)
        self.assertNotIn("get_stock_info", names)
        self.assertNotIn("get_capital_flow", names)

    @patch("src.agent.factory.build_agent_executor")
    def test_v6_agent_branch_applies_filter_and_target_aware_history(
        self, mock_build_executor: MagicMock
    ) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = MagicMock()
        pipeline.config.report_language = "zh"
        pipeline.config.agent_skills = []
        pipeline.config.agent_litellm_model = "test-model"
        pipeline.config.report_integrity_enabled = False
        pipeline.analysis_skills = None
        pipeline.social_sentiment_service = None
        pipeline.search_service = None
        pipeline._load_persisted_intelligence_context = MagicMock(return_value=None)
        pipeline._ensure_agent_history = MagicMock()
        pipeline._load_agent_analysis_context = MagicMock(return_value={})
        pipeline._build_agent_analysis_artifacts = MagicMock(return_value={})
        pipeline._build_analysis_context_pack_outputs = MagicMock(
            return_value=("", None)
        )
        pipeline._agent_result_to_analysis_result = MagicMock(return_value=None)

        executor = MagicMock()
        executor.run.return_value = MagicMock(model="test-model", runtime_facts=None)
        mock_build_executor.return_value = executor
        pipeline._filter_agent_tools_for_index = MagicMock(return_value=executor)
        target = _index_target("930955.CSI")

        result = pipeline._analyze_with_agent(
            code="csi930955",
            report_type=MagicMock(value="simple"),
            query_id="q-agent-index",
            stock_name="红利低波100",
            realtime_quote=None,
            chip_data=None,
            analysis_target=target,
        )

        self.assertIsNone(result)
        pipeline._filter_agent_tools_for_index.assert_called_once_with(executor)
        pipeline._ensure_agent_history.assert_called_once_with(
            "csi930955", analysis_target=target
        )


class PipelineDailySourceAttributionTestCase(unittest.TestCase):
    """V10 — persisted daily providers reach history and existing reports."""

    def test_v10_traditional_branch_persists_and_renders_daily_source(self) -> None:
        pipeline = _analysis_pipeline("sh000016", "上证50")
        pipeline._get_analysis_context_with_market_fallback.return_value = {
            "today": {"data_source": "TencentFetcher"}
        }
        pipeline.analyzer.analyze.return_value = _analysis_result(
            "sh000016", "上证50", "analysis:litellm"
        )

        result = pipeline.analyze_stock(
            "sh000016",
            ReportType.SIMPLE,
            "q-daily-traditional",
            analysis_target=_index_target("sh000016"),
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result.data_sources,
            "analysis:litellm,daily:TencentFetcher",
        )
        history_result = pipeline.db.save_analysis_history.call_args.kwargs["result"]
        self.assertIs(history_result, result)
        self.assertEqual(history_result.data_sources, result.data_sources)
        # V8 — persisted history uses canonical code plus registry Chinese name.
        self.assertEqual(history_result.code, "sh000016")
        self.assertEqual(history_result.name, "上证50")
        self.assertIn(
            "*📋 数据来源：analysis:litellm,daily:TencentFetcher*",
            _render_aggregate_report(result),
        )

    @patch("src.agent.factory.build_agent_executor")
    def test_v10_agent_branch_persists_and_renders_daily_source(
        self, mock_build_executor: MagicMock
    ) -> None:
        pipeline = _analysis_pipeline("csi930955", "红利低波100")
        pipeline.config.agent_litellm_model = "test-model"
        pipeline.config.report_integrity_enabled = False
        pipeline._ensure_agent_history = MagicMock()
        pipeline._load_agent_analysis_context = MagicMock(
            return_value={"today": {"data_source": "AkshareFetcher"}}
        )
        pipeline._build_agent_analysis_artifacts = MagicMock(return_value={})
        pipeline._agent_result_to_analysis_result = MagicMock(
            return_value=_analysis_result(
                "csi930955", "红利低波100", "agent:openai"
            )
        )
        pipeline._persist_skill_opinion_samples_after_history_save = MagicMock()

        agent_result = MagicMock()
        agent_result.model = "test-model"
        agent_result.runtime_facts = None
        executor = MagicMock()
        executor.run.return_value = agent_result
        mock_build_executor.return_value = executor
        pipeline._filter_agent_tools_for_index = MagicMock(return_value=executor)

        result = pipeline._analyze_with_agent(
            code="csi930955",
            report_type=ReportType.SIMPLE,
            query_id="q-daily-agent",
            stock_name="红利低波100",
            realtime_quote=None,
            chip_data=None,
            analysis_target=_index_target("930955.CSI"),
        )

        self.assertIsNotNone(result)
        self.assertEqual(
            result.data_sources,
            "agent:openai,daily:AkshareFetcher",
        )
        history_result = pipeline.db.save_analysis_history.call_args.kwargs["result"]
        self.assertIs(history_result, result)
        self.assertEqual(history_result.data_sources, result.data_sources)
        # V8 — persisted history uses canonical code plus registry Chinese name.
        self.assertEqual(history_result.code, "csi930955")
        self.assertEqual(history_result.name, "红利低波100")
        self.assertIn(
            "*📋 数据来源：agent:openai,daily:AkshareFetcher*",
            _render_aggregate_report(result, ReportType.BRIEF),
        )

    def test_v10_daily_source_deduplicates_complete_tokens_only(self) -> None:
        cases = (
            (
                None,
                "daily:AkshareFetcher",
            ),
            (
                "agent:openai,daily:AkshareFetcher",
                "agent:openai,daily:AkshareFetcher",
            ),
            (
                "agent:openai,daily:AkshareFetcherV2",
                "agent:openai,daily:AkshareFetcherV2,daily:AkshareFetcher",
            ),
        )

        for existing_sources, expected_sources in cases:
            with self.subTest(existing_sources=existing_sources):
                pipeline = _analysis_pipeline("sh000016", "上证50")
                pipeline._get_analysis_context_with_market_fallback.return_value = {
                    "today": {"data_source": "AkshareFetcher"}
                }
                pipeline.analyzer.analyze.return_value = _analysis_result(
                    "sh000016", "上证50", existing_sources
                )

                result = pipeline.analyze_stock(
                    "sh000016",
                    ReportType.SIMPLE,
                    "q-daily-dedupe",
                    analysis_target=_index_target("sh000016"),
                )

                self.assertIsNotNone(result)
                self.assertEqual(result.data_sources, expected_sources)

    def test_v10_invalid_daily_sources_fail_open(self) -> None:
        invalid_contexts = (
            {},
            {"today": {}},
            {"today": {"data_source": None}},
            {"today": {"data_source": 42}},
            {"today": {"data_source": "   "}},
            {"today": {"data_source": " Unknown "}},
            {"today": {"data_source": " realtime:TencentFetcher "}},
            {"today": {"data_source": "Realtime:TencentFetcher"}},
            {"today": {"data_source": "REALTIME:TencentFetcher"}},
        )

        for context in invalid_contexts:
            with self.subTest(context=context):
                pipeline = _analysis_pipeline("sh000016", "上证50")
                pipeline._get_analysis_context_with_market_fallback.return_value = context
                pipeline.analyzer.analyze.return_value = _analysis_result(
                    "sh000016", "上证50", "analysis:litellm"
                )

                result = pipeline.analyze_stock(
                    "sh000016",
                    ReportType.SIMPLE,
                    "q-daily-invalid",
                    analysis_target=_index_target("sh000016"),
                )

                self.assertIsNotNone(result)
                self.assertEqual(result.data_sources, "analysis:litellm")

    def test_v11_stock_result_does_not_gain_index_daily_attribution(self) -> None:
        pipeline = _analysis_pipeline("600519", "贵州茅台")
        pipeline._get_analysis_context_with_market_fallback.return_value = {
            "today": {"data_source": "AkshareFetcher"}
        }
        pipeline.analyzer.analyze.return_value = _analysis_result(
            "600519", "贵州茅台", "analysis:litellm"
        )

        result = pipeline.analyze_stock(
            "600519",
            ReportType.SIMPLE,
            "q-stock-daily-source",
            analysis_target=_stock_target("600519"),
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.data_sources, "analysis:litellm")


class PipelineSearchSemanticsTestCase(unittest.TestCase):
    """V7 — index search query subject is the Chinese name only."""

    def test_v7_traditional_search_uses_name_only_for_index(self) -> None:
        pipeline = _analysis_pipeline(
            "sh000016",
            "上证50",
            enable_search=True,
            realtime_name="provider alias",
        )

        target = _index_target("sh000016")
        pipeline.analyze_stock("sh000016", MagicMock(), "q1", analysis_target=target)

        # The search query subject must be the Chinese name only — no canonical
        # code / six-digit machine code in the provider query.
        call_kwargs = pipeline.search_service.search_comprehensive_intel.call_args.kwargs
        self.assertEqual(call_kwargs["stock_code"], "")
        self.assertEqual(call_kwargs["stock_name"], "上证50")

    def test_v7_stock_search_keeps_code(self) -> None:
        pipeline = _analysis_pipeline("600519", "贵州茅台", enable_search=True)

        pipeline.analyze_stock("600519", MagicMock(), "q1")

        call_kwargs = pipeline.search_service.search_comprehensive_intel.call_args.kwargs
        self.assertEqual(call_kwargs["stock_code"], "600519")

    def test_v7_provider_queries_contain_only_chinese_index_name(self) -> None:
        service = SearchService(
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        provider = MagicMock()
        provider.name = "DummyProvider"
        provider.is_available = True

        def search(query: str, **_kwargs) -> SearchResponse:
            return SearchResponse(
                query=query,
                results=[],
                provider="DummyProvider",
                success=True,
            )

        provider.search.side_effect = search
        service._providers = [provider]

        service.search_comprehensive_intel(
            stock_code="",
            stock_name="上证50",
            max_searches=5,
        )

        queries = [call.args[0] for call in provider.search.call_args_list]
        self.assertTrue(queries)
        for query in queries:
            self.assertIn("上证50", query)
            self.assertNotRegex(query, re.compile(r"\d{6}"))
            self.assertNotIn("sh000016", query.casefold())


class PipelineBatchFailureIsolationTestCase(unittest.TestCase):
    """V2/V10 — unsupported targets rejected before provider calls; batch continues."""

    def test_v2_run_filters_unsupported_before_prefetch(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = MagicMock()
        pipeline.config.refresh_stock_list = MagicMock()
        pipeline.config.stock_list = []
        pipeline.config.single_stock_notify = False
        pipeline.config.report_type = "simple"
        pipeline.config.analysis_delay = 0
        pipeline.max_workers = 2
        pipeline.fetcher_manager = MagicMock()
        pipeline.fetcher_manager.prefetch_daily_klines.return_value = 0
        pipeline.fetcher_manager.prefetch_realtime_quotes.return_value = 0
        pipeline.db = MagicMock()
        pipeline._save_local_report = MagicMock()
        pipeline._send_notifications = MagicMock()
        pipeline._send_single_stock_notification = MagicMock()
        pipeline._resolve_resume_target_date = MagicMock(
            return_value=date(2026, 8, 26)
        )
        pipeline.process_single_stock = MagicMock(return_value=None)

        unsupported = parse_analysis_target("930956.CSI")
        supported = [
            _stock_target("600519"),
            _stock_target("000016"),
            _stock_target("AAPL"),
            _stock_target("TSLA"),
            _stock_target("hk00700"),
        ]
        codes = ["930956.CSI", *[target.canonical_id for target in supported]]
        targets = [unsupported, *supported]

        with patch.object(
            StockAnalysisPipeline, "process_single_stock", pipeline.process_single_stock
        ):
            results = pipeline.run(
                stock_codes=codes,
                analysis_targets=targets,
                send_notification=False,
                dry_run=False,
            )

        # Five supported targets still cross the prefetch threshold, proving the
        # unsupported target was removed from every provider request first.
        supported_codes = codes[1:]
        pipeline.fetcher_manager.prefetch_daily_klines.assert_called_once_with(
            supported_codes, days=30
        )
        pipeline.fetcher_manager.prefetch_realtime_quotes.assert_called_once_with(
            supported_codes
        )
        pipeline.fetcher_manager.prefetch_stock_names.assert_called_once_with(
            supported_codes, use_bulk=False
        )
        self.assertEqual(pipeline.process_single_stock.call_count, 5)
        submitted_codes = {
            call.args[0] for call in pipeline.process_single_stock.call_args_list
        }
        self.assertEqual(submitted_codes, set(supported_codes))
        self.assertEqual(results, [])


class PipelineDryRunTestCase(unittest.TestCase):
    """V11 — dry-run preserves target identity through resume checks."""

    def test_v11_dry_run_uses_target_aware_resume_date(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = MagicMock()
        pipeline.config.refresh_stock_list = MagicMock()
        pipeline.config.stock_list = []
        pipeline.config.single_stock_notify = False
        pipeline.config.report_type = "simple"
        pipeline.config.analysis_delay = 0
        pipeline.max_workers = 1
        pipeline.fetcher_manager = MagicMock()
        pipeline.db = MagicMock()
        pipeline.db.has_today_data.return_value = True
        pipeline._save_local_report = MagicMock()
        pipeline._send_notifications = MagicMock()
        pipeline._send_single_stock_notification = MagicMock()
        pipeline.process_single_stock = MagicMock(return_value=None)

        target = _index_target("930955.CSI")
        with patch.object(
            StockAnalysisPipeline,
            "_resolve_resume_target_date",
            return_value=date(2026, 8, 26),
        ) as mock_resolve:
            pipeline.run(
                stock_codes=["csi930955"],
                dry_run=True,
                send_notification=False,
                analysis_targets=[target],
            )

        # The resume date must be resolved with the index target so market=cn
        # governs the dry-run success check.
        self.assertEqual(mock_resolve.call_count, 1)  # dry-run success count
        for call in mock_resolve.call_args_list:
            self.assertEqual(call.kwargs.get("analysis_target"), target)


if __name__ == "__main__":
    unittest.main()
