from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


_US_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _num(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        number = float(value)
        if math.isfinite(number):
            return number
    except Exception:
        pass
    return None


def _valuation_judgement(forward_pe: Any) -> Tuple[str, str]:
    pe = _num(forward_pe)
    if pe is None or pe <= 0:
        return "unknown", "Forward PE数据缺失，暂不判断"

    if pe < 30:
        return "reasonable", "Forward PE < 30，估值合理"
    if pe < 50:
        return "slightly_high", "Forward PE >= 30，估值偏高"
    return "high", "Forward PE >= 50，估值明显偏高"


def _looks_like_us_symbol(code: str, context: Dict[str, Any]) -> bool:
    market = str(context.get("market") or "").lower()
    if market == "us":
        return True
    return bool(_US_SYMBOL_RE.match(str(code or "").strip().upper()))


def fetch_yfinance_valuation(code: str) -> Dict[str, Any]:
    import yfinance as yf

    symbol = str(code or "").strip().upper()
    ticker = yf.Ticker(symbol)
    info = ticker.get_info() or {}

    trailing_pe = _num(info.get("trailingPE"))
    forward_pe = _num(info.get("forwardPE"))
    market_cap = _num(info.get("marketCap"))
    shares_outstanding = _num(info.get("sharesOutstanding"))
    float_shares = _num(info.get("floatShares"))
    level, judgement = _valuation_judgement(forward_pe)

    return {
        "pe_ratio": trailing_pe,
        "trailing_pe": trailing_pe,
        "forward_pe": forward_pe,
        "market_cap": market_cap,
        "total_mv": market_cap,
        "shares_outstanding": shares_outstanding,
        "float_shares": float_shares,
        "currency": "USD",
        "valuation_level": level,
        "valuation_judgement": judgement,
        "source": "yfinance",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def enrich_us_valuation_context(code: str, fundamental_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    ctx: Dict[str, Any] = dict(fundamental_context or {})
    if not _looks_like_us_symbol(code, ctx):
        return ctx

    valuation_data = fetch_yfinance_valuation(code)

    valuation_block = ctx.get("valuation") if isinstance(ctx.get("valuation"), dict) else {}
    old_data = valuation_block.get("data") if isinstance(valuation_block.get("data"), dict) else {}

    merged_data = dict(old_data)
    merged_data.update({k: v for k, v in valuation_data.items() if v is not None})

    ctx["valuation"] = {
        **valuation_block,
        "status": "ok",
        "data": merged_data,
    }

    coverage = ctx.get("coverage") if isinstance(ctx.get("coverage"), dict) else {}
    coverage = dict(coverage)
    coverage["valuation"] = "ok"
    ctx["coverage"] = coverage

    source_chain = ctx.get("source_chain")
    if isinstance(source_chain, list):
        if "yfinance" not in source_chain:
            source_chain.append("yfinance")
        ctx["source_chain"] = source_chain
    else:
        ctx["source_chain"] = ["yfinance"]

    if not ctx.get("market"):
        ctx["market"] = "us"

    return ctx
