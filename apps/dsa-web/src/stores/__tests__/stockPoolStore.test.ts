import { beforeEach, describe, expect, it, vi } from 'vitest';
import { analysisApi, DuplicateTaskError } from '../../api/analysis';
import { historyApi } from '../../api/history';
import type { TaskInfo, TaskListResponse } from '../../types/analysis';
import { getRecentStartDate, getTodayInShanghai } from '../../utils/format';
import { useStockPoolStore } from '../stockPoolStore';

vi.mock('../../api/history', () => ({
  historyApi: {
    getList: vi.fn(),
    getDetail: vi.fn(),
    deleteRecords: vi.fn(),
    getStockBarList: vi.fn(),
  },
}));

vi.mock('../../api/analysis', async () => {
  const actual = await vi.importActual<typeof import('../../api/analysis')>('../../api/analysis');
  return {
    ...actual,
    analysisApi: {
      analyzeAsync: vi.fn(),
      getTasks: vi.fn(),
    },
  };
});

const historyItem = {
  id: 1,
  queryId: 'q-1',
  stockCode: '600519',
  stockName: '贵州茅台',
  sentimentScore: 82,
  operationAdvice: '买入',
  createdAt: '2026-03-18T08:00:00Z',
};

const historyReport = {
  meta: {
    id: 1,
    queryId: 'q-1',
    stockCode: '600519',
    stockName: '贵州茅台',
    reportType: 'detailed' as const,
    createdAt: '2026-03-18T08:00:00Z',
  },
  summary: {
    analysisSummary: '趋势维持强势',
    operationAdvice: '继续观察买点',
    trendPrediction: '短线震荡偏强',
    sentimentScore: 78,
  },
};

const marketReviewHistoryReport = {
  ...historyReport,
  meta: {
    ...historyReport.meta,
    id: 10,
    queryId: 'q-10',
    stockCode: '',
    stockName: '大盘复盘',
    reportType: 'market_review' as const,
  },
};

function createTask(overrides: Partial<TaskInfo> = {}): TaskInfo {
  return {
    taskId: 'task-1',
    stockCode: '600519',
    stockName: '贵州茅台',
    status: 'processing',
    progress: 50,
    reportType: 'detailed',
    createdAt: '2026-03-18T08:00:00Z',
    ...overrides,
  };
}

