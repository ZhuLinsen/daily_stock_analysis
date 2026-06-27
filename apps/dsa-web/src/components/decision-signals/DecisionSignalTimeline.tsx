import type React from 'react';
import { Activity } from 'lucide-react';
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { EmptyState, InlineAlert } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiLanguage, UiTextKey } from '../../i18n/uiText';
import type { DecisionSignalItem, DecisionSignalStatus } from '../../types/decisionSignals';
import { buildDecisionActionLabelMap, getDecisionActionLabel } from '../../utils/decisionAction';
import { getDecisionProfile } from '../../utils/decisionSignalProfile';
import {
  getDecisionSignalHorizonLabel,
} from '../../utils/decisionSignalLabels';
import { parseDecisionSignalDate } from '../../utils/decisionSignalTime';
import { buildTimelineData, type TimelineDatum } from '../../utils/decisionSignalTimeline';

const RANK_LABELS: Record<number, string> = {
  [-3]: 'sell',
  [-2]: 'reduce',
  [-1]: 'avoid',
  0: 'watch / alert',
  1: 'hold',
  2: 'add',
  3: 'buy',
};

const STATUS_LABEL_KEYS: Record<DecisionSignalStatus, UiTextKey> = {
  active: 'decisionSignals.active',
  expired: 'decisionSignals.expired',
  invalidated: 'decisionSignals.invalidated',
  closed: 'decisionSignals.closed',
  archived: 'decisionSignals.archived',
};

const LOCALE_BY_LANGUAGE: Record<UiLanguage, string> = {
  zh: 'zh-CN',
  en: 'en-US',
};

export type DecisionSignalTimelineProps = {
  items: DecisionSignalItem[];
  selectedId?: number | null;
  loading?: boolean;
  error?: string | null;
  truncated?: boolean;
  onSelect: (item: DecisionSignalItem) => void;
};

