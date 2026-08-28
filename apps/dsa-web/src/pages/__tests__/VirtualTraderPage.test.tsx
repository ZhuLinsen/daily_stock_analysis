import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { VirtualTraderPage } from '../VirtualTraderPage';
import type {
  VirtualTraderAccount,
  VirtualTraderEquityCurve,
  VirtualTraderPredictionList,
  VirtualTraderStats,
  VirtualTraderTradeList,
} from '../../types/virtualTrader';

const hoisted = vi.hoisted(() => ({
  getAccount: vi.fn(),
  listTrades: vi.fn(),
  listPredictions: vi.fn(),
  getEquityCurve: vi.fn(),
  getStats: vi.fn(),
  run: vi.fn(),
  reset: vi.fn(),
}));

vi.mock('../../api/virtualTrader', () => ({
  virtualTraderApi: {
    getAccount: (...args: unknown[]) => hoisted.getAccount(...args),
    listTrades: (...args: unknown[]) => hoisted.listTrades(...args),
    listPredictions: (...args: unknown[]) => hoisted.listPredictions(...args),
    getEquityCurve: (...args: unknown[]) => hoisted.getEquityCurve(...args),
    getStats: (...args: unknown[]) => hoisted.getStats(...args),
    run: (...args: unknown[]) => hoisted.run(...args),
    reset: (...args: unknown[]) => hoisted.reset(...args),
  },
}));

const account: VirtualTraderAccount = {
  accountId: 1,
  name: 'default',
  status: 'active',
  initialCashCny: 1_000_000,
  cashCny: 120_000,
  cashHkd: 0,
  cashUsd: 0,
  cashTotalCny: 300_000,
  positions: [
    {
      id: 1,
      stockCode: '600519',
      name: '贵州茅台',
      market: 'cn',
      currency: 'CNY',
      quantity: 100,
      avgCost: 1500,
      lastPrice: 1600,
      marketValue: 160_000,
      marketValueCny: 160_000,
      unrealizedPnlPct: 6.67,
      realizedPnl: 0,
      status: 'open',
    },
  ],
  positionsValueCny: 700_000,
  totalValueCny: 1_010_000,
  totalReturnPct: 1.0,
};

const trades: VirtualTraderTradeList = {
  items: [
    {
      id: 1, stockCode: '600519', market: 'cn', side: 'buy', quantity: 100,
      price: 1500, fee: 37.5, currency: 'CNY', reason: '初始建仓（等权配置）',
      tradeDate: '2026-08-21',
    },
  ],
  total: 1, page: 1, pageSize: 30,
};

const predictions: VirtualTraderPredictionList = {
  items: [
    {
      id: 1, stockCode: '600519', market: 'cn', direction: 'up',
      anchorDate: '2026-08-21', horizonDays: 10, targetPrice: 1600, entryPrice: 1500,
      status: 'evaluated', outcome: 'hit', actualReturnPct: 4.2,
    },
  ],
  total: 1, page: 1, pageSize: 30,
};

const curve: VirtualTraderEquityCurve = {
  points: [
    { tradeDate: '2026-08-20', totalValueCny: 1_000_500, dailyReturnPct: null, positionsCount: 6 },
    { tradeDate: '2026-08-21', totalValueCny: 1_010_000, dailyReturnPct: 0.95, positionsCount: 6 },
  ],
  initialCashCny: 1_000_000,
};

const stats: VirtualTraderStats = {
  prediction: { pending: 0, hit: 1, miss: 0, unable: 0, total: 1 },
  totalTrades: 1, buyTrades: 1, sellTrades: 0, winRatePct: null, realizedPnlTotal: 0,
};

describe('VirtualTraderPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.getAccount.mockResolvedValue(account);
    hoisted.listTrades.mockResolvedValue(trades);
    hoisted.listPredictions.mockResolvedValue(predictions);
    hoisted.getEquityCurve.mockResolvedValue(curve);
    hoisted.getStats.mockResolvedValue(stats);
    hoisted.run.mockResolvedValue({ results: [] });
  });

  it('renders account stats, positions and equity curve', async () => {
    render(<VirtualTraderPage />);

    expect(await screen.findByText('¥1,010,000')).toBeInTheDocument();
    expect(screen.getByText('+1.00%')).toBeInTheDocument();
    expect(screen.getByText('100.0%')).toBeInTheDocument(); // hit rate
    expect(screen.getByText('贵州茅台')).toBeInTheDocument();
    expect(screen.getAllByText(/600519/).length).toBeGreaterThan(0);
    expect(screen.getByText('+6.67%')).toBeInTheDocument();
    // 曲线数据点足够时渲染净值曲线卡片标题
    expect(screen.getByText('净值曲线')).toBeInTheDocument();
  });

  it('shows empty placeholder before seeding', async () => {
    hoisted.getAccount.mockResolvedValue({
      ...account,
      status: 'not_seeded',
      positions: [],
      totalValueCny: 0,
      positionsValueCny: 0,
      totalReturnPct: 0,
    });
    render(<VirtualTraderPage />);

    expect(await screen.findByText('暂无持仓')).toBeInTheDocument();
  });

  it('runs the trader manually and reloads data', async () => {
    hoisted.run.mockResolvedValue({
      results: [
        { status: 'success' }, { status: 'skipped' }, { status: 'skipped' },
      ],
    });
    render(<VirtualTraderPage />);

    fireEvent.click(await screen.findByRole('button', { name: /立即运行/ }));
    await waitFor(() => expect(hoisted.run).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(hoisted.getAccount).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/1 个市场成交，2 个跳过/)).toBeInTheDocument();
  });

  it('reset requires dialog confirmation before calling the API', async () => {
    render(<VirtualTraderPage />);

    // The header button only opens the confirm dialog; the API stays untouched.
    fireEvent.click(await screen.findByRole('button', { name: /重置账户/ }));
    expect(await screen.findByText(/确定重置虚拟账户/)).toBeInTheDocument();
    expect(hoisted.reset).not.toHaveBeenCalled();

    // Cancel keeps the account untouched.
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(hoisted.reset).not.toHaveBeenCalled();

    // Confirming the dialog triggers the reset API. While the dialog is open
    // there are two 重置账户 buttons (header + dialog confirm); pick the latter.
    fireEvent.click(await screen.findByRole('button', { name: /重置账户/ }));
    const resetButtons = await screen.findAllByRole('button', { name: '重置账户' });
    fireEvent.click(resetButtons[resetButtons.length - 1]);
    await waitFor(() => expect(hoisted.reset).toHaveBeenCalledTimes(1));
  });
});
