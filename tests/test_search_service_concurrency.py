# -*- coding: utf-8 -*-
"""Concurrency regression tests for search service shared state."""

import sys
import multiprocessing
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
    _call_topic_news_in_subprocess,
    get_search_service,
    reset_search_service,
)


def _hang_topic_news_process_worker(*_args):
    time.sleep(10)


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
        cache_key = service._cache_key(
            "贵州茅台 600519 股票 最新消息|target=600519:贵州茅台|news_pref=zh",
            3,
            search_days,
        )
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

    def test_bounded_topic_search_caches_in_parent_before_starting_another_process(self):
        service = SearchService(
            bocha_keys=["dummy_key"],
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        response = SearchResponse(
            query='"影视传媒" A股 最新消息 催化',
            results=[
                SearchResult(
                    title="影视传媒订单",
                    snippet="板块近期出现新订单。",
                    url="https://example.com/topic-news",
                    source="example.com",
                    published_date=datetime.now().date().isoformat(),
                )
            ],
            provider="MockProvider",
            success=True,
        )

        with patch("src.search_service._call_topic_news_in_subprocess", return_value=response) as subprocess_call:
            first = service.search_topic_news_bounded("影视传媒", max_results=2, timeout_seconds=0.5)
            second = service.search_topic_news_bounded("影视传媒", max_results=2, timeout_seconds=0.5)

        self.assertIs(first, response)
        self.assertIs(second, response)
        subprocess_call.assert_called_once()
        self.assertEqual(service._cache_inflight, {})

    def test_bounded_topic_search_waits_when_retry_reservation_has_another_owner(self):
        service = SearchService(
            bocha_keys=["dummy_key"],
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        first_owner = threading.Event()
        retry_owner = threading.Event()
        response = SearchResponse(
            query='"影视传媒" A股 最新消息 催化',
            results=[
                SearchResult(
                    title="并发 owner 返回结果",
                    snippet="只允许 owner 执行供应商链。",
                    url="https://example.com/coalesced-topic-news",
                    source="example.com",
                    published_date=datetime.now().date().isoformat(),
                )
            ],
            provider="MockProvider",
            success=True,
        )

        with (
            patch.object(
                service,
                "_get_cached_or_reserve",
                side_effect=[
                    (None, False, first_owner),
                    (None, False, retry_owner),
                ],
            ),
            patch.object(service, "_wait_for_cached", side_effect=[None, response]) as wait_for_cached,
            patch("src.search_service._call_topic_news_in_subprocess") as subprocess_call,
        ):
            actual = service.search_topic_news_bounded("影视传媒", max_results=2, timeout_seconds=0.5)

        self.assertIs(actual, response)
        self.assertIs(wait_for_cached.call_args_list[0].args[1], first_owner)
        self.assertIs(wait_for_cached.call_args_list[1].args[1], retry_owner)
        subprocess_call.assert_not_called()

    def test_bounded_topic_search_cache_wait_uses_the_caller_deadline(self):
        service = SearchService(
            bocha_keys=["dummy_key"],
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        current_owner = threading.Event()

        with (
            patch.object(
                service,
                "_get_cached_or_reserve",
                return_value=(None, False, current_owner),
            ),
            patch("src.search_service._call_topic_news_in_subprocess") as subprocess_call,
        ):
            started = time.monotonic()
            with self.assertRaisesRegex(TimeoutError, "调用截止时间"):
                service.search_topic_news_bounded("影视传媒", max_results=2, timeout_seconds=0.05)
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.5)
        subprocess_call.assert_not_called()

    def test_bounded_topic_search_provider_receives_only_remaining_deadline(self):
        service = SearchService(
            bocha_keys=["dummy_key"],
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        first_owner = threading.Event()
        retry_owner = threading.Event()
        response = SearchResponse(
            query='"影视传媒" A股 最新消息 催化',
            results=[],
            provider="Filtered",
            success=True,
        )

        def wait_for_owner(_key, _event, *, timeout_seconds):
            self.assertGreater(timeout_seconds, 0)
            self.assertLessEqual(timeout_seconds, 0.2)
            time.sleep(0.03)
            return None

        with (
            patch.object(
                service,
                "_get_cached_or_reserve",
                side_effect=[
                    (None, False, first_owner),
                    (None, True, retry_owner),
                ],
            ),
            patch.object(service, "_wait_for_cached", side_effect=wait_for_owner),
            patch("src.search_service._call_topic_news_in_subprocess", return_value=response) as subprocess_call,
        ):
            actual = service.search_topic_news_bounded("影视传媒", max_results=2, timeout_seconds=0.2)

        self.assertIs(actual, response)
        remaining = subprocess_call.call_args.kwargs["timeout_seconds"]
        self.assertGreater(remaining, 0)
        self.assertLess(remaining, 0.2)

    def test_bounded_topic_search_timeout_terminates_and_reaps_process(self):
        with patch("src.search_service._search_topic_news_process_worker", _hang_topic_news_process_worker):
            with self.assertRaisesRegex(TimeoutError, "已终止请求进程"):
                _call_topic_news_in_subprocess(
                    constructor_kwargs={
                        "searxng_public_instances_enabled": False,
                        "news_max_age_days": 3,
                        "news_strategy_profile": "short",
                    },
                    topic="影视传媒",
                    max_results=2,
                    focus_keywords=None,
                    timeout_seconds=0.05,
                )

        active_search_children = [
            process
            for process in multiprocessing.active_children()
            if process.name == "search-topic-news"
        ]
        self.assertEqual(active_search_children, [])

    def test_bounded_topic_search_process_returns_serialized_dsa_response(self):
        response = _call_topic_news_in_subprocess(
            constructor_kwargs={
                "searxng_public_instances_enabled": False,
                "news_max_age_days": 3,
                "news_strategy_profile": "short",
            },
            topic="影视传媒",
            max_results=2,
            focus_keywords=None,
            timeout_seconds=5.0,
        )

        self.assertFalse(response.success)
        self.assertEqual(response.provider, "None")
        self.assertEqual(response.results, [])
        self.assertFalse(any(process.name == "search-topic-news" for process in multiprocessing.active_children()))

    def test_bounded_topic_search_rejects_work_when_process_capacity_is_full(self):
        slots = MagicMock()
        slots.acquire.return_value = False

        with patch("src.search_service._SEARCH_TIMEOUT_WORKER_SLOTS", slots):
            with self.assertRaisesRegex(RuntimeError, "并发已满"):
                _call_topic_news_in_subprocess(
                    constructor_kwargs={},
                    topic="影视传媒",
                    max_results=2,
                    focus_keywords=None,
                    timeout_seconds=0.5,
                )

        slots.acquire.assert_called_once_with(blocking=False)
        slots.release.assert_not_called()

    def test_bounded_topic_search_releases_capacity_when_process_start_fails(self):
        slots = MagicMock()
        slots.acquire.return_value = True
        parent_conn = MagicMock()
        child_conn = MagicMock()
        process = MagicMock()
        process.start.side_effect = OSError("spawn failed")
        context = MagicMock()
        context.Pipe.return_value = (parent_conn, child_conn)
        context.Process.return_value = process

        with (
            patch("src.search_service._SEARCH_TIMEOUT_WORKER_SLOTS", slots),
            patch("src.search_service.multiprocessing.get_context", return_value=context),
            patch("src.search_service._terminate_search_process") as terminate_process,
        ):
            with self.assertRaisesRegex(OSError, "spawn failed"):
                _call_topic_news_in_subprocess(
                    constructor_kwargs={},
                    topic="影视传媒",
                    max_results=2,
                    focus_keywords=None,
                    timeout_seconds=0.5,
                )

        process.join.assert_not_called()
        terminate_process.assert_not_called()
        parent_conn.close.assert_called_once_with()
        child_conn.close.assert_called_once_with()
        slots.release.assert_called_once_with()

    def test_bounded_topic_search_reaps_started_process_when_pipe_close_fails(self):
        slots = MagicMock()
        slots.acquire.return_value = True
        parent_conn = MagicMock()
        child_conn = MagicMock()
        child_conn.close.side_effect = [OSError("pipe close failed"), None]
        process = MagicMock()
        context = MagicMock()
        context.Pipe.return_value = (parent_conn, child_conn)
        context.Process.return_value = process

        with (
            patch("src.search_service._SEARCH_TIMEOUT_WORKER_SLOTS", slots),
            patch("src.search_service.multiprocessing.get_context", return_value=context),
            patch("src.search_service._terminate_search_process") as terminate_process,
        ):
            with self.assertRaisesRegex(OSError, "pipe close failed"):
                _call_topic_news_in_subprocess(
                    constructor_kwargs={},
                    topic="影视传媒",
                    max_results=2,
                    focus_keywords=None,
                    timeout_seconds=0.5,
                )

        process.join.assert_called_once()
        terminate_process.assert_called_once_with(process)
        parent_conn.close.assert_called_once_with()
        self.assertEqual(child_conn.close.call_count, 2)
        slots.release.assert_called_once_with()

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
