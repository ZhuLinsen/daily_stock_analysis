import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { BacktestEquityPoint, PerformanceMetrics } from '../../../types/backtest';
import { BacktestQuantInsights } from '../BacktestQuantInsights';

function makePerf(overrides: Partial<PerformanceMetrics> = {}): PerformanceMetrics {
  return {
    scope: 'overall',
    evalWindowDays: 10,
    engineVersion: 'v1.1',
    totalEvaluations: 4,
    completedCount: 4,
    insufficientCount: 0,
    longCount: 4,
    cashCount: 0,
    winCount: 3,
    lossCount: 1,
    neutralCount: 0,
    directionAccuracyPct: 75,
    winRatePct: 75,
    neutralRatePct: 0,
    avgStockReturnPct: 4.2,
    avgSimulatedReturnPct: 5.1,
    stopLossTriggerRate: 10,
    takeProfitTriggerRate: 50,
    ambiguousRate: 0,
    avgDaysToFirstHit: 3.0,
    adviceBreakdown: {},
    diagnostics: {},
    ...overrides,
  };
}

describe('BacktestQuantInsights', () => {
  it('prepends 0% origin and renders zero reference line when curve starts at index 1', () => {
    const equityCurve: BacktestEquityPoint[] = [
      { index: 1, date: '2026-03-01', code: '600519', returnPct: 5.0, equityPct: 5.0, outcome: 'win' },
      { index: 2, date: '2026-03-02', code: 'AAPL', returnPct: -7.0, equityPct: -2.0, outcome: 'loss' },
      { index: 3, date: '2026-03-03', code: '00700', returnPct: 10.2, equityPct: 8.0, outcome: 'win' },
    ];
    const perf = makePerf({
      quantMetrics: {
        sampleCount: 3,
        activeTradeCount: 3,
        profitFactor: 2.17,
        expectancyPct: 2.73,
        cumulativeReturnPct: 8.0,
        maxDrawdownPct: 7.0,
        equityCurve,
      },
    });

    const { container } = render(
      <BacktestQuantInsights overallPerf={perf} stockPerf={null} language="en" />,
    );

    const svg = screen.getByRole('img', { name: 'Chronological Simulated Equity Curve' });
    const polyline = svg.querySelector('polyline');
    expect(polyline).not.toBeNull();
    expect(polyline?.getAttribute('points')?.trim().split(/\s+/)).toHaveLength(4);
    expect(container.querySelector('svg line')).not.toBeNull();
    expect(screen.getByText('2026-03-01')).toBeInTheDocument();
  });

  it('avoids 0% cliff, omits off-range zero line, and clamps baseline for sliced trailing curves', () => {
    const equityCurve: BacktestEquityPoint[] = [
      { index: 11, date: '2026-03-11', code: '600519', returnPct: 2.0, equityPct: 15.0, outcome: 'win' },
      { index: 12, date: '2026-03-12', code: 'AAPL', returnPct: 2.6, equityPct: 18.0, outcome: 'win' },
      { index: 13, date: '2026-03-13', code: '00700', returnPct: -1.7, equityPct: 16.0, outcome: 'loss' },
      { index: 14, date: '2026-03-14', code: '600519', returnPct: 5.2, equityPct: 22.0, outcome: 'win' },
    ];
    const perf = makePerf({
      quantMetrics: {
        sampleCount: 4,
        activeTradeCount: 4,
        profitFactor: 4.5,
        expectancyPct: 2.03,
        cumulativeReturnPct: 22.0,
        maxDrawdownPct: 1.7,
        equityCurve,
      },
    });

    const { container } = render(
      <BacktestQuantInsights overallPerf={perf} stockPerf={null} language="en" />,
    );

    const svg = screen.getByRole('img', { name: 'Chronological Simulated Equity Curve' });
    const polyline = svg.querySelector('polyline');
    expect(polyline).not.toBeNull();
    expect(polyline?.getAttribute('points')?.trim().split(/\s+/)).toHaveLength(4);
    expect(container.querySelector('svg line')).toBeNull();

    const pathD = svg.querySelector('path')?.getAttribute('d') ?? '';
    const moveMatch = pathD.match(/^M\s+([0-9.-]+),([0-9.-]+)/);
    expect(moveMatch).not.toBeNull();
    const baselineY = Number(moveMatch?.[2]);
    expect(baselineY).toBeGreaterThanOrEqual(8);
    expect(baselineY).toBeLessThanOrEqual(76);

    expect(screen.getByText('#11 · 2026-03-11')).toBeInTheDocument();
    expect(screen.getByText('#14 · 2026-03-14')).toBeInTheDocument();
    expect(screen.getByText('Showing latest 4 trades (starts at #11, not 0% origin)')).toBeInTheDocument();
  });

  it('hydrates snake_case diagnostics.quant_metrics fallback and localizes advice labels in EN mode', () => {
    const perf = makePerf({
      quantMetrics: undefined,
      adviceBreakdown: {
        强烈买入: { total: 2, win: 2, loss: 0, neutral: 0, winRatePct: 100 },
      },
      diagnostics: {
        quant_metrics: {
          sample_count: 2,
          active_trade_count: 2,
          profit_factor: 3.1,
          expectancy_pct: 4.5,
          cumulative_return_pct: 9.2,
          max_drawdown_pct: 2.0,
          equity_curve: [
            { index: 1, date: '2026-03-10', equity_pct: 4.5 },
            { index: 2, date: '2026-03-12', equity_pct: 9.2 },
          ],
        },
      },
    });

    render(<BacktestQuantInsights overallPerf={perf} stockPerf={null} language="en" />);

    expect(screen.getByText('3.10')).toBeInTheDocument();
    expect(screen.getByText('+9.20%')).toBeInTheDocument();
    expect(screen.getByText('Strong Buy')).toBeInTheDocument();
    expect(screen.queryByText('强烈买入')).not.toBeInTheDocument();
  });

  it('omits the equity curve SVG instead of plotting 0% when equityPct contains null overflow points', () => {
    const perf = makePerf({
      quantMetrics: {
        sampleCount: 1800,
        activeTradeCount: 1800,
        profitFactor: null,
        expectancyPct: 50.0,
        cumulativeReturnPct: null,
        maxDrawdownPct: 0.0,
        equityCurve: [
          { index: 1799, date: '2026-03-01', code: '600519', returnPct: 50.0, equityPct: null, outcome: 'win' },
          { index: 1800, date: '2026-03-02', code: 'AAPL', returnPct: 50.0, equityPct: null, outcome: 'win' },
        ],
      },
    });

    render(<BacktestQuantInsights overallPerf={perf} stockPerf={null} language="en" />);

    expect(screen.queryByRole('img', { name: 'Chronological Simulated Equity Curve' })).not.toBeInTheDocument();
    expect(screen.getByText('+50.00%')).toBeInTheDocument();
    expect(screen.getByText('0.00%')).toBeInTheDocument();
  });
});
