# -*- coding: utf-8 -*-
"""Read-only Tracker research evidence tools for Korean stock analysis.

Tracker owns the optional sidecar and its refresh queue.  DSA deliberately
uses only its bounded ``GET /bundle`` endpoint here: an Agent query must never
enqueue a Tracker refresh or write Tracker operational storage.
"""

from __future__ import annotations

from src.agent.news_evidence import record_news_evidence
from src.agent.tools.execution import check_tool_execution
from src.agent.tools.registry import ToolDefinition, ToolParameter, ToolPolicy
from src.config import get_config
from src.services.tracker_research_client import (
    TRACKER_RESEARCH_BLOCK_SOURCES,
    TRACKER_RESEARCH_BUNDLE_SOURCE,
    create_tracker_research_client,
    tracker_news_evidence_key,
    tracker_news_headline_count,
    tracker_research_target,
)


# Backwards-compatible private alias retained for focused tool tests.
_TRACKER_BLOCK_SOURCES = TRACKER_RESEARCH_BLOCK_SOURCES
_TRACKER_RESEARCH_POLICY = ToolPolicy.declared(
    read_only=True,
    side_effects=["network_read"],
    permissions=["tracker_research:read"],
    scope_dimensions=["stock"],
    process_isolation_safe=True,
)


def _handle_get_tracker_research_bundle(stock_code: str) -> dict:
    """Fetch Tracker's already-stored Korean-stock research evidence only."""
    check_tool_execution()
    target = tracker_research_target(stock_code)
    if target is None:
        return {
            "status": "not_applicable",
            "source": TRACKER_RESEARCH_BUNDLE_SOURCE,
            "reason": "krx_ticker_required",
            "note": "Tracker research supports six-digit .KS and .KQ tickers only.",
        }
    client, reason = create_tracker_research_client(get_config())
    if client is None:
        return {
            "status": "unavailable",
            "source": TRACKER_RESEARCH_BUNDLE_SOURCE,
            "reason": reason,
        }
    result = client.read_bundle(stock_code)
    check_tool_execution()
    if result.get("status") == "available":
        record_news_evidence(
            tracker_news_headline_count(result),
            source_key=tracker_news_evidence_key(result),
        )
    return result


get_tracker_research_bundle_tool = ToolDefinition(
    name="get_tracker_research_bundle",
    description=(
        "Read Tracker's bounded, advisory Korean-stock research bundle for a .KS or .KQ ticker. "
        "The tool only reads previously stored evidence such as market data, DART, flows, KRX status, "
        "disclosure headlines, and news headlines; it never refreshes Tracker or writes operational data."
    ),
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="KRX ticker with suffix, e.g. '005930.KS' or '035720.KQ'.",
        ),
    ],
    handler=_handle_get_tracker_research_bundle,
    category="data",
    policy=_TRACKER_RESEARCH_POLICY,
)


ALL_TRACKER_RESEARCH_TOOLS = [get_tracker_research_bundle_tool]
