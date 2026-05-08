# -*- coding: utf-8 -*-
"""Tests for Agent search tool news persistence."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.agent.tools.search_tools import (
    _handle_search_comprehensive_intel,
    _handle_search_stock_news,
)
from src.search_service import SearchResponse, SearchResult


def _response(query: str, *, success: bool = True) -> SearchResponse:
    return SearchResponse(
        query=query,
        provider="UnitSearch",
        success=success,
        error_message=None if success else "search failed",
        results=[
            SearchResult(
                title="新闻标题",
                snippet="新闻摘要",
                url="https://example.com/news",
                source="example.com",
                published_date="2026-04-24",
            )
        ] if success else [],
    )


class SearchToolsPersistenceTest(unittest.TestCase):
    def test_search_stock_news_persists_successful_response(self) -> None:
        response = _response("贵州茅台 600519 latest news")
        service = SimpleNamespace(
            is_available=True,
            search_stock_news=MagicMock(return_value=response),
        )
        db = SimpleNamespace(save_news_intel=MagicMock(return_value=1))

        with patch("src.agent.tools.search_tools._get_search_service", return_value=service), \
             patch("src.agent.tools.search_tools._get_db", return_value=db):
            result = _handle_search_stock_news("600519", "贵州茅台")

        self.assertTrue(result["success"])
        db.save_news_intel.assert_called_once_with(
            code="600519",
            name="贵州茅台",
            dimension="latest_news",
            query=response.query,
            response=response,
            query_context=None,
        )

    def test_search_comprehensive_intel_persists_successful_dimensions_only(self) -> None:
        latest = _response("latest")
        failed = _response("risk", success=False)
        service = SimpleNamespace(
            is_available=True,
            search_comprehensive_intel=MagicMock(
                return_value={"latest_news": latest, "risk_check": failed}
            ),
            format_intel_report=MagicMock(return_value="report"),
        )
        db = SimpleNamespace(save_news_intel=MagicMock(return_value=1))

        with patch("src.agent.tools.search_tools._get_search_service", return_value=service), \
             patch("src.agent.tools.search_tools._get_db", return_value=db):
            result = _handle_search_comprehensive_intel("600519", "贵州茅台")

        self.assertEqual(result["report"], "report")
        self.assertEqual(list(result["dimensions"].keys()), ["latest_news"])
        db.save_news_intel.assert_called_once_with(
            code="600519",
            name="贵州茅台",
            dimension="latest_news",
            query=latest.query,
            response=latest,
            query_context=None,
        )

    def test_persistence_failure_keeps_search_result(self) -> None:
        response = _response("贵州茅台 600519 latest news")
        service = SimpleNamespace(
            is_available=True,
            search_stock_news=MagicMock(return_value=response),
        )
        db = SimpleNamespace(save_news_intel=MagicMock(side_effect=RuntimeError("db locked")))

        with patch("src.agent.tools.search_tools._get_search_service", return_value=service), \
             patch("src.agent.tools.search_tools._get_db", return_value=db):
            result = _handle_search_stock_news("600519", "贵州茅台")

        self.assertTrue(result["success"])
        self.assertEqual(result["results_count"], 1)

    def test_unavailable_or_failed_search_does_not_persist(self) -> None:
        unavailable = SimpleNamespace(is_available=False)
        db = SimpleNamespace(save_news_intel=MagicMock())
        with patch("src.agent.tools.search_tools._get_search_service", return_value=unavailable), \
             patch("src.agent.tools.search_tools._get_db", return_value=db):
            result = _handle_search_stock_news("600519", "贵州茅台")

        self.assertIn("error", result)
        db.save_news_intel.assert_not_called()

        failed = SimpleNamespace(
            is_available=True,
            search_stock_news=MagicMock(return_value=_response("latest", success=False)),
        )
        with patch("src.agent.tools.search_tools._get_search_service", return_value=failed), \
             patch("src.agent.tools.search_tools._get_db", return_value=db):
            result = _handle_search_stock_news("600519", "贵州茅台")

        self.assertFalse(result["success"])
        db.save_news_intel.assert_not_called()


if __name__ == "__main__":
    unittest.main()
