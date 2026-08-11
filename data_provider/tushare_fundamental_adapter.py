# -*- coding: utf-8 -*-
"""
Tushare fundamental adapter — fast, paid-API source for fundamental blocks.

The original A-share fundamental bundle is served by ``AkshareFundamentalAdapter``
which polls Eastmoney endpoints at ~1.4-2.2 rows/s; a full bundle takes ~15s and
frequently exceeds ``FUNDAMENTAL_STAGE_TIMEOUT_SECONDS`` (default 8s), leaving the
report with a "部分可用" fundamental block (valuation ok, growth/earnings/
institution failed, capital_flow/dragon_tiger/boards starved by stage budget).

Tushare returns the same data in 0.5-1.5s per call. This adapter mirrors the
``AkshareFundamentalAdapter`` public surface so ``get_fundamental_context`` can
switch source without restructuring (Tushare first, AkShare fallback).

Implemented interfaces (A-share only; offshore markets keep the existing path):
- ``get_fundamental_bundle``  -> daily_basic + fina_indicator (+ dividend)
- ``get_capital_flow``        -> moneyflow (main net inflow)
- ``get_dragon_tiger_flag``   -> top_list (龙虎榜)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def _normalize_code(code: str) -> str:
    """Strip exchange suffix for matching: '605090.SH' -> '605090'."""
    return str(code or "").strip().split(".")[0]


def _to_ts_code(code: str) -> Optional[str]:
    """Convert 605090 / 605090.SH / sh605090 to Tushare ts_code (605090.SH)."""
    raw = str(code or "").strip().upper().replace("SH", "").replace("SZ", "")
    # handle 'SH605090' style
    raw = raw.replace("600", "600").replace("000", "000")
    for prefix in ("SH", "SZ", "BJ"):
        if raw.startswith(prefix) and len(raw) == 9:
            raw = raw[2:]
    code6 = _normalize_code(raw)
    if not (code6.isdigit() and len(code6) == 6):
        return None
    if code6.startswith(("6", "5", "9", "68", "60")):
        suffix = "SH"
    elif code6.startswith(("4", "8", "92", "43", "83", "87", "88")):
        suffix = "BJ"
    else:
        suffix = "SZ"
    return f"{code6}.{suffix}"


def _latest_row(df: Optional[pd.DataFrame]) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    # Tushare returns newest first in practice; be defensive about sort.
    work = df.copy()
    date_col = next((c for c in work.columns if "trade_date" == c or "end_date" == c), None)
    if date_col is not None:
        try:
            work[date_col] = work[date_col].astype(str)
            work = work.sort_values(date_col, ascending=False)
        except Exception:
            pass
    return work.iloc[0]


class TushareFundamentalAdapter:
    """Fundamental adapter backed by Tushare Pro (paid token)."""

    def __init__(self) -> None:
        self._pro = None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _get_pro(self):
        if self._pro is not None:
            return self._pro
        import os
        import tushare as ts

        token = os.getenv("TUSHARE_TOKEN", "")
        if not token:
            return None
        try:
            ts.set_token(token)
            self._pro = ts.pro_api()
            return self._pro
        except Exception as exc:
            logger.warning("TushareFundamentalAdapter init failed: %s", exc)
            return None

    def _query(self, api_name: str, **kwargs) -> Optional[pd.DataFrame]:
        pro = self._get_pro()
        if pro is None:
            return None
        try:
            df = pro.query(api_name, **kwargs)
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df
        except Exception as exc:
            logger.debug("TushareFundamentalAdapter %s failed: %s", api_name, exc)
        return None

    def _single_row(self, df: Optional[pd.DataFrame]) -> Optional[pd.Series]:
        row = _latest_row(df)
        return row

    # ------------------------------------------------------------------
    # bundle
    # ------------------------------------------------------------------
    def get_fundamental_bundle(self, stock_code: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": "not_supported",
            "growth": {},
            "earnings": {},
            "institution": {},
            "source_chain": [],
            "errors": [],
        }
        ts_code = _to_ts_code(stock_code)
        if not ts_code:
            result["errors"].append(f"unsupported_code:{stock_code}")
            return result

        # ---- growth / earnings: fina_indicator (ROE, margin, YoY) ----
        fin = self._query(
            "fina_indicator",
            ts_code=ts_code,
            fields="ts_code,end_date,roe,grossprofit_margin,tr_yoy,netprofit_yoy,"
                   "netprofit_margin,revenue,profit_dedt,ocfps",
        )
        if fin is not None:
            row = self._single_row(fin)
            if row is not None:
                result["growth"] = {
                    "revenue_yoy": _safe_float(row.get("tr_yoy")),
                    "net_profit_yoy": _safe_float(row.get("netprofit_yoy")),
                    "roe": _safe_float(row.get("roe")),
                    "gross_margin": _safe_float(row.get("grossprofit_margin")),
                }
                result["earnings"]["financial_report"] = {
                    "report_date": _safe_str(row.get("end_date")),
                    "revenue": _safe_float(row.get("revenue")),
                    "net_profit_parent": _safe_float(row.get("profit_dedt")),
                    "roe": _safe_float(row.get("roe")),
                }
                result["source_chain"].append(f"growth:tushare_fina_indicator")

        # ---- valuation: daily_basic (pe/pb/mv) ----
        basic = self._query(
            "daily_basic",
            ts_code=ts_code,
            fields="ts_code,trade_date,pe_ttm,pb,total_mv,circ_mv",
        )
        if basic is not None:
            row = self._single_row(basic)
            if row is not None:
                result.setdefault("valuation", {})
                result["valuation"] = {
                    "pe_ratio": _safe_float(row.get("pe_ttm")),
                    "pb_ratio": _safe_float(row.get("pb")),
                    "total_mv": _safe_float(row.get("total_mv")),
                    "circ_mv": _safe_float(row.get("circ_mv")),
                }
                result["source_chain"].append("valuation:tushare_daily_basic")

        # ---- institution / top shareholders: top10_holders ----
        holders = self._query(
            "top10_holders",
            ts_code=ts_code,
            start_date="20150101",
            end_date=datetime.now().strftime("%Y%m%d"),
            fields="ts_code,end_date,holder_name,hold_ratio,hold_vol,change_ratio",
        )
        if holders is not None and not holders.empty:
            try:
                latest_end = holders["end_date"].astype(str).max()
                latest = holders[holders["end_date"].astype(str) == latest_end]
                holder_change = None
                if "change_ratio" in latest.columns:
                    holder_change = _safe_float(latest["change_ratio"].iloc[0])
                result["institution"] = {
                    "top10_holder_count": int(len(latest)),
                    "top10_holder_change": holder_change,
                    "top10_hold_ratio_avg": _safe_float(
                        latest["hold_ratio"].mean() if "hold_ratio" in latest.columns else None
                    ),
                    "top10_latest_end_date": _safe_str(latest_end),
                }
                result["source_chain"].append("institution:tushare_top10_holders")
            except Exception as exc:
                result["errors"].append(f"top10_holders_parse:{type(exc).__name__}")

        # ---- dividend: dividend (cash dividend history) ----
        div = self._query(
            "dividend",
            ts_code=ts_code,
            fields="ts_code,end_date,cash_div,cash_div_tax,div_proc,record_date,ex_date",
        )
        if div is not None and not div.empty:
            events = []
            for _, row in div.head(5).iterrows():
                cash = _safe_float(row.get("cash_div"))
                if cash is None:
                    continue
                events.append({
                    "end_date": _safe_str(row.get("end_date")),
                    "cash_dividend_per_share": cash,
                    "ex_date": _safe_str(row.get("ex_date")),
                    "process": _safe_str(row.get("div_proc")),
                })
            if events:
                result["earnings"]["dividend"] = {
                    "events": events,
                    "ttm_cash_dividend_per_share": None,
                }
                result["source_chain"].append("dividend:tushare_dividend")

        has_content = bool(result["growth"] or result["earnings"] or result.get("valuation"))
        result["status"] = "partial" if has_content else "not_supported"
        return result

    # ------------------------------------------------------------------
    # capital flow
    # ------------------------------------------------------------------
    def get_capital_flow(self, stock_code: str, top_n: int = 5) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": "not_supported",
            "stock_flow": {},
            "sector_rankings": {"top": [], "bottom": []},
            "source_chain": [],
            "errors": [],
        }
        ts_code = _to_ts_code(stock_code)
        if not ts_code:
            result["errors"].append(f"unsupported_code:{stock_code}")
            return result

        mf = self._query(
            "moneyflow",
            ts_code=ts_code,
            fields="ts_code,trade_date,net_mf_amount,net_mf_amount_ratio",
        )
        if mf is not None:
            row = self._single_row(mf)
            if row is not None:
                result["stock_flow"] = {
                    "main_net_inflow": _safe_float(row.get("net_mf_amount")),
                    "main_net_inflow_ratio": _safe_float(row.get("net_mf_amount_ratio")),
                }
                result["source_chain"].append("capital_stock:tushare_moneyflow")

        has_content = bool(result["stock_flow"])
        result["status"] = "partial" if has_content else "not_supported"
        return result

    # ------------------------------------------------------------------
    # dragon tiger
    # ------------------------------------------------------------------
    def get_dragon_tiger_flag(self, stock_code: str, lookback_days: int = 20) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": "not_supported",
            "is_on_list": False,
            "recent_count": 0,
            "latest_date": None,
            "source_chain": [],
            "errors": [],
        }
        ts_code = _to_ts_code(stock_code)
        if not ts_code:
            result["errors"].append(f"unsupported_code:{stock_code}")
            return result

        end = datetime.now()
        start = end - timedelta(days=max(1, lookback_days))
        tl = self._query(
            "top_list",
            ts_code=ts_code,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            fields="ts_code,trade_date",
        )
        if tl is not None and not tl.empty:
            dates = [str(d) for d in tl["trade_date"].astype(str).tolist() if str(d).isdigit()]
            result["is_on_list"] = True
            result["recent_count"] = len(dates)
            result["latest_date"] = dates[0] if dates else None
            result["status"] = "ok"
            result["source_chain"].append("dragon_tiger:tushare_top_list")
        else:
            # No rows in window still means the query succeeded (not on list).
            result["status"] = "ok"
            result["source_chain"].append("dragon_tiger:tushare_top_list")
        return result


# ---------------------------------------------------------------------------
# local helpers (kept in this module to avoid importing AkShare internals)
# ---------------------------------------------------------------------------
def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
        if pd.isna(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        s = str(value).strip()
        return s or None
    except Exception:
        return None
