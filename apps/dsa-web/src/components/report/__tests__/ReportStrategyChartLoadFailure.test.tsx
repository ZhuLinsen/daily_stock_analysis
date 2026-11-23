import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ReportStrategy } from '../ReportStrategy';

const { mockGetStockHistory } = vi.hoisted(() => ({
  mockGetStockHistory: vi.fn(),
}));

vi.mock('../../../api/stocks', () => ({
  stocksApi: {
    getHistory: mockGetStockHistory,
  },
}));

vi.mock('../ReportPriceLevelsChart', () => {
  throw new Error('price chart chunk unavailable');
});

describe('ReportStrategy chart chunk failure', () => {
  it('keeps the report visible when the optional chart module cannot load', async () => {
    mockGetStockHistory.mockResolvedValue({
      data: [{ date: '2026-11-20', open: 220, high: 230, low: 215, close: 225 }],
    });

    render(
      <ReportStrategy
        recordId={77}
        stockCode="TSLA"
        language="zh"
        strategy={{ idealBuy: '220' }}
      />,
    );

    expect(screen.getByText('220')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '价格点位图' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('日线行情加载失败。');
    expect(screen.getByText('220')).toBeInTheDocument();
  });
});
