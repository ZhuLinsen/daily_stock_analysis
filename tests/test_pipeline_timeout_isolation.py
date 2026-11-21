# -*- coding: utf-8 -*-
"""Tests for per-stock timeout isolation in StockAnalysisPipeline.run."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from concurrent.futures import CancelledError, TimeoutError
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.config import Config
from src.core.pipeline import StockAnalysisPipeline, _DaemonThreadStockExecutor
from src.enums import ReportType


@pytest.mark.parametrize("healthy_codes,hang_in_prefetch", [
    (("AAPL",), False),
    (("AAPL", "MSFT"), False),
    (("AAPL",), True),
])
def test_pipeline_run_isolates_hung_work_and_saves_completed_results(
    tmp_path, healthy_codes, hang_in_prefetch,
) -> None:
    codes = list(healthy_codes) if hang_in_prefetch else ["600519", *healthy_codes]
    config = Config(
        stock_list=codes,
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
    if hang_in_prefetch:
        pipeline.fetcher_manager.prefetch_stock_names.side_effect = (
            lambda *args, **kwargs: release_hung.wait(timeout=4.0)
        )

    def fake_process_single_stock(code: str, **kwargs):
        if code == "600519":
            release_hung.wait(timeout=4.0)
            return None
        time.sleep(0.65)
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
    pipeline._send_notifications = MagicMock()

    try:
        started = time.monotonic()
        results = pipeline.run(
            stock_codes=codes,
            dry_run=False,
            send_notification=True,
        )
        elapsed = time.monotonic() - started
    finally:
        release_hung.set()
        # A timed-out worker retains its process-wide slot until it exits.
        with _DaemonThreadStockExecutor._condition:
            assert _DaemonThreadStockExecutor._condition.wait_for(
                lambda: not _DaemonThreadStockExecutor._occupied, timeout=3,
            )

    assert elapsed < 2.5
    assert sorted(result.code for result in results) == list(healthy_codes)
    assert len(saved_batches) == 1
    assert sorted(result.code for result in saved_batches[0][0]) == list(healthy_codes)
    assert saved_batches[0][1] == ReportType.SIMPLE
    pipeline._send_notifications.assert_called_once_with(results, ReportType.SIMPLE)


def test_pipeline_timeout_does_not_overlap_queued_stock(tmp_path) -> None:
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
    release_hung = threading.Event()
    started_codes = []

    def fake_process_single_stock(code: str, **kwargs):
        started_codes.append(code)
        if code == "HUNG":
            release_hung.wait(timeout=8.0)
        return SimpleNamespace(code=code, success=True, error_message=None, dashboard={})

    pipeline.process_single_stock = fake_process_single_stock
    pipeline._save_local_report = MagicMock()
    started = time.monotonic()
    try:
        assert pipeline.run(stock_codes=["HUNG", "FAST"], send_notification=False) == []
        assert time.monotonic() - started < 2.5
        assert pipeline.run(stock_codes=["NEXT"], send_notification=False) == []
        assert started_codes == ["HUNG"]
        pipeline.fetcher_manager.prefetch_stock_names.assert_called_once_with(
            ["HUNG", "FAST"], use_bulk=False,
        )
    finally:
        release_hung.set()

    results = pipeline.run(stock_codes=["RECOVERED"], send_notification=False)
    assert [result.code for result in results] == ["RECOVERED"]
    assert started_codes == ["HUNG", "RECOVERED"]


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


def test_stock_deadline_blocks_further_work_even_if_watchdog_is_delayed():
    from src.core.pipeline import _DaemonThreadStockExecutor, _is_current_stock_cancelled

    release_watchdog = threading.Event()
    worker_finished = threading.Event()
    save_report = MagicMock()

    class DelayedWatchdogExecutor(_DaemonThreadStockExecutor):
        def _watch(self, *args):
            release_watchdog.wait(timeout=5)
            super()._watch(*args)

    def worker(code):
        time.sleep(0.2)
        if not _is_current_stock_cancelled():
            save_report(code)
        worker_finished.set()
        return code

    executor = DelayedWatchdogExecutor(timeout_seconds=0.1)
    try:
        future = executor.submit(worker, "AAPL")
        assert worker_finished.wait(timeout=3)
        save_report.assert_not_called()
        release_watchdog.set()
        assert future.result(timeout=3) is None
    finally:
        release_watchdog.set()
        executor.shutdown(cancel_futures=True)


def test_cancelled_stock_leaves_fetcher_lock_queue_without_calling_provider():
    from data_provider.base import DataFetcherManager
    from src.core.pipeline import _DaemonThreadStockExecutor

    manager = DataFetcherManager.__new__(DataFetcherManager)
    lock = threading.RLock()
    waiting_for_lock = threading.Event()
    left_queue = threading.Event()
    fetcher = MagicMock()
    executor = _DaemonThreadStockExecutor(timeout_seconds=0.25)

    def get_lock(_fetcher):
        waiting_for_lock.set()
        return lock

    manager._get_fetcher_call_lock = get_lock

    def worker(code):
        with pytest.raises(CancelledError):
            manager._call_fetcher_method(fetcher, "get_stock_name", code)
        left_queue.set()

    try:
        with lock:
            future = executor.submit(worker, "AAPL")
            assert waiting_for_lock.wait(timeout=2)
            assert future.result(timeout=3) is None
            assert left_queue.wait(timeout=2)
        fetcher.get_stock_name.assert_not_called()
    finally:
        executor.shutdown(cancel_futures=True)


def test_litellm_parameter_recovery_respects_stock_deadline():
    from src.core.stock_execution_context import StockCancellationToken, set_current_stock_cancellation
    from src.llm.errors import call_litellm_with_param_recovery

    token = StockCancellationToken(time.monotonic() + 10)
    previous = set_current_stock_cancellation(token)

    def provider(_kwargs):
        token.request_cancel()
        raise ValueError("temperature is not supported")

    completion = MagicMock(side_effect=provider)
    try:
        with pytest.raises(CancelledError):
            call_litellm_with_param_recovery(
                completion, model="fixture",
                call_kwargs={"temperature": 0.2, "timeout": 30, "num_retries": 2},
            )
    finally:
        set_current_stock_cancellation(previous)

    completion.assert_called_once()
    kwargs = completion.call_args.args[0]
    assert 0 < kwargs["timeout"] <= 10
    assert kwargs["num_retries"] == 2


def test_litellm_router_retries_same_model_deployment_with_stock_deadline():
    # Agent unit tests can install a process-wide LiteLLM stub.
    script = """
