import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, BarChart3, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { decisionSignalsApi } from '../api/decisionSignals';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { historyApi } from '../api/history';
import {
  ApiErrorAlert,
  AppPage,
  Card,
  ConfirmDialog,
  Drawer,
  EmptyState,
  InlineAlert,
  PageHeader,
  Pagination,
} from '../components/common';
import {
  DecisionSignalCard,
  DecisionSignalDetails,
} from '../components/decision-signals/DecisionSignalDisplay';
import { DecisionSignalTimeline } from '../components/decision-signals/DecisionSignalTimeline';
import { StockAutocomplete } from '../components/StockAutocomplete';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { useStockIndex } from '../hooks/useStockIndex';
import type { UiTextKey } from '../i18n/uiText';
import type { DecisionAction, MarketPhaseValue, StockBarItem } from '../types/analysis';
import type {
  DecisionSignalItem,
  DecisionSignalFeedbackItem,
  DecisionSignalFeedbackValue,
  DecisionSignalListParams,
  DecisionSignalMarket,
  DecisionSignalOutcomeItem,
  DecisionSignalOutcomeStatsResponse,
  DecisionSignalReassessResponse,
  DecisionSignalSourceType,
  DecisionSignalStatus,
  DecisionProfile,
  DecisionProfileDisplay,
} from '../types/decisionSignals';
import type { Market, StockIndexItem } from '../types/stockIndex';
import { cn } from '../utils/cn';
import { buildDecisionActionLabelMap } from '../utils/decisionAction';
import {
  getDecisionSignalMarketLabel,
  getDecisionSignalMarketPhaseLabel,
  getDecisionSignalSourceTypeLabel,
} from '../utils/decisionSignalLabels';

const PAGE_SIZE = 20;
const TIMELINE_PAGE_SIZE = 100;
const STOCK_CANDIDATE_LIMIT = 8;
const DAY_MS = 86400_000;

type ListFilters = {
  market: '' | DecisionSignalMarket;
  stockCode: string;
  action: '' | DecisionAction;
  marketPhase: '' | MarketPhaseValue;
  sourceType: '' | DecisionSignalSourceType;
  sourceReportId: string;
  status: '' | DecisionSignalStatus;
};

type TimelineRange = '30d' | '90d' | '180d';
type TimelineStatusFilter = 'all' | 'active';

type TimelineFilters = {
  market: '' | DecisionSignalMarket;
  range: TimelineRange;
  status: TimelineStatusFilter;
  decisionProfile: '' | DecisionProfileDisplay;
};

type TimelineMarketSource = 'context' | 'user' | null;

type TimelineFilterUpdate = {
  filters: TimelineFilters;
  marketSource: TimelineMarketSource;
};

type AppliedTimelineContext = TimelineFilters & {
  stockCode: string;
};

type StockContext = {
  code: string;
  displayCode?: string;
  name?: string;
  market?: DecisionSignalMarket;
};

type StockCandidate = StockContext & {
  source: 'history' | 'popular';
};

type PendingStatusChange = {
  item: DecisionSignalItem;
  status: Extract<DecisionSignalStatus, 'closed' | 'invalidated' | 'archived'>;
  message: string;
};