function createTaskListResponse(
  tasks: TaskInfo[],
  counts: Partial<Pick<TaskListResponse, 'pending' | 'processing' | 'total'>> = {},
): TaskListResponse {
  const pending = counts.pending ?? tasks.filter((task) => task.status === 'pending').length;
  const processing = counts.processing ?? tasks.filter((task) => task.status === 'processing').length;
  return {
    total: counts.total ?? tasks.length,
    pending,
    processing,
    tasks,
  };
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('stockPoolStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStockPoolStore.getState().resetDashboardState();
    vi.mocked(analysisApi.getTasks).mockResolvedValue(createTaskListResponse([]));
  });

  it('loads initial history and auto-selects the first report', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [historyItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(historyReport);

    await useStockPoolStore.getState().loadInitialHistory();

    const state = useStockPoolStore.getState();
    expect(state.historyItems).toHaveLength(1);
    expect(state.selectedReport?.meta.stockCode).toBe('600519');
    expect(state.isLoadingHistory).toBe(false);
    expect(state.isLoadingReport).toBe(false);
  });

  it('opens same-stock history trend and loads more records', async () => {
    const olderItem = {
      ...historyItem,
      id: 2,
      queryId: 'q-2',
      modelUsed: 'gemini/gemini-2.5-pro',
    };

    useStockPoolStore.setState({ selectedReport: historyReport });
    vi.mocked(historyApi.getList)
      .mockResolvedValueOnce({
        total: 2,
        page: 1,
        limit: 20,
        items: [historyItem],
      })
      .mockResolvedValueOnce({
        total: 2,
        page: 2,
        limit: 20,
        items: [olderItem],
      });

    await useStockPoolStore.getState().openHistoryTrend();

    let state = useStockPoolStore.getState();
    expect(state.isHistoryTrendOpen).toBe(true);
    expect(state.stockHistoryItems).toEqual([historyItem]);
    expect(state.stockHistoryHasMore).toBe(true);
    expect(historyApi.getList).toHaveBeenLastCalledWith({
      stockCode: '600519',
      page: 1,
      limit: 20,
    });

    await useStockPoolStore.getState().loadMoreStockHistory();

    state = useStockPoolStore.getState();
    expect(state.stockHistoryItems.map((item) => item.id)).toEqual([1, 2]);
    expect(state.stockHistoryHasMore).toBe(false);
    expect(historyApi.getList).toHaveBeenLastCalledWith({
      stockCode: '600519',
      page: 2,
      limit: 20,
    });
  });

  it('deduplicates same-stock trend records when loading more pages', async () => {
    const duplicateCurrentItem = {
      ...historyItem,
      id: 1,
      queryId: 'q-1',
    };
    const olderPageItem = {
      ...historyItem,
      id: 2,
      queryId: 'q-2',
      modelUsed: 'gemini/gemini-2.5-pro',
    };
    const thirdItem = {
      ...historyItem,
      id: 3,
      queryId: 'q-3',
      modelUsed: 'gemini/gemini-2.5-flash',
    };

    useStockPoolStore.setState({ selectedReport: historyReport });
    vi.mocked(historyApi.getList)
      .mockResolvedValueOnce({
        total: 3,
        page: 1,
        limit: 20,
        items: [olderPageItem],
      })
      .mockResolvedValueOnce({
        total: 3,
        page: 2,
        limit: 20,
        items: [duplicateCurrentItem, thirdItem],
      });

    await useStockPoolStore.getState().openHistoryTrend();
    await useStockPoolStore.getState().loadMoreStockHistory();

    const state = useStockPoolStore.getState();
    expect(state.stockHistoryItems.map((item) => item.id)).toEqual([1, 2, 3]);
  });

  it('does not inject the current report when it is outside the selected history time range', async () => {
    const oldSelectedReport = {
      ...historyReport,
      meta: {
        ...historyReport.meta,
        id: 5,
        queryId: 'q-old',
        createdAt: '2020-01-01T08:00:00Z',
      },
    };

    useStockPoolStore.setState({
      selectedReport: oldSelectedReport,
      stockHistoryFilters: {
        range: '30d',
        model: 'all',
        sort: 'desc',
      },
    });
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [
        {
          ...historyItem,
          id: 6,
          queryId: 'q-in-range',
          createdAt: '2026-03-18T08:00:00Z',
        },
      ],
    });

    await useStockPoolStore.getState().openHistoryTrend();

    const state = useStockPoolStore.getState();
    expect(state.stockHistoryItems).toHaveLength(1);
    expect(state.stockHistoryItems[0].id).toBe(6);
    expect(state.stockHistoryItems[0].id).not.toBe(5);
    expect(historyApi.getList).toHaveBeenCalledWith({
      stockCode: '600519',
      startDate: getRecentStartDate(30),
      endDate: getTodayInShanghai(),
      page: 1,
      limit: 20,
    });
  });

  it('closes and resets same-stock trend state when selecting a market-review report', async () => {
    useStockPoolStore.setState({
      selectedReport: historyReport,
      isHistoryTrendOpen: true,
      stockHistoryItems: [{ ...historyItem, modelUsed: 'gemini/gemini-2.5-pro' }],
      stockHistoryTotal: 12,
      stockHistoryPage: 3,
      stockHistoryHasMore: true,
    });

    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(marketReviewHistoryReport);

    await useStockPoolStore.getState().selectHistoryItem(1);

    const state = useStockPoolStore.getState();
    expect(state.selectedReport?.meta.reportType).toBe('market_review');
    expect(state.isHistoryTrendOpen).toBe(false);
    expect(state.stockHistoryItems).toEqual([]);
    expect(state.stockHistoryTotal).toBe(0);
    expect(state.stockHistoryPage).toBe(1);
    expect(state.stockHistoryHasMore).toBe(false);
    expect(state.isLoadingStockHistory).toBe(false);
    expect(state.isLoadingMoreStockHistory).toBe(false);
    expect(historyApi.getList).not.toHaveBeenCalled();
  });

  it('loads market review history through the dedicated MARKET filter', async () => {
    const marketItem = {
      ...historyItem,
      id: 10,
      queryId: 'market-review-q-10',
      stockCode: 'MARKET',
      stockName: '大盘复盘',
      reportType: 'market_review' as const,
      operationAdvice: '查看复盘',
      sentimentScore: 50,
    };
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 10,
      items: [marketItem],
    });

    await useStockPoolStore.getState().loadMarketReviewHistory();

    const state = useStockPoolStore.getState();
    expect(state.marketReviewHistoryItems).toEqual([marketItem]);
    expect(state.marketReviewHistoryHasMore).toBe(false);
    expect(historyApi.getList).toHaveBeenCalledWith({
      stockCode: 'MARKET',
      reportType: 'market_review',
      page: 1,
      limit: 10,
    });
  });

  it('deduplicates market review history after silent refresh shifts pagination', async () => {
    const createMarketReviewItem = (id: number) => ({
      ...historyItem,
      id,
      queryId: `market-review-q-${id}`,
      stockCode: 'MARKET',
      stockName: '大盘复盘',
      reportType: 'market_review' as const,
    });
    const loadedItems = Array.from({ length: 20 }, (_, index) => createMarketReviewItem(index + 1));
    const newlyCompletedItem = createMarketReviewItem(21);

    useStockPoolStore.setState({
      marketReviewHistoryItems: loadedItems,
      marketReviewHistoryPage: 2,
      marketReviewHistoryHasMore: true,
    });
    vi.mocked(historyApi.getList)
      .mockResolvedValueOnce({
        total: 21,
        page: 1,
        limit: 10,
        items: [newlyCompletedItem, ...loadedItems.slice(0, 9)],
      })
      .mockResolvedValueOnce({
        total: 21,
        page: 3,
        limit: 10,
        items: [loadedItems[19]],
      });

    await useStockPoolStore.getState().refreshMarketReviewHistory(true);
    await useStockPoolStore.getState().loadMoreMarketReviewHistory();

    const state = useStockPoolStore.getState();
    expect(state.marketReviewHistoryItems.map((item) => item.id)).toEqual([
      21,
      ...Array.from({ length: 20 }, (_, index) => index + 1),
    ]);
    expect(state.marketReviewHistoryHasMore).toBe(false);
    expect(historyApi.getList).toHaveBeenLastCalledWith({
      stockCode: 'MARKET',
      reportType: 'market_review',
      page: 3,
      limit: 10,
    });
  });

  it('deletes the selected market review history record and clears the open market report', async () => {
    const marketItem = {
      ...historyItem,
      id: 10,
      queryId: 'market-review-q-10',
      stockCode: 'MARKET',
      stockName: '大盘复盘',
      reportType: 'market_review' as const,
    };
    useStockPoolStore.setState({
      marketReviewHistoryItems: [marketItem],
      selectedMarketReviewHistoryIds: [10],
      selectedReport: marketReviewHistoryReport,
    });

    vi.mocked(historyApi.deleteRecords).mockResolvedValue({ deleted: 1 });
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 10,
      items: [],
    });

    await useStockPoolStore.getState().deleteSelectedMarketReviewHistory();

    const state = useStockPoolStore.getState();
    expect(historyApi.deleteRecords).toHaveBeenCalledWith([10]);
    expect(state.marketReviewHistoryItems).toEqual([]);
    expect(state.selectedMarketReviewHistoryIds).toEqual([]);
    expect(state.selectedReport).toBeNull();
  });

  it('deletes selected history and clears the selected report when nothing remains', async () => {
    useStockPoolStore.setState({
      historyItems: [historyItem],
      selectedHistoryIds: [1],
      selectedReport: historyReport,
    });

    vi.mocked(historyApi.deleteRecords).mockResolvedValue({ deleted: 1 });
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });

    await useStockPoolStore.getState().deleteSelectedHistory();

    const state = useStockPoolStore.getState();
    expect(state.historyItems).toHaveLength(0);
    expect(state.selectedHistoryIds).toHaveLength(0);
    expect(state.selectedReport).toBeNull();
    expect(historyApi.getList).toHaveBeenCalledTimes(1);
  });

  it('falls back to the next history report after deleting the currently selected item', async () => {
    const nextHistoryItem = {
      ...historyItem,
      id: 2,
      queryId: 'q-2',
      stockCode: 'AAPL',
      stockName: 'Apple',
    };
    const nextHistoryReport = {
      ...historyReport,
      meta: {
        ...historyReport.meta,
        id: 2,
        queryId: 'q-2',
        stockCode: 'AAPL',
        stockName: 'Apple',
      },
    };

    useStockPoolStore.setState({
      historyItems: [historyItem, nextHistoryItem],
      selectedHistoryIds: [1],
      selectedReport: historyReport,
    });

    vi.mocked(historyApi.deleteRecords).mockResolvedValue({ deleted: 1 });
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [nextHistoryItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(nextHistoryReport);

    await useStockPoolStore.getState().deleteSelectedHistory();

    const state = useStockPoolStore.getState();
    expect(state.historyItems).toHaveLength(1);
    expect(state.historyItems[0].id).toBe(2);
    expect(state.selectedReport?.meta.id).toBe(2);
    expect(state.selectedReport?.meta.stockCode).toBe('AAPL');
  });

  it('surfaces duplicate task errors without replacing the dashboard error state', async () => {
    vi.mocked(analysisApi.analyzeAsync).mockRejectedValue(
      new DuplicateTaskError('600519', 'task-1', '股票 600519 正在分析中'),
    );

    useStockPoolStore.getState().setQuery('600519');
    await useStockPoolStore.getState().submitAnalysis();

    const state = useStockPoolStore.getState();
    expect(state.duplicateError).toContain('600519');
    expect(state.error).toBeNull();
    expect(state.isAnalyzing).toBe(false);
  });

  it('rejects obviously invalid mixed alphanumeric input before calling the API', async () => {
    useStockPoolStore.getState().setQuery('00aaaaa');

    await useStockPoolStore.getState().submitAnalysis();

    const state = useStockPoolStore.getState();
    expect(state.inputError).toBe('请输入有效的股票代码或股票名称');
    expect(state.isAnalyzing).toBe(false);
    expect(analysisApi.analyzeAsync).not.toHaveBeenCalled();
  });

  it('accepts HK suffix codes from autocomplete without local validation errors', async () => {
    vi.mocked(analysisApi.analyzeAsync).mockResolvedValue({
      taskId: 'task-hk-1',
      stockCode: '00700.HK',
      status: 'pending',
      message: 'accepted',
    } as never);

    await useStockPoolStore.getState().submitAnalysis({
      stockCode: '00700.HK',
      stockName: '腾讯控股',
      originalQuery: '00700',
      selectionSource: 'autocomplete',
    });

    const state = useStockPoolStore.getState();
    expect(state.inputError).toBeUndefined();
    expect(state.isAnalyzing).toBe(false);
    expect(analysisApi.analyzeAsync).toHaveBeenCalledWith(expect.objectContaining({
      stockCode: '00700.HK',
      reportType: 'detailed',
      stockName: '腾讯控股',
      originalQuery: '00700',
      selectionSource: 'autocomplete',
      notify: true,
    }));
  });

  it('merges newly discovered history items during silent refresh', async () => {
    useStockPoolStore.setState({
      historyItems: [historyItem],
      currentPage: 1,
      hasMore: true,
    });

    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 2,
      page: 1,
      limit: 20,
      items: [
        { ...historyItem, id: 2, queryId: 'q-2', stockCode: 'AAPL', stockName: 'Apple' },
        historyItem,
      ],
    });

    await useStockPoolStore.getState().refreshHistory(true);

    const state = useStockPoolStore.getState();
    expect(state.historyItems.map((item) => item.id)).toEqual([2, 1]);
    expect(state.currentPage).toBe(1);
  });

  it('ignores late history responses after dashboard reset', async () => {
    const deferred = createDeferred<{
      total: number;
      page: number;
      limit: number;
      items: typeof historyItem[];
    }>();

    vi.mocked(historyApi.getList).mockImplementation(() => deferred.promise);

    const loadPromise = useStockPoolStore.getState().loadInitialHistory();
    useStockPoolStore.getState().resetDashboardState();

    deferred.resolve({
      total: 1,
      page: 1,
      limit: 20,
      items: [historyItem],
    });

    await loadPromise;

    const state = useStockPoolStore.getState();
    expect(state.historyItems).toHaveLength(0);
    expect(state.isLoadingHistory).toBe(false);
    expect(state.currentPage).toBe(1);
  });

  it('tracks task lifecycle updates and resets all dashboard state', () => {
    const pendingTask = {
      taskId: 'task-1',
      stockCode: '600519',
      stockName: '贵州茅台',
      status: 'pending' as const,
      progress: 0,
      reportType: 'detailed',
      createdAt: '2026-03-18T08:00:00Z',
    };

    useStockPoolStore.getState().syncTaskCreated(pendingTask);
    useStockPoolStore.getState().syncTaskUpdated({
      ...pendingTask,
      status: 'processing',
      progress: 60,
    });

    let state = useStockPoolStore.getState();
    expect(state.activeTasks).toHaveLength(1);
    expect(state.activeTasks[0].status).toBe('processing');

    useStockPoolStore.getState().removeTask('task-1');
    state = useStockPoolStore.getState();
    expect(state.activeTasks).toHaveLength(0);

    useStockPoolStore.setState({
      query: 'AAPL',
      selectedHistoryIds: [1],
      selectedReport: historyReport,
      markdownDrawerOpen: true,
      activeTasks: [
        {
          ...pendingTask,
          taskId: 'task-2',
          status: 'processing',
          progress: 80,
        },
      ],
    });

    useStockPoolStore.getState().resetDashboardState();
    state = useStockPoolStore.getState();
    expect(state.activeTasks).toHaveLength(0);
    expect(state.query).toBe('');
    expect(state.selectedHistoryIds).toHaveLength(0);
    expect(state.selectedReport).toBeNull();
    expect(state.markdownDrawerOpen).toBe(false);
  });

  it('ignores late task updates after a task has been removed', () => {
    const pendingTask = {
      taskId: 'task-1',
      stockCode: '600519',
      stockName: '贵州茅台',
      status: 'pending' as const,
      progress: 0,
      reportType: 'detailed',
      createdAt: '2026-03-18T08:00:00Z',
    };

    useStockPoolStore.getState().syncTaskCreated(pendingTask);
    useStockPoolStore.getState().removeTask('task-1');
    useStockPoolStore.getState().syncTaskUpdated({
      ...pendingTask,
      status: 'processing',
      progress: 35,
    });
    useStockPoolStore.getState().syncTaskCreated(pendingTask);

    expect(useStockPoolStore.getState().activeTasks).toHaveLength(0);
  });

  it('ignores unknown task updates after dashboard reset', () => {
    const pendingTask = {
      taskId: 'task-1',
      stockCode: '600519',
      stockName: '贵州茅台',
      status: 'pending' as const,
      progress: 0,
      reportType: 'detailed',
      createdAt: '2026-03-18T08:00:00Z',
    };

    useStockPoolStore.getState().syncTaskCreated(pendingTask);
    useStockPoolStore.getState().resetDashboardState();
    useStockPoolStore.getState().syncTaskUpdated({
      ...pendingTask,
      status: 'processing',
      progress: 35,
    });

    const state = useStockPoolStore.getState();
    expect(state.activeTasks).toHaveLength(0);
  });

  it('does not backfill unknown failed tasks from SSE updates', () => {
    useStockPoolStore.getState().syncTaskFailed({
      taskId: 'task-404',
      stockCode: 'AAPL',
      stockName: 'Apple',
      status: 'failed',
      progress: 100,
      reportType: 'detailed',
      createdAt: '2026-03-18T08:00:00Z',
      error: '分析失败',
    });

    const state = useStockPoolStore.getState();
    expect(state.activeTasks).toHaveLength(0);
    expect(state.error).toBeTruthy();
  });

  it('reconciles active tasks from a complete empty backend snapshot without dismissing them', async () => {
    const staleTask = createTask();
    useStockPoolStore.getState().syncTaskCreated(staleTask);
    vi.mocked(analysisApi.getTasks).mockResolvedValue(createTaskListResponse([]));

    await useStockPoolStore.getState().refreshActiveTasks();

    expect(analysisApi.getTasks).toHaveBeenCalledWith({
      status: 'pending,processing',
      limit: 100,
    });
    expect(useStockPoolStore.getState().activeTasks).toHaveLength(0);

    useStockPoolStore.getState().syncTaskCreated(staleTask);
    expect(useStockPoolStore.getState().activeTasks).toEqual([staleTask]);
  });

  it('does not prune tasks created after an active-task refresh request started', async () => {
    const emptySnapshot = createDeferred<TaskListResponse>();
    const createdTask = createTask({
      taskId: 'task-created-after-request',
      status: 'pending',
      progress: 0,
    });
    const updatedTask = {
      ...createdTask,
      status: 'processing' as const,
      progress: 35,
    };
    vi.mocked(analysisApi.getTasks).mockReturnValue(emptySnapshot.promise);

    const refreshPromise = useStockPoolStore.getState().refreshActiveTasks();
    useStockPoolStore.getState().syncTaskCreated(createdTask);

    emptySnapshot.resolve(createTaskListResponse([]));
    await refreshPromise;

    expect(useStockPoolStore.getState().activeTasks).toEqual([createdTask]);

    useStockPoolStore.getState().syncTaskUpdated(updatedTask);
    expect(useStockPoolStore.getState().activeTasks).toEqual([updatedTask]);
  });

  it('upserts pending and processing tasks from the backend snapshot', async () => {
    const existingTask = createTask({ taskId: 'task-existing', progress: 30 });
    const updatedTask = createTask({ taskId: 'task-existing', progress: 80, message: 'LLM 正在生成分析结果' });
    const newTask = createTask({
      taskId: 'task-new',
      stockCode: '000001',
      stockName: '平安银行',
      status: 'pending',
      progress: 0,
    });
    useStockPoolStore.getState().syncTaskCreated(existingTask);
    vi.mocked(analysisApi.getTasks).mockResolvedValue(
      createTaskListResponse([updatedTask, newTask]),
    );

    await useStockPoolStore.getState().refreshActiveTasks();

    expect(useStockPoolStore.getState().activeTasks).toEqual([updatedTask, newTask]);
  });

  it('does not re-add dismissed tasks from backend reconciliation', async () => {
    const dismissedTask = createTask();
    useStockPoolStore.getState().syncTaskCreated(dismissedTask);
    useStockPoolStore.getState().removeTask(dismissedTask.taskId);
    vi.mocked(analysisApi.getTasks).mockResolvedValue(
      createTaskListResponse([dismissedTask]),
    );

    await useStockPoolStore.getState().refreshActiveTasks();

    expect(useStockPoolStore.getState().activeTasks).toHaveLength(0);
  });

  it('ignores late active-task snapshots from older refreshes', async () => {
    const staleSnapshot = createDeferred<TaskListResponse>();
    const freshSnapshot = createDeferred<TaskListResponse>();
    const staleTask = createTask({ taskId: 'task-stale' });
    const freshTask = createTask({ taskId: 'task-fresh', stockCode: '000001', stockName: '平安银行' });
    vi.mocked(analysisApi.getTasks)
      .mockReturnValueOnce(staleSnapshot.promise)
      .mockReturnValueOnce(freshSnapshot.promise);

    const staleRefresh = useStockPoolStore.getState().refreshActiveTasks();
    const freshRefresh = useStockPoolStore.getState().refreshActiveTasks();

    freshSnapshot.resolve(createTaskListResponse([freshTask]));
    await freshRefresh;
    expect(useStockPoolStore.getState().activeTasks).toEqual([freshTask]);

    staleSnapshot.resolve(createTaskListResponse([staleTask]));
    await staleRefresh;
    expect(useStockPoolStore.getState().activeTasks).toEqual([freshTask]);
  });

  it('does not prune local tasks when the backend active-task snapshot is incomplete', async () => {
    const localTask = createTask({ taskId: 'task-local' });
    const remoteTask = createTask({ taskId: 'task-remote', stockCode: '000001', stockName: '平安银行' });
    useStockPoolStore.getState().syncTaskCreated(localTask);
    vi.mocked(analysisApi.getTasks).mockResolvedValue(
      createTaskListResponse([remoteTask], { processing: 2, total: 2 }),
    );

    await useStockPoolStore.getState().refreshActiveTasks();

    expect(useStockPoolStore.getState().activeTasks).toEqual([localTask, remoteTask]);
  });

  it('keeps active tasks unchanged when backend reconciliation fails', async () => {
    const activeTask = createTask();
    useStockPoolStore.getState().syncTaskCreated(activeTask);
    vi.mocked(analysisApi.getTasks).mockRejectedValue(new Error('network failed'));

    await useStockPoolStore.getState().refreshActiveTasks();

    expect(useStockPoolStore.getState().activeTasks).toEqual([activeTask]);
  });

  it('triggers an analysis with the forceRefresh flag', async () => {
    vi.mocked(analysisApi.analyzeAsync).mockResolvedValue({
      taskId: 'task-force-1',
      status: 'pending',
    } as never);

    await useStockPoolStore.getState().submitAnalysis({
      stockCode: '600519',
      forceRefresh: true,
    });

    expect(analysisApi.analyzeAsync).toHaveBeenCalledWith(expect.objectContaining({
      stockCode: '600519',
      forceRefresh: true,
    }));
  });
});
