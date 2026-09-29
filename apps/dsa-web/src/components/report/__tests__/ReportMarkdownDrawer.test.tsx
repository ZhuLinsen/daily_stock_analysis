import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
});
