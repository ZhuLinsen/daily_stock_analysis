# -*- coding: utf-8 -*-
"""Tests for multi-factor ETF rotation scoring, risk-parity weighting, and quant metrics."""

from __future__ import annotations

import math
from types import SimpleNamespace
import warnings

import numpy as np
import pandas as pd
import pytest

from src.core.etf_rotation import (
    CASH,
    SCORING_MODES,
    STRATEGY_PRESETS,
    RotationParams,
    annualized_volatility,
    compare_strategies,
    composite_momentum_scores,
    compute_extended_metrics,
    compute_factor_scores,
    compute_metrics,
    factor_snapshot,
    holdings_to_weights,
    parameter_sweep,
    rebalance_dates,
    run_backtest,
    select_holdings,
    trend_regression_stats,
)
from src.services.etf_rotation_service import build_report, params_from_config


def _dates(n: int, start: str = "2020-01-01") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _path(daily_returns: np.ndarray, start: float = 1.0) -> np.ndarray:
    return start * np.cumprod(1.0 + daily_returns)


def test_quant_params_reject_invalid_scoring_weighting_and_vol_window():
    with pytest.raises(ValueError, match="scoring_mode"):
        RotationParams(scoring_mode="unknown")
    with pytest.raises(ValueError, match="weighting"):
        RotationParams(weighting="risk_parity")
    with pytest.raises(ValueError, match="vol_lookback_days"):
        RotationParams(vol_lookback_days=1)


