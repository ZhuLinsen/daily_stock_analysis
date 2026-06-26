# -*- coding: utf-8 -*-
"""Regression tests for run-flow snapshot contracts."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from api.v1.endpoints.analysis import get_task_run_flow
from api.v1.endpoints.history import get_history_run_flow
from src.services.run_flow import (
    build_history_run_flow_snapshot,
    build_task_run_flow_snapshot,
)
from src.services.run_diagnostics import (
    activate_run_diagnostic_context,
    current_diagnostic_snapshot,
    record_llm_run,
    record_llm_run_started,
    record_notification_run,
    record_provider_run,
    record_provider_run_started,
    reset_run_diagnostic_context,
)
from src.services.task_queue import AnalysisTaskQueue, TaskInfo, TaskStatus


def _overview(*, blocks: list[dict]) -> dict:
    counts = {
        "available": 0,
        "missing": 0,
        "not_supported": 0,
        "fallback": 0,
        "stale": 0,
        "estimated": 0,
        "partial": 0,
        "fetch_failed": 0,
    }
    for block in blocks:
        counts[block["status"]] += 1
    return {
        "pack_version": "1.0",
        "created_at": "2026-06-08T10:00:05",
        "subject": {
            "code": "600519",
            "stock_name": "贵州茅台",
            "market": "cn",
        },
        "blocks": blocks,
        "counts": counts,
        "warnings": [],
        "metadata": {"trigger_source": "api", "news_result_count": 3},
    }


def _diagnostics(*, with_fallback: bool = False, unsafe: bool = False) -> dict:
    provider_runs = [
        {
            "trace_id": "trace-flow",
            "data_type": "realtime_quote",
            "provider": "QuoteFetcher",
            "operation": "get_realtime_quote",
            "success": True,
            "latency_ms": 120,
            "record_count": 1,
            "created_at": "2026-06-08T10:00:01",
        },
        {
            "trace_id": "trace-flow",
            "data_type": "daily_data",
            "provider": "DailyFetcher",
            "operation": "get_daily_data",
            "success": True,
            "latency_ms": 230,
            "record_count": 30,
            "created_at": "2026-06-08T10:00:02",
        },
    ]
    if with_fallback:
        provider_runs = [
            {
                "trace_id": "trace-flow",
                "data_type": "realtime_quote",
                "provider": "FirstQuote",
                "operation": "get_realtime_quote",
                "success": False,
                "latency_ms": 800,
                "error_type": "TimeoutError",
                "error_message_sanitized": "token=secret-token",
                "fallback_to": "SecondQuote",
                "created_at": "2026-06-08T10:00:01",
            },
            {
                "trace_id": "trace-flow",
                "data_type": "realtime_quote",
                "provider": "SecondQuote",
                "operation": "get_realtime_quote",
                "success": True,
                "latency_ms": 150,
                "record_count": 1,
                "created_at": "2026-06-08T10:00:02",
            },
        ]
    if unsafe:
        provider_runs = [
            {
                "trace_id": "trace-flow",
                "data_type": "daily_data",
                "provider": "UnsafeFetcher",
                "operation": "/home/activer/project/.env",
                "success": False,
                "error_type": "RuntimeError",
                "error_message_sanitized": (
                    "OPENAI_API_KEY=sk-secret "
                    "https://hooks.example.com/webhook?key=secret "
                    "prompt=full-user-prompt"
                ),
                "created_at": "2026-06-08T10:00:01",
            }
        ]
    return {
        "trace_id": "trace-flow",
        "task_id": "task-flow",
        "query_id": "query-flow",
        "stock_code": "600519",
        "trigger_source": "api",
        "provider_runs": provider_runs,
        "llm_runs": [
            {
                "trace_id": "trace-flow",
                "provider": "litellm",
                "model": "deepseek-chat",
                "call_type": "analysis",
                "success": True,
                "tokens": 1234,
                "duration_ms": 900,
                "created_at": "2026-06-08T10:00:03",
            }
        ],
        "history_runs": [
            {
                "trace_id": "trace-flow",
                "report_saved": True,
                "metadata_saved": True,
                "analysis_history_id": 7,
                "created_at": "2026-06-08T10:00:04",
            }
        ],
        "notification_runs": [
            {
                "trace_id": "trace-flow",
                "channel": "wechat",
                "status": "success",
                "success": True,
                "attempts": 1,
                "created_at": "2026-06-08T10:00:05",
            }
        ],
    }


def _history_record(
    *,
    context_snapshot: dict | None,
    raw_result: dict | None = None,
    code: str = "600519",
    name: str = "贵州茅台",
    report_type: str = "detailed",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        query_id="query-flow",
        code=code,
        name=name,
        report_type=report_type,
        created_at=datetime(2026, 6, 8, 10, 0, 6),
        raw_result=json.dumps(raw_result or {"success": True, "model_used": "deepseek-chat"}, ensure_ascii=False),
        context_snapshot=json.dumps(context_snapshot, ensure_ascii=False) if context_snapshot is not None else None,
    )


class _FakeHistoryDb:
    def __init__(self, record: SimpleNamespace | None):
        self.record = record

    def get_analysis_history_by_id(self, record_id: int):
        return self.record if self.record is not None and record_id == self.record.id else None

    def get_latest_analysis_by_query_id(self, query_id: str, *, code: str | None = None, report_type: str | None = None):
        if self.record is None or query_id != self.record.query_id:
            return None
        if code is not None and self.record.code != code:
            return None
        if report_type is not None and self.record.report_type != report_type:
            return None
        return self.record if self.record is not None and query_id == self.record.query_id else None


class _FakeMarketReviewDb:
    def __init__(self, save_result):
        self.save_result = save_result
        self.saved_context_snapshot = None
        self.updated_diagnostics = None

    def save_analysis_history(self, **kwargs):
        self.saved_context_snapshot = kwargs.get("context_snapshot")
        return self.save_result

    def get_latest_analysis_by_query_id(self, query_id: str, *, code: str | None = None, report_type: str | None = None):
        _ = (query_id, code, report_type)
        return SimpleNamespace(id=42)

    def update_analysis_history_diagnostics(self, *, query_id: str, code: str, diagnostics: dict) -> None:
        _ = (query_id, code)
        self.updated_diagnostics = diagnostics


class RunFlowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._original_queue = AnalysisTaskQueue._instance
        AnalysisTaskQueue._instance = None

    def tearDown(self) -> None:
        AnalysisTaskQueue._instance = self._original_queue

    def test_active_task_missing_diagnostics_returns_skeleton_flow(self) -> None:
        task = TaskInfo(
            task_id="task-active",
            trace_id="trace-active",
            stock_code="600519",
            stock_name="贵州茅台",
            status=TaskStatus.PENDING,
            message="任务已加入队列",
            created_at=datetime(2026, 6, 8, 10, 0, 0),
        )

        snapshot = build_task_run_flow_snapshot(task)

        self.assertEqual(snapshot.task_id, "task-active")
        self.assertEqual(snapshot.trace_id, "trace-active")
        self.assertEqual(snapshot.status, "pending")
        self.assertTrue(snapshot.lanes)
        self.assertIn("task_queue", {node.id for node in snapshot.nodes})
        self.assertNotIn("provider_run", {event.type for event in snapshot.events})
        self.assertNotIn("llm_run", {event.type for event in snapshot.events})

    def test_active_task_snapshot_includes_recent_flow_events_without_faking_missing_diagnostics(self) -> None:
        task = TaskInfo(
            task_id="task-active",
            trace_id="trace-active",
            stock_code="600519",
            stock_name="贵州茅台",
            status=TaskStatus.PROCESSING,
            message="正在分析中",
            created_at=datetime(2026, 6, 8, 10, 0, 0),
            started_at=datetime(2026, 6, 8, 10, 0, 1),
            flow_events=[
                {
                    "id": "flow-1",
                    "timestamp": "2026-06-08T10:00:02",
                    "severity": "success",
                    "type": "provider_run",
                    "node_id": "provider_daily_unit_1",
                    "title": "日线K线成功",
                    "message": "日线K线 UnitFetcher 成功",
                    "metadata": {
                        "provider": "UnitFetcher",
                        "node": {
                            "id": "provider_daily_unit_1",
                            "lane": "data_source",
                            "kind": "data_source",
                            "label": "日线K线 · UnitFetcher",
                            "status": "success",
                            "provider": "UnitFetcher",
                            "record_count": 30,
                        },
                    },
                }
            ],
        )

        snapshot = build_task_run_flow_snapshot(task)

        self.assertIn("provider_run", {event.type for event in snapshot.events})
        self.assertIn("provider_daily_unit_1", {node.id for node in snapshot.nodes})
        self.assertNotIn("llm_run", {event.type for event in snapshot.events})

    def test_active_provider_events_only_link_fallbacks_within_same_data_type(self) -> None:
        task = TaskInfo(
            task_id="task-active-providers",
            trace_id="trace-active-providers",
            stock_code="600519",
            stock_name="贵州茅台",
            status=TaskStatus.PROCESSING,
            created_at=datetime(2026, 6, 8, 10, 0, 0),
            flow_events=[
                {
                    "id": "flow-daily",
                    "timestamp": "2026-06-08T10:00:02",
                    "severity": "success",
                    "type": "provider_run",
                    "node_id": "provider_daily_unit_1",
                    "title": "日线K线成功",
                    "metadata": {
                        "provider": "DailyFetcher",
                        "data_type": "daily_data",
                        "node": {
                            "id": "provider_daily_unit_1",
                            "lane": "data_source",
                            "kind": "data_source",
                            "label": "日线K线 · DailyFetcher",
                            "status": "success",
                            "provider": "DailyFetcher",
                        },
                    },
                },
                {
                    "id": "flow-news",
                    "timestamp": "2026-06-08T10:00:03",
                    "severity": "success",
                    "type": "provider_run",
                    "node_id": "provider_news_unit_1",
                    "title": "新闻舆情成功",
                    "metadata": {
                        "provider": "NewsFetcher",
                        "data_type": "news_search",
                        "node": {
                            "id": "provider_news_unit_1",
                            "lane": "data_source",
                            "kind": "data_source",
                            "label": "新闻舆情 · NewsFetcher",
                            "status": "success",
                            "provider": "NewsFetcher",
                        },
                    },
                },
            ],
        )

        snapshot = build_task_run_flow_snapshot(task)
        edge_payload = [edge.model_dump(by_alias=True) for edge in snapshot.edges]

        self.assertEqual(snapshot.summary.fallback_count, 0)
        self.assertFalse(any(edge["kind"] in {"fallback", "retry"} for edge in edge_payload))

    def test_active_and_history_provider_nodes_share_id_and_core_fields(self) -> None:
        flow_events: list[dict] = []
        token = activate_run_diagnostic_context(
            trace_id="trace-provider-contract",
            task_id="task-provider-contract",
            query_id="query-provider-contract",
            stock_code="600519",
            trigger_source="api",
            event_sink=flow_events.append,
        )
        try:
            record_provider_run(
                data_type="daily_data",
                provider="DailyFetcher",
                operation="get_daily_data",
                success=True,
                latency_ms=120,
                record_count=30,
            )
            record_provider_run(
                data_type="news_search",
                provider="NewsFetcher",
                operation="search_stock_news",
                success=True,
                latency_ms=80,
                record_count=5,
            )
            record_provider_run(
                data_type="daily_data",
                provider="BackupDailyFetcher",
                operation="get_daily_data",
                success=True,
                latency_ms=90,
                record_count=28,
            )
            diagnostics = current_diagnostic_snapshot()
        finally:
            reset_run_diagnostic_context(token)

        self.assertIsNotNone(diagnostics)
        active_snapshot = build_task_run_flow_snapshot(
            TaskInfo(
                task_id="task-provider-contract",
                trace_id="trace-provider-contract",
                stock_code="600519",
                stock_name="贵州茅台",
                status=TaskStatus.PROCESSING,
                created_at=datetime(2026, 6, 8, 10, 0, 0),
                flow_events=flow_events,
            )
        )
        history_snapshot = build_history_run_flow_snapshot(
            _history_record(context_snapshot={"diagnostics": diagnostics})
        )

        expected_provider_ids = [
            "provider_daily_data_dailyfetcher_1",
            "provider_news_search_newsfetcher_1",
            "provider_daily_data_backupdailyfetcher_2",
        ]
        active_providers = {
            node.id: node for node in active_snapshot.nodes if node.id in expected_provider_ids
        }
        history_providers = {
            node.id: node for node in history_snapshot.nodes if node.id in expected_provider_ids
        }
        self.assertEqual(list(active_providers), expected_provider_ids)
        self.assertEqual(list(history_providers), expected_provider_ids)
        for node_id in expected_provider_ids:
            active_provider = active_providers[node_id]
            history_provider = history_providers[node_id]
            for field in ("id", "label", "provider", "status", "record_count", "duration_ms"):
                self.assertEqual(
                    getattr(active_provider, field),
                    getattr(history_provider, field),
                    f"{node_id}.{field}",
                )

    def test_active_started_events_update_same_provider_and_llm_nodes(self) -> None:
        flow_events: list[dict] = []
        token = activate_run_diagnostic_context(
            trace_id="trace-started",
            task_id="task-started",
            query_id="query-started",
            stock_code="600519",
            trigger_source="api",
            event_sink=flow_events.append,
        )
        try:
            record_provider_run_started(
                data_type="daily_data",
                provider="DailyFetcher",
                operation="get_daily_data",
            )
            record_provider_run(
                data_type="daily_data",
                provider="DailyFetcher",
                operation="get_daily_data",
                success=True,
                latency_ms=120,
                record_count=30,
            )
            record_llm_run_started(
                model="deepseek-chat",
                call_type="analysis",
            )
            record_llm_run(
                success=True,
                model="deepseek-chat",
                call_type="analysis",
                duration_ms=900,
            )
        finally:
            reset_run_diagnostic_context(token)

        snapshot = build_task_run_flow_snapshot(
            TaskInfo(
                task_id="task-started",
                trace_id="trace-started",
                stock_code="600519",
                stock_name="贵州茅台",
                status=TaskStatus.PROCESSING,
                created_at=datetime(2026, 6, 8, 10, 0, 0),
                flow_events=flow_events,
            )
        )

        provider_nodes = [node for node in snapshot.nodes if node.id == "provider_daily_data_dailyfetcher_1"]
        llm_nodes = [node for node in snapshot.nodes if node.id == "llm_analysis_1"]
        provider_edges = [
            edge for edge in snapshot.edges
            if edge.to_node == "provider_daily_data_dailyfetcher_1"
        ]
        llm_edges = [
            edge for edge in snapshot.edges
            if edge.to_node == "llm_analysis_1"
        ]

        self.assertEqual(len(provider_nodes), 1)
        self.assertEqual(provider_nodes[0].status, "success")
        self.assertEqual(provider_nodes[0].record_count, 30)
        self.assertTrue(provider_edges)
        self.assertTrue(all(edge.status == "success" for edge in provider_edges))
        self.assertEqual(len(llm_nodes), 1)
        self.assertEqual(llm_nodes[0].status, "success")
        self.assertTrue(llm_edges)
        self.assertTrue(all(edge.status == "success" for edge in llm_edges))
        self.assertIn("provider_run_started", {event.type for event in snapshot.events})
        self.assertIn("llm_run_started", {event.type for event in snapshot.events})

    def test_active_chip_started_event_updates_same_provider_node(self) -> None:
        flow_events: list[dict] = []
        token = activate_run_diagnostic_context(
            trace_id="trace-chip-started",
            task_id="task-chip-started",
            query_id="query-chip-started",
            stock_code="600519",
            trigger_source="api",
            event_sink=flow_events.append,
        )
        try:
            record_provider_run_started(
                data_type="chip",
                provider="ChipFetcher",
                operation="get_chip_distribution",
            )
            record_provider_run(
                data_type="chip",
                provider="ChipFetcher",
                operation="get_chip_distribution",
                success=True,
                latency_ms=80,
                record_count=1,
            )
        finally:
            reset_run_diagnostic_context(token)

        snapshot = build_task_run_flow_snapshot(
            TaskInfo(
                task_id="task-chip-started",
                trace_id="trace-chip-started",
                stock_code="600519",
                stock_name="贵州茅台",
                status=TaskStatus.PROCESSING,
                created_at=datetime(2026, 6, 8, 10, 0, 0),
                flow_events=flow_events,
            )
        )

        chip_nodes = [node for node in snapshot.nodes if node.id == "provider_chip_chipfetcher_1"]

        self.assertEqual(len(chip_nodes), 1)
        self.assertEqual(chip_nodes[0].status, "success")
        self.assertEqual(chip_nodes[0].record_count, 1)
        self.assertEqual(chip_nodes[0].label, "筹码结构 · ChipFetcher")
        self.assertIn("provider_run_started", {event.type for event in snapshot.events})

    def test_llm_started_and_result_match_by_call_type_when_model_alias_differs(self) -> None:
        flow_events: list[dict] = []
        token = activate_run_diagnostic_context(
            trace_id="trace-llm-alias",
            task_id="task-llm-alias",
            query_id="query-llm-alias",
            stock_code="600519",
            trigger_source="api",
            event_sink=flow_events.append,
        )
        try:
            record_llm_run_started(
                model="deepseek-chat",
                call_type="agent_analysis",
            )
            record_llm_run(
                success=True,
                model="deepseek/deepseek-chat",
                call_type="agent_analysis",
                duration_ms=98000,
            )
        finally:
            reset_run_diagnostic_context(token)

        snapshot = build_task_run_flow_snapshot(
            TaskInfo(
                task_id="task-llm-alias",
                trace_id="trace-llm-alias",
                stock_code="600519",
                stock_name="贵州茅台",
                status=TaskStatus.PROCESSING,
                created_at=datetime(2026, 6, 8, 10, 0, 0),
                flow_events=flow_events,
            )
        )

        llm_nodes = [node for node in snapshot.nodes if node.id.startswith("llm_agent_analysis")]

        self.assertEqual([node.id for node in llm_nodes], ["llm_agent_analysis_1"])
        self.assertEqual(llm_nodes[0].status, "success")
        self.assertIn("llm_run_started", {event.type for event in snapshot.events})
        self.assertIn("llm_run", {event.type for event in snapshot.events})

    def test_completed_active_snapshot_prunes_skeleton_tail_when_live_nodes_exist(self) -> None:
        flow_events: list[dict] = []
        token = activate_run_diagnostic_context(
            trace_id="trace-completed-live",
            task_id="task-completed-live",
            query_id="query-completed-live",
            stock_code="600519",
            trigger_source="api",
            event_sink=flow_events.append,
        )
        try:
            record_llm_run(
                success=True,
                model="deepseek/deepseek-chat",
                call_type="agent_analysis",
                duration_ms=98000,
            )
            record_notification_run(
                channel="report",
                status="not_configured",
                success=False,
                attempts=0,
            )
        finally:
            reset_run_diagnostic_context(token)

        snapshot = build_task_run_flow_snapshot(
            TaskInfo(
                task_id="task-completed-live",
                trace_id="trace-completed-live",
                stock_code="600519",
                stock_name="贵州茅台",
                status=TaskStatus.COMPLETED,
                created_at=datetime(2026, 6, 8, 10, 0, 0),
                completed_at=datetime(2026, 6, 8, 10, 2, 0),
                flow_events=flow_events,
            )
        )
        node_ids = {node.id for node in snapshot.nodes}

        self.assertIn("llm_agent_analysis_1", node_ids)
        self.assertIn("notification_report_1", node_ids)
        self.assertNotIn("llm", node_ids)
        self.assertNotIn("notification", node_ids)

    def test_task_queue_stores_bounded_flow_events_and_broadcasts_task_progress(self) -> None:
        queue = AnalysisTaskQueue(max_workers=1)
        queue._max_flow_events_per_task = 2
        task = TaskInfo(
            task_id="task-flow",
            stock_code="600519",
            status=TaskStatus.PROCESSING,
        )
        queue._tasks[task.task_id] = task
        events = []
        queue._broadcast_event = lambda event_type, data: events.append((event_type, data))

        queue.append_task_flow_event("task-flow", {"id": "evt-1", "type": "provider_run"})
        queue.append_task_flow_event("task-flow", {"id": "evt-2", "type": "llm_run"})
        queue.append_task_flow_event("task-flow", {"id": "evt-3", "type": "history_run"})

        self.assertEqual([event["id"] for event in queue.get_task_flow_events("task-flow")], ["evt-2", "evt-3"])
        self.assertEqual(events[-1][0], "task_progress")
        self.assertEqual(events[-1][1]["flow_event"]["id"], "evt-3")

    def test_completed_history_uses_diagnostics_and_context_pack_overview(self) -> None:
        context_snapshot = {
            "diagnostics": _diagnostics(),
            "analysis_context_pack_overview": _overview(
                blocks=[
                    {
                        "key": "quote",
                        "label": "行情",
                        "status": "available",
                        "source": "QuoteFetcher",
                        "warnings": [],
                        "missing_reasons": [],
                    },
                    {
                        "key": "daily_bars",
                        "label": "日线",
                        "status": "available",
                        "source": "DailyFetcher",
                        "warnings": [],
                        "missing_reasons": [],
                    },
                    {
                        "key": "news",
                        "label": "新闻",
                        "status": "available",
                        "source": "SearchProvider",
                        "warnings": [],
                        "missing_reasons": [],
                    },
                ]
            ),
        }

        snapshot = build_history_run_flow_snapshot(_history_record(context_snapshot=context_snapshot))

        self.assertEqual(snapshot.status, "success")
        self.assertEqual(snapshot.summary.model, "deepseek-chat")
        self.assertEqual(snapshot.summary.failed_attempts, 0)
        node_ids = {node.id for node in snapshot.nodes}
        self.assertIn("context_pack", node_ids)
        self.assertTrue(any(node.kind == "model" and node.status == "success" for node in snapshot.nodes))
        quote_node = next(node for node in snapshot.nodes if node.id == "provider_realtime_quote_quotefetcher_1")
        self.assertEqual(quote_node.started_at, "2026-06-08T10:00:00.880000")
        self.assertEqual(quote_node.ended_at, "2026-06-08T10:00:01")
        self.assertIn("history_run", {event.type for event in snapshot.events})
        self.assertIn("notification_run", {event.type for event in snapshot.events})

    def test_provider_fallback_maps_to_nodes_edges_and_warning_events(self) -> None:
        context_snapshot = {
            "diagnostics": _diagnostics(with_fallback=True),
            "analysis_context_pack_overview": _overview(
                blocks=[
                    {
                        "key": "quote",
                        "label": "行情",
                        "status": "available",
                        "source": "SecondQuote",
                        "warnings": [],
                        "missing_reasons": [],
                    }
                ]
            ),
        }

        snapshot = build_history_run_flow_snapshot(_history_record(context_snapshot=context_snapshot))
        edge_payload = [edge.model_dump(by_alias=True) for edge in snapshot.edges]

        self.assertEqual(snapshot.status, "degraded")
        self.assertGreaterEqual(snapshot.summary.failed_attempts, 1)
        self.assertEqual(snapshot.summary.fallback_count, 1)
        self.assertTrue(any(edge["kind"] == "fallback" for edge in edge_payload))
        self.assertTrue(
            any(event.type == "provider_run" and event.severity == "warning" for event in snapshot.events)
        )

    def test_news_search_provider_runs_map_to_run_flow_nodes(self) -> None:
        context_snapshot = {
            "diagnostics": {
                "trace_id": "trace-news",
                "task_id": "task-news",
                "query_id": "query-news",
                "stock_code": "600519",
                "trigger_source": "api",
                "provider_runs": [
                    {
                        "trace_id": "trace-news",
                        "data_type": "news_search",
                        "provider": "Tavily",
                        "operation": "search_stock_news",
                        "success": False,
                        "latency_ms": 500,
                        "error_type": "NoUsableNews",
                        "error_message_sanitized": "过滤后无有效新闻",
                        "created_at": "2026-06-08T10:00:01",
                    },
                    {
                        "trace_id": "trace-news",
                        "data_type": "news_search",
                        "provider": "SearXNG",
                        "operation": "search_stock_news",
                        "success": True,
                        "latency_ms": 700,
                        "record_count": 3,
                        "created_at": "2026-06-08T10:00:02",
                    },
                ],
                "llm_runs": [],
                "history_runs": [],
                "notification_runs": [],
            }
        }

        snapshot = build_history_run_flow_snapshot(_history_record(context_snapshot=context_snapshot))
        node_labels = {node.label for node in snapshot.nodes}
        edge_payload = [edge.model_dump(by_alias=True) for edge in snapshot.edges]

        self.assertIn("新闻舆情 · Tavily", node_labels)
        self.assertIn("新闻舆情 · SearXNG", node_labels)
        self.assertTrue(any(edge["kind"] == "fallback" for edge in edge_payload))
        self.assertTrue(any(event.type == "provider_run" and event.node_id.endswith("searxng_2") for event in snapshot.events))

    def test_degraded_context_blocks_do_not_increment_fallback_count(self) -> None:
        diagnostics = _diagnostics()
        context_snapshot = {
            "diagnostics": diagnostics,
            "analysis_context_pack_overview": _overview(
                blocks=[
                    {
                        "key": "news",
                        "label": "新闻",
                        "status": "missing",
                        "source": None,
                        "warnings": [],
                        "missing_reasons": ["news_context_missing"],
                    },
                    {
                        "key": "fundamentals",
                        "label": "基本面",
                        "status": "not_supported",
                        "source": None,
                        "warnings": [],
                        "missing_reasons": [],
                    },
                ]
            ),
        }

        snapshot = build_history_run_flow_snapshot(_history_record(context_snapshot=context_snapshot))
        edge_payload = [edge.model_dump(by_alias=True) for edge in snapshot.edges]

        self.assertEqual(snapshot.status, "degraded")
        self.assertEqual(snapshot.summary.fallback_count, 0)
        self.assertFalse(any(edge["kind"] in {"fallback", "retry"} for edge in edge_payload))

    def test_completed_history_mixed_timezone_event_timestamps_do_not_crash(self) -> None:
        diagnostics = _diagnostics()
        overview = _overview(
            blocks=[
                {
                    "key": "news",
                    "label": "新闻",
                    "status": "missing",
                    "source": None,
                    "warnings": [],
                    "missing_reasons": ["news_context_missing"],
                }
            ]
        )
        overview["created_at"] = "2026-06-08T02:00:05+00:00"
        context_snapshot = {
            "diagnostics": diagnostics,
            "analysis_context_pack_overview": overview,
        }
        record = _history_record(context_snapshot=context_snapshot)

        with patch(
            "src.services.run_flow._local_timezone",
            return_value=timezone(timedelta(hours=8)),
        ):
            snapshot = build_history_run_flow_snapshot(record)

        self.assertEqual(snapshot.summary.elapsed_ms, 5000)
        self.assertTrue(snapshot.events)

    def test_missing_diagnostics_returns_history_skeleton_without_provider_or_llm_events(self) -> None:
        snapshot = build_history_run_flow_snapshot(_history_record(context_snapshot=None))

        self.assertEqual(snapshot.status, "unknown")
        self.assertIn("history_save", {node.id for node in snapshot.nodes})
        self.assertNotIn("provider_run", {event.type for event in snapshot.events})
        self.assertNotIn("llm_run", {event.type for event in snapshot.events})

    def test_llm_model_provider_metadata_does_not_expose_runtime_config(self) -> None:
        diagnostics = _diagnostics()
        diagnostics["llm_runs"][0].update(
            {
                "provider": "litellm",
                "model": "deepseek-chat",
                "base_url": "https://llm.example.com/v1",
                "api_key": "sk-runtime-secret",
            }
        )
        context_snapshot = {
            "diagnostics": diagnostics,
            "analysis_context_pack_overview": _overview(
                blocks=[
                    {
                        "key": "quote",
                        "label": "行情",
                        "status": "available",
                        "source": "QuoteFetcher",
                        "warnings": [],
                        "missing_reasons": [],
                    }
                ]
            ),
        }

        snapshot = build_history_run_flow_snapshot(_history_record(context_snapshot=context_snapshot))
        payload = json.dumps(snapshot.model_dump(mode="json", by_alias=True), ensure_ascii=False)

        self.assertIn("deepseek-chat", payload)
        self.assertIn("litellm", payload)
        for leaked in (
            "base_url",
            "api_key",
            "llm.example.com",
            "sk-runtime-secret",
        ):
            self.assertNotIn(leaked, payload)

    def test_market_review_history_uses_same_run_flow_contract(self) -> None:
        context_snapshot = {
            "report_kind": "market_review",
            "market_review_region": "cn",
            "diagnostics": {
                "trace_id": "trace-market",
                "task_id": "task-market",
                "query_id": "query-flow",
                "stock_code": "MARKET",
                "trigger_source": "api",
                "provider_runs": [],
                "llm_runs": [],
                "history_runs": [
                    {
                        "trace_id": "trace-market",
                        "report_saved": True,
                        "metadata_saved": True,
                        "analysis_history_id": 7,
                        "created_at": "2026-06-08T10:00:02",
                    }
                ],
                "notification_runs": [
                    {
                        "trace_id": "trace-market",
                        "channel": "report",
                        "status": "skipped",
                        "success": False,
                        "attempts": 0,
                        "created_at": "2026-06-08T10:00:03",
                    }
                ],
            },
        }

        snapshot = build_history_run_flow_snapshot(
            _history_record(
                context_snapshot=context_snapshot,
                code="MARKET",
                name="大盘复盘",
                report_type="market_review",
            )
        )

        self.assertEqual(snapshot.stock_code, "MARKET")
        self.assertEqual(snapshot.task_id, "task-market")
        self.assertIn("history_run", {event.type for event in snapshot.events})
        notification = next(node for node in snapshot.nodes if node.id.startswith("notification_report"))
        self.assertEqual(notification.attempts, 0)
        self.assertTrue(snapshot.lanes)

    def test_market_review_run_flow_filters_leaked_stock_provider_runs(self) -> None:
        context_snapshot = {
            "report_kind": "market_review",
            "diagnostics": {
                "trace_id": "trace-market",
                "query_id": "query-flow",
                "stock_code": "688521.SH",
                "provider_runs": [
                    {
                        "data_type": "daily_data",
                        "provider": "StockFetcher",
                        "success": True,
                        "created_at": "2026-06-13T16:00:57",
                    },
                    {
                        "data_type": "news_search",
                        "provider": "Tavily",
                        "success": True,
                        "created_at": "2026-06-13T16:01:00",
                    },
                ],
                "llm_runs": [],
                "history_runs": [],
                "notification_runs": [],
            },
        }

        snapshot = build_history_run_flow_snapshot(
            _history_record(
                context_snapshot=context_snapshot,
                code="MARKET",
                name="大盘复盘",
                report_type="market_review",
            )
        )

        provider_labels = {node.label for node in snapshot.nodes if node.kind == "data_source"}
        self.assertEqual(snapshot.stock_code, "MARKET")
        self.assertNotIn("日线K线 · StockFetcher", provider_labels)
        self.assertIn("新闻舆情 · Tavily", provider_labels)

    def test_stock_run_flow_filters_nested_market_context_artifacts(self) -> None:
        context_snapshot = {
            "diagnostics": {
                "trace_id": "trace-stock",
                "query_id": "query-flow",
                "stock_code": "688521.SH",
                "provider_runs": [
                    {
                        "data_type": "news_search",
                        "provider": "MarketNews",
                        "success": True,
                        "created_at": "2026-06-13T16:01:00",
                    },
                    {
                        "data_type": "realtime_quote",
                        "provider": "Akshare",
                        "success": True,
                        "created_at": "2026-06-13T16:01:51",
                    },
                    {
                        "data_type": "news_search",
                        "provider": "StockNews",
                        "success": True,
                        "created_at": "2026-06-13T16:02:25",
                    },
                ],
                "llm_runs": [
                    {
                        "call_type": "analysis",
                        "success": True,
                        "created_at": "2026-06-13T16:03:54",
                    }
                ],
                "history_runs": [
                    {
                        "report_saved": True,
                        "metadata_saved": True,
                        "created_at": "2026-06-13T16:01:51",
                    },
                    {
                        "report_saved": True,
                        "metadata_saved": True,
                        "created_at": "2026-06-13T16:04:12",
                    },
                ],
                "notification_runs": [
                    {
                        "channel": "report",
                        "status": "skipped",
                        "success": False,
                        "attempts": 0,
                        "created_at": "2026-06-13T16:01:51",
                    },
                    {
                        "channel": "report",
                        "status": "not_configured",
                        "success": False,
                        "attempts": 0,
                        "created_at": "2026-06-13T16:04:12",
                    },
                ],
            },
            "analysis_context_pack_overview": _overview(
                blocks=[
                    {
                        "key": "quote",
                        "label": "行情",
                        "status": "available",
                        "source": "Akshare",
                        "warnings": [],
                        "missing_reasons": [],
                    }
                ]
            ),
        }

        snapshot = build_history_run_flow_snapshot(_history_record(context_snapshot=context_snapshot))

        self.assertEqual(
            [node.label for node in snapshot.nodes if node.label == "保存报告"],
            ["保存报告"],
        )
        self.assertEqual(
            [node.label for node in snapshot.nodes if node.label.startswith("推送通知")],
            ["推送通知 · report"],
        )
        provider_labels = {node.label for node in snapshot.nodes if node.kind == "data_source"}
        self.assertNotIn("新闻舆情 · MarketNews", provider_labels)
        self.assertIn("新闻舆情 · StockNews", provider_labels)
        notification = next(node for node in snapshot.nodes if node.id.startswith("notification_report"))
        self.assertEqual(notification.attempts, 0)

    def test_market_review_persist_records_diagnostics_with_saved_history_id(self) -> None:
        from src.core.market_review import _persist_market_review_history

        fake_db = _FakeMarketReviewDb(save_result=42)
        config = SimpleNamespace(report_language="zh")
        token = activate_run_diagnostic_context(
            trace_id="trace-market",
            task_id="task-market",
            query_id="query-flow",
            stock_code="MARKET",
            trigger_source="api",
        )
        try:
            with patch("src.storage.DatabaseManager.get_instance", return_value=fake_db):
                saved = _persist_market_review_history(
                    review_report="大盘复盘报告",
                    markdown_report="# 大盘复盘报告",
                    region="cn",
                    config=config,
                    query_id="query-flow",
                )
        finally:
            reset_run_diagnostic_context(token)

        self.assertTrue(saved)
        self.assertIsNotNone(fake_db.saved_context_snapshot)
        self.assertIn("diagnostics", fake_db.saved_context_snapshot)
        self.assertIn("analysis_context_pack_overview", fake_db.saved_context_snapshot)
        self.assertIsNotNone(fake_db.updated_diagnostics)
        history_runs = fake_db.updated_diagnostics["history_runs"]
        self.assertTrue(history_runs)
        self.assertEqual(history_runs[-1].get("analysis_history_id"), 42)

    def test_flow_endpoints_return_404_for_missing_records(self) -> None:
        with self.assertRaises(HTTPException) as history_ctx:
            get_history_run_flow("404", db_manager=_FakeHistoryDb(None))
        self.assertEqual(history_ctx.exception.status_code, 404)

        queue = SimpleNamespace(get_task=lambda task_id: None)
        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), patch(
            "api.v1.endpoints.analysis._load_history_run_flow_by_query_id",
            return_value=None,
        ):
            with self.assertRaises(HTTPException) as task_ctx:
                get_task_run_flow("missing-task")
        self.assertEqual(task_ctx.exception.status_code, 404)

    def test_completed_task_flow_refresh_uses_persisted_history_report_type_alias(self) -> None:
        task = TaskInfo(
            task_id="query-flow",
            trace_id="trace-flow",
            stock_code="600519",
            stock_name="贵州茅台",
            status=TaskStatus.COMPLETED,
            report_type="detailed",
        )
        queue = SimpleNamespace(get_task=lambda task_id: task)

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), patch(
            "api.v1.endpoints.analysis._load_history_run_flow_by_query_id",
            return_value=None,
        ) as load_history:
            snapshot = get_task_run_flow("query-flow")

        self.assertEqual(snapshot.task_id, "query-flow")
        load_history.assert_called_once_with(
            "query-flow",
            code="600519",
            report_type="full",
            fail_open=True,
        )

    def test_completed_market_review_task_flow_uses_market_history_filters(self) -> None:
        task = TaskInfo(
            task_id="market-query-flow",
            trace_id="trace-market-flow",
            stock_code="cn",
            stock_name="大盘复盘",
            status=TaskStatus.COMPLETED,
            report_type="market-review",
        )
        queue = SimpleNamespace(get_task=lambda task_id: task)

        with patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue), patch(
            "api.v1.endpoints.analysis._load_history_run_flow_by_query_id",
            return_value=None,
        ) as load_history:
            snapshot = get_task_run_flow("market-query-flow")

        self.assertEqual(snapshot.task_id, "market-query-flow")
        load_history.assert_called_once_with(
            "market-query-flow",
            code="MARKET",
            report_type="market_review",
            fail_open=True,
        )

    def test_run_flow_payload_redacts_errors_metadata_and_sensitive_paths(self) -> None:
        context_snapshot = {
            "diagnostics": _diagnostics(unsafe=True),
            "analysis_context_pack_overview": _overview(
                blocks=[
                    {
                        "key": "daily_bars",
                        "label": "日线",
                        "status": "fetch_failed",
                        "source": "UnsafeFetcher",
                        "warnings": ["failed"],
                        "missing_reasons": ["/home/activer/private/file.csv"],
                    }
                ]
            ),
        }

        snapshot = build_history_run_flow_snapshot(_history_record(context_snapshot=context_snapshot))
        payload = json.dumps(snapshot.model_dump(mode="json", by_alias=True), ensure_ascii=False)

        for leaked in (
            "sk-secret",
            "secret-token",
            "hooks.example.com/webhook",
            "full-user-prompt",
            "/home/activer",
        ):
            self.assertNotIn(leaked, payload)
        self.assertIn("<redacted>", payload)
        self.assertIn("<redacted-path>", payload)


if __name__ == "__main__":
    unittest.main()
