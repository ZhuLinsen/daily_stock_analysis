# -*- coding: utf-8 -*-
"""DSA-native market hotspot context service.

This service intentionally does not import AlphaSift.  It builds the first
market-theme layer from DSA's existing industry/concept ranking providers and
returns explicit data-quality markers when richer hotspot evidence is missing.
"""

from __future__ import annotations

import logging
import copy
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from datetime import date
import time
from typing import Any, Callable, Dict, Hashable, List, Optional, Set, Tuple

from data_provider import DataFetcherManager

from src.schemas.market_structure import (
    MarketStructureDataQuality,
    MarketStructureSource,
    MarketThemeContext,
    MarketThemeItem,
    RankedThemeItem,
    ThemeBreadth,
    ThemeRankSource,
    dump_market_structure_model,
)


logger = logging.getLogger(__name__)

DEFAULT_RANKING_FETCH_TIMEOUT_SECONDS = 3.0
DEFAULT_RANKING_CACHE_FAILURE_TTL_SECONDS = 30.0
DEFAULT_RANKING_CACHE_SUCCESS_TTL_SECONDS = 60.0
RANKING_FETCH_MAX_WORKERS = 2
RANKING_FETCH_TIMEOUT_RETRY_DELAY_SECONDS = 0.2


class MarketHotspotService:
    """Build low-sensitive A-share market/theme context from DSA rankings."""

    _ranking_fetch_slots = threading.BoundedSemaphore(RANKING_FETCH_MAX_WORKERS)
    _ranking_fetch_futures: Dict[Hashable, Future] = {}
    _ranking_fetch_detached_futures: Set[Future] = set()
    _ranking_fetch_retry_after: Dict[Hashable, Tuple[Future, float]] = {}
    _ranking_fetch_futures_lock = threading.Lock()

    def __init__(
        self,
        fetcher_manager: Optional[DataFetcherManager] = None,
        ranking_fetch_timeout_seconds: Optional[float] = None,
        failure_cache_ttl_seconds: Optional[float] = None,
        success_cache_ttl_seconds: Optional[float] = None,
    ) -> None:
        self.fetcher_manager = fetcher_manager or DataFetcherManager()
        self._ranking_fetch_timeout_seconds = ranking_fetch_timeout_seconds
        self._failure_cache_ttl_seconds = self._coerce_cache_ttl(
            DEFAULT_RANKING_CACHE_FAILURE_TTL_SECONDS
            if failure_cache_ttl_seconds is None
            else failure_cache_ttl_seconds
        )
        self._success_cache_ttl_seconds = self._coerce_cache_ttl(
            DEFAULT_RANKING_CACHE_SUCCESS_TTL_SECONDS
            if success_cache_ttl_seconds is None
            else success_cache_ttl_seconds
        )
        self._hotspots_cache: Dict[
            Tuple[str, Optional[str], int],
            Dict[str, Any],
        ] = {}
        self._hotspots_cache_lock = threading.Lock()

    def get_hotspots(
        self,
        *,
        market: str,
        trade_date: Any = None,
        limit: int = 5,
        sector_rankings: Any = None,
        concept_rankings: Any = None,
    ) -> Dict[str, Any]:
        normalized_market = str(market or "cn").strip().lower() or "cn"
        trade_date_text = self._format_trade_date(trade_date)
        try:
            limit = max(1, int(limit or 5))
        except (TypeError, ValueError):
            limit = 5

        uses_preloaded_rankings = sector_rankings is not None or concept_rankings is not None
        cache_key = (normalized_market, trade_date_text, limit)
        if not uses_preloaded_rankings:
            cached = self._get_cached_hotspots(cache_key)
            if cached is not None:
                return cached

        if normalized_market != "cn":
            context = MarketThemeContext(
                status="not_supported",
                market=normalized_market,
                trade_date=trade_date_text,
                data_quality=MarketStructureDataQuality(
                    status="not_supported",
                    missing_fields=["industry_rankings", "concept_rankings"],
                    sources=[
                        MarketStructureSource(
                            provider="dsa",
                            dataset="sector_rankings",
                            status="not_supported",
                            message="market structure hotspots are only supported for A-share first version",
                        )
                    ],
                ),
            )
            return self._store_cached_hotspots(cache_key, dump_market_structure_model(context))

        errors: List[str] = []
        sources: List[MarketStructureSource] = []
        top_industries, bottom_industries = self._resolve_rankings(
            "get_sector_rankings",
            "sector_rankings",
            limit,
            errors,
            sources,
            preloaded_rankings=sector_rankings,
        )
        top_concepts, bottom_concepts = self._resolve_rankings(
            "get_concept_rankings",
            "concept_rankings",
            limit,
            errors,
            sources,
            preloaded_rankings=concept_rankings,
        )

        leading_industries = self._normalize_ranked_items(top_industries, "industry")
        leading_concepts = self._normalize_ranked_items(top_concepts, "concept")
        lagging_themes = list(
            self._normalize_ranked_items(bottom_industries, "industry")
        ) + list(self._normalize_ranked_items(bottom_concepts, "concept"))
        active_themes = self._build_active_themes(
            list(leading_industries) + list(leading_concepts),
            limit=limit,
        )

        missing_fields: List[str] = []
        if not leading_industries and not bottom_industries:
            missing_fields.append("industry_rankings")
        if not leading_concepts and not bottom_concepts:
            missing_fields.append("concept_rankings")

        has_any_ranking = bool(leading_industries or leading_concepts or lagging_themes)
        has_partial_source = any(
            source.status == "partial"
            for source in sources
            if source.provider == "dsa" and source.dataset in {"sector_rankings", "concept_rankings"}
        )
        if not missing_fields and not errors and not has_partial_source:
            status = "ok"
        elif has_any_ranking:
            status = "partial"
        else:
            status = "unknown"

        context = MarketThemeContext(
            status=status,
            market=normalized_market,
            trade_date=trade_date_text,
            active_themes=active_themes,
            leading_industries=leading_industries,
            leading_concepts=leading_concepts,
            # Keep both ranking families. Each provider result is already bounded
            # by ``limit``; truncating the combined list here can discard every
            # lagging concept whenever the industry list fills the limit, which
            # removes valid evidence from downstream stock-board matching.
            lagging_themes=lagging_themes,
            theme_breadth=ThemeBreadth(
                active_count=len(active_themes),
                leading_industry_count=len(leading_industries),
                leading_concept_count=len(leading_concepts),
                lagging_count=len(lagging_themes),
            ),
            data_quality=MarketStructureDataQuality(
                status=status,
                missing_fields=missing_fields,
                sources=sources,
                errors=errors,
            ),
        )
        payload = dump_market_structure_model(context)
        if uses_preloaded_rankings:
            return payload
        return self._store_cached_hotspots(cache_key, payload)

    def _resolve_rankings(
        self,
        fetch_name: str,
        dataset: str,
        limit: int,
        errors: List[str],
        sources: List[MarketStructureSource],
        *,
        preloaded_rankings: Any = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        preloaded = self._rankings_from_payload(preloaded_rankings, dataset, sources)
        if preloaded is not None:
            return preloaded
        return self._fetch_rankings(fetch_name, dataset, limit, errors, sources)

    @staticmethod
    def _rankings_from_payload(
        rankings: Any,
        dataset: str,
        sources: List[MarketStructureSource],
    ) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
        if rankings is None:
            return None
        if not isinstance(rankings, dict):
            sources.append(
                MarketStructureSource(
                    provider="dsa",
                    dataset=dataset,
                    status="invalid",
                    message="preloaded ranking payload is invalid",
                )
            )
            return [], []

        top = rankings.get("top")
        bottom = rankings.get("bottom")
        top_items = list(top) if isinstance(top, list) else []
        bottom_items = list(bottom) if isinstance(bottom, list) else []
        if isinstance(rankings.get("status"), str):
            raw_status = rankings.get("status").strip().lower()
            status = raw_status if raw_status in {"ok", "partial", "not_supported", "unknown"} else "ok"
        else:
            status = "ok"
        if not top_items and not bottom_items:
            status = "empty"
        sources.append(
            MarketStructureSource(
                provider="dsa",
                dataset=dataset,
                status=status,
                message="reused fundamental_context ranking payload",
            )
        )
        return top_items, bottom_items

    def get_hotspot_detail(self, theme_name: str, market: str = "cn") -> Dict[str, Any]:
        """Return an explicit placeholder for richer hotspot detail evidence."""
        normalized_market = str(market or "cn").strip().lower() or "cn"
        status = "unknown" if normalized_market == "cn" else "not_supported"
        return {
            "theme_name": str(theme_name or "").strip(),
            "market": normalized_market,
            "status": status,
            "missing_fields": ["hotspot_route", "hotspot_constituents", "leader_stocks"],
        }

    def get_concept_rankings(
        self,
        limit: int = 5,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Get concept ranking top/bottom with timeout + concurrency protection."""
        errors: List[str] = []
        sources: List[MarketStructureSource] = []
        return self._resolve_rankings(
            "get_concept_rankings",
            "concept_rankings",
            limit,
            errors,
            sources,
        )

    def _get_cached_hotspots(
        self,
        cache_key: Tuple[str, Optional[str], int],
    ) -> Optional[Dict[str, Any]]:
        with self._hotspots_cache_lock:
            cached = self._hotspots_cache.get(cache_key)
            if not isinstance(cached, dict):
                return None

            payload = cached.get("payload")
            if not isinstance(payload, dict):
                return None

            expires_at = cached.get("expires_at")
            if isinstance(expires_at, (int, float)) and expires_at < time.time():
                self._hotspots_cache.pop(cache_key, None)
                return None

            return copy.deepcopy(payload)

    def _store_cached_hotspots(
        self,
        cache_key: Tuple[str, Optional[str], int],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if payload.get("status") == "ok":
            success_ttl = self._success_cache_ttl_seconds
            if success_ttl <= 0:
                return copy.deepcopy(payload)
            expires_at = time.time() + success_ttl
        else:
            status_error = payload.get("data_quality", {}).get("errors", [])
            has_missing = bool(payload.get("data_quality", {}).get("missing_fields", []))
            if status_error or has_missing or payload.get("status") != "ok":
                failure_ttl = self._failure_cache_ttl_seconds
                if failure_ttl <= 0:
                    return copy.deepcopy(payload)
                expires_at = time.time() + failure_ttl
            else:
                expires_at = None

        entry: Dict[str, Any] = {
            "payload": copy.deepcopy(payload),
            "expires_at": expires_at,
        }
        with self._hotspots_cache_lock:
            self._hotspots_cache[cache_key] = copy.deepcopy(entry)
        return copy.deepcopy(payload)

    @staticmethod
    def _coerce_cache_ttl(value: Any) -> float:
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return DEFAULT_RANKING_CACHE_FAILURE_TTL_SECONDS

    def _fetch_rankings(
        self,
        fetch_name: str,
        dataset: str,
        limit: int,
        errors: List[str],
        sources: List[MarketStructureSource],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        fetch_rankings = getattr(self.fetcher_manager, fetch_name, None)
        if not callable(fetch_rankings):
            sources.append(
                MarketStructureSource(
                    provider="dsa",
                    dataset=dataset,
                    status="missing",
                    message=f"{fetch_name} is unavailable",
                )
            )
            return [], []

        try:
            rankings = self._call_with_timeout(
                lambda: fetch_rankings(limit),
                timeout_seconds=self._resolve_ranking_fetch_timeout_seconds(),
                task_name=dataset,
                inflight_key=(
                    type(self.fetcher_manager),
                    id(self.fetcher_manager),
                    fetch_name,
                    limit,
                ),
            )
            if isinstance(rankings, tuple) and len(rankings) == 2:
                top, bottom = rankings
                top_items = list(top) if isinstance(top, list) else []
                bottom_items = list(bottom) if isinstance(bottom, list) else []
                sources.append(
                    MarketStructureSource(
                        provider="dsa",
                        dataset=dataset,
                        status="ok" if top_items or bottom_items else "empty",
                    )
                )
                return top_items, bottom_items
            sources.append(
                MarketStructureSource(
                    provider="dsa",
                    dataset=dataset,
                    status="invalid",
                    message="ranking provider returned an invalid payload",
                )
            )
        except Exception as exc:
            logger.debug("market hotspot ranking fetch failed dataset=%s: %s", dataset, exc)
            errors.append(f"{dataset}: {exc}")
            sources.append(
                MarketStructureSource(
                    provider="dsa",
                    dataset=dataset,
                    status="failed",
                    message=str(exc),
                )
            )
        return [], []

    def _resolve_ranking_fetch_timeout_seconds(self) -> float:
        if self._ranking_fetch_timeout_seconds is not None:
            try:
                return max(0.0, float(self._ranking_fetch_timeout_seconds))
            except (TypeError, ValueError):
                return DEFAULT_RANKING_FETCH_TIMEOUT_SECONDS
        try:
            from src.config import get_config

            value = getattr(
                get_config(),
                "fundamental_fetch_timeout_seconds",
                DEFAULT_RANKING_FETCH_TIMEOUT_SECONDS,
            )
            return max(0.0, float(value))
        except Exception:
            return DEFAULT_RANKING_FETCH_TIMEOUT_SECONDS

    @classmethod
    def _call_with_timeout(
        cls,
        task: Callable[[], Any],
        *,
        timeout_seconds: float,
        task_name: str,
        inflight_key: Optional[Hashable] = None,
    ) -> Any:
        timeout_value = max(0.0, float(timeout_seconds))
        if timeout_value <= 0:
            raise TimeoutError(f"{task_name} ranking fetch timeout")

        effective_inflight_key = inflight_key or task_name
        future = cls._get_or_submit_ranking_fetch(
            task,
            inflight_key=effective_inflight_key,
            task_name=task_name,
        )
        try:
            return future.result(timeout=timeout_value)
        except FutureTimeoutError as exc:
            if future.done() and future.exception(timeout=0) is exc:
                raise
            cls._mark_ranking_fetch_timeout(
                effective_inflight_key,
                future,
                retry_after=time.monotonic()
                + max(timeout_value, RANKING_FETCH_TIMEOUT_RETRY_DELAY_SECONDS),
            )
            raise TimeoutError(
                f"{task_name} ranking fetch timeout after {timeout_value:g}s"
            ) from exc

    @classmethod
    def _get_or_submit_ranking_fetch(
        cls,
        task: Callable[[], Any],
        *,
        inflight_key: Hashable,
        task_name: str,
    ) -> Future:
        submitted: Future
        worker: threading.Thread
        with cls._ranking_fetch_futures_lock:
            retry_entry = cls._ranking_fetch_retry_after.get(inflight_key)
            now = time.monotonic()
            if retry_entry is not None:
                retry_future, retry_after = retry_entry
                if retry_after > now:
                    raise TimeoutError(
                        f"{task_name} ranking fetch cooling down after previous timeout"
                    )
                cls._ranking_fetch_retry_after.pop(inflight_key, None)
                if cls._ranking_fetch_futures.get(inflight_key) is retry_future:
                    cls._ranking_fetch_futures.pop(inflight_key, None)
                    if retry_future.done() or retry_future.cancelled():
                        cls._ranking_fetch_slots.release()
                    else:
                        cls._ranking_fetch_detached_futures.add(retry_future)

            current = cls._ranking_fetch_futures.get(inflight_key)
            if current is not None:
                if not current.done():
                    return current
                cls._ranking_fetch_futures.pop(inflight_key, None)
                cls._ranking_fetch_slots.release()

            if not cls._ranking_fetch_slots.acquire(blocking=False):
                raise TimeoutError(f"{task_name} ranking fetch in-flight limit reached")

            future: Future = Future()
            cls._ranking_fetch_retry_after.pop(inflight_key, None)
            cls._ranking_fetch_futures[inflight_key] = future
            future.add_done_callback(
                lambda done_future: cls._forget_ranking_fetch(inflight_key, done_future)
            )
            worker = threading.Thread(
                target=cls._run_ranking_fetch,
                args=(future, task),
                daemon=True,
                name=f"market-hotspot-{task_name}",
            )
            submitted = future
        try:
            worker.start()
        except BaseException as exc:
            cls._drop_unstarted_ranking_fetch(inflight_key, submitted)
            submitted.set_exception(exc)
            raise
        return submitted

    @classmethod
    def _forget_ranking_fetch(cls, inflight_key: Hashable, future: Future) -> None:
        with cls._ranking_fetch_futures_lock:
            should_release_slot = False
            if cls._ranking_fetch_futures.get(inflight_key) is future:
                cls._ranking_fetch_futures.pop(inflight_key, None)
                should_release_slot = True
            elif future in cls._ranking_fetch_detached_futures:
                cls._ranking_fetch_detached_futures.remove(future)
                should_release_slot = True

            retry_entry = cls._ranking_fetch_retry_after.get(inflight_key)
            if retry_entry is not None and retry_entry[0] is future:
                cls._ranking_fetch_retry_after.pop(inflight_key, None)

            if should_release_slot:
                cls._ranking_fetch_slots.release()

    @classmethod
    def _mark_ranking_fetch_timeout(
        cls,
        inflight_key: Hashable,
        future: Future,
        *,
        retry_after: float,
    ) -> None:
        with cls._ranking_fetch_futures_lock:
            if cls._ranking_fetch_futures.get(inflight_key) is future:
                cls._ranking_fetch_futures.pop(inflight_key, None)
                if future.done() or future.cancelled():
                    cls._ranking_fetch_retry_after.pop(inflight_key, None)
                    cls._ranking_fetch_slots.release()
                    return
                cls._ranking_fetch_detached_futures.add(future)
                cls._ranking_fetch_retry_after[inflight_key] = (future, retry_after)

    @classmethod
    def _drop_unstarted_ranking_fetch(
        cls,
        inflight_key: Hashable,
        future: Future,
    ) -> None:
        with cls._ranking_fetch_futures_lock:
            if cls._ranking_fetch_futures.get(inflight_key) is future:
                cls._ranking_fetch_futures.pop(inflight_key, None)
                cls._ranking_fetch_slots.release()

    @staticmethod
    def _run_ranking_fetch(future: Future, task: Callable[[], Any]) -> None:
        if not future.set_running_or_notify_cancel():
            return
        try:
            result = task()
        except BaseException as exc:
            future.set_exception(exc)
        else:
            future.set_result(result)

    def _normalize_ranked_items(
        self,
        items: Any,
        source: ThemeRankSource,
    ) -> List[RankedThemeItem]:
        if not isinstance(items, list):
            return []

        normalized: List[RankedThemeItem] = []
        for index, item in enumerate(items, 1):
            if not isinstance(item, dict):
                continue
            name = self._optional_text(
                item.get("name")
                or item.get("板块名称")
                or item.get("概念名称")
                or item.get("行业名称")
            )
            if not name:
                continue
            change_pct = self._safe_float(
                item.get("change_pct")
                if "change_pct" in item
                else item.get("pct_chg")
                if "pct_chg" in item
                else item.get("涨跌幅")
                if "涨跌幅" in item
                else item.get("涨跌幅%")
            )
            normalized.append(
                RankedThemeItem(
                    name=name,
                    code=self._optional_text(item.get("code") or item.get("板块代码")),
                    change_pct=change_pct,
                    rank=self._safe_int(item.get("rank")) or index,
                    source=source,
                    updated_at=self._optional_text(item.get("updated_at")),
                )
            )
        return normalized

    def _build_active_themes(
        self,
        items: List[RankedThemeItem],
        *,
        limit: int,
    ) -> List[MarketThemeItem]:
        positive_items = [
            item for item in items if item.change_pct is not None and item.change_pct > 0
        ]
        positive_items.sort(key=lambda item: item.change_pct or 0, reverse=True)

        active: List[MarketThemeItem] = []
        for item in positive_items[:limit]:
            active.append(
                MarketThemeItem(
                    name=item.name,
                    code=item.code,
                    change_pct=item.change_pct,
                    rank=item.rank,
                    source=item.source,
                    updated_at=item.updated_at,
                    phase=self._phase_from_change(item.change_pct),
                    strength_score=self._strength_from_change(item.change_pct),
                    reason="industry/concept ranking gain",
                )
            )
        return active

    @staticmethod
    def _phase_from_change(value: Optional[float]) -> str:
        if value is None:
            return "unknown"
        if value >= 3:
            return "accelerating"
        if value > 0:
            return "warming"
        return "cooling"

    @staticmethod
    def _strength_from_change(value: Optional[float]) -> Optional[int]:
        if value is None:
            return None
        return max(0, min(100, int(round(50 + value * 8))))

    @staticmethod
    def _format_trade_date(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, date):
            return value.isoformat()
        text = str(value).strip()
        return text or None

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
