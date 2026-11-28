import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ReportOverview } from '../ReportOverview';
import { parseReportMarketSnapshot } from '../../../utils/reportDashboard';

describe('ReportOverview market snapshot and Copy Brief', () => {
  const writeTextMock = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: writeTextMock },
      configurable: true,
    });
  });

  it('extracts camelCase and snake_case market snapshots and returns null when empty', () => {
    expect(parseReportMarketSnapshot(undefined)).toBeNull();
    expect(parseReportMarketSnapshot({ rawResult: {} })).toBeNull();

    const camel = parseReportMarketSnapshot({
      contextSnapshot: {
        enhancedContext: {
          realtime: {
            open: 1680.5,
            high: 1712.0,
            low: 1675.0,
            amplitude: 2.2,
            volumeRatio: 1.45,
            turnoverRate: 0.38,
            peRatio: 24.6,
            pbRatio: 7.12,
          },
        },
      },
    });
    expect(camel).toEqual({
      open: 1680.5,
      high: 1712.0,
      low: 1675.0,
      amplitude: 2.2,
      volumeRatio: 1.45,
      turnoverRate: 0.38,
      peRatio: 24.6,
      pbRatio: 7.12,
    });

    const snake = parseReportMarketSnapshot({
      contextSnapshot: {
        realtime: {
          open: 10.2,
          high: 10.8,
          low: 10.0,
          volume_ratio: 2.1,
          turnover_rate: '3.5%',
          pe_ratio: 15.2,
          pb_ratio: 1.65,
        },
      },
    });
    expect(snake).toEqual({
      open: 10.2,
      high: 10.8,
      low: 10.0,
      amplitude: undefined,
      volumeRatio: 2.1,
      turnoverRate: 3.5,
      peRatio: 15.2,
      pbRatio: 1.65,
    });
  });

  it('renders market snapshot strip when available and omits it when absent', () => {
    const baseMeta = {
      queryId: 'q-snap',
      stockCode: '600519',
      stockName: '贵州茅台',
      reportType: 'detailed' as const,
      reportLanguage: 'en' as const,
      createdAt: '2026-11-23T08:00:00Z',
      currentPrice: 1700,
      changePct: 1.5,
    };
    const baseSummary = {
      analysisSummary: 'Momentum remains constructive',
      operationAdvice: 'Buy',
      trendPrediction: 'Bullish',
      sentimentScore: 82,
    };

    const { rerender } = render(
      <ReportOverview
        meta={baseMeta}
        summary={baseSummary}
        details={{
          contextSnapshot: {
            enhancedContext: {
              realtime: {
                open: 1680,
                high: 1712,
                low: 1675,
                volumeRatio: 1.35,
                turnoverRate: 0.42,
                peRatio: 24.6,
                pbRatio: 7.1,
              },
            },
          },
        }}
      />,
    );

    const region = screen.getByRole('region', { name: 'Market & Valuation' });
    expect(region).toHaveTextContent('Open');
    expect(region).toHaveTextContent('1680.00');
    expect(region).toHaveTextContent('1712.00 / 1675.00');
    expect(region).toHaveTextContent('24.6');

    rerender(<ReportOverview meta={baseMeta} summary={baseSummary} details={{ rawResult: {} }} />);
    expect(screen.queryByRole('region', { name: 'Market & Valuation' })).not.toBeInTheDocument();
  });

  it('copies a structured decision brief including strategy levels and snapshot to clipboard', async () => {
    render(
      <ReportOverview
        meta={{
          id: 42,
          queryId: 'q-copy',
          stockCode: '600519',
          stockName: '贵州茅台',
          reportType: 'detailed',
          reportLanguage: 'zh',
          createdAt: '2026-11-23T08:00:00Z',
          currentPrice: 1700,
          changePct: 1.5,
        }}
        summary={{
          analysisSummary: '依托均线支撑温和放量',
          operationAdvice: '买入',
          trendPrediction: '震荡上行',
          sentimentScore: 82,
        }}
        strategy={{
          idealBuy: '1650',
          stopLoss: '1580',
          takeProfit: '1820',
        }}
        details={{
          contextSnapshot: {
            realtime: {
              open: 1680,
              high: 1710,
              low: 1670,
              peRatio: 24.5,
            },
          },
          rawResult: {
            dashboard: {
              intelligence: {
                riskAlerts: ['注意量能持续性'],
              },
            },
          },
        }}
      />,
    );

    const copyBtn = screen.getByRole('button', { name: '复制要点' });
    fireEvent.click(copyBtn);

    await waitFor(() => expect(writeTextMock).toHaveBeenCalledTimes(1));
    const copied = writeTextMock.mock.calls[0][0] as string;
    expect(copied).toContain('贵州茅台 (600519)');
    expect(copied).toContain('1700.00 (+1.50%)');
    expect(copied).toContain('理想买入: 1650');
    expect(copied).toContain('止损价位: 1580');
    expect(copied).toContain('注意量能持续性');
    expect(copied).toContain('开盘 1680.00');
    expect(await screen.findByRole('button', { name: '已复制' })).toBeInTheDocument();
  });
});
