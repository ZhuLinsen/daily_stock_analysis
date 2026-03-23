import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useTaskStream } from '../useTaskStream';

const { getTaskStreamUrl } = vi.hoisted(() => ({
  getTaskStreamUrl: vi.fn(() => 'http://localhost/api/v1/analysis/tasks/stream'),
}));

vi.mock('../../api/analysis', () => ({
  analysisApi: {
    getTaskStreamUrl,
  },
}));

type MockEventSourceInstance = {
  addEventListener: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  onerror: ((event: Event) => void) | null;
};

describe('useTaskStream', () => {
  let eventSourceInstance: MockEventSourceInstance;

  beforeEach(() => {
    vi.clearAllMocks();

    eventSourceInstance = {
      addEventListener: vi.fn(),
      close: vi.fn(),
      onerror: null,
    };

    class MockEventSource {
      addEventListener = eventSourceInstance.addEventListener;
      close = eventSourceInstance.close;
      onerror = eventSourceInstance.onerror;

      constructor(...args: unknown[]) {
        void args;
      }
    }

    Object.defineProperty(window, 'EventSource', {
      writable: true,
      configurable: true,
      value: MockEventSource,
    });
  });

  it('closes the SSE connection when the hook unmounts', () => {
    const { unmount } = renderHook(() => useTaskStream({ enabled: true }));

    expect(getTaskStreamUrl).toHaveBeenCalledTimes(1);

    unmount();

    expect(eventSourceInstance.close).toHaveBeenCalled();
  });
});
