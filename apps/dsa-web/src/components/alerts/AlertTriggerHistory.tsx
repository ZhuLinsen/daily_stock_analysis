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
  headers: string[];
  status: Record<string, string>;
  quality: string;
  qualityLevels: Record<string, string>;
}> = {
  ko: {
    title: '트리거 이력', subtitle: '평가 기록', loading: '트리거 이력 불러오는 중',
    emptyTitle: '트리거 이력 없음',
    emptyDescription: '백그라운드 평가는 triggered, skipped, degraded, failed 상태를 기록합니다. 정상적으로 조건을 충족하지 않은 경우에는 이력을 만들지 않습니다.',
    headers: ['상태', '단계 / 품질', '대상', '관측값', '임계값', '데이터 소스', '데이터 시각', '사유'],
    status: { triggered: '트리거됨', skipped: '건너뜀', degraded: '강등', failed: '실패' },
    quality: '품질', qualityLevels: { good: '양호', usable: '사용 가능', limited: '제한적', poor: '미흡' },
  },
  en: {
    title: 'Trigger history', subtitle: 'Evaluation records', loading: 'Loading trigger history',
    emptyTitle: 'No trigger history',
    emptyDescription: 'Background evaluations record triggered, skipped, degraded, and failed states. Normal non-triggers are not recorded.',
    headers: ['Status', 'Phase / quality', 'Target', 'Observed', 'Threshold', 'Data source', 'Data time', 'Reason'],
    status: { triggered: 'Triggered', skipped: 'Skipped', degraded: 'Degraded', failed: 'Failed' },
    quality: 'Quality', qualityLevels: { good: 'Good', usable: 'Usable', limited: 'Limited', poor: 'Poor' },
  },
  zh: {
    title: '触发历史', subtitle: '评估记录', loading: '正在加载触发历史',
    emptyTitle: '暂无触发历史',
    emptyDescription: '后台评估会记录 triggered、skipped、degraded 和 failed 状态；正常未触发不会写入历史。',
    headers: ['状态', '阶段 / 质量', '目标', '观察值', '阈值', '数据源', '数据时间', '原因'],
    status: { triggered: '已触发', skipped: '已跳过', degraded: '降级', failed: '失败' },
    quality: '质量', qualityLevels: { good: '良好', usable: '可用', limited: '受限', poor: '较差' },
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
      {phase ? <Badge variant="default">{phase.replace(/^(市场阶段|Market phase|시장 단계)[:：]\s*/, '')}</Badge> : null}
      {quality ? <div className="text-xs text-secondary-text">{text.quality}: {text.qualityLevels[quality] ?? quality}</div> : null}
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
                {text.headers.map((header) => <th className="px-3 py-2 font-medium" key={header}>{header}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {triggers.map((trigger) => (
                <tr key={trigger.id} className="align-top">
                  <td className="px-3 py-3">
                    <Badge variant={statusVariant(trigger.status)}>
                      {text.status[trigger.status] ?? trigger.status}
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
