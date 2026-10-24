# -*- coding: utf-8 -*-
"""Docs contract checks for the #1910 Cross-Asset Context section (T20).

Mirrors tests/test_analysis_context_pack_docs.py: the docs must explain the
supported assets, field semantics, degradation behaviour and limitations of
the cross-asset context channel (issue acceptance: "文档说明支持资产、字段
语义、降级行为和限制").
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = PROJECT_ROOT / "docs" / "analysis-context-pack.md"
CHANGELOG_PATH = PROJECT_ROOT / "docs" / "CHANGELOG.md"

SECTION_HEADING = "## #1910 Cross-Asset Context"


def _read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def _section() -> str:
    doc = _read_doc()
    assert SECTION_HEADING in doc
    return doc.split(SECTION_HEADING, 1)[1].split("\n## ", 1)[0]


def test_cross_asset_doc_section_exists() -> None:
    assert SECTION_HEADING in _read_doc()


def test_cross_asset_doc_states_maintainer_boundary_and_switch() -> None:
    section = _section()

    for token in (
        "risk_appetite",
        "不直接变成买卖规则",  # calibration-only boundary
        "CROSS_ASSET_CONTEXT_ENABLED",
        "CROSS_ASSET_CONTEXT_TIMEOUT_SECONDS",
        "CROSS_ASSET_CONTEXT_STALE_DAYS",
        "_load_cross_asset_context",
    ):
        assert token in section


def test_cross_asset_doc_defines_contract_and_field_semantics() -> None:
    section = _section()

    for token in (
        "cross-asset-v1",
        "src/schemas/cross_asset_context.py",
        "schema_version",
        "risk_on|neutral|risk_off|unknown",
        "indices/fx/rates/commodities/crypto/volatility",
        "sector_links",
        "impact_summary",
        "risk_tags",
        "data_quality",
        "source/as_of/stale/error",  # mandatory quality quadruple
        "to_safe_dict()",
    ):
        assert token in section


def test_cross_asset_doc_lists_supported_assets() -> None:
    section = _section()

    for token in (
        "支持资产",
        "上证",
        "^HSI",  # hk index family
        "^GSPC",  # us index family
        "^VIX",
        "^TNX",  # US 10Y rates
        "GC=F",
        "CL=F",
        "HG=F",  # gold / oil / copper
        "BTC",
        "USD/CNH",
        "data_provider/cross_asset_fetcher.py",
        "src/services/cross_asset_context_service.py",
    ):
        assert token in section


def test_cross_asset_doc_records_injection_chain_and_guardrail() -> None:
    section = _section()

    for token in (
        "_attach_cross_asset_context",
        "cross_asset_context_summary",
        "外围环境与跨资产",
        "AgentExecutor._build_user_message",
        "RiskAgent",
        "apply_cross_asset_context_guardrail",
        "decision_type",  # guardrail never touches the decision type
    ):
        assert token in section


def test_cross_asset_doc_defines_degradation_behaviour() -> None:
    section = _section()

    for token in (
        "四级降级语义",
        "fail-open",
        "unknown",
        "not_supported",
        "不抓数、不注入 prompt、不触发 guardrail",
    ):
        assert token in section


def test_cross_asset_doc_records_snapshot_api_and_limitations() -> None:
    section = _section()

    for token in (
        "cross_asset_context_summary",  # snapshot + API meta passthrough
        "report.meta",
        "risk_appetite",  # decision-signal metadata reservation
        "risk_tags",
        "限制：",
        "as_of",
        "stale",
        "收盘",  # stale/delayed data caveat
        "不做 Web 展示",
        "不承诺实时全市场覆盖",
    ):
        assert token in section


def test_cross_asset_doc_changelog_entry_exists() -> None:
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    assert "#1910" in changelog
    assert "跨资产" in changelog
