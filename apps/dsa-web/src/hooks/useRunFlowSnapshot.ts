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
  sourceKey: string;
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

const findEventIndex = (events: RunFlowEvent[], target: RunFlowEvent): number => (
  events.findIndex((event) => (target.id ? event.id === target.id : event === target))
);

const isPrecedingEvent = (
  event: RunFlowEvent,
  index: number,
  currentEvent: RunFlowEvent,
  currentIndex: number,
): boolean => {
  if (event === currentEvent || (currentEvent.id && event.id === currentEvent.id)) {
    return false;
  }
  if (currentIndex >= 0) {
    return index < currentIndex;
  }
  return eventTime(event) < eventTime(currentEvent);
};

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
  const currentIndex = findEventIndex(events, currentEvent);
  const matchingEvents = events.filter((event, index) => (
    isPrecedingEvent(event, index, currentEvent, currentIndex)
    && typeSet.has(event.type)
    && Boolean(event.nodeId && nodeById.has(event.nodeId))
  ));
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

const refreshIncomingEdgeStatus = (
  edges: RunFlowEdge[],
  nodeId: string | null,
  status?: RunFlowEdge['status'],
): RunFlowEdge[] => {
  if (!nodeId || !status) {
    return edges;
  }
  let changed = false;
  const refreshed = edges.map((edge) => {
    if (edge.to !== nodeId || edge.status === status) {
      return edge;
    }
    changed = true;
    return {
      ...edge,
      status,
    };
  });
  return changed ? refreshed : edges;
};

const ACTIVE_NODE_STATUSES = new Set(['pending', 'running', 'cancel_requested']);

const FALLBACK_SOURCE_PROVIDER_FAMILIES: Record<string, string> = {
  akshare_em: 'akshare',
  akshare_sina: 'akshare',
  akshare_qq: 'akshare',
  akshare_hk: 'akshare',
  tencent: 'akshare',
};

const normalizeProviderKey = (value?: string | null): string => {
  if (!value) {
    return '';
  }
  return value.trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
};

const normalizeProviderToken = (value?: string | null): string => {
  const key = normalizeProviderKey(value);
  if (!key) {
    return '';
  }
  if (key.endsWith('_fetcher') && key.length > '_fetcher'.length) {
    return key.slice(0, -'_fetcher'.length);
  }
  if (key.endsWith('fetcher') && key.length > 'fetcher'.length) {
    return key.slice(0, -'fetcher'.length);
  }
  return key;
};

const providerMatchesFallbackTarget = (
  provider?: string | null,
  fallbackTo?: string | null,
): boolean => {
  const targetKey = normalizeProviderKey(fallbackTo);
  const providerKey = normalizeProviderKey(provider);
  if (!targetKey || !providerKey) {
    return false;
  }
  if (providerKey === targetKey) {
    return true;
  }
  const providerBase = normalizeProviderToken(providerKey);
  const targetBase = normalizeProviderToken(targetKey);
  if (providerBase === targetBase) {
    return true;
  }
  if (targetKey.startsWith(`${providerBase}_`) || providerKey.startsWith(`${targetBase}_`)) {
    return true;
  }
  const mappedTargetFamily = FALLBACK_SOURCE_PROVIDER_FAMILIES[targetKey];
  return Boolean(mappedTargetFamily && providerBase === mappedTargetFamily);
};

