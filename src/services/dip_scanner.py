# -*- coding: utf-8 -*-
"""
Dip Scanner — swing de quedas pontuais (US equities).

Fluxo:
    1. Universo fechado de ações + ETFs de referência (yfinance, 1 chamada).
    2. Gatilho: queda forte no dia (% ou múltiplo de ATR) com volume acima da média,
       ou queda acumulada de 3 dias.
    3. Para cada gatilho: notícias (SearchService) + técnica + queda relativa ao ETF.
    4. LLM classifica a causa: pontual / estrutural / incerto, e dá veredito.
    5. Níveis determinísticos (entrada, stop, alvo) calculados a partir do ATR.
    6. Relatório HTML (para GitHub Pages) + resumo nas notificações configuradas.
    7. Registo de sinais com retorno a 3/5/10 sessões para medir a estratégia.

Uso:
    python -m src.services.dip_scanner                # execução normal
    python -m src.services.dip_scanner --dry-run      # sem LLM/notícias/notificação
    python -m src.services.dip_scanner --tickers NVDA,TTD --force

Configuração (todas opcionais, ver .env.example secção "Dip Scanner").
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import math
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Universo por defeito
# --------------------------------------------------------------------------

DEFAULT_UNIVERSE: Dict[str, Tuple[str, str]] = {
    # ticker: (nome, ETF de referência)
    # Mega caps
    "NVDA": ("NVIDIA", "SMH"),
    "MSFT": ("Microsoft", "QQQ"),
    "META": ("Meta Platforms", "QQQ"),
    "AMZN": ("Amazon", "QQQ"),
    "GOOGL": ("Alphabet", "QQQ"),
    "AAPL": ("Apple", "QQQ"),
    "TSLA": ("Tesla", "QQQ"),
    "NFLX": ("Netflix", "QQQ"),
    "AVGO": ("Broadcom", "SMH"),
    # Semis
    "AMD": ("AMD", "SMH"),
    "MU": ("Micron", "SMH"),
    "TSM": ("Taiwan Semiconductor", "SMH"),
    "ARM": ("Arm Holdings", "SMH"),
    "MRVL": ("Marvell Technology", "SMH"),
    "AMAT": ("Applied Materials", "SMH"),
    "LRCX": ("Lam Research", "SMH"),
    # Software / growth
    "CRM": ("Salesforce", "IGV"),
    "NOW": ("ServiceNow", "IGV"),
    "ADBE": ("Adobe", "IGV"),
    "CRWD": ("CrowdStrike", "IGV"),
    "PANW": ("Palo Alto Networks", "IGV"),
    "DDOG": ("Datadog", "IGV"),
    "NET": ("Cloudflare", "IGV"),
    "SNOW": ("Snowflake", "IGV"),
    "SHOP": ("Shopify", "IGV"),
    "TTD": ("The Trade Desk", "IGV"),
    "PLTR": ("Palantir", "IGV"),
    "UBER": ("Uber", "QQQ"),
    "ABNB": ("Airbnb", "QQQ"),
    # Consumo / saúde
    "COST": ("Costco", "SPY"),
    "NKE": ("Nike", "SPY"),
    "LULU": ("Lululemon", "SPY"),
    "SBUX": ("Starbucks", "SPY"),
    "LLY": ("Eli Lilly", "XLV"),
    "NVO": ("Novo Nordisk", "XLV"),
    "UNH": ("UnitedHealth", "XLV"),
    "ISRG": ("Intuitive Surgical", "XLV"),
    # Fintech / beta cripto
    "PYPL": ("PayPal", "QQQ"),
    "COIN": ("Coinbase", "QQQ"),
    "HOOD": ("Robinhood", "QQQ"),
}

DEFAULT_BENCHMARKS = ["SPY", "QQQ", "SMH", "IGV", "XLV"]

CAUSE_LABELS = {"pontual": "Pontual", "estrutural": "Estrutural", "incerto": "Incerto"}
VERDICT_LABELS = {
    "entrar": "Entrar",
    "aguardar_estabilizacao": "Aguardar estabilização",
    "evitar": "Evitar",
}
OUTCOME_HORIZONS = (3, 5, 10)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("[dip] %s inválido (%r), a usar %s", name, raw, default)
        return default


def _parse_universe(raw: str) -> Dict[str, Tuple[str, str]]:
    """Formato: 'NVDA:SMH,TTD:IGV,AAPL' — ETF opcional (default SPY ou o do universo base)."""
    universe: Dict[str, Tuple[str, str]] = {}
    for item in raw.split(","):
        item = item.strip().upper()
        if not item:
            continue
        ticker, _, bench = item.partition(":")
        base = DEFAULT_UNIVERSE.get(ticker)
        name = base[0] if base else ticker
        universe[ticker] = (name, bench or (base[1] if base else "SPY"))
    return universe


@dataclass
class DipScanConfig:
    universe: Dict[str, Tuple[str, str]] = field(default_factory=lambda: dict(DEFAULT_UNIVERSE))
    min_drop_pct: float = 5.0          # queda diária mínima (%)
    min_atr_mult: float = 2.0          # ou queda >= N x ATR(14)
    min_volume_ratio: float = 1.3      # volume vs média 20d
    multiday_drop_pct: float = 10.0    # queda acumulada em 3 sessões
    max_signals: int = 8               # máximo de sinais analisados pelo LLM por execução
    output_dir: Path = Path("site")
    report_url: str = ""

    @classmethod
    def from_env(cls) -> "DipScanConfig":
        cfg = cls()
        raw_universe = (os.getenv("DIP_UNIVERSE") or "").strip()
        if raw_universe:
            cfg.universe = _parse_universe(raw_universe)
        cfg.min_drop_pct = _env_float("DIP_MIN_DROP_PCT", cfg.min_drop_pct)
        cfg.min_atr_mult = _env_float("DIP_MIN_ATR_MULT", cfg.min_atr_mult)
        cfg.min_volume_ratio = _env_float("DIP_MIN_VOLUME_RATIO", cfg.min_volume_ratio)
        cfg.multiday_drop_pct = _env_float("DIP_MULTIDAY_DROP_PCT", cfg.multiday_drop_pct)
        cfg.max_signals = int(_env_float("DIP_MAX_SIGNALS", cfg.max_signals))
        cfg.output_dir = Path(os.getenv("DIP_OUTPUT_DIR") or cfg.output_dir)
        cfg.report_url = (os.getenv("DIP_REPORT_URL") or "").strip() or _default_pages_url()
        return cfg

    @property
    def benchmarks(self) -> List[str]:
        extra = {b for _, b in self.universe.values()}
        return sorted(set(DEFAULT_BENCHMARKS) | extra)


def _default_pages_url() -> str:
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return ""
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


# --------------------------------------------------------------------------
# Dados
# --------------------------------------------------------------------------

def fetch_history(tickers: List[str], period: str = "1y") -> Dict[str, Any]:
    """Descarrega OHLCV diário de todos os tickers numa só chamada ao yfinance."""
    import yfinance as yf

    data = yf.download(
        tickers=" ".join(tickers),
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    out: Dict[str, Any] = {}
    for t in tickers:
        try:
            df = data[t] if len(tickers) > 1 else data
            df = df.dropna(subset=["Close"])
            if len(df) >= 30:
                out[t] = df
            else:
                logger.warning("[dip] %s: histórico insuficiente (%d barras)", t, len(df))
        except Exception as exc:  # ticker sem dados não deve parar o scan
            logger.warning("[dip] %s: sem dados (%s)", t, exc)
    return out


# --------------------------------------------------------------------------
# Técnica
# --------------------------------------------------------------------------

def _rsi(close, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - 100 / (1 + rs)
    val = rsi.iloc[-1]
    return float(val) if not math.isnan(val) else 100.0


def _safe(v: float, nd: int = 2) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else round(f, nd)


def compute_metrics(df, bench_df=None) -> Dict[str, Any]:
    """Métricas do último pregão. ATR e médias de volume excluem o dia corrente."""
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
    prev_close = close.shift(1)
    import pandas as pd

    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr_prev = tr.rolling(14).mean().shift(1).iloc[-1]

    c, pc = float(close.iloc[-1]), float(close.iloc[-2])
    h, lo = float(high.iloc[-1]), float(low.iloc[-1])
    ret_1d = (c / pc - 1) * 100
    ret_3d = (c / float(close.iloc[-4]) - 1) * 100 if len(close) > 4 else float("nan")
    avg_vol = vol.iloc[-21:-1].mean()
    sma20 = close.rolling(20).mean().iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else float("nan")
    high_52w = float(high.max())
    high_10d = float(high.iloc[-10:].max())
    low_5d = float(low.iloc[-5:].min())

    m: Dict[str, Any] = {
        "date": str(df.index[-1].date()),
        "close": _safe(c),
        "prev_close": _safe(pc),
        "ret_1d": _safe(ret_1d),
        "ret_3d": _safe(ret_3d),
        "atr": _safe(atr_prev),
        "atr_pct": _safe(atr_prev / pc * 100),
        "atr_mult": _safe((pc - c) / atr_prev) if atr_prev else None,
        "volume_ratio": _safe(float(vol.iloc[-1]) / avg_vol) if avg_vol else None,
        "rsi14": _safe(_rsi(close), 1),
        "dist_sma20": _safe((c / sma20 - 1) * 100),
        "dist_sma50": _safe((c / sma50 - 1) * 100),
        "dist_sma200": _safe((c / sma200 - 1) * 100),
        "from_52w_high": _safe((c / high_52w - 1) * 100),
        "close_in_range": _safe((c - lo) / (h - lo), 2) if h > lo else None,
        "high_10d": _safe(high_10d),
        "low_5d": _safe(low_5d),
        "day_low": _safe(lo),
    }
    if bench_df is not None and len(bench_df) >= 2:
        bc = bench_df["Close"]
        m["bench_ret_1d"] = _safe((float(bc.iloc[-1]) / float(bc.iloc[-2]) - 1) * 100)
        m["excess_1d"] = _safe(ret_1d - m["bench_ret_1d"]) if m["bench_ret_1d"] is not None else None
    return m


def check_trigger(m: Dict[str, Any], cfg: DipScanConfig) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    r1, r3 = m.get("ret_1d"), m.get("ret_3d")
    atr_mult, vr = m.get("atr_mult"), m.get("volume_ratio")
    if r1 is not None and r1 <= -cfg.min_drop_pct:
        reasons.append(f"queda {r1:.1f}% no dia")
    if atr_mult is not None and atr_mult >= cfg.min_atr_mult:
        reasons.append(f"{atr_mult:.1f}× ATR")
    if r3 is not None and r3 <= -cfg.multiday_drop_pct:
        reasons.append(f"{r3:.1f}% em 3 sessões")
    if not reasons:
        return False, []
    multiday = r3 is not None and r3 <= -cfg.multiday_drop_pct
    if not multiday and (vr is None or vr < cfg.min_volume_ratio):
        return False, []  # queda de 1 dia sem volume = ruído
    if vr is not None:
        reasons.append(f"volume {vr:.1f}× média")
    return True, reasons


def technical_score(m: Dict[str, Any]) -> Tuple[int, List[str]]:
    """Pontuação 0-100 de qualidade do setup de reversão (só técnica)."""
    rsi = m.get("rsi14") or 50
    d200, excess = m.get("dist_sma200"), m.get("excess_1d")
    cir, vr = m.get("close_in_range"), m.get("volume_ratio") or 1
    rules = [
        (rsi < 25, 15, "RSI muito sobrevendido"),
        (25 <= rsi < 35, 8, "RSI sobrevendido"),
        (d200 is not None and d200 > 0, 12, "acima da MM200 (tendência de fundo intacta)"),
        (d200 is not None and d200 < -15, -12, "muito abaixo da MM200"),
        (excess is not None and excess > -2, 8, "queda em linha com o setor (contágio)"),
        (excess is not None and excess < -6, -5, "queda muito acima do setor (idiossincrática)"),
        (cir is not None and cir >= 0.5, 10, "fechou na metade superior do range (compradores)"),
        (cir is not None and cir <= 0.1, -8, "fechou na mínima (sem estabilização)"),
        (vr >= 3, 5, "volume de capitulação"),
    ]
    score = 50 + sum(pts for cond, pts, _ in rules if cond)
    notes = [note for cond, _, note in rules if cond]
    return max(0, min(100, score)), notes


def suggest_levels(m: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Entrada, stop e alvo determinísticos (ATR). O LLM comenta, não inventa números."""
    c, atr = m.get("close"), m.get("atr")
    if not c or not atr:
        return {}
    stop_base = min(x for x in (m.get("low_5d"), m.get("day_low"), c) if x)
    stop = stop_base - 0.5 * atr
    high10 = m.get("high_10d") or c
    target = c + 0.5 * max(high10 - c, atr)  # recuperar metade da queda desde o topo de 10d
    entry_low = c - 0.5 * atr
    risk = c - stop
    rr = (target - c) / risk if risk > 0 else None
    return {
        "entry_low": _safe(entry_low),
        "entry_high": _safe(c),
        "stop": _safe(stop),
        "target": _safe(target),
        "rr": _safe(rr, 2) if rr is not None else None,
    }


