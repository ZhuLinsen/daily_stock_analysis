from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple


_US_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

_TURNOVER_KEYS = ("turnover_rate", "turnoverRate", "turnover", "换手率")
_VOLUME_KEYS = ("volume", "Volume", "成交量")
_DATE_KEYS = ("date", "Date", "日期")

_US_SECTOR_PEERS: Dict[str, List[str]] = {
    "Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "QCOM", "CSCO"],
    "Communication Services": ["META", "GOOGL", "GOOG", "NFLX", "DIS", "CMCSA", "T", "VZ"],
    "Consumer Cyclical": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "BKNG"],
    "Financial Services": ["BRK-B", "JPM", "BAC", "WFC", "GS", "MS", "V", "MA"],
    "Healthcare": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO", "ABT"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
    "Consumer Defensive": ["WMT", "COST", "PG", "KO", "PEP", "PM"],
    "Industrials": ["GE", "CAT", "BA", "HON", "UPS", "RTX"],
    "Utilities": ["NEE", "SO", "DUK", "AEP", "SRE"],
    "Real Estate": ["PLD", "AMT", "EQIX", "SPG", "O"],
    "Basic Materials": ["LIN", "APD", "SHW", "FCX", "NEM"],
}


def _num(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()
            if not value or value.upper() in {"N/A", "NONE", "NULL", "-"}:
                return None
        number = float(value)
        return number if math.isfinite(number) else None
    except Exception:
        return None


def _round(value: Any, digits: int = 2) -> Optional[float]:
    number = _num(value)
    return round(number, digits) if number is not None else None


def _first(mapping: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return None


def _records(df: Any) -> List[Dict[str, Any]]:
    if df is None:
        return []
    if hasattr(df, "to_dict"):
        try:
            return [dict(row) for row in df.to_dict("records")]
        except Exception:
            return []
    if isinstance(df, list):
        return [dict(row) for row in df if isinstance(row, dict)]
    return []


def _valuation_data(ctx: Dict[str, Any]) -> Dict[str, Any]:
    block = ctx.get("valuation") if isinstance(ctx.get("valuation"), dict) else {}
    data = block.get("data") if isinstance(block.get("data"), dict) else {}
    return dict(data)


def _share_base(ctx: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    data = _valuation_data(ctx)
    float_shares = _num(data.get("float_shares"))
    if float_shares and float_shares > 0:
        return float_shares, "流通股本"
    shares = _num(data.get("shares_outstanding"))
    if shares and shares > 0:
        return shares, "总股本"
    return None, None


def _append_source(ctx: Dict[str, Any], source: str) -> None:
    chain = ctx.get("source_chain")
    if isinstance(chain, list):
        if source not in chain:
            chain.append(source)
    else:
        ctx["source_chain"] = [source]


def enrich_daily_turnover_context(code: str, fundamental_context: Optional[Dict[str, Any]], fetcher_manager: Any, *, days: int = 60) -> Dict[str, Any]:
    ctx = dict(fundamental_context or {})
    warnings: List[str] = []
    rows: List[Dict[str, Any]] = []
    source = "unknown"

    try:
        result = fetcher_manager.get_daily_data(code, days=days)
        if isinstance(result, tuple):
            df, source = result
        else:
            df = result
        rows = _records(df)
    except Exception as exc:
        warnings.append(f"daily_data_failed: {exc}")

    share_base, share_base_name = _share_base(ctx)
    values: List[Dict[str, Any]] = []

    for row in rows:
        rate = _num(_first(row, _TURNOVER_KEYS))
        method = "provider_turnover_rate"
        if rate is None:
            volume = _num(_first(row, _VOLUME_KEYS))
            if volume is not None and share_base:
                rate = volume / share_base * 100
                method = f"estimated_by_{share_base_name}"
        if rate is None:
            continue
        values.append({
            "date": str(_first(row, _DATE_KEYS) or ""),
            "turnover_rate": round(rate, 4),
            "method": method,
        })

    latest = values[-1] if values else {}
    rates = [item["turnover_rate"] for item in values]
    avg_5 = sum(rates[-5:]) / min(len(rates), 5) if rates else None
    avg_20 = sum(rates[-20:]) / min(len(rates), 20) if rates else None
    ratio = (latest.get("turnover_rate") / avg_20) if latest and avg_20 else None

    if ratio is None:
        activity = "数据不足"
    elif ratio >= 1.5:
        activity = "放量换手"
    elif ratio <= 0.7:
        activity = "缩量换手"
    else:
        activity = "正常换手"

    status = "ok" if values else "unavailable"
    ctx["daily_turnover"] = {
        "status": status,
        "source": source,
        "latest_trade_date": latest.get("date"),
        "latest_turnover_rate": _round(latest.get("turnover_rate")),
        "avg_5d_turnover_rate": _round(avg_5),
        "avg_20d_turnover_rate": _round(avg_20),
        "latest_vs_20d_ratio": _round(ratio),
        "activity_status": activity,
        "calculation_method": latest.get("method"),
        "sample_count": len(values),
        "series_tail": values[-5:],
        "warnings": warnings,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    coverage = dict(ctx.get("coverage") or {})
    coverage["daily_turnover"] = status
    ctx["coverage"] = coverage
    _append_source(ctx, f"daily_turnover:{source}")
    return ctx


def _market_for(code: str, ctx: Dict[str, Any]) -> str:
    market = str(ctx.get("market") or "").lower()
    if market:
        return market
    return "us" if _US_SYMBOL_RE.match(str(code or "").strip().upper()) else "cn"


def _compare(current: Any, benchmark: Any) -> Dict[str, Any]:
    cur = _num(current)
    mid = _num(benchmark)
    if cur is None or mid is None or cur <= 0 or mid <= 0:
        return {"level": "unknown", "text": "数据不足"}
    ratio = cur / mid
    if ratio <= 0.85:
        level, text = "below", "低于板块中位数"
    elif ratio >= 1.15:
        level, text = "above", "高于板块中位数"
    else:
        level, text = "near", "接近板块中位数"
    return {"level": level, "text": text, "ratio": round(ratio, 2)}


def _median(values: Iterable[Any]) -> Optional[float]:
    nums = [_num(v) for v in values]
    nums = [v for v in nums if v is not None and v > 0]
    return round(median(nums), 2) if nums else None


def _primary_board(ctx: Dict[str, Any]) -> Optional[str]:
    boards = ctx.get("belong_boards")
    if not isinstance(boards, list):
        return None
    for item in boards:
        if isinstance(item, dict):
            name = item.get("name") or item.get("board_name") or item.get("板块名称")
            if name:
                return str(name)
        elif item:
            return str(item)
    return None


def _enrich_cn_sector_comparison(code: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    board = _primary_board(ctx)
    if not board:
        return {"status": "unavailable", "reason": "belong_boards_missing"}

    import akshare as ak

    last_error = None
    df = None
    for fetch_name in ("stock_board_industry_cons_em", "stock_board_concept_cons_em"):
        try:
            df = getattr(ak, fetch_name)(symbol=board)
            if df is not None and len(df) > 0:
                break
        except Exception as exc:
            last_error = exc
            df = None

    rows = _records(df)
    if not rows:
        return {"status": "unavailable", "sector": board, "reason": f"sector_constituents_missing: {last_error}"}

    pe_values = [_first(row, ("市盈率-动态", "市盈率", "pe_ratio", "PE")) for row in rows]
    pb_values = [_first(row, ("市净率", "pb_ratio", "PB")) for row in rows]
    data = _valuation_data(ctx)
    current_pe = data.get("pe_ratio") or data.get("trailing_pe")
    current_pb = data.get("pb_ratio") or data.get("price_to_book")

    for row in rows:
        row_code = str(_first(row, ("代码", "code", "symbol")) or "").zfill(6)
        if row_code == str(code).strip()[-6:]:
            current_pe = current_pe or _first(row, ("市盈率-动态", "市盈率", "pe_ratio", "PE"))
            current_pb = current_pb or _first(row, ("市净率", "pb_ratio", "PB"))
            break

    medians = {"pe_ratio": _median(pe_values), "pb_ratio": _median(pb_values)}
    return {
        "status": "ok",
        "market": "cn",
        "sector": board,
        "source": "akshare_board_constituents",
        "peer_count": len(rows),
        "current": {"pe_ratio": _round(current_pe), "pb_ratio": _round(current_pb)},
        "peer_medians": medians,
        "relative": {
            "pe_ratio": _compare(current_pe, medians.get("pe_ratio")),
            "pb_ratio": _compare(current_pb, medians.get("pb_ratio")),
        },
    }


def _enrich_us_sector_comparison(code: str, ctx: Dict[str, Any], *, max_peers: int = 8) -> Dict[str, Any]:
    import yfinance as yf

    symbol = str(code or "").strip().upper()
    info = yf.Ticker(symbol).get_info() or {}
    sector = info.get("sector") or _valuation_data(ctx).get("sector")
    industry = info.get("industry") or _valuation_data(ctx).get("industry")
    if not sector:
        return {"status": "unavailable", "market": "us", "reason": "sector_missing"}

    peers = [p for p in _US_SECTOR_PEERS.get(str(sector), []) if p.upper() != symbol][:max_peers]
    if not peers:
        return {"status": "unavailable", "market": "us", "sector": sector, "industry": industry, "reason": "peer_universe_missing"}

    peer_rows: List[Dict[str, Any]] = []
    for peer in peers:
        try:
            pinfo = yf.Ticker(peer).get_info() or {}
            peer_rows.append({
                "symbol": peer,
                "name": pinfo.get("shortName") or pinfo.get("longName") or peer,
                "trailing_pe": _round(pinfo.get("trailingPE")),
                "forward_pe": _round(pinfo.get("forwardPE")),
                "pb_ratio": _round(pinfo.get("priceToBook")),
                "ps_ratio": _round(pinfo.get("priceToSalesTrailing12Months")),
            })
        except Exception:
            continue

    data = _valuation_data(ctx)
    current = {
        "trailing_pe": _round(data.get("trailing_pe") or data.get("pe_ratio") or info.get("trailingPE")),
        "forward_pe": _round(data.get("forward_pe") or info.get("forwardPE")),
        "pb_ratio": _round(data.get("pb_ratio") or data.get("price_to_book") or info.get("priceToBook")),
        "ps_ratio": _round(data.get("ps_ratio") or data.get("price_to_sales") or info.get("priceToSalesTrailing12Months")),
    }
    medians = {
        key: _median(row.get(key) for row in peer_rows)
        for key in ("trailing_pe", "forward_pe", "pb_ratio", "ps_ratio")
    }

    return {
        "status": "ok" if peer_rows else "unavailable",
        "market": "us",
        "sector": sector,
        "industry": industry,
        "source": "yfinance_static_sector_peers",
        "peer_count": len(peer_rows),
        "current": current,
        "peer_medians": medians,
        "relative": {key: _compare(current.get(key), medians.get(key)) for key in medians},
        "peers": peer_rows[:6],
    }


def enrich_sector_valuation_comparison(code: str, fundamental_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    ctx = dict(fundamental_context or {})
    market = _market_for(code, ctx)
    try:
        comparison = _enrich_us_sector_comparison(code, ctx) if market == "us" else _enrich_cn_sector_comparison(code, ctx)
    except Exception as exc:
        comparison = {"status": "unavailable", "market": market, "reason": str(exc)}

    ctx["sector_valuation_comparison"] = comparison
    coverage = dict(ctx.get("coverage") or {})
    coverage["sector_valuation_comparison"] = comparison.get("status") or "unavailable"
    ctx["coverage"] = coverage
    _append_source(ctx, str(comparison.get("source") or "sector_valuation_comparison"))
    return ctx
