# -*- coding: utf-8 -*-
"""Startup and LLM log lines must describe what this run actually does."""
from types import SimpleNamespace

import pytest

import main
from src.analyzer import _describe_llm_result_model
from src.config import Config, ConfigIssue

_MISSING_STOCK_MESSAGE = "未配置 STOCK_LIST。请设置至少一个股票代码，例如：600519,hk00700,AAPL。"


def _config():
    issues = [
        ConfigIssue(severity="error", message=_MISSING_STOCK_MESSAGE, field="STOCK_LIST"),
        ConfigIssue(severity="warning", message="未配置通知渠道，将不发送推送通知", field="WECHAT_WEBHOOK_URL"),
        ConfigIssue(severity="error", message="no llm", field="LITELLM_MODEL"),
    ]
    return SimpleNamespace(validate_structured=lambda: issues)


def test_all_warnings_kept_without_overriding_args():
    args = SimpleNamespace(stocks=None, portfolio=None, no_notify=False)
    assert main._startup_config_warnings(_config(), args) == [
        _MISSING_STOCK_MESSAGE, "未配置通知渠道，将不发送推送通知", "no llm"
    ]


def test_cli_stocks_and_no_notify_resolve_their_warnings_only():
    args = SimpleNamespace(stocks="600519", portfolio=None, no_notify=True)
    assert main._startup_config_warnings(_config(), args) == ["no llm"]


def test_cli_overrides_filter_real_config_messages_without_mutating_config():
    config = Config(stock_list=[])
    original = config.validate()
    assert _MISSING_STOCK_MESSAGE in original
    assert "未配置通知渠道，将不发送推送通知" in original
    args = SimpleNamespace(stocks="600519", no_notify=True)
    assert main._startup_config_warnings(config, args) == [
        message for message in original
        if message not in (_MISSING_STOCK_MESSAGE, "未配置通知渠道，将不发送推送通知")
    ]
    assert config.validate() == original


def test_portfolio_resolves_missing_stock_list():
    args = SimpleNamespace(stocks=None, portfolio="futu", no_notify=False)
    assert main._startup_config_warnings(_config(), args) == ["未配置通知渠道，将不发送推送通知", "no llm"]


def test_cli_stocks_do_not_hide_other_stock_related_issues():
    config = SimpleNamespace(
        validate_structured=lambda: [
            ConfigIssue(severity="error", message=_MISSING_STOCK_MESSAGE, field="STOCK_LIST"),
            ConfigIssue(severity="warning", message="invalid stock group", field="STOCK_LIST"),
            ConfigIssue(
                severity="warning",
                message=f"{_MISSING_STOCK_MESSAGE} unrelated",
                field="STOCK_LIST",
            ),
        ]
    )
    args = SimpleNamespace(stocks="600519", portfolio=None, no_notify=False)
    assert main._startup_config_warnings(config, args) == [
        "invalid stock group",
        f"{_MISSING_STOCK_MESSAGE} unrelated",
    ]


def test_llm_log_names_fallback_model():
    assert _describe_llm_result_model("deepseek/deepseek-chat", "gemini/x", "gemini/x") == (
        "gemini/x（配置模型 deepseek/deepseek-chat，已回退）"
    )


def test_llm_log_unchanged_when_configured_model_answers():
    assert _describe_llm_result_model("gemini/x", "gemini/x") == "gemini/x"
    assert _describe_llm_result_model("gemini/x", None) == "gemini/x"


@pytest.mark.parametrize("configured, actual", [
    ("gemini/gemini-2.5-flash", "gemini-2.5-flash"),
    ("openai/gpt-4o", "gpt-4o-2024-08-06"),
])
def test_llm_log_does_not_call_normal_response_identity_a_fallback(configured, actual):
    assert _describe_llm_result_model(configured, actual, configured) == f"{actual}（配置模型 {configured}）"


def test_llm_log_distinguishes_alias_identity_from_route_fallback():
    assert _describe_llm_result_model("primary", "model-b", "primary") == "model-b（配置模型 primary）"
    assert "已回退" in _describe_llm_result_model("primary", "model-b", "backup")


def test_llm_log_marks_a_dated_model_when_it_is_an_explicit_fallback_route():
    assert "已回退" in _describe_llm_result_model(
        "openai/gpt-4o", "gpt-4o-2024-08-06", "openai/gpt-4o-2024-08-06",
    )


def test_llm_log_does_not_infer_fallback_without_route_evidence():
    assert _describe_llm_result_model("primary", "actual") == "actual（配置模型 primary）"
