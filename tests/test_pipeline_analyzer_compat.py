import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType


def _last_record_llm_run_kwargs(mock_call):
    # Helper to get the kwargs of the last record_llm_run call
    assert mock_call.called, "record_llm_run was not called"
    return mock_call.call_args_list[-1][1]


def test_pipeline_handles_analyzer_attribute_error_gracefully():
    """When the analyzer.analyze raises AttributeError, the pipeline should
    treat it as a per-stock failure (return None) and record the LLM run as failed,
    with structured telemetry including error_type and error_message.
    """
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)

    # Minimal config used by the code paths we hit
    pipeline.config = SimpleNamespace(
        report_language="zh",
        enable_realtime_quote=False,
        enable_chip_distribution=False,
        save_context_snapshot=False,
        max_workers=1,
        litellm_model="test-model",
    )

    # Minimal fetcher_manager that the pipeline expects
    fm = MagicMock()
    fm.get_stock_name.return_value = "测试股票"
    fm.get_realtime_quote.return_value = None
    fm.get_chip_distribution.return_value = None
    fm.get_fundamental_context.return_value = {}
    pipeline.fetcher_manager = fm

    # Minimal DB mock
    db = MagicMock()
    db.get_data_range.return_value = None
    db.has_today_data.return_value = False
    pipeline.db = db

    # Trend analyzer placeholder
    pipeline.trend_analyzer = MagicMock()

    # Analyzer that raises AttributeError to simulate missing method/signature
    bad_analyzer = MagicMock()

    def raise_attribute_error(*args, **kwargs):
        raise AttributeError("validate_json_response not found")

    bad_analyzer.analyze.side_effect = raise_attribute_error
    pipeline.analyzer = bad_analyzer

    # Notifier (not used in this test but some code paths check is_available)
    pipeline.notifier = MagicMock()
    pipeline.notifier.is_available.return_value = False

    # Patch record_llm_run to capture telemetry reporting
    with patch("src.core.pipeline.record_llm_run") as mock_record_llm_run:
        # Call analyze_stock and ensure it does not raise and returns None
        result = pipeline.analyze_stock(
            code="600519",
            report_type=ReportType.SIMPLE,
            query_id="test-qid-1",
        )

        assert result is None

        # Ensure record_llm_run was called to record the failure
        called_kwargs = _last_record_llm_run_kwargs(mock_record_llm_run)
        assert called_kwargs.get("success") is False
        assert called_kwargs.get("call_type") == "analysis"

        # error_type should be present and indicate AttributeError
        error_type = called_kwargs.get("error_type")
        assert error_type is not None
        assert "AttributeError" in str(error_type) or error_type == "AttributeError"

        # error_message should include the original message for debugability
        error_message = called_kwargs.get("error_message")
        assert error_message is not None
        assert "validate_json_response" in str(error_message)

        # duration_ms should be an integer (telemetry metric)
        duration_ms = called_kwargs.get("duration_ms")
        assert isinstance(duration_ms, int) and duration_ms >= 0


def test_pipeline_handles_analyzer_type_error_gracefully():
    """Simulate analyzer.analyze raising a TypeError (e.g. signature mismatch).
    The pipeline should treat it as a per-stock failure and record the LLM run as failed
    with structured telemetry including error_type and a descriptive message.
    """
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)

    pipeline.config = SimpleNamespace(
        report_language="zh",
        enable_realtime_quote=False,
        enable_chip_distribution=False,
        save_context_snapshot=False,
        max_workers=1,
        litellm_model="test-model",
    )

    fm = MagicMock()
    fm.get_stock_name.return_value = "测试股票"
    fm.get_realtime_quote.return_value = None
    fm.get_chip_distribution.return_value = None
    fm.get_fundamental_context.return_value = {}
    pipeline.fetcher_manager = fm

    db = MagicMock()
    db.get_data_range.return_value = None
    db.has_today_data.return_value = False
    pipeline.db = db

    pipeline.trend_analyzer = MagicMock()

    bad_analyzer = MagicMock()

    def raise_type_error(*args, **kwargs):
        raise TypeError("analyzer.analyze() got unexpected keyword argument 'foo'")

    bad_analyzer.analyze.side_effect = raise_type_error
    pipeline.analyzer = bad_analyzer

    pipeline.notifier = MagicMock()
    pipeline.notifier.is_available.return_value = False

    with patch("src.core.pipeline.record_llm_run") as mock_record_llm_run:
        result = pipeline.analyze_stock(
            code="000001",
            report_type=ReportType.SIMPLE,
            query_id="test-qid-2",
        )

        assert result is None

        called_kwargs = _last_record_llm_run_kwargs(mock_record_llm_run)
        assert called_kwargs.get("success") is False
        assert called_kwargs.get("call_type") == "analysis"

        error_type = called_kwargs.get("error_type")
        assert error_type is not None
        assert "TypeError" in str(error_type) or error_type == "TypeError"

        error_message = called_kwargs.get("error_message")
        assert error_message is not None
        assert "unexpected keyword" in str(error_message)

        duration_ms = called_kwargs.get("duration_ms")
        assert isinstance(duration_ms, int) and duration_ms >= 0
