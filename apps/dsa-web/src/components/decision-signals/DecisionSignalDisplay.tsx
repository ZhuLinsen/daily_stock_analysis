import type React from 'react';
import { PanelRightOpen } from 'lucide-react';
import { Badge, Card, JsonViewer } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiLanguage, UiTextKey } from '../../i18n/uiText';
import type {
  DecisionSignalFeedbackItem,
  DecisionSignalFeedbackValue,
  DecisionSignalItem,
  DecisionSignalOutcomeItem,
  DecisionSignalOutcomeValue,
  DecisionSignalStatus,
} from '../../types/decisionSignals';
import {
  buildDecisionActionLabelMap,
  getDecisionActionLabel,
  getDecisionActionTone,
  type DecisionActionTone,
} from '../../utils/decisionAction';
import { cn } from '../../utils/cn';
import { parseDecisionSignalDate } from '../../utils/decisionSignalTime';
import {
  getDecisionSignalHorizonLabel,
  getDecisionSignalMarketLabel,
  getDecisionSignalMarketPhaseLabel,
  getDecisionSignalPlanQualityLabel,
} from '../../utils/decisionSignalLabels';

type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'history';

const STATUS_LABEL_KEYS: Record<DecisionSignalStatus, UiTextKey> = {
  active: 'decisionSignals.active',
  expired: 'decisionSignals.expired',
  invalidated: 'decisionSignals.invalidated',
  closed: 'decisionSignals.closed',
  archived: 'decisionSignals.archived',
};

const STATUS_VARIANTS: Record<DecisionSignalStatus, BadgeVariant> = {
  active: 'success',
  expired: 'warning',
  invalidated: 'danger',
  closed: 'default',
  archived: 'history',
};

const ACTION_VARIANTS: Record<DecisionActionTone, BadgeVariant> = {
  success: 'success',
  warning: 'warning',
  danger: 'danger',
  default: 'default',
};

const OUTCOME_VARIANTS: Record<DecisionSignalOutcomeValue, BadgeVariant> = {
  hit: 'success',
  miss: 'danger',
  neutral: 'warning',
};

const LOCALE_BY_LANGUAGE: Record<UiLanguage, string> = {
  zh: 'zh-CN',
  en: 'en-US',
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
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return Number(value).toFixed(2).replace(/\.?0+$/, '');
}

function formatPercent(value: number | null | undefined): string {
  const number = formatNumber(value);
  return number === '-' ? number : `${number}%`;
}

