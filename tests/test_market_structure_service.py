# -*- coding: utf-8 -*-
"""Market structure service regression tests."""

from __future__ import annotations

from concurrent.futures import Future
import threading
import time

from src.services.market_hotspot_service import (
    RANKING_FETCH_TIMEOUT_RETRY_DELAY_SECONDS,
    MarketHotspotService,
)
from src.services.market_structure_service import MarketStructureService


class _FakeFetcherManager:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sector_calls = 0
        self.concept_calls = 0

    def get_sector_rankings(self, n: int = 5):
        self.sector_calls += 1
        if self.fail:
            raise RuntimeError("sector down")
        return (
            [{"name": "通用设备", "change_pct": 2.1}],
            [{"name": "旅游酒店", "change_pct": -1.8}],
        )

    def get_concept_rankings(self, n: int = 5):
        self.concept_calls += 1
        if self.fail:
            raise RuntimeError("concept down")
        return (
            [{"name": "机器人概念", "change_pct": 4.2}],
            [{"name": "转基因", "change_pct": -2.0}],
        )


class _DownTrendFetcherManager:
    def __init__(self) -> None:
        self.sector_calls = 0
        self.concept_calls = 0

    def get_sector_rankings(self, n: int = 5):
        self.sector_calls += 1
        return (
            [{"name": "通用设备", "change_pct": -1.8}],
            [{"name": "旅游酒店", "change_pct": -2.1}],
        )

    def get_concept_rankings(self, n: int = 5):
        self.concept_calls += 1
        return (
            [{"name": "机器人概念", "change_pct": 0.0}],
            [{"name": "转基因", "change_pct": -2.0}],
        )


class _OverlappingLaggingThemeFetcherManager:
    def get_sector_rankings(self, n: int = 5):
        return (
            [],
            [{"name": "旅游酒店", "rank": 1, "change_pct": -4.1}],
        )

    def get_concept_rankings(self, n: int = 5):
        return (
            [],
            [{"name": "转基因", "rank": 1, "change_pct": -2.0}],
        )


class _FullLaggingFamiliesFetcherManager:
    def get_sector_rankings(self, n: int = 5):
        return (
            [],
            [
                {"name": f"Industry {index}", "rank": index, "change_pct": -float(index)}
                for index in range(1, n + 1)
            ],
        )

    def get_concept_rankings(self, n: int = 5):
        return (
            [],
            [{"name": "Concept Target", "rank": 1, "change_pct": -6.0}],
        )


class _RecoverableFailureFetcherManager:
    def __init__(self) -> None:
        self.fail = True
        self.sector_calls = 0
        self.concept_calls = 0

    def get_sector_rankings(self, n: int = 5):
        self.sector_calls += 1
        if self.fail:
            raise RuntimeError("sector down")
        return (
            [{"name": "通用设备", "change_pct": -1.8}],
            [{"name": "旅游酒店", "change_pct": -2.1}],
        )

    def get_concept_rankings(self, n: int = 5):
        self.concept_calls += 1
        if self.fail:
            raise RuntimeError("concept down")
        return (
            [{"name": "机器人概念", "change_pct": 0.0}],
            [{"name": "转基因", "change_pct": -2.0}],
        )


class _EmptyHotspotService:
    def get_hotspots(
        self,
        *,
        market: str,
        trade_date=None,
        limit: int = 5,
        sector_rankings=None,
        concept_rankings=None,
    ):
        return {
            "status": "ok",
            "market": market,
            "trade_date": trade_date,
            "active_themes": [],
            "leading_industries": [],
            "leading_concepts": [],
            "lagging_themes": [],
        }


class _SourceConflictHotspotService:
    def get_hotspots(
        self,
        *,
        market: str,
        trade_date=None,
        limit: int = 5,
        sector_rankings=None,
        concept_rankings=None,
    ):
        return {
            "status": "ok",
            "market": market,
            "trade_date": trade_date,
            "active_themes": [],
            "leading_industries": [
                {
                    "name": "新能源",
                    "rank": 5,
                    "change_pct": 2.0,
                    "source": "industry",
                },
            ],
            "leading_concepts": [
                {
                    "name": "新能源",
                    "rank": 1,
                    "change_pct": 10.0,
                    "source": "concept",
                },
            ],
            "lagging_themes": [],
        }


