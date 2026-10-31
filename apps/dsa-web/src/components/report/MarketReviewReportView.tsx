import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { BarChart3, Clipboard, FileText, Gauge, Layers, ShieldAlert, TrendingUp, WalletCards, Workflow } from 'lucide-react';
import { historyApi } from '../../api/history';
import { formatUiText, UI_TEXT } from '../../i18n/uiText';
import type {
  AnalysisReport,
  MarketReviewIndexMaStatus,
  MarketReviewPayload,
  MarketReviewPayloadSection,
  ReportLanguage,
} from '../../types/analysis';
import { markdownToPlainText } from '../../utils/markdown';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Card } from '../common';
import { Tooltip } from '../common/Tooltip';
import { ReportMarkdownBody } from './ReportMarkdownBody';
import { ShareImageButton } from './ShareImageButton';

interface MarketReviewReportViewProps {
  report?: AnalysisReport;
  recordId?: number;
  content?: string;
  payload?: MarketReviewPayload | null;
  reportLanguage?: ReportLanguage;
  className?: string;
  onOpenRunFlow?: (recordId: number) => void;
}

type CopyType = 'markdown' | 'text';
type LoadedMarkdown = {
  recordId: number;
  content: string;
};
type LoadError = {
  recordId: number;
  message: string;
};
type MarketReviewSection = {
  id: string;
  title: string;
  content: string;
  icon: typeof FileText;
};
type StructuredMarketData = {
  id: string;
  title?: string;
  breadth?: MarketReviewPayload['breadth'];
  indices: NonNullable<MarketReviewPayload['indices']>;
  sectors?: MarketReviewPayload['sectors'];
  concepts?: MarketReviewPayload['concepts'];
  summary?: MarketReviewPayload['summary'];
  styleRotation?: MarketReviewPayload['styleRotation'];
  catalysts?: MarketReviewPayload['catalysts'];
  nextDayPlan?: MarketReviewPayload['nextDayPlan'];
  crossMarketNote?: MarketReviewPayload['crossMarketNote'];
};

const isMarketReviewPayload = (value: unknown): value is MarketReviewPayload =>
  Boolean(value && typeof value === 'object');

