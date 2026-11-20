import { render, screen } from '@testing-library/react';
import type React from 'react';
import { describe, expect, it, vi } from 'vitest';
import {
  enrichBarsWithMovingAverages,
  parseStrategyPriceLevel,
} from '../../../utils/priceChart';
import { ReportPriceLevelsChart } from '../ReportPriceLevelsChart';

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

describe('ReportPriceLevelsChart helpers & component', () => {
  it('parses strategy numeric price strings and computes MA5', () => {
    expect(parseStrategyPriceLevel('1480元')).toBe(1480);
    expect(parseStrategyPriceLevel('$210.50')).toBe(210.5);
    expect(parseStrategyPriceLevel('1,480 - 1,500')).toBe(1480);
    expect(parseStrategyPriceLevel('--')).toBeNull();

    const enriched = enrichBarsWithMovingAverages([
      { date: '2026-11-12', open: 10, high: 11, low: 9, close: 10 },
      { date: '2026-11-13', open: 10, high: 12, low: 10, close: 12 },
      { date: '2026-11-14', open: 12, high: 14, low: 11, close: 14 },
      { date: '2026-11-15', open: 14, high: 16, low: 13, close: 16 },
      { date: '2026-11-16', open: 16, high: 19, low: 15, close: 18 },
    ]);
    expect(enriched[3].ma5).toBeNull();
    expect(enriched[4].ma5).toBe(14);
  });

  it('renders close & sniper reference lines or empty message gracefully', () => {
    const { rerender } = render(<ReportPriceLevelsChart bars={[]} language="zh" />);
    expect(screen.getByText('暂无可用的日线历史行情数据。')).toBeInTheDocument();

    rerender(
      <ReportPriceLevelsChart
        bars={[
          { date: '2026-11-18', open: 1490, high: 1510, low: 1480, close: 1500 },
          { date: '2026-11-19', open: 1500, high: 1530, low: 1495, close: 1525 },
        ]}
        strategy={{ idealBuy: '1480元', stopLoss: '1400元', takeProfit: '1700元' }}
        language="zh"
      />,
    );

    expect(screen.getByTestId('composed-chart')).toBeInTheDocument();
    expect(screen.getByTestId('ref-line-1480')).toBeInTheDocument();
    expect(screen.getByTestId('ref-line-1400')).toBeInTheDocument();
    expect(screen.getByTestId('ref-line-1700')).toBeInTheDocument();
  });
});
