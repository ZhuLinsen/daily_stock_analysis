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


def test_daemon_executor_sets_cancel_context_on_timeout(tmp_path) -> None:
    from src.core.pipeline import _DaemonThreadStockExecutor, _is_current_stock_cancelled

    config = Config(
        stock_list=["SLOW"],
        per_stock_timeout_seconds=1,
        max_workers=1,
        analysis_delay=0.0,
        database_path=str(tmp_path / "pipeline_timeout_cancel.db"),
        report_type="simple",
        single_stock_notify=False,
    )
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = config
    pipeline.max_workers = 1
    pipeline.query_id = "test-cancel-ctx"
    pipeline.db = MagicMock()
    pipeline.notifier = MagicMock()

    release_worker = threading.Event()
    observed_cancelled = []

    def slow_worker(code: str, **kwargs):
        release_worker.wait(timeout=2.0)
        cancelled = _is_current_stock_cancelled()
        observed_cancelled.append(cancelled)
        if not cancelled:
            pipeline.db.save_analysis_history(code=code)
        return SimpleNamespace(code=code, success=not cancelled, error_message=None, dashboard={})

    executor = _DaemonThreadStockExecutor(timeout_seconds=0.15, max_workers=1)
    try:
        fut = executor.submit(slow_worker, "SLOW")
        assert fut.result(timeout=1.5) is None
        release_worker.set()
        # Allow daemon thread a moment to reach its checkpoint before asserting
        deadline = time.monotonic() + 1.0
        while not observed_cancelled and time.monotonic() < deadline:
            time.sleep(0.02)
        assert observed_cancelled == [True]
        pipeline.db.save_analysis_history.assert_not_called()
    finally:
        release_worker.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_daemon_executor_completes_future_when_stock_worker_raises_base_exception():
    from src.core.pipeline import _DaemonThreadStockExecutor

    executor = _DaemonThreadStockExecutor(timeout_seconds=1, max_workers=1)

    def abort(_code):
        raise SystemExit("worker stopped")

    future = executor.submit(abort, "600519")
    assert future.result(timeout=2) is None
    executor.shutdown()
