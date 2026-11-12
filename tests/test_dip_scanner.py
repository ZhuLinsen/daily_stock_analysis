# -*- coding: utf-8 -*-
"""Testes offline do Dip Scanner (dados sintéticos, sem rede)."""

import json

import numpy as np
import pandas as pd
import pytest

from src.services import dip_scanner as ds


def _frame(n=260, drop_pct=0.0, vol_mult=1.0, seed=0, sigma=0.012, end="2026-11-11"):
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.0008, sigma, n))
    if drop_pct:
        close[-1] = close[-2] * (1 - drop_pct / 100)
    high = close * 1.01
    low = close * 0.99
    if drop_pct:
        low[-1] = close[-1] * 0.98
    vol = np.full(n, 1_000_000.0)
    vol[-1] *= vol_mult
    idx = pd.bdate_range(end=end, periods=n)
    return pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


def _ohlc(rows, start="2026-10-01"):
    """rows = [(open, high, low, close), ...] em dias úteis consecutivos."""
    idx = pd.bdate_range(start=start, periods=len(rows))
    o, h, lo, c = zip(*rows)
    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c, "Volume": [1e6] * len(rows)}, index=idx)


def _bench_frames(frames):
    for b in ds.DEFAULT_BENCHMARKS:
        frames.setdefault(b, _frame(seed=2))
    return frames


def test_trigger_on_strong_drop_with_volume():
    cfg = ds.DipScanConfig()
    m = ds.compute_metrics(_frame(drop_pct=8, vol_mult=3), _frame(seed=1))
    ok, reasons = ds.check_trigger(m, cfg)
    assert ok
    assert m["ret_1d"] == pytest.approx(-8, abs=0.01)
    assert any("volume" in r for r in reasons)
    assert m["excess_1d"] is not None and m["abn_1d"] is not None


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
    # stop = mínima de 5 dias − 1×ATR por defeito; a margem é configurável (backtest)
    assert lv["stop"] == pytest.approx(m["low_5d"] - ds.STOP_ATR_BUFFER * m["atr"], abs=0.01)
    assert ds.suggest_levels(m, stop_atr=0.5)["stop"] > lv["stop"]


def test_technical_score_rules():
    base = {"rsi14": 50, "close_in_range": 0.3, "volume_ratio": 1.5, "gap_pct": -1.0}
    assert ds.technical_score(base) == (50, [])
    score, notes = ds.technical_score({**base, "rsi14": 30, "close_in_range": 0.6}, {"spy_d200": -3.0})
    assert score == 50 + 15 + 10 + 5 and any("correção" in n for n in notes)
    score, notes = ds.technical_score({**base, "close_in_range": 0.05, "volume_ratio": 4, "gap_pct": -5})
    assert score == 50 - 10 - 8 - 5
    # RSI < 25 e posição face à MM200 já não pontuam (efeito instável no backtest)
    assert ds.technical_score({**base, "rsi14": 20, "dist_sma200": 10})[0] == 50
    assert ds.technical_score(base, {"spy_d200": 2.0})[0] == 50


def test_gap_pct_uses_open_vs_previous_close():
    df = _frame(drop_pct=8, vol_mult=3)
    df.iloc[-1, df.columns.get_loc("Open")] = float(df["Close"].iloc[-2]) * 0.95
    assert ds.compute_metrics(df)["gap_pct"] == pytest.approx(-5, abs=0.01)


# --------------------------------------------------------------------------
# Beta e ordenação
# --------------------------------------------------------------------------

def test_abnormal_return_is_beta_adjusted():
    rng = np.random.default_rng(7)
    n = 200
    rb = rng.normal(0, 0.01, n)
    rs = 2 * rb + rng.normal(0, 0.002, n)
    rb[-1], rs[-1] = -0.02, -0.06
    idx = pd.bdate_range(end="2026-11-11", periods=n)

    def mk(r):
        c = 100 * np.cumprod(1 + r)
        return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)

    m = ds.compute_metrics(mk(rs), mk(rb))
    assert m["beta"] == pytest.approx(2.0, abs=0.15)
    assert m["excess_1d"] == pytest.approx(-4.0, abs=0.01)   # diferença simples
    assert m["abn_1d"] == pytest.approx(-2.0, abs=0.35)      # o beta explica metade da queda