const providerTransitionKind = (
  previous: { provider: string | null; success: boolean; fallbackTo: string | null },
  current: { provider: string | null; success: boolean; fallbackFrom: string | null },
): RunFlowEdge['kind'] => {
  if (previous.fallbackTo || current.fallbackFrom) {
    return 'fallback';
  }
  if (!previous.success && previous.provider && current.provider && previous.provider === current.provider) {
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
  fallbackFrom: (
    metadataString(event.metadata, 'fallbackFrom', 'fallback_from')
    || metadataString(node?.metadata, 'fallbackFrom', 'fallback_from')
  ),
  fallbackTo: (
    metadataString(event.metadata, 'fallbackTo', 'fallback_to')
    || metadataString(node?.metadata, 'fallbackTo', 'fallback_to')
  ),
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

  if (displayEvent.type === 'provider_run' || displayEvent.type === 'provider_run_started') {
    const dataType = dataTypeFromEvent(displayEvent, node);
    const currentIndex = findEventIndex(events, displayEvent);
    const currentRun = providerRunFromEvent(displayEvent, node);
    const currentProvider = currentRun.provider;
    const currentFallbackFrom = currentRun.fallbackFrom;
    const hasOutgoingFallbackOrRetry = (fromId: string) => edges.some(
      (edge) => edge.from === fromId && (edge.kind === 'fallback' || edge.kind === 'retry'),
    );
    const canFollowFallbackOrRetry = (
      displayEvent.type === 'provider_run_started'
      || Boolean(currentFallbackFrom)
      || node.status !== 'success'
    );
    const precedingByNodeId = new Map<string, RunFlowEvent>();
    events.forEach((event, index) => {
      if (
        !isPrecedingEvent(event, index, displayEvent, currentIndex)
        || (event.type !== 'provider_run' && event.type !== 'provider_run_started')
        || !event.nodeId
        || event.nodeId === nodeId
      ) {
        return;
      }
      const eventNode = nodeById.get(event.nodeId);
      if (!eventNode || dataTypeFromEvent(event, eventNode) !== dataType) {
        return;
      }
      precedingByNodeId.set(event.nodeId, event);
    });
    const precedingProviderEvents = Array.from(precedingByNodeId.values());

    const explicitFallbackCandidates = canFollowFallbackOrRetry
      ? precedingProviderEvents.filter((event) => {
        const eventNode = nodeById.get(event.nodeId!)!;
        const fallbackTo = providerRunFromEvent(event, eventNode).fallbackTo;
        if (!fallbackTo || hasOutgoingFallbackOrRetry(event.nodeId!)) {
          return false;
        }
        return Boolean(currentFallbackFrom) || providerMatchesFallbackTarget(currentProvider, fallbackTo);
      })
      : [];

    const matchedExplicitFallback = currentFallbackFrom
      ? explicitFallbackCandidates.filter((event) => {
        const eventNode = nodeById.get(event.nodeId!)!;
        const prevRun = providerRunFromEvent(event, eventNode);
        return (
          providerMatchesFallbackTarget(prevRun.provider, currentFallbackFrom)
          || providerMatchesFallbackTarget(currentProvider, prevRun.fallbackTo)
        );
      })
      : explicitFallbackCandidates;

    const fallbackFromCandidates = currentFallbackFrom
      ? precedingProviderEvents.filter((event) => {
        const eventNode = nodeById.get(event.nodeId!)!;
        const prevRun = providerRunFromEvent(event, eventNode);
        return (
          !hasOutgoingFallbackOrRetry(event.nodeId!)
          && !ACTIVE_NODE_STATUSES.has(eventNode.status)
          && (eventNode.status === 'failed' || eventNode.status === 'timeout' || Boolean(prevRun.fallbackTo))
        );
      })
      : [];

    const matchedFallbackFrom = currentFallbackFrom
      ? fallbackFromCandidates.filter((event) => {
        const eventNode = nodeById.get(event.nodeId!)!;
        const prevRun = providerRunFromEvent(event, eventNode);
        return providerMatchesFallbackTarget(prevRun.provider, currentFallbackFrom);
      })
      : [];

    const previousEvent = (
      (matchedExplicitFallback.at(-1) ?? explicitFallbackCandidates.at(-1))
      ?? (matchedFallbackFrom.at(-1) ?? fallbackFromCandidates.at(-1))
      ?? precedingProviderEvents.filter((event) => {
        const eventNode = nodeById.get(event.nodeId!)!;
        if (ACTIVE_NODE_STATUSES.has(eventNode.status)) {
          return false;
        }
        const prevRun = providerRunFromEvent(event, eventNode);
        if (prevRun.fallbackTo) {
          return false;
        }
        const prevFailed = eventNode.status === 'failed' || eventNode.status === 'timeout';
        if (prevFailed && (!canFollowFallbackOrRetry || hasOutgoingFallbackOrRetry(event.nodeId!))) {
          return false;
        }
        return true;
      }).at(-1)
    );

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
      currentRun,
    );
    const label = transitionKind === 'fallback'
      ? '降级'
      : transitionKind === 'retry'
        ? '重试'
        : '调用';
    const message = metadataString(displayEvent.metadata, 'fallbackFrom', 'fallback_from', 'fallbackTo', 'fallback_to');
    return appendEdge(edges, previousNode.id, nodeId, transitionKind, node.status, label, message);
  }

  if (displayEvent.type === 'llm_run' || displayEvent.type === 'llm_run_started') {
    const anchor = nodeById.has('analysis_pipeline') ? 'analysis_pipeline' : 'task_queue';
    return nodeById.has(anchor)
      ? appendEdge(edges, anchor, nodeId, 'data', node.status, '生成')
      : edges;
  }

  if (displayEvent.type === 'history_run') {
    const anchor = latestEventNodeId(events, nodeById, ['llm_run', 'llm_run_started'], displayEvent)
      || (nodeById.has('analysis_pipeline') ? 'analysis_pipeline' : 'task_queue');
    return nodeById.has(anchor)
      ? appendEdge(edges, anchor, nodeId, 'data', node.status, '保存')
      : edges;
  }

  if (displayEvent.type === 'notification_run') {
    const anchor = latestEventNodeId(events, nodeById, ['history_run'], displayEvent)
      || latestEventNodeId(events, nodeById, ['llm_run', 'llm_run_started'], displayEvent)
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
  const eventAlreadyPresent = Boolean(displayEvent.id) && snapshot.events.some((event) => event.id === displayEvent.id);
  const events = mergeEvents(snapshot.events, displayEvent);
  const node = isRunFlowNode(nodeCandidate) ? nodeCandidate : null;
  const targetNodeId = eventNodeId(displayEvent, node);
  const nodeAlreadyExisted = Boolean(
    targetNodeId && snapshot.nodes.some((existing) => existing.id === targetNodeId),
  );
  const nodes = upsertNode(snapshot.nodes, node);
  const edges = eventAlreadyPresent
    ? snapshot.edges
    : nodeAlreadyExisted
      ? refreshIncomingEdgeStatus(snapshot.edges, targetNodeId, node?.status)
      : refreshIncomingEdgeStatus(
        appendDerivedEdge(
          nodes,
          snapshot.edges,
          events,
          displayEvent,
          targetNodeId,
        ),
        targetNodeId,
        node?.status,
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

const replayEventNodeId = (flowEvent: RunFlowEvent): string | null => {
  const nodeCandidate = flowEvent.metadata?.node;
  if (isRunFlowNode(nodeCandidate)) {
    return nodeCandidate.id;
  }
  return flowEvent.nodeId || null;
};

const shouldReplayFlowEvent = (snapshot: RunFlowSnapshot, flowEvent: RunFlowEvent): boolean => {
  const nodeId = replayEventNodeId(flowEvent);
  if (!nodeId) {
    return true;
  }
  const existingNode = snapshot.nodes.find((node) => node.id === nodeId);
  return !existingNode || ACTIVE_NODE_STATUSES.has(existingNode.status);
};

const replayFlowEvents = (
  snapshot: RunFlowSnapshot,
  flowEvents: RunFlowEvent[],
): RunFlowSnapshot => flowEvents.reduce(
  (currentSnapshot, flowEvent) => (
    shouldReplayFlowEvent(currentSnapshot, flowEvent)
      ? mergeFlowEventIntoSnapshot(currentSnapshot, flowEvent)
      : currentSnapshot
  ),
  snapshot,
);

export function useRunFlowSnapshot({
  source,
  enabled = true,
}: UseRunFlowSnapshotOptions): UseRunFlowSnapshotResult {
  const [requestState, setRequestState] = useState<RunFlowRequestState>({
    sourceKey: 'none',
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
        if (current.sourceKey !== sourceKey || !current.snapshot) {
          return current;
        }
        return {
          ...current,
          snapshot: mergeFlowEventIntoSnapshot(current.snapshot, flowEvent),
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
            sourceKey,
            requestKey,
            snapshot,
            error: null,
          });
        }
      })
      .catch((err: unknown) => {
        if (active) {
          const parsedError = getParsedApiError(err);
          setRequestState((current) => ({
            sourceKey,
            requestKey,
            snapshot: current.sourceKey === sourceKey ? current.snapshot : null,
            error: parsedError,
          }));
        }
      });

    return () => {
      active = false;
    };
  }, [recordId, requestKey, shouldLoad, sourceKey, sourceType, taskId]);

  const hasSourceState = shouldLoad && requestState.sourceKey === sourceKey;
  const hasFreshRequest = shouldLoad && requestState.requestKey === requestKey;

  return {
    snapshot: hasSourceState ? requestState.snapshot : null,
    isLoading: shouldLoad && !hasFreshRequest,
    error: hasFreshRequest ? requestState.error : null,
    refetch,
  };
}
