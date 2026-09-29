import type React from 'react';
import { Activity } from 'lucide-react';
import { Badge, Card, EmptyState, Loading } from '../common';
import type { AlertTriggerItem } from '../../types/alerts';
import { formatDateTime } from '../../utils/format';
import { getMarketPhaseSummaryLabel } from '../../utils/marketPhase';

const statusLabel: Record<string, string> = {
  triggered: '已触发',
  skipped: '已跳过',
  degraded: '降级',
  failed: '失败',
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

function renderPhaseQuality(trigger: AlertTriggerItem): React.ReactNode {
  const phase = getMarketPhaseSummaryLabel(trigger.marketPhaseSummary, 'zh');
  const quality = trigger.analysisContextPackOverview?.dataQuality?.level;
  const limitations = trigger.analysisContextPackOverview?.dataQuality?.limitations?.slice(0, 2) ?? [];
  if (!phase && !quality && limitations.length === 0) {
    return <span className="text-xs text-muted-text">--</span>;
  }
  return (
    <div className="space-y-1">
      {phase ? <Badge variant="default">{phase.replace('市场阶段: ', '').replace('市场阶段：', '')}</Badge> : null}
      {quality ? <div className="text-xs text-secondary-text">质量：{quality}</div> : null}
      {limitations.length ? (
        <div className="max-w-[180px] text-xs text-muted-text">{limitations.join('；')}</div>
      ) : null}
    </div>
  );
}

interface AlertTriggerHistoryProps {
  triggers: AlertTriggerItem[];
  isLoading?: boolean;
}

export const AlertTriggerHistory: React.FC<AlertTriggerHistoryProps> = ({ triggers, isLoading = false }) => {
  return (
    <Card title="触发历史" subtitle="评估记录" variant="bordered" padding="md">
      {isLoading ? <Loading label="正在加载触发历史" /> : null}
      {!isLoading && triggers.length === 0 ? (
        <EmptyState
          icon={<Activity className="h-6 w-6" />}
          title="暂无触发历史"
          description="后台评估会记录 triggered、skipped、degraded 和 failed 状态；正常未触发不会写入历史。"
        />
      ) : null}
      {!isLoading && triggers.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead className="border-b border-border/60 text-xs uppercase text-muted-text">
              <tr>
                <th className="px-3 py-2 font-medium">状态</th>
                <th className="px-3 py-2 font-medium">阶段 / 质量</th>
                <th className="px-3 py-2 font-medium">目标</th>
                <th className="px-3 py-2 font-medium">观察值</th>
                <th className="px-3 py-2 font-medium">阈值</th>
                <th className="px-3 py-2 font-medium">数据源</th>
                <th className="px-3 py-2 font-medium">数据时间</th>
                <th className="px-3 py-2 font-medium">原因</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {triggers.map((trigger) => (
                <tr key={trigger.id} className="align-top">
                  <td className="px-3 py-3">
                    <Badge variant={statusVariant(trigger.status)}>
                      {statusLabel[trigger.status] ?? trigger.status}
                    </Badge>
                  </td>
                  <td className="px-3 py-3">{renderPhaseQuality(trigger)}</td>
                  <td className="px-3 py-3 font-mono text-secondary-text">{trigger.target}</td>
                  <td className="px-3 py-3 text-secondary-text">{formatNullable(trigger.observedValue)}</td>
                  <td className="px-3 py-3 text-secondary-text">{formatNullable(trigger.threshold)}</td>
                  <td className="px-3 py-3 text-secondary-text">{formatNullable(trigger.dataSource)}</td>
                  <td className="px-3 py-3 text-xs text-secondary-text">
                    {formatDateTime(trigger.dataTimestamp ?? trigger.triggeredAt)}
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
