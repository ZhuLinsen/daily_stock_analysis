# -*- coding: utf-8 -*-
"""Testes offline do backtest do Dip Scanner (dados sintéticos, sem rede)."""

import numpy as np
import pandas as pd
import pytest

from src.services import dip_backtest as bt
from src.services import dip_scanner as ds

N = 320
IDX = pd.bdate_range(end="2026-11-11", periods=N)


def _series(seed=0, drops=(), sigma=0.01):
    """Passeio aleatório com quedas (posição, %) e volume 3× nesses dias."""
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.0005, sigma, N))
    vol = np.full(N, 1e6)
    low = close * 0.99
    for k, pct in drops:
        close[k:] *= 1 - pct / 100
        vol[k] *= 3
        low = close * 0.99
        low[k] = close[k] * 0.98
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": low, "Close": close, "Volume": vol}, index=IDX)


def _histories(**tickers):
    h = {b: _series(seed=100 + i) for i, b in enumerate(ds.DEFAULT_BENCHMARKS)}
    h.update(tickers)
    return h


def _cfg(*tickers, **kw):
    return ds.DipScanConfig(universe={t: (t, "SPY") for t in tickers}, **kw)


K = 280  # dia da queda (há histórico suficiente antes e 10 sessões depois)


def test_finds_signal_and_measures_from_next_open():
    h = _histories(AAA=_series(seed=1, drops=[(K, 8)]))
    recs = bt.run_backtest(h, _cfg("AAA"), stop_buffers=(0.5, 1.0))
    assert [r["date"] for r in recs] == [str(IDX[K].date())]
    out = recs[0]["outcomes"]
    df = h["AAA"]
    expected = (df["Close"].iloc[K + 5] / df["Open"].iloc[K + 1] - 1) * 100
    assert out["basis"] == "next_open" and out["ret_5d"] == pytest.approx(expected, abs=0.01)
    assert {"trade_stop_0.5", "trade_stop_1", "risk_stop_0.5", "risk_stop_1"} <= set(recs[0])
    assert recs[0]["risk_stop_1"] > recs[0]["risk_stop_0.5"] > 0


def test_backtest_matches_live_scan_on_signal_day():
    h = _histories(AAA=_series(seed=1, drops=[(K, 8)]))
    rec = bt.run_backtest(h, _cfg("AAA"))[0]
    upto = {t: df.iloc[: K + 1] for t, df in h.items()}
    live, _, _ = ds.scan(_cfg("AAA"), upto)
    assert live[0]["levels"] == rec["levels"] and live[0]["tech_score"] == rec["tech_score"]


def test_cooldown_counts_sessions_since_selected_signal():
    h = _histories(AAA=_series(seed=1, drops=[(K, 8), (K + 3, 8)]))
    assert len(bt.run_backtest(h, _cfg("AAA", cooldown_sessions=5))) == 1
    assert len(bt.run_backtest(h, _cfg("AAA", cooldown_sessions=0))) == 2


def test_daily_cap_keeps_most_intense():
    h = _histories(CALM=_series(seed=1, sigma=0.005, drops=[(K, 6)]),
                   WILD=_series(seed=3, sigma=0.06, drops=[(K, 9)]))  # -9,7% mas só 2,4×ATR
    day = str(IDX[K].date())
    recs = [r for r in bt.run_backtest(h, _cfg("CALM", "WILD", max_signals=1)) if r["date"] == day]
    assert [r["ticker"] for r in recs] == ["CALM"]
    both = [r for r in bt.run_backtest(h, _cfg("CALM", "WILD", max_signals=2)) if r["date"] == day]
    assert sorted(r["ticker"] for r in both) == ["CALM", "WILD"]


def test_requires_spy():
    h = _histories(AAA=_series(seed=1, drops=[(K, 8)]))
    del h["SPY"]
    with pytest.raises(ValueError):
        bt.run_backtest(h, _cfg("AAA"))


def test_report_and_baseline():
    h = _histories(AAA=_series(seed=1, drops=[(K, 8)]), BBB=_series(seed=3, drops=[(K - 20, 9)]))
    cfg = _cfg("AAA", "BBB")
    df = bt.to_frame(bt.run_backtest(h, cfg, stop_buffers=(0.5, 1.0)))
    base = bt.baseline_returns(h, list(cfg.universe))
    assert len(base) > 0
    text = bt.report(df, base, cost_pct=0.1, split="2026-10-01", stop_buffers=(0.5, 1.0))
    for section in ("BASELINE", "== Todos ==", "Antes / depois", "Regime", "Regras técnicas", "R médio"):
        assert section in text
    assert bt.report(df.iloc[0:0]) == "Sem sinais no período."
    s = bt.summarize(df, cost_pct=0.1)
    assert s["n"] == 2 and s["trade líq."] == pytest.approx(s["trade"] - 0.1)
