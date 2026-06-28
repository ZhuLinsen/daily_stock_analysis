import type {
  RunFlowEdge,
  RunFlowEvent,
  RunFlowLane,
  RunFlowNode,
  RunFlowSnapshot,
  RunFlowStatus,
} from '../../types/runFlow';

export interface RunFlowTopologyModel {
  lanes: RunFlowLane[];
  nodes: RunFlowNode[];
  edges: RunFlowEdge[];
  events: RunFlowEvent[];
  nodeIdMap: Map<string, string>;
}

interface RunFlowTopologyOptions {
  expandedGroupIds?: Set<string>;
}

const PROVIDER_GROUP_PREFIX = 'topology_data_';

const STATUS_RANK: Record<RunFlowStatus, number> = {
  unknown: 0,
  skipped: 1,
  pending: 2,
  running: 3,
  success: 4,
  cancelled: 5,
  cancel_requested: 6,
  fallback: 7,
  degraded: 8,
  timeout: 9,
  failed: 10,
};

const statusRank = (status: RunFlowStatus): number => STATUS_RANK[status] ?? 0;

const nodeTime = (node: RunFlowNode): number | null => {
  const rawTime = node.startedAt || node.endedAt;
  if (!rawTime) return null;
  const parsed = Date.parse(rawTime);
  return Number.isFinite(parsed) ? parsed : null;
};

const minTime = (nodes: RunFlowNode[]): string | null => {
  const sorted = nodes
    .map((node) => node.startedAt || node.endedAt)
    .filter((value): value is string => Boolean(value))
    .sort((left, right) => Date.parse(left) - Date.parse(right));
  return sorted[0] || null;
};

const maxTime = (nodes: RunFlowNode[]): string | null => {
  const sorted = nodes
    .map((node) => node.endedAt || node.startedAt)
    .filter((value): value is string => Boolean(value))
    .sort((left, right) => Date.parse(right) - Date.parse(left));
  return sorted[0] || null;
};

const sumDuration = (nodes: RunFlowNode[]): number | null => {
  const total = nodes.reduce((sum, node) => (
    typeof node.durationMs === 'number' && Number.isFinite(node.durationMs)
      ? sum + node.durationMs
      : sum
  ), 0);
  return total > 0 ? total : null;
};

const firstDefinedRecordCount = (nodes: RunFlowNode[]): number | null => {
  const node = nodes.find((item) => typeof item.recordCount === 'number');
  return node?.recordCount ?? null;
};

const metadataString = (node: RunFlowNode, ...keys: string[]): string | null => {
  const value = keys.map((key) => node.metadata?.[key]).find((item) => typeof item === 'string' && item.trim());
  return typeof value === 'string' ? value.trim() : null;
};

const dataTypeFromNode = (node: RunFlowNode): string | null => {
  const value = metadataString(node, 'dataType', 'data_type');
  return typeof value === 'string' && value.trim() ? value.trim() : null;
};

const contextBlockKeyFromNode = (node: RunFlowNode): string | null => {
  const value = metadataString(node, 'blockKey', 'block_key');
  return typeof value === 'string' && value.trim() ? value.trim() : null;
};

const isProviderAttemptNode = (node: RunFlowNode): boolean => (
  node.lane === 'data_source'
  && (node.id.startsWith('provider_') || Boolean(dataTypeFromNode(node)))
);

const isContextBlockNode = (node: RunFlowNode): boolean => (
  node.id.startsWith('context_block_') || Boolean(contextBlockKeyFromNode(node))
);

const labelForDataType = (dataType: string, nodes: RunFlowNode[]): string => {
  const firstLabel = nodes.find((node) => node.label)?.label || dataType;
  const [beforeProvider] = firstLabel.split(' · ');
  return beforeProvider || dataType;
};

const groupStatus = (nodes: RunFlowNode[], edges: RunFlowEdge[]): RunFlowStatus => {
  const statuses = nodes.map((node) => node.status);
  if (statuses.length === 0) return 'unknown';
  if (statuses.includes('cancel_requested')) return 'cancel_requested';
  if (statuses.some((status) => status === 'running' || status === 'pending')) return 'running';
  if (statuses.every((status) => status === 'success')) return 'success';
  const hasSuccess = statuses.includes('success');
  const hasFailedOrTimeout = statuses.some((status) => status === 'failed' || status === 'timeout');
  const hasFallbackAttempt = statuses.includes('fallback');
  const hasRecoveryTransition = edges.some((edge) => edge.kind === 'fallback' || edge.kind === 'retry');
  if (hasSuccess && (hasFailedOrTimeout || hasFallbackAttempt) && hasRecoveryTransition) return 'fallback';
  if (hasSuccess && statuses.some((status) => ['failed', 'timeout', 'degraded', 'fallback'].includes(status))) return 'degraded';
  return statuses.reduce<RunFlowStatus>((winner, status) => (
    statusRank(status) > statusRank(winner) ? status : winner
  ), 'unknown');
};

