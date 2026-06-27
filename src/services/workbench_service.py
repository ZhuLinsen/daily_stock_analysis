# -*- coding: utf-8 -*-
"""AI 股票复盘工作台 MVP 聚合服务。"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, TimeoutError, wait
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from data_provider.base import normalize_stock_code, _is_etf_code
from data_provider.provider_router import ProviderRouter, get_provider_router
from src.config import get_config
from src.data.stock_index_loader import get_index_stock_name
from src.data.stock_mapping import STOCK_NAME_MAP, is_meaningful_stock_name
from src.services.history_service import HistoryService
from src.services.portfolio_service import PortfolioService
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
BENIGN_DATA_ERRORS = {
    "empty_limit_up_pool",
    "remote_fetch_skipped_for_fast_view",
    "fuyao_quote_unavailable",
    "unsupported_fuyao_stock_code",
    "etf_quote_cache_unavailable",
    "etf_quote_unavailable",
    "empty_etf_kline",
    "market_stats_deferred_for_fast_view",
    "limit_up_pool_deferred_for_fast_view",
}
PROVIDER_TIMEOUT_SECONDS = 5.0
DETAIL_KLINE_TIMEOUT_SECONDS = 8.0
WATCHLIST_MAX_WORKERS = 8
WATCHLIST_TOTAL_TIMEOUT_SECONDS = 14.0
DASHBOARD_TOTAL_TIMEOUT_SECONDS = 6.0
DETAIL_TOTAL_TIMEOUT_SECONDS = 10.0
WATCHLIST_ROW_TIMEOUT_SECONDS = 3.0
DAILY_REVIEW_TOTAL_TIMEOUT_SECONDS = 18.0
PORTFOLIO_ACTIONS_TIMEOUT_SECONDS = 8.0


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
    errors: List[str] = []
    for block in blocks:
        if not isinstance(block, dict) or not block.get("error"):
            continue
        errors.extend(_non_benign_errors(block.get("error")))
    sources = [str(block.get("source")) for block in blocks if isinstance(block, dict) and block.get("source")]
    return {
        "source": ",".join(dict.fromkeys(sources)) or "workbench",
        "stale": stale,
        "error": "; ".join(errors) if errors else None,
    }


def _non_benign_errors(error: Any) -> List[str]:
    parts = [part.strip() for part in str(error or "").split(";") if part and part.strip()]
    return [part for part in parts if part not in BENIGN_DATA_ERRORS]


def _local_stock_name(code: str) -> str:
    static_name = STOCK_NAME_MAP.get(code)
    if is_meaningful_stock_name(static_name, code):
        return str(static_name)
    index_name = get_index_stock_name(code)
    if is_meaningful_stock_name(index_name, code):
        return str(index_name)
    return ""


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
        blocks = self._collect_provider_blocks(
            {
                "indices": self.router.get_main_indices,
                "stats": self.router.get_market_stats,
                "industries": self.router.get_industry_boards,
                "concepts": self.router.get_concept_boards,
                "limit_pool": self.router.get_limit_up_pool,
            },
            total_timeout_seconds=DASHBOARD_TOTAL_TIMEOUT_SECONDS,
        )
        indices = blocks["indices"]
        stats = blocks["stats"]
        industries = blocks["industries"]
        concepts = blocks["concepts"]
        limit_pool = blocks["limit_pool"]

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
                "sample_size": _safe_int(stats_data.get("sample_size")),
                "total_count": _safe_int(stats_data.get("total_count")),
                "partial": bool(stats_data.get("partial")),
                "estimated": bool(stats_data.get("estimated")),
            },
            "strong_industries": industry_top,
            "strong_concepts": concept_top,
            "limit_up_pool": limit_data[:12],
            "ai_market_summary": summary,
        }

    def get_watchlist(self, *, entry_budget: float = 10000.0) -> Dict[str, Any]:
        codes = self._read_watchlist_codes()
        rows = self._build_watchlist_rows(codes, entry_budget=entry_budget)
        errors: List[str] = []
        for row in rows:
            errors.extend(_non_benign_errors(row.get("error")))
        return {
            "source": "STOCK_LIST,provider_router",
            "stale": any(bool(row.get("stale")) for row in rows),
            "error": "; ".join(errors) if errors else None,
            "disclaimer": DISCLAIMER,
            "entry_budget": _round(entry_budget) or 10000.0,
            "items": rows,
        }

    def get_portfolio_actions(self, *, account_id: Optional[int] = None, cost_method: str = "fifo") -> Dict[str, Any]:
        """Build plain-language action cards from the existing portfolio snapshot.

        This intentionally stays rule-based and fast. It reuses the portfolio
        service's current price, P/L, stale-price, and account value fields so
        page loads do not wait on a fresh LLM analysis for every holding.
        """
        try:
            snapshot = self._call_with_timeout(
                "portfolio_actions_snapshot",
                lambda: PortfolioService().get_portfolio_snapshot(account_id=account_id, cost_method=cost_method),
                PORTFOLIO_ACTIONS_TIMEOUT_SECONDS,
            )
            if isinstance(snapshot, dict) and snapshot.get("error"):
                return {
                    "source": "portfolio_snapshot",
                    "stale": True,
                    "error": snapshot.get("error"),
                    "disclaimer": DISCLAIMER,
                    "as_of": datetime.now().date().isoformat(),
                    "items": [],
                    "summary": self._portfolio_action_summary([]),
                }
            if not isinstance(snapshot, dict):
                raise ValueError("invalid_portfolio_snapshot")

            items = self._build_portfolio_action_items(snapshot)
            errors = []
            if snapshot.get("fx_stale"):
                errors.append("portfolio_fx_or_price_stale")
            for item in items:
                if item.get("price_stale"):
                    errors.append("portfolio_position_price_stale")
                if not item.get("price_available", True):
                    errors.append("portfolio_position_price_unavailable")
            return {
                "source": "portfolio_snapshot,workbench_rules",
                "stale": bool(snapshot.get("fx_stale")) or any(bool(item.get("price_stale")) for item in items),
                "error": "; ".join(dict.fromkeys(errors)) if errors else None,
                "disclaimer": DISCLAIMER,
                "as_of": snapshot.get("as_of"),
                "currency": snapshot.get("currency") or "CNY",
                "total_market_value": _round(snapshot.get("total_market_value"), 2) or 0,
                "items": items,
                "summary": self._portfolio_action_summary(items),
            }
        except Exception as exc:
            logger.warning("Portfolio action cards failed: %s", exc, exc_info=True)
            return {
                "source": "portfolio_snapshot,workbench_rules",
                "stale": True,
                "error": str(exc) or type(exc).__name__,
                "disclaimer": DISCLAIMER,
                "as_of": datetime.now().date().isoformat(),
                "items": [],
                "summary": self._portfolio_action_summary([]),
            }

    def get_stock_detail(self, symbol: str) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
        blocks = self._collect_provider_blocks(
            {
                "quote": lambda: self.router.get_realtime_quote(code, allow_legacy_remote=False),
                "kline": lambda: self.router.get_ths_stock_daily_kline(code),
                "money_flow": lambda: self.router.get_money_flow(code, allow_remote=False),
                "themes": lambda: self.router.infer_stock_themes(code, allow_remote=False),
                "news": lambda: _data_block("workbench.fast", data=[], stale=True, error="remote_fetch_skipped_for_fast_view"),
                "lhb": lambda: _data_block("workbench.fast", data={}, stale=True, error="remote_fetch_skipped_for_fast_view"),
            },
            total_timeout_seconds=DETAIL_TOTAL_TIMEOUT_SECONDS,
        )
        quote = blocks["quote"]
        kline = blocks["kline"]
        if not _unwrap(kline, []):
            kline = self._safe_provider_block(
                "daily_kline_cache",
                lambda: self.router.get_daily_kline(code, allow_remote=False),
                timeout_seconds=2.0,
            )
        money_flow = blocks["money_flow"]
        themes = blocks["themes"]
        news = blocks["news"]
        lhb = blocks["lhb"]

        quote_data = _unwrap(quote, {}) or {}
        bars = _unwrap(kline, []) or []
        analysis = self._build_ai_analysis(code, quote_data, bars, money_flow, themes)
        latest_history = self._latest_history_record(code)
        status = _block_status(quote, kline, money_flow, themes, news, lhb)

        return {
            **status,
            "disclaimer": DISCLAIMER,
            "symbol": code,
            "name": quote_data.get("name") or _local_stock_name(code) or code,
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
        pages = self._collect_page_payloads(
            {"dashboard": self.get_dashboard, "watchlist": self.get_watchlist, "portfolio_actions": self.get_portfolio_actions},
            total_timeout_seconds=DAILY_REVIEW_TOTAL_TIMEOUT_SECONDS,
        )
        dashboard = pages["dashboard"]
        watchlist = pages["watchlist"]
        portfolio_actions = pages["portfolio_actions"]
        items = watchlist.get("items", [])
        action_items = portfolio_actions.get("items", []) if isinstance(portfolio_actions, dict) else []
        strongest = dashboard.get("strong_industries", [])[:3] + dashboard.get("strong_concepts", [])[:3]
        risk_boards = self._risk_boards()
        risk_items = [item for item in items if item.get("status_tag") in {STATUS_TAGS["high_risk"], STATUS_TAGS["reduce"], STATUS_TAGS["outflow"]}]
        watch_items = [item for item in items if item.get("status_tag") in {STATUS_TAGS["confirm"], STATUS_TAGS["wait_volume"]}]
        urgent_holding_actions = [item for item in action_items if item.get("action") in {"减仓", "止损观察"}]

        summary_parts = [dashboard.get("ai_market_summary") or "今日市场暂无完整数据，先以自选股和板块热度做轻量复盘。"]
        if risk_items:
            summary_parts.append(f"自选股里 {len(risk_items)} 只出现风险标签，明日优先看能否止跌或资金回流。")
        if urgent_holding_actions:
            summary_parts.append(f"持仓里 {len(urgent_holding_actions)} 只需要优先处理，先看仓位和止损观察条件。")
        if strongest:
            summary_parts.append("强势方向集中在 " + "、".join(item.get("name", "") for item in strongest[:3] if item.get("name")) + "。")

        return {
            "source": dashboard.get("source", "workbench"),
            "stale": bool(dashboard.get("stale")) or bool(watchlist.get("stale")) or bool(portfolio_actions.get("stale")),
            "error": "; ".join(
                dict.fromkeys(
                    _non_benign_errors(dashboard.get("error"))
                    + _non_benign_errors(watchlist.get("error"))
                    + _non_benign_errors(portfolio_actions.get("error"))
                )
            ) or None,
            "disclaimer": DISCLAIMER,
            "one_liner": dashboard.get("ai_market_summary"),
            "strongest_boards": strongest,
            "risk_boards": risk_boards,
            "watchlist_performance": items,
            "holding_risks": risk_items,
            "portfolio_action_list": action_items,
            "holding_action_summary": portfolio_actions.get("summary", self._portfolio_action_summary([])),
            "next_day_watchlist": watch_items[:10],
            "ai_summary": " ".join(summary_parts),
            "markdown": self.build_daily_review_markdown(dashboard=dashboard, watchlist=watchlist, portfolio_actions=portfolio_actions),
        }

    def build_daily_review_markdown(
        self,
        dashboard: Optional[Dict[str, Any]] = None,
        watchlist: Optional[Dict[str, Any]] = None,
        portfolio_actions: Optional[Dict[str, Any]] = None,
    ) -> str:
        dashboard = dashboard or self.get_dashboard()
        watchlist = watchlist or self.get_watchlist()
        portfolio_actions = portfolio_actions or self.get_portfolio_actions()
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
        lines.extend([
            "",
            "## 明日持仓处理清单",
            "| 代码 | 名称 | 仓位 | 盈亏 | 建议 | 普通话解释 |",
            "| --- | --- | ---: | ---: | --- | --- |",
        ])
        for item in portfolio_actions.get("items", []):
            lines.append(
                f"| {item.get('symbol', '')} | {item.get('name', '')} | {_fmt_pct(item.get('weight_pct'))} | "
                f"{_fmt_pct(item.get('unrealized_pnl_pct'))} | {item.get('action', '')} | {item.get('reason', '')} |"
            )
        lines.extend(["", "## 明日观察清单"])
        for item in watchlist.get("items", [])[:10]:
            watch = item.get("next_day_watch") or []
            if watch:
                lines.append(f"- {item.get('name') or item.get('symbol')}: {'；'.join(watch[:2])}")
        return "\n".join(lines).strip() + "\n"

    def _safe_provider_block(self, label: str, getter, *, timeout_seconds: Optional[float] = None) -> Dict[str, Any]:
        try:
            block = self._call_with_timeout(label, getter, timeout_seconds) if timeout_seconds is not None else getter()
            return self._normalize_provider_block(label, block)
        except Exception as exc:
            logger.warning("Workbench provider block failed: %s: %s", label, exc, exc_info=True)
            return _data_block(label, data=None, stale=True, error=str(exc) or type(exc).__name__)

    @staticmethod
    def _normalize_provider_block(label: str, block: Any) -> Dict[str, Any]:
        if isinstance(block, dict) and block.get("error") in BENIGN_DATA_ERRORS:
            block = {**block, "error": None, "stale": True}
        if isinstance(block, dict) and {"source", "stale", "error", "data"}.issubset(block.keys()):
            return block
        return _data_block(label, data=block)

    def _collect_provider_blocks(self, getters: Dict[str, Any], *, total_timeout_seconds: float) -> Dict[str, Dict[str, Any]]:
        if not getters:
            return {}
        executor = ThreadPoolExecutor(max_workers=min(len(getters), 8), thread_name_prefix="workbench-block")
        futures = {executor.submit(getter): label for label, getter in getters.items()}
        results: Dict[str, Dict[str, Any]] = {}
        pending = set(futures)
        deadline = time.monotonic() + total_timeout_seconds
        try:
            while pending and time.monotonic() < deadline:
                done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                for future in done:
                    label = futures[future]
                    try:
                        results[label] = self._normalize_provider_block(label, future.result())
                    except Exception as exc:
                        logger.warning("Workbench provider block failed: %s: %s", label, exc, exc_info=True)
                        results[label] = _data_block(label, data=None, stale=True, error=str(exc) or type(exc).__name__)
            for future in pending:
                label = futures[future]
                future.cancel()
                results[label] = _data_block(label, data=None, stale=True, error=f"timeout_after_{total_timeout_seconds:.0f}s")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return {label: results.get(label, _data_block(label, data=None, stale=True, error="not_started")) for label in getters}

    def _collect_page_payloads(self, getters: Dict[str, Any], *, total_timeout_seconds: float) -> Dict[str, Dict[str, Any]]:
        executor = ThreadPoolExecutor(max_workers=min(len(getters), 4), thread_name_prefix="workbench-page")
        futures = {executor.submit(getter): label for label, getter in getters.items()}
        results: Dict[str, Dict[str, Any]] = {}
        pending = set(futures)
        deadline = time.monotonic() + total_timeout_seconds
        try:
            while pending and time.monotonic() < deadline:
                done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                for future in done:
                    label = futures[future]
                    try:
                        payload = future.result()
                        results[label] = payload if isinstance(payload, dict) else self._fallback_page_payload(label, "invalid_page_payload")
                    except Exception as exc:
                        logger.warning("Workbench page payload failed: %s: %s", label, exc, exc_info=True)
                        results[label] = self._fallback_page_payload(label, str(exc) or type(exc).__name__)
            for future in pending:
                label = futures[future]
                future.cancel()
                results[label] = self._fallback_page_payload(label, f"timeout_after_{total_timeout_seconds:.0f}s")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return {label: results.get(label, self._fallback_page_payload(label, "not_started")) for label in getters}

    @staticmethod
    def _fallback_page_payload(label: str, error: str) -> Dict[str, Any]:
        if label == "dashboard":
            return {
                "source": "workbench.page_timeout",
                "stale": True,
                "error": error,
                "disclaimer": DISCLAIMER,
                "indices": [],
                "breadth": {
                    "up_count": 0,
                    "down_count": 0,
                    "flat_count": 0,
                    "limit_up_count": 0,
                    "limit_down_count": 0,
                    "total_amount": None,
                    "sample_size": 0,
                    "total_count": 0,
                    "partial": False,
                    "estimated": False,
                },
                "strong_industries": [],
                "strong_concepts": [],
                "limit_up_pool": [],
                "ai_market_summary": "市场数据源响应较慢，已先返回降级复盘视图。",
            }
        if label == "watchlist":
            return {
                "source": "workbench.page_timeout",
                "stale": True,
                "error": error,
                "disclaimer": DISCLAIMER,
                "items": [],
            }
        if label == "portfolio_actions":
            return {
                "source": "workbench.page_timeout",
                "stale": True,
                "error": error,
                "disclaimer": DISCLAIMER,
                "as_of": datetime.now().date().isoformat(),
                "items": [],
                "summary": {"持有": 0, "减仓": 0, "加仓等待": 0, "止损观察": 0, "total": 0},
            }
        return {"source": "workbench.page_timeout", "stale": True, "error": error, "disclaimer": DISCLAIMER}

    def _build_portfolio_action_items(self, snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for account in snapshot.get("accounts", []) or []:
            if not isinstance(account, dict):
                continue
            account_market_value = _safe_float(account.get("total_market_value"), 0) or 0
            for position in account.get("positions", []) or []:
                if not isinstance(position, dict):
                    continue
                item = self._build_portfolio_action_item(
                    account=account,
                    position=position,
                    account_market_value=account_market_value,
                )
                items.append(item)
        action_order = {"止损观察": 0, "减仓": 1, "加仓等待": 2, "持有": 3}
        return sorted(
            items,
            key=lambda item: (action_order.get(str(item.get("action")), 99), -(_safe_float(item.get("weight_pct"), 0) or 0)),
        )

    def _build_portfolio_action_item(
        self,
        *,
        account: Dict[str, Any],
        position: Dict[str, Any],
        account_market_value: float,
    ) -> Dict[str, Any]:
        symbol = str(position.get("symbol") or "").strip()
        market_value = _safe_float(position.get("market_value_base"), 0) or 0
        weight_pct = (market_value / account_market_value * 100) if account_market_value > 0 else 0
        pnl_pct = _safe_float(position.get("unrealized_pnl_pct"))
        pnl_value = _safe_float(position.get("unrealized_pnl_base"), 0) or 0
        price_available = bool(position.get("price_available", True))
        price_stale = bool(position.get("price_stale"))
        risk_tags = self._portfolio_risk_tags(
            pnl_pct=pnl_pct,
            weight_pct=weight_pct,
            price_available=price_available,
            price_stale=price_stale,
        )
        ai_score = self._portfolio_ai_score(
            pnl_pct=pnl_pct,
            weight_pct=weight_pct,
            price_available=price_available,
            price_stale=price_stale,
            risk_tags=risk_tags,
        )
        action = self._portfolio_action_label(
            pnl_pct=pnl_pct,
            weight_pct=weight_pct,
            ai_score=ai_score,
            price_available=price_available,
            risk_tags=risk_tags,
        )
        reason = self._portfolio_action_reason(
            action=action,
            pnl_pct=pnl_pct,
            weight_pct=weight_pct,
            ai_score=ai_score,
            price_available=price_available,
            price_stale=price_stale,
            risk_tags=risk_tags,
        )
        next_day_watch = self._portfolio_next_day_watch(
            action=action,
            avg_cost=_safe_float(position.get("avg_cost")),
            last_price=_safe_float(position.get("last_price")),
            pnl_pct=pnl_pct,
            weight_pct=weight_pct,
            price_available=price_available,
        )
        return {
            "account_id": account.get("account_id"),
            "account_name": account.get("account_name") or "",
            "symbol": symbol,
            "name": _local_stock_name(normalize_stock_code(symbol)) or symbol,
            "market": position.get("market") or account.get("market"),
            "currency": account.get("base_currency") or position.get("valuation_currency") or "CNY",
            "quantity": _round(position.get("quantity"), 2) or 0,
            "avg_cost": _round(position.get("avg_cost"), 4),
            "last_price": _round(position.get("last_price"), 4),
            "market_value": _round(market_value, 2) or 0,
            "weight_pct": round(weight_pct, 2),
            "unrealized_pnl": _round(pnl_value, 2) or 0,
            "unrealized_pnl_pct": _round(pnl_pct, 2),
            "ai_score": ai_score,
            "risk_tags": risk_tags,
            "action": action,
            "reason": reason,
            "next_day_watch": next_day_watch,
            "invalid_condition": self._portfolio_invalid_condition(action, pnl_pct=pnl_pct, avg_cost=_safe_float(position.get("avg_cost"))),
            "price_source": position.get("price_source"),
            "price_date": position.get("price_date"),
            "price_stale": price_stale,
            "price_available": price_available,
            "disclaimer": DISCLAIMER,
        }

    @staticmethod
    def _portfolio_risk_tags(
        *,
        pnl_pct: Optional[float],
        weight_pct: float,
        price_available: bool,
        price_stale: bool,
    ) -> List[str]:
        tags: List[str] = []
        if not price_available:
            tags.append("价格不可用")
        elif price_stale:
            tags.append("数据延迟")
        if pnl_pct is not None:
            if pnl_pct <= -8:
                tags.append("亏损扩大")
            elif pnl_pct <= -5:
                tags.append("接近止损线")
            elif pnl_pct >= 18:
                tags.append("浮盈保护")
        if weight_pct >= 35:
            tags.append("单票仓位过高")
        elif weight_pct >= 25:
            tags.append("单票仓位偏高")
        return tags

    @staticmethod
    def _portfolio_ai_score(
        *,
        pnl_pct: Optional[float],
        weight_pct: float,
        price_available: bool,
        price_stale: bool,
        risk_tags: List[str],
    ) -> int:
        score = 62
        if pnl_pct is None:
            score -= 8
        elif pnl_pct <= -10:
            score -= 25
        elif pnl_pct <= -5:
            score -= 14
        elif pnl_pct < 0:
            score -= 4
        elif pnl_pct <= 8:
            score += 10
        elif pnl_pct <= 20:
            score += 8
        else:
            score += 3
        if weight_pct >= 35:
            score -= 14
        elif weight_pct >= 25:
            score -= 8
        elif 4 <= weight_pct <= 15:
            score += 5
        if not price_available:
            score -= 24
        elif price_stale:
            score -= 6
        score -= min(18, max(0, len([tag for tag in risk_tags if tag not in {"浮盈保护"}])) * 5)
        return int(max(0, min(100, score)))

    @staticmethod
    def _portfolio_action_label(
        *,
        pnl_pct: Optional[float],
        weight_pct: float,
        ai_score: int,
        price_available: bool,
        risk_tags: List[str],
    ) -> str:
        if not price_available or (pnl_pct is not None and pnl_pct <= -8):
            return "止损观察"
        if weight_pct >= 30 or ai_score < 45 or "接近止损线" in risk_tags:
            return "减仓"
        if ai_score >= 68 and weight_pct < 15 and (pnl_pct is None or pnl_pct >= -3):
            return "加仓等待"
        return "持有"

    @staticmethod
    def _portfolio_action_reason(
        *,
        action: str,
        pnl_pct: Optional[float],
        weight_pct: float,
        ai_score: int,
        price_available: bool,
        price_stale: bool,
        risk_tags: List[str],
    ) -> str:
        pnl_text = "盈亏未知" if pnl_pct is None else f"当前盈亏约 {pnl_pct:.2f}%"
        weight_text = f"仓位约 {weight_pct:.2f}%"
        risk_text = "，风险点是" + "、".join(risk_tags[:3]) if risk_tags else "，暂未触发明显风险标签"
        if not price_available:
            return f"价格拿不到，{pnl_text}，先不要加仓，明天优先确认行情是否恢复。"
        if action == "止损观察":
            return f"{pnl_text}，{weight_text}{risk_text}。明天先看能否止跌，不能修复就把风险放在第一位。"
        if action == "减仓":
            return f"{pnl_text}，{weight_text}{risk_text}。仓位或亏损已经需要降温，适合先降低波动对账户的影响。"
        if action == "加仓等待":
            stale_text = "不过当前价格有延迟，" if price_stale else ""
            return f"{stale_text}{pnl_text}，{weight_text}，AI评分 {ai_score}。方向不差，但等回踩不破或资金确认后再考虑加，不追高。"
        return f"{pnl_text}，{weight_text}，AI评分 {ai_score}{risk_text}。现阶段以按计划持有和观察关键价为主。"

    @staticmethod
    def _portfolio_next_day_watch(
        *,
        action: str,
        avg_cost: Optional[float],
        last_price: Optional[float],
        pnl_pct: Optional[float],
        weight_pct: float,
        price_available: bool,
    ) -> List[str]:
        watch: List[str] = []
        if avg_cost and avg_cost > 0:
            watch.append(f"观察能否站稳成本线 {avg_cost:.2f} 附近")
        if last_price and last_price > 0:
            if action == "加仓等待":
                watch.append(f"不追涨，等价格回踩 {last_price:.2f} 附近仍能企稳")
            elif action in {"减仓", "止损观察"}:
                watch.append(f"若跌破 {last_price:.2f} 附近并继续放量，先处理风险")
            else:
                watch.append(f"围绕现价 {last_price:.2f} 看承接是否正常")
        if pnl_pct is not None and pnl_pct <= -5:
            watch.append("亏损继续扩大时，不做摊低成本动作")
        if weight_pct >= 25:
            watch.append("单票仓位偏高，优先看账户整体波动")
        if not price_available:
            watch.append("先确认价格源恢复，再判断持仓动作")
        return watch[:4]

    @staticmethod
    def _portfolio_invalid_condition(action: str, *, pnl_pct: Optional[float], avg_cost: Optional[float]) -> str:
        if action == "加仓等待":
            return "跌破成本线或当日放量下跌时，取消加仓观察。"
        if action == "持有":
            return "跌破成本线且亏损扩大到 -5% 以下时，转入减仓/止损观察。"
        if action == "减仓":
            return "重新站回成本线并连续两天企稳后，再评估是否停止减仓。"
        if avg_cost:
            return f"无法收回成本线 {avg_cost:.2f} 且亏损继续扩大时，保持止损观察。"
        if pnl_pct is not None:
            return "亏损继续扩大时，保持止损观察。"
        return "行情和价格源未恢复前，不做新增动作。"

    @staticmethod
    def _portfolio_action_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary: Dict[str, Any] = {"持有": 0, "减仓": 0, "加仓等待": 0, "止损观察": 0, "total": len(items)}
        for item in items:
            action = str(item.get("action") or "")
            if action in summary:
                summary[action] += 1
        return summary

    @staticmethod
    def _call_with_timeout(label: str, getter, timeout_seconds: float) -> Any:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"workbench-{label}")
        future = executor.submit(getter)
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError:
            future.cancel()
            return _data_block(label, data=None, stale=True, error=f"timeout_after_{timeout_seconds:.0f}s")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _build_watchlist_rows(self, codes: List[str], *, entry_budget: float = 10000.0) -> List[Dict[str, Any]]:
        if not codes:
            return []
        max_workers = min(WATCHLIST_MAX_WORKERS, max(1, len(codes)))
        executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="workbench-watchlist")
        futures = {
            executor.submit(self._build_watchlist_row, code, True, entry_budget): (index, code)
            for index, code in enumerate(codes)
        }
        results: Dict[int, Dict[str, Any]] = {}
        pending = set(futures)
        deadline = time.monotonic() + WATCHLIST_TOTAL_TIMEOUT_SECONDS
        try:
            while pending and time.monotonic() < deadline:
                done, pending = wait(pending, timeout=0.4, return_when=FIRST_COMPLETED)
                for future in done:
                    index, raw_code = futures[future]
                    try:
                        results[index] = future.result()
                    except Exception as exc:
                        logger.warning("Workbench watchlist row failed for %s: %s", raw_code, exc, exc_info=True)
                        results[index] = self._fallback_watchlist_row(
                            raw_code,
                            error=str(exc) or type(exc).__name__,
                            entry_budget=entry_budget,
                        )
            for future in pending:
                index, raw_code = futures[future]
                future.cancel()
                results[index] = self._fallback_watchlist_row(
                    raw_code,
                    error=f"timeout_after_{WATCHLIST_TOTAL_TIMEOUT_SECONDS:.0f}s",
                    entry_budget=entry_budget,
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return [results[index] for index in sorted(results)]

    def _fallback_watchlist_row(self, raw_code: str, *, error: str, entry_budget: float = 10000.0) -> Dict[str, Any]:
        code = normalize_stock_code(raw_code)
        name = _local_stock_name(code) or raw_code
        analysis = self._build_ai_analysis(
            code,
            {"name": name},
            [],
            _data_block("workbench.fast", data={}),
            _data_block("workbench.fast", data={"symbol": code, "industry": [], "concepts": [], "boards": []}),
            include_history_summary=False,
            entry_budget=entry_budget,
        )
        return {
            "symbol": code,
            "name": name,
            "latest_price": None,
            "change_pct": None,
            "amount": None,
            "turnover_rate": None,
            "main_net_inflow": None,
            "industry": "",
            "concepts": [],
            "ai_score": analysis.payload.get("ai_score"),
            "status_tag": analysis.payload.get("status_tag"),
            "risk_tags": analysis.risk_tags,
            "opportunity_tags": analysis.opportunity_tags,
            "watch_tags": analysis.watch_tags,
            "next_day_watch": analysis.payload.get("next_day_watch", []),
            "entry_advice": analysis.payload.get("entry_advice", {}),
            "source": "workbench.fast_timeout",
            "stale": True,
            "error": error,
        }

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

    def _build_watchlist_row(self, raw_code: str, fast: bool = False, entry_budget: float = 10000.0) -> Dict[str, Any]:
        code = normalize_stock_code(raw_code)
        if fast:
            quote = self._normalize_provider_block("quote", self.router.get_realtime_quote(code, allow_legacy_remote=False))
            money_flow = _data_block("workbench.fast", data={}, stale=True, error="remote_fetch_skipped_for_fast_view")
            themes = self._normalize_provider_block("themes", self.router.infer_stock_themes(code, allow_remote=False))
            kline = self._normalize_provider_block("kline", self.router.get_daily_kline(code, allow_remote=False))
        else:
            blocks = self._collect_provider_blocks(
                {
                    "quote": lambda: self.router.get_realtime_quote(code, allow_legacy_remote=False),
                    "money_flow": lambda: self.router.get_money_flow(code, allow_remote=True),
                    "themes": lambda: self.router.infer_stock_themes(code, allow_remote=False),
                    "kline": lambda: self.router.get_daily_kline(code, allow_remote=True),
                },
                total_timeout_seconds=DETAIL_TOTAL_TIMEOUT_SECONDS,
            )
            quote = blocks["quote"]
            money_flow = blocks["money_flow"]
            themes = blocks["themes"]
            kline = blocks["kline"]
        quote_data = _unwrap(quote, {}) or {}
        bars = _unwrap(kline, []) or []
        analysis = self._build_ai_analysis(
            code,
            quote_data,
            bars,
            money_flow,
            themes,
            include_history_summary=not fast,
            entry_budget=entry_budget,
        )
        themes_data = _unwrap(themes, {}) or {}
        capital = _unwrap(money_flow, {}) or {}
        stock_flow = capital.get("stock_flow") if isinstance(capital, dict) else {}
        status = _block_status(quote, money_flow, themes, kline)
        return {
            "symbol": code,
            "name": quote_data.get("name") or _local_stock_name(code) or raw_code,
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
            "entry_advice": analysis.payload.get("entry_advice", {}),
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
            industries = self._safe_provider_block("risk_industry_boards", self.router.get_industry_boards, timeout_seconds=PROVIDER_TIMEOUT_SECONDS)
            concepts = self._safe_provider_block("risk_concept_boards", self.router.get_concept_boards, timeout_seconds=PROVIDER_TIMEOUT_SECONDS)
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
        *,
        include_history_summary: bool = True,
        entry_budget: float = 10000.0,
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
        history_summary = self._latest_history_summary(code) if include_history_summary else ""
        summary = history_summary or self._plain_stock_summary(status_tag, ai_score, risk_tags, opportunity_tags)
        payload = {
            "symbol": code,
            "name": quote.get("name") or _local_stock_name(code) or "",
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
            "entry_advice": self._entry_advice(
                code=code,
                budget=entry_budget,
                price=close,
                support=support,
                resistance=resistance,
                status_tag=status_tag,
                ai_score=ai_score,
                main_inflow=main_inflow,
            ),
            "operation_reference": {
                "action": self._operation_action(status_tag),
                "confidence": min(95, max(20, ai_score)),
                "invalid_condition": f"跌破观察支撑 {support}" if support else "放量下跌且资金继续流出",
            },
            "disclaimer": DISCLAIMER,
        }
        return WorkbenchAnalysis(payload=payload, risk_tags=risk_tags, opportunity_tags=opportunity_tags, watch_tags=watch_tags)

    @staticmethod
    def _entry_advice(
        *,
        code: str,
        budget: float,
        price: Optional[float],
        support: str,
        resistance: str,
        status_tag: str,
        ai_score: int,
        main_inflow: float,
    ) -> Dict[str, Any]:
        budget_value = _safe_float(budget, 10000.0) or 10000.0
        tick = 0.001 if _is_etf_code(code) else 0.01

        def parse_level(value: str) -> Optional[float]:
            return _safe_float(value)

        def round_to_tick(value: Optional[float]) -> Optional[float]:
            if value is None or value <= 0:
                return None
            digits = 3 if tick < 0.01 else 2
            return round(round(value / tick) * tick, digits)

        support_price = parse_level(support)
        resistance_price = parse_level(resistance)
        current_price = _safe_float(price)
        action = "等待确认"
        timing = "等价格靠近观察位且资金不再流出时，再考虑限价挂单。"
        basis = "支撑/均线附近"
        planned_budget_ratio = 0.3
        reference_price = support_price or current_price

        if status_tag in {STATUS_TAGS["high_risk"], STATUS_TAGS["reduce"], STATUS_TAGS["outflow"]}:
            action = "暂不建仓"
            timing = "先不挂买单，等风险标签消失、价格重新站回关键均线后再看。"
            basis = "风险优先"
            planned_budget_ratio = 0.0
            reference_price = support_price or current_price
        elif status_tag == STATUS_TAGS["breakout"]:
            action = "突破确认后试仓"
            timing = "只在放量站稳压力位后考虑，缩量冲高不追。"
            basis = "突破压力位"
            planned_budget_ratio = 0.4 if ai_score < 80 else 0.5
            reference_price = resistance_price or current_price
        elif status_tag == STATUS_TAGS["hold"]:
            action = "回踩不破试仓"
            timing = "等回踩支撑附近不破、资金继续回流时挂单。"
            basis = "回踩支撑位"
            planned_budget_ratio = 0.5
            reference_price = support_price or current_price
        elif status_tag in {STATUS_TAGS["wait_volume"], STATUS_TAGS["confirm"]}:
            action = "小仓观察"
            timing = "等量能放大或价格站上短期均线后再小单确认。"
            basis = "观察位附近"
            planned_budget_ratio = 0.3
            reference_price = support_price or current_price

        order_price = round_to_tick(reference_price)
        planned_budget = budget_value * planned_budget_ratio
        lots = 0
        shares = 0
        estimated_amount = 0.0
        if order_price and planned_budget_ratio > 0:
            lots = int(planned_budget // (order_price * 100))
            if lots <= 0 and budget_value >= order_price * 100 and ai_score >= 65:
                lots = 1
            shares = lots * 100
            estimated_amount = round(order_price * shares, 2)
        max_lots = int(budget_value // ((order_price or current_price or 0) * 100)) if (order_price or current_price or 0) > 0 else 0

        if lots <= 0 and planned_budget_ratio > 0:
            action = "资金不足或等待"
            timing = "当前预算按一手单位不足以形成参考挂单，先观察或调低价格区间。"

        invalid_condition = f"有效跌破 {support}" if support else "放量下跌且资金继续流出"
        trigger_condition = f"价格靠近 {order_price:.3f}" if order_price is not None and tick < 0.01 else f"价格靠近 {order_price:.2f}" if order_price is not None else "等待关键价位出现"
        if status_tag == STATUS_TAGS["breakout"] and resistance:
            trigger_condition = f"放量站稳 {resistance} 上方"
        if main_inflow < 0:
            trigger_condition += "，并观察资金由流出转回流"

        return {
            "budget": round(budget_value, 2),
            "planned_budget": round(planned_budget, 2),
            "action": action,
            "timing": timing,
            "order_type": "限价挂单参考",
            "reference_price": order_price,
            "price_basis": basis,
            "lots": lots,
            "shares": shares,
            "estimated_amount": estimated_amount,
            "remaining_cash": round(max(0.0, budget_value - estimated_amount), 2),
            "max_lots": max_lots,
            "trigger_condition": trigger_condition,
            "invalid_condition": invalid_condition,
            "risk_note": "只按首笔试仓估算，普通A股/ETF按100股或100份为1手。",
            "confidence": min(95, max(20, ai_score)),
            "disclaimer": DISCLAIMER,
        }

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
