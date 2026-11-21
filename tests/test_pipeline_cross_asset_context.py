# -*- coding: utf-8 -*-
"""Pipeline / injection tests for Issue #1910 cross-asset context (r2).

Phase-1 scope: the normal analysis path only — pipeline load/attach +
analyzer prompt injection, default OFF. The Agent/chat paths, the risk-off
confidence guardrail, the API meta passthrough and the DecisionSignal
passthrough are deferred to later PRs (roadmap in the PR description).

- T14 pipeline integration: switch ON -> ``enhanced_context`` carries the safe
  dict + rendered summary and the analyzer prompt contains the "外围环境"
  section (both the pipeline-rendered preferred path and the safe-dict
  fallback path);
- T15 switch OFF: zero keys, zero service calls, no prompt section;
- T16 service raise: fail-open, main analysis completes;
- T18 snapshot keeps only the low-sensitivity summary/safe dict.

The conservative switch semantics are LOCKED here on purpose (see
``TestSwitchSemanticsLocked``): config objects without the
``cross_asset_context_enabled`` attribute are treated as disabled. With the
r2 default (``False``) this means an unconfigured deployment has zero
cross-asset behaviour — the "不配置=零行为差异" guarantee.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
                source="yfinance",
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
    get zero cross-asset behaviour. With the r2 opt-in default (``False``)
    this is also what an unconfigured production deployment sees.
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
