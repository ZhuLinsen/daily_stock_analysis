# -*- coding: utf-8 -*-
"""Tests for multi-factor ETF rotation scoring, risk-parity weighting, and quant metrics."""

from __future__ import annotations

import math
from types import SimpleNamespace
import tracemalloc
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
    assert ann_slope.iloc[-1]["SMOOTH"] == pytest.approx(0.002 * 244, abs=1e-9)
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


def _next_bday(day):
    return (pd.Timestamp(day) + pd.offsets.BDay(1)).date()


def test_missing_quotes_do_not_fabricate_volatility_for_inverse_vol_or_vol_adjusted():
    # 25 business days from Mon 2024-01-01 ends on Fri 2024-02-02 (rebalance day).
    idx = _dates(25, "2024-01-01")
    a_ret = np.full(25, 0.004)
    b_ret = np.tile([0.009, -0.004], 13)[:25]
    closes = pd.DataFrame({"A": _path(a_ret), "B": _path(b_ret)}, index=idx)
    # Remove 5 consecutive trading days before Friday so A recovers on idx[-1] via ffill for momentum only.
    closes.iloc[-6:-1, closes.columns.get_loc("A")] = np.nan

    inv_vol_params = RotationParams(
        lookback_days=10,
        vol_lookback_days=6,
        top_n=2,
        cost_bps=0,
        scoring_mode="return",
        weighting="inverse_vol",
    )
    _, snap = factor_snapshot(closes, ["A", "B"], inv_vol_params)
    assert pd.isna(snap.loc["A", "ann_vol"])
    assert pd.notna(snap.loc["B", "ann_vol"])

    report = build_report(closes, ["A", "B"], None, inv_vol_params, names={}, next_session=_next_bday)
    assert report.target_weights == {"A": pytest.approx(0.5), "B": pytest.approx(0.5)}

    extended = pd.concat(
        [closes, pd.DataFrame({"A": [closes.iloc[-1, 0] * 1.001], "B": [closes.iloc[-1, 1] * 1.001]}, index=[idx[-1] + pd.offsets.BDay(1)])]
    )
    bt = run_backtest(extended, ["A", "B"], None, inv_vol_params)
    assert bt.trades[-1].to_weights == {"A": pytest.approx(0.5), "B": pytest.approx(0.5)}

    vol_adj_params = RotationParams(
        lookback_days=10,
        vol_lookback_days=6,
        top_n=2,
        scoring_mode="vol_adjusted",
        weighting="equal",
    )
    _, vol_adj_snap = factor_snapshot(closes, ["A", "B"], vol_adj_params)
    assert pd.isna(vol_adj_snap.loc["A", "score"])
    assert bool(vol_adj_snap.loc["A", "eligible"]) is False


def test_safe_asset_in_risk_pool_triggers_inverse_vol_rebalance_and_updates_holdings():
    # 20 business days = 4 Mon..Fri weeks (Fri indexes: 4, 9, 14, 19).
    idx = _dates(20, "2024-01-01")
    a_ret = np.tile([0.025, -0.012], 10)
    safe_ret = np.r_[
        np.tile([-0.0006, -0.0004], 8)[:15],  # weeks 1..3: slightly negative 5d momentum -> defensive only
        np.tile([0.0006, 0.0004], 3)[:5],     # week 4: positive 5d momentum with ultra-low volatility
    ]
    closes = pd.DataFrame({"A": _path(a_ret), "SAFE": _path(safe_ret)}, index=idx)
    params = RotationParams(
        lookback_days=5,
        vol_lookback_days=5,
        top_n=2,
        cost_bps=0,
        scoring_mode="return",
        weighting="inverse_vol",
    )

    report = build_report(closes, ["A", "SAFE"], "SAFE", params, names={}, next_session=_next_bday)
    assert "**需要调仓**" in report.markdown
    assert report.target_weights["SAFE"] > 0.7
    assert report.target_weights["A"] < 0.3

    extended = pd.concat(
        [closes, pd.DataFrame({"A": [closes.iloc[-1, 0]], "SAFE": [closes.iloc[-1, 1]]}, index=[idx[-1] + pd.offsets.BDay(1)])]
    )
    bt = run_backtest(extended, ["A", "SAFE"], "SAFE", params)
    assert set(bt.final_holdings) == {"A", "SAFE"}
    assert bt.final_weights["SAFE"] > 0.7
    assert len(bt.trades) >= 2