class _ThemedHotspotService:
    def __init__(
        self,
        *,
        active_themes=None,
        leading_concepts=None,
        leading_industries=None,
        lagging_themes=None,
        hotspot_constituents=None,
        leader_stocks=None,
    ) -> None:
        self.active_themes = active_themes or []
        self.leading_concepts = leading_concepts or []
        self.leading_industries = leading_industries or []
        self.lagging_themes = lagging_themes or []
        self.hotspot_constituents = hotspot_constituents or []
        self.leader_stocks = leader_stocks or []

    def get_hotspots(
        self,
        *,
        market: str,
        trade_date=None,
        limit: int = 5,
        sector_rankings=None,
        concept_rankings=None,
    ):
        return {
            "status": "ok",
            "market": market,
            "trade_date": trade_date,
            "active_themes": self.active_themes,
            "leading_industries": self.leading_industries,
            "leading_concepts": self.leading_concepts,
            "lagging_themes": self.lagging_themes,
            "hotspot_constituents": self.hotspot_constituents,
            "leader_stocks": self.leader_stocks,
        }


class _BlockingRankingFetcherManager:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.sector_calls = 0
        self.concept_calls = 0

    def get_sector_rankings(self, n: int = 5):
        self.sector_calls += 1
        self.release.wait(timeout=1)
        return ([{"name": "通用设备", "change_pct": 2.1}], [])

    def get_concept_rankings(self, n: int = 5):
        self.concept_calls += 1
        self.release.wait(timeout=1)
        return ([{"name": "机器人概念", "change_pct": 4.2}], [])


class _ManagerScopedBlockingRankingFetcher:
    def __init__(self, name: str, release: threading.Event) -> None:
        self.name = name
        self.release = release
        self.sector_started = threading.Event()
        self.sector_calls = 0
        self.concept_calls = 0

    def get_sector_rankings(self, n: int = 5):
        self.sector_calls += 1
        self.sector_started.set()
        self.release.wait(timeout=1)
        return ([{"name": f"{self.name}行业", "change_pct": 2.1}], [])

    def get_concept_rankings(self, n: int = 5):
        self.concept_calls += 1
        return ([{"name": f"{self.name}概念", "change_pct": 4.2}], [])


class _RecoveringTimeoutRankingFetcherManager:
    def __init__(self) -> None:
        self.release_first_sector = threading.Event()
        self.first_sector_started = threading.Event()
        self.sector_calls = 0
        self.concept_calls = 0

    def get_sector_rankings(self, n: int = 5):
        self.sector_calls += 1
        if self.sector_calls == 1:
            self.first_sector_started.set()
            self.release_first_sector.wait()
        return ([{"name": "通用设备", "change_pct": 2.1}], [])

    def get_concept_rankings(self, n: int = 5):
        self.concept_calls += 1
        return ([{"name": "机器人概念", "change_pct": 4.2}], [])


class _PermanentlyBlockingRankingFetcherManager:
    def __init__(self, *, block: bool) -> None:
        self.block = block
        self.release = threading.Event()
        self.sector_started = threading.Event()
        self.concept_started = threading.Event()
        self.sector_calls = 0
        self.concept_calls = 0

    def get_sector_rankings(self, n: int = 5):
        self.sector_calls += 1
        if self.block:
            self.sector_started.set()
            self.release.wait()
        return ([{"name": "通用设备", "change_pct": 2.1}], [])

    def get_concept_rankings(self, n: int = 5):
        self.concept_calls += 1
        if self.block:
            self.concept_started.set()
            self.release.wait()
        return ([{"name": "机器人概念", "change_pct": 4.2}], [])


class _UnexpectedRankingFetcherManager:
    def get_sector_rankings(self, n: int = 5):
        raise AssertionError("sector rankings should be reused from fundamental_context")

    def get_concept_rankings(self, n: int = 5):
        raise AssertionError("concept rankings should be reused from fundamental_context")


