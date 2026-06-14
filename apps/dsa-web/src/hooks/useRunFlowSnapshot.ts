import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { analysisApi } from '../api/analysis';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { historyApi } from '../api/history';
import type { RunFlowEdge, RunFlowEvent, RunFlowNode, RunFlowSnapshot, RunFlowSnapshotSource } from '../types/runFlow';
import { useTaskStream } from './useTaskStream';

interface UseRunFlowSnapshotOptions {
  source?: RunFlowSnapshotSource | null;
  enabled?: boolean;
}

interface UseRunFlowSnapshotResult {
  snapshot: RunFlowSnapshot | null;
  isLoading: boolean;
  error: ParsedApiError | null;
  refetch: () => Promise<void>;
}

type RunFlowRequestState = {
  requestKey: string;
  snapshot: RunFlowSnapshot | null;
  error: ParsedApiError | null;
};

const MAX_BUFFERED_FLOW_EVENTS = 50;

const getSourceKey = (source?: RunFlowSnapshotSource | null): string => {
  if (!source) {
    return 'none';
  }
  return source.type === 'task'
    ? `task:${source.taskId}`
    : `history:${source.recordId}`;
};

const isUsableSource = (source?: RunFlowSnapshotSource | null): source is RunFlowSnapshotSource => {
  if (!source) {
    return false;
  }
  if (source.type === 'task') {
    return Boolean(source.taskId.trim());
  }
  return Number.isFinite(source.recordId);
};

const eventTime = (event: RunFlowEvent): number => (
  event.timestamp ? Date.parse(event.timestamp) || 0 : 0
);

const mergeEvents = (events: RunFlowEvent[], incoming: RunFlowEvent): RunFlowEvent[] => {
  const byId = new Map<string, RunFlowEvent>();
  [...events, incoming].forEach((event, index) => {
    byId.set(event.id || `event-${index}`, event);
  });
  return Array.from(byId.values()).sort((left, right) => eventTime(left) - eventTime(right));
};

const isRunFlowNode = (value: unknown): value is RunFlowNode => {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const node = value as Partial<RunFlowNode>;
  return Boolean(node.id && node.lane && node.kind && node.label && node.status);
};

const metadataString = (
  metadata: Record<string, unknown> | undefined,
  ...keys: string[]
): string | null => {
  const value = keys
    .map((key) => metadata?.[key])
    .find((item) => typeof item === 'string' && item.trim());
  return typeof value === 'string' ? value.trim() : null;
};

const dataTypeFromNode = (node?: RunFlowNode): string | null => {
  if (!node) {
    return null;
  }
  const metadataValue = metadataString(node.metadata, 'dataType', 'data_type');
  if (metadataValue) {
    return metadataValue;
  }
  if (!node.id.startsWith('provider_')) {
    return null;
  }
  const inferred = node.id.replace(/^provider_/, '').split('_').slice(0, -2).join('_');
  return inferred || null;
};

const dataTypeFromEvent = (event: RunFlowEvent, node?: RunFlowNode): string => (
  metadataString(event.metadata, 'dataType', 'data_type')
  || dataTypeFromNode(node)
  || 'provider'
);

const eventNodeId = (event: RunFlowEvent, nodeCandidate?: RunFlowNode | null): string | null => (
  nodeCandidate?.id || event.nodeId || null
);

const latestEventNodeId = (
  events: RunFlowEvent[],
  nodeById: Map<string, RunFlowNode>,
  types: string[],
  currentEvent: RunFlowEvent,
): string | null => {
  const typeSet = new Set(types);
  const currentTime = eventTime(currentEvent);
  const matchingEvents = events
    .filter((event) => (
      event.id !== currentEvent.id
      && eventTime(event) < currentTime
      && typeSet.has(event.type)
      && event.nodeId
      && nodeById.has(event.nodeId)
    ))
    .sort((left, right) => eventTime(left) - eventTime(right));
  return matchingEvents.at(-1)?.nodeId || null;
};

