from datetime import datetime
from types import SimpleNamespace

from src.services.history_comparison_service import _record_to_signal


def _record(**overrides):
    values = {
        "created_at": datetime(2026, 7, 11, 9, 0),
        "query_id": "q1",
        "sentiment_score": 72,
        "operation_advice": "Hold",
        "trend_prediction": "Bullish",
        "report_type": "stock",
        "report_language": "en",
        "raw_result": "{}",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_history_signal_uses_score_aligned_display_action() -> None:
    signal = _record_to_signal(_record(), report_language="en")

    assert signal["action"] == "buy"
    assert signal["action_label"] == "Buy"


def test_history_signal_preserves_applied_guardrail() -> None:
    signal = _record_to_signal(
        _record(
            raw_result=(
                '{"action":"hold","dashboard":{"decision_stability":'
                '{"applied":true,"reason":"Wait for confirmation"}}}'
            )
        ),
        report_language="en",
    )

    assert signal["action"] == "hold"
    assert signal["action_label"] == "Hold"
