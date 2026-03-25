import { beforeEach, describe, expect, it, vi } from 'vitest';
import { analysisApi, DuplicateTaskError } from '../../api/analysis';
import { historyApi } from '../../api/history';
import { useStockPoolStore } from '../stockPoolStore';

vi.mock('../../api/history', () => ({
  historyApi: {
    getList: vi.fn(),
    getDetail: vi.fn(),
    deleteRecords: vi.fn(),
  },
}));

vi.mock('../../api/analysis', async () => {
  const actual = await vi.importActual<typeof import('../../api/analysis')>('../../api/analysis');
  return {
    ...actual,
    analysisApi: {
      analyzeAsync: vi.fn(),
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
    expect(analysisApi.analyzeAsync).toHaveBeenCalledWith({
      stockCode: '00700.HK',
      reportType: 'detailed',
      stockName: '腾讯控股',
      originalQuery: '00700',
      selectionSource: 'autocomplete',
      notify: true,
    });
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
});
