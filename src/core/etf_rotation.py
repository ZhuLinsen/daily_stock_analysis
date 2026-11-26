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

import numpy as np
import pandas as pd

REBALANCE_CHOICES = ("weekly", "monthly")
SCORING_MODES = ("return", "vol_adjusted", "composite", "trend_r2")
WEIGHTING_MODES = ("equal", "inverse_vol")
CASH = "CASH"
EXECUTION_LAG_DAYS = 1
TRADING_DAYS_PER_YEAR = 244
DAYS_PER_YEAR = 365.25
MAX_FORWARD_FILL_DAYS = 5
DEFAULT_VOL_LOOKBACK_DAYS = 20
MIN_VOL_FLOOR = 0.05
MIN_TREND_R2_WINDOW = 5
DEFAULT_SWEEP_LOOKBACKS = (20, 40, 60, 90, 120, 150, 200)
STRATEGY_PRESETS = (
    ("return_equal", "return", "equal"),
    ("vol_adjusted_equal", "vol_adjusted", "equal"),
    ("composite_equal", "composite", "equal"),
    ("trend_r2_inv_vol", "trend_r2", "inverse_vol"),
)

Weights = Dict[str, float]


@dataclass(frozen=True)
class RotationParams:
    lookback_days: int = 60
    rebalance: str = "weekly"
    top_n: int = 1
    switch_buffer_pct: float = 2.0
    cost_bps: float = 10.0  # one-way cost per unit of turnover
    scoring_mode: str = "return"
    weighting: str = "equal"
    vol_lookback_days: int = DEFAULT_VOL_LOOKBACK_DAYS

    def __post_init__(self) -> None:
        if self.lookback_days < 1:
            raise ValueError("lookback_days must be >= 1")
        if self.rebalance not in REBALANCE_CHOICES:
            raise ValueError(f"rebalance must be one of {REBALANCE_CHOICES}")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        if self.switch_buffer_pct < 0 or self.cost_bps < 0:
            raise ValueError("switch_buffer_pct and cost_bps must be >= 0")
        if self.scoring_mode not in SCORING_MODES:
            raise ValueError(f"scoring_mode must be one of {SCORING_MODES}")
        if self.weighting not in WEIGHTING_MODES:
            raise ValueError(f"weighting must be one of {WEIGHTING_MODES}")
        if self.vol_lookback_days < 2:
            raise ValueError("vol_lookback_days must be >= 2")


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


