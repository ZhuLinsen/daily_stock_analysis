# -*- coding: utf-8 -*-
"""
Regression tests for SerpAPI organic content fetch throttling (Issue #882).
"""

import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import SerpAPISearchProvider


class _FakeGoogleSearch:
    response_payload = {}
    init_params = []

    def __init__(self, params):
        type(self).init_params.append(params)

    def get_dict(self):
        return type(self).response_payload

    @classmethod
    def reset(cls) -> None:
        cls.response_payload = {}
        cls.init_params = []


def _fake_serpapi_module() -> ModuleType:
    module = ModuleType("serpapi")
    module.GoogleSearch = _FakeGoogleSearch
    return module


class TestSerpAPISearchProvider(unittest.TestCase):
    """Tests for provider-specific organic content fetch behavior."""

    def _patch_serpapi(self, payload):
        _FakeGoogleSearch.reset()
        _FakeGoogleSearch.response_payload = payload
        return patch.dict(sys.modules, {"serpapi": _fake_serpapi_module()})

    def test_provider_skips_body_fetch_when_snippet_is_sufficient(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])
        long_snippet = "这是一段已经足够长的摘要。 " * 12

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "Long summary result",
                        "link": "https://example.com/long-summary",
                        "snippet": long_snippet,
                        "source": "Example",
                        "date": "2026-03-20",
                    }
                ]
            }
        ), patch("src.search_service.fetch_url_content") as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].snippet, long_snippet.strip())
        self.assertEqual(resp.results[0].published_date, "2026-03-20")
        mock_fetch.assert_not_called()
        self.assertEqual(_FakeGoogleSearch.init_params[0]["num"], 3)

    def test_provider_uses_rich_snippet_extensions_without_fetching(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "Structured summary result",
                        "link": "https://example.com/structured-summary",
                        "source": "Example",
                        "rich_snippet": {
                            "top": {
                                "extensions": [
                                    "Q4 revenue grows 22% year over year and margin keeps improving",
                                    "Management raises full-year guidance after demand stays strong",
                                ]
                            },
                            "bottom": {
                                "extensions": [
                                    "Brokerages lift target prices and keep overweight ratings",
                                ]
                            },
                        },
                    }
                ]
            }
        ), patch("src.search_service.fetch_url_content") as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertIn("Q4 revenue grows 22%", resp.results[0].snippet)
        self.assertIn("Brokerages lift target prices", resp.results[0].snippet)
        mock_fetch.assert_not_called()

    def test_provider_uses_detected_rich_snippet_fields_without_fetching(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "Detected extensions result",
                        "link": "https://example.com/detected-extensions",
                        "source": "Example",
                        "rich_snippet": {
                            "top": {
                                "detected_extensions": {
                                    "price": "$125.30",
                                    "updated_at": "1 hour ago",
                                }
                            },
                            "bottom": {
                                "detected_extensions": {
                                    "rating": 4.5,
                                    "votes": 1200,
                                }
                            },
                        },
                    }
                ]
            }
        ), patch("src.search_service.fetch_url_content") as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertIn("price: $125.30", resp.results[0].snippet)
        self.assertIn("updated at: 1 hour ago", resp.results[0].snippet)
        self.assertIn("rating: 4.5", resp.results[0].snippet)
        self.assertIn("votes: 1200", resp.results[0].snippet)
        mock_fetch.assert_not_called()

    def test_provider_preserves_falsy_detected_extensions_without_fetching(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "Zero-like extensions result",
                        "link": "https://example.com/zero-like-extensions",
                        "source": "Example",
                        "rich_snippet": {
                            "top": {
                                "detected_extensions": {
                                    "price": 0,
                                    "market_open": False,
                                }
                            },
                            "bottom": {
                                "detected_extensions": {
                                    "votes": 0,
                                }
                            },
                        },
                    }
                ]
            }
        ), patch("src.search_service.fetch_url_content") as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertIn("price: 0", resp.results[0].snippet)
        self.assertIn("market open: False", resp.results[0].snippet)
        self.assertIn("votes: 0", resp.results[0].snippet)
        mock_fetch.assert_not_called()

    def test_provider_ignores_scalar_detected_extensions_and_still_fetches(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "Malformed detected extensions result",
                        "link": "https://example.com/malformed-detected-extensions",
                        "snippet": "摘要过短",
                        "source": "Example",
                        "rich_snippet": {
                            "top": {
                                "detected_extensions": True,
                            },
                        },
                    }
                ]
            }
        ), patch(
            "src.search_service.fetch_url_content",
            return_value="网页正文补充信息 " * 40,
        ) as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        mock_fetch.assert_called_once_with(
            "https://example.com/malformed-detected-extensions",
            timeout=SerpAPISearchProvider._ORGANIC_CONTENT_FETCH_TIMEOUT,
        )
        self.assertNotIn("True", resp.results[0].snippet)
        self.assertIn("【网页详情】", resp.results[0].snippet)

    def test_provider_ignores_malformed_rich_snippet_sections(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])
        long_enough_snippet = "已有摘要，足够避免补抓。 " * 16

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "Malformed rich snippet",
                        "link": "https://example.com/malformed-rich-snippet",
                        "snippet": long_enough_snippet,
                        "source": "Example",
                        "rich_snippet": {
                            "top": "unexpected string payload",
                            "bottom": ["unexpected", "list"],
                        },
                    }
                ]
            }
        ), patch("src.search_service.fetch_url_content") as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertEqual(resp.results[0].snippet, long_enough_snippet.strip())
        mock_fetch.assert_not_called()

    def test_provider_ignores_non_list_rich_snippet_extensions(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "Malformed extensions payload",
                        "link": "https://example.com/malformed-extensions",
                        "source": "Example",
                        "rich_snippet": {
                            "top": {
                                "extensions": True,
                            },
                            "bottom": {
                                "extensions": 1,
                                "detected_extensions": {
                                    "rating": 4.5,
                                },
                            },
                        },
                    }
                ]
            }
        ), patch("src.search_service.fetch_url_content") as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 1)
        self.assertIn("rating: 4.5", resp.results[0].snippet)
        mock_fetch.assert_not_called()

    def test_extract_rich_snippet_extensions_handles_non_dict_payloads(self) -> None:
        self.assertEqual(
            SerpAPISearchProvider._extract_rich_snippet_extensions(
                {"rich_snippet": "unexpected string payload"}
            ),
            [],
        )
        self.assertEqual(
            SerpAPISearchProvider._extract_rich_snippet_extensions(
                {
                    "rich_snippet": {
                        "top": "unexpected string payload",
                        "bottom": ["unexpected", "list"],
                    }
                }
            ),
            [],
        )

    def test_merge_organic_snippet_uses_normalized_length_for_ellipsis(self) -> None:
        merged = SerpAPISearchProvider._merge_organic_snippet_with_content(
            "原始摘要",
            "A" + ("\n" * (SerpAPISearchProvider._ORGANIC_FETCHED_PREVIEW_LENGTH + 20)),
        )

        self.assertFalse(merged.endswith("..."))

    def test_provider_fetches_only_one_top_short_snippet_candidate(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "Need extra context",
                        "link": "https://example.com/need-extra-context",
                        "snippet": "摘要过短",
                        "source": "Example",
                    },
                    {
                        "title": "Second short result",
                        "link": "https://example.com/second-short",
                        "snippet": "也很短",
                        "source": "Example",
                    },
                    {
                        "title": "Third short result",
                        "link": "https://example.com/third-short",
                        "snippet": "还是很短",
                        "source": "Example",
                    },
                ]
            }
        ), patch(
            "src.search_service.fetch_url_content",
            return_value="网页正文补充信息 " * 40,
        ) as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 3)
        mock_fetch.assert_called_once_with(
            "https://example.com/need-extra-context",
            timeout=SerpAPISearchProvider._ORGANIC_CONTENT_FETCH_TIMEOUT,
        )
        self.assertIn("【网页详情】", resp.results[0].snippet)
        self.assertEqual(resp.results[1].snippet, "也很短")
        self.assertEqual(resp.results[2].snippet, "还是很短")

    def test_provider_skips_asset_link_and_fetches_next_eligible_result(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "PDF attachment",
                        "link": "https://example.com/report.PDF?download=1",
                        "snippet": "附件摘要很短",
                        "source": "Example",
                    },
                    {
                        "title": "HTML article",
                        "link": "https://example.com/article",
                        "snippet": "正文摘要也短",
                        "source": "Example",
                    },
                    {
                        "title": "Third short result",
                        "link": "https://example.com/third-short",
                        "snippet": "还是很短",
                        "source": "Example",
                    },
                ]
            }
        ), patch(
            "src.search_service.fetch_url_content",
            return_value="网页正文补充信息 " * 40,
        ) as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 3)
        mock_fetch.assert_called_once_with(
            "https://example.com/article",
            timeout=SerpAPISearchProvider._ORGANIC_CONTENT_FETCH_TIMEOUT,
        )
        self.assertEqual(resp.results[0].snippet, "附件摘要很短")
        self.assertIn("【网页详情】", resp.results[1].snippet)
        self.assertEqual(resp.results[2].snippet, "还是很短")

    def test_provider_skips_query_encoded_attachment_and_fetches_next_result(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "Attachment behind download endpoint",
                        "link": "https://example.com/download?file=report.pdf",
                        "snippet": "附件摘要很短",
                        "source": "Example",
                    },
                    {
                        "title": "HTML article",
                        "link": "https://example.com/article",
                        "snippet": "正文摘要也短",
                        "source": "Example",
                    },
                    {
                        "title": "Third short result",
                        "link": "https://example.com/third-short",
                        "snippet": "还是很短",
                        "source": "Example",
                    },
                ]
            }
        ), patch(
            "src.search_service.fetch_url_content",
            return_value="网页正文补充信息 " * 40,
        ) as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=3)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 3)
        mock_fetch.assert_called_once_with(
            "https://example.com/article",
            timeout=SerpAPISearchProvider._ORGANIC_CONTENT_FETCH_TIMEOUT,
        )
        self.assertEqual(resp.results[0].snippet, "附件摘要很短")
        self.assertIn("【网页详情】", resp.results[1].snippet)
        self.assertEqual(resp.results[2].snippet, "还是很短")

    def test_provider_keeps_html_fetch_for_asset_like_query_param(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "HTML article with media param",
                        "link": "https://example.com/article?thumbnail=cover.jpg",
                        "snippet": "摘要过短",
                        "source": "Example",
                    },
                    {
                        "title": "Second short result",
                        "link": "https://example.com/second-short",
                        "snippet": "也很短",
                        "source": "Example",
                    },
                ]
            }
        ), patch(
            "src.search_service.fetch_url_content",
            return_value="网页正文补充信息 " * 40,
        ) as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=2)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 2)
        mock_fetch.assert_called_once_with(
            "https://example.com/article?thumbnail=cover.jpg",
            timeout=SerpAPISearchProvider._ORGANIC_CONTENT_FETCH_TIMEOUT,
        )
        self.assertIn("【网页详情】", resp.results[0].snippet)
        self.assertEqual(resp.results[1].snippet, "也很短")

    def test_provider_skips_non_string_link_and_keeps_fetch_budget(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "Malformed link result",
                        "link": {"href": "https://example.com/broken"},
                        "snippet": "摘要过短",
                        "source": "Example",
                    },
                    {
                        "title": "HTML article",
                        "link": "https://example.com/article",
                        "snippet": "正文摘要也短",
                        "source": "Example",
                    },
                ]
            }
        ), patch(
            "src.search_service.fetch_url_content",
            return_value="网页正文补充信息 " * 40,
        ) as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=2)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 2)
        mock_fetch.assert_called_once_with(
            "https://example.com/article",
            timeout=SerpAPISearchProvider._ORGANIC_CONTENT_FETCH_TIMEOUT,
        )
        self.assertEqual(resp.results[0].snippet, "摘要过短")
        self.assertIn("【网页详情】", resp.results[1].snippet)

    def test_provider_fetch_failure_stays_fail_open_and_stops_after_budget(self) -> None:
        provider = SerpAPISearchProvider(["dummy_key"])

        with self._patch_serpapi(
            {
                "organic_results": [
                    {
                        "title": "Slow result",
                        "link": "https://example.com/slow",
                        "snippet": "摘要过短",
                        "source": "Example",
                    },
                    {
                        "title": "Another short result",
                        "link": "https://example.com/another-short",
                        "snippet": "仍然很短",
                        "source": "Example",
                    },
                ]
            }
        ), patch(
            "src.search_service.fetch_url_content",
            side_effect=TimeoutError("slow site"),
        ) as mock_fetch:
            resp = provider.search("阿里巴巴 财报", max_results=2)

        self.assertTrue(resp.success)
        self.assertEqual(len(resp.results), 2)
        mock_fetch.assert_called_once_with(
            "https://example.com/slow",
            timeout=SerpAPISearchProvider._ORGANIC_CONTENT_FETCH_TIMEOUT,
        )
        self.assertEqual(resp.results[0].snippet, "摘要过短")
        self.assertEqual(resp.results[1].snippet, "仍然很短")


if __name__ == "__main__":
    unittest.main()
