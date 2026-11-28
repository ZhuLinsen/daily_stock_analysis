import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { copyTextToClipboard } from '../clipboard';

describe('copyTextToClipboard', () => {
  let originalClipboard: PropertyDescriptor | undefined;
  let originalExecCommand: PropertyDescriptor | undefined;

  beforeEach(() => {
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
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  it('uses navigator.clipboard.writeText when available', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });

    await expect(copyTextToClipboard('hello world')).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('hello world');
  });

  it('falls back to document.execCommand when navigator.clipboard is unavailable', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: undefined,
    });
    const execCommand = vi.fn(() => {
      const textarea = document.body.querySelector('textarea');
      expect(textarea?.value).toBe('http-lan-copy');
      return true;
    });
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    });

    await expect(copyTextToClipboard('http-lan-copy')).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith('copy');
    expect(document.body.querySelector('textarea')).toBeNull();
  });

  it('falls back to execCommand when clipboard.writeText rejects', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: vi.fn().mockRejectedValue(new DOMException('Denied', 'NotAllowedError')),
      },
    });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    });

    await expect(copyTextToClipboard('fallback-after-reject')).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith('copy');
  });

  it('returns false when both Clipboard API and execCommand fail', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: vi.fn().mockRejectedValue(new Error('denied')),
      },
    });
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: vi.fn().mockReturnValue(false),
    });

    await expect(copyTextToClipboard('cannot-copy')).resolves.toBe(false);
    expect(document.body.querySelector('textarea')).toBeNull();
  });

  it('skips execCommand fallback when shouldFallback returns false after async writeText rejection', async () => {
    let rejectWriteText!: (reason?: unknown) => void;
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: vi.fn(
          () => new Promise<void>((_resolve, reject) => {
            rejectWriteText = reject;
          }),
        ),
      },
    });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    });
    let current = true;

    const copyPromise = copyTextToClipboard('stale-text', {
      shouldFallback: () => current,
    });

    current = false;
    rejectWriteText(new DOMException('Denied', 'NotAllowedError'));

    await expect(copyPromise).resolves.toBe(false);
    expect(execCommand).not.toHaveBeenCalled();
    expect(document.body.querySelector('textarea')).toBeNull();
  });

  it('skips execCommand fallback when a newer copyTextToClipboard call supersedes an older rejection across callers', async () => {
    let rejectFirst!: (reason?: unknown) => void;
    const writeText = vi
      .fn()
      .mockImplementationOnce(
        () => new Promise<void>((_resolve, reject) => {
          rejectFirst = reject;
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

    const firstPromise = copyTextToClipboard('evidence-json');
    const secondPromise = copyTextToClipboard('quality-json');
    await expect(secondPromise).resolves.toBe(true);

    rejectFirst(new DOMException('Denied', 'NotAllowedError'));
    await expect(firstPromise).resolves.toBe(false);
    expect(execCommand).not.toHaveBeenCalled();
  });
});
