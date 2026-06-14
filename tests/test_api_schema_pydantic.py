"""Regression tests for API schema metadata under Pydantic v2."""

import json
from pathlib import Path

from api.app import create_app
from api.v1.schemas.analysis import AnalyzeRequest, MarketReviewRequest
from api.v1.schemas.common import RootResponse
from api.v1.schemas.history import HistoryItem
from api.v1.schemas.stocks import StockQuote


DECISION_SIGNAL_PATHS = (
    "/api/v1/decision-signals",
    "/api/v1/decision-signals/latest/{stock_code}",
    "/api/v1/decision-signals/{signal_id}",
    "/api/v1/decision-signals/{signal_id}/status",
)
DECISION_SIGNAL_SCHEMAS = (
    "DecisionSignalCreateRequest",
    "DecisionSignalItem",
    "DecisionSignalListResponse",
    "DecisionSignalMutationResponse",
    "DecisionSignalStatusUpdateRequest",
)


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

    status_schema = static_spec["components"]["schemas"]["DecisionSignalStatusUpdateRequest"]["properties"]["status"]
    assert status_schema["enum"] == ["active", "expired", "invalidated", "closed", "archived"]
