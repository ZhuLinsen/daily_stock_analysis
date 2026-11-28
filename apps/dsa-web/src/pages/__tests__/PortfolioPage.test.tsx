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
      coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
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
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
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

  it('converts mixed CNY and USD accounts using per-account aggregate market values', async () => {
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
          totalMarketValueAggregate: 700,
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
    for (const label of ['市场暴露', '币种暴露']) {
      const exposure = dashboardScope.getByText(label).closest('div.rounded-xl');
      const scope = within(exposure as HTMLElement);
      expect(scope.getByText('CNY 70.00')).toBeInTheDocument();
      expect(scope.getByText('CNY 700.00')).toBeInTheDocument();
      expect(scope.getByText('9.09%')).toBeInTheDocument();
      expect(scope.getByText('90.91%')).toBeInTheDocument();
      expect(scope.queryByText('CNY 100.00')).not.toBeInTheDocument();
    }
    expect(dashboardScope.queryByText('暴露不可用')).not.toBeInTheDocument();
  });

  it.each(['fresh', 'stale', 'missing', 'zero-value-account'] as const)('handles three account valuation currencies with %s conversion evidence', async (evidence) => {
    const snapshot = makeSnapshot({ fxStale: false });
    const specs = [
      { currency: 'CNY', market: 'cn', symbol: '600519', raw: 70, converted: 70 },
      { currency: 'USD', market: 'us', symbol: 'AAPL', raw: 100, converted: 700 },
      { currency: 'HKD', market: 'hk', symbol: 'HK00700', raw: 200, converted: 180 },
    ];
    const accounts = specs.map((item, index) => ({
      ...snapshot.accounts[0],
      accountId: index + 1,
      baseCurrency: item.currency,
      totalMarketValue: item.raw,
      totalMarketValueAggregate: evidence === 'missing' && index === 1 ? undefined : item.converted,
      fxStale: evidence === 'stale' && index === 1,
      positions: [makePosition({
        symbol: item.symbol, market: item.market, currency: item.currency,
        valuationCurrency: item.currency, marketValueBase: item.raw,
      })],
    }));
    if (evidence === 'zero-value-account') {
      accounts.push({
        ...accounts[2], accountId: 4, totalMarketValue: 0, totalMarketValueAggregate: 0,
        positions: [makePosition({
          symbol: 'HK09988', market: 'hk', currency: 'HKD', valuationCurrency: 'HKD', marketValueBase: 0,
        })],
      });
    }
    getSnapshot.mockResolvedValueOnce({ ...snapshot, accounts, accountCount: accounts.length, totalMarketValue: 950 });

    render(<PortfolioPage />);
    await waitForInitialLoad();
    const dashboard = within(screen.getByText('风险与暴露看板').closest('section') as HTMLElement);
    if (evidence === 'stale' || evidence === 'missing') {
      expect(dashboard.getAllByText('暴露不可用')).toHaveLength(2);
      expect(dashboard.queryByText('73.68%')).not.toBeInTheDocument();
      return;
    }
    for (const label of ['市场暴露', '币种暴露']) {
      const exposure = within(dashboard.getByText(label).closest('div.rounded-xl') as HTMLElement);
      for (const value of ['CNY 700.00', 'CNY 180.00', 'CNY 70.00', '73.68%', '18.95%', '7.37%']) {
        expect(exposure.getByText(value)).toBeInTheDocument();
      }
      if (evidence === 'zero-value-account') {
        expect(exposure.getByText('持仓 2')).toBeInTheDocument();
      }
    }
  });

  it.each([NaN, Infinity, -1, undefined])('does not hide invalid position valuation %s in otherwise complete exposure', async (marketValueBase) => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({
      fxStale: false,
      positions: [makePosition(), makePosition({ symbol: 'AAPL', market: 'us', marketValueBase })],
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();
    const dashboard = within(screen.getByText('风险与暴露看板').closest('section') as HTMLElement);
    expect(dashboard.getAllByText('暴露不可用')).toHaveLength(2);
  });

  it('distinguishes an empty portfolio from unavailable exposure', async () => {
    const snapshot = makeSnapshot({ fxStale: false });
    getSnapshot.mockResolvedValueOnce({
      ...snapshot, totalMarketValue: 0, totalEquity: 1000,
      accounts: [{ ...snapshot.accounts[0], totalMarketValue: 0, totalEquity: 1000 }],
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();
    const dashboard = within(screen.getByText('风险与暴露看板').closest('section') as HTMLElement);
    expect(dashboard.getAllByText('暂无暴露数据')).toHaveLength(2);
    expect(dashboard.getByText('总市值: CNY 0.00')).toBeInTheDocument();
    expect(dashboard.getByText('持仓: 0')).toBeInTheDocument();
    expect(screen.getByText('共 0 项')).toBeInTheDocument();
    expect(screen.getByText('当前无持仓数据')).toBeInTheDocument();
    expect(screen.getByText('最新')).toBeInTheDocument();
    expect(dashboard.queryByText('暴露不可用')).not.toBeInTheDocument();
  });

  it('labels unavailable exposure in English when FX evidence is stale', async () => {
    renderEnglishPage();
    await waitForInitialLoad();
    const dashboard = within(screen.getByText('Risk and exposure dashboard').closest('section') as HTMLElement);
    expect(dashboard.getAllByText('Exposure unavailable')).toHaveLength(2);
    expect(dashboard.queryByText('No exposure data')).not.toBeInTheDocument();
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
    expect(dashboardScope.getAllByText('暴露不可用')).toHaveLength(2);
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
    expect(dashboardScope.getAllByText('暴露不可用')).toHaveLength(2);
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
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
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

  it.each<{
    priceAvailable?: boolean;
    priceSource: string;
    lastPrice: number;
    separateAccount?: boolean;
  }>([
    { priceAvailable: false, priceSource: 'missing', lastPrice: 0 },
    { priceAvailable: undefined, priceSource: 'missing', lastPrice: 0 },
    { priceAvailable: undefined, priceSource: 'history_close', lastPrice: 1600 },
    { priceAvailable: false, priceSource: 'history_close', lastPrice: 1600 },
    { priceAvailable: true, priceSource: 'missing', lastPrice: 1600 },
    { priceAvailable: true, priceSource: 'history_close', lastPrice: 0 },
    { priceAvailable: true, priceSource: 'history_close', lastPrice: -1 },
    { priceAvailable: true, priceSource: 'history_close', lastPrice: NaN },
    { priceAvailable: true, priceSource: 'history_close', lastPrice: Infinity },
    { priceAvailable: false, priceSource: 'missing', lastPrice: 0, separateAccount: true },
  ])('hides concentration and exposure conclusions for an unusable quote: %j', async ({ separateAccount = false, ...quote }) => {
    const snapshot = makeSnapshot({
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
          marketValueBase: 0,
          priceDate: null,
          priceStale: true,
          ...quote,
        }),
      ],
    });
    snapshot.totalMarketValue = 6000;
    snapshot.accounts[0].totalMarketValue = 6000;
    if (separateAccount) {
      const unpricedPosition = snapshot.accounts[0].positions.pop()!;
      snapshot.accounts.push({
        ...snapshot.accounts[0],
        accountId: 2,
        accountName: 'Account 2',
        totalMarketValue: 0,
        positions: [unpricedPosition],
      });
      snapshot.accountCount = 2;
    }
    getSnapshot.mockResolvedValueOnce(snapshot);
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
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
        errors: [],
      },
      stopLoss: {
        nearAlert: true,
        triggeredCount: 1,
        nearCount: 1,
        items: [],
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
    expect(screen.getAllByText('暴露不可用')).toHaveLength(2);
    expect(screen.queryByText('US')).not.toBeInTheDocument();
    expect(screen.queryByText('100.00%')).not.toBeInTheDocument();
    const concentrationCard = screen.getByText('行业数据暂不可用，当前展示个股集中度').closest('div.rounded-2xl');
    expect(concentrationCard).not.toBeNull();
    const concentrationScope = within(concentrationCard as HTMLElement);
    expect(concentrationScope.getByText('暂无集中度数据')).toBeInTheDocument();
    expect(concentrationScope.getByText('板块集中度告警: 不可用')).toBeInTheDocument();
    expect(concentrationScope.getByText('Top1 权重: --')).toBeInTheDocument();
    const priceFlag = screen.getByText('价格质量').closest('div.rounded-xl');
    expect(priceFlag).not.toBeNull();
    expect(within(priceFlag as HTMLElement).getByText('缺价: 1 · 过期价: 0')).toBeInTheDocument();
    expect(within(priceFlag as HTMLElement).getByText('需处理')).toBeInTheDocument();
    const stopLossFlag = screen.getByText('止损', { exact: true }).closest('div.rounded-xl');
    expect(stopLossFlag).not.toBeNull();
    expect(within(stopLossFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    const stopLossCard = screen.getByText('止损接近预警').closest('div.rounded-2xl');
    expect(stopLossCard).not.toBeNull();
    const stopLossScope = within(stopLossCard as HTMLElement);
    expect(stopLossScope.getByText('触发数: --')).toBeInTheDocument();
    expect(stopLossScope.getByText('接近数: --')).toBeInTheDocument();
    expect(stopLossScope.getByText('告警: 不可用')).toBeInTheDocument();
  });

  it.each([false, true])('keeps genuine 100%% concentration available with a usable quote (stale: %s)', async (priceStale) => {
    const snapshot = makeSnapshot({
      fxStale: false,
      positions: [makePosition({ priceStale })],
    });
    snapshot.totalMarketValue = 1600;
    snapshot.accounts[0].totalMarketValue = 1600;
    getSnapshot.mockResolvedValueOnce(snapshot);
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 1600,
        topWeightPct: 100,
        alert: true,
        topPositions: [{ symbol: '600519', marketValueBase: 1600, weightPct: 100, isAlert: true }],
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const flag = screen.getByText('个股集中').closest('div.rounded-xl');
    expect(flag).not.toBeNull();
    const flagScope = within(flag as HTMLElement);
    expect(flagScope.getByText('100.00%')).toBeInTheDocument();
    expect(flagScope.getByText('Top1: 600519')).toBeInTheDocument();
    expect(flagScope.getByText('需处理')).toBeInTheDocument();
    expect(screen.getByText('Top1 权重: 100.00%')).toBeInTheDocument();
    expect(screen.queryByText('暂无集中度数据')).not.toBeInTheDocument();
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
    expect(screen.getAllByText('暴露不可用')).toHaveLength(2);
  });

  it('marks price quality unavailable when the portfolio snapshot fails', async () => {
    getSnapshot.mockRejectedValueOnce(new Error('snapshot unavailable'));

    render(<PortfolioPage />);

    await screen.findByText('snapshot unavailable');
    const priceFlag = (await screen.findByText('价格质量')).closest('div.rounded-xl');
    expect(priceFlag).not.toBeNull();
    expect(within(priceFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(within(priceFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    const dashboard = screen.getByText('风险与暴露看板').closest('section');
    expect(within(dashboard as HTMLElement).getByText('总市值: --')).toBeInTheDocument();
    expect(within(dashboard as HTMLElement).queryByText(/总市值: CNY 0/)).not.toBeInTheDocument();
    expect(within(dashboard as HTMLElement).getByText('持仓: --')).toBeInTheDocument();
    expect(screen.getByText('共 -- 项')).toBeInTheDocument();
    expect(screen.getByText('账户数: --')).toBeInTheDocument();
    expect(screen.getByText('计价币种: --')).toBeInTheDocument();
    expect(screen.getByText('持仓快照不可用')).toBeInTheDocument();
    expect(screen.queryByText('当前无持仓数据')).not.toBeInTheDocument();
    expect(screen.queryByText('最新')).not.toBeInTheDocument();
    expect(screen.getByText('暂无集中度数据')).toBeInTheDocument();
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
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
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
        coverage: { classifiedCount: 0, unclassifiedCount: 2, failedCount: 0 },
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
        coverage: { classifiedCount: 1, unclassifiedCount: 2, failedCount: 0 },
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

  it.each([
    { classifiedCount: 0, unclassifiedCount: 0, failedCount: 0, errors: [] },
    { classifiedCount: undefined, unclassifiedCount: 0, failedCount: 0, errors: [] },
    { classifiedCount: 1, unclassifiedCount: 1, failedCount: 0, errors: [] },
    { classifiedCount: 1, unclassifiedCount: 0, failedCount: 1, errors: [] },
    { classifiedCount: 1, unclassifiedCount: 0, failedCount: 0, errors: ['classification failed'] },
  ])('marks sector risk unavailable for incomplete classification evidence: %j', async ({ errors, ...coverage }) => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      sectorConcentration: {
        totalMarketValue: 10000,
        topWeightPct: 100,
        alert: true,
        topSectors: [{ sector: 'Technology', marketValueBase: 10000, weightPct: 100, symbolCount: 1, isAlert: true }],
        coverage,
        errors,
      },
    }));

    render(<PortfolioPage />);
    await waitForInitialLoad();
    const flag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(within(flag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(within(flag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    expect(screen.getByText('板块集中度告警: 不可用')).toBeInTheDocument();
    expect(screen.queryByText('Top1: Technology')).not.toBeInTheDocument();
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
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
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
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
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
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
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
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
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

  it.each([
    [{ symbol: '', weightPct: 60 }, { symbol: 'AAPL', weightPct: 40 }],
    [{ symbol: '600519', weightPct: 40 }, { symbol: 'AAPL', weightPct: 60 }],
    [{ symbol: '600519', weightPct: 60 }, { symbol: '', weightPct: 40 }],
    [{ symbol: '600519', weightPct: '60' }],
    [{ symbol: '600519', weightPct: 60 }, { symbol: 'AAPL', weightPct: 70 }],
  ])('rejects inconsistent concentration rows instead of relabeling Top1: %j', async (...topPositions) => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 10000,
        topWeightPct: 60,
        alert: true,
        topPositions: topPositions as never,
      },
    }));

    render(<PortfolioPage />);

    await waitForInitialLoad();
    const concentrationFlag = screen.getByText('个股集中').closest('div.rounded-xl');
    expect(within(concentrationFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(within(concentrationFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    expect(screen.queryByText('Top1: AAPL')).not.toBeInTheDocument();
    expect(screen.getByText('暂无集中度数据')).toBeInTheDocument();
  });

  it.each([
    { summary: 80, weights: [20, 80] },
    { summary: 80, weights: [70, 30] },
    { summary: 70, weights: [70, 80] },
    { summary: 120, weights: [120] },
  ])('rejects inconsistent sector Top1 evidence: %j', async ({ summary, weights }) => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false }));
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: {
        totalMarketValue: 10000, topWeightPct: 60, alert: true,
        topPositions: [{ symbol: '600519', marketValueBase: 6000, weightPct: 60, isAlert: true }],
      },
      sectorConcentration: {
        totalMarketValue: 10000, topWeightPct: summary, alert: true,
        topSectors: weights.map((weightPct, index) => ({
          sector: index === 0 ? '白酒' : '科技', marketValueBase: weightPct * 100,
          weightPct, symbolCount: 1, isAlert: true,
        })),
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 }, errors: [],
      },
    }));
    render(<PortfolioPage />);
    await waitForInitialLoad();
    const sectorFlag = screen.getByText('行业集中').closest('div.rounded-xl');
    expect(within(sectorFlag as HTMLElement).getByText('--')).toBeInTheDocument();
    expect(within(sectorFlag as HTMLElement).getAllByText('不可用')).toHaveLength(2);
    expect(screen.queryByText('Top1: 白酒')).not.toBeInTheDocument();
    expect(screen.getByText('行业数据暂不可用，当前展示个股集中度')).toBeInTheDocument();
    expect(screen.getByText('Top1: 600519')).toBeInTheDocument();
  });

  it.each(['position', 'sector'])('keeps valid %s concentration with rounded-zero tail weights', async (kind) => {
    getSnapshot.mockResolvedValueOnce(makeSnapshot({ fxStale: false, positions: [
      makePosition({ symbol: '600519', marketValueBase: 10000000 }),
      makePosition({ symbol: '000001', lastPrice: 1, marketValueBase: 1 }),
    ] }));
    const topPositions = [
      { symbol: '600519', marketValueBase: 10000000, weightPct: 100, isAlert: true },
      { symbol: '000001', marketValueBase: 1, weightPct: 0, isAlert: false },
    ];
    getRisk.mockResolvedValueOnce(makeRisk({
      concentration: { totalMarketValue: 10000001, topWeightPct: 100, alert: true, topPositions },
      ...(kind === 'sector' ? { sectorConcentration: {
        totalMarketValue: 10000001, topWeightPct: 100, alert: true,
        topSectors: topPositions.map((row, index) => ({ ...row, sector: index ? '银行' : '白酒', symbolCount: 1 })),
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 }, errors: [],
      } } : {}),
    }));
    render(<PortfolioPage />);
    await waitForInitialLoad();
    const flag = screen.getByText(kind === 'sector' ? '行业集中' : '个股集中').closest('div.rounded-xl');
    expect(within(flag as HTMLElement).getByText('100.00%')).toBeInTheDocument();
    expect(within(flag as HTMLElement).getByText('需处理')).toBeInTheDocument();
    expect(within(flag as HTMLElement).getByText(kind === 'sector' ? 'Top1: 白酒' : 'Top1: 600519')).toBeInTheDocument();
    expect(screen.queryByText('暂无集中度数据')).not.toBeInTheDocument();
    expect(screen.getByText(kind === 'sector' ? '行业集中度分布' : '行业数据暂不可用，当前展示个股集中度')).toBeInTheDocument();
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
        coverage: { classifiedCount: 2, unclassifiedCount: 0, failedCount: 0 },
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
      expect(screen.getByRole('button', { name: '刷新汇率' })).not.toBeDisabled();
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
      { symbol: '600519', market: 'cn', currency: 'CNY', quantity: 10, avgCost: 1500, totalCost: 15000, lastPrice: 1450, marketValueBase: 14500, unrealizedPnlBase: -500, unrealizedPnlPct: -3.33, valuationCurrency: 'CNY', priceSource: 'history_close', priceDate: '2026-03-18', priceStale: false, priceAvailable: true },
      { symbol: 'MSFT', market: 'us', currency: 'USD', quantity: 2, avgCost: 400, totalCost: 800, lastPrice: 400, marketValueBase: 800, unrealizedPnlBase: 0, unrealizedPnlPct: 0, valuationCurrency: 'USD', priceSource: 'history_close', priceDate: '2026-03-18', priceStale: false, priceAvailable: true },
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
    const cnRow = screen.getByText('600519').closest('tr');
    const msftRow = screen.getByText('MSFT').closest('tr');
    const aaplRow = screen.getByText('AAPL').closest('tr');
    expect(hkRow).not.toBeNull();
    expect(cnRow).not.toBeNull();
    expect(msftRow).not.toBeNull();
    expect(aaplRow).not.toBeNull();

    const hkRowCells = within(hkRow as HTMLTableRowElement).getAllByRole('cell');
    const cnRowCells = within(cnRow as HTMLTableRowElement).getAllByRole('cell');
    const msftRowCells = within(msftRow as HTMLTableRowElement).getAllByRole('cell');
    const aaplRowCells = within(aaplRow as HTMLTableRowElement).getAllByRole('cell');
    // Positive PnL & PnL% -> red-up (text-price-up)
    expect(hkRowCells.at(-4)).toHaveClass('text-price-up');
    expect(hkRowCells.at(-3)).toHaveClass('text-price-up');
    // Negative PnL & PnL% -> green-down (text-price-down)
    expect(cnRowCells.at(-4)).toHaveClass('text-price-down');
    expect(cnRowCells.at(-3)).toHaveClass('text-price-down');
    // Zero PnL & PnL% -> neutral (neither price-up nor price-down)
    expect(msftRowCells.at(-4)).not.toHaveClass('text-price-up');
    expect(msftRowCells.at(-4)).not.toHaveClass('text-price-down');
    expect(msftRowCells.at(-3)).not.toHaveClass('text-price-up');
    expect(msftRowCells.at(-3)).not.toHaveClass('text-price-down');
    // Missing price -> muted text-secondary
    expect(aaplRowCells.at(-4)).toHaveClass('text-secondary');
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
    const deleteButton = screen.getByRole('button', { name: '删除账户' });
    await waitFor(() => expect(deleteButton).toBeEnabled());
    fireEvent.click(deleteButton);

    const dialog = await screen.findByRole('dialog', { name: '删除持仓账户' });
    expect(dialog).toHaveTextContent(
      '删除后该账户会从默认列表、快照、风险和录入入口隐藏',
    );
    fireEvent.click(within(dialog).getByRole('button', { name: '确认删除' }));

    await waitFor(() => expect(deleteAccount).toHaveBeenCalledWith(1));
    await waitFor(() => expect(getAccounts).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText('Main (#1)')).not.toBeInTheDocument());
    expect(screen.getByRole('option', { name: 'Alt (#2)' })).toBeInTheDocument();
  });

  it('ignores stale getSnapshot responses when switching accounts', async () => {
    const account1Snapshot = deferredPromise<ReturnType<typeof makeSnapshot>>();

    getAccounts.mockResolvedValue(makeAccounts([{ id: 1, name: 'Main' }, { id: 2, name: 'Alt' }]));
    getSnapshot.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 1) {
        return account1Snapshot.promise;
      }
      if (accountId === 2) {
        return makeSnapshot({
          accountId: 2,
          fxStale: false,
          positions: [makePosition({ symbol: 'FRESH_ACC2', market: 'us' })],
        });
      }
      return makeSnapshot({ accountId: 1, accountCount: 2, fxStale: false });
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    await waitFor(() => expect(getSnapshot).toHaveBeenCalledWith({
      accountId: 1,
      costMethod: 'fifo',
      includeRealtime: false,
    }));

    fireEvent.change(accountSelect, { target: { value: '2' } });
    expect(await screen.findByText('FRESH_ACC2')).toBeInTheDocument();

    await act(async () => {
      account1Snapshot.resolve(makeSnapshot({
        accountId: 1,
        fxStale: false,
        positions: [makePosition({ symbol: 'STALE_ACC1', market: 'cn' })],
      }));
      await account1Snapshot.promise;
    });

    expect(screen.getByText('FRESH_ACC2')).toBeInTheDocument();
    expect(screen.queryByText('STALE_ACC1')).not.toBeInTheDocument();
  });

  it('ignores stale listTrades responses when switching event tabs', async () => {
    const pendingTrades = deferredPromise<{
      items: Array<Record<string, unknown>>;
      total: number;
      page: number;
      pageSize: number;
    }>();

    render(<PortfolioPage />);
    await waitForInitialLoad();

    listTrades.mockReturnValueOnce(pendingTrades.promise);
    listCashLedger.mockResolvedValueOnce({
      items: [
        {
          id: 88,
          accountId: 1,
          eventDate: '2026-06-18',
          direction: 'in',
          amount: 5000,
          currency: 'CNY',
          note: null,
          createdAt: '2026-06-18T00:00:00Z',
        },
      ],
      total: 45,
      page: 1,
      pageSize: 20,
    });

    fireEvent.change(screen.getByDisplayValue('全部买卖方向'), { target: { value: 'buy' } });
    await waitFor(() => expect(listTrades).toHaveBeenCalledTimes(2));

    fireEvent.change(screen.getByDisplayValue('交易流水'), { target: { value: 'cash' } });
    expect(await screen.findByText(/2026-06-18 流入 5000 CNY/)).toBeInTheDocument();
    expect(screen.getByText('第 1 / 3 页')).toBeInTheDocument();

    await act(async () => {
      pendingTrades.resolve({
        items: [
          {
            id: 99,
            accountId: 1,
            symbol: 'STALE_TRADE',
            tradeDate: '2026-05-01',
            side: 'buy',
            quantity: 10,
            price: 100,
            fee: 0,
            tax: 0,
            tradeUid: null,
            note: null,
            createdAt: '2026-05-01T00:00:00Z',
          },
        ],
        total: 100,
        page: 1,
        pageSize: 20,
      });
      await pendingTrades.promise;
    });

    expect(screen.getByText(/2026-06-18 流入 5000 CNY/)).toBeInTheDocument();
    expect(screen.getByText('第 1 / 3 页')).toBeInTheDocument();
    expect(screen.queryByText('第 1 / 5 页')).not.toBeInTheDocument();
  });

  it('does not re-fetch brokers or accounts when changing broker selection', async () => {
    listImportBrokers.mockResolvedValue({
      brokers: [
        { broker: 'huatai', aliases: [], displayName: '华泰' },
        { broker: 'citic', aliases: [], displayName: '中信' },
      ],
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();
    await screen.findByRole('option', { name: 'citic（中信）' });

    const initialBrokersCalls = listImportBrokers.mock.calls.length;
    const initialAccountsCalls = getAccounts.mock.calls.length;

    const brokerSelect = screen.getByDisplayValue('huatai（华泰）') as HTMLSelectElement;
    fireEvent.change(brokerSelect, { target: { value: 'citic' } });

    await act(async () => {
      await Promise.resolve();
    });

    expect(brokerSelect.value).toBe('citic');
    expect(listImportBrokers).toHaveBeenCalledTimes(initialBrokersCalls);
    expect(getAccounts).toHaveBeenCalledTimes(initialAccountsCalls);
  });

  it('guards double-submit on trade creation and ignores post-unmount settlements', async () => {
    const pendingTrade = deferredPromise<{ id: number }>();
    const pendingRefreshTrades = deferredPromise<{
      items: never[];
      total: number;
      page: number;
      pageSize: number;
    }>();

    createTrade.mockReturnValueOnce(pendingTrade.promise);

    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      const { unmount } = render(<PortfolioPage />);
      await waitForInitialLoad();

      const accountSelect = screen.getAllByRole('combobox')[0];
      fireEvent.change(accountSelect, { target: { value: '1' } });
      await waitFor(() => expect(screen.getByRole('button', { name: '提交交易' })).toBeEnabled());

      fireEvent.change(screen.getByPlaceholderText('股票代码（例如 600519）'), { target: { value: '600519' } });
      fireEvent.change(screen.getByPlaceholderText('数量（必填）'), { target: { value: '100' } });
      fireEvent.change(screen.getByPlaceholderText('成交价（必填）'), { target: { value: '1800' } });

      const submitTradeButton = screen.getByRole('button', { name: '提交交易' });
      fireEvent.click(submitTradeButton);
      fireEvent.click(submitTradeButton);

      expect(createTrade).toHaveBeenCalledTimes(1);
      expect(submitTradeButton).toBeDisabled();

      listTrades.mockReturnValueOnce(pendingRefreshTrades.promise);
      fireEvent.click(screen.getByRole('button', { name: '刷新流水' }));

      unmount();

      await act(async () => {
        pendingTrade.resolve({ id: 1 });
        pendingRefreshTrades.resolve({ items: [], total: 0, page: 1, pageSize: 20 });
        await Promise.resolve();
      });

      expect(consoleErrorSpy).not.toHaveBeenCalled();
    } finally {
      consoleErrorSpy.mockRestore();
    }
  });

  it('clears loading state and ignores older FX reload when concurrent trade refresh wins', async () => {
    const pendingFxRefresh = deferredPromise<{
      asOf: string;
      accountCount: number;
      pairCount: number;
      updatedCount: number;
      staleCount: number;
      errorCount: number;
    }>();
    const pendingFxSnapshot = deferredPromise<ReturnType<typeof makeSnapshot>>();
    const pendingPostTradeSnapshot = deferredPromise<ReturnType<typeof makeSnapshot>>();

    refreshFx.mockImplementationOnce(() => pendingFxRefresh.promise);

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: 1, costMethod: 'fifo', includeRealtime: false }));

    const refreshDataBtn = screen.getByRole('button', { name: '刷新数据' });
    const refreshFxBtn = screen.getByRole('button', { name: '刷新汇率' });

    // Start FX refresh first; it resolves into reloadSnapshotAndRiskForScope later
    fireEvent.click(refreshFxBtn);
    expect(await screen.findByRole('button', { name: '刷新中...' })).toBeDisabled();

    await act(async () => {
      pendingFxRefresh.resolve({
        asOf: '2026-03-19',
        accountCount: 1,
        pairCount: 1,
        updatedCount: 1,
        staleCount: 0,
        errorCount: 0,
      });
      getSnapshot.mockReturnValueOnce(pendingFxSnapshot.promise);
      await pendingFxRefresh.promise;
    });

    // Next, submit a trade while FX reload's getSnapshot is still pending
    getSnapshot.mockReturnValueOnce(pendingPostTradeSnapshot.promise);
    fireEvent.change(screen.getByPlaceholderText('股票代码（例如 600519）'), { target: { value: '600519' } });
    fireEvent.change(screen.getByPlaceholderText('数量（必填）'), { target: { value: '100' } });
    fireEvent.change(screen.getByPlaceholderText('成交价（必填）'), { target: { value: '1800' } });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '提交交易' }));
      await Promise.resolve();
    });

    // Resolve the newer post-trade snapshot first
    await act(async () => {
      pendingPostTradeSnapshot.resolve(makeSnapshot({
        accountId: 1,
        fxStale: false,
        positions: [makePosition({ symbol: 'NEW_TRADE_WIN', market: 'cn' })],
      }));
      await pendingPostTradeSnapshot.promise;
    });

    expect(await screen.findByText('NEW_TRADE_WIN')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新数据' })).toBeInTheDocument();

    // Resolving the older FX-triggered snapshot later must NOT overwrite NEW_TRADE_WIN
    await act(async () => {
      pendingFxSnapshot.resolve(makeSnapshot({
        accountId: 1,
        fxStale: false,
        positions: [makePosition({ symbol: 'OLD_FX_STALE', market: 'cn' })],
      }));
      await pendingFxSnapshot.promise;
    });

    await waitFor(() => expect(refreshDataBtn).toBeEnabled());
    expect(screen.getByText('NEW_TRADE_WIN')).toBeInTheDocument();
    expect(screen.queryByText('OLD_FX_STALE')).not.toBeInTheDocument();

    // Case 2: trade refresh starts before FX enters reloadSnapshotAndRiskForScope (isLoading wedge guard)
    const pendingRefresh2 = deferredPromise<{
      asOf: string;
      accountCount: number;
      pairCount: number;
      updatedCount: number;
      staleCount: number;
      errorCount: number;
    }>();
    const pendingTradeRefreshSnapshot2 = deferredPromise<ReturnType<typeof makeSnapshot>>();
    const pendingFxSnapshot2 = deferredPromise<ReturnType<typeof makeSnapshot>>();

    refreshFx.mockImplementationOnce(() => pendingRefresh2.promise);
    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));
    expect(await screen.findByRole('button', { name: '刷新中...' })).toBeDisabled();

    getSnapshot.mockReturnValueOnce(pendingTradeRefreshSnapshot2.promise);
    fireEvent.change(screen.getByPlaceholderText('股票代码（例如 600519）'), { target: { value: '000001' } });
    fireEvent.change(screen.getByPlaceholderText('数量（必填）'), { target: { value: '100' } });
    fireEvent.change(screen.getByPlaceholderText('成交价（必填）'), { target: { value: '12' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '提交交易' }));
      await Promise.resolve();
    });

    // Now FX resolves and enters reloadSnapshotAndRiskForScope (bumping snapshotRequestRef)
    getSnapshot.mockReturnValueOnce(pendingFxSnapshot2.promise);
    await act(async () => {
      pendingRefresh2.resolve({
        asOf: '2026-03-19',
        accountCount: 1,
        pairCount: 1,
        updatedCount: 1,
        staleCount: 0,
        errorCount: 0,
      });
      await pendingRefresh2.promise;
    });

    // Even when the earlier loadSnapshotAndRisk resolves AFTER reloadSnapshotAndRiskForScope bumped snapshotRequestRef,
    // isLoading must clear cleanly via snapshotLoadingRequestRef (no permanent loading wedge).
    await act(async () => {
      pendingTradeRefreshSnapshot2.resolve(makeSnapshot({
        accountId: 1,
        fxStale: false,
        positions: [makePosition({ symbol: 'TRADE_SNAPSHOT_2', market: 'cn' })],
      }));
      await pendingTradeRefreshSnapshot2.promise;
    });
    expect(screen.getByRole('button', { name: '刷新数据' })).toBeInTheDocument();

    await act(async () => {
      pendingFxSnapshot2.resolve(makeSnapshot({
        accountId: 1,
        fxStale: false,
        positions: [makePosition({ symbol: 'FX_WIN_2', market: 'cn' })],
      }));
      await pendingFxSnapshot2.promise;
    });
    expect(await screen.findByText('FX_WIN_2')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新数据' })).toBeEnabled());
  });

  it('tracks position analysis loading independently per row for concurrent clicks (OR-COR-c207696f)', async () => {
    const deferredCn = deferredPromise<{
      taskId: string;
      traceId: string;
      status: string;
      message: string;
      analysisPhase: string;
    }>();
    const deferredHk = deferredPromise<{
      taskId: string;
      traceId: string;
      status: string;
      message: string;
      analysisPhase: string;
    }>();

    getSnapshot.mockResolvedValue(makeSnapshot({
      accountId: 1,
      fxStale: false,
      positions: [
        makePosition({ symbol: '600519', market: 'cn' }),
        makePosition({ symbol: 'HK00700', market: 'hk', currency: 'HKD' }),
      ],
    }));
    analyzePosition.mockImplementation(async (symbol: string) => (
      symbol === '600519' ? deferredCn.promise : deferredHk.promise
    ));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const rowCn = screen.getByText('600519').closest('tr') as HTMLTableRowElement;
    const rowHk = screen.getByText('HK00700').closest('tr') as HTMLTableRowElement;
    expect(rowCn).not.toBeNull();
    expect(rowHk).not.toBeNull();

    fireEvent.click(within(rowCn).getByRole('button', { name: '分析' }));
    await waitFor(() => expect(within(rowCn).getByRole('button', { name: '提交中' })).toBeDisabled());
    expect(within(rowHk).getByRole('button', { name: '分析' })).toBeEnabled();

    fireEvent.click(within(rowHk).getByRole('button', { name: '分析' }));
    await waitFor(() => expect(analyzePosition).toHaveBeenCalledTimes(2));
    expect(within(rowCn).getByRole('button', { name: '提交中' })).toBeDisabled();
    expect(within(rowHk).getByRole('button', { name: '提交中' })).toBeDisabled();

    await act(async () => {
      deferredCn.resolve({
        taskId: 'task-cn-1',
        traceId: 'task-cn-1',
        status: 'pending',
        message: 'queued',
        analysisPhase: 'auto',
      });
      await deferredCn.promise;
    });

    await waitFor(() => expect(within(rowCn).getByRole('button', { name: '分析' })).toBeEnabled());
    expect(within(rowHk).getByRole('button', { name: '提交中' })).toBeDisabled();

    await act(async () => {
      deferredHk.resolve({
        taskId: 'task-hk-1',
        traceId: 'task-hk-1',
        status: 'pending',
        message: 'queued',
        analysisPhase: 'auto',
      });
      await deferredHk.promise;
    });

    await waitFor(() => expect(within(rowHk).getByRole('button', { name: '分析' })).toBeEnabled());
  });

  it('keeps newly created account selected across a subsequent failed manual refresh (OR-COR-0f657839)', async () => {
    const deferredCreateAccounts = deferredPromise<ReturnType<typeof makeAccounts>>();
    const deferredManualAccounts = deferredPromise<ReturnType<typeof makeAccounts>>();

    getAccounts
      .mockResolvedValueOnce(makeAccounts([{ id: 1, name: 'Main' }]))
      .mockReturnValueOnce(deferredCreateAccounts.promise)
      .mockReturnValueOnce(deferredManualAccounts.promise);
    createAccount.mockResolvedValueOnce({
      id: 3,
      name: 'Growth',
      broker: 'Demo',
      market: 'cn',
      baseCurrency: 'CNY',
      isActive: true,
      ownerId: null,
      createdAt: '2026-03-19T00:00:00Z',
      updatedAt: '2026-03-19T00:00:00Z',
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    fireEvent.click(screen.getByRole('button', { name: '新建账户' }));
    fireEvent.change(screen.getByPlaceholderText('账户名称（必填）'), { target: { value: 'Growth' } });
    fireEvent.click(screen.getByRole('button', { name: '创建账户' }));

    await waitFor(() => expect(createAccount).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(getAccounts).toHaveBeenCalledTimes(2));

    const accountSelect = screen.getAllByRole('combobox')[0];
    expect(accountSelect).toHaveValue('3');

    fireEvent.click(screen.getByRole('button', { name: '刷新数据' }));
    await waitFor(() => expect(getAccounts).toHaveBeenCalledTimes(3));

    await act(async () => {
      deferredCreateAccounts.resolve(makeAccounts([{ id: 1, name: 'Main' }, { id: 3, name: 'Growth' }]));
      await deferredCreateAccounts.promise;
    });

    await act(async () => {
      deferredManualAccounts.reject(new Error('accounts down'));
      await deferredManualAccounts.promise.catch(() => undefined);
    });

    expect(await screen.findByText(/accounts down/)).toBeInTheDocument();
    expect(accountSelect).toHaveValue('3');
    expect(screen.getByRole('option', { name: 'Growth (#3)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '提交交易' })).toBeEnabled();
  });

  it('ignores slow trade completion from account A after switching to account B (OR-COR-009e8868)', async () => {
    const pendingTrade = deferredPromise<{ id: number }>();

    getAccounts.mockResolvedValue(makeAccounts([
      { id: 1, name: 'AccA' },
      { id: 2, name: 'AccB' },
    ]));
    getSnapshot.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 1) {
        return makeSnapshot({
          accountId: 1,
          fxStale: false,
          positions: [makePosition({ symbol: 'POS_A', market: 'cn' })],
        });
      }
      if (accountId === 2) {
        return makeSnapshot({
          accountId: 2,
          fxStale: false,
          positions: [makePosition({ symbol: 'POS_B', market: 'us' })],
        });
      }
      return makeSnapshot({ accountId: 1, accountCount: 2, fxStale: false });
    });
    listTrades.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 1) {
        return {
          items: [{ id: 11, accountId: 1, symbol: 'TRADE_A', tradeDate: '2026-06-18', side: 'buy', quantity: 10, price: 100, fee: 0, tax: 0, currency: 'CNY', note: null, createdAt: '2026-06-18T00:00:00Z' }],
          total: 1,
          page: 1,
          pageSize: 20,
        };
      }
      if (accountId === 2) {
        return {
          items: [{ id: 22, accountId: 2, symbol: 'TRADE_B', tradeDate: '2026-06-18', side: 'buy', quantity: 5, price: 200, fee: 0, tax: 0, currency: 'USD', note: null, createdAt: '2026-06-18T00:00:00Z' }],
          total: 1,
          page: 1,
          pageSize: 20,
        };
      }
      return { items: [], total: 0, page: 1, pageSize: 20 };
    });
    createTrade.mockReturnValueOnce(pendingTrade.promise);

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    expect(await screen.findByText('POS_A')).toBeInTheDocument();
    expect(await screen.findByText(/TRADE_A/)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('股票代码（例如 600519）'), { target: { value: '600519' } });
    fireEvent.change(screen.getByPlaceholderText('数量（必填）'), { target: { value: '10' } });
    fireEvent.change(screen.getByPlaceholderText('成交价（必填）'), { target: { value: '150' } });
    fireEvent.click(screen.getByRole('button', { name: '提交交易' }));
    await waitFor(() => expect(createTrade).toHaveBeenCalledTimes(1));

    fireEvent.change(accountSelect, { target: { value: '2' } });
    expect(await screen.findByText('POS_B')).toBeInTheDocument();
    expect(await screen.findByText(/TRADE_B/)).toBeInTheDocument();

    const snapshotCallsBeforeResolve = getSnapshot.mock.calls.length;
    const tradeListCallsBeforeResolve = listTrades.mock.calls.length;

    await act(async () => {
      pendingTrade.resolve({ id: 99 });
      await pendingTrade.promise;
    });

    expect(screen.getByText('POS_B')).toBeInTheDocument();
    expect(screen.getByText(/TRADE_B/)).toBeInTheDocument();
    expect(screen.queryByText('POS_A')).not.toBeInTheDocument();
    expect(screen.queryByText(/TRADE_A/)).not.toBeInTheDocument();
    expect(getSnapshot).toHaveBeenCalledTimes(snapshotCallsBeforeResolve);
    expect(listTrades).toHaveBeenCalledTimes(tradeListCallsBeforeResolve);
  });

  it('clears prior account rows immediately on scope switch and preserves account B load over late failed refresh (OR-COR-6b827fdb)', async () => {
    const failedManualSnapA = deferredPromise<ReturnType<typeof makeSnapshot>>();
    const pendingTradesB = deferredPromise<{
      items: Array<Record<string, unknown>>;
      total: number;
      page: number;
      pageSize: number;
    }>();
    let acc1SnapCalls = 0;

    getAccounts.mockResolvedValue(makeAccounts([
      { id: 1, name: 'AccA' },
      { id: 2, name: 'AccB' },
    ]));
    getSnapshot.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 1) {
        acc1SnapCalls += 1;
        if (acc1SnapCalls >= 2) {
          return failedManualSnapA.promise;
        }
        return makeSnapshot({
          accountId: 1,
          fxStale: false,
          positions: [makePosition({ symbol: 'POS_ACC_A', market: 'cn' })],
        });
      }
      if (accountId === 2) {
        return makeSnapshot({
          accountId: 2,
          fxStale: false,
          positions: [makePosition({ symbol: 'POS_ACC_B', market: 'us' })],
        });
      }
      return makeSnapshot({ accountId: 1, accountCount: 2, fxStale: false });
    });
    listTrades.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 1) {
        return {
          items: [{ id: 11, accountId: 1, symbol: 'TRADE_ACC_A', tradeDate: '2026-06-18', side: 'buy', quantity: 10, price: 100, fee: 0, tax: 0, currency: 'CNY', note: null, createdAt: '2026-06-18T00:00:00Z' }],
          total: 1,
          page: 1,
          pageSize: 20,
        };
      }
      if (accountId === 2) {
        return pendingTradesB.promise;
      }
      return { items: [], total: 0, page: 1, pageSize: 20 };
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    expect(await screen.findByText('POS_ACC_A')).toBeInTheDocument();
    expect(await screen.findByText(/TRADE_ACC_A/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '刷新数据' }));
    await waitFor(() => expect(acc1SnapCalls).toBe(2));

    fireEvent.change(accountSelect, { target: { value: '2' } });
    expect(screen.queryByText(/TRADE_ACC_A/)).not.toBeInTheDocument();
    expect(await screen.findByText('POS_ACC_B')).toBeInTheDocument();

    await act(async () => {
      pendingTradesB.resolve({
        items: [{ id: 22, accountId: 2, symbol: 'TRADE_ACC_B', tradeDate: '2026-06-18', side: 'buy', quantity: 5, price: 200, fee: 0, tax: 0, currency: 'USD', note: null, createdAt: '2026-06-18T00:00:00Z' }],
        total: 1,
        page: 1,
        pageSize: 20,
      });
      await pendingTradesB.promise;
    });
    expect(await screen.findByText(/TRADE_ACC_B/)).toBeInTheDocument();

    await act(async () => {
      failedManualSnapA.reject(new Error('late A refresh failure'));
      await failedManualSnapA.promise.catch(() => undefined);
    });

    expect(screen.getByText('POS_ACC_B')).toBeInTheDocument();
    expect(screen.getByText(/TRADE_ACC_B/)).toBeInTheDocument();
    expect(screen.queryByText(/late A refresh failure/)).not.toBeInTheDocument();
  });

  it('preserves disabled FX feedback when concurrent same-account trade snapshot completes first (OR-COR-c78895d9)', async () => {
    const pendingFxReload = deferredPromise<ReturnType<typeof makeSnapshot>>();
    let acc1SnapCalls = 0;

    getSnapshot.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 1) {
        acc1SnapCalls += 1;
        if (acc1SnapCalls === 2) {
          return pendingFxReload.promise;
        }
        if (acc1SnapCalls >= 3) {
          return makeSnapshot({
            accountId: 1,
            fxStale: false,
            positions: [makePosition({ symbol: 'TRADE_WINNER', market: 'cn' })],
          });
        }
        return makeSnapshot({
          accountId: 1,
          fxStale: true,
          positions: [makePosition({ symbol: 'INIT_POS', market: 'cn' })],
        });
      }
      return makeSnapshot({ accountId: 1, fxStale: true });
    });
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

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    expect(await screen.findByText('INIT_POS')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));
    await waitFor(() => expect(acc1SnapCalls).toBe(2));

    fireEvent.change(screen.getByPlaceholderText('股票代码（例如 600519）'), { target: { value: '600519' } });
    fireEvent.change(screen.getByPlaceholderText('数量（必填）'), { target: { value: '10' } });
    fireEvent.change(screen.getByPlaceholderText('成交价（必填）'), { target: { value: '150' } });
    fireEvent.click(screen.getByRole('button', { name: '提交交易' }));

    expect(await screen.findByText('TRADE_WINNER')).toBeInTheDocument();

    await act(async () => {
      pendingFxReload.resolve(makeSnapshot({
        accountId: 1,
        fxStale: true,
        positions: [makePosition({ symbol: 'STALE_FX_SNAP', market: 'cn' })],
      }));
      await pendingFxReload.promise;
    });

    expect(await screen.findByText('汇率在线刷新已被禁用。')).toBeInTheDocument();
    expect(screen.getByText('TRADE_WINNER')).toBeInTheDocument();
    expect(screen.queryByText('STALE_FX_SNAP')).not.toBeInTheDocument();
  });

  it('ignores stale page 2 ledger responses after returning to page 1 fails (OR-COR-3c284948)', async () => {
    const pendingPage2 = deferredPromise<{
      items: Array<Record<string, unknown>>;
      total: number;
      page: number;
      pageSize: number;
    }>();

    getAccounts.mockResolvedValue(makeAccounts([{ id: 1, name: 'Main' }]));
    listTrades.mockResolvedValue({
      items: [
        {
          id: 101,
          accountId: 1,
          symbol: 'P1_RECORD',
          tradeDate: '2026-06-17',
          side: 'buy',
          quantity: 10,
          price: 100,
          fee: 0,
          tax: 0,
          tradeUid: null,
          currency: 'CNY',
          note: null,
          createdAt: '2026-06-17T00:00:00Z',
        },
      ],
      total: 25,
      page: 1,
      pageSize: 20,
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    expect(await screen.findByText(/P1_RECORD/)).toBeInTheDocument();
    expect(screen.getByText('第 1 / 2 页')).toBeInTheDocument();

    listTrades.mockReturnValueOnce(pendingPage2.promise);
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    await waitFor(() => {
      expect(listTrades).toHaveBeenLastCalledWith(expect.objectContaining({
        accountId: 1,
        page: 2,
      }));
    });
    expect(screen.getByText('第 2 / 2 页')).toBeInTheDocument();

    listTrades.mockRejectedValueOnce(new Error('Page 1 failed'));
    fireEvent.click(screen.getByRole('button', { name: '上一页' }));
    expect(await screen.findByText('Page 1 failed')).toBeInTheDocument();
    expect(screen.getByText('第 1 / 2 页')).toBeInTheDocument();

    await act(async () => {
      pendingPage2.resolve({
        items: [
          {
            id: 202,
            accountId: 1,
            symbol: 'STALE_PAGE2',
            tradeDate: '2026-06-16',
            side: 'sell',
            quantity: 5,
            price: 120,
            fee: 0,
            tax: 0,
            tradeUid: null,
            currency: 'CNY',
            note: null,
            createdAt: '2026-06-16T00:00:00Z',
          },
        ],
        total: 25,
        page: 2,
        pageSize: 20,
      });
      await pendingPage2.promise;
    });

    expect(screen.getByText('第 1 / 2 页')).toBeInTheDocument();
    expect(screen.queryByText(/STALE_PAGE2/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '删除' })).not.toBeInTheDocument();
  });

  it('scopes submit locks and draft clearing to the submitting account (OR-COR-415c24bc)', async () => {
    const pendingTradeA = deferredPromise<{ id: number }>();
    const pendingCorpA = deferredPromise<{ id: number }>();

    getAccounts.mockResolvedValue(makeAccounts([{ id: 1, name: 'Main' }, { id: 2, name: 'Alt' }]));
    createTrade.mockImplementation(async ({ accountId }: { accountId: number }) => {
      if (accountId === 1) return pendingTradeA.promise;
      return { id: 2 };
    });
    createCorporateAction.mockImplementation(async ({ accountId }: { accountId: number }) => {
      if (accountId === 1) return pendingCorpA.promise;
      return { id: 4 };
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: 1, costMethod: 'fifo', includeRealtime: false }));

    const tradeSymbolInput = screen.getByPlaceholderText('股票代码（例如 600519）') as HTMLInputElement;
    fireEvent.change(tradeSymbolInput, { target: { value: '600519' } });
    fireEvent.change(screen.getByPlaceholderText('数量（必填）'), { target: { value: '10' } });
    fireEvent.change(screen.getByPlaceholderText('成交价（必填）'), { target: { value: '150' } });
    fireEvent.click(screen.getByRole('button', { name: '提交交易' }));

    await waitFor(() => expect(createTrade).toHaveBeenCalledWith(expect.objectContaining({
      accountId: 1,
      symbol: '600519',
    })));
    expect(screen.getByRole('button', { name: '提交交易' })).toBeDisabled();

    fireEvent.change(accountSelect, { target: { value: '2' } });
    expect(screen.getByRole('button', { name: '提交交易' })).not.toBeDisabled();
    fireEvent.change(tradeSymbolInput, { target: { value: '000001' } });

    await act(async () => {
      pendingTradeA.resolve({ id: 1 });
      await pendingTradeA.promise;
    });

    expect(tradeSymbolInput.value).toBe('000001');
    fireEvent.click(screen.getByRole('button', { name: '提交交易' }));
    await waitFor(() => expect(createTrade).toHaveBeenCalledWith(expect.objectContaining({
      accountId: 2,
      symbol: '000001',
    })));
    await waitFor(() => expect(tradeSymbolInput.value).toBe(''));

    // Same account isolation holds for corporate actions.
    fireEvent.change(accountSelect, { target: { value: '1' } });
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: 1, costMethod: 'fifo', includeRealtime: false }));

    const corpSymbolInput = screen.getByPlaceholderText('股票代码') as HTMLInputElement;
    fireEvent.change(corpSymbolInput, { target: { value: '600519' } });
    fireEvent.change(screen.getByPlaceholderText('每股分红'), { target: { value: '1.5' } });
    fireEvent.click(screen.getByRole('button', { name: '提交企业行为' }));

    await waitFor(() => expect(createCorporateAction).toHaveBeenCalledWith(expect.objectContaining({
      accountId: 1,
      symbol: '600519',
    })));
    expect(screen.getByRole('button', { name: '提交企业行为' })).toBeDisabled();

    fireEvent.change(accountSelect, { target: { value: '2' } });
    expect(screen.getByRole('button', { name: '提交企业行为' })).not.toBeDisabled();
    fireEvent.change(corpSymbolInput, { target: { value: '000001' } });

    await act(async () => {
      pendingCorpA.resolve({ id: 3 });
      await pendingCorpA.promise;
    });

    expect(corpSymbolInput.value).toBe('000001');
    fireEvent.click(screen.getByRole('button', { name: '提交企业行为' }));
    await waitFor(() => expect(createCorporateAction).toHaveBeenCalledWith(expect.objectContaining({
      accountId: 2,
      symbol: '000001',
    })));
    await waitFor(() => expect(corpSymbolInput.value).toBe(''));
  });

  it('clears prior account risk on switch and commits B initial risk even if a newer snapshot lands first (OR-COR-1f94e076)', async () => {
    const pendingRiskBFirst = deferredPromise<ReturnType<typeof makeRisk>>();
    const pendingRiskBAfterTrade = deferredPromise<ReturnType<typeof makeRisk>>();
    let bSnapCalls = 0;
    let bRiskCalls = 0;

    getAccounts.mockResolvedValue(makeAccounts([{ id: 1, name: 'Main' }, { id: 2, name: 'Alt' }]));
    getSnapshot.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 1) {
        return makeSnapshot({
          accountId: 1,
          fxStale: false,
          positions: [makePosition({ symbol: 'POS_ACC_A', market: 'cn' })],
        });
      }
      if (accountId === 2) {
        bSnapCalls += 1;
        return makeSnapshot({
          accountId: 2,
          fxStale: false,
          positions: [makePosition({ symbol: bSnapCalls === 1 ? 'POS_B_INIT' : 'POS_B_TRADE', market: 'us' })],
        });
      }
      return makeSnapshot({ accountId: 1, accountCount: 2, fxStale: false });
    });
    getRisk.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 1) {
        return makeRisk({
          accountId: 1,
          drawdown: { seriesPoints: 5, maxDrawdownPct: 18.5, currentDrawdownPct: 7.2, alert: true, fxStale: false },
          stopLoss: { nearAlert: true, triggeredCount: 1, nearCount: 2, items: [] },
        });
      }
      if (accountId === 2) {
        bRiskCalls += 1;
        if (bRiskCalls === 1) return pendingRiskBFirst.promise;
        return pendingRiskBAfterTrade.promise;
      }
      return makeRisk({ accountId: null });
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    expect(await screen.findByText('POS_ACC_A')).toBeInTheDocument();
    expect(await screen.findAllByText(/最大回撤: 18\.50%/)).toHaveLength(2);

    fireEvent.change(accountSelect, { target: { value: '2' } });
    expect(screen.queryAllByText(/18\.50%/)).toHaveLength(0);
    expect(await screen.findByText('POS_B_INIT')).toBeInTheDocument();
    expect(screen.queryAllByText(/18\.50%/)).toHaveLength(0);
    await waitFor(() => expect(bRiskCalls).toBe(1));

    // Submit a trade on account B so post-trade snapshot commits while post-trade risk stays pending.
    fireEvent.change(screen.getByPlaceholderText('股票代码（例如 600519）'), { target: { value: 'AAPL' } });
    fireEvent.change(screen.getByPlaceholderText('数量（必填）'), { target: { value: '5' } });
    fireEvent.change(screen.getByPlaceholderText('成交价（必填）'), { target: { value: '200' } });
    fireEvent.click(screen.getByRole('button', { name: '提交交易' }));

    expect(await screen.findByText('POS_B_TRADE')).toBeInTheDocument();
    await waitFor(() => expect(bRiskCalls).toBe(2));

    await act(async () => {
      pendingRiskBFirst.resolve(makeRisk({
        accountId: 2,
        drawdown: { seriesPoints: 5, maxDrawdownPct: 4.25, currentDrawdownPct: 1.1, alert: false, fxStale: false },
        stopLoss: { nearAlert: false, triggeredCount: 0, nearCount: 1, items: [] },
      }));
      await pendingRiskBFirst.promise;
    });

    expect(await screen.findAllByText(/最大回撤: 4\.25%/)).toHaveLength(2);
    expect(screen.queryAllByText(/18\.50%/)).toHaveLength(0);
  });

  it('clears unedited manual trade and corporate action drafts when account A succeeds while viewing account B (OR-COR-16b3b9a9)', async () => {
    const pendingTradeA = deferredPromise<{ id: number }>();
    const pendingCorpA = deferredPromise<{ id: number }>();

    getAccounts.mockResolvedValue(makeAccounts([{ id: 1, name: 'Main' }, { id: 2, name: 'Alt' }]));
    createTrade.mockReturnValueOnce(pendingTradeA.promise);
    createCorporateAction.mockReturnValueOnce(pendingCorpA.promise);

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: 1, costMethod: 'fifo', includeRealtime: false }));

    const tradeSymbolInput = screen.getByPlaceholderText('股票代码（例如 600519）') as HTMLInputElement;
    fireEvent.change(tradeSymbolInput, { target: { value: '600519' } });
    fireEvent.change(screen.getByPlaceholderText('数量（必填）'), { target: { value: '10' } });
    fireEvent.change(screen.getByPlaceholderText('成交价（必填）'), { target: { value: '150' } });
    fireEvent.click(screen.getByRole('button', { name: '提交交易' }));
    await waitFor(() => expect(createTrade).toHaveBeenCalledTimes(1));

    // Switch to account B without editing the form, then resolve account A's trade.
    fireEvent.change(accountSelect, { target: { value: '2' } });
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: 2, costMethod: 'fifo', includeRealtime: false }));

    await act(async () => {
      pendingTradeA.resolve({ id: 10 });
      await pendingTradeA.promise;
    });

    // Switch back to account A: already-submitted draft must be cleared so clicking submit cannot duplicate it.
    fireEvent.change(accountSelect, { target: { value: '1' } });
    await waitFor(() => expect(tradeSymbolInput.value).toBe(''));
    fireEvent.click(screen.getByRole('button', { name: '提交交易' }));
    expect(createTrade).toHaveBeenCalledTimes(1);

    // Same guarantee for corporate actions.
    const corpSymbolInput = screen.getByPlaceholderText('股票代码') as HTMLInputElement;
    fireEvent.change(corpSymbolInput, { target: { value: '600519' } });
    fireEvent.change(screen.getByPlaceholderText('每股分红'), { target: { value: '1.5' } });
    fireEvent.click(screen.getByRole('button', { name: '提交企业行为' }));
    await waitFor(() => expect(createCorporateAction).toHaveBeenCalledTimes(1));

    fireEvent.change(accountSelect, { target: { value: '2' } });
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: 2, costMethod: 'fifo', includeRealtime: false }));

    await act(async () => {
      pendingCorpA.resolve({ id: 20 });
      await pendingCorpA.promise;
    });

    fireEvent.change(accountSelect, { target: { value: '1' } });
    await waitFor(() => expect(corpSymbolInput.value).toBe(''));
    fireEvent.click(screen.getByRole('button', { name: '提交企业行为' }));
    expect(createCorporateAction).toHaveBeenCalledTimes(1);
  });

  it('scopes CSV commit results and dry-run labels per account across concurrent imports (OR-COR-b6e0fe05)', async () => {
    const pendingCommitA = deferredPromise<{
      accountId: number;
      recordCount: number;
      insertedCount: number;
      duplicateCount: number;
      failedCount: number;
      dryRun: boolean;
      errors: string[];
    }>();
    const pendingCommitB = deferredPromise<{
      accountId: number;
      recordCount: number;
      insertedCount: number;
      duplicateCount: number;
      failedCount: number;
      dryRun: boolean;
      errors: string[];
    }>();

    getAccounts.mockResolvedValue(makeAccounts([{ id: 1, name: 'AccA' }, { id: 2, name: 'AccB' }]));
    commitCsvImport.mockImplementation(async (accountId: number) => (
      accountId === 1 ? pendingCommitA.promise : pendingCommitB.promise
    ));

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    await waitFor(() => expect(getSnapshot).toHaveBeenLastCalledWith({ accountId: 1, costMethod: 'fifo', includeRealtime: false }));

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).not.toBeNull();
    const csvFile = new File(['date,symbol\n2026-06-18,600519'], 'trades.csv', { type: 'text/csv' });
    fireEvent.change(fileInput, { target: { files: [csvFile] } });

    const dryRunCheckbox = screen.getByLabelText('仅预演（不写入）') as HTMLInputElement;
    expect(dryRunCheckbox.checked).toBe(true);
    fireEvent.click(dryRunCheckbox);
    expect(dryRunCheckbox.checked).toBe(false);

    // Start real CSV import in account A.
    fireEvent.click(screen.getByRole('button', { name: '提交导入' }));
    await waitFor(() => expect(commitCsvImport).toHaveBeenCalledWith(1, 'huatai', csvFile, false));

    // Switch to account B and run dry-run import.
    fireEvent.change(accountSelect, { target: { value: '2' } });
    fireEvent.click(dryRunCheckbox);
    expect(dryRunCheckbox.checked).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '提交导入' }));
    await waitFor(() => expect(commitCsvImport).toHaveBeenCalledWith(2, 'huatai', csvFile, true));

    // B finishes first.
    await act(async () => {
      pendingCommitB.resolve({
        accountId: 2,
        recordCount: 5,
        insertedCount: 5,
        duplicateCount: 0,
        failedCount: 0,
        dryRun: true,
        errors: [],
      });
      await pendingCommitB.promise;
    });

    expect(await screen.findByText('CSV 预演结果')).toBeInTheDocument();
    expect(screen.getByText('预演检查：写入 5 条，重复 0 条，失败 0 条。')).toBeInTheDocument();

    // A finishes second with partial failures while B is still active.
    await act(async () => {
      pendingCommitA.resolve({
        accountId: 1,
        recordCount: 3,
        insertedCount: 2,
        duplicateCount: 0,
        failedCount: 1,
        dryRun: false,
        errors: ['row 3 invalid'],
      });
      await pendingCommitA.promise;
    });

    // While viewing B, B's dry-run result remains shown and unchecking dry-run does NOT relabel it as real write.
    expect(screen.getByText('CSV 预演结果')).toBeInTheDocument();
    expect(screen.getByText('预演检查：写入 5 条，重复 0 条，失败 0 条。')).toBeInTheDocument();
    fireEvent.click(dryRunCheckbox);
    expect(dryRunCheckbox.checked).toBe(false);
    expect(screen.getByText('CSV 预演结果')).toBeInTheDocument();
    expect(screen.getByText('预演检查：写入 5 条，重复 0 条，失败 0 条。')).toBeInTheDocument();
    expect(screen.queryByText(/实际写入：写入 5 条/)).not.toBeInTheDocument();

    // Switch back to account A: A's own real-write partial failure result is preserved accurately.
    fireEvent.change(accountSelect, { target: { value: '1' } });
    expect(await screen.findByText('CSV 提交结果')).toBeInTheDocument();
    expect(screen.getByText('实际写入：写入 2 条，重复 0 条，失败 1 条。')).toBeInTheDocument();
    expect(screen.queryByText(/写入 5 条/)).not.toBeInTheDocument();

    // Toggling dry-run back on while viewing A must NOT relabel A's real write as dry-run.
    fireEvent.click(dryRunCheckbox);
    expect(dryRunCheckbox.checked).toBe(true);
    expect(screen.getByText('CSV 提交结果')).toBeInTheDocument();
    expect(screen.getByText('实际写入：写入 2 条，重复 0 条，失败 1 条。')).toBeInTheDocument();
  });

  it('rejects stale snapshot and risk responses after newer refresh or FX reload failures (OR-COR-1ba30f06)', async () => {
    const staleSnap1 = deferredPromise<ReturnType<typeof makeSnapshot>>();
    const staleRisk1 = deferredPromise<ReturnType<typeof makeRisk>>();
    const staleTradeSnapBeforeFxFail = deferredPromise<ReturnType<typeof makeSnapshot>>();
    const staleTradeRiskBeforeFxFail = deferredPromise<ReturnType<typeof makeRisk>>();
    const pendingFxCall1 = deferredPromise<{
      asOf: string;
      accountCount: number;
      pairCount: number;
      updatedCount: number;
      staleCount: number;
      errorCount: number;
    }>();
    const pendingFxCall2 = deferredPromise<{
      asOf: string;
      accountCount: number;
      pairCount: number;
      updatedCount: number;
      staleCount: number;
      errorCount: number;
    }>();

    let acc1SnapCall = 0;
    let acc1RiskCall = 0;
    getSnapshot.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 1) {
        acc1SnapCall += 1;
        if (acc1SnapCall === 1) {
          return makeSnapshot({
            accountId: 1,
            fxStale: false,
            positions: [makePosition({ symbol: 'INIT_POS', market: 'cn' })],
          });
        }
        if (acc1SnapCall === 2) {
          return staleSnap1.promise;
        }
        if (acc1SnapCall === 3) {
          throw createApiError(createParsedApiError({ title: '快照失败', message: 'Snapshot 503 after trade' }));
        }
        if (acc1SnapCall === 4) {
          return makeSnapshot({
            accountId: 1,
            fxStale: false,
            positions: [makePosition({ symbol: 'BEFORE_RISK_FAIL', market: 'cn' })],
          });
        }
        if (acc1SnapCall === 5) {
          return makeSnapshot({
            accountId: 1,
            fxStale: false,
            positions: [makePosition({ symbol: 'AFTER_TRADE_RISK_FAIL', market: 'cn' })],
          });
        }
        if (acc1SnapCall === 6) {
          return staleTradeSnapBeforeFxFail.promise;
        }
        if (acc1SnapCall === 7) {
          throw createApiError(createParsedApiError({ title: 'FX 快照失败', message: 'FX snapshot 503' }));
        }
        return makeSnapshot({
          accountId: 1,
          fxStale: false,
          positions: [makePosition({ symbol: 'FX_RISK_FAIL_POS', market: 'cn' })],
        });
      }
      return makeSnapshot({ accountId: 1, fxStale: false });
    });

    getRisk.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 1) {
        acc1RiskCall += 1;
        if (acc1RiskCall === 2) {
          return staleRisk1.promise;
        }
        if (acc1RiskCall === 3) {
          throw createApiError(createParsedApiError({ title: '风险失败', message: 'Risk 503 after trade' }));
        }
        if (acc1RiskCall === 4) {
          return staleTradeRiskBeforeFxFail.promise;
        }
        if (acc1RiskCall === 5) {
          throw createApiError(createParsedApiError({ title: 'FX 风险失败', message: 'FX risk 503' }));
        }
      }
      return makeRisk({ accountId: accountId ?? null });
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    expect(await screen.findByText('INIT_POS')).toBeInTheDocument();

    // Case 1: Normal refresh snapshot #2 fails with 503 while stale snapshot #1 is in flight.
    fireEvent.click(screen.getByRole('button', { name: '刷新数据' }));
    await waitFor(() => expect(acc1SnapCall).toBe(2));

    fireEvent.change(screen.getByPlaceholderText('股票代码（例如 600519）'), { target: { value: '600519' } });
    fireEvent.change(screen.getByPlaceholderText('数量（必填）'), { target: { value: '10' } });
    fireEvent.change(screen.getByPlaceholderText('成交价（必填）'), { target: { value: '150' } });
    fireEvent.click(screen.getByRole('button', { name: '提交交易' }));

    expect(await screen.findByText('Snapshot 503 after trade')).toBeInTheDocument();
    expect(screen.getByText('持仓快照不可用')).toBeInTheDocument();

    await act(async () => {
      staleSnap1.resolve(makeSnapshot({
        accountId: 1,
        fxStale: false,
        positions: [makePosition({ symbol: 'STALE_PRE_TRADE_HOLDING', market: 'cn' })],
      }));
      await staleSnap1.promise;
    });

    expect(screen.getByText('Snapshot 503 after trade')).toBeInTheDocument();
    expect(screen.getByText('持仓快照不可用')).toBeInTheDocument();
    expect(screen.queryByText('STALE_PRE_TRADE_HOLDING')).not.toBeInTheDocument();

    // Case 2: Normal refresh risk #2 fails with 503 while stale risk #1 is in flight.
    fireEvent.click(screen.getByRole('button', { name: '刷新数据' }));
    expect(await screen.findByText('BEFORE_RISK_FAIL')).toBeInTheDocument();
    await waitFor(() => expect(acc1RiskCall).toBe(2));

    fireEvent.change(screen.getByPlaceholderText('股票代码（例如 600519）'), { target: { value: '000001' } });
    fireEvent.change(screen.getByPlaceholderText('数量（必填）'), { target: { value: '20' } });
    fireEvent.change(screen.getByPlaceholderText('成交价（必填）'), { target: { value: '12' } });
    fireEvent.click(screen.getByRole('button', { name: '提交交易' }));

    expect(await screen.findByText('AFTER_TRADE_RISK_FAIL')).toBeInTheDocument();
    expect(await screen.findByText('Risk 503 after trade')).toBeInTheDocument();
    expect(screen.getByText('风险模块降级')).toBeInTheDocument();

    await act(async () => {
      staleRisk1.resolve(makeRisk({
        accountId: 1,
        drawdown: { seriesPoints: 5, maxDrawdownPct: 12.34, currentDrawdownPct: 3.21, alert: true, fxStale: false },
      }));
      await staleRisk1.promise;
    });

    expect(screen.getByText('Risk 503 after trade')).toBeInTheDocument();
    expect(screen.getByText('风险模块降级')).toBeInTheDocument();
    expect(screen.queryByText(/12\.34%/)).not.toBeInTheDocument();

    // Case 3: FX reload snapshot failure rejects older in-flight trade snapshot.
    refreshFx.mockImplementationOnce(() => pendingFxCall1.promise);
    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));
    expect(await screen.findByRole('button', { name: '刷新中...' })).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText('股票代码（例如 600519）'), { target: { value: '600519' } });
    fireEvent.change(screen.getByPlaceholderText('数量（必填）'), { target: { value: '5' } });
    fireEvent.change(screen.getByPlaceholderText('成交价（必填）'), { target: { value: '160' } });
    fireEvent.click(screen.getByRole('button', { name: '提交交易' }));
    await waitFor(() => expect(acc1SnapCall).toBe(6));

    await act(async () => {
      pendingFxCall1.resolve({
        asOf: '2026-03-19',
        accountCount: 1,
        pairCount: 1,
        updatedCount: 1,
        staleCount: 0,
        errorCount: 0,
      });
      await pendingFxCall1.promise;
    });

    expect(await screen.findByText('FX snapshot 503')).toBeInTheDocument();
    expect(screen.getByText('无法确认持仓数量或估值，请刷新重试。')).toBeInTheDocument();

    await act(async () => {
      staleTradeSnapBeforeFxFail.resolve(makeSnapshot({
        accountId: 1,
        fxStale: false,
        positions: [makePosition({ symbol: 'STALE_BEFORE_FX_SNAP_FAIL', market: 'cn' })],
      }));
      await staleTradeSnapBeforeFxFail.promise;
    });

    expect(await screen.findByText('持仓快照不可用')).toBeInTheDocument();
    expect(screen.getByText('FX snapshot 503')).toBeInTheDocument();
    expect(screen.queryByText('STALE_BEFORE_FX_SNAP_FAIL')).not.toBeInTheDocument();

    // Case 4: FX reload risk failure rejects older in-flight trade risk.
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新汇率' })).toBeEnabled());
    refreshFx.mockImplementationOnce(() => pendingFxCall2.promise);
    fireEvent.click(screen.getByRole('button', { name: '刷新汇率' }));
    expect(await screen.findByRole('button', { name: '刷新中...' })).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText('股票代码（例如 600519）'), { target: { value: '000001' } });
    fireEvent.change(screen.getByPlaceholderText('数量（必填）'), { target: { value: '5' } });
    fireEvent.change(screen.getByPlaceholderText('成交价（必填）'), { target: { value: '13' } });
    fireEvent.click(screen.getByRole('button', { name: '提交交易' }));
    await waitFor(() => expect(acc1RiskCall).toBe(4));

    await act(async () => {
      pendingFxCall2.resolve({
        asOf: '2026-03-19',
        accountCount: 1,
        pairCount: 1,
        updatedCount: 1,
        staleCount: 0,
        errorCount: 0,
      });
      await pendingFxCall2.promise;
    });

    expect(await screen.findByText('FX risk 503')).toBeInTheDocument();
    expect(screen.getByText('风险模块降级')).toBeInTheDocument();

    await act(async () => {
      staleTradeRiskBeforeFxFail.resolve(makeRisk({
        accountId: 1,
        drawdown: { seriesPoints: 5, maxDrawdownPct: 23.45, currentDrawdownPct: 4.56, alert: true, fxStale: false },
      }));
      await staleTradeRiskBeforeFxFail.promise;
    });

    expect(screen.getByText('FX risk 503')).toBeInTheDocument();
    expect(screen.getByText('风险模块降级')).toBeInTheDocument();
    expect(screen.queryByText(/23\.45%/)).not.toBeInTheDocument();
  });

  it('shows an explicit events error state instead of empty ledger when snapshot succeeds after events 503 (OR-COR-16d45fb3)', async () => {
    const pendingSnapshotB = deferredPromise<ReturnType<typeof makeSnapshot>>();
    let acc2TradeCalls = 0;

    getAccounts.mockResolvedValue(makeAccounts([
      { id: 1, name: 'AccA' },
      { id: 2, name: 'AccB' },
    ]));
    getSnapshot.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 1) {
        return makeSnapshot({
          accountId: 1,
          fxStale: false,
          positions: [makePosition({ symbol: 'POS_A', market: 'cn' })],
        });
      }
      if (accountId === 2) {
        return pendingSnapshotB.promise;
      }
      return makeSnapshot({ accountId: 1, accountCount: 2, fxStale: false });
    });
    listTrades.mockImplementation(async ({ accountId }: { accountId?: number } = {}) => {
      if (accountId === 1) {
        return {
          items: [{
            id: 11,
            accountId: 1,
            symbol: 'TRADE_A',
            tradeDate: '2026-06-18',
            side: 'buy',
            quantity: 10,
            price: 100,
            fee: 0,
            tax: 0,
            currency: 'CNY',
            note: null,
            createdAt: '2026-06-18T00:00:00Z',
          }],
          total: 1,
          page: 1,
          pageSize: 20,
        };
      }
      if (accountId === 2) {
        acc2TradeCalls += 1;
        if (acc2TradeCalls === 1) {
          throw createApiError(createParsedApiError({ title: '流水接口异常', message: 'Events ledger 503' }));
        }
        return {
          items: [{
            id: 22,
            accountId: 2,
            symbol: 'TRADE_B',
            tradeDate: '2026-06-18',
            side: 'buy',
            quantity: 5,
            price: 200,
            fee: 0,
            tax: 0,
            currency: 'USD',
            note: null,
            createdAt: '2026-06-18T00:00:00Z',
          }],
          total: 1,
          page: 1,
          pageSize: 20,
        };
      }
      return { items: [], total: 0, page: 1, pageSize: 20 };
    });

    render(<PortfolioPage />);
    await waitForInitialLoad();

    const accountSelect = screen.getAllByRole('combobox')[0];
    fireEvent.change(accountSelect, { target: { value: '1' } });
    expect(await screen.findByText(/TRADE_A/)).toBeInTheDocument();

    // Switch to account B: events fetch fails with 503 before snapshot resolves.
    fireEvent.change(accountSelect, { target: { value: '2' } });
    expect(await screen.findByText('流水加载失败')).toBeInTheDocument();
    expect(screen.getByText('Events ledger 503')).toBeInTheDocument();

    // Now account B's snapshot succeeds (clearing global error).
    await act(async () => {
      pendingSnapshotB.resolve(makeSnapshot({
        accountId: 2,
        fxStale: false,
        positions: [makePosition({ symbol: 'POS_B', market: 'us' })],
      }));
      await pendingSnapshotB.promise;
    });

    expect(await screen.findByText('POS_B')).toBeInTheDocument();
    expect(screen.getByText('流水加载失败')).toBeInTheDocument();
    expect(screen.getByText('Events ledger 503')).toBeInTheDocument();
    expect(screen.queryByText('暂无流水')).not.toBeInTheDocument();
    expect(screen.queryByText(/TRADE_A/)).not.toBeInTheDocument();

    // Refreshing events clears the error and shows account B's real ledger rows.
    fireEvent.click(screen.getByRole('button', { name: '刷新流水' }));
    expect(await screen.findByText(/TRADE_B/)).toBeInTheDocument();
    expect(screen.queryByText('流水加载失败')).not.toBeInTheDocument();
    expect(screen.queryByText('暂无流水')).not.toBeInTheDocument();
  });
});