def _wait_for_market_hotspot_workers_to_drain(timeout: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with MarketHotspotService._ranking_fetch_futures_lock:
            pending = [
                future
                for future in MarketHotspotService._ranking_fetch_futures.values()
                if not future.done()
            ]
            pending.extend(
                future
                for future in MarketHotspotService._ranking_fetch_detached_futures
                if not future.done()
            )
        if not pending:
            return True
        time.sleep(0.01)
    return False


def test_market_hotspot_service_builds_theme_context_from_dsa_rankings() -> None:
    service = MarketHotspotService(fetcher_manager=_FakeFetcherManager())

    context = service.get_hotspots(market="cn", trade_date="2026-07-04")

    assert context["schema_version"] == "market-theme-v1"
    assert context["status"] == "ok"
    assert context["active_themes"][0]["name"] == "机器人概念"
    assert context["leading_concepts"][0]["change_pct"] == 4.2
    assert context["theme_breadth"]["leading_concept_count"] == 1


def test_market_hotspot_service_caches_rankings_per_instance() -> None:
    fetcher = _FakeFetcherManager()
    service = MarketHotspotService(fetcher_manager=fetcher)

    first = service.get_hotspots(market="cn", trade_date="2026-07-04")
    second = service.get_hotspots(market="cn", trade_date="2026-07-04")

    assert first == second
    assert fetcher.sector_calls == 1
    assert fetcher.concept_calls == 1


def test_market_hotspot_service_refreshes_cached_ok_after_ttl() -> None:
    fetcher = _FakeFetcherManager()
    service = MarketHotspotService(
        fetcher_manager=fetcher,
        success_cache_ttl_seconds=0.02,
    )

    service.get_hotspots(market="cn", trade_date="2026-07-04")
    time.sleep(0.05)
    service.get_hotspots(market="cn", trade_date="2026-07-04")

    assert fetcher.sector_calls == 2
    assert fetcher.concept_calls == 2


def test_market_hotspot_service_fails_open_when_rankings_unavailable() -> None:
    service = MarketHotspotService(fetcher_manager=_FakeFetcherManager(fail=True))

    context = service.get_hotspots(market="cn", trade_date="2026-07-04")

    assert context["status"] == "unknown"
    assert context["data_quality"]["errors"]
    assert "industry_rankings" in context["data_quality"]["missing_fields"]
    assert "concept_rankings" in context["data_quality"]["missing_fields"]


def test_market_hotspot_service_bounds_ranking_fetches() -> None:
    fetcher = _BlockingRankingFetcherManager()
    service = MarketHotspotService(
        fetcher_manager=fetcher,
        ranking_fetch_timeout_seconds=0.01,
    )

    started_at = time.monotonic()
    try:
        context = service.get_hotspots(market="cn", trade_date="2026-07-04")
    finally:
        fetcher.release.set()
        _wait_for_market_hotspot_workers_to_drain()

    assert time.monotonic() - started_at < 0.2
    assert context["status"] == "unknown"
    assert fetcher.sector_calls == 1
    assert fetcher.concept_calls == 1
    assert any("timeout" in error for error in context["data_quality"]["errors"])


def test_market_hotspot_service_does_not_stack_workers_after_timeout() -> None:
    fetcher = _BlockingRankingFetcherManager()
    service = MarketHotspotService(
        fetcher_manager=fetcher,
        ranking_fetch_timeout_seconds=0.01,
        failure_cache_ttl_seconds=0.0,
    )

    try:
        first = service.get_hotspots(market="cn", trade_date="2026-07-04")
        second = service.get_hotspots(market="cn", trade_date="2026-07-04")
    finally:
        fetcher.release.set()
        _wait_for_market_hotspot_workers_to_drain()

    assert first["status"] == "unknown"
    assert second["status"] == "unknown"
    assert fetcher.sector_calls == 1
    assert fetcher.concept_calls == 1
    assert any("timeout" in error for error in first["data_quality"]["errors"])
    assert any("timeout" in error for error in second["data_quality"]["errors"])


def test_market_hotspot_service_scopes_inflight_fetches_to_manager_instance() -> None:
    release = threading.Event()
    first_fetcher = _ManagerScopedBlockingRankingFetcher("甲", release)
    second_fetcher = _ManagerScopedBlockingRankingFetcher("乙", release)
    services = (
        MarketHotspotService(fetcher_manager=first_fetcher),
        MarketHotspotService(fetcher_manager=second_fetcher),
    )
    contexts = [None, None]

    def fetch(index: int) -> None:
        contexts[index] = services[index].get_hotspots(
            market="cn",
            trade_date="2026-07-04",
        )

    threads = [threading.Thread(target=fetch, args=(index,)) for index in range(2)]
    try:
        threads[0].start()
        assert first_fetcher.sector_started.wait(timeout=0.2)
        threads[1].start()
        assert second_fetcher.sector_started.wait(timeout=0.2)
    finally:
        release.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=1)

    assert contexts[0]["leading_industries"][0]["name"] == "甲行业"
    assert contexts[1]["leading_industries"][0]["name"] == "乙行业"
    assert first_fetcher.sector_calls == 1
    assert second_fetcher.sector_calls == 1


