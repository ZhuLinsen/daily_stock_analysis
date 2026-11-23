"""Real search results retain acquisition time through screening and cache reuse."""

from datetime import datetime, timezone
import time
from unittest.mock import patch

import pytest

from src.search_service import BochaSearchProvider, SearchResponse, SearchResult, SearchService, SearXNGSearchProvider, TavilySearchProvider


@pytest.mark.parametrize("provider,kwargs", [
    (BochaSearchProvider(["test-key"]), {}),
    (SearXNGSearchProvider(base_urls=["https://search.example.test"], use_public_instances=False), {}),
    (TavilySearchProvider(["test-key"]), {"topic": "news"}),
])
def test_fresh_provider_search_records_retrieval_time(provider, kwargs):
    response = SearchResponse("test", [SearchResult("title", "snippet", "https://example.test", "test")], "test")
    before = datetime.now(timezone.utc)
    with patch.object(provider, "_do_search", return_value=response):
        result = provider.search("test", **kwargs)
    retrieved = datetime.fromisoformat(result.results[0].retrieved_at)
    assert before <= retrieved <= datetime.now(timezone.utc)
    assert retrieved.utcoffset().total_seconds() == 0
    assert result.results[0].published_date is None


@pytest.mark.parametrize("published_date", [None, datetime.now().date().isoformat()])
def test_search_processing_and_cache_preserve_original_time(published_date):
    service = SearchService(bocha_keys=["test-key"], searxng_public_instances_enabled=False)
    timestamp = "2026-01-02T03:04:05+00:00"
    response = SearchResponse("test", [SearchResult(
        "贵州茅台 600519 公告", "贵州茅台公司公告", "https://example.test", "test",
        published_date=published_date, retrieved_at=timestamp,
    )], "test")
    with patch.object(service._providers[0], "_do_search", return_value=response):
        fetched = service._providers[0].search("test")
    normalized = service._normalize_and_limit_response(fetched, max_results=3)
    filtered = service._filter_news_response(
        normalized, search_days=3, max_results=3, keep_unknown=True, log_scope="test",
    )
    ranked = service._rank_news_response(
        filtered, stock_code="600519", stock_name="贵州茅台",
        prefer_chinese=True, max_results=3, log_scope="test",
    )
    assert len(ranked.results) == 1
    assert ranked.results[0].retrieved_at == timestamp
    service._put_cache("test", ranked)
    with patch("src.search_service.time.time", return_value=time.time() + 30):
        assert service._get_cached("test").results[0].retrieved_at == timestamp
