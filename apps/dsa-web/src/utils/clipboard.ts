/**
 * Copy plain text to the system clipboard with a legacy DOM fallback.
 *
 * `navigator.clipboard` is undefined on plain HTTP origins (for example LAN
 * self-hosted deployments such as `http://192.168.x.x:8000`) and may reject
 * under restrictive permissions. Falling back to an offscreen readonly
 * `<textarea>` + `document.execCommand('copy')` keeps copy actions working
 * consistently across HTTPS, LAN HTTP, and embedded WebViews.
 */
export interface CopyTextToClipboardOptions {
  /**
   * Optional guard checked right before falling back to DOM-based
   * `document.execCommand('copy')`. Returning `false` aborts the fallback so a
   * superseded or unmounted async `navigator.clipboard.writeText` rejection
   * cannot steal focus or clobber a newer clipboard write.
   */
  shouldFallback?: () => boolean;
}

let latestClipboardAttemptId = 0;

export async function copyTextToClipboard(
  text: string,
  options?: CopyTextToClipboardOptions,
): Promise<boolean> {
  const attemptId = ++latestClipboardAttemptId;

  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to legacy execCommand copy unless a newer attempt or caller invalidated it.
    }
  }

  if (
    attemptId !== latestClipboardAttemptId ||
    (options?.shouldFallback && !options.shouldFallback())
  ) {
    return false;
  }

  if (typeof document === 'undefined' || !document.body) {
    return false;
  }

  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.top = '0';
  textarea.style.left = '-9999px';
  textarea.style.opacity = '0';

  const selection = document.getSelection?.();
  const savedRanges =
    selection && selection.rangeCount > 0
      ? Array.from({ length: selection.rangeCount }, (_, index) =>
          selection.getRangeAt(index).cloneRange(),
        )
      : [];
  const previousActiveElement =
    document.activeElement instanceof HTMLElement ? document.activeElement : null;

  document.body.appendChild(textarea);

  try {
    textarea.focus({ preventScroll: true });
    textarea.select();
    textarea.setSelectionRange(0, text.length);
    if (typeof document.execCommand !== 'function') {
      return false;
    }
    return Boolean(document.execCommand('copy'));
  } catch {
    return false;
  } finally {
    document.body.removeChild(textarea);
    if (selection) {
      selection.removeAllRanges();
      savedRanges.forEach((range) => selection.addRange(range));
    }
    previousActiveElement?.focus({ preventScroll: true });
  }
}
