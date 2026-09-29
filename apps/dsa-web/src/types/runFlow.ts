export type RunFlowStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'degraded'
  | 'fallback'
  | 'timeout'
  | 'cancel_requested'
  | 'cancelled'
  | 'skipped'
  | 'unknown';

export type RunFlowNodeKind =
  | 'entry'
  | 'queue'
  | 'data_source'
  | 'analysis'
  | 'model'
  | 'artifact'
  | 'notification';

export type RunFlowEdgeKind = 'data' | 'control' | 'fallback' | 'retry';

export type RunFlowEventSeverity = 'info' | 'success' | 'warning' | 'danger';

export interface RunFlowLane {
  id: string;
  label: string;
  order: number;
}

export interface RunFlowNode {
  id: string;
  lane: string;
  kind: RunFlowNodeKind;
  label: string;
  status: RunFlowStatus;
  provider?: string | null;
  startedAt?: string | null;
  endedAt?: string | null;
  durationMs?: number | null;
  attempts?: number | null;
  recordCount?: number | null;
  message?: string | null;
  metadata?: Record<string, unknown>;
}

export interface RunFlowEdge {
  id: string;
  from: string;
  to: string;
  kind: RunFlowEdgeKind;
  status: RunFlowStatus;
  label?: string | null;
  message?: string | null;
  metadata?: Record<string, unknown>;
}

export interface RunFlowEvent {
  id: string;
  timestamp?: string | null;
  severity: RunFlowEventSeverity;
  type: string;
  nodeId?: string | null;
  title: string;
  message?: string | null;
  metadata?: Record<string, unknown>;
}

export interface RunFlowSummary {
  elapsedMs?: number | null;
  bottleneckNodeId?: string | null;
  failedAttempts: number;
  fallbackCount: number;
  model?: string | null;
  dataSourceCount: number;
  eventCount: number;
}

export interface RunFlowSnapshot {
  taskId: string;
  traceId?: string | null;
  stockCode: string;
  stockName?: string | null;
  status: RunFlowStatus;
  summary: RunFlowSummary;
  lanes: RunFlowLane[];
  nodes: RunFlowNode[];
  edges: RunFlowEdge[];
  events: RunFlowEvent[];
  generatedAt: string;
}

export type RunFlowSnapshotSource =
  | { type: 'task'; taskId: string }
  | { type: 'history'; recordId: number };
