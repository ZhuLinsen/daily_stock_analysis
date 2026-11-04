# -*- coding: utf-8 -*-
"""Minimal guardrail tests for apply_cross_asset_context_guardrail (Issue #1910).

Covers risk_off downgrade + exception-reason requirement, no-op for other
appetites, and idempotency with a previously-capped confidence (T11-T13
essentials). Full matrix is completed by the downstream W2-tests task.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.cross_asset_context_guardrail import apply_cross_asset_context_guardrail
from src.schemas.cross_asset_context import CrossAssetContext


def _result(*, confidence="高", advice="建议立即买入，回踩加仓", decision_type="buy"):
    return SimpleNamespace(
        decision_type=decision_type,
        operation_advice=advice,
        confidence_level=confidence,
        report_language="zh",
        dashboard={},
        sentiment_score=80,
    )


def _context(risk_appetite):
    return CrossAssetContext(market="cn", trade_date="2026-10-22", risk_appetite=risk_appetite)


class TestRiskOffCalibration:
    def test_downgrades_confidence_but_not_decision_type(self):
        result = _result()
        adjustments = apply_cross_asset_context_guardrail(
            result, cross_asset_context=_context("risk_off"), report_language="zh"
        )
        assert "confidence_capped_cross_asset_context" in adjustments
        assert result.confidence_level == "中"
        assert result.decision_type == "buy"  # never hard-blocks the decision
        phase_decision = result.dashboard["phase_decision"]
        assert "例外" in phase_decision["confidence_reason"]
        assert any("risk-off" in item for item in phase_decision["data_limitations"])

    def test_accepts_safe_dict_mapping(self):
        result = _result()
        safe = _context("risk_off").to_safe_dict()
        adjustments = apply_cross_asset_context_guardrail(
            result, cross_asset_context=safe, report_language="zh"
        )
        assert "confidence_capped_cross_asset_context" in adjustments

    @pytest.mark.parametrize("risk_appetite", ["risk_on", "neutral", "unknown"])
    def test_other_appetites_never_touch_result(self, risk_appetite):
        result = _result()
        adjustments = apply_cross_asset_context_guardrail(
            result, cross_asset_context=_context(risk_appetite), report_language="zh"
        )
        assert adjustments == []
        assert result.confidence_level == "高"
        assert result.dashboard == {}

    def test_non_aggressive_buy_untouched(self):
        result = _result(confidence="高", advice="建议观望，等待右侧信号", decision_type="hold")
        adjustments = apply_cross_asset_context_guardrail(
            result, cross_asset_context=_context("risk_off"), report_language="zh"
        )
        assert adjustments == []
        assert result.confidence_level == "高"


class TestIdempotency:
    def test_already_medium_confidence_only_registers_reason_once(self):
        result = _result(confidence="中")  # previous guardrail already capped it
        first = apply_cross_asset_context_guardrail(
            result, cross_asset_context=_context("risk_off"), report_language="zh"
        )
        assert "confidence_capped_cross_asset_context" not in first
        assert "cross_asset_context_exception_reason_registered" in first
        assert result.confidence_level == "中"  # no double-downgrade

        reason_after_first = result.dashboard["phase_decision"]["confidence_reason"]
        second = apply_cross_asset_context_guardrail(
            result, cross_asset_context=_context("risk_off"), report_language="zh"
        )
        assert second == []  # fully idempotent on second pass
        assert result.dashboard["phase_decision"]["confidence_reason"] == reason_after_first

    def test_none_context_is_noop(self):
        result = _result()
        assert apply_cross_asset_context_guardrail(result, cross_asset_context=None) == []
        assert result.confidence_level == "高"
