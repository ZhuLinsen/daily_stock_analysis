import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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

beforeEach(() => {
  vi.clearAllMocks();
  mockGetOverallPerformance.mockResolvedValue(basePerformance);
  mockGetStockPerformance.mockResolvedValue(null);
  mockGetResults.mockResolvedValue({
    total: 1,
    page: 1,
    limit: 20,
    items: [
      {
        analysisHistoryId: 101,
        code: '600519',
        stockName: '贵州茅台',
        analysisDate: '2026-03-20',
        evalWindowDays: 10,
        engineVersion: 'test-engine',
        evalStatus: 'completed',
        operationAdvice: '继续持有',
        trendPrediction: '震荡偏多',
        actualMovement: 'up',
        actualReturnPct: 3.8,
        directionExpected: 'long',
        directionCorrect: true,
        outcome: 'win',
        simulatedReturnPct: 3.8,
      },
    ],
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
    expect(screen.getByText('震荡偏多')).toBeInTheDocument();
    expect(screen.getByText('上涨')).toBeInTheDocument();
    expect(screen.getByText('窗口收益')).toBeInTheDocument();
    expect(screen.getByText('方向匹配')).toBeInTheDocument();
    expect(screen.getByText('做多')).toBeInTheDocument();
    expect(screen.getAllByLabelText('是').length).toBeGreaterThan(0);
    expect(screen.getByText('方向准确率')).toBeInTheDocument();
    expect(screen.getByText('平均模拟收益')).toBeInTheDocument();
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
    render(<BacktestPage />);

    const filterInput = await screen.findByPlaceholderText('按股票代码筛选（留空表示全部）');
    const windowInput = screen.getByPlaceholderText('10');

    fireEvent.change(filterInput, { target: { value: 'tsla' } });
    fireEvent.change(windowInput, { target: { value: '15' } });
    fireEvent.click(screen.getByRole('button', { name: '运行回测' }));

    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith({
        code: 'TSLA',
        force: undefined,
        minAgeDays: undefined,
        evalWindowDays: 15,
      });
    });

    await waitFor(() => {
      expect(mockGetResults).toHaveBeenLastCalledWith({
        code: 'TSLA',
        evalWindowDays: 15,
        analysisDateFrom: undefined,
        analysisDateTo: undefined,
        analysisPhase: undefined,
        page: 1,
        limit: 20,
      });
      expect(mockGetStockPerformance).toHaveBeenLastCalledWith('TSLA', {
        evalWindowDays: 15,
        analysisDateFrom: undefined,
        analysisDateTo: undefined,
        analysisPhase: undefined,
      });
    });

    expect(await screen.findByText('已处理:')).toBeInTheDocument();
    expect(screen.getByText('已保存:')).toBeInTheDocument();
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
});