const TOP_HEADING_PATTERN = /^\s*#\s+(.+?)\s*(?:\n+|$)/;
const SECTION_HEADING_PATTERN = /^(#{2,3})\s+(.+?)\s*$/gm;

const normalizeHeading = (value: string): string =>
  value.trim().replace(/\s+/g, ' ').toLowerCase();

const stripTopHeading = (markdown: string, title?: string): string => {
  const match = markdown.match(TOP_HEADING_PATTERN);
  if (!match) {
    return markdown.trim();
  }

  const heading = normalizeHeading(match[1]);
  const reportTitle = normalizeHeading(title || '');
  const genericTitles = new Set([
    'market review',
    '大盘复盘',
    '大盘复盘详情',
    'a股市场复盘',
    'a 股市场复盘',
  ]);

  if (heading === reportTitle || genericTitles.has(heading)) {
    return markdown.slice(match[0].length).trim();
  }

  return markdown.trim();
};

const getSectionIcon = (title: string): typeof FileText => {
  const normalized = normalizeHeading(title);
  if (/指数|index|overview|大盘/.test(normalized)) {
    return BarChart3;
  }
  if (/情绪|赚钱|sentiment|breadth|temperature/.test(normalized)) {
    return Gauge;
  }
  if (/行业|板块|主题|轮动|sector|theme|rotation/.test(normalized)) {
    return TrendingUp;
  }
  if (/资金|成交|量能|flow|turnover|volume|capital/.test(normalized)) {
    return WalletCards;
  }
  if (/风险|机会|观察|risk|watch|next/.test(normalized)) {
    return ShieldAlert;
  }
  return FileText;
};

const splitMarketReviewSections = (markdown: string): MarketReviewSection[] => {
  const matches = Array.from(markdown.matchAll(SECTION_HEADING_PATTERN));
  if (matches.length === 0) {
    return [{
      id: 'full-review',
      title: '复盘正文',
      content: markdown,
      icon: FileText,
    }];
  }

  const intro = markdown.slice(0, matches[0].index).trim();
  const sections: MarketReviewSection[] = intro
    ? [{
        id: 'overview',
        title: '复盘概览',
        content: intro,
        icon: FileText,
      }]
    : [];

  matches.forEach((match, index) => {
    const start = (match.index ?? 0) + match[0].length;
    const end = index + 1 < matches.length ? matches[index + 1].index ?? markdown.length : markdown.length;
    const title = match[2].trim();
    const content = markdown.slice(start, end).trim();
    if (!content) {
      return;
    }
    sections.push({
      id: `${index}-${normalizeHeading(title).replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-').replace(/^-|-$/g, '') || 'section'}`,
      title,
      content,
      icon: getSectionIcon(title),
    });
  });

  return sections;
};

const getPayloadSections = (payload?: MarketReviewPayload | null): MarketReviewSection[] => {
  if (!payload) {
    return [];
  }

  if (payload.markets) {
    return Object.entries(payload.markets).flatMap(([region, marketPayload]) => {
      const marketTitle = marketPayload.title || region.toUpperCase();
      return getPayloadSections(marketPayload).map((section) => ({
        ...section,
        id: `${region}-${section.id}`,
        title: `${marketTitle} / ${section.title}`,
      }));
    });
  }

  const payloadTitle = normalizeHeading(payload.title || '');
  return (payload.sections || [])
    .filter((section: MarketReviewPayloadSection) => section.markdown?.trim())
    .filter((section: MarketReviewPayloadSection) => normalizeHeading(section.title || '') !== payloadTitle)
    .map((section, index) => ({
      id: `${section.key || index}-${normalizeHeading(section.title).replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-') || 'section'}`,
      title: section.title || 'Review',
      content: section.markdown,
      icon: getSectionIcon(section.title || ''),
    }));
};

const hasRankingRows = (rankings?: MarketReviewPayload['sectors']): boolean =>
  Boolean(rankings?.top?.length || rankings?.bottom?.length);

/** Issue #1584: optional enhanced structured fields (summary/rotation/catalysts/plan). */
const hasEnhancedInsightData = (payload?: MarketReviewPayload | null): boolean =>
  Boolean(
    payload?.summary
    || payload?.styleRotation
    || payload?.catalysts?.length
    || payload?.nextDayPlan
    || payload?.crossMarketNote,
  );

const hasStructuredMarketData = (payload?: MarketReviewPayload | null): boolean =>
  Boolean(
    payload?.breadth
    || payload?.indices?.length
    || hasRankingRows(payload?.sectors)
    || hasRankingRows(payload?.concepts)
    || hasEnhancedInsightData(payload),
  );

const getStructuredMarketData = (payload?: MarketReviewPayload | null): StructuredMarketData[] => {
  if (!payload) {
    return [];
  }

  if (payload.markets) {
    return Object.entries(payload.markets)
      .filter(([, marketPayload]) => hasStructuredMarketData(marketPayload))
      .map(([region, marketPayload]) => ({
        id: region,
        title: marketPayload.title || region.toUpperCase(),
        breadth: marketPayload.breadth,
        indices: marketPayload.indices || [],
        sectors: marketPayload.sectors,
        concepts: marketPayload.concepts,
        summary: marketPayload.summary,
        styleRotation: marketPayload.styleRotation,
        catalysts: marketPayload.catalysts,
        nextDayPlan: marketPayload.nextDayPlan,
        crossMarketNote: marketPayload.crossMarketNote,
      }));
  }

  if (!hasStructuredMarketData(payload)) {
    return [];
  }

  return [{
    id: payload.region || 'market',
    title: payload.title,
    breadth: payload.breadth,
    indices: payload.indices || [],
    sectors: payload.sectors,
    concepts: payload.concepts,
    summary: payload.summary,
    styleRotation: payload.styleRotation,
    catalysts: payload.catalysts,
    nextDayPlan: payload.nextDayPlan,
    crossMarketNote: payload.crossMarketNote,
  }];
};

const coerceFiniteNumber = (value: unknown): number | null => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }

  if (typeof value === 'string' && value.trim()) {
    const normalizedValue = value.trim().replace(/,/g, '');
    const numericText = normalizedValue.endsWith('%')
      ? normalizedValue.slice(0, -1).trim()
      : normalizedValue;
    const parsed = Number(numericText);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
};

const formatMarketNumber = (value: unknown, options?: { zeroAsMissing?: boolean }): string => {
  const numericValue = coerceFiniteNumber(value);
  if (numericValue === null || (options?.zeroAsMissing && numericValue === 0)) {
    return '-';
  }
  return numericValue.toFixed(2);
};

const formatMarketCount = (value: unknown): string => {
  const numericValue = coerceFiniteNumber(value);
  return numericValue === null ? '-' : numericValue.toFixed(0);
};

const formatMarketAmount = (value: unknown, unit?: string): string => {
  const formattedValue = formatMarketNumber(value);
  if (formattedValue === '-') {
    return '-';
  }
  return unit ? `${formattedValue} ${unit}` : formattedValue;
};

