# -*- coding: utf-8 -*-
"""Tests for numeric grounding verifier, stop-loss risk-budget sizing, and structured_report."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("litellm", MagicMock())

from api.v1.schemas.history import AnalysisReport, ReportMeta, ReportStrategy, ReportSummary
from src.core.grounding_verifier import (
    compute_atr_position_sizing,
    compute_stop_loss_position_sizing,
    verify_and_normalize_levels,
)
from src.utils.sniper_points import parse_sniper_value


_NEGATIVE_PRICE_TEXTS = (
    "-1元", "止损：-1元", "止损: -1.5 元", "止损：-1（哨兵值）",
    "止损：-.5元", "止损：-.5（哨兵值）", "止损：-1e2元", "止损：-1e2（哨兵值）",
    "止损：−1元", "止损：－1元", "止损：- 1元",
    "止损：MA20 -1元", "止损：-1-2元",
)


@pytest.mark.parametrize("value", _NEGATIVE_PRICE_TEXTS)
def test_parse_sniper_value_rejects_negative_prices(value: str) -> None:
    assert parse_sniper_value(value) is None


@pytest.mark.parametrize("value", ["92-96元", "92 - 96元", "92 -96元", "92-96（MA20支撑）"])
def test_parse_sniper_value_preserves_positive_ranges(value: str) -> None:
    assert parse_sniper_value(value) == 96.0


@pytest.mark.parametrize(("value", "expected"), [("买入：.5元", 0.5), ("买入：1e2元", 100.0)])
def test_parse_sniper_value_preserves_decimal_and_exponent_prices(value: str, expected: float) -> None:
    assert parse_sniper_value(value) == expected


def test_verify_and_normalize_levels_valid_long_setup() -> None:
    strategy = {
        "ideal_buy": "100.00元",
        "secondary_buy": "95.00元",
        "stop_loss": "92.00元",
        "take_profit": "120.00元",
    }
    levels = verify_and_normalize_levels(strategy, current_price=102.0, action="buy")

    assert levels["ideal_buy"] == 100.0
    assert levels["secondary_buy"] == 95.0
    assert levels["stop_loss"] == 92.0
    assert levels["take_profit"] == 120.0
    assert levels["reference_price"] == 102.0
    assert levels["status"] == "active"
    assert levels["validation"] == "ok"
    assert levels["risk_reward_ratio"] == 2.5


def test_verify_and_normalize_levels_detects_conflict_on_buy_and_watch() -> None:
    buy_levels = verify_and_normalize_levels(
        {"ideal_buy": "100.0", "stop_loss": "105.0", "take_profit": "120.0"},
        current_price=101.0,
        action="buy",
    )
    assert buy_levels["status"] == "invalid"
    assert buy_levels["validation"] == "direction_conflict"
    assert buy_levels["risk_reward_ratio"] is None

    buy_pos = compute_stop_loss_position_sizing("buy", 80, buy_levels, data_quality_level="good")
    assert buy_pos["min_pct"] == 0
    assert buy_pos["max_pct"] == 0
    assert buy_pos["cap_reason"] == "direction_conflict"
    assert buy_pos["method"] == "stop_loss_risk_budget"

    watch_levels = verify_and_normalize_levels(
        {"ideal_buy": "100.0", "stop_loss": "105.0", "take_profit": "120.0"},
        current_price=101.0,
        action="watch",
    )
    assert watch_levels["status"] == "conditional_watch"
    assert watch_levels["validation"] == "direction_conflict"
    assert watch_levels["risk_reward_ratio"] is None


@pytest.mark.parametrize(
    "strategy",
    [
        {"ideal_buy": "100", "secondary_buy": "110", "stop_loss": "105", "take_profit": "120"},
        {"ideal_buy": "100", "secondary_buy": "90", "stop_loss": "95", "take_profit": "120"},
    ],
)
def test_verify_and_normalize_levels_preserves_entry_semantics_and_checks_secondary_buy(
    strategy: dict,
) -> None:
    levels = verify_and_normalize_levels(strategy, current_price=100.0, action="buy")

    assert levels["ideal_buy"] == 100.0
    assert levels["secondary_buy"] == float(strategy["secondary_buy"])
    assert levels["validation"] == "direction_conflict"
    assert levels["status"] == "invalid"
    assert levels["risk_reward_ratio"] is None
    position = compute_stop_loss_position_sizing("buy", 80, levels, data_quality_level="good")
    assert position["min_pct"] == position["max_pct"] == 0
    assert position["cap_reason"] == "direction_conflict"


def test_verify_and_normalize_levels_out_of_range_marks_invalid_and_zero_position() -> None:
    levels = verify_and_normalize_levels(
        {"ideal_buy": "60.0", "stop_loss": "55.0", "take_profit": "80.0"},
        current_price=100.0,
        action="buy",
    )

    assert levels["validation"] == "out_of_range"
    assert levels["status"] == "invalid"
    position = compute_stop_loss_position_sizing("buy", 80, levels, data_quality_level="good")
    assert position["min_pct"] == position["max_pct"] == 0
    assert position["cap_reason"] == "invalid_levels"


def test_compute_position_sizing_caps_and_non_offensive_zero() -> None:
    levels = {"reference_price": 100.0, "stop_loss": 96.0, "validation": "ok", "status": "active"}

    buy_pos = compute_atr_position_sizing("buy", 80, levels, data_quality_level="good")
    assert buy_pos["min_pct"] >= 5
    assert buy_pos["max_pct"] <= 35
    assert buy_pos["min_pct"] <= buy_pos["max_pct"]
    assert buy_pos["stop_distance_pct"] == 4.0

    limited_pos = compute_stop_loss_position_sizing("buy", 85, levels, data_quality_level="limited")
    assert limited_pos["max_pct"] <= 20
    assert limited_pos["cap_reason"] == "limited_data_quality"

    hold_pos = compute_stop_loss_position_sizing("hold", 80, levels, data_quality_level="good")
    assert hold_pos["min_pct"] == 0
    assert hold_pos["max_pct"] == 0
    assert hold_pos["cap_reason"] == "non_offensive_action"


def test_position_sizing_uses_planned_ideal_buy_when_it_differs_from_current_price() -> None:
    levels = verify_and_normalize_levels(
        {"ideal_buy": "105", "stop_loss": "96", "take_profit": "150"},
        current_price=100.0,
        action="buy",
    )

    position = compute_stop_loss_position_sizing("buy", 80, levels, data_quality_level="good")

    assert levels["reference_price"] == 100.0
    assert position["stop_distance_pct"] == 8.58
    assert position["max_pct"] == 13
    assert position["max_pct"] * position["stop_distance_pct"] / 100 <= position["risk_budget_pct"]


@pytest.mark.parametrize(
    "stop_loss",
    [None, True, False, 0.00001, "unparseable", "0", "-1", "NaN", "Infinity", *_NEGATIVE_PRICE_TEXTS],
)
def test_position_requires_a_valid_stop_loss(stop_loss) -> None:
    levels = verify_and_normalize_levels(
        {"ideal_buy": "100", "stop_loss": stop_loss, "take_profit": "120"},
        current_price=100.0,
        action="buy",
    )
    position = compute_stop_loss_position_sizing("buy", 80, levels, "good")

    assert levels["status"] == "conditional_watch"
    assert position["min_pct"] == position["max_pct"] == 0
    assert position["stop_distance_pct"] is None
    assert position["cap_reason"] == "invalid_stop_basis"


@pytest.mark.parametrize("stop_loss", _NEGATIVE_PRICE_TEXTS)
def test_analysis_report_negative_stop_has_zero_position(stop_loss: str) -> None:
    report = AnalysisReport(
        meta=ReportMeta(query_id="q-negative-stop", stock_code="600519", current_price=100.0),
        summary=ReportSummary(action="buy", sentiment_score=80),
        strategy=ReportStrategy(ideal_buy="100元", stop_loss=stop_loss, take_profit="120元"),
    )

    assert report.structured_report is not None
    metadata = report.structured_report.metadata
    assert metadata["levels"]["stop_loss"] is None
    assert metadata["levels"]["status"] == "conditional_watch"
    assert metadata["levels"]["risk_reward_ratio"] is None
    assert metadata["position"]["min_pct"] == metadata["position"]["max_pct"] == 0
    assert metadata["position"]["stop_distance_pct"] is None
    assert metadata["position"]["cap_reason"] == "invalid_stop_basis"


def test_subprecision_reference_price_does_not_crash_normalization() -> None:
    levels = verify_and_normalize_levels(
        {"ideal_buy": "100", "stop_loss": "92", "take_profit": "120"},
        current_price=0.00001,
        action="buy",
    )
    assert levels["reference_price"] == 100.0
    assert levels["validation"] == "ok"
    assert levels["status"] == "active"


@pytest.mark.parametrize(("stop_loss", "expected_max"), [(40.0, 2), (50.0, 2), (70.0, 4)])
def test_wide_stop_position_rounds_down_without_5pct_floor(stop_loss: float, expected_max: int) -> None:
    levels = verify_and_normalize_levels(
        {"ideal_buy": "100", "stop_loss": str(stop_loss), "take_profit": "160"},
        current_price=100.0,
        action="buy",
    )
    position = compute_stop_loss_position_sizing("buy", 80, levels, data_quality_level="good")

    assert position["min_pct"] == 0
    assert position["max_pct"] == expected_max
    assert position["max_pct"] * position["stop_distance_pct"] / 100 <= position["risk_budget_pct"]


def test_high_conviction_respects_risk_budget() -> None:
    position = compute_stop_loss_position_sizing(
        "buy", 100, {"reference_price": 100.0, "stop_loss": 96.0}, data_quality_level="good"
    )

    assert position["stop_distance_pct"] == 4.0
    assert position["max_pct"] == 30
    assert position["risk_budget_pct"] == 1.2


@pytest.mark.parametrize("action", ["buy", "add"])
@pytest.mark.parametrize("score", [40, 60, 80, 81, 100])
@pytest.mark.parametrize("quality", ["good", "limited", None])
@pytest.mark.parametrize("stop_loss", [0.01, 40.0, 70.0, 94.0, 95.8619, 96.0, 99.0])
def test_position_final_risk_bound(action: str, score: int, quality: str | None, stop_loss: float) -> None:
    position = compute_stop_loss_position_sizing(
        action,
        score,
        {"reference_price": 100.0, "stop_loss": stop_loss, "validation": "ok"},
        data_quality_level=quality,
    )

    assert 0 <= position["min_pct"] <= position["max_pct"] <= (20 if quality == "limited" else 35)
    assert position["max_pct"] * position["stop_distance_pct"] / 100 <= position["risk_budget_pct"]
    assert position["max_pct"] * (100.0 - stop_loss) / 100 <= position["risk_budget_pct"]


@pytest.mark.parametrize("score", [76, 100])
def test_analysis_report_auto_populates_structured_report(score: int) -> None:
    report = AnalysisReport(
        meta=ReportMeta(
            query_id="q-100",
            stock_code="600519",
            stock_name="贵州茅台",
            report_type="detailed",
            current_price=1680.0,
        ),
        summary=ReportSummary(
            analysis_summary="均线多头排列，回踩支撑位。",
            operation_advice="买入",
            action="buy",
            trend_prediction="看多",
            sentiment_score=score,
        ),
        strategy=ReportStrategy(
            ideal_buy="1660.0",
            secondary_buy="1620.0",
            stop_loss="1580.0",
            take_profit="1840.0",
        ),
    )

    assert report.structured_report is not None
    assert report.structured_report.schema_version == "research-artifact-v1"
    meta = report.structured_report.metadata
    assert meta["levels"]["ideal_buy"] == 1660.0
    assert meta["levels"]["status"] == "active"
    assert meta["levels"]["validation"] == "ok"
    position = meta["position"]
    assert position["max_pct"] >= 5
    assert position["max_pct"] * position["stop_distance_pct"] / 100 <= position["risk_budget_pct"]
