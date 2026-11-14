# -*- coding: utf-8 -*-
"""Pipeline / injection tests for Issue #1910 cross-asset context (T14-T18).

Absorbs the former ``tests/test_pipeline_cross_asset_inject_min.py`` (10 cases,
semantics unchanged) and completes the W1-plan T14-T18 matrix:

- T14 pipeline integration: switch ON -> ``enhanced_context`` carries the safe
  dict + rendered summary and the analyzer prompt contains the "外围环境"
  section (both the pipeline-rendered preferred path and the safe-dict
  fallback path);
- T15 switch OFF: zero keys, zero service calls, no prompt section;
- T16 service raise: fail-open, main analysis completes;
- T17 Agent path: ``initial_context`` injection + ``AgentExecutor
  ._build_user_message`` + multi-agent RiskAgent message;
- T18 snapshot keeps only the low-sensitivity summary/safe dict; API meta
  passthrough is optional and old snapshots keep the old response structure.

The conservative switch semantics are LOCKED here on purpose (see
``TestSwitchSemanticsLocked``): config objects without the
``cross_asset_context_enabled`` attribute are treated as disabled. Do not
flip that default to True without the w3-review decision — flipping requires
patching every legacy SimpleNamespace/MagicMock stub in the suite.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api.v1.endpoints.analysis import (
    _attach_cross_asset_summary_to_report_meta,
    _extract_cross_asset_context_summary,
)
from src.agent.agents.risk_agent import RiskAgent
from src.agent.executor import AgentExecutor
from src.agent.protocols import AgentContext
from src.analyzer import GeminiAnalyzer
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType
from src.schemas.cross_asset_context import CrossAssetContext, CrossAssetItem

TRADE_DATE = date(2026, 6, 6)


def _config(*, enabled: bool | None = True) -> SimpleNamespace:
    config = SimpleNamespace(
        market_review_enabled=True,
        daily_market_context_enabled=False,
        report_language="zh",
    )
    if enabled is not None:
        config.cross_asset_context_enabled = enabled
    return config


def _pipeline(*, enabled: bool | None = True) -> StockAnalysisPipeline:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = _config(enabled=enabled)
    pipeline.analysis_skills = None
    return pipeline


def _risk_off_context() -> CrossAssetContext:
    return CrossAssetContext(
        market="cn",
        trade_date="2026-06-06",
        risk_appetite="risk_off",
        indices={
            "sh000001": CrossAssetItem(
                status="ok",
                value=3100.5,
                change_pct=-1.8,
                source="akshare",
                as_of="2026-06-06",
                stale=False,
                error=None,
            )
        },
        volatility={
            "VIX": CrossAssetItem(
                status="ok",
                value=25.3,
                change_pct=12.0,
                source="yfinance",
                as_of="2026-06-05",
                stale=True,
                error=None,
            )
        },
        impact_summary="外部环境偏 risk-off：VIX 25.3(+12%)，上证走弱",
        risk_tags=["vix_high", "cn_index_down"],
    )


# ---------------------------------------------------------------------------
# Absorbed minimal cases (semantics unchanged from -min file)
# ---------------------------------------------------------------------------
class TestSwitchSemanticsLocked:
    """LOCKED conservative switch semantics — intentional, do not flip.

    ``_load_cross_asset_context`` requires ``config.cross_asset_context_enabled
    is True`` (``getattr(..., None) is not True -> None``). Config objects
    predating the field (legacy snapshots, lightweight test stubs) therefore
    get zero cross-asset behaviour. This is a deliberate deviation from the
    daily-market-context mirror (``getattr(..., True)``) to protect old stubs
    from surprise network fetches; production ``Config`` always carries the
    field with default True. Whether to flip the default is a w3-review
    adjudication item, NOT a test-side choice.
    """

    def test_load_calls_service_when_switch_explicitly_true(self) -> None:
        pipeline = _pipeline(enabled=True)
        service = MagicMock()
        service.get_context.return_value = _risk_off_context()

        with patch(
            "src.core.pipeline.get_default_cross_asset_context_service",
            return_value=service,
        ) as factory:
            context = pipeline._load_cross_asset_context(
                "cn",
                target_date=TRADE_DATE,
                stock_code="600519",
            )

        factory.assert_called_once_with()
        service.get_context.assert_called_once_with(
            "cn",
            TRADE_DATE,
            "600519",
            config=pipeline.config,
        )
        assert context is not None
        assert context.risk_appetite == "risk_off"

    def test_load_skips_when_switch_off(self) -> None:
        pipeline = _pipeline(enabled=False)

        with patch(
            "src.core.pipeline.get_default_cross_asset_context_service"
        ) as factory:
            context = pipeline._load_cross_asset_context(
                "cn",
                target_date=TRADE_DATE,
            )

        assert context is None
        factory.assert_not_called()

    def test_load_treats_missing_attr_as_disabled(self) -> None:
        """Legacy config objects without the field must see zero behaviour
        change (intentionally conservative; see class docstring)."""
        pipeline = _pipeline(enabled=None)

        with patch(
            "src.core.pipeline.get_default_cross_asset_context_service"
        ) as factory:
            context = pipeline._load_cross_asset_context(
                "cn",
                target_date=TRADE_DATE,
            )

        assert context is None
        factory.assert_not_called()


class TestLoadFailOpen:
    def test_load_fail_open_on_service_raise(self) -> None:
        pipeline = _pipeline(enabled=True)
        service = MagicMock()
        service.get_context.side_effect = RuntimeError("provider exploded")

        with patch(
            "src.core.pipeline.get_default_cross_asset_context_service",
            return_value=service,
        ):
            context = pipeline._load_cross_asset_context(
                "cn",
                target_date=TRADE_DATE,
            )

        assert context is None  # fail-open: main analysis continues


class TestAttach:
    def test_attach_writes_safe_dict_and_summary_only_when_section_non_empty(self) -> None:
        pipeline = _pipeline()
        enhanced_context: dict = {"code": "600519"}

        pipeline._attach_cross_asset_context(
            enhanced_context,
            _risk_off_context(),
            report_language="zh",
        )

        assert enhanced_context["cross_asset_context"]["risk_appetite"] == "risk_off"
        assert "sh000001" in enhanced_context["cross_asset_context"]["indices"]
        # safe dict whitelist: no Chinese name field leakage beyond item keys
        assert "name" not in enhanced_context["cross_asset_context"]["indices"]["sh000001"]
        summary = enhanced_context["cross_asset_context_summary"]
        assert "外围环境与跨资产" in summary
        assert "risk-off" in summary
        assert "BEGIN_UNTRUSTED_CROSS_ASSET_SUMMARY" in summary

    def test_attach_noop_for_none_context(self) -> None:
        pipeline = _pipeline()
        enhanced_context: dict = {"code": "600519"}

        pipeline._attach_cross_asset_context(enhanced_context, None, report_language="zh")

        assert "cross_asset_context" not in enhanced_context
        assert "cross_asset_context_summary" not in enhanced_context

    def test_switch_off_leaves_context_without_cross_asset_keys(self) -> None:
        pipeline = _pipeline(enabled=False)
        enhanced_context: dict = {"code": "600519"}

        # switch off -> _load_cross_asset_context returns None -> attach is a no-op
        loaded = pipeline._load_cross_asset_context(
            "cn",
            target_date=TRADE_DATE,
        )
        pipeline._attach_cross_asset_context(
            enhanced_context,
            loaded,
            report_language="zh",
        )

        assert "cross_asset_context" not in enhanced_context
        assert "cross_asset_context_summary" not in enhanced_context


class TestPromptInjection:
    """T14 — the section reaches the analyzer prompt."""

    def test_analyzer_prompt_contains_cross_asset_section_when_attached(self) -> None:
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        analyzer._get_skill_prompt_sections = lambda: ("", "", False)
        context = {
            "code": "600519",
            "stock_name": "贵州茅台",
            "date": "2026-06-06",
            "today": {"close": 1800, "open": 1790, "high": 1810, "low": 1780},
            "cross_asset_context": _risk_off_context().to_safe_dict(),
        }

        prompt = analyzer._format_prompt(context, "贵州茅台", report_language="zh")

        assert "外围环境与跨资产" in prompt
        assert "risk-off" in prompt
        assert "上证指数与跨资产" not in prompt  # no accidental daily section title
        # section order: cross-asset after daily (absent here), before technical data
        assert prompt.index("外围环境与跨资产") < prompt.index("技术面数据")

    def test_analyzer_prompt_has_no_cross_asset_section_when_switch_off(self) -> None:
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        analyzer._get_skill_prompt_sections = lambda: ("", "", False)
        context = {
            "code": "600519",
            "stock_name": "贵州茅台",
            "date": "2026-06-06",
            "today": {"close": 1800, "open": 1790, "high": 1810, "low": 1780},
        }

        prompt = analyzer._format_prompt(context, "贵州茅台", report_language="zh")

        assert "外围环境与跨资产" not in prompt
        assert "Cross-Asset Context" not in prompt

    def test_analyzer_prompt_prefers_pipeline_rendered_summary(self) -> None:
        """Pipeline-rendered summary wins over re-rendering the safe dict."""
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        analyzer._get_skill_prompt_sections = lambda: ("", "", False)
        rendered = "## 外围环境与跨资产\n- 管线预渲染摘要（优先通道）"
        context = {
            "code": "600519",
            "stock_name": "贵州茅台",
            "date": "2026-06-06",
            "today": {"close": 1800, "open": 1790, "high": 1810, "low": 1780},
            "cross_asset_context": _risk_off_context().to_safe_dict(),
            "cross_asset_context_summary": rendered,
        }

        prompt = analyzer._format_prompt(context, "贵州茅台", report_language="zh")

        assert "管线预渲染摘要（优先通道）" in prompt
        # the fallback re-render (which would print "sh000001") is not used
        assert prompt.count("外围环境与跨资产") == 1

    def test_whitespace_only_summary_falls_back_to_safe_dict(self) -> None:
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        analyzer._get_skill_prompt_sections = lambda: ("", "", False)
        context = {
            "code": "600519",
            "stock_name": "贵州茅台",
            "date": "2026-06-06",
            "today": {"close": 1800, "open": 1790, "high": 1810, "low": 1780},
            "cross_asset_context": _risk_off_context().to_safe_dict(),
            "cross_asset_context_summary": "   ",
        }

        prompt = analyzer._format_prompt(context, "贵州茅台", report_language="zh")

        assert "外围环境与跨资产" in prompt  # fallback rendering kicks in
        assert "sh000001" in prompt


class TestSnapshot:
    """T18 — snapshot keeps only the low-sensitivity summary/safe dict."""

    def test_context_snapshot_keeps_low_sensitivity_summary(self) -> None:
        pipeline = _pipeline()
        enhanced_context = {
            "code": "600519",
            "cross_asset_context": _risk_off_context().to_safe_dict(),
            "cross_asset_context_summary": "## 外围环境与跨资产\n- 外围风险偏好：risk-off",
        }

        snapshot = pipeline._build_context_snapshot(
            enhanced_context=enhanced_context,
            news_content=None,
            realtime_quote=None,
            chip_data=None,
        )

        sanitized = snapshot["enhanced_context"]
        assert "cross_asset_context_summary" in sanitized
        assert "cross_asset_context" in sanitized
        assert sanitized["cross_asset_context"]["risk_appetite"] == "risk_off"

    def test_snapshot_cross_asset_payload_is_safe_dict_not_raw_context(self) -> None:
        pipeline = _pipeline()
        raw_context = _risk_off_context()
        enhanced_context = {
            "code": "600519",
            "cross_asset_context": raw_context.to_safe_dict(),
            "cross_asset_context_summary": "## 外围环境与跨资产\n- 外围风险偏好：risk-off",
        }

        snapshot = pipeline._build_context_snapshot(
            enhanced_context=enhanced_context,
            news_content=None,
            realtime_quote=None,
            chip_data=None,
        )

        stored = snapshot["enhanced_context"]["cross_asset_context"]
        # no raw pydantic object, no per-item display names, no generated_at
        assert isinstance(stored, dict)
        assert "generated_at" not in stored
        for group in ("indices", "volatility"):
            for item in stored[group].values():
                assert "name" not in item
                # quality quadruple survives into the snapshot
                assert {"source", "as_of", "stale", "error"} <= set(item)
        # the pipeline never persisted the raw model dump side by side
        assert snapshot["enhanced_context"].get("cross_asset_context_raw") is None


class TestGuardrailWiring:
    def test_guardrail_receives_safe_dict_from_enhanced_context_and_is_idempotent(self) -> None:
        from src.cross_asset_context_guardrail import apply_cross_asset_context_guardrail

        result = SimpleNamespace(
            confidence_level="高",
            operation_advice="立即买入，激进加仓",
            phase_decision={"confidence_reason": "", "data_limitations": []},
            dashboard={"position_advice": "建议立即重仓买入"},
        )
        enhanced_context = {"cross_asset_context": _risk_off_context().to_safe_dict()}

        first = apply_cross_asset_context_guardrail(
            result,
            cross_asset_context=enhanced_context.get("cross_asset_context"),
            report_language="zh",
        )
        second = apply_cross_asset_context_guardrail(
            result,
            cross_asset_context=enhanced_context.get("cross_asset_context"),
            report_language="zh",
        )

        assert "confidence_capped_cross_asset_context" in first
        assert result.confidence_level == "中"  # capped once, not repeatedly
        assert second == []  # idempotent on second pass (phase -> daily -> cross-asset)


# ---------------------------------------------------------------------------
# T14/T15/T16 — full pipeline integration (analyze_stock)
# ---------------------------------------------------------------------------
def _integration_pipeline(*, enabled: bool | None = True) -> StockAnalysisPipeline:
    """Analyze_stock scaffold mirroring test_pipeline_daily_market_context."""
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    config = _config(enabled=enabled)
    config.enable_realtime_quote = False
    config.enable_chip_distribution = False
    config.agent_mode = False
    config.save_context_snapshot = False
    config.report_integrity_enabled = False
    config.fundamental_stage_timeout_seconds = 1
    pipeline.config = config
    pipeline.query_source = "system"
    pipeline.analysis_phase = "auto"
    pipeline.analysis_skills = None
    pipeline.portfolio_context = None
    pipeline.fetcher_manager = MagicMock()
    pipeline.fetcher_manager.get_stock_name.return_value = "贵州茅台"
    pipeline.fetcher_manager.get_chip_distribution.return_value = None
    pipeline.fetcher_manager.get_fundamental_context.return_value = {}
    pipeline.fetcher_manager.build_failed_fundamental_context.return_value = {}
    pipeline.db = MagicMock()
    pipeline.db.get_analysis_context.return_value = {
        "code": "600519",
        "stock_name": "贵州茅台",
        "today": {},
        "yesterday": {},
    }
    pipeline.trend_analyzer = MagicMock()
    pipeline.analyzer = MagicMock()
    pipeline.analyzer.analyze.return_value = MagicMock(success=True)
    pipeline.search_service = MagicMock()
    pipeline.search_service.is_available = False
    pipeline.search_service.news_window_days = 3
    pipeline.social_sentiment_service = None
    pipeline._emit_progress = MagicMock()
    pipeline._load_daily_market_context = MagicMock(return_value=None)
    return pipeline


def _phase_context() -> SimpleNamespace:
    return SimpleNamespace(
        effective_daily_bar_date=TRADE_DATE,
        to_dict=MagicMock(
            return_value={
                "market": "cn",
                "phase": "intraday",
                "market_local_time": "2026-06-06T10:00:00+08:00",
                "session_date": "2026-06-06",
                "effective_daily_bar_date": "2026-06-06",
                "is_trading_day": True,
                "is_market_open_now": True,
                "is_partial_bar": True,
                "minutes_to_open": None,
                "minutes_to_close": 300,
                "trigger_source": "system",
                "analysis_intent": "auto",
                "warnings": [],
            }
        ),
    )


def _analyzer_context(analyzer_mock: MagicMock) -> dict:
    assert analyzer_mock.analyze.call_count == 1
    return analyzer_mock.analyze.call_args[0][0]


class TestPipelineIntegration:
    def test_switch_on_injects_keys_and_reaches_analyzer_prompt_context(self) -> None:
        """T14 — switch ON: service called once; analyzer receives safe dict +
        rendered summary."""
        pipeline = _integration_pipeline(enabled=True)
        service = MagicMock()
        service.get_context.return_value = _risk_off_context()

        with patch(
            "src.core.pipeline.build_market_phase_context",
            return_value=_phase_context(),
        ), patch(
            "src.core.pipeline.get_default_cross_asset_context_service",
            return_value=service,
        ) as factory:
            pipeline.analyze_stock("600519", ReportType.SIMPLE, "q-cross-on")

        factory.assert_called_once_with()
        service.get_context.assert_called_once_with(
            "cn", TRADE_DATE, "600519", config=pipeline.config
        )
        context = _analyzer_context(pipeline.analyzer)
        assert context["cross_asset_context"]["risk_appetite"] == "risk_off"
        summary = context["cross_asset_context_summary"]
        assert "外围环境与跨资产" in summary
        assert "BEGIN_UNTRUSTED_CROSS_ASSET_SUMMARY" in summary

    def test_switch_off_means_zero_keys_and_zero_service_calls(self) -> None:
        """T15 — switch OFF: no fetch, no keys, prompt untouched."""
        pipeline = _integration_pipeline(enabled=False)

        with patch(
            "src.core.pipeline.build_market_phase_context",
            return_value=_phase_context(),
        ), patch(
            "src.core.pipeline.get_default_cross_asset_context_service"
        ) as factory:
            pipeline.analyze_stock("600519", ReportType.SIMPLE, "q-cross-off")

        factory.assert_not_called()
        context = _analyzer_context(pipeline.analyzer)
        assert "cross_asset_context" not in context
        assert "cross_asset_context_summary" not in context

    def test_service_raise_fail_open_and_main_analysis_completes(self) -> None:
        """T16 — service explodes: pipeline still finishes the analysis."""
        pipeline = _integration_pipeline(enabled=True)
        service = MagicMock()
        service.get_context.side_effect = RuntimeError("cross-asset provider down")

        with patch(
            "src.core.pipeline.build_market_phase_context",
            return_value=_phase_context(),
        ), patch(
            "src.core.pipeline.get_default_cross_asset_context_service",
            return_value=service,
        ):
            pipeline.analyze_stock("600519", ReportType.SIMPLE, "q-cross-raise")

        # main analysis ran exactly once and was not interrupted
        assert pipeline.analyzer.analyze.call_count == 1
        context = _analyzer_context(pipeline.analyzer)
        assert "cross_asset_context" not in context
        assert "cross_asset_context_summary" not in context


# ---------------------------------------------------------------------------
# T17 — Agent path
# ---------------------------------------------------------------------------
class TestAgentPath:
    @patch("src.agent.factory.build_agent_executor")
    def test_agent_initial_context_receives_cross_asset_keys(
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
        pipeline._build_analysis_context_pack_outputs = MagicMock(return_value=("", None))
        pipeline._agent_result_to_analysis_result = MagicMock(return_value=None)

        executor = MagicMock()
        executor.run.return_value = MagicMock(model="test-model", runtime_facts=None)
        mock_build_executor.return_value = executor

        pipeline._analyze_with_agent(
            code="600519",
            report_type=ReportType.SIMPLE,
            query_id="q-agent-cross",
            stock_name="贵州茅台",
            realtime_quote=None,
            chip_data=None,
            cross_asset_context=_risk_off_context(),
        )

        executor.run.assert_called_once()
        _, run_kwargs = executor.run.call_args
        context = run_kwargs["context"]
        assert context["cross_asset_context"]["risk_appetite"] == "risk_off"
        assert "外围环境与跨资产" in context["cross_asset_context_summary"]

    def test_executor_build_user_message_renders_cross_asset_section(self) -> None:
        executor = AgentExecutor.__new__(AgentExecutor)
        context = {
            "stock_code": "600519",
            "report_type": "simple",
            "report_language": "zh",
            "cross_asset_context": _risk_off_context().to_safe_dict(),
        }

        message = executor._build_user_message("请分析股票", context)

        assert "外围环境与跨资产" in message
        assert "risk-off" in message
        assert "BEGIN_UNTRUSTED_CROSS_ASSET_SUMMARY" in message

    def test_executor_build_user_message_without_cross_asset_key(self) -> None:
        executor = AgentExecutor.__new__(AgentExecutor)
        context = {"stock_code": "600519", "report_language": "zh"}

        message = executor._build_user_message("请分析股票", context)

        assert "外围环境与跨资产" not in message
        assert "Cross-Asset Context" not in message

    def test_risk_agent_user_message_includes_cross_asset_section(self) -> None:
        """Multi-agent path: orchestrator shares ctx.meta; RiskAgent renders."""
        agent = RiskAgent(MagicMock(), MagicMock())
        ctx = AgentContext(stock_code="600519", stock_name="贵州茅台")
        ctx.meta["cross_asset_context"] = _risk_off_context().to_safe_dict()
        ctx.meta["report_language"] = "zh"

        message = agent.build_user_message(ctx)

        assert "外围环境与跨资产" in message
        assert "risk-off" in message

    def test_risk_agent_user_message_without_cross_asset_meta(self) -> None:
        agent = RiskAgent(MagicMock(), MagicMock())
        ctx = AgentContext(stock_code="600519", stock_name="贵州茅台")

        message = agent.build_user_message(ctx)

        assert "外围环境与跨资产" not in message


# ---------------------------------------------------------------------------
# OR-COR-f88926c2 — standard/quick multi-agent chains carry the summary
# ---------------------------------------------------------------------------
class TestMultiAgentMessageInjection:
    """The cross-asset summary must reach EVERY mode's agent chain through the
    real execution path (real agents, fake LLM loop): quick=technical→decision
    and standard=technical→intel→decision contain no RiskAgent, so before the
    BaseAgent injection those modes analyzed with zero external context while
    the post-processing still applied the risk-off confidence guardrail."""

    @staticmethod
    def _dashboard_json() -> str:
        return json.dumps({
            "stock_name": "贵州茅台",
            "sentiment_score": 72,
            "trend_prediction": "up",
            "operation_advice": "buy",
            "decision_type": "buy",
            "confidence_level": "高",
            "dashboard": {
                "phase_decision": {
                    "phase_context": "regular",
                    "action_window": "now",
                    "immediate_action": "watch",
                    "watch_conditions": [],
                    "next_check_time": "next session",
                    "confidence_reason": "fixture",
                    "data_limitations": [],
                },
                "core_conclusion": {
                    "one_sentence": "fixture decision",
                    "signal_type": "buy",
                    "position_advice": {"no_position": "watch", "has_position": "hold"},
                },
            },
            "analysis_summary": "fixture summary",
            "key_points": ["fixture"],
            "risk_warning": "",
        }, ensure_ascii=False)

    def _run_multi_agent(self, mode: str):
        from src.agent.orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator(
            tool_registry=MagicMock(), llm_adapter=MagicMock(), mode=mode,
        )
        ctx = orchestrator._build_context(
            "分析 600519",
            context={
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "cross_asset_context": _risk_off_context().to_safe_dict(),
            },
        )
        captured_messages = []

        def fake_run_agent_loop(messages, **kwargs):
            captured_messages.append(messages)
            return SimpleNamespace(
                success=True,
                content=self._dashboard_json(),
                total_tokens=11,
                tool_calls_log=[],
                models_used=["test/model"],
                total_steps=1,
                failure_reason=None,
            )

        with patch(
            "src.agent.agents.base_agent.run_agent_loop",
            side_effect=fake_run_agent_loop,
        ):
            result = orchestrator._execute_pipeline(ctx, parse_dashboard=False)

        chain_names = [agent.agent_name for agent in orchestrator._build_agent_chain(ctx)]
        return result, captured_messages, chain_names

    @staticmethod
    def _joined(messages) -> str:
        return "\n".join(str(message.get("content", "")) for message in messages)

    def test_standard_chain_every_stage_receives_summary(self):
        result, captured, chain_names = self._run_multi_agent("standard")

        assert result.success
        assert chain_names == ["technical", "intel", "decision"]
        assert len(captured) == 3
        for messages in captured:
            joined = self._joined(messages)
            assert "BEGIN_UNTRUSTED_CROSS_ASSET_SUMMARY" in joined
            assert "END_UNTRUSTED_CROSS_ASSET_SUMMARY" in joined
            assert "risk-off" in joined

    def test_quick_chain_every_stage_receives_summary(self):
        result, captured, chain_names = self._run_multi_agent("quick")

        assert result.success
        assert chain_names == ["technical", "decision"]
        assert len(captured) == 2
        for messages in captured:
            joined = self._joined(messages)
            assert "BEGIN_UNTRUSTED_CROSS_ASSET_SUMMARY" in joined
            assert "risk-off" in joined

    def test_full_chain_risk_stage_renders_summary_exactly_once(self):
        """RiskAgent renders the section in its own user message; the shared
        BaseAgent injection must opt out for it (no duplicated block)."""
        result, captured, chain_names = self._run_multi_agent("full")

        assert chain_names == ["technical", "intel", "risk", "decision"]
        risk_joined = self._joined(captured[chain_names.index("risk")])
        assert risk_joined.count("BEGIN_UNTRUSTED_CROSS_ASSET_SUMMARY") == 1
        assert "risk-off" in risk_joined

    def test_no_cross_asset_context_means_no_section(self):
        from src.agent.orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator(
            tool_registry=MagicMock(), llm_adapter=MagicMock(), mode="standard",
        )
        ctx = orchestrator._build_context(
            "分析 600519", context={"stock_code": "600519", "stock_name": "贵州茅台"},
        )
        captured_messages = []

        def fake_run_agent_loop(messages, **kwargs):
            captured_messages.append(messages)
            return SimpleNamespace(
                success=True,
                content=self._dashboard_json(),
                total_tokens=11,
                tool_calls_log=[],
                models_used=["test/model"],
                total_steps=1,
                failure_reason=None,
            )

        with patch(
            "src.agent.agents.base_agent.run_agent_loop",
            side_effect=fake_run_agent_loop,
        ):
            result = orchestrator._execute_pipeline(ctx, parse_dashboard=False)

        assert result.success
        for messages in captured_messages:
            joined = self._joined(messages)
            assert "外围环境与跨资产" not in joined
            assert "BEGIN_UNTRUSTED_CROSS_ASSET_SUMMARY" not in joined


# ---------------------------------------------------------------------------
# T18 — API meta passthrough (optional field, legacy-compatible)
# ---------------------------------------------------------------------------
def _report_payload() -> dict:
    return {"meta": {"created_at": "2026-06-06T15:00:00"}}


class TestApiMetaPassthrough:
    def test_summary_extracted_from_enhanced_context_first(self) -> None:
        snapshot = {
            "enhanced_context": {"cross_asset_context_summary": "enhanced 摘要"},
            "cross_asset_context_summary": "top 摘要",
        }
        assert _extract_cross_asset_context_summary(snapshot) == "enhanced 摘要"

    def test_summary_falls_back_to_snapshot_top_level(self) -> None:
        snapshot = {"cross_asset_context_summary": "top 摘要"}
        assert _extract_cross_asset_context_summary(snapshot) == "top 摘要"

    def test_old_snapshot_yields_none(self) -> None:
        assert _extract_cross_asset_context_summary({"enhanced_context": {}}) is None
        assert _extract_cross_asset_context_summary(None) is None
        assert _extract_cross_asset_context_summary("legacy") is None

    def test_attach_writes_meta_only_when_summary_present(self) -> None:
        report = _report_payload()
        snapshot = {"enhanced_context": {"cross_asset_context_summary": "外围摘要"}}

        _attach_cross_asset_summary_to_report_meta(report, snapshot)

        assert report["meta"]["cross_asset_context_summary"] == "外围摘要"
        assert report["meta"]["created_at"] == "2026-06-06T15:00:00"  # untouched

    def test_old_snapshot_keeps_report_meta_unchanged(self) -> None:
        """Old responses stay byte-identical: no key added, nothing touched."""
        report = _report_payload()
        original_keys = set(report["meta"].keys())

        _attach_cross_asset_summary_to_report_meta(report, {"enhanced_context": {}})
        _attach_cross_asset_summary_to_report_meta(report, None)

        assert set(report["meta"].keys()) == original_keys
        assert "cross_asset_context_summary" not in report["meta"]

    def test_existing_meta_value_never_overwritten_and_garbage_payload_safe(self) -> None:
        report = {"meta": {"cross_asset_context_summary": "已有值"}}
        snapshot = {"enhanced_context": {"cross_asset_context_summary": "新值"}}
        _attach_cross_asset_summary_to_report_meta(report, snapshot)
        assert report["meta"]["cross_asset_context_summary"] == "已有值"

        # non-dict report payload: fail-open no-crash
        _attach_cross_asset_summary_to_report_meta("not-a-dict", snapshot)
        _attach_cross_asset_summary_to_report_meta({"meta": "not-a-dict"}, snapshot)
