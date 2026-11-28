import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { historyApi } from '../../../api/history';
import { ReportDetails } from '../ReportDetails';
import { ReportMarkdownPanel } from '../ReportMarkdownPanel';

vi.mock('../../../api/history', () => ({
  historyApi: {
    getMarkdown: vi.fn(),
  },
}));

describe('ReportMarkdownPanel', () => {
  let originalClipboard: Clipboard | undefined;
  let originalExecCommand: typeof document.execCommand | undefined;

  beforeEach(() => {
    originalClipboard = navigator.clipboard;
    originalExecCommand = document.execCommand;
    vi.mocked(historyApi.getMarkdown).mockReset();
    vi.mocked(historyApi.getMarkdown).mockResolvedValue('# Full Report\n\n**Buy** signal');
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

  it('falls back to execCommand for markdown and plain text copy when navigator.clipboard is unavailable', async () => {
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
      <ReportMarkdownPanel
        recordId={1}
        stockName="贵州茅台"
        stockCode="600519"
        onRequestClose={vi.fn()}
        reportLanguage="zh"
      />,
    );

    const markdownButton = await waitFor(() => {
      const btn = screen.getByRole('button', { name: '复制 Markdown 源码' });
      expect(btn).not.toBeDisabled();
      return btn;
    });

    vi.useFakeTimers();
    fireEvent.click(markdownButton);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole('button', { name: '已复制' })).toBeInTheDocument();
    expect(copiedValues[0]).toBe('# Full Report\n\n**Buy** signal');

    const plainTextButton = screen.getByRole('button', { name: '复制纯文本' });
    fireEvent.click(plainTextButton);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(copiedValues).toHaveLength(2);
    expect(copiedValues[1]).toContain('Full Report');
    expect(copiedValues[1]).not.toContain('**');
  });

  it('surfaces copy failure state, allows immediate retry, and resets after timeout', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const execCommand = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: undefined,
    });
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      writable: true,
      value: execCommand,
    });

    render(
      <ReportMarkdownPanel
        recordId={2}
        stockName="Apple"
        stockCode="AAPL"
        onRequestClose={vi.fn()}
        reportLanguage="en"
      />,
    );

    const markdownButton = await waitFor(() => {
      const btn = screen.getByRole('button', { name: 'Copy Markdown Source' });
      expect(btn).not.toBeDisabled();
      return btn;
    });

    vi.useFakeTimers();
    fireEvent.click(markdownButton);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const failedButton = screen.getByRole('button', { name: 'Copy failed' });
    expect(failedButton).not.toBeDisabled();
    expect(consoleError).toHaveBeenCalled();

    fireEvent.click(failedButton);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole('button', { name: 'Copied!' })).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole('button', { name: 'Copy Markdown Source' })).toBeInTheDocument();
  });

  it('prevents an earlier ReportDetails fallback from clobbering a newer ReportMarkdownPanel copy', async () => {
    let rejectRawWrite: ((err: Error) => void) | null = null;
    const writeText = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<void>((_resolve, reject) => {
            rejectRawWrite = reject;
          }),
      )
      .mockResolvedValueOnce(undefined);
    const execCommand = vi.fn().mockReturnValue(true);

    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      writable: true,
      value: execCommand,
    });

    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    render(
      <>
        <ReportDetails
          recordId={10}
          language="zh"
          details={{ rawResult: { code: '600519', score: 88 } }}
        />
        <ReportMarkdownPanel
          recordId={10}
          stockName="贵州茅台"
          stockCode="600519"
          onRequestClose={vi.fn()}
          reportLanguage="zh"
        />
      </>,
    );

    const markdownButton = await waitFor(() => {
      const btn = screen.getByRole('button', { name: '复制 Markdown 源码' });
      expect(btn).not.toBeDisabled();
      return btn;
    });

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole('button', { name: /原始分析结果/ }));
    fireEvent.click(screen.getByRole('button', { name: '复制' }));
    fireEvent.click(markdownButton);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole('button', { name: '已复制' })).toBeInTheDocument();

    await act(async () => {
      rejectRawWrite?.(new Error('NotAllowedError'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(execCommand).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '已复制' })).toBeInTheDocument();
    expect(consoleError).toHaveBeenCalled();
  });

  it('aborts legacy fallback when unmounted before navigator.clipboard.writeText rejects', async () => {
    let rejectWrite: ((err: Error) => void) | null = null;
    const writeText = vi.fn(
      () =>
        new Promise<void>((_resolve, reject) => {
          rejectWrite = reject;
        }),
    );
    const execCommand = vi.fn().mockReturnValue(true);

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
      <ReportMarkdownPanel
        recordId={3}
        stockName="贵州茅台"
        stockCode="600519"
        onRequestClose={vi.fn()}
        reportLanguage="zh"
      />,
    );

    const markdownButton = await waitFor(() => {
      const btn = screen.getByRole('button', { name: '复制 Markdown 源码' });
      expect(btn).not.toBeDisabled();
      return btn;
    });

    fireEvent.click(markdownButton);
    unmount();

    await act(async () => {
      rejectWrite?.(new Error('NotAllowedError'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(execCommand).not.toHaveBeenCalled();
  });
});
