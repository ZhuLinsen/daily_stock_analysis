import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Message } from '../../stores/agentChatStore';
import { UI_LANGUAGE_STORAGE_KEY } from '../uiLanguage';
import { downloadSession, formatSessionAsMarkdown, formatSessionForNotification, MAX_CHAT_NOTIFICATION_CHARS } from '../chatExport';

const sampleMessages: Message[] = [
  { id: 'u1', role: 'user', content: 'Analyze AAPL' },
  { id: 'a1', role: 'assistant', content: 'Bullish setup', skillName: 'Trend Analysis' },
];

describe('chatExport', () => {
  let createObjectUrlSpy: ReturnType<typeof vi.fn>;
  let revokeObjectUrlSpy: ReturnType<typeof vi.fn>;
  let clickSpy: ReturnType<typeof vi.spyOn>;
  const originalCreateObjectURL = URL.createObjectURL;
  const originalRevokeObjectURL = URL.revokeObjectURL;

  beforeEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
    createObjectUrlSpy = vi.fn(() => 'blob:mock-chat-export');
    revokeObjectUrlSpy = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: createObjectUrlSpy,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: revokeObjectUrlSpy,
    });
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: originalCreateObjectURL,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: originalRevokeObjectURL,
    });
  });

  it('formats session markdown in zh and en explicitly', () => {
    const zhMd = formatSessionAsMarkdown(sampleMessages, 'zh');
    expect(zhMd).toContain('# 问股会话');
    expect(zhMd).toContain('生成时间:');
    expect(zhMd).toContain('## 用户');
    expect(zhMd).toContain('## AI (Trend Analysis)');

    const enMd = formatSessionAsMarkdown(sampleMessages, 'en');
    expect(enMd).toContain('# Ask AI Session');
    expect(enMd).toContain('Generated at:');
    expect(enMd).toContain('## User');
    expect(enMd).toContain('## AI (Trend Analysis)');
  });

  it('defaults single-argument format and download calls to active stored UI language', () => {
    const createElementSpy = vi.spyOn(document, 'createElement');

    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    expect(formatSessionAsMarkdown(sampleMessages)).toContain('# 问股会话');
    downloadSession(sampleMessages);
    const zhAnchor = createElementSpy.mock.results
      .map((result) => result.value as HTMLElement)
      .find((el): el is HTMLAnchorElement => el.tagName === 'A');
    expect(zhAnchor?.download).toMatch(/^问股会话_\d{8}_\d{4}\.md$/);

    createElementSpy.mockClear();
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    expect(formatSessionAsMarkdown(sampleMessages)).toContain('# Ask AI Session');
    downloadSession(sampleMessages);
    const enAnchor = createElementSpy.mock.results
      .map((result) => result.value as HTMLElement)
      .find((el): el is HTMLAnchorElement => el.tagName === 'A');
    expect(enAnchor?.download).toMatch(/^ask-ai-session_\d{8}_\d{4}\.md$/);
    expect(clickSpy).toHaveBeenCalledTimes(2);
    expect(revokeObjectUrlSpy).toHaveBeenCalledTimes(2);
  });

  it('localizes built-in strategy names and preserves custom skill names even when colliding with built-in IDs', () => {
    const multiSkillMessages: Message[] = [
      { id: 'u1', role: 'user', content: 'Analyze 600519' },
      {
        id: 'a1',
        role: 'assistant',
        content: 'Structure looks constructive',
        skills: ['chan_theory', 'ma_golden_cross'],
        skillNames: ['缠论', '均线金叉'],
      },
    ];

    const enMd = formatSessionAsMarkdown(multiSkillMessages, 'en');
    expect(enMd).toContain('## AI (Chan Theory, MA Golden Cross)');
    expect(enMd).not.toContain('、');

    const zhMd = formatSessionAsMarkdown(multiSkillMessages, 'zh');
    expect(zhMd).toContain('## AI (缠论、均线金叉)');

    // A custom skill whose display name happens to equal a built-in strategy ID
    // (e.g. id="volume_custom", name="ma_golden_cross") must keep its literal name.
    const customCollidingMessages: Message[] = [
      { id: 'u2', role: 'user', content: 'Analyze 300750' },
      {
        id: 'a2',
        role: 'assistant',
        content: 'Volume expansion confirmed',
        skills: ['volume_custom'],
        skillNames: ['ma_golden_cross'],
      },
    ];
    const customEnMd = formatSessionAsMarkdown(customCollidingMessages, 'en', {
      skills: [{ id: 'volume_custom', name: 'ma_golden_cross', description: 'Custom volume rule' }],
    });
    expect(customEnMd).toContain('## AI (ma_golden_cross)');
    expect(customEnMd).not.toContain('MA Golden Cross');

    const customEnWithoutList = formatSessionAsMarkdown(customCollidingMessages, 'en');
    expect(customEnWithoutList).toContain('## AI (ma_golden_cross)');
    expect(customEnWithoutList).not.toContain('MA Golden Cross');
  });

  it('keeps borderline long sessions within the 50,000-character notification limit in EN mode without dropping message bodies', () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date('2026-11-26T16:00:00Z'));
      const longBody = 'x'.repeat(1239);
      const longMessages: Message[] = [];
      for (let i = 0; i < 20; i += 1) {
        longMessages.push({ id: `u-${i}`, role: 'user', content: `Q${i}:${longBody.slice(0, 1239 - (`Q${i}:`).length)}` });
        longMessages.push({ id: `a-${i}`, role: 'assistant', content: `A${i}:${longBody.slice(0, 1239 - (`A${i}:`).length)}` });
      }

      const zhMd = formatSessionAsMarkdown(longMessages, 'zh');
      const verboseEnMd = formatSessionAsMarkdown(longMessages, 'en');
      const notifyEnMd = formatSessionForNotification(longMessages, 'en');

      expect(zhMd.length).toBeLessThanOrEqual(MAX_CHAT_NOTIFICATION_CHARS);
      expect(verboseEnMd.length).toBeGreaterThan(MAX_CHAT_NOTIFICATION_CHARS);
      expect(notifyEnMd.length).toBeLessThanOrEqual(MAX_CHAT_NOTIFICATION_CHARS);
      expect(notifyEnMd).toContain('# Chat');
      expect(notifyEnMd).toContain('## Q');
      expect(notifyEnMd).toContain('Q0:');
      expect(notifyEnMd).toContain('A19:');
    } finally {
      vi.useRealTimers();
    }
  });
});