function formatDateTime(value: string | null | undefined, language: UiLanguage): string {
  const date = parseDecisionSignalDate(value);
  if (!date) return '-';
  return new Intl.DateTimeFormat(LOCALE_BY_LANGUAGE[language], {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function formatNumber(value: number | null | undefined): string {
  const number = finiteNumber(value);
  if (number === null) return '-';
  return number.toFixed(2).replace(/\.?0+$/, '');
}

function finiteNumber(value: number | null | undefined): number | null {
  if (value === null || value === undefined || Number.isNaN(value) || !Number.isFinite(value)) return null;
  return value;
}

function formatConfidence(value: number | null | undefined): string {
  const number = finiteNumber(value);
  if (number === null) return '-';
  return `${formatNumber(Math.abs(number) <= 1 ? number * 100 : number)}%`;
}

type TimelineShapeProps = {
  cx?: number;
  cy?: number;
  payload?: TimelineDatum;
};

function getTimelineDatumFromClick(value: unknown): TimelineDatum | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as { item?: unknown; payload?: unknown };
  if (record.item && typeof record.item === 'object') return value as TimelineDatum;
  if (record.payload && typeof record.payload === 'object') return record.payload as TimelineDatum;
  return null;
}

const TimelinePointShape: React.FC<TimelineShapeProps> = ({ cx = 0, cy = 0, payload }) => {
  if (!payload) return null;
  const opacity = payload.terminal ? 0.46 : 0.92;
  const statusRing = (
    <circle
      data-testid={`timeline-status-ring-${payload.item.id}`}
      cx={cx}
      cy={cy}
      r={payload.radius + 4}
      fill="none"
      stroke={payload.stroke}
      strokeDasharray={payload.statusDasharray}
      strokeWidth={1.5}
      opacity={payload.terminal ? 0.55 : 0.85}
    />
  );
  if (payload.shape === 'diamond') {
    const size = payload.radius;
    return (
      <g>
        {statusRing}
        <rect
          data-testid={`timeline-point-${payload.item.id}`}
          x={cx - size}
          y={cy - size}
          width={size * 2}
          height={size * 2}
          rx={2}
          fill={payload.fill}
          opacity={opacity}
          stroke={payload.stroke}
          strokeWidth={payload.strokeWidth}
          transform={`rotate(45 ${cx} ${cy})`}
        />
      </g>
    );
  }
  return (
    <g>
      {statusRing}
      <circle
        data-testid={`timeline-point-${payload.item.id}`}
        cx={cx}
        cy={cy}
        r={payload.radius}
        fill={payload.fill}
        opacity={opacity}
        stroke={payload.stroke}
        strokeWidth={payload.strokeWidth}
      />
    </g>
  );
};

type TimelineTooltipProps = {
  active?: boolean;
  payload?: Array<{ payload?: TimelineDatum }>;
};

const TimelineTooltip: React.FC<TimelineTooltipProps> = ({ active, payload }) => {
  const { language, t } = useUiLanguage();
  const actionLabels = buildDecisionActionLabelMap(t);
  if (!active || !payload?.[0]?.payload) return null;
  const datum = payload[0].payload;
  const item = datum.item;
  const actionLabel = getDecisionActionLabel(
    item.action,
    item.actionLabel,
    null,
    t('decisionSignals.action'),
    actionLabels,
  ) ?? item.action;
  return (
    <div className="rounded-xl border border-border/70 bg-card/95 px-3 py-2 text-xs shadow-card">
      <div className="font-semibold text-foreground">{item.stockName || item.stockCode}</div>
      <div className="mt-2 grid gap-1 text-secondary-text">
        <span>{t('decisionSignals.createdAt')}: {formatDateTime(item.createdAt, language)}</span>
        <span>{t('decisionSignals.action')}: {actionLabel}</span>
        <span>{t('decisionSignals.score')}: {formatNumber(item.score)}</span>
        <span>{t('decisionSignals.confidence')}: {formatConfidence(item.confidence)}</span>
        <span>{t('decisionSignals.horizon')}: {getDecisionSignalHorizonLabel(item.horizon, t)}</span>
        <span>{t('decisionSignals.status')}: {t(STATUS_LABEL_KEYS[item.status])}</span>
        <span>{t('decisionSignals.sourceReport')}: {item.sourceReportId ? `#${item.sourceReportId}` : '-'}</span>
        <span>{t('decisionSignals.profile')}: {getDecisionProfile(item)}</span>
      </div>
    </div>
  );
};

export const DecisionSignalTimeline: React.FC<DecisionSignalTimelineProps> = ({
  items,
  selectedId = null,
  loading = false,
  error = null,
  truncated = false,
  onSelect,
}) => {
  const { language, t } = useUiLanguage();
  const data = buildTimelineData(items);
  const selectedDatum = selectedId === null ? null : data.find((datum) => datum.item.id === selectedId);
  const selectedIndex = selectedDatum?.index ?? null;

  if (loading) {
    return <p className="text-sm text-secondary-text">{t('common.loading')}...</p>;
  }

  if (error) {
    return <InlineAlert variant="danger" title={t('decisionSignals.timelineErrorTitle')} message={error} />;
  }

  if (items.length === 0) {
    return (
      <EmptyState
        className="border-none bg-transparent py-6 shadow-none"
        title={t('decisionSignals.timelineEmptyTitle')}
        description={t('decisionSignals.timelineEmptyDescription')}
        icon={<Activity className="h-6 w-6" />}
      />
    );
  }

  return (
    <div className="space-y-3">
      {truncated ? (
        <InlineAlert
          variant="warning"
          title={t('decisionSignals.timelineTruncatedTitle')}
          message={t('decisionSignals.timelineTruncatedDescription')}
        />
      ) : null}
      <div className="h-[320px] min-h-[320px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 18, right: 18, bottom: 20, left: 4 }}>
            <CartesianGrid stroke="rgba(148, 163, 184, 0.18)" vertical={false} />
            <XAxis
              dataKey="x"
              type="number"
              domain={['dataMin', 'dataMax']}
              tickFormatter={(value) => formatDateTime(new Date(Number(value)).toISOString(), language)}
              tick={{ fontSize: 11, fill: 'currentColor' }}
              stroke="rgba(148, 163, 184, 0.5)"
            />
            <YAxis
              dataKey="rank"
              type="number"
              domain={[-3.5, 3.5]}
              ticks={[-3, -2, -1, 0, 1, 2, 3]}
              tickFormatter={(value) => RANK_LABELS[Number(value)] ?? String(value)}
              tick={{ fontSize: 11, fill: 'currentColor' }}
              stroke="rgba(148, 163, 184, 0.5)"
              width={76}
            />
            <ChartTooltip
              cursor={{ stroke: 'rgba(148, 163, 184, 0.35)', strokeDasharray: '3 3' }}
              content={(props: unknown) => <TimelineTooltip {...(props as TimelineTooltipProps)} />}
            />
            <Scatter
              data={data}
              dataKey="rank"
              isAnimationActive={false}
              onClick={(value: unknown) => {
                const datum = getTimelineDatumFromClick(value);
                if (datum) onSelect(datum.item);
              }}
              shape={(props: unknown) => <TimelinePointShape {...(props as TimelineShapeProps)} />}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-secondary-text">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-[#16a34a]" />{t('decisionSignals.timelineFamilyBullish')}</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-[#dc2626]" />{t('decisionSignals.timelineFamilyDefensive')}</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-[#0891b2]" />{t('decisionSignals.timelineFamilyNeutral')}</span>
        <span>{t('decisionSignals.timelineAlertShape')}</span>
        {selectedIndex !== null ? <span>{t('decisionSignals.timelineSelected', { index: selectedIndex + 1 })}</span> : null}
      </div>
    </div>
  );
};
