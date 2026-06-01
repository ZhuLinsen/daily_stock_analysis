# -*- coding: utf-8 -*-
"""Regression tests for Issue #1386 P1b market phase summary."""

import json

from src.market_phase_summary import (
    MARKET_PHASE_SUMMARY_KEY,
    extract_market_phase_summary,
    render_market_phase_summary,
)


SUMMARY_KEYS = {
    "market",
    "phase",
    "market_local_time",
    "session_date",
    "effective_daily_bar_date",
    "is_trading_day",
    "is_market_open_now",
    "is_partial_bar",
    "minutes_to_open",
    "minutes_to_close",
    "trigger_source",
    "analysis_intent",
    "warnings",
}


def _phase_context() -> dict:
    return {
        "market": "cn",
        "phase": "intraday",
        "market_local_time": "2026-03-27T10:00:00+08:00",
        "session_date": "2026-03-27",
        "effective_daily_bar_date": "2026-03-26",
        "is_trading_day": True,
        "is_market_open_now": True,
        "is_partial_bar": True,
        "minutes_to_open": None,
        "minutes_to_close": 300,
        "trigger_source": "api",
        "analysis_intent": "auto",
        "warnings": ["partial_bar", "partial_bar"],
    }


def test_render_market_phase_summary_outputs_only_public_whitelist() -> None:
    payload = {
        **_phase_context(),
        "market_phase_context": {"raw": True},
        "analysis_context_pack_summary": "prompt text should not be exposed",
        "analysis_context_pack": {"blocks": {"quote": {"items": {"value": 1}}}},
        "quote_freshness": "fresh",
        "data_quality_score": 100,
    }

    summary = render_market_phase_summary(payload)

    assert summary is not None
    assert set(summary) == SUMMARY_KEYS
    assert summary["phase"] == "intraday"
    assert summary["minutes_to_close"] == 300
    assert summary["warnings"] == ["partial_bar"]
    rendered = json.dumps(summary, ensure_ascii=False)
    assert "market_phase_context" not in rendered
    assert "analysis_context_pack_summary" not in rendered
    assert "prompt text" not in rendered
    assert "quote_freshness" not in rendered
    assert "data_quality_score" not in rendered


def test_extract_market_phase_summary_re_sanitizes_persisted_snapshot() -> None:
    summary = {
        **_phase_context(),
        "prompt": "raw prompt should not pass through",
        "market_phase_context": {"raw": True},
        "quote_timestamp": "2026-03-27T10:00:00+08:00",
        "fallback_provider": "secret-provider",
        "trigger_source": {"prompt": "raw prompt should not pass through"},
        "analysis_intent": "api_key=secret",
    }
    snapshot = json.dumps(
        {
            MARKET_PHASE_SUMMARY_KEY: summary,
            "enhanced_context": {"code": "600519"},
        },
        ensure_ascii=False,
    )

    extracted = extract_market_phase_summary(snapshot)

    assert extracted is not None
    assert set(extracted) == SUMMARY_KEYS
    assert extracted["phase"] == "intraday"
    assert extracted["trigger_source"] is None
    assert extracted["analysis_intent"] == "[REDACTED]"
    assert "prompt" not in extracted
    assert "market_phase_context" not in extracted
    assert "quote_timestamp" not in extracted
    assert "fallback_provider" not in extracted


def test_extract_market_phase_summary_returns_none_for_missing_or_malformed_snapshot() -> None:
    assert extract_market_phase_summary(None) is None
    assert extract_market_phase_summary({"enhanced_context": {"code": "600519"}}) is None
    assert extract_market_phase_summary({MARKET_PHASE_SUMMARY_KEY: "not-a-dict"}) is None
    assert extract_market_phase_summary(
        {MARKET_PHASE_SUMMARY_KEY: {**_phase_context(), "phase": "bad_phase"}}
    ) is None
    assert extract_market_phase_summary("not-json") is None
