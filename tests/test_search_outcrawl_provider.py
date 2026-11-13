# -*- coding: utf-8 -*-
"""
Tests for the Outcrawl search provider: request shape, hit mapping and
snippet date prefixes feeding the news freshness filter.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import OutcrawlSearchProvider, SearchService, SearXNGSearchProvider


def _response(status_code=200, payload=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    response.text = str(payload)
    return response


class TestOutcrawlSearchProvider(unittest.TestCase):
    """Tests for Outcrawl provider request and mapping behavior."""

    @patch("src.search_service._post_with_retry")
    def test_search_posts_query_and_maps_hits(self, mock_post) -> None:
        mock_post.return_value = _response(
            payload={
                "hits": [
                    {
                        "url": "https://www.example.com/nvda-earnings",
                        "title": "Nvidia earnings preview",
                        "snippet": "2 days ago - Nvidia faces two competing forces.",
                        "rank": 1,
                    },
                    {
                        "url": "https://news.example.org/nvda",
                        "title": "Nvidia guidance",
                        "snippet": "Oct 28, 2026 - Guidance raised for the quarter.",
                        "rank": 2,
                    },
                    {
                        "url": "https://quotes.example.net/NVDA",
                        "title": "NVDA quote",
                        "snippet": "Get the latest news on NVIDIA stock.",
                        "rank": 3,
                    },
                ],
                "usage": {"credits": "1.5"},
            }
        )

        resp = OutcrawlSearchProvider(["ock_test"]).search("NVDA latest news", max_results=3, days=3)

        self.assertTrue(resp.success)
        self.assertEqual(resp.provider, "Outcrawl")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.outcrawl.ai/v1/search")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer ock_test")
        self.assertEqual(kwargs["json"], {"query": "NVDA latest news", "limit": 3})

        self.assertEqual(
            [(r.title, r.url, r.source, r.snippet, r.published_date) for r in resp.results],
            [
                (
                    "Nvidia earnings preview",
                    "https://www.example.com/nvda-earnings",
                    "example.com",
                    "Nvidia faces two competing forces.",
                    "2 days ago",
                ),
                (
                    "Nvidia guidance",
                    "https://news.example.org/nvda",
                    "news.example.org",
                    "Guidance raised for the quarter.",
                    "Oct 28, 2026",
                ),
                (
                    "NVDA quote",
                    "https://quotes.example.net/NVDA",
                    "quotes.example.net",
                    "Get the latest news on NVIDIA stock.",
                    None,
                ),
            ],
        )

    def test_snippet_date_prefixes_normalize_for_freshness_filter(self) -> None:
        relative, _ = OutcrawlSearchProvider._split_snippet_date("2 days ago - text")
        absolute, _ = OutcrawlSearchProvider._split_snippet_date("Oct 28, 2026 - text")

        self.assertEqual(
            SearchService._normalize_news_publish_date(relative),
            (datetime.now() - timedelta(days=2)).date(),
        )
        self.assertEqual(
            SearchService._normalize_news_publish_date(absolute).isoformat(),
            "2026-10-28",
        )

    @patch("src.search_service._post_with_retry")
    def test_api_error_returns_failed_response(self, mock_post) -> None:
        mock_post.return_value = _response(
            status_code=401,
            payload={"code": "invalid_key", "message": "The API key is not valid."},
        )

        resp = OutcrawlSearchProvider(["ock_test"]).search("query", max_results=5)

        self.assertFalse(resp.success)
        self.assertEqual(resp.results, [])
        self.assertEqual(resp.error_message, "The API key is not valid.")

    def test_service_registers_provider_from_keys(self) -> None:
        service = SearchService(outcrawl_keys=["ock_test"])

        self.assertEqual([p.name for p in service._providers], ["Outcrawl"])


class TestOutcrawlThroughSearchService(unittest.TestCase):
    """The real Outcrawl provider through search_stock_news: news filter, cache and fallback."""

    FRESH_HIT = {
        "url": "https://finance.example.com/apple-aapl-earnings",
        "title": "Apple AAPL earnings preview",
        "snippet": "1 day ago - Apple (AAPL) reports quarterly results this week.",
        "rank": 1,
    }
    STALE_HIT = {
        "url": "https://finance.example.com/apple-aapl-suppliers",
        "title": "Apple AAPL supplier update",
        "snippet": "2 weeks ago - Apple (AAPL) suppliers raised memory prices.",
        "rank": 2,
    }
    UNDATED_HIT = {
        "url": "https://quotes.example.net/AAPL",
        "title": "Apple AAPL stock quote",
        "snippet": "Get the latest Apple (AAPL) stock news.",
        "rank": 3,
    }

    def setUp(self) -> None:
        SearXNGSearchProvider.reset_public_instance_cache()

    def _service(self, **kwargs) -> SearchService:
        return SearchService(
            outcrawl_keys=["ock_test"],
            news_max_age_days=3,
            news_strategy_profile="short",
            **kwargs,
        )

    @staticmethod
    def _searxng_payload() -> dict:
        return {
            "results": [
                {
                    "title": "Apple AAPL shares rise",
                    "url": "https://searx-news.example.org/apple-aapl",
                    "content": "Apple (AAPL) shares rose after the report.",
                    "publishedDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            ]
        }

    @patch("src.search_service._post_with_retry")
    def test_search_stock_news_filters_by_snippet_date_and_caches(self, mock_post) -> None:
        mock_post.return_value = _response(
            payload={"hits": [self.FRESH_HIT, self.STALE_HIT, self.UNDATED_HIT]}
        )
        service = self._service()

        first = service.search_stock_news("AAPL", "Apple", max_results=3)
        second = service.search_stock_news("AAPL", "Apple", max_results=3)

        self.assertTrue(first.success)
        self.assertEqual(first.provider, "Outcrawl")
        self.assertEqual([r.url for r in first.results], [self.FRESH_HIT["url"]])
        self.assertEqual(
            first.results[0].published_date,
            (datetime.now() - timedelta(days=1)).date().isoformat(),
        )
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual([r.url for r in second.results], [self.FRESH_HIT["url"]])

    @patch("src.search_service._get_with_retry")
    @patch("src.search_service._post_with_retry")
    def test_search_stock_news_falls_back_when_outcrawl_fails(self, mock_post, mock_get) -> None:
        mock_post.return_value = _response(
            status_code=402,
            payload={"code": "quota_exceeded", "message": "Out of credits."},
        )
        mock_get.return_value = _response(payload=self._searxng_payload())
        service = self._service(searxng_base_urls=["https://searx.example.org"])

        resp = service.search_stock_news("AAPL", "Apple", max_results=3)

        self.assertEqual([p.name for p in service._providers], ["Outcrawl", "SearXNG"])
        self.assertEqual(mock_post.call_count, 1)
        self.assertTrue(resp.success)
        self.assertEqual(resp.provider, "SearXNG")
        self.assertEqual([r.url for r in resp.results], ["https://searx-news.example.org/apple-aapl"])

    @patch("src.search_service._get_with_retry")
    @patch("src.search_service._post_with_retry")
    def test_search_stock_news_falls_back_when_outcrawl_hits_are_filtered_out(
        self, mock_post, mock_get
    ) -> None:
        mock_post.return_value = _response(payload={"hits": [self.STALE_HIT, self.UNDATED_HIT]})
        mock_get.return_value = _response(payload=self._searxng_payload())
        service = self._service(searxng_base_urls=["https://searx.example.org"])

        resp = service.search_stock_news("AAPL", "Apple", max_results=3)

        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(resp.provider, "SearXNG")
        self.assertEqual([r.url for r in resp.results], ["https://searx-news.example.org/apple-aapl"])

    @patch("src.search_service._post_with_retry")
    def test_response_warnings_are_logged_and_hits_kept(self, mock_post) -> None:
        mock_post.return_value = _response(
            payload={"hits": [self.FRESH_HIT], "warnings": [{"code": "engines_refused"}]}
        )

        with self.assertLogs("src.search_service", level="WARNING") as logs:
            resp = OutcrawlSearchProvider(["ock_test"]).search("Apple AAPL news", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertTrue(any("engines_refused" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
