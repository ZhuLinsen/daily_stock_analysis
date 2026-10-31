import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { historyApi } from '../../../api/history';
import type {
  AnalysisReport,
  AnalysisResult,
  StrategySynthesis,
} from '../../../types/analysis';
import { ReportSummary } from '../ReportSummary';
import { StrategySynthesisCard } from '../StrategySynthesisCard';

vi.mock('../../../api/history', () => ({
  historyApi: {
    getDiagnostics: vi.fn(),
    getNews: vi.fn(),
  },
}));

// camelCase mirror of the W2-frozen backend payload
// (tests/test_strategy_synthesis_api_projection.py fixture dict).
const fullSynthesis: StrategySynthesis = {
  schemaVersion: 'strategy-synthesis-v1',
  finalSignal: 'hold',
  weightedScore: 3.4545,
  confidence: 0.6517,
  originalConfidence: 0.7545,
  consensusLevel: 'medium',
  conflictCount: 1,
  conflictSeverity: 'medium',
  summaryKey: 'strategy_synthesis.with_conflicts',
  summaryParams: {
    opinionCount: 2,
    totalOpinionCount: 2,
    invalidOpinionCount: 0,
    finalSignal: 'hold',
    consensusLevel: 'medium',
    conflictSeverity: 'medium',
    conflictCount: 1,
  },
  signalDistribution: {
    bullish: { count: 1, weightShare: 0.6 },
    neutral: { count: 1, weightShare: 0.4 },
    bearish: { count: 0, weightShare: 0.0 },
  },
  supportingSkills: [
    {
      skillId: 'skill_sell',
      agentName: 'strategy_sell',
      signal: 'sell',
      confidence: 0.8,
      reasoning: '估值偏高，回落风险累积',
      scoreAdjustment: -0.05,
      conditionsMet: ['valuation_stretched'],
      invalidSignal: false,
    },
  ],
  opposingSkills: [
    {
      skillId: 'skill_buy',
      agentName: 'strategy_buy',
      signal: 'buy',
      confidence: 0.9,
      reasoning: '突破形态成立',
      scoreAdjustment: 0.1,
      conditionsMet: [],
      invalidSignal: false,
    },
  ],
  primaryDissent: {
    skillId: 'skill_buy',
    agentName: 'strategy_buy',
    signal: 'buy',
    confidence: 0.9,
    reasoning: '突破形态成立，短线动能延续，回落判断为时尚早。',
  },
  conflicts: [
    {
      conflictType: 'signal_conflict',
      severity: 'medium',
      descriptionKey: 'strategy_synthesis.conflict.signal_direction',
      participants: ['skill_sell', 'skill_buy'],
      metadata: {},
    },
  ],
  deliberation: { summary: { confidenceAdjustment: 0.0 } },
  revisionProjection: {
    status: 'preview',
    mode: 'softened',
    projectedSignal: 'buy',
    projectedConfidence: 0.8,
    finalSignalOverridden: false,
  },
};

const expandCard = () => {
  fireEvent.click(screen.getByRole('button', { name: '展开明细' }));
};

