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
    """Fake for the keyed `firecrawl.Firecrawl` client."""

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


def _fake_firecrawl_module() -> ModuleType:
    module = ModuleType("firecrawl")
    module.Firecrawl = _FakeFirecrawlClient
    return module


class TestFirecrawlSearchProvider(unittest.TestCase):
    """Provider-specific request and mapping behavior."""

    def _patch_firecrawl(self, payload):
        _FakeFirecrawlClient.reset()
        _FakeFirecrawlClient.response_payload = payload
        return patch.dict(sys.modules, {"firecrawl": _fake_firecrawl_module()})

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

    def test_scraped_document_reads_url_title_date_from_metadata(self) -> None:
        # With scrape_options set, the SDK returns Document objects whose url/title/date
        # live under .metadata (not top-level). Mapping must fall back to metadata.
        provider = FirecrawlSearchProvider(["dummy_key"])

        with self._patch_firecrawl(
            {
                "news": [
                    {
                        "summary": "Full article body from inline scrape",
                        "metadata": {
                            "title": "Meta Title",
                            "sourceURL": "https://news.example.com/article",
                            "published_time": "2026-03-20T09:30:00Z",
                        },
                    }
                ]
            }
        ):
            resp = provider.search("BABA latest news", max_results=2, days=3, topic="news")

        self.assertTrue(resp.success)
        r = resp.results[0]
        self.assertEqual(r.title, "Meta Title")
        self.assertEqual(r.url, "https://news.example.com/article")
        self.assertEqual(r.source, "news.example.com")
        self.assertEqual(r.published_date, "2026-03-20T09:30:00Z")
        self.assertEqual(r.snippet, "Full article body from inline scrape")

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

        with self._patch_firecrawl({"web": [{"title": "A", "url": "https://a.com", "summary": long_text}]}):
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

    # --- SearchService registration -------------------------------------

    def test_service_registers_firecrawl_at_top_priority(self) -> None:
        with self._patch_firecrawl({"web": []}):
            service = SearchService(
                firecrawl_keys=["fc-key"],
                tavily_keys=["tvly-x"],
                searxng_public_instances_enabled=False,
            )
        fc = [p for p in service._providers if isinstance(p, FirecrawlSearchProvider)]
        self.assertEqual(len(fc), 1)
        self.assertEqual(service._providers.index(fc[0]), 0)  # registered first

    def test_no_firecrawl_provider_without_key(self) -> None:
        with self._patch_firecrawl({"web": []}):
            service = SearchService(
                firecrawl_keys=[],
                tavily_keys=["tvly-x"],
                searxng_public_instances_enabled=False,
            )
        self.assertFalse(any(isinstance(p, FirecrawlSearchProvider) for p in service._providers))


def _firecrawl_sdk_available() -> bool:
    try:
        import firecrawl.v2.types  # noqa: F401

        return True
    except Exception:
        return False


@unittest.skipUnless(_firecrawl_sdk_available(), "firecrawl-py not installed")
class TestFirecrawlRealSdkShape(unittest.TestCase):
    """Validate the result mapping against the REAL firecrawl-py SDK models.

    The other tests fake the SDK, so they cannot prove the actual response
    shape. This one builds genuine `firecrawl.v2.types.Document` /
    `DocumentMetadata` objects (the shape returned when scrape_options is set)
    and runs them through the provider mapping — no network, no API key.
    """

    def test_mapping_reads_metadata_from_real_document(self) -> None:
        from firecrawl.v2.types import Document, DocumentMetadata

        doc = Document(
            summary="Real article body",
            metadata=DocumentMetadata(
                title="Real Title",
                url="https://news.example.com/real",
                published_time="2026-03-20T09:30:00Z",
            ),
        )

        class _RealShapeResponse:
            news = [doc]
            web = []

        class _RealShapeClient:
            def __init__(self, *a, **k):
                pass

            def search(self, **k):
                return _RealShapeResponse()

        mod = ModuleType("firecrawl")
        mod.Firecrawl = _RealShapeClient
        provider = FirecrawlSearchProvider(["dummy_key"])
        with patch.dict(sys.modules, {"firecrawl": mod}):
            resp = provider.search("q", max_results=2, days=3, topic="news")

        self.assertTrue(resp.success)
        r = resp.results[0]
        self.assertEqual(r.title, "Real Title")
        self.assertEqual(r.url, "https://news.example.com/real")
        self.assertEqual(r.source, "news.example.com")
        self.assertEqual(r.published_date, "2026-03-20T09:30:00Z")
        self.assertEqual(r.snippet, "Real article body")


if __name__ == "__main__":
    unittest.main()
