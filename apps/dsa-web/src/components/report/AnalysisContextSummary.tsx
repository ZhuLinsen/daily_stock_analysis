import type React from 'react';
import { ChevronDown, Database } from 'lucide-react';
import type {
  AnalysisContextPackBlockStatus,
  AnalysisContextPackOverview,
  ReportLanguage,
} from '../../types/analysis';
import { normalizeReportLanguage } from '../../utils/reportLanguage';
import { Badge, Card, StatusDot } from '../common';
import { DashboardPanelHeader } from '../dashboard';

interface AnalysisContextSummaryProps {
  overview?: AnalysisContextPackOverview | null;
  language?: ReportLanguage;
}

type BadgeVariant = NonNullable<React.ComponentProps<typeof Badge>['variant']>;
type StatusTone = NonNullable<React.ComponentProps<typeof StatusDot>['tone']>;

const STATUS_STYLE: Record<AnalysisContextPackBlockStatus, { variant: BadgeVariant; tone: StatusTone }> = {
  available: { variant: 'success', tone: 'success' },
  missing: { variant: 'danger', tone: 'danger' },
  not_supported: { variant: 'default', tone: 'neutral' },
  fallback: { variant: 'warning', tone: 'warning' },
  stale: { variant: 'warning', tone: 'warning' },
  estimated: { variant: 'info', tone: 'info' },
  partial: { variant: 'warning', tone: 'warning' },
  fetch_failed: { variant: 'danger', tone: 'danger' },
};

const QUALITY_STYLE = {
  good: { variant: 'success', tone: 'success' },
  usable: { variant: 'info', tone: 'info' },
  limited: { variant: 'warning', tone: 'warning' },
  poor: { variant: 'danger', tone: 'danger' },
} as const satisfies Record<string, { variant: BadgeVariant; tone: StatusTone }>;

const BLOCK_LABELS: Record<ReportLanguage, Record<string, string>> = {
  zh: {
    quote: '行情',
    daily_bars: '日线',
    technical: '技术',
    news: '新闻',
    fundamentals: '基本面',
    chip: '筹码',
  },
  en: {
    quote: 'quote',
    daily_bars: 'daily bars',
    technical: 'technical',
    news: 'news',
    fundamentals: 'fundamentals',
    chip: 'chip',
  },
  ko: {
    quote: '시세',
    daily_bars: '일봉',
    technical: '기술',
    news: '뉴스',
    fundamentals: '펀더멘털',
    chip: '매물대',
  },
};

const TEXT = {
  zh: {
    eyebrow: '数据上下文',
    title: '输入数据块',
    counts: '状态计数',
    source: '来源',
    warnings: '告警',
    missingReasons: '缺失原因',
    inputScope: '本次分析输入',
    evidenceScope: '仅代表进入本次 LLM 的输入，不等同于数据源运行成功',
    qualityScore: '质量分',
    limitations: '数据限制',
    newsResultCount: '新闻结果数',
    triggerSource: '触发来源',
    qualityLevel: {
      good: '良好',
      usable: '可用',
      limited: '受限',
      poor: '较差',
    },
    status: {
      available: '可用',
      missing: '缺失',
      not_supported: '不支持',
      fallback: '降级',
      stale: '过期',
      estimated: '估算',
      partial: '部分可用',
      fetch_failed: '抓取失败',
    },
  },
  en: {
    eyebrow: 'DATA CONTEXT',
    title: 'Input Blocks',
    counts: 'Status Counts',
    source: 'Source',
    warnings: 'Warnings',
    missingReasons: 'Missing Reasons',
    inputScope: 'Analysis Input',
    evidenceScope: 'Shows inputs included in this LLM run, not provider run success',
    qualityScore: 'Quality',
    limitations: 'Data Limitations',
    newsResultCount: 'News Results',
    triggerSource: 'Trigger',
    qualityLevel: {
      good: 'Good',
      usable: 'Usable',
      limited: 'Limited',
      poor: 'Poor',
    },
    status: {
      available: 'Available',
      missing: 'Missing',
      not_supported: 'Not supported',
      fallback: 'Fallback',
      stale: 'Stale',
      estimated: 'Estimated',
      partial: 'Partial',
      fetch_failed: 'Fetch failed',
    },
  },
  ko: {
    eyebrow: '데이터 컨텍스트',
    title: '입력 데이터 블록',
    counts: '상태 카운트',
    source: '출처',
    warnings: '경고',
    missingReasons: '누락 사유',
    inputScope: '이번 분석 입력',
    evidenceScope: '이번 LLM 입력에 포함된 항목만 표시하며, 데이터 소스 실행 성공과는 다릅니다',
    qualityScore: '품질 점수',
    limitations: '데이터 한계',
    newsResultCount: '뉴스 결과 수',
    triggerSource: '트리거',
    qualityLevel: {
      good: '양호',
      usable: '사용 가능',
      limited: '제한적',
      poor: '미흡',
    },
    status: {
      available: '사용 가능',
      missing: '누락',
      not_supported: '미지원',
      fallback: '강등',
      stale: '만료',
      estimated: '추정',
      partial: '부분 사용',
      fetch_failed: '수집 실패',
    },
  },
} as const;