def test_beta_needs_enough_history():
    m = ds.compute_metrics(_frame(n=40, drop_pct=8, vol_mult=3), _frame(n=40, seed=1))
    assert m["beta"] is None and m["abn_1d"] == m["excess_1d"]


def test_signals_ranked_by_atr_intensity_not_raw_drop():
    volatile = _frame(drop_pct=9, vol_mult=3, sigma=0.05, seed=4)   # queda maior em %, mas normal p/ a ação
    calm = _frame(drop_pct=6, vol_mult=3, sigma=0.006, seed=5)      # queda menor em %, rara p/ a ação
    frames = _bench_frames({"VOL": volatile, "CALM": calm})
    cfg = ds.DipScanConfig(universe={"VOL": ("V", "SPY"), "CALM": ("C", "SPY")})
    signals, _, _ = ds.scan(cfg, frames)
    assert [s["ticker"] for s in signals] == ["CALM", "VOL"]
    assert signals[0]["metrics"]["intensity"] > signals[1]["metrics"]["intensity"]


def test_market_day_flag():
    spy = _frame(seed=1)
    spy.iloc[-1, spy.columns.get_loc("Close")] = float(spy["Close"].iloc[-2]) * 0.97
    mkt = ds.market_context({"SPY": spy}, "2026-11-11", ds.DipScanConfig())
    assert mkt["market_day"] is True and mkt["spy_ret_1d"] == pytest.approx(-3, abs=0.01)
    assert "DIA DE MERCADO" in ds.describe_market(mkt)
    assert ds.market_context({"SPY": _frame(seed=1)}, "2026-11-11", ds.DipScanConfig())["market_day"] is False
    assert mkt["spy_d200"] is not None and "MM200" in ds.describe_market(mkt)


def test_market_regime_below_sma200():
    spy = _frame(seed=1)
    spy["Close"] = np.linspace(200, 100, len(spy))   # tendência de queda
    mkt = ds.market_context({"SPY": spy}, "2026-11-11", ds.DipScanConfig())
    assert mkt["spy_d200"] < 0 and "correção" in ds.describe_market(mkt)


# --------------------------------------------------------------------------
# Bugs: pregão repetido, sinais repetidos, barras desatualizadas
# --------------------------------------------------------------------------

def test_rerun_same_session_without_signals_is_skipped(tmp_path, monkeypatch):
    """Feriado depois de um dia sem sinais: não reprocessa nem renotifica."""
    frames = _bench_frames({"BBB": _frame(seed=3)})
    monkeypatch.setattr(ds, "fetch_history", lambda tickers, period="1y": frames)
    calls = []
    real_render = ds.render_html
    monkeypatch.setattr(ds, "render_html", lambda *a, **k: (calls.append(1), real_render(*a, **k))[1])
    cfg = ds.DipScanConfig(universe={"BBB": ("Beta", "QQQ")}, output_dir=tmp_path)
    assert ds.run(cfg, dry_run=True) == 0
    assert ds.run(cfg, dry_run=True) == 0
    assert len(calls) == 1
    assert ds.run(cfg, dry_run=True, force=True) == 0
    assert len(calls) == 2


def test_cooldown_skips_recent_signal_of_same_ticker():
    df = _frame(drop_pct=8, vol_mult=3)
    frames = _bench_frames({"AAA": df})
    cfg = ds.DipScanConfig(universe={"AAA": ("Alpha", "SPY")}, cooldown_sessions=5)
    two_ago = str(df.index[-3].date())
    signals, _, skipped = ds.scan(cfg, frames, journal=[{"date": two_ago, "ticker": "AAA"}])
    assert signals == [] and skipped["cooldown"] == ["AAA"]

    long_ago = str(df.index[-20].date())
    signals, _, skipped = ds.scan(cfg, frames, journal=[{"date": long_ago, "ticker": "AAA"}])
    assert [s["ticker"] for s in signals] == ["AAA"] and skipped["cooldown"] == []

    cfg.cooldown_sessions = 0
    signals, _, _ = ds.scan(cfg, frames, journal=[{"date": two_ago, "ticker": "AAA"}])
    assert [s["ticker"] for s in signals] == ["AAA"]


