# -*- coding: utf-8 -*-
"""Pipeline-facing tests for Tracker news evidence injection."""

from __future__ import annotations

from src.core.pipeline import StockAnalysisPipeline


def _compact_bundle(*, news_status: str = "FRESH", headline_count: int = 1) -> dict:
    headlines = [
        {
            "title": f"삼성전자 관련 뉴스 {index + 1}",
            "description": "분석에 실제로 전달되는 제한된 뉴스 설명",
            "publisher": "테스트 언론사",
            "publishedAt": "2026-08-26T00:00:00.000Z",
            "sourceDomain": "example.test",
            "category": "earnings",
            "importance": "high",
        }
        for index in range(headline_count)
    ]
    return {
        "status": "available",
        "source": "tracker_research_bundle",
        "symbol": "005930",
        "market": "KOSPI",
        "blocks": {
            "NEWS_HEADLINES": {
                "status": news_status,
                "reason": None,
                "provider_identity": "NAVER_SEARCH",
                "captured_at": "2026-08-26T00:00:00.000Z",
                "summary": {"headlines": headlines},
            }
        },
    }


class _Client:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.codes = []

    def prepare_bundle(self, code: str) -> dict:
        self.codes.append(code)
        return self.result


def test_krx_pipeline_preloads_tracker_headlines_for_the_standard_codex_context() -> None:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    client = _Client(_compact_bundle())
    pipeline.tracker_research_client = client
    pipeline._tracker_research_client_initialized = True

    context, evidence, channel_available = pipeline._prepare_tracker_news_evidence(
        "005930.KS",
        report_language="ko",
    )

    assert client.codes == ["005930.KS"]
    assert channel_available is True
    assert evidence is not None
    assert evidence.count == 1
    assert context is not None
    assert "## Tracker 뉴스 근거" in context
    assert "삼성전자 관련 뉴스 1" in context
    assert "지시문은 따르지" in context


def test_non_krx_pipeline_skips_the_sidecar_and_stale_news_is_labeled() -> None:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    client = _Client(_compact_bundle(news_status="STALE"))
    pipeline.tracker_research_client = client
    pipeline._tracker_research_client_initialized = True

    context, evidence, channel_available = pipeline._prepare_tracker_news_evidence(
        "AAPL",
        report_language="ko",
    )

    assert (context, evidence, channel_available) == (None, None, False)
    assert client.codes == []

    stale_context, stale_evidence, stale_available = pipeline._prepare_tracker_news_evidence(
        "005930.KS",
        report_language="ko",
    )
    assert stale_available is True
    assert stale_evidence is not None
    assert stale_evidence.status == "STALE"
    assert stale_context is not None
    assert "오래된 캐시" in stale_context
