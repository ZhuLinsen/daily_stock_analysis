# -*- coding: utf-8 -*-
"""
Backtest offline do Dip Scanner.

Aplica a anos de histórico exatamente as regras do scanner (`dip_scanner`): métricas,
gatilho, pausa por ticker, filtro de dia de mercado, ordenação e limite diário, níveis e
simulação de saída a partir da abertura seguinte (o mesmo `update_outcomes` do registo).
Sem o LLM, o resultado corresponde a seguir todos os sinais (o grupo "Todos" do registo).

Não testa o LLM: as notícias de hoje sobre o passado trariam informação do futuro.

Limitações que o relatório repete:
- viés de sobrevivência: o yfinance só tem ações que ainda negoceiam. O universo
  `extended` junta ações que caíram muito, o que reduz mas não elimina o viés;
- sem custos além de `--cost-pct` por trade e sem slippage;
- sinais do mesmo dia estão correlacionados, por isso o erro-padrão é otimista.

Uso:
    python -m src.services.dip_backtest --period 15y --universe extended --split 2022-01-01
    python -m src.services.dip_backtest --stop-buffers 0.5,1,1.5 --csv sinais.csv
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence

from src.services import dip_scanner as ds

logger = logging.getLogger(__name__)

WINDOW = 252  # barras passadas ao compute_metrics, como o "1y" do scanner

# Ações que ainda negoceiam mas tiveram quedas fortes e prolongadas. Juntá-las ao universo
# reduz o viés de sobrevivência de testar só os vencedores de hoje.
EXTENDED_EXTRA: Dict[str, tuple] = {
    "INTC": ("Intel", "SMH"),
    "ZM": ("Zoom", "IGV"),
    "DOCU": ("DocuSign", "IGV"),
    "TWLO": ("Twilio", "IGV"),
    "OKTA": ("Okta", "IGV"),
    "FSLY": ("Fastly", "IGV"),
    "U": ("Unity", "IGV"),
    "PTON": ("Peloton", "SPY"),
    "ROKU": ("Roku", "QQQ"),
    "SNAP": ("Snap", "QQQ"),
    "PINS": ("Pinterest", "QQQ"),
    "ETSY": ("Etsy", "QQQ"),
    "BABA": ("Alibaba", "QQQ"),
    "LCID": ("Lucid", "QQQ"),
    "RIVN": ("Rivian", "QQQ"),
    "W": ("Wayfair", "SPY"),
    "CHWY": ("Chewy", "SPY"),
    "ENPH": ("Enphase", "SPY"),
    "SEDG": ("SolarEdge", "SPY"),
    "BA": ("Boeing", "SPY"),
    "DIS": ("Disney", "SPY"),
    "MMM": ("3M", "SPY"),
    "VFC": ("VF Corp", "SPY"),
    "EL": ("Estée Lauder", "SPY"),
    "TDOC": ("Teladoc", "XLV"),
    "MRNA": ("Moderna", "XLV"),
    "PFE": ("Pfizer", "XLV"),
    "CVS": ("CVS Health", "XLV"),
    "BIIB": ("Biogen", "XLV"),
    "UPST": ("Upstart", "XLF"),
    "AFRM": ("Affirm", "XLF"),
    "XYZ": ("Block", "XLF"),
}


# --------------------------------------------------------------------------
# Simulação
# --------------------------------------------------------------------------

def _candidate_days(df, cfg: ds.DipScanConfig) -> List[int]:
    """
    Pré-filtro vetorizado (superconjunto do check_trigger, com folga para o arredondamento).
    A decisão final é sempre do check_trigger sobre as métricas do compute_metrics.
    """
    import pandas as pd

    c, hi, lo = df["Close"], df["High"], df["Low"]
    pc = c.shift(1)
    tr = pd.concat([hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().shift(1)
    r1 = (c / pc - 1) * 100
    r3 = (c / c.shift(3) - 1) * 100
    pre = (r1 <= -(cfg.min_drop_pct - 0.01)) | ((pc - c) / atr >= cfg.min_atr_mult - 0.01) | (
        r3 <= -(cfg.multiday_drop_pct - 0.01)
    )
    return [i for i in range(len(df)) if i >= WINDOW - 1 and bool(pre.iloc[i])]


def run_backtest(
    histories: Dict[str, Any],
    cfg: ds.DipScanConfig,
    stop_buffers: Sequence[float] = (),
) -> List[Dict[str, Any]]:
    """Devolve um registo por sinal selecionado, com métricas, níveis e `outcomes`."""
    spy = histories.get("SPY")
    if spy is None:
        raise ValueError("o backtest precisa do SPY (dia de mercado, regime e comparação)")

    by_date: Dict[Any, List[tuple]] = defaultdict(list)
    for ticker in cfg.universe:
        df = histories.get(ticker)
        if df is None or len(df) < WINDOW:
            continue
        for i in _candidate_days(df, cfg):
            by_date[df.index[i]].append((ticker, i))

    last_selected: Dict[str, int] = {}
    records: List[Dict[str, Any]] = []
    for day in sorted(by_date):
        day_s = str(day.date())
        market = ds.market_context(
            {t: histories[t].loc[:day] for t in ("SPY", "QQQ") if t in histories}, day_s, cfg
        )
        candidates, pos = [], {}
        for ticker, i in by_date[day]:
            name, bench = cfg.universe[ticker]
            df = histories[ticker]
            bench_df = histories.get(bench)
            if bench_df is not None:
                bench_df = bench_df.loc[:day].iloc[-WINDOW:]
                if len(bench_df) == 0 or bench_df.index[-1] != day:
                    bench_df = None
            m = ds.compute_metrics(df.iloc[i - WINDOW + 1 : i + 1], bench_df)
            ok, reasons = ds.check_trigger(m, cfg)
            if not ok:
                continue
            since = i - last_selected[ticker] if ticker in last_selected else None
            if cfg.cooldown_sessions and since is not None and since <= cfg.cooldown_sessions:
                continue
            candidates.append(ds.build_signal(ticker, name, bench, m, reasons, market))
            pos[ticker] = i
        selected = ds.select_signals(candidates, cfg)
        for s in selected:
            m, i = s["metrics"], pos[s["ticker"]]
            last_selected[s["ticker"]] = i
            rec = {
                "date": day_s, "ticker": s["ticker"], "close": m["close"], "levels": s["levels"],
                "year": day.year, "ret_1d": m.get("ret_1d"), "abn_1d": m.get("abn_1d"),
                "beta": m.get("beta"), "intensity": m.get("intensity"), "gap_pct": m.get("gap_pct"),
                "rsi14": m.get("rsi14"), "dist_sma200": m.get("dist_sma200"),
                "close_in_range": m.get("close_in_range"), "volume_ratio": m.get("volume_ratio"),
                "tech_score": s["tech_score"], "tech_notes": s["tech_notes"],
                "market_day": market.get("market_day"),
                "spy_d200": market.get("spy_d200"),
            }
            df = histories[s["ticker"]]
            after = df.iloc[i + 1 :]
            for buf in stop_buffers:
                lv = ds.suggest_levels(m, stop_atr=buf)
                if not len(after) or not lv:
                    continue
                entry = float(after["Open"].iloc[0])
                res = ds.simulate_exit(after, entry, lv["stop"], lv["target"])
                rec[f"trade_stop_{buf:g}"] = res[1] if res else None
                # risco planeado (entrada → stop), para comparar margens em múltiplos de R
                rec[f"risk_stop_{buf:g}"] = ds._safe((entry - lv["stop"]) / entry * 100) if entry > lv["stop"] else None
            records.append(rec)
    ds.update_outcomes(records, histories)
    return records


def baseline_returns(histories: Dict[str, Any], tickers: Sequence[str]):
    """Retorno a 5 sessões desde a abertura seguinte, em qualquer dia, para as mesmas ações."""
    import pandas as pd

    parts = []
    for t in tickers:
        df = histories.get(t)
        if df is None or len(df) < WINDOW + 6:
            continue
        r = (df["Close"].shift(-5) / df["Open"].shift(-1) - 1) * 100
        parts.append(r.iloc[WINDOW - 1 :].dropna())
    return pd.concat(parts) if parts else pd.Series(dtype=float)


# --------------------------------------------------------------------------
# Relatório
# --------------------------------------------------------------------------

def to_frame(records: List[Dict[str, Any]]):
    import pandas as pd

    rows = []
    for r in records:
        o = r.get("outcomes") or {}
        row = {k: v for k, v in r.items() if k not in ("levels", "outcomes")}
        row.update({k: o.get(k) for k in ("ret_5d", "excess_5d", "ret_10d", "exit", "exit_ret", "limit_filled")})
        rows.append(row)
    return pd.DataFrame(rows)


def summarize(df, cost_pct: float = 0.0, trade_col: str = "exit_ret") -> Dict[str, Any]:
    r5 = df["ret_5d"].dropna()
    x5 = df["excess_5d"].dropna()
    tr = df[trade_col].dropna()
    exits = df["exit"].value_counts()
    closed = sum(exits.get(k, 0) for k in ("alvo", "stop", "ambos", "tempo"))
    return {
        "n": len(df),
        "média 5d": r5.mean() if len(r5) else None,
        "% pos 5d": 100 * (r5 > 0).mean() if len(r5) else None,
        "vs SPY 5d": x5.mean() if len(x5) else None,
        "trade": tr.mean() if len(tr) else None,
        "±EP": tr.std() / math.sqrt(len(tr)) if len(tr) > 1 else None,
        "trade líq.": tr.mean() - cost_pct if len(tr) else None,
        "% alvo": 100 * exits.get("alvo", 0) / closed if closed else None,
        "% stop": 100 * (exits.get("stop", 0) + exits.get("ambos", 0)) / closed if closed else None,
    }


def _table(groups, cost_pct: float) -> str:
    import pandas as pd

    t = pd.DataFrame({label: summarize(g, cost_pct) for label, g in groups if len(g)}).T
    if t.empty:
        return "(sem sinais)"
    return t.to_string(float_format=lambda v: f"{v:,.2f}")


def _buckets(df, col: str, edges: List[float], labels: List[str]):
    import pandas as pd

    cats = pd.cut(df[col], [-math.inf] + edges + [math.inf], labels=labels)
    return [(lab, df[cats == lab]) for lab in labels]


def report(
    df,
    base=None,
    cost_pct: float = 0.1,
    split: Optional[str] = None,
    stop_buffers: Sequence[float] = (),
) -> str:
    if df.empty:
        return "Sem sinais no período."
    out: List[str] = []
    add = out.append
    add(f"Dip Scanner — backtest | {df['date'].min()} → {df['date'].max()} | "
        f"{len(df)} sinais | {df['ticker'].nunique()} tickers | custo {cost_pct:.2f}%/trade")
    add("Retornos desde a abertura seguinte. 'trade' = simulação stop/alvo/10 sessões; ±EP = erro-padrão.")
    add("Atenção: viés de sobrevivência, sinais do mesmo dia correlacionados, LLM não testado.\n")
    if base is not None and len(base):
        add(f"BASELINE (qualquer dia, mesmas ações): média 5d {base.mean():+.2f}%, "
            f"positivos {100 * (base > 0).mean():.0f}%\n")
    add("== Todos ==\n" + _table([("todos", df)], cost_pct))
    if split:
        add(f"\n== Antes / depois de {split} (comparação de períodos) ==\n"
            + _table([(f"< {split}", df[df["date"] < split]), (f">= {split}", df[df["date"] >= split])], cost_pct))
    add("\n== Por ano ==\n" + _table([(str(y), g) for y, g in df.groupby("year")], cost_pct))
    regime = df["spy_d200"]
    add("\n== Regime (SPY face à MM200) ==\n" + _table(
        [("SPY acima MM200", df[regime > 0]), ("SPY abaixo MM200", df[regime <= 0])], cost_pct))
    add("\n== Dia de mercado ==\n" + _table(
        [("normal", df[df["market_day"] != True]), ("dia de mercado", df[df["market_day"] == True])],  # noqa: E712
        cost_pct))
    add("\n== Queda ajustada ao beta (abn_1d) ==\n" + _table(
        _buckets(df, "abn_1d", [-6, -2], ["< -6 (própria)", "-6 a -2", ">= -2 (contágio)"]), cost_pct))
    add("\n== Ação face à MM200 ==\n" + _table(
        _buckets(df, "dist_sma200", [-15, 0], ["< -15%", "-15% a 0", "> 0"]), cost_pct))
    add("\n== Pontuação técnica ==\n" + _table(
        _buckets(df, "tech_score", [49.5, 64.5], ["< 50", "50-64", ">= 65"]), cost_pct))
    rule_groups = []
    for note in sorted({n for ns in df["tech_notes"] for n in ns}):
        has = df["tech_notes"].apply(lambda notes, note=note: note in notes)
        rule_groups += [(f"+ {note}", df[has]), (f"- {note}", df[~has])]
    add("\n== Regras técnicas (com / sem) ==\n" + _table(rule_groups, cost_pct))
    if stop_buffers:
        import pandas as pd

        rows = {}
        for b in stop_buffers:
            row = summarize(df, cost_pct, f"trade_stop_{b:g}")
            r_mult = (df[f"trade_stop_{b:g}"] / df[f"risk_stop_{b:g}"]).dropna()
            row["risco %"] = df[f"risk_stop_{b:g}"].mean()
            row["R médio"] = r_mult.mean() if len(r_mult) else None
            rows[f"stop {b:g}×ATR"] = row
        t = pd.DataFrame(rows).T[["n", "trade", "±EP", "trade líq.", "risco %", "R médio"]]
        add("\n== Margem do stop (R = resultado / risco planeado) ==\n"
            + t.to_string(float_format=lambda v: f"{v:,.2f}"))
    return "\n".join(out)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest offline do Dip Scanner (sem LLM)")
    parser.add_argument("--period", default="10y", help="histórico do yfinance (ex.: 10y, 15y, max)")
    parser.add_argument("--universe", choices=["default", "extended"], default="default",
                        help="extended = universo do scanner + ações que caíram muito (menos viés)")
    parser.add_argument("--tickers", help="substitui o universo, ex.: NVDA:SMH,TTD")
    parser.add_argument("--split", help="data AAAA-MM-DD: compara os sinais antes e depois (estabilidade entre períodos)")
    parser.add_argument("--stop-buffers", default="0.5,1,1.5", help="margens do stop a comparar, em ATR")
    parser.add_argument("--cost-pct", type=float, default=0.1, help="custo por trade (ida e volta), em %%")
    parser.add_argument("--csv", help="grava os sinais num CSV")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    cfg = ds.DipScanConfig.from_env()
    if args.tickers:
        cfg.universe = ds._parse_universe(args.tickers)
    elif args.universe == "extended":
        cfg.universe = {**cfg.universe, **EXTENDED_EXTRA}
    stop_buffers = [float(x) for x in args.stop_buffers.split(",") if x.strip()]

    histories = ds.fetch_history(sorted(set(cfg.universe) | set(cfg.benchmarks)), period=args.period)
    records = run_backtest(histories, cfg, stop_buffers)
    df = to_frame(records)
    print(report(df, baseline_returns(histories, list(cfg.universe)), args.cost_pct, args.split, stop_buffers))
    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"\nSinais gravados em {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
