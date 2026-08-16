"""Pure intraday metric calculations."""

from __future__ import annotations

from statistics import median
from typing import Any, Iterable, Optional

from .models import IntradayMetrics


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def calculate_rvol_time(today_cum_amount: float, historical_cum_amounts: Iterable[float]) -> tuple[Optional[float], float]:
    history = [float(value) for value in historical_cum_amounts if value is not None and float(value) > 0]
    if len(history) < 5 or today_cum_amount < 0:
        return None, 0.0
    baseline = median(history)
    if baseline <= 0:
        return None, 0.0
    confidence = 1.0 if len(history) >= 10 else 0.6
    return today_cum_amount / baseline, confidence


def calculate_intraday_metrics(
    current: dict[str, Any],
    historical_same_time: list[dict[str, Any]],
    *,
    sector_score: Optional[float] = None,
    breakout_score: Optional[float] = None,
    risk_quality_score: Optional[float] = None,
) -> IntradayMetrics:
    price = _float(current.get("price") or current.get("close"))
    open_price = _float(current.get("open"))
    day_high = _float(current.get("high"), price)
    day_low = _float(current.get("low"), price)
    amount = _float(current.get("cumulative_amount") or current.get("amount"))

    history_amounts = [
        _float(item.get("cumulative_amount") or item.get("amount"))
        for item in historical_same_time
    ]
    rvol, confidence = calculate_rvol_time(amount, history_amounts)

    price_strength = ((price - open_price) / open_price * 100.0) if open_price > 0 else 0.0
    if day_high > day_low:
        high_position = _clamp((price - day_low) / (day_high - day_low), 0.0, 1.0)
    else:
        high_position = 0.5
    pullback = ((day_high - price) / day_high * 100.0) if day_high > 0 else 0.0

    return IntradayMetrics(
        rvol_time=rvol,
        rvol_confidence=confidence,
        price_strength=price_strength,
        high_position=high_position,
        pullback_from_high_pct=max(0.0, pullback),
        sector_score=sector_score,
        breakout_score=breakout_score,
        risk_quality_score=risk_quality_score,
        turnover_rate=_float(current.get("turnover_rate")) if current.get("turnover_rate") is not None else None,
        limit_state=current.get("limit_state"),
    )
