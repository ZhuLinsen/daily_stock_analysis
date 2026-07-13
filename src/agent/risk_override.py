# -*- coding: utf-8 -*-
"""Shared risk override planning for the multi-agent pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, FrozenSet, Literal, Mapping, Optional, Tuple, cast

from src.agent.protocols import AgentContext, normalize_decision_signal


_DOWNGRADE_STEPS = {
    "downgrade_one": 1,
    "downgrade_two": 2,
}

RiskControlSignal = Literal["buy", "hold", "sell"]
RiskControlTrigger = Literal["none", "risk_veto", "risk_downgrade", "high_risk_evidence"]
RiskControlPlannedAction = Literal["none", "cap_buy_to_hold", "downgrade"]
RiskControlNotAppliedReason = Literal[
    "none",
    "override_disabled",
    "no_trigger",
    "final_signal_already_within_risk_limit",
]
RiskControlAppliedReason = Literal[
    "risk_veto",
    "downgrade_one",
    "downgrade_two",
    "high_severity_flag",
]
RiskOverrideAdjustment = Literal["veto", "downgrade_one", "downgrade_two"]


class RiskControlState(str, Enum):
    """Finite final states exposed by ``risk_control``."""

    NO_EVIDENCE = "no_evidence"
    EVIDENCE_WITHOUT_OVERRIDE_TRIGGER = "evidence_without_override_trigger"
    VETO_DISABLED = "veto_disabled"
    DOWNGRADE_DISABLED = "downgrade_disabled"
    VETO_WITHIN_LIMIT = "veto_within_limit"
    DOWNGRADE_WITHIN_LIMIT = "downgrade_within_limit"
    VETO_APPLIED = "veto_applied"
    DOWNGRADE_ONE_APPLIED = "downgrade_one_applied"
    DOWNGRADE_TWO_APPLIED = "downgrade_two_applied"


class RiskControlPayloadShape(str, Enum):
    SNAPSHOT = "snapshot"
    TRANSITION = "transition"


@dataclass(frozen=True)
class RiskControlStateFacts:
    """Minimal discriminators used by every finite-state derivation."""

    applied: bool
    evidence_present: bool
    trigger: RiskControlTrigger
    override_enabled: bool
    reason: Optional[RiskControlAppliedReason]


@dataclass(frozen=True)
class RiskControlPayload:
    """Typed low-sensitivity payload validated against a finite state spec."""

    evidence_present: bool
    trigger: RiskControlTrigger
    planned_action: RiskControlPlannedAction
    applied: bool
    not_applied_reason: RiskControlNotAppliedReason
    override_enabled: bool
    from_signal: Optional[RiskControlSignal] = None
    to_signal: Optional[RiskControlSignal] = None
    reason: Optional[RiskControlAppliedReason] = None
    current: Optional[RiskControlSignal] = None
    target: Optional[RiskControlSignal] = None

    def to_public_dict(self) -> Dict[str, object]:
        payload = {
            "evidence_present": self.evidence_present,
            "trigger": self.trigger,
            "planned_action": self.planned_action,
            "applied": self.applied,
            "not_applied_reason": self.not_applied_reason,
            "override_enabled": self.override_enabled,
            "from": self.from_signal,
            "to": self.to_signal,
            "reason": self.reason,
            "current": self.current,
            "target": self.target,
        }
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True)
class RiskControlStateSpec:
    """Canonical fields and dynamic-field rules for one finite state."""

    state: RiskControlState
    evidence_present: bool
    trigger: RiskControlTrigger
    planned_action: RiskControlPlannedAction
    applied: bool
    not_applied_reason: RiskControlNotAppliedReason
    allowed_override_enabled: FrozenSet[bool]
    payload_shape: RiskControlPayloadShape
    allowed_reasons: FrozenSet[RiskControlAppliedReason] = frozenset()
    allowed_transitions: FrozenSet[Tuple[RiskControlSignal, RiskControlSignal]] = frozenset()
    application_adjustment: Optional[RiskOverrideAdjustment] = None

    def matches(self, facts: RiskControlStateFacts) -> bool:
        """Return whether normalized facts identify this state."""
        fixed_fields_match = (
            facts.applied == self.applied
            and facts.evidence_present == self.evidence_present
            and facts.trigger == self.trigger
            and facts.override_enabled in self.allowed_override_enabled
        )
        if not fixed_fields_match:
            return False
        if self.payload_shape == RiskControlPayloadShape.TRANSITION:
            return facts.reason in self.allowed_reasons
        return facts.reason is None

    def build_payload(
        self,
        *,
        override_enabled: bool,
        from_signal: Optional[RiskControlSignal] = None,
        to_signal: Optional[RiskControlSignal] = None,
        reason: Optional[RiskControlAppliedReason] = None,
        current: Optional[RiskControlSignal] = None,
        target: Optional[RiskControlSignal] = None,
    ) -> RiskControlPayload:
        payload = RiskControlPayload(
            evidence_present=self.evidence_present,
            trigger=self.trigger,
            planned_action=self.planned_action,
            applied=self.applied,
            not_applied_reason=self.not_applied_reason,
            override_enabled=override_enabled,
            from_signal=from_signal,
            to_signal=to_signal,
            reason=reason,
            current=current,
            target=target,
        )
        self.validate(payload)
        return payload

    def validate(self, payload: RiskControlPayload) -> None:
        errors = []
        expected_fields = {
            "evidence_present": self.evidence_present,
            "trigger": self.trigger,
            "planned_action": self.planned_action,
            "applied": self.applied,
            "not_applied_reason": self.not_applied_reason,
        }
        for field_name, expected in expected_fields.items():
            actual = getattr(payload, field_name)
            if actual != expected:
                errors.append(f"{field_name}={actual!r}, expected {expected!r}")
        if payload.override_enabled not in self.allowed_override_enabled:
            errors.append(
                f"override_enabled={payload.override_enabled!r}, expected one of "
                f"{sorted(self.allowed_override_enabled)!r}"
            )

        if self.payload_shape == RiskControlPayloadShape.TRANSITION:
            if payload.from_signal is None or payload.to_signal is None or payload.reason is None:
                errors.append("applied state requires from, to, and reason")
            if payload.current is not None or payload.target is not None:
                errors.append("applied state forbids current and target")
            if payload.reason is not None and payload.reason not in self.allowed_reasons:
                errors.append(f"reason={payload.reason!r} is not allowed")
            transition = (payload.from_signal, payload.to_signal)
            if None not in transition and transition not in self.allowed_transitions:
                errors.append(
                    f"transition {payload.from_signal!r}->{payload.to_signal!r} is not allowed"
                )
        else:
            if payload.from_signal is not None or payload.to_signal is not None or payload.reason is not None:
                errors.append("non-applied state forbids from, to, and reason")
            if (payload.current is None) != (payload.target is None):
                errors.append("non-applied state requires current and target together")
            if payload.current is not None and payload.current != payload.target:
                errors.append("non-applied state requires current and target to match")

        if errors:
            raise ValueError(
                f"risk_control state={self.state.value!r} conflicts: " + "; ".join(errors)
            )


RISK_CONTROL_STATE_SPECS: Mapping[RiskControlState, RiskControlStateSpec] = MappingProxyType({
    RiskControlState.NO_EVIDENCE: RiskControlStateSpec(
        state=RiskControlState.NO_EVIDENCE,
        evidence_present=False,
        trigger="none",
        planned_action="none",
        applied=False,
        not_applied_reason="none",
        allowed_override_enabled=frozenset({False, True}),
        payload_shape=RiskControlPayloadShape.SNAPSHOT,
    ),
    RiskControlState.EVIDENCE_WITHOUT_OVERRIDE_TRIGGER: RiskControlStateSpec(
        state=RiskControlState.EVIDENCE_WITHOUT_OVERRIDE_TRIGGER,
        evidence_present=True,
        trigger="high_risk_evidence",
        planned_action="none",
        applied=False,
        not_applied_reason="no_trigger",
        allowed_override_enabled=frozenset({False, True}),
        payload_shape=RiskControlPayloadShape.SNAPSHOT,
    ),
    RiskControlState.VETO_DISABLED: RiskControlStateSpec(
        state=RiskControlState.VETO_DISABLED,
        evidence_present=True,
        trigger="risk_veto",
        planned_action="cap_buy_to_hold",
        applied=False,
        not_applied_reason="override_disabled",
        allowed_override_enabled=frozenset({False}),
        payload_shape=RiskControlPayloadShape.SNAPSHOT,
    ),
    RiskControlState.DOWNGRADE_DISABLED: RiskControlStateSpec(
        state=RiskControlState.DOWNGRADE_DISABLED,
        evidence_present=True,
        trigger="risk_downgrade",
        planned_action="downgrade",
        applied=False,
        not_applied_reason="override_disabled",
        allowed_override_enabled=frozenset({False}),
        payload_shape=RiskControlPayloadShape.SNAPSHOT,
    ),
    RiskControlState.VETO_WITHIN_LIMIT: RiskControlStateSpec(
        state=RiskControlState.VETO_WITHIN_LIMIT,
        evidence_present=True,
        trigger="risk_veto",
        planned_action="cap_buy_to_hold",
        applied=False,
        not_applied_reason="final_signal_already_within_risk_limit",
        allowed_override_enabled=frozenset({True}),
        payload_shape=RiskControlPayloadShape.SNAPSHOT,
    ),
    RiskControlState.DOWNGRADE_WITHIN_LIMIT: RiskControlStateSpec(
        state=RiskControlState.DOWNGRADE_WITHIN_LIMIT,
        evidence_present=True,
        trigger="risk_downgrade",
        planned_action="downgrade",
        applied=False,
        not_applied_reason="final_signal_already_within_risk_limit",
        allowed_override_enabled=frozenset({True}),
        payload_shape=RiskControlPayloadShape.SNAPSHOT,
    ),
    RiskControlState.VETO_APPLIED: RiskControlStateSpec(
        state=RiskControlState.VETO_APPLIED,
        evidence_present=True,
        trigger="risk_veto",
        planned_action="cap_buy_to_hold",
        applied=True,
        not_applied_reason="none",
        allowed_override_enabled=frozenset({True}),
        payload_shape=RiskControlPayloadShape.TRANSITION,
        allowed_reasons=frozenset({"risk_veto", "high_severity_flag"}),
        allowed_transitions=frozenset({("buy", "hold")}),
        application_adjustment="veto",
    ),
    RiskControlState.DOWNGRADE_ONE_APPLIED: RiskControlStateSpec(
        state=RiskControlState.DOWNGRADE_ONE_APPLIED,
        evidence_present=True,
        trigger="risk_downgrade",
        planned_action="downgrade",
        applied=True,
        not_applied_reason="none",
        allowed_override_enabled=frozenset({True}),
        payload_shape=RiskControlPayloadShape.TRANSITION,
        allowed_reasons=frozenset({"downgrade_one"}),
        allowed_transitions=frozenset({("buy", "hold"), ("hold", "sell")}),
        application_adjustment="downgrade_one",
    ),
    RiskControlState.DOWNGRADE_TWO_APPLIED: RiskControlStateSpec(
        state=RiskControlState.DOWNGRADE_TWO_APPLIED,
        evidence_present=True,
        trigger="risk_downgrade",
        planned_action="downgrade",
        applied=True,
        not_applied_reason="none",
        allowed_override_enabled=frozenset({True}),
        payload_shape=RiskControlPayloadShape.TRANSITION,
        allowed_reasons=frozenset({"downgrade_two"}),
        allowed_transitions=frozenset({("buy", "sell"), ("hold", "sell")}),
        application_adjustment="downgrade_two",
    ),
})


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
    current_signal: Optional[RiskControlSignal]
    target_signal: Optional[RiskControlSignal]
    will_apply: Optional[bool]
    reason: str

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
    """Typed record of the override branch that actually changed the signal."""

    state: RiskControlState
    from_signal: RiskControlSignal
    to_signal: RiskControlSignal
    reason: RiskControlAppliedReason

    @property
    def adjustment(self) -> RiskOverrideAdjustment:
        adjustment = RISK_CONTROL_STATE_SPECS[self.state].application_adjustment
        if adjustment is None:
            raise ValueError(f"risk_control state={self.state.value!r} is not applied")
        return adjustment

    def __post_init__(self) -> None:
        spec = RISK_CONTROL_STATE_SPECS[self.state]
        spec.build_payload(
            override_enabled=True,
            from_signal=self.from_signal,
            to_signal=self.to_signal,
            reason=self.reason,
        )

    def to_context_dict(self) -> Dict[str, object]:
        return {
            "from": self.from_signal,
            "to": self.to_signal,
            "adjustment": self.adjustment,
            "reason": self.reason,
        }


def derive_risk_control_state(facts: RiskControlStateFacts) -> RiskControlState:
    """Derive one finite state from normalized runtime or payload facts."""
    matches = [
        state
        for state, spec in RISK_CONTROL_STATE_SPECS.items()
        if spec.matches(facts)
    ]
    if len(matches) != 1:
        raise ValueError(
            "risk_control facts must identify exactly one finite state: "
            f"applied={facts.applied!r}, "
            f"evidence_present={facts.evidence_present!r}, "
            f"trigger={facts.trigger!r}, "
            f"override_enabled={facts.override_enabled!r}, "
            f"reason={facts.reason!r}; "
            f"matches={[state.value for state in matches]!r}"
        )
    return matches[0]


def identify_risk_control_state(payload: RiskControlPayload) -> RiskControlState:
    """Derive and validate the one finite state represented by a payload."""
    state = derive_risk_control_state(RiskControlStateFacts(
        applied=payload.applied,
        evidence_present=payload.evidence_present,
        trigger=payload.trigger,
        override_enabled=payload.override_enabled,
        reason=payload.reason,
    ))
    RISK_CONTROL_STATE_SPECS[state].validate(payload)
    return state


def derive_risk_control_trigger(plan: RiskOverridePlan) -> RiskControlTrigger:
    """Derive the pre-application trigger represented by a risk plan."""
    if plan.veto_buy:
        return "risk_veto"
    if plan.adjustment in _DOWNGRADE_STEPS:
        return "risk_downgrade"
    if plan.risk_level_high:
        return "high_risk_evidence"
    return "none"


def derive_risk_override_application(plan: RiskOverridePlan) -> RiskOverrideApplication:
    """Derive the actual applied branch from a plan that changes the signal."""
    if plan.will_apply is not True:
        raise ValueError("risk override application requires plan.will_apply=true")
    from_signal = _require_risk_control_signal(plan.current_signal, "current_signal")
    to_signal = _require_risk_control_signal(plan.target_signal, "target_signal")

    if plan.veto_buy and from_signal == "buy":
        spec = _applied_state_spec_for_adjustment("veto")
        reason: RiskControlAppliedReason = (
            "high_severity_flag" if plan.has_high_flag else "risk_veto"
        )
    else:
        spec = _applied_state_spec_for_adjustment(plan.adjustment)
        reason = cast(RiskControlAppliedReason, spec.application_adjustment)

    return RiskOverrideApplication(
        state=spec.state,
        from_signal=from_signal,
        to_signal=to_signal,
        reason=reason,
    )


def parse_risk_override_application(value: object) -> Optional[RiskOverrideApplication]:
    """Parse the internal context record without silently defaulting invalid data."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("risk_override_applied must be a mapping when present")

    from_signal = _require_risk_control_signal(value.get("from"), "from")
    to_signal = _require_risk_control_signal(value.get("to"), "to")
    spec = _applied_state_spec_for_adjustment(value.get("adjustment"))
    reason_value = value.get("reason")
    if reason_value not in spec.allowed_reasons:
        raise ValueError(
            f"risk_override_applied.reason is not valid for state={spec.state.value!r}"
        )
    reason = cast(RiskControlAppliedReason, reason_value)
    return RiskOverrideApplication(
        state=spec.state,
        from_signal=from_signal,
        to_signal=to_signal,
        reason=reason,
    )


