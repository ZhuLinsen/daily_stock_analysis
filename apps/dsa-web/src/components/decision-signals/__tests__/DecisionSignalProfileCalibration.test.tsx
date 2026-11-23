import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import type {
  DecisionSignalProfileCalibration as DecisionSignalProfileCalibrationData,
  DecisionSignalProfileCalibrationBucket,
} from '../../../types/decisionSignals';
import { DecisionSignalProfileCalibration } from '../DecisionSignalProfileCalibration';

function bucket(
  dimensions: Record<string, string>,
  overrides: Partial<DecisionSignalProfileCalibrationBucket> = {},
): DecisionSignalProfileCalibrationBucket {
  return {
    dimensions,
    total: 30,
    completed: 30,
    unable: 0,
    hit: 15,
    miss: 15,
    neutral: 0,
    sampleSufficient: true,
    hitRatePct: 50,
    avgStockReturnPct: 1.25,
    missRatePct: 50,
    unableRatePct: 0,
    maxAdverseExcursionPct: 4.5,
    ...overrides,
  };
}

const calibration: DecisionSignalProfileCalibrationData = {
  minimumCompletedSampleSize: 30,
  breakdowns: {
    decisionProfile: [
      bucket(
        { decisionProfile: 'balanced' },
        { hitRatePct: 0, avgStockReturnPct: null, missRatePct: 100, maxAdverseExcursionPct: null },
      ),
      bucket(
        { decisionProfile: 'conservative' },
        {
          total: 29,
          completed: 29,
          hit: 14,
          miss: 15,
          sampleSufficient: false,
          hitRatePct: null,
          avgStockReturnPct: null,
          missRatePct: null,
          unableRatePct: null,
          maxAdverseExcursionPct: null,
        },
      ),
      bucket(
        { decisionProfile: 'unknown' },
        {
          total: 2,
          completed: 0,
          unable: 2,
          hit: 0,
          miss: 0,
          sampleSufficient: false,
          hitRatePct: null,
          avgStockReturnPct: null,
          missRatePct: null,
          unableRatePct: null,
          maxAdverseExcursionPct: null,
        },
      ),
    ],
    decisionProfileAction: [
      bucket({ decisionProfile: 'balanced', action: 'buy' }),
    ],
    decisionProfileHorizon: [
      bucket(
        { decisionProfile: 'balanced', horizon: '3d' },
        {
          total: 29,
          completed: 29,
          hit: 14,
          miss: 15,
          sampleSufficient: false,
          hitRatePct: null,
          avgStockReturnPct: null,
          missRatePct: null,
          unableRatePct: null,
          maxAdverseExcursionPct: null,
        },
      ),
    ],
    decisionProfileMarketPhase: [],
    decisionProfileDataQualityLevel: [],
    profileSource: [],
  },
};

function renderCalibration(value = calibration) {
  return render(
    <UiLanguageProvider>
      <DecisionSignalProfileCalibration calibration={value} />
    </UiLanguageProvider>,
  );
}

describe('DecisionSignalProfileCalibration', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem('dsa.uiLanguage', 'zh');
  });

  it('keeps profile and child sample gates independent and distinguishes zero from no result', () => {
    renderCalibration();

    expect(screen.getByRole('heading', { name: '决策风格历史表现' })).toBeInTheDocument();
    const balancedButton = screen.getByRole('button', { name: /均衡.*已完成 30/ });
    expect(balancedButton).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getAllByText('0%').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('暂无可计算结果').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('另有 2 条历史样本缺少决策风格标记，未计入三类风格。')).toBeInTheDocument();

    const horizonCard = screen.getByRole('heading', { name: '3 日' }).closest('article');
    expect(horizonCard).not.toBeNull();
    expect(within(horizonCard as HTMLElement).getByText('样本不足，仅供观察。')).toBeInTheDocument();
    expect(within(horizonCard as HTMLElement).queryByText('命中率')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /保守.*已完成 29/ }));
    expect(screen.getByRole('button', { name: /保守.*已完成 29/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('样本不足，仅供观察。')).toBeInTheDocument();
    expect(screen.getByText('暂无可观察的细分样本。')).toBeInTheDocument();
  });

  it('switches only between the two frozen user-facing breakdown views', () => {
    renderCalibration();

    const breakdownControls = screen.getByLabelText('细分统计方式');
    expect(within(breakdownControls).getAllByRole('button')).toHaveLength(2);
    const actionButton = within(breakdownControls).getByRole('button', { name: '按建议动作' });
    fireEvent.click(actionButton);

    expect(actionButton).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('heading', { name: '买入' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '3 日' })).not.toBeInTheDocument();
  });

  it('renders the same controls and disclosure in English', () => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
    renderCalibration();

    expect(screen.getByRole('heading', { name: 'Decision profile history' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Balanced.*30 completed/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    expect(screen.getByText(/descriptive only/)).toBeInTheDocument();
    expect(screen.getByText('Insufficient sample size; for observation only.')).toBeInTheDocument();
  });
});