const edgeExists = (edges: RunFlowEdge[], from: string, to: string, kind: RunFlowEdge['kind']): boolean => (
  edges.some((edge) => edge.from === from && edge.to === to && edge.kind === kind)
);

const appendEdge = (
  edges: RunFlowEdge[],
  from: string,
  to: string,
  kind: RunFlowEdge['kind'],
  status: RunFlowEdge['status'],
  label: string,
  message?: string | null,
): RunFlowEdge[] => {
  if (from === to || edgeExists(edges, from, to, kind)) {
    return edges;
  }
  return [
    ...edges,
    {
      id: `${from}_to_${to}_${kind}`,
      from,
      to,
      kind,
      status,
      label,
      message,
    },
  ];
};

const providerTransitionKind = (
  previous: { provider: string | null; success: boolean; fallbackTo: string | null },
  current: { provider: string | null; success: boolean; fallbackFrom: string | null },
): RunFlowEdge['kind'] => {
  if (previous.fallbackTo || current.fallbackFrom) {
    return 'fallback';
  }
  if (previous.provider && current.provider && previous.provider === current.provider) {
    return 'retry';
  }
  if (!previous.success) {
    return 'fallback';
  }
  return 'data';
};

const providerRunFromEvent = (
  event: RunFlowEvent,
  node?: RunFlowNode,
): { provider: string | null; success: boolean; fallbackFrom: string | null; fallbackTo: string | null } => ({
  provider: metadataString(event.metadata, 'provider') || node?.provider || null,
  success: event.severity === 'success' || node?.status === 'success' || node?.status === 'fallback',
  fallbackFrom: metadataString(event.metadata, 'fallbackFrom', 'fallback_from'),
  fallbackTo: metadataString(event.metadata, 'fallbackTo', 'fallback_to'),
});

const appendDerivedEdge = (
  nodes: RunFlowNode[],
  edges: RunFlowEdge[],
  events: RunFlowEvent[],
  displayEvent: RunFlowEvent,
  nodeId: string | null,
): RunFlowEdge[] => {
  if (!nodeId) {
    return edges;
  }
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const node = nodeById.get(nodeId);
  if (!node) {
    return edges;
  }

  if (displayEvent.type === 'provider_run') {
    const dataType = dataTypeFromEvent(displayEvent, node);
    const currentTime = eventTime(displayEvent);
    const previousEvent = events
      .filter((event) => {
        if (event.id === displayEvent.id || event.type !== 'provider_run' || !event.nodeId) {
          return false;
        }
        if (eventTime(event) >= currentTime) {
          return false;
        }
        const eventNode = nodeById.get(event.nodeId);
        return Boolean(eventNode && dataTypeFromEvent(event, eventNode) === dataType);
      })
      .sort((left, right) => eventTime(left) - eventTime(right))
      .at(-1);

    if (!previousEvent?.nodeId) {
      return nodeById.has('task_queue')
        ? appendEdge(edges, 'task_queue', nodeId, 'control', node.status, '调用')
        : edges;
    }

    const previousNode = nodeById.get(previousEvent.nodeId);
    if (!previousNode) {
      return edges;
    }
    const transitionKind = providerTransitionKind(
      providerRunFromEvent(previousEvent, previousNode),
      providerRunFromEvent(displayEvent, node),
    );
    const label = transitionKind === 'fallback'
      ? '降级'
      : transitionKind === 'retry'
        ? '重试'
        : '调用';
    const message = metadataString(displayEvent.metadata, 'fallbackFrom', 'fallback_from', 'fallbackTo', 'fallback_to');
    return appendEdge(edges, previousNode.id, nodeId, transitionKind, node.status, label, message);
  }

  if (displayEvent.type === 'llm_run') {
    const anchor = nodeById.has('analysis_pipeline') ? 'analysis_pipeline' : 'task_queue';
    return nodeById.has(anchor)
      ? appendEdge(edges, anchor, nodeId, 'data', node.status, '生成')
      : edges;
  }

  if (displayEvent.type === 'history_run') {
    const anchor = latestEventNodeId(events, nodeById, ['llm_run'], displayEvent)
      || (nodeById.has('analysis_pipeline') ? 'analysis_pipeline' : 'task_queue');
    return nodeById.has(anchor)
      ? appendEdge(edges, anchor, nodeId, 'data', node.status, '保存')
      : edges;
  }

  if (displayEvent.type === 'notification_run') {
    const anchor = latestEventNodeId(events, nodeById, ['history_run'], displayEvent)
      || latestEventNodeId(events, nodeById, ['llm_run'], displayEvent)
      || (nodeById.has('analysis_pipeline') ? 'analysis_pipeline' : 'task_queue');
    return nodeById.has(anchor)
      ? appendEdge(edges, anchor, nodeId, 'control', node.status, '通知')
      : edges;
  }

  return edges;
};

