import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import {
  enrichBarsWithMovingAverages,
  formatChartAxisPrice,
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
});
