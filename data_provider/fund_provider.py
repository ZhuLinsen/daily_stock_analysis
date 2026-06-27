# -*- coding: utf-8 -*-
"""EastMoney mutual fund helpers for the workbench.

Off-exchange mutual funds do not have intraday tradable quotes. The provider
therefore focuses on NAV, estimated NAV, return/risk metrics, and a plain
subscription reference instead of order-book style suggestions.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

DISCLAIMER = "仅供学习和复盘，不构成投资建议。场外基金按净值确认，不存在实时挂单价。"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip().replace("%", "").replace(",", "")
            if not value or value in {"-", "--", "N/A"}:
                return None
        parsed = float(value)
        return parsed if parsed == parsed else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


def _payload(source: str, *, data: Any, error: Optional[str] = None, stale: bool = False) -> Dict[str, Any]:
    return {"source": source, "stale": stale, "error": error, "updated_at": _now_iso(), "data": data}


class FundProvider:
    """Fail-open EastMoney/AkShare mutual fund provider."""

    source = "eastmoney.fund"

    def analyze_fund(self, fund_code: str, *, budget: float = 10000.0) -> Dict[str, Any]:
        code = self._normalize_fund_code(fund_code)
        if not code:
            return _payload(self.source, data=None, error="fund_code_required", stale=True)
        try:
            profile = self._get_profile(code)
            nav = self._get_nav_history(code)
            data = self._build_analysis(code=code, profile=profile, nav=nav, budget=budget)
            return _payload(self.source, data=data, stale=not bool(nav), error=None if nav else "empty_fund_nav")
        except Exception as exc:
            logger.warning("Fund analysis failed for %s: %s", code, exc, exc_info=True)
            return _payload(self.source, data=None, error=str(exc) or type(exc).__name__, stale=True)

    @staticmethod
    def _normalize_fund_code(value: str) -> str:
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        return digits.zfill(6) if digits else ""

    def _get_profile(self, code: str) -> Dict[str, Any]:
        try:
            import akshare as ak

            info = getattr(ak, "fund_individual_basic_info_xq", None)
            if callable(info):
                df = info(symbol=code)
                profile = self._profile_from_key_value_frame(df)
                if profile:
                    return profile
        except Exception as exc:
            logger.debug("fund profile via xq failed for %s: %s", code, exc)
        try:
            import akshare as ak

            names = getattr(ak, "fund_name_em", None)
            if callable(names):
                df = names()
                if df is not None and not getattr(df, "empty", True):
                    code_col = self._pick_column(df, ["基金代码", "代码", "fund_code"])
                    if code_col:
                        rows = df[df[code_col].astype(str).str.zfill(6) == code]
                        if not rows.empty:
                            row = rows.iloc[0]
                            return {
                                "name": _text(row.get("基金简称") or row.get("基金名称") or row.get("简称")),
                                "type": _text(row.get("基金类型") or row.get("类型")),
                            }
        except Exception as exc:
            logger.debug("fund name lookup failed for %s: %s", code, exc)
        return {}

    def _get_nav_history(self, code: str) -> List[Dict[str, Any]]:
        try:
            import akshare as ak

            func = getattr(ak, "fund_open_fund_info_em", None)
            if not callable(func):
                return []
            df = func(symbol=code, indicator="单位净值走势")
            if df is None or getattr(df, "empty", True):
                return []
            date_col = self._pick_column(df, ["净值日期", "日期", "FSRQ", "date"])
            nav_col = self._pick_column(df, ["单位净值", "DWJZ", "净值", "nav"])
            acc_col = self._pick_column(df, ["累计净值", "LJJZ", "acc_nav"])
            growth_col = self._pick_column(df, ["日增长率", "JZZZL", "涨跌幅", "growth"])
            records: List[Dict[str, Any]] = []
            for _, row in df.tail(260).iterrows():
                date_value = row.get(date_col) if date_col else None
                records.append({
                    "date": date_value.strftime("%Y-%m-%d") if hasattr(date_value, "strftime") else _text(date_value),
                    "nav": _safe_float(row.get(nav_col) if nav_col else None),
                    "acc_nav": _safe_float(row.get(acc_col) if acc_col else None),
                    "growth_pct": _safe_float(row.get(growth_col) if growth_col else None),
                })
            return [item for item in records if item.get("date") and item.get("nav") is not None]
        except Exception as exc:
            logger.warning("fund nav failed for %s: %s", code, exc)
            return []

    @staticmethod
    def _pick_column(df: Any, names: List[str]) -> Optional[str]:
        columns = {str(col).strip(): col for col in getattr(df, "columns", [])}
        for name in names:
            if name in columns:
                return columns[name]
        lowered = {str(col).strip().lower(): col for col in getattr(df, "columns", [])}
        for name in names:
            if name.lower() in lowered:
                return lowered[name.lower()]
        return None

    @staticmethod
    def _profile_from_key_value_frame(df: Any) -> Dict[str, Any]:
        if df is None or getattr(df, "empty", True):
            return {}
        profile: Dict[str, Any] = {}
        for _, row in df.iterrows():
            values = list(row.values)
            if len(values) < 2:
                continue
            key = _text(values[0])
            value = _text(values[1])
            if not key or not value:
                continue
            if "基金名称" in key or key == "名称":
                profile["name"] = value
            elif "基金类型" in key or key == "类型":
                profile["type"] = value
            elif "基金经理" in key:
                profile["manager"] = value
            elif "成立日期" in key:
                profile["inception_date"] = value
            elif "资产规模" in key or "基金规模" in key:
                profile["scale"] = value
        return profile

    def _build_analysis(self, *, code: str, profile: Dict[str, Any], nav: List[Dict[str, Any]], budget: float) -> Dict[str, Any]:
        latest = nav[-1] if nav else {}
        nav_values = [item["nav"] for item in nav if _safe_float(item.get("nav")) is not None]
        latest_nav = _safe_float(latest.get("nav"))
        returns = {
            "1w": self._period_return(nav_values, 5),
            "1m": self._period_return(nav_values, 21),
            "3m": self._period_return(nav_values, 63),
            "6m": self._period_return(nav_values, 126),
            "1y": self._period_return(nav_values, 252),
        }
        max_drawdown = self._max_drawdown(nav_values)
        risk_level = "低" if max_drawdown is not None and max_drawdown > -5 else "中" if max_drawdown is not None and max_drawdown > -15 else "高"
        score = self._fund_score(returns=returns, max_drawdown=max_drawdown)
        action = "分批观察"
        if score >= 75:
            action = "分批申购"
        elif score < 45:
            action = "暂缓申购"
        first_amount = 0.0 if action == "暂缓申购" else round((budget or 10000.0) * (0.3 if score < 75 else 0.4), 2)
        summary = self._summary(name=profile.get("name") or code, returns=returns, max_drawdown=max_drawdown, score=score, action=action)
        return {
            "code": code,
            "name": profile.get("name") or code,
            "type": profile.get("type") or "场外基金",
            "manager": profile.get("manager"),
            "scale": profile.get("scale"),
            "latest_nav": latest_nav,
            "latest_date": latest.get("date"),
            "latest_growth_pct": latest.get("growth_pct"),
            "returns": returns,
            "max_drawdown_pct": max_drawdown,
            "risk_level": risk_level,
            "ai_score": score,
            "summary": summary,
            "subscription_reference": {
                "budget": round(float(budget or 10000.0), 2),
                "action": action,
                "first_amount": first_amount,
                "batch_plan": self._batch_plan(action, float(budget or 10000.0)),
                "timing": "场外基金按交易日净值确认，可用定投/分批申购替代追涨。",
                "invalid_condition": "同类指数或基金净值继续创新低且回撤扩大时，暂停新增申购。",
                "disclaimer": DISCLAIMER,
            },
            "nav_history": nav,
            "disclaimer": DISCLAIMER,
        }

    @staticmethod
    def _period_return(values: List[float], days: int) -> Optional[float]:
        if len(values) <= days:
            return None
        start = values[-days - 1]
        end = values[-1]
        if start in (None, 0) or end is None:
            return None
        return round((end / start - 1) * 100, 2)

    @staticmethod
    def _max_drawdown(values: List[float]) -> Optional[float]:
        if not values:
            return None
        peak = values[0]
        max_dd = 0.0
        for value in values:
            if value > peak:
                peak = value
            if peak > 0:
                max_dd = min(max_dd, (value / peak - 1) * 100)
        return round(max_dd, 2)

    @staticmethod
    def _fund_score(*, returns: Dict[str, Optional[float]], max_drawdown: Optional[float]) -> int:
        score = 55
        for key, weight in (("1m", 8), ("3m", 10), ("6m", 8), ("1y", 6)):
            value = returns.get(key)
            if value is None:
                continue
            score += weight if value > 0 else -weight
        if max_drawdown is not None:
            if max_drawdown > -5:
                score += 10
            elif max_drawdown < -20:
                score -= 18
            elif max_drawdown < -12:
                score -= 8
        return int(max(0, min(100, score)))

    @staticmethod
    def _summary(*, name: str, returns: Dict[str, Optional[float]], max_drawdown: Optional[float], score: int, action: str) -> str:
        r3m = returns.get("3m")
        drawdown_text = "回撤数据不足" if max_drawdown is None else f"近一年样本最大回撤约 {max_drawdown:.2f}%"
        return f"{name} 当前基金评分 {score}，3个月收益 {r3m if r3m is not None else '--'}%，{drawdown_text}，申购参考为{action}。"

    @staticmethod
    def _batch_plan(action: str, budget: float) -> List[Dict[str, Any]]:
        if action == "暂缓申购":
            return []
        ratios = [0.3, 0.3, 0.4] if action == "分批观察" else [0.4, 0.3, 0.3]
        labels = ["首笔", "回撤/定投第二笔", "趋势确认第三笔"]
        return [{"label": label, "amount": round(budget * ratio, 2)} for label, ratio in zip(labels, ratios)]