def derive_risk_control_payload(
    plan: RiskOverridePlan,
    application: Optional[RiskOverrideApplication],
) -> RiskControlPayload:
    """Build the canonical public payload from plan facts and an applied record."""
    if application is not None:
        spec = RISK_CONTROL_STATE_SPECS[application.state]
        return spec.build_payload(
            override_enabled=plan.override_enabled,
            from_signal=application.from_signal,
            to_signal=application.to_signal,
            reason=application.reason,
        )

    if plan.will_apply is True:
        raise ValueError(
            "risk control plan requires an applied record when plan.will_apply=true"
        )
    trigger = derive_risk_control_trigger(plan)
    state = derive_risk_control_state(RiskControlStateFacts(
        applied=False,
        evidence_present=plan.evidence_present,
        trigger=trigger,
        override_enabled=plan.override_enabled,
        reason=None,
    ))
    return RISK_CONTROL_STATE_SPECS[state].build_payload(
        override_enabled=plan.override_enabled,
        current=_optional_risk_control_signal(plan.current_signal, "current_signal"),
        target=_optional_risk_control_signal(plan.target_signal, "target_signal"),
    )


def _require_risk_control_signal(value: object, field_name: str) -> RiskControlSignal:
    if value not in {"buy", "hold", "sell"}:
        raise ValueError(f"{field_name} must be buy, hold, or sell")
    return cast(RiskControlSignal, value)