# --------------------------------------------------------------------------
# Notícias + LLM
# --------------------------------------------------------------------------

def fetch_news(ticker: str, name: str, max_results: int = 6) -> Tuple[str, List[Dict[str, str]]]:
    try:
        from src.search_service import get_search_service

        svc = get_search_service()
        if not svc.is_available:
            return "Sem motor de notícias configurado.", []
        resp = svc.search_stock_news(ticker, name, max_results=max_results)
        links = [
            {"title": r.title, "url": r.url, "source": r.source, "date": r.published_date or ""}
            for r in (resp.results or [])[:max_results]
        ]
        return resp.to_context(max_results=max_results), links
    except Exception as exc:
        logger.warning("[dip] notícias %s falharam: %s", ticker, exc)
        return f"Falha ao obter notícias: {exc}", []


LLM_PROMPT = """És um analista de ações americano a apoiar um trader experiente que faz swing de 3 a 10 dias
comprando quedas fortes causadas por motivos PONTUAIS (não estruturais).

Ação: {ticker} ({name}) — ETF de referência: {bench}
Gatilho: {reasons}

Dados técnicos (último pregão {date}):
{metrics}

Pontuação técnica: {tech_score}/100 — {tech_notes}
Níveis calculados: {levels}

Notícias recentes:
{news}

Tarefa:
1. Identifica a causa provável da queda a partir das notícias e da queda relativa ao ETF
   (queda parecida com o ETF = movimento de mercado/setor).
2. Classifica a causa:
   - "pontual": venda generalizada, contágio de setor, downgrade, resultado ligeiramente abaixo,
     ruído macro, notícia mal interpretada, venda forçada/rebalanceamento.
   - "estrutural": perda de cliente relevante, guidance muito cortado, mudança na tese de crescimento,
     problema regulatório/contabilístico/legal sério, diluição relevante, disrupção competitiva.
   - "incerto": sem informação suficiente.
3. Dá um veredito: "entrar", "aguardar_estabilizacao" ou "evitar".
4. Sê específico e cético. Não inventes notícias. Se as notícias não explicam a queda, diz isso.

Responde APENAS com JSON válido, em português, neste formato:
{{
  "cause_type": "pontual|estrutural|incerto",
  "confidence": 0-100,
  "cause_summary": "1-2 frases sobre o que causou a queda",
  "why_classification": "porque é pontual ou estrutural",
  "catalysts": ["catalisadores de recuperação"],
  "risks": ["riscos para o trade"],
  "verdict": "entrar|aguardar_estabilizacao|evitar",
  "trigger_to_enter": "o que esperar antes de entrar (ex.: fecho acima de X, martelo, volume a secar)",
  "comment_on_levels": "comentário curto aos níveis calculados"
}}
"""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def classify_with_llm(analyzer, signal: Dict[str, Any], news_ctx: str) -> Dict[str, Any]:
    m = signal["metrics"]
    metrics_txt = "\n".join(f"- {k}: {v}" for k, v in m.items() if v is not None)
    prompt = LLM_PROMPT.format(
        ticker=signal["ticker"],
        name=signal["name"],
        bench=signal["bench"],
        reasons=", ".join(signal["reasons"]),
        date=m.get("date"),
        metrics=metrics_txt,
        tech_score=signal["tech_score"],
        tech_notes="; ".join(signal["tech_notes"]) or "—",
        levels=json.dumps(signal["levels"]),
        news=news_ctx[:6000],
    )
    try:
        raw = analyzer.generate_text(prompt, max_tokens=1200, temperature=0.2)
    except Exception as exc:
        logger.error("[dip] LLM falhou para %s: %s", signal["ticker"], exc)
        raw = None
    parsed = _extract_json(raw or "")
    if not parsed:
        return {
            "cause_type": "incerto",
            "confidence": 0,
            "cause_summary": "Análise IA indisponível nesta execução.",
            "verdict": "aguardar_estabilizacao",
        }
    if parsed.get("cause_type") not in CAUSE_LABELS:
        parsed["cause_type"] = "incerto"
    if parsed.get("verdict") not in VERDICT_LABELS:
        parsed["verdict"] = "aguardar_estabilizacao"
    return parsed


