import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType


def test_pipeline_handles_analyzer_attribute_error_gracefully():
    """When the analyzer.analyze raises AttributeError/TypeError, the pipeline should
    treat it as a per-stock failure (return None) and record the LLM run as failed,
    rather than raising and aborting the batch.
    """
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)

    # Minimal config used by the code paths we hit
    pipeline.config = SimpleNamespace(
        report_language="zh",
        enable_realtime_quote=False,
        enable_chip_distribution=False,
        save_context_snapshot=False,
        max_workers=1,
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
        assert mock_record_llm_run.called
        # The most important assertion: it should be recorded as a failure
        called_args = mock_record_llm_run.call_args[1]  # kwargs
        assert called_args.get("success") is False
        assert called_args.get("call_type") == "analysis"
        assert "AttributeError" in str(called_args.get("error_type")) or called_args.get("error_type") == "AttributeError"
