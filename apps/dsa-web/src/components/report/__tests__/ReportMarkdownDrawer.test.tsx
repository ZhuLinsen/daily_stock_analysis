import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const renderDrawer = async (onClose = vi.fn()) => {
  const { ReportMarkdownDrawer } = await import('../ReportMarkdownDrawer');

  render(
    <ReportMarkdownDrawer
      recordId={1}
      stockName="贵州茅台"
      stockCode="600519"
      onClose={onClose}
    />,
  );

  return onClose;
};

describe('ReportMarkdownDrawer', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.doUnmock('../ReportMarkdownPanel');
    vi.doUnmock('../../../api/history');
    vi.resetModules();
  });

  it('keeps panel render errors inside the drawer and closes with the drawer handler', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const onClose = vi.fn();

    vi.resetModules();
    vi.doMock('../ReportMarkdownPanel', () => ({
      ReportMarkdownPanel: () => {
        throw new Error('panel render failed');
      },
    }));

    try {
      await renderDrawer(onClose);

      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(await screen.findByText('加载报告失败')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: '关闭' }));

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
      await waitFor(() => {
        expect(onClose).toHaveBeenCalledTimes(1);
      });
    } finally {
      consoleError.mockRestore();
    }
  });

  it('keeps rejected lazy imports inside the drawer', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    vi.resetModules();
    vi.doMock('../ReportMarkdownPanel', () => Promise.reject(new Error('chunk load failed')));

    try {
      await renderDrawer();

      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(await screen.findByText('加载报告失败')).toBeInTheDocument();
    } finally {
      consoleError.mockRestore();
    }
  });

  it('retries loading the lazy panel after a rejected import and remount', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    let loadAttempts = 0;

    vi.resetModules();
    vi.doMock('../ReportMarkdownPanel', () => {
      loadAttempts += 1;
      if (loadAttempts === 1) {
        return Promise.reject(new Error('chunk load failed'));
      }

      return {
        ReportMarkdownPanel: () => <h2>Retried report panel</h2>,
      };
    });

    try {
      await renderDrawer();

      expect(await screen.findByText('加载报告失败')).toBeInTheDocument();

      cleanup();
      await renderDrawer();

      expect(await screen.findByRole('heading', { name: 'Retried report panel' })).toBeInTheDocument();
    } finally {
      consoleError.mockRestore();
    }
  });

  it('loads the real panel through the lazy boundary', async () => {
    vi.resetModules();
    vi.doMock('../../../api/history', () => ({
      historyApi: {
        getMarkdown: vi.fn().mockResolvedValue('# Lazy loaded report'),
      },
    }));

    await renderDrawer();

    expect(
      await screen.findByRole('heading', { name: 'Lazy loaded report' }, { timeout: 5000 }),
    ).toBeInTheDocument();
  });

  it('invokes onClose only once when duplicate close triggers fire within the exit transition', async () => {
    vi.resetModules();
    vi.doMock('../ReportMarkdownPanel', () => ({
      ReportMarkdownPanel: ({ onRequestClose }: { onRequestClose?: () => void }) => (
        <button type="button" onClick={onRequestClose}>
          面板关闭
        </button>
      ),
    }));

    const { ReportMarkdownDrawer } = await import('../ReportMarkdownDrawer');
    const onClose = vi.fn();

    render(
      <ReportMarkdownDrawer
        recordId={1}
        stockName="贵州茅台"
        stockCode="600519"
        onClose={onClose}
      />,
    );

    const panelCloseBtn = await screen.findByRole('button', { name: '面板关闭' });
    const drawerCloseBtn = screen.getByRole('button', { name: '关闭抽屉' });

    vi.useFakeTimers();

    act(() => {
      drawerCloseBtn.click();
      panelCloseBtn.click();
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('flushes onClose once and clears pending timer if unmounted during exit transition', async () => {
    vi.resetModules();
    vi.doMock('../ReportMarkdownPanel', () => ({
      ReportMarkdownPanel: () => <div>Loaded report</div>,
    }));

    const { ReportMarkdownDrawer } = await import('../ReportMarkdownDrawer');
    const onClose = vi.fn();

    const { unmount } = render(
      <ReportMarkdownDrawer
        recordId={1}
        stockName="贵州茅台"
        stockCode="600519"
        onClose={onClose}
      />,
    );

    await screen.findByText('Loaded report');

    vi.useFakeTimers();

    fireEvent.click(screen.getByRole('button', { name: '关闭抽屉' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(100);
    });
    expect(onClose).not.toHaveBeenCalled();

    unmount();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not call onClose when unmounted without initiating close', async () => {
    vi.resetModules();
    vi.doMock('../ReportMarkdownPanel', () => ({
      ReportMarkdownPanel: () => <div>Loaded report</div>,
    }));

    const { ReportMarkdownDrawer } = await import('../ReportMarkdownDrawer');
    const onClose = vi.fn();

    const { unmount } = render(
      <ReportMarkdownDrawer
        recordId={1}
        stockName="贵州茅台"
        stockCode="600519"
        onClose={onClose}
      />,
    );

    await screen.findByText('Loaded report');
    unmount();

    expect(onClose).not.toHaveBeenCalled();
  });

  it('flushes close across a keyed record switch mid-transition so the next report does not reopen', async () => {
    vi.resetModules();
    vi.doMock('../ReportMarkdownPanel', () => ({
      ReportMarkdownPanel: ({ recordId }: { recordId: number }) => <div>Report #{recordId}</div>,
    }));

    const { ReportMarkdownDrawer } = await import('../ReportMarkdownDrawer');
    const onCloseSpy = vi.fn();

    function KeyedSwitchHarness() {
      const [open, setOpen] = useState(true);
      const [recordId, setRecordId] = useState(1);

      return (
        <div>
          <button type="button" onClick={() => setRecordId(2)}>
            切换报告2
          </button>
          {open ? (
            <ReportMarkdownDrawer
              key={recordId}
              recordId={recordId}
              stockName={recordId === 1 ? '贵州茅台' : '平安银行'}
              stockCode={recordId === 1 ? '600519' : '000001'}
              onClose={() => {
                onCloseSpy();
                setOpen(false);
              }}
            />
          ) : null}
        </div>
      );
    }

    render(<KeyedSwitchHarness />);

    await screen.findByText('Report #1');

    fireEvent.click(screen.getByRole('button', { name: '关闭抽屉' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '切换报告2' }));

    await waitFor(() => {
      expect(onCloseSpy).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('guards ReportMarkdown wrapper close timer against duplicate triggers and unmount leaks', async () => {
    vi.resetModules();
    vi.doMock('../ReportMarkdownPanel', () => ({
      ReportMarkdownPanel: ({ onRequestClose }: { onRequestClose?: () => void }) => (
        <button type="button" onClick={onRequestClose}>
          面板关闭
        </button>
      ),
    }));

    const { ReportMarkdown } = await import('../ReportMarkdown');
    const onClose = vi.fn();

    vi.useFakeTimers();

    const { unmount } = render(
      <ReportMarkdown
        recordId={1}
        stockName="贵州茅台"
        stockCode="600519"
        onClose={onClose}
      />,
    );

    const panelCloseBtn = screen.getByRole('button', { name: '面板关闭' });
    const drawerCloseBtn = screen.getByRole('button', { name: '关闭抽屉' });

    act(() => {
      drawerCloseBtn.click();
      panelCloseBtn.click();
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(onClose).toHaveBeenCalledTimes(1);

    unmount();

    const onCloseUnmount = vi.fn();
    const secondRender = render(
      <ReportMarkdown
        recordId={2}
        stockName="腾讯控股"
        stockCode="HK00700"
        onClose={onCloseUnmount}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '关闭抽屉' }));
    await act(async () => {
      vi.advanceTimersByTime(100);
    });
    expect(onCloseUnmount).not.toHaveBeenCalled();

    secondRender.unmount();
    expect(onCloseUnmount).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(onCloseUnmount).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});
