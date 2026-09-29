# -*- coding: utf-8 -*-
"""Regression tests for #1391 Phase 1 run diagnostics."""

from __future__ import annotations

import json
import os
import sys
import unittest
from concurrent.futures import Future
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.base import BaseFetcher, DataFetcherManager
from src.services.run_diagnostics import (
    RunDiagnosticContext,
    activate_run_diagnostic_context,
    current_diagnostic_snapshot,
    record_provider_run,
    reset_run_diagnostic_context,
)
from src.services.task_queue import AnalysisTaskQueue, TaskInfo, TaskStatus


class _FailingDailyFetcher(BaseFetcher):
    name = "FailingDailyFetcher"
    priority = 0

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise NotImplementedError

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        raise RuntimeError("token=secret-token")


class _SuccessfulDailyFetcher(BaseFetcher):
    name = "SuccessfulDailyFetcher"
    priority = 1

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise NotImplementedError

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        return pd.DataFrame(
            [
                {
                    "date": "2026-05-22",
                    "open": 1,
                    "high": 2,
                    "low": 1,
                    "close": 2,
                    "volume": 100,
                    "amount": 200,
                    "pct_chg": 1,
                }
            ]
        )


class _Quote:
    name = "贵州茅台"
    price = 100
    change_pct = 1.2
    volume_ratio = 1.1
    turnover_rate = 0.5
    pe_ratio = 10
    pb_ratio = 2
    total_mv = 1000
    circ_mv = 800
    amplitude = 2

    def has_basic_data(self) -> bool:
        return True


class _EfinanceRealtimeFetcher(BaseFetcher):
    name = "EfinanceFetcher"
    priority = 0

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise NotImplementedError

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise NotImplementedError

    def get_realtime_quote(self, stock_code):
        return _Quote()


class _SyncExecutor:
    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - exercised by queue behavior
            future.set_exception(exc)
        return future

    def shutdown(self, wait=True):
        return None


