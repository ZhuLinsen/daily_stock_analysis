# -*- coding: utf-8 -*-
"""Normalize decision-signal data quality inputs for reassess guardrails."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable, Literal


DecisionSignalDataQuality = Literal["high", "medium", "low", "poor", "unknown"]


_QUALITY_ALIASES: dict[str, DecisionSignalDataQuality] = {
    "high": "high",
    "good": "high",
    "medium": "medium",
    "usable": "medium",
    "ok": "medium",
    "fair": "medium",
    "low": "low",
    "limited": "low",
    "partial": "low",
    "degraded": "low",
    "stale": "low",
    "fallback": "low",
    "poor": "poor",
    "missing": "poor",
    "unavailable": "poor",
    "fetch_failed": "poor",
    "not_supported": "poor",
    "unknown": "unknown",
}

_QUALITY_SEVERITY: dict[DecisionSignalDataQuality, int] = {
    "unknown": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "poor": 4,
}


def normalize_decision_signal_data_quality(value: Any) -> DecisionSignalDataQuality:
    """Normalize explicit quality levels without inferring quality from completeness."""

    known_levels = [
        level
        for level in _explicit_quality_levels(value)
        if level != "unknown"
    ]
    if not known_levels:
        return "unknown"
    return max(known_levels, key=lambda level: _QUALITY_SEVERITY[level])


def _normalize_scalar(value: Any) -> DecisionSignalDataQuality:
    if value is None:
        return "unknown"
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return "unknown"
        return _QUALITY_ALIASES.get(text, "unknown")
    return "unknown"


def _explicit_quality_levels(value: Any) -> Iterable[DecisionSignalDataQuality]:
    scalar = _normalize_scalar(value)
    if scalar != "unknown":
        yield scalar
        return

    if not isinstance(value, Mapping):
        yield "unknown"
        return

    for key in ("level", "quality_level", "status", "data_quality", "quality"):
        if key in value:
            yield from _explicit_quality_levels(value.get(key))

    for key in ("quote", "daily_bars", "technical"):
        if key in value:
            yield from _explicit_quality_levels(value.get(key))

    overview = value.get("analysis_context_pack_overview")
    if isinstance(overview, Mapping):
        yield from _explicit_quality_levels(overview.get("data_quality"))
