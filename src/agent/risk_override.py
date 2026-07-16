# -*- coding: utf-8 -*-
"""Shared risk override planning for the multi-agent pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from src.agent.protocols import AgentContext, normalize_decision_signal


_DOWNGRADE_STEPS = {
    "downgrade_one": 1,
    "downgrade_two": 2,
}


class DashboardDecisionSignal(str, Enum):
    """Canonical signals allowed in final dashboard decisions."""

    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"


class RiskTrigger(str, Enum):
    """Normalized risk-control trigger selected for one application."""

    NONE = "none"
    RISK_VETO = "risk_veto"
    RISK_DOWNGRADE = "risk_downgrade"


class RiskApplicationReason(str, Enum):
    """Exhaustive outcomes of evaluating a risk override against a final signal."""

    NO_RISK_EVIDENCE = "no_risk_evidence"
    NO_OVERRIDE_TRIGGER = "no_override_trigger"
    OVERRIDE_DISABLED = "override_disabled"
    FINAL_SIGNAL_ALREADY_WITHIN_RISK_LIMIT = "final_signal_already_within_risk_limit"
    RISK_VETO_APPLIED = "risk_veto_applied"
    RISK_DOWNGRADE_APPLIED = "risk_downgrade_applied"


_APPLIED_REASONS = frozenset({
    RiskApplicationReason.RISK_VETO_APPLIED,
    RiskApplicationReason.RISK_DOWNGRADE_APPLIED,
})
_VALID_DOWNGRADE_TRANSITIONS = frozenset({
    (DashboardDecisionSignal.BUY, DashboardDecisionSignal.HOLD),
    (DashboardDecisionSignal.BUY, DashboardDecisionSignal.SELL),
    (DashboardDecisionSignal.HOLD, DashboardDecisionSignal.SELL),
})


def classify_risk_application_reason(
    *,
    evidence_present: bool,
    trigger: RiskTrigger,
    override_enabled: bool,
    applied: bool,
) -> RiskApplicationReason:
    """Classify the final application reason from normalized runtime facts."""
    trigger = RiskTrigger(trigger)
    if not evidence_present:
        return RiskApplicationReason.NO_RISK_EVIDENCE
    if trigger == RiskTrigger.NONE:
        return RiskApplicationReason.NO_OVERRIDE_TRIGGER
    if not override_enabled:
        return RiskApplicationReason.OVERRIDE_DISABLED
    if not applied:
        return RiskApplicationReason.FINAL_SIGNAL_ALREADY_WITHIN_RISK_LIMIT
    if trigger == RiskTrigger.RISK_VETO:
        return RiskApplicationReason.RISK_VETO_APPLIED
    return RiskApplicationReason.RISK_DOWNGRADE_APPLIED


def validate_risk_application_transition(
    *,
    applied: bool,
    reason: RiskApplicationReason,
    final_signal: DashboardDecisionSignal,
    from_signal: Optional[DashboardDecisionSignal],
    to_signal: Optional[DashboardDecisionSignal],
) -> None:
    """Validate shared reason/transition invariants for runtime and schema models."""
    reason = RiskApplicationReason(reason)
    final_signal = DashboardDecisionSignal(final_signal)
    from_signal = DashboardDecisionSignal(from_signal) if from_signal is not None else None
    to_signal = DashboardDecisionSignal(to_signal) if to_signal is not None else None
    has_transition = from_signal is not None or to_signal is not None

    if not applied:
        if has_transition:
            raise ValueError("non-applied risk override cannot carry a signal transition")
        if reason in _APPLIED_REASONS:
            raise ValueError("applied reason requires applied=True")
        return

    if from_signal is None or to_signal is None:
        raise ValueError("applied risk override requires from_signal and to_signal")
    if from_signal == to_signal:
        raise ValueError("applied risk override must change the signal")
    if to_signal != final_signal:
        raise ValueError("to_signal must match final_signal")
    if reason == RiskApplicationReason.RISK_VETO_APPLIED:
        if (from_signal, to_signal) != (
            DashboardDecisionSignal.BUY,
            DashboardDecisionSignal.HOLD,
        ):
            raise ValueError("risk veto application must change buy to hold")
    elif reason == RiskApplicationReason.RISK_DOWNGRADE_APPLIED:
        if (from_signal, to_signal) not in _VALID_DOWNGRADE_TRANSITIONS:
            raise ValueError("risk downgrade must move to a more conservative signal")
    else:
        raise ValueError("applied risk override requires an applied reason")


@dataclass(frozen=True)
class RiskOverridePlan:
    """Configuration-aware risk override decision shared by summary and executor."""

    evidence_present: bool
    override_enabled: bool
    override_trigger_present: bool
    veto_buy: bool
    adjustment: str
    has_high_flag: bool
    risk_level_high: bool
    current_signal: Optional[str]
    target_signal: Optional[str]
    will_apply: Optional[bool]
    reason: str

    @property
    def trigger(self) -> RiskTrigger:
        """Return the effective trigger using the same precedence as execution."""
        if self.veto_buy and self.current_signal == DashboardDecisionSignal.BUY:
            return RiskTrigger.RISK_VETO
        if self.adjustment in _DOWNGRADE_STEPS:
            return RiskTrigger.RISK_DOWNGRADE
        if self.veto_buy:
            return RiskTrigger.RISK_VETO
        return RiskTrigger.NONE

    def to_low_sensitivity_dict(self) -> Dict[str, Any]:
        """Return a prompt-safe view that does not expose raw risk payloads."""
        return {
            "evidence_present": self.evidence_present,
            "override_enabled": self.override_enabled,
            "override_trigger_present": self.override_trigger_present,
            "veto_buy": self.veto_buy,
            "will_apply": self.will_apply,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RiskOverrideApplication:
    """Final, configuration-aware result of evaluating a risk override plan."""

    evidence_present: bool
    override_enabled: bool
    trigger: RiskTrigger
    applied: bool
    reason: RiskApplicationReason
    final_signal: DashboardDecisionSignal
    from_signal: Optional[DashboardDecisionSignal] = None
    to_signal: Optional[DashboardDecisionSignal] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "trigger", RiskTrigger(self.trigger))
        object.__setattr__(self, "reason", RiskApplicationReason(self.reason))
        object.__setattr__(
            self,
            "final_signal",
            DashboardDecisionSignal(self.final_signal),
        )
        if self.from_signal is not None:
            object.__setattr__(
                self,
                "from_signal",
                DashboardDecisionSignal(self.from_signal),
            )
        if self.to_signal is not None:
            object.__setattr__(
                self,
                "to_signal",
                DashboardDecisionSignal(self.to_signal),
            )

        if not self.evidence_present and self.trigger != RiskTrigger.NONE:
            raise ValueError("risk trigger requires risk evidence")
        expected_reason = classify_risk_application_reason(
            evidence_present=self.evidence_present,
            trigger=self.trigger,
            override_enabled=self.override_enabled,
            applied=self.applied,
        )
        if self.reason != expected_reason:
            raise ValueError(f"risk application reason must be {expected_reason.value} for the supplied facts")
        validate_risk_application_transition(
            applied=self.applied,
            reason=self.reason,
            final_signal=self.final_signal,
            from_signal=self.from_signal,
            to_signal=self.to_signal,
        )

    def to_risk_control_dict(self) -> Dict[str, Any]:
        """Return the complete low-sensitivity fact used by the public schema."""
        payload: Dict[str, Any] = {
            "evidence_present": self.evidence_present,
            "override_enabled": self.override_enabled,
            "trigger": self.trigger,
            "applied": self.applied,
            "reason": self.reason,
            "final_signal": self.final_signal,
        }
        if self.applied:
            payload["from_signal"] = self.from_signal
            payload["to_signal"] = self.to_signal
        return payload


def build_risk_override_application(plan: RiskOverridePlan) -> RiskOverrideApplication:
    """Build the final outcome for a plan that was evaluated against a signal."""
    if plan.current_signal is None or plan.target_signal is None or plan.will_apply is None:
        raise ValueError("risk override application requires an evaluated current signal")

    current_signal = DashboardDecisionSignal(plan.current_signal)
    target_signal = DashboardDecisionSignal(plan.target_signal)

    reason = classify_risk_application_reason(
        evidence_present=plan.evidence_present,
        trigger=plan.trigger,
        override_enabled=plan.override_enabled,
        applied=plan.will_apply,
    )

    if plan.will_apply:
        return RiskOverrideApplication(
            evidence_present=plan.evidence_present,
            override_enabled=plan.override_enabled,
            trigger=plan.trigger,
            applied=True,
            reason=reason,
            final_signal=target_signal,
            from_signal=current_signal,
            to_signal=target_signal,
        )
    return RiskOverrideApplication(
        evidence_present=plan.evidence_present,
        override_enabled=plan.override_enabled,
        trigger=plan.trigger,
        applied=False,
        reason=reason,
        final_signal=current_signal,
    )


def build_risk_override_plan(
    ctx: AgentContext,
    *,
    current_signal: Any = None,
    override_enabled: bool = True,
) -> RiskOverridePlan:
    """Build the single source of truth for risk override decisions.

    ``risk_level=high`` is risk evidence, but it is not by itself an override
    trigger. Actual execution also depends on ``override_enabled`` and on the
    final dashboard signal.
    """
    risk_raw = _latest_risk_raw(ctx)
    adjustment = str(risk_raw.get("signal_adjustment") or "").strip().lower()
    has_high_flag = any(
        str(flag.get("severity", "")).strip().lower() == "high"
        for flag in ctx.risk_flags
        if isinstance(flag, dict)
    )
    risk_level_high = str(risk_raw.get("risk_level") or "").strip().lower() == "high"
    veto_buy = bool(risk_raw.get("veto_buy")) or adjustment == "veto" or has_high_flag
    has_downgrade = adjustment in _DOWNGRADE_STEPS
    override_trigger_present = veto_buy or has_downgrade
    evidence_present = override_trigger_present or risk_level_high

    normalized_current = (
        normalize_decision_signal(current_signal)
        if isinstance(current_signal, str)
        else None
    )
    target_signal = normalized_current
    will_apply: Optional[bool]

    if normalized_current is None:
        will_apply = None
    elif not override_enabled or not override_trigger_present:
        will_apply = False
    else:
        if veto_buy and normalized_current == "buy":
            target_signal = "hold"
        elif has_downgrade:
            target_signal = _downgrade_signal(
                normalized_current,
                steps=_DOWNGRADE_STEPS[adjustment],
            )
        will_apply = target_signal != normalized_current

    return RiskOverridePlan(
        evidence_present=evidence_present,
        override_enabled=bool(override_enabled),
        override_trigger_present=override_trigger_present,
        veto_buy=veto_buy,
        adjustment=adjustment,
        has_high_flag=has_high_flag,
        risk_level_high=risk_level_high,
        current_signal=normalized_current,
        target_signal=target_signal,
        will_apply=will_apply,
        reason=_risk_override_reason(
            veto_buy=veto_buy,
            adjustment=adjustment,
            has_high_flag=has_high_flag,
            risk_level_high=risk_level_high,
        ),
    )


def _latest_risk_raw(ctx: AgentContext) -> Dict[str, Any]:
    risk_opinion = next((op for op in reversed(ctx.opinions) if op.agent_name == "risk"), None)
    if risk_opinion and isinstance(risk_opinion.raw_data, dict):
        return risk_opinion.raw_data
    return {}


def _risk_override_reason(
    *,
    veto_buy: bool,
    adjustment: str,
    has_high_flag: bool,
    risk_level_high: bool,
) -> str:
    if has_high_flag:
        return "high_severity_flag"
    if veto_buy:
        return "risk_veto"
    if adjustment in _DOWNGRADE_STEPS:
        return adjustment
    if risk_level_high:
        return "high_risk_evidence"
    return "none"


def _downgrade_signal(signal: str, steps: int = 1) -> str:
    order = ["buy", "hold", "sell"]
    try:
        index = order.index(signal)
    except ValueError:
        return signal
    return order[min(len(order) - 1, index + max(0, steps))]


__all__ = [
    "DashboardDecisionSignal",
    "RiskApplicationReason",
    "RiskOverrideApplication",
    "RiskOverridePlan",
    "RiskTrigger",
    "build_risk_override_application",
    "build_risk_override_plan",
    "classify_risk_application_reason",
    "validate_risk_application_transition",
]
