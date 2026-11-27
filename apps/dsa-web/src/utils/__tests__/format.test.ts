import { fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider, useUiLanguage } from '../../contexts/UiLanguageContext';
import { buildFollowUpPrompt } from '../chatFollowUp';
import {
  formatDate,
  formatDateInShanghai,
  formatDateTime,
  formatReportType,
  formatShortDateTime,
  getRecentStartDate,
  getTodayInShanghai,
  resolveActiveUiLanguage,
  shiftDateKey,
} from '../format';
import { UI_LANGUAGE_STORAGE_KEY } from '../uiLanguage';
import { validateStockCode } from '../validation';

describe('Shanghai calendar date helpers', () => {
  afterEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
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

describe('UI language-aware formatters', () => {
  afterEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
    document.documentElement.lang = '';
  });

  it('formats report types in zh, en, and stored UI language', () => {
    expect(formatReportType('simple')).toBe('普通');
    expect(formatReportType('detailed', 'zh')).toBe('标准');
    expect(formatReportType('full', 'zh')).toBe('完整');
    expect(formatReportType('brief', 'zh')).toBe('简版');
    expect(formatReportType('market_review', 'zh')).toBe('大盘');

    expect(formatReportType('simple', 'en')).toBe('Simple');
    expect(formatReportType('detailed', 'en')).toBe('Detailed');
    expect(formatReportType('full', 'en')).toBe('Full');
    expect(formatReportType('brief', 'en')).toBe('Brief');
    expect(formatReportType('market_review', 'en')).toBe('Market Review');
    expect(formatReportType('custom_mode', 'en')).toBe('custom_mode');
    expect(formatReportType(undefined, 'en')).toBe('—');

    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    expect(formatReportType('market_review')).toBe('Market Review');
  });

  it('formats dates and timestamps using active locale', () => {
    const sampleIso = '2026-05-18T09:30:00Z';
    const sampleDate = new Date(sampleIso);
    const expectedZhDateTime = new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(sampleDate);
    const expectedEnDateTime = new Intl.DateTimeFormat('en-US', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(sampleDate);
    const expectedEnDate = new Intl.DateTimeFormat('en-US', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(sampleDate);

    expect(formatDateTime(sampleIso, 'zh')).toBe(expectedZhDateTime);
    expect(formatDateTime(sampleIso, 'en')).toBe(expectedEnDateTime);
    expect(formatDate(sampleIso, 'en')).toBe(expectedEnDate);

    const expectedZhShortDateTime = new Intl.DateTimeFormat('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(sampleDate);
    const expectedEnShortDateTime = new Intl.DateTimeFormat('en-US', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(sampleDate);
    expect(formatShortDateTime(sampleIso, 'zh')).toBe(expectedZhShortDateTime);
    expect(formatShortDateTime(sampleIso, 'en')).toBe(expectedEnShortDateTime);
    expect(expectedEnShortDateTime).toMatch(/05\/18/);
    expect(expectedEnShortDateTime).not.toContain('/2026');

    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    expect(formatDateTime(sampleIso)).toBe(expectedEnDateTime);
    expect(formatDate(sampleIso)).toBe(expectedEnDate);
    expect(formatDateTime(null)).toBe('—');

    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
    document.documentElement.lang = 'en';
    expect(formatReportType('market_review')).toBe('Market Review');
    expect(formatDateTime(sampleIso)).toBe(expectedEnDateTime);
  });

  it('prefers mounted tab provider and document language over cross-tab localStorage writes', () => {
    // Tab A DOM is English while Tab B overwrote shared localStorage to Chinese
    document.documentElement.lang = 'en';
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');

    expect(resolveActiveUiLanguage()).toBe('en');
    expect(validateStockCode('').message).toBe('Please enter a stock code');
    expect(buildFollowUpPrompt('AAPL', null)).toBe('Please analyze AAPL in depth');
    expect(formatReportType('market_review')).toBe('Market Review');

    // Mounted UiLanguageProvider in English stays immune to subsequent localStorage mutations
    document.documentElement.lang = '';
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    const { unmount } = render(
      React.createElement(UiLanguageProvider, null, React.createElement('div'))
    );
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');

    expect(resolveActiveUiLanguage()).toBe('en');
    expect(validateStockCode('').message).toBe('Please enter a stock code');
    expect(buildFollowUpPrompt('AAPL', null)).toBe('Please analyze AAPL in depth');

    // Unmounting restores documentElement.lang = '' and removes provider entry so storage fallback works
    unmount();
    expect(document.documentElement.lang).toBe('');
    expect(resolveActiveUiLanguage()).toBe('zh');
  });

  it('synchronously updates active tab language before child memoized render reads arg-less formatters', () => {
    const sampleIso = '2026-05-18T09:30:00Z';
    const expectedZhDateTime = formatDateTime(sampleIso, 'zh');
    const expectedEnDateTime = formatDateTime(sampleIso, 'en');

    const RenderPhaseDateChild = () => {
      const { setLanguage, t } = useUiLanguage();
      const formatted = React.useMemo(() => formatDateTime(sampleIso), [t]);
      return React.createElement(
        React.Fragment,
        null,
        React.createElement('span', { 'data-testid': 'memo-date' }, formatted),
        React.createElement('button', { type: 'button', onClick: () => setLanguage('en') }, 'to-en'),
      );
    };

    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    render(
      React.createElement(UiLanguageProvider, null, React.createElement(RenderPhaseDateChild)),
    );

    expect(screen.getByTestId('memo-date').textContent).toBe(expectedZhDateTime);
    fireEvent.click(screen.getByRole('button', { name: 'to-en' }));
    expect(screen.getByTestId('memo-date').textContent).toBe(expectedEnDateTime);
  });
});
