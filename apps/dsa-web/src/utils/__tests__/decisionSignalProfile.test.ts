import { describe, expect, it } from 'vitest';
import type { DecisionSignalItem } from '../../types/decisionSignals';
import { getDecisionProfile } from '../decisionSignalProfile';

const signal: DecisionSignalItem = {
  id: 1,
  stockCode: '600519',
  market: 'cn',
  sourceType: 'analysis',
  triggerSource: 'web',
  action: 'hold',
  planQuality: 'complete',
  status: 'active',
};

describe('getDecisionProfile', () => {
  it.each(['conservative', 'balanced', 'aggressive'] as const)('reads %s from metadata', (profile) => {
    expect(getDecisionProfile({
      ...signal,
      metadata: { decision_profile: profile },
    })).toBe(profile);
  });

  it('returns unknown for missing or invalid metadata', () => {
    expect(getDecisionProfile(signal)).toBe('unknown');
    expect(getDecisionProfile({ ...signal, metadata: null })).toBe('unknown');
    expect(getDecisionProfile({ ...signal, metadata: [] })).toBe('unknown');
    expect(getDecisionProfile({ ...signal, metadata: { decision_profile: 'balanced-v2' } })).toBe('unknown');
  });
});