const formatMarketPercent = (value: unknown): string => {
  const formattedValue = formatMarketNumber(value);
  return formattedValue === '-' ? '-' : `${formattedValue}%`;
};

const formatMarketHighLow = (high: unknown, low: unknown): string => {
  const highText = formatMarketNumber(high, { zeroAsMissing: true });
  const lowText = formatMarketNumber(low, { zeroAsMissing: true });
  return highText === '-' && lowText === '-' ? '-' : `${highText} / ${lowText}`;
};

/** Issue #1584: render ma_status as compact tokens, e.g. "5↑ 10↓ 20↑"; null when absent. */
const MA_STATE_TOKENS: Record<string, string> = { above: '↑', below: '↓', near: '—' };

const formatMaStatus = (maStatus?: MarketReviewIndexMaStatus | null): string | null => {
  if (!maStatus || typeof maStatus !== 'object') {
    return null;
  }
  const tokens = (['ma5', 'ma10', 'ma20'] as const)
    .map((key) => {
      const token = MA_STATE_TOKENS[maStatus[key] || ''];
      return token ? `${key.slice(2)}${token}` : null;
    })
    .filter((token): token is string => Boolean(token));
  return tokens.length > 0 ? tokens.join(' ') : null;
};

const hasAnyMaStatus = (indices: NonNullable<MarketReviewPayload['indices']>): boolean =>
  indices.some((index) => formatMaStatus(index.maStatus) !== null);

type MarketReviewCatalystItem = NonNullable<MarketReviewPayload['catalysts']>[number];

const formatCatalystDirection = (
  direction: MarketReviewCatalystItem['direction'],
  text: { catalystDirection: Record<string, string> },
): string | null => {
  if (!direction || typeof direction !== 'string') {
    return null;
  }
  return text.catalystDirection[direction] || null;
};

const MARKET_REVIEW_TEXT: Record<ReportLanguage, {
  reviewSummary: string;
  noReviewSummary: string;
  noSentimentScore: string;
  rotationAndFunds: string;
  noRotationView: string;
  riskAndWatch: string;
  noRiskWatch: string;
  structuredMarketData: string;
  noBreadthData: string;
  advancers: string;
  decliners: string;
  limitUpDown: string;
  turnover: string;
  index: string;
  last: string;
  change: string;
  highLow: string;
  industryBoards: string;
  conceptBoards: string;
  leading: string;
  lagging: string;
  /** ---- Issue #1584 optional structured fields ---- */
  temperature: string;
  marketStatus: string;
  positionAdvice: string;
  coreConclusion: string;
  divergenceDiagnosis: string;
  maStatusColumn: string;
  styleRotation: string;
  catalysts: string;
  nextDayPlan: string;
  invalidation: string;
  crossMarketNote: string;
  catalystDirection: Record<string, string>;
  digestedLabel: string;
  notDigestedLabel: string;
}> = {
  zh: {
    reviewSummary: '复盘摘要',
    noReviewSummary: '暂无摘要',
    noSentimentScore: '暂无评分',
    rotationAndFunds: '轮动与资金',
    noRotationView: '暂无轮动观点',
    riskAndWatch: '风险与观察',
    noRiskWatch: '暂无观察重点',
    structuredMarketData: '结构化大盘数据',
    noBreadthData: '暂无数据',
    advancers: '上涨家数',
    decliners: '下跌家数',
    limitUpDown: '涨停/跌停',
    turnover: '成交额',
    index: '指数',
    last: '最新',
    change: '涨跌幅',
    highLow: '高/低',
    industryBoards: '行业板块',
    conceptBoards: '概念板块',
    leading: '领涨',
    lagging: '领跌',
    temperature: '市场温度',
    marketStatus: '市场状态',
    positionAdvice: '建议仓位',
    coreConclusion: '核心结论',
    divergenceDiagnosis: '宽度分化诊断',
    maStatusColumn: '均线状态',
    styleRotation: '风格轮动',
    catalysts: '消息催化',
    nextDayPlan: '明日计划',
    invalidation: '失效条件',
    crossMarketNote: '跨市场参考',
    catalystDirection: { bullish: '利好', bearish: '利空', neutral: '中性' },
    digestedLabel: '已消化',
    notDigestedLabel: '未消化',
  },
  en: {
    reviewSummary: 'Review Summary',
    noReviewSummary: 'No review summary yet',
    noSentimentScore: 'No score yet',
    rotationAndFunds: 'Rotation & Funds',
    noRotationView: 'No rotation view yet',
    riskAndWatch: 'Risks & Watchlist',
    noRiskWatch: 'No key observations yet',
    structuredMarketData: 'Structured Market Data',
    noBreadthData: 'No data',
    advancers: 'Advancers',
    decliners: 'Decliners',
    limitUpDown: 'Limit Up/Down',
    turnover: 'Turnover',
    index: 'Index',
    last: 'Last',
    change: 'Change',
    highLow: 'High/Low',
    industryBoards: 'Industry Sectors',
    conceptBoards: 'Concept Themes',
    leading: 'Leading',
    lagging: 'Lagging',
    temperature: 'Market Temperature',
    marketStatus: 'Market Status',
    positionAdvice: 'Position Advice',
    coreConclusion: 'Core Conclusion',
    divergenceDiagnosis: 'Breadth Divergence',
    maStatusColumn: 'MA Status',
    styleRotation: 'Style Rotation',
    catalysts: 'News Catalysts',
    nextDayPlan: 'Next-Day Plan',
    invalidation: 'Invalidation',
    crossMarketNote: 'Cross-Market Note',
    catalystDirection: { bullish: 'Bullish', bearish: 'Bearish', neutral: 'Neutral' },
    digestedLabel: 'Digested',
    notDigestedLabel: 'Not digested',
  },
  ko: {
    reviewSummary: '리뷰 요약',
    noReviewSummary: '요약 없음',
    noSentimentScore: '점수 없음',
    rotationAndFunds: '순환과 자금',
    noRotationView: '순환 관점 없음',
    riskAndWatch: '리스크와 관찰',
    noRiskWatch: '관찰 포인트 없음',
    structuredMarketData: '구조화 시장 데이터',
    noBreadthData: '데이터 없음',
    advancers: '상승 종목 수',
    decliners: '하락 종목 수',
    limitUpDown: '상한가/하한가',
    turnover: '거래대금',
    index: '지수',
    last: '현재',
    change: '등락률',
    highLow: '고가/저가',
    industryBoards: '업종 섹터',
    conceptBoards: '테마 섹터',
    leading: '강세',
    lagging: '약세',
    temperature: '시장 온도',
    marketStatus: '시장 상태',
    positionAdvice: '포지션 권고',
    coreConclusion: '핵심 결론',
    divergenceDiagnosis: '지수-개별주 괴리 진단',
    maStatusColumn: '이동평균 상태',
    styleRotation: '스타일 로테이션',
    catalysts: '뉴스 촉매',
    nextDayPlan: '익일 계획',
    invalidation: '무효 조건',
    crossMarketNote: '교차 시장 참고',
    catalystDirection: { bullish: '강세', bearish: '약세', neutral: '중립' },
    digestedLabel: '소화됨',
    notDigestedLabel: '미소화',
  },
};