def annualized_volatility(
    closes: pd.DataFrame,
    vol_lookback_days: int = DEFAULT_VOL_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Trailing realized annualized volatility from daily simple returns."""
    if vol_lookback_days < 2:
        raise ValueError("vol_lookback_days must be >= 2")
    rets = closes.pct_change(fill_method=None)
    return rets.rolling(vol_lookback_days, min_periods=vol_lookback_days).std(ddof=0) * math.sqrt(
        TRADING_DAYS_PER_YEAR
    )


def trend_regression_stats(
    closes: pd.DataFrame,
    window: int,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Causal trailing log-price OLS annualized slope and R^2 per column."""
    w = max(int(window), MIN_TREND_R2_WINDOW)
    nan_df = pd.DataFrame(np.nan, index=closes.index, columns=closes.columns, dtype=float)
    if closes.empty or len(closes) < w or len(closes.columns) == 0:
        return nan_df, nan_df.copy()

    arr = closes.to_numpy(dtype=float)
    valid_pos = np.isfinite(arr) & (arr > 0)
    safe = np.where(valid_pos, arr, 1.0)
    logs = np.where(valid_pos, np.log(safe), np.nan)

    win = np.lib.stride_tricks.sliding_window_view(logs, window_shape=w, axis=0)
    win_valid = np.isfinite(win).all(axis=-1)
    win_clean = np.where(win_valid[..., None], win, 0.0)

    x_c = np.arange(w, dtype=float) - (w - 1) / 2.0
    s_xx = float(np.dot(x_c, x_c))
    s_xy = np.einsum("ncw,w->nc", win_clean, x_c)
    y_c = win_clean - win_clean.mean(axis=-1, keepdims=True)
    s_yy = np.sum(y_c * y_c, axis=-1)

    denom = s_xx * s_yy
    valid_denom = denom > 1e-18
    raw_r2 = np.where(valid_denom, (s_xy * s_xy) / np.where(valid_denom, denom, 1.0), 0.0)
    r2_tail = np.where(win_valid, np.clip(raw_r2, 0.0, 1.0), np.nan)
    slope_tail = s_xy / s_xx
    ann_slope_tail = np.where(
        win_valid,
        np.expm1(np.clip(slope_tail * TRADING_DAYS_PER_YEAR, -20.0, 20.0)),
        np.nan,
    )

    ann_slope_full = np.full(arr.shape, np.nan, dtype=float)
    r2_full = np.full(arr.shape, np.nan, dtype=float)
    ann_slope_full[w - 1 :] = ann_slope_tail
    r2_full[w - 1 :] = r2_tail
    return (
        pd.DataFrame(ann_slope_full, index=closes.index, columns=closes.columns),
        pd.DataFrame(r2_full, index=closes.index, columns=closes.columns),
    )


def composite_momentum_scores(closes: pd.DataFrame, lookback_days: int) -> pd.DataFrame:
    """Blended multi-horizon momentum (short/mid/long = 0.4/0.4/0.2)."""
    if lookback_days < 3:
        return momentum_scores(closes, lookback_days)

    horizon_weights: Dict[int, float] = {}
    for w, wt in (
        (max(5, lookback_days // 3), 0.4),
        (lookback_days, 0.4),
        (lookback_days * 2, 0.2),
    ):
        horizon_weights[w] = horizon_weights.get(w, 0.0) + wt

    total = pd.DataFrame(0.0, index=closes.index, columns=closes.columns, dtype=float)
    valid = pd.DataFrame(True, index=closes.index, columns=closes.columns, dtype=bool)
    for w, wt in horizon_weights.items():
        component = momentum_scores(closes, w)
        valid &= component.notna()
        total = total + component.fillna(0.0) * wt
    return total.where(valid)


def compute_factor_scores(closes: pd.DataFrame, params: RotationParams) -> pd.DataFrame:
    """Compute causal ranking scores according to ``params.scoring_mode``."""
    if params.scoring_mode == "return":
        return momentum_scores(closes, params.lookback_days)
    if params.scoring_mode == "vol_adjusted":
        raw = momentum_scores(closes, params.lookback_days)
        vol = annualized_volatility(closes, params.vol_lookback_days)
        return raw.where(raw.notna() & vol.notna()) / vol.clip(lower=MIN_VOL_FLOOR)
    if params.scoring_mode == "composite":
        return composite_momentum_scores(closes, params.lookback_days)
    if params.scoring_mode == "trend_r2":
        ann_slope, r2 = trend_regression_stats(closes, params.lookback_days)
        return ann_slope * r2
    raise ValueError(f"scoring_mode must be one of {SCORING_MODES}")


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


def _unique_risk_assets(closes: pd.DataFrame, risk_assets: Sequence[str]) -> List[str]:
    """Preserve caller ordering while dropping duplicates and missing symbols."""
    return list(dict.fromkeys(c for c in risk_assets if c in closes.columns))


def select_holdings(
    scores: pd.Series,
    current: Sequence[str],
    params: RotationParams,
) -> Tuple[str, ...]:
    """Pick up to ``top_n`` risk assets; an empty tuple means fully defensive."""
    eligible = scores.replace([math.inf, -math.inf], math.nan).dropna()
    eligible = eligible[eligible > 0].sort_values(ascending=False)
    if eligible.empty:
        return ()

    slots = min(params.top_n, len(eligible))
    anchor = float(eligible.iloc[slots - 1])
    if params.scoring_mode in ("vol_adjusted", "trend_r2"):
        cutoff = anchor * max(0.0, 1.0 - params.switch_buffer_pct / 100.0)
    else:
        cutoff = anchor - params.switch_buffer_pct / 100.0
    kept = [code for code in current if code in eligible.index and eligible[code] >= cutoff]
    kept = sorted(kept, key=lambda code: eligible[code], reverse=True)[:slots]
    newcomers = [code for code in eligible.index if code not in kept][: slots - len(kept)]
    chosen = kept + newcomers
    return tuple(sorted(chosen, key=lambda code: eligible[code], reverse=True))


def holdings_to_weights(
    holdings: Sequence[str],
    top_n: int,
    safe_asset: Optional[str],
    *,
    weighting: str = "equal",
    vols: Optional[pd.Series] = None,
) -> Weights:
    """Allocate risk budget across ``holdings`` and route unfilled slots to safe/cash."""
    if weighting not in WEIGHTING_MODES:
        raise ValueError(f"weighting must be one of {WEIGHTING_MODES}")
    slot = 1.0 / top_n
    weights: Weights = {}
    if holdings:
        risk_budget = slot * len(holdings)
        use_inverse_vol = False
        inv_vols: Dict[str, float] = {}
        if weighting == "inverse_vol" and vols is not None:
            for code in holdings:
                v = vols.get(code)
                if v is not None and pd.notna(v) and math.isfinite(float(v)) and float(v) > 0:
                    inv_vols[code] = 1.0 / max(float(v), 1e-6)
                else:
                    inv_vols.clear()
                    break
            use_inverse_vol = len(inv_vols) == len(holdings)

        if use_inverse_vol:
            inv_sum = sum(inv_vols.values())
            weights = {code: risk_budget * inv_vols[code] / inv_sum for code in holdings}
        else:
            weights = {code: slot for code in holdings}

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
    risk = _unique_risk_assets(closes, risk_assets)
    if not risk:
        raise ValueError("no risk asset has price data")
    if safe_asset and safe_asset not in closes.columns:
        safe_asset = None

    frame = prepare_closes(closes)
    quoted = _valid_closes(closes)
    scores = compute_factor_scores(frame[risk], params).where(quoted[risk].notna())
    vols = (
        annualized_volatility(frame[risk], params.vol_lookback_days).where(quoted[risk].notna())
        if params.weighting == "inverse_vol"
        else None
    )
    valid_rows = scores.notna().any(axis=1)
    if not valid_rows.any():
        raise ValueError(
            f"not enough history for lookback_days={params.lookback_days}"
        )
    start = valid_rows.idxmax()
    frame = frame.loc[start:]
    scores = scores.loc[start:]
    quoted = quoted.loc[start:]
    if vols is not None:
        vols = vols.loc[start:]
    # Carry the last known mark for valuation, never for execution. On quote
    # recovery the full change from that mark belongs to existing holders.
    valuation = _valid_closes(closes).ffill().loc[start:]
    daily_returns = valuation.pct_change(fill_method=None).fillna(0.0)

    rebal = set(rebalance_dates(frame.index, params.rebalance))
    dates = list(frame.index)
    cost_rate = params.cost_bps / 10000.0

    weights: Weights = {CASH: 1.0}
    holdings: Tuple[str, ...] = ()
    pending: Optional[Tuple[int, pd.Timestamp, Tuple[str, ...], Optional[pd.Series]]] = None
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
            _, signal_day, new_holdings, signal_vols = pending
            pending = None
            available_safe = safe_asset if safe_asset and pd.notna(quoted.loc[day, safe_asset]) else None
            target = holdings_to_weights(
                new_holdings,
                params.top_n,
                available_safe,
                weighting=params.weighting,
                vols=signal_vols,
            )
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
            signal_vols = vols.loc[day] if vols is not None else None
            pending = (i + EXECUTION_LAG_DAYS, day, chosen, signal_vols)

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


def compute_extended_metrics(
    equity: pd.Series,
    benchmark_equity: Optional[pd.Series] = None,
    trades: Optional[Sequence[Trade]] = None,
) -> Dict[str, float]:
    """Institutional risk/turnover metrics layered atop ``compute_metrics``."""
    base = compute_metrics(equity)
    out = dict(base)
    out.update(
        {
            "sortino": math.nan,
            "max_drawdown_days": math.nan,
            "monthly_win_rate": math.nan,
            "excess_cagr": math.nan,
            "information_ratio": math.nan,
            "annual_turnover": math.nan,
            "trade_count": float(len(trades)) if trades is not None else math.nan,
        }
    )

    series = equity.dropna()
    if len(series) < 2 or series.iloc[0] <= 0:
        return out

    rets = series.pct_change(fill_method=None).dropna()
    if len(rets) > 0:
        downside = np.minimum(rets.to_numpy(dtype=float), 0.0)
        downside_vol = float(np.sqrt(np.mean(downside * downside)) * math.sqrt(TRADING_DAYS_PER_YEAR))
        if math.isfinite(downside_vol) and downside_vol > 0:
            out["sortino"] = float(rets.mean() * TRADING_DAYS_PER_YEAR / downside_vol)

    underwater = (series < series.cummax()).to_numpy(dtype=bool)
    cur_streak = 0
    max_streak = 0
    for is_underwater in underwater:
        if is_underwater:
            cur_streak += 1
            if cur_streak > max_streak:
                max_streak = cur_streak
        else:
            cur_streak = 0
    out["max_drawdown_days"] = float(max_streak)

    month_groups = series.groupby([series.index.year, series.index.month])
    month_counts = month_groups.size()
    month_end = month_groups.last()
    if len(month_end) > 0:
        prev = month_end.shift(1)
        prev.iloc[0] = series.iloc[0]
        monthly_rets = month_end / prev - 1.0
        # A curve starting on a month-end session has zero holding days in that initial month.
        if len(monthly_rets) > 1 and int(month_counts.iloc[0]) == 1:
            monthly_rets = monthly_rets.iloc[1:]
        out["monthly_win_rate"] = float((monthly_rets > 0).mean())

    years = (series.index[-1] - series.index[0]).days / DAYS_PER_YEAR
    if trades is not None and years > 0:
        out["annual_turnover"] = float(sum(t.turnover for t in trades) / years)

    if benchmark_equity is not None:
        bench_metrics = compute_metrics(benchmark_equity)
        if not math.isnan(base["cagr"]) and not math.isnan(bench_metrics["cagr"]):
            out["excess_cagr"] = float(base["cagr"] - bench_metrics["cagr"])

        joined = pd.concat([series, benchmark_equity.dropna()], axis=1).dropna()
        if len(joined) >= 2:
            joined.columns = ["strategy", "benchmark"]
            s_rets = joined["strategy"].pct_change(fill_method=None).dropna()
            b_rets = joined["benchmark"].pct_change(fill_method=None).dropna()
            active = (s_rets - b_rets).dropna()
            if len(active) > 0:
                tracking_error = float(active.std(ddof=0) * math.sqrt(TRADING_DAYS_PER_YEAR))
                if tracking_error > 0:
                    out["information_ratio"] = float(
                        active.mean() * TRADING_DAYS_PER_YEAR / tracking_error
                    )

    return out


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
    risk = _unique_risk_assets(frame, risk_assets)
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
            scoring_mode=params.scoring_mode,
            weighting=params.weighting,
            vol_lookback_days=params.vol_lookback_days,
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
    """Factor scores on the latest bar, sorted high to low (NaN last)."""
    frame = prepare_closes(closes)
    risk = _unique_risk_assets(frame, risk_assets)
    scores = compute_factor_scores(frame[risk], params)
    scores = scores.where(_valid_closes(closes)[risk].notna())
    as_of = frame.index[-1]
    return as_of, scores.loc[as_of].sort_values(ascending=False, na_position="last")


def factor_snapshot(
    closes: pd.DataFrame,
    risk_assets: Sequence[str],
    params: RotationParams,
) -> Tuple[pd.Timestamp, pd.DataFrame]:
    """Latest-bar factor breakdown for each asset in ``risk_assets``, ranked by ``score``."""
    frame = prepare_closes(closes)
    quoted = _valid_closes(closes)
    risk = _unique_risk_assets(frame, risk_assets)
    if not risk or frame.empty:
        raise ValueError("no risk asset has price data")

    as_of = frame.index[-1]
    latest_valid = quoted[risk].loc[as_of].notna()

    scores = compute_factor_scores(frame[risk], params).loc[as_of].where(latest_valid)
    ret_20d = momentum_scores(frame[risk], 20).loc[as_of].where(latest_valid)
    ret_lookback = momentum_scores(frame[risk], params.lookback_days).loc[as_of].where(latest_valid)
    ret_120d = momentum_scores(frame[risk], 120).loc[as_of].where(latest_valid)
    ann_vol = annualized_volatility(frame[risk], params.vol_lookback_days).loc[as_of].where(latest_valid)
    _, trend_r2_df = trend_regression_stats(frame[risk], params.lookback_days)
    trend_r2 = trend_r2_df.loc[as_of].where(latest_valid)
    vol_adj_score = (ret_lookback / ann_vol.clip(lower=MIN_VOL_FLOOR)).where(
        ret_lookback.notna() & ann_vol.notna()
    )

    df = pd.DataFrame(
        {
            "score": scores,
            "ret_20d": ret_20d,
            "ret_lookback": ret_lookback,
            "ret_120d": ret_120d,
            "ann_vol": ann_vol,
            "trend_r2": trend_r2,
            "vol_adj_score": vol_adj_score,
        },
        index=risk,
    ).sort_values(by="score", ascending=False, na_position="last", kind="mergesort")
    df["eligible"] = df["score"].notna() & (df["score"] > 0)
    return as_of, df


def compare_strategies(
    closes: pd.DataFrame,
    risk_assets: Sequence[str],
    safe_asset: Optional[str],
    params: RotationParams,
    min_years: float = 0.0,
) -> List[Tuple[str, Dict[str, float]]]:
    """Compare all built-in factor/weighting presets (plus active custom combo) on a common window."""
    frame = prepare_closes(closes)
    risk = _unique_risk_assets(frame, risk_assets)
    if not risk or frame.empty:
        return []

    specs = list(STRATEGY_PRESETS)
    preset_combos = {(mode, wt) for _, mode, wt in STRATEGY_PRESETS}
    if (params.scoring_mode, params.weighting) not in preset_combos:
        specs.append(("current", params.scoring_mode, params.weighting))

    runs: List[Tuple[str, BacktestResult]] = []
    for preset_key, scoring_mode, weighting in specs:
        preset_params = RotationParams(
            lookback_days=params.lookback_days,
            rebalance=params.rebalance,
            top_n=params.top_n,
            switch_buffer_pct=params.switch_buffer_pct,
            cost_bps=params.cost_bps,
            scoring_mode=scoring_mode,
            weighting=weighting,
            vol_lookback_days=params.vol_lookback_days,
        )
        try:
            runs.append((preset_key, run_backtest(closes, risk, safe_asset, preset_params)))
        except ValueError:
            continue

    last_day = frame.index[-1]
    runs = [
        (preset_key, result)
        for preset_key, result in runs
        if (last_day - result.equity.index[0]).days / DAYS_PER_YEAR >= min_years
    ]
    if not runs:
        return []

    common_start = max(result.equity.index[0] for _, result in runs)
    results: List[Tuple[str, Dict[str, float]]] = []
    for preset_key, result in runs:
        sub_equity = result.equity.loc[common_start:]
        if sub_equity.empty or float(sub_equity.iloc[0]) <= 0:
            continue
        sub_equity = sub_equity / float(sub_equity.iloc[0])
        sub_bench = result.benchmark_equity.loc[common_start:]
        if not sub_bench.empty and float(sub_bench.iloc[0]) > 0:
            sub_bench = sub_bench / float(sub_bench.iloc[0])
        sub_trades = [t for t in result.trades if t.exec_date >= common_start]
        results.append(
            (preset_key, compute_extended_metrics(sub_equity, sub_bench, sub_trades))
        )
    return results
