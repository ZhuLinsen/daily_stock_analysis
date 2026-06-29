# -*- coding: utf-8 -*-
"""Pure deterministic calculations for post-close sentiment reviews."""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from typing import Optional


def safe_ratio(
    numerator: float,
    denominator: float,
    *,
    subtract_one: bool = False,
) -> Optional[float]:
    if denominator == 0:
        return None
    value = numerator / denominator
    return value - 1 if subtract_one else value


def promotion_rates(
    today: Mapping[int, int],
    previous: Mapping[int, int],
) -> dict[str, Optional[float]]:
    today_fourth_plus = sum(count for board, count in today.items() if board >= 4)
    previous_third_plus = sum(count for board, count in previous.items() if board >= 3)
    return {
        "second": safe_ratio(today.get(2, 0), previous.get(1, 0)),
        "third": safe_ratio(today.get(3, 0), previous.get(2, 0)),
        "fourth_plus": safe_ratio(today_fourth_plus, previous_third_plus),
    }


def broken_board_rate(limit_up_count: int, broken_count: int) -> Optional[float]:
    return safe_ratio(broken_count, limit_up_count + broken_count)


def auction_stats(values: Sequence[float]) -> dict[str, Optional[float] | int]:
    clean = [float(value) for value in values]
    if not clean:
        return {"median": None, "stdev": None, "sample_count": 0}
    return {
        "median": statistics.median(clean),
        "stdev": statistics.stdev(clean) if len(clean) >= 2 else None,
        "sample_count": len(clean),
    }


def empirical_percentile(
    values: Sequence[float],
    current: float,
    *,
    min_samples: int = 20,
) -> Optional[float]:
    clean = [float(value) for value in values]
    if len(clean) < min_samples:
        return None
    return sum(value <= current for value in clean) / len(clean)


def weighted_theme_strength(counts: Sequence[float]) -> Optional[float]:
    if not counts:
        return None
    weights = list(range(1, len(counts) + 1))
    return sum(float(value) * weight for value, weight in zip(counts, weights)) / sum(weights)


def classify_emotion(
    percentile: Optional[float],
    breadth_delta: Optional[int],
) -> Optional[str]:
    if percentile is None or breadth_delta is None:
        return None
    if percentile <= 0.10:
        return "deep_ice"
    if percentile <= 0.20:
        return "ice"
    if percentile >= 0.90:
        return "climax"
    if breadth_delta > 1000:
        return "strong"
    if breadth_delta < -1000:
        return "weak"
    return "neutral"
