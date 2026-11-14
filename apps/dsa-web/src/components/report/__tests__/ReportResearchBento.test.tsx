import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ResearchArtifact } from '../../../types/researchArtifact';
import { ReportResearchBento } from '../ReportResearchBento';
import { ReportStrategy } from '../ReportStrategy';

const makeArtifact = (overrides: Partial<ResearchArtifact> = {}): ResearchArtifact => ({
  schemaVersion: 'research-artifact-v1',
  artifactId: 'report:42',
  subject: {
    stockCode: '600519',
    stockName: '贵州茅台',
    market: 'CN',
  },
  thesis: {
    direction: 'bullish',
    summary: '均线多头排列，回踩支撑位。',
    score: 76,
    confidence: 0.52,
    action: 'buy',
    actionLabel: '买入',
    reasons: ['站稳 5 日线'],
    risks: [],
  },
  evidence: [],
  invalidationConditions: [
    {
      id: 'price:stop_loss',
      category: 'price',
      description: '跌破止损位 1580.0 触发重新评估',
      severity: 'critical',
      metadata: {},
    },
  ],
  nextActions: [
    {
      action: 'buy',
      label: '分批买入',
      reason: '回踩企稳后执行',
      metadata: {},
    },
  ],
  dataQuality: {
    level: 'limited',
    overallScore: 68,
    sourceCount: 3,
    staleCount: 1,
    missingBlocks: [],
    limitations: ['部分新闻延迟'],
  },
  metadata: {
    levels: {
      idealBuy: 1660,
      secondaryBuy: 1620,
      stopLoss: 1580,
      takeProfit: 1840,
      referencePrice: 1680,
      riskRewardRatio: 2.25,
      status: 'active',
      validation: 'ok',
    },
    position: {
      minPct: 15,
      maxPct: 20,
      method: 'atr_risk_budget',
      riskBudgetPct: 1.2,
    },
    riskFlags: [
      {
        code: 'LIMITED_DATA_QUALITY',
        severity: 'warning',
        message: 'Partial or stale data inputs detected.',
      },
    ],
    committee: {
      baseDisagreement: {
        type: 'bullish_with_neutral',
        agents: [
          { agent: 'technical', signal: 'buy', confidence: 0.8 },
          { agent: 'intel', signal: 'hold', confidence: 0.6 },
          { agent: 'risk', signal: 'sell', confidence: 0.7 },
        ],
      },
      riskControl: {
        applied: true,
      },
    },
  },
  ...overrides,
});

