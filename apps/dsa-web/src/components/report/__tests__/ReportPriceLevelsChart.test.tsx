import { fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import type { StockKLineItem } from '../../../api/stocks';
import {
  computeQuantTelemetry,
  enrichBarsWithMovingAverages,
  formatChartAxisPrice,
  parseStrategyPriceLevel,
} from '../../../utils/priceChart';
import { ReportPriceLevelsChart } from '../ReportPriceLevelsChart';

vi.mock('recharts', async () => {
  const ReactMod = await vi.importActual<typeof import('react')>('react');
  const ChartDataContext = ReactMod.createContext<unknown[]>([]);
  return {
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="recharts-container">{children}</div>
    ),
    ComposedChart: ({ data = [], children }: { data?: unknown[]; children: React.ReactNode }) => (
      <ChartDataContext.Provider value={data}>
        <div data-testid="composed-chart">{children}</div>
      </ChartDataContext.Provider>
    ),
    CartesianGrid: () => null,
    XAxis: ({ dataKey }: { dataKey?: string }) => <div data-testid="chart-xaxis" data-key={dataKey} />,
    YAxis: ({ domain }: { domain?: unknown }) => (
      <div data-testid="chart-yaxis" data-domain={JSON.stringify(domain)} />
    ),
    Legend: () => null,
    Tooltip: ({ content }: { content: React.ReactElement<{ active?: boolean; payload?: unknown }> }) => {
      const data = ReactMod.useContext(ChartDataContext);
      const latest = data.length > 0 ? data[data.length - 1] : null;
      return (
        <div data-testid="levels-tooltip">
          {ReactMod.cloneElement(content, {
            active: latest != null,
            payload: latest != null ? [{ payload: latest }] : [],
          })}
        </div>
      );
    },
    Area: () => null,
    Bar: ({ dataKey, children }: { dataKey?: string; children?: React.ReactNode }) => (
      <div data-testid={`chart-bar-${dataKey}`}>{children}</div>
    ),
    Cell: ({ fill }: { fill?: string }) => <span data-testid="chart-bar-cell" data-fill={fill} />,
    Line: () => null,
    ReferenceLine: ({ x, y, label }: { x?: string; y?: number; label?: { value: string } }) => {
      if (y != null) {
        return <div data-testid={`ref-line-${y}`}>{label?.value}</div>;
      }
      if (x != null) {
        return <div data-testid={`ref-line-x-${x}`}>{label?.value}</div>;
      }
      return null;
    },
  };
});

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
    expect(parseStrategyPriceLevel('等待收复 20 日均线后再评估')).toBeNull();
    expect(parseStrategyPriceLevel('20 일 이동평균선 회복 대기')).toBeNull();
    expect(parseStrategyPriceLevel('等待收复 5/20 日均线后再评估')).toBeNull();
    expect(parseStrategyPriceLevel('5/20일 이동평균선 회복 대기')).toBeNull();
    expect(parseStrategyPriceLevel('等待收复 5、10、20 日均线后再评估')).toBeNull();
    expect(parseStrategyPriceLevel('5·10·20일 이동평균선 회복 대기')).toBeNull();
    expect(parseStrategyPriceLevel('等待收复 5、10 和 20 日均线后再评估')).toBeNull();
    expect(parseStrategyPriceLevel('5 및 20일 이동평균선 회복 대기')).toBeNull();
    expect(parseStrategyPriceLevel('20일 이동평균선(52.68원) 회복 대기')).toBeNull();
    expect(parseStrategyPriceLevel('等待站稳 20 日均線（52.68元）再评估')).toBeNull();
    expect(parseStrategyPriceLevel('20일 이동 평균선(52.68원) 회복 대기')).toBeNull();
    expect(parseStrategyPriceLevel('Wait for the 20-day moving averages (52.68) to turn higher')).toBeNull();
    expect(parseStrategyPriceLevel('1st target: $60')).toBe(60);
    expect(parseStrategyPriceLevel('1차 목표가 53,000원')).toBe(53000);
    expect(parseStrategyPriceLevel('1차 목표가 53000')).toBe(53000);
    expect(parseStrategyPriceLevel('1차목표가 53000')).toBe(53000);
    expect(parseStrategyPriceLevel('第1个止盈目标：60')).toBe(60);
    expect(parseStrategyPriceLevel('首个止盈目标：风险回报比 2:1，止盈 60 元')).toBe(60);
    expect(parseStrategyPriceLevel('止盈目标：风险回报比 2∶1，止盈 60')).toBe(60);
    expect(parseStrategyPriceLevel('止盈目标：风险回报比 2/1，止盈 60')).toBe(60);
    expect(parseStrategyPriceLevel('Risk/reward ratio of 2 to 1, take profit at $60')).toBe(60);
    expect(parseStrategyPriceLevel('R/R 2 to 1, take profit at $60')).toBe(60);
    expect(parseStrategyPriceLevel('손익비 2/1, 목표가 60원')).toBe(60);
    expect(parseStrategyPriceLevel('止盈目标：60/65 元，分两批卖出')).toBe(60);
    expect(parseStrategyPriceLevel('止盈目标：60/65 元，分 2 批卖出')).toBe(60);
    expect(parseStrategyPriceLevel('Take profit target: $60/$65, sell in two batches')).toBe(60);
    expect(parseStrategyPriceLevel('止盈目标：风险回报比 2 比 1，止盈 $60')).toBe(60);
    expect(parseStrategyPriceLevel('Take profit at 60, above the current price of $50')).toBe(60);
    expect(parseStrategyPriceLevel('止损设在 48，当前价 50 元')).toBe(48);
    expect(parseStrategyPriceLevel('Current price: $50; take profit at 60')).toBe(60);
    expect(parseStrategyPriceLevel('止盈目标 60，当前价格 50 元')).toBe(60);
    expect(parseStrategyPriceLevel('当前价：50元，止损设在 48')).toBe(48);
    expect(parseStrategyPriceLevel('当前价：50元，暂不设止损')).toBeNull();
    expect(parseStrategyPriceLevel('当前价：约50元，止损设在 48')).toBe(48);
    expect(parseStrategyPriceLevel('当前价：约50元，暂不设止损')).toBeNull();
    expect(parseStrategyPriceLevel('当前价格约为 50 元，止损价格 48 元')).toBe(48);
    expect(parseStrategyPriceLevel('现价约为 50 元，暂无止损位')).toBeNull();
    expect(parseStrategyPriceLevel('Current price: approximately $50; take profit at 60')).toBe(60);
    expect(parseStrategyPriceLevel('止损位：跌破前低（48元）')).toBe(48);
    expect(parseStrategyPriceLevel('Stop-loss: ($48)')).toBe(48);
    expect(parseStrategyPriceLevel('止损：跌破 2026-11-20 的前低 48 元')).toBe(48);
    expect(parseStrategyPriceLevel('Stop-loss: below the Nov. 20 low at $48')).toBe(48);
    expect(parseStrategyPriceLevel('Stop-loss: below the Nov. 20, 2026 low at $48')).toBe(48);
    expect(parseStrategyPriceLevel('Stop-loss: below 20 Nov 2026 low at $48')).toBe(48);
    expect(parseStrategyPriceLevel('止盈目标：60/65 港元，风险回报比 2/1')).toBe(60);
    expect(parseStrategyPriceLevel('止盈目标：60/65 港元，计划分 2 批卖出（风险回报比 2/1）')).toBe(60);
    expect(parseStrategyPriceLevel('Stop-loss: below the 20 Nov low at $48')).toBe(48);
    expect(parseStrategyPriceLevel('止损：跌破 11/20 的前低 48 元')).toBe(48);
    expect(parseStrategyPriceLevel('Ideal buy: $48; 20-day moving-average confirmation required')).toBe(48);
    expect(parseStrategyPriceLevel('理想买入价：48；20日均线企稳后执行')).toBe(48);
    expect(parseStrategyPriceLevel('止损：连续2根K线收于48元下方')).toBe(48);
    expect(parseStrategyPriceLevel('Stop-loss: after 2 consecutive closes below $48')).toBe(48);
    expect(parseStrategyPriceLevel('等待收复5和20日均线后再评估')).toBeNull();
    expect(parseStrategyPriceLevel('5와 20일 이동평균선 회복 대기')).toBeNull();
    expect(parseStrategyPriceLevel('Risk-to-reward 2 to 1, take profit at $60')).toBe(60);
    expect(parseStrategyPriceLevel('손익 비율 2 to 1, 목표가 60원')).toBe(60);
    expect(parseStrategyPriceLevel('当前价格为：50 元，止损价格 48 元')).toBe(48);
    expect(parseStrategyPriceLevel('目前价格为：50 元，暂无止损位')).toBeNull();
    expect(parseStrategyPriceLevel('等待突破 20 日均线附近（52.68元）后评估')).toBeNull();
    expect(parseStrategyPriceLevel('20일 이동 평균선 부근(52.68원) 회복 대기')).toBeNull();
    expect(parseStrategyPriceLevel('止盈目标：60/65港币，风险回报比 2/1')).toBe(60);
    expect(parseStrategyPriceLevel('止盈目标：60/65港币，计划分 2 批卖出（风险回报比 2/1）')).toBe(60);
    expect(parseStrategyPriceLevel('Stop-loss: below the 20/11 low at $48')).toBe(48);
    expect(parseStrategyPriceLevel('止损：跌破 11月20号前低 48 元')).toBe(48);
    expect(parseStrategyPriceLevel('Ideal buy: $48, 20-day moving-average confirmation required')).toBe(48);
    expect(parseStrategyPriceLevel('理想买入价：48，20日均线企稳后执行')).toBe(48);
    expect(parseStrategyPriceLevel('止损：2次收盘低于48元')).toBe(48);
    expect(parseStrategyPriceLevel('Stop-loss: after 2 closes below $48')).toBe(48);
    expect(parseStrategyPriceLevel('8-9元')).toBe(8);
    expect(parseStrategyPriceLevel('8/9 港元')).toBe(8);
    expect(parseStrategyPriceLevel('止盈目标：150，160港元')).toBe(150);
    expect(parseStrategyPriceLevel('Stop-loss is 10 percent below entry')).toBeNull();
    expect(parseStrategyPriceLevel('손절: 매수가 대비 5 퍼센트 하락')).toBeNull();
    expect(parseStrategyPriceLevel('止损：RSI低于30且价格跌破48元时退出')).toBe(48);
    expect(parseStrategyPriceLevel('Stop-loss: if RSI drops below 30, exit at $48')).toBe(48);
    expect(parseStrategyPriceLevel('等待收复5及20日均线后再评估')).toBeNull();
    expect(parseStrategyPriceLevel('等待收复20日均线一带（52.68元）后再评估')).toBeNull();
    expect(parseStrategyPriceLevel('Reward-to-risk 2 to 1, take profit at $60')).toBe(60);
    expect(parseStrategyPriceLevel('当前价格：为50元，止损设在48元')).toBe(48);
    expect(parseStrategyPriceLevel('Stop-loss: below the 20/11/2026 low at $48')).toBe(48);
    expect(parseStrategyPriceLevel('Ideal buy: 48, 20-day moving-average confirmation required')).toBe(48);
    expect(parseStrategyPriceLevel('Stop loss: 48, 20-day moving-average confirmation required')).toBe(48);
    expect(parseStrategyPriceLevel('理想买入：48，20日均线企稳后执行')).toBe(48);
    expect(parseStrategyPriceLevel('止损：2次日线收盘低于48元')).toBe(48);
    expect(parseStrategyPriceLevel('Stop loss: after 2 daily closes below $48')).toBe(48);
    expect(parseStrategyPriceLevel('8-9美元')).toBe(8);
    expect(parseStrategyPriceLevel('止盈目标：8/9美元')).toBe(8);
    expect(parseStrategyPriceLevel('止盈目标：150.5,160港元')).toBe(150.5);
    expect(parseStrategyPriceLevel('止盈目标：1，480元')).toBe(1480);
    expect(parseStrategyPriceLevel('止损：较买入价下跌百分之5')).toBeNull();
    expect(parseStrategyPriceLevel('止损：若RSI高于70且价格跌破48元则退出')).toBe(48);
    expect(parseStrategyPriceLevel('Take profit when RSI rises above 70 and price reaches $60')).toBe(60);
    expect(parseStrategyPriceLevel('Ideal buy: $.50')).toBe(0.5);
    expect(parseStrategyPriceLevel('Stop loss: if price falls below 50¢')).toBe(0.5);
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

  it('does not treat condition metadata as strategy prices', () => {
    const cases: Array<[string, number | null]> = [
      ['等待收復5與20日均線後再評估', null],
      ['等待收复5与20日均线后再评估', null],
      ['止损：跌破48元且跌破5及20日均线', 48],
      ['Reward/risk 2 to 1, take profit at $60', 60],
      ['当前价格：为$50，止损设在48元', 48],
      ['等待站稳20日均线附近区域（52.68元）后再评估', null],
      ['止盈目标：60/65日元，计划分 2 批卖出（风险回报比 2/1）', 60],
      ['Stop-loss: below the 20/11/2026 and 19/11/2026 lows at $48', 48],
      ['Take profit: 60, 20-day moving average confirmation required', 60],
      ['次优买入：48，20日均线企稳后执行', 48],
      ['Stop loss: after 2 consecutive daily closes below $48', 48],
      ['理想买入：8/9新台币', 8],
      ['止盈目标：123,456元', 123456],
      ['止盈目标：1,234,567.89元', 1234567.89],
      ['止损：较买入价下跌百分之约5', null],
      ['Stop loss: 5 per cent below entry', null],
      ['止损：若RSI回落至30以下且价格跌破48元则退出', 48],
      ['止损：跌破 MA20（止损设在48元）', 48],
      ['Take profit when RSI climbs above 70 and price reaches $60', 60],
      ['Ideal buy: $1.20 (20¢ below current price)', 1.2],
      ['止损：暂无固定止损位，持仓成本52元', null],
      ['Stop-loss: none; entry price $52', null],
    ];
    for (const [input, expected] of cases) {
      expect(parseStrategyPriceLevel(input), input).toBe(expected);
    }
  });

  it('preserves sub-cent moving-average precision', () => {
    const bars = Array.from({ length: 20 }, (_, i) => ({
      date: `2026-01-${String(i + 1).padStart(2, '0')}`,
      open: 0.0056,
      high: 0.0056,
      low: 0.0056,
      close: 0.0056,
    }));
    const last = enrichBarsWithMovingAverages(bars).at(-1);
    expect(last?.ma5).toBeCloseTo(0.0056, 10);
    expect(last?.ma20).toBeCloseTo(0.0056, 10);
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

  it('does not overlay saved levels when the report and current bars use different price scales', () => {
    render(
      <ReportPriceLevelsChart
        bars={[{ date: '2026-11-20', open: 19, high: 21, low: 18, close: 20 }]}
        strategy={{ idealBuy: '95', stopLoss: '80', takeProfit: '120' }}
        reportCurrentPrice={100}
      />,
    );

    expect(screen.getByRole('status')).toHaveTextContent('价格口径不一致');
    expect(screen.queryByTestId(/^ref-line-/)).not.toBeInTheDocument();
  });

  it('formats axis prices cleanly and merges identical reference lines with historical report notice', () => {
    expect(formatChartAxisPrice(71.7832)).toBe('71.78');
    expect(formatChartAxisPrice(1523.45)).toBe('1523');
    expect(formatChartAxisPrice(0.4567)).toBe('0.457');

    render(
      <ReportPriceLevelsChart
        bars={[
          { date: '2026-08-21', open: 68, high: 70, low: 66, close: 69 },
          { date: '2026-11-20', open: 33, high: 34, low: 32, close: 32.86 },
        ]}
        strategy={{ secondaryBuy: '47.47元', stopLoss: '跌破47.47元离场', takeProfit: '55.13元' }}
        reportDate="2026-08-02 21:01:53"
        language="zh"
      />,
    );

    expect(screen.getByRole('status')).toHaveTextContent('2026-08-02');
    expect(screen.getByTestId('ref-line-47.47')).toHaveTextContent('次/损 47.47');
    expect(screen.getByTestId('ref-line-55.13')).toHaveTextContent('盈 55.13');
  });

  it('computes BOLL, MA60, RSI(14), MACD, KDJ, ATR, and quantitative risk telemetry accurately', () => {
    const uptrendBars: StockKLineItem[] = Array.from({ length: 75 }, (_, i) => {
      const date = new Date(Date.UTC(2026, 0, i + 1)).toISOString().slice(0, 10);
      const wave = (i % 5 === 0 ? -0.4 : 0.9);
      const close = Number((100 + i * 0.75 + wave).toFixed(2));
      return {
        date,
        open: close - 0.5,
        high: close + 1.2,
        low: close - 1.1,
        close,
        volume: 100000 + i * 500,
      };
    });

    const enriched = enrichBarsWithMovingAverages(uptrendBars, 60);
    expect(enriched).toHaveLength(60);
    const last = enriched[enriched.length - 1];
    expect(last.ma60).not.toBeNull();
    expect(last.bollUpper).not.toBeNull();
    expect(last.bollMid).toBeCloseTo(last.ma20 ?? 0, 8);
    expect(last.bollLower).not.toBeNull();
    expect((last.bollUpper ?? 0)).toBeGreaterThan((last.bollLower ?? 0));
    expect(last.rsi14).toBeGreaterThan(55);
    expect(last.rsi14).toBeLessThanOrEqual(100);
    expect(last.macdDif).not.toBeNull();
    expect(last.macdDea).not.toBeNull();
    expect(last.macdHist).not.toBeNull();
    expect(last.kdjK).not.toBeNull();
    expect(last.kdjD).not.toBeNull();
    expect(last.kdjJ).not.toBeNull();
    expect(last.atrPct).toBeGreaterThan(0);

    const flatBars: StockKLineItem[] = Array.from({ length: 25 }, (_, i) => ({
      date: `2026-03-${String(i + 1).padStart(2, '0')}`,
      open: 50,
      high: 50.2,
      low: 49.8,
      close: 50,
    }));
    const flatTelemetry = computeQuantTelemetry(enrichBarsWithMovingAverages(flatBars, 60));
    expect(flatTelemetry.bollBandwidthPct).toBe(0);
    expect(flatTelemetry.bollSqueeze).toBe(true);
    expect(flatTelemetry.rsi14).toBe(50);

    const telemetry = computeQuantTelemetry(enriched, {
      idealBuy: 140,
      stopLoss: 130,
      takeProfit: 165,
    });
    expect(telemetry.riskRewardRatio).toBeCloseTo(2.5, 5);
    expect(telemetry.upsidePct).toBeGreaterThan(17);
    expect(telemetry.downsidePct).toBeGreaterThan(7);
    expect(telemetry.annualizedVolPct).toBeGreaterThan(0);
    expect(telemetry.maxDrawdownPct).toBeLessThanOrEqual(0);
    expect(telemetry.ma20BiasPct).not.toBeNull();
  });

  it('supports interactive timeframe switching, MA60/BOLL overlays, sub-panels, and trilingual governance without native title attrs', () => {
    const bars: StockKLineItem[] = Array.from({ length: 70 }, (_, i) => {
      const date = new Date(Date.UTC(2026, 0, i + 1)).toISOString().slice(0, 10);
      const close = Number((80 + i * 0.6 + Math.sin(i / 3) * 2).toFixed(2));
      return {
        date,
        open: close - 0.3,
        high: close + 1.0,
        low: close - 0.9,
        close,
      };
    });

    const { container, rerender } = render(
      <ReportPriceLevelsChart
        bars={bars}
        strategy={{ idealBuy: '115', stopLoss: '105', takeProfit: '140' }}
        language="zh"
      />,
    );

    // Zero native HTML title attributes (ui_governance)
    expect(container.querySelectorAll('[title]')).toHaveLength(0);

    // Default telemetry strip & single chart (sub-panel Off by default)
    expect(screen.getByTestId('quant-telemetry-strip')).toHaveTextContent('盈亏比');
    expect(screen.getByTestId('quant-telemetry-strip')).toHaveTextContent('1:2.5');
    expect(screen.queryByTestId(/^quant-subpanel-/)).not.toBeInTheDocument();

    // Switch timeframe 60D -> 20D -> All
    fireEvent.click(screen.getByRole('button', { name: '20D' }));
    expect(screen.getByText(/\(20D\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '全部' }));
    expect(screen.getByText(/\(70D\)/)).toBeInTheDocument();

    // Toggle MA60 & BOLL overlays
    const ma60Btn = screen.getByRole('button', { name: 'MA60' });
    const bollBtn = screen.getByRole('button', { name: 'BOLL' });
    expect(ma60Btn).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(ma60Btn);
    fireEvent.click(bollBtn);
    expect(ma60Btn).toHaveAttribute('aria-pressed', 'true');
    expect(bollBtn).toHaveAttribute('aria-pressed', 'true');

    // Toggle synchronized sub-panels RSI -> MACD -> KDJ -> Off
    fireEvent.click(screen.getByRole('button', { name: 'RSI(14)' }));
    expect(screen.getByTestId('quant-subpanel-rsi')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'MACD' }));
    expect(screen.getByTestId('quant-subpanel-macd')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'KDJ' }));
    expect(screen.getByTestId('quant-subpanel-kdj')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    expect(screen.queryByTestId(/^quant-subpanel-/)).not.toBeInTheDocument();

    // Verify EN & KO localization
    rerender(
      <ReportPriceLevelsChart
        bars={bars}
        strategy={{ idealBuy: '115', stopLoss: '105', takeProfit: '140' }}
        language="en"
      />,
    );
    expect(screen.getByTestId('quant-telemetry-strip')).toHaveTextContent('R:R:');
    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument();

    rerender(
      <ReportPriceLevelsChart
        bars={bars}
        strategy={{ idealBuy: '115', stopLoss: '105', takeProfit: '140' }}
        language="ko"
      />,
    );
    expect(screen.getByTestId('quant-telemetry-strip')).toHaveTextContent('손익비:');
    expect(screen.getByRole('button', { name: '전체' })).toBeInTheDocument();
    expect(container.querySelectorAll('[title]')).toHaveLength(0);
  });

  it('deduplicates duplicate dates, normalizes inverted OHLC bounds, and guards micro stop distances', () => {
    const rawBars: StockKLineItem[] = Array.from({ length: 16 }, (_, i) => ({
      date: `2026-04-${String(i + 1).padStart(2, '0')}`,
      open: 100 + i,
      // Intentionally invert high/low on later bars
      high: 98 + i,
      low: 103 + i,
      close: 100 + i,
    }));
    rawBars.push({
      date: '2026-04-16',
      open: 118,
      high: 112,
      low: 121,
      close: 120,
    });

    const enriched = enrichBarsWithMovingAverages(rawBars, 0);
    expect(enriched).toHaveLength(16);
    const last = enriched[enriched.length - 1];
    expect(last.close).toBe(120);
    expect(last.high).toBe(121);
    expect(last.low).toBe(112);
    expect(last.kdjK).toBeGreaterThanOrEqual(0);
    expect(last.kdjK).toBeLessThanOrEqual(100);
    expect(last.atr14).toBeGreaterThan(0);

    const microStopTelemetry = computeQuantTelemetry(enriched, {
      idealBuy: 100.001,
      stopLoss: 100.0,
      takeProfit: 130,
    });
    expect(microStopTelemetry.riskRewardRatio).toBeNull();
  });

  it('preserves sub-cent yDomain and adaptive price precision for micro-priced tickers', () => {
    const bars = Array.from({ length: 20 }, (_, i) => ({
      date: `2026-01-${String(i + 1).padStart(2, '0')}`,
      open: 0.0056,
      high: 0.0056,
      low: 0.0056,
      close: 0.0056,
    }));

    render(<ReportPriceLevelsChart bars={bars} language="zh" />);

    expect(screen.getAllByText('0.0056').length).toBeGreaterThanOrEqual(1);
    const yAxis = screen.getByTestId('chart-yaxis');
    const domain = JSON.parse(yAxis.getAttribute('data-domain') || '[]') as number[];
    expect(domain[0]).toBeLessThan(0.0056);
    expect(domain[1]).toBeGreaterThan(0.0056);
  });

  it('anchors cross-year historical report markers by full ISO date and plots positive/negative MACD histogram bars', () => {
    const crossYearBars: StockKLineItem[] = [
      ...Array.from({ length: 25 }, (_, i) => ({
        date: `2025-11-${String(i + 1).padStart(2, '0')}`,
        open: 50 + i * 0.8,
        close: 50 + i * 0.8,
        high: 51 + i * 0.8,
        low: 49 + i * 0.8,
      })),
      ...Array.from({ length: 25 }, (_, i) => ({
        date: `2026-11-${String(i + 1).padStart(2, '0')}`,
        open: 70 - i * 0.9,
        close: 70 - i * 0.9,
        high: 71 - i * 0.9,
        low: 69 - i * 0.9,
      })),
    ];

    render(
      <ReportPriceLevelsChart
        bars={crossYearBars}
        reportDate="2025-11-20"
        language="zh"
      />,
    );

    expect(screen.getByTestId('chart-xaxis')).toHaveAttribute('data-key', 'date');
    expect(screen.getByTestId('ref-line-x-2025-11-20')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'MACD' }));
    const histBar = screen.getByTestId('chart-bar-macdHist');
    const cellFills = Array.from(histBar.querySelectorAll('[data-testid="chart-bar-cell"]')).map((el) =>
      el.getAttribute('data-fill'),
    );
    expect(cellFills.some((f) => f === 'rgba(16, 185, 129, 0.65)')).toBe(true);
    expect(cellFills.some((f) => f === 'rgba(244, 63, 94, 0.65)')).toBe(true);
  });

  it('shows localized insufficient-session status messages in sub-panels on short history without native title attributes', () => {
    const shortBars: StockKLineItem[] = Array.from({ length: 5 }, (_, i) => ({
      date: `2026-05-0${i + 1}`,
      open: 100 + i,
      high: 101 + i,
      low: 99 + i,
      close: 100 + i,
    }));

    const { container, rerender } = render(<ReportPriceLevelsChart bars={shortBars} language="zh" />);
    fireEvent.click(screen.getByRole('button', { name: 'RSI(14)' }));
    expect(screen.getByTestId('quant-subpanel-rsi')).toHaveTextContent('至少需要 15 个交易日以计算 RSI(14)');

    fireEvent.click(screen.getByRole('button', { name: 'MACD' }));
    expect(screen.getByTestId('quant-subpanel-macd')).toHaveTextContent('至少需要 26 个交易日以计算 MACD');

    fireEvent.click(screen.getByRole('button', { name: 'KDJ' }));
    expect(screen.getByTestId('quant-subpanel-kdj')).toHaveTextContent('至少需要 9 个交易日以计算 KDJ');

    rerender(<ReportPriceLevelsChart bars={shortBars} language="en" />);
    expect(screen.getByTestId('quant-subpanel-kdj')).toHaveTextContent('Needs at least 9 sessions to compute KDJ');

    rerender(<ReportPriceLevelsChart bars={shortBars} language="ko" />);
    expect(screen.getByTestId('quant-subpanel-kdj')).toHaveTextContent('KDJ 계산에 최소 9거래일 필요');
    expect(container.querySelectorAll('[title]')).toHaveLength(0);
  });

  it('keeps missing or zero open prices as null instead of substituting close and renders Tooltip accurately via real chart data', () => {
    const barsWithMissingOpen: StockKLineItem[] = [
      { date: '2026-05-01', open: 0, high: 101, low: 99, close: 100 },
      { date: '2026-05-02', open: Number.NaN, high: 103, low: 98, close: 102 },
      { date: '2026-05-03', high: 102.5, low: 99, close: 101 } as unknown as StockKLineItem,
      { date: '2026-05-04', open: 101.5, high: 104, low: 100, close: 103 },
    ];
    const enriched = enrichBarsWithMovingAverages(barsWithMissingOpen, 60);
    expect(enriched[0].open).toBeNull();
    expect(enriched[1].open).toBeNull();
    expect(enriched[2].open).toBeNull();
    expect(enriched[3].open).toBe(101.5);

    const { rerender } = render(<ReportPriceLevelsChart bars={barsWithMissingOpen.slice(0, 3)} language="zh" />);
    const tooltipMissing = screen.getByTestId('levels-tooltip');
    expect(tooltipMissing).toHaveTextContent('2026-05-03');
    expect(tooltipMissing).toHaveTextContent('101.00');
    expect(tooltipMissing).not.toHaveTextContent('开盘');

    rerender(<ReportPriceLevelsChart bars={barsWithMissingOpen} language="zh" />);
    const tooltipValid = screen.getByTestId('levels-tooltip');
    expect(tooltipValid).toHaveTextContent('2026-05-04');
    expect(tooltipValid).toHaveTextContent('开盘:');
    expect(tooltipValid).toHaveTextContent('101.50');
  });

  it('falls back to secondaryBuy instead of latest close when idealBuy is absent for R:R telemetry', () => {
    const bars: StockKLineItem[] = Array.from({ length: 20 }, (_, i) => ({
      date: `2026-04-${String(i + 1).padStart(2, '0')}`,
      open: 100,
      high: 102,
      low: 98,
      close: 100,
    }));
    const enriched = enrichBarsWithMovingAverages(bars, 60);
    const telemetry = computeQuantTelemetry(enriched, {
      idealBuy: null,
      secondaryBuy: 120,
      stopLoss: 90,
      takeProfit: 130,
    });
    expect(telemetry.riskRewardRatio).toBeCloseTo(1 / 3, 5);
    expect(telemetry.upsidePct).toBeCloseTo((10 / 120) * 100, 5);
    expect(telemetry.downsidePct).toBeCloseTo(25, 5);

    render(
      <ReportPriceLevelsChart
        bars={bars}
        strategy={{ secondaryBuy: '120', stopLoss: '90', takeProfit: '130' }}
        language="zh"
      />,
    );
    const strip = screen.getByTestId('quant-telemetry-strip');
    expect(strip).toHaveTextContent('1:0.3');
    expect(strip).toHaveTextContent('+8.3% / -25.0%');
    expect(strip).not.toHaveTextContent('1:3.0');
  });

  it('classifies flat-price zero-diff MACD as neutral instead of bullish in both zh and en', () => {
    const flatBars: StockKLineItem[] = Array.from({ length: 30 }, (_, i) => ({
      date: `2026-03-${String(i + 1).padStart(2, '0')}`,
      open: 100,
      high: 100,
      low: 100,
      close: 100,
    }));
    const telemetry = computeQuantTelemetry(enrichBarsWithMovingAverages(flatBars, 60));
    expect(telemetry.macdSignal).toBe('neutral');

    const { rerender } = render(<ReportPriceLevelsChart bars={flatBars} language="zh" />);
    const strip = screen.getByTestId('quant-telemetry-strip');
    expect(strip).toHaveTextContent('MACD:中性');
    expect(strip).not.toHaveTextContent('多头');

    rerender(<ReportPriceLevelsChart bars={flatBars} language="en" />);
    expect(strip).toHaveTextContent('MACD:Neutral');
    expect(strip).not.toHaveTextContent('Bullish');
  });

  it('excludes zero/missing high-low bars from ATR and KDJ and shows localized range-unavailable notice', () => {
    const noRangeBars: StockKLineItem[] = Array.from({ length: 15 }, (_, i) => ({
      date: `2026-06-${String(i + 1).padStart(2, '0')}`,
      open: 100,
      high: 0,
      low: 0,
      close: 100,
    }));

    const enrichedNoRange = enrichBarsWithMovingAverages(noRangeBars, 60);
    expect(enrichedNoRange[14].hasValidRange).toBe(false);
    expect(enrichedNoRange[14].atr14).toBeNull();
    expect(enrichedNoRange[14].atrPct).toBeNull();
    expect(enrichedNoRange[14].kdjK).toBeNull();
    expect(enrichedNoRange[14].kdjD).toBeNull();
    expect(enrichedNoRange[14].kdjJ).toBeNull();
    expect(computeQuantTelemetry(enrichedNoRange).atrPct).toBeNull();

    const { rerender } = render(<ReportPriceLevelsChart bars={noRangeBars} language="zh" />);
    expect(screen.getByTestId('levels-tooltip')).not.toHaveTextContent('最高/最低');
    expect(screen.getByTestId('quant-telemetry-strip')).not.toHaveTextContent('ATR%');

    fireEvent.click(screen.getByRole('button', { name: 'KDJ' }));
    expect(screen.getByTestId('quant-subpanel-kdj')).toHaveTextContent(
      '缺少有效最高/最低价数据，暂无法计算 KDJ',
    );

    rerender(<ReportPriceLevelsChart bars={noRangeBars} language="en" />);
    expect(screen.getByTestId('quant-subpanel-kdj')).toHaveTextContent(
      'Valid high/low range data is unavailable to compute KDJ',
    );

    rerender(<ReportPriceLevelsChart bars={noRangeBars} language="ko" />);
    expect(screen.getByTestId('quant-subpanel-kdj')).toHaveTextContent(
      '유효한 고가/저가 데이터가 없어 KDJ를 계산할 수 없습니다',
    );

    // A mid-series missing high/low bar resets ATR and KDJ until fresh valid windows complete.
    const midMissingBars: StockKLineItem[] = Array.from({ length: 30 }, (_, i) => ({
      date: `2026-07-${String(i + 1).padStart(2, '0')}`,
      open: 100 + i,
      high: i === 15 ? 0 : 102 + i,
      low: i === 15 ? 0 : 98 + i,
      close: 100 + i,
    }));
    const enrichedMid = enrichBarsWithMovingAverages(midMissingBars, 60);
    expect(enrichedMid[15].hasValidRange).toBe(false);
    expect(enrichedMid[15].kdjK).toBeNull();
    expect(enrichedMid[15].atr14).toBeNull();
    expect(enrichedMid[23].kdjK).toBeNull();
    expect(enrichedMid[24].kdjK).not.toBeNull();
    expect(enrichedMid[28].atr14).toBeNull();
    expect(enrichedMid[29].atr14).not.toBeNull();
  });

  it('aligns MACD below-zero rebound regime and crossing rules with TrendAnalyzer semantics', () => {
    const reboundBars: StockKLineItem[] = Array.from({ length: 35 }, (_, i) => {
      const close = i < 28 ? 150 - i * 2 : 96 + (i - 28);
      return {
        date: new Date(Date.UTC(2026, 0, i + 1)).toISOString().slice(0, 10),
        open: close,
        high: close + 1,
        low: close - 1,
        close,
      };
    });

    const enriched = enrichBarsWithMovingAverages(reboundBars, 60);
    const prev = enriched[33];
    const last = enriched[34];
    expect(last.macdDif!).toBeLessThan(0);
    expect(last.macdDea!).toBeLessThan(0);
    expect(prev.macdHist!).toBeGreaterThan(0);
    expect(last.macdHist!).toBeGreaterThan(0);

    const telemetry = computeQuantTelemetry(enriched);
    expect(telemetry.macdSignal).toBe('bearish');

    const { rerender } = render(<ReportPriceLevelsChart bars={reboundBars} language="zh" />);
    const strip = screen.getByTestId('quant-telemetry-strip');
    expect(strip).toHaveTextContent('MACD:空头');
    expect(strip).not.toHaveTextContent('MACD:多头');

    rerender(<ReportPriceLevelsChart bars={reboundBars} language="en" />);
    expect(strip).toHaveTextContent('MACD:Bearish');
    expect(strip).not.toHaveTextContent('MACD:Bullish');

    const baseDatum = enriched[34];
    expect(
      computeQuantTelemetry([
        { ...baseDatum, macdDif: 0.2, macdDea: -0.1 },
        { ...baseDatum, macdDif: 0.3, macdDea: -0.05 },
      ]).macdSignal,
    ).toBe('neutral');
    expect(
      computeQuantTelemetry([
        { ...baseDatum, macdDif: -0.5, macdDea: -0.3 },
        { ...baseDatum, macdDif: -0.2, macdDea: -0.25 },
      ]).macdSignal,
    ).toBe('bullish_cross');
    expect(
      computeQuantTelemetry([
        { ...baseDatum, macdDif: 0.5, macdDea: 0.3 },
        { ...baseDatum, macdDif: 0.2, macdDea: 0.25 },
      ]).macdSignal,
    ).toBe('bearish_cross');
  });

  it('withholds MACD signals and curves until at least 26 trading sessions are available', () => {
    const makeRising = (len: number): StockKLineItem[] =>
      Array.from({ length: len }, (_, i) => ({
        date: `2026-08-${String(i + 1).padStart(2, '0')}`,
        open: 100 + i,
        high: 101 + i,
        low: 99 + i,
        close: 100 + i,
      }));

    const enriched20 = enrichBarsWithMovingAverages(makeRising(20), 60);
    expect(enriched20.every((d) => d.macdDif === null && d.macdDea === null && d.macdHist === null)).toBe(true);
    expect(computeQuantTelemetry(enriched20).macdSignal).toBeNull();

    const enriched25 = enrichBarsWithMovingAverages(makeRising(25), 60);
    expect(enriched25[24].macdDif).toBeNull();
    expect(computeQuantTelemetry(enriched25).macdSignal).toBeNull();

    const { rerender } = render(<ReportPriceLevelsChart bars={makeRising(20)} language="zh" />);
    expect(screen.getByTestId('quant-telemetry-strip')).not.toHaveTextContent('MACD:');
    fireEvent.click(screen.getByRole('button', { name: 'MACD' }));
    expect(screen.getByTestId('quant-subpanel-macd')).toHaveTextContent('至少需要 26 个交易日以计算 MACD');

    rerender(<ReportPriceLevelsChart bars={makeRising(20)} language="en" />);
    expect(screen.getByTestId('quant-subpanel-macd')).toHaveTextContent('Needs at least 26 sessions to compute MACD');

    const bars26 = makeRising(26);
    const enriched26 = enrichBarsWithMovingAverages(bars26, 60);
    expect(enriched26[24].macdDif).toBeNull();
    expect(enriched26[25].macdDif).not.toBeNull();
    expect(computeQuantTelemetry(enriched26).macdSignal).toBe('bullish');

    rerender(<ReportPriceLevelsChart bars={bars26} language="zh" />);
    expect(screen.getByTestId('quant-telemetry-strip')).toHaveTextContent('MACD:多头');
    expect(screen.getByTestId('chart-bar-macdHist')).toBeInTheDocument();
  });

  it('detects MACD golden cross on the exact 26th session when session 25 is hidden', () => {
    const bars26: StockKLineItem[] = Array.from({ length: 26 }, (_, i) => {
      const close = i < 25 ? 150 - i * 2 : 124;
      return {
        date: `2026-09-${String(i + 1).padStart(2, '0')}`,
        open: close,
        high: close + 1,
        low: close - 1,
        close,
      };
    });

    const enriched26 = enrichBarsWithMovingAverages(bars26, 60);
    expect(enriched26[24].macdDif).toBeNull();
    expect(enriched26[25].macdDif).not.toBeNull();
    expect(computeQuantTelemetry(enriched26).macdSignal).toBe('bullish_cross');

    const { rerender } = render(<ReportPriceLevelsChart bars={bars26} language="zh" />);
    expect(screen.getByTestId('quant-telemetry-strip')).toHaveTextContent('MACD:金叉');
    expect(screen.getByTestId('quant-telemetry-strip')).not.toHaveTextContent('MACD:空头');

    rerender(<ReportPriceLevelsChart bars={bars26} language="en" />);
    expect(screen.getByTestId('quant-telemetry-strip')).toHaveTextContent('MACD:Golden Cross');
    expect(screen.getByTestId('quant-telemetry-strip')).not.toHaveTextContent('MACD:Bearish');
  });

  it('ignores close-synthesized positive OHLC when ohlcSynthesized is true', () => {
    const closeOnlyBars: StockKLineItem[] = Array.from({ length: 15 }, (_, i) => ({
      date: `2026-10-${String(i + 1).padStart(2, '0')}`,
      open: 100,
      high: 100,
      low: 100,
      close: 100,
    }));

    const enriched = enrichBarsWithMovingAverages(closeOnlyBars, 60, { ohlcSynthesized: true });
    expect(enriched.every((d) => d.open === null && d.hasValidRange === false && d.atrPct === null && d.kdjK === null)).toBe(true);
    expect(computeQuantTelemetry(enriched).atrPct).toBeNull();

    render(<ReportPriceLevelsChart bars={closeOnlyBars} ohlcSynthesized language="zh" />);
    expect(screen.getByTestId('quant-telemetry-strip')).not.toHaveTextContent('ATR%:');
    const tooltip = screen.getByTestId('levels-tooltip');
    expect(tooltip).not.toHaveTextContent('开盘:');
    expect(tooltip).not.toHaveTextContent('最高/最低:');

    fireEvent.click(screen.getByRole('button', { name: 'KDJ' }));
    expect(screen.getByTestId('quant-subpanel-kdj')).toHaveTextContent('缺少有效最高/最低价数据，暂无法计算 KDJ');
  });

  it('pauses cross-session return, volatility, and indicator analytics for unadjusted split history', () => {
    const splitBars: StockKLineItem[] = Array.from({ length: 60 }, (_, i) => {
      const price = i === 59 ? 50 : 100;
      return {
        date: `2026-${String(Math.floor(i / 28) + 1).padStart(2, '0')}-${String((i % 28) + 1).padStart(2, '0')}`,
        open: price,
        high: price,
        low: price,
        close: price,
      };
    });

    const enriched60 = enrichBarsWithMovingAverages(splitBars, 60);
    const pausedTelemetry = computeQuantTelemetry(
      enriched60,
      { idealBuy: 48, stopLoss: 45, takeProfit: 60 },
      { priceAdjustment: 'unadjusted' },
    );
    expect(pausedTelemetry.riskRewardRatio).toBeCloseTo(4);
    expect(pausedTelemetry.maxDrawdownPct).toBeNull();
    expect(pausedTelemetry.annualizedVolPct).toBeNull();
    expect(pausedTelemetry.rsi14).toBeNull();
    expect(pausedTelemetry.macdSignal).toBeNull();
    expect(pausedTelemetry.atrPct).toBeNull();
    expect(pausedTelemetry.ma20BiasPct).toBeNull();

    const { rerender } = render(
      <ReportPriceLevelsChart
        bars={splitBars}
        priceAdjustment="unadjusted"
        strategy={{ idealBuy: '48', stopLoss: '45', takeProfit: '60' }}
        language="zh"
      />,
    );
    expect(screen.getByText(/未复权历史行情/)).toBeInTheDocument();
    const strip = screen.getByTestId('quant-telemetry-strip');
    expect(strip).toHaveTextContent('盈亏比:1:4.0');
    expect(strip).not.toHaveTextContent('回撤:');
    expect(strip).not.toHaveTextContent('年化波动:');
    expect(strip).not.toHaveTextContent('RSI(14):');
    expect(strip).not.toHaveTextContent('MACD:');
    expect(strip).not.toHaveTextContent('MA20乖离:');

    const tooltip = screen.getByTestId('levels-tooltip');
    expect(tooltip).not.toHaveTextContent('MA5:');
    expect(tooltip).not.toHaveTextContent('MA20:');
    expect(tooltip).not.toHaveTextContent('RSI(14):');

    fireEvent.click(screen.getByRole('button', { name: 'MACD' }));
    expect(screen.getByTestId('quant-subpanel-macd')).toHaveTextContent(/未复权历史行情/);

    rerender(
      <ReportPriceLevelsChart
        bars={splitBars}
        priceAdjustment="unadjusted"
        strategy={{ idealBuy: '48', stopLoss: '45', takeProfit: '60' }}
        language="en"
      />,
    );
    expect(screen.getAllByText(/unadjusted prices/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId('quant-subpanel-macd')).toHaveTextContent(/unadjusted prices/i);
  });
});
