import { create } from 'zustand';
import { analysisApi, DuplicateTaskError } from '../api/analysis';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import { historyApi } from '../api/history';
import type { AnalysisReport, HistoryItem, HistoryListResponse, StockHistoryFilters, StockHistoryRange, TaskInfo } from '../types/analysis';
import { getRecentStartDate, getTodayInShanghai } from '../utils/format';
import { isObviouslyInvalidStockQuery, looksLikeStockCode, validateStockCode } from '../utils/validation';

const PAGE_SIZE = 20;
const STOCK_HISTORY_PAGE_SIZE = 20;

type SelectionSource = 'manual' | 'autocomplete' | 'import' | 'image';

type FetchHistoryOptions = {
  autoSelectFirst?: boolean;
  reset?: boolean;
  silent?: boolean;
};

type SubmitAnalysisOptions = {
  stockCode?: string;
  stockName?: string;
  originalQuery?: string;
  selectionSource?: SelectionSource;
  notify?: boolean;
  forceRefresh?: boolean;
  skills?: string[];
};

let reportRequestSeq = 0;
let analyzeRequestSeq = 0;
let historyRequestSeq = 0;
let stockHistoryRequestSeq = 0;
let activeTaskRequestSeq = 0;
let activeTaskLocalRevision = 0;
const dismissedTaskIds = new Set<string>();

export interface StockPoolState {
  query: string;
  selectionSource: SelectionSource;
  notify: boolean;
  inputError?: string;
  duplicateError: string | null;
  error: ParsedApiError | null;
  isAnalyzing: boolean;
  historyItems: HistoryItem[];
  selectedHistoryIds: number[];
  isDeletingHistory: boolean;
  isLoadingHistory: boolean;
  isLoadingMore: boolean;
  hasMore: boolean;
  currentPage: number;
  selectedReport: AnalysisReport | null;
  isLoadingReport: boolean;
  isHistoryTrendOpen: boolean;
  stockHistoryItems: HistoryItem[];
  stockHistoryTotal: number;
  stockHistoryPage: number;
  stockHistoryHasMore: boolean;
  isLoadingStockHistory: boolean;
  isLoadingMoreStockHistory: boolean;
  stockHistoryError: ParsedApiError | null;
  stockHistoryFilters: StockHistoryFilters;
  activeTasks: TaskInfo[];
  markdownDrawerOpen: boolean;
  setQuery: (query: string) => void;
  clearError: () => void;
  clearInlineMessages: () => void;
  openMarkdownDrawer: () => void;
  closeMarkdownDrawer: () => void;
  openHistoryTrend: () => Promise<void>;
  closeHistoryTrend: () => void;
  setStockHistoryRange: (range: StockHistoryRange) => Promise<void>;
  loadMoreStockHistory: () => Promise<void>;
  loadInitialHistory: () => Promise<void>;
  refreshHistory: (silent?: boolean) => Promise<void>;
  loadMoreHistory: () => Promise<void>;
  selectHistoryItem: (recordId: number) => Promise<void>;
  toggleHistorySelection: (recordId: number) => void;
  toggleSelectAllVisible: () => void;
  deleteSelectedHistory: () => Promise<void>;
  submitAnalysis: (options?: SubmitAnalysisOptions) => Promise<void>;
  setNotify: (notify: boolean) => void;
  syncTaskCreated: (task: TaskInfo) => void;
  syncTaskUpdated: (task: TaskInfo) => void;
  syncTaskFailed: (task: TaskInfo) => void;
  refreshActiveTasks: () => Promise<void>;
  removeTask: (taskId: string) => void;
  resetDashboardState: () => void;
}

const initialState = {
  query: '',
  selectionSource: 'manual' as SelectionSource,
  notify: true,
  inputError: undefined,
  duplicateError: null,
  error: null,
  isAnalyzing: false,
  historyItems: [] as HistoryItem[],
  selectedHistoryIds: [] as number[],
  isDeletingHistory: false,
  isLoadingHistory: false,
  isLoadingMore: false,
  hasMore: true,
  currentPage: 1,
  selectedReport: null as AnalysisReport | null,
  isLoadingReport: false,
  isHistoryTrendOpen: false,
  stockHistoryItems: [] as HistoryItem[],
  stockHistoryTotal: 0,
  stockHistoryPage: 1,
  stockHistoryHasMore: false,
  isLoadingStockHistory: false,
  isLoadingMoreStockHistory: false,
  stockHistoryError: null as ParsedApiError | null,
  stockHistoryFilters: {
    range: 'all' as StockHistoryRange,
    model: 'all',
    sort: 'desc' as const,
  },
  activeTasks: [] as TaskInfo[],
  markdownDrawerOpen: false,
};

