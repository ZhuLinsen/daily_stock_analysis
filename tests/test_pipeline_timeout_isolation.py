# -*- coding: utf-8 -*-
"""Tests for per-stock timeout isolation in StockAnalysisPipeline.run."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.config import Config
from src.core.pipeline import StockAnalysisPipeline
from src.enums import ReportType


def test_pipeline_run_isolates_hung_stock_and_saves_completed_results(tmp_path) -> None:
    config = Config(
        stock_list=["600519", "AAPL"],
        per_stock_timeout_seconds=1,
        max_workers=2,
        analysis_delay=0.0,
        database_path=str(tmp_path / "pipeline_timeout.db"),
        report_type="simple",
        single_stock_notify=False,
    )

    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = config
    pipeline.max_workers = 2
    pipeline.query_id = "test-timeout-isolation"
    pipeline.db = MagicMock()
    pipeline.db.has_today_data.return_value = False
    pipeline.fetcher_manager = MagicMock()
    pipeline.notifier = MagicMock()
    pipeline.notifier.is_available.return_value = False
    pipeline.save_context_snapshot = False
    pipeline.analysis_skills = None

    release_hung = threading.Event()
    saved_batches = []

    def fake_process_single_stock(code: str, **kwargs):
        if code == "600519":
            release_hung.wait(timeout=2.0)
            return None
        return SimpleNamespace(
            code=code,
            name="Apple",
            sentiment_score=80,
            operation_advice="买入",
            trend_prediction="看多",
            success=True,
            error_message=None,
            dashboard={},
        )

    pipeline.process_single_stock = fake_process_single_stock
    pipeline._save_local_report = lambda res, rtype: saved_batches.append((res, rtype))

    try:
        started = time.monotonic()
        results = pipeline.run(
            stock_codes=["600519", "AAPL"],
            dry_run=False,
            send_notification=False,
        )
        elapsed = time.monotonic() - started
    finally:
        release_hung.set()

    assert elapsed < 1.8
    assert len(results) == 1
    assert results[0].code == "AAPL"
    assert len(saved_batches) == 1
    assert saved_batches[0][0][0].code == "AAPL"
    assert saved_batches[0][1] == ReportType.SIMPLE


def test_pipeline_timeout_releases_single_worker_for_queued_stock(tmp_path) -> None:
    config = Config(
        stock_list=["HUNG", "FAST"],
        per_stock_timeout_seconds=1,
        max_workers=1,
        analysis_delay=0.0,
        database_path=str(tmp_path / "pipeline_timeout_single_worker.db"),
        report_type="simple",
        single_stock_notify=False,
    )
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = config
    pipeline.max_workers = 1
    pipeline.query_id = "test-timeout-single-worker"
    pipeline.db = MagicMock()
    pipeline.db.has_today_data.return_value = False
    pipeline.fetcher_manager = MagicMock()
    pipeline.notifier = MagicMock()
    pipeline.notifier.is_available.return_value = False
    pipeline.save_context_snapshot = False
    pipeline.analysis_skills = None

    def fake_process_single_stock(code: str, **kwargs):
        if code == "HUNG":
            time.sleep(5.0)
        return SimpleNamespace(code=code, success=True, error_message=None, dashboard={})

    pipeline.process_single_stock = fake_process_single_stock
    started = time.monotonic()
    results = pipeline.run(
        stock_codes=["HUNG", "FAST"],
        dry_run=False,
        send_notification=False,
    )

    assert time.monotonic() - started < 2.5
    assert [result.code for result in results] == ["FAST"]