const countByStatus = (nodes: RunFlowNode[], status: RunFlowStatus): number =>
  nodes.filter((node) => node.status === status).length;

const transitionCount = (edges: RunFlowEdge[], kind: 'fallback' | 'retry'): number =>
  edges.filter((edge) => edge.kind === kind).length;

const compactProviderChain = (nodes: RunFlowNode[]): string | null => {
  const providers = nodes
    .map((node) => node.provider)
    .filter((provider): provider is string => Boolean(provider));
  if (!providers.length) return null;
  return providers.join(' -> ');
};

const buildProviderGroupNode = (
  dataType: string,
  attempts: RunFlowNode[],
  attemptEdges: RunFlowEdge[],
  expanded: boolean,
): RunFlowNode => {
  const sortedAttempts = [...attempts].sort((left, right) => (
    (nodeTime(left) ?? Number.MAX_SAFE_INTEGER) - (nodeTime(right) ?? Number.MAX_SAFE_INTEGER)
  ));
  const fallbackCount = transitionCount(attemptEdges, 'fallback');
  const retryCount = transitionCount(attemptEdges, 'retry');
  const successCount = countByStatus(sortedAttempts, 'success');
  const failedCount = sortedAttempts.filter((node) => ['failed', 'timeout'].includes(node.status)).length;
  const providerChain = compactProviderChain(sortedAttempts);
  const label = labelForDataType(dataType, sortedAttempts);
  return {
    id: `${PROVIDER_GROUP_PREFIX}${dataType}`,
    lane: 'data_source',
    kind: 'data_source',
    label,
    status: groupStatus(sortedAttempts, attemptEdges),
    provider: providerChain,
    startedAt: minTime(sortedAttempts),
    endedAt: maxTime(sortedAttempts),
    durationMs: sumDuration(sortedAttempts),
    attempts: sortedAttempts.length,
    recordCount: firstDefinedRecordCount([...sortedAttempts].reverse()),
    metadata: {
      topologyGroup: 'provider_attempts',
      topologyRole: 'provider_group',
      expanded,
      data_type: dataType,
      provider_chain: providerChain,
      success_count: successCount,
      failed_count: failedCount,
      fallback_count: fallbackCount,
      retry_count: retryCount,
      attempts: sortedAttempts.map((node) => ({
        id: node.id,
        label: node.label,
        provider: node.provider,
        status: node.status,
        startedAt: node.startedAt,
        endedAt: node.endedAt,
        durationMs: node.durationMs,
        recordCount: node.recordCount,
        message: node.message,
        metadata: node.metadata,
      })),
    },
  };
};

const attachContextBlocksToPack = (node: RunFlowNode, contextBlocks: RunFlowNode[]): RunFlowNode => {
  if (node.id !== 'context_pack' || contextBlocks.length === 0) return node;
  const statusCounts = contextBlocks.reduce<Record<string, number>>((counts, block) => {
    counts[block.status] = (counts[block.status] || 0) + 1;
    return counts;
  }, {});
  return {
    ...node,
    metadata: {
      ...(node.metadata || {}),
      topologyGroup: 'context_pack',
      context_blocks: contextBlocks.map((block) => ({
        id: block.id,
        label: block.label,
        provider: block.provider,
        status: block.status,
        startedAt: block.startedAt,
        endedAt: block.endedAt,
        recordCount: block.recordCount,
        message: block.message,
        metadata: block.metadata,
      })),
      context_status_counts: statusCounts,
    },
  };
};