# --------------------------------------------------------------------------
# Registo de sinais
# --------------------------------------------------------------------------

def load_journal(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[dip] registo ilegível (%s), a começar do zero", exc)
        return []


def update_outcomes(journal: List[Dict[str, Any]], histories: Dict[str, Any]) -> None:
    """Preenche retorno a N sessões e se stop/alvo foram tocados primeiro."""
    for rec in journal:
        df = histories.get(rec["ticker"])
        if df is None:
            continue
        idx = [str(d.date()) for d in df.index]
        if rec["date"] not in idx:
            continue
        i0 = idx.index(rec["date"])
        entry = rec["close"]
        after = df.iloc[i0 + 1 :]
        outcomes = rec.setdefault("outcomes", {})
        for n in OUTCOME_HORIZONS:
            if len(after) >= n and f"ret_{n}d" not in outcomes:
                outcomes[f"ret_{n}d"] = _safe((float(after["Close"].iloc[n - 1]) / entry - 1) * 100)
        lv = rec.get("levels") or {}
        if "exit" not in outcomes and lv.get("stop") and lv.get("target"):
            for _, row in after.iloc[:10].iterrows():
                hit_stop = float(row["Low"]) <= lv["stop"]
                hit_target = float(row["High"]) >= lv["target"]
                if hit_stop and hit_target:
                    outcomes["exit"] = "ambos"  # mesmo dia, inconclusivo
                    break
                if hit_stop:
                    outcomes["exit"] = "stop"
                    break
                if hit_target:
                    outcomes["exit"] = "alvo"
                    break
            else:
                if len(after) >= 10:
                    outcomes["exit"] = "tempo"


def journal_stats(journal: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = {}
    for key in list(CAUSE_LABELS) + ["todos"]:
        recs = [r for r in journal if key == "todos" or r.get("cause_type") == key]
        r5 = [r["outcomes"]["ret_5d"] for r in recs if r.get("outcomes", {}).get("ret_5d") is not None]
        exits = [r["outcomes"].get("exit") for r in recs if r.get("outcomes", {}).get("exit") in ("alvo", "stop")]
        stats[key] = {
            "n": len(recs),
            "n_closed": len(r5),
            "avg_5d": _safe(sum(r5) / len(r5)) if r5 else None,
            "win_5d": _safe(100 * sum(1 for x in r5 if x > 0) / len(r5), 0) if r5 else None,
            "target_rate": _safe(100 * exits.count("alvo") / len(exits), 0) if exits else None,
        }
    return stats


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _pct(v: Optional[float], signed: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def _num(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:,.2f}"


CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1a1a1a;--mut:#6b6b6b;--line:#e6e6e2;--g:#1f8a4c;--r:#c2410c;--a:#b7791f;--acc:#2f5bea}
@media (prefers-color-scheme:dark){:root{--bg:#111213;--card:#1a1b1d;--fg:#ededed;--mut:#9a9a9a;--line:#2a2b2e;--g:#4ade80;--r:#fb923c;--a:#facc15;--acc:#7c9cff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:960px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 12px}.mut{color:var(--mut)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:12px 0}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}
.tk{font-size:20px;font-weight:700}.drop{font-size:20px;font-weight:700;color:var(--r)}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;margin-right:6px;border:1px solid currentColor}
.pontual{color:var(--g)}.estrutural{color:var(--r)}.incerto{color:var(--a)}
.entrar{color:var(--g)}.aguardar_estabilizacao{color:var(--a)}.evitar{color:var(--r)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px;margin:12px 0}
.kv{background:var(--bg);border-radius:10px;padding:8px 10px}.kv b{display:block;font-size:15px}.kv span{font-size:12px;color:var(--mut)}
ul{margin:6px 0;padding-left:18px}a{color:var(--acc);text-decoration:none}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:right;padding:6px 6px;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}th{color:var(--mut);font-weight:500}
.scroll{overflow-x:auto}.neg{color:var(--r)}.pos{color:var(--g)}
details summary{cursor:pointer;color:var(--mut);font-size:13px;margin-top:8px}
footer{margin-top:40px;font-size:12px;color:var(--mut)}
"""


def _signal_card(s: Dict[str, Any]) -> str:
    m, a, lv = s["metrics"], s.get("ai") or {}, s.get("levels") or {}
    cause, verdict = a.get("cause_type", "incerto"), a.get("verdict", "aguardar_estabilizacao")
    li = lambda xs: "".join(f"<li>{_e(x)}</li>" for x in (xs or []))  # noqa: E731
    news = "".join(
        f'<li><a href="{_e(n["url"])}" target="_blank" rel="noopener">{_e(n["title"])}</a> '
        f'<span class="mut">{_e(n.get("source"))} {_e(n.get("date"))}</span></li>'
        for n in s.get("news", [])
    )
    return f"""
<div class="card">
  <div class="top"><div><span class="tk">{_e(s['ticker'])}</span> <span class="mut">{_e(s['name'])}</span></div>
  <div class="drop">{_pct(m.get('ret_1d'))}</div></div>
  <div style="margin-top:6px"><span class="badge {cause}">{CAUSE_LABELS[cause]} · {_e(a.get('confidence', 0))}%</span>
  <span class="badge {verdict}">{VERDICT_LABELS[verdict]}</span>
  <span class="mut" style="font-size:13px">{_e(', '.join(s['reasons']))}</span></div>
  <p><b>Causa:</b> {_e(a.get('cause_summary'))}</p>
  {f"<p class='mut'>{_e(a.get('why_classification'))}</p>" if a.get('why_classification') else ''}
  <div class="grid">
    <div class="kv"><span>Fecho</span><b>{_num(m.get('close'))}</b></div>
    <div class="kv"><span>vs {_e(s['bench'])}</span><b>{_pct(m.get('excess_1d'))}</b></div>
    <div class="kv"><span>RSI 14</span><b>{_e(m.get('rsi14'))}</b></div>
    <div class="kv"><span>vs MM200</span><b>{_pct(m.get('dist_sma200'))}</b></div>
    <div class="kv"><span>Do topo 52s</span><b>{_pct(m.get('from_52w_high'))}</b></div>
    <div class="kv"><span>Técnica</span><b>{s['tech_score']}/100</b></div>
  </div>
  <div class="grid">
    <div class="kv"><span>Entrada</span><b>{_num(lv.get('entry_low'))}–{_num(lv.get('entry_high'))}</b></div>
    <div class="kv"><span>Stop</span><b class="neg">{_num(lv.get('stop'))}</b></div>
    <div class="kv"><span>Alvo</span><b class="pos">{_num(lv.get('target'))}</b></div>
    <div class="kv"><span>R/R</span><b>{_e(lv.get('rr'))}</b></div>
  </div>
  {f"<p><b>Gatilho de entrada:</b> {_e(a.get('trigger_to_enter'))}</p>" if a.get('trigger_to_enter') else ''}
  {f"<p><b>Catalisadores</b></p><ul>{li(a.get('catalysts'))}</ul>" if a.get('catalysts') else ''}
  {f"<p><b>Riscos</b></p><ul>{li(a.get('risks'))}</ul>" if a.get('risks') else ''}
  {f"<p class='mut'>{_e(a.get('comment_on_levels'))}</p>" if a.get('comment_on_levels') else ''}
  <details><summary>Técnica e notícias</summary>
    <ul>{li(s['tech_notes'])}</ul>
    {f'<ul>{news}</ul>' if news else '<p class="mut">Sem notícias.</p>'}
  </details>
</div>"""


def render_html(run_date: str, signals: List[Dict[str, Any]], watch: List[Dict[str, Any]],
                journal: List[Dict[str, Any]], stats: Dict[str, Dict[str, Any]]) -> str:
    cards = "".join(_signal_card(s) for s in signals) or (
        '<div class="card mut">Nenhuma queda relevante hoje no universo.</div>'
    )
    rows = "".join(
        f"<tr><td><b>{_e(w['ticker'])}</b></td>"
        f"<td class='{'neg' if (w.get('ret_1d') or 0) < 0 else 'pos'}'>{_pct(w.get('ret_1d'))}</td>"
        f"<td>{_pct(w.get('excess_1d'))}</td><td>{_pct(w.get('ret_3d'))}</td><td>{_e(w.get('atr_mult'))}</td>"
        f"<td>{_e(w.get('volume_ratio'))}</td><td>{_e(w.get('rsi14'))}</td><td>{_pct(w.get('dist_sma200'))}</td></tr>"
        for w in watch
    )
    stat_rows = "".join(
        f"<tr><td>{'Todos' if k == 'todos' else CAUSE_LABELS[k]}</td><td>{v['n']}</td><td>{v['n_closed']}</td>"
        f"<td>{_pct(v['avg_5d'])}</td><td>{_pct(v['win_5d'], False)}</td><td>{_pct(v['target_rate'], False)}</td></tr>"
        for k, v in stats.items()
    )
    hist = "".join(
        f"<tr><td>{_e(r['date'])} <b>{_e(r['ticker'])}</b></td><td>{_pct(r.get('ret_1d'))}</td>"
        f"<td>{_e(CAUSE_LABELS.get(r.get('cause_type'), '—'))}</td><td>{_e(VERDICT_LABELS.get(r.get('verdict'), '—'))}</td>"
        + "".join(f"<td>{_pct((r.get('outcomes') or {}).get(f'ret_{n}d'))}</td>" for n in OUTCOME_HORIZONS)
        + f"<td>{_e((r.get('outcomes') or {}).get('exit', '…'))}</td></tr>"
        for r in sorted(journal, key=lambda r: r["date"], reverse=True)[:60]
    )
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!DOCTYPE html><html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Dip Scanner · {run_date}</title>
<style>{CSS}</style></head><body><main>
<h1>Dip Scanner</h1><div class="mut">Pregão de {run_date} · {len(signals)} sinal(is) · gerado {gen}</div>
<h2>Sinais de hoje</h2>{cards}
<h2>Registo de sinais</h2>
<div class="card scroll"><table><tr><th>Causa</th><th>Sinais</th><th>Com 5d</th><th>Média 5d</th><th>% positivos 5d</th><th>% alvo antes do stop</th></tr>{stat_rows}</table></div>
<div class="card scroll"><table><tr><th>Sinal</th><th>Dia</th><th>Causa</th><th>Veredito</th><th>3d</th><th>5d</th><th>10d</th><th>Saída</th></tr>{hist or '<tr><td colspan=8 class=mut>Ainda sem histórico.</td></tr>'}</table></div>
<h2>Universo hoje</h2>
<div class="card scroll"><table><tr><th>Ticker</th><th>Dia</th><th>vs ETF</th><th>3d</th><th>×ATR</th><th>Vol×</th><th>RSI</th><th>vs MM200</th></tr>{rows}</table></div>
<footer>Ferramenta de apoio à decisão. Não é aconselhamento financeiro. Níveis calculados por ATR; causa classificada por IA a partir de notícias públicas.</footer>
</main></body></html>"""


def build_message(run_date: str, signals: List[Dict[str, Any]], url: str) -> str:
    if not signals:
        lines = [f"📉 *Dip Scanner* · {run_date}", "Nenhuma queda relevante hoje no universo."]
    else:
        lines = [f"📉 *Dip Scanner* · {run_date} · {len(signals)} sinal(is)", ""]
        icon = {"pontual": "🟢", "estrutural": "🔴", "incerto": "🟡"}
        for s in signals:
            a, lv, m = s.get("ai") or {}, s.get("levels") or {}, s["metrics"]
            lines.append(
                f"{icon.get(a.get('cause_type'), '🟡')} *{s['ticker']}* {_pct(m.get('ret_1d'))} "
                f"(vs {s['bench']} {_pct(m.get('excess_1d'))}) · {CAUSE_LABELS.get(a.get('cause_type'), 'Incerto')} "
                f"· {VERDICT_LABELS.get(a.get('verdict'), '—')}"
            )
            if a.get("cause_summary"):
                lines.append(f"  {a['cause_summary']}")
            if lv:
                lines.append(f"  Entrada {_num(lv.get('entry_low'))}–{_num(lv.get('entry_high'))} · "
                             f"Stop {_num(lv.get('stop'))} · Alvo {_num(lv.get('target'))}")
            lines.append("")
    if url:
        # link Markdown: o Telegram (Markdown legado) apaga "_" em URLs soltas
        lines.append(f"[📊 Abrir relatório]({url})")
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------

def scan(cfg: DipScanConfig, histories: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Calcula métricas de todo o universo e devolve (gatilhos, linhas da watchlist)."""
    triggered, watch = [], []
    for ticker, (name, bench) in cfg.universe.items():
        df = histories.get(ticker)
        if df is None:
            continue
        m = compute_metrics(df, histories.get(bench))
        watch.append({"ticker": ticker, **m})
        ok, reasons = check_trigger(m, cfg)
        if ok:
            score, notes = technical_score(m)
            triggered.append({
                "ticker": ticker, "name": name, "bench": bench, "metrics": m,
                "reasons": reasons, "tech_score": score, "tech_notes": notes,
                "levels": suggest_levels(m),
            })
    watch.sort(key=lambda w: w.get("ret_1d") if w.get("ret_1d") is not None else 0)
    triggered.sort(key=lambda s: s["metrics"].get("ret_1d") or 0)
    return triggered[: cfg.max_signals], watch


def run(cfg: DipScanConfig, dry_run: bool = False, notify: bool = True, force: bool = False) -> int:
    tickers = sorted(set(cfg.universe) | set(cfg.benchmarks))
    logger.info("[dip] a descarregar %d tickers", len(tickers))
    histories = fetch_history(tickers)
    if not histories:
        logger.error("[dip] sem dados de mercado — abortar")
        return 1

    spy = histories.get("SPY")
    run_date = str(spy.index[-1].date()) if spy is not None else datetime.now().strftime("%Y-%m-%d")
    out = cfg.output_dir
    journal_path = out / "data" / "signals.json"
    journal = load_journal(journal_path)

    if not force and any(r["date"] == run_date for r in journal) and (out / "reports" / f"{run_date}.html").exists():
        logger.info("[dip] pregão %s já processado — nada a fazer (use --force)", run_date)
        return 0

    signals, watch = scan(cfg, histories)
    logger.info("[dip] %d gatilho(s): %s", len(signals), ", ".join(s["ticker"] for s in signals) or "—")

    analyzer = None
    if signals and not dry_run:
        from src.analyzer import get_analyzer
        analyzer = get_analyzer()
    for s in signals:
        if dry_run:
            s["news"] = []
            s["ai"] = {"cause_type": "incerto", "confidence": 0,
                       "cause_summary": "dry-run: sem IA", "verdict": "aguardar_estabilizacao"}
            continue
        news_ctx, s["news"] = fetch_news(s["ticker"], s["name"])
        s["ai"] = classify_with_llm(analyzer, s, news_ctx)

    # registo: substitui sinais do mesmo pregão (re-execução com --force)
    journal = [r for r in journal if r["date"] != run_date]
    for s in signals:
        a = s.get("ai") or {}
        journal.append({
            "date": s["metrics"]["date"], "ticker": s["ticker"], "close": s["metrics"]["close"],
            "ret_1d": s["metrics"]["ret_1d"], "excess_1d": s["metrics"].get("excess_1d"),
            "tech_score": s["tech_score"], "cause_type": a.get("cause_type"),
            "confidence": a.get("confidence"), "verdict": a.get("verdict"), "levels": s["levels"],
        })
    update_outcomes(journal, histories)
    stats = journal_stats(journal)

    page = render_html(run_date, signals, watch, journal, stats)
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "reports" / f"{run_date}.html").write_text(page, encoding="utf-8")
    journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / ".nojekyll").touch()
    logger.info("[dip] relatório escrito em %s", out / "index.html")

    msg = build_message(run_date, signals, cfg.report_url)
    print(msg)
    if notify and not dry_run:
        try:
            from src.notification import get_notification_service
            svc = get_notification_service()
            if svc.is_available():
                svc.send(msg, route_type="report")
            else:
                logger.info("[dip] nenhum canal de notificação configurado")
        except Exception as exc:  # notificação nunca deve partir o scan
            logger.error("[dip] notificação falhou: %s", exc)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Dip Scanner — quedas pontuais para swing")
    parser.add_argument("--dry-run", action="store_true", help="sem LLM, notícias nem notificação")
    parser.add_argument("--no-notify", action="store_true", help="não enviar notificação")
    parser.add_argument("--force", action="store_true", help="reprocessar mesmo pregão")
    parser.add_argument("--tickers", help="substitui o universo, ex.: NVDA:SMH,TTD")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    cfg = DipScanConfig.from_env()
    if args.tickers:
        cfg.universe = _parse_universe(args.tickers)
    return run(cfg, dry_run=args.dry_run, notify=not args.no_notify, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
