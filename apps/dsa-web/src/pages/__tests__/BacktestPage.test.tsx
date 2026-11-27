import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { toCamelCase } from '../../api/utils';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import type { PerformanceMetrics } from '../../types/backtest';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import BacktestPage from '../BacktestPage';

const {
  mockGetResults,
  mockGetOverallPerformance,
  mockGetStockPerformance,
  mockRun,
} = vi.hoisted(() => ({
  mockGetResults: vi.fn(),
  mockGetOverallPerformance: vi.fn(),
  mockGetStockPerformance: vi.fn(),
  mockRun: vi.fn(),
}));

vi.mock('../../api/backtest', () => ({
  backtestApi: {
    getResults: mockGetResults,
    getOverallPerformance: mockGetOverallPerformance,
    getStockPerformance: mockGetStockPerformance,
    run: mockRun,
  },
}));

const basePerformance = {
  scope: 'overall',
  evalWindowDays: 10,
  engineVersion: 'test-engine',
  totalEvaluations: 3,
  completedCount: 2,
  insufficientCount: 1,
  longCount: 2,
  cashCount: 1,
  winCount: 1,
  lossCount: 1,
  neutralCount: 0,
  directionAccuracyPct: 66.7,
  winRatePct: 50,
  neutralRatePct: 0,
  avgStockReturnPct: 2.4,
  avgSimulatedReturnPct: 1.2,
  stopLossTriggerRate: 10,
  takeProfitTriggerRate: 20,
  ambiguousRate: 0,
  avgDaysToFirstHit: 3.5,
  adviceBreakdown: {},
  diagnostics: {},
};

const baseResultItem = {
  analysisHistoryId: 101,
  code: '600519',
  stockName: '贵州茅台',
  analysisDate: '2026-03-20',
  evalWindowDays: 10,
  engineVersion: 'test-engine',
  evalStatus: 'completed',
  operationAdvice: '继续持有',
  action: 'watch',
  actionLabel: '观望',
  trendPrediction: '震荡偏多',
  actualMovement: 'up',
  actualReturnPct: 3.8,
  directionExpected: 'long',
  directionCorrect: true,
  outcome: 'win',
  simulatedReturnPct: 3.8,
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  mockGetOverallPerformance.mockResolvedValue(basePerformance);
  mockGetStockPerformance.mockResolvedValue(null);
  mockGetResults.mockResolvedValue({
    total: 1,
    page: 1,
    limit: 20,
    items: [baseResultItem],
  });
  mockRun.mockResolvedValue({
    processed: 1,
    saved: 1,
    completed: 1,
    insufficient: 0,
    errors: 0,
  });
});