function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${formatNumber(normalized)}%`;
}

function formatEntryRange(item: DecisionSignalItem): string {
  const hasLow = item.entryLow !== null && item.entryLow !== undefined;
  const hasHigh = item.entryHigh !== null && item.entryHigh !== undefined;
  if (hasLow && hasHigh) {
    return item.entryLow === item.entryHigh
      ? formatNumber(item.entryLow)
      : `${formatNumber(item.entryLow)} - ${formatNumber(item.entryHigh)}`;
  }
  if (hasLow) return formatNumber(item.entryLow);
  if (hasHigh) return formatNumber(item.entryHigh);
  return '-';
}

function formatJsonish(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value.trim() || null;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function asJsonViewerData(value: unknown): Record<string, unknown> | unknown[] | null {
  if (Array.isArray(value)) return value;
  if (value && typeof value === 'object') return value as Record<string, unknown>;
  return null;
}

function getActionLabel(item: DecisionSignalItem, t: (key: UiTextKey) => string): string {
  return getDecisionActionLabel(
    item.action,
    item.actionLabel,
    null,
    t('decisionSignals.action'),
    buildDecisionActionLabelMap(t),
  ) ?? t('decisionSignals.action');
}

function getActionVariant(item: DecisionSignalItem): BadgeVariant {
  return ACTION_VARIANTS[getDecisionActionTone(item.action, item.actionLabel, null)];
}

function getOutcomeLabel(value: DecisionSignalOutcomeValue | null | undefined, t: (key: UiTextKey) => string): string {
  if (!value) return '-';
  const key = `decisionSignals.outcome.${value}` as UiTextKey;
  return t(key);
}

function getFeedbackLabel(value: DecisionSignalFeedbackValue | null | undefined, t: (key: UiTextKey) => string): string {
  if (!value) return t('decisionSignals.feedbackNone');
  const key = `decisionSignals.feedback.${value}` as UiTextKey;
  return t(key);
}

function hasDisplayValue(value: string): boolean {
  return value !== '-';
}

type SignalMetricTone = 'default' | 'success' | 'warning' | 'danger';

const metricToneClass: Record<SignalMetricTone, string> = {
  default: 'text-foreground',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
};

type SignalMetricProps = {
  label: string;
  value: string;
  tone?: SignalMetricTone;
};

const SignalMetric: React.FC<SignalMetricProps> = ({ label, value, tone = 'default' }) => (
  <div className="min-w-0 rounded-xl border border-border/60 bg-elevated/45 px-3 py-2">
    <p className="truncate text-[11px] text-muted-text">{label}</p>
    <p className={cn('mt-1 truncate text-sm font-semibold tabular-nums', metricToneClass[tone])}>{value}</p>
  </div>
);

type SignalTextTone = 'default' | 'warning' | 'danger' | 'info';

const textToneClass: Record<SignalTextTone, string> = {
  default: 'border-border/55 bg-elevated/35 text-secondary-text',
  warning: 'border-warning/25 bg-warning/10 text-warning',
  danger: 'border-danger/25 bg-danger/10 text-danger',
  info: 'border-cyan/25 bg-cyan/10 text-cyan',
};

type SignalTextBlockProps = {
  label: string;
  value?: string | null;
  tone?: SignalTextTone;
  clamp?: boolean;
};

const SignalTextBlock: React.FC<SignalTextBlockProps> = ({ label, value, tone = 'default', clamp = true }) => {
  const normalized = value?.trim();
  if (!normalized) return null;
  return (
    <div className={cn('rounded-xl border px-3 py-2.5', textToneClass[tone])}>
      <p className="text-[11px] font-medium text-current/80">{label}</p>
      <p className={cn('mt-1 text-sm leading-5 text-current', clamp ? 'line-clamp-2' : 'whitespace-pre-wrap')}>
        {normalized}
      </p>
    </div>
  );
};

type DecisionSignalCardProps = {
  item: DecisionSignalItem;
  onSelect?: (item: DecisionSignalItem) => void;
  selected?: boolean;
};

export const DecisionSignalCard: React.FC<DecisionSignalCardProps> = ({ item, onSelect, selected = false }) => {
  const { language, t } = useUiLanguage();
  const actionLabel = getActionLabel(item, t);
  const interactive = Boolean(onSelect);
  const entryRange = formatEntryRange(item);
  const pricePlanItems = [
    { label: t('decisionSignals.entryRange'), value: entryRange, tone: 'default' as const },
    { label: t('decisionSignals.stopLoss'), value: formatNumber(item.stopLoss), tone: 'danger' as const },
    { label: t('decisionSignals.targetPrice'), value: formatNumber(item.targetPrice), tone: 'success' as const },
  ].filter((entry) => hasDisplayValue(entry.value));
  const className = cn(
    'block w-full rounded-2xl border bg-card/75 p-4 text-left',
    interactive ? 'transition-colors hover:border-cyan/40 hover:bg-hover/70' : '',
    selected ? 'border-cyan/50 bg-cyan/10' : 'border-border/70',
  );
  const content = (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={getActionVariant(item)}>{actionLabel}</Badge>
            <Badge variant={STATUS_VARIANTS[item.status]}>{t(STATUS_LABEL_KEYS[item.status])}</Badge>
            <span className="font-mono text-sm text-secondary-text">{item.stockCode}</span>
          </div>
          <h3 className="mt-2 text-base font-semibold text-foreground">
            {item.stockName || item.stockCode}
          </h3>
        </div>
        <div className="text-right text-xs text-secondary-text">
          <div>{getDecisionSignalMarketLabel(item.market, t)}</div>
          <div className="mt-1">{formatDateTime(item.createdAt, language)}</div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2">
        <SignalMetric label={t('decisionSignals.score')} value={formatNumber(item.score)} />
        <SignalMetric label={t('decisionSignals.confidence')} value={formatConfidence(item.confidence)} />
        <SignalMetric label={t('decisionSignals.horizon')} value={getDecisionSignalHorizonLabel(item.horizon, t)} />
      </div>

      {pricePlanItems.length > 0 ? (
        <div className="mt-3 rounded-xl border border-border/60 bg-elevated/35 px-3 py-2.5">
          <div className="grid gap-2 sm:grid-cols-3">
            {pricePlanItems.map((entry) => (
              <div key={entry.label} className="min-w-0">
                <p className="truncate text-[11px] text-muted-text">{entry.label}</p>
                <p className={cn('mt-1 truncate text-sm font-semibold tabular-nums', metricToneClass[entry.tone])}>
                  {entry.value}
                </p>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-3 grid gap-2">
        <SignalTextBlock label={t('decisionSignals.reason')} value={item.reason} />
        <SignalTextBlock label={t('decisionSignals.catalystSummary')} value={item.catalystSummary} tone="info" />
        <SignalTextBlock label={t('decisionSignals.watchConditions')} value={item.watchConditions} />
        <SignalTextBlock label={t('decisionSignals.riskSummary')} value={item.riskSummary} tone="warning" />
        <SignalTextBlock label={t('decisionSignals.invalidation')} value={item.invalidation} tone="danger" />
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-text">
        <span>{t('decisionSignals.planQuality')}: {getDecisionSignalPlanQualityLabel(item.planQuality, t)}</span>
        <span>{t('decisionSignals.marketPhase')}: {getDecisionSignalMarketPhaseLabel(item.marketPhase, t)}</span>
        <span>{t('decisionSignals.expiresAt')}: {formatDateTime(item.expiresAt, language)}</span>
        {item.sourceReportId ? <span>{t('decisionSignals.sourceReport')}: #{item.sourceReportId}</span> : null}
      </div>
    </>
  );

  if (!interactive) {
    return <div className={className}>{content}</div>;
  }

  return (
    <div className={className}>
      {content}
      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={() => onSelect?.(item)}
          className="btn-secondary inline-flex items-center gap-1.5 !px-3 !py-1.5 !text-xs"
          aria-label={t('decisionSignals.viewDetailsFor', { stock: item.stockName || item.stockCode })}
        >
          <PanelRightOpen className="h-3.5 w-3.5" />
          {t('common.details')}
        </button>
      </div>
    </div>
  );
};

type DetailRowProps = {
  label: string;
  value?: React.ReactNode;
};

const DetailRow: React.FC<DetailRowProps> = ({ label, value }) => (
  <div className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-2">
    <p className="text-xs text-secondary-text">{label}</p>
    <div className="mt-1 text-sm text-foreground">{value || '-'}</div>
  </div>
);

type DecisionSignalDetailsProps = {
  item: DecisionSignalItem;
  actions?: React.ReactNode;
  outcomes?: DecisionSignalOutcomeItem[];
  outcomesLoading?: boolean;
  outcomesError?: string | null;
  feedback?: DecisionSignalFeedbackItem | null;
  feedbackLoading?: boolean;
  feedbackSaving?: boolean;
  feedbackError?: string | null;
  onFeedbackSubmit?: (value: DecisionSignalFeedbackValue) => void;
};

export const DecisionSignalDetails: React.FC<DecisionSignalDetailsProps> = ({
  item,
  actions,
  outcomes = [],
  outcomesLoading = false,
  outcomesError = null,
  feedback = null,
  feedbackLoading = false,
  feedbackSaving = false,
  feedbackError = null,
  onFeedbackSubmit,
}) => {
  const { language, t } = useUiLanguage();
  const actionLabel = getActionLabel(item, t);
  const entryRange = formatEntryRange(item);
  const evidenceData = asJsonViewerData(item.evidence);
  const qualityData = asJsonViewerData(item.dataQualitySummary);
  const metadataData = asJsonViewerData(item.metadata);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={getActionVariant(item)} size="md">{actionLabel}</Badge>
            <Badge variant={STATUS_VARIANTS[item.status]} size="md">{t(STATUS_LABEL_KEYS[item.status])}</Badge>
          </div>
          <h3 className="mt-3 text-xl font-semibold text-foreground">{item.stockName || item.stockCode}</h3>
          <p className="mt-1 font-mono text-sm text-secondary-text">{item.stockCode} · {getDecisionSignalMarketLabel(item.market, t)}</p>
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <DetailRow label={t('decisionSignals.score')} value={formatNumber(item.score)} />
        <DetailRow label={t('decisionSignals.confidence')} value={formatConfidence(item.confidence)} />
        <DetailRow label={t('decisionSignals.horizon')} value={getDecisionSignalHorizonLabel(item.horizon, t)} />
        <DetailRow label={t('decisionSignals.planQuality')} value={getDecisionSignalPlanQualityLabel(item.planQuality, t)} />
        <DetailRow label={t('decisionSignals.marketPhase')} value={getDecisionSignalMarketPhaseLabel(item.marketPhase, t)} />
        <DetailRow label={t('decisionSignals.sourceReport')} value={item.sourceReportId ? `#${item.sourceReportId}` : '-'} />
        <DetailRow label={t('decisionSignals.createdAt')} value={formatDateTime(item.createdAt, language)} />
        <DetailRow label={t('decisionSignals.expiresAt')} value={formatDateTime(item.expiresAt, language)} />
      </div>

      <Card title={t('decisionSignals.pricePlan')} padding="sm" className="rounded-xl">
        <div className="grid gap-3 sm:grid-cols-3">
          <DetailRow label={t('decisionSignals.entryRange')} value={entryRange} />
          <DetailRow label={t('decisionSignals.stopLoss')} value={formatNumber(item.stopLoss)} />
          <DetailRow label={t('decisionSignals.targetPrice')} value={formatNumber(item.targetPrice)} />
        </div>
      </Card>

      <Card padding="sm" className="rounded-xl">
        <div className="grid gap-3">
          <SignalTextBlock label={t('decisionSignals.reason')} value={formatJsonish(item.reason)} clamp={false} />
          <SignalTextBlock label={t('decisionSignals.catalystSummary')} value={formatJsonish(item.catalystSummary)} tone="info" clamp={false} />
          <SignalTextBlock label={t('decisionSignals.watchConditions')} value={formatJsonish(item.watchConditions)} clamp={false} />
          <SignalTextBlock label={t('decisionSignals.riskSummary')} value={formatJsonish(item.riskSummary)} tone="warning" clamp={false} />
          <SignalTextBlock label={t('decisionSignals.invalidation')} value={formatJsonish(item.invalidation)} tone="danger" clamp={false} />
        </div>
      </Card>

      <Card title={t('decisionSignals.outcomes')} padding="sm" className="rounded-xl">
        {outcomesLoading ? (
          <p className="text-sm text-secondary-text">{t('common.loading')}...</p>
        ) : outcomesError ? (
          <p className="text-sm text-danger">{outcomesError}</p>
        ) : outcomes.length === 0 ? (
          <p className="text-sm text-secondary-text">{t('decisionSignals.noOutcomes')}</p>
        ) : (
          <div className="grid gap-3">
            {outcomes.map((outcome) => (
              <div key={outcome.id} className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-foreground">{getDecisionSignalHorizonLabel(outcome.horizon, t)}</span>
                    {outcome.outcome ? (
                      <Badge variant={OUTCOME_VARIANTS[outcome.outcome]}>
                        {getOutcomeLabel(outcome.outcome, t)}
                      </Badge>
                    ) : (
                      <Badge variant="warning">{t('decisionSignals.outcome.unable')}</Badge>
                    )}
                  </div>
                  <span className="text-xs text-secondary-text">{outcome.engineVersion}</span>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                  <DetailRow label={t('decisionSignals.returnPct')} value={formatPercent(outcome.stockReturnPct)} />
                  <DetailRow label={t('decisionSignals.directionExpected')} value={outcome.directionExpected || '-'} />
                  <DetailRow label={t('decisionSignals.unableReason')} value={outcome.unableReason || '-'} />
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title={t('decisionSignals.feedbackTitle')} padding="sm" className="rounded-xl">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm text-foreground">
              {feedbackLoading ? `${t('common.loading')}...` : getFeedbackLabel(feedback?.feedbackValue, t)}
            </p>
            {feedback?.reasonCode ? (
              <p className="mt-1 text-xs text-secondary-text">{feedback.reasonCode}</p>
            ) : null}
            {feedbackError ? <p className="mt-2 text-sm text-danger">{feedbackError}</p> : null}
          </div>
          {onFeedbackSubmit ? (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-secondary !px-3 !py-1.5 !text-xs"
                disabled={feedbackSaving}
                onClick={() => onFeedbackSubmit('useful')}
              >
                {t('decisionSignals.feedback.useful')}
              </button>
              <button
                type="button"
                className="btn-secondary !px-3 !py-1.5 !text-xs"
                disabled={feedbackSaving}
                onClick={() => onFeedbackSubmit('not_useful')}
              >
                {t('decisionSignals.feedback.not_useful')}
              </button>
            </div>
          ) : null}
        </div>
      </Card>

      {evidenceData ? (
        <Card title={t('decisionSignals.evidence')} padding="sm" className="rounded-xl">
          <JsonViewer data={evidenceData} maxHeight="240px" />
        </Card>
      ) : null}
      {qualityData ? (
        <Card title={t('decisionSignals.dataQuality')} padding="sm" className="rounded-xl">
          <JsonViewer data={qualityData} maxHeight="240px" />
        </Card>
      ) : null}
      {metadataData ? (
        <Card title={t('decisionSignals.metadata')} padding="sm" className="rounded-xl">
          <JsonViewer data={metadataData} maxHeight="240px" />
        </Card>
      ) : null}
    </div>
  );
};

type PortfolioSignalSummaryProps = {
  item?: DecisionSignalItem;
  loading?: boolean;
};

export const PortfolioSignalSummary: React.FC<PortfolioSignalSummaryProps> = ({ item, loading = false }) => {
  const { t } = useUiLanguage();
  if (loading && !item) {
    return <span className="text-xs text-secondary-text">{t('decisionSignals.portfolioLoading')}</span>;
  }
  if (!item) {
    return <span className="text-xs text-muted-text">{t('decisionSignals.portfolioEmpty')}</span>;
  }
  const actionLabel = getActionLabel(item, t);
  return (
    <div className="min-w-[11rem] max-w-[18rem] text-left">
      <div className="flex flex-wrap items-center justify-end gap-1.5">
        <Badge variant={getActionVariant(item)}>{actionLabel}</Badge>
        {item.horizon ? <span className="text-[11px] text-secondary-text">{getDecisionSignalHorizonLabel(item.horizon, t)}</span> : null}
      </div>
      {item.riskSummary ? <p className="mt-1 line-clamp-2 text-[11px] text-warning">{item.riskSummary}</p> : null}
      {item.watchConditions ? <p className="mt-1 line-clamp-2 text-[11px] text-secondary-text">{item.watchConditions}</p> : null}
    </div>
  );
};
