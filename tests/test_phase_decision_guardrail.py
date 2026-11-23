# -*- coding: utf-8 -*-
"""Tests for Issue #1386 P5 phase decision guardrails."""

from types import SimpleNamespace

from src.analyzer import AnalysisResult
from src.phase_decision_guardrail import apply_phase_decision_guardrails


def _result(**kwargs) -> AnalysisResult:
    defaults = {
        "code": "600519",
        "name": "贵州茅台",
        "trend_prediction": "看多",
        "sentiment_score": 76,
        "operation_advice": "立即买入",
        "decision_type": "buy",
        "confidence_level": "高",
        "analysis_summary": "盘中偏强",
        "dashboard": {
            "core_conclusion": {"one_sentence": "立即买入"},
            "phase_decision": {
                "action_window": "盘中跟踪",
                "immediate_action": "立即买入",
                "watch_conditions": ["放量突破"],
                "next_check_time": "14:30",
                "confidence_reason": "趋势偏强",
                "data_limitations": [],
            },
        },
    }
    defaults.update(kwargs)
    return AnalysisResult(**defaults)


def _phase(phase: str = "intraday") -> dict:
    return {
        "phase": phase,
        "market": "cn",
        "market_local_time": "2026-06-02T10:30:00+08:00",
        "is_trading_day": True,
        "is_market_open_now": phase == "intraday",
        "is_partial_bar": phase in {"intraday", "lunch_break", "closing_auction"},
        "warnings": ["calendar_unavailable"],
    }


def _overview(status: str = "stale") -> dict:
    return {
        "subject": {"code": "600519", "stock_name": "贵州茅台", "market": "cn"},
        "blocks": [
            {
                "key": "quote",
                "label": "行情",
                "status": status,
                "source": "tencent",
                "warnings": [],
                "missing_reasons": [],
            },
            {
                "key": "daily_bars",
                "label": "日线",
                "status": "available",
                "source": "akshare",
                "warnings": [],
                "missing_reasons": [],
            },
            {
                "key": "technical",
                "label": "技术",
                "status": "available",
                "source": "local",
                "warnings": [],
                "missing_reasons": [],
            },
        ],
        "data_quality": {
            "overall_score": 65,
            "level": "limited",
            "limitations": ["quote: stale"],
        },
    }


def test_degraded_core_data_caps_high_confidence_buy() -> None:
    result = _result()

    adjustments = apply_phase_decision_guardrails(
        result,
        market_phase_summary=_phase("intraday"),
        analysis_context_pack_overview=_overview("stale"),
        report_language="zh",
    )

    assert "confidence_capped_core_data_degraded" in adjustments
    assert result.confidence_level == "中"
    pd = result.dashboard["phase_decision"]
    assert pd["phase_context"]["phase"] == "intraday"
    assert "quote: stale" in pd["data_limitations"]
    assert "核心行情" in pd["confidence_reason"]


def test_degraded_core_data_caps_high_confidence_hold_advice() -> None:
    result = _result(
        operation_advice="暂不加仓，观望",
        decision_type="hold",
        confidence_level="高",
        dashboard={
            "core_conclusion": {"one_sentence": "暂不加仓，观望"},
            "phase_decision": {
                "action_window": "盘中跟踪",
                "immediate_action": "暂不加仓，观望",
                "watch_conditions": ["放量突破"],
                "next_check_time": "14:30",
                "confidence_reason": "趋势未确认",
                "data_limitations": [],
            },
        },
    )

    adjustments = apply_phase_decision_guardrails(
        result,
        market_phase_summary=_phase("intraday"),
        analysis_context_pack_overview=_overview("stale"),
        report_language="zh",
    )

    assert "confidence_capped_core_data_degraded" in adjustments
    assert result.confidence_level == "中"
    assert "核心行情" in result.dashboard["phase_decision"]["confidence_reason"]
    assert "quote: stale" in result.dashboard["phase_decision"]["data_limitations"]


def test_premarket_high_confidence_immediate_action_is_conservative() -> None:
    result = _result()

    adjustments = apply_phase_decision_guardrails(
        result,
        market_phase_summary=_phase("premarket"),
        analysis_context_pack_overview=_overview("available"),
        report_language="zh",
    )

    assert "confidence_capped_non_intraday_action" in adjustments
    assert result.confidence_level == "低"
    assert result.dashboard["phase_decision"]["immediate_action"] == "等待盘中确认，禁止追高。"


def test_premarket_medium_confidence_immediate_action_rewrites_action_only() -> None:
    result = _result(
        operation_advice="Hold unless confirmed",
        decision_type="hold",
        confidence_level="Medium",
        report_language="en",
        dashboard={
            "core_conclusion": {"one_sentence": "Wait"},
            "phase_decision": {
                "action_window": "Premarket plan",
                "immediate_action": "buy now",
                "watch_conditions": ["breakout with volume"],
                "next_check_time": "market open",
                "confidence_reason": "Setup is forming",
                "data_limitations": [],
            },
        },
    )

    adjustments = apply_phase_decision_guardrails(
        result,
        market_phase_summary=_phase("premarket"),
        analysis_context_pack_overview=_overview("available"),
        report_language="en",
    )

    assert "non_intraday_action_adjusted" in adjustments
    assert "confidence_capped_non_intraday_action" not in adjustments
    assert result.confidence_level == "Medium"
    assert result.dashboard["phase_decision"]["immediate_action"] == (
        "Wait for intraday confirmation; do not chase."
    )
    assert "buy now" not in result.dashboard["phase_decision"]["immediate_action"].lower()


