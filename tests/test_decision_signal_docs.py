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
        "/api/v1/decision-signals/latest/{stock_code}",
        "/api/v1/decision-signals/outcomes/run",
        "/api/v1/decision-signals/{signal_id}/feedback",
    ):
        assert path in topic
        assert path in api_spec["paths"]

    for schema_name in (
        "DecisionSignalCreateRequest",
        "DecisionSignalItem",
        "DecisionSignalOutcomeItem",
        "DecisionSignalFeedbackRequest",
        "PortfolioDecisionSignalRiskBlock",
    ):
        assert schema_name in api_spec["components"]["schemas"]

    assert "sanitize_decision_signal_text()" in topic
    assert "sanitize_decision_signal_payload()" in topic
    assert "DECISION_SIGNAL_*" in topic
    assert "revert" in topic
    assert "decision-signals.md" in full_guide
    assert "decision-signals.md" in full_guide_en
    assert "decision-signals.md" in index
    assert "decision-signals.md" in index_en
    assert "decision-signals.md" in alerts
    assert "decision-signals.md" in notifications

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
