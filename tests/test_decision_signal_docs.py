# -*- coding: utf-8 -*-
"""Documentation and closeout contract tests for #1390 DecisionSignal P7."""

from __future__ import annotations

import json
from pathlib import Path

from src.services.system_config_service import SystemConfigService


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_decision_signal_topic_references_live_api_schema_and_docs() -> None:
    topic = _read("docs/decision-signals.md")
    alerts = _read("docs/alerts.md")
    notifications = _read("docs/notifications.md")
    full_guide = _read("docs/full-guide.md")
    full_guide_en = _read("docs/full-guide_EN.md")
    index = _read("docs/INDEX.md")
    index_en = _read("docs/INDEX_EN.md")
    api_spec = json.loads(_read("docs/architecture/api_spec.json"))

    for path in (
        "/api/v1/decision-signals",
        "/api/v1/decision-signals/reassess",
        "/api/v1/decision-signals/latest/{stock_code}",
        "/api/v1/decision-signals/outcomes/run",
        "/api/v1/decision-signals/{signal_id}/feedback",
    ):
        assert path in topic
        assert path in api_spec["paths"]

    for schema_name in (
        "DecisionSignalCreateRequest",
        "DecisionSignalItem",
        "DecisionSignalReassessRequest",
        "DecisionSignalReassessResponse",
        "DecisionSignalOutcomeItem",
        "DecisionSignalFeedbackRequest",
        "PortfolioDecisionSignalRiskBlock",
    ):
        assert schema_name in api_spec["components"]["schemas"]

    assert "sanitize_decision_signal_text()" in topic
    assert "sanitize_decision_signal_payload()" in topic
    assert "DECISION_SIGNAL_*" in topic
    assert "revert" in topic
    assert "persist=true" in topic
    assert "guardrail_blocked" in topic
    assert "MIN_ACTIONABLE_CONFIDENCE = 0.5" in topic
    assert "source_agent=decision_profile_reassess" in topic
    assert "trigger_source=web:decision_profile_reassess" in topic
    assert "scoring_breakdown" in topic
    assert "persist_status=created" in topic
    assert "`existing` item 原样保留" in topic
    assert "active relaxed dimension-fill 只补齐缺失的 horizon/market phase" in topic
    assert "HTTP 422" in topic
    assert "decision-signals.md" in full_guide
    assert "decision-signals.md" in full_guide_en
    assert "decision-signals.md" in index
    assert "decision-signals.md" in index_en
    assert "decision-signals.md" in alerts
    assert "decision-signals.md" in notifications
    assert "(source_report_id, source_type, market, stock_code, decision_profile" in full_guide
    assert "(source_report_id, source_type, market, stock_code, decision_profile" in full_guide_en
    assert "顶层显式 `null`、空值或非法值会被拒绝" in full_guide
    assert "top-level explicit `null`, empty value, or invalid value is rejected" in full_guide_en
    assert "metadata 省略或显式 `null` 均按无 metadata 处理" in full_guide
    assert "Omitted or explicit `null` metadata is treated as absent" in full_guide_en
    assert "显式 `null` 时清空为 SQL `NULL`" in full_guide
    assert "explicit `null` clears it to SQL `NULL`" in full_guide_en
    assert "正式字段为 legacy `NULL` 时会移除请求 object 中的 profile key" in full_guide
    assert "for a legacy formal `NULL`, the profile key is removed" in full_guide_en
    assert "API 响应 schema 不变" not in full_guide
    assert "The API response schema is unchanged" not in full_guide_en

    list_parameters = api_spec["paths"]["/api/v1/decision-signals"]["get"]["parameters"]
    latest_parameters = api_spec["paths"]["/api/v1/decision-signals/latest/{stock_code}"]["get"]["parameters"]
    market_descriptions = [
        parameter["description"]
        for parameter in [*list_parameters, *latest_parameters]
        if parameter["name"] == "market"
    ]
    assert market_descriptions == [
        "Optional market filter: cn/hk/us/jp/kr/tw",
        "Optional market filter: cn/hk/us/jp/kr/tw",
    ]


def test_decision_signal_topic_source_anchors_exist() -> None:
    topic = _read("docs/decision-signals.md")

    for source_path in (
        "api/v1/schemas/decision_signals.py",
        "api/v1/endpoints/decision_signals.py",
        "src/services/decision_signal_service.py",
        "src/utils/sanitize.py",
    ):
        assert source_path in topic
        assert (ROOT / source_path).exists()


def test_decision_signal_has_no_web_settings_schema_entry() -> None:
    schema = SystemConfigService().get_schema()
    field_keys = {
        field["key"]
        for category in schema["categories"]
        for field in category["fields"]
    }

    assert not any(key.startswith("DECISION_SIGNAL") for key in field_keys)
    assert "DECISION_SIGNAL_ENABLED" not in _read("docs/decision-signals.md")