function buildHistoryParams(page: number) {
  return {
    startDate: getRecentStartDate(30),
    endDate: getTodayInShanghai(),
    page,
    limit: PAGE_SIZE,
  };
}

function buildStockHistoryParams(stockCode: string, page: number, filters: StockHistoryFilters) {
  const params: {
    stockCode: string;
    startDate?: string;
    endDate?: string;
    page: number;
    limit: number;
  } = {
    stockCode,
    page,
    limit: STOCK_HISTORY_PAGE_SIZE,
  };

  if (filters.range === '30d') {
    params.startDate = getRecentStartDate(30);
    params.endDate = getTodayInShanghai();
  } else if (filters.range === '90d') {
    params.startDate = getRecentStartDate(90);
    params.endDate = getTodayInShanghai();
  }

  return params;
}

function reportToHistoryItem(report: AnalysisReport): HistoryItem | null {
  if (report.meta.id === undefined) {
    return null;
  }

  return {
    id: report.meta.id,
    queryId: report.meta.queryId,
    stockCode: report.meta.stockCode,
    stockName: report.meta.stockName,
    reportType: report.meta.reportType,
    trendPrediction: report.summary.trendPrediction,
    analysisSummary: report.summary.analysisSummary,
    sentimentScore: report.summary.sentimentScore,
    operationAdvice: report.summary.operationAdvice,
    currentPrice: report.meta.currentPrice,
    changePct: report.meta.changePct,
    modelUsed: report.meta.modelUsed,
    createdAt: report.meta.createdAt,
  };
}

function isDateInHistoryRange(createdAt: string | undefined, range: StockHistoryRange): boolean {
  if (range === 'all') {
    return true;
  }
  if (!createdAt) {
    return false;
  }

  const reportDate = createdAt.slice(0, 10);
  const startDate = range === '30d' ? getRecentStartDate(30) : getRecentStartDate(90);
  const endDate = getTodayInShanghai();

  return reportDate >= startDate && reportDate <= endDate;
}

function includeSelectedReport(
  items: HistoryItem[],
  report: AnalysisReport,
  range: StockHistoryRange,
): HistoryItem[] {
  const current = reportToHistoryItem(report);
  if (!current || !isDateInHistoryRange(current.createdAt, range) || items.some((item) => item.id === current.id)) {
    return items;
  }
  return [current, ...items];
}

function dedupeHistoryItems(items: HistoryItem[]): HistoryItem[] {
  const seen = new Set<number>();
  return items.filter((item) => {
    if (seen.has(item.id)) {
      return false;
    }
    seen.add(item.id);
    return true;
  });
}

function resetStockHistoryState(set: (partial: Partial<StockPoolState>) => void) {
  set({
    stockHistoryItems: [],
    stockHistoryTotal: 0,
    stockHistoryPage: 1,
    stockHistoryHasMore: false,
    isLoadingStockHistory: false,
    isLoadingMoreStockHistory: false,
    stockHistoryError: null,
  });
}

async function fetchStockHistory(
  get: () => StockPoolState,
  set: (partial: Partial<StockPoolState>) => void,
  options: { reset?: boolean } = {},
): Promise<HistoryListResponse | null> {
  const { reset = true } = options;
  const state = get();
  const report = state.selectedReport;

  if (!report || report.meta.reportType === 'market_review') {
    resetStockHistoryState(set);
    set({
      isHistoryTrendOpen: false,
    });
    return null;
  }

  const page = reset ? 1 : state.stockHistoryPage + 1;
  const requestId = ++stockHistoryRequestSeq;
  set(
    reset
      ? { isLoadingStockHistory: true, isLoadingMoreStockHistory: false, stockHistoryError: null }
      : { isLoadingMoreStockHistory: true, stockHistoryError: null },
  );

  try {
    const response = await historyApi.getList(
      buildStockHistoryParams(report.meta.stockCode, page, state.stockHistoryFilters),
    );
    if (requestId !== stockHistoryRequestSeq) {
      return null;
    }

    const nextItems = reset
      ? dedupeHistoryItems(includeSelectedReport(response.items, report, state.stockHistoryFilters.range))
      : dedupeHistoryItems([...get().stockHistoryItems, ...response.items]);
    const nextTotal = Math.max(response.total, nextItems.length);
    set({
      stockHistoryItems: nextItems,
      stockHistoryTotal: nextTotal,
      stockHistoryPage: page,
      stockHistoryHasMore: nextItems.length < nextTotal,
    });
    return response;
  } catch (error) {
    if (requestId !== stockHistoryRequestSeq) {
      return null;
    }
    set({ stockHistoryError: getParsedApiError(error) });
    return null;
  } finally {
    if (requestId === stockHistoryRequestSeq) {
      set({
        isLoadingStockHistory: false,
        isLoadingMoreStockHistory: false,
      });
    }
  }
}

