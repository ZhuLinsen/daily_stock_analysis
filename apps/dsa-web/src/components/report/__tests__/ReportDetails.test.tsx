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

  it('renders ABU, Kronos, and vn.py as separate evidence cards', () => {
    render(<ReportDetails details={{
      quantEnrichment: {
        status: 'ok',
        asOf: '2026-08-01',
        dataQuality: { status: '正常' },
        technical: { states: ['EMA多头排列'] },
        kronos: { points: [{}, {}, {}, {}, {}], endReturnPct: 1.25, positivePathRatio: 0.6, pathCount: 20 },
        validation: { status: 'ok', sampleCount: 24, horizonDays: 5, directionWinRate: 0.625, medianDirectionalReturn: 0.008, confidence: 'medium' },
      },
    }} />);

    expect(screen.getByText('ABU 规则信号')).toBeInTheDocument();
    expect(screen.getByText('Kronos 概率预测')).toBeInTheDocument();
    expect(screen.getByText('vn.py 历史评价')).toBeInTheDocument();
    expect(screen.getByText(/样本 24 · 胜率 62.5%/)).toBeInTheDocument();
  });

  it('shows recent daily signals before older weekly signals', () => {
    render(<ReportDetails details={{
      quantEnrichment: {
        status: 'ok',
        asOf: '2026-08-05',
        technical: {
          recentDays: 7,
          events: [
            { eventId: 'old-week', date: '2026-06-26', timeframe: '1w', direction: 'bearish', name: '旧周线信号', detail: '旧信号' },
            { eventId: 'recent-day', date: '2026-08-05', timeframe: '1d', direction: 'bullish', name: '20日新高突破', detail: '最新信号' },
          ],
        },
      },
    }} />);

    const recentSignalPanel = screen.getByText(/最近 7 日及 8 周信号/).parentElement;
    expect(recentSignalPanel).not.toBeNull();
    const panelText = recentSignalPanel?.textContent || '';
    expect(panelText).toContain('20日新高突破');
    expect(panelText.indexOf('20日新高突破')).toBeLessThan(panelText.indexOf('旧周线信号'));
  });
});
