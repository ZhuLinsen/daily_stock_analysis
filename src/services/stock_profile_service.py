# -*- coding: utf-8 -*-
"""Aggregate existing stock research capabilities behind one partial-data contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from data_provider.base import canonical_stock_code
from src.analysis_context_pack_overview import extract_analysis_context_pack_overview
from src.repositories.portfolio_repo import PortfolioRepository
from src.services.alert_service import AlertService
from src.services.history_service import HistoryService
from src.services.intelligence_service import IntelligenceService
from src.services.market_symbol_utils import get_suffix_market
from src.services.research_artifact_service import build_research_artifact
from src.services.stock_code_utils import resolve_daily_stock_identity
from src.services.stock_service import StockService
from src.utils.data_processing import (
    extract_fundamental_detail_fields,
    extract_market_structure_detail_field,
)

_BLOCK_NAMES = ("quote", "history", "research", "intelligence", "portfolio", "monitors")


class InvalidStockProfileCode(ValueError):
    """Raised when a stock profile request has no unambiguous shared identity."""


class StockProfileService:
    """Build a stock profile while isolating optional-source failures by block."""

    def __init__(
        self,
        *,
        stock_service: Optional[StockService] = None,
        history_service: Optional[HistoryService] = None,
        intelligence_service: Optional[IntelligenceService] = None,
        portfolio_repository: Optional[PortfolioRepository] = None,
        alert_service: Optional[AlertService] = None,
    ):
        self.stock_service = stock_service
        self.history_service = history_service
        self.intelligence_service = intelligence_service
        self.portfolio_repository = portfolio_repository
        self.alert_service = alert_service

    def get_profile(self, requested_code: str, *, history_days: int = 60) -> Dict[str, Any]:
        canonical_code = self.canonicalize_code(requested_code)
        market = self.market_for_code(canonical_code)
        blocks = {
            "quote": self._quote_block(canonical_code),
            "history": self._history_block(canonical_code, history_days=history_days),
            "research": self._research_block(canonical_code, market=market),
            "intelligence": self._intelligence_block(canonical_code, market=market),
            "portfolio": self._portfolio_block(canonical_code, market=market),
            "monitors": self._monitor_block(canonical_code, market=market),
        }
        return {
            "requested_code": str(requested_code).strip(),
            "canonical_code": canonical_code,
            "market": market,
            "as_of": datetime.now().astimezone().isoformat(),
            **blocks,
            "evidence_quality": self._evidence_quality(blocks),
        }

    @staticmethod
    def canonicalize_code(value: str) -> str:
        raw = str(value or "").strip()
        identity = resolve_daily_stock_identity(raw)
        if identity is None:
            raise InvalidStockProfileCode("stock code has no unambiguous market identity")
        normalized = canonical_stock_code(identity.refill_code or identity.normalized_code)
        if normalized.isdigit() and len(normalized) == 5:
            return f"HK{normalized.zfill(5)}"
        return normalized.upper()

    @staticmethod
    def market_for_code(canonical_code: str) -> str:
        if canonical_code.startswith("HK"):
            return "hk"
        suffix_market = get_suffix_market(canonical_code)
        if suffix_market:
            return suffix_market
        if canonical_code.isdigit() and len(canonical_code) == 6:
            return "cn"
        return "us"

    def _quote_block(self, code: str) -> Dict[str, Any]:
        try:
            quote = self._stock_service().get_realtime_quote(code)
        except Exception:
            quote = None
        if not quote:
            return self._unavailable("quote_unavailable", data=None)
        return {"status": "fresh", "data": quote, "limitations": []}

    def _history_block(self, code: str, *, history_days: int) -> Dict[str, Any]:
        try:
            result = self._stock_service().get_history_data(code, period="daily", days=history_days)
            rows = list(result.get("data") or [])
        except Exception:
            rows = []
        if not rows:
            return {
                "status": "unavailable",
                "period": "daily",
                "data": [],
                "limitations": ["history_unavailable"],
            }
        return {"status": "fresh", "period": "daily", "data": rows, "limitations": []}

    def _research_block(self, code: str, *, market: str) -> Dict[str, Any]:
        empty_data = {"latest_report": None, "recent_reports": [], "structured_report": None}
        try:
            query_options: Dict[str, Any] = {
                "stock_code": code,
                "page": 1,
                "limit": 5,
                "market_hint": market,
            }
            if market in {"jp", "kr", "tw"}:
                query_options["include_ambiguous_numeric_aliases"] = False
            result = self._history_service().get_history_list(**query_options)
            reports = list(result.get("items") or [])
        except Exception:
            return self._unavailable("report_list_unavailable", data=empty_data)
        if not reports:
            return self._unavailable("no_reports", data=empty_data)

        latest = reports[0]
        record_id = latest.get("id")
        if record_id is None:
            return {
                "status": "partial",
                "data": {
                    "latest_report": latest,
                    "recent_reports": reports,
                    "structured_report": None,
                },
                "limitations": ["latest_report_id_unavailable"],
            }
        try:
            detail = self._history_service().get_history_detail_by_id(int(record_id))
        except Exception:
            detail = None
        if not detail:
            return {
                "status": "partial",
                "data": {
                    "latest_report": latest,
                    "recent_reports": reports,
                    "structured_report": None,
                },
                "limitations": ["latest_report_detail_unavailable"],
            }
        try:
            artifact = build_research_artifact(self._artifact_input(detail))
        except Exception:
            artifact = None
        return {
            "status": "fresh" if artifact else "partial",
            "data": {
                "latest_report": latest,
                "recent_reports": reports,
                "structured_report": artifact,
            },
            "limitations": [] if artifact else ["structured_report_unavailable"],
        }

    def _intelligence_block(self, code: str, *, market: str) -> Dict[str, Any]:
        items_by_id: Dict[Any, Dict[str, Any]] = {}
        successful_queries = 0
        failed_queries = 0
        markets = [market] if market == "global" else [market, "global"]
        aliases = self._code_aliases(code, market_hint=market)
        safe_global_aliases = set(
            self._code_aliases(
                code,
                market_hint=market,
                include_ambiguous_numeric=False,
            )
        )
        for alias in aliases:
            for query_market in markets:
                if query_market == "global" and alias not in safe_global_aliases:
                    continue
                try:
                    result = self._intelligence_service().list_items(
                        scope_type="symbol",
                        scope_value=alias,
                        market=query_market,
                        page=1,
                        page_size=10,
                    )
                    successful_queries += 1
                except Exception:
                    failed_queries += 1
                    continue
                for item in result.get("items") or []:
                    key = item.get("id")
                    if key is None:
                        key = (item.get("source_type"), item.get("url"), item.get("title"))
                    items_by_id.setdefault(key, item)
        if successful_queries == 0:
            return self._unavailable("intelligence_query_failed", items=[])
        items = sorted(
            items_by_id.values(),
            key=lambda item: (
                str(item.get("published_at") or item.get("fetched_at") or item.get("created_at") or ""),
                int(item.get("id") or 0),
            ),
            reverse=True,
        )[:10]
        if not items:
            if failed_queries:
                return {
                    "status": "partial",
                    "items": [],
                    "limitations": ["intelligence_alias_query_partial"],
                }
            return self._unavailable("no_symbol_intelligence", items=[])
        return {
            "status": "partial" if failed_queries else "fresh",
            "items": items,
            "limitations": ["intelligence_alias_query_partial"] if failed_queries else [],
        }

    def _portfolio_block(self, code: str, *, market: str) -> Dict[str, Any]:
        try:
            profile_identity = resolve_daily_stock_identity(code, market_hint=market)
            identities = self._portfolio_repository().list_cached_position_identities()
            matches = []
            for position_market, symbol in identities:
                normalized_market = str(position_market or "").strip().lower()
                identity = resolve_daily_stock_identity(symbol, market_hint=normalized_market)
                if identity is None or identity.market != normalized_market or identity.market != market:
                    continue
                if self._same_profile_identity(identity, profile_identity):
                    matches.append(normalized_market)
        except Exception:
            return self._unavailable(
                "portfolio_relation_unavailable",
                data={"held": False, "matched_markets": []},
            )
        return {
            "status": "partial",
            "data": {"held": bool(matches), "matched_markets": list(dict.fromkeys(matches))},
            "limitations": ["cached_positions_only"],
        }

    @staticmethod
    def _same_profile_identity(position_identity: Any, profile_identity: Any) -> bool:
        if profile_identity is None:
            return False
        position_codes = {
            str(position_identity.normalized_code or "").strip().upper(),
            str(position_identity.refill_code or "").strip().upper(),
        } - {""}
        profile_codes = {
            str(profile_identity.normalized_code or "").strip().upper(),
            str(profile_identity.refill_code or "").strip().upper(),
        } - {""}
        if position_codes & profile_codes:
            return True
        if position_identity.market in {"kr", "tw"} and not position_identity.refill_code:
            profile_base = str(profile_identity.normalized_code or "").split(".", 1)[0]
            return position_identity.normalized_code == profile_base
        return False

    def _monitor_block(self, code: str, *, market: str) -> Dict[str, Any]:
        rules_by_id: Dict[Any, Dict[str, Any]] = {}
        successful_queries = 0
        failed_queries = 0
        for alias in self._code_aliases(
            code,
            market_hint=market,
            include_ambiguous_numeric=False,
        ):
            page = 1
            scanned = 0
            try:
                while True:
                    result = self._alert_service().list_rules(
                        target_scope="single_symbol",
                        target=alias,
                        page=page,
                        page_size=100,
                    )
                    successful_queries += 1
                    rules = list(result.get("items") or [])
                    for rule in rules:
                        key = rule.get("id")
                        if key is None:
                            key = (alias, rule.get("name"), rule.get("alert_type"))
                        rules_by_id.setdefault(key, rule)
                    scanned += len(rules)
                    total = int(result.get("total") or 0)
                    if scanned >= total or not rules:
                        break
                    page += 1
            except Exception:
                failed_queries += 1
        if successful_queries == 0:
            return self._unavailable(
                "monitor_query_failed",
                data={"total_rule_count": 0, "enabled_rule_count": 0, "rule_ids": []},
            )
        rules = list(rules_by_id.values())
        return {
            "status": "partial" if failed_queries else "fresh",
            "data": {
                "total_rule_count": len(rules),
                "enabled_rule_count": sum(1 for rule in rules if rule.get("enabled")),
                "rule_ids": [int(rule["id"]) for rule in rules if rule.get("id") is not None],
            },
            "limitations": ["monitor_alias_query_partial"] if failed_queries else [],
        }

    @staticmethod
    def _code_aliases(
        code: str,
        *,
        market_hint: Optional[str] = None,
        include_ambiguous_numeric: bool = True,
    ) -> List[str]:
        market = str(market_hint or StockProfileService.market_for_code(code)).strip().lower()
        identity = resolve_daily_stock_identity(code, market_hint=market)
        candidates = list(identity.code_candidates) if identity is not None and identity.market == market else [code]
        if include_ambiguous_numeric and market in {"jp", "kr", "tw"} and "." in code:
            numeric_base = code.split(".", 1)[0]
            if numeric_base.isdigit():
                candidates.append(numeric_base)
        aliases: List[str] = []
        seen_aliases = set()
        for candidate in candidates or [code]:
            candidate_text = str(candidate).strip()
            if not include_ambiguous_numeric and candidate_text.isdigit():
                unhinted_identity = resolve_daily_stock_identity(candidate_text)
                same_market = unhinted_identity is not None and unhinted_identity.market == market
                legacy_short_hk = (
                    market == "hk"
                    and len(candidate_text) <= 3
                    and (
                        hinted_identity := resolve_daily_stock_identity(
                            candidate_text,
                            market_hint="hk",
                        )
                    ) is not None
                    and hinted_identity.market == "hk"
                )
                if not same_market and not legacy_short_hk:
                    continue
            alias_key = candidate_text.casefold()
            if candidate_text and alias_key not in seen_aliases:
                seen_aliases.add(alias_key)
                aliases.append(candidate_text)
        return aliases

    def _artifact_input(self, detail: Dict[str, Any]) -> Dict[str, Any]:
        context_snapshot = detail.get("context_snapshot")
        raw_result = detail.get("raw_result")
        raw_fundamental = (
            raw_result.get("fundamental_context") or raw_result
            if isinstance(raw_result, dict)
            else None
        )
        extracted_fundamental = extract_fundamental_detail_fields(
            context_snapshot,
            raw_fundamental,
        )
        try:
            persisted_fundamental = self._history_service().get_latest_fundamental_snapshot(
                query_id=str(detail.get("query_id") or "").strip(),
                stock_code=str(
                    detail.get("storage_stock_code") or detail.get("stock_code") or ""
                ).strip(),
            )
        except Exception:
            persisted_fundamental = None
        persisted_fields = extract_fundamental_detail_fields(
            None,
            persisted_fundamental,
        )
        context_overview = extract_analysis_context_pack_overview(context_snapshot)
        market_structure = extract_market_structure_detail_field(
            context_snapshot,
            raw_result,
        )
        return {
            "meta": {
                "id": detail.get("id"),
                "query_id": detail.get("query_id"),
                "stock_code": detail.get("stock_code"),
                "stock_name": detail.get("stock_name"),
                "created_at": detail.get("created_at"),
            },
            "summary": {
                "analysis_summary": detail.get("analysis_summary"),
                "operation_advice": detail.get("operation_advice"),
                "action": detail.get("action"),
                "action_label": detail.get("action_label"),
                "trend_prediction": detail.get("trend_prediction"),
                "sentiment_score": detail.get("sentiment_score"),
            },
            "strategy": {
                "ideal_buy": detail.get("ideal_buy"),
                "secondary_buy": detail.get("secondary_buy"),
                "stop_loss": detail.get("stop_loss"),
                "take_profit": detail.get("take_profit"),
            },
            "details": {
                "news_content": detail.get("news_content"),
                "empty_news_disclosure": detail.get("empty_news_disclosure"),
                "analysis_context_pack_overview": context_overview,
                "financial_report": detail.get("financial_report")
                or extracted_fundamental.get("financial_report")
                or persisted_fields.get("financial_report"),
                "dividend_metrics": detail.get("dividend_metrics")
                or extracted_fundamental.get("dividend_metrics")
                or persisted_fields.get("dividend_metrics"),
                "market_structure": detail.get("market_structure") or market_structure,
            },
        }

    def _stock_service(self) -> StockService:
        if self.stock_service is None:
            self.stock_service = StockService()
        return self.stock_service

    def _history_service(self) -> HistoryService:
        if self.history_service is None:
            self.history_service = HistoryService()
        return self.history_service

    def _intelligence_service(self) -> IntelligenceService:
        if self.intelligence_service is None:
            self.intelligence_service = IntelligenceService()
        return self.intelligence_service

    def _portfolio_repository(self) -> PortfolioRepository:
        if self.portfolio_repository is None:
            self.portfolio_repository = PortfolioRepository()
        return self.portfolio_repository

    def _alert_service(self) -> AlertService:
        if self.alert_service is None:
            self.alert_service = AlertService()
        return self.alert_service

    @staticmethod
    def _unavailable(limitation: str, **payload: Any) -> Dict[str, Any]:
        return {"status": "unavailable", **payload, "limitations": [limitation]}

    @staticmethod
    def _evidence_quality(blocks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        statuses = {name: str(blocks[name]["status"]) for name in _BLOCK_NAMES}
        status_values = set(statuses.values())
        if status_values == {"fresh"}:
            overall = "fresh"
        elif status_values == {"unavailable"}:
            overall = "unavailable"
        else:
            overall = "partial"
        limitations = []
        for name in _BLOCK_NAMES:
            limitations.extend(str(item) for item in blocks[name].get("limitations") or [])
        return {
            "status": overall,
            "blocks": statuses,
            "limitations": list(dict.fromkeys(limitations)),
        }