def test_unknown_low_confidence_immediate_action_rewrites_action_only() -> None:
    result = _result(
        operation_advice="观察为主",
        decision_type="hold",
        confidence_level="低",
        dashboard={
            "core_conclusion": {"one_sentence": "观察为主"},
            "phase_decision": {
                "action_window": "未知阶段观察",
                "immediate_action": "立即买入",
                "watch_conditions": ["确认开市状态"],
                "next_check_time": "阶段确认后",
                "confidence_reason": "阶段未知",
                "data_limitations": [],
            },
        },
    )

    adjustments = apply_phase_decision_guardrails(
        result,
        market_phase_summary=_phase("unknown"),
        analysis_context_pack_overview=_overview("available"),
        report_language="zh",
    )

    assert "non_intraday_action_adjusted" in adjustments
    assert "confidence_capped_non_intraday_action" not in adjustments
    assert result.confidence_level == "低"
    assert result.dashboard["phase_decision"]["immediate_action"] == "等待盘中确认，禁止追高。"


def test_premarket_degraded_immediate_action_uses_strongest_cap() -> None:
    result = _result()

    adjustments = apply_phase_decision_guardrails(
        result,
        market_phase_summary=_phase("premarket"),
        analysis_context_pack_overview=_overview("stale"),
        report_language="zh",
    )

    assert "confidence_capped_core_data_degraded" in adjustments
    assert "confidence_capped_non_intraday_action" in adjustments
    assert result.confidence_level == "低"
    assert result.dashboard["phase_decision"]["immediate_action"] == "等待盘中确认，禁止追高。"


def test_intraday_postmarket_recap_wording_is_adjusted_in_zh_and_en() -> None:
    zh_result = _result(
        operation_advice="今日收盘后复盘显示可买入",
        analysis_summary="明日重点关注突破",
        dashboard={
            "core_conclusion": {"one_sentence": "今日收盘后复盘显示偏强"},
            "phase_decision": {"immediate_action": "明日重点关注突破", "watch_conditions": []},
        },
    )

    zh_adjustments = apply_phase_decision_guardrails(
        zh_result,
        market_phase_summary=_phase("intraday"),
        analysis_context_pack_overview=_overview("available"),
        report_language="zh",
    )

    assert "postmarket_recap_wording_adjusted" in zh_adjustments
    assert "今日收盘后" not in zh_result.dashboard["core_conclusion"]["one_sentence"]
    assert "明日重点" not in zh_result.analysis_summary

    en_result = _result(
        operation_advice="Buy after today's close",
        analysis_summary="Focus tomorrow on the breakout",
        confidence_level="High",
        report_language="en",
        dashboard={
            "core_conclusion": {"one_sentence": "After today's close, buy"},
            "phase_decision": {"immediate_action": "focus tomorrow", "watch_conditions": []},
        },
    )

    en_adjustments = apply_phase_decision_guardrails(
        en_result,
        market_phase_summary=_phase("intraday"),
        analysis_context_pack_overview=_overview("available"),
        report_language="en",
    )

    assert "postmarket_recap_wording_adjusted" in en_adjustments
    assert "after today's close" not in en_result.dashboard["core_conclusion"]["one_sentence"].lower()
    assert "focus tomorrow" not in en_result.analysis_summary.lower()


def test_postmarket_recap_and_missing_inputs_are_fail_open() -> None:
    postmarket = _result(
        operation_advice="今日收盘后复盘显示可持有",
        dashboard={
            "core_conclusion": {"one_sentence": "今日收盘后复盘显示可持有"},
            "phase_decision": {"watch_conditions": ["不破支撑"]},
        },
    )

    adjustments = apply_phase_decision_guardrails(
        postmarket,
        market_phase_summary=_phase("postmarket"),
        analysis_context_pack_overview=None,
        report_language="zh",
    )

    assert adjustments == []
    assert "今日收盘后" in postmarket.dashboard["core_conclusion"]["one_sentence"]
    assert postmarket.dashboard["phase_decision"]["watch_conditions"] == ["不破支撑"]

    missing = _result(dashboard={})
    adjustments = apply_phase_decision_guardrails(
        missing,
        market_phase_summary=None,
        analysis_context_pack_overview=None,
        report_language="zh",
    )

    assert adjustments == []
    assert missing.dashboard["phase_decision"]["watch_conditions"] == []
    assert missing.dashboard["phase_decision"]["data_limitations"] == []


def test_guardrail_creates_dashboard_for_agent_compatible_result_object() -> None:
    result = SimpleNamespace(
        confidence_level="高",
        decision_type="hold",
        operation_advice="持有",
        analysis_summary="测试摘要",
    )

    adjustments = apply_phase_decision_guardrails(
        result,
        market_phase_summary=_phase("intraday"),
        analysis_context_pack_overview=_overview("available"),
        report_language="zh",
    )

    assert adjustments == []
    assert result.dashboard["phase_decision"]["phase_context"]["phase"] == "intraday"
    assert result.dashboard["phase_decision"]["watch_conditions"] == []
