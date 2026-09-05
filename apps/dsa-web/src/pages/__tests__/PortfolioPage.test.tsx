import type React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { decisionSignalsApi } from '../../api/decisionSignals';
import { createApiError, createParsedApiError } from '../../api/error';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import type { DecisionSignalItem } from '../../types/decisionSignals';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
import PortfolioPage from '../PortfolioPage';

const {
  getAccounts,
  getSnapshot,
  getRisk,
  refreshFx,
  listImportBrokers,
  listTrades,
  listCashLedger,
  listCorporateActions,
  createTrade,
  deleteTrade,
  createCashLedger,
  deleteCashLedger,
  createCorporateAction,
  deleteCorporateAction,
  parseCsvImport,
  commitCsvImport,
  createAccount,
  deleteAccount,
  analyzePosition,
  listDecisionSignals,
  getLatestDecisionSignals,
} = vi.hoisted(() => ({
  getAccounts: vi.fn(),
  getSnapshot: vi.fn(),
  getRisk: vi.fn(),
  refreshFx: vi.fn(),
  listImportBrokers: vi.fn(),
  listTrades: vi.fn(),
  listCashLedger: vi.fn(),
  listCorporateActions: vi.fn(),
  createTrade: vi.fn(),
  deleteTrade: vi.fn(),
  createCashLedger: vi.fn(),
  deleteCashLedger: vi.fn(),
  createCorporateAction: vi.fn(),
  deleteCorporateAction: vi.fn(),
  parseCsvImport: vi.fn(),
  commitCsvImport: vi.fn(),
  createAccount: vi.fn(),
  deleteAccount: vi.fn(),
  analyzePosition: vi.fn(),
  listDecisionSignals: vi.fn(),
  getLatestDecisionSignals: vi.fn(),
}));

vi.mock('../../api/decisionSignals', () => ({
  decisionSignalsApi: {
    list: listDecisionSignals,
    getLatest: getLatestDecisionSignals,
  },
}));

vi.mock('../../api/portfolio', () => ({
  portfolioApi: {
    getAccounts,
    getSnapshot,
    getRisk,
    refreshFx,
    listImportBrokers,
    listTrades,
    listCashLedger,
    listCorporateActions,
    createTrade,
    deleteTrade,
    createCashLedger,
    deleteCashLedger,
    createCorporateAction,
    deleteCorporateAction,
    parseCsvImport,
    commitCsvImport,
    createAccount,
    deleteAccount,
    analyzePosition,
  },
}));

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PieChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Pie: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Tooltip: () => null,
  Legend: () => null,
  Cell: () => null,
}));

type AccountItem = {
  id: number;
  name: string;
  market?: 'cn' | 'hk' | 'us' | 'jp' | 'kr' | 'tw';
  baseCurrency?: string;
};

function makeAccounts(items: AccountItem[] = [{ id: 1, name: 'Main' }]) {
  return {
    accounts: items.map((item) => ({
      id: item.id,
      name: item.name,
      broker: 'Demo',
      market: item.market ?? 'us',
      baseCurrency: item.baseCurrency ?? 'CNY',
      isActive: true,
      ownerId: null,
      createdAt: '2026-03-19T00:00:00Z',
      updatedAt: '2026-03-19T00:00:00Z',
    })),
  };
}

function makeSnapshot(options: {
  accountId?: number;
  fxStale?: boolean;
  accountCount?: number;
  dataQuality?: string;
  limitations?: string[];
  positions?: Array<Record<string, unknown>>;
} = {}) {
  const accountId = options.accountId ?? 1;
  return {
    asOf: '2026-03-19',
    costMethod: 'fifo' as const,
    currency: 'CNY',
    accountCount: options.accountCount ?? 1,
    totalCash: 1000,
    totalMarketValue: 2000,
    totalEquity: 3000,
    realizedPnl: 0,
    unrealizedPnl: 0,
    feeTotal: 0,
    taxTotal: 0,
    fxStale: options.fxStale ?? true,
    dataQuality: options.dataQuality ?? 'ok',
    limitations: options.limitations ?? [],
    accounts: [
      {
        accountId,
        accountName: `Account ${accountId}`,
        ownerId: null,
        broker: 'Demo',
        market: 'us',
        baseCurrency: 'CNY',
        asOf: '2026-03-19',
        costMethod: 'fifo' as const,
        totalCash: 1000,
        totalMarketValue: 2000,
        totalEquity: 3000,
        realizedPnl: 0,
        unrealizedPnl: 0,
        feeTotal: 0,
        taxTotal: 0,
        fxStale: options.fxStale ?? true,
        positions: options.positions ?? [],
      },
    ],
  };
}

function makePosition(overrides: Record<string, unknown> = {}) {
  return {
    symbol: '600519',
    market: 'cn',
    currency: 'CNY',
    quantity: 1,
    avgCost: 1500,
    totalCost: 1500,
    lastPrice: 1600,
    marketValueBase: 1600,
    unrealizedPnlBase: 100,
    unrealizedPnlPct: 6.67,
    valuationCurrency: 'CNY',
    priceSource: 'history_close',
    priceDate: '2026-06-17',
    priceStale: false,
    priceAvailable: true,
    ...overrides,
  };
}

function makeRisk(overrides: Record<string, unknown> = {}) {
  return {
    asOf: '2026-03-19',
    accountId: null,
    costMethod: 'fifo' as const,
    currency: 'CNY',
    thresholds: {},
    concentration: {
      totalMarketValue: 0,
      topWeightPct: 0,
      alert: false,
      topPositions: [],
    },
    sectorConcentration: {
      totalMarketValue: 0,
      topWeightPct: 0,
      alert: false,
      topSectors: [],
      coverage: { unclassifiedCount: 0, failedCount: 0 },
      errors: [],
    },
    drawdown: {
      seriesPoints: 0,
      maxDrawdownPct: 0,
      currentDrawdownPct: 0,
      alert: false,
      fxStale: false,
    },
    stopLoss: {
      nearAlert: false,
      triggeredCount: 0,
      nearCount: 0,
      items: [],
    },
    decisionSignalRisk: {
      available: true,
      total: 0,
      actions: { sell: 0, reduce: 0, alert: 0 },
      items: [],
    },
    ...overrides,
  };
}

function makeDecisionSignal(overrides: Partial<DecisionSignalItem> = {}): DecisionSignalItem {
  return {
    id: 100,
    stockCode: '600519',
    stockName: '贵州茅台',
    market: 'cn',
    sourceType: 'analysis',
    sourceReportId: 1,
    traceId: null,
    marketPhase: 'intraday',
    triggerSource: 'portfolio',
    action: 'hold',
    actionLabel: null,
    confidence: 0.7,
    score: 80,
    horizon: '3d',
    entryLow: null,
    entryHigh: null,
    stopLoss: null,
    targetPrice: null,
    invalidation: null,
    watchConditions: '观察量能',
    reason: '趋势延续',
    riskSummary: '短线回撤风险',
    catalystSummary: null,
    evidence: undefined,
    dataQualitySummary: undefined,
    planQuality: 'partial',
    status: 'active',
    expiresAt: null,
    createdAt: '2026-06-17T08:00:00',
    updatedAt: '2026-06-17T08:00:00',
    metadata: undefined,
    ...overrides,
  };
}

function deferredPromise<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function waitForInitialLoad() {
  await waitFor(() => expect(getAccounts).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(getSnapshot).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(getRisk).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(listTrades).toHaveBeenCalledTimes(1));
}

