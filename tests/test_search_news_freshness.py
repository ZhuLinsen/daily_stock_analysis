# -*- coding: utf-8 -*-
"""
Unit tests for search_stock_news and search_comprehensive_intel news_max_age_days logic (Issue #296).
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import SearchResponse, SearchResult, SearchService


def _fake_search_response() -> SearchResponse:
    """Return a successful SearchResponse for mocking."""
    return SearchResponse(
        query="test",
        results=[
            SearchResult(
                title="Test",
                snippet="snippet",
                url="https://example.com/1",
                source="example.com",
                published_date=None,
            )
        ],
        provider="Mock",
        success=True,
    )


class SearchNewsFreshnessTestCase(unittest.TestCase):
    """Tests for news_max_age_days in search_stock_news and search_comprehensive_intel."""

    def _create_service_with_mock_provider(self, news_max_age_days: int = 3):
        """Create SearchService with a mock provider that records search() calls."""
        service = SearchService(
            bocha_keys=["dummy_key"],
            news_max_age_days=news_max_age_days,
        )
        mock_search = MagicMock(return_value=_fake_search_response())
        service._providers[0].search = mock_search
        return service, mock_search

    @patch("src.search_service.datetime")
    def test_search_stock_news_days_monday_limit_by_news_max_age(
        self, mock_dt: MagicMock
    ) -> None:
        """Monday + news_max_age_days=1 -> search_days=1 (min(3,1)=1)."""
        mock_dt.now.return_value.weekday.return_value = 0  # Monday -> weekday_days=3
        service, mock_search = self._create_service_with_mock_provider(
            news_max_age_days=1
        )
        service.search_stock_news("600519", "贵州茅台")
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args[1]
        self.assertEqual(call_kwargs["days"], 1)

    @patch("src.search_service.datetime")
    def test_search_stock_news_days_tuesday_weekday_dominates(
        self, mock_dt: MagicMock
    ) -> None:
        """Tuesday + news_max_age_days=3 -> search_days=1 (min(1,3)=1)."""
        mock_dt.now.return_value.weekday.return_value = 1  # Tuesday -> weekday_days=1
        service, mock_search = self._create_service_with_mock_provider(
            news_max_age_days=3
        )
        service.search_stock_news("600519", "贵州茅台")
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args[1]
        self.assertEqual(call_kwargs["days"], 1)

    @patch("src.search_service.datetime")
    def test_search_stock_news_days_monday_news_max_age_dominates(
        self, mock_dt: MagicMock
    ) -> None:
        """Monday + news_max_age_days=5 -> search_days=3 (min(3,5)=3)."""
        mock_dt.now.return_value.weekday.return_value = 0  # Monday -> weekday_days=3
        service, mock_search = self._create_service_with_mock_provider(
            news_max_age_days=5
        )
        service.search_stock_news("600519", "贵州茅台")
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args[1]
        self.assertEqual(call_kwargs["days"], 3)

    @patch("src.search_service.datetime")
    def test_search_stock_news_days_weekend(self, mock_dt: MagicMock) -> None:
        """Saturday + news_max_age_days=5 -> search_days=2 (min(2,5)=2)."""
        mock_dt.now.return_value.weekday.return_value = 5  # Saturday -> weekday_days=2
        service, mock_search = self._create_service_with_mock_provider(
            news_max_age_days=5
        )
        service.search_stock_news("600519", "贵州茅台")
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args[1]
        self.assertEqual(call_kwargs["days"], 2)

    def test_search_comprehensive_intel_uses_news_max_age_days(self) -> None:
        """search_comprehensive_intel passes news_max_age_days directly to provider.search."""
        service, mock_search = self._create_service_with_mock_provider(
            news_max_age_days=2
        )
        with patch("src.search_service.time.sleep"):  # avoid delay in tests
            service.search_comprehensive_intel(
                stock_code="600519",
                stock_name="贵州茅台",
                max_searches=2,
            )
        self.assertGreaterEqual(mock_search.call_count, 1)
        for call in mock_search.call_args_list:
            call_kwargs = call[1]
            self.assertEqual(
                call_kwargs["days"],
                2,
                msg=f"Expected days=2, got {call_kwargs.get('days')}",
            )
