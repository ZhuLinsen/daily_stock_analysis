# -*- coding: utf-8 -*-
"""Run-flow snapshot API contract."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


RunFlowStatus = Literal[
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
]

RunFlowNodeKind = Literal[
    "entry",
    "queue",
    "data_source",
    "analysis",
    "model",
    "artifact",
    "notification",
]

RunFlowEdgeKind = Literal["data", "control", "fallback", "retry"]

RunFlowEventSeverity = Literal["info", "success", "warning", "danger"]


class RunFlowLane(BaseModel):
    """A fixed visual lane for the run-flow topology."""

    id: str = Field(..., description="Stable lane id")
    label: str = Field(..., description="Display label")
    order: int = Field(..., description="Display order")


class RunFlowNode(BaseModel):
    """One node in the task run-flow topology."""

    id: str = Field(..., description="Stable node id")
    lane: str = Field(..., description="Lane id")
    kind: RunFlowNodeKind = Field(..., description="Node kind")
    label: str = Field(..., description="Display label")
    status: RunFlowStatus = Field(..., description="Node status")
    provider: Optional[str] = Field(None, description="Provider/model/channel name")
    started_at: Optional[str] = Field(None, description="ISO timestamp when the node started")
    ended_at: Optional[str] = Field(None, description="ISO timestamp when the node ended")
    duration_ms: Optional[int] = Field(None, ge=0, description="Node duration in milliseconds")
    attempts: Optional[int] = Field(None, ge=0, description="Attempt count represented by this node")
    record_count: Optional[int] = Field(None, ge=0, description="Returned record count")
    message: Optional[str] = Field(None, description="Short sanitized status message")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Sanitized low-sensitivity metadata")


class RunFlowEdge(BaseModel):
    """One directed edge in the task run-flow topology."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., description="Stable edge id")
    from_node: str = Field(..., alias="from", description="Source node id")
    to_node: str = Field(..., alias="to", description="Target node id")
    kind: RunFlowEdgeKind = Field(..., description="Edge kind")
    status: RunFlowStatus = Field(..., description="Edge status")
    label: Optional[str] = Field(None, description="Short display label")
    message: Optional[str] = Field(None, description="Short sanitized edge message")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Sanitized low-sensitivity metadata")


class RunFlowEvent(BaseModel):
    """One chronological event backing the run-flow view."""

    id: str = Field(..., description="Stable event id")
    timestamp: Optional[str] = Field(None, description="ISO timestamp")
    severity: RunFlowEventSeverity = Field(..., description="Event severity")
    type: str = Field(..., description="Stable event type")
    node_id: Optional[str] = Field(None, description="Related node id")
    title: str = Field(..., description="Short event title")
    message: Optional[str] = Field(None, description="Short sanitized event message")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Sanitized low-sensitivity metadata")


class RunFlowSummary(BaseModel):
    """Compact summary metrics for the run-flow view."""

    elapsed_ms: Optional[int] = Field(None, ge=0, description="Observed elapsed time")
    bottleneck_node_id: Optional[str] = Field(None, description="Node with the longest observed duration")
    failed_attempts: int = Field(0, ge=0, description="Failed provider/model/history/notification attempts")
    fallback_count: int = Field(0, ge=0, description="Fallback or retry transitions")
    model: Optional[str] = Field(None, description="Sanitized model name observed in diagnostics")
    data_source_count: int = Field(0, ge=0, description="Data source nodes represented in the graph")
    event_count: int = Field(0, ge=0, description="Event count")


class RunFlowSnapshot(BaseModel):
    """Public run-flow snapshot returned by task and history endpoints."""

    task_id: str = Field(..., description="Task id or query id")
    trace_id: Optional[str] = Field(None, description="Diagnostic trace id")
    stock_code: str = Field(..., description="Stock code")
    stock_name: Optional[str] = Field(None, description="Stock name")
    status: RunFlowStatus = Field(..., description="Overall run-flow status")
    summary: RunFlowSummary
    lanes: List[RunFlowLane] = Field(default_factory=list)
    nodes: List[RunFlowNode] = Field(default_factory=list)
    edges: List[RunFlowEdge] = Field(default_factory=list)
    events: List[RunFlowEvent] = Field(default_factory=list)
    generated_at: str = Field(..., description="ISO timestamp when this snapshot was generated")
