# -*- coding: utf-8 -*-
"""Tests for low-sensitive DecisionSignal summary helpers."""

from __future__ import annotations

from src.services.decision_signal_summary import (
    format_decision_signal_excerpt,
    summarize_decision_signal,
)


def test_summarize_decision_signal_keeps_only_low_sensitive_fields() -> None:
    summary = summarize_decision_signal({
        "id": 42,
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "market": "cn",
        "action": "sell",
        "action_label": "卖出",
        "horizon": "3d",
        "status": "active",
        "source_type": "alert",
        "source_agent": "alert_worker",
        "source_report_id": 88,
        "reason": "token=secret-value 触发止损",
        "watch_conditions": ["观察量能", "password=hidden"],
        "risk_summary": {"drawdown": "webhook=https://hooks.slack.com/services/T/B/C"},
        "created_at": "2026-06-18T10:00:00+08:00",
        "expires_at": "2026-06-25T10:00:00+08:00",
        "metadata": {"webhook_url": "https://hooks.slack.com/services/T/B/C"},
        "evidence": {"secret": "raw"},
        "diagnostics": "authorization=Bearer raw",
    })

    assert summary is not None
    assert set(summary) == {
        "id",
        "stock_code",
        "stock_name",
        "market",
        "action",
        "action_label",
        "horizon",
        "status",
        "source_type",
        "source_report_id",
        "reason",
        "watch_conditions",
        "risk_summary",
        "created_at",
        "expires_at",
    }
    assert summary["reason"] == "token=[REDACTED] 触发止损"
    assert summary["watch_conditions"] == ["观察量能", "password=[REDACTED]"]
    assert summary["risk_summary"] == {"drawdown": "webhook=[REDACTED_URL]"}


def test_summarize_decision_signal_rejects_non_dict_and_empty_payload() -> None:
    assert summarize_decision_signal(None) is None
    assert summarize_decision_signal(["not", "a", "dict"]) is None
    assert summarize_decision_signal({"metadata": {"token": "secret"}, "evidence": {"raw": True}}) is None
    assert summarize_decision_signal({"stock_code": "", "reason": None}) is None


def test_format_decision_signal_excerpt_formats_chinese_list_and_dict_fields() -> None:
    excerpt = format_decision_signal_excerpt({
        "action_label": "卖出",
        "horizon": "3d",
        "source_report_id": 88,
        "reason": "跌破止损线",
        "watch_conditions": ["观察 1660 支撑", "等待成交量收缩"],
        "risk_summary": {"drawdown": "组合回撤扩大"},
    })

    assert excerpt.startswith("**AI 决策信号**")
    assert "动作: 卖出 | 周期: 3d | 报告: #88" in excerpt
    assert "- 理由: 跌破止损线" in excerpt
    assert "- 观察条件: 观察 1660 支撑；等待成交量收缩" in excerpt
    assert "- 风险: drawdown: 组合回撤扩大" in excerpt


def test_format_decision_signal_excerpt_formats_english_and_redacts_text() -> None:
    excerpt = format_decision_signal_excerpt({
        "action": "alert",
        "horizon": "5d",
        "reason": "authorization: Bearer raw-token",
        "watch_conditions": "Check price",
        "risk_summary": "token=hidden",
    }, report_language="en")

    assert excerpt.startswith("**AI decision signal**")
    assert "Action: alert | Horizon: 5d" in excerpt
    assert "- Reason: authorization: [REDACTED]" in excerpt
    assert "- Watch: Check price" in excerpt
    assert "- Risk: token=[REDACTED]" in excerpt


def test_format_decision_signal_excerpt_preserves_complete_sanitized_reason() -> None:
    reason = (
        "159516当前处于中期震荡、短期调整阶段。技术面上，价格缩量回踩MA5，乖离率仅1.29%，"
        "具备洗盘结束的特征。然而，均线系统尚未形成标准多头排列，且大盘环境风险等级较高，"
        "压制了反弹空间。建议投资者保持谨慎，关注MA5支撑的有效性，切勿盲目追高。"
    )

    excerpt = format_decision_signal_excerpt({
        "reason": f"{reason} token=secret-value",
        "watch_conditions": "观察" * 80,
        "risk_summary": "风险" * 80,
    })

    assert f"- 理由: {reason} token=[REDACTED]" in excerpt
    assert "切勿盲目追高。" in excerpt
    watch_line = next(line for line in excerpt.splitlines() if line.startswith("- 观察条件: "))
    risk_line = next(line for line in excerpt.splitlines() if line.startswith("- 风险: "))
    assert len(watch_line.removeprefix("- 观察条件: ")) == 120
    assert len(risk_line.removeprefix("- 风险: ")) == 120


def test_format_decision_signal_excerpt_returns_empty_for_invalid_input() -> None:
    assert format_decision_signal_excerpt(None) == ""
    assert format_decision_signal_excerpt({}) == ""
    assert format_decision_signal_excerpt(["not", "a", "dict"]) == ""