describe('StrategySynthesisCard', () => {
  it('renders first-layer signal, consensus, conflict, distribution and opinion counts', () => {
    render(<StrategySynthesisCard synthesis={fullSynthesis} />);

    // Final signal / confidence / consensus / conflict (first layer metrics)
    expect(screen.getByText('最终信号')).toBeInTheDocument();
    expect(screen.getByText('持有')).toBeInTheDocument();
    expect(screen.getByText('共识等级')).toBeInTheDocument();
    expect(screen.getByText('中等共识')).toBeInTheDocument();
    expect(screen.getByText(/冲突/).textContent).toContain('1');
    expect(screen.getByText('中度分歧')).toBeInTheDocument();
    expect(screen.getByText('加权得分')).toBeInTheDocument();
    expect(screen.getByText('3.45')).toBeInTheDocument();
    expect(screen.getByText('置信度: 65.2%')).toBeInTheDocument();
    // 0.7545 * 100 = 75.4499... in IEEE754, so toFixed(1) renders 75.4%
    expect(screen.getByText('原始置信度: 75.4%')).toBeInTheDocument();

    // Signal distribution: camp counts + weight shares
    expect(screen.getByText('信号分布')).toBeInTheDocument();
    const bullish = screen.getByTestId('synthesis-dist-bullish');
    expect(within(bullish).getByText('看多')).toBeInTheDocument();
    expect(within(bullish).getByText('1')).toBeInTheDocument();
    expect(within(bullish).getByText('60.0%')).toBeInTheDocument();
    const neutral = screen.getByTestId('synthesis-dist-neutral');
    expect(within(neutral).getByText('中性')).toBeInTheDocument();
    expect(within(neutral).getByText('40.0%')).toBeInTheDocument();
    const bearish = screen.getByTestId('synthesis-dist-bearish');
    expect(within(bearish).getByText('看空')).toBeInTheDocument();
    expect(within(bearish).getByText('0')).toBeInTheDocument();
    expect(within(bearish).getByText('0.0%')).toBeInTheDocument();

    // valid / excluded opinion counts from summaryParams
    expect(screen.getByText('有效观点: 2')).toBeInTheDocument();
    expect(screen.getByText('剔除观点: 0')).toBeInTheDocument();
  });

  it('reveals supporting, opposing, dissent, conflicts, deliberation and preview after expanding', () => {
    render(<StrategySynthesisCard synthesis={fullSynthesis} />);

    expect(screen.queryByText('支持策略')).not.toBeInTheDocument();
    expandCard();

    expect(screen.getByText('支持策略')).toBeInTheDocument();
    expect(screen.getByText('strategy_sell')).toBeInTheDocument();
    expect(screen.getByText('估值偏高，回落风险累积')).toBeInTheDocument();
    expect(screen.getByText('反对策略')).toBeInTheDocument();
    // strategy_buy appears in both the opposing list and the primary dissent entry
    expect(screen.getAllByText('strategy_buy').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('首要分歧')).toBeInTheDocument();
    expect(screen.getByText('突破形态成立，短线动能延续，回落判断为时尚早。')).toBeInTheDocument();
    expect(screen.getByText('冲突明细')).toBeInTheDocument();
    expect(screen.getByText(/strategy_synthesis\.conflict\.signal_direction/)).toBeInTheDocument();
    expect(screen.getByText('协同推演摘要')).toBeInTheDocument();
    const preview = screen.getByTestId('synthesis-revision-preview');
    expect(within(preview).getByText('非权威预览')).toBeInTheDocument();
    expect(
      within(preview).getByText('协同推演预览，不改变系统最终建议'),
    ).toBeInTheDocument();
  });

  it('renders nothing when synthesis is null or undefined', () => {
    const { container: nullContainer } = render(
      <StrategySynthesisCard synthesis={null} />,
    );
    expect(nullContainer).toBeEmptyDOMElement();

    const { container: undefinedContainer } = render(
      <StrategySynthesisCard />,
    );
    expect(undefinedContainer).toBeEmptyDOMElement();
  });

  it('localizes labels for english and korean reports', () => {
    const en = render(<StrategySynthesisCard synthesis={fullSynthesis} language="en" />);
    expect(en.container.textContent).toContain('Final Signal');
    expect(en.container.textContent).toContain('Consensus');
    expect(en.container.textContent).toContain('Signal Distribution');
    expect(within(screen.getByTestId('synthesis-dist-bullish')).getByText('Bullish')).toBeInTheDocument();

    en.unmount();

    const ko = render(<StrategySynthesisCard synthesis={fullSynthesis} language="ko" />);
    expect(ko.container.textContent).toContain('최종 신호');
    expect(ko.container.textContent).toContain('합의 수준');
    expect(ko.container.textContent).toContain('신호 분포');
    expect(within(screen.getByTestId('synthesis-dist-bearish')).getByText('약세')).toBeInTheDocument();
  });

  it('labels camps with text words instead of relying on color only', () => {
    render(<StrategySynthesisCard synthesis={fullSynthesis} />);

    expect(screen.getByText('看多')).toBeInTheDocument();
    expect(screen.getByText('中性')).toBeInTheDocument();
    expect(screen.getByText('看空')).toBeInTheDocument();
    // Theme tests assert words/labels, never color classes.
    expect(screen.getByTestId('strategy-synthesis-card').className).not.toMatch(/text-success/);
  });

  it('truncates long reasoning by default and offers a per-entry expand control', () => {
    const longReasoning = `${'这是一段很长的反方理由。'.repeat(30)}分歧结论尾部标记`;
    render(
      <StrategySynthesisCard
        synthesis={{
          ...fullSynthesis,
          primaryDissent: {
            ...fullSynthesis.primaryDissent!,
            reasoning: longReasoning,
          },
        }}
      />,
    );
    expandCard();

    const reasoning = screen.getByText(longReasoning);
    expect(reasoning).toHaveClass('line-clamp-3');

    fireEvent.click(screen.getByRole('button', { name: '展开' }));
    expect(screen.getByText(longReasoning)).not.toHaveClass('line-clamp-3');
  });

  it('does not borrow RiskAgent risk-level vocabulary for dissent labels', () => {
    render(<StrategySynthesisCard synthesis={fullSynthesis} />);

    const card = screen.getByTestId('strategy-synthesis-card');
    expect(within(card).getByText('中度分歧')).toBeInTheDocument();
    expect(within(card).queryByText(/高风险|中风险|低风险/)).not.toBeInTheDocument();
    expect(card.textContent).not.toContain('风险');
  });

  it('shows preview and final signal side by side when they differ (M2)', () => {
    render(<StrategySynthesisCard synthesis={fullSynthesis} />);
    expandCard();

    // Final signal stays authoritative at the first layer...
    expect(screen.getByText('最终信号')).toBeInTheDocument();
    expect(screen.getByText('持有')).toBeInTheDocument();
    // ...while the preview section shows the different projected signal with
    // the non-authoritative annotation.
    const preview = screen.getByTestId('synthesis-revision-preview');
    expect(within(preview).getByText('推演信号')).toBeInTheDocument();
    expect(within(preview).getByText('买入')).toBeInTheDocument();
    expect(within(preview).getByText('非权威预览')).toBeInTheDocument();
    expect(
      within(preview).getByText('协同推演预览，不改变系统最终建议'),
    ).toBeInTheDocument();
  });

  it('renders the insufficient-evidence intermediate state (M3)', () => {
    render(
      <StrategySynthesisCard
        synthesis={{
          ...fullSynthesis,
          consensusLevel: 'insufficient',
          conflictCount: 0,
          conflictSeverity: 'none',
          summaryParams: {
            opinionCount: 0,
            totalOpinionCount: 2,
            invalidOpinionCount: 2,
          },
          signalDistribution: {
            bullish: { count: 0, weightShare: null },
            neutral: { count: 0, weightShare: null },
            bearish: { count: 0, weightShare: null },
          },
          supportingSkills: [],
          opposingSkills: [],
          primaryDissent: null,
        }}
      />,
    );

    expect(screen.getByText('证据不足')).toBeInTheDocument();
    expect(screen.getByText('无分歧')).toBeInTheDocument();
    expect(within(screen.getByTestId('synthesis-dist-bullish')).getByText('—')).toBeInTheDocument();
    expect(screen.getByText('有效观点: 0')).toBeInTheDocument();
    expect(screen.getByText('剔除观点: 2')).toBeInTheDocument();
  });

  it('renders the single-valid-strategy intermediate state without dissent (M3)', () => {
    render(
      <StrategySynthesisCard
        synthesis={{
          ...fullSynthesis,
          consensusLevel: 'high',
          conflictCount: 0,
          conflictSeverity: 'none',
          summaryParams: {
            opinionCount: 1,
            totalOpinionCount: 1,
            invalidOpinionCount: 0,
          },
          signalDistribution: {
            bullish: { count: 1, weightShare: 1.0 },
            neutral: { count: 0, weightShare: null },
            bearish: { count: 0, weightShare: null },
          },
          supportingSkills: [fullSynthesis.supportingSkills![0]],
          opposingSkills: [],
          primaryDissent: null,
        }}
      />,
    );
    expandCard();

    expect(screen.getByText('高共识')).toBeInTheDocument();
    expect(within(screen.getByTestId('synthesis-dist-bullish')).getByText('100.0%')).toBeInTheDocument();
    expect(within(screen.getByTestId('synthesis-dist-neutral')).getByText('—')).toBeInTheDocument();
    expect(screen.getByText('无反方观点')).toBeInTheDocument();
  });
});

