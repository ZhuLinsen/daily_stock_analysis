import type React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { decisionSignalsApi } from '../../api/decisionSignals';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import type {
  DecisionSignalFeedbackItem,
  DecisionSignalItem,
  DecisionSignalListResponse,
  DecisionSignalOutcomeListResponse,
  DecisionSignalOutcomeStatsResponse,
  DecisionSignalReassessResponse,
} from '../../types/decisionSignals';
import DecisionSignalsPage from '../DecisionSignalsPage';

vi.mock('../../api/decisionSignals', () => ({
  decisionSignalsApi: {
    list: vi.fn(),
    getLatest: vi.fn(),
    getOutcomeStats: vi.fn(),
    getSignalOutcomes: vi.fn(),
    getFeedback: vi.fn(),
    putFeedback: vi.fn(),
    updateStatus: vi.fn(),
    reassess: vi.fn(),
  },
}));

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ScatterChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CartesianGrid: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  Scatter: ({
    data,
    onClick,
    shape,
  }: {
    data: Array<{ item: DecisionSignalItem }>;
    onClick: (datum: { item: DecisionSignalItem }) => void;
    shape: (props: unknown) => React.ReactNode;
  }) => (
    <div>
      {data.map((datum, index) => (
        <button
          key={datum.item.id}
          type="button"
          data-testid={`timeline-click-${datum.item.id}`}
          onClick={() => onClick(datum)}
        >
          {shape({ cx: 20 + index * 20, cy: 20, payload: datum })}
          {datum.item.stockCode}
        </button>
      ))}
    </div>
  ),
}));

const signal: DecisionSignalItem = {
  id: 7,
  stockCode: '600519',
  stockName: '贵州茅台',
  market: 'cn',
  sourceType: 'analysis',
  sourceReportId: 3001,
  marketPhase: 'intraday',
  triggerSource: 'web',
  action: 'hold',
  actionLabel: null,
  confidence: 0.72,
  score: 82,
  horizon: '3d',
  entryLow: 1600,
  entryHigh: 1620,
  stopLoss: 1550,
  targetPrice: 1700,
  invalidation: '跌破 1550',
  watchConditions: '观察成交量',
  reason: '趋势保持',
  riskSummary: '放量下跌风险',
  catalystSummary: '业绩窗口',
  evidence: { technical: 'ma' },
  dataQualitySummary: { freshness: 'ok' },
  planQuality: 'complete',
  status: 'active',
  expiresAt: '2026-06-18T09:30:00',
  createdAt: '2026-06-17T09:30:00',
  updatedAt: '2026-06-17T09:30:00',
  metadata: { source: 'test' },
};

function makeSignal(overrides: Partial<DecisionSignalItem> = {}): DecisionSignalItem {
  return {
    ...signal,
    ...overrides,
  };
}

const formattedCreatedAt = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
}).format(new Date('2026-06-17T09:30:00Z'));

function listResponse(items: DecisionSignalItem[] = [signal], total = items.length): DecisionSignalListResponse {
  return {
    items,
    total,
    page: 1,
    pageSize: 20,
  };
}

const outcomeStats: DecisionSignalOutcomeStatsResponse = {
  engineVersion: 'decision-signal-v1',
  horizons: null,
  statuses: ['active', 'expired', 'invalidated', 'closed'],
  total: 3,
  completed: 2,
  unable: 1,
  hit: 1,
  miss: 1,
  neutral: 0,
  hitRatePct: 50,
  avgStockReturnPct: 2.5,
  unableReasons: { missing_anchor_price: 1 },
  breakdowns: {},
};

const outcomeList: DecisionSignalOutcomeListResponse = {
  items: [
    {
      id: 31,
      signalId: 7,
      horizon: '3d',
      engineVersion: 'decision-signal-v1',
      evalStatus: 'completed',
      outcome: 'hit',
      directionExpected: 'not_down',
      directionCorrect: true,
      anchorDate: '2024-01-02',
      evalWindowDays: 3,
      startPrice: 100,
      endClose: 105,
      stockReturnPct: 5,
      action: 'hold',
      market: 'cn',
      planQuality: 'complete',
      dataQualityLevel: 'good',
      holdingState: 'holding',
    },
  ],
  total: 1,
  page: 1,
  pageSize: 100,
};

const emptyFeedback: DecisionSignalFeedbackItem = {
  signalId: 7,
  feedbackValue: null,
  reasonCode: null,
  note: null,
  source: null,
};

