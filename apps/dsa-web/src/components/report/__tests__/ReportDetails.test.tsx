import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ReportDetails } from '../ReportDetails';

describe('ReportDetails', () => {
  const writeTextMock = vi.fn().mockResolvedValue(undefined);
  let originalClipboard: Navigator['clipboard'] | undefined;
  let originalExecCommand: PropertyDescriptor | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    writeTextMock.mockReset();
    writeTextMock.mockResolvedValue(undefined);
    originalClipboard = navigator.clipboard;
    originalExecCommand = Object.getOwnPropertyDescriptor(document, 'execCommand');
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: writeTextMock,
      },
    });
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: originalClipboard,
    });
    if (originalExecCommand) {
      Object.defineProperty(document, 'execCommand', originalExecCommand);
    } else {
      Reflect.deleteProperty(document, 'execCommand');
    }
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('keeps copied feedback scoped to the panel that was copied', async () => {
    const details = {
      rawResult: { score: 82 },
      contextSnapshot: { window: '30d' },
    };

    render(
      <ReportDetails
        recordId={7}
        details={details}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '原始分析结果' }));
    fireEvent.click(screen.getByRole('button', { name: '分析快照' }));

    const [rawCopyButton, snapshotCopyButton] = screen.getAllByRole('button', { name: '复制' });

    await act(async () => {
      fireEvent.click(rawCopyButton);
      await Promise.resolve();
    });

    expect(writeTextMock).toHaveBeenNthCalledWith(1, JSON.stringify(details.rawResult, null, 2));
    expect(screen.getByRole('button', { name: '已复制' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '复制' })).toHaveLength(1);

    await act(async () => {
      fireEvent.click(snapshotCopyButton);
      await Promise.resolve();
    });

    expect(writeTextMock).toHaveBeenNthCalledWith(2, JSON.stringify(details.contextSnapshot, null, 2));
    expect(screen.getAllByRole('button', { name: '已复制' })).toHaveLength(2);

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.getAllByRole('button', { name: '复制' })).toHaveLength(2);
  });

  it('does not render when details and record id are both absent', () => {
    const { container } = render(<ReportDetails />);
    expect(container).toBeEmptyDOMElement();
  });

  it('copies via legacy fallback on plain HTTP and surfaces failure state when copy fails', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: undefined,
    });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    });

    const details = {
      rawResult: { score: 82 },
    };

    render(<ReportDetails recordId={7} details={details} language="en" />);
    fireEvent.click(screen.getByRole('button', { name: 'Raw Analysis Result' }));

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
      await Promise.resolve();
    });

    expect(execCommand).toHaveBeenCalledWith('copy');
    expect(screen.getByRole('button', { name: 'Copied!' })).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    execCommand.mockReturnValue(false);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
      await Promise.resolve();
    });

    expect(screen.getByRole('button', { name: 'Copy failed' })).toBeInTheDocument();
    expect(consoleErrorSpy).toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
  });

  it('resets copy feedback immediately when record changes and ignores stale async settlements', async () => {
    let resolveClipboard!: () => void;
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: vi
          .fn()
          .mockImplementationOnce(
            () => new Promise<void>((resolve) => {
              resolveClipboard = resolve;
            }),
          )
          .mockResolvedValue(undefined),
      },
    });

    const { rerender } = render(
      <ReportDetails recordId={7} details={{ rawResult: { score: 82 } }} language="en" />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Raw Analysis Result' }));
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

    rerender(
      <ReportDetails recordId={8} details={{ rawResult: { score: 91 } }} language="en" />,
    );
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();

    await act(async () => {
      resolveClipboard();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
      await Promise.resolve();
    });
    expect(screen.getByRole('button', { name: 'Copied!' })).toBeInTheDocument();

    rerender(
      <ReportDetails recordId={7} details={{ rawResult: { score: 82 } }} language="en" />,
    );
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();
  });

  it('skips execCommand fallback when a stale writeText rejects after switching reports or copying another panel', async () => {
    let rejectRecord7Raw!: (reason?: unknown) => void;
    let rejectRecord8Raw!: (reason?: unknown) => void;
    const writeText = vi
      .fn()
      .mockImplementationOnce(
        () => new Promise<void>((_resolve, reject) => {
          rejectRecord7Raw = reject;
        }),
      )
      .mockResolvedValueOnce(undefined)
      .mockImplementationOnce(
        () => new Promise<void>((_resolve, reject) => {
          rejectRecord8Raw = reject;
        }),
      )
      .mockResolvedValueOnce(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    });

    const { rerender } = render(
      <ReportDetails
        recordId={7}
        details={{ rawResult: { score: 82 }, contextSnapshot: { window: '30d' } }}
        language="en"
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Raw Analysis Result' }));
    fireEvent.click(screen.getByRole('button', { name: 'Analysis Snapshot' }));

    // 1) Start copying record 7 raw -> switch to record 8 and copy record 8 raw.
    const [rawBtn7] = screen.getAllByRole('button', { name: 'Copy' });
    fireEvent.click(rawBtn7);

    rerender(
      <ReportDetails
        recordId={8}
        details={{ rawResult: { score: 91 }, contextSnapshot: { window: '60d' } }}
        language="en"
      />,
    );
    const [rawBtn8, snapshotBtn8] = screen.getAllByRole('button', { name: 'Copy' });
    await act(async () => {
      fireEvent.click(rawBtn8);
      await Promise.resolve();
    });
    expect(screen.getByRole('button', { name: 'Copied!' })).toBeInTheDocument();

    // Record 7's pending writeText rejects -> must NOT invoke execCommand or clobber record 8.
    await act(async () => {
      rejectRecord7Raw(new DOMException('Denied', 'NotAllowedError'));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(execCommand).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Copied!' })).toBeInTheDocument();

    // 2) On record 8, start a new pending raw copy, then succeed copying snapshot -> raw rejects.
    fireEvent.click(screen.getByRole('button', { name: 'Copied!' }));
    await act(async () => {
      fireEvent.click(snapshotBtn8);
      await Promise.resolve();
    });
    await act(async () => {
      rejectRecord8Raw(new DOMException('Denied', 'NotAllowedError'));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(execCommand).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Copy failed' })).not.toBeInTheDocument();
    // Snapshot succeeded; raw button must NOT stay stuck on 'Copied!' after its retry was superseded.
    expect(screen.getAllByRole('button', { name: 'Copied!' })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: 'Copy' })).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.queryByRole('button', { name: 'Copied!' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Copy' })).toHaveLength(2);
  });

  it('clears active copy reset timers on unmount even after content changes', async () => {
    const { rerender, unmount } = render(
      <ReportDetails recordId={7} details={{ rawResult: { score: 82 } }} language="en" />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Raw Analysis Result' }));

    // Trigger contentKey change before setting a copy reset timer to verify ref identity is preserved.
    rerender(
      <ReportDetails recordId={8} details={{ rawResult: { score: 91 } }} language="en" />,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
      await Promise.resolve();
    });
    expect(screen.getByRole('button', { name: 'Copied!' })).toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(1);

    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