class RunDiagnosticsP1TestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._original_queue = AnalysisTaskQueue._instance
        AnalysisTaskQueue._instance = None

    def tearDown(self) -> None:
        queue = AnalysisTaskQueue._instance
        if queue is not None and queue is not self._original_queue:
            executor = getattr(queue, "_executor", None)
            if executor is not None and hasattr(executor, "shutdown"):
                executor.shutdown(wait=False)
        AnalysisTaskQueue._instance = self._original_queue

    def test_task_info_exposes_trace_id_for_sse_and_status_payloads(self) -> None:
        task = TaskInfo(task_id="task-1", stock_code="600519")

        self.assertEqual(task.to_dict()["trace_id"], "task-1")
        self.assertEqual(task.copy().trace_id, "task-1")

    def test_background_task_reuses_task_id_as_trace_id(self) -> None:
        queue = AnalysisTaskQueue(max_workers=1)
        queue._executor = _SyncExecutor()

        task = queue.submit_background_task(
            lambda: {"ok": True},
            stock_code="market_review",
            task_id="market-task-1",
        )
        stored = queue.get_task(task.task_id)

        self.assertIsNotNone(stored)
        self.assertEqual(stored.trace_id, "market-task-1")
        self.assertEqual(stored.status, TaskStatus.COMPLETED)

    def test_daily_data_provider_runs_record_failure_then_success(self) -> None:
        manager = DataFetcherManager(
            fetchers=[_FailingDailyFetcher(), _SuccessfulDailyFetcher()]
        )
        token = activate_run_diagnostic_context(
            trace_id="trace-daily",
            query_id="query-daily",
            stock_code="600519",
            trigger_source="api",
        )
        try:
            df, source = manager.get_daily_data("600519")
            snapshot = current_diagnostic_snapshot()
        finally:
            reset_run_diagnostic_context(token)

        self.assertFalse(df.empty)
        self.assertEqual(source, "SuccessfulDailyFetcher")
        runs = snapshot["provider_runs"]
        self.assertEqual([run["provider"] for run in runs], ["FailingDailyFetcher", "SuccessfulDailyFetcher"])
        self.assertFalse(runs[0]["success"])
        self.assertEqual(runs[0]["fallback_to"], "SuccessfulDailyFetcher")
        self.assertNotIn("secret-token", runs[0]["error_message_sanitized"])
        self.assertTrue(runs[1]["success"])
        self.assertEqual(runs[1]["record_count"], 1)

    def test_realtime_quote_provider_run_records_success(self) -> None:
        manager = DataFetcherManager(fetchers=[_EfinanceRealtimeFetcher()])
        config = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="efinance",
        )
        token = activate_run_diagnostic_context(
            trace_id="trace-realtime",
            query_id="query-realtime",
            stock_code="600519",
            trigger_source="api",
        )
        try:
            with patch("src.config.get_config", return_value=config):
                quote = manager.get_realtime_quote("600519")
            snapshot = current_diagnostic_snapshot()
        finally:
            reset_run_diagnostic_context(token)

        self.assertIsNotNone(quote)
        runs = snapshot["provider_runs"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["data_type"], "realtime_quote")
        self.assertEqual(runs[0]["provider"], "EfinanceFetcher")
        self.assertTrue(runs[0]["success"])

    def test_record_provider_run_sanitizes_sensitive_text(self) -> None:
        token = activate_run_diagnostic_context(trace_id="trace-secret")
        try:
            record_provider_run(
                data_type="daily_data",
                provider="UnitFetcher",
                operation="get_daily_data",
                success=False,
                error_type="RuntimeError",
                error_message="failed token=secret https://example.com/webhook?key=abc",
            )
            snapshot = current_diagnostic_snapshot()
        finally:
            reset_run_diagnostic_context(token)

        message = snapshot["provider_runs"][0]["error_message_sanitized"]
        self.assertNotIn("secret", message)
        self.assertNotIn("example.com/webhook", message)

    def test_diagnostic_event_sink_receives_provider_llm_history_and_notification_events(self) -> None:
        events = []
        token = activate_run_diagnostic_context(
            trace_id="trace-flow",
            task_id="task-flow",
            query_id="task-flow",
            stock_code="600519",
            event_sink=events.append,
        )
        try:
            record_provider_run(
                data_type="daily_data",
                provider="UnitFetcher",
                operation="get_daily_data",
                success=True,
                latency_ms=12,
                record_count=3,
            )
            from src.services.run_diagnostics import record_history_run, record_llm_run, record_notification_run

            record_llm_run(success=True, model="deepseek-chat", duration_ms=34)
            record_history_run(report_saved=True, metadata_saved=True, analysis_history_id=7)
            record_notification_run(channel="report", status="success", success=True)
        finally:
            reset_run_diagnostic_context(token)

        self.assertEqual(
            [event["type"] for event in events],
            ["provider_run", "llm_run", "history_run", "notification_run"],
        )
        self.assertEqual(events[0]["metadata"]["node"]["lane"], "data_source")
        provider_node = events[0]["metadata"]["node"]
        provider_started = datetime.fromisoformat(provider_node["started_at"])
        provider_ended = datetime.fromisoformat(provider_node["ended_at"])
        self.assertEqual(int((provider_ended - provider_started).total_seconds() * 1000), 12)
        self.assertEqual(events[1]["metadata"]["node"]["kind"], "model")
        llm_node = events[1]["metadata"]["node"]
        llm_started = datetime.fromisoformat(llm_node["started_at"])
        llm_ended = datetime.fromisoformat(llm_node["ended_at"])
        self.assertEqual(int((llm_ended - llm_started).total_seconds() * 1000), 34)

    def test_provider_flow_event_attempt_index_is_scoped_by_data_type(self) -> None:
        events = []
        token = activate_run_diagnostic_context(
            trace_id="trace-provider-attempts",
            task_id="task-provider-attempts",
            query_id="query-provider-attempts",
            stock_code="600519",
            event_sink=events.append,
        )
        try:
            record_provider_run(
                data_type="daily_data",
                provider="DailyFetcher",
                operation="get_daily_data",
                success=True,
            )
            record_provider_run(
                data_type="news_search",
                provider="NewsFetcher",
                operation="search_stock_news",
                success=True,
            )
            record_provider_run(
                data_type="daily_data",
                provider="BackupDailyFetcher",
                operation="get_daily_data",
                success=True,
            )
        finally:
            reset_run_diagnostic_context(token)

        provider_node_ids = [
            event["metadata"]["node"]["id"]
            for event in events
            if event["type"] == "provider_run"
        ]
        self.assertEqual(
            provider_node_ids,
            [
                "provider_daily_data_dailyfetcher_1",
                "provider_news_search_newsfetcher_1",
                "provider_daily_data_backupdailyfetcher_2",
            ],
        )

    def test_live_flow_event_sink_redacts_paths_and_sensitive_metadata(self) -> None:
        events = []
        context = RunDiagnosticContext(trace_id="trace-live-redaction", event_sink=events.append)

        context._emit_flow_event(
            {
                "timestamp": "2026-06-08T10:00:01",
                "severity": "danger",
                "type": "provider_run",
                "node_id": "provider_daily_data_unsafe_1",
                "title": "Provider failed",
                "message": (
                    r"failed /home/activer/private/.env C:\Users\activer\.env "
                    "prompt=full-user-prompt raw_response=full-raw-response "
                    "https://hooks.example.com/webhook?key=secret"
                ),
                "metadata": {
                    "trace_id": "trace-live-redaction",
                    "operation": "/home/activer/project/.env",
                    "prompt": "full prompt body",
                    "raw_response": "full raw body",
                    "headers": {"Authorization": "Bearer sk-live-secret"},
                    "proxy": "http://proxy_user:proxy_pass@proxy.internal",
                    "node": {
                        "id": "provider_daily_data_unsafe_1",
                        "lane": "data_source",
                        "kind": "data_source",
                        "label": "日线K线 · UnsafeFetcher",
                        "status": "failed",
                        "message": r"failed in C:\Users\activer\.env raw_response=full-raw-response",
                    },
                },
            }
        )

        payload = json.dumps(events, ensure_ascii=False)
        for leaked in (
            "/home/activer",
            "Users",
            "full-user-prompt",
            "full-raw-response",
            "full prompt body",
            "full raw body",
            "hooks.example.com/webhook",
            "sk-live-secret",
            "proxy_user",
            "proxy_pass",
        ):
            self.assertNotIn(leaked, payload)
        self.assertIn("<redacted-path>", payload)
        self.assertIn("<redacted>", payload)
        self.assertIn('"prompt": "<redacted>"', payload)
        self.assertIn('"raw_response": "<redacted>"', payload)


if __name__ == "__main__":
    unittest.main()
