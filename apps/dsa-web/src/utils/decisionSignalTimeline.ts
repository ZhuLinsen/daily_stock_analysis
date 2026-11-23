import type { DecisionAction } from '../types/analysis';
import type { DecisionSignalItem, DecisionSignalStatus } from '../types/decisionSignals';
import { parseDecisionSignalDate } from './decisionSignalTime';

const TERMINAL_STATUSES = new Set<DecisionSignalStatus>(['expired', 'invalidated', 'closed', 'archived']);
const DEFAULT_RADIUS = 6;
const MIN_RADIUS = 4;
const MAX_RADIUS = 12;
const DEFAULT_STROKE_WIDTH = 2;
const MIN_STROKE_WIDTH = 1.5;
const MAX_STROKE_WIDTH = 5;
const INVALID_DATE_STEP_MS = 60 * 60 * 1000;

export const ACTION_RANK: Record<DecisionAction, number> = {
  sell: -3,
  reduce: -2,
  avoid: -1,
  watch: 0,
  alert: 0,
  hold: 1,
  add: 2,
  buy: 3,
};

type ActionFamily = 'bullish' | 'defensive' | 'neutral';
export type PointShape = 'circle' | 'diamond';

export type TimelinePointStyle = {
  rank: number;
  family: ActionFamily;
  radius: number;
  strokeWidth: number;
  terminal: boolean;
  shape: PointShape;
  fill: string;
  stroke: string;
  statusDasharray: string | undefined;
};

export type TimelineDatum = TimelinePointStyle & {
  item: DecisionSignalItem;
  index: number;
  x: number;
  createdTime: number | null;
};

function finiteNumber(value: number | null | undefined): number | null {
  if (value === null || value === undefined || Number.isNaN(value) || !Number.isFinite(value)) return null;
  return value;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function getActionFamily(action: DecisionAction): ActionFamily {
  if (action === 'buy' || action === 'add' || action === 'hold') return 'bullish';
  if (action === 'sell' || action === 'reduce' || action === 'avoid') return 'defensive';
  return 'neutral';
}

function getPointColor(family: ActionFamily, terminal: boolean): string {
  if (terminal) return '#8a9099';
  if (family === 'bullish') return '#16a34a';
  if (family === 'defensive') return '#dc2626';
  return '#0891b2';
}

export function getTimelinePointStyle(item: DecisionSignalItem): TimelinePointStyle {
  const score = finiteNumber(item.score);
  const confidence = finiteNumber(item.confidence);
  const normalizedScore = score === null ? null : clamp(score, 0, 100);
  const normalizedConfidence = confidence === null ? null : clamp(confidence, 0, 1);
  const terminal = TERMINAL_STATUSES.has(item.status);
  const family = getActionFamily(item.action);
  const color = getPointColor(family, terminal);
  return {
    rank: ACTION_RANK[item.action],
    family,
    radius: normalizedScore === null
      ? DEFAULT_RADIUS
      : MIN_RADIUS + ((MAX_RADIUS - MIN_RADIUS) * normalizedScore) / 100,
    strokeWidth: normalizedConfidence === null
      ? DEFAULT_STROKE_WIDTH
      : MIN_STROKE_WIDTH + ((MAX_STROKE_WIDTH - MIN_STROKE_WIDTH) * normalizedConfidence),
    terminal,
    shape: item.action === 'alert' ? 'diamond' : 'circle',
    fill: color,
    stroke: color,
    statusDasharray: getStatusDasharray(item.status),
  };
}

function getStatusDasharray(status: DecisionSignalStatus): string | undefined {
  if (status === 'active') return undefined;
  if (status === 'expired') return '6 3';
  if (status === 'invalidated') return '2 2';
  if (status === 'closed') return '8 3';
  return '1 3';
}

export function sortDecisionSignalTimelineItems(items: DecisionSignalItem[]): DecisionSignalItem[] {
  return [...items].sort((a, b) => {
    const left = parseDecisionSignalDate(a.createdAt)?.getTime() ?? Number.POSITIVE_INFINITY;
    const right = parseDecisionSignalDate(b.createdAt)?.getTime() ?? Number.POSITIVE_INFINITY;
    return left - right;
  });
}

export function buildTimelineData(items: DecisionSignalItem[], fallbackNow = Date.now()): TimelineDatum[] {
  const sortedItems = sortDecisionSignalTimelineItems(items);
  const parsedTimes = sortedItems.map((item) => parseDecisionSignalDate(item.createdAt)?.getTime() ?? null);
  const validTimes = parsedTimes.filter((time): time is number => time !== null);
  const maxTime = validTimes.length > 0 ? Math.max(...validTimes) : fallbackNow;
  let invalidOffset = 0;
  return sortedItems.map((item, index) => {
    const createdTime = parsedTimes[index];
    const style = getTimelinePointStyle(item);
    if (createdTime === null) {
      invalidOffset += 1;
    }
    return {
      ...style,
      item,
      index,
      createdTime,
      x: createdTime ?? maxTime + invalidOffset * INVALID_DATE_STEP_MS,
    };
  });
}