const MISSING_REASON_LABELS: Record<ReportLanguage, Record<string, string>> = {
  zh: {
    daily_bars_missing: '未进入分析输入',
    news_context_missing: '未进入分析输入',
    realtime_quote_missing: '未进入分析输入',
    trend_result_missing: '未进入分析输入',
    fundamental_context_missing: '未进入分析输入',
    chip_distribution_missing: '未进入分析输入',
    today_missing: '今日数据未进入分析输入',
    yesterday_missing: '昨日数据未进入分析输入',
  },
  en: {
    daily_bars_missing: 'Not included in analysis input',
    news_context_missing: 'Not included in analysis input',
    realtime_quote_missing: 'Not included in analysis input',
    trend_result_missing: 'Not included in analysis input',
    fundamental_context_missing: 'Not included in analysis input',
    chip_distribution_missing: 'Not included in analysis input',
    today_missing: 'Today data not included in analysis input',
    yesterday_missing: 'Yesterday data not included in analysis input',
  },
  ko: {
    daily_bars_missing: '분석 입력에 포함되지 않음',
    news_context_missing: '분석 입력에 포함되지 않음',
    realtime_quote_missing: '분석 입력에 포함되지 않음',
    trend_result_missing: '분석 입력에 포함되지 않음',
    fundamental_context_missing: '분석 입력에 포함되지 않음',
    chip_distribution_missing: '분석 입력에 포함되지 않음',
    today_missing: '당일 데이터가 분석 입력에 포함되지 않음',
    yesterday_missing: '전일 데이터가 분석 입력에 포함되지 않음',
  },
};

const STATUS_ORDER: AnalysisContextPackBlockStatus[] = [
  'available',
  'missing',
  'fetch_failed',
  'not_supported',
  'fallback',
  'stale',
  'estimated',
  'partial',
];

const getCount = (
  overview: AnalysisContextPackOverview,
  status: AnalysisContextPackBlockStatus,
): number => {
  if (status === 'not_supported') {
    return overview.counts.notSupported || 0;
  }
  if (status === 'fetch_failed') {
    return overview.counts.fetchFailed || 0;
  }
  return overview.counts[status] || 0;
};

const formatLimitation = (
  value: string,
  language: ReportLanguage,
  text: (typeof TEXT)[ReportLanguage],
): string => {
  const [rawKey, ...statusParts] = value.split(':');
  if (!rawKey || statusParts.length === 0) {
    return value;
  }

  const key = rawKey.trim();
  const status = statusParts.join(':').trim();
  if (!key || !status) {
    return value;
  }

  const label = BLOCK_LABELS[language][key] || key;
  const statusLabel = (text.status as Record<string, string>)[status] || status;
  return language === 'zh' ? `${label}：${statusLabel}` : `${label}: ${statusLabel}`;
};

const formatMissingReason = (reason: string, language: ReportLanguage): string => {
  const label = MISSING_REASON_LABELS[language][reason];
  return label ? `${label} (${reason})` : reason;
};

