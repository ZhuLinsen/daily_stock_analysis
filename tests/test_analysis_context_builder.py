# -*- coding: utf-8 -*-
"""Tests for the Issue #1389 P2 AnalysisContextPack assembler."""

from __future__ import annotations

import builtins
import importlib
from dataclasses import dataclass

import pytest

from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from src.schemas.analysis_context_pack import ContextFieldStatus
import src.services.analysis_context_builder as builder_module
from src.services.analysis_context_builder import (
    AnalysisContextBuilder,
    PipelineAnalysisArtifacts,
)


@dataclass
class _FakeTrend:
    data: dict

    def to_dict(self) -> dict:
        return dict(self.data)


@dataclass
class _FakeChip:
    data: dict

    def to_dict(self) -> dict:
        return dict(self.data)


class _BrokenTrend:
    def to_dict(self) -> dict:
        raise RuntimeError("broken trend artifact")


class _InvalidTrend:
    def to_dict(self) -> list:
        return ["not", "a", "mapping"]


def _quote(
    source: RealtimeSource = RealtimeSource.AKSHARE_EM,
    **overrides,
) -> UnifiedRealtimeQuote:
    return UnifiedRealtimeQuote(
        code="600519",
        name="贵州茅台",
        source=source,
        price=1880.0,
        change_pct=1.2,
        volume_ratio=1.3,
        turnover_rate=0.5,
        **overrides,
    )


def _artifacts(**overrides) -> PipelineAnalysisArtifacts:
    data = {
        "code": "600519",
        "stock_name": "贵州茅台",
        "market": "cn",
        "phase": {"market": "cn", "phase": "intraday"},
        "base_context": {
            "code": "600519",
            "stock_name": "贵州茅台",
            "date": "2026-05-24",
            "today": {"date": "2026-05-24", "close": 1880.0},
            "yesterday": {"date": "2026-05-23", "close": 1860.0},
        },
        "enhanced_context": {
            "today": {"date": "2026-05-24", "close": 1880.0},
        },
        "realtime_quote": _quote(),
        "trend_result": _FakeTrend(
            {
                "trend_status": "多头排列",
                "ma5": 1800.0,
                "ma10": 1780.0,
                "rsi_6": 66.0,
            }
        ),
        "chip_data": _FakeChip(
            {
                "code": "600519",
                "date": "2026-05-24",
                "source": "akshare",
                "profit_ratio": 0.72,
                "avg_cost": 1700.0,
            }
        ),
        "fundamental_context": {
            "status": "ok",
            "coverage": {"valuation": "ok"},
            "source_chain": [{"provider": "fundamental_pipeline", "result": "ok"}],
        },
        "news_context": "公司公告与行业新闻摘要",
        "news_result_count": 3,
        "metadata": {"query_id": "q-1", "trigger_source": "api"},
    }
    data.update(overrides)
    return PipelineAnalysisArtifacts(**data)


def test_quote_block_maps_available_missing_fallback_and_explicit_stale() -> None:
    available = AnalysisContextBuilder.build(_artifacts()).blocks["quote"]
    assert available.status == ContextFieldStatus.AVAILABLE
    assert available.source == "akshare_em"
    assert available.items["price"].value == 1880.0

    missing = AnalysisContextBuilder.build(
        _artifacts(realtime_quote=None)
    ).blocks["quote"]
    assert missing.status == ContextFieldStatus.MISSING
    assert missing.items["quote"].missing_reason == "realtime_quote_missing"

    fallback = AnalysisContextBuilder.build(
        _artifacts(realtime_quote=_quote(RealtimeSource.FALLBACK))
    ).blocks["quote"]
    assert fallback.status == ContextFieldStatus.FALLBACK
    assert "realtime_provider_fallback" in fallback.warnings
    assert fallback.items["price"].fallback_from is None

    explicit_fallback = AnalysisContextBuilder.build(
        _artifacts(
            realtime_quote={
                "source": "fallback",
                "price": 1870.0,
                "fallback_from": "primary_realtime_provider",
            }
        )
    ).blocks["quote"]
    assert explicit_fallback.status == ContextFieldStatus.FALLBACK
    assert explicit_fallback.items["price"].fallback_from == "primary_realtime_provider"
    assert "realtime_provider_fallback" not in explicit_fallback.warnings

    stale = AnalysisContextBuilder.build(
        _artifacts(metadata={"query_id": "q-1", "price_stale": True})
    ).blocks["quote"]
    assert stale.status == ContextFieldStatus.STALE
    assert stale.metadata["price_stale"] is True
    assert "quote_stale" in stale.warnings


