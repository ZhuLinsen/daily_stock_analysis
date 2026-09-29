# -*- coding: utf-8 -*-
"""Pipeline tests for Issue #1381 daily market context injection."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.analyzer import GeminiAnalyzer
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType
from src.services.daily_market_context import DailyMarketContext


def _pipeline_config(*, daily_market_context_enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(
        max_workers=1,
        save_context_snapshot=False,
        bocha_api_keys=[],
        tavily_api_keys=[],
        anspire_api_keys=[],
        brave_api_keys=[],
        serpapi_keys=[],
        minimax_api_keys=[],
        searxng_base_urls=[],
        searxng_public_instances_enabled=False,
        news_max_age_days=3,
        news_strategy_profile="short",
        enable_realtime_quote=False,
        realtime_source_priority=[],
        enable_chip_distribution=False,
        social_sentiment_api_key="",
        social_sentiment_api_url="https://example.invalid/social",
        daily_market_context_enabled=daily_market_context_enabled,
    )


def _build_initialized_pipeline(
    config: SimpleNamespace,
    **kwargs,
) -> StockAnalysisPipeline:
    search_service = MagicMock()
    search_service.is_available = False
    social_sentiment_service = MagicMock()
    social_sentiment_service.is_available = False

    with patch("src.core.pipeline.get_db", return_value=MagicMock()), \
         patch("src.core.pipeline.DataFetcherManager", return_value=MagicMock()), \
         patch("src.core.pipeline.StockTrendAnalyzer", return_value=MagicMock()), \
         patch("src.core.pipeline.GeminiAnalyzer", return_value=MagicMock()), \
         patch("src.core.pipeline.NotificationService", return_value=MagicMock()), \
         patch("src.core.pipeline.SearchService", return_value=search_service), \
         patch("src.core.pipeline.SocialSentimentService", return_value=social_sentiment_service):
        return StockAnalysisPipeline(config=config, **kwargs)


def _market_context() -> DailyMarketContext:
    return DailyMarketContext(
        region="cn",
        trade_date=date(2026, 6, 6),
        summary="大盘退潮，高风险，建议观望，仓位上限30%。",
        risk_tags=["high_risk", "low_position_cap"],
        source="analysis_history",
    )


def test_pipeline_constructor_defaults_daily_context_flag_from_config() -> None:
    pipeline = _build_initialized_pipeline(
        _pipeline_config(daily_market_context_enabled=True)
    )

    assert pipeline.daily_market_context_enabled is True


def test_pipeline_constructor_keeps_config_disabled_by_default() -> None:
    pipeline = _build_initialized_pipeline(
        _pipeline_config(daily_market_context_enabled=False)
    )

    assert pipeline.daily_market_context_enabled is False


def test_pipeline_constructor_explicit_flag_overrides_config() -> None:
    pipeline = _build_initialized_pipeline(
        _pipeline_config(daily_market_context_enabled=True),
        daily_market_context_enabled=False,
    )

    assert pipeline.daily_market_context_enabled is False


def test_pipeline_loads_daily_market_context_when_market_review_enabled() -> None:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        market_review_enabled=True,
        daily_market_context_enabled=True,
        report_language="zh",
    )
    pipeline.daily_market_context_enabled = True
    pipeline.db = MagicMock()
    pipeline.notifier = MagicMock()
    pipeline.analyzer = MagicMock()
    pipeline.search_service = MagicMock()
    pipeline.query_id = "pipeline-query"

    with patch("src.core.pipeline.DailyMarketContextService") as service_cls:
        service = service_cls.return_value
        service.get_context.return_value = _market_context()

        target_date = date(2026, 6, 6)

        context = pipeline._load_daily_market_context("cn", target_date=target_date)

    assert context is not None
    service_cls.assert_called_once_with(db_manager=pipeline.db)
    service.get_context.assert_called_once_with(
        region="cn",
        config=pipeline.config,
        notifier=pipeline.notifier,
        analyzer=pipeline.analyzer,
        search_service=pipeline.search_service,
        force_refresh=False,
        allow_generate=True,
        target_date=target_date,
        current_query_id="pipeline-query",
    )


def test_pipeline_can_load_daily_market_context_without_runtime_generation() -> None:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        market_review_enabled=True,
        daily_market_context_enabled=True,
        report_language="zh",
    )
    pipeline.daily_market_context_enabled = True
    pipeline.db = MagicMock()
    pipeline.notifier = MagicMock()
    pipeline.analyzer = MagicMock()
    pipeline.search_service = MagicMock()
    pipeline.daily_market_context_allow_generate = False

    with patch("src.core.pipeline.DailyMarketContextService") as service_cls:
        service = service_cls.return_value
        service.get_context.return_value = None

        context = pipeline._load_daily_market_context(
            "cn",
            target_date=date(2026, 6, 6),
        )

    assert context is None
    service.get_context.assert_called_once()
    assert service.get_context.call_args.kwargs["allow_generate"] is False


def test_pipeline_skips_daily_market_context_when_context_is_disabled() -> None:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        market_review_enabled=True,
        daily_market_context_enabled=True,
        report_language="zh",
    )
    pipeline.daily_market_context_enabled = False

    with patch("src.core.pipeline.DailyMarketContextService") as service_cls:
        context = pipeline._load_daily_market_context(
            "cn",
            target_date=date(2026, 6, 6),
        )

    assert context is None
    service_cls.assert_not_called()


def test_pipeline_skips_daily_market_context_when_config_is_disabled() -> None:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        market_review_enabled=True,
        daily_market_context_enabled=False,
        report_language="zh",
    )
    pipeline.daily_market_context_enabled = True

    with patch("src.core.pipeline.DailyMarketContextService") as service_cls:
        context = pipeline._load_daily_market_context(
            "cn",
            target_date=date(2026, 6, 6),
        )

    assert context is None
    service_cls.assert_not_called()


def test_pipeline_initializes_daily_market_context_service_once_across_threads() -> None:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = SimpleNamespace(
        market_review_enabled=True,
        daily_market_context_enabled=True,
        report_language="zh",
    )
    pipeline.daily_market_context_enabled = True
    pipeline.db = MagicMock()
    pipeline.notifier = MagicMock()
    pipeline.analyzer = MagicMock()
    pipeline.search_service = MagicMock()

    service = MagicMock()
    service.get_context.return_value = _market_context()
    worker_count = 8
    start_barrier = threading.Barrier(worker_count)
    constructor_entered = threading.Event()
    release_constructor = threading.Event()

    def _load() -> DailyMarketContext:
        start_barrier.wait(timeout=2)
        return pipeline._load_daily_market_context(
            "cn",
            target_date=date(2026, 6, 6),
        )

    def _create_service(*args, **kwargs):
        constructor_entered.set()
        release_constructor.wait(timeout=2)
        return service

    with patch("src.core.pipeline.DailyMarketContextService", side_effect=_create_service) as service_cls:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_load) for _ in range(worker_count)]
            assert constructor_entered.wait(timeout=2)
            time.sleep(0.05)
            release_constructor.set()
            contexts = [future.result(timeout=2) for future in futures]

    assert contexts == [_market_context()] * worker_count
    service_cls.assert_called_once_with(db_manager=pipeline.db)
    assert service.get_context.call_count == worker_count


def test_pipeline_uses_market_phase_effective_date_for_daily_market_context() -> None:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    phase_context = SimpleNamespace(
        effective_daily_bar_date=date(2026, 3, 26),
        to_dict=MagicMock(
            return_value={
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
        ),
    )
    pipeline.config = SimpleNamespace(
        enable_realtime_quote=False,
        enable_chip_distribution=False,
        market_review_enabled=True,
        report_language="zh",
        agent_mode=False,
        save_context_snapshot=False,
        report_integrity_enabled=False,
        fundamental_stage_timeout_seconds=1,
    )
    pipeline.query_source = "system"
    pipeline.analysis_phase = "auto"
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
    pipeline._emit_progress = MagicMock()
    pipeline._load_daily_market_context = MagicMock(return_value=_market_context())

    with patch("src.core.pipeline.build_market_phase_context", return_value=phase_context):
        pipeline.analyze_stock(
            "600519",
            ReportType.SIMPLE,
            "q-effective-date",
        )

    pipeline._load_daily_market_context.assert_called_once_with(
        "cn",
        target_date=date(2026, 3, 26),
    )


def test_pipeline_attaches_low_sensitive_market_context_to_enhanced_context() -> None:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    enhanced_context = {"code": "600519"}

    pipeline._attach_daily_market_context(
        enhanced_context,
        _market_context(),
        report_language="zh",
    )

    assert enhanced_context["daily_market_context"]["region"] == "cn"
    assert enhanced_context["daily_market_context"]["summary"].startswith("大盘退潮")
    assert "大盘环境摘要" in enhanced_context["daily_market_context_summary"]
    assert "market_review_payload" not in str(enhanced_context)


def test_analyzer_prompt_renders_daily_market_context_before_technical_data() -> None:
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._get_skill_prompt_sections = lambda: ("", "", False)
    context = {
        "code": "600519",
        "stock_name": "贵州茅台",
        "date": "2026-06-06",
        "today": {"close": 1800, "open": 1790, "high": 1810, "low": 1780},
        "daily_market_context": _market_context().to_safe_dict(),
    }

    prompt = analyzer._format_prompt(context, "贵州茅台", report_language="zh")

    assert "大盘环境摘要" in prompt
    assert "大盘退潮" in prompt
    assert prompt.index("大盘环境摘要") < prompt.index("技术面数据")