export const buildRunFlowTopologyModel = (
  snapshot: RunFlowSnapshot,
  options: RunFlowTopologyOptions = {},
): RunFlowTopologyModel => {
  const providerAttempts = snapshot.nodes.filter(isProviderAttemptNode);
  const contextBlocks = snapshot.nodes.filter((node) => isContextBlockNode(node) && !isProviderAttemptNode(node));
  const nodeIdMap = new Map<string, string>();

  snapshot.nodes.forEach((node) => {
    nodeIdMap.set(node.id, node.id);
  });
  contextBlocks.forEach((node) => {
    nodeIdMap.set(node.id, 'context_pack');
  });

  const attemptsByDataType = new Map<string, RunFlowNode[]>();
  const attemptDataTypeById = new Map<string, string>();
  providerAttempts.forEach((node) => {
    const dataType = dataTypeFromNode(node) || node.id.replace(/^provider_/, '').split('_').slice(0, -2).join('_') || 'provider';
    const group = attemptsByDataType.get(dataType) || [];
    group.push(node);
    attemptsByDataType.set(dataType, group);
    attemptDataTypeById.set(node.id, dataType);
    const groupId = `${PROVIDER_GROUP_PREFIX}${dataType}`;
    nodeIdMap.set(node.id, options.expandedGroupIds?.has(groupId) ? node.id : groupId);
  });

  const attemptTopologyById = new Map<string, {
    dataType: string;
    groupId: string;
    order: number;
  }>();
  attemptsByDataType.forEach((attempts, dataType) => {
    [...attempts]
      .sort((left, right) => (
        (nodeTime(left) ?? Number.MAX_SAFE_INTEGER) - (nodeTime(right) ?? Number.MAX_SAFE_INTEGER)
      ))
      .forEach((node, index) => {
        attemptTopologyById.set(node.id, {
          dataType,
          groupId: `${PROVIDER_GROUP_PREFIX}${dataType}`,
          order: index + 1,
        });
      });
  });

  const providerGroupNodes = Array.from(attemptsByDataType.entries()).map(([dataType, attempts]) => {
    const attemptIds = new Set(attempts.map((node) => node.id));
    const attemptEdges = snapshot.edges.filter((edge) => attemptIds.has(edge.from) && attemptIds.has(edge.to));
    const groupId = `${PROVIDER_GROUP_PREFIX}${dataType}`;
    return buildProviderGroupNode(dataType, attempts, attemptEdges, Boolean(options.expandedGroupIds?.has(groupId)));
  });

  const collapsedProviderIds = providerAttempts
    .filter((node) => {
      const dataType = attemptDataTypeById.get(node.id);
      return !dataType || !options.expandedGroupIds?.has(`${PROVIDER_GROUP_PREFIX}${dataType}`);
    })
    .map((node) => node.id);
  const collapsedNodeIds = new Set([
    ...collapsedProviderIds,
    ...contextBlocks.map((node) => node.id),
  ]);

  const visibleNodes = snapshot.nodes
    .filter((node) => !collapsedNodeIds.has(node.id))
    .map((node) => {
      const topology = attemptTopologyById.get(node.id);
      if (!topology) {
        return node;
      }
      return {
        ...node,
        metadata: {
          ...(node.metadata || {}),
          data_type: topology.dataType,
          topologyParentId: topology.groupId,
          topologyRole: 'provider_attempt',
          topologyOrder: topology.order,
        },
      };
    })
    .map((node) => attachContextBlocksToPack(node, contextBlocks));

  const nodes = [...visibleNodes, ...providerGroupNodes];
  const visibleNodeIds = new Set(nodes.map((node) => node.id));
  const edgeByKey = new Map<string, RunFlowEdge>();

  snapshot.edges.forEach((edge) => {
    const fromDataType = attemptDataTypeById.get(edge.from);
    const toDataType = attemptDataTypeById.get(edge.to);
    if (toDataType && options.expandedGroupIds?.has(`${PROVIDER_GROUP_PREFIX}${toDataType}`) && !fromDataType) {
      return;
    }
    const from = nodeIdMap.get(edge.from) || edge.from;
    const to = nodeIdMap.get(edge.to) || edge.to;
    if (from === to || !visibleNodeIds.has(from) || !visibleNodeIds.has(to)) return;
    const key = `${from}->${to}:${edge.kind}`;
    const existing = edgeByKey.get(key);
    const mappedEdge: RunFlowEdge = {
      ...edge,
      id: existing?.id || `topology_${edgeByKey.size + 1}_${from}_${to}_${edge.kind}`,
      from,
      to,
      status: existing && statusRank(existing.status) > statusRank(edge.status) ? existing.status : edge.status,
      label: existing?.label || edge.label,
      message: existing?.message || edge.message,
    };
    edgeByKey.set(key, mappedEdge);
  });

  attemptsByDataType.forEach((attempts, dataType) => {
    const groupId = `${PROVIDER_GROUP_PREFIX}${dataType}`;
    if (!visibleNodeIds.has(groupId)) return;
    const sortedAttempts = [...attempts].sort((left, right) => (
      (nodeTime(left) ?? Number.MAX_SAFE_INTEGER) - (nodeTime(right) ?? Number.MAX_SAFE_INTEGER)
    ));
    const groupNode = providerGroupNodes.find((node) => node.id === groupId);
    if (!edgeByKey.has(`task_queue->${groupId}:control`) && visibleNodeIds.has('task_queue')) {
      edgeByKey.set(`task_queue->${groupId}:control`, {
        id: `topology_task_queue_${groupId}`,
        from: 'task_queue',
        to: groupId,
        kind: 'control',
        status: groupNode?.status || 'unknown',
        label: '调用',
      });
    }
    if (!options.expandedGroupIds?.has(groupId)) return;
    const firstAttempt = sortedAttempts.find((attempt) => visibleNodeIds.has(attempt.id));
    if (firstAttempt) {
      edgeByKey.set(`${groupId}->${firstAttempt.id}:control`, {
        id: `topology_${groupId}_${firstAttempt.id}`,
        from: groupId,
        to: firstAttempt.id,
        kind: 'control',
        status: firstAttempt.status,
        label: '详情',
      });
    }
  });

  const events = snapshot.events.map((event) => ({
    ...event,
    nodeId: event.nodeId ? nodeIdMap.get(event.nodeId) || event.nodeId : event.nodeId,
  }));

  return {
    lanes: snapshot.lanes,
    nodes,
    edges: Array.from(edgeByKey.values()),
    events,
    nodeIdMap,
  };
};