const reassessResponse: DecisionSignalReassessResponse = {
  preview: {
    action: 'watch',
    score: 72,
    confidence: null,
    horizon: '3d',
    entryLow: 1680,
    stopLoss: 1600,
    reason: 'preview reason',
    metadata: {
      decision_profile: 'balanced',
      data_quality_level: 'medium',
      scoring_breakdown: { raw_action: 'buy' },
      guardrail_result: {
        raw_action: 'buy',
        final_action: 'watch',
        passed: false,
        violations: ['missing_confidence'],
        adjustments: ['action_downgraded_by_guardrail'],
        adjusted: true,
      },
    },
  },
  item: null,
  created: false,
  warnings: [{ code: 'action_blocked_by_guardrail' }],
  blockedReason: 'actionable_signal_blocked_by_guardrail',
};

function renderPage() {
  return render(
    <UiLanguageProvider>
      <DecisionSignalsPage />
    </UiLanguageProvider>,
  );
}

function deferredPromise<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

beforeEach(() => {
  window.history.pushState({}, '', '/');
  window.localStorage.clear();
  window.localStorage.setItem('dsa.uiLanguage', 'zh');
  vi.clearAllMocks();
  vi.mocked(decisionSignalsApi.list).mockResolvedValue(listResponse());
  vi.mocked(decisionSignalsApi.getLatest).mockResolvedValue(listResponse([signal]));
  vi.mocked(decisionSignalsApi.getOutcomeStats).mockResolvedValue(outcomeStats);
  vi.mocked(decisionSignalsApi.getSignalOutcomes).mockResolvedValue(outcomeList);
  vi.mocked(decisionSignalsApi.getFeedback).mockResolvedValue(emptyFeedback);
  vi.mocked(decisionSignalsApi.putFeedback).mockResolvedValue({
    ...emptyFeedback,
    feedbackValue: 'useful',
    source: 'web',
  });
  vi.mocked(decisionSignalsApi.updateStatus).mockResolvedValue({ ...signal, status: 'invalidated' });
  vi.mocked(decisionSignalsApi.reassess).mockResolvedValue(reassessResponse);
});

