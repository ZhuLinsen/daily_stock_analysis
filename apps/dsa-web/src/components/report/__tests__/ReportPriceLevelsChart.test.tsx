import { render, screen } from '@testing-library/react';
import React from 'react';
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
  Legend: () => null,
  Tooltip: ({ content }: { content: React.ReactElement<{ active?: boolean; payload?: unknown }> }) => (
    <div data-testid="levels-tooltip">
      {React.cloneElement(content, {
        active: true,
        payload: [{ payload: { date: '2026-11-20', close: 225 } }],
      })}
    </div>
  ),
  Area: () => null,
  Line: () => null,
  ReferenceLine: ({ y, label }: { y?: number; label?: { value: string } }) => (
    <div data-testid={`ref-line-${y}`}>{label?.value}</div>
  ),
}));

describe('ReportPriceLevelsChart helpers & component', () => {
  it('parses strategy price strings while ignoring MA periods and percentage-only text', () => {
    expect(parseStrategyPriceLevel('1480元')).toBe(1480);
    expect(parseStrategyPriceLevel('$210.50')).toBe(210.5);
    expect(parseStrategyPriceLevel('1,480 - 1,500')).toBe(1480);
    expect(parseStrategyPriceLevel('次优买入点：1680元')).toBe(1680);
    expect(parseStrategyPriceLevel('--')).toBeNull();
    expect(parseStrategyPriceLevel('暂无理想买点：需先收复并站稳MA5（52.68）且放量')).toBeNull();
    expect(parseStrategyPriceLevel('放量收复MA10（55.13）确认趋势反转后介入')).toBeNull();
    expect(parseStrategyPriceLevel('Wait for the 5- and 20-day moving averages to turn higher')).toBeNull();
    expect(parseStrategyPriceLevel('Wait for a reclaim of the 20-period moving average')).toBeNull();
    expect(parseStrategyPriceLevel('Wait for the 5/20-day moving averages to turn higher')).toBeNull();
    expect(parseStrategyPriceLevel('Wait for the 5, 10, and 20-day moving averages to turn higher')).toBeNull();
    expect(parseStrategyPriceLevel('Wait for the 5 and 20 periods to align')).toBeNull();
    expect(parseStrategyPriceLevel('Wait for the 5/20 MA crossover')).toBeNull();
    expect(parseStrategyPriceLevel('Wait for the 20D moving average to turn higher')).toBeNull();
    expect(parseStrategyPriceLevel('1st target: $60')).toBe(60);
    expect(parseStrategyPriceLevel('1차 목표가 53,000원')).toBe(53000);
    expect(parseStrategyPriceLevel('1차 목표가 53000')).toBe(53000);
    expect(parseStrategyPriceLevel('第1个止盈目标：60')).toBe(60);
    expect(parseStrategyPriceLevel('首个止盈目标：风险回报比 2:1，止盈 60 元')).toBe(60);
    expect(parseStrategyPriceLevel('+12%')).toBeNull();
    expect(parseStrategyPriceLevel('-2.5')).toBeNull();
  });

  it('computes MA5 and MA20 using earlier sessions before capping the plot to 60 bars', () => {
    const bars = Array.from({ length: 87 }, (_, i) => ({
      date: new Date(Date.UTC(2026, 6, 6 + Math.floor(i / 5) * 7 + i % 5)).toISOString().slice(0, 10),
      open: 100 + i,
      high: 101 + i,
      low: 99 + i,
      close: 100 + i,
    }));
    const capped = enrichBarsWithMovingAverages([...bars].reverse());
    expect(capped).toHaveLength(60);
    expect(capped[0]).toMatchObject({ date: bars[27].date, ma5: 125, ma20: 117.5 });
    expect(capped[59].date).toBe(bars[86].date);
  });

  it('renders close, secondaryBuy, and sniper reference lines or empty retry button gracefully', () => {
    const onRetry = vi.fn();
    const { rerender } = render(<ReportPriceLevelsChart bars={[]} language="zh" onRetry={onRetry} />);
    expect(screen.getByText('暂无可用的日线历史行情数据。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新加载' })).toBeInTheDocument();

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

  it.each([
    '暂无理想买点：需先收复并站稳MA 5（52.68）且放量',
    '放量站稳 MA 5/10（52.68元）之后再评估',
    'Wait for a reclaim of the 20-day moving average',
    'Wait for MA 5 (52.68) and 1.5x average volume',
    'Wait for MA 5 (52.68',
    '20일 이동평균선 회복 대기',
  ])('omits the period-only buy level in "%s"', (idealBuy) => {
    render(
      <ReportPriceLevelsChart
        bars={[{ date: '2026-11-20', open: 52, high: 55, low: 51, close: 54 }]}
        strategy={{ idealBuy }}
      />,
    );

    expect(screen.getByTestId('composed-chart')).toBeInTheDocument();
    expect(screen.queryByTestId(/^ref-line-/)).not.toBeInTheDocument();
    expect(screen.queryByText('理想买点:')).not.toBeInTheDocument();
  });

  it('finds the trading price after moving-average periods', () => {
    expect(parseStrategyPriceLevel('站稳 MA   20 后在 52.68 元买入')).toBe(52.68);
    expect(parseStrategyPriceLevel('Reclaim the 20-day moving average, then buy at $52.68')).toBe(52.68);
    expect(parseStrategyPriceLevel('Reclaim MA 5 (52.68), then buy at $54')).toBe(54);
    expect(parseStrategyPriceLevel('Target 52.68 with 10% upside')).toBe(52.68);
  });

  it('localizes Korean chart summaries and reference lines', () => {
    render(
      <ReportPriceLevelsChart
        bars={[{ date: '2026-11-20', open: 220, high: 230, low: 215, close: 225 }]}
        strategy={{ idealBuy: '220', secondaryBuy: '215', stopLoss: '200', takeProfit: '260' }}
        language="ko"
      />,
    );

    expect(screen.getByText('최근 종가:')).toBeInTheDocument();
    expect(screen.getByText('종가:')).toBeInTheDocument();
    expect(screen.getByText('이상적 매수가:')).toBeInTheDocument();
    expect(screen.getByText('추가 매수가:')).toBeInTheDocument();
    expect(screen.getByText('손절가:')).toBeInTheDocument();
    expect(screen.getByText('목표가:')).toBeInTheDocument();
    expect(screen.getByTestId('ref-line-220')).toHaveTextContent('매수 220');
    expect(screen.getByTestId('ref-line-215')).toHaveTextContent('추가 매수 215');
    expect(screen.getByTestId('ref-line-200')).toHaveTextContent('손절 200');
    expect(screen.getByTestId('ref-line-260')).toHaveTextContent('목표 260');
  });
});