def test_quote_block_maps_realtime_metadata_and_status_priority() -> None:
    fallback = AnalysisContextBuilder.build(
        _artifacts(
            realtime_quote=_quote(
                fetched_at="2026-05-31T10:00:05+00:00",
                provider_timestamp="2026-05-31T10:00:00+00:00",
                is_stale=False,
                stale_seconds=5,
                fallback_from="efinance",
            )
        )
    ).blocks["quote"]

    assert fallback.status == ContextFieldStatus.FALLBACK
    assert fallback.source == "akshare_em"
    assert fallback.timestamp == "2026-05-31T10:00:00+00:00"
    assert fallback.items["price"].timestamp == "2026-05-31T10:00:00+00:00"
    assert fallback.items["price"].fallback_from == "efinance"
    assert fallback.metadata["fetched_at"] == "2026-05-31T10:00:05+00:00"
    assert fallback.metadata["provider_timestamp"] == "2026-05-31T10:00:00+00:00"
    assert fallback.metadata["is_stale"] is False
    assert fallback.metadata["stale_seconds"] == 5
    assert fallback.metadata["fallback_from"] == "efinance"

    stale = AnalysisContextBuilder.build(
        _artifacts(
            realtime_quote=_quote(
                fetched_at="2026-05-31T10:15:00+00:00",
                provider_timestamp="2026-05-31T10:00:00+00:00",
                is_stale=True,
                stale_seconds=900,
                fallback_from="efinance",
            )
        )
    ).blocks["quote"]

    assert stale.status == ContextFieldStatus.STALE
    assert stale.source == "akshare_em"
    assert stale.items["price"].fallback_from == "efinance"
    assert "quote_stale" in stale.warnings


def test_quote_block_ignores_invalid_or_legacy_timestamp_metadata() -> None:
    block = AnalysisContextBuilder.build(
        _artifacts(
            realtime_quote={
                "source": "akshare_em",
                "price": 1870.0,
                "provider_timestamp": "not-a-date",
                "fetched_at": "2026-05-31T10:00:05+00:00",
                "timestamp": 0,
            }
        )
    ).blocks["quote"]

    assert block.status == ContextFieldStatus.AVAILABLE
    assert block.timestamp == "2026-05-31T10:00:05+00:00"
    assert block.items["price"].timestamp == "2026-05-31T10:00:05+00:00"
    assert block.metadata["fetched_at"] == "2026-05-31T10:00:05+00:00"
    assert "provider_timestamp" not in block.metadata

    legacy_timestamp_only = AnalysisContextBuilder.build(
        _artifacts(
            realtime_quote={
                "source": "akshare_em",
                "price": 1870.0,
                "timestamp": 0,
            }
        )
    ).blocks["quote"]
    assert legacy_timestamp_only.timestamp is None
    assert legacy_timestamp_only.items["price"].timestamp is None

    space_separated_timestamp = AnalysisContextBuilder.build(
        _artifacts(
            realtime_quote={
                "source": "akshare_em",
                "price": 1870.0,
                "provider_timestamp": "2026-05-31 10:00:00",
            }
        )
    ).blocks["quote"]
    assert space_separated_timestamp.timestamp is None
    assert space_separated_timestamp.items["price"].timestamp is None


def test_daily_bars_uses_base_context_and_keeps_dates_out_of_timestamp() -> None:
    pack = AnalysisContextBuilder.build(
        _artifacts(
            base_context={
                "code": "600519",
                "stock_name": "贵州茅台",
                "date": "2026-05-24",
                "data_missing": True,
                "today": {},
                "yesterday": {},
            },
            enhanced_context={
                "today": {
                    "date": "2026-05-26",
                    "close": 1900.0,
                    "data_source": "realtime:akshare_em",
                }
            },
        )
    )

    block = pack.blocks["daily_bars"]
    dumped = block.model_dump(mode="json")

    assert block.status == ContextFieldStatus.MISSING
    assert block.metadata["date"] == "2026-05-24"
    assert all(item["timestamp"] is None for item in dumped["items"].values())
    assert dumped["items"]["today"]["metadata"]["date"] == "2026-05-24"

    date_only = AnalysisContextBuilder.build(
        _artifacts(
            base_context={
                "date": "2026-05-24",
                "today": {},
                "yesterday": {},
            }
        )
    ).blocks["daily_bars"]
    assert date_only.status == ContextFieldStatus.MISSING
    assert date_only.items["date"].status == ContextFieldStatus.AVAILABLE

    one_bar = AnalysisContextBuilder.build(
        _artifacts(
            base_context={
                "date": "2026-05-24",
                "today": {"date": "2026-05-24", "close": 1880.0},
                "yesterday": {},
            }
        )
    ).blocks["daily_bars"]
    assert one_bar.status == ContextFieldStatus.PARTIAL