def test_tied_momentum_report_matches_backtest_with_17_etfs():
    codes = [f"5103{i:02d}" for i in range(1, 18)]
    idx = _dates(16, "2024-01-01")  # idx[14] = Fri 2024-01-19, idx[15] = Mon 2024-01-22
    ret = np.full(16, -0.002)
    ret[14] = 0.05  # Exact tie across all 17 ETFs turns 5d return positive on rebalance Friday.
    ret[15] = 0.001
    closes = pd.DataFrame({code: _path(ret) for code in codes}, index=idx)
    params = RotationParams(lookback_days=5, top_n=2, cost_bps=0, scoring_mode="return", weighting="equal")

    report = build_report(closes.iloc[:15], codes, None, params, names={})
    bt = run_backtest(closes, codes, None, params)
    assert tuple(report.target_weights.keys()) == ("510301", "510302")
    assert set(report.target_weights) == set(bt.trades[-1].to_weights)


def test_compare_strategies_treats_common_start_trades_symmetrically_under_high_cost():
    n = 400
    idx = _dates(n, "2020-01-06")
    rebal = rebalance_dates(idx, "weekly")
    switch_sig = rebal[8]  # Fri 2020-03-06 (bar 44 > 40) -> exec Mon 2020-03-09 (common_start)
    s_pos = idx.get_loc(switch_sig)

    r_a = np.full(n, 0.005)
    r_a[s_pos:] = -0.02
    r_a[s_pos] = -0.35

    r_b = np.full(n, -0.002)
    r_b[s_pos] = 0.35  # Flips both return_equal (A->B) and composite_equal (CASH->B) at common_start
    r_b[s_pos + 1 :] = 0.003

    closes = pd.DataFrame({"A": _path(r_a), "B": _path(r_b)}, index=idx)
    params = RotationParams(lookback_days=20, top_n=1, cost_bps=500, scoring_mode="return", weighting="equal")

    rows = dict(compare_strategies(closes, ["A", "B"], None, params, min_years=1.0))
    assert "return_equal" in rows and "composite_equal" in rows
    ret_m = rows["return_equal"]
    comp_m = rows["composite_equal"]
    assert ret_m["trade_count"] == pytest.approx(0.0)
    assert comp_m["trade_count"] == pytest.approx(0.0)
    assert ret_m["annual_turnover"] == pytest.approx(0.0)
    assert comp_m["annual_turnover"] == pytest.approx(0.0)
    assert ret_m["total_return"] == pytest.approx(comp_m["total_return"], rel=1e-9)
    assert ret_m["cagr"] == pytest.approx(comp_m["cagr"], rel=1e-9)