describe('PortfolioPage FX refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();

    getAccounts.mockResolvedValue(makeAccounts());
    getSnapshot.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => makeSnapshot({ accountId, fxStale: true }));
    getRisk.mockResolvedValue(makeRisk());
    refreshFx.mockResolvedValue({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: true,
      disabledReason: null,
      pairCount: 1,
      updatedCount: 1,
      staleCount: 0,
      errorCount: 0,
    });
    listImportBrokers.mockResolvedValue({
      brokers: [{ broker: 'huatai', aliases: [], displayName: '华泰' }],
    });
    listTrades.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 });
    listCashLedger.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 });
    listCorporateActions.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 });
    createTrade.mockResolvedValue({ id: 1 });
    deleteTrade.mockResolvedValue({ deleted: 1 });
    createCashLedger.mockResolvedValue({ id: 1 });
    deleteCashLedger.mockResolvedValue({ deleted: 1 });
    createCorporateAction.mockResolvedValue({ id: 1 });
    deleteCorporateAction.mockResolvedValue({ deleted: 1 });
    parseCsvImport.mockResolvedValue({ broker: 'huatai', recordCount: 0, skippedCount: 0, errorCount: 0, records: [], errors: [] });
    commitCsvImport.mockResolvedValue({
      accountId: 1,
      recordCount: 0,
      insertedCount: 0,
      duplicateCount: 0,
      failedCount: 0,
      dryRun: true,
      errors: [],
    });
    createAccount.mockResolvedValue({ id: 1 });
    deleteAccount.mockResolvedValue({ deleted: 1 });
    analyzePosition.mockResolvedValue({
      taskId: 'task-portfolio-1',
      traceId: 'task-portfolio-1',
      status: 'pending',
      message: '分析任务已加入队列: HK00700',
      analysisPhase: 'auto',
    });
    getLatestDecisionSignals.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 1 });
  });

  function renderEnglishPage() {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    render(
      <UiLanguageProvider>
        <PortfolioPage />
      </UiLanguageProvider>,
    );
  }

  it('uses fast portfolio valuation for page snapshot and risk loads', async () => {
    render(<PortfolioPage />);

    await waitForInitialLoad();

    expect(getSnapshot).toHaveBeenCalledWith({ accountId: undefined, costMethod: 'fifo', includeRealtime: false });
    expect(getRisk).toHaveBeenCalledWith({ accountId: undefined, costMethod: 'fifo', includeRealtime: false });
  });

  it('renders stale FX status with a manual refresh button', async () => {
    render(<PortfolioPage />);

    await waitForInitialLoad();

    expect(await screen.findByText('过期')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新汇率' })).toBeInTheDocument();
  });

  it('renders portfolio risk flags and exposure dashboard from snapshot and risk data', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [
        makePosition({
          symbol: '600519',
          market: 'cn',
          currency: 'CNY',
          valuationCurrency: 'CNY',
          marketValueBase: 6000,
        }),
        makePosition({
          symbol: 'HK00700',
          market: 'hk',
          currency: 'HKD',
          valuationCurrency: 'CNY',
          marketValueBase: 4000,
          priceStale: true,
        }),
      ],
    }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        alert: true,
        topPositions: [{ symbol: '600519', marketValueBase: 6000, weightPct: 60, isAlert: true }],
      },
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: true,
        topSectors: [{ sector: '白酒', marketValueBase: 7000, weightPct: 70, symbolCount: 2, isAlert: true }],
        coverage: { unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
      drawdown: {
        seriesPoints: 10,
        maxDrawdownPct: 18.5,
        currentDrawdownPct: 12.5,
        alert: true,
        fxStale: false,
      },
      stopLoss: {
        nearAlert: true,
        triggeredCount: 1,
        nearCount: 2,
        items: [],
      },
      decisionSignalRisk: {
        available: true,
        total: 1,
        actions: { sell: 0, reduce: 1, alert: 0 },
        items: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);

    expect(dashboardScope.getByText('风险旗标')).toBeInTheDocument();
    expect(dashboardScope.getAllByText('需处理').length).toBeGreaterThanOrEqual(5);
    expect(dashboardScope.getByText('个股集中')).toBeInTheDocument();
    expect(dashboardScope.getByText('Top1: 600519')).toBeInTheDocument();
    expect(dashboardScope.getByText('行业集中')).toBeInTheDocument();
    expect(dashboardScope.getByText('Top1: 白酒')).toBeInTheDocument();
    expect(dashboardScope.getByText('最大回撤: 18.50%')).toBeInTheDocument();
    expect(dashboardScope.getByText('触发: 1 · 接近: 2')).toBeInTheDocument();
    expect(dashboardScope.getByText('缺价: 0 · 过期价: 1')).toBeInTheDocument();
    expect(dashboardScope.getAllByText('市场暴露').length).toBeGreaterThan(0);
    expect(dashboardScope.getAllByText('币种暴露').length).toBeGreaterThan(0);
    expect(dashboardScope.getByText('CN')).toBeInTheDocument();
    expect(dashboardScope.getByText('HK')).toBeInTheDocument();
    expect(dashboardScope.getByText('CNY')).toBeInTheDocument();
    expect(dashboardScope.getByText('HKD')).toBeInTheDocument();
  });

  it('converts single-account foreign-currency exposure values into the snapshot currency', async () => {
    getSnapshot.mockResolvedValueOnce({
      asOf: '2026-03-19',
      costMethod: 'fifo' as const,
      currency: 'CNY',
      accountCount: 1,
      totalCash: 0,
      totalMarketValue: 700,
      totalEquity: 700,
      realizedPnl: 0,
      unrealizedPnl: 0,
      feeTotal: 0,
      taxTotal: 0,
      fxStale: false,
      dataQuality: 'ok',
      limitations: [],
      accounts: [
        {
          accountId: 1,
          accountName: 'USD Account',
          ownerId: null,
          broker: 'Demo',
          market: 'us',
          baseCurrency: 'USD',
          asOf: '2026-03-19',
          costMethod: 'fifo' as const,
          totalCash: 0,
          totalMarketValue: 100,
          totalEquity: 100,
          realizedPnl: 0,
          unrealizedPnl: 0,
          feeTotal: 0,
          taxTotal: 0,
          fxStale: false,
          dataQuality: 'ok',
          limitations: [],
          positions: [
            makePosition({
              symbol: 'AAPL',
              market: 'us',
              currency: 'USD',
              valuationCurrency: 'USD',
              marketValueBase: 100,
            }),
          ],
        },
      ],
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);
    expect(dashboardScope.getByText('US')).toBeInTheDocument();
    expect(dashboardScope.getAllByText('CNY 700.00').length).toBeGreaterThan(0);
    expect(dashboardScope.queryByText('CNY 100.00')).not.toBeInTheDocument();
    expect(dashboardScope.getAllByText('100.00%').length).toBeGreaterThan(0);
  });

  it('hides exposure breakdowns when all-account totals mix base currencies without per-account converted values', async () => {
    getSnapshot.mockResolvedValueOnce({
      asOf: '2026-03-19',
      costMethod: 'fifo' as const,
      currency: 'CNY',
      accountCount: 2,
      totalCash: 0,
      totalMarketValue: 770,
      totalEquity: 770,
      realizedPnl: 0,
      unrealizedPnl: 0,
      feeTotal: 0,
      taxTotal: 0,
      fxStale: false,
      dataQuality: 'ok',
      limitations: [],
      accounts: [
        {
          accountId: 1,
          accountName: 'CNY Account',
          ownerId: null,
          broker: 'Demo',
          market: 'cn',
          baseCurrency: 'CNY',
          asOf: '2026-03-19',
          costMethod: 'fifo' as const,
          totalCash: 0,
          totalMarketValue: 70,
          totalEquity: 70,
          realizedPnl: 0,
          unrealizedPnl: 0,
          feeTotal: 0,
          taxTotal: 0,
          fxStale: false,
          dataQuality: 'ok',
          limitations: [],
          positions: [
            makePosition({
              symbol: '600519',
              market: 'cn',
              currency: 'CNY',
              valuationCurrency: 'CNY',
              marketValueBase: 70,
            }),
          ],
        },
        {
          accountId: 2,
          accountName: 'USD Account',
          ownerId: null,
          broker: 'Demo',
          market: 'us',
          baseCurrency: 'USD',
          asOf: '2026-03-19',
          costMethod: 'fifo' as const,
          totalCash: 0,
          totalMarketValue: 100,
          totalEquity: 100,
          realizedPnl: 0,
          unrealizedPnl: 0,
          feeTotal: 0,
          taxTotal: 0,
          fxStale: false,
          dataQuality: 'ok',
          limitations: [],
          positions: [
            makePosition({
              symbol: 'AAPL',
              market: 'us',
              currency: 'USD',
              valuationCurrency: 'USD',
              marketValueBase: 100,
            }),
          ],
        },
      ],
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);
    expect(dashboardScope.getAllByText('暂无暴露数据')).toHaveLength(2);
  });

  it('hides exposure breakdowns when positions mix valuation currencies under one aggregate snapshot', async () => {
    getSnapshot.mockResolvedValueOnce({
      asOf: '2026-03-19',
      costMethod: 'fifo' as const,
      currency: 'CNY',
      accountCount: 1,
      totalCash: 0,
      totalMarketValue: 1040,
      totalEquity: 1040,
      realizedPnl: 0,
      unrealizedPnl: 0,
      feeTotal: 0,
      taxTotal: 0,
      fxStale: false,
      dataQuality: 'ok',
      limitations: [],
      accounts: [
        {
          accountId: 1,
          accountName: 'Mixed FX Account',
          ownerId: null,
          broker: 'Demo',
          market: 'us',
          baseCurrency: 'USD',
          asOf: '2026-03-19',
          costMethod: 'fifo' as const,
          totalCash: 0,
          totalMarketValue: 300,
          totalEquity: 300,
          realizedPnl: 0,
          unrealizedPnl: 0,
          feeTotal: 0,
          taxTotal: 0,
          fxStale: false,
          dataQuality: 'ok',
          limitations: [],
          positions: [
            makePosition({
              symbol: 'AAPL',
              market: 'us',
              currency: 'USD',
              valuationCurrency: 'USD',
              marketValueBase: 100,
            }),
            makePosition({
              symbol: 'HK00700',
              market: 'hk',
              currency: 'HKD',
              valuationCurrency: 'HKD',
              marketValueBase: 200,
            }),
          ],
        },
      ],
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);
    expect(dashboardScope.getAllByText('暂无暴露数据')).toHaveLength(2);
  });

  it('renders every market exposure group instead of silently dropping the remainder', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [
        makePosition({ symbol: '600519', market: 'cn', marketValueBase: 100 }),
        makePosition({ symbol: 'HK00700', market: 'hk', marketValueBase: 100 }),
        makePosition({ symbol: 'AAPL', market: 'us', marketValueBase: 100 }),
        makePosition({ symbol: '7203.T', market: 'jp', marketValueBase: 100 }),
        makePosition({ symbol: '005930.KS', market: 'kr', marketValueBase: 100 }),
        makePosition({ symbol: '2330.TW', market: 'tw', marketValueBase: 100 }),
      ],
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const marketExposure = screen.getByText('市场暴露').closest('div.rounded-xl');
    expect(marketExposure).not.toBeNull();
    const exposureScope = within(marketExposure as HTMLElement);
    for (const market of ['CN', 'HK', 'US', 'JP', 'KR', 'TW']) {
      expect(exposureScope.getByText(market)).toBeInTheDocument();
    }
  });

  it('hides exposure amounts and weights when aggregate FX uses stale fallback values', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: true,
      positions: [
        makePosition({
          symbol: 'AAPL',
          market: 'us',
          currency: 'USD',
          valuationCurrency: 'USD',
          marketValueBase: 100,
        }),
      ],
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);
    expect(dashboardScope.getAllByText('暂无暴露数据')).toHaveLength(2);
    expect(dashboardScope.queryByText('CNY 100.00')).not.toBeInTheDocument();
    expect(dashboardScope.queryByText('100.00%')).not.toBeInTheDocument();
  });

  it('marks server-derived risk flags unavailable when risk loading fails', async () => {
    getRisk.mockRejectedValueOnce(
      createApiError(
        createParsedApiError({
          title: '风险失败',
          message: '风险接口暂不可用',
        }),
      ),
    );

    render(<PortfolioPage />);

    await waitForInitialLoad();

    expect(await screen.findByText('风险模块降级')).toBeInTheDocument();
    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);
    expect(dashboardScope.getAllByText('不可用').length).toBeGreaterThanOrEqual(5);

    const concentrationCard = screen.getByText('行业数据暂不可用，当前展示个股集中度').closest('div.rounded-2xl');
    expect(concentrationCard).not.toBeNull();
    const concentrationScope = within(concentrationCard as HTMLElement);
    expect(concentrationScope.getByText('板块集中度告警: 不可用')).toBeInTheDocument();
    expect(concentrationScope.getByText('Top1 权重: --')).toBeInTheDocument();

    const drawdownCard = screen.getByText('回撤监控').closest('div.rounded-2xl');
    expect(drawdownCard).not.toBeNull();
    const drawdownScope = within(drawdownCard as HTMLElement);
    expect(drawdownScope.getByText('最大回撤: --')).toBeInTheDocument();
    expect(drawdownScope.getByText('当前回撤: --')).toBeInTheDocument();
    expect(drawdownScope.getByText('告警: 不可用')).toBeInTheDocument();

    const stopLossCard = screen.getByText('止损接近预警').closest('div.rounded-2xl');
    expect(stopLossCard).not.toBeNull();
    const stopLossScope = within(stopLossCard as HTMLElement);
    expect(stopLossScope.getByText('触发数: --')).toBeInTheDocument();
    expect(stopLossScope.getByText('接近数: --')).toBeInTheDocument();
    expect(stopLossScope.getByText('告警: 不可用')).toBeInTheDocument();

    const aiRiskCard = screen.getByText('AI 风险信号').closest('div.rounded-2xl');
    expect(aiRiskCard).not.toBeNull();
    expect(within(aiRiskCard as HTMLElement).getByText('信号风险暂不可用')).toBeInTheDocument();
  });

  it('treats empty server risk blocks as unavailable instead of normal', async () => {
    getRisk.mockResolvedValueOnce({
      ...makeRisk(),
      concentration: {},
      sectorConcentration: {},
      drawdown: {},
      stopLoss: {},
      decisionSignalRisk: {} as never,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(dashboard).not.toBeNull();
    const dashboardScope = within(dashboard as HTMLElement);
    expect(dashboardScope.getAllByText('不可用').length).toBeGreaterThanOrEqual(5);
    expect(dashboardScope.getAllByText('--').length).toBeGreaterThanOrEqual(5);
  });

  it('treats zero-point drawdown as unavailable even when numeric fields are zero', async () => {
    getRisk.mockResolvedValueOnce(makeRisk({
      drawdown: {
        seriesPoints: 0,
        maxDrawdownPct: 0,
        currentDrawdownPct: 0,
        alert: false,
        fxStale: false,
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const drawdownFlag = screen.getByText('回撤').closest('div.rounded-xl');
    expect(drawdownFlag).not.toBeNull();
    expect(within(drawdownFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(within(drawdownFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
  });

  it('treats one-point drawdown as unavailable because no decline can be measured', async () => {
    getRisk.mockResolvedValueOnce(makeRisk({
      drawdown: {
        seriesPoints: 1,
        maxDrawdownPct: 0,
        currentDrawdownPct: 0,
        alert: false,
        fxStale: false,
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const drawdownFlag = screen.getByText('回撤').closest('div.rounded-xl');
    expect(drawdownFlag).not.toBeNull();
    expect(within(drawdownFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(within(drawdownFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
  });

  it('treats stale-FX drawdown as unavailable instead of normal', async () => {
    getRisk.mockResolvedValueOnce(makeRisk({
      drawdown: {
        seriesPoints: 10,
        maxDrawdownPct: 0,
        currentDrawdownPct: 0,
        alert: false,
        fxStale: true,
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const drawdownFlag = screen.getByText('回撤').closest('div.rounded-xl');
    expect(drawdownFlag).not.toBeNull();
    expect(within(drawdownFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(within(drawdownFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
  });

  it('treats stale-FX concentration summaries as unavailable instead of authoritative', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: true }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        alert: true,
        topPositions: [{ symbol: '600519', marketValueBase: 6000, weightPct: 60, isAlert: true }],
      },
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: true,
        topSectors: [{ sector: '白酒', marketValueBase: 7000, weightPct: 70, symbolCount: 2, isAlert: true }],
        coverage: { unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    for (const label of ['个股集中', '行业集中']) {
      const flag = screen.getByText(label).closest('div.rounded-xl');
      expect(flag).not.toBeNull();
      expect(within(flag as HTMLElement).getByText('--')).toBeInTheDocument();
      expect(within(flag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    }
    expect(screen.queryByText('Top1: 白酒')).not.toBeInTheDocument();
    expect(screen.queryByText('60.00%')).not.toBeInTheDocument();
  });

  it('hides concentration and exposure conclusions when any holding lacks a price', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [
        makePosition({
          symbol: '600519',
          market: 'cn',
          currency: 'CNY',
          valuationCurrency: 'CNY',
          marketValueBase: 6000,
          priceAvailable: true,
        }),
        makePosition({
          symbol: 'AAPL',
          market: 'us',
          currency: 'USD',
          valuationCurrency: 'CNY',
          lastPrice: 0,
          marketValueBase: 0,
          priceSource: 'missing',
          priceDate: null,
          priceStale: true,
          priceAvailable: false,
        }),
      ],
    }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 6000,
        topWeightPct: 100,
        alert: true,
        topPositions: [{ symbol: '600519', marketValueBase: 6000, weightPct: 100, isAlert: true }],
      },
      sectorConcentration: {
        totalMarketValue: 6000,
        topWeightPct: 100,
        alert: true,
        topSectors: [{ sector: '白酒', marketValueBase: 6000, weightPct: 100, symbolCount: 1, isAlert: true }],
        coverage: { unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    for (const label of ['个股集中', '行业集中']) {
      const flag = screen.getByText(label).closest('div.rounded-xl');
      expect(flag).not.toBeNull();
      expect(within(flag as HTMLElement).getByText('--')).toBeInTheDocument();
      expect(within(flag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    }
    expect(screen.getAllByText('暂无暴露数据')).toHaveLength(2);
    expect(screen.queryByText('US')).not.toBeInTheDocument();
    expect(screen.queryByText('100.00%')).not.toBeInTheDocument();
  });

  it('uses nested account FX quality when the aggregate flag is incorrectly fresh', async () => {
    const snapshot = makeSnapshot({
      fxStale: false,
      positions: [makePosition({ marketValueBase: 6000 })],
    });
    snapshot.accounts[0].fxStale = true;
    getSnapshot.mockResolvedValueOnce(snapshot);
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 6000,
        topWeightPct: 100,
        alert: true,
        topPositions: [{ symbol: '600519', marketValueBase: 6000, weightPct: 100, isAlert: true }],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const concentrationFlag = screen.getByText('个股集中').closest('div.rounded-xl');
    expect(concentrationFlag).not.toBeNull();
    expect(within(concentrationFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(within(concentrationFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    expect(screen.getAllByText('暂无暴露数据')).toHaveLength(2);
  });

  it('marks price quality unavailable when the portfolio snapshot fails', async () => {
    getSnapshot.mockRejectedValueOnce(new Error('snapshot unavailable'));

    render(<PortfolioPage />);

    await screen.findByText('snapshot unavailable');
    const priceFlag = (await screen.findByText('价格质量')).closest('div.rounded-xl');
    expect(priceFlag).not.toBeNull();
    expect(within(priceFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(within(priceFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
  });

  it('treats partial server risk blocks as unavailable instead of normal', async () => {
    getRisk.mockResolvedValueOnce({
      ...makeRisk(),
      concentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        topPositions: [{ symbol: '600519', marketValueBase: 6000, weightPct: 60, isAlert: true }],
      } as never,
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        topSectors: [{ sector: '白酒', marketValueBase: 7000, weightPct: 70, symbolCount: 2, isAlert: true }],
        coverage: { unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      } as never,
      drawdown: {
        seriesPoints: 10,
        maxDrawdownPct: 18.5,
        currentDrawdownPct: 12.5,
        fxStale: false,
      } as never,
      stopLoss: {
        triggeredCount: 1,
        nearCount: 2,
        items: [],
      } as never,
      decisionSignalRisk: {
        total: 1,
        actions: { sell: 0, reduce: 1, alert: 0 },
        items: [],
      } as never,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    for (const label of ['个股集中', '行业集中', '回撤', '止损', 'AI 信号']) {
      const card = screen.getByText(label).closest('div.rounded-xl');
      expect(card).not.toBeNull();
      const cardScope = within(card as HTMLElement);
      expect(cardScope.getAllByText('不可用').length).toBeGreaterThanOrEqual(1);
      expect(cardScope.getByText('--')).toBeInTheDocument();
    }

    const concentrationCard = screen.getByText('行业数据暂不可用，当前展示个股集中度').closest('div.rounded-2xl');
    expect(concentrationCard).not.toBeNull();
    const concentrationScope = within(concentrationCard as HTMLElement);
    expect(concentrationScope.getByText('板块集中度告警: 不可用')).toBeInTheDocument();
    expect(concentrationScope.getByText('Top1 权重: --')).toBeInTheDocument();
    expect(concentrationScope.queryByText('600519')).not.toBeInTheDocument();

    const drawdownCard = screen.getByText('回撤监控').closest('div.rounded-2xl');
    expect(drawdownCard).not.toBeNull();
    const drawdownScope = within(drawdownCard as HTMLElement);
    expect(drawdownScope.getByText('最大回撤: --')).toBeInTheDocument();
    expect(drawdownScope.getByText('当前回撤: --')).toBeInTheDocument();
    expect(drawdownScope.getByText('告警: 不可用')).toBeInTheDocument();

    const stopLossCard = screen.getByText('止损接近预警').closest('div.rounded-2xl');
    expect(stopLossCard).not.toBeNull();
    const stopLossScope = within(stopLossCard as HTMLElement);
    expect(stopLossScope.getByText('触发数: --')).toBeInTheDocument();
    expect(stopLossScope.getByText('接近数: --')).toBeInTheDocument();
    expect(stopLossScope.getByText('告警: 不可用')).toBeInTheDocument();

    const aiRiskCard = screen.getByText('AI 风险信号').closest('div.rounded-2xl');
    expect(aiRiskCard).not.toBeNull();
    expect(within(aiRiskCard as HTMLElement).getByText('信号风险暂不可用')).toBeInTheDocument();
  });

  it('treats an all-UNCLASSIFIED sector result as unavailable and falls back to positions', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        alert: true,
        topPositions: [{ symbol: 'AAPL', marketValueBase: 6000, weightPct: 60, isAlert: true }],
      },
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 100,
        alert: true,
        topSectors: [{
          sector: 'UNCLASSIFIED',
          marketValueBase: 10000,
          weightPct: 100,
          symbolCount: 2,
          isAlert: true,
        }],
        coverage: { classifiedCount: 0, unclassifiedCount: 2 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    expect(within(sectorFlag as HTMLElement).getByText('--')).toBeInTheDocument();

    const concentrationCard = screen.getByText('行业数据暂不可用，当前展示个股集中度').closest('div.rounded-2xl');
    expect(concentrationCard).not.toBeNull();
    const concentrationScope = within(concentrationCard as HTMLElement);
    expect(concentrationScope.getByText('板块集中度告警: 不可用')).toBeInTheDocument();
    expect(concentrationScope.getByText('Top1 权重: 60.00%')).toBeInTheDocument();
    expect(screen.queryByText('UNCLASSIFIED')).not.toBeInTheDocument();
  });

  it('treats partially covered sector risk as unavailable instead of presenting a subset as complete', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        alert: true,
        topSectors: [
          {
            sector: 'UNCLASSIFIED',
            marketValueBase: 6000,
            weightPct: 60,
            symbolCount: 2,
            isAlert: true,
          },
          {
            sector: 'Technology',
            marketValueBase: 4000,
            weightPct: 40,
            symbolCount: 1,
            isAlert: false,
          },
        ],
        coverage: { classifiedCount: 1, unclassifiedCount: 2 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    expect(screen.queryByText('Top1: Technology')).not.toBeInTheDocument();
    expect(screen.queryByText('40.00%')).not.toBeInTheDocument();
    const concentrationCard = screen.getByText('行业数据暂不可用，当前展示个股集中度').closest('div.rounded-2xl');
    expect(concentrationCard).not.toBeNull();
    const concentrationScope = within(concentrationCard as HTMLElement);
    expect(concentrationScope.getByText('板块集中度告警: 不可用')).toBeInTheDocument();
    expect(concentrationScope.getByText('Top1 权重: --')).toBeInTheDocument();
    expect(screen.queryByText('UNCLASSIFIED')).not.toBeInTheDocument();
  });

  it('requires explicit sector coverage counters before declaring sector risk available', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: false,
        topSectors: [{ sector: '白酒', marketValueBase: 7000, weightPct: 70, symbolCount: 2, isAlert: false }],
        coverage: {},
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(within(sectorFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    expect(screen.queryByText('Top1: 白酒')).not.toBeInTheDocument();
  });

  it('requires an explicit sector error array before declaring sector risk available', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: false,
        topSectors: [{ sector: '白酒', marketValueBase: 7000, weightPct: 70, symbolCount: 2, isAlert: false }],
        coverage: { unclassifiedCount: 0, failedCount: 0 },
      } as never,
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(screen.queryByText('Top1: 白酒')).not.toBeInTheDocument();
  });

  it('rejects numeric-string sector weights without crashing the page', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: false,
        topSectors: [{
          sector: '白酒',
          marketValueBase: 7000,
          weightPct: '70',
          symbolCount: 2,
          isAlert: false,
        } as never],
        coverage: { unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(screen.getByText('行业数据暂不可用，当前展示个股集中度')).toBeInTheDocument();
  });

  it('treats malformed sector rows as unavailable instead of crashing the page', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: true,
        topSectors: [{
          sector: null,
          marketValueBase: 7000,
          weightPct: 70,
          symbolCount: 2,
          isAlert: true,
        } as never],
        coverage: { unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(screen.getByText('行业数据暂不可用，当前展示个股集中度')).toBeInTheDocument();
  });

  it('treats a malformed sector row collection as unavailable', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: true,
        topSectors: { sector: 'Technology', weightPct: 70 } as never,
        coverage: { unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(screen.getByText('行业数据暂不可用，当前展示个股集中度')).toBeInTheDocument();
  });

  it('requires a valid top-position row before showing concentration status', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        alert: true,
        topPositions: { symbol: '600519', weightPct: 60 } as never,
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const concentrationFlag = screen.getByText('个股集中').closest('div.rounded-xl');
    expect(concentrationFlag).not.toBeNull();
    expect(within(concentrationFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(within(concentrationFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
  });

  it('marks stop-loss risk unavailable when any holding lacks a usable quote', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [makePosition({
        lastPrice: 0,
        priceAvailable: false,
        priceStale: true,
      })],
    }));
    getRisk.mockResolvedValueOnce(makeRisk({
      stopLoss: {
        nearAlert: true,
        triggeredCount: 1,
        nearCount: 0,
        items: [{ symbol: '600519' }],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const stopLossFlag = screen.getByText('止损').closest('div.rounded-xl');
    expect(stopLossFlag).not.toBeNull();
    expect(within(stopLossFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(within(stopLossFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    const stopLossCard = screen.getByText('止损接近预警').closest('div.rounded-2xl');
    expect(stopLossCard).not.toBeNull();
    expect(within(stopLossCard as HTMLElement).getByText('告警: 不可用')).toBeInTheDocument();
  });

  it('uses the validated sector block alert when a top row disagrees', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 70,
        alert: true,
        topSectors: [{ sector: '白酒', marketValueBase: 7000, weightPct: 70, symbolCount: 2, isAlert: false }],
        coverage: { unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(sectorFlag).not.toBeNull();
    expect(within(sectorFlag as HTMLElement).getByText('需处理')).toBeInTheDocument();
    expect(within(sectorFlag as HTMLElement).getByText('70.00%')).toBeInTheDocument();
    expect(screen.getByText('板块集中度告警: 是')).toBeInTheDocument();
  });

  it('counts missing and stale price-quality positions without double counting missing quotes', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      positions: [
        makePosition({
          symbol: 'HK00700',
          market: 'hk',
          currency: 'HKD',
          valuationCurrency: 'CNY',
          marketValueBase: 4200,
          priceStale: true,
          priceAvailable: true,
        }),
        makePosition({
          symbol: 'AAPL',
          market: 'us',
          currency: 'USD',
          valuationCurrency: 'CNY',
          marketValueBase: 0,
          lastPrice: 0,
          priceSource: 'missing',
          priceDate: null,
          priceStale: true,
          priceAvailable: false,
        }),
      ],
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const card = screen.getByText('价格质量').closest('div.rounded-xl');
    expect(card).not.toBeNull();
    const cardScope = within(card as HTMLElement);
    expect(cardScope.getByText('2')).toBeInTheDocument();
    expect(cardScope.getByText('缺价: 1 · 过期价: 1')).toBeInTheDocument();
  });

  it('counts a missing quote once when it is also marked stale', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      positions: [
        makePosition({
          symbol: 'AAPL',
          market: 'us',
          currency: 'USD',
          valuationCurrency: 'USD',
          marketValueBase: 0,
          lastPrice: 0,
          priceSource: 'missing',
          priceDate: null,
          priceStale: true,
          priceAvailable: false,
        }),
      ],
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const card = screen.getByText('价格质量').closest('div.rounded-xl');
    expect(card).not.toBeNull();
    const cardScope = within(card as HTMLElement);
    expect(cardScope.getByText('1')).toBeInTheDocument();
    expect(cardScope.getByText('缺价: 1 · 过期价: 0')).toBeInTheDocument();
  });

  it('shows aggregate partial valuation limitations near summary totals', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      dataQuality: 'partial',
      limitations: ['realtime_quote_best_effort', 'fx_and_cost_basis_partial'],
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    expect(await screen.findByText('组合估值限制')).toBeInTheDocument();
    expect(screen.getByText(/实时行情为尽力获取/)).toBeInTheDocument();
    expect(screen.getByText(/汇率与成本基础为部分口径/)).toBeInTheDocument();
  });

  it('renders portfolio risk drawdown labels in English UI mode', async () => {
    renderEnglishPage();

    await waitForInitialLoad();

    expect(await screen.findByText('Portfolio management')).toBeInTheDocument();
    expect(screen.getByText('Drawdown monitor')).toBeInTheDocument();
    expect(screen.getAllByText(/Max drawdown:/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Current drawdown:/).length).toBeGreaterThan(0);
    expect(screen.getByText('Stop-loss proximity warning')).toBeInTheDocument();
    expect(screen.getByText('Scope')).toBeInTheDocument();
    expect(screen.getByText('AI risk signals')).toBeInTheDocument();
    expect(screen.getByText('No defensive signals')).toBeInTheDocument();
    expect(screen.queryByText('回撤监控')).not.toBeInTheDocument();
  });

  it('renders portfolio decision signal risk summary', async () => {
    getRisk.mockResolvedValueOnce(makeRisk({
      decisionSignalRisk: {
        available: true,
        total: 2,
        actions: { sell: 1, reduce: 0, alert: 1 },
        items: [
          {
            accountId: 1,
            symbol: '600519',
            market: 'cn',
            signal: makeDecisionSignal({ id: 201, action: 'sell', actionLabel: null }),
          },
          {
            accountId: 1,
            symbol: '300750',
            market: 'cn',
            signal: makeDecisionSignal({ id: 202, stockCode: '300750', action: 'alert', actionLabel: null }),
          },
        ],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    expect(screen.getByText('AI 风险信号')).toBeInTheDocument();
    expect(screen.getByText(/风险信号: 2/)).toBeInTheDocument();
    expect(screen.getByText(/卖出: 1 · 减仓: 0 · 预警: 1/)).toBeInTheDocument();
    expect(screen.getByText('600519 · 卖出')).toBeInTheDocument();
    expect(screen.getByText('300750 · 预警')).toBeInTheDocument();
    expect(screen.queryByText('600519 · sell')).not.toBeInTheDocument();
    expect(screen.queryByText('300750 · alert')).not.toBeInTheDocument();
  });

  it('uses the current UI language for portfolio decision signal risk action labels', async () => {
    getRisk.mockResolvedValueOnce(makeRisk({
      decisionSignalRisk: {
        available: true,
        total: 1,
        actions: { sell: 1, reduce: 0, alert: 0 },
        items: [
          {
            accountId: 1,
            symbol: '600519',
            market: 'cn',
            signal: makeDecisionSignal({ id: 203, action: 'sell', actionLabel: '卖出' }),
          },
        ],
      },
    }));

    renderEnglishPage();

    await waitForInitialLoad();

    expect(screen.getByText('AI risk signals')).toBeInTheDocument();
    expect(screen.getByText('600519 · Sell')).toBeInTheDocument();
    expect(screen.queryByText('600519 · 卖出')).not.toBeInTheDocument();
    expect(screen.queryByText('600519 · sell')).not.toBeInTheDocument();
  });

  it('renders portfolio decision signal risk fail-open state', async () => {
    getRisk.mockResolvedValueOnce(makeRisk({
      decisionSignalRisk: {
        available: false,
        total: 0,
        actions: { sell: 0, reduce: 0, alert: 0 },
        items: [],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    expect(screen.getByText('信号风险暂不可用')).toBeInTheDocument();
  });

  it('refreshes FX for a single selected account and only reloads snapshot/risk', async () => {
    getSnapshot
      .mockResolvedValueOnce(makeSnapshot({ fxStale: true }))
      .mockResolvedValueOnce(makeSnapshot({ accountId: 1, fxStale: true }))
      .mockResolvedValueOnce(makeSnapshot({ accountId: 1, fxStale: false }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });

    await waitFor(() => {
      expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: 1, costMethod: 'fifo', includeRealtime: false });
    });

    const snapshotCallsBeforeRefresh = getSnapshot.mock.calls.length;
    const riskCallsBeforeRefresh = getRisk.mock.calls.length;
    const tradeCallsBeforeRefresh = listTrades.mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    await waitFor(() => expect(refreshFx).toHaveBeenCalledWith({ accountId: 1 }));
    expect(await screen.findByText('汇率已刷新，共更新 1 对。')).toBeInTheDocument();
    await waitFor(() => expect(getSnapshot).toHaveBeenCalledTimes(snapshotCallsBeforeRefresh + 1));
    await waitFor(() => expect(getRisk).toHaveBeenCalledTimes(riskCallsBeforeRefresh + 1));
    expect(listTrades).toHaveBeenCalledTimes(tradeCallsBeforeRefresh);
    expect(listCashLedger).not.toHaveBeenCalled();
    expect(listCorporateActions).not.toHaveBeenCalled();
    expect(screen.getByText('最新')).toBeInTheDocument();
  });

  it('refreshes FX for the full portfolio without sending accountId and shows neutral feedback when no pair exists', async () => {
    refreshFx.mockResolvedValueOnce({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: true,
      disabledReason: null,
      pairCount: 0,
      updatedCount: 0,
      staleCount: 0,
      errorCount: 0,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    await waitFor(() => expect(refreshFx).toHaveBeenCalledWith({ accountId: undefined }));
    expect(await screen.findByText('当前范围无可刷新的汇率对。')).toBeInTheDocument();
  });

  it('shows disabled feedback when FX online refresh is disabled even without a disabled reason', async () => {
    refreshFx.mockResolvedValueOnce({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: false,
      pairCount: 1,
      updatedCount: 0,
      staleCount: 0,
      errorCount: 0,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    expect(await screen.findByText('汇率在线刷新已被禁用。')).toBeInTheDocument();
  });

  it('renders backend-provided position valuation fields and stale missing-price hint', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: true, positions: [
      { symbol: 'HK00700', market: 'hk', currency: 'HKD', quantity: 10, avgCost: 400, totalCost: 4000, lastPrice: 420, marketValueBase: 4200, unrealizedPnlBase: 200, unrealizedPnlPct: 5, valuationCurrency: 'HKD', priceSource: 'history_close', priceDate: '2026-03-18', priceStale: true, priceAvailable: true },
      { symbol: 'AAPL', market: 'us', currency: 'USD', quantity: 5, avgCost: 100, totalCost: 500, lastPrice: 0, marketValueBase: 0, unrealizedPnlBase: 0, unrealizedPnlPct: null, valuationCurrency: 'USD', priceSource: 'missing', priceDate: null, priceStale: true, priceAvailable: false },
    ] }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    expect(await screen.findByText('HK00700')).toBeInTheDocument();
    expect(screen.getByText('420.0000')).toBeInTheDocument();
    expect(screen.getByText('HKD 4,200.00')).toBeInTheDocument();
    expect(screen.getByText('+5.00%')).toBeInTheDocument();
    expect(screen.getByText('收盘价 · 2026-03-18')).toBeInTheDocument();
    expect(screen.getByText('缺价')).toBeInTheDocument();
    expect(screen.getAllByText('--').length).toBeGreaterThanOrEqual(2);

    const hkRow = screen.getByText('HK00700').closest('tr');
    const aaplRow = screen.getByText('AAPL').closest('tr');
    expect(hkRow).not.toBeNull();
    expect(aaplRow).not.toBeNull();

    const hkRowCells = within(hkRow as HTMLTableRowElement).getAllByRole('cell');
    const aaplRowCells = within(aaplRow as HTMLTableRowElement).getAllByRole('cell');
    expect(hkRowCells.at(-3)).toHaveClass('text-success');
    expect(aaplRowCells.at(-3)).toHaveClass('text-secondary');
  });

  it('loads latest active signals for holdings without scanning paginated signal lists', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ positions: [
      { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
    ] }));
    const latestSignal = makeDecisionSignal({
      id: 101,
      stockCode: '600519',
      riskSummary: '分页后的风险摘要',
      watchConditions: '分页后的观察条件',
    });
    getLatestDecisionSignals.mockResolvedValueOnce({ items: [latestSignal], total: 1, page: 1, pageSize: 1 });

    render(<PortfolioPage />);

    expect(await screen.findByText('600519')).toBeInTheDocument();
    expect(await screen.findByText('分页后的风险摘要')).toBeInTheDocument();
    expect(decisionSignalsApi.getLatest).toHaveBeenCalledWith('600519', {
      market: 'cn',
      limit: 1,
    });
    expect(decisionSignalsApi.list).not.toHaveBeenCalled();
  });

  it('refreshes holding signals when manually refreshing unchanged portfolio data', async () => {
    const position = { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true };
    getSnapshot.mockResolvedValue(makeSnapshot({ positions: [position] }));
    getLatestDecisionSignals
      .mockResolvedValueOnce({
        items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '旧 AI 风险' })],
        total: 1,
        page: 1,
        pageSize: 1,
      })
      .mockResolvedValueOnce({
        items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '新 AI 风险' })],
        total: 1,
        page: 1,
        pageSize: 1,
      });

    render(<PortfolioPage />);

    expect(await screen.findByText('旧 AI 风险')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新数据' }));

    expect(await screen.findByText('新 AI 风险')).toBeInTheDocument();
    await waitFor(() => expect(getLatestDecisionSignals).toHaveBeenCalledTimes(2));
    expect(screen.queryByText('旧 AI 风险')).not.toBeInTheDocument();
  });

  it('waits for the selected-account snapshot before loading account-scoped holding signals', async () => {
    getAccounts.mockResolvedValueOnce(makeAccounts([
      { id: 1, name: 'Main' },
      { id: 2, name: 'Alt' },
    ]));
    const accountTwoSnapshot = deferredPromise<ReturnType<typeof makeSnapshot>>();
    getSnapshot
      .mockResolvedValueOnce(makeSnapshot({
        accountCount: 2,
        positions: [
          { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
        ],
      }))
      .mockReturnValueOnce(accountTwoSnapshot.promise);
    getLatestDecisionSignals.mockResolvedValue({
      items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '账号信号' })],
      total: 1,
      page: 1,
      pageSize: 1,
    });

    render(<PortfolioPage />);

    expect(await screen.findByText('账号信号')).toBeInTheDocument();
    const signalCallsBeforeSwitch = getLatestDecisionSignals.mock.calls.length;

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '2' } });

    await waitFor(() => {
      expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: 2, costMethod: 'fifo', includeRealtime: false });
    });
    expect(screen.queryByText('账号信号')).not.toBeInTheDocument();
    expect(getLatestDecisionSignals).toHaveBeenCalledTimes(signalCallsBeforeSwitch);

    await act(async () => {
      accountTwoSnapshot.resolve(makeSnapshot({
        accountId: 2,
        positions: [
          { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
        ],
      }));
      await accountTwoSnapshot.promise;
    });

    await waitFor(() => {
      expect(getLatestDecisionSignals).toHaveBeenLastCalledWith('600519', {
        market: 'cn',
        limit: 1,
      });
    });
  });

  it('drops late holding-signal responses after switching account scope', async () => {
    getAccounts.mockResolvedValueOnce(makeAccounts([
      { id: 1, name: 'Main' },
      { id: 2, name: 'Alt' },
    ]));
    getSnapshot
      .mockResolvedValueOnce(makeSnapshot({
        accountCount: 2,
        positions: [
          { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
        ],
      }))
      .mockResolvedValueOnce(makeSnapshot({
        accountId: 2,
        positions: [
          { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
        ],
      }));
    const oldSignals = deferredPromise<{
      items: DecisionSignalItem[];
      total: number;
      page: number;
      pageSize: number;
    }>();
    getLatestDecisionSignals
      .mockReturnValueOnce(oldSignals.promise)
      .mockResolvedValueOnce({
        items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '新账号信号' })],
        total: 1,
        page: 1,
        pageSize: 1,
      });

    render(<PortfolioPage />);

    expect(await screen.findByText('600519')).toBeInTheDocument();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '2' } });

    expect(await screen.findByText('新账号信号')).toBeInTheDocument();

    await act(async () => {
      oldSignals.resolve({
        items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '旧账号晚返回信号' })],
        total: 1,
        page: 1,
        pageSize: 1,
      });
      await oldSignals.promise;
    });

    expect(screen.getByText('新账号信号')).toBeInTheDocument();
    expect(screen.queryByText('旧账号晚返回信号')).not.toBeInTheDocument();
  });

  it('matches holding signals by stock-code equivalence and leaves unmatched rows empty', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ positions: [
      { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
      { symbol: 'SH600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
      { symbol: '00700.HK', market: 'hk', currency: 'HKD', quantity: 10, avgCost: 400, totalCost: 4000, lastPrice: 420, marketValueBase: 4200, unrealizedPnlBase: 200, unrealizedPnlPct: 5, valuationCurrency: 'HKD', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
      { symbol: 'AAPL', market: 'us', currency: 'USD', quantity: 2, avgCost: 180, totalCost: 360, lastPrice: 190, marketValueBase: 380, unrealizedPnlBase: 20, unrealizedPnlPct: 5.56, valuationCurrency: 'USD', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
    ] }));
    getLatestDecisionSignals.mockImplementation(async (stockCode: string) => {
      if (stockCode.includes('600519')) {
        return {
          items: [makeDecisionSignal({ id: 1, stockCode: '600519', market: 'cn', riskSummary: 'A 股风险' })],
          total: 1,
          page: 1,
          pageSize: 1,
        };
      }
      if (stockCode.includes('00700')) {
        return {
          items: [makeDecisionSignal({ id: 2, stockCode: 'HK00700', market: 'hk', riskSummary: '港股风险', watchConditions: '观察回购' })],
          total: 1,
          page: 1,
          pageSize: 1,
        };
      }
      return { items: [], total: 0, page: 1, pageSize: 1 };
    });

    render(<PortfolioPage />);

    expect(await screen.findAllByText('A 股风险')).toHaveLength(2);
    expect(screen.getByText('港股风险')).toBeInTheDocument();
    const latestLookupSymbols = getLatestDecisionSignals.mock.calls.map(([stockCode]) => String(stockCode));
    expect(latestLookupSymbols.filter((stockCode) => stockCode.includes('600519'))).toEqual(['600519']);
    expect(getLatestDecisionSignals).toHaveBeenCalledTimes(3);
    expect(getLatestDecisionSignals).toHaveBeenCalledWith('00700.HK', {
      market: 'hk',
      limit: 1,
    });
    const aaplRow = screen.getByText('AAPL').closest('tr');
    expect(aaplRow).not.toBeNull();
    expect(within(aaplRow as HTMLTableRowElement).getByText('—')).toBeInTheDocument();
  });

  it('shows a visible partial warning when one latest holding signal lookup fails', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ positions: [
      { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
      { symbol: 'AAPL', market: 'us', currency: 'USD', quantity: 2, avgCost: 180, totalCost: 360, lastPrice: 190, marketValueBase: 380, unrealizedPnlBase: 20, unrealizedPnlPct: 5.56, valuationCurrency: 'USD', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
    ] }));
    getLatestDecisionSignals
      .mockResolvedValueOnce({
        items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '已加载风险' })],
        total: 1,
        page: 1,
        pageSize: 1,
      })
      .mockRejectedValueOnce(new Error('latest AAPL failed'));

    render(<PortfolioPage />);

    expect(await screen.findByText('已加载风险')).toBeInTheDocument();
    expect(await screen.findByText('AI 建议降级')).toBeInTheDocument();
    expect(screen.getByText(/latest AAPL failed/)).toBeInTheDocument();
  });

  it('loads each unique holding through the latest endpoint once', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ positions: [
      { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 1, avgCost: 1500, totalCost: 1500, lastPrice: 1600, marketValueBase: 1600, unrealizedPnlBase: 100, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
      { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 2, avgCost: 1500, totalCost: 3000, lastPrice: 1600, marketValueBase: 3200, unrealizedPnlBase: 200, unrealizedPnlPct: 6.67, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-06-17', priceStale: false, priceAvailable: true },
    ] }));
    getLatestDecisionSignals.mockResolvedValueOnce({
      items: [makeDecisionSignal({ stockCode: '600519', riskSummary: '唯一 latest 风险' })],
      total: 1,
      page: 1,
      pageSize: 1,
    });

    render(<PortfolioPage />);

    expect(await screen.findAllByText('唯一 latest 风险')).toHaveLength(2);
    expect(getLatestDecisionSignals).toHaveBeenCalledTimes(1);
    expect(decisionSignalsApi.list).not.toHaveBeenCalled();
  });

  it('limits concurrent latest lookups for large portfolios', async () => {
    const positions = Array.from({ length: 10 }, (_, index) => makePosition({
      symbol: `AAPL${index}`,
      market: 'us',
      currency: 'USD',
      totalCost: 100 + index,
      marketValueBase: 120 + index,
    }));
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ positions }));
    let inFlight = 0;
    let maxInFlight = 0;
    getLatestDecisionSignals.mockImplementation(async () => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 5));
      inFlight -= 1;
      return { items: [], total: 0, page: 1, pageSize: 1 };
    });

    render(<PortfolioPage />);

    expect(await screen.findByText('AAPL0')).toBeInTheDocument();
    await waitFor(() => expect(getLatestDecisionSignals).toHaveBeenCalledTimes(10));
    await waitFor(() => expect(inFlight).toBe(0));
    expect(maxInFlight).toBeLessThanOrEqual(6);
  });

  it('submits manual analysis for a held position without exposing portfolio details in the UI call', async () => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: true, positions: [
      { symbol: 'HK00700', market: 'hk', currency: 'HKD', quantity: 10, avgCost: 400, totalCost: 4000, lastPrice: 420, marketValueBase: 4200, unrealizedPnlBase: 200, unrealizedPnlPct: 5, valuationCurrency: 'HKD', priceSource: 'history_close', priceDate: '2026-03-18', priceStale: true, priceAvailable: true },
    ] }));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const row = screen.getByText('HK00700').closest('tr');
    expect(row).not.toBeNull();
    fireEvent.click(within(row as HTMLTableRowElement).getByRole('button', { name: '分析' }));

    await waitFor(() => {
      expect(analyzePosition).toHaveBeenCalledWith('HK00700', {
        accountId: 1,
        analysisPhase: 'auto',
        force: false,
      });
    });
    expect(await screen.findByText('已提交 HK00700 分析任务：task-portfolio-1')).toBeInTheDocument();
  });

  it('prefers disabled feedback over empty-pair feedback when refresh is disabled', async () => {
    refreshFx.mockResolvedValueOnce({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: false,
      disabledReason: 'portfolio_fx_update_disabled',
      pairCount: 0,
      updatedCount: 0,
      staleCount: 0,
      errorCount: 0,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    expect(await screen.findByText('汇率在线刷新已被禁用。')).toBeInTheDocument();
    expect(screen.queryByText('当前范围无可刷新的汇率对。')).not.toBeInTheDocument();
  });

  it('shows warning feedback when FX refresh still falls back to stale rates', async () => {
    refreshFx.mockResolvedValueOnce({
      asOf: '2026-03-19',
      accountCount: 1,
      pairCount: 2,
      updatedCount: 1,
      staleCount: 1,
      errorCount: 0,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    expect(await screen.findByText(/stale\/fallback 汇率/)).toBeInTheDocument();
  });

  it('shows warning feedback when FX refresh returns online errors without stale pairs', async () => {
    refreshFx.mockResolvedValueOnce({
      asOf: '2026-03-19',
      accountCount: 1,
      pairCount: 1,
      updatedCount: 0,
      staleCount: 0,
      errorCount: 1,
    });

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const snapshotCallsBeforeRefresh = getSnapshot.mock.calls.length;
    const riskCallsBeforeRefresh = getRisk.mock.calls.length;
    const tradeCallsBeforeRefresh = listTrades.mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    expect(await screen.findByText(/在线刷新未完全成功/)).toBeInTheDocument();
    await waitFor(() => expect(getSnapshot).toHaveBeenCalledTimes(snapshotCallsBeforeRefresh + 1));
    await waitFor(() => expect(getRisk).toHaveBeenCalledTimes(riskCallsBeforeRefresh + 1));
    expect(listTrades).toHaveBeenCalledTimes(tradeCallsBeforeRefresh);
    expect(listCashLedger).not.toHaveBeenCalled();
    expect(listCorporateActions).not.toHaveBeenCalled();
  });

  it('restores the button state and shows the existing error alert when FX refresh fails', async () => {
    refreshFx.mockRejectedValueOnce(
      createApiError(
        createParsedApiError({
          title: '刷新失败',
          message: '汇率服务暂时不可用',
        }),
      ),
    );

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const refreshButton = screen.getByRole('button', { name: '刷新汇率' });
    fireEvent.click(refreshButton);

    const fxAlertTitle = await screen.findByText('刷新失败');
    expect(fxAlertTitle.closest('[role="alert"]')).toHaveTextContent('汇率服务暂时不可用');
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新汇率' })).not.toBeDisabled());
  });

  it('does not keep success feedback when snapshot reload fails after FX refresh succeeds', async () => {
    getSnapshot
      .mockResolvedValueOnce(makeSnapshot({ fxStale: true }))
      .mockRejectedValueOnce(
        createApiError(
          createParsedApiError({
            title: '快照刷新失败',
            message: '无法加载最新持仓快照',
          }),
        ),
      );

    render(<PortfolioPage />);

    await waitForInitialLoad();

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));

    const fxAlertTitle = await screen.findByText('快照刷新失败');
    expect(fxAlertTitle.closest('[role="alert"]')).toHaveTextContent('无法加载最新持仓快照');
    await waitFor(() => expect(screen.queryByText('汇率已刷新，共更新 1 对。')).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新汇率' })).not.toBeDisabled());
  });

  it('drops late FX refresh results after switching to another account scope', async () => {
    getAccounts.mockResolvedValueOnce(makeAccounts([{ id: 1, name: 'Main' }, { id: 2, name: 'Alt' }]));
    getSnapshot.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 2) {
        return makeSnapshot({ accountId: 2, fxStale: false });
      }
      return makeSnapshot({ accountId: accountId ?? 1, fxStale: true, accountCount: accountId ? 1 : 2 });
    });

    const pendingRefresh = deferredPromise<{
      asOf: string;
      accountCount: number;
      pairCount: number;
      updatedCount: number;
      staleCount: number;
      errorCount: number;
    }>();
    refreshFx.mockImplementationOnce(() => pendingRefresh.promise);

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: 1, costMethod: 'fifo', includeRealtime: false }));

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));
    expect(await screen.findByRole('button', { name: '刷新中...' })).toBeDisabled();

    fireEvent.change(accountSelect, { target: { value: '2' } });
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: 2, costMethod: 'fifo', includeRealtime: false }));
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新汇率' })).not.toBeDisabled());

    const snapshotCallsAfterSwitch = getSnapshot.mock.calls.length;
    const riskCallsAfterSwitch = getRisk.mock.calls.length;

    await act(async () => {
      pendingRefresh.resolve({
        asOf: '2026-03-19',
        accountCount: 1,
        pairCount: 1,
        updatedCount: 1,
        staleCount: 0,
        errorCount: 0,
      });
      await pendingRefresh.promise;
    });

    expect(getSnapshot).toHaveBeenCalledTimes(snapshotCallsAfterSwitch);
    expect(getRisk).toHaveBeenCalledTimes(riskCallsAfterSwitch);
    expect(screen.queryByText('汇率已刷新，共更新 1 对。')).not.toBeInTheDocument();
  });

  it('drops late FX refresh results after switching cost method', async () => {
    const pendingRefresh = deferredPromise<{
      asOf: string;
      accountCount: number;
      pairCount: number;
      updatedCount: number;
      staleCount: number;
      errorCount: number;
    }>();
    refreshFx.mockImplementationOnce(() => pendingRefresh.promise);

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const costMethodSelect = screen.getAllByRole('combobox')[1];

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));
    expect(await screen.findByRole('button', { name: '刷新中...' })).toBeDisabled();

    fireEvent.change(costMethodSelect, { target: { value: 'avg' } });
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: undefined, costMethod: 'avg', includeRealtime: false }));
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新汇率' })).not.toBeDisabled());

    const snapshotCallsAfterSwitch = getSnapshot.mock.calls.length;
    const riskCallsAfterSwitch = getRisk.mock.calls.length;

    await act(async () => {
      pendingRefresh.resolve({
        asOf: '2026-03-19',
        accountCount: 1,
        pairCount: 1,
        updatedCount: 1,
        staleCount: 0,
        errorCount: 0,
      });
      await pendingRefresh.promise;
    });

    expect(getSnapshot).toHaveBeenCalledTimes(snapshotCallsAfterSwitch);
    expect(getRisk).toHaveBeenCalledTimes(riskCallsAfterSwitch);
    expect(screen.queryByText('汇率已刷新，共更新 1 对。')).not.toBeInTheDocument();
  });

  it('deactivates the selected account from the account toolbar and reloads accounts', async () => {
    getAccounts
      .mockResolvedValueOnce(makeAccounts([{ id: 1, name: 'Main' }, { id: 2, name: 'Alt' }]))
      .mockResolvedValueOnce(makeAccounts([{ id: 2, name: 'Alt' }]));

    render(<PortfolioPage />);

    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });

    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: 1, costMethod: 'fifo', includeRealtime: false }));
    fireEvent.click(screen.getByRole('button', { name: '删除账户' }));

    const dialog = await screen.findByText('删除持仓账户');
    expect(dialog.closest('[role="dialog"]') ?? document.body).toHaveTextContent(
      '删除后该账户会从默认列表、快照、风险和录入入口隐藏',
    );
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));

    await waitFor(() => expect(deleteAccount).toHaveBeenCalledWith(1));
    await waitFor(() => expect(getAccounts).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText('Main (#1)')).not.toBeInTheDocument());
    expect(screen.getByRole('option', { name: 'Alt (#2)' })).toBeInTheDocument();
  });
});