async function fetchHistory(
  get: () => StockPoolState,
  set: (partial: Partial<StockPoolState>) => void,
  options: FetchHistoryOptions = {},
): Promise<HistoryListResponse | null> {
  const { autoSelectFirst = false, reset = true, silent = false } = options;
  const currentState = get();
  const page = reset ? 1 : currentState.currentPage + 1;
  const requestId = ++historyRequestSeq;

  if (!silent) {
    set(
      reset
        ? { isLoadingHistory: true, isLoadingMore: false, currentPage: 1 }
        : { isLoadingMore: true },
    );
  }

  try {
    const response = await historyApi.getList(buildHistoryParams(page));
    if (requestId !== historyRequestSeq) {
      return null;
    }

    if (silent && reset) {
      const existingIds = new Set(get().historyItems.map((item) => item.id));
      const newItems = response.items.filter((item) => !existingIds.has(item.id));
      if (newItems.length > 0) {
        set({ historyItems: [...newItems, ...get().historyItems] });
      }
    } else if (reset) {
      set({
        historyItems: response.items,
        currentPage: 1,
      });
    } else {
      set({
        historyItems: [...get().historyItems, ...response.items],
        currentPage: page,
      });
    }

    if (!silent) {
      const totalLoaded = reset ? response.items.length : get().historyItems.length;
      set({ hasMore: totalLoaded < response.total });
    }

    const visibleIds = new Set(get().historyItems.map((item) => item.id));
    set({
      selectedHistoryIds: get().selectedHistoryIds.filter((id) => visibleIds.has(id)),
    });

    if (autoSelectFirst && response.items.length > 0 && !get().selectedReport) {
      await get().selectHistoryItem(response.items[0].id);
    }

    return response;
  } catch (error) {
    if (requestId !== historyRequestSeq) {
      return null;
    }
    set({ error: getParsedApiError(error) });
    return null;
  } finally {
    if (requestId === historyRequestSeq) {
      set({
        isLoadingHistory: false,
        isLoadingMore: false,
      });
    }
  }
}

