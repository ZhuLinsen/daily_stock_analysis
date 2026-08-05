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
    sourceUnavailable: '未记录输入来源',
    warnings: '告警',
    missingReasons: '说明',
    diagnosticCode: '诊断码',
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
    sourceUnavailable: 'Input source not recorded',
    warnings: 'Warnings',
    missingReasons: 'Details',
    diagnosticCode: 'Diagnostic code',
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
    sourceUnavailable: '입력 출처 기록 없음',
    warnings: '경고',
    missingReasons: '설명',
    diagnosticCode: '진단 코드',
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
    daily_bars_missing: '日线数据未进入本次分析，技术指标可能不完整；请检查日线数据源、网络或限流后重新分析',
    news_context_missing: '新闻未进入本次 LLM 分析，结论未使用新闻上下文；报告页相关资讯由独立接口补充，显示与否不代表已进入本次分析。请检查搜索配置、网络或限流后重新分析',
    realtime_quote_missing: '实时行情未进入本次分析，当前价格相关结论可能受限；请检查行情数据源、网络或限流后重新分析',
    trend_result_missing: '技术分析结果未进入本次分析，技术面判断可能不完整；请检查日线完整性后重新分析',
    fundamental_context_missing: '基本面未进入本次分析，结论未使用基本面数据；请检查基本面数据源、网络或限流后重新分析',
    fundamental_pipeline_failed: '基本面抓取失败，本次分析未使用基本面数据；请检查数据源配置、网络或限流后重新分析',
    fundamentals_not_supported: '当前市场或标的不支持基本面数据，本次分析未使用该数据；请结合其他指标判断',
    fundamental_coverage_missing: '基本面覆盖数据未进入本次分析，结论可能缺少部分财务信息；请检查数据源覆盖范围后重新分析',
    fundamental_source_chain_missing: '未记录基本面来源链元数据；基本面是否进入本次分析以当前状态为准，请结合来源和告警复核数据出处',
    chip_distribution_missing: '筹码数据未进入本次分析，结论未使用筹码分布；请确认当前市场或标的数据支持情况',
    chip_not_supported: '当前市场或标的不支持筹码数据，本次分析未使用该指标；请结合其他指标判断',
    today_missing: '今日数据未进入本次分析，盘中判断可能受限；请结合实时行情复核后重新分析',
    yesterday_missing: '昨日数据未进入本次分析，日线对比可能不完整；请等待数据源更新后重新分析',
  },
  en: {
    daily_bars_missing: 'Daily bars were not included, so technical indicators may be incomplete; check the daily data source, network, or rate limits and rerun',
    news_context_missing: 'News was not included in this LLM run, so the conclusion did not use news context; related news on the report page is loaded separately and does not indicate that it was used in this analysis. Check search configuration, network, or rate limits and rerun',
    realtime_quote_missing: 'Real-time quotes were not included, so price-related conclusions may be limited; check the quote source, network, or rate limits and rerun',
    trend_result_missing: 'Technical analysis was not included, so the technical view may be incomplete; check daily-bar completeness and rerun',
    fundamental_context_missing: 'Fundamentals were not included, so the conclusion did not use fundamental data; check the data source, network, or rate limits and rerun',
    fundamental_pipeline_failed: 'Fundamental retrieval failed and this analysis did not use fundamental data; check the data-source configuration, network, or rate limits and rerun',
    fundamentals_not_supported: 'Fundamental data is not supported for this market or symbol and was not used; cross-check other indicators',
    fundamental_coverage_missing: 'Fundamental coverage was not included, so some financial context may be missing; check source coverage and rerun',
    fundamental_source_chain_missing: 'Fundamental source-chain metadata was not recorded; use the current status to determine whether fundamentals were included, and review the source and warnings for provenance',
    chip_distribution_missing: 'Chip distribution was not included and was not used in the conclusion; confirm support for this market or symbol',
    chip_not_supported: 'Chip data is not supported for this market or symbol and was not used; cross-check other indicators',
    today_missing: 'Today\'s data was not included, so intraday conclusions may be limited; cross-check real-time quotes and rerun',
    yesterday_missing: 'Yesterday\'s data was not included, so daily comparisons may be incomplete; wait for the source to update and rerun',
  },
  ko: {
    daily_bars_missing: '일봉이 포함되지 않아 기술 지표가 불완전할 수 있습니다. 일봉 소스, 네트워크 또는 제한을 확인한 후 다시 분석하세요',
    news_context_missing: '뉴스가 이번 LLM 분석에 포함되지 않아 결론에 뉴스 맥락이 반영되지 않았습니다. 보고서 페이지의 관련 뉴스는 별도 API에서 불러오며, 표시 여부가 이번 분석에 사용되었음을 의미하지는 않습니다. 검색 설정, 네트워크 또는 제한을 확인한 후 다시 분석하세요',
    realtime_quote_missing: '실시간 시세가 포함되지 않아 가격 관련 결론이 제한될 수 있습니다. 시세 소스, 네트워크 또는 제한을 확인한 후 다시 분석하세요',
    trend_result_missing: '기술 분석 결과가 포함되지 않아 기술적 판단이 불완전할 수 있습니다. 일봉 완전성을 확인한 후 다시 분석하세요',
    fundamental_context_missing: '펀더멘털이 포함되지 않아 결론에 펀더멘털 데이터가 반영되지 않았습니다. 데이터 소스, 네트워크 또는 제한을 확인한 후 다시 분석하세요',
    fundamental_pipeline_failed: '펀더멘털 수집에 실패해 이번 분석에서 사용되지 않았습니다. 데이터 소스 설정, 네트워크 또는 제한을 확인한 후 다시 분석하세요',
    fundamentals_not_supported: '현재 시장 또는 종목은 펀더멘털 데이터를 지원하지 않아 분석에 사용되지 않았습니다. 다른 지표와 함께 판단하세요',
    fundamental_coverage_missing: '펀더멘털 커버리지가 포함되지 않아 일부 재무 맥락이 빠질 수 있습니다. 소스 범위를 확인한 후 다시 분석하세요',
    fundamental_source_chain_missing: '펀더멘털 소스 체인 메타데이터가 기록되지 않았습니다. 펀더멘털 포함 여부는 현재 상태를 기준으로 판단하고 출처와 경고를 함께 확인하세요',
    chip_distribution_missing: '매물대 데이터가 포함되지 않아 결론에 반영되지 않았습니다. 현재 시장 또는 종목의 지원 여부를 확인하세요',
    chip_not_supported: '현재 시장 또는 종목은 매물대 데이터를 지원하지 않아 분석에 사용되지 않았습니다. 다른 지표와 함께 판단하세요',
    today_missing: '당일 데이터가 포함되지 않아 장중 판단이 제한될 수 있습니다. 실시간 시세와 대조한 후 다시 분석하세요',
    yesterday_missing: '전일 데이터가 포함되지 않아 일봉 비교가 불완전할 수 있습니다. 소스 갱신 후 다시 분석하세요',
  },
};

