# -*- coding: utf-8 -*-
"""Concurrency regression tests for search service shared state."""

import sys
import threading
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import (
    BaseSearchProvider,
    SearchResponse,
    SearchResult,
    SearchService,
    get_search_service,
    reset_search_service,
)


class _ThreadUnsafeCycle:
    def __init__(self, values):
        self._values = list(values)
        self._index = 0
        self._active = False

    def __next__(self):
        if self._active:
            raise AssertionError("concurrent cycle access")
        self._active = True
        try:
            time.sleep(0.05)
            value = self._values[self._index % len(self._values)]
            self._index += 1
            return value
        finally:
            self._active = False


class _DummyProvider(BaseSearchProvider):
    def __init__(self, api_keys):
        super().__init__(api_keys, "DummyProvider")

    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        return SearchResponse(
            query=query,
            results=[
                SearchResult(
                    title=f"{api_key}:{query}",
                    snippet="snippet",
                    url=f"https://example.com/{api_key}",
                    source="example.com",
                    published_date=datetime.now().date().isoformat(),
                )
            ],
            provider=self.name,
            success=True,
        )


class SearchServiceConcurrencyTestCase(unittest.TestCase):
    def tearDown(self) -> None:
        reset_search_service()

    def test_get_cached_or_reserve_prefers_cached_response(self):
        service = SearchService(
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        cache_key = "cached-query|3|3"
        response = SearchResponse(
            query="cached-query",
            results=[
                SearchResult(
                    title="cached-news",
                    snippet="snippet",
                    url="https://example.com/cached-news",
                    source="example.com",
                    published_date=datetime.now().date().isoformat(),
                )
            ],
            provider="Cache",
            success=True,
        )
        service._put_cache(cache_key, response)

        cached, owner, event = service._get_cached_or_reserve(cache_key)

        self.assertIs(cached, response)
        self.assertFalse(owner)
        self.assertIsNone(event)
        self.assertNotIn(cache_key, service._cache_inflight)

    def test_provider_key_rotation_is_serialized(self):
        provider = _DummyProvider(["key-1", "key-2"])
        provider._key_cycle = _ThreadUnsafeCycle(["key-1", "key-2"])

        barrier = threading.Barrier(2)
        errors = []

        def worker():
            try:
                barrier.wait(timeout=1)
                provider.search("query", max_results=1)
            except Exception as exc:  # pragma: no cover - thread collection
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertEqual(sum(provider._key_usage.values()), 2)

    def test_search_stock_news_coalesces_concurrent_cache_fill(self):
        service = SearchService(
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short",
        )

        call_count = 0
        call_lock = threading.Lock()

        def provider_search(query, max_results, days=7, **_kwargs):
            nonlocal call_count
            with call_lock:
                call_count += 1
            time.sleep(0.05)
            return SearchResponse(
                query=query,
                results=[
                    SearchResult(
                        title="fresh-news",
                        snippet="snippet",
                        url="https://example.com/fresh-news",
                        source="example.com",
                        published_date=datetime.now().date().isoformat(),
                    )
                ],
                provider="MockProvider",
                success=True,
            )

        provider = SimpleNamespace(
            is_available=True,
            name="MockProvider",
            search=MagicMock(side_effect=provider_search),
        )
        service._providers = [provider]

        barrier = threading.Barrier(4)
        errors = []
        responses = []

        def worker():
            try:
                barrier.wait(timeout=1)
                responses.append(service.search_stock_news("600519", "贵州茅台", max_results=3))
            except Exception as exc:  # pragma: no cover - thread collection
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertEqual(call_count, 1)
        self.assertEqual(len(responses), 4)
        for response in responses:
            self.assertTrue(response.success)
            self.assertEqual([item.title for item in response.results], ["fresh-news"])

    def test_search_stock_news_rechecks_cache_after_wait_before_provider_search(self):
        service = SearchService(
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        search_days = service._effective_news_window_days()
        cache_key = service._cache_key("贵州茅台 600519 股票 最新消息|news_pref=zh", 3, search_days)
        cached_response = SearchResponse(
            query="贵州茅台 600519 股票 最新消息",
            results=[
                SearchResult(
                    title="cached-after-wait",
                    snippet="snippet",
                    url="https://example.com/cached-after-wait",
                    source="example.com",
                    published_date=datetime.now().date().isoformat(),
                )
            ],
            provider="Cache",
            success=True,
        )
        service._cache_inflight[cache_key] = threading.Event()
        provider = SimpleNamespace(
            is_available=True,
            name="MockProvider",
            search=MagicMock(side_effect=AssertionError("provider search should not run after cache fills")),
        )
        service._providers = [provider]

        def wait_for_cached(key, _event):
            self.assertEqual(key, cache_key)
            service._put_cache(cache_key, cached_response)
            return None

        with patch.object(service, "_wait_for_cached", side_effect=wait_for_cached):
            response = service.search_stock_news("600519", "贵州茅台", max_results=3)

        self.assertIs(response, cached_response)
        provider.search.assert_not_called()

    def test_get_search_service_initializes_singleton_once(self):
        reset_search_service()
        config = SimpleNamespace(
            bocha_api_keys=[],
            tavily_api_keys=[],
            brave_api_keys=[],
            serpapi_keys=[],
            minimax_api_keys=[],
            searxng_base_urls=[],
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short",
            anspire_api_keys=[],
        )

        created = []

        def build_service(**kwargs):
            time.sleep(0.05)
            service = SimpleNamespace(kwargs=kwargs)
            created.append(service)
            return service

        barrier = threading.Barrier(4)
        errors = []
        services = []

        with patch("src.search_service.SearchService", side_effect=build_service) as mock_cls:
            with patch("src.config.get_config", return_value=config):
                def worker():
                    try:
                        barrier.wait(timeout=1)
                        services.append(get_search_service())
                    except Exception as exc:  # pragma: no cover - thread collection
                        errors.append(exc)

                threads = [threading.Thread(target=worker) for _ in range(4)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertEqual(mock_cls.call_count, 1)
        self.assertEqual(len(created), 1)
        self.assertEqual(len({id(service) for service in services}), 1)


if __name__ == "__main__":
    unittest.main()