export const AnalysisContextSummary: React.FC<AnalysisContextSummaryProps> = ({
  overview,
  language = 'zh',
}) => {
  const reportLanguage = normalizeReportLanguage(language);
  const text = TEXT[reportLanguage];

  if (!overview || !overview.blocks?.length) {
    return null;
  }

  const visibleCounts = STATUS_ORDER
    .map((status) => ({ status, value: getCount(overview, status) }))
    .filter((item) => item.value > 0);
  const summaryCounts = STATUS_ORDER
    .map((status) => ({ status, value: getCount(overview, status) }))
    .filter((item) => item.status === 'available' || item.status === 'missing' || item.value > 0);
  const metadataItems = [
    typeof overview.metadata?.newsResultCount === 'number'
      ? `${text.newsResultCount}: ${overview.metadata.newsResultCount}`
      : null,
  ].filter((item): item is string => Boolean(item));
  const triggerSource = overview.metadata?.triggerSource?.trim();
  const quality = overview.dataQuality;
  const qualityLevel = quality?.level || undefined;
  const qualityStyle = qualityLevel ? QUALITY_STYLE[qualityLevel] : undefined;
  const qualityLabel = qualityLevel ? text.qualityLevel[qualityLevel] : undefined;
  const limitations = quality?.limitations?.map((item) => formatLimitation(item, reportLanguage, text)) || [];

  return (
    <Card variant="bordered" padding="none" className="home-panel-card">
      <details data-testid="analysis-context-summary" className="group">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-cyan/10 text-cyan">
              <Database className="h-4 w-4" aria-hidden="true" />
            </span>
            <span className="min-w-0">
              <span className="label-uppercase">{text.eyebrow}</span>
              <span className="mt-0.5 block truncate text-base font-semibold text-foreground">
                {text.title}
              </span>
              <span className="mt-1 block text-xs leading-5 text-muted-text">
                {text.evidenceScope}
              </span>
            </span>
          </div>
          <span className="flex min-w-0 flex-wrap items-center justify-end gap-2">
            {typeof quality?.overallScore === 'number' ? (
              <Badge variant={qualityStyle?.variant || 'default'} className="gap-1.5 shadow-none">
                {qualityStyle ? <StatusDot tone={qualityStyle.tone} className="h-1.5 w-1.5" /> : null}
                {text.qualityScore} {quality.overallScore}/100{qualityLabel ? ` ${qualityLabel}` : ''}
              </Badge>
            ) : null}
            {summaryCounts.map(({ status, value }) => {
              const style = STATUS_STYLE[status];
              return (
                <Badge key={status} variant={style.variant} className="gap-1.5 shadow-none">
                  <StatusDot tone={style.tone} className="h-1.5 w-1.5" />
                  {text.status[status]} {value}
                </Badge>
              );
            })}
            {triggerSource ? (
              <span className="home-accent-chip px-2 py-0.5 text-xs text-muted-text">
                {text.triggerSource}: {triggerSource}
              </span>
            ) : null}
            <span className="home-accent-chip px-2 py-0.5 text-xs text-muted-text">
              {text.inputScope}
            </span>
            <ChevronDown className="h-4 w-4 shrink-0 text-muted-text transition-transform group-open:rotate-180" aria-hidden="true" />
          </span>
        </summary>

        <div className="home-divider border-t px-4 pb-4 pt-3">
          <DashboardPanelHeader
            eyebrow={text.eyebrow}
            title={text.title}
            leading={(
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan/10 text-cyan">
                <Database className="h-4 w-4" aria-hidden="true" />
              </span>
            )}
            actions={metadataItems.length > 0 || typeof quality?.overallScore === 'number' ? (
              <div className="hidden flex-wrap justify-end gap-2 text-xs text-muted-text md:flex">
                {typeof quality?.overallScore === 'number' ? (
                  <span className="home-accent-chip px-2 py-0.5">
                    {text.qualityScore}: {quality.overallScore}/100{qualityLabel ? ` ${qualityLabel}` : ''}
                  </span>
                ) : null}
                {metadataItems.map((item) => (
                  <span key={item} className="home-accent-chip px-2 py-0.5">
                    {item}
                  </span>
                ))}
                <span className="home-accent-chip px-2 py-0.5">
                  {text.inputScope}
                </span>
              </div>
            ) : undefined}
          />

          {visibleCounts.length > 0 ? (
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="label-uppercase">{text.counts}</span>
              {visibleCounts.map(({ status, value }) => {
                const style = STATUS_STYLE[status];
                return (
                  <Badge key={status} variant={style.variant} className="gap-1.5 shadow-none">
                    <StatusDot tone={style.tone} className="h-1.5 w-1.5" />
                    {text.status[status]} {value}
                  </Badge>
                );
              })}
            </div>
          ) : null}

          {limitations.length ? (
            <div className="mb-3 home-subpanel p-3 text-xs leading-5 text-muted-text">
              <span className="font-medium text-foreground">{text.limitations}: </span>
              {limitations.join(', ')}
            </div>
          ) : null}

          {overview.warnings?.length ? (
            <div className="mb-3 home-subpanel p-3 text-xs leading-5 text-warning">
              <span className="font-medium">{text.warnings}: </span>
              {overview.warnings.join(', ')}
            </div>
          ) : null}

          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {overview.blocks.map((block) => {
              const style = STATUS_STYLE[block.status] || STATUS_STYLE.missing;
              return (
                <div key={block.key} className="home-subpanel p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">{block.label}</p>
                      {block.source ? (
                        <p className="mt-1 truncate text-xs text-secondary-text">
                          {text.source}: {block.source}
                        </p>
                      ) : null}
                    </div>
                    <Badge variant={style.variant} className="shrink-0 gap-1.5 shadow-none">
                      <StatusDot tone={style.tone} className="h-1.5 w-1.5" />
                      {text.status[block.status] || block.status}
                    </Badge>
                  </div>

                  {block.warnings?.length ? (
                    <p className="mt-2 text-xs leading-5 text-warning">
                      {text.warnings}: {block.warnings.join(', ')}
                    </p>
                  ) : null}
                  {block.missingReasons?.length ? (
                    <p className="mt-2 text-xs leading-5 text-muted-text">
                      {text.missingReasons}: {block.missingReasons
                        .map((reason) => formatMissingReason(reason, reportLanguage))
                        .join(', ')}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>

          {metadataItems.length > 0 || typeof quality?.overallScore === 'number' ? (
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-text md:hidden">
              {typeof quality?.overallScore === 'number' ? (
                <span className="home-accent-chip px-2 py-0.5">
                  {text.qualityScore}: {quality.overallScore}/100{qualityLabel ? ` ${qualityLabel}` : ''}
                </span>
              ) : null}
              {metadataItems.map((item) => (
                <span key={item} className="home-accent-chip px-2 py-0.5">
                  {item}
                </span>
              ))}
              <span className="home-accent-chip px-2 py-0.5">
                {text.inputScope}
              </span>
            </div>
          ) : null}
        </div>
      </details>
    </Card>
  );
};
