import type React from 'react';
import { ChevronDown, ChevronRight, Info, X } from 'lucide-react';
import { Badge, Button, StatusDot } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { RunFlowNode, RunFlowStatus } from '../../types/runFlow';
import {
  formatDateTime,
  formatDuration,
  formatMetadataValue,
  getRunFlowNodeKindLabel,
  getRunFlowStatusLabel,
  RUN_FLOW_STATUS_STYLE,
} from './utils';

interface RunFlowNodeDetailsProps {
  node?: RunFlowNode | null;
  isExpanded?: boolean;
  onToggleExpanded?: (nodeId: string) => void;
  onClose?: () => void;
}

interface DetailItem {
  id?: string;
  label?: string;
  provider?: string | null;
  status?: string;
  durationMs?: number | null;
  recordCount?: number | null;
  startedAt?: string | null;
  endedAt?: string | null;
  message?: string | null;
}

const ALWAYS_HIDDEN_METADATA_KEYS = new Set([
  'attempts',
  'context_blocks',
  'topologyGroup',
  'expanded',
  'counts',
  'dataQuality',
  'packVersion',
]);
const TOPOLOGY_SUMMARY_METADATA_KEYS = new Set([
  'data_type',
  'dataType',
  'provider_chain',
  'providerChain',
  'success_count',
  'successCount',
  'failed_count',
  'failedCount',
  'fallback_count',
  'fallbackCount',
  'retry_count',
  'retryCount',
  'context_status_counts',
  'contextStatusCounts',
]);

type DetailRow = [string, string];

interface DataQualityMetadata {
  overallScore?: number;
  level?: string;
  blockScores?: Record<string, number>;
}

const readDetailItems = (node: RunFlowNode, key: string): DetailItem[] => {
  const value = node.metadata?.[key];
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is DetailItem => Boolean(item) && typeof item === 'object');
};

const readNumberRecord = (value: unknown): Record<string, number> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.entries(value as Record<string, unknown>).reduce<Record<string, number>>((items, [key, item]) => {
    if (typeof item === 'number' && Number.isFinite(item)) {
      items[key] = item;
    }
    return items;
  }, {});
};

const readDataQuality = (value: unknown): DataQualityMetadata | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  return {
    overallScore: typeof raw.overallScore === 'number' ? raw.overallScore : undefined,
    level: typeof raw.level === 'string' ? raw.level : undefined,
    blockScores: readNumberRecord(raw.blockScores),
  };
};

const shouldHideMetadataKey = (node: RunFlowNode, key: string): boolean => (
  ALWAYS_HIDDEN_METADATA_KEYS.has(key)
  || (Boolean(node.metadata?.topologyGroup) && TOPOLOGY_SUMMARY_METADATA_KEYS.has(key))
);

const isRunFlowStatus = (value: unknown): value is RunFlowStatus => (
  typeof value === 'string' && value in RUN_FLOW_STATUS_STYLE
);

const hasFiniteNumber = (value: unknown): value is number => (
  typeof value === 'number' && Number.isFinite(value)
);

const isContextPackNode = (node: RunFlowNode): boolean => (
  node.id === 'context_pack' || node.metadata?.topologyGroup === 'context_pack'
);

