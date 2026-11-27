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
  Legend: () => null,
  Tooltip: () => null,
  Area: () => null,
  Line: () => null,
  ReferenceLine: ({ y }: { y?: number }) => <div data-testid={`ref-line-${y}`} />,
}));

describe('ReportStrategy Levels Chart', () => {
  beforeEach(() => {
    mockGetStockHistory.mockReset();
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

    const toggle = screen.getByRole('button', { name: '价格点位图' });
    fireEvent.click(toggle);
    expect(screen.queryByTestId('composed-chart')).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.getByTestId('composed-chart')).toBeInTheDocument();
    expect(mockGetStockHistory).toHaveBeenCalledTimes(1);
  });

  it('passes the saved report price to the chart scale guard', async () => {
    mockGetStockHistory.mockResolvedValue({
      data: [{ date: '2026-11-20', open: 19, high: 21, low: 18, close: 20 }],
    });

    render(
      <ReportStrategy
        recordId={78}
        stockCode="TSLA"
        currentPrice={100}
        strategy={{ idealBuy: '95', stopLoss: '80', takeProfit: '120' }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '价格点位图' }));
    expect(await screen.findByText('报告点位与当前行情价格口径不一致，暂不叠加参考线。')).toBeInTheDocument();
    expect(screen.queryByTestId(/^ref-line-/)).not.toBeInTheDocument();
  });

  it.each([
    { currentPrice: 105, close: 52.5, label: 'a two-for-one scale change' },
    { currentPrice: undefined, close: 21, label: 'a historical report without a saved price' },
  ])('hides levels for $label', async ({ currentPrice, close }) => {
    mockGetStockHistory.mockResolvedValue({
      data: [{ date: '2026-11-20', open: close, high: close, low: close, close }],
    });

    render(
      <ReportStrategy
        recordId={79}
        stockCode="TSLA"
        currentPrice={currentPrice}
        historical
        strategy={{ idealBuy: '95', stopLoss: '80', takeProfit: '120' }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '价格点位图' }));
    expect(await screen.findByText('报告点位与当前行情价格口径不一致，暂不叠加参考线。')).toBeInTheDocument();
    expect(screen.queryByTestId(/^ref-line-/)).not.toBeInTheDocument();
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

  it('invalidates a request when leaving and returning to the same report', async () => {
    let resolveStale!: (value: unknown) => void;
    mockGetStockHistory
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveStale = resolve;
      }))
      .mockResolvedValueOnce({
        data: [{ date: '2026-11-20', open: 220, high: 230, low: 215, close: 225 }],
      });

    const { rerender } = render(
      <ReportStrategy recordId={104} stockCode="TSLA" strategy={{ idealBuy: '220' }} />,
    );
    fireEvent.click(screen.getByRole('button', { name: '价格点位图' }));
    await waitFor(() => expect(mockGetStockHistory).toHaveBeenCalledTimes(1));

    rerender(<ReportStrategy recordId={105} stockCode="AAPL" strategy={{ idealBuy: '185' }} />);
    rerender(<ReportStrategy recordId={104} stockCode="TSLA" strategy={{ idealBuy: '220' }} />);

    const toggle = screen.getByRole('button', { name: '价格点位图' });
    expect(toggle).toBeEnabled();
    fireEvent.click(toggle);
    expect(await screen.findByText('225.00')).toBeInTheDocument();

    await act(async () => {
      resolveStale({ data: [{ date: '2026-11-20', open: 995, high: 1000, low: 990, close: 999 }] });
    });
    expect(screen.getByText('225.00')).toBeInTheDocument();
    expect(screen.queryByText('999.00')).not.toBeInTheDocument();
  });

  it.each(['resolves', 'rejects'])('can fetch again when a stale request later %s', async (outcome) => {
    let settleStale!: () => void;
    mockGetStockHistory
      .mockImplementationOnce(() => new Promise((resolve, reject) => {
        settleStale = outcome === 'resolves'
          ? () => resolve({ data: [{ date: '2026-11-20', open: 995, high: 1000, low: 990, close: 999 }] })
          : () => reject(new Error('Stale request failed'));
      }))
      .mockResolvedValueOnce({
        data: [{ date: '2026-11-20', open: 220, high: 230, low: 215, close: 225 }],
      });

    const tsla = <ReportStrategy recordId={101} stockCode="TSLA" strategy={{ idealBuy: '220' }} />;
    const { rerender } = render(tsla);
    fireEvent.click(screen.getByRole('button', { name: '价格点位图' }));
    expect(screen.getByRole('button', { name: '加载行情...' })).toBeDisabled();

    rerender(<ReportStrategy recordId={102} stockCode="AAPL" strategy={{ idealBuy: '185' }} />);
    expect(screen.getByRole('button', { name: '价格点位图' })).toBeEnabled();
    rerender(tsla);
    expect(mockGetStockHistory).toHaveBeenCalledTimes(1);

    const toggle = screen.getByRole('button', { name: '价格点位图' });
    expect(toggle).toBeEnabled();
    fireEvent.click(toggle);
    expect(await screen.findByText('225.00')).toBeInTheDocument();
    expect(mockGetStockHistory).toHaveBeenNthCalledWith(2, 'TSLA', 60, 'daily');

    await act(async () => settleStale());
    expect(screen.getByText('225.00')).toBeInTheDocument();
    expect(screen.queryByText('999.00')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('localizes the Korean chart toggle, loading state, and empty retry', async () => {
    mockGetStockHistory
      .mockResolvedValueOnce({ data: [] })
      .mockResolvedValueOnce({
        data: [{ date: '2026-11-20', open: 220, high: 230, low: 215, close: 225 }],
      });

    render(<ReportStrategy recordId={103} stockCode="TSLA" language="ko" strategy={{ idealBuy: '220' }} />);
    fireEvent.click(screen.getByRole('button', { name: '가격대 차트' }));
    expect(screen.getByRole('button', { name: '시세 불러오는 중...' })).toBeDisabled();
    expect(await screen.findByText('사용할 수 있는 일봉 시세가 없습니다.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('225.00')).toBeInTheDocument();
    expect(mockGetStockHistory).toHaveBeenCalledTimes(2);
  });

  it('offers a localized retry after an HTTP error and renders recovered prices', async () => {
    mockGetStockHistory
      .mockRejectedValueOnce({ response: { status: 500, data: { detail: '获取历史行情失败' } } })
      .mockResolvedValueOnce({
        data: [{ date: '2026-11-20', open: 220, high: 230, low: 215, close: 225 }],
      });

    render(<ReportStrategy recordId={103} stockCode="TSLA" language="ko" strategy={{ idealBuy: '220' }} />);
    fireEvent.click(screen.getByRole('button', { name: '가격대 차트' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('일봉 시세를 불러오지 못했습니다.');

    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('225.00')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(mockGetStockHistory).toHaveBeenCalledTimes(2);
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

  it('forwards priceAdjustment and ohlcSynthesized metadata to ReportPriceLevelsChart', async () => {
    const splitBars = Array.from({ length: 15 }, (_, i) => ({
      date: `2026-10-${String(i + 1).padStart(2, '0')}`,
      open: 0,
      high: 0,
      low: 0,
      close: i === 14 ? 50 : 100,
    }));
    mockGetStockHistory.mockResolvedValueOnce({
      stockCode: 'AAPL',
      period: 'daily',
      priceAdjustment: 'unadjusted',
      ohlcSynthesized: true,
      data: splitBars,
    });

    render(
      <ReportStrategy
        recordId={99}
        stockCode="AAPL"
        language="zh"
        strategy={{ idealBuy: '48', stopLoss: '45', takeProfit: '60' }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '价格点位图' }));
    expect(await screen.findByText(/未复权历史行情/)).toBeInTheDocument();
    expect(screen.queryByText(/年化波动:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/回撤:/)).not.toBeInTheDocument();
  });
});