type SelectedSignal = {
  item: DecisionSignalItem;
  source: 'list' | 'latest' | 'timeline';
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const MARKET_OPTIONS: DecisionSignalMarket[] = ['cn', 'hk', 'us', 'jp', 'kr', 'tw'];
const ACTION_OPTIONS: DecisionAction[] = ['buy', 'add', 'hold', 'reduce', 'sell', 'watch', 'avoid', 'alert'];
const PHASE_OPTIONS: MarketPhaseValue[] = ['premarket', 'intraday', 'lunch_break', 'closing_auction', 'postmarket', 'non_trading', 'unknown'];
const SOURCE_OPTIONS: DecisionSignalSourceType[] = ['analysis', 'agent', 'alert', 'market_review', 'manual'];
const STATUS_OPTIONS: DecisionSignalStatus[] = ['active', 'expired', 'invalidated', 'closed', 'archived'];

const STATUS_ACTIONS: Array<PendingStatusChange['status']> = ['closed', 'invalidated', 'archived'];
const REASSESS_PROFILES: DecisionProfile[] = ['conservative', 'balanced', 'aggressive'];

const STATUS_LABEL_KEYS: Record<DecisionSignalStatus, UiTextKey> = {
  active: 'decisionSignals.active',
  expired: 'decisionSignals.expired',
  invalidated: 'decisionSignals.invalidated',
  closed: 'decisionSignals.closed',
  archived: 'decisionSignals.archived',
};

const STATUS_ACTION_LABEL_KEYS: Record<PendingStatusChange['status'], UiTextKey> = {
  closed: 'decisionSignals.close',
  invalidated: 'decisionSignals.invalidate',
  archived: 'decisionSignals.archive',
};

const STATUS_ACTION_CONFIRM_KEYS: Record<PendingStatusChange['status'], UiTextKey> = {
  closed: 'decisionSignals.closeConfirm',
  invalidated: 'decisionSignals.invalidateConfirm',
  archived: 'decisionSignals.archiveConfirm',
};

const DEFAULT_LIST_FILTERS: ListFilters = {
  market: '',
  stockCode: '',
  action: '',
  marketPhase: '',
  sourceType: '',
  sourceReportId: '',
  status: 'active',
};

const DEFAULT_TIMELINE_FILTERS: TimelineFilters = {
  market: '',
  range: '90d',
  status: 'all',
  decisionProfile: '',
};

const TIMELINE_RANGE_DAYS: Record<TimelineRange, number> = {
  '30d': 30,
  '90d': 90,
  '180d': 180,
};

function parseSourceReportId(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

function getInitialFilters(search = typeof window === 'undefined' ? '' : window.location.search): ListFilters {
  const params = new URLSearchParams(search);
  const sourceReportId = parseSourceReportId(params.get('sourceReportId') ?? params.get('source_report_id') ?? '');
  if (sourceReportId === undefined) return DEFAULT_LIST_FILTERS;
  return {
    ...DEFAULT_LIST_FILTERS,
    sourceReportId: String(sourceReportId),
  };
}

function toListParams(filters: ListFilters, page: number): DecisionSignalListParams {
  const sourceReportId = parseSourceReportId(filters.sourceReportId);
  if (sourceReportId !== undefined) {
    return {
      sourceReportId,
      sourceType: 'analysis',
      page,
      pageSize: PAGE_SIZE,
    };
  }

  return {
    market: filters.market || undefined,
    stockCode: filters.stockCode.trim() || undefined,
    action: filters.action || undefined,
    marketPhase: filters.marketPhase || undefined,
    sourceType: filters.sourceType || undefined,
    status: filters.status || undefined,
    page,
    pageSize: PAGE_SIZE,
  };
}

function refreshLatestSelection(
  current: SelectedSignal | null,
  latestItems: DecisionSignalItem[],
): SelectedSignal | null {
  if (!current || current.source !== 'latest') return current;
  const refreshed = latestItems.find((item) => item.id === current.item.id);
  return refreshed ? { source: 'latest', item: refreshed } : null;
}

function refreshTimelineSelection(
  current: SelectedSignal | null,
  timelineItems: DecisionSignalItem[],
): SelectedSignal | null {
  if (!current || current.source !== 'timeline') return current;
  const refreshed = timelineItems.find((item) => item.id === current.item.id);
  return refreshed ? { source: 'timeline', item: refreshed } : null;
}

function normalizeDecisionSignalMarket(value: unknown): DecisionSignalMarket | undefined {
  const market = String(value ?? '').trim().toUpperCase();
  if (!market || market === 'INDEX' || market === 'ETF' || market === 'UNKNOWN') return undefined;
  if (market === 'CN' || market === 'BSE') return 'cn';
  if (market === 'HK') return 'hk';
  if (market === 'US') return 'us';
  if (market === 'JP') return 'jp';
  if (market === 'KR') return 'kr';
  if (market === 'TW') return 'tw';
  if (MARKET_OPTIONS.includes(market.toLowerCase() as DecisionSignalMarket)) {
    return market.toLowerCase() as DecisionSignalMarket;
  }
  return undefined;
}

function getCandidateKey(candidate: Pick<StockCandidate, 'code' | 'market'>): string {
  const code = candidate.code.trim().toUpperCase();
  return candidate.market ? `${candidate.market}:${code}` : code;
}

function toHistoryCandidate(item: StockBarItem): StockCandidate | null {
  const code = String(item.stockCode || '').trim();
  if (!code || code.toUpperCase() === 'MARKET') return null;
  return {
    code,
    displayCode: code,
    name: item.stockName || undefined,
    market: normalizeDecisionSignalMarket(item.marketPhaseSummary?.market),
    source: 'history',
  };
}

function toPopularCandidates(index: StockIndexItem[], limit = STOCK_CANDIDATE_LIMIT): StockCandidate[] {
  const candidates: StockCandidate[] = [];
  const seen = new Set<string>();
  const sorted = [...index]
    .filter((item) => item.active && item.assetType === 'stock')
    .sort((left, right) => (right.popularity ?? 0) - (left.popularity ?? 0));

  for (const item of sorted) {
    const market = normalizeDecisionSignalMarket(item.market);
    const candidate: StockCandidate = {
      code: item.canonicalCode,
      displayCode: item.displayCode,
      name: item.nameZh,
      market,
      source: 'popular',
    };
    const key = getCandidateKey(candidate);
    if (seen.has(key)) continue;
    seen.add(key);
    candidates.push(candidate);
    if (candidates.length >= limit) break;
  }

  return candidates;
}

function toTimelineParams(filters: TimelineFilters, stockCode: string): DecisionSignalListParams {
  const days = TIMELINE_RANGE_DAYS[filters.range];
  const createdTo = new Date();
  const createdFrom = new Date(createdTo.getTime() - days * DAY_MS);
  return {
    market: filters.market || undefined,
    stockCode,
    createdFrom: createdFrom.toISOString(),
    createdTo: createdTo.toISOString(),
    status: filters.status === 'active' ? 'active' : undefined,
    decisionProfile: filters.decisionProfile || undefined,
    page: 1,
    pageSize: TIMELINE_PAGE_SIZE,
  };
}

function isSameStockContext(
  previousContext: StockContext | null,
  nextContext: StockContext,
): boolean {
  return previousContext?.code.trim().toUpperCase() === nextContext.code.trim().toUpperCase()
    && previousContext?.market === nextContext.market;
}

function buildNextTimelineFilters(
  currentFilters: TimelineFilters,
  previousContext: StockContext | null,
  nextContext: StockContext,
  marketSource: TimelineMarketSource,
): TimelineFilterUpdate {
  if (isSameStockContext(previousContext, nextContext)) {
    return { filters: currentFilters, marketSource };
  }
  if (nextContext.market) {
    return {
      filters: { ...currentFilters, market: nextContext.market },
      marketSource: 'context',
    };
  }
  if (marketSource === 'context') {
    return {
      filters: { ...currentFilters, market: '' },
      marketSource: null,
    };
  }
  return { filters: currentFilters, marketSource };
}

function draftMatchesStockContext(draft: string, context: StockContext | null): context is StockContext {
  if (!context) return false;
  const normalizedDraft = draft.trim().toUpperCase();
  if (!normalizedDraft) return false;
  return normalizedDraft === context.code.trim().toUpperCase()
    || normalizedDraft === String(context.displayCode ?? '').trim().toUpperCase();
}

function formatStatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return Number(value).toFixed(2).replace(/\.?0+$/, '');
}

function formatStatPercent(value: number | null | undefined): string {
  const formatted = formatStatNumber(value);
  return formatted === '-' ? formatted : `${formatted}%`;
}

const DecisionSignalsPage: React.FC = () => {
  const { t } = useUiLanguage();
  const actionLabels = useMemo(() => buildDecisionActionLabelMap(t), [t]);
  const { index: stockIndex } = useStockIndex();
  const [filters, setFilters] = useState<ListFilters>(() => getInitialFilters());
  const [appliedFilters, setAppliedFilters] = useState<ListFilters>(() => getInitialFilters());
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<DecisionSignalItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [selected, setSelected] = useState<SelectedSignal | null>(null);
  const [pendingStatus, setPendingStatus] = useState<PendingStatusChange | null>(null);
  const [statusUpdating, setStatusUpdating] = useState(false);
  const [outcomeStats, setOutcomeStats] = useState<DecisionSignalOutcomeStatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<ParsedApiError | null>(null);
  const [stockDraft, setStockDraft] = useState('');
  const [activeStockContext, setActiveStockContext] = useState<StockContext | null>(null);
  const [historyCandidates, setHistoryCandidates] = useState<StockCandidate[]>([]);
  const [historyCandidatesLoaded, setHistoryCandidatesLoaded] = useState(false);
  const [latestItems, setLatestItems] = useState<DecisionSignalItem[]>([]);
  const [latestSearched, setLatestSearched] = useState(false);
  const [latestLoading, setLatestLoading] = useState(false);
  const [latestError, setLatestError] = useState<ParsedApiError | null>(null);
  const [timelineFilters, setTimelineFilters] = useState<TimelineFilters>(DEFAULT_TIMELINE_FILTERS);
  const [appliedTimelineContext, setAppliedTimelineContext] = useState<AppliedTimelineContext | null>(null);
  const [timelineItems, setTimelineItems] = useState<DecisionSignalItem[]>([]);
  const [timelineSearched, setTimelineSearched] = useState(false);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineError, setTimelineError] = useState<ParsedApiError | null>(null);
  const [timelineTruncated, setTimelineTruncated] = useState(false);
  const [selectedOutcomes, setSelectedOutcomes] = useState<DecisionSignalOutcomeItem[]>([]);
  const [selectedOutcomesLoading, setSelectedOutcomesLoading] = useState(false);
  const [selectedOutcomesError, setSelectedOutcomesError] = useState<ParsedApiError | null>(null);
  const [selectedFeedback, setSelectedFeedback] = useState<DecisionSignalFeedbackItem | null>(null);
  const [selectedFeedbackLoading, setSelectedFeedbackLoading] = useState(false);
  const [selectedFeedbackError, setSelectedFeedbackError] = useState<ParsedApiError | null>(null);
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const [reassessProfile, setReassessProfile] = useState<DecisionProfile>('balanced');
  const [reassessResponse, setReassessResponse] = useState<DecisionSignalReassessResponse | null>(null);
  const [reassessLoading, setReassessLoading] = useState(false);
  const [reassessError, setReassessError] = useState<ParsedApiError | null>(null);
  const requestIdRef = useRef(0);
  const statsRequestIdRef = useRef(0);
  const latestRequestIdRef = useRef(0);
  const timelineRequestIdRef = useRef(0);
  const detailRequestIdRef = useRef(0);
  const reassessRequestIdRef = useRef(0);
  const selectedSignalIdRef = useRef<number | null>(null);
  const statusUpdateInFlightRef = useRef(false);
  const timelineMarketSourceRef = useRef<TimelineMarketSource>(null);

  const popularCandidates = useMemo(
    () => toPopularCandidates(stockIndex, STOCK_CANDIDATE_LIMIT),
    [stockIndex],
  );
  const stockCandidates = historyCandidates.length > 0 ? historyCandidates : popularCandidates;
  const stockCandidateMode: 'history' | 'popular' | 'empty' = historyCandidates.length > 0
    ? 'history'
    : stockCandidates.length > 0
      ? 'popular'
      : 'empty';

  useEffect(() => {
    document.title = t('decisionSignals.pageTitle');
  }, [t]);

  useEffect(() => {
    let mounted = true;
    void historyApi.getStockBarList({ limit: STOCK_CANDIDATE_LIMIT })
      .then((response) => {
        if (!mounted) return;
        const nextCandidates: StockCandidate[] = [];
        const seen = new Set<string>();
        for (const item of response.items) {
          const candidate = toHistoryCandidate(item);
          if (!candidate) continue;
          const key = getCandidateKey(candidate);
          if (seen.has(key)) continue;
          seen.add(key);
          nextCandidates.push(candidate);
          if (nextCandidates.length >= STOCK_CANDIDATE_LIMIT) break;
        }
        setHistoryCandidates(nextCandidates);
      })
      .catch(() => {
        if (mounted) setHistoryCandidates([]);
      })
      .finally(() => {
        if (mounted) setHistoryCandidatesLoaded(true);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const loadSignalsForPage = useCallback(async (nextPage: number) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoading(true);
    try {
      const response = await decisionSignalsApi.list(toListParams(appliedFilters, nextPage));
      if (requestIdRef.current !== requestId) return;
      const lastPage = Math.max(1, Math.ceil(response.total / PAGE_SIZE));
      if (response.total > 0 && nextPage > lastPage) {
        setPage(lastPage);
        return;
      }
      setItems(response.items);
      setTotal(response.total);
      setError(null);
      setSelected((current) => {
        if (!current) return current;
        if (current.source !== 'list') return current;
        const refreshed = response.items.find((item) => item.id === current.item.id);
        return refreshed ? { source: 'list', item: refreshed } : null;
      });
    } catch (err) {
      if (requestIdRef.current !== requestId) return;
      setError(getParsedApiError(err));
      setItems([]);
      setTotal(0);
      setSelected((current) => (current?.source === 'list' ? null : current));
    } finally {
      if (requestIdRef.current === requestId) {
        setLoading(false);
      }
    }
  }, [appliedFilters]);

  const loadSignals = useCallback(async () => {
    await loadSignalsForPage(page);
  }, [loadSignalsForPage, page]);

  const loadOutcomeStats = useCallback(async () => {
    const requestId = statsRequestIdRef.current + 1;
    statsRequestIdRef.current = requestId;
    setStatsLoading(true);
    try {
      const response = await decisionSignalsApi.getOutcomeStats();
      if (statsRequestIdRef.current !== requestId) return;
      setOutcomeStats(response);
      setStatsError(null);
    } catch (err) {
      if (statsRequestIdRef.current !== requestId) return;
      setOutcomeStats(null);
      setStatsError(getParsedApiError(err));
    } finally {
      if (statsRequestIdRef.current === requestId) {
        setStatsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadSignals();
    return () => {
      requestIdRef.current += 1;
    };
  }, [loadSignals]);

  useEffect(() => {
    void loadOutcomeStats();
    return () => {
      statsRequestIdRef.current += 1;
    };
  }, [loadOutcomeStats]);

  useEffect(() => () => {
    latestRequestIdRef.current += 1;
  }, []);

  useEffect(() => () => {
    timelineRequestIdRef.current += 1;
  }, []);

  useEffect(() => {
    selectedSignalIdRef.current = selected?.item.id ?? null;
    if (!selected) {
      detailRequestIdRef.current += 1;
      setSelectedOutcomes([]);
      setSelectedOutcomesError(null);
      setSelectedFeedback(null);
      setSelectedFeedbackError(null);
      setSelectedOutcomesLoading(false);
      setSelectedFeedbackLoading(false);
      return;
    }

    const requestId = detailRequestIdRef.current + 1;
    detailRequestIdRef.current = requestId;
    setSelectedOutcomesLoading(true);
    setSelectedFeedbackLoading(true);
    setSelectedOutcomesError(null);
    setSelectedFeedbackError(null);

    void decisionSignalsApi.getSignalOutcomes(selected.item.id)
      .then((response) => {
        if (detailRequestIdRef.current !== requestId) return;
        setSelectedOutcomes(response.items);
      })
      .catch((err) => {
        if (detailRequestIdRef.current !== requestId) return;
        setSelectedOutcomes([]);
        setSelectedOutcomesError(getParsedApiError(err));
      })
      .finally(() => {
        if (detailRequestIdRef.current === requestId) {
          setSelectedOutcomesLoading(false);
        }
      });

    void decisionSignalsApi.getFeedback(selected.item.id)
      .then((response) => {
        if (detailRequestIdRef.current !== requestId) return;
        setSelectedFeedback(response);
      })
      .catch((err) => {
        if (detailRequestIdRef.current !== requestId) return;
        setSelectedFeedback(null);
        setSelectedFeedbackError(getParsedApiError(err));
      })
      .finally(() => {
        if (detailRequestIdRef.current === requestId) {
          setSelectedFeedbackLoading(false);
        }
      });
  }, [selected]);

  const appliedSourceReportId = parseSourceReportId(appliedFilters.sourceReportId);
  const selectedSourceReportId = selected?.item.sourceReportId ?? undefined;
  const reassessSourceReportId = selected ? selectedSourceReportId : appliedSourceReportId;
  const reassessContextKey = [
    selected ? `selected:${selected.item.id}` : 'source',
    reassessSourceReportId ?? '',
    reassessProfile,
  ].join(':');

  useEffect(() => {
    reassessRequestIdRef.current += 1;
    setReassessResponse(null);
    setReassessError(null);
    setReassessLoading(false);
  }, [reassessContextKey]);

  const handleReassess = useCallback(async () => {
    if (!reassessSourceReportId) return;
    const requestId = reassessRequestIdRef.current + 1;
    reassessRequestIdRef.current = requestId;
    setReassessLoading(true);
    setReassessError(null);
    try {
      const response = await decisionSignalsApi.reassess({
        sourceReportId: reassessSourceReportId,
        decisionProfile: reassessProfile,
        persist: false,
      });
      if (reassessRequestIdRef.current !== requestId) return;
      setReassessResponse(response);
    } catch (err) {
      if (reassessRequestIdRef.current !== requestId) return;
      setReassessResponse(null);
      setReassessError(getParsedApiError(err));
    } finally {
      if (reassessRequestIdRef.current === requestId) {
        setReassessLoading(false);
      }
    }
  }, [reassessProfile, reassessSourceReportId]);

  const handleApplyFilters = (event: React.FormEvent) => {
    event.preventDefault();
    setAppliedFilters(filters);
    setPage(1);
  };

  const resetLatestView = useCallback(() => {
    latestRequestIdRef.current += 1;
    setLatestItems([]);
    setLatestSearched(false);
    setLatestLoading(false);
    setLatestError(null);
    setSelected((current) => (current?.source === 'latest' ? null : current));
  }, []);

  const loadLatestForContext = useCallback(async (context: StockContext) => {
    const stockCode = context.code.trim();
    if (!stockCode) return;
    const requestId = latestRequestIdRef.current + 1;
    latestRequestIdRef.current = requestId;
    setLatestLoading(true);
    setLatestError(null);
    setLatestSearched(true);
    setLatestItems([]);
    setSelected((current) => (current?.source === 'latest' ? null : current));
    try {
      const response = await decisionSignalsApi.getLatest(stockCode, {
        market: context.market,
        limit: 5,
      });
      if (latestRequestIdRef.current !== requestId) return;
      setLatestItems(response.items);
      setSelected((current) => refreshLatestSelection(current, response.items));
    } catch (err) {
      if (latestRequestIdRef.current !== requestId) return;
      setLatestItems([]);
      setSelected((current) => refreshLatestSelection(current, []));
      setLatestError(getParsedApiError(err));
    } finally {
      if (latestRequestIdRef.current === requestId) {
        setLatestLoading(false);
      }
    }
  }, []);

  const resetTimelineView = useCallback(() => {
    timelineRequestIdRef.current += 1;
    setTimelineItems([]);
    setTimelineSearched(false);
    setTimelineLoading(false);
    setTimelineError(null);
    setTimelineTruncated(false);
    setAppliedTimelineContext(null);
    setSelected((current) => (current?.source === 'timeline' ? null : current));
  }, []);

  const loadTimelineForContext = useCallback(async (
    context: StockContext,
    filtersSnapshot: TimelineFilters,
  ) => {
    const stockCode = context.code.trim();
    if (!stockCode) return;
    const requestId = timelineRequestIdRef.current + 1;
    timelineRequestIdRef.current = requestId;
    setTimelineLoading(true);
    setTimelineError(null);
    setTimelineSearched(true);
    setTimelineItems([]);
    setTimelineTruncated(false);
    setAppliedTimelineContext(null);
    setSelected((current) => (current?.source === 'timeline' ? null : current));
    const nextAppliedContext: AppliedTimelineContext = {
      ...filtersSnapshot,
      stockCode,
    };
    try {
      const response = await decisionSignalsApi.list(toTimelineParams(filtersSnapshot, stockCode));
      if (timelineRequestIdRef.current !== requestId) return;
      setAppliedTimelineContext(nextAppliedContext);
      setTimelineItems(response.items);
      setTimelineTruncated(response.total > response.items.length);
      setSelected((current) => refreshTimelineSelection(current, response.items));
    } catch (err) {
      if (timelineRequestIdRef.current !== requestId) return;
      setTimelineItems([]);
      setTimelineTruncated(false);
      setSelected((current) => refreshTimelineSelection(current, []));
      setTimelineError(getParsedApiError(err));
    } finally {
      if (timelineRequestIdRef.current === requestId) {
        setTimelineLoading(false);
      }
    }
  }, []);

  const applyStockContext = useCallback((nextContext: StockContext) => {
    const nextTimeline = buildNextTimelineFilters(
      timelineFilters,
      activeStockContext,
      nextContext,
      timelineMarketSourceRef.current,
    );
    timelineMarketSourceRef.current = nextTimeline.marketSource;
    setActiveStockContext(nextContext);
    setStockDraft(nextContext.displayCode ?? nextContext.code);
    setTimelineFilters(nextTimeline.filters);
    void loadLatestForContext(nextContext);
    void loadTimelineForContext(nextContext, nextTimeline.filters);
  }, [activeStockContext, loadLatestForContext, loadTimelineForContext, timelineFilters]);

  const handleStockSubmit = useCallback((
    code: string,
    name?: string,
    _source?: 'manual' | 'autocomplete',
    metadata?: { market?: Market; displayCode?: string },
  ) => {
    const trimmedCode = code.trim();
    if (!trimmedCode) return;
    applyStockContext({
      code: trimmedCode,
      displayCode: metadata?.displayCode,
      name,
      market: normalizeDecisionSignalMarket(metadata?.market),
    });
  }, [applyStockContext]);

  const handleCandidateSelect = useCallback((candidate: StockCandidate) => {
    applyStockContext(candidate);
  }, [applyStockContext]);

  const handleStockFormSubmit = useCallback((code: string) => {
    if (draftMatchesStockContext(code, activeStockContext)) {
      applyStockContext(activeStockContext);
      return;
    }
    handleStockSubmit(code);
  }, [activeStockContext, applyStockContext, handleStockSubmit]);

  const handleClearStockContext = useCallback(() => {
    setStockDraft('');
    setActiveStockContext(null);
    timelineMarketSourceRef.current = null;
    setTimelineFilters((current) => ({ ...current, market: '' }));
    resetLatestView();
    resetTimelineView();
  }, [resetLatestView, resetTimelineView]);

  const handleTimelineSearch = useCallback((event: React.FormEvent) => {
    event.preventDefault();
    if (!activeStockContext) return;
    void loadTimelineForContext(activeStockContext, timelineFilters);
  }, [activeStockContext, loadTimelineForContext, timelineFilters]);

  const handleStatusUpdate = async () => {
    if (!pendingStatus || statusUpdateInFlightRef.current) return;
    statusUpdateInFlightRef.current = true;
    setStatusUpdating(true);
    try {
      const updated = await decisionSignalsApi.updateStatus(pendingStatus.item.id, {
        status: pendingStatus.status,
      });
      setPendingStatus(null);
      setLatestItems((current) => current.flatMap((item) => {
        if (item.id !== updated.id) return [item];
        return updated.status === 'active' ? [updated] : [];
      }));
      setTimelineItems((current) => current.flatMap((item) => {
        if (item.id !== updated.id) return [item];
        return appliedTimelineContext?.status === 'active' && updated.status !== 'active' ? [] : [updated];
      }));
      setSelected((current) => {
        if (!current || current.item.id !== updated.id) return current;
        if (current.source === 'latest') {
          return updated.status === 'active' ? { source: 'latest', item: updated } : null;
        }
        if (current.source === 'timeline') {
          return appliedTimelineContext?.status === 'active' && updated.status !== 'active'
            ? null
            : { source: 'timeline', item: updated };
        }
        if (!parseSourceReportId(appliedFilters.sourceReportId) && appliedFilters.status && updated.status !== appliedFilters.status) return null;
        return { source: 'list', item: updated };
      });
      setError(null);
      await loadSignalsForPage(page);
      await loadOutcomeStats();
    } catch (err) {
      setError(getParsedApiError(err));
      setPendingStatus(null);
    } finally {
      setStatusUpdating(false);
      statusUpdateInFlightRef.current = false;
    }
  };

  const handleFeedbackSubmit = useCallback(async (feedbackValue: DecisionSignalFeedbackValue) => {
    if (!selected || feedbackSaving) return;
    const signalId = selected.item.id;
    setFeedbackSaving(true);
    try {
      const updated = await decisionSignalsApi.putFeedback(signalId, {
        feedbackValue,
        source: 'web',
      });
      if (selectedSignalIdRef.current !== signalId) return;
      setSelectedFeedback(updated);
      setSelectedFeedbackError(null);
    } catch (err) {
      if (selectedSignalIdRef.current !== signalId) return;
      setSelectedFeedbackError(getParsedApiError(err));
    } finally {
      setFeedbackSaving(false);
    }
  }, [feedbackSaving, selected]);

  const renderReassessPanel = () => {
    const preview = reassessResponse?.preview ?? null;
    const metadata = preview?.metadata ?? {};
    const guardrail = isRecord(metadata.guardrail_result) ? metadata.guardrail_result : null;
    const rawAction = typeof guardrail?.raw_action === 'string' ? guardrail.raw_action : null;
    const finalAction = typeof guardrail?.final_action === 'string' ? guardrail.final_action : null;
    const passed = typeof guardrail?.passed === 'boolean' ? guardrail.passed : null;
    return (
      <div className="rounded-xl border border-border/60 bg-elevated/30 p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-semibold text-foreground">{t('decisionSignals.reassessTitle')}</h3>
            </div>
            <p className="mt-1 text-xs text-secondary-text">
              {reassessSourceReportId
                ? t('decisionSignals.reassessSource', { id: reassessSourceReportId })
                : t('decisionSignals.reassessUnsupported')}
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <select
              className="input-surface input-focus-glow h-10 rounded-xl border bg-transparent px-3 text-sm"
              value={reassessProfile}
              onChange={(event) => setReassessProfile(event.target.value as DecisionProfile)}
              aria-label={t('decisionSignals.reassessProfile')}
              disabled={!reassessSourceReportId || reassessLoading}
            >
              {REASSESS_PROFILES.map((profile) => (
                <option key={profile} value={profile}>
                  {t(`decisionSignals.profile.${profile}` as UiTextKey)}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn-secondary inline-flex h-10 items-center justify-center gap-2"
              onClick={() => void handleReassess()}
              disabled={!reassessSourceReportId || reassessLoading}
            >
              <RefreshCw className={cn('h-4 w-4', reassessLoading ? 'animate-spin' : '')} />
              {t('decisionSignals.reassessPreview')}
            </button>
          </div>
        </div>

        {!reassessSourceReportId ? (
          <InlineAlert
            className="mt-3"
            variant="warning"
            title={t('decisionSignals.reassessUnsupportedTitle')}
            message={t('decisionSignals.reassessUnsupported')}
          />
        ) : null}
        {reassessError ? <ApiErrorAlert className="mt-3" error={reassessError} /> : null}
        {preview ? (
          <div className="mt-4 space-y-3">
            {reassessResponse?.blockedReason ? (
              <InlineAlert
                variant="warning"
                title={t('decisionSignals.reassessBlockedTitle')}
                message={reassessResponse.blockedReason}
              />
            ) : null}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.action')}</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{actionLabels[preview.action]}</p>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.score')}</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{preview.score ?? '-'}</p>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.confidence')}</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{preview.confidence ?? '-'}</p>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.horizon')}</p>
                <p className="mt-1 text-sm font-semibold text-foreground">{preview.horizon ?? '-'}</p>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.entryRange')}</p>
                <p className="mt-1 text-sm text-foreground">
                  {preview.entryLow || preview.entryHigh
                    ? `${preview.entryLow ?? '-'} ~ ${preview.entryHigh ?? '-'}`
                    : '-'}
                </p>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.stopLoss')}</p>
                <p className="mt-1 text-sm text-foreground">{preview.stopLoss ?? '-'}</p>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.targetPrice')}</p>
                <p className="mt-1 text-sm text-foreground">{preview.targetPrice ?? '-'}</p>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.reassessRawFinal')}</p>
                <p className="mt-1 text-sm text-foreground">{rawAction ?? '-'} {'->'} {finalAction ?? '-'}</p>
              </div>
            </div>
            <div className="space-y-2 text-sm text-secondary-text">
              {passed === false ? (
                <p className="font-medium text-warning">{t('decisionSignals.reassessBlockedNote')}</p>
              ) : null}
              {preview.invalidation ? <p><span className="text-foreground">{t('decisionSignals.invalidation')}:</span> {preview.invalidation}</p> : null}
              {preview.reason ? <p><span className="text-foreground">{t('decisionSignals.reason')}:</span> {preview.reason}</p> : null}
              {preview.riskSummary ? <p><span className="text-foreground">{t('decisionSignals.riskSummary')}:</span> {preview.riskSummary}</p> : null}
              {preview.watchConditions ? <p><span className="text-foreground">{t('decisionSignals.watchConditions')}:</span> {preview.watchConditions}</p> : null}
            </div>
            {reassessResponse?.warnings.length ? (
              <div className="rounded-lg border border-warning/30 bg-warning/10 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-warning">{t('decisionSignals.reassessWarnings')}</p>
                <ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-secondary-text">
                  {reassessResponse.warnings.map((warning, index) => (
                    <li key={`${warning.code}-${index}`}>{warning.message || warning.code}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  };

  const activeStockLabel = activeStockContext
    ? [
      activeStockContext.displayCode ?? activeStockContext.code,
      activeStockContext.name,
      activeStockContext.market,
    ].filter(Boolean).join(' / ')
    : null;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <AppPage>
      <div className="space-y-5">
        <PageHeader
          eyebrow={t('decisionSignals.activeOnly')}
          title={t('decisionSignals.title')}
          description={t('decisionSignals.description')}
          actions={(
            <button
              type="button"
              className="btn-secondary inline-flex items-center gap-2"
              onClick={() => {
                void loadSignals();
                void loadOutcomeStats();
              }}
              disabled={loading}
            >
              <RefreshCw className={cn('h-4 w-4', loading ? 'animate-spin' : '')} />
              {t('decisionSignals.refresh')}
            </button>
          )}
        />

        <Card title={t('decisionSignals.stockContextTitle')} subtitle={t('decisionSignals.stockContextDescription')} padding="md">
          <form
            className="flex flex-col gap-3 md:flex-row"
            onSubmit={(event) => {
              event.preventDefault();
              handleStockFormSubmit(stockDraft);
            }}
          >
            <div className="min-w-0 flex-1">
              <StockAutocomplete
                value={stockDraft}
                onChange={setStockDraft}
                onSubmit={handleStockSubmit}
                placeholder={t('decisionSignals.stockContextPlaceholder')}
                ariaLabel={t('decisionSignals.stockContextInput')}
              />
            </div>
            <button
              type="submit"
              className="btn-primary inline-flex h-11 items-center justify-center gap-2"
              disabled={!stockDraft.trim()}
            >
              <Search className="h-4 w-4" />
              {t('decisionSignals.stockContextApply')}
            </button>
            <button
              type="button"
              className="btn-secondary inline-flex h-11 items-center justify-center gap-2"
              onClick={handleClearStockContext}
              disabled={!activeStockContext && !stockDraft}
            >
              {t('decisionSignals.stockContextClear')}
            </button>
          </form>

          {activeStockLabel ? (
            <p className="mt-3 text-sm text-secondary-text">
              {t('decisionSignals.stockContextCurrent', { stock: activeStockLabel })}
            </p>
          ) : (
            <p className="mt-3 text-sm text-secondary-text">{t('decisionSignals.stockContextEmpty')}</p>
          )}

          {historyCandidatesLoaded && stockCandidates.length > 0 ? (
            <div className="mt-4">
              <p className="text-xs font-medium uppercase text-muted-text">
                {stockCandidateMode === 'history'
                  ? t('decisionSignals.stockContextRecent')
                  : t('decisionSignals.stockContextPopular')}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {stockCandidates.map((candidate) => (
                  <button
                    key={`${candidate.source}:${getCandidateKey(candidate)}`}
                    type="button"
                    className="rounded-full border border-border/70 bg-elevated/40 px-3 py-1.5 text-sm text-foreground transition-colors hover:border-primary/60 hover:text-primary"
                    onClick={() => handleCandidateSelect(candidate)}
                  >
                    <span className="font-mono">{candidate.displayCode ?? candidate.code}</span>
                    {candidate.name ? <span className="ml-1 text-secondary-text">{candidate.name}</span> : null}
                    {candidate.market ? <span className="ml-1 text-muted-text">/ {candidate.market}</span> : null}
                  </button>
                ))}
              </div>
            </div>
          ) : historyCandidatesLoaded ? (
            <p className="mt-4 text-sm text-secondary-text">{t('decisionSignals.stockContextNoCandidates')}</p>
          ) : null}
        </Card>

        <Card padding="md">
          <form className="grid gap-3 md:grid-cols-3 xl:grid-cols-7" onSubmit={handleApplyFilters}>
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.market}
              onChange={(event) => setFilters((current) => ({ ...current, market: event.target.value as ListFilters['market'] }))}
              aria-label={t('decisionSignals.market')}
            >
              <option value="">{t('decisionSignals.allMarkets')}</option>
              {MARKET_OPTIONS.map((market) => (
                <option key={market} value={market}>{getDecisionSignalMarketLabel(market, t)}</option>
              ))}
            </select>
            <input
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.stockCode}
              onChange={(event) => setFilters((current) => ({ ...current, stockCode: event.target.value }))}
              placeholder={t('decisionSignals.stockCode')}
              aria-label={t('decisionSignals.stockCode')}
            />
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.action}
              onChange={(event) => setFilters((current) => ({ ...current, action: event.target.value as ListFilters['action'] }))}
              aria-label={t('decisionSignals.action')}
            >
              <option value="">{t('decisionSignals.allActions')}</option>
              {ACTION_OPTIONS.map((action) => (
                <option key={action} value={action}>{actionLabels[action]}</option>
              ))}
            </select>
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.marketPhase}
              onChange={(event) => setFilters((current) => ({ ...current, marketPhase: event.target.value as ListFilters['marketPhase'] }))}
              aria-label={t('decisionSignals.marketPhase')}
            >
              <option value="">{t('decisionSignals.allPhases')}</option>
              {PHASE_OPTIONS.map((phase) => (
                <option key={phase} value={phase}>{getDecisionSignalMarketPhaseLabel(phase, t)}</option>
              ))}
            </select>
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.sourceType}
              onChange={(event) => setFilters((current) => ({ ...current, sourceType: event.target.value as ListFilters['sourceType'] }))}
              aria-label={t('decisionSignals.source')}
            >
              <option value="">{t('decisionSignals.allSources')}</option>
              {SOURCE_OPTIONS.map((source) => (
                <option key={source} value={source}>{getDecisionSignalSourceTypeLabel(source, t)}</option>
              ))}
            </select>
            <input
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.sourceReportId}
              onChange={(event) => setFilters((current) => ({ ...current, sourceReportId: event.target.value }))}
              placeholder={t('decisionSignals.sourceReportId')}
              aria-label={t('decisionSignals.sourceReportId')}
              inputMode="numeric"
              min={1}
              step={1}
              type="number"
            />
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={filters.status}
              onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value as ListFilters['status'] }))}
              aria-label={t('decisionSignals.status')}
            >
              <option value="">{t('decisionSignals.allStatuses')}</option>
              {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{t(STATUS_LABEL_KEYS[status])}</option>)}
            </select>
            <button type="submit" className="btn-primary inline-flex h-11 items-center justify-center gap-2">
              <Search className="h-4 w-4" />
              {t('decisionSignals.filter')}
            </button>
          </form>
        </Card>

        {!selected && appliedSourceReportId ? (
          <Card padding="md">
            {renderReassessPanel()}
          </Card>
        ) : null}

        <Card title={t('decisionSignals.statsTitle')} subtitle={t('decisionSignals.statsDescription')} padding="md">
          <p className="mb-3 text-sm text-secondary-text">{t('decisionSignals.statsGlobalScope')}</p>
          {statsError ? (
            <ApiErrorAlert
              error={{ ...statsError, title: t('decisionSignals.statsErrorTitle') }}
              actionLabel={t('common.retry')}
              onAction={() => void loadOutcomeStats()}
            />
          ) : statsLoading ? (
            <p className="text-sm text-secondary-text">{t('common.loading')}...</p>
          ) : outcomeStats && outcomeStats.total > 0 ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              <div className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.statsTotal')}</p>
                <p className="mt-1 text-2xl font-semibold text-foreground">{outcomeStats.total}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.statsHitRate')}</p>
                <p className="mt-1 text-2xl font-semibold text-success">{formatStatPercent(outcomeStats.hitRatePct)}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.outcome.hit')}</p>
                <p className="mt-1 text-2xl font-semibold text-success">{outcomeStats.hit}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.outcome.miss')}</p>
                <p className="mt-1 text-2xl font-semibold text-danger">{outcomeStats.miss}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-elevated/40 px-3 py-3">
                <p className="text-xs text-secondary-text">{t('decisionSignals.outcome.unable')}</p>
                <p className="mt-1 text-2xl font-semibold text-warning">{outcomeStats.unable}</p>
              </div>
            </div>
          ) : (
            <EmptyState
              className="border-none bg-transparent py-6 shadow-none"
              title={t('decisionSignals.noReviewedStatsTitle')}
              description={t('decisionSignals.noReviewedStatsDescription')}
              icon={<BarChart3 className="h-6 w-6" />}
            />
          )}
        </Card>

        <Card title={t('decisionSignals.latestTitle')} subtitle={t('decisionSignals.latestDescription')} padding="md">
          {!activeStockContext ? (
            <EmptyState
              className="border-none bg-transparent py-6 shadow-none"
              title={t('decisionSignals.stockContextGuideTitle')}
              description={t('decisionSignals.stockContextGuideDescription')}
              icon={<Activity className="h-6 w-6" />}
            />
          ) : null}
          {latestError ? <ApiErrorAlert className="mt-3" error={latestError} /> : null}
          {latestSearched && !latestLoading && !latestError && latestItems.length === 0 ? (
            <EmptyState
              className="mt-4 border-none bg-transparent py-6 shadow-none"
              title={t('decisionSignals.noLatestTitle')}
              description={t('decisionSignals.noLatestDescription')}
              icon={<Activity className="h-6 w-6" />}
            />
          ) : null}
          {latestLoading ? <p className="mt-3 text-sm text-secondary-text">{t('common.loading')}...</p> : null}
          {latestItems.length > 0 ? (
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              {latestItems.map((item) => (
                <DecisionSignalCard
                  key={item.id}
                  item={item}
                  onSelect={(selectedItem) => setSelected({ source: 'latest', item: selectedItem })}
                  selected={selected?.item.id === item.id}
                />
              ))}
            </div>
          ) : null}
        </Card>

        <Card title={t('decisionSignals.timelineTitle')} subtitle={t('decisionSignals.timelineDescription')} padding="md">
          <form className="grid gap-3 md:grid-cols-5" onSubmit={handleTimelineSearch}>
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={timelineFilters.market}
              onChange={(event) => {
                const market = event.target.value as TimelineFilters['market'];
                timelineMarketSourceRef.current = market ? 'user' : null;
                setTimelineFilters((current) => ({ ...current, market }));
              }}
              aria-label={t('decisionSignals.timelineMarket')}
            >
              <option value="">{t('decisionSignals.allMarkets')}</option>
              {MARKET_OPTIONS.map((market) => (
                <option key={market} value={market}>{getDecisionSignalMarketLabel(market, t)}</option>
              ))}
            </select>
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={timelineFilters.range}
              onChange={(event) => setTimelineFilters((current) => ({ ...current, range: event.target.value as TimelineRange }))}
              aria-label={t('decisionSignals.timelineRange')}
            >
              <option value="30d">{t('decisionSignals.timelineRange.30d')}</option>
              <option value="90d">{t('decisionSignals.timelineRange.90d')}</option>
              <option value="180d">{t('decisionSignals.timelineRange.180d')}</option>
            </select>
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={timelineFilters.status}
              onChange={(event) => setTimelineFilters((current) => ({ ...current, status: event.target.value as TimelineStatusFilter }))}
              aria-label={t('decisionSignals.timelineStatus')}
            >
              <option value="all">{t('decisionSignals.timelineStatus.all')}</option>
              <option value="active">{t('decisionSignals.timelineStatus.active')}</option>
            </select>
            <select
              className="input-surface input-focus-glow h-11 rounded-xl border bg-transparent px-3 text-sm"
              value={timelineFilters.decisionProfile}
              onChange={(event) => setTimelineFilters((current) => ({
                ...current,
                decisionProfile: event.target.value as TimelineFilters['decisionProfile'],
              }))}
              aria-label={t('decisionSignals.timelineProfile')}
            >
              <option value="">{t('decisionSignals.allProfiles')}</option>
              {REASSESS_PROFILES.map((profile) => (
                <option key={profile} value={profile}>
                  {t(`decisionSignals.profile.${profile}` as UiTextKey)}
                </option>
              ))}
              <option value="unknown">{t('decisionSignals.profile.unknown')}</option>
            </select>
            <button
              type="submit"
              className="btn-secondary inline-flex h-11 items-center justify-center gap-2"
              disabled={timelineLoading || !activeStockContext?.code}
            >
              <Search className="h-4 w-4" />
              {t('decisionSignals.timelineSearch')}
            </button>
          </form>
          <div className="mt-4">
            {!timelineSearched ? (
              <EmptyState
                className="border-none bg-transparent py-6 shadow-none"
                title={activeStockContext ? t('decisionSignals.timelineGuideTitle') : t('decisionSignals.stockContextGuideTitle')}
                description={activeStockContext ? t('decisionSignals.timelineGuideDescription') : t('decisionSignals.stockContextGuideDescription')}
                icon={<Activity className="h-6 w-6" />}
              />
            ) : (
              <DecisionSignalTimeline
                items={timelineItems}
                selectedId={selected?.item.id ?? null}
                loading={timelineLoading}
                error={timelineError?.message ?? null}
                truncated={timelineTruncated}
                onSelect={(selectedItem) => setSelected({ source: 'timeline', item: selectedItem })}
              />
            )}
          </div>
        </Card>

        {error ? (
          <ApiErrorAlert
            error={{ ...error, title: t('decisionSignals.errorTitle') }}
            actionLabel={t('common.retry')}
            onAction={() => void loadSignals()}
          />
        ) : null}

        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-secondary-text">{t('decisionSignals.total', { total })}</p>
          {loading ? <span className="text-xs text-secondary-text">{t('common.loading')}...</span> : null}
        </div>

        {!loading && items.length === 0 ? (
          <EmptyState
            title={t('decisionSignals.emptyTitle')}
            description={t('decisionSignals.emptyDescription')}
            icon={<Activity className="h-7 w-7" />}
          />
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">
            {items.map((item) => (
              <DecisionSignalCard
                key={item.id}
                item={item}
                onSelect={(selectedItem) => setSelected({ source: 'list', item: selectedItem })}
                selected={selected?.item.id === item.id}
              />
            ))}
          </div>
        )}

        <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
      </div>

      <Drawer
        isOpen={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={t('decisionSignals.detailTitle')}
        width="max-w-3xl"
      >
        {selected ? (
          <div className="space-y-4">
            {renderReassessPanel()}
            <DecisionSignalDetails
              item={selected.item}
              outcomes={selectedOutcomes}
              outcomesLoading={selectedOutcomesLoading}
              outcomesError={selectedOutcomesError?.message ?? null}
              feedback={selectedFeedback}
              feedbackLoading={selectedFeedbackLoading}
              feedbackSaving={feedbackSaving}
              feedbackError={selectedFeedbackError?.message ?? null}
              onFeedbackSubmit={handleFeedbackSubmit}
              actions={STATUS_ACTIONS.map((status) => (
                <button
                  key={status}
                  type="button"
                  className="btn-secondary !px-3 !py-1.5 !text-xs"
                  onClick={() => setPendingStatus({
                    item: selected.item,
                    status,
                    message: t(STATUS_ACTION_CONFIRM_KEYS[status]),
                  })}
                  disabled={statusUpdating || selected.item.status === status}
                >
                  {t(STATUS_ACTION_LABEL_KEYS[status])}
                </button>
              ))}
            />
          </div>
        ) : null}
      </Drawer>

      {statusUpdating ? (
        <InlineAlert
          className="fixed bottom-5 right-5 z-[60] max-w-sm"
          variant="info"
          title={t('common.processing')}
          message={t('decisionSignals.confirmStatusTitle')}
        />
      ) : null}

      <ConfirmDialog
        isOpen={Boolean(pendingStatus)}
        title={t('decisionSignals.confirmStatusTitle')}
        message={pendingStatus?.message ?? ''}
        confirmText={t('common.confirm')}
        confirmDisabled={statusUpdating}
        cancelDisabled={statusUpdating}
        onConfirm={() => void handleStatusUpdate()}
        onCancel={() => setPendingStatus(null)}
      />
    </AppPage>
  );
};

export default DecisionSignalsPage;
