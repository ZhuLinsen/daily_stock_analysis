# -*- coding: utf-8 -*-
"""Unit tests for the read-only Tracker research evidence tool."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from src.agent.tools import tracker_research_tools


class _Response:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self._body


def _config(**overrides):
    values = {
        "tracker_research_api_url": "http://127.0.0.1:47832",
        "tracker_research_api_token": "a" * 32,
        "tracker_research_api_timeout_s": 5,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _bundle() -> dict:
    blocks = {}
    for source in tracker_research_tools._TRACKER_BLOCK_SOURCES:
        blocks[source] = {
            "source": source,
            "status": "FRESH",
            "reason": None,
            "providerIdentity": "test-provider",
            "capturedAt": "2026-08-26T00:00:00.000Z",
            "asOfDate": "2026-08-25",
            "ageMs": 1,
            "staleAfterMs": 60000,
            "normalizedSummary": {"source": source, "value": "evidence"},
        }
    return {
        "version": "tracker-research-bundle/v1",
        "symbol": "005930",
        "market": "KOSPI",
        "capturedAtOrBefore": "2026-08-26T00:00:00.000Z",
        "blocks": blocks,
    }


def test_tracker_bundle_reads_only_loopback_get_and_compacts_evidence() -> None:
    with patch.object(tracker_research_tools, "get_config", return_value=_config()), patch(
        "src.services.tracker_research_client.urlopen",
        return_value=_Response(_bundle()),
    ) as request:
        result = tracker_research_tools._handle_get_tracker_research_bundle("005930.KS")

    assert result["status"] == "available"
    assert result["market"] == "KOSPI"
    assert result["blocks"]["DART"]["status"] == "FRESH"
    assert result["blocks"]["NEWS_HEADLINES"]["summary"]["value"] == "evidence"
    sent_request = request.call_args.args[0]
    assert sent_request.method == "GET"
    assert sent_request.full_url.startswith(
        "http://127.0.0.1:47832/v1/research/stocks/005930.KS/bundle?"
    )
    assert "capturedAtOrBefore=" in sent_request.full_url
    assert sent_request.get_header("Authorization") == f"Bearer {'a' * 32}"


def test_tracker_bundle_never_calls_network_when_not_configured_or_not_krx() -> None:
    with patch(
        "src.services.tracker_research_client.urlopen",
        side_effect=AssertionError("network must not be called"),
    ) as request, patch.object(
        tracker_research_tools,
        "get_config",
        return_value=_config(tracker_research_api_token=""),
    ):
        unconfigured = tracker_research_tools._handle_get_tracker_research_bundle("005930.KS")
        not_applicable = tracker_research_tools._handle_get_tracker_research_bundle("AAPL")

    assert unconfigured["reason"] == "tracker_research_not_configured"
    assert not_applicable["status"] == "not_applicable"
    request.assert_not_called()


def test_tracker_bundle_hides_http_failure_details_and_rejects_non_loopback_url() -> None:
    with patch.object(
        tracker_research_tools,
        "get_config",
        return_value=_config(tracker_research_api_url="http://example.test:47832"),
    ), patch(
        "src.services.tracker_research_client.urlopen",
        side_effect=AssertionError("network must not be called"),
    ) as request:
        invalid_url = tracker_research_tools._handle_get_tracker_research_bundle("005930.KS")

    assert invalid_url["reason"] == "tracker_research_configuration_invalid"
    request.assert_not_called()

    with patch.object(tracker_research_tools, "get_config", return_value=_config()), patch(
        "src.services.tracker_research_client.urlopen",
        side_effect=HTTPError("http://127.0.0.1:47832", 503, "unavailable", {}, None),
    ):
        failed = tracker_research_tools._handle_get_tracker_research_bundle("005930.KS")

    assert failed == {
        "status": "unavailable",
        "source": "tracker_research_bundle",
        "reason": "tracker_research_http_error",
    }


def test_tracker_bundle_rejects_mismatched_or_incomplete_contract() -> None:
    mismatched = _bundle()
    mismatched["symbol"] = "035420"
    with patch.object(tracker_research_tools, "get_config", return_value=_config()), patch(
        "src.services.tracker_research_client.urlopen",
        return_value=_Response(mismatched),
    ):
        result = tracker_research_tools._handle_get_tracker_research_bundle("005930.KS")

    assert result["reason"] == "tracker_research_response_invalid"


def test_tracker_bundle_is_explicitly_process_isolation_safe() -> None:
    policy = tracker_research_tools.get_tracker_research_bundle_tool.policy

    assert policy.read_only is True
    assert policy.process_isolation_safe is True
    assert policy.cancellation_safe is False
