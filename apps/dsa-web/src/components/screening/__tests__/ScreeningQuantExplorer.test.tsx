import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type {
  ScreeningCandidate,
  ScreeningStrategy,
  ScreeningStrategyStyle,
} from '../../../api/screening';
import {
  escapeCsvCell,
  sanitizeFilenameSegment,
} from '../../../utils/screeningQuant';
import {
  CandidateComparisonMatrix,
  StrategyFactorBlueprint,
} from '../ScreeningQuantExplorer';

function makeCandidate(
  overrides: Partial<ScreeningCandidate> = {},
): ScreeningCandidate {
  return {
    rank: 1,
    code: '600519',
    name: '贵州茅台',
    industry: '白酒',
    price: 1520.0,
    changePct: 1.85,
    score: 86.4,
    riskLevel: 'low',
    reason: '稳健估值',
    factorScores: {
      momentum: 68.0,
      value: 92.5,
    },
    raw: {},
    ...overrides,
  };
}

describe('ScreeningQuantExplorer components & helpers', () => {
  it('renders localized watchlist holdingPeriod and snake_case market_regime badges in ZH and EN', () => {
    const rawStyle = {
      risk_profile: 'defensive',
      holding_period: 'watchlist',
      market_regime: ['risk_off', 'range_bound'],
    } as unknown as ScreeningStrategyStyle;

    const strategy: ScreeningStrategy = {
      id: 'quality_value',
      name: '质量价值',
      description: '高质量低波',
      factorWeights: { value: 0.6, stability: 0.4 },
      style: rawStyle,
    };

    const { rerender } = render(
      <StrategyFactorBlueprint strategy={strategy} language="zh" />,
    );
    expect(screen.getByText('持续观察')).toBeInTheDocument();
    expect(screen.getByText('防御避险 / 区间震荡')).toBeInTheDocument();

    rerender(<StrategyFactorBlueprint strategy={strategy} language="en" />);
    expect(screen.getByText('Watchlist')).toBeInTheDocument();
    expect(screen.getByText('Risk-Off / Range-Bound')).toBeInTheDocument();
  });

  it('handles 0, 1, and >=2 compared candidates with optional AI score row and distinct remove aria-label', () => {
    const c1 = makeCandidate({ code: '600519', name: '贵州茅台', llmScore: 91.2 });
    const c2 = makeCandidate({
      rank: 2,
      code: '300750',
      name: '宁德时代',
      score: 82.1,
      llmScore: 84.5,
      riskLevel: 'medium',
      factorScores: { momentum: 95.0, value: 70.0 },
    });

    const onRemove = vi.fn();
    const onClear = vi.fn();

    const { container, rerender } = render(
      <CandidateComparisonMatrix
        candidates={[]}
        language="zh"
        onRemove={onRemove}
        onClear={onClear}
      />,
    );
    expect(container.firstChild).toBeNull();

    // 1 candidate -> compact pinned tray with 1/3 progress prompt
    rerender(
      <CandidateComparisonMatrix
        candidates={[c1]}
        language="zh"
        onRemove={onRemove}
        onClear={onClear}
      />,
    );
    expect(
      screen.getByText('已选 1/3 只对比，再选 1 只展开因子矩阵'),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '移除对比 600519' }));
    expect(onRemove).toHaveBeenCalledWith('600519');
    fireEvent.click(screen.getByRole('button', { name: '清空对比' }));
    expect(onClear).toHaveBeenCalledTimes(1);

    // 2 candidates with llmScore -> full matrix + AI score row + distinct Remove aria-label in EN
    rerender(
      <CandidateComparisonMatrix
        candidates={[c1, c2]}
        language="en"
        onRemove={onRemove}
        onClear={onClear}
      />,
    );
    expect(screen.getByText('Multi-Candidate Quant Factor Comparison Matrix')).toBeInTheDocument();
    expect(screen.getByText('Select up to 3 candidates')).toBeInTheDocument();
    expect(screen.getByText('AI Score')).toBeInTheDocument();
    expect(screen.getByText('91.20')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove 600519' })).toBeInTheDocument();

    // 2 candidates without llmScore -> omits AI score row
    const noLlm1 = makeCandidate({ code: '600519', llmScore: undefined });
    const noLlm2 = makeCandidate({ code: '300750', name: '宁德时代', llmScore: undefined });
    rerender(
      <CandidateComparisonMatrix
        candidates={[noLlm1, noLlm2]}
        language="en"
        onRemove={onRemove}
        onClear={onClear}
      />,
    );
    expect(screen.queryByText('AI Score')).not.toBeInTheDocument();
  });

  it('sanitizes CSV export filenames and leading-whitespace/newline formula payloads', () => {
    expect(sanitizeFilenameSegment('foo/bar baz')).toBe('foo_bar_baz');
    expect(sanitizeFilenameSegment('///')).toBe('custom');
    expect(escapeCsvCell(' =SUM(1,2)')).toBe('"\' =SUM(1,2)"');
    expect(escapeCsvCell('\n=1+1')).toBe('"\'\n=1+1"');
    expect(escapeCsvCell('-2.35')).toBe('"-2.35"');
  });

  it('displays <1% instead of 0% for small positive factor weights in StrategyFactorBlueprint', () => {
    const strategy: ScreeningStrategy = {
      id: 'sub_percent',
      name: 'Tiny Weight',
      description: 'sub-1% weight test',
      factorWeights: { value: 0.002, momentum: 0.998 },
    };

    render(<StrategyFactorBlueprint strategy={strategy} language="en" />);
    expect(screen.getByText('<1%')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
  });
});
