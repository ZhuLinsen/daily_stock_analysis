# -*- coding: utf-8 -*-
"""Testes offline do Dip Scanner (dados sintéticos, sem rede)."""

import json

import numpy as np
import pandas as pd
import pytest

from src.services import dip_scanner as ds


def _frame(n=260, drop_pct=0.0, vol_mult=1.0, seed=0):
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.0008, 0.012, n))
    if drop_pct:
        close[-1] = close[-2] * (1 - drop_pct / 100)
    high = close * 1.01
    low = close * 0.99
    if drop_pct:
        low[-1] = close[-1] * 0.98
    vol = np.full(n, 1_000_000.0)
    vol[-1] *= vol_mult
    idx = pd.bdate_range(end="2026-11-11", periods=n)
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


def test_trigger_on_strong_drop_with_volume():
    cfg = ds.DipScanConfig()
    m = ds.compute_metrics(_frame(drop_pct=8, vol_mult=3), _frame(seed=1))
    ok, reasons = ds.check_trigger(m, cfg)
    assert ok
    assert m["ret_1d"] == pytest.approx(-8, abs=0.01)
    assert any("volume" in r for r in reasons)
    assert m["excess_1d"] is not None


def test_no_trigger_without_volume():
    cfg = ds.DipScanConfig()
    m = ds.compute_metrics(_frame(drop_pct=6, vol_mult=1.0))
    assert ds.check_trigger(m, cfg) == (False, [])


def test_no_trigger_on_normal_day():
    cfg = ds.DipScanConfig()
    m = ds.compute_metrics(_frame(vol_mult=3))
    assert ds.check_trigger(m, cfg)[0] is False


def test_levels_are_consistent():
    m = ds.compute_metrics(_frame(drop_pct=8, vol_mult=3))
    lv = ds.suggest_levels(m)
    assert lv["stop"] < lv["entry_low"] < lv["entry_high"] < lv["target"]
    assert lv["rr"] > 0


def test_extract_json_handles_fences():
    raw = '```json\n{"cause_type": "pontual", "verdict": "entrar"}\n```'
    assert ds._extract_json(raw) == {"cause_type": "pontual", "verdict": "entrar"}
    assert ds._extract_json("sem json") is None


def test_classify_falls_back_when_llm_returns_garbage():
    class Fake:
        def generate_text(self, *a, **k):
            return "não sei"

    sig = {"ticker": "X", "name": "X", "bench": "SPY", "reasons": [], "metrics": {"date": "2026-11-11"},
           "tech_score": 50, "tech_notes": [], "levels": {}}
    out = ds.classify_with_llm(Fake(), sig, "")
    assert out["cause_type"] == "incerto"
    assert out["verdict"] == "aguardar_estabilizacao"


def test_classify_normalises_unknown_labels():
    class Fake:
        def generate_text(self, *a, **k):
            return json.dumps({"cause_type": "temporária", "verdict": "comprar", "confidence": 70})

    sig = {"ticker": "X", "name": "X", "bench": "SPY", "reasons": [], "metrics": {},
           "tech_score": 50, "tech_notes": [], "levels": {}}
    out = ds.classify_with_llm(Fake(), sig, "")
    assert out["cause_type"] == "incerto" and out["verdict"] == "aguardar_estabilizacao"


def test_outcomes_and_stats():
    df = _frame(n=60)
    d0 = str(df.index[-11].date())
    c0 = float(df["Close"].iloc[-11])
    journal = [{"date": d0, "ticker": "AAA", "close": c0, "cause_type": "pontual",
                "levels": {"stop": c0 * 0.5, "target": c0 * 10}}]
    ds.update_outcomes(journal, {"AAA": df})
    out = journal[0]["outcomes"]
    assert set(out) >= {"ret_3d", "ret_5d", "ret_10d", "exit"}
    assert out["exit"] == "tempo"
    stats = ds.journal_stats(journal)
    assert stats["pontual"]["n_closed"] == 1 and stats["todos"]["n"] == 1


def test_parse_universe_keeps_default_benchmarks():
    u = ds._parse_universe("nvda, ttd:qqq, zzzz")
    assert u["NVDA"] == ("NVIDIA", "SMH")
    assert u["TTD"][1] == "QQQ"
    assert u["ZZZZ"] == ("ZZZZ", "SPY")


def test_run_dry_writes_site(tmp_path, monkeypatch):
    frames = {"AAA": _frame(drop_pct=9, vol_mult=4), "BBB": _frame(seed=3), "SPY": _frame(seed=1)}
    for b in ds.DEFAULT_BENCHMARKS:
        frames.setdefault(b, _frame(seed=2))
    monkeypatch.setattr(ds, "fetch_history", lambda tickers, period="1y": frames)
    cfg = ds.DipScanConfig(universe={"AAA": ("Alpha", "SPY"), "BBB": ("Beta", "QQQ")}, output_dir=tmp_path)
    assert ds.run(cfg, dry_run=True) == 0
    html_text = (tmp_path / "index.html").read_text()
    assert "AAA" in html_text and "Registo de sinais" in html_text
    journal = json.loads((tmp_path / "data" / "signals.json").read_text())
    assert [r["ticker"] for r in journal] == ["AAA"]
    # segunda execução no mesmo pregão é ignorada
    assert ds.run(cfg, dry_run=True) == 0
    assert len(json.loads((tmp_path / "data" / "signals.json").read_text())) == 1


def test_message_wraps_url_in_markdown_link():
    msg = ds.build_message("2026-11-11", [], "https://x.github.io/daily_stock_analysis/")
    assert "(https://x.github.io/daily_stock_analysis/)" in msg and "](" in msg