def test_trend_regression_stats_and_factor_snapshot_stay_low_memory_on_large_panel():
    n_rows, n_cols, window = 2000, 80, 500
    idx = _dates(n_rows, "2018-01-01")
    cols = [f"ETF{i:02d}" for i in range(n_cols)]
    t = np.arange(n_rows, dtype=float)
    data = {col: np.exp(0.0005 * t + 0.02 * np.sin(0.05 * t + i * 0.1)) for i, col in enumerate(cols)}
    closes = pd.DataFrame(data, index=idx)

    tracemalloc.start()
    try:
        _, r2_df = trend_regression_stats(closes, window=window)
        _, snap = factor_snapshot(
            closes,
            cols,
            RotationParams(lookback_days=window, scoring_mode="return", weighting="equal"),
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < 64 * 1024 * 1024
    # Check exact R^2 value on trailing 500 bars of ETF00.
    y = np.log(closes["ETF00"].iloc[-window:].to_numpy(dtype=float))
    x_c = np.arange(window, dtype=float) - (window - 1) / 2.0
    y_c = y - y.mean()
    expected_r2 = float((y_c @ x_c) ** 2 / ((x_c @ x_c) * (y_c @ y_c)))
    assert r2_df.iloc[-1]["ETF00"] == pytest.approx(expected_r2, abs=1e-9)
    assert snap.loc["ETF00", "trend_r2"] == pytest.approx(expected_r2, abs=1e-9)


def test_equal_weight_safe_asset_promotion_does_not_rebalance_drift():
    # 25 business days starting Mon 2024-01-01 (Fridays: idx 4, 9, 14, 19, 24).
    idx = _dates(25, "2024-01-01")
    a_ret = np.full(25, 0.01)
    safe_ret = np.r_[
        np.full(15, -0.0005),  # weeks 1..3: negative 5d return -> SAFE held only as defensive filler
        np.full(10, 0.003),    # week 4..5: positive 5d return -> SAFE qualifies as formal risk holding
    ]
    closes = pd.DataFrame({"A": _path(a_ret), "SAFE": _path(safe_ret)}, index=idx)
    params = RotationParams(
        lookback_days=5,
        top_n=2,
        cost_bps=10.0,
        scoring_mode="return",
        weighting="equal",
    )

    report = build_report(closes.iloc[:20], ["A", "SAFE"], "SAFE", params, names={}, next_session=_next_bday)
    assert "**需要调仓**" not in report.markdown
    assert "维持不变" in report.markdown

    bt = run_backtest(closes, ["A", "SAFE"], "SAFE", params)
    assert len(bt.trades) == 1
    assert set(bt.final_weights) == {"A", "SAFE"}
    assert bt.final_weights["A"] > 0.52

    # Missing vol forces inverse_vol to fall back to 50/50 equal targets; it must not rebalance drift either.
    inv_fallback = RotationParams(
        lookback_days=5,
        vol_lookback_days=50,
        top_n=2,
        cost_bps=10.0,
        scoring_mode="return",
        weighting="inverse_vol",
    )
    bt_fallback = run_backtest(closes, ["A", "SAFE"], "SAFE", inv_fallback)
    assert len(bt_fallback.trades) == 1


def test_trend_r2_uses_linear_annualized_log_slope_without_expm1_inversion():
    window = 60
    idx = _dates(window + 1, "2024-01-01")
    t = np.arange(window, dtype=float)
    x_c = t - (window - 1) / 2.0
    s_xx = float(np.dot(x_c, x_c))

    # Asset A: exact daily log slope 0.003, R^2 = 1.0 -> 0.003 * 244 = 0.732
    log_a = 0.003 * t
    # Asset B: daily log slope 0.005, orthogonal sinusoidal noise scaled for R^2 = 0.5 -> 0.005 * 244 * 0.5 = 0.610
    noise = np.sin(2.0 * np.pi * t / window)
    noise -= noise.mean()
    noise -= (np.dot(noise, x_c) / s_xx) * x_c
    target_noise_ss = (0.005 ** 2) * s_xx
    noise *= math.sqrt(target_noise_ss / float(np.dot(noise, noise)))
    log_b = 0.005 * x_c + noise
    log_b -= log_b[0]

    # Append 1 execution bar carrying forward last step safely for run_backtest fill.
    log_a_full = np.r_[log_a, log_a[-1] + 0.003]
    log_b_full = np.r_[log_b, log_b[-1] + 0.005]
    closes = pd.DataFrame({"A": np.exp(log_a_full), "B": np.exp(log_b_full)}, index=idx)
    assert float(closes.pct_change().abs().max().max()) < 0.045

    params = RotationParams(lookback_days=window, top_n=1, cost_bps=0, scoring_mode="trend_r2", weighting="equal")
    scores_row = compute_factor_scores(closes.iloc[:window], params).iloc[-1]
    assert scores_row["A"] == pytest.approx(0.003 * 244, rel=1e-6)
    assert scores_row["B"] == pytest.approx(0.005 * 244 * 0.5, rel=1e-4)
    assert scores_row["A"] > scores_row["B"]

    report = build_report(closes.iloc[:window], ["A", "B"], None, params, names={})
    assert list(report.target_weights.keys()) == ["A"]
    bt = run_backtest(closes, ["A", "B"], None, params)
    assert bt.trades[-1].to_weights == {"A": 1.0}


def test_identical_strategy_and_benchmark_report_nan_information_ratio():
    n = 650
    idx = _dates(n, "2022-01-03")
    r = 0.0015 + 0.0008 * np.sin(np.arange(n) * 0.25)
    closes = pd.DataFrame({"A": _path(r)}, index=idx)
    params = RotationParams(lookback_days=20, top_n=1, cost_bps=0.0, scoring_mode="return", weighting="equal")

    bt = run_backtest(closes, ["A"], None, params)
    ext = compute_extended_metrics(bt.equity, bt.benchmark_equity, bt.trades)
    assert len(bt.trades) == 1
    assert ext["excess_cagr"] == pytest.approx(0.0)
    assert math.isnan(ext["information_ratio"])

    report = build_report(closes, ["A"], None, params, names={"A": "单一ETF"})
    assert "| 信息比率 (IR) | - | - |" in report.markdown


def test_compare_strategies_with_precomputed_matches_fresh_computation():
    n = 400
    idx = _dates(n, "2021-01-01")
    half = n // 2
    r_a = np.r_[np.full(half, 0.003), np.full(n - half, -0.002)]
    r_b = -r_a + 0.0005
    closes = pd.DataFrame({"A": _path(r_a), "B": _path(r_b), "SAFE": _path(np.full(n, 0.0001))}, index=idx)
    params = RotationParams(lookback_days=40, top_n=2, scoring_mode="return", weighting="equal")

    bt = run_backtest(closes, ["A", "B"], "SAFE", params)
    direct = compare_strategies(closes, ["A", "B"], "SAFE", params, min_years=1.0)
    reused = compare_strategies(closes, ["A", "B"], "SAFE", params, min_years=1.0, precomputed=bt)
    assert dict(reused).keys() == dict(direct).keys()
    for key in dict(direct):
        assert dict(reused)[key] == pytest.approx(dict(direct)[key], nan_ok=True)


def test_inverse_vol_rebalances_when_same_holdings_vol_reverses():
    # 11 business days: Fri idx=4 (week 1 signal), Mon idx=5 (fill), Fri idx=9 (week 2 signal), Mon idx=10 (fill)
    idx = _dates(11, "2024-01-01")
    r_a = np.array([0.01, 0.001, 0.003, 0.001, 0.003, 0.01, 0.05, -0.04, 0.06, 0.03, 0.0])
    r_b = np.array([0.01, 0.08, -0.05, 0.07, 0.04, 0.01, 0.001, 0.003, 0.001, 0.003, 0.0])
    closes = pd.DataFrame({"A": _path(r_a), "B": _path(r_b)}, index=idx)
    params = RotationParams(
        lookback_days=3,
        vol_lookback_days=4,
        top_n=2,
        cost_bps=0,
        scoring_mode="return",
        weighting="inverse_vol",
    )

    report = build_report(closes.iloc[:10], ["A", "B"], None, params, names={}, next_session=_next_bday)
    assert "**需要调仓**" in report.markdown
    assert report.target_weights["B"] > 0.85
    assert report.target_weights["A"] < 0.15

    bt = run_backtest(closes, ["A", "B"], None, params)
    assert len(bt.trades) == 2
    assert bt.trades[0].to_weights["A"] > 0.85
    assert bt.final_weights["B"] > 0.85


def test_inverse_vol_rebalances_on_equal_weight_fallback_after_midweek_gap():
    idx = _dates(11, "2024-01-01")
    r_a = np.array([0.01, 0.001, 0.003, 0.001, 0.003, 0.002, 0.001, 0.003, 0.001, 0.003, 0.0])
    r_b = np.array([0.01, 0.08, -0.05, 0.07, 0.04, 0.002, 0.001, 0.003, 0.001, 0.003, 0.0])
    closes = pd.DataFrame({"A": _path(r_a), "B": _path(r_b)}, index=idx)
    # Missing Tuesday quote breaks B's 4-day volatility window on Friday while Friday & Monday have valid quotes.
    closes.iloc[6, closes.columns.get_loc("B")] = np.nan
    params = RotationParams(
        lookback_days=3,
        vol_lookback_days=4,
        top_n=2,
        cost_bps=0,
        scoring_mode="return",
        weighting="inverse_vol",
    )

    report = build_report(closes.iloc[:10], ["A", "B"], None, params, names={}, next_session=_next_bday)
    assert "**需要调仓**" in report.markdown
    assert report.target_weights == pytest.approx({"A": 0.5, "B": 0.5})

    bt = run_backtest(closes, ["A", "B"], None, params)
    assert len(bt.trades) == 2
    assert bt.trades[0].to_weights["A"] > 0.85
    assert bt.final_weights == pytest.approx({"A": 0.5, "B": 0.5})


def test_zero_return_equal_six_etfs_reports_zero_max_drawdown_days():
    idx = _dates(366, "2022-01-03")
    cols = [f"ETF{i}" for i in range(6)]
    rets = np.r_[np.full(6, 0.01), np.zeros(360)]
    closes = pd.DataFrame({c: _path(rets) for c in cols}, index=idx)
    params = RotationParams(
        lookback_days=5,
        top_n=6,
        cost_bps=0.0,
        scoring_mode="return",
        weighting="equal",
    )

    bt = run_backtest(closes, cols, None, params)
    ext = compute_extended_metrics(bt.equity, bt.benchmark_equity, bt.trades)
    assert ext["max_drawdown_days"] == 0.0
    report = build_report(closes, cols, None, params, names={})
    assert "| 最长回撤天数 | 0 天 | 0 天 |" in report.markdown
