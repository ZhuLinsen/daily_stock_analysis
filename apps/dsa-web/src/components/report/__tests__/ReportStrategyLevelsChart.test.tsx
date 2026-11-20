import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  ReferenceLine: () => null,
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
});
