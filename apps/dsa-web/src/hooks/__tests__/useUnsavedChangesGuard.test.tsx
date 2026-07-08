import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useUnsavedChangesGuard } from '../useUnsavedChangesGuard';

describe('useUnsavedChangesGuard', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('registers and cleans up a beforeunload handler while there are unsaved changes', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    const removeSpy = vi.spyOn(window, 'removeEventListener');

    const { unmount } = renderHook(() => useUnsavedChangesGuard(true));

    expect(addSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));

    unmount();

    expect(removeSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));
  });

  it('does not register a beforeunload handler when there are no unsaved changes', () => {
    const addSpy = vi.spyOn(window, 'addEventListener');

    renderHook(() => useUnsavedChangesGuard(false));

    expect(addSpy).not.toHaveBeenCalledWith('beforeunload', expect.any(Function));
  });

  it('triggers the native prompt by preventing default and clearing returnValue', () => {
    let handler: ((event: BeforeUnloadEvent) => void) | undefined;
    vi.spyOn(window, 'addEventListener').mockImplementation((type, listener) => {
      if (type === 'beforeunload') {
        handler = listener as (event: BeforeUnloadEvent) => void;
      }
    });

    renderHook(() => useUnsavedChangesGuard(true));

    expect(handler).toBeDefined();

    const event = {
      preventDefault: vi.fn(),
      returnValue: undefined as unknown as string,
    } as unknown as BeforeUnloadEvent;
    handler?.(event);

    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(event.returnValue).toBe('');
  });

  it('removes the handler once changes are saved', () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener');

    const { rerender } = renderHook(({ dirty }) => useUnsavedChangesGuard(dirty), {
      initialProps: { dirty: true },
    });

    rerender({ dirty: false });

    expect(removeSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function));
  });
});
