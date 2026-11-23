# -*- coding: utf-8 -*-
"""Market structure context composer for stock reports."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from data_provider import DataFetcherManager

from src.schemas.market_structure import (
    MARKET_STRUCTURE_SCHEMA_VERSION,
    MARKET_THEME_SCHEMA_VERSION,
    STOCK_MARKET_POSITION_SCHEMA_VERSION,
    MarketStructureContext,
    MarketStructureDataQuality,
    MarketStructureRiskTag,
    MarketStructureSource,
    MarketThemeContext,
    PrimaryTheme,
    StockBoardPosition,
    StockMarketPosition,
    ThemePhase,
    ThemeRankSource,
    dump_market_structure_model,
)
from src.services.market_hotspot_service import MarketHotspotService
from src.utils.data_processing import extract_board_detail_fields


logger = logging.getLogger(__name__)

_VALID_THEME_SOURCES = {"industry", "concept", "mixed", "unknown"}
_VALID_THEME_PHASES = {"warming", "accelerating", "cooling", "unknown"}


class MarketStructureService:
    """Compose market-theme and stock-position layers into one context."""

    def __init__(
        self,
        fetcher_manager: Optional[DataFetcherManager] = None,
        hotspot_service: Optional[MarketHotspotService] = None,
    ) -> None:
        self.fetcher_manager = fetcher_manager or DataFetcherManager()
        self.hotspot_service = hotspot_service or MarketHotspotService(
            fetcher_manager=self.fetcher_manager,
        )

    def build_context(
        self,
        *,
        code: str,
        stock_name: Optional[str],
        market: str,
        fundamental_context: Optional[Dict[str, Any]],
        trade_date: Any = None,
        market_phase_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_market = str(market or "cn").strip().lower() or "cn"
        trade_date_text = self._resolve_trade_date(trade_date, market_phase_summary)
        stock_code = str(code or "").strip()

        if normalized_market != "cn":
            return self._build_not_supported_context(
                market=normalized_market,
                trade_date=trade_date_text,
                stock_code=stock_code,
                stock_name=stock_name,
                missing_fields=["a_share_theme_context"],
                message="stock market structure is only supported for A-share first version",
            )

        if self._is_unsupported_fundamental_context(fundamental_context):
            return self._build_not_supported_context(
                market=normalized_market,
                trade_date=trade_date_text,
                stock_code=stock_code,
                stock_name=stock_name,
                missing_fields=["fundamental_boards"],
                message="fundamental board context is not supported for this stock",
            )

        board_details = extract_board_detail_fields(
            {"fundamental_context": fundamental_context or {}}
        )
        sector_rankings_payload = board_details.get("sector_rankings")
        concept_rankings_payload = board_details.get("concept_rankings")
        sector_rankings = sector_rankings_payload or {}
        concept_rankings = concept_rankings_payload or {}
        market_theme_payload = self.hotspot_service.get_hotspots(
            market=normalized_market,
            trade_date=trade_date_text,
            sector_rankings=sector_rankings_payload,
            concept_rankings=concept_rankings_payload,
        )
        market_theme_context = MarketThemeContext.model_validate(market_theme_payload)

        related_sector_rankings = self._merge_rankings_for_board_matching(
            sector_rankings=sector_rankings,
            leading_items=market_theme_payload.get("leading_industries", []),
            lagging_items=market_theme_payload.get("lagging_themes", []),
            lagging_allowed_sources={"industry", "unknown"},
        )
        related_concept_rankings = self._merge_rankings_for_board_matching(
            sector_rankings=concept_rankings,
            leading_items=market_theme_payload.get("leading_concepts", []),
            lagging_items=market_theme_payload.get("lagging_themes", []),
            lagging_allowed_sources={"concept", "unknown"},
        )

        related_boards = self._build_related_boards(
            board_details.get("belong_boards") or [],
            sector_rankings=related_sector_rankings,
            concept_rankings=related_concept_rankings,
        )
        primary_theme, primary_theme_has_market_match = self._infer_primary_theme(
            market_theme_payload,
            related_boards,
        )
        has_primary_market_evidence = self._has_primary_market_evidence(primary_theme)
        hotspot_constituents = self._safe_cast_market_list(
            market_theme_payload.get("hotspot_constituents"),
        )
        leader_stocks = self._safe_cast_market_list(
            market_theme_payload.get("leader_stocks"),
        )
        has_stock_role_evidence = self._has_stock_role_evidence(
            stock_code,
            primary_theme,
            hotspot_constituents,
            leader_stocks,
        )
        stock_role = self._infer_stock_role(
            stock_code=stock_code,
            primary_theme=primary_theme,
            related_boards=related_boards,
            has_market_match=primary_theme_has_market_match,
            has_primary_market_evidence=has_primary_market_evidence,
            has_stock_role_evidence=has_stock_role_evidence,
            hotspot_constituents=hotspot_constituents,
            leader_stocks=leader_stocks,
        )
        theme_phase: ThemePhase = primary_theme.phase if primary_theme is not None else "unknown"

        missing_fields: List[str] = []
        if not self._is_non_empty_list(market_theme_payload.get("hotspot_constituents")):
            missing_fields.append("hotspot_constituents")
        if not self._is_non_empty_list(market_theme_payload.get("leader_stocks")):
            missing_fields.append("leader_stocks")
        risk_tags: List[MarketStructureRiskTag] = []
        if market_theme_context.status != "ok":
            risk_tags.append(
                MarketStructureRiskTag(
                    code="theme_data_partial",
                    message="市场题材数据不完整，题材强弱仅作降级参考",
                )
            )
        if related_boards and not primary_theme_has_market_match:
            missing_fields.append("theme_ranking_match")
            risk_tags.append(
                MarketStructureRiskTag(
                    code="stock_theme_evidence_partial",
                    message="个股板块未匹配到市场题材榜单，个股位置按降级证据处理",
                )
            )
        if not related_boards:
            missing_fields.append("belong_boards")
            risk_tags.append(
                MarketStructureRiskTag(
                    code="board_membership_missing",
                    message="缺少个股所属板块证据，无法判断题材位置",
                )
            )

        if stock_role in {"leader", "follower"}:
            stock_status = "ok"
        elif primary_theme is not None or related_boards:
            stock_status = "partial"
        else:
            stock_status = "unknown"

        if market_theme_context.status == "ok" and stock_status == "ok":
            combined_status = "ok"
        elif market_theme_context.status in {"ok", "partial"} or stock_status in {"ok", "partial"}:
            combined_status = "partial"
        else:
            combined_status = "unknown"

        stock_position = StockMarketPosition(
            status=stock_status,
            stock_code=stock_code,
            stock_name=stock_name,
            market=normalized_market,
            primary_theme=primary_theme,
            related_boards=related_boards,
            stock_role=stock_role,
            theme_phase=theme_phase,
            risk_tags=risk_tags,
            missing_fields=missing_fields,
        )
        context = MarketStructureContext(
            status=combined_status,
            market=normalized_market,
            trade_date=trade_date_text,
            market_theme_context=market_theme_context,
            stock_market_position=stock_position,
        )
        return dump_market_structure_model(context)

    @staticmethod
    def _is_unsupported_fundamental_context(
        fundamental_context: Optional[Dict[str, Any]],
    ) -> bool:
        if not isinstance(fundamental_context, dict):
            return False

        if MarketStructureService._is_not_supported_status(fundamental_context.get("status")):
            return True

        boards_block = fundamental_context.get("boards")
        boards_status = boards_block.get("status") if isinstance(boards_block, dict) else None
        if MarketStructureService._is_not_supported_status(boards_status):
            return True

        coverage = fundamental_context.get("coverage")
        boards_coverage = coverage.get("boards") if isinstance(coverage, dict) else None
        return MarketStructureService._is_not_supported_status(boards_coverage)

    @staticmethod
    def _is_not_supported_status(value: Any) -> bool:
        return str(value or "").strip().lower() == "not_supported"

    @staticmethod
    def _build_not_supported_context(
        *,
        market: str,
        trade_date: Optional[str],
        stock_code: str,
        stock_name: Optional[str],
        missing_fields: List[str],
        message: str,
    ) -> Dict[str, Any]:
        theme_context = MarketThemeContext(
            status="not_supported",
            market=market,
            trade_date=trade_date,
            data_quality=MarketStructureDataQuality(
                status="not_supported",
                missing_fields=missing_fields,
                sources=[
                    MarketStructureSource(
                        provider="dsa",
                        dataset="market_structure",
                        status="not_supported",
                        message=message,
                    )
                ],
            ),
        )
        stock_position = StockMarketPosition(
            status="not_supported",
            stock_code=stock_code,
            stock_name=stock_name,
            market=market,
            missing_fields=missing_fields,
        )
        return dump_market_structure_model(
            MarketStructureContext(
                status="not_supported",
                market=market,
                trade_date=trade_date,
                market_theme_context=theme_context,
                stock_market_position=stock_position,
            )
        )

    def _build_related_boards(
        self,
        boards: Any,
        *,
        sector_rankings: Dict[str, Any],
        concept_rankings: Dict[str, Any],
    ) -> List[StockBoardPosition]:
        if not isinstance(boards, list):
            return []

        related: List[StockBoardPosition] = []
        for board in boards:
            if not isinstance(board, dict):
                continue
            name = self._optional_text(board.get("name"))
            if not name:
                continue
            board_type = self._optional_text(board.get("type"))
            source, ranking_item = self._resolve_board_rank_source(
                name,
                board_type=board_type,
                sector_rankings=sector_rankings,
                concept_rankings=concept_rankings,
            )
            related.append(
                StockBoardPosition(
                    name=name,
                    type=board_type,
                    code=self._optional_text(board.get("code")),
                    rank=self._safe_int((ranking_item or {}).get("rank")),
                    change_pct=self._safe_float((ranking_item or {}).get("change_pct")),
                    source=source,
                )
            )
        return related

    def _resolve_board_rank_source(
        self,
        name: str,
        *,
        board_type: Optional[str],
        sector_rankings: Dict[str, Any],
        concept_rankings: Dict[str, Any],
    ) -> tuple[ThemeRankSource, Optional[Dict[str, Any]]]:
        if board_type is not None:
            source: ThemeRankSource = "concept" if self._is_concept_type(board_type) else "industry"
            ranking_payload = concept_rankings if source == "concept" else sector_rankings
            return source, self._find_ranking_item(name, ranking_payload)

        concept_item = self._find_ranking_item(name, concept_rankings)
        if concept_item is not None:
            return "concept", concept_item

        sector_item = self._find_ranking_item(name, sector_rankings)
        if sector_item is not None:
            return "industry", sector_item

        if self._is_concept_type(name):
            return "concept", None
        return "industry", None

    @staticmethod
    def _merge_rankings_for_board_matching(
        *,
        sector_rankings: Any,
        leading_items: Any,
        lagging_items: Any,
        lagging_allowed_sources: set[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        top: List[Dict[str, Any]] = []
        bottom: List[Dict[str, Any]] = []

        def append_if_dict(target: List[Dict[str, Any]], item: Any) -> None:
            if not isinstance(item, dict):
                return
            name = item.get("name")
            if not name:
                return
            target.append(dict(item))

        if isinstance(sector_rankings, dict):
            for item in sector_rankings.get("top", []):
                append_if_dict(top, item)
            for item in sector_rankings.get("bottom", []):
                append_if_dict(bottom, item)

        for item in leading_items if isinstance(leading_items, list) else []:
            append_if_dict(top, item)

        for item in lagging_items if isinstance(lagging_items, list) else []:
            source = str(item.get("source") or "unknown").strip().lower()
            if source not in lagging_allowed_sources:
                continue
            append_if_dict(bottom, item)

        return {"top": top, "bottom": bottom}

    def _infer_primary_theme(
        self,
        market_theme_payload: Dict[str, Any],
        related_boards: List[StockBoardPosition],
    ) -> tuple[Optional[PrimaryTheme], bool]:
        if not related_boards:
            return None, False

        related_names = {board.name for board in related_boards}
        candidates: List[Dict[str, Any]] = []
        for field in (
            "active_themes",
            "leading_concepts",
            "leading_industries",
            "lagging_themes",
        ):
            value = market_theme_payload.get(field)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))

        for item in candidates:
            name = self._optional_text(item.get("name"))
            if not name or name not in related_names:
                continue
            source = self._theme_source(item.get("source"))
            if source in {"concept", "industry"}:
                if not any(
                    board.name == name and board.source == source
                    for board in related_boards
                ):
                    continue
            phase = self._theme_phase(item.get("phase"))
            if phase == "unknown":
                phase = self._phase_from_change(self._safe_float(item.get("change_pct")))
            return PrimaryTheme(
                name=name,
                source=source,
                phase=phase,
                rank=self._safe_int(item.get("rank")),
                change_pct=self._safe_float(item.get("change_pct")),
            ), True

        first = self._select_ranked_related_board(related_boards)
        return PrimaryTheme(
            name=first.name,
            source=first.source,
            phase=self._phase_from_change(first.change_pct),
            rank=first.rank,
            change_pct=first.change_pct,
        ), False

    @staticmethod
    def _select_ranked_related_board(
        related_boards: List[StockBoardPosition],
    ) -> StockBoardPosition:
        for board in related_boards:
            if board.rank is not None or board.change_pct is not None:
                return board
        return related_boards[0]

    @classmethod
    def _infer_stock_role(
        cls,
        stock_code: str,
        primary_theme: Optional[PrimaryTheme],
        related_boards: List[StockBoardPosition],
        has_market_match: bool,
        has_primary_market_evidence: bool,
        has_stock_role_evidence: bool,
        *,
        hotspot_constituents: List[Dict[str, Any]],
        leader_stocks: List[Dict[str, Any]],
    ) -> str:
        if primary_theme is None:
            return "edge" if related_boards else "unknown"
        if not has_market_match:
            return "edge" if related_boards else "unknown"
        if not has_primary_market_evidence or not has_stock_role_evidence:
            return "edge" if related_boards else "unknown"
        for board in related_boards:
            if board.name == primary_theme.name:
                if cls._is_stock_leader_for_theme(
                    stock_code,
                    primary_theme.name,
                    leader_stocks,
                ):
                    return "leader"
                if cls._is_stock_in_constituents_for_theme(
                    stock_code,
                    primary_theme.name,
                    hotspot_constituents,
                ):
                    return "follower"
                break
        return "edge" if related_boards else "unknown"

    @staticmethod
    def _is_non_empty_list(value: Any) -> bool:
        return isinstance(value, list) and bool(value)

    @classmethod
    def _has_stock_role_evidence(
        cls,
        stock_code: str,
        primary_theme: Optional[PrimaryTheme],
        hotspot_constituents: List[Dict[str, Any]],
        leader_stocks: List[Dict[str, Any]],
    ) -> bool:
        if primary_theme is None:
            return False
        if not stock_code:
            return False
        return (
            cls._is_stock_in_constituents_for_theme(
                stock_code,
                primary_theme.name,
                hotspot_constituents,
            )
            or cls._is_stock_leader_for_theme(
                stock_code,
                primary_theme.name,
                leader_stocks,
            )
        )

    @staticmethod
    def _safe_cast_market_list(value: Any) -> List[Dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    @classmethod
    def _is_stock_in_constituents_for_theme(
        cls,
        stock_code: str,
        theme_name: str,
        items: List[Dict[str, Any]],
    ) -> bool:
        return cls._match_stock_in_thematic_list(
            stock_code,
            theme_name,
            items,
        )

    @classmethod
    def _is_stock_leader_for_theme(
        cls,
        stock_code: str,
        theme_name: str,
        items: List[Dict[str, Any]],
    ) -> bool:
        return cls._match_stock_in_thematic_list(
            stock_code,
            theme_name,
            items,
        )

    @classmethod
    def _match_stock_in_thematic_list(
        cls,
        stock_code: str,
        theme_name: str,
        items: List[Dict[str, Any]],
    ) -> bool:
        normalized_stock_code = cls._normalize_stock_code(stock_code)
        normalized_theme = cls._normalize_theme_name(theme_name)
        if not normalized_stock_code or not normalized_theme:
            return False

        for item in items:
            candidate_code = cls._extract_stock_code(item)
            if not candidate_code or candidate_code != normalized_stock_code:
                continue
            themes = cls._extract_item_themes(item)
            if not themes:
                continue
            if normalized_theme in themes:
                return True
        return False

    @staticmethod
    def _extract_stock_code(item: Dict[str, Any]) -> str:
        for key in ("code", "stock_code", "ts_code", "ticker", "symbol"):
            value = item.get(key)
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized:
                return normalized.upper()
        return ""

    @staticmethod
    def _extract_item_themes(item: Dict[str, Any]) -> set[str]:
        themes: set[str] = set()
        for key in (
            "theme",
            "theme_name",
            "topic",
            "topic_name",
            "industry",
            "industry_name",
            "concept",
            "concept_name",
            "board",
            "board_name",
            "theme_name_cn",
            "theme_name_en",
            "topic_name_cn",
            "topic_name_en",
        ):
            value = str(item.get(key) or "").strip().lower()
            if value:
                themes.add(value)
        return themes

    @staticmethod
    def _normalize_theme_name(value: str) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _normalize_stock_code(value: str) -> str:
        return str(value or "").strip().upper()

    @staticmethod
    def _has_primary_market_evidence(primary_theme: Optional[PrimaryTheme]) -> bool:
        if primary_theme is None:
            return False
        return (
            primary_theme.rank is not None
            or primary_theme.change_pct is not None
            or primary_theme.phase != "unknown"
        )

    @staticmethod
    def _resolve_trade_date(
        trade_date: Any,
        market_phase_summary: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if trade_date is not None:
            if isinstance(trade_date, date):
                return trade_date.isoformat()
            text = str(trade_date).strip()
            if text:
                return text
        if isinstance(market_phase_summary, dict):
            for key in ("effective_daily_bar_date", "trade_date", "market_date"):
                value = market_phase_summary.get(key)
                if value:
                    return str(value)
        return None

    @staticmethod
    def _find_ranking_item(name: str, rankings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(rankings, dict):
            return None
        for field in ("top", "bottom"):
            items = rankings.get(field)
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and str(item.get("name") or "").strip() == name:
                    return item
        return None

    @staticmethod
    def _is_concept_type(value: Optional[str]) -> bool:
        text = str(value or "").strip().lower()
        return any(keyword in text for keyword in ("概念", "题材", "concept", "theme"))

    @staticmethod
    def _theme_source(value: Any) -> ThemeRankSource:
        text = str(value or "unknown").strip()
        return text if text in _VALID_THEME_SOURCES else "unknown"

    @staticmethod
    def _theme_phase(value: Any) -> ThemePhase:
        text = str(value or "unknown").strip()
        return text if text in _VALID_THEME_PHASES else "unknown"

    @staticmethod
    def _phase_from_change(value: Optional[float]) -> ThemePhase:
        if value is None:
            return "unknown"
        if value >= 3:
            return "accelerating"
        if value > 0:
            return "warming"
        return "cooling"

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    return None
                if text.endswith("%"):
                    text = text[:-1].strip()
                return float(text)
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_text(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


__all__ = [
    "MARKET_THEME_SCHEMA_VERSION",
    "MARKET_STRUCTURE_SCHEMA_VERSION",
    "STOCK_MARKET_POSITION_SCHEMA_VERSION",
    "MarketStructureService",
]
