# -*- coding: utf-8 -*-
"""Deterministic numeric grounding verifier and ATR risk-budget position sizer."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Dict, Optional

from src.utils.sniper_points import parse_sniper_value


_OFFENSIVE_ACTIONS = {"buy", "add"}
_DEFAULT_STOP_DISTANCE_PCT = 4.0
_MIN_STOP_DISTANCE_PCT = 2.5
_DEFAULT_RISK_BUDGET_PCT = 1.2
_ANCHOR_DRIFT_LIMIT = 0.25


def _read_attr_or_key(source: Any, key: str) -> Any:
    if source is None:
        return None
    if isinstance(source, Mapping):
        if key in source:
            return source[key]
        parts = key.split("_")
        camel = parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
        return source.get(camel)
    return getattr(source, key, None)


def _finite_positive(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num) or num <= 0:
        return None
    return round(num, 4)


def verify_and_normalize_levels(
    strategy: Any,
    current_price: Optional[float],
    action: Optional[str],
) -> Dict[str, Any]:
    """Parse sniper levels into numbers and validate geometric & anchor consistency."""
    ideal_buy = _finite_positive(parse_sniper_value(_read_attr_or_key(strategy, "ideal_buy")))
    secondary_buy = _finite_positive(parse_sniper_value(_read_attr_or_key(strategy, "secondary_buy")))
    stop_loss = _finite_positive(parse_sniper_value(_read_attr_or_key(strategy, "stop_loss")))
    take_profit = _finite_positive(parse_sniper_value(_read_attr_or_key(strategy, "take_profit")))
    ref_current = _finite_positive(current_price)

    normalized_action = str(action or "").strip().lower() or None
    validation = "ok"
    if normalized_action in _OFFENSIVE_ACTIONS and (
        (ideal_buy is not None and stop_loss is not None and stop_loss >= ideal_buy)
        or (secondary_buy is not None and stop_loss is not None and stop_loss >= secondary_buy)
        or (ideal_buy is not None and secondary_buy is not None and secondary_buy > ideal_buy)
        or (
            ideal_buy is not None
            and take_profit is not None
            and take_profit <= ideal_buy
        )
    ):
        validation = "direction_conflict"
    elif (
        ideal_buy is not None
        and stop_loss is not None
        and stop_loss >= ideal_buy
    ):
        validation = "direction_conflict"
    elif (
        ref_current is not None
        and ideal_buy is not None
        and abs(ideal_buy - ref_current) / ref_current > _ANCHOR_DRIFT_LIMIT
    ):
        validation = "out_of_range"

    reference_price = ref_current if ref_current is not None else ideal_buy

    status = (
        "active"
        if normalized_action in _OFFENSIVE_ACTIONS and validation == "ok"
        else "invalid" if normalized_action in _OFFENSIVE_ACTIONS else "conditional_watch"
    )

    if ref_current is not None and ideal_buy is not None:
        entry_ref: Optional[float] = min(ref_current, ideal_buy)
    else:
        entry_ref = ideal_buy if ideal_buy is not None else ref_current

    risk_reward_ratio: Optional[float] = None
    if (
        validation == "ok"
        and entry_ref is not None
        and stop_loss is not None
        and take_profit is not None
        and entry_ref > stop_loss
        and take_profit > entry_ref
    ):
        risk_reward_ratio = round((take_profit - entry_ref) / (entry_ref - stop_loss), 2)

    return {
        "ideal_buy": ideal_buy,
        "secondary_buy": secondary_buy,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "reference_price": reference_price,
        "risk_reward_ratio": risk_reward_ratio,
        "status": status,
        "validation": validation,
    }


def compute_atr_position_sizing(
    action: Optional[str],
    sentiment_score: Optional[int],
    levels: Dict[str, Any],
    data_quality_level: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute bounded single-stock position sizing from stop distance and data quality."""
    normalized_action = str(action or "").strip().lower() or None
    quality = str(data_quality_level or "").strip().lower() or None

    if normalized_action not in _OFFENSIVE_ACTIONS or quality == "poor":
        return {
            "min_pct": 0,
            "max_pct": 0,
            "method": "atr_risk_budget",
            "stop_distance_pct": None,
            "risk_budget_pct": _DEFAULT_RISK_BUDGET_PCT,
            "cap_reason": (
                "non_offensive_action"
                if normalized_action not in _OFFENSIVE_ACTIONS
                else "poor_data_quality"
            ),
        }

    if levels.get("validation") not in (None, "ok") or levels.get("status") == "invalid":
        return {
            "min_pct": 0,
            "max_pct": 0,
            "method": "atr_risk_budget",
            "stop_distance_pct": None,
            "risk_budget_pct": _DEFAULT_RISK_BUDGET_PCT,
            "cap_reason": "invalid_levels",
        }

    ref_price = _finite_positive(levels.get("reference_price"))
    stop_loss = _finite_positive(levels.get("stop_loss"))
    if ref_price is not None and stop_loss is not None and stop_loss >= ref_price:
        return {
            "min_pct": 0,
            "max_pct": 0,
            "method": "atr_risk_budget",
            "stop_distance_pct": None,
            "risk_budget_pct": _DEFAULT_RISK_BUDGET_PCT,
            "cap_reason": "invalid_levels",
        }
    if ref_price is not None and stop_loss is not None and ref_price > stop_loss:
        raw_dist = (ref_price - stop_loss) / ref_price * 100.0
    else:
        raw_dist = _DEFAULT_STOP_DISTANCE_PCT

    effective_stop_pct = max(raw_dist, _MIN_STOP_DISTANCE_PCT)

    score = 60 if sentiment_score is None else int(sentiment_score)
    conviction = max(0.5, min(1.2, (score - 40) / 40.0))

    base_pct = (_DEFAULT_RISK_BUDGET_PCT / effective_stop_pct) * 100.0 * conviction
    cap = 20.0 if quality == "limited" else 35.0
    capped_pct = min(base_pct, cap)

    # Never round up: the displayed position must remain within the risk budget.
    # A normal round can increase the displayed percentage by up to 0.005pp.
    rounded_max = math.floor(min(capped_pct, cap) * 100.0 + 1e-9) / 100.0
    rounded_min = round(max(0.0, rounded_max - 5.0), 2)

    return {
        "min_pct": rounded_min,
        "max_pct": rounded_max,
        "method": "atr_risk_budget",
        "stop_distance_pct": round(effective_stop_pct, 2),
        "risk_budget_pct": _DEFAULT_RISK_BUDGET_PCT,
        "cap_reason": "limited_data_quality" if quality == "limited" else None,
    }
