import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatDateInShanghai, getRecentStartDate, getTodayInShanghai, shiftDateKey } from '../format';

describe('Shanghai calendar date helpers', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('computes 30-day and 90-day Shanghai start dates across DST boundaries', () => {
    vi.useFakeTimers();

    vi.setSystemTime(new Date('2026-03-10T15:30:00Z'));
    expect(getTodayInShanghai()).toBe('2026-03-10');
    expect(getRecentStartDate(30)).toBe('2026-02-08');
    expect(getRecentStartDate(90)).toBe('2025-12-10');

    vi.setSystemTime(new Date('2026-11-02T16:30:00Z'));
    expect(getTodayInShanghai()).toBe('2026-11-03');
    expect(getRecentStartDate(30)).toBe('2026-10-04');
    expect(getRecentStartDate(90)).toBe('2026-08-05');
  });

  it('does not throw when Intl.DateTimeFormat.prototype.format returns a non-ISO M/d/y string (CLDR 42 regression)', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-03-10T15:30:00Z'));

    // Simulate browsers (e.g. Firefox 111 / CLDR 42) where en-CA format() yields "3/10/2026".
    const originalDescriptor = Object.getOwnPropertyDescriptor(Intl.DateTimeFormat.prototype, 'format');
    Object.defineProperty(Intl.DateTimeFormat.prototype, 'format', {
      configurable: true,
      get: () => () => '3/10/2026',
    });

    try {
      expect(getTodayInShanghai()).toBe('2026-03-10');
      expect(getRecentStartDate(30)).toBe('2026-02-08');
      expect(getRecentStartDate(90)).toBe('2025-12-10');
    } finally {
      if (originalDescriptor) {
        Object.defineProperty(Intl.DateTimeFormat.prototype, 'format', originalDescriptor);
      }
    }
  });

  it('zero-pads single-digit month and day parts returned by formatToParts', () => {
    vi.spyOn(Intl.DateTimeFormat.prototype, 'formatToParts').mockReturnValue([
      { type: 'month', value: '3' },
      { type: 'literal', value: '/' },
      { type: 'day', value: '5' },
      { type: 'literal', value: '/' },
      { type: 'year', value: '2026' },
    ]);

    expect(formatDateInShanghai(new Date('2026-03-05T08:00:00Z'))).toBe('2026-03-05');
    expect(shiftDateKey('2026-03-05', -30)).toBe('2026-02-03');
  });
});
