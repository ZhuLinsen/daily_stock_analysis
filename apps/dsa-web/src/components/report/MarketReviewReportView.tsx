import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { BarChart3, Clipboard, FileText, Gauge, Layers, ShieldAlert, TrendingUp, WalletCards, Workflow } from 'lucide-react';
import { historyApi } from '../../api/history';
import { formatUiText, UI_TEXT } from '../../i18n/uiText';
import type {
  AnalysisReport,
  MarketReviewPayload,
  MarketReviewPayloadSection,
  ReportLanguage,
} from '../../types/analysis';
import { markdownToPlainText } from '../../utils/markdown';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Card } from '../common';
import { Tooltip } from '../common/Tooltip';
import { ReportMarkdownBody } from './ReportMarkdownBody';
import { type WorkbenchLabels } from './MarketReviewWorkbench';
import {
  MarketReviewMarketModules,
  type StructuredMarketData,
} from './MarketReviewModules';
import { orderMarketEntries } from './marketReviewModuleMatching';

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
const isMarketReviewPayload = (value: unknown): value is MarketReviewPayload =>
  Boolean(value && typeof value === 'object');

// 后端注入 markdown 报告的工作台段标题（固定字面量，与
// src/core/market_review_workbench.py 的 WORKBENCH_HEADING_* 同步）。
// 存在结构化工作台字段时过滤该 markdown 段，避免与结构化卡片重复展示；
// 纯 markdown 降级路径（无结构化字段）保留该段。
// 与后端注入块标题字面量同步（src/core/market_review_workbench.py SUMMARY_HEADING_*）；
// "复盘工作台"为开发期过渡记录的旧字面量，保留以兼容
const WORKBENCH_SECTION_TITLES = new Set([
  '一句话结论',
  'one-line conclusion',
  '复盘工作台',
  'review workbench',
  '복기 워크벤치',
]);

// 判据需与后端注入工作台 markdown 块的条件保持一致（含仅指数均线/点评、
// 仅数据质量说明的降级形态），否则注入段会漏过滤造成重复展示
const hasWorkbenchData = (payload?: MarketReviewPayload | null): boolean =>
  Boolean(
    payload?.summary
    || payload?.catalysts?.length
    || payload?.nextSessionPlan
    || payload?.styleRotation
    || payload?.breadth?.divergenceDiagnosis
    || payload?.dataQuality?.notes?.length
    || payload?.indices?.some((index) => index.technicalStatus || index.comment),
  );

// 整个 payload 的模式开关：任一市场携带工作台字段即进入模块化展示；
// 旧记录/旧后端 → 走既有 Markdown/sections 展示路径，零变化
const isWorkbenchPayload = (payload?: MarketReviewPayload | null): boolean =>
  hasWorkbenchData(payload)
  || Object.values(payload?.markets ?? {}).some((marketPayload) => hasWorkbenchData(marketPayload));

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

  return getSingleMarketSections(payload)
    .map((section, index) => ({
      id: `${section.key || index}-${normalizeHeading(section.title).replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-') || 'section'}`,
      title: section.title || 'Review',
      content: section.markdown,
      icon: getSectionIcon(section.title || ''),
    }));
};

/** \u5355\u5e02\u573a payload \u7684\u539f\u59cb\uff08\u672a\u52a0\u5e02\u573a\u524d\u7f00\uff09\u53d9\u4e8b sections\uff1a\u8fc7\u6ee4\u7a7a\u6bb5/\u91cd\u590d\u6807\u9898/\u6ce8\u5165\u7684\u7ed3\u8bba\u6bb5 */
const getSingleMarketSections = (
  payload: MarketReviewPayload,
): MarketReviewPayloadSection[] => {
  const payloadTitle = normalizeHeading(payload.title || '');
  const hideWorkbenchSection = hasWorkbenchData(payload);
  return (payload.sections || [])
    .filter((section: MarketReviewPayloadSection) => section.markdown?.trim())
    .filter((section: MarketReviewPayloadSection) => normalizeHeading(section.title || '') !== payloadTitle)
    .filter((section: MarketReviewPayloadSection) => (
      !hideWorkbenchSection || !WORKBENCH_SECTION_TITLES.has(normalizeHeading(section.title || ''))
    ));
};

const hasRankingRows = (rankings?: MarketReviewPayload['sectors']): boolean =>
  Boolean(rankings?.top?.length || rankings?.bottom?.length);

