import type React from 'react';
import { useMemo, useId } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Badge, StatusDot } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { RunFlowEdge, RunFlowLane, RunFlowNode, RunFlowStatus } from '../../types/runFlow';
import {
  compactText,
  formatDateTime,
  formatDuration,
  getNodeDisplayOrder,
  getRunFlowEdgeKindLabel,
  getRunFlowStatusLabel,
  RUN_FLOW_STATUS_STYLE,
} from './utils';

type RunFlowT = ReturnType<typeof useUiLanguage>['t'];

interface RunFlowGraphProps {
  lanes: RunFlowLane[];
  nodes: RunFlowNode[];
  edges: RunFlowEdge[];
  selectedNodeId?: string | null;
  expandedNodeIds?: Set<string>;
  onSelectNode?: (node: RunFlowNode) => void;
  onToggleExpanded?: (nodeId: string) => void;
}

type PositionedNode = RunFlowNode & {
  x: number;
  y: number;
  width: number;
  height: number;
  row: number;
  laneIndex: number;
  compact?: boolean;
  expandedGroupId?: string;
};

interface DataSourceBlock {
  id: string;
  nodes: RunFlowNode[];
}

type EdgePort = 'top' | 'right' | 'bottom' | 'left';
type EdgeFocusLevel = 'none' | 'direct' | 'internal';

interface PortPoint {
  x: number;
  y: number;
  side: EdgePort;
}

interface LaneMetrics {
  laneWidth: number;
  nodeWidth: number;
}

const DEFAULT_LANE_WIDTH = 260;
const DEFAULT_NODE_WIDTH = 224;
const LANE_METRICS: Record<string, LaneMetrics> = {
  entry: { laneWidth: 220, nodeWidth: 188 },
  data_source: { laneWidth: 292, nodeWidth: 244 },
  analysis: { laneWidth: 260, nodeWidth: 224 },
  artifact: { laneWidth: 220, nodeWidth: 188 },
};
const NODE_HEIGHT = 112;
const COMPACT_NODE_HEIGHT = 96;
const HEADER_HEIGHT = 42;
const ROW_HEIGHT = 140;
const ENTRY_ROW_HEIGHT = 152;
const ARTIFACT_ROW_HEIGHT = 152;
const DATA_SOURCE_ATTEMPT_GAP = 42;
const DATA_SOURCE_BLOCK_GAP = 40;
const DATA_SOURCE_GROUP_X_PADDING = 18;
const DATA_SOURCE_GROUP_TOP_PADDING = 18;
const DATA_SOURCE_GROUP_BOTTOM_PADDING = 18;
const LEFT_PADDING = 20;
const TOP_PADDING = 18;
const BOTTOM_PADDING = 30;

const getEdgeStroke = (status: RunFlowStatus): string => {
  if (status === 'failed' || status === 'timeout') return 'hsl(var(--destructive))';
  if (status === 'fallback' || status === 'degraded' || status === 'cancel_requested') return 'hsl(var(--warning))';
  if (status === 'success') return 'hsl(var(--success))';
  if (status === 'running') return 'hsl(var(--primary))';
  return 'hsl(var(--muted-text))';
};

const getEdgeFocusRank = (level: EdgeFocusLevel): number => {
  if (level === 'internal') return 2;
  if (level === 'direct') return 1;
  return 0;
};

const getEdgeStrokeWidth = (edge: RunFlowEdge, focusLevel: EdgeFocusLevel): number => {
  const isFallbackPath = edge.kind === 'fallback' || edge.kind === 'retry';
  if (focusLevel === 'internal') {
    return isFallbackPath ? 3.5 : 3;
  }
  if (focusLevel === 'direct') {
    return isFallbackPath ? 3 : 2.4;
  }
  return isFallbackPath ? 2.5 : 1.75;
};

const getEdgeOpacity = (selectedNodeId: string | null | undefined, focusLevel: EdgeFocusLevel): number => {
  if (!selectedNodeId) return 0.68;
  if (focusLevel === 'internal') return 0.95;
  if (focusLevel === 'direct') return 0.82;
  return 0.18;
};

const findAvailableRow = (occupiedRows: Set<number>, preferredRow: number): number => {
  const safePreferred = Math.max(0, preferredRow);
  for (let distance = 0; distance < 1000; distance += 1) {
    const lower = safePreferred - distance;
    const upper = safePreferred + distance;
    if (lower >= 0 && !occupiedRows.has(lower)) {
      return lower;
    }
    if (!occupiedRows.has(upper)) {
      return upper;
    }
  }
  return occupiedRows.size;
};

