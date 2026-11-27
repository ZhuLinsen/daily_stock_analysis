import type React from 'react';
import { Activity } from 'lucide-react';
import { Badge, Card, EmptyState, Loading } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiLanguage } from '../../i18n/uiText';
import type { AlertTriggerItem } from '../../types/alerts';
import { formatDateTime } from '../../utils/format';
import { getMarketPhaseSummaryLabel } from '../../utils/marketPhase';

const TEXT: Record<UiLanguage, {
  title: string;
  subtitle: string;
  loading: string;
  emptyTitle: string;
  emptyDescription: string;
  qualityPrefix: string;
  limitationSeparator: string;
  headers: {
    status: string;
    phaseQuality: string;
    target: string;
    observed: string;
    threshold: string;
    dataSource: string;
    dataTime: string;
    reason: string;
  };
  statusLabels: Record<string, string>;
}> = {
  zh: {
    title: '触发历史',
    subtitle: '评估记录',
    loading: '正在加载触发历史',
    emptyTitle: '暂无触发历史',
    emptyDescription: '后台评估会记录 triggered、skipped、degraded 和 failed 状态；正常未触发不会写入历史。',
    qualityPrefix: '质量：',
    limitationSeparator: '；',
    headers: {
      status: '状态',
      phaseQuality: '阶段 / 质量',
      target: '目标',
      observed: '观察值',
      threshold: '阈值',
      dataSource: '数据源',
      dataTime: '数据时间',
      reason: '原因',
    },
    statusLabels: {
      triggered: '已触发',
      skipped: '已跳过',
      degraded: '降级',
      failed: '失败',
    },
  },
  en: {
    title: 'Trigger history',
    subtitle: 'Evaluation records',
    loading: 'Loading trigger history',
    emptyTitle: 'No trigger history yet',
    emptyDescription: 'Background evaluations record triggered, skipped, degraded, and failed statuses; normal non-triggered checks are not written to history.',
    qualityPrefix: 'Quality: ',
    limitationSeparator: '; ',
    headers: {
      status: 'Status',
      phaseQuality: 'Phase / Quality',
      target: 'Target',
      observed: 'Observed',
      threshold: 'Threshold',
      dataSource: 'Data source',
      dataTime: 'Data time',
      reason: 'Reason',
    },
    statusLabels: {
      triggered: 'Triggered',
      skipped: 'Skipped',
      degraded: 'Degraded',
      failed: 'Failed',
    },
  },
};

function statusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'triggered') return 'success';
  if (status === 'skipped' || status === 'degraded') return 'warning';
  if (status === 'failed') return 'danger';
  return 'default';
}

function formatNullable(value?: string | number | null): string {
  if (value === null || value === undefined || value === '') return '--';
  return String(value);
}

function renderPhaseQuality(trigger: AlertTriggerItem, language: UiLanguage): React.ReactNode {
  const text = TEXT[language];
  const phase = getMarketPhaseSummaryLabel(trigger.marketPhaseSummary, language);
  const quality = trigger.analysisContextPackOverview?.dataQuality?.level;
  const limitations = trigger.analysisContextPackOverview?.dataQuality?.limitations?.slice(0, 2) ?? [];
  if (!phase && !quality && limitations.length === 0) {
    return <span className="text-xs text-muted-text">--</span>;
  }
  return (
    <div className="space-y-1">
      {phase ? (
        <Badge variant="default">
          {phase.replace(/^市场阶段[:：]\s*/, '').replace(/^Market phase:\s*/i, '')}
        </Badge>
      ) : null}
      {quality ? <div className="text-xs text-secondary-text">{text.qualityPrefix}{quality}</div> : null}
      {limitations.length ? (
        <div className="max-w-[180px] text-xs text-muted-text">{limitations.join(text.limitationSeparator)}</div>
      ) : null}
    </div>
  );
}

interface AlertTriggerHistoryProps {
  triggers: AlertTriggerItem[];
  isLoading?: boolean;
}

export const AlertTriggerHistory: React.FC<AlertTriggerHistoryProps> = ({ triggers, isLoading = false }) => {
  const { language } = useUiLanguage();
  const text = TEXT[language];

  return (
    <Card title={text.title} subtitle={text.subtitle} variant="bordered" padding="md">
      {isLoading ? <Loading label={text.loading} /> : null}
      {!isLoading && triggers.length === 0 ? (
        <EmptyState
          icon={<Activity className="h-6 w-6" />}
          title={text.emptyTitle}
          description={text.emptyDescription}
        />
      ) : null}
      {!isLoading && triggers.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead className="border-b border-border/60 text-xs uppercase text-muted-text">
              <tr>
                <th className="px-3 py-2 font-medium">{text.headers.status}</th>
                <th className="px-3 py-2 font-medium">{text.headers.phaseQuality}</th>
                <th className="px-3 py-2 font-medium">{text.headers.target}</th>
                <th className="px-3 py-2 font-medium">{text.headers.observed}</th>
                <th className="px-3 py-2 font-medium">{text.headers.threshold}</th>
                <th className="px-3 py-2 font-medium">{text.headers.dataSource}</th>
                <th className="px-3 py-2 font-medium">{text.headers.dataTime}</th>
                <th className="px-3 py-2 font-medium">{text.headers.reason}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {triggers.map((trigger) => (
                <tr key={trigger.id} className="align-top">
                  <td className="px-3 py-3">
                    <Badge variant={statusVariant(trigger.status)}>
                      {Object.hasOwn(text.statusLabels, trigger.status)
                        ? text.statusLabels[trigger.status]
                        : trigger.status}
                    </Badge>
                  </td>
                  <td className="px-3 py-3">{renderPhaseQuality(trigger, language)}</td>
                  <td className="px-3 py-3 font-mono text-secondary-text">{trigger.target}</td>
                  <td className="px-3 py-3 text-secondary-text">{formatNullable(trigger.observedValue)}</td>
                  <td className="px-3 py-3 text-secondary-text">{formatNullable(trigger.threshold)}</td>
                  <td className="px-3 py-3 text-secondary-text">{formatNullable(trigger.dataSource)}</td>
                  <td className="px-3 py-3 text-xs text-secondary-text">
                    {formatDateTime(trigger.dataTimestamp ?? trigger.triggeredAt, language)}
                  </td>
                  <td className="px-3 py-3 text-secondary-text">
                    {trigger.reason || trigger.diagnostics || '--'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </Card>
  );
};