describe('ReportResearchBento & ReportStrategy', () => {
  it('renders data quality caution, invalidations, risk flags, and committee tally', () => {
    const artifact = makeArtifact();
    render(<ReportResearchBento artifact={artifact} language="zh" />);

    expect(screen.getByText('LIMITED · 3 src / 1 stale')).toBeInTheDocument();
    expect(screen.getByText('数据质量受限，结论置信度已做保守降级')).toBeInTheDocument();
    expect(screen.getByText('跌破止损位 1580.0 触发重新评估')).toBeInTheDocument();
    expect(screen.getByText('Partial or stale data inputs detected.')).toBeInTheDocument();
    expect(screen.getByText('风控覆写已触发')).toBeInTheDocument();
    expect(screen.getByText('1 / 1 / 1')).toBeInTheDocument();
  });

  it('renders risk/reward ratio, stop-risk position badge, and price scale in ReportStrategy', () => {
    const artifact = makeArtifact();
    render(
      <ReportStrategy
        strategy={{
          idealBuy: '1660.0',
          secondaryBuy: '1620.0',
          stopLoss: '1580.0',
          takeProfit: '1840.0',
        }}
        currentPrice={1680}
        artifact={artifact}
        language="zh"
      />,
    );

    expect(screen.getByText('有效点位')).toBeInTheDocument();
    expect(screen.getByText('盈亏比 1:2.25')).toBeInTheDocument();
    expect(screen.getByText('止损风险预算仓位 15%–20%')).toBeInTheDocument();
    expect(screen.getByText('1580.00')).toBeInTheDocument();
    expect(screen.getByText('1840.00')).toBeInTheDocument();
  });

  it('hides position metadata that only fits current price when planned entry is higher', () => {
    const artifact = makeArtifact({ metadata: {
      levels: { reference_price: 100, ideal_buy: 105, stop_loss: 96, validation: 'ok' },
      position: { min_pct: 25, max_pct: 30, risk_budget_pct: 1.2 },
    } });
    render(<ReportStrategy strategy={{ idealBuy: '105', stopLoss: '96' }} artifact={artifact} />);

    expect(screen.queryByText(/止损风险预算仓位/)).not.toBeInTheDocument();
  });

  it.each([null, true, false, 'unparseable', 0, -1, NaN, Infinity, 100, 105])(
    'hides legacy positive position advice when stop loss is invalid: %s',
    (stopLoss) => {
      const artifact = makeArtifact({ metadata: {
        levels: { referencePrice: 100, idealBuy: 100, stopLoss, status: 'conditional_watch' },
        position: { minPct: 25, maxPct: 30, riskBudgetPct: 1.2 },
      } });
      render(<ReportStrategy strategy={{ idealBuy: '100', takeProfit: '120' }} artifact={artifact} />);
      expect(screen.getByText('条件观察（待触发）')).toBeInTheDocument();
      expect(screen.queryByText(/止损风险预算仓位/)).not.toBeInTheDocument();
    },
  );

  it.each([5, 4])('only displays wide-stop advice within the declared budget: %s%%', (maxPct) => {
    const artifact = makeArtifact({ metadata: {
      levels: { reference_price: 100, stop_loss: 70, status: 'active', validation: 'ok' },
      position: { min_pct: 0, max_pct: maxPct, risk_budget_pct: 1.2 },
    } });
    render(<ReportStrategy strategy={{ idealBuy: '100', stopLoss: '70' }} artifact={artifact} />);
    if (maxPct === 4) {
      expect(screen.getByText('止损风险预算仓位 0%–4%')).toBeInTheDocument();
    } else {
      expect(screen.queryByText(/止损风险预算仓位/)).not.toBeInTheDocument();
    }
  });

  it('hides positive legacy advice without a verifiable risk budget', () => {
    const artifact = makeArtifact({ metadata: {
      levels: { referencePrice: 100, stopLoss: 96 },
      position: { minPct: 25, maxPct: 30 },
    } });
    render(<ReportStrategy strategy={{ idealBuy: '100', stopLoss: '96' }} artifact={artifact} />);
    expect(screen.queryByText(/止损风险预算仓位/)).not.toBeInTheDocument();
  });

  it.each([
    { minPct: null, maxPct: 20, riskBudgetPct: 1.2 },
    { minPct: false, maxPct: 20, riskBudgetPct: 1.2 },
    { minPct: '', maxPct: 20, riskBudgetPct: 1.2 },
    { minPct: 0, maxPct: '20', riskBudgetPct: 1.2 },
    { minPct: -1, maxPct: 20, riskBudgetPct: 1.2 },
    { minPct: 25, maxPct: 20, riskBudgetPct: 1.2 },
    { minPct: 0, maxPct: Infinity, riskBudgetPct: 1.2 },
    { minPct: 0, maxPct: 20, riskBudgetPct: -1 },
    { minPct: 0, maxPct: 20, riskBudgetPct: Infinity },
  ])('hides malformed legacy position metadata: %j', (position) => {
    const artifact = makeArtifact({ metadata: {
      levels: { referencePrice: 100, stopLoss: 96 }, position,
    } });
    render(<ReportStrategy strategy={{ idealBuy: '100', stopLoss: '96' }} artifact={artifact} />);
    expect(screen.queryByText(/止损风险预算仓位/)).not.toBeInTheDocument();
  });

  it.each([
    { language: 'en', label: 'Stop-loss Risk-budget Position' },
    { language: 'ko', label: '손절 위험 예산 비중' },
  ] as const)('uses the stop-risk label in $language', ({ language, label }) => {
    render(<ReportStrategy strategy={{ idealBuy: '1660', stopLoss: '1580' }}
      artifact={makeArtifact()} language={language} />);
    expect(screen.getByText(`${label} 15%–20%`)).toBeInTheDocument();
  });

  it('renders invalid status badge separately from conditional_watch and hides position badge on conflict', () => {
    const artifact = makeArtifact({
      metadata: {
        levels: {
          idealBuy: 100,
          stopLoss: 105,
          takeProfit: 120,
          referencePrice: 100,
          status: 'invalid',
          validation: 'direction_conflict',
        },
        position: { minPct: 10, maxPct: 15, riskBudgetPct: 1.2 },
      },
    });
    render(
      <ReportStrategy
        strategy={{ idealBuy: '100', stopLoss: '105', takeProfit: '120' }}
        currentPrice={100}
        artifact={artifact}
        language="zh"
      />,
    );

    expect(screen.getByText('点位无效')).toBeInTheDocument();
    expect(screen.queryByText('条件观察（待触发）')).not.toBeInTheDocument();
    expect(screen.getByText('点位方向冲突，请人工复核')).toBeInTheDocument();
    expect(screen.queryByText(/止损风险预算仓位|建议仓位/)).not.toBeInTheDocument();
  });

  it('hides position badge when levels are invalid due to out_of_range', () => {
    const artifact = makeArtifact({
      metadata: {
        levels: {
          idealBuy: 150,
          stopLoss: 140,
          takeProfit: 180,
          referencePrice: 100,
          status: 'invalid',
          validation: 'out_of_range',
        },
        position: { minPct: 10, maxPct: 15, riskBudgetPct: 1.2 },
      },
    });
    render(
      <ReportStrategy
        strategy={{ idealBuy: '150', stopLoss: '140', takeProfit: '180' }}
        currentPrice={100}
        artifact={artifact}
        language="en"
      />,
    );

    expect(screen.getByText('Invalid Levels')).toBeInTheDocument();
    expect(screen.getByText('Entry deviates >25% from reference price')).toBeInTheDocument();
    expect(screen.queryByText(/Stop-loss Risk-budget Position/)).not.toBeInTheDocument();
  });
});