describe('DecisionSignalsPage', () => {
  it('loads active signals by default', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { name: 'AI 建议' })).toBeInTheDocument();
    await waitFor(() => {
      expect(decisionSignalsApi.list).toHaveBeenCalledWith(expect.objectContaining({
        status: 'active',
        page: 1,
        pageSize: 20,
      }));
    });
    expect(screen.getByText('贵州茅台')).toBeInTheDocument();
    expect(await screen.findByText('信号表现统计')).toBeInTheDocument();
    expect(screen.getByText('50%')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '查看 贵州茅台 AI 建议详情' })).toBeInTheDocument();
    expect(screen.getByText('贵州茅台').closest('button')).toBeNull();
    expect(screen.getByText('放量下跌风险')).toBeInTheDocument();
    expect(screen.getByText(formattedCreatedAt)).toBeInTheDocument();
  });

  it('uses a source report id query parameter as an exact analysis lookup on load', async () => {
    window.history.pushState({}, '', '/decision-signals?sourceReportId=3001&status=closed&market=cn');

    renderPage();

    expect(await screen.findByRole('heading', { name: 'AI 建议' })).toBeInTheDocument();
    await waitFor(() => {
      expect(decisionSignalsApi.list).toHaveBeenCalledWith({
        sourceReportId: 3001,
        sourceType: 'analysis',
        page: 1,
        pageSize: 20,
      });
    });
    expect(screen.getByLabelText('来源报告 ID')).toHaveValue(3001);
  });

  it('renders decision signal enum filter labels in Chinese', async () => {
    renderPage();
    await screen.findByText('贵州茅台');

    expect(within(screen.getByLabelText('市场')).getByRole('option', { name: '日股' })).toHaveValue('jp');
    expect(within(screen.getByLabelText('市场')).getByRole('option', { name: '韩股' })).toHaveValue('kr');
    expect(within(screen.getByLabelText('阶段')).getByRole('option', { name: '午间休市' })).toHaveValue('lunch_break');
    expect(within(screen.getByLabelText('阶段')).getByRole('option', { name: '集合竞价' })).toHaveValue('closing_auction');
    expect(within(screen.getByLabelText('来源')).getByRole('option', { name: '大盘复盘' })).toHaveValue('market_review');
    expect(screen.getByLabelText('来源报告 ID')).toBeInTheDocument();
  });

  it('renders decision signal filters and card value labels in English', async () => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
    vi.mocked(decisionSignalsApi.list).mockResolvedValueOnce(listResponse([
      makeSignal({
        market: 'jp',
        marketPhase: 'closing_auction',
        horizon: '10d',
        planQuality: 'partial',
      }),
    ]));

    renderPage();

    expect(await screen.findByRole('heading', { name: 'AI signals' })).toBeInTheDocument();
    expect(within(screen.getByLabelText('Market')).getByRole('option', { name: 'Japan' })).toHaveValue('jp');
    expect(within(screen.getByLabelText('Market')).getByRole('option', { name: 'Korea' })).toHaveValue('kr');
    expect(within(screen.getByLabelText('Phase')).getByRole('option', { name: 'Closing auction' })).toHaveValue('closing_auction');
    expect(within(screen.getByLabelText('Source')).getByRole('option', { name: 'Market review' })).toHaveValue('market_review');
    expect(screen.getByLabelText('Source report ID')).toBeInTheDocument();
    expect(screen.getAllByText('Japan').length).toBeGreaterThan(1);
    expect(screen.getByText('Horizon')).toBeInTheDocument();
    expect(screen.getByText('10 days')).toBeInTheDocument();
    expect(screen.getByText('Plan quality: Partial')).toBeInTheDocument();
    expect(screen.getByText('Phase: Closing auction')).toBeInTheDocument();
    expect(screen.queryByText('10d')).not.toBeInTheDocument();
    expect(screen.queryByText('closing_auction')).not.toBeInTheDocument();
  });

  it('passes filter parameters when applying filters', async () => {
    renderPage();
    await screen.findByText('贵州茅台');

    fireEvent.change(screen.getByLabelText('市场'), { target: { value: 'cn' } });
    fireEvent.change(screen.getByLabelText('股票代码'), { target: { value: '600519' } });
    fireEvent.change(screen.getByLabelText('动作'), { target: { value: 'hold' } });
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));

    await waitFor(() => {
      expect(decisionSignalsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({
        market: 'cn',
        stockCode: '600519',
        action: 'hold',
        status: 'active',
        page: 1,
        pageSize: 20,
      }));
    });
  });

  it('uses an exact analysis source report lookup when a report id filter is applied', async () => {
    renderPage();
    await screen.findByText('贵州茅台');

    fireEvent.change(screen.getByLabelText('市场'), { target: { value: 'cn' } });
    fireEvent.change(screen.getByLabelText('股票代码'), { target: { value: '600519' } });
    fireEvent.change(screen.getByLabelText('动作'), { target: { value: 'hold' } });
    fireEvent.change(screen.getByLabelText('来源'), { target: { value: 'alert' } });
    fireEvent.change(screen.getByLabelText('状态'), { target: { value: 'closed' } });
    fireEvent.change(screen.getByLabelText('来源报告 ID'), { target: { value: '3001' } });
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));

    await waitFor(() => {
      expect(decisionSignalsApi.list).toHaveBeenLastCalledWith({
        sourceReportId: 3001,
        sourceType: 'analysis',
        page: 1,
        pageSize: 20,
      });
    });
  });

  it('reassesses from the selected signal source report without triggering list lookup', async () => {
    renderPage();
    await screen.findByText('贵州茅台');

    fireEvent.click(screen.getByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));
    expect(await screen.findByText('决策风格重评估预览')).toBeInTheDocument();
    vi.mocked(decisionSignalsApi.list).mockClear();

    fireEvent.click(screen.getByRole('button', { name: '生成预览' }));

    await waitFor(() => {
      expect(decisionSignalsApi.reassess).toHaveBeenCalledWith({
        sourceReportId: 3001,
        decisionProfile: 'balanced',
        persist: false,
      });
    });
    expect(decisionSignalsApi.list).not.toHaveBeenCalled();
    expect(await screen.findByText('actionable_signal_blocked_by_guardrail')).toBeInTheDocument();
    expect(screen.getByText('buy -> watch')).toBeInTheDocument();
    expect(screen.getByText('action_blocked_by_guardrail')).toBeInTheDocument();
  });

  it('reassesses from an existing source report id filter without a selected signal', async () => {
    window.history.pushState({}, '', '/decision-signals?sourceReportId=3001');
    vi.mocked(decisionSignalsApi.list).mockResolvedValueOnce(listResponse([], 0));

    renderPage();
    expect(await screen.findByText('决策风格重评估预览')).toBeInTheDocument();
    vi.mocked(decisionSignalsApi.list).mockClear();

    fireEvent.click(screen.getByRole('button', { name: '生成预览' }));

    await waitFor(() => {
      expect(decisionSignalsApi.reassess).toHaveBeenCalledWith({
        sourceReportId: 3001,
        decisionProfile: 'balanced',
        persist: false,
      });
    });
    expect(decisionSignalsApi.list).not.toHaveBeenCalled();
  });

  it('disables reassess when no source report id is available', async () => {
    vi.mocked(decisionSignalsApi.list).mockResolvedValueOnce(listResponse([
      makeSignal({ sourceReportId: null }),
    ]));

    renderPage();
    await screen.findByText('贵州茅台');
    fireEvent.click(screen.getByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));

    await waitFor(() => {
      expect(screen.getAllByText('该信号不支持重评估').length).toBeGreaterThan(0);
    });
    expect(screen.getByRole('button', { name: '生成预览' })).toBeDisabled();
  });

  it('does not fallback to page source report id for a selected signal without source report id', async () => {
    window.history.pushState({}, '', '/decision-signals?sourceReportId=3001');
    vi.mocked(decisionSignalsApi.list).mockResolvedValueOnce(listResponse([
      makeSignal({ sourceReportId: null }),
    ]));

    renderPage();
    await screen.findByText('决策风格重评估预览');
    fireEvent.click(screen.getByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));

    await waitFor(() => {
      expect(screen.getAllByText('该信号不支持重评估').length).toBeGreaterThan(0);
    });
    expect(screen.getByRole('button', { name: '生成预览' })).toBeDisabled();
    expect(decisionSignalsApi.reassess).not.toHaveBeenCalled();
  });

  it('ignores stale reassess responses after switching the selected signal', async () => {
    const nextSignal = makeSignal({
      id: 8,
      stockCode: '000001',
      stockName: '平安银行',
      sourceReportId: 3002,
    });
    const pending = deferredPromise<DecisionSignalReassessResponse>();
    vi.mocked(decisionSignalsApi.list).mockResolvedValueOnce(listResponse([signal, nextSignal], 2));
    vi.mocked(decisionSignalsApi.reassess).mockReturnValueOnce(pending.promise);

    renderPage();
    await screen.findByText('贵州茅台');
    fireEvent.click(screen.getByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));
    fireEvent.click(await screen.findByRole('button', { name: '生成预览' }));
    fireEvent.click(screen.getByRole('button', { name: '查看 平安银行 AI 建议详情' }));

    await act(async () => {
      pending.resolve({
        ...reassessResponse,
        preview: { ...reassessResponse.preview, reason: 'stale A preview' },
      });
    });

    expect(screen.queryByText('stale A preview')).not.toBeInTheDocument();
  });

  it('queries latest active signals by stock code', async () => {
    renderPage();
    await screen.findByText('贵州茅台');

    fireEvent.change(screen.getByLabelText('最新股票代码'), {
      target: { value: '600519' },
    });
    fireEvent.click(screen.getByRole('button', { name: '查询最新' }));

    await waitFor(() => {
      expect(decisionSignalsApi.getLatest).toHaveBeenCalledWith('600519', {
        market: undefined,
        limit: 5,
      });
    });
  });

  it('uses the applied market filter for latest lookup instead of draft filter state', async () => {
    renderPage();
    await screen.findByText('贵州茅台');

    const marketSelect = screen.getByLabelText('市场');
    fireEvent.change(marketSelect, { target: { value: 'cn' } });
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));
    await waitFor(() => {
      expect(decisionSignalsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({
        market: 'cn',
      }));
    });

    fireEvent.change(marketSelect, { target: { value: 'hk' } });
    fireEvent.change(screen.getByLabelText('最新股票代码'), {
      target: { value: '600519' },
    });
    fireEvent.click(screen.getByRole('button', { name: '查询最新' }));

    await waitFor(() => {
      expect(decisionSignalsApi.getLatest).toHaveBeenCalledWith('600519', {
        market: 'cn',
        limit: 5,
      });
    });
  });

  it('ignores stale latest-search responses', async () => {
    const firstSearch = deferredPromise<DecisionSignalListResponse>();
    const secondSignal = {
      ...signal,
      id: 8,
      stockCode: 'AAPL',
      stockName: 'Apple',
      market: 'us' as const,
      riskSummary: '第二次查询结果',
    };
    vi.mocked(decisionSignalsApi.getLatest)
      .mockReturnValueOnce(firstSearch.promise)
      .mockResolvedValueOnce(listResponse([secondSignal]));
    renderPage();
    await screen.findByText('贵州茅台');

    const latestInput = screen.getByLabelText('最新股票代码');
    fireEvent.change(latestInput, {
      target: { value: '600519' },
    });
    fireEvent.click(screen.getByRole('button', { name: '查询最新' }));

    fireEvent.change(latestInput, {
      target: { value: 'AAPL' },
    });
    fireEvent.submit(latestInput.closest('form') as HTMLFormElement);

    expect(await screen.findByText('第二次查询结果')).toBeInTheDocument();

    await act(async () => {
      firstSearch.resolve(listResponse([{ ...signal, riskSummary: '第一次晚返回结果' }]));
      await firstSearch.promise;
    });

    await waitFor(() => {
      expect(screen.queryByText('第一次晚返回结果')).not.toBeInTheDocument();
    });
    expect(screen.getByText('第二次查询结果')).toBeInTheDocument();
  });

  it('renders latest empty and error states', async () => {
    vi.mocked(decisionSignalsApi.getLatest).mockResolvedValueOnce(listResponse([], 0));
    renderPage();
    await screen.findByText('贵州茅台');

    fireEvent.change(screen.getByLabelText('最新股票代码'), {
      target: { value: '600519' },
    });
    fireEvent.click(screen.getByRole('button', { name: '查询最新' }));

    expect(await screen.findByText('暂无最新有效信号')).toBeInTheDocument();

    vi.mocked(decisionSignalsApi.getLatest).mockRejectedValueOnce(new Error('latest down'));
    fireEvent.click(screen.getByRole('button', { name: '查询最新' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('latest down');
  });

  it('does not request the timeline before a non-empty stock search', async () => {
    renderPage();

    await screen.findByText('贵州茅台');
    expect(screen.getByText('输入股票代码查看时间线')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '查询时间线' })).toBeDisabled();
    expect(decisionSignalsApi.list).toHaveBeenCalledTimes(1);
    expect(within(screen.getByLabelText('时间线状态')).queryByRole('option', { name: '已关闭' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('profile')).not.toBeInTheDocument();
  });

  it('queries timeline with independent filters and no default status', async () => {
    renderPage();
    await screen.findByText('贵州茅台');

    fireEvent.change(screen.getByLabelText('时间线市场'), { target: { value: 'cn' } });
    fireEvent.change(screen.getByLabelText('时间线股票代码'), { target: { value: ' 600519 ' } });
    fireEvent.change(screen.getByLabelText('时间范围'), { target: { value: '30d' } });
    fireEvent.click(screen.getByRole('button', { name: '查询时间线' }));

    await waitFor(() => {
      expect(decisionSignalsApi.list).toHaveBeenCalledTimes(2);
    });
    expect(decisionSignalsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({
      market: 'cn',
      stockCode: '600519',
      page: 1,
      pageSize: 100,
      status: undefined,
    }));
    const params = vi.mocked(decisionSignalsApi.list).mock.calls.at(-1)?.[0] as Record<string, string>;
    expect(params.createdFrom).toEqual(expect.any(String));
    expect(params.createdTo).toEqual(expect.any(String));
  });

  it('passes active timeline status, shows truncation, and opens details from a point', async () => {
    const timelineSignal = makeSignal({
      id: 8,
      stockCode: 'AAPL',
      stockName: 'Apple',
      market: 'us',
      action: 'alert',
      riskSummary: 'Timeline risk',
    });
    vi.mocked(decisionSignalsApi.list)
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(listResponse([timelineSignal], 150));
    renderPage();
    await screen.findByText('贵州茅台');

    fireEvent.change(screen.getByLabelText('时间线股票代码'), { target: { value: 'AAPL' } });
    fireEvent.change(screen.getByLabelText('时间线状态'), { target: { value: 'active' } });
    fireEvent.click(screen.getByRole('button', { name: '查询时间线' }));

    await waitFor(() => {
      expect(decisionSignalsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({
        stockCode: 'AAPL',
        status: 'active',
        pageSize: 100,
      }));
    });
    expect(await screen.findByText('仅展示最近 100 条信号，请缩小时间范围。')).toBeInTheDocument();
    fireEvent.click(await screen.findByTestId('timeline-click-8'));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Timeline risk')).toBeInTheDocument();
  });

  it('returns to the timeline guide when stock code is cleared after a search', async () => {
    const timelineSignal = makeSignal({
      id: 8,
      stockCode: 'AAPL',
      stockName: 'Apple',
      market: 'us',
      riskSummary: 'Timeline stale risk',
    });
    vi.mocked(decisionSignalsApi.list)
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(listResponse([timelineSignal], 1));
    renderPage();
    await screen.findByText('贵州茅台');

    const timelineStockInput = screen.getByLabelText('时间线股票代码');
    fireEvent.change(timelineStockInput, { target: { value: 'AAPL' } });
    fireEvent.click(screen.getByRole('button', { name: '查询时间线' }));
    fireEvent.click(await screen.findByTestId('timeline-click-8'));
    expect(within(await screen.findByRole('dialog')).getByText('Timeline stale risk')).toBeInTheDocument();

    fireEvent.change(timelineStockInput, { target: { value: '' } });

    expect(screen.getByText('输入股票代码查看时间线')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '查询时间线' })).toBeDisabled();
    expect(screen.queryByTestId('timeline-click-8')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(decisionSignalsApi.list).toHaveBeenCalledTimes(2);
  });

  it('closes a timeline-sourced drawer when an active timeline status update removes it', async () => {
    const timelineSignal = makeSignal({
      id: 8,
      stockCode: 'AAPL',
      stockName: 'Apple',
      market: 'us',
      riskSummary: 'Timeline active risk',
    });
    vi.mocked(decisionSignalsApi.list)
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(listResponse([timelineSignal], 1))
      .mockResolvedValueOnce(listResponse());
    vi.mocked(decisionSignalsApi.updateStatus).mockResolvedValueOnce({ ...timelineSignal, status: 'invalidated' });
    renderPage();
    await screen.findByText('贵州茅台');

    fireEvent.change(screen.getByLabelText('时间线股票代码'), { target: { value: 'AAPL' } });
    fireEvent.change(screen.getByLabelText('时间线状态'), { target: { value: 'active' } });
    fireEvent.click(screen.getByRole('button', { name: '查询时间线' }));
    fireEvent.click(await screen.findByTestId('timeline-click-8'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: '标记失效' }));
    fireEvent.click(await screen.findByRole('button', { name: '确定' }));

    await waitFor(() => {
      expect(decisionSignalsApi.updateStatus).toHaveBeenCalledWith(8, { status: 'invalidated' });
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByText('暂无时间线信号')).toBeInTheDocument();
  });

  it('uses applied timeline filters instead of draft filters after status updates', async () => {
    const timelineSignal = makeSignal({
      id: 8,
      stockCode: 'AAPL',
      stockName: 'Apple',
      market: 'us',
      riskSummary: 'Timeline all risk',
    });
    vi.mocked(decisionSignalsApi.list)
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(listResponse([timelineSignal], 1))
      .mockResolvedValueOnce(listResponse());
    vi.mocked(decisionSignalsApi.updateStatus).mockResolvedValueOnce({ ...timelineSignal, status: 'invalidated' });
    renderPage();
    await screen.findByText('贵州茅台');

    fireEvent.change(screen.getByLabelText('时间线股票代码'), { target: { value: 'AAPL' } });
    fireEvent.click(screen.getByRole('button', { name: '查询时间线' }));
    fireEvent.change(screen.getByLabelText('时间线状态'), { target: { value: 'active' } });
    fireEvent.click(await screen.findByTestId('timeline-click-8'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: '标记失效' }));
    fireEvent.click(await screen.findByRole('button', { name: '确定' }));

    await waitFor(() => {
      expect(decisionSignalsApi.updateStatus).toHaveBeenCalledWith(8, { status: 'invalidated' });
    });
    await waitFor(() => {
      expect(within(screen.getByRole('dialog')).getByText('已失效')).toBeInTheDocument();
    });
    expect(screen.queryByText('暂无时间线信号')).not.toBeInTheDocument();
  });

  it('renders empty and error states', async () => {
    vi.mocked(decisionSignalsApi.list).mockResolvedValueOnce(listResponse([], 0));

    renderPage();

    expect(await screen.findByText('暂无决策信号')).toBeInTheDocument();
    vi.mocked(decisionSignalsApi.list).mockRejectedValueOnce(new Error('boom'));
    fireEvent.click(screen.getByRole('button', { name: '刷新' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('boom');
  });

  it('clears stale list data and closes a list drawer when refresh fails', async () => {
    vi.mocked(decisionSignalsApi.list)
      .mockResolvedValueOnce(listResponse())
      .mockRejectedValueOnce(new Error('filter failed'));
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('股票代码'), { target: { value: 'AAPL' } });
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('filter failed');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: '查看 贵州茅台 AI 建议详情' })).not.toBeInTheDocument();
    expect(screen.getByText('共 0 条信号')).toBeInTheDocument();
  });

  it('opens details and confirms terminal status updates', async () => {
    vi.mocked(decisionSignalsApi.list)
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(listResponse([], 0));
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));
    const dialog = await screen.findByRole('dialog');
    expect(screen.getAllByText('贵州茅台')).toHaveLength(2);
    expect(within(dialog).getByText('趋势保持')).toBeInTheDocument();
    expect(within(dialog).getByText('#3001')).toBeInTheDocument();
    expect(await within(dialog).findByText('命中')).toBeInTheDocument();
    expect(within(dialog).getByText('暂无反馈')).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: '标记失效' }));
    expect(await screen.findByRole('heading', { name: '更新信号状态' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确定' }));

    await waitFor(() => {
      expect(decisionSignalsApi.updateStatus).toHaveBeenCalledWith(7, { status: 'invalidated' });
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByText('共 0 条信号')).toBeInTheDocument();
    expect(screen.getByText('暂无决策信号')).toBeInTheDocument();
  });

  it('submits useful feedback from the details drawer', async () => {
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(await within(dialog).findByRole('button', { name: '有用' }));

    await waitFor(() => {
      expect(decisionSignalsApi.putFeedback).toHaveBeenCalledWith(7, {
        feedbackValue: 'useful',
        source: 'web',
      });
    });
    await waitFor(() => {
      expect(within(dialog).getAllByText('有用').length).toBeGreaterThan(1);
    });
  });

  it('ignores stale feedback submit responses after selecting another signal', async () => {
    const feedbackSave = deferredPromise<DecisionSignalFeedbackItem>();
    const nextSignal = makeSignal({
      id: 8,
      stockCode: 'AAPL',
      stockName: 'Apple',
      market: 'us',
      reason: 'Second signal reason',
    });
    vi.mocked(decisionSignalsApi.list).mockResolvedValueOnce(listResponse([signal, nextSignal], 2));
    vi.mocked(decisionSignalsApi.getFeedback).mockImplementation(async (signalId: number) => ({
      ...emptyFeedback,
      signalId,
    }));
    vi.mocked(decisionSignalsApi.putFeedback).mockReturnValueOnce(feedbackSave.promise);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));
    let dialog = await screen.findByRole('dialog');
    fireEvent.click(await within(dialog).findByRole('button', { name: '有用' }));
    fireEvent.click(screen.getByRole('button', { name: '查看 Apple AI 建议详情' }));
    dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('Second signal reason')).toBeInTheDocument();

    await act(async () => {
      feedbackSave.resolve({
        ...emptyFeedback,
        feedbackValue: 'useful',
        source: 'web',
      });
      await feedbackSave.promise;
    });

    await waitFor(() => {
      expect(within(dialog).getByText('暂无反馈')).toBeInTheDocument();
      expect(within(dialog).getAllByText('有用')).toHaveLength(1);
    });
  });

  it('closes a list-sourced drawer when filters remove the selected signal', async () => {
    vi.mocked(decisionSignalsApi.list)
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(listResponse([], 0));
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('股票代码'), { target: { value: 'AAPL' } });
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByText('暂无决策信号')).toBeInTheDocument();
  });

  it('keeps a latest-sourced drawer open when the main list refreshes', async () => {
    const latestSignal = makeSignal({
      id: 8,
      stockCode: 'AAPL',
      stockName: 'Apple',
      market: 'us',
      riskSummary: 'Latest risk',
    });
    vi.mocked(decisionSignalsApi.list)
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(listResponse([], 0));
    vi.mocked(decisionSignalsApi.getLatest).mockResolvedValueOnce(listResponse([latestSignal]));
    renderPage();

    await screen.findByText('贵州茅台');
    fireEvent.change(screen.getByLabelText('最新股票代码'), { target: { value: 'AAPL' } });
    fireEvent.click(screen.getByRole('button', { name: '查询最新' }));
    fireEvent.click(await screen.findByRole('button', { name: '查看 Apple AI 建议详情' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Latest risk')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('股票代码'), { target: { value: '600519' } });
    fireEvent.click(screen.getByRole('button', { name: '筛选' }));

    await waitFor(() => {
      expect(within(screen.getByRole('dialog')).getByText('Latest risk')).toBeInTheDocument();
    });
  });

  it('closes a latest-sourced drawer when the next latest search excludes the selected signal', async () => {
    const firstLatestSignal = makeSignal({
      id: 8,
      stockCode: 'AAPL',
      stockName: 'Apple',
      market: 'us',
      riskSummary: 'Latest A risk',
    });
    const nextLatestSignal = makeSignal({
      id: 9,
      stockCode: 'MSFT',
      stockName: 'Microsoft',
      market: 'us',
      riskSummary: 'Latest B risk',
    });
    vi.mocked(decisionSignalsApi.getLatest)
      .mockResolvedValueOnce(listResponse([firstLatestSignal]))
      .mockResolvedValueOnce(listResponse([nextLatestSignal]));
    renderPage();

    await screen.findByText('贵州茅台');
    const latestInput = screen.getByLabelText('最新股票代码');
    fireEvent.change(latestInput, { target: { value: 'AAPL' } });
    fireEvent.click(screen.getByRole('button', { name: '查询最新' }));
    fireEvent.click(await screen.findByRole('button', { name: '查看 Apple AI 建议详情' }));
    expect(within(await screen.findByRole('dialog')).getByText('Latest A risk')).toBeInTheDocument();

    fireEvent.change(latestInput, { target: { value: 'MSFT' } });
    fireEvent.click(screen.getByRole('button', { name: '查询最新' }));

    expect(await screen.findByText('Latest B risk')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('closes a latest-sourced drawer when latest search fails', async () => {
    const latestSignal = makeSignal({
      id: 8,
      stockCode: 'AAPL',
      stockName: 'Apple',
      market: 'us',
      riskSummary: 'Latest risk before failure',
    });
    vi.mocked(decisionSignalsApi.getLatest)
      .mockResolvedValueOnce(listResponse([latestSignal]))
      .mockRejectedValueOnce(new Error('latest failed'));
    renderPage();

    await screen.findByText('贵州茅台');
    const latestInput = screen.getByLabelText('最新股票代码');
    fireEvent.change(latestInput, { target: { value: 'AAPL' } });
    fireEvent.click(screen.getByRole('button', { name: '查询最新' }));
    fireEvent.click(await screen.findByRole('button', { name: '查看 Apple AI 建议详情' }));
    expect(within(await screen.findByRole('dialog')).getByText('Latest risk before failure')).toBeInTheDocument();

    fireEvent.change(latestInput, { target: { value: 'MSFT' } });
    fireEvent.click(screen.getByRole('button', { name: '查询最新' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('latest failed');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('keeps a list-sourced drawer open when latest search results change', async () => {
    const latestSignal = makeSignal({
      id: 8,
      stockCode: 'AAPL',
      stockName: 'Apple',
      market: 'us',
      riskSummary: 'Latest lookup risk',
    });
    vi.mocked(decisionSignalsApi.getLatest).mockResolvedValueOnce(listResponse([latestSignal]));
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));
    expect(within(await screen.findByRole('dialog')).getByText('趋势保持')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('最新股票代码'), { target: { value: 'AAPL' } });
    fireEvent.click(screen.getByRole('button', { name: '查询最新' }));

    expect(await screen.findByText('Latest lookup risk')).toBeInTheDocument();
    expect(within(screen.getByRole('dialog')).getByText('趋势保持')).toBeInTheDocument();
  });

  it('ignores duplicate status confirmation clicks and disables confirmation controls', async () => {
    const statusUpdate = deferredPromise<DecisionSignalItem>();
    vi.mocked(decisionSignalsApi.updateStatus).mockReturnValueOnce(statusUpdate.promise);
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: '标记失效' }));
    const confirmButton = await screen.findByRole('button', { name: '确定' });

    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);

    expect(decisionSignalsApi.updateStatus).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(confirmButton).toBeDisabled());

    await act(async () => {
      statusUpdate.resolve({ ...signal, status: 'invalidated' });
      await statusUpdate.promise;
    });
  });

  it('clamps to a valid page after status update removes the only item on the last page', async () => {
    const pageTwoSignal = makeSignal({ id: 8, stockCode: 'AAPL', stockName: 'Apple', market: 'us' });
    vi.mocked(decisionSignalsApi.list)
      .mockResolvedValueOnce(listResponse([signal], 21))
      .mockResolvedValueOnce(listResponse([pageTwoSignal], 21))
      .mockResolvedValueOnce(listResponse([], 20))
      .mockResolvedValueOnce(listResponse([signal], 20));
    vi.mocked(decisionSignalsApi.updateStatus).mockResolvedValueOnce({ ...pageTwoSignal, status: 'invalidated' });
    renderPage();

    await screen.findByText('贵州茅台');
    fireEvent.click(screen.getByRole('button', { name: '2' }));
    fireEvent.click(await screen.findByRole('button', { name: '查看 Apple AI 建议详情' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: '标记失效' }));
    fireEvent.click(await screen.findByRole('button', { name: '确定' }));

    await waitFor(() => {
      expect(decisionSignalsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({
        page: 1,
        pageSize: 20,
      }));
    });
    expect(screen.getByText('共 20 条信号')).toBeInTheDocument();
    expect(screen.queryByText('暂无决策信号')).not.toBeInTheDocument();
  });

  it('closes the status confirmation dialog and shows an error when status update fails', async () => {
    vi.mocked(decisionSignalsApi.updateStatus).mockRejectedValueOnce(new Error('status update failed'));
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: '标记失效' }));
    expect(await screen.findByRole('heading', { name: '更新信号状态' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '确定' }));

    const errorMessage = await screen.findByText('status update failed');
    expect(errorMessage.closest('[role="alert"]')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: '更新信号状态' })).not.toBeInTheDocument();
    });
    expect(within(dialog).getByText('有效')).toBeInTheDocument();
  });

  it.each([
    ['关闭信号', 'closed'],
    ['归档', 'archived'],
  ] as const)('confirms %s without exposing active recovery', async (buttonName, status) => {
    vi.mocked(decisionSignalsApi.updateStatus).mockResolvedValueOnce({ ...signal, status });
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: '查看 贵州茅台 AI 建议详情' }));
    const dialog = await screen.findByRole('dialog');

    expect(within(dialog).getByRole('button', { name: '关闭信号' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '标记失效' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: '归档' })).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: '有效' })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: '已过期' })).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: buttonName }));
    fireEvent.click(await screen.findByRole('button', { name: '确定' }));

    await waitFor(() => {
      expect(decisionSignalsApi.updateStatus).toHaveBeenCalledWith(7, { status });
    });
  });
});