import os
import time
from unittest.mock import patch

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
import litellm
from src.core.stock_execution_context import StockCancellationToken, set_current_stock_cancellation
from src.llm.errors import call_litellm_with_param_recovery

deployments = [
    {"model_name": "fixture", "litellm_params": {"model": "openai/gpt-4o", "api_key": key}}
    for key in ("sk-primary", "sk-backup")
]
router = litellm.Router(model_list=deployments, num_retries=2)
available = router.get_model_list(model_name="fixture")
response = litellm.ModelResponse(choices=[{"message": {"role": "assistant", "content": "recovered"}}])
failure = litellm.RateLimitError(message="fixture limit", llm_provider="openai", model="gpt-4o")
set_current_stock_cancellation(StockCancellationToken(time.monotonic() + 10))
with patch.object(router, "get_available_deployment", side_effect=available):
    with patch.object(litellm, "completion", side_effect=[failure, response]) as completion:
        result = call_litellm_with_param_recovery(
            lambda kwargs: router.completion(**kwargs),
            model="fixture",
            call_kwargs={"model": "fixture", "messages": [{"role": "user", "content": "test"}]},
        )

assert result.choices[0].message.content == "recovered"
assert [call.kwargs["api_key"] for call in completion.call_args_list] == ["sk-primary", "sk-backup"]
assert all(0 < call.kwargs["timeout"] <= 10 for call in completion.call_args_list)
"""
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_shutdown_cancels_queued_stock_before_releasing_running_slot():
    from src.core.pipeline import _DaemonThreadStockExecutor

    release = threading.Event()
    running = threading.Event()
    queued = MagicMock()

    def first(_code):
        running.set()
        release.wait(timeout=5)

    executor = _DaemonThreadStockExecutor(timeout_seconds=2)
    try:
        executor.submit(first, "FIRST")
        assert running.wait(timeout=2)
        future = executor.submit(queued, "QUEUED")
        executor.shutdown(wait=False, cancel_futures=True)
        assert future.result(timeout=1) is None
    finally:
        release.set()
        executor.shutdown()
    queued.assert_not_called()


def test_name_lookup_returning_after_timeout_does_not_start_daily_fetch():
    from src.core.pipeline import _DaemonThreadStockExecutor, _is_current_stock_cancelled

    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.fetcher_manager = MagicMock()
    pipeline.db = MagicMock()
    pipeline.db.has_today_data.return_value = False
    pipeline._resolve_resume_target_date = MagicMock()
    pipeline.fetcher_manager.get_daily_data.return_value = (None, "fixture")
    started = threading.Event()
    release = threading.Event()

    def fetch_name(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        assert _is_current_stock_cancelled()
        return "贵州茅台"

    pipeline.fetcher_manager.get_stock_name.side_effect = fetch_name
    executor = _DaemonThreadStockExecutor(timeout_seconds=1)
    try:
        future = executor.submit(pipeline.fetch_and_save_stock_data, "600519")
        assert started.wait(timeout=2)
        assert future.result(timeout=3) is None
    finally:
        release.set()
        executor.shutdown()

    pipeline.fetcher_manager.get_daily_data.assert_not_called()
    pipeline.db.save_daily_data.assert_not_called()


def test_agent_tool_observes_stock_cancellation_and_skips_writes_and_next_model(monkeypatch):
    from src.agent.llm_adapter import LLMResponse, ToolCall
    from src.agent.runner import run_agent_loop
    from src.agent.tools import search_tools
    from src.agent.tools.registry import ToolRegistry
    from src.core.pipeline import _DaemonThreadStockExecutor, _is_current_stock_cancelled

    entered_search = threading.Event()
    release_search = threading.Event()
    observed_cancellation = []
    db = MagicMock()

    def search(*args, **kwargs):
        entered_search.set()
        release_search.wait(timeout=5)
        observed_cancellation.append(_is_current_stock_cancelled())
        return SimpleNamespace(success=True, query="news", results=[object()])

    registry = ToolRegistry()
    registry.register(search_tools.search_stock_news_tool)
    monkeypatch.setattr(search_tools, "_get_db", lambda: db)
    monkeypatch.setattr(
        search_tools, "_get_search_service",
        lambda: SimpleNamespace(is_available=True, search_stock_news=search),
    )
    call = ToolCall("news", "search_stock_news", {"stock_code": "600519", "stock_name": "贵州茅台"})
    adapter = MagicMock()
    adapter.call_with_tools.side_effect = [
        LLMResponse(provider="mock", tool_calls=[call]),
        LLMResponse(provider="mock", content="complete"),
    ]
    executor = _DaemonThreadStockExecutor(timeout_seconds=10)
    next_executor = _DaemonThreadStockExecutor(timeout_seconds=0.5)
    try:
        future = executor.submit(
            lambda _code: run_agent_loop(
                messages=[], tool_registry=registry, llm_adapter=adapter,
                tool_call_timeout_seconds=3,
            ),
            "600519",
        )
        assert entered_search.wait(timeout=5)
        executor.shutdown(wait=False, cancel_futures=True)
        assert future.result(timeout=2) is None
        subsequent = next_executor.submit(lambda code: code, "AAPL")
        assert next_executor.wait_for_results({subsequent}) == set()
        assert subsequent.result() is None
    finally:
        release_search.set()
        executor.shutdown(cancel_futures=True)
        next_executor.shutdown(cancel_futures=True)

    assert observed_cancellation == [True]
    db.save_news_intel.assert_not_called()
    adapter.call_with_tools.assert_called_once()


@pytest.mark.parametrize("nested_provider", [False, True])
def test_pipeline_reuses_completed_stock_slot_after_agent_tool_timeout(monkeypatch, nested_provider):
    from src.agent.llm_adapter import LLMResponse, ToolCall
    from src.agent.runner import run_agent_loop
    from src.agent.tools import search_tools
    from src.agent.tools.registry import ToolRegistry
    from src.core.stock_execution_context import (
        get_current_stock_cancellation,
        is_current_stock_cancelled,
        stock_child_thread_pool,
    )
    from src.services.stock_list_parser import default_index_registry

    default_index_registry()  # Warm the index rows before starting the tool timer.

    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = Config(per_stock_timeout_seconds=3, analysis_delay=0.0, single_stock_notify=False)
    pipeline.max_workers = 1
    pipeline.fetcher_manager = MagicMock()
    pipeline._save_local_report = MagicMock()
    pipeline._send_notifications = MagicMock()

    started_search = threading.Event()
    check_search_cancellation = threading.Event()
    checked_search_cancellation = threading.Event()
    release_search = threading.Event()
    search_worker = []
    search_cancellation = []
    db = MagicMock()

    def hung_provider():
        started_search.set()
        if check_search_cancellation.wait(timeout=5):
            stock_token = get_current_stock_cancellation()
            search_cancellation.append((is_current_stock_cancelled(), stock_token.is_cancelled()))
            checked_search_cancellation.set()
        release_search.wait(timeout=10)
        return SimpleNamespace(success=True, query="news", results=[object()])

    def search(*args, **kwargs):
        search_worker.append(threading.current_thread())
        if nested_provider:
            with stock_child_thread_pool(1, "search-provider") as pool:
                return pool.submit(hung_provider).result()
        return hung_provider()

    registry = ToolRegistry(category_timeout_map={"search": 0.5})
    registry.register(search_tools.search_stock_news_tool)
    monkeypatch.setattr(search_tools, "_get_db", lambda: db)
    monkeypatch.setattr(
        search_tools, "_get_search_service",
        lambda: SimpleNamespace(is_available=True, search_stock_news=search),
    )
    call = ToolCall("news", "search_stock_news", {"stock_code": "600519", "stock_name": "贵州茅台"})

    def respond(*args, **kwargs):
        if adapter.call_with_tools.call_count == 1:
            return LLMResponse(provider="mock", tool_calls=[call])
        check_search_cancellation.set()
        assert checked_search_cancellation.wait(timeout=2)
        assert not is_current_stock_cancelled()
        return LLMResponse(provider="mock", content="complete")

    adapter = MagicMock()
    adapter.call_with_tools.side_effect = respond

    def process_stock(code, **kwargs):
        if code == "600519":
            result = run_agent_loop(messages=[], tool_registry=registry, llm_adapter=adapter)
            assert result.success
            assert result.content == "complete"
            assert result.tool_calls_log[0]["timeout"] is True
        else:
            assert started_search.is_set()
            assert search_worker[0].is_alive()
        return SimpleNamespace(code=code, success=True)

    pipeline.process_single_stock = process_stock
    try:
        results = pipeline.run(stock_codes=["600519", "AAPL"], send_notification=True)
        assert sorted(result.code for result in results) == ["600519", "AAPL"]
        pipeline._save_local_report.assert_called_once_with(results, ReportType.SIMPLE)
        pipeline._send_notifications.assert_called_once_with(results, ReportType.SIMPLE)
    finally:
        check_search_cancellation.set()
        release_search.set()
        for worker in search_worker:
            worker.join(timeout=3)
            assert not worker.is_alive()
        with _DaemonThreadStockExecutor._condition:
            assert _DaemonThreadStockExecutor._condition.wait_for(
                lambda: not _DaemonThreadStockExecutor._occupied, timeout=3,
            )

    assert search_cancellation == [(True, False)]
    db.save_news_intel.assert_not_called()


@pytest.mark.parametrize("provider", ["efinance", "fundamental"])
def test_completed_stock_releases_slot_after_provider_timeout(provider):
    from data_provider.base import DataFetcherManager
    from data_provider.efinance_fetcher import _ef_call_with_timeout
    from src.core.stock_execution_context import is_current_stock_cancelled

    expired = threading.Event()
    checked = threading.Event()
    release = threading.Event()
    worker_threads = []
    observed = []

    def hung_provider():
        worker_threads.append(threading.current_thread())
        if expired.wait(timeout=4):
            observed.append(is_current_stock_cancelled())
            checked.set()
        release.wait(timeout=4)

    def process(code):
        if code == "600519":
            if provider == "efinance":
                with pytest.raises(TimeoutError):
                    _ef_call_with_timeout(hung_provider, timeout=0.1)
            else:
                manager = DataFetcherManager()
                result, error, _ = manager._run_with_timeout(hung_provider, 0.1, "fixture")
                assert result is None and error == "fixture timeout"
            expired.set()
            assert checked.wait(timeout=2)
            assert not is_current_stock_cancelled()
        else:
            assert worker_threads[0].is_alive()
        return code

    executor = _DaemonThreadStockExecutor(timeout_seconds=3, max_workers=1)
    try:
        first = executor.submit(process, "600519")
        second = executor.submit(process, "AAPL")
        assert first.result(timeout=4) == "600519"
        assert second.result(timeout=2) == "AAPL"
        assert observed == [True]
    finally:
        expired.set()
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)
        for worker in worker_threads:
            worker.join(timeout=3)


@pytest.mark.parametrize("entrypoint,lock_type", [
    ("history", "writer"),
    ("history", "reader"),
    ("history", "retry"),
    ("agent_news", "writer"),
])
def test_cancelled_save_does_not_write_after_sqlite_lock_released(tmp_path, monkeypatch, entrypoint, lock_type):
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import event

    from src.agent.tools import search_tools
    from src.agent.tools.execution import TOOL_CANCEL_EVENT
    from src.analyzer import AnalysisResult
    from src.search_service import SearchResponse, SearchResult
    from src.storage import DatabaseManager

    if lock_type == "reader":
        monkeypatch.setattr("src.storage.get_config", lambda: Config(sqlite_wal_enabled=False))
    elif lock_type == "retry":
        config = Config(sqlite_busy_timeout_ms=50, sqlite_write_retry_max=5, sqlite_write_retry_base_delay=0.1)
        monkeypatch.setattr("src.storage.get_config", lambda: config)
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'locked.db'}")
    monkeypatch.setattr(search_tools, "_get_db", lambda: db)
    waiting_for_lock = threading.Event()
    write_attempts = []
    tool_cancelled = threading.Event()
    code = "600519"

    @event.listens_for(db._engine, "before_cursor_execute")
    def observe_write(_conn, _cursor, statement, *_args):
        if statement in ("BEGIN IMMEDIATE", "BEGIN EXCLUSIVE"):
            write_attempts.append(statement)
            if lock_type != "retry" or len(write_attempts) >= 2:
                waiting_for_lock.set()

    def save_report(stock_code):
        result = AnalysisResult(
            code=stock_code, name="贵州茅台", sentiment_score=50,
            trend_prediction="未知", operation_advice="观望",
        )
        return db.save_analysis_history(result, "fixture-report", "simple", None)

    def save_agent_news():
        context = TOOL_CANCEL_EVENT.set(tool_cancelled)
        try:
            response = SearchResponse("news", [
                SearchResult("公告", "贵州茅台公告", "https://example.invalid/news", "fixture"),
            ], "fixture")
            search_tools._persist_news_response(
                stock_code=code, stock_name="贵州茅台", dimension="latest_news", response=response,
            )
        finally:
            TOOL_CANCEL_EVENT.reset(context)

    executor = _DaemonThreadStockExecutor(timeout_seconds=1) if entrypoint == "history" else ThreadPoolExecutor(1)
    try:
        with db._engine.connect() as blocker:
            if lock_type == "reader":
                blocker.exec_driver_sql("BEGIN")
                blocker.exec_driver_sql("SELECT id FROM analysis_history").all()
            else:
                blocker.exec_driver_sql("BEGIN IMMEDIATE")
            waiting_for_lock.clear()
            if entrypoint == "history":
                future = executor.submit(save_report, code)
                assert waiting_for_lock.wait(timeout=2)
                assert future.result(timeout=3) is None
            else:
                future = executor.submit(save_agent_news)
                assert waiting_for_lock.wait(timeout=2)
                tool_cancelled.set()
            blocker.rollback()
        assert future.result(timeout=3) is None
        executor.shutdown(wait=True)
        assert db.get_analysis_history(query_id="fixture-report") == []
        assert db.get_recent_news(code) == []
        assert save_report(code) > 0
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        DatabaseManager.reset_instance()


@pytest.mark.parametrize("entrypoint", ["tool", "discovery", "efinance"])
def test_hung_nested_worker_does_not_keep_cli_process_alive(entrypoint):
    script = """
