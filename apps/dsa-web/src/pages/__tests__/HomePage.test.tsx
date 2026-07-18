import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { analysisApi, DuplicateTaskError } from '../../api/analysis';
import { agentApi } from '../../api/agent';
import { historyApi } from '../../api/history';
import { systemConfigApi } from '../../api/systemConfig';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import { useTaskStream } from '../../hooks/useTaskStream';
import { useStockPoolStore } from '../../stores';
import type { RunFlowSnapshot } from '../../types/runFlow';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import HomePage from '../HomePage';

const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('../../api/history', () => ({
  historyApi: {
    getList: vi.fn(),
    getDetail: vi.fn(),
    getNews: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    getMarkdown: vi.fn().mockResolvedValue('# report'),
    getDiagnostics: vi.fn(),
    getRecordFlow: vi.fn(),
    getStockBarList: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    deleteByCode: vi.fn(),
  },
}));

vi.mock('../../api/analysis', async () => {
  const actual = await vi.importActual<typeof import('../../api/analysis')>('../../api/analysis');
  return {
    ...actual,
    analysisApi: {
      analyzeAsync: vi.fn(),
      triggerMarketReview: vi.fn(),
      getStatus: vi.fn(),
      getTasks: vi.fn(),
      getTaskFlow: vi.fn(),
    },
  };
});

vi.mock('../../api/systemConfig', () => ({
  systemConfigApi: {
    getSetupStatus: vi.fn(),
    getWatchlist: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../api/agent', () => ({
  agentApi: {
    getSkills: vi.fn(),
  },
}));

vi.mock('../../hooks/useTaskStream', () => ({
  useTaskStream: vi.fn(),
}));

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
    reportLanguage: 'zh' as const,
    createdAt: '2026-03-18T08:00:00Z',
  },
  summary: {
    analysisSummary: '趋势维持强势',
    operationAdvice: '继续观察买点',
    trendPrediction: '短线震荡偏强',
    sentimentScore: 78,
  },
};

function configureWatchlistBatch(count: number): string[] {
  const codes = Array.from({ length: count }, (_, index) => `T${String(index + 1).padStart(3, '0')}`);
  vi.mocked(systemConfigApi.getWatchlist).mockResolvedValue(codes);
  vi.mocked(historyApi.getStockBarList).mockResolvedValue({
    total: codes.length,
    items: codes.map((code, index) => ({
      id: 500 + index,
      stockCode: code,
      stockName: code,
      reportType: 'detailed',
      sentimentScore: 60,
      operationAdvice: '观察',
      analysisCount: 1,
      lastAnalysisTime: '2026-01-01T09:00:00+08:00',
    })),
  });
  vi.mocked(historyApi.getList).mockResolvedValue({
    total: 0,
    page: 1,
    limit: 20,
    items: [],
  });
  return codes;
}

const marketReviewHistoryItem = {
  id: 2,
  queryId: 'market-review-q-1',
  stockCode: 'MARKET',
  stockName: '大盘复盘',
  reportType: 'market_review' as const,
  createdAt: '2026-03-18T08:00:00Z',
};

const marketReviewHistoryReport = {
  meta: {
    id: 2,
    queryId: 'market-review-q-1',
    stockCode: 'MARKET',
    stockName: '大盘复盘',
    reportType: 'market_review' as const,
    reportLanguage: 'zh' as const,
    createdAt: '2026-03-18T08:00:00Z',
  },
  summary: {
    analysisSummary: '大盘复盘摘要',
    operationAdvice: '查看复盘',
    trendPrediction: '大盘复盘',
    sentimentScore: 50,
  },
};

const runFlowSnapshot: RunFlowSnapshot = {
  taskId: 'task-1',
  traceId: 'trace-1',
  stockCode: '600519',
  stockName: '贵州茅台',
  status: 'running',
  generatedAt: '2026-06-08T08:00:00Z',
  summary: {
    elapsedMs: 1200,
    failedAttempts: 0,
    fallbackCount: 0,
    dataSourceCount: 1,
    eventCount: 1,
  },
  lanes: [
    { id: 'entry', label: '入口', order: 1 },
    { id: 'analysis', label: '分析引擎', order: 2 },
  ],
  nodes: [
    {
      id: 'request',
      lane: 'entry',
      kind: 'entry',
      label: '用户请求',
      status: 'success',
    },
    {
      id: 'analysis',
      lane: 'analysis',
      kind: 'analysis',
      label: '分析流程',
      status: 'running',
    },
  ],
  edges: [
    {
      id: 'request-analysis',
      from: 'request',
      to: 'analysis',
      kind: 'control',
      status: 'running',
      label: '调度',
    },
  ],
  events: [
    {
      id: 'evt-1',
      timestamp: '2026-06-08T08:00:00Z',
      severity: 'info',
      type: 'task_started',
      nodeId: 'analysis',
      title: '任务开始',
    },
  ],
};

