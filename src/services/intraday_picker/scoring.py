"""Transparent deterministic scoring for intraday candidates."""

from __future__ import annotations

from .models import IntradayCandidate


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_rvol(rvol: float | None) -> float:
    if rvol is None:
        return 50.0
    if rvol < 0.8:
        return 10.0
    if rvol < 1.0:
        return 25.0
    if rvol < 1.5:
        return 45.0
    if rvol < 2.0:
        return 65.0
    if rvol < 3.0:
        return 80.0
    if rvol < 4.0:
        return 90.0
    return 100.0


def score_price_strength(candidate: IntradayCandidate) -> float:
    metrics = candidate.metrics
    intraday = clamp(50.0 + metrics.price_strength * 8.0)
    position = clamp(metrics.high_position * 100.0)
    return intraday * 0.6 + position * 0.4


def resonance_bonus(hit_count: int) -> float:
    if hit_count >= 4:
        return 7.0
    if hit_count == 3:
        return 5.0
    if hit_count == 2:
        return 3.0
    return 0.0


def calculate_penalty(candidate: IntradayCandidate) -> float:
    change = candidate.change_pct
    pullback = candidate.metrics.pullback_from_high_pct
    penalty = 0.0
    if change > 8.8:
        penalty += 10.0
    elif change > 7.5:
        penalty += 5.0
    elif change > 6.0:
        penalty += 2.0

    if pullback > 4.0:
        penalty += 10.0
    elif pullback > 2.5:
        penalty += 5.0
    elif pullback > 1.5:
        penalty += 2.0

    turnover = candidate.metrics.turnover_rate
    if turnover is not None and turnover > 25:
        penalty += 5.0
    if candidate.metrics.limit_state in {"broken_limit", "weak_limit"}:
        penalty += 5.0
    return penalty


def score_candidate(candidate: IntradayCandidate) -> float:
    metrics = candidate.metrics
    strategy = clamp(candidate.strategy_score)
    rvol = score_rvol(metrics.rvol_time)
    if metrics.rvol_time is not None:
        rvol = rvol * metrics.rvol_confidence + 50.0 * (1.0 - metrics.rvol_confidence)
    sector = 50.0 if metrics.sector_score is None else clamp(metrics.sector_score)
    price = score_price_strength(candidate)
    breakout = 50.0 if metrics.breakout_score is None else clamp(metrics.breakout_score)
    quality = 50.0 if metrics.risk_quality_score is None else clamp(metrics.risk_quality_score)
    resonance = resonance_bonus(len(candidate.strategy_hits) + sum(1 for result in candidate.confirmations if result.matched))

    weighted = (
        strategy * 0.35
        + rvol * 0.25
        + sector * 0.15
        + price * 0.10
        + breakout * 0.05
        + quality * 0.05
        + clamp(resonance / 7.0 * 100.0) * 0.05
    )
    candidate.resonance_score = resonance
    candidate.penalty_score = calculate_penalty(candidate)
    candidate.picker_score = clamp(weighted - candidate.penalty_score)
    return candidate.picker_score


def rank_candidates(candidates: list[IntradayCandidate]) -> list[IntradayCandidate]:
    for candidate in candidates:
        score_candidate(candidate)
    return sorted(candidates, key=lambda item: item.picker_score, reverse=True)
