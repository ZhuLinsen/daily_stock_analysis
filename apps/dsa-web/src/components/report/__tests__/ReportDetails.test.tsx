import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ReportDetails } from '../ReportDetails';

describe('ReportDetails', () => {
  const writeTextMock = vi.fn().mockResolvedValue(undefined);
  let originalClipboard: Navigator['clipboard'] | undefined;

  beforeEach(() => {
    vi.useFakeTimers();
    writeTextMock.mockClear();
    originalClipboard = navigator.clipboard;
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
});