def test_vol_adjusted_prefers_smooth_uptrend_and_excludes_negative_returns():
    n = 90
    idx = _dates(n)
    smooth_ret = np.full(n, 0.002)
    # Match total return over 60 bars while carrying high daily volatility.
    zig = np.tile([0.032, -0.0272], n // 2)[:n]
    down_ret = np.full(n, -0.002)

    closes = pd.DataFrame(
        {
            "SMOOTH": _path(smooth_ret),
            "CHOPPY": _path(zig),
            "DOWN": _path(down_ret),
        },
        index=idx,
    )
    params = RotationParams(lookback_days=40, scoring_mode="vol_adjusted", vol_lookback_days=20)
    scores = compute_factor_scores(closes, params).iloc[-1]

    assert scores["SMOOTH"] > scores["CHOPPY"] > 0
    assert scores["DOWN"] < 0


def test_composite_momentum_blends_horizons_and_requires_longest_window():
    n = 140
    idx = _dates(n)
    r = np.linspace(0.0005, 0.0025, n)
    closes = pd.DataFrame({"A": _path(r)}, index=idx)

    comp = composite_momentum_scores(closes, lookback_days=60)
    # Long horizon = 120 bars -> bar index 119 still lacks shift(120); bar index 120 has all 3.
    assert pd.isna(comp.iloc[119, 0])
    assert pd.notna(comp.iloc[120, 0])

    short_ret = closes.iloc[-1, 0] / closes.iloc[-21, 0] - 1.0
    mid_ret = closes.iloc[-1, 0] / closes.iloc[-61, 0] - 1.0
    long_ret = closes.iloc[-1, 0] / closes.iloc[-121, 0] - 1.0
    expected = 0.4 * short_ret + 0.4 * mid_ret + 0.2 * long_ret
    assert comp.iloc[-1, 0] == pytest.approx(expected)


def test_trend_regression_stats_identifies_clean_trend_and_penalizes_noise_without_warnings():
    n = 80
    idx = _dates(n)
    t = np.arange(n, dtype=float)
    smooth = np.exp(0.002 * t)
    # Same log endpoint, sinusoidal chop around the trend line.
    choppy = np.exp(0.002 * t + 0.15 * np.sin(np.linspace(0, 8 * np.pi, n)))
    flat = np.full(n, 10.0)
    down = np.exp(-0.002 * t)
    pre_listed = smooth.copy()
    pre_listed[:40] = np.nan

    closes = pd.DataFrame(
        {
            "SMOOTH": smooth,
            "CHOPPY": choppy,
            "FLAT": flat,
            "DOWN": down,
            "LATE": pre_listed,
        },
        index=idx,
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        ann_slope, r2 = trend_regression_stats(closes, window=40)
        scores = compute_factor_scores(closes, RotationParams(lookback_days=40, scoring_mode="trend_r2"))

    assert not caught
    assert r2.iloc[-1]["SMOOTH"] == pytest.approx(1.0, abs=1e-9)
    assert r2.iloc[-1]["CHOPPY"] < 0.7
    assert r2.iloc[-1]["FLAT"] == pytest.approx(0.0)
    assert scores.iloc[-1]["FLAT"] == pytest.approx(0.0)
    assert scores.iloc[-1]["DOWN"] < 0
    assert scores.iloc[-1]["SMOOTH"] > scores.iloc[-1]["CHOPPY"]
    # LATE only has 40 valid trailing observations at bar 79, so bars <= 78 remain NaN.
    assert pd.isna(scores.iloc[78]["LATE"])
    assert pd.notna(scores.iloc[79]["LATE"])


@pytest.mark.parametrize("scoring_mode", SCORING_MODES)
@pytest.mark.parametrize("weighting", ("equal", "inverse_vol"))
def test_no_lookahead_signal_day_jump_not_captured_across_modes(scoring_mode: str, weighting: str):
    n = 120
    index = _dates(n, "2024-01-01")
    rebal = rebalance_dates(index, "weekly")
    signal_day = rebal[15]
    pos = index.get_loc(signal_day)

    returns = np.zeros(n)
    # Use small alternating negative returns prior to signal_day so volatility is
    # strictly positive for inverse_vol while every factor stays negative until signal_day.
    returns[:pos] = np.where(np.arange(pos) % 2 == 0, -0.002, -0.001)
    returns[pos] = 0.15  # Signal bar jump flips scores positive but cannot fill until t+1.
    closes = pd.DataFrame({"A": _path(returns)}, index=index)

    params = RotationParams(
        lookback_days=10,
        vol_lookback_days=10,
        cost_bps=0,
        scoring_mode=scoring_mode,
        weighting=weighting,
    )
    result = run_backtest(closes, ["A"], None, params)
    assert result.trades and result.trades[0].signal_date == signal_day
    assert result.equity.iloc[-1] == pytest.approx(1.0)


def test_inverse_vol_weighting_allocates_higher_weight_to_lower_vol_and_falls_back():
    vols = pd.Series({"LOW_VOL": 0.10, "HIGH_VOL": 0.30, "ZERO_VOL": 0.0, "NAN_VOL": np.nan})

    weights = holdings_to_weights(
        ("LOW_VOL", "HIGH_VOL"),
        top_n=3,
        safe_asset="SAFE",
        weighting="inverse_vol",
        vols=vols,
    )
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["SAFE"] == pytest.approx(1.0 / 3.0)
    assert weights["LOW_VOL"] + weights["HIGH_VOL"] == pytest.approx(2.0 / 3.0)
    assert weights["LOW_VOL"] == pytest.approx(3.0 * weights["HIGH_VOL"])

    # Missing or non-positive volatility cleanly falls back to equal slot weights.
    fallback = holdings_to_weights(
        ("LOW_VOL", "NAN_VOL"),
        top_n=2,
        safe_asset=None,
        weighting="inverse_vol",
        vols=vols,
    )
    assert fallback == {"LOW_VOL": 0.5, "NAN_VOL": 0.5}

    zero_fallback = holdings_to_weights(
        ("LOW_VOL", "ZERO_VOL"),
        top_n=2,
        safe_asset=None,
        weighting="inverse_vol",
        vols=vols,
    )
    assert zero_fallback == {"LOW_VOL": 0.5, "ZERO_VOL": 0.5}


def test_backtest_inverse_vol_uses_signal_day_vol_without_lookahead():
    n = 160
    idx = _dates(n, "2023-01-01")
    low_vol_a = np.tile([0.0025, 0.0015], n // 2)[:n]
    # B shares strong positive drift with higher noise so both qualify.
    high_vol_b = np.tile([0.015, -0.011], n // 2)[:n]
    closes = pd.DataFrame({"A": _path(low_vol_a), "B": _path(high_vol_b)}, index=idx)

    params = RotationParams(
        lookback_days=20,
        vol_lookback_days=20,
        top_n=2,
        cost_bps=0,
        scoring_mode="vol_adjusted",
        weighting="inverse_vol",
    )
    result = run_backtest(closes, ["A", "B"], None, params)
    assert result.trades
    first_trade = result.trades[0]
    sig_vols = annualized_volatility(closes, 20).loc[first_trade.signal_date]
    expected = holdings_to_weights(("A", "B"), top_n=2, safe_asset=None, weighting="inverse_vol", vols=sig_vols)
    assert first_trade.to_weights["A"] > first_trade.to_weights["B"]
    assert first_trade.to_weights["A"] == pytest.approx(expected["A"])
    assert first_trade.to_weights["B"] == pytest.approx(expected["B"])


def test_compute_extended_metrics_preserves_compute_metrics_and_computes_institutional_stats():
    idx = pd.to_datetime(
        ["2021-01-04", "2021-01-29", "2021-02-26", "2021-03-31", "2021-04-30"]
    )
    equity = pd.Series([1.0, 1.2, 0.9, 1.1, 1.44], index=idx)
    bench = pd.Series([1.0, 1.05, 1.0, 1.08, 1.12], index=idx)

    # compute_metrics remains untouched (6 keys exact).
    base = compute_metrics(equity)
    assert set(base.keys()) == {"total_return", "cagr", "ann_vol", "sharpe", "max_drawdown", "calmar"}

    ext = compute_extended_metrics(equity, benchmark_equity=bench, trades=[])
    assert ext["max_drawdown_days"] == pytest.approx(2.0)  # Feb & Mar below Jan peak 1.2
    # Months: Jan +20% (win), Feb -25% (loss), Mar +22.2% (win), Apr +30.9% (win) => 3/4.
    assert ext["monthly_win_rate"] == pytest.approx(0.75)
    assert math.isfinite(ext["sortino"])
    assert ext["excess_cagr"] > 0
    assert math.isfinite(ext["information_ratio"])
    assert ext["annual_turnover"] == pytest.approx(0.0)
    assert ext["trade_count"] == pytest.approx(0.0)


def test_factor_snapshot_masks_missing_latest_quote_and_ranks_descending():
    n = 140
    idx = _dates(n, "2023-01-01")
    closes = pd.DataFrame(
        {
            "STRONG": _path(np.full(n, 0.003)),
            "MID": _path(np.full(n, 0.001)),
            "MISSING_LAST": _path(np.full(n, 0.005)),
        },
        index=idx,
    )
    closes.iloc[-1, closes.columns.get_loc("MISSING_LAST")] = np.nan

    as_of, snap = factor_snapshot(
        closes,
        ["STRONG", "MID", "MISSING_LAST"],
        RotationParams(lookback_days=20, scoring_mode="trend_r2"),
    )
    assert as_of == idx[-1]
    assert list(snap.index) == ["STRONG", "MID", "MISSING_LAST"]
    assert list(snap.columns) == [
        "score",
        "ret_20d",
        "ret_lookback",
        "ret_120d",
        "ann_vol",
        "trend_r2",
        "vol_adj_score",
        "eligible",
    ]
    assert bool(snap.loc["STRONG", "eligible"]) is True
    assert bool(snap.loc["MISSING_LAST", "eligible"]) is False
    assert pd.isna(snap.loc["MISSING_LAST", "score"])
    assert pd.isna(snap.loc["MISSING_LAST", "ann_vol"])


def test_compare_strategies_aligns_presets_on_common_window_and_builds_quant_report():
    n = 500
    idx = _dates(n, "2021-01-01")
    half = n // 2
    r_a = np.r_[np.full(half, 0.003), np.full(n - half, -0.002)]
    r_b = -r_a + 0.0005
    closes = pd.DataFrame(
        {"A": _path(r_a), "B": _path(r_b), "SAFE": _path(np.full(n, 0.0001))},
        index=idx,
    )

    params = RotationParams(
        lookback_days=40,
        vol_lookback_days=20,
        top_n=2,
        scoring_mode="trend_r2",
        weighting="inverse_vol",
    )
    rows = compare_strategies(closes, ["A", "B"], "SAFE", params, min_years=1.0)
    assert [key for key, _ in rows] == [preset[0] for preset in STRATEGY_PRESETS]
    for _, metrics in rows:
        assert math.isfinite(metrics["cagr"])
        assert math.isfinite(metrics["sortino"])
        assert math.isfinite(metrics["annual_turnover"])

    report = build_report(
        closes,
        ["A", "B"],
        "SAFE",
        params,
        names={"A": "科技ETF", "B": "红利ETF", "SAFE": "货币ETF", CASH: "现金"},
    )
    for marker in (
        "## 最新信号",
        "趋势质量动量 (Slope×R²)",
        "反波动率风险平价",
        "趋势R²",
        "Sortino 比率",
        "月度胜率",
        "最长回撤天数",
        "信息比率 (IR)",
        "## 量化因子与配权横向对比",
        "趋势质量 R² + 反波动平价 ⬅ 当前",
    ):
        assert marker in report.markdown

    # Short history omits comparison table alongside other backtest sections.
    short_closes = closes.iloc[:180]
    short_report = build_report(short_closes, ["A", "B"], "SAFE", params, names={})
    assert "## 量化因子与配权横向对比" not in short_report.markdown


def test_params_from_config_defaults_safely_and_reads_optional_fields():
    legacy_cfg = SimpleNamespace(
        etf_rotation_lookback_days=60,
        etf_rotation_rebalance="weekly",
        etf_rotation_top_n=2,
        etf_rotation_switch_buffer_pct=2.0,
        etf_rotation_cost_bps=10.0,
    )
    legacy = params_from_config(legacy_cfg)
    assert legacy.scoring_mode == "return"
    assert legacy.weighting == "equal"
    assert legacy.vol_lookback_days == 20

    quant_cfg = SimpleNamespace(
        etf_rotation_lookback_days=60,
        etf_rotation_rebalance="monthly",
        etf_rotation_top_n=2,
        etf_rotation_switch_buffer_pct=2.0,
        etf_rotation_cost_bps=10.0,
        etf_rotation_scoring_mode="trend_r2",
        etf_rotation_weighting="inverse_vol",
        etf_rotation_vol_lookback_days=30,
    )
    quant = params_from_config(quant_cfg)
    assert quant.scoring_mode == "trend_r2"
    assert quant.weighting == "inverse_vol"
    assert quant.vol_lookback_days == 30

    normalized_cfg = SimpleNamespace(
        etf_rotation_lookback_days=60,
        etf_rotation_rebalance="weekly",
        etf_rotation_top_n=2,
        etf_rotation_switch_buffer_pct=2.0,
        etf_rotation_cost_bps=10.0,
        etf_rotation_scoring_mode=" Composite ",
        etf_rotation_weighting=" Inverse_Vol ",
        etf_rotation_vol_lookback_days=True,
    )
    normalized = params_from_config(normalized_cfg)
    assert normalized.scoring_mode == "composite"
    assert normalized.weighting == "inverse_vol"
    assert normalized.vol_lookback_days == 20


def test_select_holdings_rejects_nonfinite_scores():
    scores = pd.Series({"INF": math.inf, "NINF": -math.inf, "VALID": 0.12})
    assert select_holdings(scores, (), RotationParams()) == ("VALID",)


def test_compute_extended_metrics_skips_single_bar_starting_month_end():
    idx = pd.to_datetime(["2021-01-29", "2021-02-26", "2021-03-31"])
    equity = pd.Series([1.0, 1.1, 1.2], index=idx)
    ext = compute_extended_metrics(equity)
    assert ext["monthly_win_rate"] == pytest.approx(1.0)


def test_duplicate_risk_assets_and_custom_combo_comparison_and_rules():
    n = 500
    idx = _dates(n, "2021-01-01")
    half = n // 2
    r_a = np.r_[np.full(half, 0.003), np.full(n - half, -0.002)]
    r_b = -r_a + 0.0005
    closes = pd.DataFrame(
        {"A": _path(r_a), "B": _path(r_b), "SAFE": _path(np.full(n, 0.0001))},
        index=idx,
    )

    custom_params = RotationParams(
        lookback_days=40,
        vol_lookback_days=25,
        top_n=2,
        scoring_mode="composite",
        weighting="inverse_vol",
    )
    res = run_backtest(closes, ["A", "A", "B"], "SAFE", custom_params)
    assert not res.equity.empty
    _, snap = factor_snapshot(closes, ["A", "A", "B"], custom_params)
    assert list(snap.index) == ["A", "B"] or set(snap.index) == {"A", "B"}
    assert len(snap.index) == 2
    assert len(parameter_sweep(closes, ["A", "A", "B"], "SAFE", custom_params, lookbacks=(40,), min_years=1.0)) == 1

    cmp_rows = compare_strategies(closes, ["A", "A", "B"], "SAFE", custom_params, min_years=1.0)
    assert [key for key, _ in cmp_rows] == [p[0] for p in STRATEGY_PRESETS] + ["current"]

    custom_report = build_report(closes, ["A", "B"], "SAFE", custom_params, names={})
    assert "多周期复合动量 (短/中/长加权) + 反波动率风险平价 ⬅ 当前" in custom_report.markdown

    vol_adj_report = build_report(
        closes,
        ["A", "B"],
        "SAFE",
        RotationParams(lookback_days=40, vol_lookback_days=25, scoring_mode="vol_adjusted", weighting="equal"),
        names={},
    )
    assert "波动率窗口 25 日" in vol_adj_report.markdown