def test_market_hotspot_service_retries_after_ranking_timeout_cooldown() -> None:
    fetcher = _RecoveringTimeoutRankingFetcherManager()
    service = MarketHotspotService(
        fetcher_manager=fetcher,
        ranking_fetch_timeout_seconds=0.01,
        failure_cache_ttl_seconds=0.0,
    )
    drained = False

    try:
        first = service.get_hotspots(market="cn", trade_date="2026-07-04")

        assert first["status"] == "partial"
        assert fetcher.first_sector_started.is_set()
        assert fetcher.sector_calls == 1
        assert any(
            "sector_rankings" in error and "timeout" in error
            for error in first["data_quality"]["errors"]
        )

        time.sleep(RANKING_FETCH_TIMEOUT_RETRY_DELAY_SECONDS + 0.05)
        recovered = service.get_hotspots(market="cn", trade_date="2026-07-04")
    finally:
        fetcher.release_first_sector.set()
        drained = _wait_for_market_hotspot_workers_to_drain()

    assert drained
    assert recovered["status"] == "ok"
    assert recovered["leading_industries"][0]["name"] == "通用设备"
    assert fetcher.sector_calls == 2
    assert fetcher.concept_calls == 2


def test_market_hotspot_service_drops_stale_timeout_future_before_retry() -> None:
    fetcher = _FakeFetcherManager()
    service = MarketHotspotService(
        fetcher_manager=fetcher,
        ranking_fetch_timeout_seconds=0.01,
        failure_cache_ttl_seconds=0.0,
    )
    stale_future: Future = Future()
    inflight_key = (type(fetcher), id(fetcher), "get_sector_rankings", 5)
    stale_future.add_done_callback(
        lambda done_future: MarketHotspotService._forget_ranking_fetch(
            inflight_key, done_future
        )
    )

    with MarketHotspotService._ranking_fetch_futures_lock:
        acquired = MarketHotspotService._ranking_fetch_slots.acquire(blocking=False)
        assert acquired
        MarketHotspotService._ranking_fetch_futures[inflight_key] = stale_future
        MarketHotspotService._ranking_fetch_retry_after[inflight_key] = (
            stale_future,
            time.monotonic() - 0.01,
        )

    try:
        context = service.get_hotspots(market="cn", trade_date="2026-07-04")
    finally:
        if not stale_future.done():
            stale_future.set_result(None)
        _wait_for_market_hotspot_workers_to_drain()

    assert context["status"] == "ok"
    assert fetcher.sector_calls == 1
    assert fetcher.concept_calls == 1
    with MarketHotspotService._ranking_fetch_futures_lock:
        assert (
            MarketHotspotService._ranking_fetch_futures.get(inflight_key)
            is not stale_future
        )


