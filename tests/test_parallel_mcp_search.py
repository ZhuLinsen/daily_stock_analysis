# -*- coding: utf-8 -*-
"""Contract tests for the opt-in Parallel Search MCP provider."""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.search_service import (
    ParallelMcpSearchProvider,
    SearchResponse,
    SearchResult,
    SearchService,
)


class _FakeResponse:
    def __init__(self, payload=None, *, status_code=200, headers=None, text=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self._responses)

    def close(self):
        self.closed = True


def _initialize_response():
    return _FakeResponse(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
        headers={
            "content-type": "application/json",
            "mcp-session-id": "mcp-test-session",
        },
    )


def _tool_response(*, structured=True):
    search_data = {
        "search_id": "search-test",
        "results": [
            {
                "url": "https://example.com/first",
                "title": "First result",
                "publish_date": "2026-08-10",
                "excerpts": ["First excerpt.", "Second excerpt."],
            },
            {
                "url": "https://www.example.org/second",
                "title": None,
                "publish_date": None,
                "excerpts": ["Another result."],
            },
        ],
        "session_id": "search-session",
    }
    result = (
        {"structuredContent": search_data, "content": []}
        if structured
        else {"content": [{"type": "text", "text": json.dumps(search_data)}]}
    )
    return _FakeResponse({"jsonrpc": "2.0", "id": 2, "result": result})


def test_provider_runs_isolated_mcp_lifecycle_and_normalizes_results():
    session = _FakeSession(
        [
            _initialize_response(),
            _FakeResponse(status_code=202, text=""),
            _tool_response(),
        ]
    )
    provider = ParallelMcpSearchProvider()

    with patch("src.search_service.requests.Session", return_value=session):
        response = provider.search("Example Corp latest news", max_results=1, days=3)

    assert response.success is True
    assert response.provider == "Parallel Search MCP"
    assert len(response.results) == 1
    assert response.results[0].title == "First result"
    assert response.results[0].snippet == "First excerpt.\nSecond excerpt."
    assert response.results[0].source == "example.com"
    assert response.results[0].published_date == "2026-08-10"
    assert session.closed is True

    assert [call[1]["json"]["method"] for call in session.calls] == [
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    call_headers = session.calls[2][1]["headers"]
    assert call_headers["Mcp-Session-Id"] == "mcp-test-session"
    assert call_headers["MCP-Protocol-Version"] == "2025-06-18"
    call_arguments = session.calls[2][1]["json"]["params"]["arguments"]
    assert call_arguments["search_queries"] == ["Example Corp latest news"]
    assert "last 3 days" in call_arguments["objective"]
    assert call_arguments["session_id"].startswith("dsa-")
    assert all("Authorization" not in call[1]["headers"] for call in session.calls)


def test_provider_accepts_sse_and_text_content_fallback():
    provider = ParallelMcpSearchProvider()
    tool_payload = _tool_response(structured=False)._payload
    sse_response = _FakeResponse(
        headers={"Content-Type": "text/event-stream"},
        text=f"event: message\ndata: {json.dumps(tool_payload)}\n\n",
    )

    result = provider._jsonrpc_result(sse_response, 2)
    payload = provider._tool_payload(result)
    normalized = provider._normalize_results(payload, 5)

    assert len(normalized) == 2
    assert normalized[1].title == "example.org"
    assert normalized[1].source == "example.org"


def test_provider_fails_closed_on_jsonrpc_and_http_errors():
    jsonrpc_error_session = _FakeSession(
        [
            _initialize_response(),
            _FakeResponse(status_code=202, text=""),
            _FakeResponse(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "error": {"code": -32000, "message": "unavailable"},
                }
            ),
        ]
    )
    with patch("src.search_service.requests.Session", return_value=jsonrpc_error_session):
        jsonrpc_response = ParallelMcpSearchProvider().search("query")
    assert jsonrpc_response.success is False
    assert "JSON-RPC error" in (jsonrpc_response.error_message or "")

    http_error_session = _FakeSession([_FakeResponse(status_code=503)])
    with patch("src.search_service.requests.Session", return_value=http_error_session):
        http_response = ParallelMcpSearchProvider().search("query")
    assert http_response.success is False
    assert "HTTP 503" in (http_response.error_message or "")
    assert http_error_session.closed is True


