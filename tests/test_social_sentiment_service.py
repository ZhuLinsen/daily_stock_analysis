# -*- coding: utf-8 -*-
"""Tests for SocialSentimentService."""

import threading
import time
import unittest
from unittest.mock import patch, MagicMock

from src.services.social_sentiment_service import SocialSentimentService


class TestServiceAvailability(unittest.TestCase):
    """Tests for is_available property."""

    def test_unavailable_without_key(self):
        svc = SocialSentimentService(api_key=None)
        self.assertFalse(svc.is_available)

    def test_unavailable_with_empty_key(self):
        svc = SocialSentimentService(api_key="  ")
        self.assertFalse(svc.is_available)

    def test_available_with_key(self):
        svc = SocialSentimentService(api_key="sk_live_test123")
        self.assertTrue(svc.is_available)


class TestFetchRedditReport(unittest.TestCase):
    """Tests for fetch_reddit_report."""

    def setUp(self):
        self.svc = SocialSentimentService(api_key="sk_live_test", api_url="https://api.example.com")

    @patch("src.services.social_sentiment_service._get_with_retry")
    def test_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Payload shape of the current /reddit/stocks/v1/stock/{ticker} endpoint:
        # flat stock object (no "report" wrapper).
        mock_resp.json.return_value = {
            "buzz_score": 85.5,
            "sentiment_score": 0.23,
            "mentions": 342,
            "trend": "rising",
        }
        mock_get.return_value = mock_resp

        result = self.svc.fetch_reddit_report("TSLA")
        self.assertIsNotNone(result)
        self.assertEqual(result["buzz_score"], 85.5)
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        url = call_args[0][0]
        # Regression for issue #2448: must hit the current per-stock endpoint
        self.assertIn("/reddit/stocks/v1/stock/TSLA", url)
        self.assertNotIn("/reddit/stocks/v1/report/", url)

    @patch("src.services.social_sentiment_service._get_with_retry")
    def test_http_error_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = self.svc.fetch_reddit_report("UNKNOWN")
        self.assertIsNone(result)

    @patch("src.services.social_sentiment_service._get_with_retry")
    def test_timeout_returns_none(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout("timed out")

        result = self.svc.fetch_reddit_report("AAPL")
        self.assertIsNone(result)


class TestFetchTrending(unittest.TestCase):
    """Tests for trending endpoints with caching."""

    def setUp(self):
        self.svc = SocialSentimentService(api_key="sk_live_test", api_url="https://api.example.com")

    @patch("src.services.social_sentiment_service._get_with_retry")
    def test_x_trending_returns_list(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "trending": [
                {"ticker": "AAPL", "buzz_score": 72.1, "sentiment_score": 0.15},
                {"ticker": "TSLA", "buzz_score": 65.0, "sentiment_score": -0.05},
            ]
        }
        mock_get.return_value = mock_resp

        result = self.svc.fetch_x_trending()
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)

    @patch("src.services.social_sentiment_service._get_with_retry")
    def test_trending_cache_prevents_duplicate_calls(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"trending": [{"ticker": "AAPL"}]}
        mock_get.return_value = mock_resp

        # First call hits API
        self.svc.fetch_x_trending()
        # Second call should use cache
        self.svc.fetch_x_trending()

        self.assertEqual(mock_get.call_count, 1)

    def test_trending_cache_is_thread_safe_for_same_key(self):
        call_count = 0
        lock = threading.Lock()
        barrier = threading.Barrier(4)
        errors = []
        results = []

        def fake_fetch_json(_url, _params=None):
            nonlocal call_count
            with lock:
                call_count += 1
            time.sleep(0.05)
            return {"trending": [{"ticker": "AAPL"}]}

        with patch.object(self.svc, "_fetch_json", side_effect=fake_fetch_json):
            def worker():
                try:
                    barrier.wait(timeout=1)
                    results.append(self.svc.fetch_x_trending())
                except Exception as exc:  # pragma: no cover - thread collection
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertEqual(call_count, 1)
        self.assertEqual(len(results), 4)
        for result in results:
            self.assertEqual(result, [{"ticker": "AAPL"}])

    def test_waiter_fallback_uses_capped_wait_and_populates_cache(self):
        inflight = MagicMock()
        inflight.wait.return_value = False
        self.svc._cache_inflight["x_trending"] = inflight
        payload = {"trending": [{"ticker": "AAPL"}]}

        with patch.object(self.svc, "_fetch_json", return_value=payload) as mock_fetch:
            first = self.svc.fetch_x_trending()
            second = self.svc.fetch_x_trending()

        self.assertEqual(first, [{"ticker": "AAPL"}])
        self.assertEqual(second, [{"ticker": "AAPL"}])
        inflight.wait.assert_called_once_with(timeout=self.svc._cache_wait_timeout_seconds())
        self.assertLess(self.svc._cache_wait_timeout_seconds(), self.svc._TRENDING_CACHE_TTL)
        self.assertLessEqual(self.svc._cache_wait_timeout_seconds(), 30.0)
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertEqual(self.svc._cache["x_trending"][1], payload)


