import type React from 'react';
import { Clock, Database, GitBranch, MessageSquareText, Workflow } from 'lucide-react';
import { Badge, StatusDot } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { RunFlowSnapshot } from '../../types/runFlow';
import { compactText, formatDateTime, formatDuration, getRunFlowStatusLabel, RUN_FLOW_STATUS_STYLE } from './utils';

interface RunFlowSummaryBarProps {
  snapshot: RunFlowSnapshot;
}

export const RunFlowSummaryBar: React.FC<RunFlowSummaryBarProps> = ({ snapshot }) => {
  const { language, t } = useUiLanguage();
  const style = RUN_FLOW_STATUS_STYLE[snapshot.status] || RUN_FLOW_STATUS_STYLE.unknown;
  const title = snapshot.stockName || snapshot.stockCode || t('runFlow.valueUnavailable');
  const taskId = compactText(snapshot.taskId, 32);
  const traceId = compactText(snapshot.traceId || '', 32);

  const items = [
    {
      key: 'elapsed',
      icon: Clock,
      label: t('runFlow.summary.elapsed'),
      value: formatDuration(snapshot.summary.elapsedMs, t),
    },
    {
      key: 'fallback',
      icon: GitBranch,
      label: t('runFlow.summary.fallbackCount'),
      value: String(snapshot.summary.fallbackCount ?? 0),
    },
    {
      key: 'failed',
      icon: MessageSquareText,
      label: t('runFlow.summary.failedAttempts'),
      value: String(snapshot.summary.failedAttempts ?? 0),
    },
    {
      key: 'sources',
      icon: Database,
      label: t('runFlow.summary.dataSources'),
      value: String(snapshot.summary.dataSourceCount ?? 0),
    },
  ];

  return (
    <div className="home-subpanel p-3" data-testid="run-flow-summary">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Workflow className="h-4 w-4 shrink-0 text-cyan" aria-hidden="true" />
            <h3 className="truncate text-base font-semibold text-foreground">{title}</h3>
            <Badge variant={style.badge} className="gap-1.5 shadow-none">
              <StatusDot tone={style.tone} pulse={style.pulse} className="h-1.5 w-1.5" />
              {getRunFlowStatusLabel(snapshot.status, t)}
            </Badge>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-text">
            <span className="home-accent-chip px-2 py-0.5 font-mono">
              {t('runFlow.summary.task')}: {taskId || t('runFlow.valueUnavailable')}
            </span>
            {traceId ? (
              <span className="home-accent-chip px-2 py-0.5 font-mono">
                {t('runFlow.summary.trace')}: {traceId}
              </span>
            ) : null}
            {snapshot.summary.model ? (
              <span className="home-accent-chip px-2 py-0.5">
                {t('runFlow.summary.model')}: {compactText(snapshot.summary.model, 36)}
              </span>
            ) : null}
            <span className="home-accent-chip px-2 py-0.5">
              {t('runFlow.summary.generatedAt')}: {formatDateTime(snapshot.generatedAt, language, t)}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:min-w-[28rem]">
          {items.map(({ key, icon: Icon, label, value }) => (
            <div key={key} className="rounded-lg border border-subtle bg-surface/40 px-3 py-2">
              <div className="flex items-center gap-1.5 text-xs text-muted-text">
                <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span className="truncate">{label}</span>
              </div>
              <p className="mt-1 text-sm font-semibold text-foreground tabular-nums">{value}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