def test_market_hotspot_service_keeps_permanent_timeouts_under_worker_cap() -> None:
    fetcher = _PermanentlyBlockingRankingFetcherManager(block=True)
    service = MarketHotspotService(
        fetcher_manager=fetcher,
        ranking_fetch_timeout_seconds=0.05,
        failure_cache_ttl_seconds=0.0,
    )
    drained = False

    try:
        first = service.get_hotspots(market="cn", trade_date="2026-07-04")

        assert first["status"] == "unknown"
        assert fetcher.sector_started.wait(timeout=0.2)
        assert fetcher.concept_started.wait(timeout=0.2)

        time.sleep(RANKING_FETCH_TIMEOUT_RETRY_DELAY_SECONDS + 0.05)
        second = service.get_hotspots(market="cn", trade_date="2026-07-04")

        time.sleep(RANKING_FETCH_TIMEOUT_RETRY_DELAY_SECONDS + 0.05)
        third = service.get_hotspots(market="cn", trade_date="2026-07-04")
    finally:
        fetcher.release.set()
        drained = _wait_for_market_hotspot_workers_to_drain()

    assert drained
    assert second["status"] == "unknown"
    assert third["status"] == "unknown"
    assert fetcher.sector_calls == 1
    assert fetcher.concept_calls == 1


def test_market_hotspot_service_marks_flat_down_rankings_as_ok_without_active_themes() -> None:
    service = MarketHotspotService(fetcher_manager=_DownTrendFetcherManager())

    context = service.get_hotspots(market="cn", trade_date="2026-07-04")

    assert context["status"] == "ok"
    assert context["active_themes"] == []
    assert context["theme_breadth"]["active_count"] == 0
    assert context["data_quality"]["missing_fields"] == []
    assert not context["data_quality"]["errors"]


def test_market_hotspot_service_recovers_after_failed_cache_ttl_expiry() -> None:
    fetcher = _RecoverableFailureFetcherManager()
    service = MarketHotspotService(
        fetcher_manager=fetcher,
        failure_cache_ttl_seconds=0.0,
    )

    failed = service.get_hotspots(market="cn", trade_date="2026-07-04")
    assert failed["status"] == "unknown"

    fetcher.fail = False
    recovered = service.get_hotspots(market="cn", trade_date="2026-07-04")

    assert recovered["status"] == "ok"
    assert recovered["active_themes"] == []
    assert fetcher.sector_calls == 2
    assert fetcher.concept_calls == 2


