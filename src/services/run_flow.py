# -*- coding: utf-8 -*-
"""Build sanitized run-flow snapshots from tasks and persisted diagnostics."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from api.v1.schemas.run_flow import RunFlowSnapshot
from src.analysis_context_pack_overview import extract_analysis_context_pack_overview
from src.services.run_diagnostics import (
    safe_diagnostic_key,
    sanitize_diagnostic_metadata,
    sanitize_diagnostic_text,
)
from src.utils.data_processing import normalize_model_used, parse_json_field


_LANES = [
    {"id": "entry", "label": "入口", "order": 1},
    {"id": "data_source", "label": "数据来源", "order": 2},
    {"id": "analysis", "label": "分析引擎", "order": 3},
    {"id": "artifact", "label": "产物", "order": 4},
]

_RUN_STATUS_MAP = {
    "pending": "pending",
    "processing": "running",
    "running": "running",
    "completed": "success",
    "success": "success",
    "failed": "failed",
    "cancel_requested": "cancel_requested",
    "cancelled": "cancelled",
}

_DATA_TYPE_LABELS = {
    "realtime_quote": "实时行情",
    "daily_data": "日线K线",
    "daily_bars": "日线K线",
    "technical": "技术指标",
    "news": "新闻舆情",
    "news_search": "新闻舆情",
    "fundamental": "基本面",
    "fundamentals": "基本面",
    "belong_boards": "所属板块",
    "chip": "筹码结构",
}

_DATA_TYPE_TO_BLOCK_KEY = {
    "realtime_quote": "quote",
    "daily_data": "daily_bars",
    "daily_bars": "daily_bars",
    "technical": "technical",
    "news": "news",
    "news_search": "news",
    "fundamental": "fundamentals",
    "fundamentals": "fundamentals",
    "belong_boards": "fundamentals",
    "chip": "chip",
}

_CONTEXT_STATUS_TO_FLOW = {
    "available": "success",
    "fallback": "fallback",
    "partial": "degraded",
    "stale": "degraded",
    "estimated": "degraded",
    "missing": "skipped",
    "not_supported": "skipped",
    "fetch_failed": "failed",
}

def build_task_run_flow_snapshot(
    task: Any,
    *,
    generated_at: Optional[datetime] = None,
) -> RunFlowSnapshot:
    """Build a skeleton run-flow snapshot from an in-memory task."""
    status_value = _task_status_value(task)
    flow_status = _map_task_status(status_value)
    task_id = _safe_text(getattr(task, "task_id", None), max_length=96) or "unknown"
    trace_id = _safe_text(getattr(task, "trace_id", None), max_length=96) or task_id
    stock_code = _safe_text(getattr(task, "stock_code", None), max_length=32) or "unknown"
    stock_name = _safe_text(getattr(task, "stock_name", None), max_length=80)

    created_at = _datetime_to_iso(getattr(task, "created_at", None))
    started_at = _datetime_to_iso(getattr(task, "started_at", None))
    completed_at = _datetime_to_iso(getattr(task, "completed_at", None))
    now_iso = _datetime_to_iso(generated_at or datetime.now()) or datetime.now().isoformat()

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []

    _put_node(
        nodes,
        "request",
        lane="entry",
        kind="entry",
        label="用户请求",
        status="success" if created_at else "unknown",
        started_at=created_at,
        ended_at=created_at,
        message=_safe_text(getattr(task, "original_query", None), max_length=120)
        or "任务请求已创建",
        metadata={
            "selection_source": getattr(task, "selection_source", None),
            "query_source": getattr(task, "query_source", None),
            "report_type": getattr(task, "report_type", None),
            "analysis_phase": getattr(task, "analysis_phase", None),
        },
    )
    _put_node(
        nodes,
        "task_queue",
        lane="entry",
        kind="queue",
        label="任务队列",
        status=flow_status,
        started_at=created_at,
        ended_at=completed_at,
        duration_ms=_elapsed_ms(getattr(task, "created_at", None), getattr(task, "completed_at", None)),
        message=getattr(task, "message", None) or _task_status_message(flow_status),
        metadata={
            "progress": getattr(task, "progress", None),
            "error": getattr(task, "error", None),
        },
    )
    _append_edge(edges, "request", "task_queue", "control", flow_status, label="提交")

    if flow_status in {"pending", "running", "cancel_requested"}:
        _put_node(
            nodes,
            "analysis_pipeline",
            lane="analysis",
            kind="analysis",
            label="分析流程",
            status="running" if flow_status == "running" else flow_status,
            started_at=started_at,
            message=getattr(task, "message", None) or _task_status_message(flow_status),
        )
        _append_edge(edges, "task_queue", "analysis_pipeline", "control", flow_status, label="调度")
    else:
        _put_skeleton_tail(nodes, edges, anchor_node_id="task_queue", status=flow_status)

    _append_task_events(events, task, flow_status)
    _append_active_flow_events(
        nodes,
        edges,
        events,
        _as_list(getattr(task, "flow_events", None)),
        flow_status=flow_status,
    )
    _prune_active_skeleton_tail(nodes, edges)

    summary = _build_summary(
        nodes,
        edges,
        events,
        elapsed_ms=_elapsed_ms(getattr(task, "created_at", None), getattr(task, "completed_at", None)),
    )
    return RunFlowSnapshot.model_validate(
        {
            "task_id": task_id,
            "trace_id": trace_id,
            "stock_code": stock_code,
            "stock_name": stock_name,
            "status": flow_status,
            "summary": summary,
            "lanes": _LANES,
            "nodes": list(nodes.values()),
            "edges": edges,
            "events": events,
            "generated_at": now_iso,
        }
    )


def build_history_run_flow_snapshot(
    record: Any,
    *,
    context_snapshot: Optional[Any] = None,
    raw_result: Optional[Any] = None,
    generated_at: Optional[datetime] = None,
) -> RunFlowSnapshot:
    """Build a run-flow snapshot from a persisted history record."""
    snapshot = _as_mapping(context_snapshot if context_snapshot is not None else getattr(record, "context_snapshot", None))
    raw = _as_mapping(raw_result if raw_result is not None else getattr(record, "raw_result", None))
    diagnostics = _as_mapping(snapshot.get("diagnostics")) if snapshot else {}
    diagnostics = _normalize_history_diagnostics_for_record(record, snapshot, diagnostics)
    overview = extract_analysis_context_pack_overview(snapshot) if snapshot else None
    overview_metadata = overview.get("metadata") if isinstance((overview or {}).get("metadata"), Mapping) else {}

    query_id = _safe_text(getattr(record, "query_id", None), max_length=96) or diagnostics.get("query_id") or "unknown"
    task_id = _safe_text(diagnostics.get("task_id"), max_length=96) or query_id
    trace_id = (
        _safe_text(diagnostics.get("trace_id"), max_length=96)
        or _safe_text(snapshot.get("trace_id") if snapshot else None, max_length=96)
        or _safe_text(raw.get("trace_id") if raw else None, max_length=96)
        or task_id
    )
    stock_code = (
        _safe_text(getattr(record, "code", None), max_length=32)
        or _safe_text(diagnostics.get("stock_code"), max_length=32)
        or _safe_text(raw.get("stock_code") or raw.get("code"), max_length=32)
        or "unknown"
    )
    stock_name = _safe_text(getattr(record, "name", None), max_length=80) or _safe_text(raw.get("name"), max_length=80)
    created_at = _datetime_to_iso(getattr(record, "created_at", None))
    now_iso = _datetime_to_iso(generated_at or datetime.now()) or datetime.now().isoformat()

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []

    _put_node(
        nodes,
        "request",
        lane="entry",
        kind="entry",
        label="用户请求",
        status="success",
        started_at=created_at,
        ended_at=created_at,
        message="历史分析记录",
        metadata={
            "query_id": query_id,
            "trigger_source": diagnostics.get("trigger_source") or overview_metadata.get("trigger_source"),
            "report_type": getattr(record, "report_type", None),
        },
    )
    _put_node(
        nodes,
        "task_queue",
        lane="entry",
        kind="queue",
        label="任务队列",
        status="success",
        started_at=created_at,
        ended_at=created_at,
        message="任务已完成并进入历史记录",
    )
    _append_edge(edges, "request", "task_queue", "control", "success", label="提交")
    _append_event(
        events,
        "task_completed",
        node_id="task_queue",
        timestamp=created_at,
        severity="success",
        title="任务完成",
        message="历史记录已生成",
    )

    provider_success_by_block = _append_provider_runs(
        nodes,
        edges,
        events,
        _as_list(diagnostics.get("provider_runs")),
    )

    context_status = _context_pack_status(overview)
    _put_node(
        nodes,
        "context_pack",
        lane="analysis",
        kind="analysis",
        label="ContextPack",
        status=context_status,
        started_at=(overview or {}).get("created_at"),
        message=_context_pack_message(overview),
        metadata={
            "pack_version": (overview or {}).get("pack_version"),
            "counts": (overview or {}).get("counts"),
            "warnings": (overview or {}).get("warnings"),
            "data_quality": (overview or {}).get("data_quality"),
        },
    )
    _append_context_blocks(nodes, edges, events, overview, provider_success_by_block)
    if not any(edge["to"] == "context_pack" for edge in edges):
        _append_edge(edges, "task_queue", "context_pack", "data", context_status, label="输入")

    last_analysis_node = _append_llm_runs(
        nodes,
        edges,
        events,
        _as_list(diagnostics.get("llm_runs")),
        raw,
    )
    if last_analysis_node is None:
        _put_node(
            nodes,
            "llm",
            lane="analysis",
            kind="model",
            label="LLM 生成",
            status="unknown",
            provider=normalize_model_used(raw.get("model_used")) if raw else None,
            message="LLM 未记录诊断信息",
        )
        _append_edge(edges, "context_pack", "llm", "data", "unknown", label="生成")
        last_analysis_node = "llm"

    last_artifact_node = _append_history_runs(
        nodes,
        edges,
        events,
        _as_list(diagnostics.get("history_runs")),
        anchor_node_id=last_analysis_node,
        fallback_created_at=created_at,
    )
    if last_artifact_node is None:
        _put_node(
            nodes,
            "history_save",
            lane="artifact",
            kind="artifact",
            label="保存报告",
            status="success",
            ended_at=created_at,
            message="历史记录已存在",
            metadata={"analysis_history_id": getattr(record, "id", None)},
        )
        _append_edge(edges, last_analysis_node, "history_save", "data", "success", label="保存")
        last_artifact_node = "history_save"

    notification_count = _append_notification_runs(
        nodes,
        edges,
        events,
        _as_list(diagnostics.get("notification_runs")),
        anchor_node_id=last_artifact_node,
    )
    if notification_count == 0:
        _put_node(
            nodes,
            "notification",
            lane="artifact",
            kind="notification",
            label="推送通知",
            status="unknown",
            message="通知结果未记录",
        )
        _append_edge(edges, last_artifact_node, "notification", "control", "unknown", label="通知")

    summary = _build_summary(nodes, edges, events)
    status = _history_snapshot_status(nodes, diagnostics, overview)
    if summary.get("model") is None:
        summary["model"] = _safe_text(normalize_model_used(raw.get("model_used")) if raw else None, max_length=120)

    return RunFlowSnapshot.model_validate(
        {
            "task_id": task_id,
            "trace_id": trace_id,
            "stock_code": stock_code,
            "stock_name": stock_name,
            "status": status,
            "summary": summary,
            "lanes": _LANES,
            "nodes": list(nodes.values()),
            "edges": edges,
            "events": events,
            "generated_at": now_iso,
        }
    )


def _append_provider_runs(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    provider_runs: List[Any],
) -> Dict[str, str]:
    success_by_data_type = {
        data_type: any(_as_mapping(run).get("success") is True for run in runs)
        for data_type, runs in _group_provider_runs(provider_runs).items()
    }
    previous_node_by_type: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    provider_success_by_block: Dict[str, str] = {}
    attempt_index_by_type: Dict[str, int] = defaultdict(int)

    for index, raw_run in enumerate(provider_runs, start=1):
        run = _as_mapping(raw_run)
        if not run:
            continue
        data_type = _safe_key(run.get("data_type") or "provider")
        attempt_index_by_type[data_type] += 1
        attempt_index = attempt_index_by_type[data_type]
        provider = _safe_text(run.get("provider"), max_length=80) or "unknown"
        label = _DATA_TYPE_LABELS.get(data_type, data_type)
        node_id = f"provider_{_safe_key(data_type)}_{_safe_key(provider)}_{attempt_index}"
        success = run.get("success") is True
        had_previous_failure = data_type in previous_node_by_type and previous_node_by_type[data_type][1].get("success") is False
        status = _provider_run_status(run, had_previous_failure=had_previous_failure)
        duration_ms = _safe_int(run.get("latency_ms"))
        timestamp = _datetime_to_iso(run.get("created_at"))
        started_at = _started_at_from_end_and_duration(timestamp, duration_ms)
        message = _provider_run_message(label, provider, run, success=success)
        block_key = _DATA_TYPE_TO_BLOCK_KEY.get(data_type, data_type)

        _put_node(
            nodes,
            node_id,
            lane="data_source",
            kind="data_source",
            label=f"{label} · {provider}",
            status=status,
            provider=provider,
            started_at=started_at,
            ended_at=timestamp,
            duration_ms=duration_ms,
            attempts=1,
            record_count=_safe_int(run.get("record_count")),
            message=message,
            metadata={
                "data_type": data_type,
                "operation": run.get("operation"),
                "attempt": attempt_index,
                "fallback_from": run.get("fallback_from"),
                "fallback_to": run.get("fallback_to"),
                "cache_hit": run.get("cache_hit"),
                "stale_seconds": run.get("stale_seconds"),
                "error_type": run.get("error_type"),
                "error_message": run.get("error_message_sanitized"),
            },
        )

        previous = previous_node_by_type.get(data_type)
        if previous:
            previous_node_id, previous_run = previous
            edge_kind = _provider_transition_kind(previous_run, run)
            _append_edge(
                edges,
                previous_node_id,
                node_id,
                edge_kind,
                status,
                label="降级" if edge_kind == "fallback" else "重试",
                message=_safe_text(run.get("fallback_from") or run.get("fallback_to"), max_length=120),
            )
        else:
            _append_edge(edges, "task_queue", node_id, "control", status, label="调用")

        if success:
            provider_success_by_block[block_key] = node_id

        severity = "success" if success else ("warning" if success_by_data_type.get(data_type) else "danger")
        _append_event(
            events,
            "provider_run",
            node_id=node_id,
            timestamp=timestamp,
            severity=severity,
            title=f"{label}{'成功' if success else '失败'}",
            message=message,
            metadata={
                "provider": provider,
                "data_type": data_type,
                "duration_ms": duration_ms,
                "record_count": run.get("record_count"),
                "fallback_from": run.get("fallback_from"),
                "fallback_to": run.get("fallback_to"),
                "error_type": run.get("error_type"),
            },
        )
        previous_node_by_type[data_type] = (node_id, run)

    return provider_success_by_block


def _append_context_blocks(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    overview: Optional[Dict[str, Any]],
    provider_success_by_block: Dict[str, str],
) -> None:
    if not overview:
        return
    metadata = overview.get("metadata") if isinstance(overview.get("metadata"), Mapping) else {}
    overview_timestamp = overview.get("created_at")
    for block in _as_list(overview.get("blocks")):
        block_map = _as_mapping(block)
        key = _safe_key(block_map.get("key"))
        if not key:
            continue
        status = _CONTEXT_STATUS_TO_FLOW.get(str(block_map.get("status") or ""), "unknown")
        node_id = f"context_block_{key}"
        record_count = metadata.get("news_result_count") if key == "news" else None
        _put_node(
            nodes,
            node_id,
            lane="data_source",
            kind="data_source",
            label=_safe_text(block_map.get("label"), max_length=80) or key,
            status=status,
            provider=block_map.get("source"),
            started_at=overview_timestamp,
            ended_at=overview_timestamp,
            record_count=_safe_int(record_count),
            message=_context_block_message(block_map),
            metadata={
                "block_key": key,
                "source": block_map.get("source"),
                "warnings": block_map.get("warnings"),
                "missing_reasons": block_map.get("missing_reasons"),
            },
        )
        provider_node_id = provider_success_by_block.get(key)
        if provider_node_id:
            _append_edge(edges, provider_node_id, node_id, "data", status, label="输入")
        else:
            _append_edge(edges, "task_queue", node_id, "data", status, label="输入")
        _append_edge(edges, node_id, "context_pack", "data", status, label="组装")
        if status != "success":
            _append_event(
                events,
                "context_block_status",
                node_id=node_id,
                timestamp=overview.get("created_at"),
                severity="danger" if status == "failed" else "warning",
                title=f"{block_map.get('label') or key}输入状态",
                message=_context_block_message(block_map),
                metadata={
                    "block_key": key,
                    "status": block_map.get("status"),
                    "warnings": block_map.get("warnings"),
                    "missing_reasons": block_map.get("missing_reasons"),
                },
            )


def _append_llm_runs(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    llm_runs: List[Any],
    raw_result: Dict[str, Any],
) -> Optional[str]:
    previous_node_id = "context_pack"
    last_node_id: Optional[str] = None
    for index, raw_run in enumerate(llm_runs, start=1):
        run = _as_mapping(raw_run)
        if not run:
            continue
        call_type = _safe_key(run.get("call_type") or "analysis")
        model = normalize_model_used(run.get("model")) or normalize_model_used(raw_result.get("model_used"))
        provider = _safe_text(run.get("provider"), max_length=80)
        node_id = f"llm_{call_type}_{index}"
        success = run.get("success") is True
        status = "success" if success else "failed"
        if success and (run.get("fallback_model") or index > 1):
            status = "fallback"
        timestamp = _datetime_to_iso(run.get("created_at"))
        duration_ms = _safe_int(run.get("duration_ms"))
        started_at = _started_at_from_end_and_duration(timestamp, duration_ms)
        message = _llm_run_message(model, run, success=success)
        edge_kind = "data"
        if index > 1:
            edge_kind = "fallback" if run.get("fallback_model") else "retry"
        _put_node(
            nodes,
            node_id,
            lane="analysis",
            kind="model",
            label="LLM 生成",
            status=status,
            provider=model or provider,
            started_at=started_at,
            ended_at=timestamp,
            duration_ms=duration_ms,
            attempts=1,
            message=message,
            metadata={
                "provider": provider,
                "model": model,
                "call_type": call_type,
                "tokens": run.get("tokens"),
                "fallback_model": run.get("fallback_model"),
                "error_type": run.get("error_type"),
                "error_message": run.get("error_message_sanitized"),
            },
        )
        _append_edge(edges, previous_node_id, node_id, edge_kind, status, label="生成")
        _append_event(
            events,
            "llm_run",
            node_id=node_id,
            timestamp=timestamp,
            severity="success" if success else "danger",
            title=f"LLM {'成功' if success else '失败'}",
            message=message,
            metadata={
                "provider": provider,
                "model": model,
                "call_type": call_type,
                "tokens": run.get("tokens"),
                "duration_ms": duration_ms,
                "fallback_model": run.get("fallback_model"),
                "error_type": run.get("error_type"),
            },
        )
        previous_node_id = node_id
        last_node_id = node_id
    return last_node_id


def _append_history_runs(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    history_runs: List[Any],
    *,
    anchor_node_id: str,
    fallback_created_at: Optional[str],
) -> Optional[str]:
    last_node_id: Optional[str] = None
    previous_node_id = anchor_node_id
    for index, raw_run in enumerate(history_runs, start=1):
        run = _as_mapping(raw_run)
        if not run:
            continue
        success = run.get("report_saved") is True
        status = "success" if success else "failed"
        node_id = "history_save" if index == 1 else f"history_save_{index}"
        timestamp = _datetime_to_iso(run.get("created_at")) or fallback_created_at
        message = "报告历史已保存" if success else f"报告历史保存失败：{_safe_text(run.get('error_message_sanitized'), max_length=160) or '未知错误'}"
        _put_node(
            nodes,
            node_id,
            lane="artifact",
            kind="artifact",
            label="保存报告",
            status=status,
            ended_at=timestamp,
            message=message,
            metadata={
                "metadata_saved": run.get("metadata_saved"),
                "analysis_history_id": run.get("analysis_history_id"),
                "error_message": run.get("error_message_sanitized"),
            },
        )
        _append_edge(edges, previous_node_id, node_id, "data", status, label="保存")
        _append_event(
            events,
            "history_run",
            node_id=node_id,
            timestamp=timestamp,
            severity="success" if success else "danger",
            title="历史保存成功" if success else "历史保存失败",
            message=message,
            metadata={
                "metadata_saved": run.get("metadata_saved"),
                "analysis_history_id": run.get("analysis_history_id"),
            },
        )
        previous_node_id = node_id
        last_node_id = node_id
    return last_node_id


def _append_notification_runs(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    notification_runs: List[Any],
    *,
    anchor_node_id: str,
) -> int:
    count = 0
    for index, raw_run in enumerate(notification_runs, start=1):
        run = _as_mapping(raw_run)
        if not run:
            continue
        count += 1
        channel = _safe_text(run.get("channel"), max_length=80) or "unknown"
        raw_status = _safe_text(run.get("status"), max_length=80) or "unknown"
        if raw_status in {"skipped", "not_configured"}:
            status = "skipped"
        elif run.get("success") is True:
            status = "success"
        elif run.get("success") is False:
            status = "failed"
        else:
            status = "unknown"
        node_id = f"notification_{_safe_key(channel)}_{index}"
        timestamp = _datetime_to_iso(run.get("created_at"))
        message = _notification_run_message(channel, run, status)
        _put_node(
            nodes,
            node_id,
            lane="artifact",
            kind="notification",
            label=f"推送通知 · {channel}",
            status=status,
            provider=channel,
            ended_at=timestamp,
            attempts=_safe_int(run.get("attempts")) if _safe_int(run.get("attempts")) is not None else 1,
            message=message,
            metadata={
                "channel": channel,
                "status": raw_status,
                "attempts": run.get("attempts"),
                "error_message": run.get("error_message_sanitized"),
            },
        )
        _append_edge(edges, anchor_node_id, node_id, "control", status, label="通知")
        _append_event(
            events,
            "notification_run",
            node_id=node_id,
            timestamp=timestamp,
            severity="success" if status == "success" else ("warning" if status == "skipped" else "danger"),
            title="通知发送成功" if status == "success" else ("通知跳过" if status == "skipped" else "通知失败"),
            message=message,
            metadata={
                "channel": channel,
                "status": raw_status,
                "attempts": run.get("attempts"),
            },
        )
    return count


_STOCK_CONTEXT_PROVIDER_DATA_TYPES = {
    "realtime_quote",
    "daily_data",
    "daily_bars",
    "technical",
    "fundamental",
    "fundamentals",
    "belong_boards",
    "chip",
}


def _normalize_history_diagnostics_for_record(
    record: Any,
    snapshot: Dict[str, Any],
    diagnostics: Dict[str, Any],
) -> Dict[str, Any]:
    if not diagnostics:
        return diagnostics

    normalized = dict(diagnostics)
    report_type = _safe_key(getattr(record, "report_type", None))
    code = _safe_text(getattr(record, "code", None), max_length=32)
    report_kind = _safe_key(snapshot.get("report_kind")) if snapshot else ""

    if report_type == "market_review" or report_kind == "market_review" or (code or "").upper() == "MARKET":
        normalized["stock_code"] = "MARKET"
        normalized.setdefault("scope", "market_review")
        normalized["provider_runs"] = [
            run
            for run in _as_list(normalized.get("provider_runs"))
            if _safe_key(_as_mapping(run).get("data_type")) not in _STOCK_CONTEXT_PROVIDER_DATA_TYPES
        ]
        return normalized

    first_llm_at = _first_timestamp(_as_list(normalized.get("llm_runs")))
    if first_llm_at is not None:
        normalized["history_runs"] = [
            run
            for run in _as_list(normalized.get("history_runs"))
            if not _timestamp_before(_as_mapping(run).get("created_at"), first_llm_at)
        ]
        normalized["notification_runs"] = [
            run
            for run in _as_list(normalized.get("notification_runs"))
            if not _timestamp_before(_as_mapping(run).get("created_at"), first_llm_at)
        ]

    first_stock_data_at = _first_timestamp(
        [
            run
            for run in _as_list(normalized.get("provider_runs"))
            if _safe_key(_as_mapping(run).get("data_type")) in _STOCK_CONTEXT_PROVIDER_DATA_TYPES
        ]
    )
    if first_stock_data_at is not None:
        normalized["provider_runs"] = [
            run
            for run in _as_list(normalized.get("provider_runs"))
            if _safe_key(_as_mapping(run).get("data_type")) != "news_search"
            or not _timestamp_before(_as_mapping(run).get("created_at"), first_stock_data_at)
        ]
    return normalized


def _first_timestamp(items: List[Any]) -> Optional[datetime]:
    timestamps = [
        parsed
        for parsed in (_datetime_for_elapsed(_as_mapping(item).get("created_at")) for item in items)
        if parsed is not None
    ]
    return min(timestamps) if timestamps else None


def _timestamp_before(value: Any, boundary: datetime) -> bool:
    parsed = _datetime_for_elapsed(value)
    if parsed is None:
        return False
    if parsed.tzinfo is None and boundary.tzinfo is not None:
        parsed = parsed.replace(tzinfo=boundary.tzinfo)
    elif parsed.tzinfo is not None and boundary.tzinfo is None:
        boundary = boundary.replace(tzinfo=parsed.tzinfo)
    return parsed < boundary


def _put_skeleton_tail(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    *,
    anchor_node_id: str,
    status: str,
) -> None:
    downstream_status = "skipped" if status in {"failed", "cancelled"} else "unknown"
    _put_node(
        nodes,
        "context_pack",
        lane="analysis",
        kind="analysis",
        label="ContextPack",
        status=downstream_status,
        message="尚未记录输入上下文诊断",
    )
    _put_node(
        nodes,
        "llm",
        lane="analysis",
        kind="model",
        label="LLM 生成",
        status=downstream_status,
        message="尚未记录 LLM 诊断",
    )
    _put_node(
        nodes,
        "history_save",
        lane="artifact",
        kind="artifact",
        label="保存报告",
        status=downstream_status,
        message="尚未记录历史保存结果",
    )
    _put_node(
        nodes,
        "notification",
        lane="artifact",
        kind="notification",
        label="推送通知",
        status=downstream_status,
        message="尚未记录通知结果",
    )
    _append_edge(edges, anchor_node_id, "context_pack", "data", downstream_status, label="输入")
    _append_edge(edges, "context_pack", "llm", "data", downstream_status, label="生成")
    _append_edge(edges, "llm", "history_save", "data", downstream_status, label="保存")
    _append_edge(edges, "history_save", "notification", "control", downstream_status, label="通知")


def _prune_active_skeleton_tail(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> None:
    remove_node_ids = set()
    if "llm" in nodes and any(node_id.startswith("llm_") for node_id in nodes):
        remove_node_ids.add("llm")
    if "notification" in nodes and any(node_id.startswith("notification_") for node_id in nodes):
        remove_node_ids.add("notification")
    if not remove_node_ids:
        return
    for node_id in remove_node_ids:
        nodes.pop(node_id, None)
    edges[:] = [
        edge
        for edge in edges
        if edge.get("from") not in remove_node_ids and edge.get("to") not in remove_node_ids
    ]


def _append_task_events(events: List[Dict[str, Any]], task: Any, flow_status: str) -> None:
    _append_event(
        events,
        "task_created",
        node_id="task_queue",
        timestamp=_datetime_to_iso(getattr(task, "created_at", None)),
        severity="info",
        title="任务已创建",
        message=getattr(task, "message", None) or "任务已加入队列",
    )
    if getattr(task, "started_at", None):
        _append_event(
            events,
            "task_started",
            node_id="task_queue",
            timestamp=_datetime_to_iso(getattr(task, "started_at", None)),
            severity="info",
            title="任务开始执行",
            message=getattr(task, "message", None) or "任务执行中",
        )
    if flow_status == "failed":
        _append_event(
            events,
            "task_failed",
            node_id="task_queue",
            timestamp=_datetime_to_iso(getattr(task, "completed_at", None)),
            severity="danger",
            title="任务失败",
            message=getattr(task, "error", None) or getattr(task, "message", None),
        )
    elif flow_status in {"cancel_requested", "cancelled"}:
        _append_event(
            events,
            f"task_{flow_status}",
            node_id="task_queue",
            timestamp=_datetime_to_iso(getattr(task, "completed_at", None)),
            severity="warning",
            title="任务取消" if flow_status == "cancelled" else "任务请求取消",
            message=getattr(task, "message", None),
        )
    elif flow_status == "success":
        _append_event(
            events,
            "task_completed",
            node_id="task_queue",
            timestamp=_datetime_to_iso(getattr(task, "completed_at", None)),
            severity="success",
            title="任务完成",
            message=getattr(task, "message", None) or "分析完成",
        )


def _append_active_flow_events(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    flow_events: List[Any],
    *,
    flow_status: str,
) -> None:
    if not flow_events:
        return

    known_node_ids = set(nodes)
    last_provider_node_by_type: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    last_llm_node: Optional[str] = None
    last_history_node: Optional[str] = None

    for raw_event in flow_events:
        event = _as_mapping(raw_event)
        if not event:
            continue
        metadata = _sanitize_metadata(event.get("metadata") or {})
        node_payload = metadata.get("node") if isinstance(metadata, Mapping) else None
        node_id = _safe_key(event.get("node_id"))

        if isinstance(node_payload, Mapping):
            raw_node_id = _safe_text(node_payload.get("id"), max_length=120) or node_id
            if raw_node_id:
                node_id = raw_node_id
                _put_node(
                    nodes,
                    node_id,
                    lane=str(node_payload.get("lane") or "analysis"),
                    kind=str(node_payload.get("kind") or "analysis"),
                    label=str(node_payload.get("label") or node_id),
                    status=str(node_payload.get("status") or flow_status),
                    provider=node_payload.get("provider"),
                    started_at=node_payload.get("started_at")
                    or _started_at_from_end_and_duration(
                        node_payload.get("ended_at") or event.get("timestamp"),
                        node_payload.get("duration_ms"),
                    ),
                    ended_at=node_payload.get("ended_at") or event.get("timestamp"),
                    duration_ms=node_payload.get("duration_ms"),
                    attempts=node_payload.get("attempts"),
                    record_count=node_payload.get("record_count"),
                    message=node_payload.get("message") or event.get("message"),
                    metadata={key: value for key, value in metadata.items() if key != "node"},
                )

        event_type = _safe_key(event.get("type")) or "event"
        provider_data_type = None
        provider_run = None
        if event_type in {"provider_run", "provider_run_started"} and node_id and node_id in nodes:
            provider_data_type = _safe_key(metadata.get("data_type") or "provider")
            provider_run = {
                "provider": metadata.get("provider") or nodes[node_id].get("provider"),
                "success": event.get("severity") == "success" or nodes[node_id].get("status") in {"success", "fallback"},
                "fallback_from": metadata.get("fallback_from"),
                "fallback_to": metadata.get("fallback_to"),
            }

        if node_id and node_id in nodes and node_id in known_node_ids:
            _refresh_incoming_edge_status(edges, node_id, nodes[node_id].get("status"))
            if provider_data_type and provider_run:
                last_provider_node_by_type[provider_data_type] = (node_id, provider_run)
            elif event_type in {"llm_run", "llm_run_started"}:
                last_llm_node = node_id
            elif event_type == "history_run":
                last_history_node = node_id

        if node_id and node_id in nodes and node_id not in known_node_ids:
            if provider_data_type and provider_run:
                previous_provider = last_provider_node_by_type.get(provider_data_type)
                if previous_provider:
                    previous_provider_node, previous_provider_run = previous_provider
                    edge_kind = _provider_transition_kind(previous_provider_run, provider_run)
                    _append_edge(
                        edges,
                        previous_provider_node,
                        node_id,
                        edge_kind,
                        nodes[node_id].get("status", "unknown"),
                        label="降级" if edge_kind == "fallback" else ("重试" if edge_kind == "retry" else "调用"),
                    )
                else:
                    _append_edge(edges, "task_queue", node_id, "control", nodes[node_id].get("status", "unknown"), label="调用")
                last_provider_node_by_type[provider_data_type] = (node_id, provider_run)
            elif event_type in {"llm_run", "llm_run_started"}:
                anchor = "analysis_pipeline" if "analysis_pipeline" in nodes else "task_queue"
                _append_edge(edges, anchor, node_id, "data", nodes[node_id].get("status", "unknown"), label="生成")
                last_llm_node = node_id
            elif event_type == "history_run":
                anchor = last_llm_node or ("analysis_pipeline" if "analysis_pipeline" in nodes else "task_queue")
                _append_edge(edges, anchor, node_id, "data", nodes[node_id].get("status", "unknown"), label="保存")
                last_history_node = node_id
            elif event_type == "notification_run":
                anchor = last_history_node or last_llm_node or ("analysis_pipeline" if "analysis_pipeline" in nodes else "task_queue")
                _append_edge(edges, anchor, node_id, "control", nodes[node_id].get("status", "unknown"), label="通知")
            known_node_ids.add(node_id)

        _append_external_event(events, event)


def _append_external_event(events: List[Dict[str, Any]], event: Dict[str, Any]) -> None:
    event_id = _safe_text(event.get("id"), max_length=96) or f"flow_{len(events) + 1:04d}"
    if any(existing.get("id") == event_id for existing in events):
        return
    metadata = _sanitize_metadata(event.get("metadata") or {})
    if isinstance(metadata, Mapping) and "node" in metadata:
        metadata = {key: value for key, value in metadata.items() if key != "node"}
    events.append(
        {
            "id": event_id,
            "timestamp": _datetime_to_iso(event.get("timestamp")),
            "severity": event.get("severity") if event.get("severity") in {"info", "success", "warning", "danger"} else "info",
            "type": _safe_key(event.get("type")) or "event",
            "node_id": _safe_text(event.get("node_id"), max_length=120),
            "title": _safe_text(event.get("title"), max_length=100) or "运行事件",
            "message": _safe_text(event.get("message"), max_length=220),
            "metadata": metadata,
        }
    )


def _group_provider_runs(provider_runs: List[Any]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for run in provider_runs:
        run_map = _as_mapping(run)
        if run_map:
            grouped[_safe_key(run_map.get("data_type") or "provider")].append(run_map)
    return grouped


def _provider_run_status(run: Dict[str, Any], *, had_previous_failure: bool) -> str:
    if run.get("success") is True:
        if run.get("fallback_from") or had_previous_failure:
            return "fallback"
        return "success"
    error_type = str(run.get("error_type") or "").lower()
    if "timeout" in error_type:
        return "timeout"
    return "failed"


def _provider_transition_kind(previous_run: Dict[str, Any], current_run: Dict[str, Any]) -> str:
    previous_provider = _safe_text(previous_run.get("provider"), max_length=80)
    current_provider = _safe_text(current_run.get("provider"), max_length=80)
    if previous_run.get("fallback_to") or current_run.get("fallback_from"):
        return "fallback"
    if previous_provider and previous_provider == current_provider:
        return "retry"
    if previous_run.get("success") is False:
        return "fallback"
    return "data"


def _history_snapshot_status(
    nodes: Dict[str, Dict[str, Any]],
    diagnostics: Dict[str, Any],
    overview: Optional[Dict[str, Any]],
) -> str:
    statuses = [node.get("status") for node in nodes.values()]
    has_diagnostics = bool(diagnostics)
    has_overview = bool(overview)
    if not has_diagnostics and not has_overview:
        return "unknown"
    if any(
        node.get("kind") in {"model", "artifact"}
        and node.get("status") in {"failed", "timeout"}
        for node in nodes.values()
    ):
        return "failed"
    if any(status in {"failed", "timeout", "degraded", "fallback"} for status in statuses):
        return "degraded"
    return "success"


def _context_pack_status(overview: Optional[Dict[str, Any]]) -> str:
    if not overview:
        return "unknown"
    block_statuses = [
        _CONTEXT_STATUS_TO_FLOW.get(str(_as_mapping(block).get("status") or ""), "unknown")
        for block in _as_list(overview.get("blocks"))
    ]
    if not block_statuses:
        return "unknown"
    if any(status in {"failed", "fallback", "degraded", "skipped"} for status in block_statuses):
        return "degraded"
    if all(status == "success" for status in block_statuses):
        return "success"
    return "unknown"


def _context_pack_message(overview: Optional[Dict[str, Any]]) -> str:
    if not overview:
        return "未记录 AnalysisContextPack overview"
    counts = overview.get("counts")
    if isinstance(counts, Mapping):
        available = counts.get("available", 0)
        return f"输入上下文已组装，可用块 {available}"
    return "输入上下文已组装"


def _context_block_message(block: Dict[str, Any]) -> str:
    status = str(block.get("status") or "")
    if status == "available":
        return "已进入本次分析输入"
    if status == "fallback":
        return "本次分析输入使用降级数据"
    if status == "partial":
        return "本次分析输入仅部分可用"
    if status == "stale":
        return "本次分析输入使用过期数据"
    if status == "estimated":
        return "本次分析输入使用估算数据"
    if status == "fetch_failed":
        return "输入块抓取失败"
    if status == "missing":
        reasons = _as_list(block.get("missing_reasons"))
        reason = _safe_text(reasons[0], max_length=120) if reasons else None
        return f"未进入本次分析输入：{reason}" if reason else "未进入本次分析输入"
    if status == "not_supported":
        return "当前市场或链路不支持该输入块"
    return f"输入块状态为 {status or 'unknown'}"


def _provider_run_message(label: str, provider: str, run: Dict[str, Any], *, success: bool) -> str:
    if success:
        record_count = _safe_int(run.get("record_count"))
        suffix = f"，返回 {record_count} 条" if record_count is not None else ""
        return f"{label} {provider} 成功{suffix}"
    error = _safe_text(run.get("error_message_sanitized") or run.get("error_type"), max_length=160)
    return f"{label} {provider} 失败：{error or '未知错误'}"


def _llm_run_message(model: Optional[str], run: Dict[str, Any], *, success: bool) -> str:
    display_model = _safe_text(model or run.get("provider") or "unknown", max_length=120)
    if success:
        if run.get("fallback_model"):
            return f"LLM {display_model} 成功，期间发生模型切换"
        return f"LLM {display_model} 成功"
    error = _safe_text(run.get("error_message_sanitized") or run.get("error_type"), max_length=160)
    return f"LLM {display_model} 失败：{error or '未知错误'}"


def _notification_run_message(channel: str, run: Dict[str, Any], status: str) -> str:
    if status == "success":
        return f"{channel} 通知发送成功"
    if status == "skipped":
        return f"{channel} 通知跳过"
    if status == "failed":
        error = _safe_text(run.get("error_message_sanitized") or run.get("status"), max_length=160)
        return f"{channel} 通知失败：{error or '未知错误'}"
    return f"{channel} 通知结果未知"


def _build_summary(
    nodes: Dict[str, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    *,
    elapsed_ms: Optional[int] = None,
) -> Dict[str, Any]:
    bottleneck_node_id = None
    max_duration = -1
    for node_id, node in nodes.items():
        duration_ms = _safe_int(node.get("duration_ms"))
        if duration_ms is not None and duration_ms > max_duration:
            max_duration = duration_ms
            bottleneck_node_id = node_id

    if elapsed_ms is None:
        elapsed_ms = _events_elapsed_ms(events)
    if elapsed_ms is None and max_duration >= 0:
        elapsed_ms = sum(
            _safe_int(node.get("duration_ms")) or 0
            for node in nodes.values()
        ) or None

    failed_attempts = sum(
        1
        for node in nodes.values()
        if node.get("status") in {"failed", "timeout"}
        and node.get("kind") in {"data_source", "model", "artifact", "notification"}
    )
    fallback_count = sum(
        1
        for edge in edges
        if edge.get("kind") in {"fallback", "retry"}
    )
    data_source_count = sum(1 for node in nodes.values() if node.get("kind") == "data_source")
    model = next(
        (
            _safe_text(node.get("provider"), max_length=120)
            for node in nodes.values()
            if node.get("kind") == "model" and node.get("provider")
        ),
        None,
    )
    return {
        "elapsed_ms": elapsed_ms,
        "bottleneck_node_id": bottleneck_node_id,
        "failed_attempts": failed_attempts,
        "fallback_count": fallback_count,
        "model": model,
        "data_source_count": data_source_count,
        "event_count": len(events),
    }


def _put_node(
    nodes: Dict[str, Dict[str, Any]],
    node_id: str,
    *,
    lane: str,
    kind: str,
    label: str,
    status: str,
    provider: Optional[Any] = None,
    started_at: Optional[Any] = None,
    ended_at: Optional[Any] = None,
    duration_ms: Optional[Any] = None,
    attempts: Optional[Any] = None,
    record_count: Optional[Any] = None,
    message: Optional[Any] = None,
    metadata: Optional[Any] = None,
) -> None:
    payload = {
        "id": node_id,
        "lane": lane,
        "kind": kind,
        "label": _safe_text(label, max_length=80) or node_id,
        "status": _valid_status(status),
        "provider": _safe_text(provider, max_length=120),
        "started_at": _datetime_to_iso(started_at),
        "ended_at": _datetime_to_iso(ended_at),
        "duration_ms": _safe_int(duration_ms),
        "attempts": _safe_int(attempts),
        "record_count": _safe_int(record_count),
        "message": _safe_text(message, max_length=220),
        "metadata": _sanitize_metadata(metadata or {}),
    }
    nodes[node_id] = {key: value for key, value in payload.items() if value not in (None, {}, [])}


def _append_edge(
    edges: List[Dict[str, Any]],
    from_node: str,
    to_node: str,
    kind: str,
    status: str,
    *,
    label: Optional[Any] = None,
    message: Optional[Any] = None,
    metadata: Optional[Any] = None,
) -> None:
    edge_id = f"{from_node}_to_{to_node}_{kind}"
    for edge in edges:
        if edge["id"] != edge_id:
            continue
        edge["status"] = _valid_status(status)
        safe_label = _safe_text(label, max_length=40)
        if safe_label:
            edge["label"] = safe_label
        safe_message = _safe_text(message, max_length=180)
        if safe_message:
            edge["message"] = safe_message
        safe_metadata = _sanitize_metadata(metadata or {})
        if safe_metadata:
            edge["metadata"] = safe_metadata
        return
    edges.append(
        {
            "id": edge_id,
            "from": from_node,
            "to": to_node,
            "kind": kind if kind in {"data", "control", "fallback", "retry"} else "data",
            "status": _valid_status(status),
            "label": _safe_text(label, max_length=40),
            "message": _safe_text(message, max_length=180),
            "metadata": _sanitize_metadata(metadata or {}),
        }
    )


def _refresh_incoming_edge_status(
    edges: List[Dict[str, Any]],
    node_id: Optional[str],
    status: Optional[Any],
) -> None:
    if not node_id or status is None:
        return
    valid_status = _valid_status(status)
    for edge in edges:
        if edge.get("to") == node_id:
            edge["status"] = valid_status


def _append_event(
    events: List[Dict[str, Any]],
    event_type: str,
    *,
    node_id: Optional[str],
    timestamp: Optional[Any],
    severity: str,
    title: str,
    message: Optional[Any] = None,
    metadata: Optional[Any] = None,
) -> None:
    event_id = f"evt_{len(events) + 1:04d}"
    events.append(
        {
            "id": event_id,
            "timestamp": _datetime_to_iso(timestamp),
            "severity": severity if severity in {"info", "success", "warning", "danger"} else "info",
            "type": _safe_key(event_type) or "event",
            "node_id": node_id,
            "title": _safe_text(title, max_length=100) or event_type,
            "message": _safe_text(message, max_length=220),
            "metadata": _sanitize_metadata(metadata or {}),
        }
    )


def _task_status_value(task: Any) -> str:
    status = getattr(task, "status", None)
    value = getattr(status, "value", status)
    return str(value or "unknown").strip().lower()


def _map_task_status(status_value: str) -> str:
    return _RUN_STATUS_MAP.get(status_value, "unknown")


def _task_status_message(status: str) -> str:
    return {
        "pending": "任务已加入队列",
        "running": "任务执行中",
        "success": "任务已完成",
        "failed": "任务失败",
        "cancel_requested": "任务请求取消",
        "cancelled": "任务已取消",
    }.get(status, "任务状态未知")


def _valid_status(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    if text in {
        "pending",
        "running",
        "success",
        "failed",
        "degraded",
        "fallback",
        "timeout",
        "cancel_requested",
        "cancelled",
        "skipped",
        "unknown",
    }:
        return text
    return "unknown"


def _safe_text(value: Any, *, max_length: int = 300) -> Optional[str]:
    return sanitize_diagnostic_text(value, max_length=max_length)


def _safe_key(value: Any) -> str:
    return safe_diagnostic_key(value)


def _safe_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _sanitize_metadata(value: Any, *, depth: int = 0) -> Any:
    return sanitize_diagnostic_metadata(value, depth=depth)


def _as_mapping(value: Any) -> Dict[str, Any]:
    parsed = parse_json_field(value)
    if isinstance(parsed, Mapping):
        return dict(parsed)
    if isinstance(parsed, str) and parsed.strip():
        try:
            loaded = json.loads(parsed)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(loaded) if isinstance(loaded, Mapping) else {}
    return {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _datetime_to_iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return _safe_text(value, max_length=80)
    return None


def _elapsed_ms(start: Any, end: Any) -> Optional[int]:
    start_dt = _datetime_for_elapsed(start)
    end_dt = _datetime_for_elapsed(end)
    if start_dt is None or end_dt is None:
        return None
    seconds = (end_dt - start_dt).total_seconds()
    if seconds < 0:
        return None
    return int(seconds * 1000)


def _started_at_from_end_and_duration(end: Any, duration_ms: Any) -> Optional[str]:
    duration = _safe_int(duration_ms)
    if duration is None:
        return None
    if isinstance(end, datetime):
        parsed = end
    elif isinstance(end, str) and "T" in end:
        normalized = end[:-1] + "+00:00" if end.endswith("Z") else end
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None
    return (parsed - timedelta(milliseconds=duration)).isoformat()


def _local_timezone():
    return datetime.now().astimezone().tzinfo or timezone.utc


def _datetime_for_elapsed(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and "T" in value:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_local_timezone())
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _events_elapsed_ms(events: Iterable[Dict[str, Any]]) -> Optional[int]:
    timestamps: List[datetime] = []
    for event in events:
        parsed = _datetime_for_elapsed(event.get("timestamp"))
        if parsed is not None:
            timestamps.append(parsed)
    if len(timestamps) < 2:
        return None
    elapsed = (max(timestamps) - min(timestamps)).total_seconds()
    return int(elapsed * 1000) if elapsed >= 0 else None
