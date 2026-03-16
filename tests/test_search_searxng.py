# -*- coding: utf-8 -*-
"""
Unit tests for SearXNGSearchProvider (Fixes #550).
"""

import sys
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import SearXNGSearchProvider


class TestSearXNGSearchProvider(unittest.TestCase):
    """Tests for SearXNG search provider."""

    def _create_provider(self):
        return SearXNGSearchProvider(base_urls=["https://searx.example.org"])

    @patch("src.search_service.requests.get")
    def test_success_response_maps_fields(self, mock_get):
        """Successful JSON response maps title, url, snippet correctly."""
        fresh_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "title": "Test Article",
                    "url": "https://example.com/article",
                    "content": "Summary snippet here",
                    "publishedDate": fresh_date,
                }
            ]
        }
        mock_get.return_value = mock_resp

        provider = self._create_provider()
        resp = provider.search("AAPL stock", max_results=5, days=7)

        self.assertTrue(resp.success)
        self.assertEqual(resp.provider, "SearXNG")
        self.assertEqual(len(resp.results), 1)
        r = resp.results[0]
        self.assertEqual(r.title, "Test Article")
        self.assertEqual(r.url, "https://example.com/article")
        self.assertEqual(r.snippet, "Summary snippet here")
        expected_date = datetime.fromisoformat(fresh_date.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        self.assertEqual(r.published_date, expected_date)
        self.assertEqual(r.source, "example.com")

    @patch("src.search_service.requests.get")
    def test_uses_description_when_content_missing(self, mock_get):
        """Uses description when content is missing."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "title": "Title",
                    "url": "https://foo.com/page",
                    "description": "Desc text",
                }
            ]
        }
        mock_get.return_value = mock_resp

        provider = self._create_provider()
        resp = provider.search("query", max_results=5)

        self.assertTrue(resp.success)
        self.assertEqual(resp.results[0].snippet, "Desc text")

    @patch("src.search_service.requests.get")
    def test_403_returns_specific_error(self, mock_get):
        """403 returns error about enabling JSON in settings.yml."""
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.headers = {}
        mock_resp.text = "forbidden"
        mock_get.return_value = mock_resp

        provider = self._create_provider()
        resp = provider.search("query", max_results=5)

        self.assertFalse(resp.success)
        self.assertIn("settings.yml", resp.error_message or "")

    @patch("src.search_service.requests.get")
    def test_empty_results_success(self, mock_get):
        """Empty results array returns success with empty list."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": []}
        mock_get.return_value = mock_resp

        provider = self._create_provider()
        resp = provider.search("query", max_results=5)

        self.assertTrue(resp.success)
        self.assertEqual(resp.results, [])

    @patch("src.search_service.requests.get")
    def test_skips_item_without_url(self, mock_get):
        """Items without url are skipped."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"title": "No URL", "content": "x"},
                {"title": "Has URL", "url": "https://b.com/page", "content": "y"},
            ]
        }
        mock_get.return_value = mock_resp

        provider = self._create_provider()
        resp = provider.search("query", max_results=5)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].url, "https://b.com/page")

    @patch("src.search_service.requests.get")
    def test_results_not_list_uses_empty(self, mock_get):
        """When results is not a list, treat as empty."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": {"invalid": "dict"}}
        mock_get.return_value = mock_resp

        provider = self._create_provider()
        resp = provider.search("query", max_results=5)

        self.assertTrue(resp.success)
        self.assertEqual(resp.results, [])

    @patch("src.search_service.requests.get")
    def test_respects_max_results(self, mock_get):
        """Only returns up to max_results items."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"title": f"Item{i}", "url": f"https://x.com/{i}", "content": "x"}
                for i in range(10)
            ]
        }
        mock_get.return_value = mock_resp

        provider = self._create_provider()
        resp = provider.search("query", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 3)

    @patch("src.search_service.requests.get")
    def test_time_range_mapping(self, mock_get):
        """time_range param maps correctly for all four branches."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": []}
        mock_get.return_value = mock_resp

        provider = self._create_provider()
        cases = [
            (1, "day"),
            (7, "week"),
            (30, "month"),
            (31, "year"),
        ]
        for days, expected in cases:
            with self.subTest(days=days):
                provider.search("query", max_results=5, days=days)
                self.assertEqual(mock_get.call_args[1]["params"]["time_range"], expected)

    @patch("src.search_service.requests.get")
    def test_non_json_response_returns_failure(self, mock_get):
        """Non-JSON response body returns success=False."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("No JSON")
        mock_get.return_value = mock_resp

        provider = self._create_provider()
        resp = provider.search("query", max_results=5)

        self.assertFalse(resp.success)

    @patch("src.search_service.requests.get")
    def test_json_returns_non_dict_returns_failure(self, mock_get):
        """response.json() returning a list (not dict) returns success=False."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"results": []}]
        mock_get.return_value = mock_resp

        provider = self._create_provider()
        resp = provider.search("query", max_results=5)

        self.assertFalse(resp.success)

    @patch("src.search_service.time.sleep")
    @patch("src.search_service.requests.get")
    def test_timeout_returns_failure(self, mock_get, _mock_sleep):
        """Network timeout returns success=False with descriptive message."""
        import requests as req_module
        mock_get.side_effect = req_module.exceptions.Timeout()

        provider = self._create_provider()
        resp = provider.search("query", max_results=5)

        self.assertFalse(resp.success)
        self.assertIn("超时", resp.error_message or "")

    @patch("src.search_service.time.sleep")
    @patch("src.search_service.requests.get")
    def test_request_exception_returns_failure(self, mock_get, _mock_sleep):
        """Network error (RequestException) returns success=False."""
        import requests as req_module
        mock_get.side_effect = req_module.exceptions.ConnectionError("refused")

        provider = self._create_provider()
        resp = provider.search("query", max_results=5)

        self.assertFalse(resp.success)
        self.assertIn("网络请求失败", resp.error_message or "")

    @patch("src.search_service.time.sleep")
    @patch("src.search_service.requests.get")
    def test_transient_timeout_retries_then_succeeds(self, mock_get, _mock_sleep):
        """Transient timeout should be retried before succeeding."""
        import requests as req_module

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": []}
        mock_get.side_effect = [req_module.exceptions.Timeout(), mock_resp]

        provider = self._create_provider()
        resp = provider.search("query", max_results=5)

        self.assertTrue(resp.success)
        self.assertEqual(mock_get.call_count, 2)

    @patch("src.search_service.requests.get")
    def test_filters_before_applying_max_results(self, mock_get):
        """Valid results after skipped items should still be returned."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"title": "Missing URL", "content": "x"},
                {"title": "Valid", "url": "https://x.com/valid", "content": "ok"},
            ]
        }
        mock_get.return_value = mock_resp

        provider = self._create_provider()
        resp = provider.search("query", max_results=1)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].title, "Valid")

    @patch("src.search_service.requests.get")
    def test_non_200_preserves_response_body(self, mock_get):
        """HTTP errors should preserve useful response details."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.text = "upstream gateway failed"
        mock_get.return_value = mock_resp

        provider = self._create_provider()
        resp = provider.search("query", max_results=5)

        self.assertFalse(resp.success)
        self.assertIn("gateway failed", resp.error_message or "")


if __name__ == "__main__":
    unittest.main()