const hasStructuredMarketData = (payload?: MarketReviewPayload | null): boolean =>
  Boolean(
    payload?.breadth
    || payload?.indices?.length
    || hasRankingRows(payload?.sectors)
    || hasRankingRows(payload?.concepts)
    || hasWorkbenchData(payload),
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
        nextSessionPlan: marketPayload.nextSessionPlan,
        dataQuality: marketPayload.dataQuality,
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
    nextSessionPlan: payload.nextSessionPlan,
    dataQuality: payload.dataQuality,
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

interface MarketModuleGroup {
  market: StructuredMarketData;
  sections: MarketReviewPayloadSection[];
  title?: string;
}

/** 模块化路径的数据分组：单市场一组（无标题），多市场按后端区域顺序分组 */
const getMarketModuleGroups = (payload?: MarketReviewPayload | null): MarketModuleGroup[] => {
  if (!payload) {
    return [];
  }
  if (payload.markets) {
    const markets = getStructuredMarketData(payload);
    const byId = new Map(markets.map((market) => [market.id, market]));
    return orderMarketEntries(payload.markets)
      .map(([region, marketPayload]): MarketModuleGroup | null => {
        const market = byId.get(region);
        const sections = getSingleMarketSections(marketPayload);
        // 防御兜底：混合 payload 中无任何结构化/工作台字段、仅有叙事
        // sections 的市场（降级形态）不得被静默丢弃——以空结构化数据
        // 渲染其叙事正文；两者皆无才跳过
        if (!market && sections.length === 0) {
          return null;
        }
        return {
          market: market ?? {
            id: region,
            title: marketPayload.title || region.toUpperCase(),
            indices: [],
          },
          sections,
          title: marketPayload.title || region.toUpperCase(),
        };
      })
      .filter((group): group is MarketModuleGroup => group !== null);
  }
  const markets = getStructuredMarketData(payload);
  if (!markets.length) {
    return [];
  }
  return [{ market: markets[0], sections: getSingleMarketSections(payload) }];
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
  workbench: WorkbenchLabels;
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
    workbench: {
      temperature: '市场温度',
      marketState: '市场状态',
      suggestedPosition: '建议仓位',
      structureNote: '结构观察',
      weightNote: '权重观察',
      divergence: '宽度诊断',
      rotationStrong: '走强',
      rotationWeak: '承压',
      catalystTitle: '消息',
      nature: '性质',
      scope: '影响范围',
      duration: '持续性',
      digestion: '消化状态',
      catalystComment: '点评',
      positionAdvice: '仓位',
      focus: '关注',
      avoid: '回避',
      keyLevels: '关键位',
      riskTriggers: '风险触发',
      dataQualityNotes: '数据说明',
      moduleConclusion: '一句话结论',
      moduleIndices: '核心指数表现',
      moduleBreadth: '市场宽度与分化',
      moduleSectors: '行业板块与题材主线',
      moduleCatalysts: '消息面与政策催化',
      modulePlan: '明日交易计划',
      close: '收盘',
      amountHeader: '成交额',
      indexHeader: '指数',
      changeHeader: '涨跌幅',
      maStatusHeader: '均线状态',
      sectorHeader: '板块',
      leaderHeader: '领涨股',
      persistenceHeader: '持续性',
      commentHeader: '点评',
      rotationJudgment: '判断',
      leading: '最强板块（前5）',
      lagging: '最弱板块（前5）',
    },
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
    workbench: {
      temperature: 'Temperature',
      marketState: 'Market State',
      suggestedPosition: 'Suggested Position',
      structureNote: 'Structure',
      weightNote: 'Heavyweights',
      divergence: 'Breadth Diagnosis',
      rotationStrong: 'Strong:',
      rotationWeak: 'Weak:',
      catalystTitle: 'News',
      nature: 'Nature',
      scope: 'Scope',
      duration: 'Duration',
      digestion: 'Digestion',
      catalystComment: 'Comment',
      positionAdvice: 'Position',
      focus: 'Focus',
      avoid: 'Avoid',
      keyLevels: 'Key Levels',
      riskTriggers: 'Risk Triggers',
      dataQualityNotes: 'Data Notes',
      moduleConclusion: 'One-Line Conclusion',
      moduleIndices: 'Core Index Performance',
      moduleBreadth: 'Breadth & Divergence',
      moduleSectors: 'Sectors & Themes',
      moduleCatalysts: 'News & Policy Catalysts',
      modulePlan: 'Next-Session Trading Plan',
      close: 'Close',
      amountHeader: 'Turnover',
      indexHeader: 'Index',
      changeHeader: 'Change',
      maStatusHeader: 'MA Status',
      sectorHeader: 'Sector',
      leaderHeader: 'Leader',
      persistenceHeader: 'Persistence',
      commentHeader: 'Comment',
      rotationJudgment: 'View',
      leading: 'Strongest Sectors (Top 5)',
      lagging: 'Weakest Sectors (Top 5)',
    },
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
    workbench: {
      temperature: '시장 온도',
      marketState: '시장 상태',
      suggestedPosition: '제안 포지션',
      structureNote: '구조 관찰',
      weightNote: '대형주 관찰',
      divergence: '괴리 진단',
      rotationStrong: '강세',
      rotationWeak: '약세',
      catalystTitle: '뉴스',
      nature: '성격',
      scope: '영향 범위',
      duration: '지속성',
      digestion: '소화 상태',
      catalystComment: '코멘트',
      positionAdvice: '포지션',
      focus: '관심',
      avoid: '회피',
      keyLevels: '주요 레벨',
      riskTriggers: '리스크 트리거',
      dataQualityNotes: '데이터 참고',
      moduleConclusion: '한 줄 결론',
      moduleIndices: '핵심 지수 동향',
      moduleBreadth: '시장 폭과 괴리',
      moduleSectors: '업종·테마 주도주',
      moduleCatalysts: '뉴스·정책 촉매',
      modulePlan: '다음 거래일 계획',
      close: '종가',
      amountHeader: '거래대금',
      indexHeader: '지수',
      changeHeader: '등락률',
      maStatusHeader: '이평선 상태',
      sectorHeader: '섹터',
      leaderHeader: '주도주',
      persistenceHeader: '지속성',
      commentHeader: '코멘트',
      rotationJudgment: '판단',
      leading: '강세 섹터 (Top 5)',
      lagging: '약세 섹터 (Top 5)',
    },
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
  // 模块化展示模式（Issue #1584）：任一市场携带工作台字段即按模块分卡渲染；
  // 否则（旧记录/旧后端/纯 markdown）走既有展示路径，零变化
  const workbenchMode = isWorkbenchPayload(marketReviewPayload);
  const moduleGroups = useMemo(
    () => (workbenchMode ? getMarketModuleGroups(marketReviewPayload) : []),
    [workbenchMode, marketReviewPayload],
  );
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
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
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

      {/* 工作台模式下隐藏洞察卡：其 sentimentScore 与模块①温度会同屏出现
          两个不同分数，且"复盘摘要"卡内容为整份 markdown（D7 去重） */}
      {summary && !workbenchMode ? (
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

      {workbenchMode ? (
        <div data-testid="market-review-modules" className="space-y-4">
          {moduleGroups.map((group) => (
            <MarketReviewMarketModules
              key={group.market.id}
              market={group.market}
              sections={group.sections}
              labels={marketReviewText.workbench}
              language={normalizedReportLanguage === 'zh' ? 'zh' : 'en'}
              conceptTitle={marketReviewText.conceptBoards}
              breadthLabels={{
                advancers: marketReviewText.advancers,
                decliners: marketReviewText.decliners,
                limitUpDown: marketReviewText.limitUpDown,
                turnover: marketReviewText.turnover,
              }}
              title={group.title}
              getNarrativeIcon={getSectionIcon}
            />
          ))}
        </div>
      ) : null}

      {!workbenchMode && structuredMarketData.length > 0 ? (
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
                {marketData.indices.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead className="text-left text-xs uppercase text-muted-text">
                        <tr>
                          <th className="px-2 py-2">{marketReviewText.index}</th>
                          <th className="px-2 py-2">{marketReviewText.last}</th>
                          <th className="px-2 py-2">{marketReviewText.change}</th>
                          <th className="px-2 py-2">{marketReviewText.highLow}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-subtle">
                        {marketData.indices.map((index) => (
                          <tr key={index.code || index.name}>
                            <td className="px-2 py-2 font-medium text-foreground">{index.name}</td>
                            <td className="px-2 py-2 text-secondary-text">{formatMarketNumber(index.current)}</td>
                            <td className="px-2 py-2 text-secondary-text">{formatMarketPercent(index.changePct)}</td>
                            <td className="px-2 py-2 text-secondary-text">{formatMarketHighLow(index.high, index.low)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
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
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {/* 模块化路径的叙事卡在各市场分组内渲染；本区块仅服务既有展示路径 */}
      {workbenchMode ? null : isLoading ? (
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