const getAnchorOffset = (total: number, index: number, height: number): number => {
  if (total <= 1) {
    return height / 2;
  }
  const step = height / (total + 1);
  return step * (index + 1);
};

const getCenteredTrackOffset = (total: number, index: number, step = 12): number => (
  (index - (total - 1) / 2) * step
);

const getLaneMetrics = (laneId: string): LaneMetrics => (
  LANE_METRICS[laneId] || { laneWidth: DEFAULT_LANE_WIDTH, nodeWidth: DEFAULT_NODE_WIDTH }
);

const getLaneRowHeight = (laneId: string): number => (
  laneId === 'entry' ? ENTRY_ROW_HEIGHT : (laneId === 'artifact' ? ARTIFACT_ROW_HEIGHT : ROW_HEIGHT)
);

const isExpandableNode = (node: RunFlowNode): boolean => node.metadata?.topologyGroup === 'provider_attempts';

const getEdgeLabel = (label: string | null | undefined, t: RunFlowT): string | null => {
  if (!label) return null;
  if (label === '调用') return t('runFlow.edgeLabel.invoke');
  if (label === '详情') return t('runFlow.edgeLabel.details');
  return label;
};

const metadataString = (node: RunFlowNode, key: string): string | null => {
  const value = node.metadata?.[key];
  return typeof value === 'string' && value.trim() ? value.trim() : null;
};

const dataTypeFromNode = (node: RunFlowNode): string | null => metadataString(node, 'data_type');

const topologyParentIdFromNode = (node: RunFlowNode): string | null => metadataString(node, 'topologyParentId');

const topologyRoleFromNode = (node: RunFlowNode): string | null => metadataString(node, 'topologyRole');

const topologyOrderFromNode = (node: RunFlowNode): number | null => {
  const value = node.metadata?.topologyOrder;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
};

const isExpandedProviderGroup = (node: RunFlowNode, expandedNodeIds?: Set<string>): boolean => (
  isExpandableNode(node) && (expandedNodeIds?.has(node.id) || node.metadata?.expanded === true)
);

const portPoint = (node: PositionedNode, side: EdgePort, offset = 0): PortPoint => {
  if (side === 'top') {
    return { x: node.x + node.width / 2 + offset, y: node.y, side };
  }
  if (side === 'bottom') {
    return { x: node.x + node.width / 2 + offset, y: node.y + node.height, side };
  }
  if (side === 'left') {
    return { x: node.x, y: node.y + node.height / 2 + offset, side };
  }
  return { x: node.x + node.width, y: node.y + node.height / 2 + offset, side };
};

const chooseEdgePorts = (
  edge: RunFlowEdge,
  from: PositionedNode,
  to: PositionedNode,
): { startSide: EdgePort; endSide: EdgePort; vertical: boolean } => {
  const sameLane = from.lane === to.lane;
  const verticalDistance = Math.abs(to.y - from.y);
  const isVerticalRelation = verticalDistance >= ROW_HEIGHT / 2;

  if (sameLane && isVerticalRelation) {
    return to.y >= from.y
      ? { startSide: 'bottom', endSide: 'top', vertical: true }
      : { startSide: 'top', endSide: 'bottom', vertical: true };
  }

  if ((edge.kind === 'fallback' || edge.kind === 'retry') && isVerticalRelation && Math.abs(to.x - from.x) < DEFAULT_LANE_WIDTH * 1.25) {
    return to.y >= from.y
      ? { startSide: 'bottom', endSide: 'top', vertical: true }
      : { startSide: 'top', endSide: 'bottom', vertical: true };
  }

  return to.x >= from.x
    ? { startSide: 'right', endSide: 'left', vertical: false }
    : { startSide: 'left', endSide: 'right', vertical: false };
};

const orthogonalPath = (start: PortPoint, end: PortPoint): string => {
  if ((start.side === 'top' || start.side === 'bottom') && (end.side === 'top' || end.side === 'bottom')) {
    if (Math.abs(start.x - end.x) < 1) {
      return `M ${start.x} ${start.y} V ${end.y}`;
    }
    const midY = (start.y + end.y) / 2;
    return `M ${start.x} ${start.y} V ${midY} H ${end.x} V ${end.y}`;
  }

  const midX = (start.x + end.x) / 2;
  return `M ${start.x} ${start.y} H ${midX} V ${end.y} H ${end.x}`;
};

