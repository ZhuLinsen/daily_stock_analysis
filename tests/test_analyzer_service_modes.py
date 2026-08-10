# -*- coding: utf-8 -*-
"""Focused coverage for the cost-bounded stock analyzer service entrypoint."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from src.enums import ReportType
from src.services.analyzer_service import (
    StockAnalysisMode,
    StockAnalysisRunResult,
    _module_available,
    analyze_stock,
    analyze_stocks,
    run_stock_analysis,
)


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        generation_backend="litellm",
        realtime_source_priority="tencent,efinance",
        max_workers=2,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("check", StockAnalysisMode.CHECK),
        ("preflight", StockAnalysisMode.CHECK),
        ("dry-run", StockAnalysisMode.DATA),
        ("fetch_only", StockAnalysisMode.DATA),
        ("ai", StockAnalysisMode.FULL),
    ],
)
def test_mode_aliases(value, expected):
    assert StockAnalysisMode.from_value(value) is expected


def test_module_probe_accepts_an_already_loaded_test_double(monkeypatch):
    monkeypatch.setitem(sys.modules, "stubbed_runtime", SimpleNamespace(__spec__=None))

    assert _module_available("stubbed_runtime") is True


def test_check_mode_never_builds_pipeline_or_allows_external_calls():
    with patch("src.services.analyzer_service._build_pipeline") as build_pipeline:
        outcome = run_stock_analysis("600519", mode="check", config=_config())

    build_pipeline.assert_not_called()
    assert outcome.success is True
    assert outcome.network_allowed is False
    assert outcome.llm_allowed is False
    assert outcome.notification_allowed is False
    assert outcome.details["config_loaded"] is True
    assert outcome.details["pipeline_module_available"] is True


def test_check_mode_fails_on_structured_config_errors():
    config = _config()
    config.validate_structured = MagicMock(
        return_value=[
            SimpleNamespace(
                severity="error",
                message="未配置可用的 LLM 渠道",
                field="LLM_CHANNELS",
                code="missing_llm_channel",
            ),
            SimpleNamespace(
                severity="warning",
                message="搜索增强未配置",
                field="TAVILY_API_KEY",
                code="",
            ),
        ]
    )

    with patch("src.services.analyzer_service._module_available", return_value=True):
        outcome = run_stock_analysis("600519", mode="check", config=config)

    config.validate_structured.assert_called_once_with()
    assert outcome.success is False
    assert outcome.error == "本地配置或运行环境不完整"
    assert outcome.details["config_valid"] is False
    assert outcome.details["full_analysis_ready"] is False
    assert outcome.details["config_validation_errors"] == [
        {
            "severity": "error",
            "message": "未配置可用的 LLM 渠道",
            "field": "LLM_CHANNELS",
            "code": "missing_llm_channel",
        }
    ]
    assert len(outcome.details["config_validation_issues"]) == 2


def test_check_mode_keeps_warnings_visible_without_failing():
    config = _config()
    config.validate_structured = MagicMock(
        return_value=[
            SimpleNamespace(
                severity="warning",
                message="搜索增强未配置",
                field="TAVILY_API_KEY",
                code="",
            )
        ]
    )

    with patch("src.services.analyzer_service._module_available", return_value=True):
        outcome = run_stock_analysis("600519", mode="check", config=config)

    assert outcome.success is True
    assert outcome.details["config_valid"] is True
    assert outcome.details["config_validation_errors"] == []
    assert outcome.details["config_validation_issues"][0]["severity"] == "warning"


def test_check_mode_downgrades_errors_unrelated_to_explicit_no_notify_run():
    config = _config()
    config.validate_structured = MagicMock(
        return_value=[
            SimpleNamespace(
                severity="error",
                message="未配置 STOCK_LIST",
                field="STOCK_LIST",
                code="",
            ),
            SimpleNamespace(
                severity="error",
                message="Telegram 通知配置不完整",
                field="TELEGRAM_CHAT_ID",
                code="",
            ),
            SimpleNamespace(
                severity="error",
                message="通知时区配置无效",
                field="NOTIFICATION_TIMEZONE",
                code="",
            ),
        ]
    )

    with patch("src.services.analyzer_service._module_available", return_value=True):
        outcome = run_stock_analysis("600519", mode="check", config=config)

    assert outcome.success is True
    assert outcome.details["config_valid"] is True
    assert outcome.details["config_validation_errors"] == []
    assert {
        issue["field"]: issue["severity"]
        for issue in outcome.details["config_validation_issues"]
    } == {
        "STOCK_LIST": "warning",
        "TELEGRAM_CHAT_ID": "warning",
        "NOTIFICATION_TIMEZONE": "warning",
    }


def test_check_mode_keeps_notification_errors_blocking_when_requested():
    config = _config()
    config.validate_structured = MagicMock(
        return_value=[
            SimpleNamespace(
                severity="error",
                message="Telegram 通知配置不完整",
                field="TELEGRAM_CHAT_ID",
                code="",
            )
        ]
    )

    with patch("src.services.analyzer_service._module_available", return_value=True):
        outcome = run_stock_analysis(
            "600519",
            mode="check",
            config=config,
            notifier=object(),
        )

    assert outcome.success is False
    assert outcome.details["config_valid"] is False
    assert outcome.details["config_validation_errors"][0]["field"] == "TELEGRAM_CHAT_ID"


def test_check_mode_fails_when_selected_local_cli_is_missing():
    config = _config()
    config.generation_backend = "codex_cli"

    with patch(
        "src.services.analyzer_service._module_available",
        return_value=True,
    ), patch("src.llm.local_cli_backend.shutil.which", return_value=None):
        outcome = run_stock_analysis("600519", mode="check", config=config)

    assert outcome.success is False
    assert outcome.details["generation_backend"] == "codex_cli"
    assert outcome.details["generation_backend_ready"] is False
    assert outcome.details["generation_backend_config_error"]["error_code"] == "command_not_found"
    assert outcome.details["generation_backend_config_error"]["reason"] == "executable_not_found"


def test_check_mode_local_cli_does_not_require_litellm_runtime():
    config = _config()
    config.generation_backend = "codex_cli"

    with patch(
        "src.services.analyzer_service._module_available",
        side_effect=lambda module_name: module_name != "litellm",
    ), patch(
        "src.llm.local_cli_backend.shutil.which",
        return_value="/usr/local/bin/codex",
    ), patch("src.llm.local_cli_backend.os.access", return_value=True):
        outcome = run_stock_analysis("600519", mode="check", config=config)

    assert outcome.success is True
    assert outcome.details["llm_runtime_available"] is False
    assert outcome.details["generation_backend_ready"] is True
    assert outcome.details["generation_backend_config_error"] is None


def test_data_mode_fetches_only_without_analysis_or_notification():
    pipeline = MagicMock()
    pipeline.fetch_and_save_stock_data.return_value = (True, None)

    with patch("src.services.analyzer_service._build_pipeline", return_value=pipeline):
        outcome = run_stock_analysis(
            "600519",
            mode="data",
            config=_config(),
            force_refresh=True,
            notifier=object(),
        )

    pipeline.fetch_and_save_stock_data.assert_called_once_with("600519", force_refresh=True)
    pipeline.process_single_stock.assert_not_called()
    assert outcome.success is True
    assert outcome.network_allowed is True
    assert outcome.llm_allowed is False
    assert outcome.notification_allowed is False
    assert outcome.details == {"force_refresh": True, "data_ready": True}


def test_data_mode_keeps_fetch_error_visible():
    pipeline = MagicMock()
    pipeline.fetch_and_save_stock_data.return_value = (False, "provider unavailable")

    with patch("src.services.analyzer_service._build_pipeline", return_value=pipeline):
        outcome = run_stock_analysis("600519", mode="data", config=_config())

    assert outcome.success is False
    assert outcome.error == "provider unavailable"
    assert outcome.details["data_ready"] is False


def test_full_mode_preserves_pipeline_contract_and_explicit_notification():
    analysis = SimpleNamespace(success=True)
    pipeline = MagicMock()
    pipeline.process_single_stock.return_value = analysis
    notifier = object()

    with patch("src.services.analyzer_service._build_pipeline", return_value=pipeline):
        outcome = run_stock_analysis(
            "600519",
            mode="full",
            config=_config(),
            full_report=True,
            notifier=notifier,
        )

    assert pipeline.notifier is notifier
    pipeline.process_single_stock.assert_called_once_with(
        code="600519",
        skip_analysis=False,
        single_stock_notify=True,
        report_type=ReportType.FULL,
    )
    assert outcome.analysis is analysis
    assert outcome.success is True
    assert outcome.network_allowed is True
    assert outcome.llm_allowed is True
    assert outcome.notification_allowed is True


def test_legacy_analyze_stock_still_returns_analysis_result():
    analysis = object()
    outcome = StockAnalysisRunResult(
        stock_code="600519",
        mode=StockAnalysisMode.FULL,
        success=True,
        query_id="q1",
        analysis=analysis,
    )
    config = _config()
    notifier = object()

    with patch("src.services.analyzer_service.run_stock_analysis", return_value=outcome) as run:
        result = analyze_stock("600519", config, True, notifier)

    assert result is analysis
    run.assert_called_once_with(
        "600519",
        mode=StockAnalysisMode.FULL,
        config=config,
        full_report=True,
        notifier=notifier,
    )


def test_legacy_analyze_stocks_keeps_positional_per_stock_calls_and_filters_none():
    first = object()
    second = object()
    config = _config()
    notifier = object()

    with patch(
        "src.services.analyzer_service.analyze_stock",
        side_effect=[first, None, second],
    ) as analyze:
        results = analyze_stocks(["600519", "000001", "AAPL"], config, True, notifier)

    assert results == [first, second]
    assert analyze.call_args_list == [
        call("600519", config, True, notifier),
        call("000001", config, True, notifier),
        call("AAPL", config, True, notifier),
    ]


def test_blank_stock_code_fails_before_config_or_pipeline_loading():
    with patch("src.services.analyzer_service._resolve_config") as resolve_config, patch(
        "src.services.analyzer_service._build_pipeline"
    ) as build_pipeline:
        outcome = run_stock_analysis("  ", mode="full")

    resolve_config.assert_not_called()
    build_pipeline.assert_not_called()
    assert outcome.success is False
    assert outcome.error == "股票代码不能为空"