const UNKNOWN_REASON_DETAILS: Record<ReportLanguage, string> = {
  zh: '未记录明确原因；请结合状态、来源和告警排查',
  en: 'No specific reason was recorded; review the status, source, and warnings',
  ko: '명확한 원인이 기록되지 않았습니다. 상태, 출처 및 경고를 함께 확인하세요',
};

const STATUS_FALLBACK_GUIDANCE: Record<
  ReportLanguage,
  Partial<Record<AnalysisContextPackBlockStatus, string>>
> = {
  zh: {
    missing: '数据未进入本次分析，相关结论可能不完整；请检查数据源、配置或网络后重新分析',
    fetch_failed: '数据抓取失败，本次分析未使用该数据；请检查数据源、网络或限流后重新分析',
    not_supported: '当前市场或标的不支持该数据，本次分析未使用该数据；请结合其他指标判断',
    fallback: '本次分析使用了备用数据路径；请结合来源和告警复核结果',
    stale: '本次分析使用的不是最新数据；请检查更新时间并按需重新分析',
    estimated: '本次分析使用了估算数据；请结合原始数据复核结果',
    partial: '仅部分数据进入本次分析，相关结论可能不完整；请检查告警和数据源后重新分析',
  },
  en: {
    missing: 'Data was not included, so related conclusions may be incomplete; check the data source, configuration, or network and rerun',
    fetch_failed: 'Data retrieval failed and this analysis did not use the data; check the source, network, or rate limits and rerun',
    not_supported: 'This data is not supported for the current market or symbol and was not used; cross-check other indicators',
    fallback: 'This analysis used a fallback data path; review the result against its source and warnings',
    stale: 'This analysis used data that may not be current; check the timestamp and rerun if needed',
    estimated: 'This analysis used estimated data; cross-check the result against source data',
    partial: 'Only part of the data was included, so related conclusions may be incomplete; check warnings and the data source and rerun',
  },
  ko: {
    missing: '데이터가 포함되지 않아 관련 결론이 불완전할 수 있습니다. 데이터 소스, 설정 또는 네트워크를 확인한 후 다시 분석하세요',
    fetch_failed: '데이터 수집에 실패해 이번 분석에서 사용되지 않았습니다. 데이터 소스, 네트워크 또는 제한을 확인한 후 다시 분석하세요',
    not_supported: '현재 시장 또는 종목은 이 데이터를 지원하지 않아 분석에 사용되지 않았습니다. 다른 지표와 함께 판단하세요',
    fallback: '이번 분석은 대체 데이터 경로를 사용했습니다. 출처와 경고를 기준으로 결과를 검토하세요',
    stale: '이번 분석은 최신이 아닐 수 있는 데이터를 사용했습니다. 갱신 시각을 확인하고 필요하면 다시 분석하세요',
    estimated: '이번 분석은 추정 데이터를 사용했습니다. 원본 데이터와 결과를 교차 확인하세요',
    partial: '데이터의 일부만 포함되어 관련 결론이 불완전할 수 있습니다. 경고와 데이터 소스를 확인한 후 다시 분석하세요',
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

const formatMissingReason = (
  reason: string,
  language: ReportLanguage,
  status: AnalysisContextPackBlockStatus,
): string => {
  const detail = MISSING_REASON_LABELS[language][reason]
    || STATUS_FALLBACK_GUIDANCE[language][status]
    || UNKNOWN_REASON_DETAILS[language];
  return `${detail} (${TEXT[language].diagnosticCode}: ${reason})`;
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
              const hasMissingReasons = Boolean(block.missingReasons?.length);
              const detail = hasMissingReasons
                ? block.missingReasons
                  ?.map((reason) => formatMissingReason(
                    reason,
                    reportLanguage,
                    block.status,
                  ))
                  .join('; ')
                : STATUS_FALLBACK_GUIDANCE[reportLanguage][block.status];
              return (
                <div key={block.key} className="home-subpanel p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">{block.label}</p>
                      <p className="mt-1 truncate text-xs text-secondary-text">
                        {text.source}: {block.source || text.sourceUnavailable}
                      </p>
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
                  {detail ? (
                    <p className="mt-2 text-xs leading-5 text-muted-text">
                      {text.missingReasons}: {detail}
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
