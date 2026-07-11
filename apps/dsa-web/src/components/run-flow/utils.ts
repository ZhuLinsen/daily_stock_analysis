import type { UiTextKey } from '../../i18n/uiText';
import type {
  RunFlowEdgeKind,
  RunFlowEventSeverity,
  RunFlowNode,
  RunFlowNodeKind,
  RunFlowStatus,
} from '../../types/runFlow';

export type RunFlowT = (key: UiTextKey, params?: Record<string, string | number>) => string;

export const RUN_FLOW_STATUS_STYLE: Record<RunFlowStatus, {
  badge: 'default' | 'success' | 'warning' | 'danger' | 'info';
  tone: 'success' | 'warning' | 'danger' | 'info' | 'neutral';
  pulse?: boolean;
}> = {
  pending: { badge: 'default', tone: 'neutral' },
  running: { badge: 'info', tone: 'info', pulse: true },
  success: { badge: 'success', tone: 'success' },
  failed: { badge: 'danger', tone: 'danger' },
  degraded: { badge: 'warning', tone: 'warning' },
  fallback: { badge: 'warning', tone: 'warning' },
  timeout: { badge: 'danger', tone: 'danger' },
  cancel_requested: { badge: 'warning', tone: 'warning', pulse: true },
  cancelled: { badge: 'default', tone: 'neutral' },
  skipped: { badge: 'default', tone: 'neutral' },
  unknown: { badge: 'default', tone: 'neutral' },
};

export const RUN_FLOW_SEVERITY_STYLE: Record<RunFlowEventSeverity, {
  badge: 'default' | 'success' | 'warning' | 'danger' | 'info';
  tone: 'success' | 'warning' | 'danger' | 'info' | 'neutral';
}> = {
  info: { badge: 'info', tone: 'info' },
  success: { badge: 'success', tone: 'success' },
  warning: { badge: 'warning', tone: 'warning' },
  danger: { badge: 'danger', tone: 'danger' },
};

const STATUS_LABEL_KEYS: Record<RunFlowStatus, UiTextKey> = {
  pending: 'runFlow.status.pending',
  running: 'runFlow.status.running',
  success: 'runFlow.status.success',
  failed: 'runFlow.status.failed',
  degraded: 'runFlow.status.degraded',
  fallback: 'runFlow.status.fallback',
  timeout: 'runFlow.status.timeout',
  cancel_requested: 'runFlow.status.cancelRequested',
  cancelled: 'runFlow.status.cancelled',
  skipped: 'runFlow.status.skipped',
  unknown: 'runFlow.status.unknown',
};

const SEVERITY_LABEL_KEYS: Record<RunFlowEventSeverity, UiTextKey> = {
  info: 'runFlow.severity.info',
  success: 'runFlow.severity.success',
  warning: 'runFlow.severity.warning',
  danger: 'runFlow.severity.danger',
};

const EDGE_KIND_LABEL_KEYS: Record<RunFlowEdgeKind, UiTextKey> = {
  data: 'runFlow.edge.data',
  control: 'runFlow.edge.control',
  fallback: 'runFlow.edge.fallback',
  retry: 'runFlow.edge.retry',
};

const NODE_KIND_LABEL_KEYS: Record<RunFlowNodeKind, UiTextKey> = {
  entry: 'runFlow.nodeKind.entry',
  queue: 'runFlow.nodeKind.queue',
  data_source: 'runFlow.nodeKind.dataSource',
  analysis: 'runFlow.nodeKind.analysis',
  model: 'runFlow.nodeKind.model',
  artifact: 'runFlow.nodeKind.artifact',
  notification: 'runFlow.nodeKind.notification',
};

export const getRunFlowStatusLabel = (status: RunFlowStatus, t: RunFlowT): string =>
  t(STATUS_LABEL_KEYS[status] || 'runFlow.status.unknown');

export const getRunFlowSeverityLabel = (severity: RunFlowEventSeverity, t: RunFlowT): string =>
  t(SEVERITY_LABEL_KEYS[severity] || 'runFlow.severity.info');

export const getRunFlowEdgeKindLabel = (kind: RunFlowEdgeKind, t: RunFlowT): string =>
  t(EDGE_KIND_LABEL_KEYS[kind] || 'runFlow.edge.control');

export const getRunFlowNodeKindLabel = (kind: RunFlowNodeKind, t: RunFlowT): string =>
  t(NODE_KIND_LABEL_KEYS[kind] || 'runFlow.nodeKind.analysis');

export const formatDuration = (value: number | null | undefined, t: RunFlowT): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return t('runFlow.valueUnavailable');
  }
  if (value < 1000) {
    return t('runFlow.durationMs', { value });
  }
  if (value < 60000) {
    return t('runFlow.durationSeconds', { value: (value / 1000).toFixed(1) });
  }
  return t('runFlow.durationMinutes', { value: (value / 60000).toFixed(1) });
};

export const formatDateTime = (
  value: string | null | undefined,
  language: 'zh' | 'en',
  t: RunFlowT,
): string => {
  if (!value) {
    return t('runFlow.valueUnavailable');
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(language === 'en' ? 'en-US' : 'zh-CN');
};

export const compactText = (value: string | null | undefined, maxLength = 64): string => {
  const text = (value || '').trim();
  if (!text || text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, Math.max(8, maxLength - 12))}...${text.slice(-8)}`;
};

export const getNodeDisplayOrder = (node: RunFlowNode, index: number): number => {
  const explicitOrder = node.metadata?.order;
  if (typeof explicitOrder === 'number' && Number.isFinite(explicitOrder)) {
    return explicitOrder;
  }
  return index;
};

export const formatMetadataValue = (value: unknown): string => {
  if (value === null || value === undefined || value === '') {
    return '-';
  }
  if (typeof value === 'string') {
    return compactText(value, 120);
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  try {
    return compactText(JSON.stringify(value), 120);
  } catch {
    return compactText(String(value), 120);
  }
};