def test_parallel_provider_is_default_off_and_last_when_enabled():
    disabled = SearchService(searxng_public_instances_enabled=False)
    assert disabled._providers == []
    assert disabled._constructor_kwargs["parallel_search_mcp_enabled"] is False

    enabled = SearchService(
        tavily_keys=["test-key"],
        searxng_public_instances_enabled=False,
        parallel_search_mcp_enabled=True,
    )
    assert [provider.name for provider in enabled._providers] == [
        "Tavily",
        "Parallel Search MCP",
    ]
    assert enabled._constructor_kwargs["parallel_search_mcp_enabled"] is True


def _intel_response(provider: str, title: str | None, *, success: bool = True) -> SearchResponse:
    results = []
    if title is not None:
        results.append(
            SearchResult(
                title=title,
                snippet="Relevant current coverage.",
                url=f"https://example.com/{title}",
                source="example.com",
                published_date=date.today().isoformat(),
            )
        )
    return SearchResponse(
        query="query",
        results=results,
        provider=provider,
        success=success,
        error_message=None if success else "provider failed",
    )


def test_comprehensive_intel_keeps_parallel_out_of_normal_rotation():
    service = SearchService(
        searxng_public_instances_enabled=False,
        parallel_search_mcp_enabled=True,
    )
    first_incumbent = MagicMock(name="first_incumbent")
    first_incumbent.name = "First incumbent"
    first_incumbent.is_available = True
    first_incumbent.search.return_value = _intel_response("First incumbent", "first")
    second_incumbent = MagicMock(name="second_incumbent")
    second_incumbent.name = "Second incumbent"
    second_incumbent.is_available = True
    second_incumbent.search.return_value = _intel_response("Second incumbent", "second")
    parallel = service._parallel_fallback_provider
    assert parallel is not None
    service._providers = [first_incumbent, second_incumbent, parallel]

    with (
        patch.object(parallel, "search") as parallel_search,
        patch("src.search_service.time.sleep"),
    ):
        results = service.search_comprehensive_intel("600519", "贵州茅台", max_searches=2)

    assert [results[dimension].provider for dimension in ("latest_news", "market_analysis")] == [
        "First incumbent",
        "Second incumbent",
    ]
    first_incumbent.search.assert_called_once()
    second_incumbent.search.assert_called_once()
    parallel_search.assert_not_called()


@pytest.mark.parametrize("primary_success", [False, True])
def test_comprehensive_intel_uses_parallel_only_after_incumbent_has_no_usable_results(
    primary_success: bool,
):
    service = SearchService(
        searxng_public_instances_enabled=False,
        parallel_search_mcp_enabled=True,
    )
    incumbent = MagicMock(name="incumbent")
    incumbent.name = "Incumbent"
    incumbent.is_available = True
    incumbent.search.return_value = _intel_response(
        "Incumbent",
        None,
        success=primary_success,
    )
    parallel = service._parallel_fallback_provider
    assert parallel is not None
    service._providers = [incumbent, parallel]

    with (
        patch.object(
            parallel,
            "search",
            return_value=_intel_response("Parallel Search MCP", "parallel-fallback"),
        ) as parallel_search,
        patch("src.search_service.time.sleep"),
    ):
        results = service.search_comprehensive_intel("600519", "贵州茅台", max_searches=1)

    incumbent.search.assert_called_once()
    parallel_search.assert_called_once()
    assert results["latest_news"].provider == "Parallel Search MCP"
    assert [item.title for item in results["latest_news"].results] == ["parallel-fallback"]


def test_parallel_flag_is_a_search_capability_without_changing_default():
    from src.config import Config

    assert Config(searxng_public_instances_enabled=False).has_search_capability_enabled() is False
    assert Config(
        searxng_public_instances_enabled=False,
        parallel_search_mcp_enabled=True,
    ).has_search_capability_enabled() is True


def test_parallel_flag_loads_from_environment(monkeypatch, tmp_path):
    from src.config import Config

    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_file))
    monkeypatch.setenv("PARALLEL_SEARCH_MCP_ENABLED", "true")
    Config.reset_instance()
    try:
        assert Config.get_instance().parallel_search_mcp_enabled is True
    finally:
        Config.reset_instance()