const nodeTimeOrder = (node: RunFlowNode): number | null => {
  const rawTime = node.startedAt || node.endedAt;
  if (!rawTime) {
    return null;
  }
  const parsed = Date.parse(rawTime);
  return Number.isFinite(parsed) ? parsed : null;
};

const compareLaneNodes = (
  laneId: string,
  left: RunFlowNode,
  right: RunFlowNode,
  originalIndex: Map<string, number>,
): number => {
  const leftOriginal = originalIndex.get(left.id) ?? 0;
  const rightOriginal = originalIndex.get(right.id) ?? 0;
  if (laneId === 'data_source') {
    const leftTime = nodeTimeOrder(left);
    const rightTime = nodeTimeOrder(right);
    if (leftTime !== null || rightTime !== null) {
      return (leftTime ?? Number.MAX_SAFE_INTEGER) - (rightTime ?? Number.MAX_SAFE_INTEGER)
        || getNodeDisplayOrder(left, leftOriginal) - getNodeDisplayOrder(right, rightOriginal);
    }
  }
  return getNodeDisplayOrder(left, leftOriginal) - getNodeDisplayOrder(right, rightOriginal);
};

const buildDataSourceBlocks = (
  laneNodes: RunFlowNode[],
  originalIndex: Map<string, number>,
  expandedNodeIds?: Set<string>,
): DataSourceBlock[] => {
  const expandedGroupByDataType = new Map<string, RunFlowNode>();
  const expandedGroupById = new Map<string, RunFlowNode>();
  laneNodes.forEach((node) => {
    const dataType = dataTypeFromNode(node);
    if (dataType && isExpandedProviderGroup(node, expandedNodeIds)) {
      expandedGroupByDataType.set(dataType, node);
      expandedGroupById.set(node.id, node);
    }
  });

  const attemptGroupIdByNodeId = new Map<string, string>();
  const attemptsByGroupId = new Map<string, RunFlowNode[]>();
  laneNodes.forEach((node) => {
    if (isExpandableNode(node)) {
      return;
    }
    const explicitParentId = topologyParentIdFromNode(node);
    const providerAttemptLike = topologyRoleFromNode(node) === 'provider_attempt'
      || Boolean(explicitParentId)
      || node.id.startsWith('provider_');
    const dataType = dataTypeFromNode(node);
    const fallbackGroup = dataType ? expandedGroupByDataType.get(dataType) : null;
    const groupId = explicitParentId && expandedGroupById.has(explicitParentId)
      ? explicitParentId
      : (providerAttemptLike ? fallbackGroup?.id : undefined);
    if (!groupId || !expandedGroupById.has(groupId)) {
      return;
    }
    const attempts = attemptsByGroupId.get(groupId) || [];
    attempts.push(node);
    attemptsByGroupId.set(groupId, attempts);
    attemptGroupIdByNodeId.set(node.id, groupId);
  });

  const topLevelNodes = laneNodes
    .filter((node) => !attemptGroupIdByNodeId.has(node.id))
    .sort((left, right) => compareLaneNodes('data_source', left, right, originalIndex));

  return topLevelNodes.map((node) => {
    if (!isExpandedProviderGroup(node, expandedNodeIds)) {
      return { id: node.id, nodes: [node] };
    }
    const attempts = [...(attemptsByGroupId.get(node.id) || [])].sort((left, right) => (
      (topologyOrderFromNode(left) ?? Number.MAX_SAFE_INTEGER) - (topologyOrderFromNode(right) ?? Number.MAX_SAFE_INTEGER)
      || (nodeTimeOrder(left) ?? Number.MAX_SAFE_INTEGER) - (nodeTimeOrder(right) ?? Number.MAX_SAFE_INTEGER)
      || getNodeDisplayOrder(left, originalIndex.get(left.id) ?? 0) - getNodeDisplayOrder(right, originalIndex.get(right.id) ?? 0)
    ));
    return { id: node.id, nodes: [node, ...attempts] };
  });
};

