import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MarketReviewPayload } from '../../../types/analysis';
import { MarketReviewReportView } from '../MarketReviewReportView';

vi.mock('../../../api/history', () => ({
  historyApi: {
    getMarkdown: vi.fn(),
  },
}));

const sampleMarketReviewPayload: MarketReviewPayload = {
  version: 1,
  kind: 'market_review',
  region: 'cn',
  language: 'zh',
  rootTitle: '大盘复盘',
};

describe('MarketReviewReportView clipboard fallback', () => {
  let originalClipboard: Clipboard | undefined;
  let originalExecCommand: typeof document.execCommand | undefined;

  beforeEach(() => {
    originalClipboard = navigator.clipboard;
    originalExecCommand = document.execCommand;
  });

  afterEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: originalClipboard,
    });
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      writable: true,
      value: originalExecCommand,
    });
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('falls back to execCommand for markdown and plain text copy on plain HTTP', async () => {
    const copiedValues: string[] = [];
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      writable: true,
      value: vi.fn(() => {
        const textarea = document.body.querySelector('textarea');
        if (textarea) {
          copiedValues.push(textarea.value);
        }
        return true;
      }),
    });

    render(
      <MarketReviewReportView
        payload={sampleMarketReviewPayload}
        content={'# 大盘复盘\n\n**放量上涨**'}
        recordId={8}
        reportLanguage="zh"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '复制 Markdown 源码' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '已复制' })).toBeInTheDocument();
    });
    expect(copiedValues[0]).toBe('# 大盘复盘\n\n**放量上涨**');

    fireEvent.click(screen.getByRole('button', { name: '复制纯文本' }));
    await waitFor(() => {
      expect(copiedValues).toHaveLength(2);
    });
    expect(copiedValues[1]).toContain('放量上涨');
    expect(copiedValues[1]).not.toContain('**');
  });

  it('surfaces failure state and aborts pending fallback on unmount', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    let rejectWrite: ((err: Error) => void) | null = null;
    const writeText = vi
      .fn()
      .mockRejectedValueOnce(new Error('NotAllowedError'))
      .mockImplementationOnce(
        () =>
          new Promise<void>((_resolve, reject) => {
            rejectWrite = reject;
          }),
      );
    const execCommand = vi.fn().mockReturnValue(false);

    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      writable: true,
      value: execCommand,
    });

    const { unmount } = render(
      <MarketReviewReportView
        payload={sampleMarketReviewPayload}
        content="# Market Review"
        recordId={9}
        reportLanguage="en"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Copy Markdown Source' }));
    const failedButton = await screen.findByRole('button', { name: 'Copy failed' });
    expect(consoleError).toHaveBeenCalled();
    expect(execCommand).toHaveBeenCalledTimes(1);

    fireEvent.click(failedButton);
    unmount();

    await act(async () => {
      rejectWrite?.(new Error('NotAllowedError'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(execCommand).toHaveBeenCalledTimes(1);
  });
});
