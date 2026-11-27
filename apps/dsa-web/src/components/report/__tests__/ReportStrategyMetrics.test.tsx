import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReportStrategy } from '../ReportStrategy';

describe('ReportStrategy metrics and price range ruler', () => {
  it('renders risk/reward ratio, upside/downside % and per-level delta percentages', () => {
    render(
      <ReportStrategy
        language="zh"
        currentPrice={100}
        strategy={{
          idealBuy: '100',
          secondaryBuy: '95',
          stopLoss: '90',
          takeProfit: '125',
        }}
      />,
    );

    expect(screen.getByRole('img', { name: '价位区间标尺' })).toBeInTheDocument();
    expect(screen.getByText('盈亏比 1:2.50')).toBeInTheDocument();
    expect(screen.getByText('潜在空间 +25.0%')).toBeInTheDocument();
    expect(screen.getByText('止损幅度 -10.0%')).toBeInTheDocument();
    expect(screen.getByText('现价: 100.00')).toBeInTheDocument();
    expect(screen.getByText('-5.0%')).toBeInTheDocument();
    expect(screen.getByText('-10.0%')).toBeInTheDocument();
    expect(screen.getByText('+25.0%')).toBeInTheDocument();
  });

  it('shows entry basis label, out-of-range badge, and suppresses R:R for sell actions', () => {
    const { rerender } = render(
      <ReportStrategy
        language="zh"
        currentPrice={85}
        action="hold"
        strategy={{
          idealBuy: '100',
          stopLoss: '90',
          takeProfit: '125',
        }}
      />,
    );

    expect(screen.getByText('盈亏比 1:2.50 (按买点)')).toBeInTheDocument();
    expect(screen.getByText('已破止损')).toBeInTheDocument();

    rerender(
      <ReportStrategy
        language="zh"
        currentPrice={85}
        action="sell"
        strategy={{
          idealBuy: '100',
          stopLoss: '90',
          takeProfit: '125',
        }}
      />,
    );
    expect(screen.queryByRole('img', { name: '价位区间标尺' })).not.toBeInTheDocument();
  });

  it('omits range ruler when price levels are inverted or scale-mismatched', () => {
    const { rerender } = render(
      <ReportStrategy
        language="en"
        currentPrice={100}
        strategy={{
          idealBuy: '110',
          stopLoss: '120',
          takeProfit: '105',
        }}
      />,
    );
    expect(screen.queryByLabelText('Price Range')).not.toBeInTheDocument();

    rerender(
      <ReportStrategy
        language="en"
        currentPrice={10}
        strategy={{
          idealBuy: '1000',
          stopLoss: '900',
          takeProfit: '1200',
        }}
      />,
    );
    expect(screen.queryByLabelText('Price Range')).not.toBeInTheDocument();
  });
});