export const RunFlowGraph: React.FC<RunFlowGraphProps> = ({
  lanes,
  nodes,
  edges,
  selectedNodeId,
  expandedNodeIds,
  onSelectNode,
  onToggleExpanded,
}) => {
  const arrowId = useId().replace(/:/g, '-');
  const { language, t } = useUiLanguage();
  const laneList = useMemo(() => {
    const sortedLanes = [...lanes].sort((left, right) => left.order - right.order);
    const knownLaneIds = new Set(sortedLanes.map((lane) => lane.id));
    const extraLanes = nodes
      .map((node) => node.lane)
      .filter((laneId, index, values) => !knownLaneIds.has(laneId) && values.indexOf(laneId) === index)
      .map((laneId, index) => ({
        id: laneId,
        label: laneId,
        order: sortedLanes.length + index + 1,
      }));
    return [...sortedLanes, ...extraLanes];
  }, [lanes, nodes]);
  const layout = useMemo(() => {
    const grouped = new Map<string, RunFlowNode[]>();
    const originalIndex = new Map<string, number>();
    const nodeById = new Map<string, RunFlowNode>();
    const laneIndexById = new Map<string, number>();
    const laneOffsets = new Map<string, number>();
    let nextLaneOffset = LEFT_PADDING;
    laneList.forEach((lane, index) => {
      laneIndexById.set(lane.id, index);
      laneOffsets.set(lane.id, nextLaneOffset);
      nextLaneOffset += getLaneMetrics(lane.id).laneWidth;
    });
    nodes.forEach((node, index) => {
      const items = grouped.get(node.lane) || [];
      items.push(node);
      grouped.set(node.lane, items);
      originalIndex.set(node.id, index);
      nodeById.set(node.id, node);
    });

    const dataSourceBlocks = buildDataSourceBlocks(grouped.get('data_source') || [], originalIndex, expandedNodeIds);
    const dataSourceNodeSequence = dataSourceBlocks.flatMap((block) => block.nodes);
    const expandedGroupIdByAttemptId = new Map<string, string>();
    dataSourceBlocks.forEach((block) => {
      if (block.nodes.length <= 1 || !isExpandedProviderGroup(block.nodes[0], expandedNodeIds)) {
        return;
      }
      block.nodes.slice(1).forEach((node) => {
        expandedGroupIdByAttemptId.set(node.id, block.nodes[0].id);
      });
    });

    const validEdges = edges.filter((edge) => nodeById.has(edge.from) && nodeById.has(edge.to));
    const incomingByNode = new Map<string, RunFlowEdge[]>();
    const outgoingByNode = new Map<string, RunFlowEdge[]>();
    validEdges.forEach((edge) => {
      incomingByNode.set(edge.to, [...(incomingByNode.get(edge.to) || []), edge]);
      outgoingByNode.set(edge.from, [...(outgoingByNode.get(edge.from) || []), edge]);
    });

    const laneOrderByNode = new Map<string, number>();
    laneList.forEach((lane) => {
      const laneNodes = lane.id === 'data_source'
        ? dataSourceNodeSequence
        : [...(grouped.get(lane.id) || [])].sort((left, right) => (
          compareLaneNodes(lane.id, left, right, originalIndex)
        ));
      laneNodes.forEach((node, index) => {
        laneOrderByNode.set(node.id, index);
      });
    });

    const preferredRows = new Map<string, number>();
    const visiting = new Set<string>();
    const resolvePreferredRow = (nodeId: string): number => {
      if (preferredRows.has(nodeId)) {
        return preferredRows.get(nodeId) || 0;
      }
      if (visiting.has(nodeId)) {
        return laneOrderByNode.get(nodeId) || 0;
      }
      visiting.add(nodeId);
      const node = nodeById.get(nodeId);
      const baseRow = laneOrderByNode.get(nodeId) || 0;
      if (!node) {
        visiting.delete(nodeId);
        return baseRow;
      }
      const nodeLaneIndex = laneIndexById.get(node.lane) || 0;
      const parentRows = (incomingByNode.get(nodeId) || [])
        .map((edge) => nodeById.get(edge.from))
        .filter((parent): parent is RunFlowNode => Boolean(parent))
        .filter((parent) => (laneIndexById.get(parent.lane) || 0) <= nodeLaneIndex)
        .map((parent) => {
          const parentRow = resolvePreferredRow(parent.id);
          return parent.lane === node.lane ? parentRow + 1 : parentRow;
        });
      const preferredRow = parentRows.length > 0
        ? Math.max(0, Math.round(parentRows.reduce((sum, row) => sum + row, 0) / parentRows.length))
        : baseRow;
      const resolvedRow = Math.max(0, Math.max(baseRow - 1, preferredRow));
      preferredRows.set(nodeId, resolvedRow);
      visiting.delete(nodeId);
      return resolvedRow;
    };

    const positioned = new Map<string, PositionedNode>();
    let maxY = HEADER_HEIGHT + TOP_PADDING;
    laneList.forEach((lane, lanePosition) => {
      const metrics = getLaneMetrics(lane.id);
      if (lane.id === 'data_source') {
        let yCursor = HEADER_HEIGHT + TOP_PADDING;
        let row = 0;
        dataSourceBlocks.forEach((block, blockIndex) => {
          block.nodes.forEach((node, nodeIndex) => {
            const compact = nodeIndex > 0 && expandedGroupIdByAttemptId.has(node.id);
            const height = compact ? COMPACT_NODE_HEIGHT : NODE_HEIGHT;
            positioned.set(node.id, {
              ...node,
              x: laneOffsets.get(lane.id) ?? LEFT_PADDING,
              y: yCursor,
              width: metrics.nodeWidth,
              height,
              row,
              laneIndex: lanePosition,
              compact,
              expandedGroupId: expandedGroupIdByAttemptId.get(node.id),
            });
            maxY = Math.max(maxY, yCursor + height);
            yCursor += height;
            yCursor += nodeIndex < block.nodes.length - 1
              ? DATA_SOURCE_ATTEMPT_GAP
              : (blockIndex < dataSourceBlocks.length - 1 ? DATA_SOURCE_BLOCK_GAP : 0);
            row += 1;
          });
        });
        maxY = Math.max(maxY, yCursor);
        return;
      }

      const laneNodes = [...(grouped.get(lane.id) || [])].sort((left, right) => (
        resolvePreferredRow(left.id) - resolvePreferredRow(right.id)
        || compareLaneNodes(lane.id, left, right, originalIndex)
      ));
      const occupiedRows = new Set<number>();
      const rowHeight = getLaneRowHeight(lane.id);
      laneNodes.forEach((node) => {
        const row = findAvailableRow(occupiedRows, resolvePreferredRow(node.id));
        const y = HEADER_HEIGHT + TOP_PADDING + row * rowHeight;
        occupiedRows.add(row);
        positioned.set(node.id, {
          ...node,
          x: laneOffsets.get(lane.id) ?? LEFT_PADDING,
          y,
          width: metrics.nodeWidth,
          height: NODE_HEIGHT,
          row,
          laneIndex: lanePosition,
        });
        maxY = Math.max(maxY, y + NODE_HEIGHT);
      });
    });

    const expandedGroups = dataSourceBlocks
      .map((block) => {
        if (block.nodes.length <= 1 || !isExpandedProviderGroup(block.nodes[0], expandedNodeIds)) {
          return null;
        }
        const groupNode = positioned.get(block.nodes[0].id);
        const lastNode = positioned.get(block.nodes[block.nodes.length - 1].id);
        if (!groupNode || !lastNode) return null;
        return {
          id: groupNode.id,
          x: groupNode.x - DATA_SOURCE_GROUP_X_PADDING,
          y: groupNode.y - DATA_SOURCE_GROUP_TOP_PADDING,
          width: groupNode.width + DATA_SOURCE_GROUP_X_PADDING * 2,
          height: lastNode.y + lastNode.height - groupNode.y + DATA_SOURCE_GROUP_TOP_PADDING + DATA_SOURCE_GROUP_BOTTOM_PADDING,
        };
      })
      .filter((item): item is NonNullable<typeof item> => Boolean(item));
    const expandedGroupBottom = expandedGroups.reduce((bottom, group) => (
      Math.max(bottom, group.y + group.height)
    ), 0);

    const sortEdgesForAnchors = (edgeItems: RunFlowEdge[], fromNodeId: string) => [...edgeItems].sort((left, right) => {
      const leftTarget = nodeById.get(left.to);
      const rightTarget = nodeById.get(right.to);
      const leftSource = nodeById.get(left.from);
      const rightSource = nodeById.get(right.from);
      const leftOther = left.from === fromNodeId ? leftTarget : leftSource;
      const rightOther = right.from === fromNodeId ? rightTarget : rightSource;
      const leftPosition = leftOther ? positioned.get(leftOther.id) : null;
      const rightPosition = rightOther ? positioned.get(rightOther.id) : null;
      return (leftPosition?.laneIndex ?? 0) - (rightPosition?.laneIndex ?? 0)
        || (leftPosition?.row ?? 0) - (rightPosition?.row ?? 0)
        || left.id.localeCompare(right.id);
    });

    const outgoingAnchors = new Map<string, number>();
    outgoingByNode.forEach((nodeEdges, nodeId) => {
      const node = positioned.get(nodeId);
      if (!node) return;
      const sortedEdges = sortEdgesForAnchors(nodeEdges, nodeId);
      sortedEdges.forEach((edge, index) => {
        outgoingAnchors.set(edge.id, node.y + getAnchorOffset(sortedEdges.length, index, node.height));
      });
    });

    const incomingAnchors = new Map<string, number>();
    incomingByNode.forEach((nodeEdges, nodeId) => {
      const node = positioned.get(nodeId);
      if (!node) return;
      const sortedEdges = sortEdgesForAnchors(nodeEdges, nodeId);
      sortedEdges.forEach((edge, index) => {
        incomingAnchors.set(edge.id, node.y + getAnchorOffset(sortedEdges.length, index, node.height));
      });
    });

    return {
      positioned,
      incomingAnchors,
      outgoingAnchors,
      laneOffsets,
      expandedGroups,
      width: Math.max(nextLaneOffset + LEFT_PADDING, DEFAULT_LANE_WIDTH),
      height: Math.max(maxY, expandedGroupBottom) + BOTTOM_PADDING,
    };
  }, [edges, expandedNodeIds, laneList, nodes]);

  const selectedNode = selectedNodeId ? layout.positioned.get(selectedNodeId) : null;
  const selectedDataType = selectedNode ? dataTypeFromNode(selectedNode) : null;
  const selectedProviderGroup = selectedDataType
    ? Array.from(layout.positioned.values()).find((node) => (
      isExpandedProviderGroup(node, expandedNodeIds) && dataTypeFromNode(node) === selectedDataType
    ))
    : null;
  const selectedRelatedNodeIds = new Set<string>();
  if (selectedNodeId) {
    selectedRelatedNodeIds.add(selectedNodeId);
  }
  if (selectedProviderGroup) {
    selectedRelatedNodeIds.add(selectedProviderGroup.id);
    Array.from(layout.positioned.values()).forEach((node) => {
      if (dataTypeFromNode(node) === selectedDataType && (node.id === selectedProviderGroup.id || node.expandedGroupId === selectedProviderGroup.id)) {
        selectedRelatedNodeIds.add(node.id);
      }
    });
  }

  const edgePaths = edges
    .map((edge, edgeIndex) => {
      const from = layout.positioned.get(edge.from);
      const to = layout.positioned.get(edge.to);
      if (!from || !to) {
        return null;
      }
      const trackOffset = getCenteredTrackOffset(edges.length, edgeIndex, 2);
      const ports = chooseEdgePorts(edge, from, to);
      const startOffset = ports.startSide === 'left' || ports.startSide === 'right'
        ? (layout.outgoingAnchors.get(edge.id) ?? from.y + from.height / 2) - (from.y + from.height / 2)
        : trackOffset;
      const endOffset = ports.endSide === 'left' || ports.endSide === 'right'
        ? (layout.incomingAnchors.get(edge.id) ?? to.y + to.height / 2) - (to.y + to.height / 2)
        : trackOffset;
      const start = portPoint(from, ports.startSide, startOffset);
      const end = portPoint(to, ports.endSide, endOffset);
      const path = orthogonalPath(start, end);
      const fromInSelectedGroup = selectedRelatedNodeIds.has(edge.from);
      const toInSelectedGroup = selectedRelatedNodeIds.has(edge.to);
      const internallyRelated = Boolean(selectedProviderGroup && fromInSelectedGroup && toInSelectedGroup);
      const directlyRelated = Boolean(
        edge.from === selectedNodeId
        || edge.to === selectedNodeId
        || (selectedProviderGroup && (fromInSelectedGroup || toInSelectedGroup)),
      );
      const focusLevel: EdgeFocusLevel = selectedNodeId
        ? (internallyRelated ? 'internal' : (directlyRelated ? 'direct' : 'none'))
        : 'none';
      return {
        edge,
        path,
        labelX: ports.vertical ? Math.max(start.x, end.x) + 10 : (start.x + end.x) / 2,
        labelY: ports.vertical ? (start.y + end.y) / 2 + 4 : (start.y + end.y) / 2 - 8,
        labelAnchor: ports.vertical ? ('start' as const) : ('middle' as const),
        focusLevel,
        relatedToSelected: focusLevel !== 'none',
      };
    })
    .filter((item): item is NonNullable<typeof item> => Boolean(item));

  const edgePathViews = edgePaths.reduce<Array<typeof edgePaths[number] & {
    displayLabel: string | null;
    showLabel: boolean;
  }>>((items, item) => {
    const displayLabel = getEdgeLabel(item.edge.label, t);
    const labelKey = `${item.edge.to}:${displayLabel || ''}`;
    const duplicateLabel = items.some((existing) => (
      existing.relatedToSelected
      && getEdgeLabel(existing.edge.label, t)
      && `${existing.edge.to}:${getEdgeLabel(existing.edge.label, t)}` === labelKey
    ));
    items.push({
      ...item,
      displayLabel,
      showLabel: Boolean(
        displayLabel
        && (!selectedNodeId || item.relatedToSelected || item.edge.kind === 'fallback' || item.edge.kind === 'retry')
        && !duplicateLabel,
      ),
    });
    return items;
  }, []).sort((left, right) => getEdgeFocusRank(left.focusLevel) - getEdgeFocusRank(right.focusLevel));

  return (
    <div className="home-subpanel overflow-hidden p-3" data-testid="run-flow-graph">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="label-uppercase">{t('runFlow.graph.title')}</p>
          <p className="mt-1 text-xs text-muted-text">{t('runFlow.graph.description')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(['data', 'control', 'fallback', 'retry'] as const).map((kind) => (
            <Badge key={kind} variant={kind === 'fallback' || kind === 'retry' ? 'warning' : 'default'} className="shadow-none">
              {getRunFlowEdgeKindLabel(kind, t)}
            </Badge>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto pb-2">
        <div
          className="relative"
          style={{ width: layout.width, minHeight: layout.height }}
        >
          <svg
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 z-10"
            width={layout.width}
            height={layout.height}
            viewBox={`0 0 ${layout.width} ${layout.height}`}
          >
            <defs>
              <marker
                id={`${arrowId}-arrow`}
                markerWidth="4"
                markerHeight="4"
                refX="3.5"
                refY="2"
                orient="auto"
                markerUnits="strokeWidth"
              >
                <path d="M 0 0 L 4 2 L 0 4 z" fill="currentColor" />
              </marker>
            </defs>
            {edgePathViews.map(({ edge, path, labelX, labelY, labelAnchor, focusLevel, showLabel, displayLabel }) => (
              <g key={edge.id} style={{ color: getEdgeStroke(edge.status) }}>
                <path
                  data-testid={`run-flow-edge-${edge.id}`}
                  d={path}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={getEdgeStrokeWidth(edge, focusLevel)}
                  strokeDasharray={edge.kind === 'retry' ? '7 5' : edge.kind === 'fallback' ? '4 4' : undefined}
                  markerEnd={`url(#${arrowId}-arrow)`}
                  opacity={getEdgeOpacity(selectedNodeId, focusLevel)}
                />
                {showLabel ? (
                  <text
                    x={labelX}
                    y={labelY}
                    textAnchor={labelAnchor}
                    className="fill-muted-text text-[10px]"
                    style={{ paintOrder: 'stroke', stroke: 'hsl(var(--card))', strokeWidth: 4 }}
                  >
                    {compactText(displayLabel, 22)}
                  </text>
                ) : null}
              </g>
            ))}
          </svg>

          {laneList.map((lane) => {
            const metrics = getLaneMetrics(lane.id);
            const left = layout.laneOffsets.get(lane.id) ?? LEFT_PADDING;
            return (
            <div
              key={`${lane.id}-band`}
              aria-hidden="true"
              className="absolute top-0 z-0 rounded-lg border border-subtle/70 bg-base/20"
              style={{
                left: left - 8,
                width: metrics.nodeWidth + 16,
                height: layout.height,
              }}
            />
            );
          })}

          {layout.expandedGroups.map((group) => (
            <div
              key={group.id}
              data-testid={`run-flow-expanded-group-${group.id}`}
              aria-hidden="true"
              className="pointer-events-none absolute rounded-lg border border-primary/25 bg-primary/7 shadow-inner"
              style={{
                left: group.x,
                top: group.y,
                width: group.width,
                height: group.height,
                zIndex: 5,
              }}
            />
          ))}

          {laneList.map((lane) => {
            const metrics = getLaneMetrics(lane.id);
            const left = layout.laneOffsets.get(lane.id) ?? LEFT_PADDING;
            return (
            <div
              key={lane.id}
              className="absolute top-0 z-20 rounded-lg border border-subtle bg-base/75 px-3 py-2 text-xs font-medium text-secondary-text backdrop-blur-sm"
              style={{ left, width: metrics.nodeWidth }}
            >
              {lane.label}
            </div>
            );
          })}

          {Array.from(layout.positioned.values()).map((node) => {
            const style = RUN_FLOW_STATUS_STYLE[node.status] || RUN_FLOW_STATUS_STYLE.unknown;
            const selected = selectedNodeId === node.id;
            const statusLabel = getRunFlowStatusLabel(node.status, t);
            const expandable = isExpandableNode(node) && Boolean(onToggleExpanded);
            const expanded = Boolean(expandedNodeIds?.has(node.id));
            const compact = Boolean(node.compact);
            const nodeStateClass = selected
              ? 'border-primary/85 bg-primary/8 shadow-lg ring-2 ring-primary/25'
              : compact
                ? 'border-subtle/70 bg-base/70 ring-1 ring-white/5'
                : 'border-subtle/80 bg-elevated/92 ring-1 ring-white/5';
            const nodeDensityClass = compact
              ? 'px-2.5 py-2 shadow-none hover:shadow-soft-card'
              : 'px-3 py-2 shadow-soft-card hover:shadow-lg';
            return (
              <div
                key={node.id}
                data-testid={`run-flow-node-${node.id}-wrapper`}
                className="absolute z-30"
                style={{ left: node.x, top: node.y, width: node.width, height: node.height }}
              >
                <button
                  type="button"
                  data-testid={`run-flow-node-${node.id}`}
                  onClick={() => onSelectNode?.(node)}
                  aria-pressed={selected}
                  aria-label={t('runFlow.graph.nodeAria', { label: node.label, status: statusLabel })}
                  data-layout-lane={node.laneIndex}
                  data-layout-row={node.row}
                  className={`box-border flex max-w-full min-w-0 flex-col items-start overflow-hidden rounded-lg border-2 text-left backdrop-blur-sm transition-all hover:-translate-y-0.5 hover:border-primary/60 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan/15 ${nodeDensityClass} ${nodeStateClass} ${
                    expandable ? 'pb-8' : ''
                  }`}
                  style={{ width: node.width, height: node.height }}
                >
                  <span className="flex w-full min-w-0 items-start justify-between gap-2">
                    <span className="min-w-0 max-w-full overflow-hidden">
                      <span className="block max-w-full truncate text-sm font-semibold text-foreground">{node.label}</span>
                      {node.provider ? (
                        <span className="mt-0.5 block max-w-full truncate text-xs text-muted-text">{node.provider}</span>
                      ) : null}
                    </span>
                    <StatusDot tone={style.tone} pulse={style.pulse} className="mt-1 h-2 w-2" />
                  </span>
                  <span className="mt-2 flex w-full min-w-0 flex-wrap items-center gap-1.5">
                    <Badge variant={style.badge} className="shadow-none">
                      {statusLabel}
                    </Badge>
                    {typeof node.durationMs === 'number' ? (
                      <span className="min-w-0 truncate text-[11px] text-muted-text">{formatDuration(node.durationMs, t)}</span>
                    ) : null}
                  </span>
                  {node.startedAt ? (
                    <span className="mt-1 block w-full min-w-0 truncate text-[11px] text-muted-text">
                      {t('runFlow.graph.startedAt')}: {formatDateTime(node.startedAt, language, t)}
                    </span>
                  ) : null}
                </button>
                {expandable ? (
                  <button
                    type="button"
                    data-testid={`run-flow-node-${node.id}-toggle`}
                    aria-label={expanded ? t('runFlow.graph.collapseNode', { label: node.label }) : t('runFlow.graph.expandNode', { label: node.label })}
                    aria-expanded={expanded}
                    onClick={(event) => {
                      event.stopPropagation();
                      onToggleExpanded?.(node.id);
                    }}
                    className="absolute bottom-2 right-2 z-40 inline-flex h-[18px] items-center gap-0.5 rounded-md border border-subtle bg-base/80 px-1 text-[9px] font-medium leading-none text-secondary-text shadow-sm transition-colors hover:border-primary/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan/15"
                  >
                    {expanded ? (
                      <ChevronDown className="h-2 w-2" aria-hidden="true" />
                    ) : (
                      <ChevronRight className="h-2 w-2" aria-hidden="true" />
                    )}
                    {expanded ? t('runFlow.graph.collapse') : t('runFlow.graph.expand')}
                  </button>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
