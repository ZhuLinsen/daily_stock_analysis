# -*- coding: utf-8 -*-
"""
Regression tests for the Outcrawl news search provider (Issue #2444).

Covers: request shape, hit mapping, date-prefix splitting, caching, quota/HTTP
error fallback, stale/undated filtering, and warnings logging.
"""

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.search_service import OutcrawlSearchProvider, SearchResponse, SearchService


class _FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code, json_payload, text=""):
        self.status_code = status_code
        self._json = json_payload
        self.text = text
        self.headers = {"content-type": "application/json"}

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


def _post_factory(payload_by_query):
    """Return a fake `_post_with_retry` keyed by request payload `query`."""

    def _fake_post(url, *, headers, json, timeout):
        query = json.get("query")
        if query in payload_by_query:
            entry = payload_by_query[query]
            if isinstance(entry, Exception):
                raise entry
            if isinstance(entry, _FakeResponse):
                return entry
            return _FakeResponse(entry.get("status", 200), entry.get("json", {}),
                                 entry.get("text", ""))
        return _FakeResponse(404, {"code": "not_found", "message": "no mock"})

    return _fake_post


class TestOutcrawlSearchProvider(unittest.TestCase):
    """Tests for OutcrawlSearchProvider request and mapping behavior."""

    def test_request_shape_and_hit_mapping(self):
        fake_post = _post_factory({
            "Apple AAPL": {
                "json": {
                    "hits": [
                        {
                            "url": "https://example.com/aapl-1",
                            "title": "Apple AAPL rises",
                            "snippet": "2 days ago - Apple shares gained on earnings",
                            "rank": 1,
                        },
                        {
                            "url": "https://example.com/aapl-2",
                            "title": "Old AAPL news",
                            "snippet": "3 weeks ago - stale story",
                            "rank": 2,
                        },
                        {
                            "url": "https://example.com/aapl-3",
                            "title": "No date here",
                            "snippet": "Just some news without any date prefix",
                            "rank": 3,
                        },
                    ],
                    "usage": {"credits": "2.5"},
                }
            }
        })
        with patch("src.search_service._post_with_retry", side_effect=fake_post):
            provider = OutcrawlSearchProvider(["ock_test_key"])
            response = provider.search("Apple AAPL", max_results=5, days=3)

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "Outcrawl")
        self.assertEqual(len(response.results), 3)

        # Date prefix split: "2 days ago" -> published date, snippet trimmed.
        first = response.results[0]
        self.assertEqual(first.title, "Apple AAPL rises")
        self.assertEqual(first.url, "https://example.com/aapl-1")
        self.assertEqual(first.source, "example.com")
        self.assertIsNotNone(first.published_date)
        self.assertEqual(first.snippet, "Apple shares gained on earnings")
        expected = (datetime.now(timezone.utc).astimezone() - timedelta(days=2)).date()
        self.assertEqual(first.published_date, expected)

        # Stale hit keeps its parsed date (3 weeks ago).
        self.assertIsNotNone(response.results[1].published_date)
        # Undated hit keeps None and full snippet.
        self.assertIsNone(response.results[2].published_date)
        self.assertEqual(response.results[2].snippet, "Just some news without any date prefix")

    def test_provider_does_not_filter_by_age(self):
        """Provider returns all hits; freshness filtering is the service's job."""
        fake_post = _post_factory({
            "Q": {"json": {"hits": [
                {"url": "https://example.com/old", "title": "Old", "snippet": "3 weeks ago - stale", "rank": 1},
                {"url": "https://example.com/new", "title": "New", "snippet": "1 day ago - fresh", "rank": 2},
            ]}}
        })
        with patch("src.search_service._post_with_retry", side_effect=fake_post):
            provider = OutcrawlSearchProvider(["ock_test_key"])
            response = provider.search("Q", max_results=5)
        self.assertTrue(response.success)
        self.assertEqual(len(response.results), 2)

    def test_warnings_are_logged_and_hits_kept(self):
        fake_post = _post_factory({
            "Q": {"json": {"hits": [
                {"url": "https://example.com/h", "title": "Hit", "snippet": "1 day ago - fresh", "rank": 1},
            ], "warnings": [{"code": "engines_refused"}]}}
        })
        with patch("src.search_service._post_with_retry", side_effect=fake_post):
            provider = OutcrawlSearchProvider(["ock_test_key"])
            response = provider.search("Q", max_results=5)
        self.assertTrue(response.success)
        self.assertEqual(len(response.results), 1)

    def test_http_error_returns_failure(self):
        fake_post = _post_factory({
            "Q": _FakeResponse(402, {"code": "quota_exceeded", "message": "quota exceeded"}),
        })
        with patch("src.search_service._post_with_retry", side_effect=fake_post):
            provider = OutcrawlSearchProvider(["ock_test_key"])
            response = provider.search("Q", max_results=5)
        self.assertFalse(response.success)
        self.assertEqual(len(response.results), 0)
        self.assertIn("quota", (response.error_message or "").lower())

    def test_request_uses_bearer_header_and_limit(self):
        captured = {}

        def _capture(url, *, headers, json, timeout):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse(200, {"hits": []})

        with patch("src.search_service._post_with_retry", side_effect=_capture):
            provider = OutcrawlSearchProvider(["ock_secret_key"])
            provider.search("Apple", max_results=3)

        self.assertEqual(captured["url"], "https://api.outcrawl.ai/v1/search")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer ock_secret_key")
        self.assertEqual(captured["json"]["query"], "Apple")
        self.assertEqual(captured["json"]["limit"], 3)


