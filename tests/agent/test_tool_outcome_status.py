"""Structured tool outcomes must agree with progress and trajectory status."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from evals.agent_trajectory.metrics import GoldenSample, compute_trajectory_metrics
from src.agent.llm_adapter import LLMResponse, ToolCall
from src.agent.runner import _execute_tools, run_agent_loop
from src.agent.tools.data_tools import get_realtime_quote_tool
from src.agent.tools.execution import serialize_tool_result
from src.agent.tools.registry import ToolDefinition, ToolRegistry
from src.agent.tools.search_tools import search_stock_news_tool


@pytest.mark.parametrize("payload, expected_success", [
    ({"error": "provider unavailable"}, False),
    ({"success": False, "error": None}, False),
    ({"success": True, "results": []}, True),
    ({"error": None, "data": []}, True),
    ({"status": "partial", "errors": ["optional source unavailable"]}, True),
    ({"status": "ok", "risk": {"error": "optional risk lookup failed"}}, True),
    ({"status": "not_supported", "note": "Outside provider coverage"}, True),
    ({}, True),
    ([], True),
    (None, True),
    ("An ordinary string mentioning an error", True),
])
def test_runner_classifies_only_explicit_top_level_failures(payload, expected_success):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="result_fixture", description="Return a fixture", parameters=[],
        handler=lambda: payload,
    ))
    events, log = [], []
    results = _execute_tools(
        [ToolCall(id="fixture", name="result_fixture", arguments={})],
        registry, 1, events.append, log,
    )

    assert log[0]["success"] is expected_success
    assert next(event for event in events if event["type"] == "tool_done")["success"] is expected_success
    assert results[0]["result_str"] == serialize_tool_result(payload)


def test_real_tool_failures_remain_failed_when_cached_and_do_not_abort_the_loop():
    registry = ToolRegistry()
    registry.register(get_realtime_quote_tool)
    registry.register(search_stock_news_tool)
    quote_args = {"stock_code": "AAPL"}
    news_args = {"stock_code": "AAPL", "stock_name": "Apple"}
    adapter = Mock()
    adapter.call_with_tools.side_effect = [
        LLMResponse(tool_calls=[
            ToolCall(id="quote1", name="get_realtime_quote", arguments=quote_args),
            ToolCall(id="news1", name="search_stock_news", arguments=news_args),
        ], usage={}),
        LLMResponse(tool_calls=[
            ToolCall(id="quote2", name="get_realtime_quote", arguments=quote_args),
        ], usage={}),
        LLMResponse(content="Data unavailable; wait for confirmation.", usage={}),
    ]
    manager = Mock()
    manager.get_realtime_quote.return_value = None
    service = Mock(is_available=True)
    service.search_stock_news.return_value = SimpleNamespace(
        success=False, query="AAPL news", error_message="provider unavailable",
    )
    events = []
    with (
        patch("src.agent.tools.data_tools._get_fetcher_manager", return_value=manager),
        patch("src.agent.tools.search_tools._get_search_service", return_value=service),
    ):
        result = run_agent_loop(
            messages=[{"role": "user", "content": "Analyze AAPL"}],
            tool_registry=registry, llm_adapter=adapter, max_steps=3,
            progress_callback=events.append,
        )

    assert result.success is True
    assert result.content == "Data unavailable; wait for confirmation."
    assert len(result.tool_calls_log) == 3
    assert all(entry["success"] is False for entry in result.tool_calls_log)
    assert [entry["cached"] for entry in result.tool_calls_log] == [False, False, True]
    done_events = [event for event in events if event["type"] == "tool_done"]
    assert len(done_events) == 3
    assert all(event["success"] is False for event in done_events)
    manager.get_realtime_quote.assert_called_once_with("AAPL")
    service.search_stock_news.assert_called_once_with("AAPL", "Apple", max_results=5)
    tool_messages = [message for message in result.messages if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["quote1", "news1", "quote2"]
    assert tool_messages[0]["content"] == tool_messages[2]["content"]
    assert json.loads(tool_messages[0]["content"])["retriable"] is False
    assert json.loads(tool_messages[1]["content"])["success"] is False
    metrics = compute_trajectory_metrics(result.tool_calls_log, GoldenSample(
        id="tool-failure-status", task_description="Analyze AAPL", stock_code="AAPL",
        expected_tools=["get_realtime_quote", "search_stock_news"],
    ))
    assert (metrics.failed_calls, metrics.retries, metrics.cached_calls) == (3, 1, 1)


@pytest.mark.parametrize("failure", [
    {"error": "temporarily unavailable", "retriable": True},
    {"success": False, "error": None},
])
def test_uncached_failure_can_recover_in_a_mixed_parallel_batch(failure):
    handler = Mock(side_effect=[failure, {"success": True, "results": []}])
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="recovering", description="Recover on a later call", parameters=[], handler=handler,
    ))
    registry.register(ToolDefinition(
        name="healthy", description="Successful empty result", parameters=[], handler=lambda: [],
    ))
    cache, log = {}, []
    for step in (1, 2):
        _execute_tools([
            ToolCall(id=f"recovering{step}", name="recovering", arguments={}),
            ToolCall(id=f"healthy{step}", name="healthy", arguments={}),
        ], registry, step, None, log, non_retriable_tool_results=cache)

    assert [entry["success"] for entry in log if entry["tool"] == "recovering"] == [False, True]
    assert all(entry["success"] for entry in log if entry["tool"] == "healthy")
    assert all(entry["cached"] is False for entry in log)
    assert handler.call_count == 2
    assert cache == {}


def test_real_news_search_with_no_results_is_successful():
    registry = ToolRegistry()
    registry.register(search_stock_news_tool)
    service = Mock(is_available=True)
    service.search_stock_news.return_value = SimpleNamespace(
        success=True, query="AAPL news", provider="fixture", results=[],
    )
    log = []
    with patch("src.agent.tools.search_tools._get_search_service", return_value=service):
        results = _execute_tools([
            ToolCall(id="empty", name="search_stock_news", arguments={
                "stock_code": "AAPL", "stock_name": "Apple",
            }),
        ], registry, 1, None, log)

    assert log[0]["success"] is True
    payload = json.loads(results[0]["result_str"])
    assert payload["success"] is True
    assert payload["results_count"] == 0
    assert payload["results"] == []