const formatRankingChange = (value: unknown): string => {
  const numeric = typeof value === 'number' ? value : Number(String(value ?? '').replace(/%$/, ''));
  if (!Number.isFinite(numeric)) {
    return '-';
  }
  const sign = numeric > 0 ? '+' : '';
  return `${sign}${numeric.toFixed(2)}%`;
};

export const MarketReviewReportView: React.FC<MarketReviewReportViewProps> = ({
  report,
  recordId,
  content: providedContent,
  payload: providedPayload,
  reportLanguage = 'zh',
  className = '',
  onOpenRunFlow,
}) => {
  const normalizedReportLanguage = normalizeReportLanguage(reportLanguage);
  const text = getReportText(normalizedReportLanguage);
  const runFlowText = UI_TEXT[normalizedReportLanguage === 'ko' ? 'en' : normalizedReportLanguage];
  const marketReviewText = MARKET_REVIEW_TEXT[normalizedReportLanguage];
  const [loadedMarkdown, setLoadedMarkdown] = useState<LoadedMarkdown | null>(null);
  const [loadError, setLoadError] = useState<LoadError | null>(null);
  const [copiedType, setCopiedType] = useState<CopyType | null>(null);
  const summary = report?.summary;
  const meta = report?.meta;
  const contextPayload = report?.details?.contextSnapshot?.marketReviewPayload;
  const marketReviewPayload = providedPayload ?? (isMarketReviewPayload(contextPayload) ? contextPayload : null);
  const loadedContent = loadedMarkdown && loadedMarkdown.recordId === recordId ? loadedMarkdown.content : '';
  const content = providedContent ?? marketReviewPayload?.markdownReport ?? loadedContent;
  const error = loadError && loadError.recordId === recordId ? loadError.message : null;
  const hasStructuredContent = Boolean(marketReviewPayload?.sections?.length || marketReviewPayload?.markets);
  const isLoading = Boolean(recordId && !providedContent && !hasStructuredContent && loadedMarkdown?.recordId !== recordId && !error);
  const displayTitle = marketReviewPayload?.rootTitle || marketReviewPayload?.title || meta?.stockName || 'Market Review';
  const structuredContent = useMemo(
    () => stripTopHeading(content, displayTitle),
    [content, displayTitle],
  );
  const sections = useMemo(
    () => {
      const payloadSections = getPayloadSections(marketReviewPayload);
      return payloadSections.length > 0 ? payloadSections : splitMarketReviewSections(structuredContent);
    },
    [marketReviewPayload, structuredContent],
  );
  const structuredMarketData = useMemo(
    () => getStructuredMarketData(marketReviewPayload),
    [marketReviewPayload],
  );
  const showStructuredMarketTitles = Boolean(marketReviewPayload?.markets);
  const canOpenRunFlow = recordId !== undefined && onOpenRunFlow;

  useEffect(() => {
    if (!recordId || providedContent || hasStructuredContent) {
      return undefined;
    }

    let isMounted = true;

    historyApi.getMarkdown(recordId)
      .then((markdownContent) => {
        if (isMounted) {
          setLoadedMarkdown({ recordId, content: markdownContent });
          setLoadError(null);
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          setLoadError({
            recordId,
            message: err instanceof Error ? err.message : text.loadReportFailed,
          });
        }
      });

    return () => {
      isMounted = false;
    };
  }, [hasStructuredContent, providedContent, recordId, text.loadReportFailed]);

  const handleCopy = useCallback(async (type: CopyType) => {
    if (!content) {
      return;
    }
    try {
      const value = type === 'markdown' ? content : markdownToPlainText(content);
      await navigator.clipboard.writeText(value);
      setCopiedType(type);
      window.setTimeout(() => setCopiedType(null), 2000);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  }, [content]);

  const insightCards = useMemo(() => [
    {
      icon: FileText,
      label: marketReviewText.reviewSummary,
      value: summary?.analysisSummary || marketReviewText.noReviewSummary,
    },
    {
      icon: Gauge,
      label: text.marketSentiment,
      value: summary?.sentimentScore !== undefined
        ? `${summary.sentimentScore} / 100`
        : marketReviewText.noSentimentScore,
    },
    {
      icon: Layers,
      label: marketReviewText.rotationAndFunds,
      value: summary?.operationAdvice || marketReviewText.noRotationView,
    },
    {
      icon: ShieldAlert,
      label: marketReviewText.riskAndWatch,
      value: summary?.trendPrediction || marketReviewText.noRiskWatch,
    },
  ], [marketReviewText, summary, text.marketSentiment]);

  return (
    <div className={`animate-fade-in space-y-4 pb-8 ${className}`}>
      <Card variant="gradient" padding="md" className="home-report-hero text-left">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-2 inline-flex items-center gap-2 text-xs font-semibold text-secondary-text">
              <BarChart3 className="h-4 w-4" aria-hidden="true" />
              <span>MARKET REVIEW</span>
            </div>
            <h2 className="text-[26px] font-bold leading-tight text-foreground sm:text-[30px]">
              {displayTitle}
            </h2>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-text">
              {meta?.stockCode ? (
                <span className="home-accent-chip px-2 py-0.5 font-mono">{meta.stockCode}</span>
              ) : null}
              {meta?.createdAt ? <span>{new Date(meta.createdAt).toLocaleString()}</span> : null}
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <ShareImageButton
              recordId={recordId}
              reportTitle={displayTitle}
              reportLanguage={reportLanguage}
            />
            {canOpenRunFlow ? (
              <Tooltip content={runFlowText['runFlow.open']}>
                <span className="inline-flex">
                  <button
                    type="button"
                    onClick={() => onOpenRunFlow(recordId)}
                    className="home-surface-button flex h-10 w-10 items-center justify-center rounded-lg text-secondary-text hover:text-foreground"
                    aria-label={formatUiText(runFlowText['runFlow.openHistoryAria'], { recordId })}
                  >
                    <Workflow className="h-5 w-5" aria-hidden="true" />
                  </button>
                </span>
              </Tooltip>
            ) : null}
            <Tooltip content={text.copyMarkdownSource}>
              <span className="inline-flex">
                <button
                  type="button"
                  onClick={() => void handleCopy('markdown')}
                  disabled={isLoading || !content || copiedType !== null}
                  className="home-surface-button flex h-10 w-10 items-center justify-center rounded-lg text-secondary-text hover:text-foreground disabled:opacity-50"
                  aria-label={text.copyMarkdownSource}
                >
                  {copiedType === 'markdown' ? (
                    <svg className="h-5 w-5 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <Clipboard className="h-5 w-5" aria-hidden="true" />
                  )}
                </button>
              </span>
            </Tooltip>
            <Tooltip content={text.copyPlainText}>
              <span className="inline-flex">
                <button
                  type="button"
                  onClick={() => void handleCopy('text')}
                  disabled={isLoading || !content || copiedType !== null}
                  className="home-surface-button flex h-10 w-10 items-center justify-center rounded-lg text-secondary-text hover:text-foreground disabled:opacity-50"
                  aria-label={text.copyPlainText}
                >
                  {copiedType === 'text' ? (
                    <svg className="h-5 w-5 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <FileText className="h-5 w-5" aria-hidden="true" />
                  )}
                </button>
              </span>
            </Tooltip>
          </div>
        </div>
      </Card>

      {summary ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {insightCards.map(({ icon: Icon, label, value }) => (
            <Card key={label} variant="bordered" padding="sm" className="home-panel-card text-left">
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <p className="label-uppercase">{label}</p>
                  <p className="mt-2 line-clamp-4 text-sm leading-6 text-foreground">{value}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : null}

      {structuredMarketData.length > 0 ? (
        <Card variant="bordered" padding="md" className="home-panel-card text-left">
          <div className="mb-3 flex items-center gap-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <BarChart3 className="h-4 w-4" aria-hidden="true" />
            </span>
            <h3 className="text-base font-semibold text-foreground">{marketReviewText.structuredMarketData}</h3>
          </div>
          <div className="space-y-5">
            {structuredMarketData.map((marketData) => (
              <div key={marketData.id} className="space-y-3">
                {showStructuredMarketTitles ? (
                  <h4 className="text-sm font-semibold text-foreground">{marketData.title}</h4>
                ) : null}
                {(() => {
                  // Issue #1584: optional market summary chips (all fields may be null).
                  const summary = marketData.summary;
                  if (!summary) {
                    return null;
                  }
                  const summaryChips = [
                    {
                      label: marketReviewText.temperature,
                      value: summary.temperature !== null && summary.temperature !== undefined
                        ? String(summary.temperature)
                        : null,
                    },
                    { label: marketReviewText.marketStatus, value: summary.marketStatus || null },
                    { label: marketReviewText.positionAdvice, value: summary.positionAdvice || null },
                    { label: marketReviewText.coreConclusion, value: summary.coreConclusion || null },
                  ].filter((chip) => chip.value);
                  if (summaryChips.length === 0) {
                    return null;
                  }
                  return (
                    <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
                      {summaryChips.map((chip) => (
                        <div key={chip.label} className="rounded-lg border border-subtle p-3">
                          <p className="label-uppercase">{chip.label}</p>
                          <p className="mt-1 break-words font-semibold text-foreground">{chip.value}</p>
                        </div>
                      ))}
                    </div>
                  );
                })()}
                {marketData.breadth ? (
                  <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
                    <div className="rounded-lg border border-subtle p-3">
                      <p className="label-uppercase">{marketReviewText.advancers}</p>
                      <p className="mt-1 font-semibold text-foreground">
                        {formatMarketCount(marketData.breadth.upCount)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-subtle p-3">
                      <p className="label-uppercase">{marketReviewText.decliners}</p>
                      <p className="mt-1 font-semibold text-foreground">
                        {formatMarketCount(marketData.breadth.downCount)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-subtle p-3">
                      <p className="label-uppercase">{marketReviewText.limitUpDown}</p>
                      <p className="mt-1 font-semibold text-foreground">
                        {formatMarketCount(marketData.breadth.limitUpCount)} /{' '}
                        {formatMarketCount(marketData.breadth.limitDownCount)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-subtle p-3">
                      <p className="label-uppercase">{marketReviewText.turnover}</p>
                      <p className="mt-1 font-semibold text-foreground">
                        {formatMarketAmount(marketData.breadth.totalAmount, marketData.breadth.turnoverUnit)}
                      </p>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-secondary-text">{marketReviewText.noBreadthData}</p>
                )}
                {marketData.breadth?.divergenceDiagnosis ? (
                  <p className="rounded-lg border border-subtle bg-primary/5 p-3 text-sm leading-6 text-secondary-text">
                    <span className="font-semibold text-foreground">{marketReviewText.divergenceDiagnosis}</span>
                    {': '}
                    <span>{marketData.breadth.divergenceDiagnosis}</span>
                  </p>
                ) : null}
                {(() => {
                  const showMaColumn = hasAnyMaStatus(marketData.indices);
                  if (marketData.indices.length === 0) {
                    return null;
                  }
                  return (
                    <div className="overflow-x-auto">
                      <table className="min-w-full text-sm">
                        <thead className="text-left text-xs uppercase text-muted-text">
                          <tr>
                            <th className="px-2 py-2">{marketReviewText.index}</th>
                            <th className="px-2 py-2">{marketReviewText.last}</th>
                            <th className="px-2 py-2">{marketReviewText.change}</th>
                            <th className="px-2 py-2">{marketReviewText.highLow}</th>
                            {showMaColumn ? (
                              <th className="px-2 py-2">{marketReviewText.maStatusColumn}</th>
                            ) : null}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-subtle">
                          {marketData.indices.map((index) => {
                            const maStatusText = formatMaStatus(index.maStatus);
                            return (
                              <tr key={index.code || index.name}>
                                <td className="px-2 py-2">
                                  <div className="font-medium text-foreground">{index.name}</div>
                                  {index.comment ? (
                                    <div className="mt-0.5 text-xs text-muted-text">{index.comment}</div>
                                  ) : null}
                                </td>
                                <td className="px-2 py-2 text-secondary-text">{formatMarketNumber(index.current)}</td>
                                <td className="px-2 py-2 text-secondary-text">{formatMarketPercent(index.changePct)}</td>
                                <td className="px-2 py-2 text-secondary-text">{formatMarketHighLow(index.high, index.low)}</td>
                                {showMaColumn ? (
                                  <td className="px-2 py-2 font-mono text-secondary-text">{maStatusText || '-'}</td>
                                ) : null}
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  );
                })()}
                {(() => {
                  const boardTypes = [{
                    key: 'sectors' as const,
                    title: marketReviewText.industryBoards,
                    rankings: marketData.sectors,
                  }, {
                    key: 'concepts' as const,
                    title: marketReviewText.conceptBoards,
                    rankings: marketData.concepts,
                  }].filter(({ rankings }) => hasRankingRows(rankings));
                  if (boardTypes.length === 0) {
                    return null;
                  }
                  const renderPanels = (
                    key: string,
                    title: string,
                    rankings: MarketReviewPayload['sectors'],
                  ) => (['top', 'bottom'] as const).map((side) => {
                    const rows = rankings?.[side] || [];
                    if (rows.length === 0) {
                      return null;
                    }
                    return (
                      <div key={`${key}-${side}`} className="rounded-lg border border-subtle p-3">
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <p className="label-uppercase">{title}</p>
                          <span className="text-xs text-secondary-text">
                            {side === 'top' ? marketReviewText.leading : marketReviewText.lagging}
                          </span>
                        </div>
                        <div className="space-y-1.5">
                          {rows.slice(0, 5).map((item, index) => (
                            <div key={`${item.name}-${index}`} className="flex items-center justify-between gap-3 text-sm">
                              <span className="min-w-0 truncate text-foreground">{item.name}</span>
                              <span className="shrink-0 font-mono text-secondary-text">
                                {formatRankingChange(item.changePct)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  });
                  // 两类板块都存在时按 行业|概念 左右并列，节省纵向空间；只有一类时保留 领涨|领跌 横向布局。
                  if (boardTypes.length >= 2) {
                    return (
                      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                        {boardTypes.map(({ key, title, rankings }) => (
                          <div key={key} className="space-y-3">
                            {renderPanels(key, title, rankings)}
                          </div>
                        ))}
                      </div>
                    );
                  }
                  const { key, title, rankings } = boardTypes[0];
                  return (
                    <div key={key} className="grid grid-cols-1 gap-3 md:grid-cols-2">
                      {renderPanels(key, title, rankings)}
                    </div>
                  );
                })()}
                {(() => {
                  // Issue #1584: optional style rotation, catalysts, next-day plan and cross-market note.
                  const rotation = marketData.styleRotation;
                  const rotationSignal = rotation?.signal || null;
                  const rotationComment = rotation?.comment || null;
                  if (rotationSignal || rotationComment) {
                    return (
                      <div className="rounded-lg border border-subtle p-3 text-sm">
                        <p className="label-uppercase">{marketReviewText.styleRotation}</p>
                        <p className="mt-1 break-words text-foreground">
                          {rotationSignal ? <span className="font-semibold">{rotationSignal}</span> : null}
                          {rotationSignal && rotationComment ? <span className="text-muted-text"> · </span> : null}
                          {rotationComment ? <span className="text-secondary-text">{rotationComment}</span> : null}
                        </p>
                      </div>
                    );
                  }
                  return null;
                })()}
                {(() => {
                  const catalysts = (marketData.catalysts || []).filter((item) => item?.title);
                  if (catalysts.length === 0) {
                    return null;
                  }
                  return (
                    <div className="rounded-lg border border-subtle p-3">
                      <p className="label-uppercase">{marketReviewText.catalysts}</p>
                      <div className="mt-2 space-y-2">
                        {catalysts.slice(0, 8).map((catalyst, index) => {
                          const directionText = formatCatalystDirection(catalyst.direction, marketReviewText);
                          const directionTone = catalyst.direction === 'bullish'
                            ? 'text-success'
                            : catalyst.direction === 'bearish'
                              ? 'text-danger'
                              : 'text-secondary-text';
                          const catalystMeta = [catalyst.scope, catalyst.persistence].filter(Boolean).join(' · ');
                          return (
                            <div
                              key={`${catalyst.title}-${index}`}
                              className="flex items-start justify-between gap-3 text-sm"
                            >
                              <div className="min-w-0">
                                <span className="font-medium text-foreground">{catalyst.title}</span>
                                {catalystMeta ? (
                                  <span className="ml-2 text-xs text-muted-text">{catalystMeta}</span>
                                ) : null}
                              </div>
                              <div className="flex shrink-0 items-center gap-1.5 text-xs">
                                {directionText ? (
                                  <span className={`font-medium ${directionTone}`}>{directionText}</span>
                                ) : null}
                                {catalyst.digested === true ? (
                                  <span className="rounded bg-primary/10 px-1.5 py-0.5 text-secondary-text">
                                    {marketReviewText.digestedLabel}
                                  </span>
                                ) : null}
                                {catalyst.digested === false ? (
                                  <span className="rounded bg-primary/10 px-1.5 py-0.5 text-muted-text">
                                    {marketReviewText.notDigestedLabel}
                                  </span>
                                ) : null}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}
                {(() => {
                  const plan = marketData.nextDayPlan;
                  if (!plan) {
                    return null;
                  }
                  const watchlist = (plan.watchlist || []).filter((item) => item);
                  const hasPlan = watchlist.length > 0 || plan.positionAdvice || plan.invalidation || plan.notes;
                  if (!hasPlan) {
                    return null;
                  }
                  return (
                    <div className="rounded-lg border border-subtle p-3 text-sm">
                      <p className="label-uppercase">{marketReviewText.nextDayPlan}</p>
                      <div className="mt-2 space-y-1.5">
                        {watchlist.map((item, index) => (
                          <div key={`${item}-${index}`} className="flex items-start gap-2 text-secondary-text">
                            <span className="text-primary">·</span>
                            <span className="min-w-0 break-words">{item}</span>
                          </div>
                        ))}
                        {plan.positionAdvice ? (
                          <p className="break-words text-secondary-text">{plan.positionAdvice}</p>
                        ) : null}
                        {plan.invalidation ? (
                          <p className="break-words text-xs text-muted-text">
                            <span>{marketReviewText.invalidation}</span>
                            <span>{': '}</span>
                            <span>{plan.invalidation}</span>
                          </p>
                        ) : null}
                      </div>
                    </div>
                  );
                })()}
                {marketData.crossMarketNote ? (
                  <p className="rounded-lg border border-subtle p-3 text-sm leading-6 text-secondary-text">
                    <span className="font-semibold text-foreground">{marketReviewText.crossMarketNote}</span>
                    {': '}
                    <span>{marketData.crossMarketNote}</span>
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {isLoading ? (
        <Card variant="bordered" padding="md" className="home-panel-card text-left">
          <div className="flex h-64 flex-col items-center justify-center">
            <div className="home-spinner h-10 w-10 animate-spin border-[3px]" />
            <p className="mt-4 text-sm text-secondary-text">{text.loadingReport}</p>
          </div>
        </Card>
      ) : error ? (
        <Card variant="bordered" padding="md" className="home-panel-card text-left">
          <div className="flex h-64 flex-col items-center justify-center">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-danger/10">
              <ShieldAlert className="h-6 w-6 text-danger" aria-hidden="true" />
            </div>
            <p className="text-sm text-danger">{error}</p>
          </div>
        </Card>
      ) : (
        <div data-testid="market-review-report" className="space-y-4">
          {sections.map(({ id, title, content: sectionContent, icon: Icon }) => (
            <Card key={id} variant="bordered" padding="md" className="home-panel-card text-left">
              <div className="mb-3 flex items-center gap-2">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </span>
                <h3 className="text-base font-semibold text-foreground">{title}</h3>
              </div>
              <ReportMarkdownBody
                content={sectionContent}
                className="market-review-markdown"
              />
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};
