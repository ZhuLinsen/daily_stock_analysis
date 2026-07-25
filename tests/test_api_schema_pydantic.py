"""Regression tests for API schema metadata under Pydantic v2."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from api.app import create_app
from api.v1.router import router as api_v1_router
from api.v1.schemas.analysis import AnalyzeRequest, MarketReviewRequest
from api.v1.schemas.common import RootResponse
from api.v1.schemas.history import HistoryItem
from api.v1.schemas.stocks import StockQuote


DECISION_SIGNAL_PATHS = (
    "/api/v1/decision-signals",
    "/api/v1/decision-signals/reassess",
    "/api/v1/decision-signals/outcomes/run",
    "/api/v1/decision-signals/outcomes",
    "/api/v1/decision-signals/outcomes/stats",
    "/api/v1/decision-signals/latest/{stock_code}",
    "/api/v1/decision-signals/{signal_id}/outcomes",
    "/api/v1/decision-signals/{signal_id}/feedback",
    "/api/v1/decision-signals/{signal_id}",
    "/api/v1/decision-signals/{signal_id}/status",
)
DECISION_SIGNAL_SCHEMAS = (
    "DecisionSignalCreateRequest",
    "DecisionSignalFeedbackItem",
    "DecisionSignalFeedbackRequest",
    "DecisionSignalItem",
    "DecisionSignalListResponse",
    "DecisionSignalMutationResponse",
    "DecisionSignalOutcomeItem",
    "DecisionSignalOutcomeListResponse",
    "DecisionSignalOutcomeRunRequest",
    "DecisionSignalOutcomeRunResponse",
    "DecisionSignalOutcomeStatsBucket",
    "DecisionSignalOutcomeStatsResponse",
    "DecisionSignalProfileCalibration",
    "DecisionSignalProfileCalibrationBreakdowns",
    "DecisionSignalProfileCalibrationBucket",
    "DecisionSignalPreview",
    "DecisionSignalReassessErrorResponse",
    "DecisionSignalReassessRequest",
    "DecisionSignalReassessResponse",
    "DecisionSignalStatusUpdateRequest",
    "DecisionSignalWarning",
)
P6_SIGNAL_LINKED_PATHS = (
    "/api/v1/alerts/triggers",
    "/api/v1/portfolio/risk",
)
P6_SIGNAL_LINKED_SCHEMAS = (
    "AlertTriggerItem",
    "AlertTriggerListResponse",
    "PortfolioDecisionSignalRiskBlock",
    "PortfolioDecisionSignalRiskItem",
    "PortfolioRiskResponse",
)


def _collect_component_schema_refs(node: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            refs.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            refs.update(_collect_component_schema_refs(value))
    elif isinstance(node, list):
        for value in node:
            refs.update(_collect_component_schema_refs(value))
    return refs


def test_schema_examples_remain_in_openapi_schema() -> None:
    root_schema = RootResponse.model_json_schema()
    analyze_schema = AnalyzeRequest.model_json_schema()
    history_schema = HistoryItem.model_json_schema()
    quote_schema = StockQuote.model_json_schema()

    assert root_schema["properties"]["message"]["example"] == "Daily Stock Analysis API is running"
    assert root_schema["example"]["version"] == "1.0.0"
    assert analyze_schema["properties"]["stock_code"]["example"] == "600519"
    assert analyze_schema["properties"]["skills"]["example"] == ["bull_trend", "growth_quality"]
    assert analyze_schema["properties"]["analysis_phase"]["default"] == "auto"
    assert analyze_schema["properties"]["analysis_phase"]["enum"] == [
        "auto",
        "premarket",
        "intraday",
        "postmarket",
    ]
    assert history_schema["example"]["stock_code"] == "600519"
    assert quote_schema["example"]["stock_name"] == "贵州茅台"


def test_analyze_request_supports_legacy_strategies_dict_input() -> None:
    request = AnalyzeRequest.model_validate({
        "stock_code": "600519",
        "strategies": ["bull_trend", "growth_quality"],
    })

    assert request.skills == ["bull_trend", "growth_quality"]


def test_request_models_accept_report_language_camel_case_alias() -> None:
    analyze_request = AnalyzeRequest.model_validate({
        "stock_code": "600519",
        "reportLanguage": "en",
    })
    assert analyze_request.report_language == "en"

    market_review_request = MarketReviewRequest.model_validate({
        "send_notification": False,
        "reportLanguage": "en",
    })
    assert market_review_request.report_language == "en"


def test_request_models_accept_korean_report_language() -> None:
    analyze_request = AnalyzeRequest.model_validate({
        "stock_code": "005930.KS",
        "report_language": "ko",
    })
    assert analyze_request.report_language == "ko"

    market_review_request = MarketReviewRequest.model_validate({
        "send_notification": False,
        "report_language": "ko",
    })
    assert market_review_request.report_language == "ko"


@pytest.mark.parametrize(
    ("raw_region", "expected"),
    [
        ("cn", "cn"),
        ("US", "us"),
        (" jp , kr ", "jp,kr"),
        ("kr,jp", "jp,kr"),
        ("cn,cn,us", "cn,us"),
        ("both", "cn,hk,us,jp,kr"),
    ],
)
def test_market_review_request_normalizes_strict_region_input(
    raw_region: str,
    expected: str,
) -> None:
    request = MarketReviewRequest.model_validate({"region": raw_region})

    assert request.region == expected


@pytest.mark.parametrize(
    "raw_region",
    ["", "   ", "abc", "cn,abc", "cn,,us", "both,us"],
)
def test_market_review_request_rejects_invalid_region_input(raw_region: str) -> None:
    with pytest.raises(ValidationError, match="region"):
        MarketReviewRequest.model_validate({"region": raw_region})


def test_market_review_request_omitted_region_inherits_server_config() -> None:
    assert MarketReviewRequest().region is None
    assert MarketReviewRequest.model_validate({"region": None}).region is None


def test_market_review_request_openapi_exposes_only_region_override_name() -> None:
    schema = MarketReviewRequest.model_json_schema()

    region_schema = schema["properties"]["region"]
    assert region_schema["example"] == "cn,us"
    string_schema = next(
        option for option in region_schema["anyOf"] if option.get("type") == "string"
    )
    assert string_schema["maxLength"] == 64
    assert string_schema["minLength"] == 1
    assert region_schema["examples"] == ["cn", "jp,kr", "both"]
    description = region_schema["description"]
    for contract_text in ("cn", "both 只能单独使用", "空 token", "整体返回 4xx", "64"):
        assert contract_text in description
    assert "market_review_region" not in schema["properties"]


def test_market_review_request_rejects_region_over_length_boundary() -> None:
    with pytest.raises(ValidationError, match="64"):
        MarketReviewRequest.model_validate({"region": "cn," * 22})


def test_analyze_request_analysis_phase_defaults_to_auto() -> None:
    request = AnalyzeRequest(stock_code="600519")

    assert request.analysis_phase == "auto"


def test_analyze_request_rejects_invalid_analysis_phase() -> None:
    try:
        AnalyzeRequest.model_validate({
            "stock_code": "600519",
            "analysis_phase": "lunch_break",
        })
    except Exception as exc:
        assert "analysis_phase" in str(exc)
    else:
        raise AssertionError("invalid analysis_phase should be rejected")


def test_decision_signal_static_api_spec_matches_runtime_paths() -> None:
    static_spec_path = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "api_spec.json"
    static_spec = json.loads(static_spec_path.read_text(encoding="utf-8"))
    runtime_spec = create_app().openapi()

    assert static_spec["openapi"] == runtime_spec["openapi"]
    assert static_spec["info"]["description"] == runtime_spec["info"]["description"]
    assert "暂无认证要求" not in static_spec["info"]["description"]
    assert "ADMIN_AUTH_ENABLED=true" in static_spec["info"]["description"]
    for path in DECISION_SIGNAL_PATHS:
        assert static_spec["paths"][path] == runtime_spec["paths"][path]
        for operation in static_spec["paths"][path].values():
            assert "401" in operation["responses"]
            assert operation["security"] == [{"AdminSessionCookie": []}]
    assert static_spec["components"]["securitySchemes"] == runtime_spec["components"]["securitySchemes"]
    for schema_name in DECISION_SIGNAL_SCHEMAS:
        assert static_spec["components"]["schemas"][schema_name] == runtime_spec["components"]["schemas"][schema_name]

    for path in P6_SIGNAL_LINKED_PATHS:
        assert static_spec["paths"][path] == runtime_spec["paths"][path]
    for schema_name in P6_SIGNAL_LINKED_SCHEMAS:
        assert static_spec["components"]["schemas"][schema_name] == runtime_spec["components"]["schemas"][schema_name]
    schema_refs = _collect_component_schema_refs(static_spec)
    missing_schema_refs = sorted(schema_refs - set(static_spec["components"]["schemas"]))
    assert missing_schema_refs == []

    status_schema = static_spec["components"]["schemas"]["DecisionSignalStatusUpdateRequest"]["properties"]["status"]
    assert status_schema["enum"] == ["active", "expired", "invalidated", "closed", "archived"]


def test_v1_prefix_is_applied_at_app_mount_level() -> None:
    assert api_v1_router.prefix == ""

    runtime_paths = create_app().openapi()["paths"]
    assert "/api/v1/history" in runtime_paths
    assert "/api/v1/decision-signals" in runtime_paths
    assert "/api/v1/history/" not in runtime_paths
    assert "/api/v1/decision-signals/" not in runtime_paths