const upsertNode = (nodes: RunFlowNode[], nodeCandidate: RunFlowNode | null): RunFlowNode[] => {
  if (!nodeCandidate) {
    return nodes;
  }
  const existingIndex = nodes.findIndex((node) => node.id === nodeCandidate.id);
  if (existingIndex < 0) {
    return [...nodes, nodeCandidate];
  }
  return nodes.map((node, index) => {
    if (index !== existingIndex) {
      return node;
    }
    return {
      ...node,
      ...nodeCandidate,
      metadata: {
        ...(node.metadata || {}),
        ...(nodeCandidate.metadata || {}),
      },
    };
  });
};

const buildLiveSummary = (
  snapshot: RunFlowSnapshot,
  nodes: RunFlowNode[],
  edges: RunFlowEdge[],
  events: RunFlowEvent[],
): RunFlowSnapshot['summary'] => {
  const bottleneck = nodes.reduce<{ id: string | null; duration: number }>((current, node) => {
    const duration = typeof node.durationMs === 'number' && Number.isFinite(node.durationMs)
      ? node.durationMs
      : -1;
    return duration > current.duration ? { id: node.id, duration } : current;
  }, { id: null, duration: -1 });
  const failedAttempts = nodes.filter((node) => (
    (node.status === 'failed' || node.status === 'timeout')
    && ['data_source', 'model', 'artifact', 'notification'].includes(node.kind)
  )).length;
  const fallbackCount = edges.filter((edge) => edge.kind === 'fallback' || edge.kind === 'retry').length;
  const dataSourceCount = nodes.filter((node) => node.kind === 'data_source').length;
  const model = nodes.find((node) => node.kind === 'model' && node.provider)?.provider
    || snapshot.summary.model
    || null;

  return {
    ...snapshot.summary,
    bottleneckNodeId: bottleneck.id || snapshot.summary.bottleneckNodeId || null,
    failedAttempts,
    fallbackCount,
    model,
    dataSourceCount,
    eventCount: events.length,
  };
};

const mergeFlowEventIntoSnapshot = (
  snapshot: RunFlowSnapshot,
  flowEvent: RunFlowEvent,
): RunFlowSnapshot => {
  const nodeCandidate = flowEvent.metadata?.node;
  const eventMetadata = { ...(flowEvent.metadata || {}) };
  delete eventMetadata.node;
  const displayEvent: RunFlowEvent = {
    ...flowEvent,
    metadata: eventMetadata,
  };
  const eventAlreadyPresent = snapshot.events.some((event) => event.id === displayEvent.id);
  const events = mergeEvents(snapshot.events, displayEvent);
  const node = isRunFlowNode(nodeCandidate) ? nodeCandidate : null;
  const nodes = upsertNode(snapshot.nodes, node);
  const edges = eventAlreadyPresent
    ? snapshot.edges
    : appendDerivedEdge(
      nodes,
      snapshot.edges,
      events,
      displayEvent,
      eventNodeId(displayEvent, node),
    );

  return {
    ...snapshot,
    nodes,
    edges,
    events,
    summary: buildLiveSummary(snapshot, nodes, edges, events),
    generatedAt: flowEvent.timestamp || snapshot.generatedAt,
  };
};

