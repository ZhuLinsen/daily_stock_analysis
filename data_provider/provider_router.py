# -*- coding: utf-8 -*-
"""Provider router for the AI stock workbench MVP.

The router keeps provider fan-out in one place and preserves the page-level
contract: provider failures are represented in the payload rather than raised.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from data_provider.base import DataFetcherManager
from data_provider.eastmoney_provider import EastMoneyProvider
from data_provider.ths_provider import THSProvider


class ProviderRouter:
    """Small compatibility layer over new providers and existing manager."""

    def __init__(self, manager: Optional[DataFetcherManager] = None):
        self.manager = manager or DataFetcherManager()
        self.eastmoney = EastMoneyProvider(manager=self.manager)
        self.ths = THSProvider(manager=self.manager)

    def get_realtime_quote(self, symbol: str) -> Dict[str, Any]:
        return self.eastmoney.get_realtime_quote(symbol)

    def get_daily_kline(self, symbol: str, period: str = "daily") -> Dict[str, Any]:
        return self.eastmoney.get_daily_kline(symbol, period=period)

    def get_money_flow(self, symbol: str) -> Dict[str, Any]:
        return self.eastmoney.get_money_flow(symbol)

    def get_lhb(self, symbol: str) -> Dict[str, Any]:
        return self.eastmoney.get_lhb(symbol)

    def get_limit_up_pool(self) -> Dict[str, Any]:
        return self.eastmoney.get_limit_up_pool()

    def get_stock_news(self, symbol: str) -> Dict[str, Any]:
        return self.eastmoney.get_stock_news(symbol)

    def get_industry_boards(self) -> Dict[str, Any]:
        return self.ths.get_industry_boards()

    def get_concept_boards(self) -> Dict[str, Any]:
        return self.ths.get_concept_boards()

    def get_industry_constituents(self, board_name: str) -> Dict[str, Any]:
        return self.ths.get_industry_constituents(board_name)

    def get_concept_constituents(self, concept_name: str) -> Dict[str, Any]:
        return self.ths.get_concept_constituents(concept_name)

    def infer_stock_themes(self, symbol: str) -> Dict[str, Any]:
        return self.ths.infer_stock_themes(symbol)


_provider_router_singleton: Optional[ProviderRouter] = None


def get_provider_router() -> ProviderRouter:
    global _provider_router_singleton
    if _provider_router_singleton is None:
        _provider_router_singleton = ProviderRouter()
    return _provider_router_singleton
