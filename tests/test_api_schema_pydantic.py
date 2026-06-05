"""Regression tests for API schema metadata under Pydantic v2."""

from api.v1.schemas.analysis import AnalyzeRequest
from api.v1.schemas.common import RootResponse
from api.v1.schemas.history import HistoryItem
from api.v1.schemas.stocks import StockQuote


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