def test_cooldown_ignores_same_session_records_on_force_rerun():
    df = _frame(drop_pct=8, vol_mult=3)
    cfg = ds.DipScanConfig(universe={"AAA": ("Alpha", "SPY")})
    signals, _, _ = ds.scan(cfg, _bench_frames({"AAA": df}), journal=[{"date": "2026-11-11", "ticker": "AAA"}])
    assert [s["ticker"] for s in signals] == ["AAA"]


def test_stale_ticker_is_skipped_and_session_date_uses_majority():
    stale = _frame(drop_pct=8, vol_mult=3, end="2026-11-10")
    frames = _bench_frames({"OLD": stale, "NEW": _frame(seed=3)})
    assert ds.session_date(frames) == "2026-11-11"
    cfg = ds.DipScanConfig(universe={"OLD": ("Old", "SPY"), "NEW": ("New", "SPY")})
    signals, watch, skipped = ds.scan(cfg, frames)
    assert signals == [] and skipped["stale"] == ["OLD"]
    assert [w["ticker"] for w in watch] == ["NEW"]


def test_stale_benchmark_is_not_compared():
    frames = _bench_frames({"AAA": _frame(drop_pct=8, vol_mult=3)})
    frames["SPY"] = _frame(seed=1, end="2026-11-10")
    cfg = ds.DipScanConfig(universe={"AAA": ("Alpha", "SPY")})
    signals, _, _ = ds.scan(cfg, frames, run_date="2026-11-11")
    assert "excess_1d" not in signals[0]["metrics"]


# --------------------------------------------------------------------------
# Resultados (earnings)
# --------------------------------------------------------------------------

NY = "America/New_York"
SESSIONS = [str(d.date()) for d in pd.bdate_range(end="2026-11-11", periods=30)]


def _ts(s):
    return pd.Timestamp(s, tz=NY)


def test_earnings_after_close_reacts_next_session():
    ctx = ds.earnings_context([(_ts("2026-11-10 16:00"), -4.2)], SESSIONS)
    assert ctx["reaction_sessions_ago"] == 0 and ctx["eps_surprise_pct"] == -4.2


def test_earnings_before_open_reacts_same_day():
    assert ds.earnings_context([(_ts("2026-11-11 07:00"), None)], SESSIONS)["reaction_sessions_ago"] == 0
    assert ds.earnings_context([(_ts("2026-11-10 07:00"), None)], SESSIONS)["reaction_sessions_ago"] == 1


def test_old_earnings_are_ignored_and_upcoming_are_flagged():
    events = [(_ts("2026-11-03 16:00"), 1.0), (_ts("2026-11-18 16:00"), None), (_ts("2027-02-20 16:00"), None)]
    ctx = ds.earnings_context(events, SESSIONS)
    assert ctx["reaction_sessions_ago"] is None
    assert ctx["next_date"] == "2026-11-18"
    # resultados hoje depois do fecho = risco para amanhã, não reação de hoje
    ctx = ds.earnings_context([(_ts("2026-11-11 16:05"), None)], SESSIONS)
    assert ctx["reaction_sessions_ago"] is None and ctx["next_date"] == "2026-11-11"
    # demasiado longe
    assert ds.earnings_context([(_ts("2027-01-30 16:00"), None)], SESSIONS)["next_date"] is None


