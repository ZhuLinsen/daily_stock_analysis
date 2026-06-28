import { describe, expect, it } from 'vitest';
import { parseDecisionSignalDate } from '../decisionSignalTime';

describe('parseDecisionSignalDate', () => {
  it('treats timezone-less DecisionSignal ISO strings as UTC', () => {
    expect(parseDecisionSignalDate('2098-12-31T16:00:00')?.toISOString()).toBe('2098-12-31T16:00:00.000Z');
  });

  it('preserves explicit timezone offsets and rejects invalid values', () => {
    expect(parseDecisionSignalDate('2098-12-31T16:00:00+08:00')?.toISOString()).toBe('2098-12-31T08:00:00.000Z');
    expect(parseDecisionSignalDate('not-a-date')).toBeNull();
  });
});
