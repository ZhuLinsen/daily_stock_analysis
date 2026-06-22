# -*- coding: utf-8 -*-
"""
Tests for the Firecrawl search provider: request shaping (news source + tbs
recency window), inline-content extraction, and SearchService integration.
"""

import sys
import unittest
from datetime import datetime, timezone
from types import ModuleType
from unittest.mock import MagicMock, patch

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import FirecrawlSearchProvider, SearchService


class _FakeFirecrawlClient:
    """Fake for the top-level keyed `firecrawl.Firecrawl` client."""
    response_payload = {"web": []}
    init_api_keys = []
    search_calls = []

    def __init__(self, api_key=None, **_kwargs):
        type(self).init_api_keys.append(api_key)

    def search(self, **kwargs):
        type(self).search_calls.append(kwargs)
        return type(self).response_payload

    @classmethod
    def reset(cls) -> None:
        cls.response_payload = {"web": []}
        cls.init_api_keys = []
        cls.search_calls = []


class _FakeFirecrawlV2Client:
    """Fake for the keyless `firecrawl.v2.FirecrawlClient` (constructed with NO key)."""
    response_payload = {"web": []}
    init_count = 0
    init_kwargs = []
    search_calls = []

    def __init__(self, *args, **kwargs):
        type(self).init_count += 1
        type(self).init_kwargs.append({"args": args, "kwargs": kwargs})

    def search(self, **kwargs):
        type(self).search_calls.append(kwargs)
        return type(self).response_payload

    @classmethod
    def reset(cls) -> None:
        cls.response_payload = {"web": []}
        cls.init_count = 0
        cls.init_kwargs = []
        cls.search_calls = []


def _fake_firecrawl_module() -> ModuleType:
    module = ModuleType("firecrawl")
    module.Firecrawl = _FakeFirecrawlClient
    return module


def _fake_firecrawl_v2_module() -> ModuleType:
    module = ModuleType("firecrawl.v2")
    module.FirecrawlClient = _FakeFirecrawlV2Client
    return module


