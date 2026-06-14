import type React from 'react';
import { useMemo, useId } from 'react';
import { Badge, StatusDot, Tooltip } from '../common';
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

interface RunFlowGraphProps {
  lanes: RunFlowLane[];
  nodes: RunFlowNode[];
  edges: RunFlowEdge[];
  selectedNodeId?: string | null;
  onSelectNode?: (node: RunFlowNode) => void;
}

type PositionedNode = RunFlowNode & {
  x: number;
  y: number;
  width: number;
  height: number;
  row: number;
  laneIndex: number;
};

type EdgePort = 'top' | 'right' | 'bottom' | 'left';

interface PortPoint {
  x: number;
  y: number;
  side: EdgePort;
}

const LANE_WIDTH = 292;
const NODE_WIDTH = 244;
const NODE_HEIGHT = 124;
const HEADER_HEIGHT = 42;
const ROW_HEIGHT = 144;
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

  if ((edge.kind === 'fallback' || edge.kind === 'retry') && isVerticalRelation && Math.abs(to.x - from.x) < LANE_WIDTH * 1.25) {
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

export const RunFlowGraph: React.FC<RunFlowGraphProps> = ({
  lanes,
  nodes,
  edges,
  selectedNodeId,
  onSelectNode,
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
    laneList.forEach((lane, index) => {
      laneIndexById.set(lane.id, index);
    });
    nodes.forEach((node, index) => {
      const items = grouped.get(node.lane) || [];
      items.push(node);
      grouped.set(node.lane, items);
      originalIndex.set(node.id, index);
      nodeById.set(node.id, node);
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
      const laneNodes = [...(grouped.get(lane.id) || [])].sort((left, right) => (
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
    let maxRow = 0;
    laneList.forEach((lane, lanePosition) => {
      const laneNodes = [...(grouped.get(lane.id) || [])].sort((left, right) => (
        resolvePreferredRow(left.id) - resolvePreferredRow(right.id)
        || compareLaneNodes(lane.id, left, right, originalIndex)
      ));
      const occupiedRows = new Set<number>();
      laneNodes.forEach((node) => {
        const row = findAvailableRow(occupiedRows, resolvePreferredRow(node.id));
        occupiedRows.add(row);
        maxRow = Math.max(maxRow, row);
        positioned.set(node.id, {
          ...node,
          x: lanePosition * LANE_WIDTH + LEFT_PADDING,
          y: HEADER_HEIGHT + TOP_PADDING + row * ROW_HEIGHT,
          width: NODE_WIDTH,
          height: NODE_HEIGHT,
          row,
          laneIndex: lanePosition,
        });
      });
    });

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
      width: Math.max(laneList.length * LANE_WIDTH + LEFT_PADDING, LANE_WIDTH),
      height: HEADER_HEIGHT + TOP_PADDING + (maxRow + 1) * ROW_HEIGHT + BOTTOM_PADDING,
    };
  }, [edges, laneList, nodes]);

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
      const relatedToSelected = Boolean(selectedNodeId && (edge.from === selectedNodeId || edge.to === selectedNodeId));
      return {
        edge,
        path,
        labelX: (start.x + end.x) / 2,
        labelY: (start.y + end.y) / 2 - 6,
        relatedToSelected,
      };
    })
    .filter((item): item is NonNullable<typeof item> => Boolean(item));

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
                markerWidth="8"
                markerHeight="8"
                refX="7"
                refY="4"
                orient="auto"
                markerUnits="strokeWidth"
              >
                <path d="M 0 0 L 8 4 L 0 8 z" fill="currentColor" />
              </marker>
            </defs>
            {edgePaths.map(({ edge, path, labelX, labelY, relatedToSelected }) => (
              <g key={edge.id} style={{ color: getEdgeStroke(edge.status) }}>
                <path
                  d={path}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={edge.kind === 'fallback' || edge.kind === 'retry' ? 2.5 : 1.75}
                  strokeDasharray={edge.kind === 'retry' ? '7 5' : edge.kind === 'fallback' ? '4 4' : undefined}
                  markerEnd={`url(#${arrowId}-arrow)`}
                  opacity={selectedNodeId ? (relatedToSelected ? 0.9 : 0.22) : 0.68}
                />
                {edge.label && (!selectedNodeId || relatedToSelected || edge.kind === 'fallback' || edge.kind === 'retry') ? (
                  <text
                    x={labelX}
                    y={labelY}
                    textAnchor="middle"
                    className="fill-muted-text text-[10px]"
                    style={{ paintOrder: 'stroke', stroke: 'hsl(var(--card))', strokeWidth: 4 }}
                  >
                    {compactText(edge.label, 22)}
                  </text>
                ) : null}
              </g>
            ))}
          </svg>

          {laneList.map((lane, index) => (
            <div
              key={`${lane.id}-band`}
              aria-hidden="true"
              className="absolute top-0 z-0 rounded-lg border border-subtle/70 bg-base/20"
              style={{
                left: index * LANE_WIDTH + LEFT_PADDING - 8,
                width: NODE_WIDTH + 16,
                height: layout.height,
              }}
            />
          ))}

          {laneList.map((lane, index) => (
            <div
              key={lane.id}
              className="absolute top-0 z-20 rounded-lg border border-subtle bg-base/75 px-3 py-2 text-xs font-medium text-secondary-text backdrop-blur-sm"
              style={{ left: index * LANE_WIDTH + LEFT_PADDING, width: NODE_WIDTH }}
            >
              {lane.label}
            </div>
          ))}

          {Array.from(layout.positioned.values()).map((node) => {
            const style = RUN_FLOW_STATUS_STYLE[node.status] || RUN_FLOW_STATUS_STYLE.unknown;
            const selected = selectedNodeId === node.id;
            const statusLabel = getRunFlowStatusLabel(node.status, t);
            return (
              <Tooltip key={node.id} content={node.message || statusLabel} side="bottom">
                <button
                  type="button"
                  data-testid={`run-flow-node-${node.id}`}
                  onClick={() => onSelectNode?.(node)}
                  aria-pressed={selected}
                  aria-label={t('runFlow.graph.nodeAria', { label: node.label, status: statusLabel })}
                  data-layout-lane={node.laneIndex}
                  data-layout-row={node.row}
                  className={`absolute z-30 flex flex-col items-start rounded-lg border bg-elevated/92 px-3 py-2 text-left shadow-soft-card backdrop-blur-sm transition-all hover:-translate-y-0.5 hover:border-primary/60 hover:shadow-lg focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan/15 ${
                    selected ? 'border-primary/70 ring-2 ring-primary/20' : 'border-subtle'
                  }`}
                  style={{ left: node.x, top: node.y, width: node.width, minHeight: node.height }}
                >
                  <span className="flex w-full min-w-0 items-start justify-between gap-2">
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold text-foreground">{node.label}</span>
                      {node.provider ? (
                        <span className="mt-0.5 block truncate text-xs text-muted-text">{node.provider}</span>
                      ) : null}
                    </span>
                    <StatusDot tone={style.tone} pulse={style.pulse} className="mt-1 h-2 w-2" />
                  </span>
                  <span className="mt-2 flex w-full flex-wrap items-center gap-1.5">
                    <Badge variant={style.badge} className="shadow-none">
                      {statusLabel}
                    </Badge>
                    {typeof node.durationMs === 'number' ? (
                      <span className="text-[11px] text-muted-text">{formatDuration(node.durationMs, t)}</span>
                    ) : null}
                  </span>
                  {node.startedAt ? (
                    <span className="mt-1 block w-full truncate text-[11px] text-muted-text">
                      {t('runFlow.graph.startedAt')}: {formatDateTime(node.startedAt, language, t)}
                    </span>
                  ) : null}
                </button>
              </Tooltip>
            );
          })}
        </div>
      </div>
    </div>
  );
};