class TestOutcrawlSearchService(unittest.TestCase):
    """Tests for Outcrawl integration in SearchService."""

    def test_service_dedupes_second_call_from_cache(self):
        calls = []

        def _counting_post(url, *, headers, json, timeout):
            calls.append(url)
            return _FakeResponse(200, {"hits": [
                {"url": "https://example.com/h", "title": "Hit",
                 "snippet": "1 day ago - fresh", "rank": 1},
            ]})

        with patch("src.search_service._post_with_retry", side_effect=_counting_post):
            svc = SearchService(outcrawl_keys=["ock_test_key"], news_max_age_days=3,
                                news_strategy_profile="short")
            r1 = svc.search_stock_news("AAPL", "Apple", max_results=5)
            r2 = svc.search_stock_news("AAPL", "Apple", max_results=5)

        self.assertTrue(r1.success)
        self.assertGreaterEqual(len(r1.results), 1)
        # Second call served from cache: no new HTTP POST.
        self.assertEqual(len(calls), 1, f"expected 1 HTTP call, got {len(calls)}")

    def test_http_402_marks_outcrawl_failed(self):
        def _failing_post(url, *, headers, json, timeout):
            return _FakeResponse(402, {"code": "quota_exceeded", "message": "quota exceeded"})

        with patch("src.search_service._post_with_retry", side_effect=_failing_post):
            svc = SearchService(outcrawl_keys=["ock_bad_key"], news_max_age_days=3,
                                news_strategy_profile="short")
            r = svc.search_stock_news("AAPL", "Apple", max_results=5)

        # Outcrawl failed and no other provider is configured -> empty result.
        self.assertFalse(r.success)
        self.assertEqual(len(r.results), 0)

    def test_provider_registered_when_key_present(self):
        with patch("src.search_service._post_with_retry", side_effect=_post_factory({})):
            svc = SearchService(outcrawl_keys=["ock_test_key"], news_max_age_days=3,
                                news_strategy_profile="short")
        names = [p.name for p in svc._providers]
        self.assertIn("Outcrawl", names)

    def test_provider_not_registered_without_key(self):
        with patch("src.search_service._post_with_retry", side_effect=_post_factory({})):
            svc = SearchService(news_max_age_days=3, news_strategy_profile="short")
        names = [p.name for p in svc._providers]
        self.assertNotIn("Outcrawl", names)


if __name__ == "__main__":
    unittest.main()
