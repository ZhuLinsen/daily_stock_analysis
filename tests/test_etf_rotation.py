# -*- coding: utf-8 -*-
"""Tests for the rule-based ETF rotation engine and service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from src.config import Config, DEFAULT_ETF_ROTATION_POOL
from src.core.etf_rotation import (
    CASH,
    EXECUTION_LAG_DAYS,
    RotationParams,
    annual_returns,
    compute_metrics,
    holdings_to_weights,
    is_rebalance_day,
    parameter_sweep,
    rebalance_dates,
    run_backtest,
    select_holdings,
)
from src.services.etf_rotation_service import (
    LoadedPrices,
    build_report,
    data_quality_warnings,
    load_closes,
    run_etf_rotation,
)


def _dates(n: int, start: str = "2020-01-01") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _path(daily_returns: np.ndarray, start: float = 1.0) -> np.ndarray:
    return start * np.cumprod(1.0 + daily_returns)


def _regime_closes(n: int = 400) -> pd.DataFrame:
    """A rises then falls, B falls then rises, SAFE grows slowly."""
    half = n // 2
    a = np.r_[np.full(half, 0.004), np.full(n - half, -0.004)]
    b = -a
    return pd.DataFrame(
        {"A": _path(a), "B": _path(b), "SAFE": _path(np.full(n, 0.0001))},
        index=_dates(n),
    )


# --- params ------------------------------------------------------------------

def test_params_reject_invalid_values():
    with pytest.raises(ValueError):
        RotationParams(rebalance="daily")
    with pytest.raises(ValueError):
        RotationParams(top_n=0)
    with pytest.raises(ValueError):
        RotationParams(cost_bps=-1)


# --- rebalance calendar ----------------------------------------------------------

def test_is_rebalance_day_compares_with_next_session():
    friday, monday = pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-08")
    wednesday, thursday = pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04")
    assert is_rebalance_day(friday, monday, "weekly")
    assert not is_rebalance_day(wednesday, thursday, "weekly")
    assert not is_rebalance_day(friday, monday, "monthly")
    assert is_rebalance_day(pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-01"), "monthly")


def test_weekly_rebalance_dates_are_last_trading_day_of_each_week():
    index = _dates(10, "2024-01-01")  # Mon 1st .. Fri 12th
    result = rebalance_dates(index, "weekly")
    assert list(result) == [pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-12")]


def test_monthly_rebalance_dates_include_partial_last_month():
    index = _dates(30, "2024-01-15")
    result = rebalance_dates(index, "monthly")
    assert list(result) == [pd.Timestamp("2024-01-31"), index[-1]]


# --- selection -------------------------------------------------------------------

def test_select_holdings_goes_defensive_when_nothing_is_positive():
    scores = pd.Series({"A": -0.01, "B": -0.2, "C": np.nan})
    assert select_holdings(scores, (), RotationParams()) == ()


def test_select_holdings_picks_strongest_positive():
    scores = pd.Series({"A": 0.05, "B": 0.10, "C": np.nan})
    assert select_holdings(scores, (), RotationParams()) == ("B",)


def test_switch_buffer_keeps_incumbent_within_buffer():
    scores = pd.Series({"A": 0.090, "B": 0.105})
    params = RotationParams(switch_buffer_pct=2.0)
    assert select_holdings(scores, ("A",), params) == ("A",)


def test_switch_buffer_replaces_incumbent_beyond_buffer():
    scores = pd.Series({"A": 0.07, "B": 0.105})
    params = RotationParams(switch_buffer_pct=2.0)
    assert select_holdings(scores, ("A",), params) == ("B",)


def test_incumbent_dropped_when_momentum_turns_negative():
    scores = pd.Series({"A": -0.001, "B": 0.001})
    params = RotationParams(switch_buffer_pct=50.0)
    assert select_holdings(scores, ("A",), params) == ("B",)


def test_top_n_fills_only_eligible_slots():
    scores = pd.Series({"A": 0.05, "B": -0.02, "C": 0.01})
    assert select_holdings(scores, (), RotationParams(top_n=3)) == ("A", "C")


def test_unfilled_slots_go_to_safe_asset_or_cash():
    assert holdings_to_weights(("A",), 2, "SAFE") == {"A": 0.5, "SAFE": 0.5}
    assert holdings_to_weights((), 1, None) == {CASH: 1.0}
    assert holdings_to_weights(("A", "B"), 2, "SAFE") == {"A": 0.5, "B": 0.5}


# --- backtest --------------------------------------------------------------------

def test_backtest_follows_regimes_and_uses_safe_asset():
    closes = _regime_closes()
    result = run_backtest(closes, ["A", "B"], "SAFE", RotationParams(lookback_days=20, cost_bps=0))

    held = [tuple(sorted(t.to_weights)) for t in result.trades]
    assert held[0] == ("A",)
    assert ("B",) in held
    assert result.equity.iloc[-1] > 1.0
    assert result.final_holdings == ("B",)


def test_trades_execute_one_bar_after_signal_on_rebalance_days():
    closes = _regime_closes()
    params = RotationParams(lookback_days=20, rebalance="weekly", cost_bps=0)
    result = run_backtest(closes, ["A", "B"], "SAFE", params)

    index = closes.index
    rebal = set(rebalance_dates(index, "weekly"))
    for trade in result.trades:
        assert trade.signal_date in rebal
        assert index.get_loc(trade.exec_date) - index.get_loc(trade.signal_date) == EXECUTION_LAG_DAYS


def test_no_lookahead_signal_day_jump_is_not_captured():
    """A jump on the signal bar must not be earned: the order fills at the next close."""
    index = _dates(60, "2024-01-01")
    signal_day = rebalance_dates(index, "weekly")[5]
    pos = index.get_loc(signal_day)
    returns = np.zeros(60)
    returns[pos] = 0.10  # makes momentum positive exactly on the signal bar
    closes = pd.DataFrame({"A": _path(returns)}, index=index)

    result = run_backtest(closes, ["A"], None, RotationParams(lookback_days=5, cost_bps=0))

    assert result.trades and result.trades[0].signal_date == signal_day
    assert result.equity.iloc[-1] == pytest.approx(1.0)


def test_costs_reduce_equity_by_turnover():
    closes = _regime_closes()
    free = run_backtest(closes, ["A", "B"], "SAFE", RotationParams(lookback_days=20, cost_bps=0))
    costly = run_backtest(closes, ["A", "B"], "SAFE", RotationParams(lookback_days=20, cost_bps=100))

    assert len(free.trades) == len(costly.trades) > 0
    assert costly.equity.iloc[-1] < free.equity.iloc[-1]


def test_entry_cost_is_exactly_turnover_times_rate():
    closes = _regime_closes()
    free = run_backtest(closes, ["A"], None, RotationParams(lookback_days=20, cost_bps=0))
    costly = run_backtest(closes, ["A"], None, RotationParams(lookback_days=20, cost_bps=100))

    assert costly.trades[0].turnover == pytest.approx(1.0)
    assert costly.equity.iloc[0] == free.equity.iloc[0] == pytest.approx(1.0)
    assert costly.equity.iloc[1] / free.equity.iloc[1] == pytest.approx(0.99)


def test_strategy_and_benchmark_start_together_at_first_fill():
    closes = _regime_closes()
    result = run_backtest(closes, ["A", "B"], "SAFE", RotationParams(lookback_days=20))

    assert result.equity.index[0] == result.trades[0].exec_date
    assert result.benchmark_equity.index.equals(result.equity.index)
    assert result.equity.iloc[0] == pytest.approx(1.0)
    assert result.benchmark_equity.iloc[0] == pytest.approx(1.0)


def test_first_signal_fully_defensive_still_starts_curves_at_fill():
    n = 120
    closes = pd.DataFrame({"A": _path(np.full(n, -0.002))}, index=_dates(n))
    result = run_backtest(closes, ["A"], None, RotationParams(lookback_days=10))

    assert result.trades == []  # cash -> cash is not a trade
    assert result.final_weights == {CASH: 1.0}
    assert result.equity.index[0] > closes.index[10]
    assert (result.equity == 1.0).all()


def test_cash_leg_is_not_counted_as_turnover():
    closes = _regime_closes()
    result = run_backtest(closes, ["A"], None, RotationParams(lookback_days=20, cost_bps=0))

    assert result.trades[0].from_weights == {CASH: 1.0}
    assert result.trades[0].turnover == pytest.approx(1.0)  # cash -> A
    exit_trade = next(t for t in result.trades if t.to_weights == {CASH: 1.0})
    assert exit_trade.turnover == pytest.approx(1.0)  # A -> cash


def test_unchanged_holdings_are_not_retraded_to_exact_weights():
    n = 200
    closes = pd.DataFrame(
        {"A": _path(np.full(n, 0.003)), "B": _path(np.full(n, 0.001))},
        index=_dates(n),
    )
    result = run_backtest(closes, ["A", "B"], None, RotationParams(lookback_days=20, top_n=2))

    assert len(result.trades) == 1  # initial entry only, no weekly drift re-balancing


def test_all_negative_momentum_parks_in_safe_asset():
    n = 120
    closes = pd.DataFrame(
        {"A": _path(np.full(n, -0.002)), "SAFE": _path(np.full(n, 0.001))},
        index=_dates(n),
    )
    result = run_backtest(closes, ["A"], "SAFE", RotationParams(lookback_days=10, cost_bps=0))

    assert result.final_weights == {"SAFE": 1.0}
    assert result.equity.iloc[-1] > 1.0


def test_pre_listing_asset_is_ignored_until_it_has_history():
    closes = _regime_closes()
    closes.loc[closes.index[:250], "B"] = np.nan  # B lists late
    result = run_backtest(closes, ["A", "B"], "SAFE", RotationParams(lookback_days=20, cost_bps=0))

    first_b = next(t for t in result.trades if "B" in t.to_weights)
    assert first_b.signal_date >= closes.index[250 + 20]


def test_backtest_requires_enough_history():
    closes = pd.DataFrame({"A": [1.0, 1.1, 1.2]}, index=_dates(3))
    with pytest.raises(ValueError):
        run_backtest(closes, ["A"], None, RotationParams(lookback_days=10))


# --- metrics ---------------------------------------------------------------------

def test_compute_metrics_drawdown_and_return():
    equity = pd.Series([1.0, 2.0, 1.0, 3.0], index=pd.to_datetime(
        ["2020-01-01", "2020-06-01", "2020-09-01", "2021-01-01"]
    ))
    metrics = compute_metrics(equity)
    assert metrics["total_return"] == pytest.approx(2.0)
    assert metrics["max_drawdown"] == pytest.approx(-0.5)
    assert metrics["cagr"] == pytest.approx(2.0, rel=0.01)


def test_annual_returns_chain_across_years():
    equity = pd.Series([1.0, 1.1, 1.21], index=pd.to_datetime(["2020-01-02", "2020-12-31", "2021-12-31"]))
    result = annual_returns(equity)
    assert result[2020] == pytest.approx(0.1)
    assert result[2021] == pytest.approx(0.1)


def test_parameter_sweep_skips_lookbacks_longer_than_history():
    closes = _regime_closes(300)
    rows = parameter_sweep(closes, ["A", "B"], "SAFE", RotationParams(), lookbacks=(20, 60, 1000))
    assert [lookback for lookback, _ in rows] == [20, 60]
    assert all(not np.isnan(m["cagr"]) for _, m in rows)


def test_parameter_sweep_uses_common_window_when_safe_asset_has_longer_history():
    closes = _regime_closes(600)
    closes.loc[closes.index[:300], ["A", "B"]] = np.nan  # risk pool lists late, SAFE does not
    rows = dict(parameter_sweep(closes, ["A", "B"], "SAFE", RotationParams(cost_bps=0), lookbacks=(20, 120)))

    runs = {
        lookback: run_backtest(closes, ["A", "B"], "SAFE", RotationParams(lookback_days=lookback, cost_bps=0))
        for lookback in rows
    }
    common_start = max(run.equity.index[0] for run in runs.values())
    assert common_start > closes.index[300 + 120]  # set by the longest lookback, not by SAFE
    for lookback, run in runs.items():
        assert rows[lookback] == compute_metrics(run.equity.loc[common_start:])


def test_parameter_sweep_always_includes_configured_lookback():
    rows = parameter_sweep(_regime_closes(300), ["A", "B"], "SAFE", RotationParams(lookback_days=75), lookbacks=(20, 60))
    assert [lookback for lookback, _ in rows] == [20, 60, 75]


def test_parameter_sweep_drops_lookbacks_that_leave_too_short_a_window():
    closes = _regime_closes(400)  # about 1.5 years
    rows = parameter_sweep(closes, ["A", "B"], "SAFE", RotationParams(lookback_days=20),
                           lookbacks=(20, 200), min_years=1.0)
    assert [lookback for lookback, _ in rows] == [20]


# --- service ---------------------------------------------------------------------

class _FakeFetcher:
    def __init__(self, closes: pd.DataFrame, broken=(), malformed=()):
        self._closes = closes
        self._broken = set(broken)
        self._malformed = set(malformed)

    def get_daily_data(self, code, start_date=None, end_date=None, days=30):
        if code in self._broken:
            raise RuntimeError("all sources failed")
        series = self._closes[code]
        if code in self._malformed:
            return pd.DataFrame({"trade_date": series.index, "close": series.values}), "fake"
        return pd.DataFrame({"date": series.index, "close": series.values}), "fake"

    def get_stock_name(self, code, allow_realtime=True):
        return {"A": "进攻ETF", "B": "防守ETF"}.get(code)


def _config(**overrides):
    base = dict(
        etf_rotation_pool=["A", "B", "BROKEN"],
        etf_rotation_safe_asset="SAFE",
        etf_rotation_lookback_days=20,
        etf_rotation_rebalance="weekly",
        etf_rotation_top_n=1,
        etf_rotation_switch_buffer_pct=2.0,
        etf_rotation_cost_bps=10.0,
        etf_rotation_backtest_years=3,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _notifier(available=True):
    notifier = MagicMock()
    notifier.is_available.return_value = available
    notifier.send.return_value = True
    notifier.save_report_to_file.return_value = "reports/x.md"
    return notifier


def test_run_etf_rotation_reports_failures_and_sends_report():
    notifier = _notifier()
    report = run_etf_rotation(
        _config(), send_notification=True,
        fetcher_manager=_FakeFetcher(_regime_closes(), broken={"BROKEN"}), notifier=notifier,
    )

    assert report.failed_codes.keys() == {"BROKEN"}
    assert report.target_weights == {"B": 1.0}
    for section in ("最新信号", "回测表现", "分年度收益", "参数平原检验", "规则说明", "BROKEN"):
        assert section in report.markdown
    assert "进攻ETF(A)" in report.markdown
    notifier.save_report_to_file.assert_called_once()
    notifier.send.assert_called_once_with(report.markdown, route_type="report")


def test_run_etf_rotation_skips_send_when_disabled():
    notifier = _notifier()
    run_etf_rotation(_config(), send_notification=False,
                     fetcher_manager=_FakeFetcher(_regime_closes(), broken={"BROKEN"}), notifier=notifier)
    notifier.send.assert_not_called()
    notifier.save_report_to_file.assert_called_once()


def test_run_etf_rotation_survives_save_and_send_errors():
    notifier = _notifier()
    notifier.save_report_to_file.side_effect = OSError("read-only")
    notifier.send.side_effect = RuntimeError("channel crashed")
    report = run_etf_rotation(_config(), send_notification=True,
                              fetcher_manager=_FakeFetcher(_regime_closes(), broken={"BROKEN"}), notifier=notifier)

    assert "最新信号" in report.markdown
    notifier.send.assert_called_once()  # a failed save does not skip the push


def test_run_etf_rotation_treats_malformed_frame_as_single_failure():
    report = run_etf_rotation(
        _config(etf_rotation_pool=["A", "B"]), send_notification=False,
        fetcher_manager=_FakeFetcher(_regime_closes(), malformed={"B"}), notifier=_notifier(),
    )
    assert "date" in report.failed_codes["B"]
    assert report.target_weights


def test_load_closes_drops_bars_after_end():
    closes = _regime_closes(30)
    end = closes.index[-3].date()
    loaded = load_closes(_FakeFetcher(closes), ["A"], years=1, end=end)
    assert loaded.closes.index[-1] == pd.Timestamp(end)


def _next_bday(day):
    return (pd.Timestamp(day) + pd.offsets.BDay(1)).date()


def test_signal_on_rebalance_day_is_actionable():
    closes = _regime_closes()
    closes = closes.loc[: rebalance_dates(closes.index, "weekly")[-2]]  # end on a Friday
    report = build_report(closes, ["A", "B"], "SAFE", RotationParams(lookback_days=20),
                          names={}, next_session=_next_bday)
    assert "仅供参考" not in report.markdown


def test_signal_on_non_rebalance_day_is_reference_only():
    closes = _regime_closes()
    closes = closes.loc[: rebalance_dates(closes.index, "weekly")[-2] - pd.Timedelta(days=2)]  # a Wednesday
    report = build_report(closes, ["A", "B"], "SAFE", RotationParams(lookback_days=20),
                          names={}, next_session=_next_bday)
    assert "今天不是调仓日" in report.markdown
    assert "**需要调仓**" not in report.markdown


def test_signal_without_calendar_says_rebalance_day_unknown():
    report = build_report(_regime_closes(), ["A", "B"], "SAFE", RotationParams(lookback_days=20), names={})
    assert "无法确认今天是否为调仓日" in report.markdown


def test_short_history_omits_backtest_sections():
    n = 200  # under one year of bars
    closes = pd.DataFrame({"A": _path(np.full(n, 0.003)), "B": _path(np.full(n, 0.001))}, index=_dates(n))
    report = build_report(closes, ["A", "B"], None, RotationParams(lookback_days=20), names={})

    assert "不足 1 年" in report.markdown
    for section in ("回测表现", "分年度收益", "参数平原检验", "近期调仓记录"):
        assert f"## {section}" not in report.markdown
    assert "## 最新信号" in report.markdown


def test_run_etf_rotation_fails_when_whole_pool_unavailable():
    with pytest.raises(RuntimeError):
        run_etf_rotation(_config(etf_rotation_pool=["BROKEN"]), send_notification=False,
                         fetcher_manager=_FakeFetcher(_regime_closes(), broken={"BROKEN"}), notifier=_notifier())


def test_no_rebalance_flag_when_top_n_holdings_unchanged_after_drift():
    n = 200
    closes = pd.DataFrame(
        {"A": _path(np.full(n, 0.003)), "B": _path(np.full(n, 0.001))},
        index=_dates(n),
    )
    report = build_report(closes, ["A", "B"], None, RotationParams(lookback_days=20, top_n=2), names={})

    assert report.target_weights == {"A": 0.5, "B": 0.5}
    assert "维持不变" in report.markdown


def test_missing_safe_asset_falls_back_to_cash_with_warning():
    closes = _regime_closes()
    report = build_report(
        closes[["A", "B"]], ["A", "B"], "SAFE", RotationParams(lookback_days=20),
        names={}, warnings=["SAFE 数据获取失败"],
    )
    assert "防守资产 SAFE 不可用" in report.markdown


def test_data_quality_warnings_flag_truncation_jumps_and_mixed_sources():
    closes = _regime_closes()
    closes.loc[closes.index[100], "A"] *= 0.5  # unadjusted split-like drop
    closes.loc[closes.index[:200], "B"] = np.nan  # history starts late
    loaded = LoadedPrices(
        closes=closes,
        requested_start=closes.index[0].date(),
        failed={"C": "timeout"},
        sources={"A": "EfinanceFetcher", "B": "BaostockFetcher", "SAFE": "EfinanceFetcher"},
    )
    text = "\n".join(data_quality_warnings(loaded))

    assert "C 数据获取失败" in text
    assert "A 存在异常单日涨跌" in text
    assert "B 历史起点" in text
    assert "多个数据源" in text


def test_clean_data_produces_no_warnings():
    closes = _regime_closes()
    loaded = LoadedPrices(closes, closes.index[0].date(), sources={c: "EfinanceFetcher" for c in closes})
    assert data_quality_warnings(loaded) == []


# --- config ----------------------------------------------------------------------

def test_pool_parser_defaults_trims_and_dedupes():
    assert Config._parse_etf_rotation_pool(None) == list(DEFAULT_ETF_ROTATION_POOL)
    assert Config._parse_etf_rotation_pool(" 510300, 518880 ,510300,, ") == ["510300", "518880"]


def test_rebalance_parser_falls_back_to_weekly():
    assert Config._parse_etf_rotation_rebalance("Monthly") == "monthly"
    assert Config._parse_etf_rotation_rebalance("daily") == "weekly"
    assert Config._parse_etf_rotation_rebalance(None) == "weekly"