class TestGetSocialContext(unittest.TestCase):
    """Tests for get_social_context (main entry point)."""

    def test_returns_none_when_unavailable(self):
        svc = SocialSentimentService(api_key=None)
        result = svc.get_social_context("AAPL")
        self.assertIsNone(result)

    @patch("src.services.social_sentiment_service._get_with_retry")
    def test_returns_none_when_no_data(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        svc = SocialSentimentService(api_key="sk_live_test")
        result = svc.get_social_context("XYZZY")
        self.assertIsNone(result)

    @patch("src.services.social_sentiment_service._get_with_retry")
    def test_formats_reddit_data(self, mock_get):
        requested_urls = []

        def side_effect(url, **kwargs):
            requested_urls.append(url)
            resp = MagicMock()
            if "/reddit/" in url:
                resp.status_code = 200
                resp.json.return_value = {
                    "buzz_score": 87.5,
                    "sentiment_score": 0.23,
                    "mentions": 342,
                    "subreddit_count": 8,
                    "trend": "rising",
                    "top_mentions": [
                        {
                            "text_snippet": "TSLA looking strong",
                            "subreddit": "wallstreetbets",
                            "upvotes": 1234,
                        }
                    ],
                }
            else:
                resp.status_code = 200
                resp.json.return_value = {"trending": []}
            return resp

        mock_get.side_effect = side_effect

        svc = SocialSentimentService(api_key="sk_live_test")
        result = svc.get_social_context("TSLA")

        self.assertIsNotNone(result)
        self.assertIn("Social Sentiment Intelligence", result)
        self.assertIn("Reddit", result)
        self.assertIn("87.5", result)
        self.assertIn("342", result)
        self.assertIn("TSLA looking strong", result)
        # Regression for issue #2448: the removed report endpoint must never
        # be requested again.
        for url in requested_urls:
            self.assertNotIn("/reddit/stocks/v1/report/", url)
        self.assertTrue(
            any("/reddit/stocks/v1/stock/TSLA" in url for url in requested_urls)
        )

    @patch("src.services.social_sentiment_service._get_with_retry")
    def test_includes_all_platforms(self, mock_get):
        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "/reddit/" in url:
                resp.json.return_value = {"buzz_score": 80, "trend": "rising"}
            elif "/x/" in url:
                resp.json.return_value = {"trending": [{"ticker": "AAPL", "buzz_score": 65}]}
            elif "/polymarket/" in url:
                resp.json.return_value = {"trending": [{"ticker": "AAPL", "buzz_score": 45, "trade_count": 120}]}
            else:
                resp.json.return_value = {"trending": []}
            return resp

        mock_get.side_effect = side_effect

        svc = SocialSentimentService(api_key="sk_live_test")
        result = svc.get_social_context("AAPL")

        self.assertIsNotNone(result)
        self.assertIn("Reddit", result)
        self.assertIn("X (Twitter)", result)
        self.assertIn("Polymarket", result)
        self.assertIn("65", result)  # X buzz
        self.assertIn("120", result)  # Polymarket trades


class TestRedditFoundFalseContract(unittest.TestCase):
    """The current per-stock endpoint signals "no data" with HTTP 200 and
    ``{"ticker": ..., "found": false}`` (official openapi.json).  An empty
    payload must not be treated as valid social evidence (PR #2452 review
    OR-COR-369e9579): no Reddit context text, no evidence registration.
    """

    @patch("src.services.social_sentiment_service.requests.get")
    def test_found_false_only_yields_no_context_and_no_evidence(self, mock_get):
        from src.services.empty_news import news_evidence_present

        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "/reddit/stocks/v1/stock/" in url:
                # Official empty-data contract: 200 + found=false.
                resp.json.return_value = {"ticker": "TSLA", "found": False}
            else:
                resp.json.return_value = {"trending": []}
            return resp

        mock_get.side_effect = side_effect

        svc = SocialSentimentService(api_key="sk_live_test")
        result = svc.get_social_context("TSLA")

        # No Reddit evidence text may be produced for an empty payload.
        self.assertIsNone(result)
        self.assertFalse(news_evidence_present(result))

    @patch("src.services.social_sentiment_service.requests.get")
    def test_found_false_reddit_keeps_x_contributions(self, mock_get):
        from src.services.empty_news import news_evidence_present

        def side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "/reddit/stocks/v1/stock/" in url:
                resp.json.return_value = {"ticker": "TSLA", "found": False}
            elif "/x/" in url:
                resp.json.return_value = {
                    "trending": [
                        {"ticker": "TSLA", "buzz_score": 65, "sentiment_score": 0.2}
                    ]
                }
            else:
                resp.json.return_value = {"trending": []}
            return resp

        mock_get.side_effect = side_effect

        svc = SocialSentimentService(api_key="sk_live_test")
        result = svc.get_social_context("TSLA")

        # X data is real evidence and must survive the empty Reddit payload.
        self.assertIsNotNone(result)
        self.assertIn("X (Twitter) Sentiment", result)
        self.assertIn("Buzz Score: 65", result)
        # The Reddit section must not claim community sentiment data.
        self.assertNotIn("Reddit Community Sentiment", result)
        self.assertIn("Reddit: No data available", result)
        # Evidence still registers because X contributed real data.
        self.assertTrue(news_evidence_present(result))


class TestZeroValueHandling(unittest.TestCase):
    """Verify that zero-valued numeric fields (e.g. neutral sentiment) are preserved."""

    def test_zero_sentiment_preserved_in_reddit(self):
        result = SocialSentimentService._format_social_intel(
            "AAPL",
            reddit_data={"report": {"buzz_score": 50, "sentiment_score": 0, "total_mentions": 10}},
            x_entry=None,
            poly_entry=None,
        )
        self.assertIn("Sentiment Score: 0", result)
        self.assertIn("Buzz Score: 50", result)
        self.assertIn("Mentions: 10", result)

    def test_zero_buzz_preserved_in_x(self):
        result = SocialSentimentService._format_social_intel(
            "AAPL",
            reddit_data=None,
            x_entry={"buzz_score": 0, "sentiment_score": 0.0, "total_mentions": 0},
            poly_entry=None,
        )
        self.assertIn("Buzz Score: 0/100", result)
        self.assertIn("Sentiment Score: 0.0", result)
        self.assertIn("Mentions: 0", result)

    def test_coalesce_preserves_zero(self):
        self.assertEqual(SocialSentimentService._coalesce(0, 5), 0)
        self.assertEqual(SocialSentimentService._coalesce(0.0, 1.0), 0.0)
        self.assertEqual(SocialSentimentService._coalesce(None, 0), 0)
        self.assertIsNone(SocialSentimentService._coalesce(None, None))


class TestRedditStockPayloadParsing(unittest.TestCase):
    """Formatting must accept the flat payload of the current
    /reddit/stocks/v1/stock/{ticker} endpoint (issue #2448)."""

    def test_flat_stock_payload_renders(self):
        result = SocialSentimentService._format_social_intel(
            "AAPL",
            reddit_data={"buzz_score": 70, "sentiment_score": 0.4, "mentions": 55},
            x_entry=None,
            poly_entry=None,
        )
        self.assertIn("Buzz Score: 70", result)
        self.assertIn("Sentiment Score: 0.4", result)
        self.assertIn("Mentions: 55", result)

    def test_daily_trend_list_rendered(self):
        # DailyTrendItem per the official contract carries "sentiment_score".
        result = SocialSentimentService._format_social_intel(
            "AAPL",
            reddit_data={
                "buzz_score": 70,
                "daily_trend": [
                    {"date": "2026-01-01", "mentions": 12, "sentiment_score": 0.31}
                ],
            },
            x_entry=None,
            poly_entry=None,
        )
        self.assertIn("Recent Daily Activity", result)
        self.assertIn("2026-01-01: 12 mentions", result)
        self.assertIn("avg sentiment 0.31", result)

    def test_daily_trend_zero_sentiment_score_rendered(self):
        # Zero is a valid neutral value and must not degrade to "?".
        result = SocialSentimentService._format_social_intel(
            "AAPL",
            reddit_data={
                "buzz_score": 70,
                "daily_trend": [
                    {"date": "2026-01-01", "mentions": 12, "sentiment_score": 0}
                ],
            },
            x_entry=None,
            poly_entry=None,
        )
        self.assertIn("avg sentiment 0", result)
        self.assertNotIn("avg sentiment ?", result)

    def test_top_mention_text_snippet_rendered(self):
        # TopMention per the official contract carries "text_snippet".
        result = SocialSentimentService._format_social_intel(
            "AAPL",
            reddit_data={
                "buzz_score": 70,
                "top_mentions": [
                    {
                        "text_snippet": "$AAPL to the moon",
                        "subreddit": "wallstreetbets",
                        "sentiment_score": 0.8,
                    }
                ],
            },
            x_entry=None,
            poly_entry=None,
        )
        self.assertIn("Top Mentions", result)
        self.assertIn("$AAPL to the moon", result)

    def test_top_mention_legacy_text_field_still_renders(self):
        # Backward compatibility: older payloads used "text"/"title".
        result = SocialSentimentService._format_social_intel(
            "AAPL",
            reddit_data={
                "buzz_score": 70,
                "top_mentions": [{"text": "legacy mention body"}],
            },
            x_entry=None,
            poly_entry=None,
        )
        self.assertIn("legacy mention body", result)

    def test_daily_trend_non_list_ignored(self):
        result = SocialSentimentService._format_social_intel(
            "AAPL",
            reddit_data={"buzz_score": 70, "daily_trend": "rising"},
            x_entry=None,
            poly_entry=None,
        )
        self.assertNotIn("Recent Daily Activity", result)
        self.assertIn("Buzz Score: 70", result)


class TestFindTickerInTrending(unittest.TestCase):
    """Tests for _find_ticker_in_trending helper."""

    def test_finds_by_ticker_field(self):
        trending = [{"ticker": "AAPL", "buzz": 80}, {"ticker": "TSLA", "buzz": 60}]
        result = SocialSentimentService._find_ticker_in_trending(trending, "TSLA")
        self.assertIsNotNone(result)
        self.assertEqual(result["buzz"], 60)

    def test_finds_by_symbol_field(self):
        trending = [{"symbol": "AAPL", "buzz": 80}]
        result = SocialSentimentService._find_ticker_in_trending(trending, "AAPL")
        self.assertIsNotNone(result)

    def test_returns_none_when_not_found(self):
        trending = [{"ticker": "AAPL", "buzz": 80}]
        result = SocialSentimentService._find_ticker_in_trending(trending, "MSFT")
        self.assertIsNone(result)

    def test_case_insensitive_match(self):
        trending = [{"ticker": "aapl", "buzz": 80}]
        result = SocialSentimentService._find_ticker_in_trending(trending, "AAPL")
        self.assertIsNotNone(result)


class TestUSStockGating(unittest.TestCase):
    """Verify that only US stock codes are processed."""

    def test_a_share_code_not_us(self):
        from data_provider.us_index_mapping import is_us_stock_code
        self.assertFalse(is_us_stock_code("600519"))
        self.assertFalse(is_us_stock_code("000001"))
        self.assertFalse(is_us_stock_code("300750"))

    def test_hk_code_not_us(self):
        from data_provider.us_index_mapping import is_us_stock_code
        self.assertFalse(is_us_stock_code("HK00700"))

    def test_us_code_detected(self):
        from data_provider.us_index_mapping import is_us_stock_code
        self.assertTrue(is_us_stock_code("AAPL"))
        self.assertTrue(is_us_stock_code("TSLA"))
        self.assertTrue(is_us_stock_code("NVDA"))


if __name__ == "__main__":
    unittest.main()
