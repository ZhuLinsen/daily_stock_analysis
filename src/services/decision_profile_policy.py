# -*- coding: utf-8 -*-
"""Minimal deterministic decision-profile policy for reassessment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.schemas.decision_action import DecisionAction
from src.services.decision_signal_data_quality import DecisionSignalDataQuality


MIN_ACTIONABLE_CONFIDENCE = 0.5
PROFILE_POLICY_VERSION = "decision-profile-v1"
SIGNAL_GENERATION_VERSION = "decision-profile-reassess-v1"
SCORING_VERSION = "decision-profile-scoring-v1"
PRICE_RELATIONSHIP_VIOLATION_CODES = frozenset(
    {
        "entry_range_invalid",
        "stop_loss_not_below_target_price",
        "stop_loss_not_below_entry_high",
        "target_price_not_above_entry_low",
    }
)


@dataclass(frozen=True)
class DecisionSignalCandidate:
    action: DecisionAction
    score: Optional[int] = None
    confidence: Optional[float] = None
    horizon: Optional[str] = None
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    invalidation: Optional[str] = None
    reason: Optional[str] = None
    risk_summary: Optional[str] = None
    watch_conditions: Optional[str] = None
    market_phase: Optional[str] = None


@dataclass(frozen=True)
class GuardrailResult:
    raw_action: DecisionAction
    final_action: DecisionAction
    passed: bool
    violations: list[str] = field(default_factory=list)
    adjustments: list[str] = field(default_factory=list)
    adjusted: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "raw_action": self.raw_action,
            "final_action": self.final_action,
            "passed": self.passed,
            "violations": list(self.violations),
            "adjustments": list(self.adjustments),
            "adjusted": self.adjusted,
        }


@dataclass(frozen=True)
class PolicyResult:
    candidate: DecisionSignalCandidate
    guardrail_result: GuardrailResult
    warnings: list[dict[str, object]]
    blocked_reason: Optional[str]
    scoring_breakdown: dict[str, object]


def apply_decision_profile_policy(
    candidate: DecisionSignalCandidate,
    *,
    decision_profile: str,
    data_quality_level: DecisionSignalDataQuality,
) -> PolicyResult:
    """Apply the minimal profile policy and guardrail to a snapshot candidate."""

    normalized_candidate = _apply_profile_bias(candidate, decision_profile)
    guardrail = _apply_guardrail(normalized_candidate, decision_profile, data_quality_level)
    final_candidate = _replace_action(normalized_candidate, guardrail.final_action)
    warnings = _warnings_for_guardrail(guardrail)
    blocked_reason = (
        "actionable_signal_blocked_by_guardrail"
        if not guardrail.passed
        else None
    )
    scoring_breakdown = {
        "raw_action": candidate.action,
        "final_action": guardrail.final_action,
        "decision_profile": decision_profile,
        "score": candidate.score,
        "confidence": candidate.confidence,
        "data_quality_level": data_quality_level,
        "policy": "minimal_deterministic",
    }
    return PolicyResult(
        candidate=final_candidate,
        guardrail_result=guardrail,
        warnings=warnings,
        blocked_reason=blocked_reason,
        scoring_breakdown=scoring_breakdown,
    )


def _apply_profile_bias(candidate: DecisionSignalCandidate, decision_profile: str) -> DecisionSignalCandidate:
    horizon = candidate.horizon
    if not horizon:
        horizon = "intraday" if candidate.action == "alert" or candidate.market_phase == "intraday" else "3d"
    return DecisionSignalCandidate(
        action=candidate.action,
        score=candidate.score,
        confidence=candidate.confidence,
        horizon=horizon,
        entry_low=candidate.entry_low,
        entry_high=candidate.entry_high,
        stop_loss=candidate.stop_loss,
        target_price=candidate.target_price,
        invalidation=candidate.invalidation,
        reason=candidate.reason,
        risk_summary=candidate.risk_summary,
        watch_conditions=candidate.watch_conditions,
        market_phase=candidate.market_phase,
    )


def _apply_guardrail(
    candidate: DecisionSignalCandidate,
    decision_profile: str,
    data_quality_level: DecisionSignalDataQuality,
) -> GuardrailResult:
    violations: list[str] = []
    adjustments: list[str] = []
    raw_action = candidate.action
    final_action = raw_action
    passed = True

    if raw_action in ("buy", "add"):
        if not candidate.horizon:
            violations.append("missing_horizon")
        if not candidate.invalidation and candidate.stop_loss is None:
            violations.append("missing_invalidation_or_stop_loss")
        if data_quality_level in ("poor", "unknown"):
            violations.append("insufficient_data_quality")
        if candidate.confidence is None:
            violations.append("missing_confidence")
        elif candidate.confidence < MIN_ACTIONABLE_CONFIDENCE:
            violations.append("confidence_below_actionable_threshold")
        if decision_profile == "aggressive" and not candidate.invalidation:
            violations.append("aggressive_missing_explicit_invalidation")
        if decision_profile == "aggressive" and candidate.horizon == "long":
            violations.append("aggressive_horizon_long_not_allowed")
        violations.extend(_price_violations(candidate))

    if raw_action in ("buy", "add") and violations:
        has_price_violation = any(code in PRICE_RELATIONSHIP_VIOLATION_CODES for code in violations)
        final_action = "alert" if has_price_violation else "watch"
        adjustments.append("action_downgraded_by_guardrail")
        # Missing confidence/invalidation or weak data can safely become a
        # non-actionable watch signal. Contradictory price relationships cannot
        # be persisted without changing the historical snapshot, so they stay
        # blocked even though preview still exposes an alert fallback.
        passed = not has_price_violation

    adjusted = raw_action != final_action or bool(adjustments)
    return GuardrailResult(
        raw_action=raw_action,
        final_action=final_action,
        passed=passed,
        violations=violations,
        adjustments=adjustments,
        adjusted=adjusted,
    )


def _price_violations(candidate: DecisionSignalCandidate) -> list[str]:
    violations: list[str] = []
    if (
        candidate.entry_low is not None
        and candidate.entry_high is not None
        and candidate.entry_low > candidate.entry_high
    ):
        violations.append("entry_range_invalid")
    if (
        candidate.stop_loss is not None
        and candidate.target_price is not None
        and candidate.stop_loss >= candidate.target_price
    ):
        violations.append("stop_loss_not_below_target_price")
    if (
        candidate.stop_loss is not None
        and candidate.entry_high is not None
        and candidate.stop_loss >= candidate.entry_high
    ):
        violations.append("stop_loss_not_below_entry_high")
    if (
        candidate.target_price is not None
        and candidate.entry_low is not None
        and candidate.target_price <= candidate.entry_low
    ):
        violations.append("target_price_not_above_entry_low")
    return violations


def _replace_action(candidate: DecisionSignalCandidate, action: DecisionAction) -> DecisionSignalCandidate:
    return DecisionSignalCandidate(
        action=action,
        score=candidate.score,
        confidence=candidate.confidence,
        horizon=candidate.horizon,
        entry_low=candidate.entry_low,
        entry_high=candidate.entry_high,
        stop_loss=candidate.stop_loss,
        target_price=candidate.target_price,
        invalidation=candidate.invalidation,
        reason=candidate.reason,
        risk_summary=candidate.risk_summary,
        watch_conditions=candidate.watch_conditions,
        market_phase=candidate.market_phase,
    )


def _warnings_for_guardrail(guardrail: GuardrailResult) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    if guardrail.adjusted:
        warnings.append(
            {
                "code": "action_adjusted_by_guardrail",
                "message": (
                    f"原始动作 {guardrail.raw_action} 已由风控调整为 "
                    f"{guardrail.final_action}。"
                ),
                "params": {
                    "raw_action": guardrail.raw_action,
                    "final_action": guardrail.final_action,
                },
            }
        )
    if not guardrail.passed:
        warnings.append(
            {
                "code": "action_blocked_by_guardrail",
                "message": "重评估结果未通过持久化风控，未保存为决策信号。",
                "params": {
                    "raw_action": guardrail.raw_action,
                    "final_action": guardrail.final_action,
                    "violations": list(guardrail.violations),
                },
            }
        )
    return warnings