class TestFirecrawlSearchProvider(unittest.TestCase):
    """Provider-specific request and mapping behavior."""

    def _patch_firecrawl(self, payload, *, v2_payload=None):
        _FakeFirecrawlClient.reset()
        _FakeFirecrawlV2Client.reset()
        _FakeFirecrawlClient.response_payload = payload
        _FakeFirecrawlV2Client.response_payload = v2_payload if v2_payload is not None else payload
        return patch.dict(
            sys.modules,
            {
                "firecrawl": _fake_firecrawl_module(),
                "firecrawl.v2": _fake_firecrawl_v2_module(),
            },
        )

    def test_days_to_tbs_mapping(self) -> None:
        self.assertEqual(FirecrawlSearchProvider._days_to_tbs(1), "qdr:d")
        self.assertEqual(FirecrawlSearchProvider._days_to_tbs(3), "qdr:w")
        self.assertEqual(FirecrawlSearchProvider._days_to_tbs(7), "qdr:w")
        self.assertEqual(FirecrawlSearchProvider._days_to_tbs(30), "qdr:m")
        self.assertEqual(FirecrawlSearchProvider._days_to_tbs(200), "qdr:y")
        self.assertIsNone(FirecrawlSearchProvider._days_to_tbs(0))

    def test_news_topic_sets_news_source_and_tbs(self) -> None:
        provider = FirecrawlSearchProvider(["dummy_key"])

        with self._patch_firecrawl(
            {
                "news": [
                    {
                        "title": "Alibaba earnings beat",
                        "url": "https://example.com/alibaba-earnings",
                        "summary": "Full article summary text",
                        "date": "2026-03-20T09:30:00Z",
                    }
                ]
            }
        ):
            resp = provider.search("BABA latest news", max_results=5, days=3, topic="news")

        self.assertTrue(resp.success)
        self.assertEqual(_FakeFirecrawlClient.init_api_keys, ["dummy_key"])
        self.assertEqual(len(_FakeFirecrawlClient.search_calls), 1)
        call = _FakeFirecrawlClient.search_calls[0]
        self.assertEqual(call["sources"], [{"type": "news"}])
        self.assertEqual(call["tbs"], "qdr:w")
        self.assertEqual(call["limit"], 5)
        self.assertEqual(call["scrape_options"], {"formats": ["summary"]})
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].snippet, "Full article summary text")
        self.assertEqual(resp.results[0].url, "https://example.com/alibaba-earnings")
        self.assertEqual(resp.results[0].source, "example.com")
        self.assertEqual(resp.results[0].published_date, "2026-03-20T09:30:00Z")

    def test_non_news_search_does_not_set_news_source(self) -> None:
        provider = FirecrawlSearchProvider(["dummy_key"])

        with self._patch_firecrawl(
            {
                "web": [
                    {
                        "title": "Alibaba price action",
                        "url": "https://example.com/alibaba-price",
                        "description": "General result",
                    }
                ]
            }
        ):
            resp = provider.search("BABA stock price", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(_FakeFirecrawlClient.search_calls), 1)
        self.assertNotIn("sources", _FakeFirecrawlClient.search_calls[0])
        self.assertEqual(resp.results[0].snippet, "General result")

    def test_content_prefers_summary_then_markdown_then_description(self) -> None:
        provider = FirecrawlSearchProvider(["dummy_key"])

        with self._patch_firecrawl(
            {
                "web": [
                    {"title": "A", "url": "https://a.com", "markdown": "md", "description": "desc"},
                    {"title": "B", "url": "https://b.com", "description": "only desc"},
                ]
            }
        ):
            resp = provider.search("anything", max_results=5)

        self.assertEqual(resp.results[0].snippet, "md")
        self.assertEqual(resp.results[1].snippet, "only desc")

    def test_content_is_truncated_to_limit(self) -> None:
        provider = FirecrawlSearchProvider(["dummy_key"])
        long_text = "x" * 5000

        with self._patch_firecrawl(
            {"web": [{"title": "A", "url": "https://a.com", "summary": long_text}]}
        ):
            resp = provider.search("anything", max_results=1)

        self.assertEqual(len(resp.results[0].snippet), FirecrawlSearchProvider._CONTENT_CHAR_LIMIT)

    def test_missing_dependency_returns_failure(self) -> None:
        provider = FirecrawlSearchProvider(["dummy_key"])
        # Ensure the firecrawl import fails
        with patch.dict(sys.modules, {"firecrawl": None}):
            resp = provider.search("anything", max_results=1)
        self.assertFalse(resp.success)
        self.assertIn("firecrawl-py", resp.error_message)

    def test_search_stock_news_uses_firecrawl_news_topic(self) -> None:
        published_dt = datetime.now(timezone.utc).replace(microsecond=0)
        published_text = published_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        expected_date = published_dt.astimezone().date().isoformat()

        with self._patch_firecrawl(
            {
                "news": [
                    {
                        "title": "Fresh Alibaba coverage",
                        "url": "https://example.com/fresh-article",
                        "summary": "Recent coverage body",
                        "date": published_text,
                    }
                ]
            }
        ):
            service = SearchService(
                firecrawl_keys=["dummy_key"],
                searxng_public_instances_enabled=False,
                news_max_age_days=3,
                news_strategy_profile="short",
            )
            resp = service.search_stock_news("BABA", "阿里巴巴", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].published_date, expected_date)
        self.assertEqual(_FakeFirecrawlClient.search_calls[0]["sources"], [{"type": "news"}])

    # --- Keyless mode ---------------------------------------------------

    def test_keyless_provider_is_available_without_keys(self) -> None:
        self.assertFalse(FirecrawlSearchProvider().is_available)
        self.assertTrue(FirecrawlSearchProvider(keyless=True).is_available)
        self.assertTrue(FirecrawlSearchProvider(["k"]).is_available)

    def test_keyless_search_uses_v2_client_without_key(self) -> None:
        provider = FirecrawlSearchProvider(keyless=True)

        with self._patch_firecrawl(
            {"news": [{"title": "Keyless hit", "url": "https://ex.com/x", "summary": "body"}]}
        ):
            resp = provider.search("BABA news", max_results=2, days=3, topic="news")

        # v2 keyless client used; top-level keyed Firecrawl never constructed
        self.assertEqual(_FakeFirecrawlV2Client.init_count, 1)
        self.assertEqual(_FakeFirecrawlV2Client.init_kwargs[0], {"args": (), "kwargs": {}})
        self.assertEqual(_FakeFirecrawlClient.init_api_keys, [])
        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(_FakeFirecrawlV2Client.search_calls[0]["sources"], [{"type": "news"}])
        self.assertEqual(_FakeFirecrawlV2Client.search_calls[0]["tbs"], "qdr:w")

    def test_keyed_search_does_not_construct_v2_keyless_client(self) -> None:
        provider = FirecrawlSearchProvider(["fc-key"])

        with self._patch_firecrawl(
            {"web": [{"title": "Keyed", "url": "https://ex.com/y", "summary": "body"}]}
        ):
            resp = provider.search("BABA price", max_results=2)

        self.assertTrue(resp.success)
        self.assertEqual(_FakeFirecrawlClient.init_api_keys, ["fc-key"])
        self.assertEqual(_FakeFirecrawlV2Client.init_count, 0)

    def test_keyless_ip_block_surfaces_friendly_error(self) -> None:
        provider = FirecrawlSearchProvider(keyless=True)

        class _IPBlockedClient(_FakeFirecrawlV2Client):
            def search(self, **kwargs):
                raise RuntimeError(
                    "Website Not Supported: your IP address looks suspicious, "
                    "so Firecrawl can't be used without an API key from here."
                )

        mod = ModuleType("firecrawl.v2")
        mod.FirecrawlClient = _IPBlockedClient
        with patch.dict(sys.modules, {"firecrawl.v2": mod}):
            resp = provider.search("anything", max_results=1)

        self.assertFalse(resp.success)
        self.assertIn("Keyless 模式当前 IP 不受信任", resp.error_message)

    def test_service_registers_keyless_fallback_at_low_priority(self) -> None:
        with self._patch_firecrawl({"web": []}):
            service = SearchService(
                firecrawl_keys=[],
                firecrawl_keyless_enabled=True,
                tavily_keys=["tvly-x"],
                searxng_public_instances_enabled=False,
            )
        fc = [p for p in service._providers if isinstance(p, FirecrawlSearchProvider)]
        self.assertEqual(len(fc), 1)
        self.assertTrue(fc[0]._keyless)
        # keyless Firecrawl is lowest priority (after the configured Tavily provider)
        self.assertGreater(
            service._providers.index(fc[0]),
            service._providers.index(next(p for p in service._providers if p.name == "Tavily")),
        )

    def test_service_keyless_disabled_registers_nothing(self) -> None:
        with self._patch_firecrawl({"web": []}):
            service = SearchService(
                firecrawl_keys=[],
                firecrawl_keyless_enabled=False,
                tavily_keys=["tvly-x"],
                searxng_public_instances_enabled=False,
            )
        self.assertFalse(any(isinstance(p, FirecrawlSearchProvider) for p in service._providers))

    def test_service_with_key_uses_keyed_not_keyless(self) -> None:
        with self._patch_firecrawl({"web": []}):
            service = SearchService(
                firecrawl_keys=["fc-key"],
                firecrawl_keyless_enabled=True,
                searxng_public_instances_enabled=False,
            )
        fc = [p for p in service._providers if isinstance(p, FirecrawlSearchProvider)]
        self.assertEqual(len(fc), 1)
        self.assertFalse(fc[0]._keyless)
        # keyed Firecrawl is top priority
        self.assertEqual(service._providers.index(fc[0]), 0)


if __name__ == "__main__":
    unittest.main()
