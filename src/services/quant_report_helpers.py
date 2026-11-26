# -*- coding: utf-8 -*-
"""Quantitative factor & sniper Risk/Reward formatting helpers for Jinja2 reports."""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Mapping, Optional

from src.report_language import normalize_report_language

_RATIO_CONTEXT_RE = re.compile(
    r"(?:risk\s*[-/]?\s*(?:to\s*[-/]?\s*)?(?:reward|return)|reward\s*(?:[-/]?\s*to\s*[-/]?\s*risk|[-/]\s*risk)|"
    r"risk\s*reward|ratio|R\s*/\s*R|风险\s*(?:回报|收益)|回报比|收益比|比率|손익\s*비)",
    re.IGNORECASE,
)
_MA_PREFIX_RE = re.compile(r"(?:MA|BOLL|RSI|KDJ|MACD|WR|BIAS|T\+)\s*(?:\d+\s*/\s*)*$", re.IGNORECASE)
_NON_PRICE_SUFFIX_RE = re.compile(
    r"^(?:%|percent(?:age)?\b|百分之|퍼센트|日|周|週|月|年|天|个交易日|倍|거래일|일|주|개월|년|배|"
    r"(?:[-‐‑–]\s*)?(?:(?:trading\s+)?(?:days?|sessions?|periods?)|weeks?|months?|years?|times?|x|d)\b)",
    re.IGNORECASE,
)
_PRICE_UNIT_AFTER_RE = re.compile(
    r"^\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY|dollars?|euros?)\b|元|美元|美金|港元|港币|港幣|日元|新台币|新臺幣|円|원)",
    re.IGNORECASE,
)
_PRICE_UNIT_BEFORE_RE = re.compile(r"(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)$", re.IGNORECASE)
_DATE_RE = re.compile(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b")
_ORDINAL_PREFIX_RE = re.compile(r"(?:第)\s*$")
_ORDINAL_SUFFIX_RE = re.compile(r"^(?:st|nd|rd|th|차|个|批)\b", re.IGNORECASE)
_CURRENT_PRICE_RE = re.compile(
    r"(?:current|latest|last|market)\s+price(?:\s+(?:is|of|at))?\s*[:：]?\s*"
    r"(?:about|around|approx(?:imately)?|approximately)?\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)?$|"
    r"(?:当前价(?:格)?|目前价(?:格)?|现价)\s*(?:(?:约|大约)\s*)?(?:(?:是|为|在)\s*)?[:：]?\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)?$",
    re.IGNORECASE,
)
_NO_STOP_RE = re.compile(r"(?:止损|stop\s*-?\s*loss)[^;；,，]*(?:暂无|不设|没有|无固定|none|no\s+fixed)", re.IGNORECASE)
_NO_LEVEL_RE = re.compile(
    r"^\s*(?:暂无|无明确|不建议|不设|暂不|none\b|n/?a\b|no\s+(?:ideal|clear|fixed|valid)?\s*(?:buy|entry|stop|target))",
    re.IGNORECASE,
)

_REGIME_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "trending_bullish": {"zh": "趋势多头", "en": "Trending Bullish", "ko": "상승 추세"},
    "trending_bearish": {"zh": "趋势走弱", "en": "Trending Bearish", "ko": "하락 추세"},
    "volatility_squeeze": {"zh": "波动率收口", "en": "Volatility Squeeze", "ko": "변동성 수축"},
    "range_squeeze": {"zh": "缩量蓄势", "en": "Volatility Squeeze", "ko": "변동성 수축"},
    "pullback_bullish": {"zh": "多头回踩", "en": "Bullish Pullback", "ko": "상승 눌림목"},
    "oversold_rebound": {"zh": "超卖反弹窗口", "en": "Oversold Rebound", "ko": "과매도 반등"},
    "overbought_extension": {"zh": "高位超买扩张", "en": "Overbought Extension", "ko": "과매수 확장"},
    "overbought_caution": {"zh": "高位超买警惕", "en": "Overbought Caution", "ko": "과매수 경계"},
    "range_bound": {"zh": "区间震荡", "en": "Range Bound", "ko": "박스권 횡보"},
    "neutral": {"zh": "中性震荡", "en": "Neutral", "ko": "중립 횡보"},
    "insufficient_data": {"zh": "样本不足", "en": "Insufficient Data", "ko": "데이터 부족"},
}


