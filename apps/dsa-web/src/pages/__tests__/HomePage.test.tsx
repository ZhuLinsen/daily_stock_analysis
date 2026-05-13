import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { analysisApi, DuplicateTaskError } from '../../api/analysis';
import { historyApi } from '../../api/history';
import { systemConfigApi } from '../../api/systemConfig';
import { useStockPoolStore } from '../../stores';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
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
    deleteRecords: vi.fn(),
    getNews: vi.fn().mockResolvedValue({ total: 0, items: [] }),
    getMarkdown: vi.fn().mockResolvedValue('# report'),
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
    },
  };
});

vi.mock('../../api/systemConfig', () => ({
  systemConfigApi: {
    getSetupStatus: vi.fn(),
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

describe('HomePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigateMock.mockReset();
    useStockPoolStore.getState().resetDashboardState();
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
    expect(screen.getByText('暂无历史分析记录')).toBeInTheDocument();
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
      marketReviewReport: Array.from({ length: 30 }, (_, index) => `第 ${index + 1} 行复盘内容`).join('\n'),
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
    expect(await screen.findByText('开始分析')).toBeInTheDocument();
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

  it('confirms and deletes selected history from the dashboard state flow', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [historyItem],
    });
    vi.mocked(historyApi.getDetail).mockResolvedValue(historyReport);
    vi.mocked(historyApi.deleteRecords).mockResolvedValue({ deleted: 1 });

    useStockPoolStore.setState({
      historyItems: [historyItem],
      selectedHistoryIds: [1],
      selectedReport: historyReport,
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '删除' }));

    expect(
      await screen.findByText('确认删除这条历史记录吗？删除后将不可恢复。'),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));

    await waitFor(() => {
      expect(historyApi.deleteRecords).toHaveBeenCalledWith([1]);
    });
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

  it('renders active task panel content from dashboard state', async () => {
    vi.mocked(historyApi.getList).mockResolvedValue({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });

    useStockPoolStore.setState({
      activeTasks: [
        {
          taskId: 'task-1',
          stockCode: '600519',
          stockName: '贵州茅台',
          status: 'processing',
          progress: 45,
          message: '正在抓取最新行情',
          reportType: 'detailed',
          createdAt: '2026-03-18T08:00:00Z',
        },
      ],
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
  });
});
