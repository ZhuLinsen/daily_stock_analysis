# -*- coding: utf-8 -*-
"""Decision guardrail using CrossAssetContext for Issue #1910.

Scope boundary (maintainer-confirmed): cross-asset signals only calibrate
risk appetite and confidence — they never become trading rules. This
guardrail is deliberately LIGHTER than ``apply_daily_market_context_guardrail``:

- fires ONLY when ``risk_appetite == "risk_off"`` AND the result carries a
  high-confidence aggressive-buy signal (marker word lists reused from
  ``src/daily_market_context_guardrail.py``);
- downgrades confidence high → medium, appends an exception-rationale
  requirement to ``phase_decision.confidence_reason`` and registers the
  calibration in ``phase_decision.data_limitations``;
- NEVER changes ``decision_type`` / ``operation_advice`` / sentiment;
- idempotent: if a previous guardrail already capped confidence, it only
  (re-)registers the reason/limitation, never double-downgrades.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from src.daily_market_context_guardrail import (
    _has_aggressive_buy_signal,
    _is_high_confidence,
)
from src.report_language import (
    localize_confidence_level,
    normalize_report_language,
)

_EXCEPTION_REQUIREMENT_ZH = (
    "外围环境 risk-off：若维持高置信激进买入结论，必须在置信度理由中写明例外依据，否则应下调置信度。"
)
_EXCEPTION_REQUIREMENT_EN = (
    "Cross-asset context is risk-off: keeping a high-confidence aggressive buy requires an explicit "
    "exception rationale in the confidence reason; otherwise lower the confidence."
)
_EXCEPTION_LIMITATION_ZH = (
    "外围环境 risk-off，已对高置信激进买入做置信度校准（要求写明例外理由）。"
)
_EXCEPTION_LIMITATION_EN = (
    "Cross-asset context is risk-off; high-confidence aggressive buy was calibrated and an "
    "exception rationale is required."
)


def apply_cross_asset_context_guardrail(
    result: Any,
    *,
    cross_asset_context: Any,
    report_language: str = "zh",
) -> List[str]:
    """Calibrate confidence when cross-asset context is risk_off.

    Returns a list of adjustment markers (empty when no action taken).
    """

    if result is None:
        return []
    payload = _coerce_context_mapping(cross_asset_context)
    if str(payload.get("risk_appetite") or "").strip().lower() != "risk_off":
        return []

    language = normalize_report_language(
        report_language or getattr(result, "report_language", "zh")
    )
    if not _has_aggressive_buy_signal(result, language=language):
        return []

    adjustments: List[str] = []

    # Idempotent downgrade: only cap when still high (a previous guardrail
    # may already have capped it to medium — T13 semantics).
    if _is_high_confidence(getattr(result, "confidence_level", "")):
        result.confidence_level = localize_confidence_level("medium", language)
        adjustments.append("confidence_capped_cross_asset_context")

    if _register_exception_requirement(result, language=language):
        adjustments.append("cross_asset_context_exception_reason_registered")

    return adjustments


def _register_exception_requirement(result: Any, *, language: str) -> bool:
    """Append the exception-rationale requirement + limitation (idempotent)."""

    dashboard = getattr(result, "dashboard", None)
    if not isinstance(dashboard, dict):
        dashboard = {}
        result.dashboard = dashboard

    phase_decision = dashboard.get("phase_decision")
    if not isinstance(phase_decision, dict):
        phase_decision = {}
        dashboard["phase_decision"] = phase_decision

    changed = False

    requirement = _EXCEPTION_REQUIREMENT_EN if language in ("en", "ko") else _EXCEPTION_REQUIREMENT_ZH
    reason = str(phase_decision.get("confidence_reason") or "").strip()
    if requirement not in reason:
        separator = "; " if language in ("en", "ko") else "；"
        phase_decision["confidence_reason"] = f"{reason}{separator}{requirement}" if reason else requirement
        changed = True

    limitation = _EXCEPTION_LIMITATION_EN if language in ("en", "ko") else _EXCEPTION_LIMITATION_ZH
    limitations = phase_decision.get("data_limitations")
    if not isinstance(limitations, list):
        limitations = []
    if limitation not in limitations:
        limitations.append(limitation)
        phase_decision["data_limitations"] = limitations
        changed = True

    return changed


def _coerce_context_mapping(context: Any) -> Dict[str, Any]:
    if context is None:
        return {}
    to_safe_dict = getattr(context, "to_safe_dict", None)
    if callable(to_safe_dict):
        try:
            payload = to_safe_dict()
        except Exception:
            payload = None
        if isinstance(payload, Mapping):
            return dict(payload)
        return {}
    if isinstance(context, Mapping):
        return dict(context)
    return {}