def test_market_structure_service_reuses_fundamental_rankings_for_theme_layer() -> None:
    service = MarketStructureService(fetcher_manager=_UnexpectedRankingFetcherManager())
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "机器人概念", "type": "概念"}],
        "concept_boards": {
            "status": "ok",
            "data": {
                "top": [{"name": "机器人概念", "rank": 1, "change_pct": 4.2}],
                "bottom": [],
            },
        },
        "boards": {
            "status": "ok",
            "data": {
                "top": [{"name": "通用设备", "rank": 2, "change_pct": 2.1}],
                "bottom": [],
            },
        },
    }

    context = service.build_context(
        code="300024",
        stock_name="机器人",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    assert context["market_theme_context"]["active_themes"][0]["name"] == "机器人概念"
    assert context["market_theme_context"]["leading_concepts"][0]["rank"] == 1


def test_market_structure_service_marks_partial_if_fundamental_rankings_partial_with_missing_bottom() -> None:
    service = MarketStructureService(fetcher_manager=_FakeFetcherManager())
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "机器人概念", "type": "概念"}],
        "concept_boards": {
            "status": "partial",
            "data": {
                "top": [{"name": "机器人概念", "rank": 1, "change_pct": 4.2}],
                "bottom": [],
            },
        },
        "boards": {
            "status": "partial",
            "data": {
                "top": [{"name": "通用设备", "rank": 2, "change_pct": 2.1}],
                "bottom": [],
            },
        },
    }

    context = service.build_context(
        code="300024",
        stock_name="机器人",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    market_theme = context["market_theme_context"]
    position = context["stock_market_position"]
    assert market_theme["status"] == "partial"
    assert market_theme["data_quality"]["status"] == "partial"
    assert {source["status"] for source in market_theme["data_quality"]["sources"]} == {
        "partial"
    }
    assert any(tag["code"] == "theme_data_partial" for tag in position["risk_tags"])


def test_market_structure_service_skips_hotspots_for_unsupported_board_context() -> None:
    unsupported_payloads = [
        {
            "market": "cn",
            "status": "not_supported",
            "coverage": {"boards": "not_supported"},
            "boards": {"status": "not_supported", "data": {}},
            "errors": ["fundamental pipeline disabled"],
        },
        {
            "market": "cn",
            "status": "partial",
            "coverage": {"boards": "not_supported"},
            "boards": {"status": "not_supported", "data": {}},
            "errors": ["etf not fully supported"],
        },
    ]

    for fundamental_context in unsupported_payloads:
        fetcher = _FakeFetcherManager()
        service = MarketStructureService(fetcher_manager=fetcher)

        context = service.build_context(
            code="159915",
            stock_name="创业板ETF",
            market="cn",
            fundamental_context=fundamental_context,
            trade_date="2026-07-04",
        )

        assert context["status"] == "not_supported"
        assert context["market_theme_context"]["status"] == "not_supported"
        assert context["stock_market_position"]["status"] == "not_supported"
        assert fetcher.sector_calls == 0
        assert fetcher.concept_calls == 0


def test_market_structure_service_combines_market_and_stock_layers() -> None:
    service = MarketStructureService(fetcher_manager=_FakeFetcherManager())
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "机器人概念", "type": "概念"}],
        "concept_boards": {
            "status": "ok",
            "data": {
                "top": [{"name": "机器人概念", "change_pct": 4.2}],
                "bottom": [],
            },
        },
        "boards": {
            "status": "ok",
            "data": {
                "top": [{"name": "通用设备", "change_pct": 2.1}],
                "bottom": [],
            },
        },
    }

    context = service.build_context(
        code="300024",
        stock_name="机器人",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    assert context["schema_version"] == "market-structure-v1"
    assert context["market_theme_context"]["active_themes"][0]["name"] == "机器人概念"
    position = context["stock_market_position"]
    assert position["primary_theme"]["name"] == "机器人概念"
    assert position["theme_phase"] == "accelerating"
    assert position["stock_role"] == "edge"
    assert "leader_stocks" in position["missing_fields"]


def test_market_structure_service_recognizes_leader_only_for_matching_theme() -> None:
    service = MarketStructureService(
        fetcher_manager=_FakeFetcherManager(),
        hotspot_service=_ThemedHotspotService(
            leading_concepts=[{"name": "机器人概念", "change_pct": 4.2}],
            hotspot_constituents=[{"code": "300024", "topic": "机器人概念"}],
            leader_stocks=[{"code": "300024", "topic": "机器人概念"}],
        ),
    )
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "机器人概念", "type": "概念"}],
        "concept_boards": {
            "status": "ok",
            "data": {"top": [{"name": "机器人概念", "change_pct": 4.2}], "bottom": []},
        },
    }

    context = service.build_context(
        code="300024",
        stock_name="机器人",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    position = context["stock_market_position"]
    assert position["stock_role"] == "leader"
    assert position["status"] == "ok"


def test_market_structure_service_recognizes_follower_when_constituent_theme_matches() -> None:
    service = MarketStructureService(
        fetcher_manager=_FakeFetcherManager(),
        hotspot_service=_ThemedHotspotService(
            leading_concepts=[{"name": "机器人概念", "change_pct": 4.2}],
            hotspot_constituents=[{"code": "300024", "topic": "机器人概念"}],
            leader_stocks=[{"code": "300010", "topic": "机器人概念"}],
        ),
    )
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "机器人概念", "type": "概念"}],
        "concept_boards": {
            "status": "ok",
            "data": {"top": [{"name": "机器人概念", "change_pct": 4.2}], "bottom": []},
        },
    }

    context = service.build_context(
        code="300024",
        stock_name="机器人",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    position = context["stock_market_position"]
    assert position["stock_role"] == "follower"
    assert position["status"] == "ok"


def test_market_structure_service_rejects_role_evidence_from_unmatched_theme() -> None:
    service = MarketStructureService(
        fetcher_manager=_FakeFetcherManager(),
        hotspot_service=_ThemedHotspotService(
            leading_concepts=[{"name": "机器人概念", "change_pct": 4.2}],
            hotspot_constituents=[{"code": "300024", "topic": "新能源"},
                                 {"code": "300024", "topic": "半导体"}],
            leader_stocks=[{"code": "300024", "theme": "新能源"}],
        ),
    )
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "机器人概念", "type": "概念"}],
        "concept_boards": {
            "status": "ok",
            "data": {"top": [{"name": "机器人概念", "change_pct": 4.2}], "bottom": []},
        },
    }

    context = service.build_context(
        code="300024",
        stock_name="机器人",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    position = context["stock_market_position"]
    assert position["stock_role"] == "edge"
    assert "leader_stocks" not in position["missing_fields"]
    assert "hotspot_constituents" not in position["missing_fields"]


def test_market_structure_service_infers_concept_board_from_missing_type_name() -> None:
    service = MarketStructureService(
        fetcher_manager=_FakeFetcherManager(),
        hotspot_service=_EmptyHotspotService(),
    )
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "机器人概念"}],
        "concept_boards": {
            "status": "ok",
            "data": {
                "top": [{"name": "机器人概念", "rank": 1, "change_pct": 4.2}],
                "bottom": [],
            },
        },
        "boards": {
            "status": "ok",
            "data": {
                "top": [{"name": "通用设备", "rank": 2, "change_pct": 2.1}],
                "bottom": [],
            },
        },
    }

    context = service.build_context(
        code="300024",
        stock_name="机器人",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    position = context["stock_market_position"]
    assert position["status"] == "partial"
    assert position["primary_theme"]["source"] == "concept"
    assert position["primary_theme"]["change_pct"] == 4.2
    assert position["theme_phase"] == "accelerating"
    assert position["related_boards"][0]["source"] == "concept"
    assert position["stock_role"] == "edge"
    assert "theme_ranking_match" in position["missing_fields"]


def test_market_structure_service_resolves_missing_type_board_from_concept_rankings() -> None:
    service = MarketStructureService(
        fetcher_manager=_FakeFetcherManager(),
        hotspot_service=_EmptyHotspotService(),
    )
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "新能源"}],
        "concept_boards": {
            "status": "ok",
            "data": {
                "top": [{"name": "新能源", "rank": 1, "change_pct": 5.6}],
                "bottom": [],
            },
        },
        "boards": {
            "status": "ok",
            "data": {
                "top": [{"name": "通用设备", "rank": 2, "change_pct": 2.1}],
                "bottom": [],
            },
        },
    }

    context = service.build_context(
        code="300024",
        stock_name="机器人",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    position = context["stock_market_position"]
    assert position["status"] == "partial"
    assert position["primary_theme"]["source"] == "concept"
    assert position["primary_theme"]["change_pct"] == 5.6
    assert position["theme_phase"] == "accelerating"
    assert position["stock_role"] == "edge"
    assert "theme_ranking_match" in position["missing_fields"]
    assert position["related_boards"][0]["source"] == "concept"
    assert position["related_boards"][0]["change_pct"] == 5.6


def test_market_structure_service_keeps_stock_layer_partial_without_ranking_evidence() -> None:
    service = MarketStructureService(fetcher_manager=_FakeFetcherManager())
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "未上榜概念", "type": "概念"}],
        "concept_boards": {
            "status": "ok",
            "data": {"top": [{"name": "机器人概念", "change_pct": 4.2}], "bottom": []},
        },
    }

    context = service.build_context(
        code="300024",
        stock_name="机器人",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    position = context["stock_market_position"]
    assert position["status"] == "partial"
    assert position["stock_role"] == "edge"
    assert position["primary_theme"]["name"] == "未上榜概念"
    assert position["theme_phase"] == "unknown"
    assert "theme_ranking_match" in position["missing_fields"]
    assert {tag["code"] for tag in position["risk_tags"]} == {"stock_theme_evidence_partial"}


def test_market_structure_service_uses_lagging_themes_for_board_match() -> None:
    service = MarketStructureService(fetcher_manager=_DownTrendFetcherManager())
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "转基因", "type": "概念"}],
    }

    context = service.build_context(
        code="300024",
        stock_name="转基因",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    position = context["stock_market_position"]
    assert position["status"] == "partial"
    assert position["primary_theme"]["name"] == "转基因"
    assert position["theme_phase"] == "cooling"
    assert position["stock_role"] == "edge"
    assert position["related_boards"][0]["name"] == "转基因"
    assert position["related_boards"][0]["source"] == "concept"
    assert position["related_boards"][0]["change_pct"] == -2.0
    assert "theme_ranking_match" not in position["missing_fields"]


def test_market_structure_service_keeps_lagging_sources_before_board_match() -> None:
    service = MarketStructureService(fetcher_manager=_OverlappingLaggingThemeFetcherManager())
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "旅游酒店"}],
    }

    context = service.build_context(
        code="000001",
        stock_name="平安银行",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    lagging_themes = context["market_theme_context"]["lagging_themes"]
    assert lagging_themes[0]["source"] == "industry"
    position = context["stock_market_position"]
    assert position["primary_theme"]["source"] == "industry"
    assert position["primary_theme"]["change_pct"] == -4.1
    assert position["related_boards"][0]["source"] == "industry"
    assert "theme_ranking_match" not in position["missing_fields"]


def test_market_structure_service_preserves_lagging_concepts_after_full_industry_list() -> None:
    service = MarketStructureService(fetcher_manager=_FullLaggingFamiliesFetcherManager())
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "Concept Target", "type": "concept"}],
    }

    context = service.build_context(
        code="300024",
        stock_name="Example Stock",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-10",
    )

    lagging_themes = context["market_theme_context"]["lagging_themes"]
    assert len(lagging_themes) == 6
    assert lagging_themes[-1]["name"] == "Concept Target"
    assert lagging_themes[-1]["source"] == "concept"
    position = context["stock_market_position"]
    assert position["primary_theme"]["name"] == "Concept Target"
    assert position["primary_theme"]["source"] == "concept"
    assert position["primary_theme"]["change_pct"] == -6.0
    assert "theme_ranking_match" not in position["missing_fields"]


