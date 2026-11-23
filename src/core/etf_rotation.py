# -*- coding: utf-8 -*-
"""ETF rotation engine (pure logic, no I/O).

Rules (dual momentum):
1. On the last trading day of each week/month, rank risk assets by their
   ``lookback_days`` return (relative momentum).
2. Only assets with a positive lookback return are eligible (absolute
   momentum). Empty slots go to the safe asset, or cash when none is set.
3. An incumbent is kept while it stays eligible and its score is within
   ``switch_buffer_pct`` of the weakest selected candidate, to reduce churn.
4. Trades happen only when the selected set changes (drifted weights are
   not re-equalised). Orders are executed at the close of the next trading day
   (``EXECUTION_LAG_DAYS``), so a signal never trades on its own bar.

The strategy and the benchmark (equal-weight risk pool, daily rebalanced, no
costs) are both measured from the first execution day, so neither curve
carries a leading all-cash stretch the other does not have.

All inputs are wide close-price frames: index = trading date, columns = codes.
Prices are expected to be forward-adjusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

REBALANCE_CHOICES = ("weekly", "monthly")
CASH = "CASH"
EXECUTION_LAG_DAYS = 1
TRADING_DAYS_PER_YEAR = 244
DAYS_PER_YEAR = 365.25
MAX_FORWARD_FILL_DAYS = 5
DEFAULT_SWEEP_LOOKBACKS = (20, 40, 60, 90, 120, 150, 200)

Weights = Dict[str, float]


@dataclass(frozen=True)
class RotationParams:
    lookback_days: int = 60
    rebalance: str = "weekly"
    top_n: int = 1
    switch_buffer_pct: float = 2.0
    cost_bps: float = 10.0  # one-way cost per unit of turnover

    def __post_init__(self) -> None:
        if self.lookback_days < 1:
            raise ValueError("lookback_days must be >= 1")
        if self.rebalance not in REBALANCE_CHOICES:
            raise ValueError(f"rebalance must be one of {REBALANCE_CHOICES}")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        if self.switch_buffer_pct < 0 or self.cost_bps < 0:
            raise ValueError("switch_buffer_pct and cost_bps must be >= 0")


@dataclass(frozen=True)
class Trade:
    signal_date: pd.Timestamp
    exec_date: pd.Timestamp
    from_weights: Weights
    to_weights: Weights
    turnover: float


@dataclass
class BacktestResult:
    equity: pd.Series
    benchmark_equity: pd.Series
    trades: List[Trade] = field(default_factory=list)
    final_weights: Weights = field(default_factory=dict)
    final_holdings: Tuple[str, ...] = ()


def prepare_closes(closes: pd.DataFrame) -> pd.DataFrame:
    """Sort by date and bridge short suspensions; pre-listing gaps stay NaN."""
    return _valid_closes(closes).ffill(limit=MAX_FORWARD_FILL_DAYS)


def _valid_closes(closes: pd.DataFrame) -> pd.DataFrame:
    frame = closes.sort_index()
    frame = frame[~frame.index.duplicated(keep="last")].apply(pd.to_numeric, errors="coerce")
    return frame.replace([math.inf, -math.inf], math.nan).where(frame > 0)


def momentum_scores(closes: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
    return closes / closes.shift(lookback_days) - 1.0


def _period_code(rebalance: str) -> str:
    if rebalance not in REBALANCE_CHOICES:
        raise ValueError(f"rebalance must be one of {REBALANCE_CHOICES}")
    return "W" if rebalance == "weekly" else "M"


def rebalance_dates(index: pd.DatetimeIndex, rebalance: str) -> pd.DatetimeIndex:
    """Last available trading date of every week or month in ``index``."""
    period = _period_code(rebalance)
    if len(index) == 0:
        return index
    keys = index.to_period(period)
    is_last = keys != keys.to_series().shift(-1).values
    return index[is_last]


def is_rebalance_day(day: pd.Timestamp, next_session: pd.Timestamp, rebalance: str) -> bool:
    """True when ``day`` is the last trading day of its week/month."""
    period = _period_code(rebalance)
    return pd.Timestamp(day).to_period(period) != pd.Timestamp(next_session).to_period(period)


def select_holdings(
    scores: pd.Series,
    current: Sequence[str],
    params: RotationParams,
) -> Tuple[str, ...]:
    """Pick up to ``top_n`` risk assets; an empty tuple means fully defensive."""
    eligible = scores.dropna()
    eligible = eligible[eligible > 0].sort_values(ascending=False)
    if eligible.empty:
        return ()

    slots = min(params.top_n, len(eligible))
    cutoff = eligible.iloc[slots - 1] - params.switch_buffer_pct / 100.0
    kept = [code for code in current if code in eligible.index and eligible[code] >= cutoff]
    kept = sorted(kept, key=lambda code: eligible[code], reverse=True)[:slots]
    newcomers = [code for code in eligible.index if code not in kept][: slots - len(kept)]
    chosen = kept + newcomers
    return tuple(sorted(chosen, key=lambda code: eligible[code], reverse=True))


def holdings_to_weights(
    holdings: Sequence[str],
    top_n: int,
    safe_asset: Optional[str],
) -> Weights:
    """Each slot is 1/top_n; unfilled slots go to the safe asset (or cash)."""
    slot = 1.0 / top_n
    weights: Weights = {code: slot for code in holdings}
    spare = 1.0 - slot * len(holdings)
    if spare > 1e-12:
        defensive = safe_asset or CASH
        weights[defensive] = weights.get(defensive, 0.0) + spare
    return weights


def _turnover(old: Weights, new: Weights) -> float:
    """Traded notional as a fraction of equity; the cash leg is not a trade."""
    codes = (set(old) | set(new)) - {CASH}
    return sum(abs(new.get(c, 0.0) - old.get(c, 0.0)) for c in codes)


def _drift(weights: Weights, returns: Dict[str, float]) -> Tuple[Weights, float]:
    """Apply one day of returns; return drifted weights and portfolio return."""
    grown = {c: w * (1.0 + returns.get(c, 0.0)) for c, w in weights.items()}
    total = sum(grown.values())
    port_ret = total - 1.0 if weights else 0.0
    if total <= 0:
        return {}, port_ret
    return {c: v / total for c, v in grown.items()}, port_ret


def run_backtest(
    closes: pd.DataFrame,
    risk_assets: Sequence[str],
    safe_asset: Optional[str],
    params: RotationParams,
) -> BacktestResult:
    """Simulate the rotation; curves start on the first execution day.

    Signals start on the first day any risk score exists. Before the first
    order fills the portfolio is all cash (equity stays 1.0), so the returned
    curves begin at that fill with value 1.0; the entry cost shows up in the
    next bar's return. Without any fill the curves hold only the last bar.
    """
    risk = [c for c in risk_assets if c in closes.columns]
    if not risk:
        raise ValueError("no risk asset has price data")
    if safe_asset and safe_asset not in closes.columns:
        safe_asset = None

    frame = prepare_closes(closes)
    quoted = _valid_closes(closes)
    scores = momentum_scores(frame[risk], params.lookback_days).where(quoted[risk].notna())
    valid_rows = scores.notna().any(axis=1)
    if not valid_rows.any():
        raise ValueError(
            f"not enough history for lookback_days={params.lookback_days}"
        )
    start = valid_rows.idxmax()
    frame = frame.loc[start:]
    scores = scores.loc[start:]
    quoted = quoted.loc[start:]
    # Carry the last known mark for valuation, never for execution. On quote
    # recovery the full change from that mark belongs to existing holders.
    valuation = _valid_closes(closes).ffill().loc[start:]
    daily_returns = valuation.pct_change(fill_method=None).fillna(0.0)

    rebal = set(rebalance_dates(frame.index, params.rebalance))
    dates = list(frame.index)
    cost_rate = params.cost_bps / 10000.0

    weights: Weights = {CASH: 1.0}
    holdings: Tuple[str, ...] = ()
    pending: Optional[Tuple[int, pd.Timestamp, Tuple[str, ...]]] = None
    entry: Optional[int] = None
    trades: List[Trade] = []
    equity_values: List[float] = []
    bench_values: List[float] = []
    equity = 1.0
    bench = 1.0

    for i, day in enumerate(dates):
        row = daily_returns.loc[day]
        if i > 0:
            weights, port_ret = _drift(weights, {c: row[c] for c in weights if c in row})
            equity *= 1.0 + port_ret
            listed = [c for c in risk if pd.notna(valuation.loc[day, c]) and pd.notna(valuation[c].iloc[i - 1])]
            bench *= 1.0 + (float(row[listed].mean()) if listed else 0.0)

        if pending is not None and pending[0] == i:
            _, signal_day, new_holdings = pending
            pending = None
            available_safe = safe_asset if safe_asset and pd.notna(quoted.loc[day, safe_asset]) else None
            target = holdings_to_weights(new_holdings, params.top_n, available_safe)
            # Do not fabricate a buy or sell at a carried-forward price. Keep
            # the current portfolio until a later scheduled signal can trade.
            involved = (set(weights) | set(target)) - {CASH}
            can_trade = all(pd.notna(quoted.loc[day, code]) for code in involved)
            # Same holdings -> no trade; drifted weights are not re-equalised.
            if can_trade and (entry is None or set(target) != set(weights)):
                if entry is None:
                    entry = i
                turnover = _turnover(weights, target)
                if turnover > 1e-9:
                    equity *= 1.0 - turnover * cost_rate
                    trades.append(Trade(signal_day, day, dict(weights), target, turnover))
                weights, holdings = target, new_holdings

        if day in rebal and i + EXECUTION_LAG_DAYS < len(dates):
            chosen = select_holdings(scores.loc[day], holdings, params)
            pending = (i + EXECUTION_LAG_DAYS, day, chosen)

        equity_values.append(equity)
        bench_values.append(bench)

    first = entry if entry is not None else len(dates) - 1
    index = frame.index[first:]
    # Equity is exactly 1.0 before the first fill (all cash), so the pre-cost
    # base is 1.0; the benchmark is rebased to the same day.
    strategy_values = [1.0] + equity_values[first + 1:]
    benchmark_values = [v / bench_values[first] for v in bench_values[first:]]
    return BacktestResult(
        equity=pd.Series(strategy_values, index=index, name="strategy"),
        benchmark_equity=pd.Series(benchmark_values, index=index, name="benchmark"),
        trades=trades,
        final_weights=weights,
        final_holdings=holdings,
    )


def compute_metrics(equity: pd.Series) -> Dict[str, float]:
    """CAGR / vol / Sharpe (rf=0) / max drawdown / Calmar for an equity curve."""
    empty = {k: math.nan for k in ("total_return", "cagr", "ann_vol", "sharpe", "max_drawdown", "calmar")}
    series = equity.dropna()
    if len(series) < 2 or series.iloc[0] <= 0:
        return empty

    total_return = series.iloc[-1] / series.iloc[0] - 1.0
    years = (series.index[-1] - series.index[0]).days / DAYS_PER_YEAR
    cagr = (1.0 + total_return) ** (1.0 / years) - 1.0 if years > 0 and total_return > -1 else math.nan
    rets = series.pct_change(fill_method=None).dropna()
    ann_vol = float(rets.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR))
    sharpe = float(rets.mean() * TRADING_DAYS_PER_YEAR / ann_vol) if ann_vol > 0 else math.nan
    max_drawdown = float((series / series.cummax() - 1.0).min())
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 and not math.isnan(cagr) else math.nan
    return {
        "total_return": float(total_return),
        "cagr": float(cagr),
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "calmar": float(calmar),
    }


def annual_returns(equity: pd.Series) -> pd.Series:
    """Calendar-year returns; the first year is measured from the curve start."""
    series = equity.dropna()
    if series.empty:
        return pd.Series(dtype=float)
    year_end = series.groupby(series.index.year).last()
    prev = year_end.shift(1)
    prev.iloc[0] = series.iloc[0]
    return year_end / prev - 1.0


def parameter_sweep(
    closes: pd.DataFrame,
    risk_assets: Sequence[str],
    safe_asset: Optional[str],
    params: RotationParams,
    lookbacks: Sequence[int] = DEFAULT_SWEEP_LOOKBACKS,
    min_years: float = 0.0,
) -> List[Tuple[int, Dict[str, float]]]:
    """Re-run the backtest over several lookbacks to expose overfitting.

    The configured ``params.lookback_days`` is always included. Every run is
    evaluated from the latest start among the kept runs (normally the longest
    lookback), so the rows cover the same calendar window. Lookbacks whose own
    curve is shorter than ``min_years`` are dropped so they cannot shrink that
    common window below ``min_years``.
    """
    frame = prepare_closes(closes)
    risk = [c for c in risk_assets if c in frame.columns]
    if not risk:
        return []

    runs: List[Tuple[int, BacktestResult]] = []
    for lookback in sorted(set(lookbacks) | {params.lookback_days}):
        swept = RotationParams(
            lookback_days=lookback,
            rebalance=params.rebalance,
            top_n=params.top_n,
            switch_buffer_pct=params.switch_buffer_pct,
            cost_bps=params.cost_bps,
        )
        try:
            runs.append((lookback, run_backtest(closes, risk, safe_asset, swept)))
        except ValueError:  # not enough history for this lookback
            continue
    last_day = frame.index[-1]
    runs = [
        (lookback, result) for lookback, result in runs
        if (last_day - result.equity.index[0]).days / DAYS_PER_YEAR >= min_years
    ]
    if not runs:
        return []
    common_start = max(result.equity.index[0] for _, result in runs)
    return [(lookback, compute_metrics(result.equity.loc[common_start:])) for lookback, result in runs]


def latest_ranking(
    closes: pd.DataFrame,
    risk_assets: Sequence[str],
    params: RotationParams,
) -> Tuple[pd.Timestamp, pd.Series]:
    """Momentum scores on the latest bar, sorted high to low (NaN last)."""
    frame = prepare_closes(closes)
    risk = [c for c in risk_assets if c in frame.columns]
    scores = momentum_scores(frame[risk], params.lookback_days)
    scores = scores.where(_valid_closes(closes)[risk].notna())
    as_of = frame.index[-1]
    return as_of, scores.loc[as_of].sort_values(ascending=False, na_position="last")