def test_earnings_unknown_when_fetch_fails():
    assert ds.earnings_context(None, SESSIONS) == {"known": False}
    assert "indisponíveis" in ds.describe_earnings({"known": False})
    text = ds.describe_earnings({"known": True, "reaction_sessions_ago": 0, "eps_surprise_pct": -3.0,
                                 "next_date": None})
    assert "hoje" in text and "-3.0%" in text


# --------------------------------------------------------------------------
# LLM
# --------------------------------------------------------------------------

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


def test_prompt_includes_market_and_earnings_context():
    seen = {}

    class Fake:
        def generate_text(self, prompt, **k):
            seen["prompt"] = prompt
            return "{}"

    sig = {"ticker": "X", "name": "X", "bench": "SPY", "reasons": [], "metrics": {"abn_1d": -3.1},
           "tech_score": 50, "tech_notes": [], "levels": {},
           "market": {"spy_ret_1d": -3.0, "market_day": True},
           "earnings": {"known": True, "reaction_sessions_ago": 0, "eps_surprise_pct": 2.0, "next_date": None}}
    ds.classify_with_llm(Fake(), sig, "")
    assert "DIA DE MERCADO" in seen["prompt"] and "reação a resultados hoje" in seen["prompt"]
    assert "abn_1d: -3.1" in seen["prompt"]


# --------------------------------------------------------------------------
# Registo e estatísticas
# --------------------------------------------------------------------------

def test_simulate_exit_rules():
    # D+1 abre a 100 (entrada), D+2 abre abaixo do stop → sai na abertura
    after = _ohlc([(100, 101, 99, 100), (90, 91, 89, 90)])
    assert ds.simulate_exit(after, 100, 95, 110) == ("stop", -10.0)
    # abertura de entrada já abaixo do stop → setup invalidado
    assert ds.simulate_exit(_ohlc([(94, 95, 93, 94)]), 94, 95, 110) == ("sem_entrada", None)
    # stop e alvo no mesmo dia → conservador (stop)
    assert ds.simulate_exit(_ohlc([(100, 111, 94, 100)]), 100, 95, 110) == ("ambos", -5.0)
    assert ds.simulate_exit(_ohlc([(100, 111, 99, 100)]), 100, 95, 110) == ("alvo", 10.0)
    # ainda em aberto
    assert ds.simulate_exit(_ohlc([(100, 101, 99, 100)]), 100, 95, 110) is None


def test_outcomes_measured_from_next_open_and_vs_spy():
    # D (sinal, fecho 100), D+1 abre 96 → entrada 96; fecho de D+3 = 99.84 → +4%
    stock = _ohlc([(100, 101, 99, 100), (96, 98, 95, 97), (97, 99, 96, 98), (98, 100, 97, 99.84)])
    spy = _ohlc([(50, 50, 50, 50), (50, 50, 50, 50), (50, 51, 50, 51), (51, 52, 51, 51)])  # +2%
    journal = [{"date": "2026-10-01", "ticker": "AAA", "close": 100,
                "levels": {"entry_low": 95.5, "stop": 90, "target": 120},
                "outcomes": {"ret_3d": 99.0, "exit": "stop"}}]  # registo antigo (base = fecho)
    ds.update_outcomes(journal, {"AAA": stock, "SPY": spy})
    out = journal[0]["outcomes"]
    assert out["basis"] == "next_open" and out["entry_open"] == 96
    assert out["ret_3d"] == pytest.approx(4.0, abs=0.01)
    assert out["excess_3d"] == pytest.approx(2.0, abs=0.01)
    assert out["limit_filled"] is True
    assert "exit" not in out   # recalculado e ainda em aberto