def test_market_structure_service_prefers_ranked_related_board_fallback() -> None:
    service = MarketStructureService(
        fetcher_manager=_FakeFetcherManager(),
        hotspot_service=_EmptyHotspotService(),
    )
    fundamental_context = {
        "market": "cn",
        "belong_boards": [
            {"name": "宽基板块", "type": "行业"},
            {"name": "机器人概念", "type": "概念"},
        ],
        "concept_boards": {
            "status": "ok",
            "data": {
                "top": [{"name": "机器人概念", "rank": 3}],
                "bottom": [],
            },
        },
        "boards": {
            "status": "ok",
            "data": {"top": [], "bottom": []},
        },
    }

    context = service.build_context(
        code="300024",
        stock_name="机器人",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    position = context["stock_market_position"]
    assert position["status"] == "partial"
    assert position["primary_theme"]["name"] == "机器人概念"
    assert position["primary_theme"]["rank"] == 3
    assert position["stock_role"] == "edge"
    assert "theme_ranking_match" in position["missing_fields"]


def test_market_structure_service_prefers_board_source_for_primary_theme() -> None:
    service = MarketStructureService(
        fetcher_manager=_FakeFetcherManager(),
        hotspot_service=_SourceConflictHotspotService(),
    )
    fundamental_context = {
        "market": "cn",
        "belong_boards": [{"name": "新能源", "type": "行业"}],
        "concept_boards": {
            "status": "ok",
            "data": {
                "top": [],
                "bottom": [],
            },
        },
        "boards": {
            "status": "ok",
            "data": {
                "top": [],
                "bottom": [],
            },
        },
    }

    context = service.build_context(
        code="000001",
        stock_name="新能源相关股",
        market="cn",
        fundamental_context=fundamental_context,
        trade_date="2026-07-04",
    )

    position = context["stock_market_position"]
    assert position["primary_theme"]["name"] == "新能源"
    assert position["primary_theme"]["source"] == "industry"
    assert position["primary_theme"]["change_pct"] == 2.0
    assert position["primary_theme"]["phase"] == "warming"
    assert position["stock_role"] == "edge"
    assert "theme_ranking_match" not in position["missing_fields"]


def test_market_structure_service_returns_not_supported_for_non_cn() -> None:
    service = MarketStructureService(fetcher_manager=_FakeFetcherManager())

    context = service.build_context(
        code="AAPL",
        stock_name="Apple",
        market="us",
        fundamental_context={"market": "us", "belong_boards": [{"name": "Technology"}]},
    )

    assert context["status"] == "not_supported"
    assert context["market_theme_context"]["status"] == "not_supported"
    assert context["stock_market_position"]["status"] == "not_supported"
