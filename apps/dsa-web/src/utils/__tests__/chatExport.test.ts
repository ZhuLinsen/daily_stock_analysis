import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Message } from '../../stores/agentChatStore';
import { UI_LANGUAGE_STORAGE_KEY } from '../uiLanguage';
import { downloadSession, formatSessionAsMarkdown } from '../chatExport';

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

  it('localizes built-in strategy names and multi-skill delimiters when exporting in EN mode', () => {
    const multiSkillMessages: Message[] = [
      { id: 'u1', role: 'user', content: 'Analyze 600519' },
      {
        id: 'a1',
        role: 'assistant',
        content: 'Structure looks constructive',
        skillNames: ['缠论', 'ma_golden_cross'],
      },
    ];

    const enMd = formatSessionAsMarkdown(multiSkillMessages, 'en');
    expect(enMd).toContain('## AI (Chan Theory, MA Golden Cross)');
    expect(enMd).not.toContain('、');

    const zhMd = formatSessionAsMarkdown(multiSkillMessages, 'zh');
    expect(zhMd).toContain('## AI (缠论、ma_golden_cross)');
  });
});