def test_outcomes_and_stats():
    df = _frame(n=60)
    d0 = str(df.index[-12].date())
    c0 = float(df["Close"].iloc[-12])
    journal = [
        {"date": d0, "ticker": "AAA", "close": c0, "cause_type": "pontual", "verdict": "entrar",
         "levels": {"stop": c0 * 0.5, "target": c0 * 10}},
        {"date": d0, "ticker": "BBB", "close": c0, "cause_type": "estrutural", "verdict": "evitar",
         "levels": {"stop": c0 * 0.5, "target": c0 * 10}},
    ]
    ds.update_outcomes(journal, {"AAA": df, "BBB": df, "SPY": df})
    out = journal[0]["outcomes"]
    assert set(out) >= {"ret_3d", "ret_5d", "ret_10d", "excess_5d", "exit", "exit_ret"}
    assert out["exit"] == "tempo" and out["excess_5d"] == pytest.approx(0, abs=0.01)
    stats = ds.journal_stats(journal)
    assert stats["todos"]["n"] == 2
    assert stats["causa"]["pontual"]["n_closed"] == 1
    assert stats["veredito"]["entrar"]["n"] == 1 and stats["veredito"]["evitar"]["n"] == 1
    assert stats["veredito"]["aguardar_estabilizacao"]["n"] == 0
    assert stats["regime"]["correcao"]["n"] == 0 and stats["regime"]["alta"]["n"] == 0
    journal[0]["spy_d200"], journal[1]["spy_d200"] = -1.0, 3.0
    stats = ds.journal_stats(journal)
    assert stats["regime"]["correcao"]["n"] == 1 and stats["regime"]["alta"]["n"] == 1
    assert stats["todos"]["avg_trade"] is not None


def test_parse_universe_keeps_default_benchmarks():
    u = ds._parse_universe("nvda, ttd:qqq, zzzz")
    assert u["NVDA"] == ("NVIDIA", "SMH")
    assert u["TTD"][1] == "QQQ"
    assert u["ZZZZ"] == ("ZZZZ", "SPY")


def test_benchmarks_include_universe_etfs():
    assert {"IBIT", "XLF", "SPY", "QQQ"} <= set(ds.DipScanConfig().benchmarks)


def test_run_dry_writes_site(tmp_path, monkeypatch):
    frames = _bench_frames({"AAA": _frame(drop_pct=9, vol_mult=4), "BBB": _frame(seed=3), "SPY": _frame(seed=1)})
    monkeypatch.setattr(ds, "fetch_history", lambda tickers, period="1y": frames)
    monkeypatch.setattr(ds, "fetch_earnings", lambda t: pytest.fail("dry-run não deve consultar resultados"))
    cfg = ds.DipScanConfig(universe={"AAA": ("Alpha", "SPY"), "BBB": ("Beta", "QQQ")}, output_dir=tmp_path)
    assert ds.run(cfg, dry_run=True) == 0
    html_text = (tmp_path / "index.html").read_text()
    assert "AAA" in html_text and "Registo de sinais" in html_text and "Veredito: Entrar" in html_text
    journal = json.loads((tmp_path / "data" / "signals.json").read_text())
    assert [r["ticker"] for r in journal] == ["AAA"]
    assert {"abn_1d", "beta", "gap_pct", "intensity", "market_day", "spy_d200"} <= set(journal[0])
    assert "Regime: SPY abaixo da MM200" in html_text
    # segunda execução no mesmo pregão é ignorada
    assert ds.run(cfg, dry_run=True) == 0
    assert len(json.loads((tmp_path / "data" / "signals.json").read_text())) == 1


def test_message_wraps_url_in_markdown_link():
    msg = ds.build_message("2026-11-11", [], "https://x.github.io/daily_stock_analysis/")
    assert "(https://x.github.io/daily_stock_analysis/)" in msg and "](" in msg


def test_message_flags_market_day_and_earnings():
    sig = {"ticker": "AAA", "bench": "SPY", "metrics": {"ret_1d": -7.0, "abn_1d": -2.0},
           "ai": {"cause_type": "pontual", "verdict": "entrar"}, "levels": {},
           "earnings": {"known": True, "reaction_sessions_ago": 0, "next_date": "2026-11-18"}}
    msg = ds.build_message("2026-11-11", [sig], "", {"spy_ret_1d": -3.0, "market_day": True})
    assert "Dia de mercado" in msg and "📅 resultados" in msg and "2026-11-18" in msg
    assert "β-aj. -2.0%" in msg