describe('BacktestPage', () => {
  function renderEnglishPage() {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    render(
      <UiLanguageProvider>
        <BacktestPage />
      </UiLanguageProvider>,
    );
  }

  it('renders shared surface inputs and prediction tracking outputs', async () => {
    render(<BacktestPage />);

    const filterInput = await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）');
    const windowInput = screen.getByPlaceholderText('10');

    expect(filterInput).toHaveClass('input-surface');
    expect(filterInput).toHaveClass('input-focus-glow');
    expect(windowInput).toHaveClass('input-surface');
    expect(windowInput).toHaveClass('input-focus-glow');

    expect(await screen.findByText('盈利')).toBeInTheDocument();
    expect(screen.getByText('已完成')).toBeInTheDocument();
    expect(screen.getByText('600519')).toBeInTheDocument();
    expect(screen.getByText('贵州茅台')).toBeInTheDocument();
    const resultRow = screen.getByText('600519').closest('tr');
    expect(resultRow).not.toBeNull();
    const rowScope = within(resultRow as HTMLElement);
    expect(rowScope.getByText('观望')).toBeInTheDocument();
    expect(rowScope.getByText('震荡偏多')).toBeInTheDocument();
    expect(rowScope.getByText('继续持有')).toBeInTheDocument();
    expect(screen.getByText('上涨')).toBeInTheDocument();
    expect(screen.getByText('窗口收益')).toBeInTheDocument();
    expect(screen.getByText('方向匹配')).toBeInTheDocument();
    expect(screen.getByText('做多')).toBeInTheDocument();
    expect(screen.getAllByLabelText('是').length).toBeGreaterThan(0);
    expect(screen.getByText('方向准确率')).toBeInTheDocument();
    expect(screen.getByText('平均模拟收益')).toBeInTheDocument();
  });

  it('falls back to the taxonomy label when backtest actionLabel is missing', async () => {
    mockGetResults.mockResolvedValueOnce({
      total: 1,
      page: 1,
      limit: 20,
      items: [
        {
          ...baseResultItem,
          action: 'watch',
          actionLabel: null,
        },
      ],
    });

    render(<BacktestPage />);

    const codeCell = await screen.findByText('600519');
    const resultRow = codeCell.closest('tr');
    expect(resultRow).not.toBeNull();
    const rowScope = within(resultRow as HTMLElement);
    expect(rowScope.getByText('观望')).toBeInTheDocument();
    expect(rowScope.getByText('继续持有')).toBeInTheDocument();
  });

  it('uses localized taxonomy labels before server labels in English UI mode', async () => {
    mockGetResults.mockResolvedValueOnce({
      total: 1,
      page: 1,
      limit: 20,
      items: [
        {
          ...baseResultItem,
          operationAdvice: 'continue holding',
          action: 'watch',
          actionLabel: '观望',
          trendPrediction: 'range-bound',
        },
      ],
    });

    renderEnglishPage();

    const codeCell = await screen.findByText('600519');
    const resultRow = codeCell.closest('tr');
    expect(resultRow).not.toBeNull();
    const rowScope = within(resultRow as HTMLElement);
    expect(rowScope.getByText('Watch')).toBeInTheDocument();
    expect(rowScope.getByText('continue holding')).toBeInTheDocument();
    expect(rowScope.queryByText('观望')).not.toBeInTheDocument();
  });

  it('keeps operation advice visible when backtest action fields are absent for multi-guard advice', async () => {
    mockGetResults.mockResolvedValueOnce({
      total: 1,
      page: 1,
      limit: 20,
      items: [
        {
          ...baseResultItem,
          operationAdvice: 'risk alert, avoid buying',
          action: null,
          actionLabel: null,
        },
      ],
    });

    render(<BacktestPage />);

    const codeCell = await screen.findByText('600519');
    const resultRow = codeCell.closest('tr');
    expect(resultRow).not.toBeNull();
    const rowScope = within(resultRow as HTMLElement);
    expect(rowScope.getByText('震荡偏多')).toBeInTheDocument();
    expect(rowScope.getByText('risk alert, avoid buying')).toBeInTheDocument();
    expect(rowScope.queryByText('回避')).not.toBeInTheDocument();
    expect(rowScope.queryByText('预警')).not.toBeInTheDocument();
  });

  it('renders backtest controls and result headings in English UI mode', async () => {
    renderEnglishPage();

    expect(await screen.findByPlaceholderText('Filter by stock code (leave empty for all)')).toBeInTheDocument();
    expect(screen.getByText('Evaluation window')).toBeInTheDocument();
    expect(screen.getAllByText('Phase').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Run backtest' })).toBeInTheDocument();
    expect(await screen.findByText('Window return')).toBeInTheDocument();
    expect(screen.getByText('Direction match')).toBeInTheDocument();
    expect(screen.getByText('Direction accuracy')).toBeInTheDocument();
    expect(screen.queryByText('运行回测')).not.toBeInTheDocument();
    expect(screen.queryByText('窗口收益')).not.toBeInTheDocument();
  });

  it('filters results with stock code, window, phase, and analysis date range when clicking Filter', async () => {
    render(<BacktestPage />);

    const filterInput = await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）');
    const windowInput = screen.getByPlaceholderText('10');
    const phaseSelect = screen.getByDisplayValue('全部阶段');
    const fromInput = screen.getByLabelText('分析开始日期');
    const toInput = screen.getByLabelText('分析结束日期');

    fireEvent.change(filterInput, { target: { value: 'aapl' } });
    fireEvent.change(windowInput, { target: { value: '20' } });
    fireEvent.change(phaseSelect, { target: { value: 'intraday' } });
    fireEvent.change(fromInput, { target: { value: '2026-03-01' } });
    fireEvent.change(toInput, { target: { value: '2026-03-31' } });
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));

    await waitFor(() => {
      expect(mockGetResults).toHaveBeenLastCalledWith({
        code: 'AAPL',
        evalWindowDays: 20,
        analysisDateFrom: '2026-03-01',
        analysisDateTo: '2026-03-31',
        analysisPhase: 'intraday',
        page: 1,
        limit: 20,
      });
      expect(mockGetStockPerformance).toHaveBeenLastCalledWith('AAPL', {
        evalWindowDays: 20,
        analysisDateFrom: '2026-03-01',
        analysisDateTo: '2026-03-31',
        analysisPhase: 'intraday',
      });
    });
  });

  it('runs a backtest and refreshes results using the shared filter values', async () => {
    mockRun.mockResolvedValueOnce({
      processed: 0,
      saved: 0,
      completed: 0,
      insufficient: 0,
      errors: 0,
      message: '未找到符合条件的历史分析记录',
      diagnostics: { emptyReason: 'no_matching_analysis' },
    });
    render(<BacktestPage />);

    const filterInput = await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）');
    const windowInput = screen.getByPlaceholderText('10');
    const fromInput = screen.getByLabelText('分析开始日期');
    const toInput = screen.getByLabelText('分析结束日期');

    fireEvent.change(filterInput, { target: { value: '600519.SH' } });
    fireEvent.change(windowInput, { target: { value: '15' } });
    fireEvent.change(fromInput, { target: { value: '2026-03-01' } });
    fireEvent.change(toInput, { target: { value: '2026-03-31' } });
    fireEvent.click(screen.getByRole('button', { name: '运行回测' }));

    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith({
        code: '600519.SH',
        force: undefined,
        minAgeDays: undefined,
        evalWindowDays: 15,
        analysisDateFrom: '2026-03-01',
        analysisDateTo: '2026-03-31',
      });
    });

    await waitFor(() => {
      expect(mockGetResults).toHaveBeenLastCalledWith({
        code: '600519.SH',
        evalWindowDays: 15,
        analysisDateFrom: '2026-03-01',
        analysisDateTo: '2026-03-31',
        analysisPhase: undefined,
        page: 1,
        limit: 20,
      });
      expect(mockGetStockPerformance).toHaveBeenLastCalledWith('600519.SH', {
        evalWindowDays: 15,
        analysisDateFrom: '2026-03-01',
        analysisDateTo: '2026-03-31',
        analysisPhase: undefined,
      });
    });

    expect(await screen.findByText('已处理:')).toBeInTheDocument();
    expect(screen.getByText('已保存:')).toBeInTheDocument();
    expect(screen.getByText('未找到符合条件的历史分析记录')).toBeInTheDocument();
  });

  it('uses backend-applied eval window when run input is empty', async () => {
    mockRun.mockResolvedValueOnce({
      processed: 0,
      saved: 0,
      completed: 0,
      insufficient: 0,
      errors: 0,
      appliedEvalWindowDays: 10,
      message: '未找到符合条件的历史分析记录',
      diagnostics: { emptyReason: 'no_matching_analysis' },
    });
    render(<BacktestPage />);

    const filterInput = await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）');
    const windowInput = screen.getByPlaceholderText('10');
    const fromInput = screen.getByLabelText('分析开始日期');
    const toInput = screen.getByLabelText('分析结束日期');

    fireEvent.change(filterInput, { target: { value: '600519.SH' } });
    fireEvent.change(windowInput, { target: { value: '' } });
    fireEvent.change(fromInput, { target: { value: '2026-03-01' } });
    fireEvent.change(toInput, { target: { value: '2026-03-31' } });
    fireEvent.click(screen.getByRole('button', { name: '运行回测' }));

    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith({
        code: '600519.SH',
        force: undefined,
        minAgeDays: undefined,
        evalWindowDays: undefined,
        analysisDateFrom: '2026-03-01',
        analysisDateTo: '2026-03-31',
      });
    });

    await waitFor(() => {
      expect(windowInput).toHaveValue(10);
      expect(mockGetResults).toHaveBeenLastCalledWith({
        code: '600519.SH',
        evalWindowDays: 10,
        analysisDateFrom: '2026-03-01',
        analysisDateTo: '2026-03-31',
        analysisPhase: undefined,
        page: 1,
        limit: 20,
      });
      expect(mockGetStockPerformance).toHaveBeenLastCalledWith('600519.SH', {
        evalWindowDays: 10,
        analysisDateFrom: '2026-03-01',
        analysisDateTo: '2026-03-31',
        analysisPhase: undefined,
      });
      expect(mockGetOverallPerformance).toHaveBeenLastCalledWith({
        evalWindowDays: 10,
        analysisDateFrom: '2026-03-01',
        analysisDateTo: '2026-03-31',
        analysisPhase: undefined,
      });
    });

    expect(await screen.findByText('未找到符合条件的历史分析记录')).toBeInTheDocument();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('switches to next-day validation with the 1D shortcut', async () => {
    render(<BacktestPage />);

    await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）');
    fireEvent.click(screen.getByRole('button', { name: '1 日验证' }));

    await waitFor(() => {
      expect(mockGetResults).toHaveBeenLastCalledWith({
        code: undefined,
        evalWindowDays: 1,
        analysisDateFrom: undefined,
        analysisDateTo: undefined,
        analysisPhase: undefined,
        page: 1,
        limit: 20,
      });
      expect(mockGetOverallPerformance).toHaveBeenLastCalledWith({
        evalWindowDays: 1,
        analysisDateFrom: undefined,
        analysisDateTo: undefined,
        analysisPhase: undefined,
      });
    });

    expect(screen.getByText('实际表现')).toBeInTheDocument();
    expect(screen.getByText('准确性')).toBeInTheDocument();
    expect(screen.getByText('1 日验证模式会用下一个交易日收盘表现校验 AI 预测。')).toBeInTheDocument();
  });

  it('ignores stale filter responses when a newer request settles first', async () => {
    let resolveInitPerf!: (value: typeof basePerformance) => void;
    let resolveSlowResults!: (value: { total: number; page: number; limit: number; items: Array<typeof baseResultItem> }) => void;
    let resolveSlowPerf!: (value: typeof basePerformance) => void;

    // 1. Slow initial overall performance resolves after a user filter has already completed.
    mockGetOverallPerformance.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveInitPerf = resolve;
        }),
    );

    render(<BacktestPage />);

    const filterInput = await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）');
    mockGetResults.mockResolvedValueOnce({
      total: 1,
      page: 1,
      limit: 20,
      items: [
        {
          ...baseResultItem,
          analysisHistoryId: 202,
          code: 'AAPL',
          stockName: '苹果',
          evalWindowDays: 5,
        },
      ],
    });
    mockGetOverallPerformance.mockResolvedValueOnce({
      ...basePerformance,
      evalWindowDays: 5,
      winRatePct: 88,
    });
    mockGetStockPerformance.mockResolvedValueOnce(null);

    fireEvent.change(filterInput, { target: { value: 'AAPL' } });
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));

    expect(await screen.findByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('88.0%')).toBeInTheDocument();

    await act(async () => {
      resolveInitPerf({
        ...basePerformance,
        evalWindowDays: 10,
        winRatePct: 12,
      });
      await Promise.resolve();
    });

    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('88.0%')).toBeInTheDocument();
    expect(screen.queryByText('12.0%')).not.toBeInTheDocument();
    expect(mockGetResults).toHaveBeenCalledTimes(1);

    // 2. Slow Enter filter resolves after a newer Enter filter settles.
    fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '5' } });
    mockGetResults.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSlowResults = resolve;
        }),
    );
    mockGetOverallPerformance.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSlowPerf = resolve;
        }),
    );
    mockGetStockPerformance.mockResolvedValueOnce(null);

    fireEvent.change(filterInput, { target: { value: '600519' } });
    fireEvent.keyDown(filterInput, { key: 'Enter' });

    mockGetResults.mockResolvedValueOnce({
      total: 1,
      page: 1,
      limit: 20,
      items: [
        {
          ...baseResultItem,
          analysisHistoryId: 303,
          code: 'MSFT',
          stockName: '微软',
          evalWindowDays: 5,
        },
      ],
    });
    mockGetOverallPerformance.mockResolvedValueOnce({
      ...basePerformance,
      evalWindowDays: 5,
      winRatePct: 77,
    });
    mockGetStockPerformance.mockResolvedValueOnce(null);

    fireEvent.change(filterInput, { target: { value: 'MSFT' } });
    fireEvent.keyDown(filterInput, { key: 'Enter' });

    expect(await screen.findByText('MSFT')).toBeInTheDocument();
    expect(screen.getByText('77.0%')).toBeInTheDocument();

    await act(async () => {
      resolveSlowResults({
        total: 1,
        page: 1,
        limit: 20,
        items: [baseResultItem],
      });
      resolveSlowPerf({
        ...basePerformance,
        winRatePct: 19,
      });
      await Promise.resolve();
    });

    expect(screen.getByText('MSFT')).toBeInTheDocument();
    expect(screen.queryByText('600519')).not.toBeInTheDocument();
    expect(screen.getByText('77.0%')).toBeInTheDocument();
    expect(screen.queryByText('19.0%')).not.toBeInTheDocument();
  });

  it('keeps results error visible even when concurrent performance request succeeds', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<BacktestPage />);
    await screen.findByText('600519');

    mockGetResults.mockRejectedValueOnce(new Error('Results service timeout'));
    mockGetOverallPerformance.mockResolvedValueOnce({
      ...basePerformance,
      evalWindowDays: 1,
    });

    fireEvent.click(screen.getByRole('button', { name: '1 日验证' }));

    expect(await screen.findByText('Results service timeout')).toBeInTheDocument();
    expect(consoleErrorSpy).toHaveBeenCalled();
  });

  it('surfaces initial overall performance load failures cleanly without unhandled rejection', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    mockGetOverallPerformance.mockRejectedValueOnce(new Error('Initial metrics unavailable'));
    mockGetResults.mockResolvedValueOnce({
      total: 0,
      page: 1,
      limit: 20,
      items: [],
    });

    render(<BacktestPage />);

    expect(await screen.findByText('Initial metrics unavailable')).toBeInTheDocument();
    expect(screen.getByText('暂无结果')).toBeInTheDocument();
    expect(consoleErrorSpy).toHaveBeenCalled();
  });

  it('submits filters when pressing Enter inside the eval window input', async () => {
    render(<BacktestPage />);
    await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）');

    const windowInput = screen.getByPlaceholderText('10');
    fireEvent.change(windowInput, { target: { value: '5' } });
    fireEvent.keyDown(windowInput, { key: 'Enter' });

    await waitFor(() => {
      expect(mockGetResults).toHaveBeenLastCalledWith({
        code: undefined,
        evalWindowDays: 5,
        analysisDateFrom: undefined,
        analysisDateTo: undefined,
        analysisPhase: undefined,
        page: 1,
        limit: 20,
      });
      expect(mockGetOverallPerformance).toHaveBeenLastCalledWith({
        evalWindowDays: 5,
        analysisDateFrom: undefined,
        analysisDateTo: undefined,
        analysisPhase: undefined,
      });
    });
  });

  it('commits updated overall performance even when stock performance request fails', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<BacktestPage />);
    expect(await screen.findByText('50.0%')).toBeInTheDocument();

    mockGetResults.mockResolvedValueOnce({
      total: 1,
      page: 1,
      limit: 20,
      items: [{ ...baseResultItem, code: 'AAPL', evalWindowDays: 1 }],
    });
    mockGetOverallPerformance.mockResolvedValueOnce({
      ...basePerformance,
      evalWindowDays: 1,
      winRatePct: 80,
    });
    mockGetStockPerformance.mockRejectedValueOnce(new Error('Stock metrics timeout'));

    fireEvent.change(screen.getByPlaceholderText('按股票代码筛选（留空表示全部）'), {
      target: { value: 'AAPL' },
    });
    fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));

    expect(await screen.findByText('80.0%')).toBeInTheDocument();
    expect(screen.queryByText('50.0%')).not.toBeInTheDocument();
    expect(screen.getByText('Stock metrics timeout')).toBeInTheDocument();
    expect(consoleErrorSpy).toHaveBeenCalled();
  });

  it('keeps table columns and pagination aligned with applied window when draft evalDays is edited during initial load', async () => {
    let resolveInitPerf!: (value: typeof basePerformance) => void;
    mockGetOverallPerformance.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveInitPerf = resolve;
        }),
    );
    mockGetResults.mockResolvedValue({
      total: 25,
      page: 1,
      limit: 20,
      items: [baseResultItem],
    });

    render(<BacktestPage />);

    const windowInput = screen.getByPlaceholderText('10');
    fireEvent.change(windowInput, { target: { value: '1' } });
    expect(windowInput).toHaveValue(1);

    await act(async () => {
      resolveInitPerf({ ...basePerformance, evalWindowDays: 10 });
      await Promise.resolve();
    });

    expect(await screen.findByText('600519')).toBeInTheDocument();
    expect(windowInput).toHaveValue(1);
    expect(screen.getByText('窗口收益')).toBeInTheDocument();
    expect(screen.getByText('方向匹配')).toBeInTheDocument();
    expect(screen.queryByText('实际表现')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /2/ }));
    await waitFor(() => {
      expect(mockGetResults).toHaveBeenLastCalledWith({
        code: undefined,
        evalWindowDays: 10,
        analysisDateFrom: undefined,
        analysisDateTo: undefined,
        analysisPhase: undefined,
        page: 2,
        limit: 20,
      });
    });
  });

  it('starts empty-window filter immediately without waiting for in-flight initial load', async () => {
    let resolveInitPerf!: (value: typeof basePerformance) => void;
    mockGetOverallPerformance.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveInitPerf = resolve;
        }),
    );

    render(<BacktestPage />);
    const filterInput = await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）');

    mockGetOverallPerformance.mockResolvedValueOnce({
      ...basePerformance,
      evalWindowDays: 1,
      winRatePct: 90,
    });
    mockGetStockPerformance.mockResolvedValueOnce({
      ...basePerformance,
      scope: 'stock',
      code: 'TSLA',
      evalWindowDays: 1,
      winRatePct: 88,
    });
    mockGetResults.mockResolvedValueOnce({
      total: 1,
      page: 1,
      limit: 20,
      items: [{ ...baseResultItem, analysisHistoryId: 901, code: 'TSLA', evalWindowDays: 1 }],
    });

    fireEvent.change(filterInput, { target: { value: 'TSLA' } });
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));

    await waitFor(() => {
      expect(within(screen.getByRole('table')).getByText('TSLA')).toBeInTheDocument();
    });
    expect(mockGetResults).toHaveBeenCalledTimes(1);
    expect(mockGetResults).toHaveBeenCalledWith({
      code: 'TSLA',
      evalWindowDays: undefined,
      analysisDateFrom: undefined,
      analysisDateTo: undefined,
      analysisPhase: undefined,
      page: 1,
      limit: 20,
    });

    await act(async () => {
      resolveInitPerf({ ...basePerformance, evalWindowDays: 10, winRatePct: 12 });
      await Promise.resolve();
    });

    expect(within(screen.getByRole('table')).getByText('TSLA')).toBeInTheDocument();
    expect(screen.getByText('90.0%')).toBeInTheDocument();
    expect(screen.getByText('窗口收益')).toBeInTheDocument();
    expect(mockGetResults).toHaveBeenCalledTimes(1);
  });

  it('does not block empty-window stock results or stock summary when overall summary stays pending (OR-COR-fe04c290)', async () => {
    mockGetOverallPerformance.mockResolvedValueOnce({
      ...basePerformance,
      evalWindowDays: 1,
    });
    mockGetResults.mockResolvedValueOnce({
      total: 1,
      page: 1,
      limit: 20,
      items: [{ ...baseResultItem, evalWindowDays: 1 }],
    });

    render(<BacktestPage />);
    await screen.findByText('600519');

    // Overall performance hangs indefinitely while stock performance and results respond quickly.
    mockGetOverallPerformance.mockImplementationOnce(() => new Promise(() => {}));
    mockGetStockPerformance.mockResolvedValueOnce({
      ...basePerformance,
      scope: 'stock',
      code: 'AAPL',
      evalWindowDays: 10,
      winRatePct: 75,
    });
    mockGetResults.mockResolvedValueOnce({
      total: 1,
      page: 1,
      limit: 20,
      items: [{ ...baseResultItem, analysisHistoryId: 202, code: 'AAPL', evalWindowDays: 10 }],
    });

    fireEvent.change(screen.getByPlaceholderText('按股票代码筛选（留空表示全部）'), {
      target: { value: 'AAPL' },
    });
    fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('分析开始日期'), { target: { value: '2026-03-01' } });
    fireEvent.change(screen.getByLabelText('分析结束日期'), { target: { value: '2026-03-25' } });
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));

    await waitFor(() => {
      expect(within(screen.getByRole('table')).getByText('AAPL')).toBeInTheDocument();
    });
    expect(mockGetResults).toHaveBeenLastCalledWith({
      code: 'AAPL',
      evalWindowDays: undefined,
      analysisDateFrom: '2026-03-01',
      analysisDateTo: '2026-03-25',
      analysisPhase: undefined,
      page: 1,
      limit: 20,
    });
    expect(screen.getByText('75.0%')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '筛选' })).toBeEnabled();
  });

  it('does not fall back to stale overall window on empty-window filter or pagination after summary failure', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      mockGetOverallPerformance.mockResolvedValueOnce({
        ...basePerformance,
        evalWindowDays: 1,
      });
      mockGetResults.mockResolvedValueOnce({
        total: 1,
        page: 1,
        limit: 20,
        items: [{ ...baseResultItem, evalWindowDays: 1 }],
      });

      render(<BacktestPage />);
      expect(await screen.findByText('实际表现')).toBeInTheDocument();

      mockGetOverallPerformance.mockRejectedValueOnce(new Error('Summary HTTP 500'));
      mockGetResults
        .mockResolvedValueOnce({
          total: 25,
          page: 1,
          limit: 20,
          items: [{ ...baseResultItem, analysisHistoryId: 301, evalWindowDays: 10 }],
        })
        .mockResolvedValueOnce({
          total: 25,
          page: 2,
          limit: 20,
          items: [{ ...baseResultItem, analysisHistoryId: 302, evalWindowDays: 10 }],
        });

      fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '' } });
      fireEvent.click(screen.getByRole('button', { name: '筛选' }));

      await waitFor(() => {
        expect(mockGetResults).toHaveBeenLastCalledWith({
          code: undefined,
          evalWindowDays: undefined,
          analysisDateFrom: undefined,
          analysisDateTo: undefined,
          analysisPhase: undefined,
          page: 1,
          limit: 20,
        });
      });

      expect(screen.queryByText('实际表现')).not.toBeInTheDocument();
      expect(screen.getByText('窗口收益')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /2/ }));
      await waitFor(() => {
        expect(mockGetResults).toHaveBeenLastCalledWith({
          code: undefined,
          evalWindowDays: undefined,
          analysisDateFrom: undefined,
          analysisDateTo: undefined,
          analysisPhase: undefined,
          page: 2,
          limit: 20,
        });
      });
    } finally {
      consoleErrorSpy.mockRestore();
    }
  });

  it('keeps all evaluation windows visible when clearing evalDays after initial load (OR-COR-ce1dc277)', async () => {
    mockGetOverallPerformance.mockResolvedValueOnce({
      ...basePerformance,
      evalWindowDays: 1,
    });
    mockGetResults.mockResolvedValueOnce({
      total: 1,
      page: 1,
      limit: 20,
      items: [{ ...baseResultItem, evalWindowDays: 1 }],
    });

    render(<BacktestPage />);
    expect(await screen.findByText('实际表现')).toBeInTheDocument();

    mockGetOverallPerformance.mockResolvedValueOnce({
      ...basePerformance,
      evalWindowDays: 1,
    });
    mockGetStockPerformance.mockResolvedValueOnce({
      ...basePerformance,
      scope: 'stock',
      code: 'AAPL',
      evalWindowDays: 1,
    });
    mockGetResults
      .mockResolvedValueOnce({
        total: 25,
        page: 1,
        limit: 20,
        items: [
          { ...baseResultItem, analysisHistoryId: 401, code: 'AAPL', evalWindowDays: 1 },
          { ...baseResultItem, analysisHistoryId: 402, code: 'AAPL', evalWindowDays: 10 },
        ],
      })
      .mockResolvedValueOnce({
        total: 25,
        page: 2,
        limit: 20,
        items: [
          { ...baseResultItem, analysisHistoryId: 403, code: 'AAPL', evalWindowDays: 10 },
        ],
      });

    fireEvent.change(screen.getByPlaceholderText('按股票代码筛选（留空表示全部）'), {
      target: { value: 'AAPL' },
    });
    fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));

    await waitFor(() => {
      expect(mockGetResults).toHaveBeenLastCalledWith({
        code: 'AAPL',
        evalWindowDays: undefined,
        analysisDateFrom: undefined,
        analysisDateTo: undefined,
        analysisPhase: undefined,
        page: 1,
        limit: 20,
      });
    });

    expect(screen.getAllByText('AAPL').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('窗口收益')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /2/ }));
    await waitFor(() => {
      expect(mockGetResults).toHaveBeenLastCalledWith({
        code: 'AAPL',
        evalWindowDays: undefined,
        analysisDateFrom: undefined,
        analysisDateTo: undefined,
        analysisPhase: undefined,
        page: 2,
        limit: 20,
      });
    });
  });

  it('keeps previous appliedFilters and page when handleRun refresh fails (OR-COR-b19fb2f2)', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      mockGetOverallPerformance.mockResolvedValueOnce({
        ...basePerformance,
        evalWindowDays: 10,
      });
      mockGetResults
        .mockResolvedValueOnce({
          total: 25,
          page: 1,
          limit: 20,
          items: [{ ...baseResultItem, analysisHistoryId: 501, code: '600519', evalWindowDays: 10 }],
        })
        .mockResolvedValueOnce({
          total: 25,
          page: 2,
          limit: 20,
          items: [{ ...baseResultItem, analysisHistoryId: 502, code: '000001', stockName: '平安银行', evalWindowDays: 10 }],
        });

      render(<BacktestPage />);
      expect(await screen.findByText('600519')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /2/ }));
      expect(await screen.findByText('000001')).toBeInTheDocument();

      mockRun.mockResolvedValueOnce({
        processed: 5,
        saved: 5,
        completed: 5,
        insufficient: 0,
        errors: 0,
        appliedEvalWindowDays: 1,
      });
      mockGetResults.mockRejectedValueOnce(new Error('Refresh HTTP 500'));
      mockGetOverallPerformance.mockResolvedValueOnce({
        ...basePerformance,
        evalWindowDays: 1,
      });
      mockGetStockPerformance.mockResolvedValueOnce({
        ...basePerformance,
        scope: 'stock',
        code: 'AAPL',
        evalWindowDays: 1,
      });

      fireEvent.change(screen.getByPlaceholderText('按股票代码筛选（留空表示全部）'), {
        target: { value: 'AAPL' },
      });
      fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '1' } });
      fireEvent.click(screen.getByRole('button', { name: '运行回测' }));

      expect(await screen.findByText('Refresh HTTP 500')).toBeInTheDocument();
      // Previous rows and applied header metadata remain aligned rather than relabeled as AAPL page 1.
      expect(within(screen.getByRole('table')).getByText('000001')).toBeInTheDocument();
      expect(screen.getByText(/全部股票 · 10 日窗口/)).toBeInTheDocument();
      expect(screen.queryByText(/筛选股票: AAPL/)).not.toBeInTheDocument();
      expect(screen.getByText('窗口收益')).toBeInTheDocument();
      expect(screen.queryByText('实际表现')).not.toBeInTheDocument();

      // Pagination still queries the committed All Stocks 10-day filter and keeps the refresh error visible.
      mockGetResults.mockResolvedValueOnce({
        total: 25,
        page: 1,
        limit: 20,
        items: [{ ...baseResultItem, analysisHistoryId: 501, code: '600519', evalWindowDays: 10 }],
      });
      fireEvent.click(screen.getByRole('button', { name: /^1$/ }));
      await waitFor(() => {
        expect(mockGetResults).toHaveBeenLastCalledWith({
          code: undefined,
          evalWindowDays: 10,
          analysisDateFrom: undefined,
          analysisDateTo: undefined,
          analysisPhase: undefined,
          page: 1,
          limit: 20,
        });
      });
      expect(await screen.findByText('600519')).toBeInTheDocument();
      expect(screen.getByText('Refresh HTTP 500')).toBeInTheDocument();
      expect(screen.getByText(/全部股票 · 10 日窗口/)).toBeInTheDocument();

      // Re-running Filter clears the refresh error once details align with AAPL 1-day summary.
      mockGetResults.mockResolvedValueOnce({
        total: 1,
        page: 1,
        limit: 20,
        items: [{ ...baseResultItem, analysisHistoryId: 601, code: 'AAPL', stockName: 'Apple', evalWindowDays: 1 }],
      });
      mockGetOverallPerformance.mockResolvedValueOnce({
        ...basePerformance,
        evalWindowDays: 1,
      });
      mockGetStockPerformance.mockResolvedValueOnce({
        ...basePerformance,
        scope: 'stock',
        code: 'AAPL',
        evalWindowDays: 1,
      });
      fireEvent.click(screen.getByRole('button', { name: '筛选' }));
      expect(await screen.findByText(/筛选 AAPL · 1 日窗口/)).toBeInTheDocument();
      expect(screen.queryByText('Refresh HTTP 500')).not.toBeInTheDocument();
    } finally {
      consoleErrorSpy.mockRestore();
    }
  });

  it('clears a standalone pagination error when a subsequent page request succeeds', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      mockGetOverallPerformance.mockResolvedValueOnce(basePerformance);
      mockGetResults
        .mockResolvedValueOnce({
          total: 25,
          page: 1,
          limit: 20,
          items: [{ ...baseResultItem, analysisHistoryId: 701, code: '600519', evalWindowDays: 10 }],
        })
        .mockRejectedValueOnce(new Error('Page 2 HTTP 503'))
        .mockResolvedValueOnce({
          total: 25,
          page: 2,
          limit: 20,
          items: [{ ...baseResultItem, analysisHistoryId: 702, code: '000001', stockName: '平安银行', evalWindowDays: 10 }],
        });

      render(<BacktestPage />);
      expect(await screen.findByText('600519')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /2/ }));
      expect(await screen.findByText('Page 2 HTTP 503')).toBeInTheDocument();
      expect(screen.getByText('600519')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: /2/ }));
      expect(await screen.findByText('000001')).toBeInTheDocument();
      expect(screen.queryByText('Page 2 HTTP 503')).not.toBeInTheDocument();
    } finally {
      consoleErrorSpy.mockRestore();
    }
  });

  it('renders camelCased backend quant telemetry, equity curve, outcome filter, sort, and row replay drawer', async () => {
    const rawSnakePerf = {
      ...basePerformance,
      advice_breakdown: {
        买入: { total: 3, win: 2, loss: 1, neutral: 0, win_rate_pct: 66.7 },
      },
      quant_metrics: {
        sample_count: 3,
        active_trade_count: 3,
        profit_factor: 3.1,
        expectancy_pct: 4.2,
        payoff_ratio: 2.2,
        avg_win_pct: 8.8,
        avg_loss_pct: -4.0,
        cumulative_return_pct: 12.6,
        max_drawdown_pct: 4.0,
        sharpe_ratio: 1.95,
        sortino_ratio: 3.1,
        calmar_ratio: 3.15,
        best_trade_pct: 10.2,
        worst_trade_pct: -4.0,
        max_consecutive_wins: 2,
        max_consecutive_losses: 1,
        exit_reason_breakdown: { take_profit: 2, stop_loss: 1 },
        equity_curve: [
          { index: 1, date: '2026-03-10', code: '600519', return_pct: 7.4, equity_pct: 7.4, outcome: 'win' },
          { index: 2, date: '2026-03-15', code: 'AAPL', return_pct: -4.0, equity_pct: 3.1, outcome: 'loss' },
          { index: 3, date: '2026-03-20', code: '00700', return_pct: 9.2, equity_pct: 12.6, outcome: 'win' },
        ],
      },
    };
    mockGetOverallPerformance.mockResolvedValueOnce(toCamelCase<PerformanceMetrics>(rawSnakePerf));
    mockGetResults.mockResolvedValueOnce({
      total: 2,
      page: 1,
      limit: 20,
      items: [
        {
          ...baseResultItem,
          analysisHistoryId: 201,
          code: 'AAPL',
          stockName: 'Apple',
          outcome: 'loss',
          simulatedEntryPrice: 180.0,
          simulatedExitPrice: 172.8,
          simulatedExitReason: 'stop_loss',
          simulatedReturnPct: -4.0,
          stopLoss: 172.8,
          takeProfit: 200.0,
          firstHit: 'stop_loss',
          firstHitDate: '2026-03-18',
          firstHitTradingDays: 3,
          startPrice: 180.0,
          endClose: 174.0,
          maxHigh: 185.4,
          minLow: 171.0,
        },
        {
          ...baseResultItem,
          analysisHistoryId: 202,
          code: '00700',
          stockName: '腾讯控股',
          outcome: 'win',
          simulatedEntryPrice: 400.0,
          simulatedExitPrice: 440.0,
          simulatedExitReason: 'take_profit',
          simulatedReturnPct: 10.0,
          stopLoss: 380.0,
          takeProfit: 440.0,
          firstHit: 'take_profit',
          firstHitDate: '2026-03-25',
          firstHitTradingDays: 4,
          startPrice: 400.0,
          endClose: 435.0,
          maxHigh: 442.0,
          minLow: 396.0,
        },
      ],
    });

    render(<BacktestPage />);

    expect(await screen.findByText('量化风险绩效与模拟净值')).toBeInTheDocument();
    expect(screen.getByText('+12.60%')).toBeInTheDocument();
    expect(screen.getByText('3.10')).toBeInTheDocument();
    expect(screen.getByLabelText('策略顺序模拟净值曲线')).toBeInTheDocument();
    expect(screen.getByText('按操作建议胜率分布')).toBeInTheDocument();
    expect(screen.getAllByText('触发止盈').length).toBeGreaterThan(0);

    // Sort by simulated return descending so 00700 (+10%) moves above AAPL (-4%)
    const sortSelect = screen.getByLabelText('排序');
    fireEvent.change(sortSelect, { target: { value: 'sim_desc' } });
    const rowsAfterSort = screen.getAllByRole('row');
    expect(within(rowsAfterSort[1]).getByText('00700')).toBeInTheDocument();

    // Expand replay detail row on the sorted second data row (AAPL)
    const expandButtons = await screen.findAllByLabelText('展开回测交易回放详情');
    fireEvent.click(expandButtons[1]);
    expect(await screen.findByText('单笔回测执行与波动回放')).toBeInTheDocument();
    expect(screen.getByText('触发止损 · 2026-03-18 · 第 3 交易日')).toBeInTheDocument();

    // Filter to wins only
    fireEvent.click(screen.getByRole('button', { name: '仅盈利' }));
    expect(screen.queryByText('AAPL')).not.toBeInTheDocument();
    expect(screen.getByText('00700')).toBeInTheDocument();

    // Filter to losses only
    fireEvent.click(screen.getByRole('button', { name: '仅亏损' }));
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.queryByText('00700')).not.toBeInTheDocument();
  });

  it('localizes quant risk panel and trade replay labels in English UI mode', async () => {
    mockGetOverallPerformance.mockResolvedValueOnce({
      ...basePerformance,
      quantMetrics: {
        sampleCount: 2,
        activeTradeCount: 2,
        profitFactor: 2.5,
        expectancyPct: 3.0,
        cumulativeReturnPct: 6.0,
        maxDrawdownPct: 2.0,
        sharpeRatio: 1.5,
        sortinoRatio: 2.0,
        calmarRatio: 3.0,
        equityCurve: [
          { index: 1, date: '2026-03-10', code: '600519', returnPct: 6.0, equityPct: 6.0, outcome: 'win' },
          { index: 2, date: '2026-03-11', code: '600519', returnPct: 0.0, equityPct: 6.0, outcome: 'neutral' },
        ],
      },
    });

    renderEnglishPage();

    expect(await screen.findByText('Quant Risk Telemetry & Equity Curve')).toBeInTheDocument();
    expect(screen.getByLabelText('Chronological Simulated Equity Curve')).toBeInTheDocument();
    fireEvent.click(await screen.findByLabelText('Expand trade replay details'));
    expect(await screen.findByText('Trade Execution & Window Excursion Replay')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open in Workspace' })).toHaveAttribute('href', '/?stock=600519');
  });

  it('uses simulatedEntryPrice as MFE/MAE excursion basis and resets expanded rows on pagination', async () => {
    mockGetResults
      .mockResolvedValueOnce({
        total: 25,
        page: 1,
        limit: 20,
        items: [
          {
            ...baseResultItem,
            analysisHistoryId: 301,
            code: '600519',
            stockName: '贵州茅台',
            startPrice: 100.0,
            simulatedEntryPrice: 110.0,
            simulatedExitPrice: 118.8,
            simulatedExitReason: 'take_profit',
            simulatedReturnPct: 8.0,
            maxHigh: 121.0,
            minLow: 99.0,
          },
        ],
      })
      .mockResolvedValueOnce({
        total: 25,
        page: 2,
        limit: 20,
        items: [
          {
            ...baseResultItem,
            analysisHistoryId: 301,
            code: '000001',
            stockName: '平安银行',
            startPrice: 12.0,
            simulatedEntryPrice: 12.0,
            maxHigh: 12.6,
            minLow: 11.4,
          },
        ],
      });

    render(<BacktestPage />);

    const expandButton = await screen.findByLabelText('展开回测交易回放详情');
    fireEvent.click(expandButton);
    expect(await screen.findByText('单笔回测执行与波动回放')).toBeInTheDocument();
    expect(screen.getByText('(+10.00% / -10.00%)')).toBeInTheDocument();
    expect(screen.queryByText('(+21.00% / -1.00%)')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '2' }));
    expect(await screen.findByText('000001')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText('单笔回测执行与波动回放')).not.toBeInTheDocument();
    });
  });

  it('filters by simulatedReturnPct instead of directional outcome and omits fabricated replay prices', async () => {
    mockGetResults.mockResolvedValueOnce({
      total: 3,
      page: 1,
      limit: 20,
      items: [
        {
          // Stopped out at -4% even though directional outcome is win (+10% window close)
          ...baseResultItem,
          analysisHistoryId: 801,
          code: '600519',
          stockName: '贵州茅台',
          outcome: 'win',
          startPrice: 100.0,
          endClose: 110.0,
          simulatedEntryPrice: 100.0,
          simulatedExitPrice: 96.0,
          simulatedExitReason: 'stop_loss',
          simulatedReturnPct: -4.0,
        },
        {
          // Cash / stand aside row: no simulated fills
          ...baseResultItem,
          analysisHistoryId: 802,
          code: '000001',
          stockName: '平安银行',
          outcome: 'win',
          startPrice: 100.0,
          endClose: 110.0,
          simulatedEntryPrice: null,
          simulatedExitPrice: null,
          simulatedExitReason: 'cash',
          simulatedReturnPct: 0.0,
        },
        {
          // Invalid targets row: missing simulatedExitPrice and simulatedReturnPct
          ...baseResultItem,
          analysisHistoryId: 803,
          code: '00700',
          stockName: '腾讯控股',
          outcome: 'win',
          startPrice: 100.0,
          endClose: 110.0,
          simulatedEntryPrice: 100.0,
          simulatedExitPrice: null,
          simulatedExitReason: 'invalid_targets',
          simulatedReturnPct: null,
        },
      ],
    });

    render(<BacktestPage />);

    expect(await screen.findByText('600519')).toBeInTheDocument();
    // P&L summary counts based on simulatedReturnPct: 0 wins, 1 loss (600519), 1 neutral (000001)
    expect(screen.getByText('(0/1/1)')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '仅盈利' }));
    expect(screen.getByText('当前页没有匹配筛选条件的回测记录')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '仅亏损' }));
    expect(screen.getByText('600519')).toBeInTheDocument();
    expect(screen.queryByText('000001')).not.toBeInTheDocument();
    expect(screen.queryByText('00700')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '全部' }));
    const expandButtons = await screen.findAllByLabelText('展开回测交易回放详情');
    // Expand cash row (index 1: 000001) and invalid_targets row (index 2: 00700)
    fireEvent.click(expandButtons[1]);
    fireEvent.click(expandButtons[2]);

    expect(await screen.findByText('100.00 → --')).toBeInTheDocument();
    expect(screen.queryByText('100.00 → 110.00')).not.toBeInTheDocument();
  });
});
