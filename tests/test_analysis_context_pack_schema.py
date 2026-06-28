# -*- coding: utf-8 -*-
"""Tests for the Issue #1389 P1 AnalysisContextPack schema."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.core.trading_calendar import build_market_phase_context
from src.schemas.analysis_context_pack import (
    PACK_VERSION,
    AnalysisContextBlock,
    AnalysisContextItem,
    AnalysisContextPack,
    AnalysisSubject,
    ContextFieldStatus,
    DataQuality,
)
from src.utils.sanitize import redact_sensitive_mapping


def _subject() -> AnalysisSubject:
    return AnalysisSubject(code="600519", stock_name="贵州茅台", market="cn")


def test_pack_defaults_and_json_serialization_are_stable() -> None:
    pack = AnalysisContextPack(
        subject=_subject(),
        created_at=datetime(2026, 5, 24, 9, 30, tzinfo=timezone.utc),
    )

    dumped = pack.model_dump(mode="json")
    json.dumps(dumped, ensure_ascii=False)

    assert dumped["pack_version"] == PACK_VERSION
    assert dumped["subject"] == {
        "code": "600519",
        "stock_name": "贵州茅台",
        "market": "cn",
    }
    assert dumped["blocks"] == {}
    assert dumped["data_quality"] == {
        "overall_score": None,
        "level": None,
        "block_scores": {},
        "limitations": [],
        "warnings": [],
        "metadata": {},
    }
    assert dumped["metadata"] == {}
    assert dumped["created_at"] == "2026-05-24T09:30:00Z"


def test_pack_version_is_fixed_to_p1_contract() -> None:
    pack = AnalysisContextPack(subject=_subject())

    assert pack.pack_version == PACK_VERSION

    with pytest.raises(ValidationError):
        AnalysisContextPack(subject=_subject(), pack_version="2.0")

    with pytest.raises(ValidationError):
        pack.pack_version = "2.0"

    with pytest.raises(ValidationError):
        pack.model_copy(update={"pack_version": "2.0"})

    copied = pack.model_copy(update={"metadata": {"trace_id": "q-1"}})

    assert copied.pack_version == PACK_VERSION
    assert copied.metadata == {"trace_id": "q-1"}
    assert pack.to_safe_dict()["pack_version"] == PACK_VERSION


def test_pack_model_copy_preserves_shallow_copy_semantics() -> None:
    block = AnalysisContextBlock(
        status=ContextFieldStatus.AVAILABLE,
        items={
            "price": AnalysisContextItem(
                status=ContextFieldStatus.AVAILABLE,
                value=1880.0,
            )
        },
    )
    pack = AnalysisContextPack(subject=_subject(), blocks={"quote": block})

    copied = pack.model_copy(update={"metadata": {"trace_id": "q-1"}})

    assert copied.blocks is pack.blocks
    assert copied.blocks["quote"] is block
    assert copied.metadata == {"trace_id": "q-1"}


@pytest.mark.parametrize(
    ("item_ts", "block_ts"),
    (
        ("2026-05-24T09:30:00+08:00", "2026-05-24T09:30:01+08:00"),
        ("2026-05-24T01:30:00Z", "2026-05-24T01:30:01Z"),
    ),
)
def test_item_and_block_timestamp_use_iso_strings(
    item_ts: str,
    block_ts: str,
) -> None:
    item = AnalysisContextItem(
        status=ContextFieldStatus.AVAILABLE,
        value=1880.0,
        timestamp=item_ts,
    )
    block = AnalysisContextBlock(
        status=ContextFieldStatus.AVAILABLE,
        items={"price": item},
        timestamp=block_ts,
    )

    dumped = block.model_dump(mode="json")

    assert dumped["timestamp"] == block_ts
    assert dumped["items"]["price"]["timestamp"] == item_ts


@pytest.mark.parametrize("timestamp", ("yesterday", "2026/05/24", "2026-05-24"))
def test_item_and_block_timestamp_reject_non_iso_datetime_strings(
    timestamp: str,
) -> None:
    with pytest.raises(ValidationError):
        AnalysisContextItem(status=ContextFieldStatus.AVAILABLE, timestamp=timestamp)

    with pytest.raises(ValidationError):
        AnalysisContextBlock(status=ContextFieldStatus.AVAILABLE, timestamp=timestamp)


def test_item_and_block_reject_invalid_assignment_updates() -> None:
    item = AnalysisContextItem(
        status=ContextFieldStatus.AVAILABLE,
        timestamp="2026-05-24T09:30:00+08:00",
    )
    block = AnalysisContextBlock(
        status=ContextFieldStatus.AVAILABLE,
        items={"price": item},
        timestamp="2026-05-24T09:30:01+08:00",
    )

    with pytest.raises(ValidationError):
        item.timestamp = "yesterday"

    item.status = "fetch_failed"

    with pytest.raises(ValidationError):
        block.timestamp = "2026/05/24"

    block.status = "fetch_failed"

    with pytest.raises(ValidationError):
        item.status = "bad_status"

    with pytest.raises(ValidationError):
        block.status = "bad_status"

    assert item.timestamp == "2026-05-24T09:30:00+08:00"
    assert item.status == ContextFieldStatus.FETCH_FAILED
    assert block.timestamp == "2026-05-24T09:30:01+08:00"
    assert block.status == ContextFieldStatus.FETCH_FAILED


def test_context_field_status_allows_current_quality_states() -> None:
    for state in (
        "available",
        "missing",
        "not_supported",
        "fallback",
        "stale",
        "estimated",
        "partial",
        "fetch_failed",
    ):
        assert ContextFieldStatus(state).value == state

    with pytest.raises(ValueError):
        ContextFieldStatus("bad_status")

    with pytest.raises(ValidationError):
        AnalysisContextItem(status="bad_status")


def test_market_phase_context_dict_can_be_used_as_phase_slot() -> None:
    phase = build_market_phase_context(
        market="cn",
        current_time=datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
        trigger_source="system",
        analysis_intent="auto",
    ).to_dict()
    pack = AnalysisContextPack(subject=_subject(), phase=phase)

    assert pack.phase == phase
    assert isinstance(pack.model_dump(mode="json")["phase"], dict)


def test_block_and_item_status_are_independent_contract_fields() -> None:
    block = AnalysisContextBlock(
        status=ContextFieldStatus.PARTIAL,
        items={
            "price": AnalysisContextItem(
                status=ContextFieldStatus.AVAILABLE,
                value=1880.0,
            ),
            "turnover_rate": AnalysisContextItem(
                status=ContextFieldStatus.MISSING,
                missing_reason="provider_empty",
            ),
        },
    )

    dumped = block.model_dump(mode="json")

    assert dumped["status"] == "partial"
    assert dumped["items"]["price"]["status"] == "available"
    assert dumped["items"]["turnover_rate"]["status"] == "missing"


def test_data_quality_serializes_p5_scoring_fields_and_legacy_fields() -> None:
    data_quality = DataQuality(
        overall_score=72,
        level="usable",
        block_scores={"quote": 65},
        limitations=["quote: fallback"],
        warnings=["quote_stale"],
        metadata={"note": "P5 scoring is low sensitivity"},
    )

    assert data_quality.model_dump(mode="json") == {
        "overall_score": 72,
        "level": "usable",
        "block_scores": {"quote": 65},
        "limitations": ["quote: fallback"],
        "warnings": ["quote_stale"],
        "metadata": {"note": "P5 scoring is low sensitivity"},
    }


def test_redact_sensitive_mapping_recurses_dicts_and_lists_by_key() -> None:
    payload = {
        "API_KEY": "ak-secret",
        "OPENAI_API_KEY": "openai-secret",
        "GEMINI_API_KEY": "gemini-secret",
        "openai_api_key_value": "openai-secret-value",
        "vendorsecretkey": "vendor-secret-key",
        "apitoken": "api-token-secret",
        "secretvalue": "secret-value",
        "passwordvalue": "password-value",
        "tokenvalue": "token-value",
        "data_api": "akshare",
        "dataApi": "akshare-camel",
        "api_url": "https://example.test/data",
        "prompt_tokens": 42,
        "input_tokens": 11,
        "output_tokens": 12,
        "total_tokens": 23,
        "nested": [
            {
                "authorization_header": "Bearer token",
                "authorizationHeader": "Bearer camel-token",
                "license_key": "license-secret",
                "vendor_license_key": "vendor-license-secret",
                "source": "provider",
            },
            {
                "webhook_url": "https://hooks.example.test/abc",
                "send_key": "send-key-secret",
                "sessionToken": "session-token-secret",
                "normal": "kept",
            },
        ],
        "metadata": {"Cookie": "session=abc", "count": 1},
    }

    redacted = redact_sensitive_mapping(payload)

    assert redacted["API_KEY"] == "[REDACTED]"
    assert redacted["OPENAI_API_KEY"] == "[REDACTED]"
    assert redacted["GEMINI_API_KEY"] == "[REDACTED]"
    assert redacted["openai_api_key_value"] == "[REDACTED]"
    assert redacted["vendorsecretkey"] == "[REDACTED]"
    assert redacted["apitoken"] == "[REDACTED]"
    assert redacted["secretvalue"] == "[REDACTED]"
    assert redacted["passwordvalue"] == "[REDACTED]"
    assert redacted["tokenvalue"] == "[REDACTED]"
    assert redacted["data_api"] == "akshare"
    assert redacted["dataApi"] == "akshare-camel"
    assert redacted["api_url"] == "https://example.test/data"
    assert redacted["prompt_tokens"] == 42
    assert redacted["input_tokens"] == 11
    assert redacted["output_tokens"] == 12
    assert redacted["total_tokens"] == 23
    assert redacted["nested"][0]["authorization_header"] == "[REDACTED]"
    assert redacted["nested"][0]["authorizationHeader"] == "[REDACTED]"
    assert redacted["nested"][0]["license_key"] == "[REDACTED]"
    assert redacted["nested"][0]["vendor_license_key"] == "[REDACTED]"
    assert redacted["nested"][0]["source"] == "provider"
    assert redacted["nested"][1]["webhook_url"] == "[REDACTED]"
    assert redacted["nested"][1]["send_key"] == "[REDACTED]"
    assert redacted["nested"][1]["sessionToken"] == "[REDACTED]"
    assert redacted["nested"][1]["normal"] == "kept"
    assert redacted["metadata"]["Cookie"] == "[REDACTED]"
    assert redacted["metadata"]["count"] == 1


def test_pack_safe_dict_redacts_sensitive_metadata_but_keeps_business_fields() -> None:
    pack = AnalysisContextPack(
        subject=_subject(),
        blocks={
            "quote": AnalysisContextBlock(
                status=ContextFieldStatus.AVAILABLE,
                items={
                    "price": AnalysisContextItem(
                        status=ContextFieldStatus.AVAILABLE,
                        value=1880.0,
                        source="akshare",
                        metadata={"access_token": "secret", "data_api": "kept"},
                    )
                },
            )
        },
        metadata={"webhook_url": "https://hooks.example.test/abc", "trace_id": "q-1"},
    )

    safe = pack.to_safe_dict()

    assert safe["metadata"]["webhook_url"] == "[REDACTED]"
    assert safe["metadata"]["trace_id"] == "q-1"
    price_metadata = safe["blocks"]["quote"]["items"]["price"]["metadata"]
    assert price_metadata["access_token"] == "[REDACTED]"
    assert price_metadata["data_api"] == "kept"
