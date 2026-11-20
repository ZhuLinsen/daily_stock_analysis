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
  it('parses strategy price strings while ignoring MA periods and percentage-only text', () => {
    expect(parseStrategyPriceLevel('1480元')).toBe(1480);
    expect(parseStrategyPriceLevel('$210.50')).toBe(210.5);
    expect(parseStrategyPriceLevel('1,480 - 1,500')).toBe(1480);
    expect(parseStrategyPriceLevel('次优买入点：1680元')).toBe(1680);
    expect(parseStrategyPriceLevel('--')).toBeNull();
    // Counterexample OR-COR-cf3ffd9f / b51586cb: MA period numbers are not entry prices
    expect(parseStrategyPriceLevel('暂无理想买点：需先收复并站稳MA5（52.68）且放量')).toBeNull();
    expect(parseStrategyPriceLevel('放量收复MA10（55.13）确认趋势反转后介入')).toBeNull();
    expect(parseStrategyPriceLevel('+12%')).toBeNull();

    // Counterexample OR-COR-5fddb93d: compute rolling averages then cap display to 60 trading sessions
    const bars87 = Array.from({ length: 87 }, (_, i) => ({
      date: `2026-08-${String(i + 1).padStart(2, '0')}`,
      open: 100 + i,
      high: 101 + i,
      low: 99 + i,
      close: 100 + i,
    }));
    const capped = enrichBarsWithMovingAverages(bars87, 60);
    expect(capped).toHaveLength(60);
    expect(capped[0].date).toBe('2026-08-28');
    expect(capped[0].ma20).not.toBeNull();
    expect(capped[59].date).toBe('2026-08-87');
  });

  it('renders close, secondaryBuy, and sniper reference lines or empty retry button gracefully', () => {
    const onRetry = vi.fn();
    const { rerender } = render(<ReportPriceLevelsChart bars={[]} language="zh" onRetry={onRetry} />);
    expect(screen.getByText('暂无可用的日线历史行情数据。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument();

    // Counterexample OR-COR-85f33008 / 3380828d: secondaryBuy must appear in summary & ReferenceLine
    rerender(
      <ReportPriceLevelsChart
        bars={[
          { date: '2026-11-18', open: 1490, high: 1510, low: 1480, close: 1500 },
          { date: '2026-11-19', open: 1500, high: 1530, low: 1495, close: 1525 },
        ]}
        strategy={{ idealBuy: '1480元', secondaryBuy: '次优买入点：1680元', stopLoss: '1400元', takeProfit: '1700元' }}
        language="zh"
      />,
    );

    expect(screen.getByTestId('composed-chart')).toBeInTheDocument();
    expect(screen.getByTestId('ref-line-1480')).toBeInTheDocument();
    expect(screen.getByTestId('ref-line-1680')).toBeInTheDocument();
    expect(screen.getByTestId('ref-line-1400')).toBeInTheDocument();
    expect(screen.getByTestId('ref-line-1700')).toBeInTheDocument();
    expect(screen.getByText('次优买点:')).toBeInTheDocument();
  });
});
