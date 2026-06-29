from __future__ import annotations

import pytest

from src.services.sentiment_review_calculator import (
    auction_stats,
    broken_board_rate,
    classify_emotion,
    empirical_percentile,
    promotion_rates,
    safe_ratio,
    weighted_theme_strength,
)


def test_reference_day_formulas() -> None:
    assert safe_ratio(35523, 35942, subtract_one=True) == pytest.approx(-0.01165767)
    assert promotion_rates(
        today={1: 52, 2: 4, 3: 2, 4: 1, 6: 1},
        previous={1: 69, 2: 14, 3: 1, 5: 1},
    ) == pytest.approx({"second": 4 / 69, "third": 2 / 14, "fourth_plus": 1.0})


def test_zero_denominator_and_missing_samples_are_null() -> None:
    assert safe_ratio(2, 0) is None
    assert broken_board_rate(limit_up_count=0, broken_count=0) is None
    assert auction_stats([0.01]) == {"median": 0.01, "stdev": None, "sample_count": 1}


def test_empirical_percentile_requires_twenty_samples() -> None:
    assert empirical_percentile(list(range(19)), 5, min_samples=20) is None
    assert empirical_percentile(list(range(30)), 1, min_samples=20) == pytest.approx(2 / 30)


def test_weighted_theme_strength_uses_linear_recency_weights() -> None:
    assert weighted_theme_strength([1, 2, 3]) == pytest.approx((1 * 1 + 2 * 2 + 3 * 3) / 6)


def test_emotion_classification_is_rule_based() -> None:
    assert classify_emotion(0.067, -3639) == "deep_ice"
    assert classify_emotion(0.15, -1200) == "ice"
    assert classify_emotion(0.95, 2200) == "climax"
    assert classify_emotion(None, -3639) is None
