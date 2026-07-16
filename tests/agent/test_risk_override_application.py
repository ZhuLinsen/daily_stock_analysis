# -*- coding: utf-8 -*-
"""Focused tests for final risk override application states."""

import pytest

from src.agent.protocols import AgentContext, AgentOpinion
from src.agent.risk_override import (
    DashboardDecisionSignal,
    RiskApplicationReason,
    RiskOverrideApplication,
    build_risk_override_application,
    build_risk_override_plan,
)


def _application(
    *,
    current_signal="buy",
    override_enabled=True,
    risk_raw=None,
):
    ctx = AgentContext()
    if risk_raw is not None:
        ctx.add_opinion(AgentOpinion(agent_name="risk", signal="hold", raw_data=risk_raw))
    plan = build_risk_override_plan(
        ctx,
        current_signal=current_signal,
        override_enabled=override_enabled,
    )
    return build_risk_override_application(plan)


@pytest.mark.parametrize(
    ("application", "reason"),
    [
        (_application(), RiskApplicationReason.NO_RISK_EVIDENCE),
        (
            _application(risk_raw={"risk_level": "high"}),
            RiskApplicationReason.NO_OVERRIDE_TRIGGER,
        ),
        (
            _application(risk_raw={"veto_buy": True}, override_enabled=False),
            RiskApplicationReason.OVERRIDE_DISABLED,
        ),
        (
            _application(current_signal="hold", risk_raw={"veto_buy": True}),
            RiskApplicationReason.FINAL_SIGNAL_ALREADY_WITHIN_RISK_LIMIT,
        ),
    ],
)
def test_non_applied_reasons_remain_distinct(application, reason):
    assert application.applied is False
    assert application.reason == reason
    assert application.from_signal is None
    assert application.to_signal is None


def test_veto_application_records_real_transition():
    application = _application(current_signal="buy", risk_raw={"veto_buy": True})

    assert application == RiskOverrideApplication(
        evidence_present=True,
        override_enabled=True,
        trigger="risk_veto",
        applied=True,
        reason=RiskApplicationReason.RISK_VETO_APPLIED,
        final_signal=DashboardDecisionSignal.HOLD,
        from_signal=DashboardDecisionSignal.BUY,
        to_signal=DashboardDecisionSignal.HOLD,
    )


def test_downgrade_application_records_real_transition():
    application = _application(
        current_signal="hold",
        risk_raw={"signal_adjustment": "downgrade_one"},
    )

    assert application.reason == RiskApplicationReason.RISK_DOWNGRADE_APPLIED
    assert application.final_signal == DashboardDecisionSignal.SELL
    assert application.from_signal == DashboardDecisionSignal.HOLD
    assert application.to_signal == DashboardDecisionSignal.SELL


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "evidence_present": True,
            "override_enabled": False,
            "trigger": "risk_veto",
            "applied": True,
            "reason": "override_disabled",
            "final_signal": "hold",
            "from_signal": "buy",
            "to_signal": "hold",
        },
        {
            "evidence_present": True,
            "override_enabled": True,
            "trigger": "risk_veto",
            "applied": True,
            "reason": "risk_veto_applied",
            "final_signal": "hold",
        },
        {
            "evidence_present": True,
            "override_enabled": True,
            "trigger": "risk_veto",
            "applied": True,
            "reason": "risk_veto_applied",
            "final_signal": "buy",
            "from_signal": "buy",
            "to_signal": "buy",
        },
        {
            "evidence_present": True,
            "override_enabled": False,
            "trigger": "risk_veto",
            "applied": False,
            "reason": "override_disabled",
            "final_signal": "buy",
            "from_signal": "buy",
            "to_signal": "hold",
        },
        {
            "evidence_present": True,
            "override_enabled": True,
            "trigger": "risk_veto",
            "applied": True,
            "reason": "risk_veto_applied",
            "final_signal": "sell",
            "from_signal": "buy",
            "to_signal": "sell",
        },
        {
            "evidence_present": True,
            "override_enabled": True,
            "trigger": "risk_downgrade",
            "applied": True,
            "reason": "risk_downgrade_applied",
            "final_signal": "hold",
            "from_signal": "sell",
            "to_signal": "hold",
        },
    ],
)
def test_application_rejects_invalid_transition_shape(kwargs):
    with pytest.raises(ValueError):
        RiskOverrideApplication(**kwargs)