def _optional_risk_control_signal(
    value: object,
    field_name: str,
) -> Optional[RiskControlSignal]:
    if value is None:
        return None
    return _require_risk_control_signal(value, field_name)


def _applied_state_spec_for_adjustment(adjustment: object) -> RiskControlStateSpec:
    matches = [
        spec
        for spec in RISK_CONTROL_STATE_SPECS.values()
        if spec.application_adjustment == adjustment
    ]
    if len(matches) != 1:
        raise ValueError(
            "risk override adjustment must identify exactly one applied state: "
            f"adjustment={adjustment!r}"
        )
    return matches[0]


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
    "RISK_CONTROL_STATE_SPECS",
    "RiskControlAppliedReason",
    "RiskControlNotAppliedReason",
    "RiskControlPayload",
    "RiskControlPayloadShape",
    "RiskControlPlannedAction",
    "RiskControlSignal",
    "RiskControlState",
    "RiskControlStateFacts",
    "RiskControlStateSpec",
    "RiskControlTrigger",
    "RiskOverrideAdjustment",
    "RiskOverrideApplication",
    "RiskOverridePlan",
    "build_risk_override_plan",
    "derive_risk_control_payload",
    "derive_risk_control_state",
    "derive_risk_control_trigger",
    "derive_risk_override_application",
    "identify_risk_control_state",
    "parse_risk_override_application",
]
