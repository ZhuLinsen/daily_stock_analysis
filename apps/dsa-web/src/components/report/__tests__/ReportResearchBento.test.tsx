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

  it('renders risk/reward ratio, ATR position badge, and price scale in ReportStrategy', () => {
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
    expect(screen.getByText('ATR 建议仓位 15%–20%')).toBeInTheDocument();
    expect(screen.getByText('1580.00')).toBeInTheDocument();
    expect(screen.getByText('1840.00')).toBeInTheDocument();
  });
});