describe('StrategySynthesisCard malformed-input degradation (OR-COR-12e5b2ef)', () => {
  // The API layer keeps conflicts/revisionProjection as Dict[str, Any], so a
  // legacy/malformed record can carry nested objects where the camelCase types
  // promise strings/numbers. The card must degrade per field instead of
  // throwing during render (normalizeSignal .trim() / invalid React children).
  const malformedSynthesis = {
    ...fullSynthesis,
    finalSignal: { bad: 'hold' },
    weightedScore: { value: 3.45 },
    consensusLevel: { level: 'medium' },
    conflictCount: { n: 1 },
    conflictSeverity: { level: 'medium' },
    supportingSkills: [
      {
        skillId: 'skill_hold',
        agentName: { name: 'strategy_hold' },
        signal: { bad: 'hold' },
        confidence: 'high',
        reasoning: { text: '区间震荡' },
      },
    ],
    opposingSkills: ['junk-entry'],
    primaryDissent: {
      skillId: 'skill_buy',
      agentName: { name: 'strategy_buy' },
      signal: { bad: 'buy' },
      confidence: { value: 0.9 },
      reasoning: { text: '突破形态成立' },
    },
    conflicts: [
      {
        conflictType: { kind: 'direction' },
        severity: { level: 'high' },
        descriptionKey: ['strategy_conflict.directional_opposition'],
        participants: 'skill_sell,skill_buy',
        metadata: {},
      },
      'junk-entry',
    ],
    revisionProjection: {
      status: 'preview',
      mode: 'softened',
      projectedSignal: { bad: 'buy' },
      projectedConfidence: { value: 0.8 },
      finalSignalOverridden: false,
    },
  } as unknown as StrategySynthesis;

  it('degrades field by field instead of throwing when nested fields are objects', () => {
    render(<StrategySynthesisCard synthesis={malformedSynthesis} />);
    expandCard();

    // The card and its expandable sections survive malformed nested values.
    expect(screen.getByTestId('strategy-synthesis-card')).toBeInTheDocument();
    expect(screen.getByText('冲突明细')).toBeInTheDocument();
    const preview = screen.getByTestId('synthesis-revision-preview');
    expect(within(preview).getByText('非权威预览')).toBeInTheDocument();

    // The malformed projectedSignal degrades to the placeholder badge.
    expect(within(preview).getByText('—')).toBeInTheDocument();

    // No malformed value may leak into the DOM as "[object Object]".
    expect(screen.queryByText(/\[object Object\]/)).not.toBeInTheDocument();
  });

  it('renders malformed conflict entries with placeholder severity and no description key', () => {
    render(<StrategySynthesisCard synthesis={malformedSynthesis} />);
    expandCard();

    const card = screen.getByTestId('strategy-synthesis-card');
    // severity object -> placeholder severity badge...
    expect(within(card).getAllByText('—').length).toBeGreaterThan(0);
    // ...and the descriptionKey array must not render as an invalid child.
    expect(
      within(card).queryByText(/strategy_conflict\.directional_opposition/),
    ).not.toBeInTheDocument();
    expect(within(card).queryByText(/\[object Object\]/)).not.toBeInTheDocument();
  });
});