def test_technical_missing_and_realtime_overlay_statuses_are_explicit() -> None:
    missing = AnalysisContextBuilder.build(
        _artifacts(trend_result=None)
    ).blocks["technical"]
    assert missing.status == ContextFieldStatus.MISSING
    assert missing.items["trend_result"].missing_reason == "trend_result_missing"

    pack = AnalysisContextBuilder.build(
        _artifacts(
            enhanced_context={
                "today": {
                    "close": 1880.0,
                    "data_source": "realtime:akshare_em",
                }
            }
        )
    )
    block = pack.blocks["technical"]

    assert block.status == ContextFieldStatus.PARTIAL
    assert block.items["trend_result"].status == ContextFieldStatus.AVAILABLE
    assert block.items["intraday_overlay"].status == ContextFieldStatus.ESTIMATED
    assert "intraday_realtime_overlay" in block.warnings
    assert "intraday_realtime_overlay" in pack.data_quality.warnings

    explicit_pack = AnalysisContextBuilder.build(
        _artifacts(
            enhanced_context={
                "today": {
                    "close": 1880.0,
                    "is_partial_bar": True,
                    "is_estimated": True,
                    "estimated_fields": ["close", "ma5"],
                }
            }
        )
    )
    explicit_block = explicit_pack.blocks["technical"]

    assert explicit_block.status == ContextFieldStatus.PARTIAL
    assert explicit_block.items["intraday_overlay"].status == ContextFieldStatus.ESTIMATED
    assert explicit_block.metadata["is_partial_bar"] is True
    assert explicit_block.metadata["is_estimated"] is True
    assert explicit_block.metadata["estimated_fields"] == ["close", "ma5"]


def test_chip_missing_defaults_to_missing_and_explicit_not_supported() -> None:
    missing = AnalysisContextBuilder.build(_artifacts(chip_data=None)).blocks["chip"]
    assert missing.status == ContextFieldStatus.MISSING
    assert (
        missing.items["chip_distribution"].missing_reason
        == "chip_distribution_missing"
    )

    not_supported = AnalysisContextBuilder.build(
        _artifacts(chip_data=None, metadata={"chip_not_supported": True})
    ).blocks["chip"]
    assert not_supported.status == ContextFieldStatus.NOT_SUPPORTED
    assert (
        not_supported.items["chip_distribution"].missing_reason
        == "chip_not_supported"
    )


@pytest.mark.parametrize(
    ("payload_status", "expected_status"),
    (
        ("ok", ContextFieldStatus.AVAILABLE),
        ("not_supported", ContextFieldStatus.NOT_SUPPORTED),
        ("partial", ContextFieldStatus.PARTIAL),
        ("failed", ContextFieldStatus.FETCH_FAILED),
    ),
)
def test_fundamentals_maps_supported_statuses_without_raw_errors(
    payload_status: str,
    expected_status: ContextFieldStatus,
) -> None:
    block = AnalysisContextBuilder.build(
        _artifacts(
            fundamental_context={
                "status": payload_status,
                "coverage": {"valuation": payload_status},
                "source_chain": [
                    {"provider": "fundamental_pipeline", "result": payload_status}
                ],
                "errors": ["token=secret should not be persisted"],
            }
        )
    ).blocks["fundamentals"]

    assert block.status == expected_status
    assert block.metadata["coverage"] == {"valuation": payload_status}
    assert block.items["coverage"].status == expected_status
    assert block.items["source_chain"].status == expected_status
    assert "errors" not in block.metadata
    assert "token=secret" not in str(block.model_dump(mode="json"))
    if payload_status == "failed":
        assert block.items["status"].missing_reason == "fundamental_pipeline_failed"
        assert block.items["coverage"].missing_reason == "fundamental_pipeline_failed"
        assert (
            block.items["source_chain"].missing_reason
            == "fundamental_pipeline_failed"
        )