import sys
import threading
from types import SimpleNamespace
from data_provider.efinance_fetcher import _ef_call_with_timeout
from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import AgentContext
from src.agent.runner import _execute_tools
from src.agent.tools.registry import ToolDefinition, ToolRegistry
from src.core.pipeline import _DaemonThreadStockExecutor

started = threading.Event()
def hang():
    started.set()
    threading.Event().wait()

registry = ToolRegistry()
registry.register(ToolDefinition(name="hang", description="hang", parameters=[], handler=hang))
call = SimpleNamespace(id="1", name="hang", arguments={})
orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
orchestrator._run_stage_agent = lambda *args, **kwargs: hang()
entrypoints = {
    "tool": lambda: _execute_tools([call], registry, 1, None, [], tool_call_timeout_seconds=5),
    "discovery": lambda: orchestrator._run_discovery_wave_parallel(
        SimpleNamespace(), SimpleNamespace(), AgentContext(query="Analyze AAPL"),
    ),
    "efinance": lambda: _ef_call_with_timeout(hang, timeout=30),
}
executor = _DaemonThreadStockExecutor(timeout_seconds=1)
future = executor.submit(lambda _code: entrypoints[sys.argv[1]](), "AAPL")
assert started.wait(timeout=2)
assert future.result(timeout=3) is None
executor.shutdown(wait=False, cancel_futures=True)
print("stock batch returned", flush=True)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, entrypoint], capture_output=True, text=True, timeout=30
    )
    assert child.returncode == 0, child.stderr
    assert "stock batch returned" in child.stdout