describe('ReportSummary strategy synthesis placement', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the synthesis card between overview and strategy sections', async () => {
    vi.mocked(historyApi.getNews).mockResolvedValue({
      total: 0,
      items: [],
    });

    const report: AnalysisReport = {
      meta: {
        id: 1,
        queryId: 'q1',
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        reportLanguage: 'zh',
        createdAt: '2026-04-10T12:00:00',
      },
      summary: {
        analysisSummary: 'summary',
        operationAdvice: '持有',
        trendPrediction: '震荡',
        sentimentScore: 70,
      },
      strategy: {
        idealBuy: '120',
      },
      details: {
        strategySynthesis: fullSynthesis,
      },
    };
    const result: AnalysisResult = {
      queryId: 'q1',
      stockCode: '600519',
      stockName: '贵州茅台',
      report,
      diagnosticSummary: {
        status: 'normal',
        statusLabel: '正常',
        reason: '运行正常',
        components: {},
        copyText: '',
      },
      createdAt: '2026-04-10T12:00:00',
    };

    render(<ReportSummary data={result} />);

    await vi.waitFor(() => {
      expect(screen.getByText('暂无相关资讯')).toBeInTheDocument();
    });

    const overviewAnchor = screen.getByText('操作建议');
    const synthesisCard = screen.getByTestId('strategy-synthesis-card');
    const strategyAnchor = screen.getByText('狙击点位');

    expect(
      overviewAnchor.compareDocumentPosition(synthesisCard) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      synthesisCard.compareDocumentPosition(strategyAnchor) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});
