# -*- coding: utf-8 -*-
"""AI 股票复盘工作台 MVP 聚合服务。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from data_provider.base import normalize_stock_code
from data_provider.provider_router import ProviderRouter, get_provider_router
from src.config import get_config
from src.services.history_service import HistoryService
from src.services.system_config_service import SystemConfigService
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)

DISCLAIMER = "仅供学习和复盘，不构成投资建议。"
STATUS_TAGS = {
    "breakout": "强势突破",
    "hold": "趋势持有",
    "wait_volume": "缩量等待",
    "high_risk": "高位风险",
    "reduce": "破位减仓",
    "outflow": "资金流出",
    "confirm": "等待确认",
}


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            value = value.strip().replace("%", "").replace(",", "")
            if not value or value in {"-", "--", "N/A"}:
                return default
        parsed = float(value)
        return parsed if parsed == parsed else default
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    parsed = _safe_float(value)
    return int(parsed) if parsed is not None else default


def _round(value: Any, digits: int = 2) -> Optional[float]:
    parsed = _safe_float(value)
    return round(parsed, digits) if parsed is not None else None


def _fmt_pct(value: Any) -> str:
    parsed = _safe_float(value)
    return "--" if parsed is None else f"{parsed:.2f}%"


def _fmt_amount_yi(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "--"
    if abs(parsed) >= 100000000:
        parsed = parsed / 100000000
    return f"{parsed:.0f}亿" if abs(parsed) >= 100 else f"{parsed:.2f}亿"


def _data_block(source: str, *, data: Any, stale: bool = False, error: Optional[str] = None) -> Dict[str, Any]:
    return {"source": source, "stale": stale, "error": error, "data": data}


def _unwrap(block: Any, default: Any) -> Any:
    if isinstance(block, dict):
        return block.get("data", default)
    return default


def _block_status(*blocks: Dict[str, Any]) -> Dict[str, Any]:
    stale = any(bool(block.get("stale")) for block in blocks if isinstance(block, dict))
    errors = [str(block.get("error")) for block in blocks if isinstance(block, dict) and block.get("error")]
    sources = [str(block.get("source")) for block in blocks if isinstance(block, dict) and block.get("source")]
    return {
        "source": ",".join(dict.fromkeys(sources)) or "workbench",
        "stale": stale,
        "error": "; ".join(errors) if errors else None,
    }


@dataclass
class WorkbenchAnalysis:
    payload: Dict[str, Any]
    risk_tags: List[str]
    opportunity_tags: List[str]
    watch_tags: List[str]


class WorkbenchService:
    """Build four MVP workbench pages from existing providers/services."""

    def __init__(
        self,
        provider_router: Optional[ProviderRouter] = None,
        db_manager: Optional[DatabaseManager] = None,
        system_config_service: Optional[SystemConfigService] = None,
    ):
        self.router = provider_router or get_provider_router()
        self.db = db_manager or DatabaseManager.get_instance()
        self.history_service = HistoryService(db_manager=self.db)
        self.system_config_service = system_config_service or SystemConfigService()

    def get_dashboard(self) -> Dict[str, Any]:
        indices = self._safe_provider_block("main_indices", lambda: _data_block("DataFetcherManager", data=self.router.manager.get_main_indices(region="cn")))
        stats = self._safe_provider_block("market_stats", lambda: _data_block("DataFetcherManager", data=self.router.manager.get_market_stats(purpose="workbench_dashboard")))
        industries = self.router.get_industry_boards()
        concepts = self.router.get_concept_boards()
        limit_pool = self.router.get_limit_up_pool()

        indices_data = self._pick_main_indices(_unwrap(indices, []))
        stats_data = _unwrap(stats, {}) or {}
        industry_top = self._top_boards(_unwrap(industries, []), limit=8)
        concept_top = self._top_boards(_unwrap(concepts, []), limit=8)
        limit_data = _unwrap(limit_pool, []) or []
        summary = self._market_sentiment_summary(indices_data, stats_data, industry_top, concept_top, limit_data)
        status = _block_status(indices, stats, industries, concepts, limit_pool)

        return {
            **status,
            "disclaimer": DISCLAIMER,
            "indices": indices_data,
            "breadth": {
                "up_count": _safe_int(stats_data.get("up_count")),
                "down_count": _safe_int(stats_data.get("down_count")),
                "flat_count": _safe_int(stats_data.get("flat_count")),
                "limit_up_count": _safe_int(stats_data.get("limit_up_count")) or len(limit_data),
                "limit_down_count": _safe_int(stats_data.get("limit_down_count")),
                "total_amount": _round(stats_data.get("total_amount")),
            },
            "strong_industries": industry_top,
            "strong_concepts": concept_top,
            "limit_up_pool": limit_data[:12],
            "ai_market_summary": summary,
        }

    def get_watchlist(self) -> Dict[str, Any]:
        codes = self._read_watchlist_codes()
        rows = [self._build_watchlist_row(code) for code in codes]
        errors = [row.get("error") for row in rows if row.get("error")]
        return {
            "source": "STOCK_LIST,provider_router",
            "stale": any(bool(row.get("stale")) for row in rows),
            "error": "; ".join(errors) if errors else None,
            "disclaimer": DISCLAIMER,
            "items": rows,
        }

    def get_stock_detail(self, symbol: str) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
        quote = self.router.get_realtime_quote(code)
        kline = self.router.get_daily_kline(code)
        money_flow = self.router.get_money_flow(code)
        themes = self.router.infer_stock_themes(code)
        news = self.router.get_stock_news(code)
        lhb = self.router.get_lhb(code)

        quote_data = _unwrap(quote, {}) or {}
        bars = _unwrap(kline, []) or []
        analysis = self._build_ai_analysis(code, quote_data, bars, money_flow, themes)
        latest_history = self._latest_history_record(code)
        status = _block_status(quote, kline, money_flow, themes, news, lhb)

        return {
            **status,
            "disclaimer": DISCLAIMER,
            "symbol": code,
            "name": quote_data.get("name") or self.router.manager.get_stock_name(code, allow_realtime=False) or code,
            "quote": quote_data,
            "kline": bars,
            "money_flow": _unwrap(money_flow, {}) or {},
            "themes": _unwrap(themes, {}) or {"industry": [], "concepts": [], "boards": []},
            "lhb": _unwrap(lhb, {}) or {},
            "news": _unwrap(news, []) or [],
            "ai_analysis": analysis.payload,
            "risk_tags": analysis.risk_tags,
            "opportunity_tags": analysis.opportunity_tags,
            "watch_tags": analysis.watch_tags,
            "latest_report": latest_history,
        }

    def get_daily_review(self) -> Dict[str, Any]:
        dashboard = self.get_dashboard()
        watchlist = self.get_watchlist()
        items = watchlist.get("items", [])
        strongest = dashboard.get("strong_industries", [])[:3] + dashboard.get("strong_concepts", [])[:3]
        risk_boards = self._risk_boards()
        risk_items = [item for item in items if item.get("status_tag") in {STATUS_TAGS["high_risk"], STATUS_TAGS["reduce"], STATUS_TAGS["outflow"]}]
        watch_items = [item for item in items if item.get("status_tag") in {STATUS_TAGS["confirm"], STATUS_TAGS["wait_volume"]}]

        summary_parts = [dashboard.get("ai_market_summary") or "今日市场暂无完整数据，先以自选股和板块热度做轻量复盘。"]
        if risk_items:
            summary_parts.append(f"自选股里 {len(risk_items)} 只出现风险标签，明日优先看能否止跌或资金回流。")
        if strongest:
            summary_parts.append("强势方向集中在 " + "、".join(item.get("name", "") for item in strongest[:3] if item.get("name")) + "。")

        return {
            "source": dashboard.get("source", "workbench"),
            "stale": bool(dashboard.get("stale")) or bool(watchlist.get("stale")),
            "error": "; ".join([x for x in [dashboard.get("error"), watchlist.get("error")] if x]) or None,
            "disclaimer": DISCLAIMER,
            "one_liner": dashboard.get("ai_market_summary"),
            "strongest_boards": strongest,
            "risk_boards": risk_boards,
            "watchlist_performance": items,
            "holding_risks": risk_items,
            "next_day_watchlist": watch_items[:10],
            "ai_summary": " ".join(summary_parts),
            "markdown": self.build_daily_review_markdown(dashboard=dashboard, watchlist=watchlist),
        }

    def build_daily_review_markdown(self, dashboard: Optional[Dict[str, Any]] = None, watchlist: Optional[Dict[str, Any]] = None) -> str:
        dashboard = dashboard or self.get_dashboard()
        watchlist = watchlist or self.get_watchlist()
        today = datetime.now().strftime("%Y-%m-%d")
        lines = [
            f"# {today} AI 股票复盘",
            "",
            f"> {DISCLAIMER}",
            "",
            "## 今日市场一句话",
            dashboard.get("ai_market_summary") or "暂无完整市场总结。",
            "",
            "## 主要指数",
        ]
        for item in dashboard.get("indices", []):
            lines.append(f"- {item.get('name')}: {item.get('current', '--')} ({_fmt_pct(item.get('change_pct'))})")
        breadth = dashboard.get("breadth", {})
        lines.extend([
            "",
            "## 市场温度",
            f"- 成交额: {_fmt_amount_yi(breadth.get('total_amount'))}",
            f"- 涨跌家数: {breadth.get('up_count', 0)} / {breadth.get('down_count', 0)}",
            f"- 涨停/跌停: {breadth.get('limit_up_count', 0)} / {breadth.get('limit_down_count', 0)}",
            "",
            "## 今日最强板块",
        ])
        for item in (dashboard.get("strong_industries", [])[:5] + dashboard.get("strong_concepts", [])[:5]):
            lines.append(f"- {item.get('name')}: {_fmt_pct(item.get('change_pct'))}")
        lines.extend(["", "## 自选股表现", "| 代码 | 名称 | 涨跌幅 | AI评分 | 状态 |", "| --- | --- | ---: | ---: | --- |"])
        for item in watchlist.get("items", []):
            lines.append(
                f"| {item.get('symbol', '')} | {item.get('name', '')} | {_fmt_pct(item.get('change_pct'))} | "
                f"{item.get('ai_score', '--')} | {item.get('status_tag', '')} |"
            )
        lines.extend(["", "## 明日观察清单"])
        for item in watchlist.get("items", [])[:10]:
            watch = item.get("next_day_watch") or []
            if watch:
                lines.append(f"- {item.get('name') or item.get('symbol')}: {'；'.join(watch[:2])}")
        return "\n".join(lines).strip() + "\n"

    def _safe_provider_block(self, label: str, getter) -> Dict[str, Any]:
        try:
            block = getter()
            if isinstance(block, dict) and {"source", "stale", "error", "data"}.issubset(block.keys()):
                return block
            return _data_block(label, data=block)
        except Exception as exc:
            logger.warning("Workbench provider block failed: %s: %s", label, exc, exc_info=True)
            return _data_block(label, data=None, stale=True, error=str(exc) or type(exc).__name__)

    def _read_watchlist_codes(self) -> List[str]:
        try:
            config_data = self.system_config_service.get_config(include_schema=False)
            stock_list_str = ""
            for item in config_data.get("items", []):
                if item.get("key") == "STOCK_LIST":
                    stock_list_str = str(item.get("value", ""))
                    break
            return [code.strip() for code in stock_list_str.split(",") if code.strip()]
        except Exception as exc:
            logger.warning("Read watchlist failed: %s", exc)
            try:
                return [code.strip() for code in getattr(get_config(), "stock_list", []) if code.strip()]
            except Exception:
                return []

    def _build_watchlist_row(self, raw_code: str) -> Dict[str, Any]:
        code = normalize_stock_code(raw_code)
        quote = self.router.get_realtime_quote(code)
        money_flow = self.router.get_money_flow(code)
        themes = self.router.infer_stock_themes(code)
        kline = self.router.get_daily_kline(code)
        quote_data = _unwrap(quote, {}) or {}
        bars = _unwrap(kline, []) or []
        analysis = self._build_ai_analysis(code, quote_data, bars, money_flow, themes)
        themes_data = _unwrap(themes, {}) or {}
        capital = _unwrap(money_flow, {}) or {}
        stock_flow = capital.get("stock_flow") if isinstance(capital, dict) else {}
        status = _block_status(quote, money_flow, themes, kline)
        return {
            "symbol": code,
            "name": quote_data.get("name") or self.router.manager.get_stock_name(code, allow_realtime=False) or raw_code,
            "latest_price": quote_data.get("price"),
            "change_pct": quote_data.get("change_pct"),
            "amount": quote_data.get("amount"),
            "turnover_rate": quote_data.get("turnover_rate"),
            "main_net_inflow": (stock_flow or {}).get("main_net_inflow") if isinstance(stock_flow, dict) else None,
            "industry": (themes_data.get("industry") or [None])[0] if isinstance(themes_data.get("industry"), list) else "",
            "concepts": themes_data.get("concepts") or [],
            "ai_score": analysis.payload.get("ai_score"),
            "status_tag": analysis.payload.get("status_tag"),
            "risk_tags": analysis.risk_tags,
            "opportunity_tags": analysis.opportunity_tags,
            "watch_tags": analysis.watch_tags,
            "next_day_watch": analysis.payload.get("next_day_watch", []),
            **status,
        }

    @staticmethod
    def _pick_main_indices(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        names = ("上证指数", "深证成指", "创业板指")
        normalized = []
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            if item.get("name") in names:
                normalized.append({
                    "code": item.get("code"),
                    "name": item.get("name"),
                    "current": _round(item.get("current")),
                    "change": _round(item.get("change")),
                    "change_pct": _round(item.get("change_pct")),
                    "amount": _round(item.get("amount")),
                })
        order = {name: index for index, name in enumerate(names)}
        return sorted(normalized, key=lambda item: order.get(item.get("name"), 99))

    @staticmethod
    def _top_boards(rows: Iterable[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
        unique: Dict[str, Dict[str, Any]] = {}
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in unique:
                continue
            unique[name] = {
                "name": name,
                "type": item.get("type") or item.get("direction"),
                "change_pct": _round(item.get("change_pct")),
                "amount": _round(item.get("amount")),
                "leading_stock": item.get("leading_stock"),
            }
        return sorted(unique.values(), key=lambda item: _safe_float(item.get("change_pct"), -999) or -999, reverse=True)[:limit]

    def _risk_boards(self) -> List[Dict[str, Any]]:
        try:
            industries = self.router.get_industry_boards()
            concepts = self.router.get_concept_boards()
            rows = (_unwrap(industries, []) or []) + (_unwrap(concepts, []) or [])
            return sorted(
                [item for item in rows if _safe_float(item.get("change_pct"), 0) is not None],
                key=lambda item: _safe_float(item.get("change_pct"), 0) or 0,
            )[:8]
        except Exception:
            return []

    @staticmethod
    def _market_sentiment_summary(indices: List[Dict[str, Any]], stats: Dict[str, Any], industries: List[Dict[str, Any]], concepts: List[Dict[str, Any]], limit_pool: List[Dict[str, Any]]) -> str:
        avg_index = sum(_safe_float(item.get("change_pct"), 0) or 0 for item in indices) / max(len(indices), 1)
        up_count = _safe_int(stats.get("up_count"))
        down_count = _safe_int(stats.get("down_count"))
        limit_count = _safe_int(stats.get("limit_up_count")) or len(limit_pool)
        hot_names = [item.get("name") for item in industries[:2] + concepts[:2] if item.get("name")]
        if avg_index > 0.8 and up_count > down_count:
            mood = "市场情绪偏强，赚钱效应主要来自指数与题材共振"
        elif avg_index < -0.8 or down_count > up_count * 1.5:
            mood = "市场情绪偏谨慎，普通用户更适合先看风险和仓位"
        elif limit_count >= 40:
            mood = "短线情绪活跃，但需要区分板块持续性和一日游"
        else:
            mood = "市场整体偏震荡，适合围绕强势板块和自选股关键位做复盘"
        suffix = f"；当前强势方向：{'、'.join(hot_names[:4])}" if hot_names else "。"
        return mood + suffix

    def _build_ai_analysis(
        self,
        code: str,
        quote: Dict[str, Any],
        bars: List[Dict[str, Any]],
        money_flow: Dict[str, Any],
        themes: Dict[str, Any],
    ) -> WorkbenchAnalysis:
        latest = bars[-1] if bars else {}
        close = _safe_float(quote.get("price"), _safe_float(latest.get("close")))
        change_pct = _safe_float(quote.get("change_pct"), _safe_float(latest.get("pct_chg"), 0)) or 0
        ma5 = _safe_float(latest.get("ma5"))
        ma10 = _safe_float(latest.get("ma10"))
        ma20 = _safe_float(latest.get("ma20"))
        ma60 = _safe_float(latest.get("ma60"))
        rsi = _safe_float(latest.get("rsi"), 50) or 50
        macd = _safe_float(latest.get("macd"), 0) or 0
        stock_flow = (_unwrap(money_flow, {}) or {}).get("stock_flow", {}) if isinstance(money_flow, dict) else {}
        main_inflow = _safe_float((stock_flow or {}).get("main_net_inflow"), 0) or 0
        theme_data = _unwrap(themes, {}) or {}
        hot_topics = (theme_data.get("industry") or [])[:2] + (theme_data.get("concepts") or [])[:4]

        technical_score = 50
        if close is not None and ma5 and ma10 and ma20:
            if close >= ma5 >= ma10 >= ma20:
                technical_score += 22
            elif close >= ma20:
                technical_score += 10
            else:
                technical_score -= 15
        if macd > 0:
            technical_score += 6
        if 45 <= rsi <= 70:
            technical_score += 5
        elif rsi > 78:
            technical_score -= 12
        if change_pct > 5:
            technical_score += 6
        if change_pct < -5:
            technical_score -= 10

        capital_score = 55 + (12 if main_inflow > 0 else -12 if main_inflow < 0 else 0)
        sector_score = 55 + min(len(hot_topics) * 4, 20)
        ai_score = int(max(0, min(100, technical_score * 0.5 + capital_score * 0.25 + sector_score * 0.25)))

        risk_tags: List[str] = []
        opportunity_tags: List[str] = []
        watch_tags: List[str] = []
        if rsi > 78:
            risk_tags.append("高位过热")
        if close is not None and ma20 and close < ma20:
            risk_tags.append("跌破20日线")
        if main_inflow < 0:
            risk_tags.append("主力净流出")
        if close is not None and ma5 and ma10 and ma20 and close >= ma5 >= ma10 >= ma20:
            opportunity_tags.append("均线多头")
        if change_pct > 3:
            opportunity_tags.append("日内强势")
        if not hot_topics:
            watch_tags.append("题材归属待确认")
        if 40 <= rsi <= 60:
            watch_tags.append("指标中性")

        if risk_tags and (close is not None and ma20 and close < ma20):
            status_tag = STATUS_TAGS["reduce"]
        elif main_inflow < 0 and ai_score < 60:
            status_tag = STATUS_TAGS["outflow"]
        elif rsi > 78:
            status_tag = STATUS_TAGS["high_risk"]
        elif opportunity_tags and change_pct > 3:
            status_tag = STATUS_TAGS["breakout"]
        elif opportunity_tags:
            status_tag = STATUS_TAGS["hold"]
        elif watch_tags:
            status_tag = STATUS_TAGS["wait_volume"]
        else:
            status_tag = STATUS_TAGS["confirm"]

        support = self._price_level([ma5, ma10, ma20, latest.get("boll_lower")], prefer="below", price=close)
        resistance = self._price_level([latest.get("boll_upper"), latest.get("high"), ma60], prefer="above", price=close)
        history_summary = self._latest_history_summary(code)
        summary = history_summary or self._plain_stock_summary(status_tag, ai_score, risk_tags, opportunity_tags)
        payload = {
            "symbol": code,
            "name": quote.get("name") or self.router.manager.get_stock_name(code, allow_realtime=False) or "",
            "summary": summary,
            "ai_score": ai_score,
            "status_tag": status_tag,
            "trend": {
                "direction": "上行" if opportunity_tags else "下行" if risk_tags else "震荡",
                "strength": max(0, min(100, int(technical_score))),
                "reason": "看MA5/10/20排列、MACD和当天涨跌幅，偏向普通复盘口径。",
            },
            "technical": {
                "score": max(0, min(100, int(technical_score))),
                "summary": self._technical_words(close, ma5, ma10, ma20, rsi, macd),
                "support": support,
                "resistance": resistance,
            },
            "capital": {
                "score": max(0, min(100, int(capital_score))),
                "summary": "主力资金偏流入。" if main_inflow > 0 else "主力资金偏流出，短线要看能否回流。" if main_inflow < 0 else "资金流数据暂不明显。",
            },
            "sector": {
                "score": max(0, min(100, int(sector_score))),
                "hot_topics": hot_topics,
                "summary": "所属题材有可跟踪热度。" if hot_topics else "暂未识别出明确题材，需要结合公告和新闻确认。",
            },
            "risks": risk_tags or ["暂无明显风险标签，但仍需控制仓位。"],
            "next_day_watch": self._next_day_watch(status_tag, support, resistance, main_inflow),
            "operation_reference": {
                "action": self._operation_action(status_tag),
                "confidence": min(95, max(20, ai_score)),
                "invalid_condition": f"跌破观察支撑 {support}" if support else "放量下跌且资金继续流出",
            },
            "disclaimer": DISCLAIMER,
        }
        return WorkbenchAnalysis(payload=payload, risk_tags=risk_tags, opportunity_tags=opportunity_tags, watch_tags=watch_tags)

    @staticmethod
    def _price_level(values: Iterable[Any], *, prefer: str, price: Optional[float]) -> str:
        parsed = sorted(v for v in (_safe_float(value) for value in values) if v is not None)
        if not parsed:
            return ""
        if price is None:
            return f"{parsed[-1]:.2f}" if prefer == "below" else f"{parsed[0]:.2f}"
        if prefer == "below":
            candidates = [value for value in parsed if value <= price]
            return f"{(candidates[-1] if candidates else parsed[0]):.2f}"
        candidates = [value for value in parsed if value >= price]
        return f"{(candidates[0] if candidates else parsed[-1]):.2f}"

    @staticmethod
    def _plain_stock_summary(status_tag: str, score: int, risks: List[str], opportunities: List[str]) -> str:
        if risks:
            return f"当前状态为{status_tag}，AI评分{score}。主要风险是{'、'.join(risks[:2])}。"
        if opportunities:
            return f"当前状态为{status_tag}，AI评分{score}。亮点是{'、'.join(opportunities[:2])}。"
        return f"当前状态为{status_tag}，AI评分{score}，更适合等待方向确认。"

    @staticmethod
    def _technical_words(close: Optional[float], ma5: Optional[float], ma10: Optional[float], ma20: Optional[float], rsi: float, macd: float) -> str:
        parts = []
        if close is not None and ma5 and ma10 and ma20:
            parts.append("价格站在短中期均线上方" if close >= ma5 >= ma10 >= ma20 else "均线结构还没有完全走顺" if close >= ma20 else "价格低于20日线，趋势偏弱")
        parts.append("MACD偏多" if macd > 0 else "MACD仍偏弱")
        parts.append("RSI偏热" if rsi > 70 else "RSI中性" if rsi >= 40 else "RSI偏弱")
        return "，".join(parts) + "。"

    @staticmethod
    def _next_day_watch(status_tag: str, support: str, resistance: str, main_inflow: float) -> List[str]:
        watch = []
        if support:
            watch.append(f"观察是否守住 {support} 附近支撑")
        if resistance:
            watch.append(f"放量突破 {resistance} 再确认强度")
        watch.append("看主力资金是否继续流入" if main_inflow >= 0 else "先看资金能否从流出转为回流")
        if status_tag in {STATUS_TAGS["high_risk"], STATUS_TAGS["reduce"]}:
            watch.append("若继续放量下跌，优先降低风险暴露")
        return watch[:4]

    @staticmethod
    def _operation_action(status_tag: str) -> str:
        if status_tag in {STATUS_TAGS["breakout"], STATUS_TAGS["confirm"]}:
            return "观察"
        if status_tag == STATUS_TAGS["hold"]:
            return "持有"
        if status_tag in {STATUS_TAGS["reduce"], STATUS_TAGS["high_risk"], STATUS_TAGS["outflow"]}:
            return "减仓"
        return "等待确认"

    def _latest_history_record(self, code: str) -> Optional[Dict[str, Any]]:
        try:
            records = self.db.get_analysis_history(code=code, days=90, limit=1)
            if not records:
                return None
            detail = self.history_service.get_history_detail_by_id(records[0].id)
            return detail
        except Exception as exc:
            logger.debug("Latest history detail failed for %s: %s", code, exc)
            return None

    def _latest_history_summary(self, code: str) -> str:
        try:
            records = self.db.get_analysis_history(code=code, days=90, limit=1)
            if not records:
                return ""
            raw = getattr(records[0], "analysis_summary", None)
            if raw:
                return str(raw).strip()[:240]
            raw_result = getattr(records[0], "raw_result", None)
            if raw_result:
                data = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
                if isinstance(data, dict):
                    summary = data.get("analysis_summary") or data.get("summary")
                    if summary:
                        return str(summary).strip()[:240]
        except Exception:
            return ""
        return ""
