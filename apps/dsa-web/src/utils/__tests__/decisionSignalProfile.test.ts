import { describe, expect, it } from 'vitest';
import type { DecisionSignalItem } from '../../types/decisionSignals';
import { getDecisionProfile, getDecisionProfileLabel } from '../decisionSignalProfile';

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
  it('prefers the first-class field over legacy metadata', () => {
    expect(getDecisionProfile({
      ...signal,
      decisionProfile: 'aggressive',
      metadata: { decision_profile: 'balanced' },
    })).toBe('aggressive');
  });

  it.each(['conservative', 'balanced', 'aggressive'] as const)('reads %s from metadata', (profile) => {
    expect(getDecisionProfile({
      ...signal,
      metadata: { decision_profile: profile },
    })).toBe(profile);
  });

  it('treats explicit null first-class profile as unknown without metadata fallback', () => {
    expect(getDecisionProfile({
      ...signal,
      decisionProfile: null,
      metadata: { decision_profile: 'balanced' },
    })).toBe('unknown');
  });

  it('returns unknown for missing or invalid metadata', () => {
    expect(getDecisionProfile(signal)).toBe('unknown');
    expect(getDecisionProfile({ ...signal, decisionProfile: undefined, metadata: { decision_profile: 'balanced' } })).toBe('unknown');
    expect(getDecisionProfile({ ...signal, metadata: null })).toBe('unknown');
    expect(getDecisionProfile({ ...signal, metadata: [] })).toBe('unknown');
    expect(getDecisionProfile({ ...signal, metadata: { decision_profile: 'balanced-v2' } })).toBe('unknown');
  });

  it('maps profile display values through UI labels', () => {
    const labels = {
      'decisionSignals.profile.aggressive': '进取',
      'decisionSignals.profile.balanced': '均衡',
      'decisionSignals.profile.conservative': '保守',
      'decisionSignals.profile.unknown': '未知',
    } as const;
    const t = (key: string) => labels[key as keyof typeof labels] ?? key;

    expect(getDecisionProfileLabel('aggressive', t)).toBe('进取');
    expect(getDecisionProfileLabel('unknown', t)).toBe('未知');
  });
});