export const RunFlowNodeDetails: React.FC<RunFlowNodeDetailsProps> = ({
  node,
  isExpanded = false,
  onToggleExpanded,
  onClose,
}) => {
  const { language, t } = useUiLanguage();

  if (!node) {
    return (
      <aside className="home-subpanel p-4 text-sm text-secondary-text" data-testid="run-flow-node-details-empty">
        <div className="flex items-center gap-2">
          <Info className="h-4 w-4 text-cyan" aria-hidden="true" />
          {t('runFlow.nodeDetails.empty')}
        </div>
      </aside>
    );
  }

  const style = RUN_FLOW_STATUS_STYLE[node.status] || RUN_FLOW_STATUS_STYLE.unknown;
  const metadata = Object.entries(node.metadata || {}).filter(([key, value]) => (
    !shouldHideMetadataKey(node, key)
    && value !== null
    && value !== undefined
    && value !== ''
  ));
  const attempts = readDetailItems(node, 'attempts');
  const contextBlocks = readDetailItems(node, 'context_blocks');
  const contextCounts = readNumberRecord(node.metadata?.counts || node.metadata?.context_status_counts);
  const contextStatusCounts = readNumberRecord(node.metadata?.context_status_counts);
  const dataQuality = readDataQuality(node.metadata?.dataQuality);
  const blockScores = dataQuality?.blockScores || {};
  const canToggleExpanded = node.metadata?.topologyGroup === 'provider_attempts' && Boolean(onToggleExpanded);
  const formatDetailStatus = (status: string | undefined) => (
    isRunFlowStatus(status) ? getRunFlowStatusLabel(status, t) : status || t('runFlow.valueUnavailable')
  );
  const detailRows: DetailRow[] = [[t('runFlow.nodeDetails.kind'), getRunFlowNodeKindLabel(node.kind, t)]];
  const addProviderRow = () => {
    if (node.provider) {
      detailRows.push([t('runFlow.nodeDetails.provider'), node.provider]);
    }
  };
  const addDurationRow = () => {
    if (hasFiniteNumber(node.durationMs)) {
      detailRows.push([t('runFlow.nodeDetails.duration'), formatDuration(node.durationMs, t)]);
    }
  };
  const addAttemptRow = () => {
    if (hasFiniteNumber(node.attempts)) {
      detailRows.push([t('runFlow.nodeDetails.attempts'), String(node.attempts)]);
    }
  };
  const addRecordRow = () => {
    if (hasFiniteNumber(node.recordCount)) {
      detailRows.push([t('runFlow.nodeDetails.recordCount'), String(node.recordCount)]);
    }
  };
  const addTimeRows = () => {
    if (node.startedAt) {
      detailRows.push([t('runFlow.nodeDetails.startedAt'), formatDateTime(node.startedAt, language, t)]);
    }
    if (node.endedAt) {
      detailRows.push([t('runFlow.nodeDetails.endedAt'), formatDateTime(node.endedAt, language, t)]);
    }
  };

  if (isContextPackNode(node)) {
    if (typeof node.metadata?.packVersion === 'string') {
      detailRows.push([t('runFlow.nodeDetails.version'), node.metadata.packVersion]);
    }
    addTimeRows();
  } else if (node.kind === 'entry' || node.kind === 'queue') {
    addTimeRows();
  } else if (node.kind === 'data_source') {
    addProviderRow();
    addDurationRow();
    addAttemptRow();
    addRecordRow();
    addTimeRows();
  } else if (node.kind === 'analysis' || node.kind === 'model') {
    addProviderRow();
    addDurationRow();
    addAttemptRow();
    addRecordRow();
    addTimeRows();
  } else {
    addDurationRow();
    addAttemptRow();
    addRecordRow();
    addTimeRows();
  }

  return (
    <aside className="home-subpanel p-4" data-testid="run-flow-node-details">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="label-uppercase">{t('runFlow.nodeDetails.title')}</p>
          <h3 className="mt-1 truncate text-base font-semibold text-foreground">{node.label}</h3>
          {node.message ? (
            <p className="mt-2 text-sm leading-6 text-secondary-text">{node.message}</p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {canToggleExpanded ? (
            <Button
              type="button"
              variant="secondary"
              size="xsm"
              onClick={() => onToggleExpanded?.(node.id)}
              aria-expanded={isExpanded}
              className="h-7 px-2"
            >
              {isExpanded ? (
                <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              {isExpanded ? t('runFlow.nodeDetails.collapseAttempts') : t('runFlow.nodeDetails.expandAttempts')}
            </Button>
          ) : null}
          <Badge variant={style.badge} className="gap-1.5 shadow-none">
            <StatusDot tone={style.tone} pulse={style.pulse} className="h-1.5 w-1.5" />
            {getRunFlowStatusLabel(node.status, t)}
          </Badge>
          {onClose ? (
            <Button
              type="button"
              variant="ghost"
              size="xsm"
              onClick={onClose}
              aria-label={t('runFlow.nodeDetails.close')}
              className="h-7 w-7 px-0"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
          ) : null}
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
        {detailRows.map(([label, value]) => (
          <div key={label} className="rounded-lg border border-subtle bg-base/35 px-3 py-2">
            <dt className="text-xs text-muted-text">{label}</dt>
            <dd className="mt-1 break-words text-foreground">{value}</dd>
          </div>
        ))}
      </dl>

      {attempts.length > 0 ? (
        <div className="mt-4">
          <p className="label-uppercase">{t('runFlow.nodeDetails.attemptList')}</p>
          <div className="mt-2 overflow-x-auto rounded-lg border border-subtle">
            <table className="min-w-full divide-y divide-subtle text-left text-xs">
              <thead className="bg-base/45 text-muted-text">
                <tr>
                  <th className="px-3 py-2 font-medium">{t('runFlow.nodeDetails.column.name')}</th>
                  <th className="px-3 py-2 font-medium">{t('runFlow.nodeDetails.column.status')}</th>
                  <th className="px-3 py-2 font-medium">{t('runFlow.nodeDetails.column.duration')}</th>
                  <th className="px-3 py-2 font-medium">{t('runFlow.nodeDetails.column.records')}</th>
                  <th className="px-3 py-2 font-medium">{t('runFlow.nodeDetails.column.time')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-subtle bg-base/20">
                {attempts.map((attempt, index) => (
                  <tr key={attempt.id || `${attempt.label}-${index}`}>
                    <td className="px-3 py-2 text-foreground">
                      <span className="block font-medium">{attempt.label || attempt.provider || t('runFlow.valueUnavailable')}</span>
                      {attempt.provider ? <span className="mt-0.5 block text-muted-text">{attempt.provider}</span> : null}
                    </td>
                    <td className="px-3 py-2 text-secondary-text">{formatDetailStatus(attempt.status)}</td>
                    <td className="px-3 py-2 text-secondary-text">{formatDuration(attempt.durationMs, t)}</td>
                    <td className="px-3 py-2 text-secondary-text">
                      {typeof attempt.recordCount === 'number' ? attempt.recordCount : t('runFlow.valueUnavailable')}
                    </td>
                    <td className="px-3 py-2 text-secondary-text">{formatDateTime(attempt.startedAt, language, t)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {contextBlocks.length > 0 ? (
        <div className="mt-4">
          <p className="label-uppercase">{t('runFlow.nodeDetails.contextBlocks')}</p>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {contextBlocks.map((block, index) => (
              <div key={block.id || `${block.label}-${index}`} className="rounded-lg border border-subtle bg-base/35 px-3 py-2 text-sm">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-foreground">{block.label || t('runFlow.valueUnavailable')}</p>
                    {block.provider ? <p className="mt-0.5 truncate text-xs text-muted-text">{block.provider}</p> : null}
                  </div>
                  <span className="shrink-0 text-xs text-secondary-text">{formatDetailStatus(block.status)}</span>
                </div>
                {block.message ? <p className="mt-2 text-xs leading-5 text-secondary-text">{block.message}</p> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {(dataQuality || Object.keys(contextCounts).length > 0 || Object.keys(contextStatusCounts).length > 0) ? (
        <div className="mt-4">
          <p className="label-uppercase">{t('runFlow.nodeDetails.contextQuality')}</p>
          <dl className="mt-2 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            {typeof dataQuality?.overallScore === 'number' ? (
              <div className="rounded-lg border border-subtle bg-base/35 px-3 py-2">
                <dt className="text-xs text-muted-text">{t('runFlow.nodeDetails.overallScore')}</dt>
                <dd className="mt-1 text-foreground">{dataQuality.overallScore}</dd>
              </div>
            ) : null}
            {dataQuality?.level ? (
              <div className="rounded-lg border border-subtle bg-base/35 px-3 py-2">
                <dt className="text-xs text-muted-text">{t('runFlow.nodeDetails.qualityLevel')}</dt>
                <dd className="mt-1 text-foreground">{dataQuality.level}</dd>
              </div>
            ) : null}
            {[
              ['available', 'success', t('runFlow.nodeDetails.count.available')],
              ['missing', null, t('runFlow.nodeDetails.count.missing')],
              ['partial', null, t('runFlow.nodeDetails.count.partial')],
              ['degraded', null, t('runFlow.nodeDetails.count.degraded')],
              ['fallback', null, t('runFlow.nodeDetails.count.fallback')],
              ['skipped', null, t('runFlow.nodeDetails.count.skipped')],
            ].map(([key, statusKey, label]) => {
              const count = contextCounts[key || ''] ?? (statusKey ? contextStatusCounts[statusKey] : contextStatusCounts[key || '']);
              if (typeof count !== 'number') return null;
              return (
                <div key={key} className="rounded-lg border border-subtle bg-base/35 px-3 py-2">
                  <dt className="text-xs text-muted-text">{label}</dt>
                  <dd className="mt-1 text-foreground">{count}</dd>
                </div>
              );
            })}
          </dl>

          {Object.keys(blockScores).length > 0 ? (
            <div className="mt-3">
              <p className="text-xs font-medium text-muted-text">{t('runFlow.nodeDetails.blockScores')}</p>
              <dl className="mt-2 grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
                {Object.entries(blockScores).map(([key, score]) => (
                  <div key={key} className="rounded-lg border border-subtle bg-base/35 px-3 py-2">
                    <dt className="font-mono text-xs text-muted-text">{key}</dt>
                    <dd className="mt-1 text-foreground">{score}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : null}
        </div>
      ) : null}

      {metadata.length > 0 ? (
        <div className="mt-4">
          <p className="label-uppercase">{t('runFlow.nodeDetails.metadata')}</p>
          <dl className="mt-2 grid grid-cols-1 gap-2 text-sm">
            {metadata.map(([key, value]) => (
              <div key={key} className="rounded-lg border border-subtle bg-base/35 px-3 py-2">
                <dt className="font-mono text-xs text-muted-text">{key}</dt>
                <dd className="mt-1 break-words text-foreground">{formatMetadataValue(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
    </aside>
  );
};