def test_builder_does_not_hide_broken_artifact_to_dict() -> None:
    with pytest.raises(RuntimeError, match="broken trend artifact"):
        AnalysisContextBuilder.build(_artifacts(trend_result=_BrokenTrend()))


def test_builder_rejects_non_mapping_artifact_to_dict() -> None:
    with pytest.raises(TypeError, match="to_dict\\(\\) must return a mapping"):
        AnalysisContextBuilder.build(_artifacts(trend_result=_InvalidTrend()))


def test_news_block_treats_blank_as_missing_and_records_pack_metadata() -> None:
    blank = AnalysisContextBuilder.build(
        _artifacts(news_context="  ", news_result_count=0)
    )
    assert blank.blocks["news"].status == ContextFieldStatus.MISSING
    assert blank.metadata["news_result_count"] == 0

    available = AnalysisContextBuilder.build(
        _artifacts(news_context="news", news_result_count=5)
    )
    assert available.blocks["news"].status == ContextFieldStatus.AVAILABLE
    assert available.blocks["news"].items["content"].value == "news"
    assert available.metadata["news_result_count"] == 5


def test_data_quality_scores_fixed_blocks_and_limits_auxiliary_missing() -> None:
    pack = AnalysisContextBuilder.build(_artifacts())

    assert pack.data_quality.overall_score == 100
    assert pack.data_quality.level == "good"
    assert pack.data_quality.block_scores == {
        "quote": 100,
        "daily_bars": 100,
        "technical": 100,
        "news": 100,
        "fundamentals": 100,
        "chip": 100,
    }
    assert pack.data_quality.limitations == []

    failed_fundamentals = AnalysisContextBuilder.build(
        _artifacts(
            fundamental_context={
                "status": "failed",
                "coverage": {"valuation": "failed"},
                "source_chain": [
                    {"provider": "fundamental_pipeline", "result": "failed"}
                ],
            }
        )
    )
    assert failed_fundamentals.blocks["fundamentals"].status == ContextFieldStatus.FETCH_FAILED
    assert failed_fundamentals.data_quality.block_scores["fundamentals"] == 25
    assert failed_fundamentals.data_quality.overall_score == 92
    assert failed_fundamentals.data_quality.level == "good"
    assert failed_fundamentals.data_quality.limitations == ["fundamentals: fetch_failed"]

    blank_news = AnalysisContextBuilder.build(
        _artifacts(news_context="  ", news_result_count=0)
    )
    assert blank_news.blocks["news"].status == ContextFieldStatus.MISSING
    assert blank_news.data_quality.block_scores["news"] == 35
    assert "news: missing" not in blank_news.data_quality.limitations


def test_build_batch_returns_one_pack_per_artifact() -> None:
    packs = AnalysisContextBuilder.build_batch(
        [
            _artifacts(code="600519", stock_name="贵州茅台"),
            _artifacts(code="000001", stock_name="平安银行"),
        ]
    )

    assert [pack.subject.code for pack in packs] == ["600519", "000001"]


def test_builder_output_safe_dict_redacts_sensitive_mapping_keys() -> None:
    pack = AnalysisContextBuilder.build(
        _artifacts(
            metadata={
                "query_id": "q-1",
                "webhook_url": "https://hooks.example.test/secret",
            },
            fundamental_context={
                "status": "ok",
                "coverage": {
                    "valuation": "ok",
                    "access_token": "secret-token",
                },
                "source_chain": [{"provider": "fundamental_pipeline"}],
            },
        )
    )

    safe = pack.to_safe_dict()

    assert safe["metadata"]["webhook_url"] == "[REDACTED]"
    assert (
        safe["blocks"]["fundamentals"]["metadata"]["coverage"]["access_token"]
        == "[REDACTED]"
    )
    assert safe["blocks"]["fundamentals"]["metadata"]["coverage"]["valuation"] == "ok"


def test_builder_module_stays_zero_fetch_and_zero_storage_import(monkeypatch) -> None:
    forbidden_modules = (
        "data_provider",
        "fetcher_manager",
        "search_service",
        "src.storage",
        "src.services.search_service",
        "src.repositories",
        "src.database",
    )
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and any(
            name == module or name.startswith(f"{module}.")
            for module in forbidden_modules
        ):
            raise AssertionError(f"unexpected zero-fetch import: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    reloaded = importlib.reload(builder_module)
    pack = reloaded.AnalysisContextBuilder.build(_artifacts())

    assert pack.blocks["quote"].status == ContextFieldStatus.AVAILABLE