export const useStockPoolStore = create<StockPoolState>((set, get) => ({
  ...initialState,

  setQuery: (query) => {
    set({
      query,
      selectionSource: 'manual',
      inputError: undefined,
      duplicateError: null,
    });
  },

  clearError: () => set({ error: null }),

  clearInlineMessages: () => set({ inputError: undefined, duplicateError: null }),

  setNotify: (notify) => set({ notify }),

  openMarkdownDrawer: () => set({ markdownDrawerOpen: true }),

  closeMarkdownDrawer: () => set({ markdownDrawerOpen: false }),

  openHistoryTrend: async () => {
    if (!get().selectedReport || get().selectedReport?.meta.reportType === 'market_review') {
      return;
    }
    set({ isHistoryTrendOpen: true });
    await fetchStockHistory(get, set, { reset: true });
  },

  closeHistoryTrend: () => {
    stockHistoryRequestSeq += 1;
    resetStockHistoryState(set);
    set({
      isHistoryTrendOpen: false,
    });
  },

  setStockHistoryRange: async (range) => {
    set({
      stockHistoryFilters: {
        ...get().stockHistoryFilters,
        range,
      },
    });
    if (get().isHistoryTrendOpen) {
      await fetchStockHistory(get, set, { reset: true });
    }
  },

  loadMoreStockHistory: async () => {
    const state = get();
    if (!state.isHistoryTrendOpen || state.isLoadingMoreStockHistory || !state.stockHistoryHasMore) {
      return;
    }
    await fetchStockHistory(get, set, { reset: false });
  },

  loadInitialHistory: async () => {
    await fetchHistory(get, set, { autoSelectFirst: true, reset: true });
  },

  refreshHistory: async (silent = false) => {
    await fetchHistory(get, set, { reset: true, silent });
  },

  loadMoreHistory: async () => {
    const state = get();
    if (state.isLoadingMore || !state.hasMore) {
      return;
    }
    await fetchHistory(get, set, { reset: false });
  },

  selectHistoryItem: async (recordId) => {
    const requestId = ++reportRequestSeq;
    const shouldShowInitialLoading = !get().selectedReport;

    if (shouldShowInitialLoading) {
      set({ isLoadingReport: true });
    }

    try {
      const report = await historyApi.getDetail(recordId);
      if (requestId !== reportRequestSeq) {
        return;
      }

      set({
        selectedReport: report,
        error: null,
        isLoadingReport: false,
      });

      if (report.meta.reportType === 'market_review' || !report.meta.stockCode) {
        stockHistoryRequestSeq += 1;
        resetStockHistoryState(set);
        set({ isHistoryTrendOpen: false });
        return;
      }

      if (get().isHistoryTrendOpen) {
        await fetchStockHistory(get, set, { reset: true });
      }
    } catch (error) {
      if (requestId !== reportRequestSeq) {
        return;
      }

      set({
        error: getParsedApiError(error),
        isLoadingReport: false,
      });
    }
  },

  toggleHistorySelection: (recordId) => {
    const selected = new Set(get().selectedHistoryIds);
    if (selected.has(recordId)) {
      selected.delete(recordId);
    } else {
      selected.add(recordId);
    }

    set({ selectedHistoryIds: Array.from(selected) });
  },

  toggleSelectAllVisible: () => {
    const visibleIds = get().historyItems.map((item) => item.id);
    const selectedIds = get().selectedHistoryIds;
    const visibleSet = new Set(visibleIds);
    const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));

    set({
      selectedHistoryIds: allSelected
        ? selectedIds.filter((id) => !visibleSet.has(id))
        : Array.from(new Set([...selectedIds, ...visibleIds])),
    });
  },

  deleteSelectedHistory: async () => {
    const state = get();
    const recordIds = Array.from(new Set(state.selectedHistoryIds));
    if (recordIds.length === 0 || state.isDeletingHistory) {
      return;
    }

    set({ isDeletingHistory: true });
    try {
      await historyApi.deleteRecords(recordIds);

      const deletedIds = new Set(recordIds);
      const selectedWasDeleted = state.selectedReport?.meta.id !== undefined
        && deletedIds.has(state.selectedReport.meta.id);

      set({ selectedHistoryIds: [] });

      const freshPage = await fetchHistory(get, set, { reset: true });

      if (selectedWasDeleted) {
        const nextItem = freshPage?.items?.[0];
        if (nextItem) {
          await get().selectHistoryItem(nextItem.id);
        } else {
          stockHistoryRequestSeq += 1;
          resetStockHistoryState(set);
          set({
            isHistoryTrendOpen: false,
            selectedReport: null,
          });
        }
      }
    } catch (error) {
      set({ error: getParsedApiError(error) });
    } finally {
      set({ isDeletingHistory: false });
    }
  },

  submitAnalysis: async (options) => {
    const state = get();
    const rawStockCode = options?.stockCode ?? state.query;
    const stockCodeInput = rawStockCode.trim();
    const stockName = options?.stockName;
    const selectionSource = options?.selectionSource ?? state.selectionSource;
    const originalQuery = (options?.originalQuery ?? state.query).trim();
    const notify = options?.notify ?? state.notify;
    const forceRefresh = options?.forceRefresh ?? false;
    const skills = options?.skills;

    if (!stockCodeInput) {
      set({ inputError: '请输入股票代码', duplicateError: null });
      return;
    }

    if (selectionSource !== 'autocomplete' && isObviouslyInvalidStockQuery(stockCodeInput)) {
      set({ inputError: '请输入有效的股票代码或股票名称', duplicateError: null });
      return;
    }

    let normalizedStockCode = stockCodeInput;
    if (selectionSource === 'autocomplete' || looksLikeStockCode(stockCodeInput)) {
      const { valid, message, normalized } = validateStockCode(stockCodeInput);
      if (!valid) {
        set({ inputError: message, duplicateError: null });
        return;
      }
      normalizedStockCode = normalized;
    }

    set({
      inputError: undefined,
      duplicateError: null,
      error: null,
      isAnalyzing: true,
    });

    const requestId = ++analyzeRequestSeq;
    try {
      await analysisApi.analyzeAsync({
        stockCode: normalizedStockCode,
        reportType: 'detailed',
        stockName,
        originalQuery: originalQuery || stockCodeInput,
        selectionSource,
        notify,
        forceRefresh,
        skills,
      });

      if (requestId !== analyzeRequestSeq) {
        return;
      }

      set({
        query: '',
        selectionSource: 'manual',
      });
    } catch (error) {
      if (requestId !== analyzeRequestSeq) {
        return;
      }

      if (error instanceof DuplicateTaskError) {
        set({
          duplicateError: `股票 ${error.stockCode} 正在分析中，请等待完成`,
        });
        return;
      }

      set({ error: getParsedApiError(error) });
    } finally {
      if (requestId === analyzeRequestSeq) {
        set({ isAnalyzing: false });
      }
    }
  },

  syncTaskCreated: (task) => {
    if (dismissedTaskIds.has(task.taskId)) {
      return;
    }
    if (get().activeTasks.some((item) => item.taskId === task.taskId)) {
      return;
    }
    activeTaskLocalRevision += 1;
    set({ activeTasks: [...get().activeTasks, task] });
  },

  syncTaskUpdated: (task) => {
    if (dismissedTaskIds.has(task.taskId)) {
      return;
    }
    const nextTasks = [...get().activeTasks];
    const index = nextTasks.findIndex((item) => item.taskId === task.taskId);
    if (index >= 0) {
      nextTasks[index] = task;
      activeTaskLocalRevision += 1;
      set({ activeTasks: nextTasks });
    }
  },

  syncTaskFailed: (task) => {
    get().syncTaskUpdated(task);
    set({ error: getParsedApiError(task.error || '分析失败') });
  },

  refreshActiveTasks: async () => {
    const requestId = ++activeTaskRequestSeq;
    const localRevisionAtRequest = activeTaskLocalRevision;
    try {
      const response = await analysisApi.getTasks({
        status: 'pending,processing',
        limit: 100,
      });
      if (requestId !== activeTaskRequestSeq) {
        return;
      }

      const remoteTasks = response.tasks.filter(
        (task) => !dismissedTaskIds.has(task.taskId),
      );
      const remoteTaskIds = new Set(remoteTasks.map((task) => task.taskId));
      const remoteTaskById = new Map(remoteTasks.map((task) => [task.taskId, task]));
      const isCompleteSnapshot = response.tasks.length === response.pending + response.processing;
      const canPruneLocalTasks = isCompleteSnapshot && activeTaskLocalRevision === localRevisionAtRequest;

      const currentTasks = get().activeTasks;
      const nextTasks = currentTasks
        .filter((task) => !dismissedTaskIds.has(task.taskId))
        .filter((task) => !canPruneLocalTasks || remoteTaskIds.has(task.taskId))
        .map((task) => remoteTaskById.get(task.taskId) ?? task);

      const localTaskIds = new Set(nextTasks.map((task) => task.taskId));
      for (const task of remoteTasks) {
        if (!localTaskIds.has(task.taskId)) {
          nextTasks.push(task);
        }
      }

      const hasActiveTaskChanges = nextTasks.length !== currentTasks.length
        || nextTasks.some((task, index) => task !== currentTasks[index]);
      if (hasActiveTaskChanges) {
        activeTaskLocalRevision += 1;
        set({ activeTasks: nextTasks });
      }
    } catch {
      // Keep the current task panel when reconciliation cannot reach the API.
    }
  },

  removeTask: (taskId) => {
    dismissedTaskIds.add(taskId);
    const currentTasks = get().activeTasks;
    const nextTasks = currentTasks.filter((task) => task.taskId !== taskId);
    if (nextTasks.length !== currentTasks.length) {
      activeTaskLocalRevision += 1;
    }
    set({ activeTasks: nextTasks });
  },

  resetDashboardState: () => {
    historyRequestSeq += 1;
    stockHistoryRequestSeq += 1;
    reportRequestSeq = 0;
    analyzeRequestSeq = 0;
    activeTaskRequestSeq += 1;
    activeTaskLocalRevision += 1;
    dismissedTaskIds.clear();
    set({ ...initialState });
  },
}));
