from __future__ import annotations

import pytest

from src.services.decision_signal_data_quality import normalize_decision_signal_data_quality


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"level": "good"}, "high"),
        ({"data_quality": {"level": "usable"}}, "medium"),
        ({"analysis_context_pack_overview": {"data_quality": {"level": "limited"}}}, "low"),
        ({"status": "fetch_failed"}, "poor"),
        ({"quote": "high", "daily_bars": "fetch_failed"}, "poor"),
        ({"level": "good", "technical": {"status": "degraded"}}, "low"),
        ({"not_quality": "good", "fields": ["many"]}, "unknown"),
        (None, "unknown"),
    ],
)
def test_normalize_decision_signal_data_quality_only_uses_explicit_quality(value, expected) -> None:
    assert normalize_decision_signal_data_quality(value) == expected


def test_normalize_decision_signal_data_quality_outputs_known_enum_values() -> None:
    values = [
        normalize_decision_signal_data_quality(value)
        for value in ("good", "usable", "partial", "poor", {"unknown": "shape"})
    ]

    assert set(values) <= {"high", "medium", "low", "poor", "unknown"}
