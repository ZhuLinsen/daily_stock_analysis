from __future__ import annotations

from src.services.decision_profile_policy import DecisionSignalCandidate, apply_decision_profile_policy


def test_policy_keeps_valid_snapshot_action_without_profile_upgrade() -> None:
    result = apply_decision_profile_policy(
        DecisionSignalCandidate(
            action="hold",
            score=52,
            confidence=0.6,
            horizon=None,
            market_phase=None,
        ),
        decision_profile="aggressive",
        data_quality_level="medium",
    )

    assert result.candidate.action == "hold"
    assert result.candidate.horizon == "3d"
    assert result.guardrail_result.passed is True
    assert result.guardrail_result.adjusted is False


def test_policy_safely_downgrades_buy_with_missing_confidence() -> None:
    result = apply_decision_profile_policy(
        DecisionSignalCandidate(
            action="buy",
            score=70,
            confidence=None,
            horizon="3d",
            stop_loss=10,
            target_price=15,
        ),
        decision_profile="balanced",
        data_quality_level="medium",
    )

    assert result.guardrail_result.raw_action == "buy"
    assert result.guardrail_result.final_action == "watch"
    assert result.candidate.action == "watch"
    assert result.guardrail_result.passed is True
    assert result.guardrail_result.adjusted is True
    assert "missing_confidence" in result.guardrail_result.violations
    assert result.guardrail_result.adjustments
    assert result.blocked_reason is None
    assert {warning["code"] for warning in result.warnings} == {"action_adjusted_by_guardrail"}
    assert all(warning.get("message") for warning in result.warnings)


def test_policy_requires_explicit_invalidation_for_aggressive_buy() -> None:
    result = apply_decision_profile_policy(
        DecisionSignalCandidate(
            action="buy",
            score=70,
            confidence=0.7,
            horizon="3d",
            stop_loss=10,
            target_price=15,
        ),
        decision_profile="aggressive",
        data_quality_level="medium",
    )

    assert result.candidate.action == "watch"
    assert "aggressive_missing_explicit_invalidation" in result.guardrail_result.violations


def test_policy_blocks_aggressive_buy_with_long_horizon_without_silent_cap() -> None:
    result = apply_decision_profile_policy(
        DecisionSignalCandidate(
            action="buy",
            confidence=0.7,
            horizon="long",
            invalidation="跌破趋势线",
            stop_loss=10,
            target_price=15,
        ),
        decision_profile="aggressive",
        data_quality_level="medium",
    )

    assert result.candidate.action == "watch"
    assert result.candidate.horizon == "long"
    assert "aggressive_horizon_long_not_allowed" in result.guardrail_result.violations


def test_policy_records_price_relationship_violations() -> None:
    result = apply_decision_profile_policy(
        DecisionSignalCandidate(
            action="add",
            confidence=0.7,
            horizon="3d",
            invalidation="跌破趋势线",
            entry_low=20,
            entry_high=18,
            stop_loss=19,
            target_price=17,
        ),
        decision_profile="balanced",
        data_quality_level="medium",
    )

    assert result.guardrail_result.final_action == "alert"
    assert result.guardrail_result.adjusted is True
    assert result.guardrail_result.passed is False
    assert "entry_range_invalid" in result.guardrail_result.violations
    assert "stop_loss_not_below_target_price" in result.guardrail_result.violations
    assert result.blocked_reason
    assert {warning["code"] for warning in result.warnings} == {
        "action_adjusted_by_guardrail",
        "action_blocked_by_guardrail",
    }
    assert all(warning.get("message") for warning in result.warnings)
