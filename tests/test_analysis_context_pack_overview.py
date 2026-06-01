# -*- coding: utf-8 -*-
"""Tests for #1389 P4 public AnalysisContextPack overviews."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.analysis_context_pack_overview import (
    extract_analysis_context_pack_overview,
    render_analysis_context_pack_overview,
    sanitize_context_snapshot_for_api,
)
from src.analysis_context_pack_prompt import (
    format_analysis_context_pack_prompt_section,
    iter_analysis_context_pack_block_keys,
)
from src.schemas.analysis_context_pack import (
    AnalysisContextBlock,
    AnalysisContextItem,
    AnalysisContextPack,
    AnalysisSubject,
    ContextFieldStatus,
    DataQuality,
)


def _pack() -> AnalysisContextPack:
    return AnalysisContextPack(
        subject=AnalysisSubject(code="600519", stock_name="贵州茅台", market="cn"),
        created_at=datetime(2026, 4, 10, 8, 30, tzinfo=timezone.utc),
        blocks={
            "news": AnalysisContextBlock(
                status=ContextFieldStatus.MISSING,
                items={
                    "content": AnalysisContextItem(
                        status=ContextFieldStatus.MISSING,
                        value="这是一段不应出现在公共 overview 的完整新闻正文",
                        missing_reason="news_context_missing",
                    ),
                    "freshness": AnalysisContextItem(
                        status=ContextFieldStatus.MISSING,
                        value=None,
                        missing_reason="news_context_missing",
                    ),
                    "provider": AnalysisContextItem(
                        status=ContextFieldStatus.MISSING,
                        value=None,
                        missing_reason="provider_timeout",
                    ),
                    "backup": AnalysisContextItem(
                        status=ContextFieldStatus.MISSING,
                        value=None,
                        missing_reason="backup_unavailable",
                    ),
                    "extra": AnalysisContextItem(
                        status=ContextFieldStatus.MISSING,
                        value=None,
                        missing_reason="extra_reason_not_exposed",
                    ),
                },
            ),
            "quote": AnalysisContextBlock(
                status=ContextFieldStatus.FALLBACK,
                source="fallback_quote_provider",
                warnings=["realtime_provider_fallback"],
                items={
                    "price": AnalysisContextItem(
                        status=ContextFieldStatus.FALLBACK,
                        value=1880.0,
                        source="primary_quote_provider",
                    )
                },
            ),
            "technical": AnalysisContextBlock(
                status=ContextFieldStatus.PARTIAL,
                warnings=["intraday_realtime_overlay"],
                items={
                    "trend_result": AnalysisContextItem(
                        status=ContextFieldStatus.AVAILABLE,
                        value={"trend_status": "多头排列", "ma5": 1800.0},
                    )
                },
            ),
            "fundamentals": AnalysisContextBlock(
                status=ContextFieldStatus.AVAILABLE,
                metadata={"api_key": "secret-key"},
                items={
                    "fundamental_context": AnalysisContextItem(
                        status=ContextFieldStatus.AVAILABLE,
                        value={"pe": 28, "authorization": "Bearer secret"},
                    )
                },
            ),
        },
        data_quality=DataQuality(
            overall_score=76,
            level="usable",
            block_scores={
                "quote": 65,
                "daily_bars": 100,
                "technical": 75,
                "news": 35,
                "fundamentals": 100,
                "chip": 100,
            },
            limitations=["quote: fallback", "technical: partial"],
            warnings=["intraday_realtime_overlay", "intraday_realtime_overlay"]
        ),
        metadata={
            "trigger_source": "api",
            "news_result_count": 3,
            "webhook_url": "https://hooks.example.test/secret",
        },
    )


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys = list(value)
        for child in value.values():
            keys.extend(_walk_keys(child))
        return keys
    if isinstance(value, list):
        keys: list[str] = []
        for child in value:
            keys.extend(_walk_keys(child))
        return keys
    return []


def test_renderer_outputs_only_public_schema_fields() -> None:
    overview = render_analysis_context_pack_overview(_pack(), report_language="zh")

    assert overview is not None
    assert set(overview) == {
        "pack_version",
        "created_at",
        "subject",
        "blocks",
        "counts",
        "data_quality",
        "warnings",
        "metadata",
    }
    assert set(overview["subject"]) == {"code", "stock_name", "market"}
    assert set(overview["metadata"]) == {"trigger_source", "news_result_count"}
    assert set(overview["blocks"][0]) == {
        "key",
        "label",
        "status",
        "source",
        "warnings",
        "missing_reasons",
    }
    assert set(overview["data_quality"]) == {
        "overall_score",
        "level",
        "block_scores",
        "limitations",
    }
    assert overview["data_quality"] == {
        "overall_score": 76,
        "level": "usable",
        "block_scores": {
            "quote": 65,
            "daily_bars": 100,
            "technical": 75,
            "news": 35,
            "fundamentals": 100,
            "chip": 100,
        },
        "limitations": ["quote: fallback", "technical: partial"],
    }


def test_renderer_does_not_dump_items_values_payloads_or_sensitive_markers() -> None:
    overview = render_analysis_context_pack_overview(_pack(), report_language="zh")

    assert overview is not None
    keys = set(_walk_keys(overview))
    assert "items" not in keys
    assert "value" not in keys
    assert "metadata" in keys

    rendered = json.dumps(overview, ensure_ascii=False)
    assert "完整新闻正文" not in rendered
    assert "多头排列" not in rendered
    assert "secret-key" not in rendered
    assert "hooks.example.test" not in rendered
    assert "authorization" not in rendered
    assert "api_key" not in rendered
    assert "webhook_url" not in rendered


def test_counts_are_by_block_status_and_missing_reasons_are_deduped() -> None:
    overview = render_analysis_context_pack_overview(_pack(), report_language="zh")

    assert overview is not None
    assert overview["counts"] == {
        "available": 1,
        "missing": 1,
        "not_supported": 0,
        "fallback": 1,
        "stale": 0,
        "estimated": 0,
        "partial": 1,
        "fetch_failed": 0,
    }
    news_block = next(block for block in overview["blocks"] if block["key"] == "news")
    assert news_block["missing_reasons"] == [
        "news_context_missing",
        "provider_timeout",
        "backup_unavailable",
    ]


def test_labels_follow_report_language_and_prompt_block_order() -> None:
    pack = _pack()
    overview_zh = render_analysis_context_pack_overview(pack, report_language="zh")
    overview_en = render_analysis_context_pack_overview(pack, report_language="en")

    assert overview_zh is not None
    assert overview_en is not None
    assert [block["key"] for block in overview_zh["blocks"]] == iter_analysis_context_pack_block_keys(
        pack.model_dump(mode="json")["blocks"]
    )
    assert [block["label"] for block in overview_zh["blocks"][:3]] == [
        "行情",
        "技术",
        "基本面",
    ]
    assert [block["label"] for block in overview_en["blocks"][:3]] == [
        "quote",
        "technical",
        "fundamentals",
    ]
    prompt = format_analysis_context_pack_prompt_section(pack, report_language="zh")
    assert prompt.index("行情:") < prompt.index("技术:") < prompt.index("基本面:")


def test_extract_and_sanitize_handle_json_snapshot_strings() -> None:
    overview = render_analysis_context_pack_overview(_pack(), report_language="zh")
    snapshot = json.dumps(
        {
            "enhanced_context": {"code": "600519"},
            "analysis_context_pack_overview": overview,
            "market_phase_summary": {"phase": "intraday", "market": "cn"},
        },
        ensure_ascii=False,
    )

    extracted = extract_analysis_context_pack_overview(snapshot)
    sanitized = sanitize_context_snapshot_for_api(snapshot)

    assert extracted is not None
    assert extracted["subject"]["code"] == "600519"
    assert sanitized == {"enhanced_context": {"code": "600519"}}


def test_extract_reprojects_persisted_overview_to_public_schema() -> None:
    snapshot = {
        "analysis_context_pack_overview": {
            "pack_version": "1.0",
            "created_at": "2026-04-10T08:30:00+00:00",
            "subject": {
                "code": "600519",
                "stock_name": "贵州茅台",
                "market": "cn",
                "api_key": "secret-key",
            },
            "blocks": [
                {
                    "key": "quote",
                    "label": "行情",
                    "status": "available",
                    "source": "mock",
                    "warnings": ["ok", "ok"],
                    "missing_reasons": [],
                    "items": {"price": {"value": 1880.0}},
                },
                {
                    "key": "news",
                    "label": "新闻",
                    "status": "missing",
                    "source": None,
                    "warnings": [],
                    "missing_reasons": [
                        "news_context_missing",
                        "provider_timeout",
                        "backup_unavailable",
                        "extra_reason_not_exposed",
                    ],
                    "content": "完整新闻正文不应出现",
                },
            ],
            "counts": {
                "available": 999,
                "missing": 999,
                "not_supported": 999,
                "fallback": 999,
                "stale": 999,
                "estimated": 999,
                "partial": 999,
                "fetch_failed": 999,
            },
            "data_quality": {
                "overall_score": 76,
                "level": "usable",
                "block_scores": {
                    "quote": 65,
                    "news": 35,
                    "api_key": 99,
                    "technical": 999,
                },
                "limitations": [
                    "quote: fallback",
                    "token=secret should not pass",
                    "technical: partial",
                    "technical: partial",
                ],
                "warnings": ["not-public"],
            },
            "warnings": ["top_warning", "top_warning"],
            "metadata": {
                "trigger_source": "api",
                "news_result_count": 3,
                "webhook_url": "https://hooks.example.test/secret",
            },
            "value": "raw payload should not pass through",
        }
    }

    extracted = extract_analysis_context_pack_overview(snapshot)

    assert extracted is not None
    assert extracted["counts"] == {
        "available": 1,
        "missing": 1,
        "not_supported": 0,
        "fallback": 0,
        "stale": 0,
        "estimated": 0,
        "partial": 0,
        "fetch_failed": 0,
    }
    assert extracted["data_quality"] == {
        "overall_score": 76,
        "level": "usable",
        "block_scores": {"quote": 65, "news": 35},
        "limitations": [
            "quote: fallback",
            "[REDACTED]",
            "technical: partial",
        ],
    }
    assert extracted["blocks"][1]["missing_reasons"] == [
        "news_context_missing",
        "provider_timeout",
        "backup_unavailable",
    ]
    rendered = json.dumps(extracted, ensure_ascii=False)
    assert "items" not in rendered
    assert "value" not in rendered
    assert "完整新闻正文" not in rendered
    assert "webhook_url" not in rendered
    assert "hooks.example.test" not in rendered
    assert "secret-key" not in rendered


def test_extract_accepts_legacy_overview_without_data_quality() -> None:
    extracted = extract_analysis_context_pack_overview(
        {
            "analysis_context_pack_overview": {
                "pack_version": "1.0",
                "subject": {"code": "600519"},
                "blocks": [
                    {
                        "key": "quote",
                        "label": "行情",
                        "status": "available",
                        "source": "mock",
                        "warnings": [],
                        "missing_reasons": [],
                    }
                ],
                "metadata": {},
            }
        }
    )

    assert extracted is not None
    assert "data_quality" not in extracted
    assert extracted["counts"]["fetch_failed"] == 0


def test_extract_returns_none_for_malformed_persisted_overview() -> None:
    assert extract_analysis_context_pack_overview(
        {
            "analysis_context_pack_overview": {
                "subject": {"code": "600519"},
                "blocks": [{"key": "quote", "label": "行情", "status": "bad_status"}],
            }
        }
    ) is None
    assert extract_analysis_context_pack_overview(
        {
            "analysis_context_pack_overview": {
                "subject": {"code": "600519"},
                "blocks": "not-a-list",
            }
        }
    ) is None
