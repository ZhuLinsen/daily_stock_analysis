import { act, fireEvent, render, screen } from '@testing-library/react';
import type React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { JsonViewer } from '../JsonViewer';

function renderJsonViewer(data: React.ComponentProps<typeof JsonViewer>['data']) {
  return render(
    <UiLanguageProvider>
      <JsonViewer data={data} />
    </UiLanguageProvider>,
  );
}

describe('JsonViewer', () => {
  let originalClipboard: PropertyDescriptor | undefined;
  let originalExecCommand: PropertyDescriptor | undefined;

  beforeEach(() => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    originalClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    originalExecCommand = Object.getOwnPropertyDescriptor(document, 'execCommand');
  });

  afterEach(() => {
    if (originalClipboard) {
      Object.defineProperty(navigator, 'clipboard', originalClipboard);
    } else {
      Reflect.deleteProperty(navigator, 'clipboard');
    }
    if (originalExecCommand) {
      Object.defineProperty(document, 'execCommand', originalExecCommand);
    } else {
      Reflect.deleteProperty(document, 'execCommand');
    }
    window.localStorage.clear();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('renders html-like JSON strings as inert text', () => {
    const { container } = renderJsonViewer({
      payload: '<img src=x onerror="window.__jsonViewerXss = true">',
      nested: {
        script: '<script>window.__jsonViewerScript = true</script>',
      },
    });

    expect(container.textContent).toContain('<img src=x onerror=\\"window.__jsonViewerXss = true\\">');
    expect(container.textContent).toContain('<script>window.__jsonViewerScript = true</script>');
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('[onerror]')).toBeNull();
  });

  it('keeps keys and values visually tokenized without injecting html', () => {
    renderJsonViewer({
      status: true,
      score: 82,
      note: 'ok',
    });

    expect(screen.getByText('"status"')).toHaveClass('text-cyan-400');
    expect(screen.getByText('true')).toHaveClass('text-purple-400');
    expect(screen.getByText('82')).toHaveClass('text-amber-400');
    expect(screen.getByText('"ok"')).toHaveClass('text-emerald-400');
  });

  it('supports fallback copy without throwing on HTTP and surfaces failure state', async () => {
    vi.useFakeTimers();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: undefined,
    });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    });

    renderJsonViewer({ ok: true });

    const copyBtn = screen.getByRole('button', { name: '复制' });
    expect(copyBtn).toHaveAttribute('type', 'button');

    await act(async () => {
      fireEvent.click(copyBtn);
      await Promise.resolve();
    });
    expect(execCommand).toHaveBeenCalledWith('copy');
    expect(screen.getByRole('button', { name: '已复制!' })).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    execCommand.mockReturnValue(false);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '复制' }));
      await Promise.resolve();
    });
    expect(screen.getByRole('button', { name: '复制失败' })).toBeInTheDocument();
  });

  it('resets copy feedback immediately when data changes and ignores stale async settlements', async () => {
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

    const { rerender } = renderJsonViewer({ signalId: 1 });
    fireEvent.click(screen.getByRole('button', { name: '复制' }));

    rerender(
      <UiLanguageProvider>
        <JsonViewer data={{ signalId: 2 }} />
      </UiLanguageProvider>,
    );
    expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument();

    await act(async () => {
      resolveClipboard();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '复制' }));
      await Promise.resolve();
    });
    expect(screen.getByRole('button', { name: '已复制!' })).toBeInTheDocument();

    rerender(
      <UiLanguageProvider>
        <JsonViewer data={{ signalId: 1 }} />
      </UiLanguageProvider>,
    );
    expect(screen.getByRole('button', { name: '复制' })).toBeInTheDocument();
  });

  it('skips execCommand fallback when a stale writeText rejects after data changes and newer copy succeeds', async () => {
    let rejectFirstCopy!: (reason?: unknown) => void;
    const writeText = vi
      .fn()
      .mockImplementationOnce(
        () => new Promise<void>((_resolve, reject) => {
          rejectFirstCopy = reject;
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

    const { rerender } = renderJsonViewer({ signalId: 1 });
    fireEvent.click(screen.getByRole('button', { name: '复制' }));

    rerender(
      <UiLanguageProvider>
        <JsonViewer data={{ signalId: 2 }} />
      </UiLanguageProvider>,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '复制' }));
      await Promise.resolve();
    });
    expect(screen.getByRole('button', { name: '已复制!' })).toBeInTheDocument();

    await act(async () => {
      rejectFirstCopy(new DOMException('Denied', 'NotAllowedError'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(execCommand).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '已复制!' })).toBeInTheDocument();
  });

  it('skips execCommand fallback when a stale writeText rejects after another JsonViewer instance copies', async () => {
    let rejectFirstCopy!: (reason?: unknown) => void;
    const writeText = vi
      .fn()
      .mockImplementationOnce(
        () => new Promise<void>((_resolve, reject) => {
          rejectFirstCopy = reject;
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

    render(
      <UiLanguageProvider>
        <JsonViewer data={{ section: 'evidence' }} />
        <JsonViewer data={{ section: 'quality' }} />
      </UiLanguageProvider>,
    );

    const copyButtons = screen.getAllByRole('button', { name: '复制' });
    expect(copyButtons).toHaveLength(2);

    fireEvent.click(copyButtons[0]);
    await act(async () => {
      fireEvent.click(copyButtons[1]);
      await Promise.resolve();
    });
    expect(screen.getAllByRole('button', { name: '已复制!' })).toHaveLength(1);

    await act(async () => {
      rejectFirstCopy(new DOMException('Denied', 'NotAllowedError'));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(execCommand).not.toHaveBeenCalled();
    expect(screen.getAllByRole('button', { name: '已复制!' })).toHaveLength(1);
  });
});