def parse_strategy_price_value(raw: Any) -> Optional[float]:
    """Parse finite positive trading price from a strategy level string or numeric value."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        num = float(raw)
        return num if math.isfinite(num) and num > 0 else None
    text = str(raw).strip()
    if not text or _NO_STOP_RE.search(text) or _NO_LEVEL_RE.search(text):
        return None
    normalized = text.replace("，", ",")
    normalized = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", normalized)
    normalized = re.sub(r"\([^)]*(?:MA|BOLL|RSI|KDJ|MACD|均线)[^)]*\)", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"（[^）]*(?:MA|BOLL|RSI|KDJ|MACD|均线)[^）]*）", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r"(?:(?<![A-Za-z])(?:E?MA|BOLL|RSI|KDJ|MACD|WR|BIAS)\s*[\d\s/,-]*|均线|均線)\s*(?:附近区域|附近)?\s*[（(][^()（）]*[）)]",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )

    date_spans = [m.span() for m in _DATE_RE.finditer(normalized)]
    ratio_spans = [
        (m.start(), m.end())
        for m in re.finditer(r"\d+(?:\.\d+)?\s*([:：/／]|比|to)\s*\d+(?:\.\d+)?", normalized, flags=re.IGNORECASE)
        if not (
            _PRICE_UNIT_AFTER_RE.search(normalized[m.end():])
            or _PRICE_UNIT_BEFORE_RE.search(normalized[:m.start()])
        )
        and (
            m.group(1) not in {"/", "／", "to", "TO"}
            or bool(_RATIO_CONTEXT_RE.search(normalized[max(0, m.start() - 32): min(len(normalized), m.end() + 32)]))
        )
    ]

    for m in re.finditer(r"(?<![A-Za-z0-9_.])(\d+(?:\.\d+)?|\.\d+)", normalized):
        start, end = m.span()
        if any(s <= start and end <= e for s, e in date_spans):
            continue
        if any(s <= start and end <= e for s, e in ratio_spans):
            continue
        prefix = normalized[:start]
        suffix = normalized[end:].lstrip()
        if _MA_PREFIX_RE.search(prefix):
            continue
        if _NON_PRICE_SUFFIX_RE.match(suffix):
            continue
        if _ORDINAL_PREFIX_RE.search(prefix) or _ORDINAL_SUFFIX_RE.match(suffix):
            continue
        if _CURRENT_PRICE_RE.search(prefix):
            continue
        val = float(m.group(1))
        if math.isfinite(val) and val > 0:
            return val
    return None


def compute_sniper_risk_reward(
    sniper: Any,
    *,
    current_price: Any = None,
) -> Optional[Dict[str, Any]]:
    """Compute entry/stop/target Risk-Reward ratio and upside/downside percentages."""
    if not isinstance(sniper, Mapping):
        return None
    ideal_buy = parse_strategy_price_value(sniper.get("ideal_buy"))
    secondary_buy = parse_strategy_price_value(sniper.get("secondary_buy"))
    stop_loss = parse_strategy_price_value(sniper.get("stop_loss"))
    take_profit = parse_strategy_price_value(sniper.get("take_profit"))
    fallback_curr = parse_strategy_price_value(current_price)

    entry = ideal_buy or secondary_buy or fallback_curr
    if entry is None or stop_loss is None or take_profit is None:
        return None
    if not (take_profit > entry > stop_loss):
        return None

    upside_pct = ((take_profit - entry) / entry) * 100.0
    downside_pct = ((entry - stop_loss) / entry) * 100.0
    risk = entry - stop_loss
    if risk <= 0:
        return None
    ratio = (take_profit - entry) / risk
    if not math.isfinite(ratio) or ratio <= 0:
        return None

    ratio_display = f"1:{ratio:.1f}"
    summary = f"{ratio_display} (+{upside_pct:.1f}% / -{downside_pct:.1f}%)"
    return {
        "entry": round(entry, 4),
        "stop_loss": round(stop_loss, 4),
        "take_profit": round(take_profit, 4),
        "ratio": round(ratio, 2),
        "ratio_display": ratio_display,
        "upside_pct": round(upside_pct, 1),
        "downside_pct": round(downside_pct, 1),
        "summary": summary,
    }


def _to_plain_dict(obj: Any) -> Optional[Dict[str, Any]]:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return dict(obj)
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        raw = to_dict()
        return dict(raw) if isinstance(raw, Mapping) else None
    return None


def _fmt_num(val: Any, decimals: int = 2, suffix: str = "") -> str:
    if val is None or isinstance(val, bool):
        return "N/A"
    try:
        num = float(val)
    except (TypeError, ValueError):
        return "N/A"
    if not math.isfinite(num):
        return "N/A"
    return f"{num:.{decimals}f}{suffix}"


def _fmt_signed(val: Any, decimals: int = 2, suffix: str = "%") -> str:
    if val is None or isinstance(val, bool):
        return "N/A"
    try:
        num = float(val)
    except (TypeError, ValueError):
        return "N/A"
    if not math.isfinite(num):
        return "N/A"
    return f"{num:+.{decimals}f}{suffix}"


def extract_quant_factors(
    result: Any,
    *,
    quant_factors_by_code: Optional[Mapping[str, Any]] = None,
    report_language: Optional[str] = "zh",
) -> Optional[Dict[str, Any]]:
    """Extract and localize structured ``quant_factors`` metrics from result/snapshots."""
    lang = normalize_report_language(report_language)
    code = str(getattr(result, "code", "") or "").strip()

    raw: Optional[Dict[str, Any]] = None
    if isinstance(quant_factors_by_code, Mapping) and code:
        raw = _to_plain_dict(quant_factors_by_code.get(code))

    if raw is None:
        raw = _to_plain_dict(getattr(result, "quant_factors", None))

    dashboard = getattr(result, "dashboard", None)
    if raw is None and isinstance(dashboard, Mapping):
        raw = _to_plain_dict(dashboard.get("quant_factors"))

    if raw is None:
        for snap_attr in ("context_snapshot", "diagnostic_context_snapshot", "market_snapshot"):
            snap = getattr(result, snap_attr, None)
            if not isinstance(snap, Mapping):
                continue
            containers = [snap]
            enhanced_snap = snap.get("enhanced_context")
            if isinstance(enhanced_snap, Mapping):
                containers.append(enhanced_snap)
            for container in containers:
                cand = _to_plain_dict(container.get("quant_factors"))
                if cand is None and isinstance(container.get("trend_analysis"), Mapping):
                    cand = _to_plain_dict(container["trend_analysis"].get("quant_factors"))
                if cand is None and isinstance(container.get("technical"), Mapping):
                    cand = _to_plain_dict(container["technical"].get("quant_factors"))
                if cand is not None:
                    raw = cand
                    break
            if raw is not None:
                break

    if not raw or raw.get("sufficient_data") is False:
        return None

    score = raw.get("quant_composite_score")
    if score is None or isinstance(score, bool):
        return None
    try:
        score_float = float(score)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score_float):
        return None
    score_int = int(round(score_float))

    regime_key = str(raw.get("quant_regime") or "neutral").strip().lower()
    regime_label = _REGIME_TRANSLATIONS.get(regime_key, {}).get(lang) or regime_key

    squeeze_flag = " Squeeze" if raw.get("boll_squeeze") else ""
    boll_summary = (
        f"{_fmt_num(raw.get('boll_lower'))} / {_fmt_num(raw.get('boll_mid'))} / "
        f"{_fmt_num(raw.get('boll_upper'))} "
        f"(%B={_fmt_num(raw.get('boll_pct_b'))}, BW={_fmt_num(raw.get('boll_bandwidth_pct'), 2, '%')}{squeeze_flag})"
    )
    atr_summary = (
        f"ATR14={_fmt_num(raw.get('atr_14'))} ({_fmt_num(raw.get('atr_pct'), 2, '%')}), "
        f"2xATR Stop={_fmt_num(raw.get('atr_stop_loss_long'))}, "
        f"Donchian={raw.get('donchian_signal') or 'inside'}"
    )
    adx_part = (
        f"ADX={_fmt_num(raw.get('adx_14'), 1)} (+DI={_fmt_num(raw.get('plus_di_14'), 1)} / -DI={_fmt_num(raw.get('minus_di_14'), 1)})"
        if raw.get("adx_14") is not None
        else "ADX=N/A"
    )
    kdj_adx_summary = (
        f"K={_fmt_num(raw.get('kdj_k'), 1)} D={_fmt_num(raw.get('kdj_d'), 1)} "
        f"J={_fmt_num(raw.get('kdj_j'), 1)} ({raw.get('kdj_status') or 'neutral'}); {adx_part}"
    )
    flow_summary = (
        f"VWAP Bias={_fmt_signed(raw.get('vwap_bias_pct'))}, "
        f"OBV={raw.get('obv_trend') or 'flat'}, "
        f"MFI14={_fmt_num(raw.get('mfi_14'), 1)}"
    )
    momentum_summary = (
        f"ROC5={_fmt_signed(raw.get('roc_5_pct'))}, "
        f"ROC20={_fmt_signed(raw.get('roc_20_pct'))}, "
        f"ROC60={_fmt_signed(raw.get('roc_60_pct'))}"
    )
    risk_summary = (
        f"60D MaxDD={_fmt_num(raw.get('max_drawdown_60_pct'), 2, '%')}, "
        f"Sharpe={_fmt_num(raw.get('sharpe_60'), 2)}, "
        f"HV20={_fmt_num(raw.get('hv_20_annualized_pct'), 2, '%')}"
    )

    signals = [str(s).strip() for s in (raw.get("factor_signals") or []) if str(s).strip()]

    return {
        **raw,
        "score": score_int,
        "regime_key": regime_key,
        "regime_label": regime_label,
        "boll_squeeze": bool(raw.get("boll_squeeze")),
        "boll_summary": boll_summary,
        "atr_summary": atr_summary,
        "kdj_adx_summary": kdj_adx_summary,
        "flow_summary": flow_summary,
        "momentum_summary": momentum_summary,
        "risk_summary": risk_summary,
        "signals_text": ", ".join(signals[:5]) if signals else "N/A",
    }


def format_quant_pulse(
    qf: Optional[Mapping[str, Any]],
    rr: Optional[Mapping[str, Any]],
    language: Optional[str] = "zh",
) -> str:
    """Render a compact one-line Quant Factor + R:R badge strip for summary & push cards."""
    lang = normalize_report_language(language)
    parts = []
    if qf:
        score = qf.get("score")
        regime_label = qf.get("regime_label") or ""
        if lang == "ko":
            label = f"정량 {score}/100"
        elif lang == "en":
            label = f"Quant {score}/100"
        else:
            label = f"量化 {score}/100"
        if regime_label:
            label = f"{label} ({regime_label})"
        if qf.get("boll_squeeze"):
            sq = "BOLL 수축" if lang == "ko" else ("BOLL Squeeze" if lang == "en" else "BOLL收口")
            label = f"{label} · {sq}"
        parts.append(label)
    if rr and rr.get("ratio_display"):
        rr_prefix = "손익비" if lang == "ko" else ("R:R" if lang == "en" else "盈亏比")
        parts.append(f"{rr_prefix} {rr['ratio_display']}")
    return " · ".join(parts)


def _escape_md_cell(value: Any) -> str:
    """Escape pipe characters and collapse newlines inside Markdown table cells."""
    text = str(value if value is not None else "N/A")
    return " ".join(text.replace("|", "\\|").splitlines()).strip() or "N/A"


def render_quant_factors_markdown_lines(
    qf: Optional[Mapping[str, Any]],
    labels: Mapping[str, str],
) -> List[str]:
    """Render structured Quantitative Factors Markdown section matching ``report_markdown.j2``."""
    if not isinstance(qf, Mapping):
        return []
    lines = [
        f"### 📐 {labels['quant_factors_heading']}",
        "",
        f"**{labels['quant_composite_label']}**: {qf.get('score')}/100 | "
        f"**{labels['quant_regime_label']}**: {_escape_md_cell(qf.get('regime_label'))}",
        "",
        f"| {labels['quant_dimension_label']} | {labels['quant_snapshot_label']} |",
        "|---------|------|",
        f"| {labels['quant_boll_label']} | {_escape_md_cell(qf.get('boll_summary'))} |",
        f"| {labels['quant_atr_label']} | {_escape_md_cell(qf.get('atr_summary'))} |",
        f"| {labels['quant_kdj_adx_label']} | {_escape_md_cell(qf.get('kdj_adx_summary'))} |",
        f"| {labels['quant_flow_label']} | {_escape_md_cell(qf.get('flow_summary'))} |",
        f"| {labels['quant_momentum_label']} | {_escape_md_cell(qf.get('momentum_summary'))} |",
        f"| {labels['quant_risk_label']} | {_escape_md_cell(qf.get('risk_summary'))} |",
    ]
    signals_text = qf.get("signals_text")
    if signals_text and signals_text != "N/A":
        lines.append(f"**{labels['quant_signals_label']}**: {_escape_md_cell(signals_text)}")
    lines.append("")
    return lines
