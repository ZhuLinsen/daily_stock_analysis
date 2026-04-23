# -*- coding: utf-8 -*-
"""
Unit tests for SearXNG search provider public-instance rotation and failover.
"""

import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import SearchService, SearXNGSearchProvider


class TestSearXNGSearchProvider(unittest.TestCase):
    """Tests for SearXNG search provider."""

    def setUp(self) -> None:
        SearXNGSearchProvider.reset_public_instance_cache()
        # Clear penalized-instance state if the provider implements it.
        if hasattr(SearXNGSearchProvider, "_penalized_instances"):
            SearXNGSearchProvider._penalized_instances.clear()

    def _create_provider(
        self,
        base_urls=None,
        *,
        use_public_instances: bool = False,
    ) -> SearXNGSearchProvider:
        return SearXNGSearchProvider(
            base_urls=base_urls or [],
            use_public_instances=use_public_instances,
        )

    @staticmethod
    def _response(
        *,
        status_code: int = 200,
        json_payload=None,
        text: str = "",
        headers=None,
        json_side_effect=None,
    ) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        resp.headers = headers or {"content-type": "application/json"}
        if json_side_effect is not None:
            resp.json.side_effect = json_side_effect
        else:
            resp.json.return_value = {} if json_payload is None else json_payload
        return resp

    @staticmethod
    def _public_feed(urls):
        instances = {}
        for idx, url in enumerate(urls):
            instances[url] = {
                "network_type": "normal",
                "http": {"status_code": 200},
                "timing": {
                    "search": {
                        "success_percentage": 100.0 - idx,
                        "all": {"mean": 0.3 + idx * 0.1},
                    }
                },
            }
        return {"instances": instances}

    @patch("src.search_service._get_with_retry")
    def test_success_response_maps_fields_for_self_hosted_instance(self, mock_get):
        fresh_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        mock_get.return_value = self._response(
            json_payload={
                "results": [
                    {
                        "title": "Test Article",
                        "url": "https://example.com/article",
                        "content": "Summary snippet here",
                        "publishedDate": fresh_date,
                    }
                ]
            }
        )

        provider = self._create_provider(["https://searx.example.org"])
        resp = provider.search("AAPL stock", max_results=5, days=7)

        self.assertTrue(resp.success)
        self.assertEqual(resp.provider, "SearXNG")
        self.assertEqual(len(resp.results), 1)
        result = resp.results[0]
        self.assertEqual(result.title, "Test Article")
        self.assertEqual(result.url, "https://example.com/article")
        self.assertEqual(result.snippet, "Summary snippet here")
        expected_date = datetime.fromisoformat(fresh_date.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        self.assertEqual(result.published_date, expected_date)
        self.assertEqual(result.source, "example.com")

    @patch("src.search_service._get_with_retry")
    def test_self_hosted_uses_description_when_content_missing(self, mock_get):
        mock_get.return_value = self._response(
            json_payload={
                "results": [
                    {
                        "title": "Title",
                        "url": "https://foo.com/page",
                        "description": "Desc text",
                    }
                ]
            }
        )

        provider = self._create_provider(["https://searx.example.org"])
        resp = provider.search("query", max_results=5)

        self.assertTrue(resp.success)
        self.assertEqual(resp.results[0].snippet, "Desc text")

    @patch("src.search_service._get_with_retry")
    def test_self_hosted_403_returns_specific_error(self, mock_get):
        mock_get.return_value = self._response(
            status_code=403,
            text="forbidden",
            headers={"content-type": "text/plain"},
        )

        provider = self._create_provider(["https://searx.example.org"])
        resp = provider.search("query", max_results=5)

        self.assertFalse(resp.success)
        self.assertIn("settings.yml", resp.error_message or "")

    @patch("src.search_service._get_with_retry")
    def test_self_hosted_empty_results_success(self, mock_get):
        mock_get.return_value = self._response(json_payload={"results": []})

        provider = self._create_provider(["https://searx.example.org"])
        resp = provider.search("query", max_results=5)

        self.assertTrue(resp.success)
        self.assertEqual(resp.results, [])

    @patch("src.search_service._get_with_retry")
    def test_filters_before_applying_max_results(self, mock_get):
        mock_get.return_value = self._response(
            json_payload={
                "results": [
                    {"title": "Missing URL", "content": "x"},
                    {"title": "Valid", "url": "https://x.com/valid", "content": "ok"},
                ]
            }
        )

        provider = self._create_provider(["https://searx.example.org"])
        resp = provider.search("query", max_results=1)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].title, "Valid")

    @patch("src.search_service._get_with_retry")
    def test_time_range_mapping(self, mock_get):
        mock_get.return_value = self._response(json_payload={"results": []})
        provider = self._create_provider(["https://searx.example.org"])

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

    @patch("src.search_service._get_with_retry")
    def test_non_json_response_returns_failure(self, mock_get):
        mock_get.return_value = self._response(json_side_effect=ValueError("No JSON"))

        provider = self._create_provider(["https://searx.example.org"])
        resp = provider.search("query", max_results=5)

        self.assertFalse(resp.success)
        self.assertIn("JSON", resp.error_message or "")

    @patch("src.search_service._get_with_retry")
    def test_json_returns_non_dict_returns_failure(self, mock_get):
        mock_get.return_value = self._response(json_payload=[{"results": []}])

        provider = self._create_provider(["https://searx.example.org"])
        resp = provider.search("query", max_results=5)

        self.assertFalse(resp.success)
        self.assertIn("格式无效", resp.error_message or "")

    @patch("src.search_service._get_with_retry")
    def test_self_hosted_failover_tries_next_instance_on_timeout(self, mock_get):
        import requests as req_module

        mock_get.side_effect = [
            req_module.exceptions.Timeout(),
            self._response(json_payload={"results": [{"title": "OK", "url": "https://ok.example", "content": "done"}]}),
        ]

        provider = self._create_provider(
            ["https://searx-a.example.org", "https://searx-b.example.org"]
        )
        resp = provider.search("query", max_results=5)

        self.assertTrue(resp.success)
        self.assertEqual(mock_get.call_count, 2)
        self.assertIn("https://searx-a.example.org/search", mock_get.call_args_list[0][0][0])
        self.assertIn("https://searx-b.example.org/search", mock_get.call_args_list[1][0][0])

    @patch("src.search_service._get_with_retry")
    def test_self_hosted_rotation_advances_start_instance(self, mock_get):
        mock_get.return_value = self._response(json_payload={"results": []})
        provider = self._create_provider(
            [
                "https://searx-a.example.org",
                "https://searx-b.example.org",
                "https://searx-c.example.org",
            ]
        )

        provider.search("first", max_results=5)
        provider.search("second", max_results=5)

        self.assertEqual(mock_get.call_count, 2)
        self.assertIn("https://searx-a.example.org/search", mock_get.call_args_list[0][0][0])
        self.assertIn("https://searx-b.example.org/search", mock_get.call_args_list[1][0][0])

    def test_public_instance_extraction_filters_and_sorts(self):
        payload = {
            "instances": {
                "https://slow.example/": {
                    "network_type": "normal",
                    "http": {"status_code": 200},
                    "timing": {"search": {"success_percentage": 95.0, "all": {"mean": 1.1}}},
                },
                "https://fast.example/": {
                    "network_type": "normal",
                    "http": {"status_code": 200},
                    "timing": {"search": {"success_percentage": 95.0, "all": {"median": 0.4}}},
                },
                "https://best.example/": {
                    "network_type": "normal",
                    "http": {"status_code": 200},
                    "timing": {"search": {"success_percentage": 100.0, "all": {"mean": 0.8}}},
                },
                "https://zero.example/": {
                    "network_type": "normal",
                    "http": {"status_code": 200},
                    "timing": {"search": {"success_percentage": 0.0, "all": {"mean": 0.1}}},
                },
                "https://tor.example/": {
                    "network_type": "tor",
                    "http": {"status_code": 200},
                    "timing": {"search": {"success_percentage": 100.0, "all": {"mean": 0.1}}},
                },
            }
        }

        urls = SearXNGSearchProvider._extract_public_instances(payload)
        self.assertEqual(
            urls,
            [
                "https://best.example",
                "https://fast.example",
                "https://slow.example",
            ],
        )

    @patch("src.search_service.requests.get")
    def test_public_mode_lazily_fetches_and_caches_instance_feed(self, mock_get):
        feed_resp = self._response(json_payload=self._public_feed(["https://public-1.example/"]))
        search_resp = self._response(json_payload={"results": []})
        mock_get.side_effect = [feed_resp, search_resp, search_resp]

        provider = self._create_provider(use_public_instances=True)
        first = provider.search("first", max_results=5)
        second = provider.search("second", max_results=5)

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_get.call_args_list[0][0][0], SearXNGSearchProvider.PUBLIC_INSTANCES_URL)
        self.assertIn("https://public-1.example/search", mock_get.call_args_list[1][0][0])
        self.assertIn("https://public-1.example/search", mock_get.call_args_list[2][0][0])

    @patch("src.search_service._get_with_retry")
    @patch("src.search_service.requests.get")
    def test_public_mode_uses_requests_without_tenacity_retry(self, mock_get, mock_retry_get):
        mock_get.side_effect = [
            self._response(json_payload=self._public_feed(["https://public-1.example/"])),
            self._response(json_payload={"results": []}),
        ]

        provider = self._create_provider(use_public_instances=True)
        resp = provider.search("query", max_results=5)

        self.assertTrue(resp.success)
        mock_retry_get.assert_not_called()

    @patch("src.search_service.requests.get")
    def test_public_mode_limits_failover_to_max_attempts_instances(self, mock_get):
        feed_urls = [
            f"https://public-{i}.example/"
            for i in range(1, SearXNGSearchProvider.PUBLIC_INSTANCES_MAX_ATTEMPTS + 2)
        ]
        max_attempts = SearXNGSearchProvider.PUBLIC_INSTANCES_MAX_ATTEMPTS
        mock_get.side_effect = [
            self._response(json_payload=self._public_feed(feed_urls)),
        ] + [
            self._response(status_code=500, text=f"bad-{i}", headers={"content-type": "text/plain"})
            for i in range(1, max_attempts + 1)
        ]

        provider = self._create_provider(use_public_instances=True)
        resp = provider.search("query", max_results=5)

        self.assertFalse(resp.success)
        self.assertEqual(mock_get.call_count, 1 + max_attempts)
        last_search_url = mock_get.call_args_list[-1][0][0]
        self.assertIn(f"https://public-{max_attempts}.example/search", last_search_url)

    @patch("src.search_service.requests.get")
    def test_public_mode_rotates_start_instance_across_requests(self, mock_get):
        feed_urls = [
            "https://public-1.example/",
            "https://public-2.example/",
            "https://public-3.example/",
        ]
        mock_get.side_effect = [
            self._response(json_payload=self._public_feed(feed_urls)),
            self._response(json_payload={"results": []}),
            self._response(json_payload={"results": []}),
        ]

        provider = self._create_provider(use_public_instances=True)
        provider.search("first", max_results=5)
        provider.search("second", max_results=5)

        self.assertEqual(mock_get.call_count, 3)
        self.assertIn("https://public-1.example/search", mock_get.call_args_list[1][0][0])
        self.assertIn("https://public-2.example/search", mock_get.call_args_list[2][0][0])

    @patch("src.search_service.requests.get")
    def test_public_mode_returns_failure_when_feed_unavailable(self, mock_get):
        import requests as req_module

        mock_get.side_effect = req_module.exceptions.ConnectionError("dns failed")

        provider = self._create_provider(use_public_instances=True)
        resp = provider.search("query", max_results=5)

        self.assertFalse(resp.success)
        self.assertIn("公共 SearXNG 实例", resp.error_message or "")
        self.assertEqual(mock_get.call_count, 1)

    @patch("src.search_service.time.time")
    @patch("src.search_service.requests.get")
    def test_public_mode_cold_start_failure_honors_backoff_then_retries(self, mock_get, mock_time):
        import requests as req_module

        current_time = [1000.0]
        mock_time.side_effect = lambda: current_time[0]  # noqa: E731
        mock_get.side_effect = [
            req_module.exceptions.ConnectionError("dns failed"),
            self._response(json_payload=self._public_feed(["https://public-1.example/"])),
            self._response(json_payload={"results": []}),
        ]

        provider = self._create_provider(use_public_instances=True)
        first = provider.search("first", max_results=5)
        current_time[0] = 1001.0
        second = provider.search("second", max_results=5)
        current_time[0] = 1000.0 + SearXNGSearchProvider.PUBLIC_INSTANCES_STALE_REFRESH_BACKOFF_SECONDS + 1
        third = provider.search("third", max_results=5)

        self.assertFalse(first.success)
        self.assertFalse(second.success)
        self.assertTrue(third.success)
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_get.call_args_list[0][0][0], SearXNGSearchProvider.PUBLIC_INSTANCES_URL)
        self.assertEqual(mock_get.call_args_list[1][0][0], SearXNGSearchProvider.PUBLIC_INSTANCES_URL)
        self.assertIn("https://public-1.example/search", mock_get.call_args_list[2][0][0])

    @patch("src.search_service.time.time")
    @patch("src.search_service.requests.get")
    def test_public_instance_refresh_failure_reuses_stale_cache(self, mock_get, mock_time):
        import requests as req_module

        fallback_time = (
            1000.0 + SearXNGSearchProvider.PUBLIC_INSTANCES_CACHE_TTL_SECONDS + 2
        )
        time_values = iter(
            [
                1000.0,
                1000.0 + SearXNGSearchProvider.PUBLIC_INSTANCES_CACHE_TTL_SECONDS + 1,
                fallback_time,
            ]
        )
        mock_time.side_effect = lambda: next(time_values, fallback_time)  # noqa: E731
        mock_get.side_effect = [
            self._response(json_payload=self._public_feed(["https://public-1.example/"])),
            req_module.exceptions.ConnectionError("dns failed"),
        ]

        first = SearXNGSearchProvider._get_public_instances()
        second = SearXNGSearchProvider._get_public_instances()
        third = SearXNGSearchProvider._get_public_instances()

        self.assertEqual(first, ["https://public-1.example"])
        self.assertEqual(second, ["https://public-1.example"])
        self.assertEqual(third, ["https://public-1.example"])
        self.assertEqual(mock_get.call_count, 2)

    @patch.object(SearXNGSearchProvider, "_get_public_instances")
    @patch("src.search_service._get_with_retry")
    def test_self_hosted_mode_does_not_fetch_public_instances(self, mock_get, mock_public_instances):
        mock_get.return_value = self._response(json_payload={"results": []})

        provider = self._create_provider(["https://searx.example.org"], use_public_instances=True)
        resp = provider.search("query", max_results=5)

        self.assertTrue(resp.success)
        mock_public_instances.assert_not_called()

    def test_search_service_adds_public_searxng_provider_when_enabled(self):
        service = SearchService(searxng_public_instances_enabled=True)

        self.assertTrue(service.is_available)
        self.assertTrue(any(provider.name == "SearXNG" for provider in service._providers))


if __name__ == "__main__":
    unittest.main()
