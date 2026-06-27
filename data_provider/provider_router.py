# -*- coding: utf-8 -*-
"""Provider router for the AI stock workbench MVP.

The router keeps provider fan-out in one place and preserves the page-level
contract: provider failures are represented in the payload rather than raised.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from data_provider.base import DataFetcherManager, normalize_stock_code, _is_etf_code
from data_provider.eastmoney_provider import EastMoneyProvider
from data_provider.ths_provider import THSProvider


class ProviderRouter:
    """Small compatibility layer over new providers and existing manager."""

    def __init__(self, manager: Optional[DataFetcherManager] = None):
        self.manager = manager or DataFetcherManager()
        self.eastmoney = EastMoneyProvider(manager=self.manager)
        self.ths = THSProvider(manager=self.manager)
        self._cache: Dict[str, tuple[datetime, Dict[str, Any]]] = {}

    def _cached(self, key: str, ttl_seconds: int, getter) -> Dict[str, Any]:
        now = datetime.now()
        cached = self._cache.get(key)
        if cached is not None:
            cached_at, payload = cached
            if now - cached_at <= timedelta(seconds=ttl_seconds):
                clone = dict(payload)
                clone["stale"] = bool(clone.get("stale"))
                return clone
        payload = getter()
        if isinstance(payload, dict):
            self._cache[key] = (now, payload)
            return payload
        return {"source": key, "stale": True, "error": "invalid_provider_payload", "data": payload}

    @staticmethod
    def _has_data(payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        data = payload.get("data")
        if isinstance(data, (list, tuple, dict)):
            return bool(data)
        return data is not None

    @staticmethod
    def _merge_fallback_errors(primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(fallback, dict):
            return primary
        errors = [str(value) for value in (primary.get("error"), fallback.get("error")) if value]
        sources = [str(value) for value in (primary.get("source"), fallback.get("source")) if value]
        return {
            **primary,
            "source": ",".join(dict.fromkeys(sources)) or str(primary.get("source") or "provider_router"),
            "error": "; ".join(dict.fromkeys(errors)) if errors else None,
            "stale": bool(primary.get("stale")) or bool(fallback.get("stale")),
        }

    def get_main_indices(self) -> Dict[str, Any]:
        def getter() -> Dict[str, Any]:
            fuyao = self.ths.get_main_indices()
            if self._has_data(fuyao):
                return fuyao
            try:
                fallback = {"source": "DataFetcherManager", "stale": True, "error": None, "data": self.manager.get_main_indices(region="cn")}
            except Exception as exc:
                fallback = {"source": "DataFetcherManager", "stale": True, "error": str(exc) or type(exc).__name__, "data": []}
            return self._merge_fallback_errors(fallback, fuyao)

        return self._cached("main_indices", 15, getter)

    def get_market_stats(self) -> Dict[str, Any]:
        def getter() -> Dict[str, Any]:
            fuyao = self.ths.get_market_stats()
            if self._has_data(fuyao):
                return fuyao
            return {
                "source": "workbench.fast",
                "stale": True,
                "error": fuyao.get("error") or "market_stats_deferred_for_fast_view",
                "data": {},
            }

        return self._cached("market_stats", 30, getter)

    def get_realtime_quote(self, symbol: str, *, allow_legacy_remote: bool = True) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
        def getter() -> Dict[str, Any]:
            if _is_etf_code(code):
                return self.eastmoney.get_etf_quote(code, allow_remote=allow_legacy_remote)
            fuyao = self.ths.get_stock_snapshot(code)
            if self._has_data(fuyao):
                return fuyao
            if allow_legacy_remote:
                fallback = self.eastmoney.get_realtime_quote(code)
            else:
                fallback = self.eastmoney.get_cached_quote(code, error="fuyao_quote_unavailable")
            return self._merge_fallback_errors(fallback, fuyao)

        mode = "legacy" if allow_legacy_remote else "fast"
        return self._cached(f"quote:{mode}:{code}", 15, getter)

    def get_daily_kline(self, symbol: str, period: str = "daily", *, allow_remote: bool = True) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
        ttl = 300 if allow_remote else 60
        mode = "remote" if allow_remote else "cache"
        def getter() -> Dict[str, Any]:
            if _is_etf_code(code):
                return self.eastmoney.get_etf_daily_kline(code, period=period, allow_remote=allow_remote)
            if period == "daily" and allow_remote:
                fuyao = self.ths.get_stock_daily_kline(code)
                if self._has_data(fuyao):
                    enriched = self.eastmoney.enrich_kline_records(fuyao.get("data") or [])
                    return {**fuyao, "data": enriched}
                fallback = self.eastmoney.get_daily_kline(code, period=period, allow_remote=allow_remote)
                return self._merge_fallback_errors(fallback, fuyao)
            return self.eastmoney.get_daily_kline(code, period=period, allow_remote=allow_remote)

        return self._cached(f"kline:{mode}:{code}:{period}", ttl, getter)

    def get_money_flow(self, symbol: str, *, allow_remote: bool = True) -> Dict[str, Any]:
        ttl = 300 if allow_remote else 60
        mode = "remote" if allow_remote else "cache"
        return self._cached(
            f"money_flow:{mode}:{symbol}",
            ttl,
            lambda: self.eastmoney.get_money_flow(symbol, allow_remote=allow_remote),
        )

    def get_lhb(self, symbol: str) -> Dict[str, Any]:
        return self.eastmoney.get_lhb(symbol)

    def get_limit_up_pool(self) -> Dict[str, Any]:
        def getter() -> Dict[str, Any]:
            fuyao = self.ths.get_limit_up_pool()
            if self._has_data(fuyao):
                return fuyao
            return {
                "source": "workbench.fast",
                "stale": True,
                "error": fuyao.get("error") or "limit_up_pool_deferred_for_fast_view",
                "data": [],
            }

        return self._cached("limit_up_pool", 180, getter)

    def get_ths_stock_snapshot(self, symbol: str) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
        if _is_etf_code(code):
            return self._cached(f"etf_snapshot:{code}", 15, lambda: self.eastmoney.get_etf_quote(code, allow_remote=True))
        return self._cached(f"ths_snapshot:{code}", 15, lambda: self.ths.get_stock_snapshot(code))

    def get_ths_stock_daily_kline(self, symbol: str) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
        def getter() -> Dict[str, Any]:
            if _is_etf_code(code):
                return self.eastmoney.get_etf_daily_kline(code, allow_remote=True)
            payload = self.ths.get_stock_daily_kline(code)
            if self._has_data(payload):
                return {**payload, "data": self.eastmoney.enrich_kline_records(payload.get("data") or [])}
            fallback = self.eastmoney.get_daily_kline(code, allow_remote=False)
            return self._merge_fallback_errors(fallback, payload)

        return self._cached(f"ths_kline:{code}", 300, getter)

    def get_stock_news(self, symbol: str) -> Dict[str, Any]:
        return self._cached(f"stock_news:{symbol}", 600, lambda: self.eastmoney.get_stock_news(symbol))

    def get_industry_boards(self) -> Dict[str, Any]:
        return self._cached("industry_boards", 300, self.ths.get_industry_boards)

    def get_concept_boards(self) -> Dict[str, Any]:
        return self._cached("concept_boards", 300, self.ths.get_concept_boards)

    def get_industry_constituents(self, board_name: str) -> Dict[str, Any]:
        return self.ths.get_industry_constituents(board_name)

    def get_concept_constituents(self, concept_name: str) -> Dict[str, Any]:
        return self.ths.get_concept_constituents(concept_name)

    def infer_stock_themes(self, symbol: str, *, allow_remote: bool = False) -> Dict[str, Any]:
        ttl = 1800 if allow_remote else 300
        mode = "remote" if allow_remote else "cache"
        return self._cached(
            f"themes:{mode}:{symbol}",
            ttl,
            lambda: self.ths.infer_stock_themes(symbol, allow_remote=allow_remote),
        )


_provider_router_singleton: Optional[ProviderRouter] = None


def get_provider_router() -> ProviderRouter:
    global _provider_router_singleton
    if _provider_router_singleton is None:
        _provider_router_singleton = ProviderRouter()
    return _provider_router_singleton
