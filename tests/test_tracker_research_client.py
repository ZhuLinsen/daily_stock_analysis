# -*- coding: utf-8 -*-
"""Focused contract tests for the DSA-owned Tracker sidecar client."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError

from src.services.tracker_research_client import (
    TRACKER_RESEARCH_BLOCK_SOURCES,
    TrackerResearchClient,
    TrackerResearchSettings,
    create_tracker_research_client,
    tracker_news_evidence_from_bundle,
)


class _Response:
    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._body


def _bundle(*, headline_count: int = 1, news_status: str = "FRESH") -> dict:
    blocks = {}
    for source in TRACKER_RESEARCH_BLOCK_SOURCES:
        summary = {"source": source}
        if source == "NEWS_HEADLINES":
            summary["headlines"] = [
                {
                    "title": f"뉴스 {index + 1}",
                    "description": "실제 분석에 제공할 뉴스 요약",
                    "publisher": "테스트 언론사",
                    "publishedAt": "2026-08-26T00:00:00.000Z",
                    "sourceDomain": "example.test",
                    "category": "earnings",
                    "importance": "high",
                }
                for index in range(headline_count)
            ]
        blocks[source] = {
            "source": source,
            "status": news_status if source == "NEWS_HEADLINES" else "FRESH",
            "reason": None,
            "providerIdentity": "NAVER_SEARCH" if source == "NEWS_HEADLINES" else "TEST",
            "capturedAt": "2026-08-26T00:00:00.000Z",
            "asOfDate": "2026-08-26",
            "ageMs": 1,
            "staleAfterMs": 60_000,
            "normalizedSummary": summary,
        }
    return {
        "version": "tracker-research-bundle/v1",
        "symbol": "005930",
        "market": "KOSPI",
        "capturedAtOrBefore": "2026-08-26T00:00:00.000Z",
        "blocks": blocks,
    }


def _settings(**overrides) -> TrackerResearchSettings:
    values = {
        "base_url": "http://127.0.0.1:47832",
        "bearer_token": "a" * 32,
        "timeout_s": 5.0,
        "preflight_enabled": True,
        "refresh_wait_s": 2.0,
    }
    values.update(overrides)
    return TrackerResearchSettings(**values)


def test_preflight_refreshes_only_the_sidecar_then_reads_a_valid_bundle() -> None:
    refresh_required = HTTPError(
        "http://127.0.0.1:47832/v1/research/stocks/005930.KS/bundle",
        409,
        "Conflict",
        {},
        io.BytesIO(b'{"error":"refresh_required"}'),
    )
    responses = [
        refresh_required,
        _Response(202, {"status": "QUEUED"}),
        _Response(200, {"status": "SUCCEEDED"}),
        _Response(200, _bundle()),
    ]
    requests = []
    clock = {"value": 0.0}

    def open_url(request, *, timeout):
        requests.append((request, timeout))
        next_response = responses.pop(0)
        if isinstance(next_response, BaseException):
            raise next_response
        return next_response

    def sleep(seconds: float) -> None:
        clock["value"] += seconds

    client = TrackerResearchClient(
        _settings(),
        open_url=open_url,
        monotonic=lambda: clock["value"],
        sleep=sleep,
        now_iso=lambda: "2026-08-26T00:00:00.000Z",
    )

    result = client.prepare_bundle("005930.KS")

    assert result["status"] == "available"
    assert len(requests) == 4
    assert requests[0][0].method == "GET"
    assert "capturedAtOrBefore=2026-08-26T00%3A00%3A00.000Z" in requests[0][0].full_url
    assert requests[1][0].method == "POST"
    assert requests[1][0].full_url.endswith("/v1/research/stocks/005930.KS/refresh")
    assert requests[2][0].method == "GET"
    assert requests[3][0].method == "GET"
    assert all(
        request.get_header("Authorization") == f"Bearer {'a' * 32}"
        for request, _timeout in requests
    )


def test_client_never_uses_network_for_missing_or_invalid_private_config() -> None:
    no_token, no_token_reason = create_tracker_research_client(
        SimpleNamespace(
            tracker_research_api_url="http://127.0.0.1:47832",
            tracker_research_api_token="",
        )
    )
    invalid_url, invalid_url_reason = create_tracker_research_client(
        SimpleNamespace(
            tracker_research_api_url="http://example.test:47832",
            tracker_research_api_token="a" * 32,
        )
    )

    assert no_token is None
    assert no_token_reason == "tracker_research_not_configured"
    assert invalid_url is None
    assert invalid_url_reason == "tracker_research_configuration_invalid"


def test_refresh_pending_fails_open_without_provider_failure_details() -> None:
    refresh_required = HTTPError(
        "http://127.0.0.1:47832/v1/research/stocks/005930.KS/bundle",
        409,
        "Conflict",
        {},
        io.BytesIO(b'{"error":"refresh_required"}'),
    )
    responses = [
        refresh_required,
        _Response(202, {"status": "QUEUED"}),
        _Response(200, {"status": "RUNNING"}),
    ]
    clock = {"value": 0.0}

    def open_url(_request, *, timeout):
        next_response = responses.pop(0)
        if isinstance(next_response, BaseException):
            raise next_response
        return next_response

    def sleep(seconds: float) -> None:
        clock["value"] += seconds

    result = TrackerResearchClient(
        _settings(refresh_wait_s=0.75),
        open_url=open_url,
        monotonic=lambda: clock["value"],
        sleep=sleep,
    ).prepare_bundle("005930.KS")

    assert result == {
        "status": "unavailable",
        "source": "tracker_research_bundle",
        "reason": "tracker_research_refresh_pending",
    }


def test_tracker_headline_extraction_is_bounded_and_preserves_stale_status() -> None:
    compact = TrackerResearchClient(
        _settings(),
        open_url=lambda *_args, **_kwargs: _Response(200, _bundle(headline_count=8, news_status="STALE")),
        now_iso=lambda: "2026-08-26T00:00:00.000Z",
    ).read_bundle("005930.KS")

    evidence = tracker_news_evidence_from_bundle(compact)

    assert evidence is not None
    assert evidence.status == "STALE"
    assert evidence.count == 5
    assert evidence.dedupe_key.startswith("tracker_news:005930:KOSPI:")
