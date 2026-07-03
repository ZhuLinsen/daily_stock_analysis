# -*- coding: utf-8 -*-
"""Brinson performance attribution for backtest results.

Implements the Brinson-Fachler model to decompose excess return into:
- **Selection effect**: benefit of over/under-weighting strategy groups
- **Timing effect**: benefit of the strategy's execution within each group
- **Interaction effect**: cross term

Benchmark = equal-weight buy-and-hold of all stocks (using ``stock_return_pct``).
Portfolio = strategy-executed (``simulated_return_pct`` for long positions, 0% for cash).

The grouping is by ``position_recommendation`` (long/cash) for the Brinson
decomposition, and by ``operation_advice`` for the strategy-level attribution
summary. Both groupings degrade gracefully when fields are missing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from src.schemas.backtest_attribution import (
    BacktestAttributionResult,
    BrinsonAttribution,
    StrategyGroupAttribution,
)


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
        if f != f:  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None


def compute_brinson_attribution(
    results: Sequence[Any],
    *,
    group_field: str = "position_recommendation",
) -> BacktestAttributionResult:
    """Compute Brinson attribution from a list of BacktestResult-like objects.

    Each result must expose: ``position_recommendation``, ``operation_advice``,
    ``stock_return_pct``, ``simulated_return_pct``, ``outcome``.

    Results with missing return data are skipped. If fewer than 2 valid results
    remain, an empty attribution is returned with zeroed effects.
    """
    valid = _filter_valid_results(results)
    total_count = len(valid)
    if total_count < 2:
        return _empty_attribution(total_count, group_field)

    # Benchmark: equal-weight buy-and-hold of all stocks
    benchmark_return = _mean([r_stock for _, r_stock, _ in valid])

    # Portfolio: simulated return for long, 0 for cash
    portfolio_returns = [
        r_sim if r_sim is not None else (r_stock if _is_long(pos) else 0.0)
        for pos, r_stock, r_sim in valid
    ]
    portfolio_return = _mean(portfolio_returns)

    brinson = _decompose_brinson(valid, benchmark_return, portfolio_return, group_field)
    strategy_groups = _build_strategy_groups(valid, portfolio_return, benchmark_return)

    return BacktestAttributionResult(
        brinson=brinson,
        strategy_groups=strategy_groups,
        total_results=total_count,
        attribution_basis=group_field,
    )


def _filter_valid_results(
    results: Sequence[Any],
) -> List[tuple]:
    """Return list of (position, stock_return, simulated_return) for valid results."""
    valid: List[tuple] = []
    for r in results:
        pos = getattr(r, "position_recommendation", None) or "unknown"
        r_stock = _safe_float(getattr(r, "stock_return_pct", None))
        r_sim = _safe_float(getattr(r, "simulated_return_pct", None))
        if r_stock is None and r_sim is None:
            continue
        if r_stock is None:
            r_stock = r_sim
        valid.append((str(pos).lower(), r_stock, r_sim))
    return valid


def _is_long(position: str) -> bool:
    return position in ("long", "buy", "hold")


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _decompose_brinson(
    valid: List[tuple],
    benchmark_return: float,
    portfolio_return: float,
    group_field: str,
) -> BrinsonAttribution:
    """Decompose excess return using the Brinson-Fachler model."""
    total = len(valid)
    groups = _group_by_position(valid)

    selection = 0.0
    timing = 0.0
    interaction = 0.0

    for pos, items in groups.items():
        n_i = len(items)
        wb_i = n_i / total  # benchmark weight (equal weight)
        rb_i = _mean([r_stock for _, r_stock, _ in items])

        # Portfolio weight: long stocks keep their weight, cash stocks get 0
        if _is_long(pos):
            wp_i = n_i / total
            rp_i = _mean([
                r_sim if r_sim is not None else r_stock
                for _, r_stock, r_sim in items
            ])
        else:
            wp_i = 0.0
            rp_i = 0.0

        selection += (wp_i - wb_i) * rb_i
        timing += wb_i * (rp_i - rb_i)
        interaction += (wp_i - wb_i) * (rp_i - rb_i)

    total_excess = portfolio_return - benchmark_return
    # Reconcile: total_excess should ≈ selection + timing + interaction
    # Small floating-point drift is acceptable; large gaps indicate a bug.
    return BrinsonAttribution(
        selection_effect=round(selection, 4),
        timing_effect=round(timing, 4),
        interaction_effect=round(interaction, 4),
        total_excess_return=round(total_excess, 4),
        benchmark_return_pct=round(benchmark_return, 4),
        portfolio_return_pct=round(portfolio_return, 4),
    )


def _group_by_position(valid: List[tuple]) -> Dict[str, List[tuple]]:
    groups: Dict[str, List[tuple]] = {}
    for pos, r_stock, r_sim in valid:
        groups.setdefault(pos, []).append((pos, r_stock, r_sim))
    return groups


def _build_strategy_groups(
    valid: List[tuple],
    portfolio_return: float,
    benchmark_return: float,
) -> List[StrategyGroupAttribution]:
    """Build per-strategy attribution for the operation_advice grouping.

    Since ``valid`` tuples only carry position data, this function provides
    a simpler grouping by position_recommendation. The service layer can
    enhance this with operation_advice if the raw results are available.
    """
    total = len(valid)
    groups = _group_by_position(valid)
    result: List[StrategyGroupAttribution] = []

    for pos, items in sorted(groups.items()):
        n_i = len(items)
        stock_returns = [r_stock for _, r_stock, _ in items]
        sim_returns = [
            r_sim if r_sim is not None else (r_stock if _is_long(pos) else 0.0)
            for _, r_stock, r_sim in items
        ]
        rb_i = _mean(stock_returns)
        rp_i = _mean(sim_returns)
        wp_i = (n_i / total) if _is_long(pos) else 0.0
        wb_i = n_i / total

        wins = sum(1 for r in sim_returns if r > 0)
        win_rate = wins / n_i if n_i else 0.0

        contribution = wp_i * rp_i - wb_i * rb_i

        result.append(StrategyGroupAttribution(
            strategy=pos,
            stock_count=n_i,
            portfolio_weight=round(wp_i, 4),
            benchmark_weight=round(wb_i, 4),
            portfolio_return_pct=round(rp_i, 4),
            benchmark_return_pct=round(rb_i, 4),
            contribution_pct=round(contribution, 4),
            win_rate=round(win_rate, 4),
            selection_effect=round((wp_i - wb_i) * rb_i, 4),
            timing_effect=round(wb_i * (rp_i - rb_i), 4),
            interaction_effect=round((wp_i - wb_i) * (rp_i - rb_i), 4),
        ))

    result.sort(key=lambda g: g.contribution_pct, reverse=True)
    return result


def _empty_attribution(total: int, group_field: str) -> BacktestAttributionResult:
    return BacktestAttributionResult(
        brinson=BrinsonAttribution(
            selection_effect=0.0,
            timing_effect=0.0,
            interaction_effect=0.0,
            total_excess_return=0.0,
            benchmark_return_pct=0.0,
            portfolio_return_pct=0.0,
        ),
        strategy_groups=[],
        total_results=total,
        attribution_basis=group_field,
    )
