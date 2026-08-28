# -*- coding: utf-8 -*-
"""Market dashboard service: 大盘仪表盘.

在一次聚合里给出：市场温度（复用实时全市场宽度并落库）、主要指数、涨跌家数、
热门板块/概念、板块资金流排行、以及从热门板块推导的候选观察池。
除温度外均为实时只读数据，各分块独立 fail-open，缺数据时在 notes 里说明。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.services.market_temperature_service import (
    MarketTemperatureService,
    _to_float,
    build_snapshot_from_overview,
)

logger = logging.getLogger(__name__)

# 候选池里需要排除的名称特征（ST / 退市整理等）
_EXCLUDED_NAME_MARKERS = ("ST", "退")


def _sanitize_ranking(rows: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "") or "")
        if not name:
            continue
        result.append({"name": name, "change_pct": _to_float(row.get("change_pct"))})
    return result


def _sanitize_flow(rows: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "") or "")
        if not name:
            continue
        result.append({"name": name, "net_inflow": _to_float(row.get("net_inflow"))})
    return result


def _is_excluded_stock(name: str) -> bool:
    upper = str(name or "").upper()
    return any(marker in upper for marker in _EXCLUDED_NAME_MARKERS)


class MarketDashboardService:
    """聚合大盘仪表盘：温度 + 指数 + 宽度 + 热门板块/概念 + 资金流 + 候选观察池。"""

    CANDIDATE_SECTOR_COUNT = 3
    CANDIDATES_PER_SECTOR = 2
    MAX_CANDIDATES = 6
    FLOW_BUDGET_SECONDS = 15.0
    # 单板块成份股抓取的硬超时：个别网络环境下东财请求可能长时间挂起，
    # 超时后放弃该板块，避免拖垮整个仪表盘。
    SECTOR_FETCH_TIMEOUT_SECONDS = 30.0
    # 资金流上下文是按个股设计的接口，但其中的板块资金流排行与个股无关，
    # 用基准代码触发一次调用即可拿到市场级板块资金流。
    _FLOW_PROBE_CODE = "000001"

    def __init__(
        self,
        temperature_service: Optional[MarketTemperatureService] = None,
        data_manager: Optional[Any] = None,
    ) -> None:
        self.temperature_service = temperature_service or MarketTemperatureService()
        self._data_manager = data_manager

    @property
    def data_manager(self) -> Any:
        if self._data_manager is None:
            from data_provider.base import DataFetcherManager

            self._data_manager = DataFetcherManager()
        return self._data_manager

    def dashboard(
        self,
        market: str,
        overview_provider: Optional[Callable[[], Any]] = None,
        flow_provider: Optional[Callable[[], Any]] = None,
        constituents_provider: Optional[Callable[[str, int], List[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """构建大盘仪表盘。market 当前仅支持 cn（与实时宽度数据源一致）。"""
        market = self.temperature_service.normalize_market(market)
        if market not in MarketTemperatureService.PROVIDER_SUPPORTED_MARKETS:
            raise ValueError("market dashboard only supports market=cn currently")

        notes: List[str] = []
        overview = self._fetch_overview(market, overview_provider)

        temperature = self._build_temperature(market, overview, notes)
        indices = self._build_indices(overview)
        breadth = self._build_breadth(overview)
        hot_sectors = {
            "top": _sanitize_ranking(getattr(overview, "top_sectors", None)),
            "bottom": _sanitize_ranking(getattr(overview, "bottom_sectors", None)),
        }
        hot_concepts = {
            "top": _sanitize_ranking(getattr(overview, "top_concepts", None)),
            "bottom": _sanitize_ranking(getattr(overview, "bottom_concepts", None)),
        }
        capital_flow = self._build_capital_flow(flow_provider, notes)
        candidates = self._build_candidates(overview, hot_sectors, constituents_provider, notes)

        trade_date = str(getattr(overview, "date", "") or "").strip()
        return {
            "market": market,
            "trade_date": trade_date,
            "temperature": temperature,
            "indices": indices,
            "breadth": breadth,
            "hot_sectors": hot_sectors,
            "hot_concepts": hot_concepts,
            "capital_flow": capital_flow,
            "candidates": candidates,
            "notes": notes,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

    # ------------------------------------------------------------------ blocks

    def _fetch_overview(self, market: str, overview_provider: Optional[Callable[[], Any]]) -> Any:
        if overview_provider is not None:
            overview = overview_provider()
        else:
            from src.market_analyzer import MarketAnalyzer

            overview = MarketAnalyzer(region=market).get_market_overview()
        if overview is None:
            raise ValueError("failed to fetch market overview from data provider")
        return overview

    def _build_temperature(self, market: str, overview: Any, notes: List[str]) -> Optional[Dict[str, Any]]:
        snapshot = build_snapshot_from_overview(overview)
        if not snapshot:
            notes.append("实时宽度数据不可用，本次未生成市场温度。")
            return None
        trade_date = str(getattr(overview, "date", "") or "").strip()
        result = self.temperature_service.snapshot(market, snapshot, trade_date=trade_date or None)
        result["source"] = "market_stats"
        return result

    @staticmethod
    def _build_indices(overview: Any) -> List[Dict[str, Any]]:
        indices: List[Dict[str, Any]] = []
        for item in getattr(overview, "indices", None) or []:
            indices.append({
                "code": str(getattr(item, "code", "") or ""),
                "name": str(getattr(item, "name", "") or ""),
                "change_pct": _to_float(getattr(item, "change_pct", None)),
            })
        return indices

    @staticmethod
    def _build_breadth(overview: Any) -> Dict[str, Any]:
        def _int(name: str) -> int:
            value = _to_float(getattr(overview, name, None))
            return int(value) if value is not None else 0

        return {
            "up_count": _int("up_count"),
            "down_count": _int("down_count"),
            "flat_count": _int("flat_count"),
            "limit_up_count": _int("limit_up_count"),
            "limit_down_count": _int("limit_down_count"),
            "total_amount": _to_float(getattr(overview, "total_amount", None)) or 0.0,
        }

    def _build_capital_flow(self, flow_provider: Optional[Callable[[], Any]], notes: List[str]) -> Dict[str, Any]:
        try:
            if flow_provider is not None:
                block = flow_provider()
            else:
                block = self.data_manager.get_capital_flow_context(
                    self._FLOW_PROBE_CODE,
                    budget_seconds=self.FLOW_BUDGET_SECONDS,
                )
        except Exception as exc:
            logger.warning("market dashboard capital flow fetch failed: %s", exc)
            block = None

        data = (block or {}).get("data") or {}
        rankings = data.get("sector_rankings") or {}
        top = _sanitize_flow(rankings.get("top"))
        bottom = _sanitize_flow(rankings.get("bottom"))
        if not top and not bottom:
            notes.append("板块资金流数据源暂不可用（本机网络或数据源限制），该分块已留空。")
            return {"status": "unavailable", "sector_rankings": {"top": [], "bottom": []}}
        return {"status": "ok", "sector_rankings": {"top": top, "bottom": bottom}}

    def _fetch_constituents_bounded(
        self,
        sector_name: str,
        constituents_provider: Optional[Callable[[str, int], List[Dict[str, Any]]]],
    ) -> List[Dict[str, Any]]:
        """抓取单个板块的成份股，带硬超时；超时/异常返回空列表。"""
        top_n = self.CANDIDATES_PER_SECTOR

        def _fetch() -> List[Dict[str, Any]]:
            if constituents_provider is not None:
                return constituents_provider(sector_name, top_n)
            return self.data_manager.get_sector_constituents(sector_name, top_n)

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_fetch)
            return future.result(timeout=self.SECTOR_FETCH_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            logger.warning(
                "constituents fetch timed out after %.0fs for sector %s",
                self.SECTOR_FETCH_TIMEOUT_SECONDS,
                sector_name,
            )
            return []
        finally:
            executor.shutdown(wait=False)

    def _build_candidates(
        self,
        overview: Any,
        hot_sectors: Dict[str, List[Dict[str, Any]]],
        constituents_provider: Optional[Callable[[str, int], List[Dict[str, Any]]]],
        notes: List[str],
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        seen_codes: set = set()

        for sector in hot_sectors.get("top", [])[: self.CANDIDATE_SECTOR_COUNT]:
            if len(candidates) >= self.MAX_CANDIDATES:
                break
            sector_name = sector["name"]
            sector_change = sector.get("change_pct")
            try:
                rows = self._fetch_constituents_bounded(
                    sector_name, constituents_provider
                )
            except Exception as exc:
                logger.warning("constituents fetch failed for sector %s: %s", sector_name, exc)
                rows = []

            for row in rows or []:
                code = str(row.get("code", "") or "")
                name = str(row.get("name", "") or "")
                if not code or not name or code in seen_codes or _is_excluded_stock(name):
                    continue
                seen_codes.add(code)
                change_pct = _to_float(row.get("change_pct"))
                sector_text = f"{sector_name} 板块领涨"
                if sector_change is not None:
                    sector_text += f" {sector_change:+.2f}%"
                stock_text = ""
                if change_pct is not None:
                    stock_text = f"，个股涨幅 {change_pct:+.2f}%"
                candidates.append({
                    "code": code,
                    "name": name,
                    "sector": sector_name,
                    "sector_change_pct": sector_change,
                    "change_pct": change_pct,
                    "price": _to_float(row.get("price")),
                    "reason": sector_text + stock_text,
                })
                if len(candidates) >= self.MAX_CANDIDATES:
                    break

        if not candidates:
            notes.append("热门板块成份股数据暂不可用，本次未生成候选观察池。")
        return candidates
