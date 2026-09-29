import type React from 'react';
import { useMemo, useState } from 'react';
import { AlertTriangle, Filter, GitBranch, ListFilter, OctagonAlert, XCircle } from 'lucide-react';
import { Badge, Button, StatusDot } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import type { RunFlowEvent } from '../../types/runFlow';
import {
  compactText,
  formatDateTime,
  formatMetadataValue,
  getRunFlowSeverityLabel,
  RUN_FLOW_SEVERITY_STYLE,
} from './utils';

interface RunFlowEventListProps {
  events: RunFlowEvent[];
  selectedNodeId?: string | null;
  onSelectNode?: (nodeId: string) => void;
}

type EventFilter = 'all' | 'important' | 'problems' | 'fallback' | 'cancelled';

const FILTER_ICONS = {
  all: ListFilter,
  important: AlertTriangle,
  problems: OctagonAlert,
  fallback: GitBranch,
  cancelled: XCircle,
} as const;

const eventText = (event: RunFlowEvent): string =>
  `${event.type} ${event.title} ${event.message || ''}`.toLowerCase();

const matchesFilter = (event: RunFlowEvent, filter: EventFilter): boolean => {
  if (filter === 'all') return true;
  const text = eventText(event);
  if (filter === 'important') {
    return event.severity === 'warning'
      || event.severity === 'danger'
      || /fallback|retry|cancel|failed|error|timeout/.test(text);
  }
  if (filter === 'problems') {
    return event.severity === 'warning'
      || event.severity === 'danger'
      || /failed|error|timeout/.test(text);
  }
  if (filter === 'fallback') {
    return /fallback|retry|降级|重试/.test(text);
  }
  return /cancel|取消/.test(text);
};

export const RunFlowEventList: React.FC<RunFlowEventListProps> = ({
  events,
  selectedNodeId,
  onSelectNode,
}) => {
  const { language, t } = useUiLanguage();
  const [filter, setFilter] = useState<EventFilter>('all');
  const sortedEvents = useMemo(() => (
    [...events].sort((left, right) => {
      const leftTime = left.timestamp ? Date.parse(left.timestamp) : 0;
      const rightTime = right.timestamp ? Date.parse(right.timestamp) : 0;
      return leftTime - rightTime;
    })
  ), [events]);
  const visibleEvents = useMemo(
    () => sortedEvents.filter((event) => matchesFilter(event, filter)),
    [filter, sortedEvents],
  );
  const filters: EventFilter[] = ['all', 'important', 'problems', 'fallback', 'cancelled'];

  return (
    <div className="home-subpanel flex min-h-0 flex-col overflow-hidden p-3" data-testid="run-flow-events">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="label-uppercase">{t('runFlow.events.title')}</p>
          <p className="mt-1 text-xs text-muted-text">
            {t('runFlow.events.count', { count: visibleEvents.length })}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5" aria-label={t('runFlow.events.filters')}>
          {filters.map((item) => {
            const Icon = FILTER_ICONS[item];
            return (
              <Button
                key={item}
                type="button"
                variant={filter === item ? 'outline' : 'ghost'}
                size="xsm"
                onClick={() => setFilter(item)}
                aria-pressed={filter === item}
                className="h-7 px-2 text-xs"
              >
                <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                {t(`runFlow.events.filter.${item}` as UiTextKey)}
              </Button>
            );
          })}
        </div>
      </div>

      <div className="mt-3 min-h-0 space-y-2 overflow-y-auto pr-1">
        {visibleEvents.length > 0 ? visibleEvents.map((event) => {
          const style = RUN_FLOW_SEVERITY_STYLE[event.severity] || RUN_FLOW_SEVERITY_STYLE.info;
          const selected = Boolean(event.nodeId && event.nodeId === selectedNodeId);
          const metadata = Object.entries(event.metadata || {})
            .filter(([, value]) => value !== null && value !== undefined && value !== '')
            .slice(0, 3);
          const content = (
            <div
              className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                selected ? 'border-primary/70 bg-primary/10' : 'border-subtle bg-base/30 hover:bg-hover/60'
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={style.badge} className="gap-1.5 shadow-none">
                  <StatusDot tone={style.tone} className="h-1.5 w-1.5" />
                  {getRunFlowSeverityLabel(event.severity, t)}
                </Badge>
                <span className="text-xs text-muted-text">
                  {formatDateTime(event.timestamp, language, t)}
                </span>
                <span className="font-mono text-[11px] text-muted-text">{compactText(event.type, 28)}</span>
              </div>
              <p className="mt-2 text-sm font-medium text-foreground">{event.title}</p>
              {event.message ? (
                <p className="mt-1 text-xs leading-5 text-secondary-text">{event.message}</p>
              ) : null}
              {metadata.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {metadata.map(([key, value]) => (
                    <span key={key} className="home-accent-chip px-2 py-0.5 text-[11px] text-muted-text">
                      {key}: {formatMetadataValue(value)}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          );

          if (!event.nodeId || !onSelectNode) {
            return <div key={event.id}>{content}</div>;
          }

          return (
            <button
              key={event.id}
              type="button"
              className="block w-full"
              onClick={() => onSelectNode(event.nodeId || '')}
              aria-label={t('runFlow.events.openNode', { title: event.title })}
            >
              {content}
            </button>
          );
        }) : (
          <div className="flex min-h-32 flex-col items-center justify-center rounded-lg border border-dashed border-subtle px-4 py-8 text-center text-sm text-secondary-text">
            <Filter className="mb-2 h-5 w-5 text-muted-text" aria-hidden="true" />
            {t('runFlow.events.empty')}
          </div>
        )}
      </div>
    </div>
  );
};
