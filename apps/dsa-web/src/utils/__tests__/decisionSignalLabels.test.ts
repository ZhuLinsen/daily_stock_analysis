import { describe, expect, it } from 'vitest';
import {
  getDecisionSignalHorizonLabel,
  getDecisionSignalMarketLabel,
  getDecisionSignalMarketPhaseLabel,
  getDecisionSignalPlanQualityLabel,
  getDecisionSignalSourceTypeLabel,
} from '../decisionSignalLabels';
import type { UiTextKey } from '../../i18n/uiText';

const labels: Partial<Record<UiTextKey, string>> = {
  'decisionSignals.horizon.10d': '10 days',
  'decisionSignals.market.jp': 'Japan',
  'decisionSignals.marketPhase.closing_auction': 'Closing auction',
  'decisionSignals.planQuality.partial': 'Partial',
  'decisionSignals.sourceType.market_review': 'Market review',
};

const t = (key: UiTextKey): string => labels[key] ?? '';

describe('decisionSignalLabels helpers', () => {
  it('maps known wire values through explicit i18n keys', () => {
    expect(getDecisionSignalMarketLabel('jp', t)).toBe('Japan');
    expect(getDecisionSignalMarketPhaseLabel('closing_auction', t)).toBe('Closing auction');
    expect(getDecisionSignalHorizonLabel('10d', t)).toBe('10 days');
    expect(getDecisionSignalPlanQualityLabel('partial', t)).toBe('Partial');
    expect(getDecisionSignalSourceTypeLabel('market_review', t)).toBe('Market review');
  });

  it('does not expose unknown runtime values as raw enum text', () => {
    expect(getDecisionSignalHorizonLabel('30d' as never, t)).toBe('-');
    expect(getDecisionSignalSourceTypeLabel('batch_job' as never, t)).toBe('-');
  });
});
