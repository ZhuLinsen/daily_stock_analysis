import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ReportStrategy } from '../ReportStrategy';

const { mockGetStockHistory } = vi.hoisted(() => ({
  mockGetStockHistory: vi.fn(),
}));

vi.mock('../../../api/stocks', () => ({
  stocksApi: {
    getHistory: mockGetStockHistory,
  },
}));

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="recharts-container">{children}</div>,
  ComposedChart: ({ children }: { children: React.ReactNode }) => <div data-testid="composed-chart">{children}</div>,
  CartesianGrid: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  Area: () => null,
  Line: () => null,
  ReferenceLine: ({ y }: { y?: number }) => <div data-testid={`ref-line-${y}`} />,
}));

describe('ReportStrategy Levels Chart', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('hides chart toggle when recordId is missing or non-positive', () => {
    render(
      <ReportStrategy
        recordId={0}
        stockCode="600519"
        language="zh"
        strategy={{ idealBuy: '1480元', stopLoss: '1400元', takeProfit: '1700元' }}
      />,
    );
    expect(screen.queryByRole('button', { name: '价格点位图' })).not.toBeInTheDocument();
  });

  it('fetches 60D daily K-line history only when clicking Levels Chart', async () => {
    mockGetStockHistory.mockResolvedValue({
      stockCode: 'TSLA',
      period: 'daily',
      data: [{ date: '2026-11-20', open: 220, high: 230, low: 215, close: 225 }],
    });

    render(
      <ReportStrategy
        recordId={77}
        stockCode="TSLA"
        language="zh"
        strategy={{ idealBuy: '220', stopLoss: '200', takeProfit: '260' }}
      />,
    );

    expect(mockGetStockHistory).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '价格点位图' }));
    await waitFor(() => expect(mockGetStockHistory).toHaveBeenCalledWith('TSLA', 60, 'daily'));
    expect(await screen.findByTestId('composed-chart')).toBeInTheDocument();
  });

  it('isolates chart state and discards stale responses when switching reports', async () => {
    let resolveTsla!: (v: unknown) => void;
    mockGetStockHistory.mockImplementation((code: string) => {
      if (code === 'TSLA') {
        return new Promise((resolve) => {
          resolveTsla = resolve;
        });
      }
      return Promise.resolve({
        stockCode: 'AAPL',
        period: 'daily',
        data: [{ date: '2026-11-20', open: 190, high: 195, low: 188, close: 192 }],
      });
    });

    const { rerender } = render(
      <ReportStrategy
        recordId={101}
        stockCode="TSLA"
        language="zh"
        strategy={{ idealBuy: '220', stopLoss: '200', takeProfit: '260' }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '价格点位图' }));
    await waitFor(() => expect(mockGetStockHistory).toHaveBeenCalledWith('TSLA', 60, 'daily'));

    // Switch to AAPL before TSLA settles
    rerender(
      <ReportStrategy
        recordId={102}
        stockCode="AAPL"
        language="zh"
        strategy={{ idealBuy: '185', stopLoss: '175', takeProfit: '210' }}
      />,
    );
    expect(screen.queryByTestId('composed-chart')).not.toBeInTheDocument();

    // Stale TSLA response resolves and must NOT leak onto AAPL report
    await act(async () => {
      resolveTsla({
        stockCode: 'TSLA',
        period: 'daily',
        data: [{ date: '2026-11-20', open: 220, high: 230, low: 215, close: 999 }],
      });
    });
    expect(screen.queryByTestId('composed-chart')).not.toBeInTheDocument();
    expect(screen.queryByText('999.00')).not.toBeInTheDocument();

    // Expanding AAPL fetches AAPL bars cleanly
    fireEvent.click(screen.getByRole('button', { name: '价格点位图' }));
    await waitFor(() => expect(mockGetStockHistory).toHaveBeenCalledWith('AAPL', 60, 'daily'));
    expect(await screen.findByText('192.00')).toBeInTheDocument();
  });

  it('retries fetching when re-expanding after empty history array', async () => {
    mockGetStockHistory
      .mockResolvedValueOnce({ stockCode: '600519', period: 'daily', data: [] })
      .mockResolvedValueOnce({
        stockCode: '600519',
        period: 'daily',
        data: [{ date: '2026-11-20', open: 1490, high: 1510, low: 1480, close: 1505 }],
      });

    render(
      <ReportStrategy
        recordId={88}
        stockCode="600519"
        language="zh"
        strategy={{ idealBuy: '1480', stopLoss: '1400', takeProfit: '1700' }}
      />,
    );

    const toggleBtn = screen.getByRole('button', { name: '价格点位图' });
    fireEvent.click(toggleBtn);
    expect(await screen.findByText('暂无可用的日线历史行情数据。')).toBeInTheDocument();

    // Collapse then re-expand -> retries fetch instead of caching empty state forever
    fireEvent.click(toggleBtn);
    fireEvent.click(toggleBtn);
    await waitFor(() => expect(mockGetStockHistory).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('1505.00')).toBeInTheDocument();
  });
});