describe('HomePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigateMock.mockReset();
    window.localStorage.clear();
    useStockPoolStore.getState().resetDashboardState();
    vi.mocked(analysisApi.getTasks).mockResolvedValue({
      total: 0,
      pending: 0,
      processing: 0,
      tasks: [],
    });
    vi.mocked(systemConfigApi.getWatchlist).mockResolvedValue([]);
    vi.mocked(agentApi.getSkills).mockResolvedValue({ skills: [], default_skill_id: '' });
    vi.mocked(historyApi.getDiagnostics).mockResolvedValue({
      status: 'unknown',
      statusLabel: '未知',
      reason: '旧报告或诊断证据不足，无法判断本次运行状态',
      components: {},
      copyText: 'data_status: unknown',
    });
    vi.mocked(historyApi.getRecordFlow).mockResolvedValue(runFlowSnapshot);
    vi.mocked(analysisApi.getTaskFlow).mockResolvedValue(runFlowSnapshot);
    vi.mocked(systemConfigApi.getSetupStatus).mockResolvedValue({
      isComplete: true,
      readyForSmoke: true,
      requiredMissingKeys: [],
      nextStepKey: null,
      checks: [],
    });
  });

  it('renders the dashboard workspace and auto-loads the first report', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [historyItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(historyReport);
    vi.mocked(analysisApi.analyzeAsync).mockResolvedValue({
      taskId: 'task-1',
      status: 'pending',
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    const dashboard = await screen.findByTestId('home-dashboard');
    expect(dashboard).toBeInTheDocument();
    expect(dashboard.className).toContain('h-[calc(100vh-5rem)]');
    expect(dashboard.className).toContain('lg:h-[calc(100vh-2rem)]');
    expect(dashboard.firstElementChild?.className).toContain('min-h-0');
    expect(dashboard.querySelector('.flex-1.flex.min-h-0.overflow-hidden')).toBeTruthy();
    expect(screen.getByTestId('home-dashboard-scroll')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('输入股票代码或名称，如 600519、贵州茅台、AAPL')).toBeInTheDocument();
    expect(await screen.findByText('趋势维持强势')).toBeInTheDocument();
    expect(
      screen.getByRole('button', {
        name: getReportText(normalizeReportLanguage(historyReport.meta.reportLanguage)).fullReport,
      }),
    ).toBeInTheDocument();
    expect(historyApi.getMarkdown).not.toHaveBeenCalled();
  });

  it('loads markdown only after opening the full report drawer', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [historyItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(historyReport);
    vi.mocked(historyApi.getMarkdown).mockResolvedValue('# Full Markdown Report');

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    const fullReportButton = await screen.findByRole('button', {
      name: getReportText(normalizeReportLanguage(historyReport.meta.reportLanguage)).fullReport,
    });
    expect(historyApi.getMarkdown).not.toHaveBeenCalled();

    fireEvent.click(fullReportButton);

    await waitFor(() => {
      expect(historyApi.getMarkdown).toHaveBeenCalledWith(historyReport.meta.id);
    });
    expect(await screen.findByRole('heading', { name: 'Full Markdown Report' })).toBeInTheDocument();
  });

  it('shows the empty report workspace when history is empty', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('开始分析')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '开始分析', level: 3 })).toBeInTheDocument();
    expect(screen.getByText('输入股票代码进行分析，或从左侧选择历史报告查看。')).toBeInTheDocument();
    expect(screen.getByText('暂无个股记录')).toBeInTheDocument();
  });

  it('opens the run-flow drawer from an active task in TaskPanel', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });
    vi.mocked(analysisApi.getTasks).mockResolvedValue({
      total: 1,
      pending: 0,
      processing: 1,
      tasks: [
        {
          taskId: 'task-1',
          traceId: 'trace-1',
          stockCode: '600519',
          stockName: '贵州茅台',
          status: 'processing',
          progress: 35,
          message: '分析中',
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
      ],
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '查看 贵州茅台 运行流' }));

    await waitFor(() => {
      expect(analysisApi.getTaskFlow).toHaveBeenCalledWith('task-1');
    });
    expect(await screen.findByTestId('run-flow-panel')).toBeInTheDocument();
    expect(screen.getByText('贵州茅台 运行流')).toBeInTheDocument();
  });

  it('opens the run-flow drawer from completed report diagnostics', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [historyItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(historyReport);

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByText('运行状态'));
    fireEvent.click(screen.getByRole('button', { name: '查看历史记录 1 运行流' }));

    await waitFor(() => {
      expect(historyApi.getRecordFlow).toHaveBeenCalledWith(1);
    });
    expect(await screen.findByTestId('run-flow-panel')).toBeInTheDocument();
    expect(screen.getByText('贵州茅台 历史运行流')).toBeInTheDocument();
  });

  it('shows market review history in the stock bar', async () => {
    vi.mocked(historyApi.getStockBarList).mockResolvedValue({
      total: 1,
      items: [{
        id: 11,
        stockCode: 'AAPL',
        stockName: 'Apple',
        reportType: 'detailed',
        sentimentScore: 72,
        operationAdvice: '观察',
        analysisCount: 2,
        lastAnalysisTime: '2026-03-19T08:00:00Z',
      }],
    });
    vi.mocked(historyApi.getList).mockImplementation((params: { reportType?: string } = {}) => {
      if (params.reportType === 'market_review') {
        return Promise.resolve({
          total: 1,
          page: 1,
          limit: 10,
          items: [marketReviewHistoryItem],
        });
      }
      return Promise.resolve({
        total: 0,
        page: 1,
        limit: 20,
        items: [],
      });
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(marketReviewHistoryReport);

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('button', { name: /MARKET/ })).toBeInTheDocument();
    const newerStockButton = await screen.findByRole('button', { name: /AAPL/ });
    const marketButton = await screen.findByRole('button', { name: /MARKET/ });
    expect(newerStockButton.compareDocumentPosition(marketButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText('大盘复盘历史')).not.toBeInTheDocument();
    expect(historyApi.getList).toHaveBeenCalledWith({
      stockCode: 'MARKET',
      reportType: 'market_review',
      page: 1,
      limit: 10,
    });

    fireEvent.click(await screen.findByRole('button', { name: /MARKET/ }));

    expect(await screen.findByText('大盘复盘摘要')).toBeInTheDocument();
  });

  it('treats timezone-less stock-bar timestamps as Shanghai local time for watchlist pending state', async () => {
    const todayInShanghai = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
    vi.mocked(systemConfigApi.getWatchlist).mockResolvedValue(['600519']);
    vi.mocked(historyApi.getStockBarList).mockResolvedValue({
      total: 1,
      items: [{
        id: 11,
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        sentimentScore: 72,
        operationAdvice: '观察',
        analysisCount: 2,
        lastAnalysisTime: `${todayInShanghai}T23:30:00`,
      }],
    });
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '自选' }));

    expect(await screen.findByLabelText('今日已分析')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '仅未分析' })).toBeDisabled();
    expect(analysisApi.analyzeAsync).not.toHaveBeenCalled();
  });

  it('blocks pending watchlist submission when the stock-bar refresh after completion fails', async () => {
    vi.mocked(systemConfigApi.getWatchlist).mockResolvedValue(['600519']);
    vi.mocked(historyApi.getStockBarList)
      .mockResolvedValueOnce({
        total: 1,
        items: [{
          id: 11,
          stockCode: '600519',
          stockName: '贵州茅台',
          reportType: 'detailed',
          sentimentScore: 72,
          operationAdvice: '观察',
          analysisCount: 1,
          lastAnalysisTime: '2026-01-01T09:00:00+08:00',
        }],
      })
      .mockRejectedValueOnce(new Error('temporary stock-bar failure'));
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '自选' }));
    expect(await screen.findByLabelText('今日未分析')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '仅未分析' })).toBeEnabled();

    const taskStreamOptions = vi.mocked(useTaskStream).mock.calls.at(-1)?.[0];
    act(() => {
      taskStreamOptions?.onTaskCompleted?.({
        taskId: 'task-600519',
        stockCode: '600519',
        stockName: '贵州茅台',
        status: 'completed',
        progress: 100,
        reportType: 'detailed',
        createdAt: '2026-03-18T08:00:00Z',
      });
    });

    expect(await screen.findByLabelText('今日状态未知')).toBeInTheDocument();
    const analyzePendingButton = screen.getByRole('button', { name: '仅未分析' });
    expect(analyzePendingButton).toBeDisabled();
    fireEvent.click(analyzePendingButton);
    expect(analysisApi.analyzeAsync).not.toHaveBeenCalled();
  });

  it('falls back to watchlist history lookup when watchlist code is outside stock-bar window', async () => {
    const todayInShanghai = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
    vi.mocked(systemConfigApi.getWatchlist).mockResolvedValue(['AAPL']);
    vi.mocked(historyApi.getStockBarList).mockResolvedValue({
      total: 1,
      items: [{
        id: 11,
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        sentimentScore: 72,
        operationAdvice: '观察',
        analysisCount: 2,
        lastAnalysisTime: `${todayInShanghai}T22:00:00`,
      }],
    });
    vi.mocked(historyApi.getList).mockImplementation((params: { stockCode?: string } = {}) => {
      if (params.stockCode === 'AAPL') {
        return Promise.resolve({
          total: 1,
          page: 1,
          limit: 1,
          items: [{
            id: 12,
            queryId: 'q-aapl',
            stockCode: 'AAPL',
            stockName: 'Apple',
            reportType: 'detailed' as const,
            sentimentScore: 68,
            operationAdvice: '中性',
            createdAt: `${todayInShanghai}T09:20:00`,
          }],
        });
      }
      if (params.stockCode) {
        return Promise.resolve({
          total: 0,
          page: 1,
          limit: 1,
          items: [],
        });
      }
      if ('startDate' in params) {
        return Promise.resolve({
          total: 1,
          page: 1,
          limit: 100,
          items: [{
            id: 12,
            queryId: 'q-aapl',
            stockCode: 'AAPL',
            stockName: 'Apple',
            reportType: 'detailed' as const,
            sentimentScore: 68,
            operationAdvice: '中性',
            createdAt: `${todayInShanghai}T09:20:00`,
          }],
        });
      }

      return Promise.resolve({
        total: 0,
        page: 1,
        limit: 20,
        items: [],
      });
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '自选' }));

    expect(await screen.findByLabelText('今日已分析')).toBeInTheDocument();
    const analyzePendingButton = screen.getByRole('button', { name: '仅未分析' });
    expect(analyzePendingButton).toBeDisabled();
    fireEvent.click(analyzePendingButton);
    expect(analysisApi.analyzeAsync).not.toHaveBeenCalled();
    expect(screen.queryByText('今天还没有分析结果')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '今日' }));
    expect(await screen.findByRole('button', { name: /Apple/ })).toBeInTheDocument();
  });

  it('keeps pending watchlist submission disabled while fallback history lookup is unresolved', async () => {
    const todayInShanghai = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
    let resolveAaplHistory!: (response: Awaited<ReturnType<typeof historyApi.getList>>) => void;
    const aaplHistoryPromise = new Promise<Awaited<ReturnType<typeof historyApi.getList>>>((resolve) => {
      resolveAaplHistory = resolve;
    });

    vi.mocked(systemConfigApi.getWatchlist).mockResolvedValue(['AAPL']);
    vi.mocked(historyApi.getStockBarList).mockResolvedValue({
      total: 1,
      items: [{
        id: 11,
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        sentimentScore: 72,
        operationAdvice: '观察',
        analysisCount: 2,
        lastAnalysisTime: `${todayInShanghai}T22:00:00`,
      }],
    });
    vi.mocked(historyApi.getList).mockImplementation((params: { stockCode?: string; limit?: number } = {}) => {
      if (params.stockCode === 'AAPL') {
        return aaplHistoryPromise;
      }

      return Promise.resolve({
        total: 0,
        page: 1,
        limit: params.limit ?? 20,
        items: [],
      });
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '自选' }));

    await waitFor(() => {
      expect(historyApi.getList).toHaveBeenCalledWith({ stockCode: 'AAPL', limit: 1 });
    });
    expect(await screen.findByLabelText('确认今日状态中')).toBeInTheDocument();

    const analyzePendingButton = screen.getByRole('button', { name: '仅未分析' });
    expect(analyzePendingButton).toBeDisabled();
    fireEvent.click(analyzePendingButton);
    expect(analysisApi.analyzeAsync).not.toHaveBeenCalled();

    await act(async () => {
      resolveAaplHistory({
        total: 1,
        page: 1,
        limit: 1,
        items: [{
          id: 12,
          queryId: 'q-aapl',
          stockCode: 'AAPL',
          stockName: 'Apple',
          reportType: 'detailed',
          sentimentScore: 68,
          operationAdvice: '中性',
          createdAt: `${todayInShanghai}T09:20:00`,
        }],
      });
      await aaplHistoryPromise;
    });
    expect(await screen.findByLabelText('今日已分析')).toBeInTheDocument();
  });

  it('waits for stock-bar load before launching watchlist fallback lookups', async () => {
    let resolveStockBar!: (response: Awaited<ReturnType<typeof historyApi.getStockBarList>>) => void;
    const stockBarPromise = new Promise<Awaited<ReturnType<typeof historyApi.getStockBarList>>>((resolve) => {
      resolveStockBar = resolve;
    });

    vi.mocked(systemConfigApi.getWatchlist).mockResolvedValue(['AAPL']);
    vi.mocked(historyApi.getStockBarList).mockReturnValue(stockBarPromise);
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '自选' }));

    expect(await screen.findByLabelText('确认今日状态中')).toBeInTheDocument();
    expect(
      vi.mocked(historyApi.getList).mock.calls.some(([params]) => params?.stockCode === 'AAPL'),
    ).toBe(false);

    await act(async () => {
      resolveStockBar({
        total: 0,
        items: [],
      });
      await stockBarPromise;
    });

    await waitFor(() => {
      expect(historyApi.getList).toHaveBeenCalledWith({ stockCode: 'AAPL', limit: 1 });
    });
  });

  it('keeps failed fallback history lookups out of pending submission', async () => {
    vi.mocked(systemConfigApi.getWatchlist).mockResolvedValue(['AAPL']);
    vi.mocked(historyApi.getStockBarList).mockResolvedValue({
      total: 1,
      items: [{
        id: 11,
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        sentimentScore: 72,
        operationAdvice: '观察',
        analysisCount: 2,
        lastAnalysisTime: '2026-03-18T22:00:00',
      }],
    });
    vi.mocked(historyApi.getList).mockImplementation((params: { stockCode?: string; limit?: number } = {}) => {
      if (params.stockCode === 'AAPL') {
        return Promise.reject(new Error('temporary history failure'));
      }

      return Promise.resolve({
        total: 0,
        page: 1,
        limit: params.limit ?? 20,
        items: [],
      });
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '自选' }));

    expect(await screen.findByLabelText('今日状态未知')).toBeInTheDocument();
    const analyzePendingButton = screen.getByRole('button', { name: '仅未分析' });
    expect(analyzePendingButton).toBeDisabled();
    fireEvent.click(analyzePendingButton);
    expect(analysisApi.analyzeAsync).not.toHaveBeenCalled();
  });

  it('loads the Today ranking from paginated history instead of the capped stock bar', async () => {
    const todayInShanghai = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
    const rangeStart = new Date(`${todayInShanghai}T12:00:00Z`);
    rangeStart.setUTCDate(rangeStart.getUTCDate() - 1);
    const rangeEnd = new Date(`${todayInShanghai}T12:00:00Z`);
    rangeEnd.setUTCDate(rangeEnd.getUTCDate() + 1);
    const startDate = rangeStart.toISOString().slice(0, 10);
    const endDate = rangeEnd.toISOString().slice(0, 10);
    vi.mocked(historyApi.getStockBarList).mockResolvedValue({
      total: 1,
      items: [{
        id: 11,
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        sentimentScore: 72,
        operationAdvice: '观察',
        analysisCount: 2,
        lastAnalysisTime: `${todayInShanghai}T10:00:00`,
      }],
    });
    vi.mocked(historyApi.getList).mockImplementation((params: {
      startDate?: string;
      endDate?: string;
      reportType?: string;
      page?: number;
      limit?: number;
    } = {}) => {
      if (params.startDate === startDate && params.endDate === endDate && params.limit === 100) {
        if (params.page === 1) {
          return Promise.resolve({
            total: 101,
            page: 1,
            limit: 100,
            items: Array.from({ length: 100 }, (_, index) => ({
              id: 31 + index,
              queryId: `q-today-${index}`,
              stockCode: index === 0 ? 'AAPL' : `T${index.toString().padStart(3, '0')}`,
              stockName: index === 0 ? 'Apple' : `Stock ${index}`,
              reportType: 'detailed' as const,
              sentimentScore: index === 0 ? 61 : 50,
              operationAdvice: '观察',
              createdAt: `${todayInShanghai}T09:${String(index % 60).padStart(2, '0')}:00`,
            })),
          });
        }

        return Promise.resolve({
          total: 101,
          page: 2,
          limit: 100,
          items: [{
            id: 32,
            queryId: 'q-nvda-today',
            stockCode: 'NVDA',
            stockName: 'NVIDIA',
            reportType: 'detailed' as const,
            sentimentScore: 93,
            operationAdvice: '买入',
            createdAt: `${todayInShanghai}T11:00:00`,
          }],
        });
      }

      return Promise.resolve({
        total: 0,
        page: params.page ?? 1,
        limit: params.limit ?? 20,
        items: [],
      });
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '今日' }));

    await waitFor(() => {
      expect(historyApi.getList).toHaveBeenCalledWith({
        startDate,
        endDate,
        page: 2,
        limit: 100,
      });
    });

    const highScoreButton = await screen.findByRole('button', { name: /NVIDIA/ });
    const lowerScoreButton = screen.getByRole('button', { name: /Apple/ });
    expect(highScoreButton).toBeInTheDocument();
    expect(
      highScoreButton.compareDocumentPosition(lowerScoreButton) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('keeps Shanghai-day records that fall on the previous server date', async () => {
    const todayInShanghai = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
    const rangeStart = new Date(`${todayInShanghai}T12:00:00Z`);
    rangeStart.setUTCDate(rangeStart.getUTCDate() - 1);
    const rangeEnd = new Date(`${todayInShanghai}T12:00:00Z`);
    rangeEnd.setUTCDate(rangeEnd.getUTCDate() + 1);
    const startDate = rangeStart.toISOString().slice(0, 10);
    const endDate = rangeEnd.toISOString().slice(0, 10);

    vi.mocked(historyApi.getStockBarList).mockResolvedValue({ total: 0, items: [] });
    vi.mocked(historyApi.getList).mockImplementation((params: {
      startDate?: string;
      endDate?: string;
      page?: number;
      limit?: number;
    } = {}) => {
      if (params.startDate === startDate && params.endDate === endDate) {
        return Promise.resolve({
          total: 1,
          page: 1,
          limit: 100,
          items: [{
            id: 71,
            queryId: 'q-shanghai-boundary',
            stockCode: 'AAPL',
            stockName: 'Apple',
            reportType: 'detailed' as const,
            sentimentScore: 88,
            operationAdvice: '买入',
            createdAt: `${startDate}T16:30:00Z`,
          }],
        });
      }

      return Promise.resolve({
        total: 0,
        page: params.page ?? 1,
        limit: params.limit ?? 20,
        items: [],
      });
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '今日' }));

    expect(await screen.findByRole('button', { name: /Apple/ })).toBeInTheDocument();
  });

  it('shows an error instead of capped stock-bar fallback when Today ranking load fails', async () => {
    const todayInShanghai = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
    const rangeStart = new Date(`${todayInShanghai}T12:00:00Z`);
    rangeStart.setUTCDate(rangeStart.getUTCDate() - 1);
    const rangeEnd = new Date(`${todayInShanghai}T12:00:00Z`);
    rangeEnd.setUTCDate(rangeEnd.getUTCDate() + 1);
    const startDate = rangeStart.toISOString().slice(0, 10);
    const endDate = rangeEnd.toISOString().slice(0, 10);
    vi.mocked(historyApi.getStockBarList).mockResolvedValue({
      total: 1,
      items: [{
        id: 11,
        stockCode: 'AAPL',
        stockName: 'Apple',
        reportType: 'detailed',
        sentimentScore: 72,
        operationAdvice: '观察',
        analysisCount: 2,
        lastAnalysisTime: `${todayInShanghai}T10:00:00`,
      }],
    });
    vi.mocked(historyApi.getList).mockImplementation((params: { startDate?: string; endDate?: string } = {}) => {
      if (params.startDate === startDate && params.endDate === endDate) {
        return Promise.reject(new Error('today history failed'));
      }

      return Promise.resolve({
        total: 0,
        page: 1,
        limit: 20,
        items: [],
      });
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '今日' }));

    expect(await screen.findByText('今日排行加载失败')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Apple/ })).not.toBeInTheDocument();
  });

  it('refreshes the Today ranking after a stock analysis task completes', async () => {
    const todayInShanghai = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
    const rangeStart = new Date(`${todayInShanghai}T12:00:00Z`);
    rangeStart.setUTCDate(rangeStart.getUTCDate() - 1);
    const rangeEnd = new Date(`${todayInShanghai}T12:00:00Z`);
    rangeEnd.setUTCDate(rangeEnd.getUTCDate() + 1);
    const startDate = rangeStart.toISOString().slice(0, 10);
    const endDate = rangeEnd.toISOString().slice(0, 10);
    let taskCompleted = false;
    vi.mocked(historyApi.getStockBarList).mockImplementation(() => Promise.resolve({
      total: 1,
      items: [{
        id: taskCompleted ? 12 : 11,
        stockCode: taskCompleted ? 'NVDA' : 'AAPL',
        stockName: taskCompleted ? 'NVIDIA' : 'Apple',
        reportType: 'detailed',
        sentimentScore: taskCompleted ? 93 : 72,
        operationAdvice: taskCompleted ? '买入' : '观察',
        analysisCount: 1,
        lastAnalysisTime: `${todayInShanghai}T${taskCompleted ? '11' : '10'}:00:00`,
      }],
    }));
    vi.mocked(historyApi.getList).mockImplementation((params: {
      startDate?: string;
      endDate?: string;
      page?: number;
      limit?: number;
    } = {}) => {
      if (params.startDate === startDate && params.endDate === endDate) {
        return Promise.resolve({
          total: 1,
          page: 1,
          limit: 100,
          items: [{
            id: taskCompleted ? 12 : 11,
            queryId: taskCompleted ? 'q-nvda-today' : 'q-aapl-today',
            stockCode: taskCompleted ? 'NVDA' : 'AAPL',
            stockName: taskCompleted ? 'NVIDIA' : 'Apple',
            reportType: 'detailed' as const,
            sentimentScore: taskCompleted ? 93 : 72,
            operationAdvice: taskCompleted ? '买入' : '观察',
            createdAt: `${todayInShanghai}T${taskCompleted ? '11' : '10'}:00:00`,
          }],
        });
      }

      return Promise.resolve({
        total: 0,
        page: params.page ?? 1,
        limit: params.limit ?? 20,
        items: [],
      });
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '今日' }));
    expect(await screen.findByRole('button', { name: /Apple/ })).toBeInTheDocument();

    const taskStreamOptions = vi.mocked(useTaskStream).mock.calls.at(-1)?.[0];
    expect(taskStreamOptions).toBeDefined();
    taskCompleted = true;
    act(() => {
      taskStreamOptions?.onTaskCompleted?.({
        taskId: 'task-nvda',
        stockCode: 'NVDA',
        stockName: 'NVIDIA',
        status: 'completed',
        progress: 100,
        reportType: 'detailed',
        createdAt: `${todayInShanghai}T10:59:00`,
        completedAt: `${todayInShanghai}T11:00:00`,
      });
    });

    expect(await screen.findByRole('button', { name: /NVIDIA/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Apple/ })).not.toBeInTheDocument();
  });

  it('refreshes the Today ranking when the dashboard becomes visible', async () => {
    const todayInShanghai = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
    let refreshed = false;
    vi.mocked(historyApi.getList).mockImplementation((params: { startDate?: string } = {}) => {
      if (params.startDate) {
        return Promise.resolve({
          total: 1,
          page: 1,
          limit: 100,
          items: [{
            id: refreshed ? 42 : 41,
            queryId: refreshed ? 'q-nvda-visible' : 'q-aapl-visible',
            stockCode: refreshed ? 'NVDA' : 'AAPL',
            stockName: refreshed ? 'NVIDIA' : 'Apple',
            reportType: 'detailed' as const,
            sentimentScore: refreshed ? 93 : 72,
            operationAdvice: refreshed ? '买入' : '观察',
            createdAt: `${todayInShanghai}T10:00:00`,
          }],
        });
      }

      return Promise.resolve({ total: 0, page: 1, limit: 20, items: [] });
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '今日' }));
    expect(await screen.findByRole('button', { name: /Apple/ })).toBeInTheDocument();

    refreshed = true;
    act(() => {
      Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        value: 'visible',
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    expect(await screen.findByRole('button', { name: /NVIDIA/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Apple/ })).not.toBeInTheDocument();
  });

  it('submits a watchlist in multiple chunks and reports the confirmed totals', async () => {
    configureWatchlistBatch(51);
    vi.mocked(analysisApi.analyzeAsync).mockImplementation(async ({ stockCodes = [] }) => ({
      accepted: stockCodes.map((stockCode, index) => ({
        taskId: `task-${stockCode}-${index}`,
        stockCode,
        status: 'pending' as const,
      })),
      duplicates: [],
      message: 'accepted',
    }));

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '自选' }));
    const taskRefreshCallsBeforeSubmit = vi.mocked(analysisApi.getTasks).mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: '分析全部' }));

    expect(await screen.findByText('已提交 51 个任务，0 个正在运行')).toBeInTheDocument();
    expect(analysisApi.analyzeAsync).toHaveBeenCalledTimes(2);
    expect(vi.mocked(analysisApi.analyzeAsync).mock.calls[0]?.[0].stockCodes).toHaveLength(50);
    expect(vi.mocked(analysisApi.analyzeAsync).mock.calls[1]?.[0].stockCodes).toHaveLength(1);
    expect(vi.mocked(analysisApi.getTasks).mock.calls.length).toBeGreaterThan(taskRefreshCallsBeforeSubmit);
  });

  it('reports partial watchlist submission and refreshes accepted tasks after a later chunk fails', async () => {
    configureWatchlistBatch(51);
    vi.mocked(analysisApi.analyzeAsync)
      .mockImplementationOnce(async ({ stockCodes = [] }) => ({
        accepted: stockCodes.slice(0, 45).map((stockCode, index) => ({
          taskId: `task-${stockCode}-${index}`,
          stockCode,
          status: 'pending' as const,
        })),
        duplicates: stockCodes.slice(45).map((stockCode, index) => ({
          stockCode,
          existingTaskId: `existing-${index}`,
          message: 'already running',
        })),
        message: 'accepted',
      }))
      .mockRejectedValueOnce(new Error('gateway timeout'));

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '自选' }));
    const taskRefreshCallsBeforeSubmit = vi.mocked(analysisApi.getTasks).mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: '分析全部' }));

    const status = await screen.findByText(/已确认提交 45 个任务，5 个正在运行；另有 1 只未确认/);
    expect(status).toHaveTextContent('已停止后续提交并刷新任务列表');
    expect(status).toHaveTextContent('服务端访问外部依赖时超时');
    expect(analysisApi.analyzeAsync).toHaveBeenCalledTimes(2);
    expect(vi.mocked(analysisApi.getTasks).mock.calls.length).toBeGreaterThan(taskRefreshCallsBeforeSubmit);
  });

  it('stops when a successful batch response does not account for every requested stock', async () => {
    configureWatchlistBatch(51);
    vi.mocked(analysisApi.analyzeAsync).mockImplementationOnce(async ({ stockCodes = [] }) => ({
      accepted: stockCodes.slice(0, 40).map((stockCode, index) => ({
        taskId: `task-${stockCode}-${index}`,
        stockCode,
        status: 'pending' as const,
      })),
      duplicates: [],
      message: 'incomplete response',
    }));

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '自选' }));
    const taskRefreshCallsBeforeSubmit = vi.mocked(analysisApi.getTasks).mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: '分析全部' }));

    const status = await screen.findByText(/已确认提交 40 个任务，0 个正在运行；另有 11 只未确认/);
    expect(status).toHaveTextContent('本组请求 50 只，仅确认 40 只');
    expect(analysisApi.analyzeAsync).toHaveBeenCalledTimes(1);
    expect(vi.mocked(analysisApi.getTasks).mock.calls.length).toBeGreaterThan(taskRefreshCallsBeforeSubmit);
  });

  it('refreshes the task list and reports a full failure when the first chunk fails', async () => {
    configureWatchlistBatch(51);
    vi.mocked(analysisApi.analyzeAsync).mockRejectedValueOnce(new Error('gateway timeout'));

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '自选' }));
    const taskRefreshCallsBeforeSubmit = vi.mocked(analysisApi.getTasks).mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: '分析全部' }));

    expect(await screen.findByText(/服务端访问外部依赖时超时/)).toBeInTheDocument();
    expect(screen.queryByText(/已确认提交/)).not.toBeInTheDocument();
    expect(analysisApi.analyzeAsync).toHaveBeenCalledTimes(1);
    expect(vi.mocked(analysisApi.getTasks).mock.calls.length).toBeGreaterThan(taskRefreshCallsBeforeSubmit);
  });

  it('counts a single-stock duplicate as a confirmed running task', async () => {
    configureWatchlistBatch(1);
    vi.mocked(analysisApi.analyzeAsync).mockRejectedValueOnce(
      new DuplicateTaskError('T001', 'existing-task', 'T001 is already running'),
    );

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '自选' }));
    fireEvent.click(screen.getByRole('button', { name: '分析全部' }));

    expect(await screen.findByText('已提交 0 个任务，1 个正在运行')).toBeInTheDocument();
    expect(analysisApi.analyzeAsync).toHaveBeenCalledTimes(1);
  });

  it('removes the MARKET stock bar item after deleting market review history', async () => {
    let isMarketReviewDeleted = false;
    vi.mocked(historyApi.getStockBarList).mockResolvedValue({
      total: 0,
      items: [],
    });
    vi.mocked(historyApi.getList).mockImplementation((params: { reportType?: string } = {}) => {
      if (params.reportType === 'market_review') {
        return Promise.resolve({
          total: isMarketReviewDeleted ? 0 : 1,
          page: 1,
          limit: 10,
          items: isMarketReviewDeleted ? [] : [marketReviewHistoryItem],
        });
      }
      return Promise.resolve({
        total: 0,
        page: 1,
        limit: 20,
        items: [],
      });
    });
    vi.mocked(historyApi.deleteByCode).mockImplementation(async () => {
      isMarketReviewDeleted = true;
      return { deleted: 1 };
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('button', { name: /MARKET/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '删除 大盘复盘 历史记录' }));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /MARKET/ })).not.toBeInTheDocument();
    });
    expect(historyApi.deleteByCode).toHaveBeenCalledWith('MARKET');
  });

  it('surfaces duplicate task warnings from dashboard submission', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });
    vi.mocked(analysisApi.analyzeAsync).mockRejectedValue(
      new DuplicateTaskError('600519', 'task-1', '股票 600519 正在分析中'),
    );

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    const input = await screen.findByPlaceholderText('输入股票代码或名称，如 600519、贵州茅台、AAPL');
    fireEvent.change(input, { target: { value: '600519' } });
    fireEvent.click(screen.getByRole('button', { name: '分析' }));

    await waitFor(() => {
      expect(screen.getByText(/股票 600519 正在分析中/)).toBeInTheDocument();
    });
    expect(screen.getByText(/股票 600519 正在分析中/).closest('[role="alert"]')).toBeInTheDocument();
  });

  it('dismisses the duplicate task banner when its close button is clicked', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    await screen.findByPlaceholderText('输入股票代码或名称，如 600519、贵州茅台、AAPL');

    act(() => {
      useStockPoolStore.setState({ duplicateError: '股票 600519 正在分析中，请等待完成' });
    });

    expect(screen.getByText(/股票 600519 正在分析中/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '关闭' }));

    expect(screen.queryByText(/股票 600519 正在分析中/)).not.toBeInTheDocument();
  });

  it('auto-dismisses the duplicate task banner after 5 seconds', async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(historyApi.getList).mockResolvedValue({
        total: 0,
        page: 1,
        limit: 20,
        items: [],
      });

      render(
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>,
      );

      await act(async () => {
        await Promise.resolve();
      });

      act(() => {
        useStockPoolStore.setState({ duplicateError: '股票 600519 正在分析中，请等待完成' });
      });

      expect(screen.getByText(/股票 600519 正在分析中/)).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4999);
      });
      expect(screen.getByText(/股票 600519 正在分析中/)).toBeInTheDocument();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(screen.queryByText(/股票 600519 正在分析中/)).not.toBeInTheDocument();
    } finally {
      vi.runOnlyPendingTimers();
      vi.useRealTimers();
    }
  });

  it('restarts the auto-dismiss countdown when a duplicate task is triggered again', async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(historyApi.getList).mockResolvedValue({
        total: 0,
        page: 1,
        limit: 20,
        items: [],
      });

      render(
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>,
      );

      await act(async () => {
        await Promise.resolve();
      });

      act(() => {
        useStockPoolStore.setState({ duplicateError: '股票 600519 正在分析中，请等待完成' });
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4000);
      });
      expect(screen.getByText(/股票 600519 正在分析中/)).toBeInTheDocument();

      // Trigger the duplicate prompt again (the store clears then re-sets the message).
      act(() => {
        useStockPoolStore.setState({ duplicateError: null });
      });
      act(() => {
        useStockPoolStore.setState({ duplicateError: '股票 600519 正在分析中，请等待完成' });
      });

      // 4s after the restart: still within the fresh 5s window because the countdown reset.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(4000);
      });
      expect(screen.getByText(/股票 600519 正在分析中/)).toBeInTheDocument();

      // Crossing the fresh 5s threshold finally closes the banner.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(screen.queryByText(/股票 600519 正在分析中/)).not.toBeInTheDocument();
    } finally {
      vi.runOnlyPendingTimers();
      vi.useRealTimers();
    }
  });

  it('submits market review from the home toolbar', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });
    vi.mocked(analysisApi.triggerMarketReview).mockResolvedValue({
      status: 'accepted',
      sendNotification: true,
      message: '大盘复盘任务已提交',
      taskId: 'task-1',
    });
    vi.mocked(analysisApi.getStatus).mockResolvedValue({
      taskId: 'task-1',
      status: 'completed',
      marketReviewReport: '市场复盘报告示例文本',
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '大盘复盘' }));

    await waitFor(() => {
      expect(analysisApi.triggerMarketReview).toHaveBeenCalledWith({ sendNotification: true });
    });
    expect(await screen.findByText('大盘复盘已完成')).toBeInTheDocument();
    expect(await screen.findByText('市场复盘报告示例文本')).toBeInTheDocument();
    expect(analysisApi.getStatus).toHaveBeenCalledWith('task-1');
  });

  it('keeps report language unset when only the UI language is English', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });
    vi.mocked(analysisApi.analyzeAsync).mockResolvedValue({
      taskId: 'task-1',
      status: 'pending',
    });
    vi.mocked(analysisApi.triggerMarketReview).mockResolvedValue({
      status: 'accepted',
      sendNotification: true,
      message: 'Market review task submitted',
      taskId: 'market-task-1',
    });
    vi.mocked(analysisApi.getStatus).mockResolvedValue({
      taskId: 'market-task-1',
      status: 'completed',
      marketReviewReport: 'Market review report',
      marketReviewPayload: {
        kind: 'market_review',
        language: 'en',
        title: 'Market review',
        sections: [],
      },
    });

    render(
      <UiLanguageProvider>
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>
      </UiLanguageProvider>,
    );

    fireEvent.change(await screen.findByPlaceholderText('Enter a stock code or name, e.g. 600519, Kweichow Moutai, AAPL'), {
      target: { value: 'AAPL' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Analyze' }));
    fireEvent.click(screen.getByRole('button', { name: 'Market review' }));

    await waitFor(() => {
      expect(analysisApi.analyzeAsync).toHaveBeenCalled();
      expect(analysisApi.triggerMarketReview).toHaveBeenCalledWith({ sendNotification: true });
    });
    expect(vi.mocked(analysisApi.analyzeAsync).mock.calls[0]?.[0]).not.toHaveProperty('reportLanguage');
  });

  it('uses the payload language for live market review controls', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });
    vi.mocked(analysisApi.triggerMarketReview).mockResolvedValue({
      status: 'accepted',
      sendNotification: true,
      message: 'Market review task submitted',
      taskId: 'task-1',
    });
    vi.mocked(analysisApi.getStatus).mockResolvedValue({
      taskId: 'task-1',
      status: 'completed',
      marketReviewReport: '# US Market Recap\n\n## Summary\n\nUS market review body',
      marketReviewPayload: {
        kind: 'market_review',
        region: 'us',
        language: 'en',
        title: 'US Market Recap',
        sections: [
          {
            key: 'summary',
            title: 'Summary',
            markdown: 'US market review body',
          },
        ],
      },
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '大盘复盘' }));

    expect(await screen.findByRole('button', { name: 'Copy Markdown Source' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy Plain Text' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '复制 Markdown 源码' })).not.toBeInTheDocument();
  });

  it('scrolls the dashboard to market review feedback after toolbar clicks', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [historyItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(historyReport);
    vi.mocked(analysisApi.triggerMarketReview).mockResolvedValue({
      status: 'accepted',
      sendNotification: true,
      message: '大盘复盘任务已提交',
      taskId: 'task-1',
    });
    vi.mocked(analysisApi.getStatus).mockResolvedValue({
      taskId: 'task-1',
      status: 'completed',
      marketReviewReport: '市场复盘报告示例文本',
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    await screen.findByText('趋势维持强势');
    const dashboardScroll = screen.getByTestId('home-dashboard-scroll');
    const scrollToMock = vi.fn(function scrollTo(this: HTMLElement, options?: ScrollToOptions) {
      if (typeof options?.top === 'number') {
        this.scrollTop = options.top;
      }
    });
    Object.defineProperty(dashboardScroll, 'scrollTo', {
      configurable: true,
      value: scrollToMock,
    });
    dashboardScroll.scrollTop = 480;

    fireEvent.click(screen.getByRole('button', { name: '大盘复盘' }));

    await waitFor(() => {
      expect(scrollToMock).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
    });
    expect(dashboardScroll.scrollTop).toBe(0);
    expect(await screen.findByText('大盘复盘已完成')).toBeInTheDocument();
  });

  it('keeps market review results in the main dashboard scroll area', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });
    vi.mocked(analysisApi.triggerMarketReview).mockResolvedValue({
      status: 'accepted',
      sendNotification: true,
      message: '大盘复盘任务已提交',
      taskId: 'task-1',
    });
    vi.mocked(analysisApi.getStatus).mockResolvedValue({
      taskId: 'task-1',
      status: 'completed',
      marketReviewReport: [
        '# A股市场复盘',
        '',
        '> 市场情绪修复',
        '',
        '## 指数概览',
        '',
        '| 指数 | 表现 |',
        '| --- | --- |',
        '| 上证指数 | 震荡走强 |',
        '',
        '## 风险提示',
        '',
        '- 资金回流核心资产',
      ].join('\n'),
      marketReviewPayload: {
        kind: 'market_review',
        region: 'cn',
        title: 'A股市场复盘',
        breadth: {
          upCount: 3200,
          downCount: 1700,
          limitUpCount: 60,
          limitDownCount: 8,
          totalAmount: 9800,
          turnoverUnit: '亿',
        },
        indices: [
          {
            code: '000001',
            name: '上证指数',
            current: 3150.2,
            changePct: 0.62,
            high: 3168.4,
            low: 3120.8,
          },
        ],
        sections: [
          {
            key: 'index_overview',
            title: '指数概览',
            markdown: '| 指数 | 表现 |\n| --- | --- |\n| 上证指数 | 震荡走强 |',
          },
          {
            key: 'risk',
            title: '风险提示',
            markdown: '- 资金回流核心资产',
          },
        ],
      },
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '大盘复盘' }));

    const dashboardScroll = screen.getByTestId('home-dashboard-scroll');
    const marketReviewReport = await screen.findByTestId('market-review-report');
    expect(dashboardScroll).toContainElement(marketReviewReport);
    expect(marketReviewReport.className).not.toContain('max-h-64');
    expect(marketReviewReport.className).not.toContain('overflow-y-auto');
    expect(screen.getByRole('heading', { name: '结构化大盘数据' })).toBeInTheDocument();
    expect(screen.getByText('3200')).toBeInTheDocument();
    expect(screen.getByText('3150.20')).toBeInTheDocument();
    expect(marketReviewReport.querySelector('h2, h3')?.textContent).not.toBe('A股市场复盘');
    expect(screen.getByRole('heading', { name: '指数概览' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '风险提示' })).toBeInTheDocument();
    expect(screen.getAllByRole('table').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('# A股市场复盘')).not.toBeInTheDocument();
    expect(screen.queryByText('开始分析')).not.toBeInTheDocument();
  });

  it('shows first-run setup gaps and links to settings', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });
    vi.mocked(systemConfigApi.getSetupStatus).mockResolvedValue({
      isComplete: false,
      readyForSmoke: false,
      requiredMissingKeys: ['llm_primary', 'stock_list'],
      nextStepKey: 'llm_primary',
      checks: [
        {
          key: 'llm_primary',
          title: 'LLM 主渠道',
          category: 'ai_model',
          required: true,
          status: 'needs_action',
          message: '缺少主模型配置',
        },
        {
          key: 'stock_list',
          title: '自选股',
          category: 'base',
          required: true,
          status: 'needs_action',
          message: '缺少自选股',
        },
      ],
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('基础配置未完成')).toBeInTheDocument();
    expect(screen.getByText(/LLM 主渠道、自选股/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '去配置' }));
    expect(navigateMock).toHaveBeenCalledWith('/settings');
  });

  it('navigates to chat with report context when asking a follow-up question', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [historyItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(historyReport);

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    const followUpButton = await screen.findByRole('button', { name: '追问 AI' });
    fireEvent.click(followUpButton);

    expect(navigateMock).toHaveBeenCalledWith(
      '/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0&recordId=1',
    );
  });

  it('opens and closes the mobile history drawer without changing dashboard styles', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });

    const { container } = render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    const trigger = await screen.findByRole('button', { name: '历史记录' });
    fireEvent.click(trigger);

    expect(container.querySelector('.page-drawer-overlay')).toBeTruthy();
    expect(container.querySelector('.dashboard-card')).toBeTruthy();

    fireEvent.click(container.querySelector('.fixed.inset-0.z-40') as HTMLElement);

    await waitFor(() => {
      expect(container.querySelector('.page-drawer-overlay')).toBeFalsy();
    });
  });

  it('keeps same-stock history range controls in empty result state and allows switching back', async () => {
    const staleReport = {
      ...historyReport,
      meta: {
        ...historyReport.meta,
        createdAt: '2020-01-01T08:00:00Z',
      },
    };

    vi.mocked(historyApi.getStockBarList).mockResolvedValue({
      total: 1,
      items: [
        {
          id: 1,
          stockCode: '600519',
          stockName: '贵州茅台',
          reportType: 'detailed',
          sentimentScore: 58,
          operationAdvice: '继续观察买点',
          analysisCount: 2,
          lastAnalysisTime: '2026-03-21T08:00:00Z',
        },
      ],
    });

    vi.mocked(historyApi.getList).mockImplementation((params: { stockCode?: string; startDate?: string } = {}) => {
      if (!Object.prototype.hasOwnProperty.call(params, 'stockCode')) {
        return Promise.resolve({
          total: 1,
          page: 1,
          limit: 20,
          items: [historyItem],
        });
      }

      return Promise.resolve({
        total: 0,
        page: 1,
        limit: 20,
        items: [],
      });
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(staleReport);

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    const historyTrendButton = await screen.findByRole('button', { name: '历史趋势' });
    fireEvent.click(historyTrendButton);

    const range30Button = await screen.findByRole('button', { name: '近30天' });
    fireEvent.click(range30Button);

    await waitFor(() => {
      expect(screen.getByText('暂无更多同股历史分析')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '全部历史' })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: '全部历史' }));

    await waitFor(() => {
      expect(screen.queryByText('暂无更多同股历史分析')).not.toBeInTheDocument();
    });
    expect(screen.getAllByRole('button', { name: /贵州茅台/ }).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/2次/)).toBeInTheDocument();

    const historyCalls = vi.mocked(historyApi.getList).mock.calls.filter((call) => call[0]?.stockCode === '600519');
    expect(historyCalls).toHaveLength(3);
    expect(historyCalls[1][0]).toHaveProperty('startDate');
    expect(historyCalls[2][0]).not.toHaveProperty('startDate');
  });

  it('renders active task panel content from dashboard state', async () => {
    const activeTask = {
      taskId: 'task-1',
      stockCode: '600519',
      stockName: '贵州茅台',
      status: 'processing' as const,
      progress: 45,
      message: '正在抓取最新行情',
      reportType: 'detailed',
      createdAt: '2026-03-18T08:00:00Z',
    };
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });
    vi.mocked(analysisApi.getTasks).mockResolvedValue({
      total: 1,
      pending: 0,
      processing: 1,
      tasks: [activeTask],
    });

    useStockPoolStore.setState({
      activeTasks: [activeTask],
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('分析任务')).toBeInTheDocument();
    expect(screen.getByText('正在抓取最新行情')).toBeInTheDocument();
  });

  it('triggers reanalyze for the current report even if the search input has other text', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [historyItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(historyReport);
    vi.mocked(analysisApi.analyzeAsync).mockResolvedValue({
      taskId: 'task-re-1',
      status: 'pending',
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    // Wait for the report to load
    await screen.findByText('趋势维持强势');

    // Type something else in the search box
    const input = screen.getByPlaceholderText('输入股票代码或名称，如 600519、贵州茅台、AAPL');
    fireEvent.change(input, { target: { value: 'AAPL' } });

    // Click "Reanalyze"
    const reanalyzeButton = screen.getByRole('button', { name: '重新分析' });
    fireEvent.click(reanalyzeButton);

    // Verify that analyzeAsync is called with the report's stock code, not the search box text
    expect(analysisApi.analyzeAsync).toHaveBeenCalledWith(expect.objectContaining({
      stockCode: '600519',
      originalQuery: '600519',
      forceRefresh: true,
    }));
    expect(vi.mocked(analysisApi.analyzeAsync).mock.calls[0]?.[0]).not.toHaveProperty('reportLanguage');
  });

  it('passes the selected strategy when submitting stock analysis', async () => {
    vi.mocked(agentApi.getSkills).mockResolvedValue({
      default_skill_id: 'bull_trend',
      skills: [
        { id: 'bull_trend', name: '默认多头趋势', description: '趋势分析' },
        { id: 'growth_quality', name: '成长质量', description: '成长股分析' },
      ],
    });
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });
    vi.mocked(analysisApi.analyzeAsync).mockResolvedValue({
      taskId: 'task-strategy-1',
      status: 'pending',
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '策略' }));
    fireEvent.click(screen.getByRole('menuitemradio', { name: /成长质量/ }));

    const input = screen.getByPlaceholderText('输入股票代码或名称，如 600519、贵州茅台、AAPL');
    fireEvent.change(input, { target: { value: '600519' } });
    fireEvent.click(screen.getByRole('button', { name: '分析' }));

    await waitFor(() => {
      expect(analysisApi.analyzeAsync).toHaveBeenCalledWith(expect.objectContaining({
        stockCode: '600519',
        skills: ['growth_quality'],
      }));
    });
  });

  it('supports keyboard navigation in the strategy menu', async () => {
    vi.mocked(agentApi.getSkills).mockResolvedValue({
      default_skill_id: 'bull_trend',
      skills: [
        { id: 'bull_trend', name: '默认多头趋势', description: '趋势分析' },
        { id: 'growth_quality', name: '成长质量', description: '成长股分析' },
      ],
    });
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    const trigger = await screen.findByRole('button', { name: '策略' });
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });

    const defaultOption = await screen.findByRole('menuitemradio', { name: /默认策略/ });
    await waitFor(() => {
      expect(defaultOption).toHaveFocus();
    });

    const menu = screen.getByRole('menu');
    fireEvent.keyDown(menu, { key: 'ArrowDown' });
    expect(screen.getByRole('menuitemradio', { name: /默认多头趋势/ })).toHaveFocus();

    fireEvent.keyDown(menu, { key: 'End' });
    expect(screen.getByRole('menuitemradio', { name: /成长质量/ })).toHaveFocus();

    fireEvent.keyDown(menu, { key: 'Escape' });
    await waitFor(() => {
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });
    expect(trigger).toHaveFocus();
  });

  it('renders market review history reports with a dedicated markdown view', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [marketReviewHistoryItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(marketReviewHistoryReport);
    vi.mocked(historyApi.getMarkdown).mockResolvedValue([
      '# 大盘复盘详情',
      '',
      '## 市场情绪与赚钱效应',
      '',
      '**赚钱效应** 改善',
      '',
      '## 行业/主题轮动',
      '',
      '| 方向 | 状态 |',
      '| --- | --- |',
      '| 半导体 | 轮动增强 |',
    ].join('\n'));

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    await screen.findByText('大盘复盘摘要');
    expect(screen.queryByRole('heading', { name: '大盘复盘详情' })).not.toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: '市场情绪与赚钱效应' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '行业/主题轮动' })).toBeInTheDocument();
    expect(screen.getByText('赚钱效应')).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '重新分析' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '追问 AI' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新复盘' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '历史趋势' })).toBeInTheDocument();
    expect(historyApi.getMarkdown).toHaveBeenCalledWith(marketReviewHistoryReport.meta.id);

    expect(analysisApi.analyzeAsync).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('clears live market review output when switching to a history report', async () => {
    vi.mocked(historyApi.getList).mockImplementation((params: { reportType?: string } = {}) => {
      if (params.reportType === 'market_review') {
        return Promise.resolve({
          total: 1,
          page: 1,
          limit: 10,
          items: [marketReviewHistoryItem],
        });
      }
      return Promise.resolve({
        total: 1,
        page: 1,
        limit: 20,
        items: [historyItem],
      });
    });
    vi.mocked(historyApi.getStockBarList).mockResolvedValue({
      total: 1,
      items: [
        {
          id: 1,
          stockCode: '600519',
          stockName: '贵州茅台',
          sentimentScore: 82,
          operationAdvice: '买入',
          analysisCount: 1,
          lastAnalysisTime: '2026-03-18T08:00:00Z',
          reportType: 'detailed',
        },
      ],
    });
    vi.mocked(historyApi.getDetail).mockImplementation((recordId: number) => {
      if (recordId === 2) {
        return Promise.resolve(marketReviewHistoryReport);
      }
      return Promise.resolve(historyReport);
    });
    vi.mocked(historyApi.getMarkdown).mockResolvedValue([
      '# 大盘复盘详情',
      '',
      '## 市场情绪与赚钱效应',
      '',
      '**赚钱效应** 改善',
      '',
      '## 行业/主题轮动',
      '',
      '| 方向 | 状态 |',
      '| --- | --- |',
      '| 半导体 | 轮动增强 |',
    ].join('\n'));
    vi.mocked(analysisApi.triggerMarketReview).mockResolvedValue({
      status: 'accepted',
      sendNotification: true,
      message: '大盘复盘任务已提交',
      taskId: 'task-1',
    });
    vi.mocked(analysisApi.getStatus).mockResolvedValue({
      taskId: 'task-1',
      status: 'completed',
      marketReviewReport: '市场复盘报告示例文本',
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    await screen.findByText('趋势维持强势');

    fireEvent.click(screen.getByRole('button', { name: '大盘复盘' }));

    await waitFor(() => {
      expect(screen.getByText('大盘复盘已完成')).toBeInTheDocument();
      expect(screen.getByText('市场复盘报告示例文本')).toBeInTheDocument();
    });

    const marketHistoryButton = await screen.findByRole('button', { name: /MARKET/ });
    fireEvent.click(marketHistoryButton);

    await waitFor(() => {
      expect(screen.queryByText('市场复盘报告示例文本')).not.toBeInTheDocument();
      expect(screen.queryByText('大盘复盘已完成')).not.toBeInTheDocument();
    });
    expect(await screen.findByText('大盘复盘摘要')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '市场情绪与赚钱效应' })).toBeInTheDocument();
    expect(vi.mocked(historyApi.getDetail)).toHaveBeenCalledWith(2);
  });
});