const rememberFlowEvent = (events: RunFlowEvent[], flowEvent: RunFlowEvent): RunFlowEvent[] => {
  const byId = new Map<string, RunFlowEvent>();
  [...events, flowEvent].forEach((event, index) => {
    byId.set(event.id || `${event.type}:${event.nodeId || 'none'}:${event.timestamp || index}`, event);
  });
  return Array.from(byId.values())
    .sort((left, right) => eventTime(left) - eventTime(right))
    .slice(-MAX_BUFFERED_FLOW_EVENTS);
};

const replayFlowEvents = (
  snapshot: RunFlowSnapshot,
  flowEvents: RunFlowEvent[],
): RunFlowSnapshot => flowEvents.reduce(
  (currentSnapshot, flowEvent) => mergeFlowEventIntoSnapshot(currentSnapshot, flowEvent),
  snapshot,
);

export function useRunFlowSnapshot({
  source,
  enabled = true,
}: UseRunFlowSnapshotOptions): UseRunFlowSnapshotResult {
  const [requestState, setRequestState] = useState<RunFlowRequestState>({
    requestKey: 'none',
    snapshot: null,
    error: null,
  });
  const [reloadToken, setReloadToken] = useState(0);
  const sourceKey = useMemo(() => getSourceKey(source), [source]);
  const sourceType = source?.type;
  const taskId = source?.type === 'task' ? source.taskId : '';
  const recordId = source?.type === 'history' ? source.recordId : null;
  const requestKey = `${sourceKey}:${reloadToken}`;
  const shouldLoad = enabled && isUsableSource(source);
  const flowEventBufferRef = useRef<RunFlowEvent[]>([]);

  const refetch = useCallback(async () => {
    setReloadToken((value) => value + 1);
  }, []);

  useEffect(() => {
    flowEventBufferRef.current = [];
  }, [sourceKey]);

  useTaskStream({
    enabled: shouldLoad && sourceType === 'task',
    onTaskFlowEvent: (task, flowEvent) => {
      if (task.taskId !== taskId) {
        return;
      }
      flowEventBufferRef.current = rememberFlowEvent(flowEventBufferRef.current, flowEvent);
      setRequestState((current) => {
        const hasFreshState = current.requestKey === requestKey && current.snapshot;
        if (!hasFreshState) {
          return current;
        }
        return {
          ...current,
          snapshot: mergeFlowEventIntoSnapshot(current.snapshot as RunFlowSnapshot, flowEvent),
        };
      });
    },
    onTaskCompleted: (task) => {
      if (task.taskId === taskId) {
        void refetch();
      }
    },
    onTaskFailed: (task) => {
      if (task.taskId === taskId) {
        void refetch();
      }
    },
    onError: () => {
      if (sourceType === 'task') {
        void refetch();
      }
    },
  });

  useEffect(() => {
    if (!shouldLoad || !sourceType) {
      return undefined;
    }

    let active = true;

    const request = sourceType === 'task'
      ? analysisApi.getTaskFlow(taskId)
      : historyApi.getRecordFlow(recordId ?? 0);

    request
      .then((result) => {
        if (active) {
          const snapshot = sourceType === 'task'
            ? replayFlowEvents(result, flowEventBufferRef.current)
            : result;
          setRequestState({
            requestKey,
            snapshot,
            error: null,
          });
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setRequestState({
            requestKey,
            snapshot: null,
            error: getParsedApiError(err),
          });
        }
      });

    return () => {
      active = false;
    };
  }, [recordId, requestKey, shouldLoad, sourceType, taskId]);

  const hasFreshState = shouldLoad && requestState.requestKey === requestKey;

  return {
    snapshot: hasFreshState ? requestState.snapshot : null,
    isLoading: shouldLoad && !hasFreshState,
    error: hasFreshState ? requestState.error : null,
    refetch,
  };
}
