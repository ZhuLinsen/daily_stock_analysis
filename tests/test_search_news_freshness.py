# -*- coding: utf-8 -*-
"""
Unit tests for strict news freshness filtering and strategy window logic (Issue #697).
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import SearchResponse, SearchResult, SearchService


def _result(title: str, published_date: str | None) -> SearchResult:
    return SearchResult(
        title=title,
        snippet="snippet",
        url=f"https://example.com/{title}",
        source="example.com",
        published_date=published_date,
    )


def _response(results) -> SearchResponse:
    return SearchResponse(
        query="test",
        results=results,
        provider="Mock",
        success=True,
    )


class SearchNewsFreshnessTestCase(unittest.TestCase):
    """Tests for strategy window and strict published_date filtering."""

    def _create_service_with_mock_provider(
        self,
        *,
        news_max_age_days: int = 3,
        news_strategy_profile: str = "short",
        response: SearchResponse | None = None,
    ):
        service = SearchService(
            bocha_keys=["dummy_key"],
            searxng_public_instances_enabled=False,
            news_max_age_days=news_max_age_days,
            news_strategy_profile=news_strategy_profile,
        )
        mock_search = MagicMock(
            return_value=response
            or _response([_result("default", datetime.now().date().isoformat())])
        )
        service._providers[0].search = mock_search
        return service, mock_search

    def test_effective_window_uses_profile_and_news_max_age(self) -> None:
        """window = min(profile_days, NEWS_MAX_AGE_DAYS)."""
        service, mock_search = self._create_service_with_mock_provider(
            news_max_age_days=3,
            news_strategy_profile="medium",  # 7
        )
        service.search_stock_news("600519", "贵州茅台", max_results=5)
        kwargs = mock_search.call_args[1]
        self.assertEqual(kwargs["days"], 3)

    def test_invalid_profile_falls_back_to_short(self) -> None:
        """Invalid profile should fallback to short (3 days)."""
        service, mock_search = self._create_service_with_mock_provider(
            news_max_age_days=30,
            news_strategy_profile="invalid_profile",
        )
        service.search_stock_news("600519", "贵州茅台", max_results=5)
        kwargs = mock_search.call_args[1]
        self.assertEqual(kwargs["days"], 3)

    def test_search_stock_news_strict_filters(self) -> None:
        """Drop old/unknown/future+2, keep future+1 and within-window dates."""
        today = datetime.now().date()
        fresh = today.isoformat()
        old = (today - timedelta(days=30)).isoformat()
        future_1 = (today + timedelta(days=1)).isoformat()
        future_2 = (today + timedelta(days=2)).isoformat()

        service, _ = self._create_service_with_mock_provider(
            news_max_age_days=7,
            news_strategy_profile="medium",
            response=_response(
                [
                    _result("old", old),
                    _result("unknown", None),
                    _result("future_2", future_2),
                    _result("future_1", future_1),
                    _result("fresh", fresh),
                ]
            ),
        )

        resp = service.search_stock_news("600519", "贵州茅台", max_results=5)
        titles = [r.title for r in resp.results]
        self.assertEqual(titles, ["future_1", "fresh"])
        for item in resp.results:
            self.assertRegex(item.published_date or "", r"^\d{4}-\d{2}-\d{2}$")

    def test_search_stock_news_overfetch_before_filter(self) -> None:
        """Provider request size should be increased before filtering."""
        service, mock_search = self._create_service_with_mock_provider(
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        service.search_stock_news("600519", "贵州茅台", max_results=4)
        args, kwargs = mock_search.call_args
        requested = kwargs.get("max_results")
        if requested is None:
            requested = args[1]
        self.assertEqual(requested, 8)

    def test_search_stock_news_try_next_provider_when_filtered_empty(self) -> None:
        """If provider-A passes API call but all results are filtered, continue to provider-B."""
        today = datetime.now().date()
        old = (today - timedelta(days=90)).isoformat()
        fresh = today.isoformat()

        service = SearchService(
            bocha_keys=["dummy_key"],
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short",
        )

        p1 = SimpleNamespace(
            is_available=True,
            name="P1",
            search=MagicMock(return_value=_response([_result("too_old", old)])),
        )
        p2 = SimpleNamespace(
            is_available=True,
            name="P2",
            search=MagicMock(return_value=_response([_result("fresh", fresh)])),
        )
        service._providers = [p1, p2]

        resp = service.search_stock_news("600519", "贵州茅台", max_results=3)
        self.assertEqual([r.title for r in resp.results], ["fresh"])
        p1.search.assert_called_once()
        p2.search.assert_called_once()

    def test_search_comprehensive_intel_splits_strict_and_non_strict_filters(self) -> None:
        """Latest news stays strict while market analysis keeps undated results."""
        today = datetime.now().date()
        old = (today - timedelta(days=20)).isoformat()
        fresh = (today - timedelta(days=1)).isoformat()
        analysis_dt = datetime.now(timezone.utc).replace(microsecond=0)
        analysis_text = analysis_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        expected_analysis_date = analysis_dt.astimezone().date().isoformat()

        service, mock_search = self._create_service_with_mock_provider(
            news_max_age_days=3,
            news_strategy_profile="medium",  # min(7,3)=3
        )
        mock_search.side_effect = [
            _response([_result("old", old), _result("fresh", fresh)]),
            _response([_result("analysis_unknown", None), _result("analysis_dated", analysis_text)]),
        ]
        with patch("src.search_service.time.sleep"):
            intel = service.search_comprehensive_intel(
                stock_code="600519",
                stock_name="贵州茅台",
                max_searches=2,
            )

        self.assertGreaterEqual(mock_search.call_count, 1)
        for call in mock_search.call_args_list:
            kwargs = call[1]
            self.assertEqual(kwargs["days"], 3)
            self.assertEqual(kwargs["max_results"], 6)  # target 3 -> overfetch 6

        self.assertEqual([item.title for item in intel["latest_news"].results], ["fresh"])
        self.assertEqual(
            [item.title for item in intel["market_analysis"].results],
            ["analysis_unknown", "analysis_dated"],
        )
        self.assertIsNone(intel["market_analysis"].results[0].published_date)
        self.assertEqual(intel["market_analysis"].results[1].published_date, expected_analysis_date)

    def test_search_comprehensive_intel_etf_risk_check_keeps_unknown_dates(self) -> None:
        """ETF risk_check should avoid strict freshness filtering."""
        fresh_dt = datetime.now(timezone.utc).replace(microsecond=0)
        fresh_text = fresh_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        expected_fresh_date = fresh_dt.astimezone().date().isoformat()

        service, mock_search = self._create_service_with_mock_provider(
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        mock_search.side_effect = [
            _response([_result("latest_news", fresh_text)]),
            _response([_result("market_analysis_unknown", None)]),
            _response([_result("risk_unknown", None)]),
        ]

        with patch("src.search_service.time.sleep"):
            intel = service.search_comprehensive_intel(
                stock_code="510300",
                stock_name="沪深300ETF",
                max_searches=3,
            )

        self.assertEqual(intel["latest_news"].results[0].published_date, expected_fresh_date)
        self.assertEqual([item.title for item in intel["market_analysis"].results], ["market_analysis_unknown"])
        self.assertIsNone(intel["market_analysis"].results[0].published_date)
        self.assertEqual([item.title for item in intel["risk_check"].results], ["risk_unknown"])
        self.assertIsNone(intel["risk_check"].results[0].published_date)

    def test_search_comprehensive_intel_non_etf_risk_check_stays_strict(self) -> None:
        """Non-ETF risk_check should keep strict freshness filtering."""
        fresh_dt = datetime.now(timezone.utc).replace(microsecond=0)
        fresh_text = fresh_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        expected_fresh_date = fresh_dt.astimezone().date().isoformat()

        service, mock_search = self._create_service_with_mock_provider(
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        mock_search.side_effect = [
            _response([_result("latest_news", fresh_text)]),
            _response([_result("market_analysis_unknown", None)]),
            _response([_result("risk_unknown", None)]),
        ]

        with patch("src.search_service.time.sleep"):
            intel = service.search_comprehensive_intel(
                stock_code="600519",
                stock_name="贵州茅台",
                max_searches=3,
            )

        self.assertEqual(intel["latest_news"].results[0].published_date, expected_fresh_date)
        self.assertEqual([item.title for item in intel["market_analysis"].results], ["market_analysis_unknown"])
        self.assertIsNone(intel["market_analysis"].results[0].published_date)
        self.assertEqual(intel["risk_check"].results, [])

    def test_effective_window_helper_has_no_side_effect(self) -> None:
        """_effective_news_window_days should not mutate stored news_window_days."""
        service, _ = self._create_service_with_mock_provider(
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        service.news_window_days = 99
        resolved = service._effective_news_window_days()
        self.assertEqual(resolved, 3)
        self.assertEqual(service.news_window_days, 99)

    def test_unix_timestamp_normalizes_to_local_date(self) -> None:
        """Unix timestamp should be converted to local date before window filtering."""
        dt_utc = datetime(2026, 3, 15, 23, 30, tzinfo=timezone.utc)
        timestamp = str(int(dt_utc.timestamp()))
        expected_local_date = dt_utc.astimezone().date()
        parsed = SearchService._normalize_news_publish_date(timestamp)
        self.assertEqual(parsed, expected_local_date)

    def test_iso_utc_string_normalizes_to_local_date(self) -> None:
        """ISO datetime with timezone should be converted to local date."""
        dt_utc = datetime(2026, 3, 15, 23, 30, tzinfo=timezone.utc)
        iso_text = "2026-03-15T23:30:00Z"
        expected_local_date = dt_utc.astimezone().date()
        parsed = SearchService._normalize_news_publish_date(iso_text)
        self.assertEqual(parsed, expected_local_date)

    def test_rfc_utc_string_normalizes_to_local_date(self) -> None:
        """RFC datetime with timezone should be converted to local date."""
        dt_utc = datetime(2026, 3, 15, 23, 30, tzinfo=timezone.utc)
        rfc_text = "Sun, 15 Mar 2026 23:30:00 +0000"
        expected_local_date = dt_utc.astimezone().date()
        parsed = SearchService._normalize_news_publish_date(rfc_text)
        self.assertEqual(parsed, expected_local_date)


if __name__ == "__main__":
    unittest.main()
