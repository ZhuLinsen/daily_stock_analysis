import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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
  listeners: Record<string, ((event: MessageEvent<string>) => void) | undefined>;
  addEventListener: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  onerror: ((event: Event) => void) | null;
};

describe('useTaskStream', () => {
  let eventSourceInstance: MockEventSourceInstance;
  let eventSourceInstances: MockEventSourceInstance[];
  let constructorBehaviors: Array<() => void>;

  beforeEach(() => {
    vi.clearAllMocks();
    eventSourceInstances = [];
    constructorBehaviors = [];
    eventSourceInstance = createEventSourceInstance();

    function createEventSourceInstance(): MockEventSourceInstance {
      const instance: MockEventSourceInstance = {
        listeners: {},
        addEventListener: vi.fn((type: string, listener: (event: MessageEvent<string>) => void) => {
          instance.listeners[type] = listener;
        }),
        close: vi.fn(),
        onerror: null,
      };
      return instance;
    }

    class MockEventSource {
      addEventListener: MockEventSourceInstance['addEventListener'];
      close: MockEventSourceInstance['close'];

      constructor(...args: unknown[]) {
        void args;
        const behavior = constructorBehaviors.shift();
        behavior?.();
        const instance = createEventSourceInstance();
        eventSourceInstance = instance;
        eventSourceInstances.push(instance);
        this.addEventListener = instance.addEventListener;
        this.close = instance.close;
        Object.defineProperty(this, 'onerror', {
          configurable: true,
          get: () => instance.onerror,
          set: (handler: ((event: Event) => void) | null) => {
            instance.onerror = handler;
          },
        });
      }
    }

    Object.defineProperty(window, 'EventSource', {
      writable: true,
      configurable: true,
      value: MockEventSource,
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('closes the SSE connection when the hook unmounts', async () => {
    const { unmount } = renderHook(() => useTaskStream({ enabled: true }));

    await waitFor(() => expect(getTaskStreamUrl).toHaveBeenCalledTimes(1));

    unmount();

    expect(eventSourceInstance.close).toHaveBeenCalled();
  });

  it('parses task_progress events and forwards the updated task payload', async () => {
    const onTaskProgress = vi.fn();
    const onTaskFlowEvent = vi.fn();

    renderHook(() => useTaskStream({ enabled: true, onTaskProgress, onTaskFlowEvent }));
    await waitFor(() => expect(eventSourceInstance.listeners.task_progress).toBeDefined());

    eventSourceInstance.listeners.task_progress?.(
      new MessageEvent('task_progress', {
        data: JSON.stringify({
          task_id: 'task-1',
          trace_id: 'trace-task-1',
          stock_code: 'sh000016',
          stock_name: '上证50',
          asset_type: 'index',
          status: 'processing',
          progress: 72,
          message: 'LLM 正在生成分析结果',
          report_type: 'detailed',
          analysis_phase: 'intraday',
          created_at: '2026-03-29T08:00:00Z',
          skills: ['growth_quality'],
          region: 'jp,kr',
          flow_event: {
            id: 'flow-1',
            timestamp: '2026-03-29T08:00:01Z',
            severity: 'success',
            type: 'provider_run',
            node_id: 'provider_daily_1',
            title: '日线K线成功',
            metadata: {
              node: {
                id: 'provider_daily_1',
                lane: 'data_source',
                kind: 'data_source',
                label: '日线K线',
                status: 'success',
              },
            },
          },
        }),
      }),
    );

    expect(onTaskProgress).toHaveBeenCalledWith({
      taskId: 'task-1',
      traceId: 'trace-task-1',
      stockCode: 'sh000016',
      stockName: '上证50',
      status: 'processing',
      progress: 72,
      message: 'LLM 正在生成分析结果',
      reportType: 'detailed',
      createdAt: '2026-03-29T08:00:00Z',
      startedAt: undefined,
      completedAt: undefined,
      error: undefined,
      originalQuery: undefined,
      selectionSource: undefined,
      analysisPhase: 'intraday',
      skills: ['growth_quality'],
      region: 'jp,kr',
      assetType: 'index',
    });
    expect(onTaskFlowEvent).toHaveBeenCalledWith(
      expect.objectContaining({ taskId: 'task-1' }),
      expect.objectContaining({
        id: 'flow-1',
        nodeId: 'provider_daily_1',
        metadata: expect.objectContaining({
          node: expect.objectContaining({ lane: 'data_source' }),
        }),
      }),
    );
  });

  it('shares one SSE connection across multiple hook instances', async () => {
    const firstConnected = vi.fn();
    const secondConnected = vi.fn();
    const firstProgress = vi.fn();
    const secondProgress = vi.fn();

    const first = renderHook(() => useTaskStream({
      enabled: true,
      onConnected: firstConnected,
      onTaskProgress: firstProgress,
    }));
    const second = renderHook(() => useTaskStream({
      enabled: true,
      onConnected: secondConnected,
      onTaskProgress: secondProgress,
    }));

    await waitFor(() => expect(eventSourceInstances).toHaveLength(1));
    expect(getTaskStreamUrl).toHaveBeenCalledTimes(1);

    eventSourceInstance.listeners.connected?.(new MessageEvent('connected'));

    await waitFor(() => expect(first.result.current.isConnected).toBe(true));
    expect(second.result.current.isConnected).toBe(true);
    expect(firstConnected).toHaveBeenCalledTimes(1);
    expect(secondConnected).toHaveBeenCalledTimes(1);

    eventSourceInstance.listeners.task_progress?.(
      new MessageEvent('task_progress', {
        data: JSON.stringify({
          task_id: 'task-1',
          stock_code: '600519',
          status: 'processing',
          progress: 50,
          report_type: 'detailed',
          created_at: '2026-03-29T08:00:00Z',
        }),
      }),
    );

    expect(firstProgress).toHaveBeenCalledTimes(1);
    expect(secondProgress).toHaveBeenCalledTimes(1);

    first.unmount();
    expect(eventSourceInstance.close).not.toHaveBeenCalled();

    second.unmount();
    expect(eventSourceInstance.close).toHaveBeenCalledTimes(1);
  });

  it('reconnects the shared stream once after errors', async () => {
    vi.useFakeTimers();
    const firstError = vi.fn();
    const secondError = vi.fn();

    renderHook(() => useTaskStream({ enabled: true, onError: firstError }));
    renderHook(() => useTaskStream({ enabled: true, onError: secondError }));

    await vi.runOnlyPendingTimersAsync();
    expect(eventSourceInstances).toHaveLength(1);

    eventSourceInstance.onerror?.(new Event('error'));

    expect(firstError).toHaveBeenCalledTimes(1);
    expect(secondError).toHaveBeenCalledTimes(1);
    expect(eventSourceInstances[0].close).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(3000);

    expect(eventSourceInstances).toHaveLength(2);
    expect(getTaskStreamUrl).toHaveBeenCalledTimes(2);
  });

  it('keeps active SSE connection and connected state when reconnect options change', async () => {
    const { result, rerender } = renderHook(
      ({ reconnectDelay, autoReconnect }) => useTaskStream({ enabled: true, reconnectDelay, autoReconnect }),
      { initialProps: { reconnectDelay: 3000, autoReconnect: true } },
    );

    await waitFor(() => expect(eventSourceInstances).toHaveLength(1));

    act(() => {
      eventSourceInstance.listeners.connected?.(new MessageEvent('connected'));
    });

    await waitFor(() => expect(result.current.isConnected).toBe(true));

    rerender({ reconnectDelay: 5000, autoReconnect: false });
    await act(async () => {
      await Promise.resolve();
    });

    expect(eventSourceInstances).toHaveLength(1);
    expect(eventSourceInstances[0].close).not.toHaveBeenCalled();
    expect(result.current.isConnected).toBe(true);
  });

  it('does not let an earlier disable microtask clobber isConnected after re-enabling', async () => {
    const first = renderHook(() => useTaskStream({ enabled: true }));
    const second = renderHook(
      ({ enabled }) => useTaskStream({ enabled }),
      { initialProps: { enabled: true } },
    );

    await waitFor(() => expect(eventSourceInstances).toHaveLength(1));

    act(() => {
      eventSourceInstance.listeners.connected?.(new MessageEvent('connected'));
    });

    await waitFor(() => {
      expect(first.result.current.isConnected).toBe(true);
      expect(second.result.current.isConnected).toBe(true);
    });

    act(() => {
      second.rerender({ enabled: false });
    });
    act(() => {
      second.rerender({ enabled: true });
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(second.result.current.isConnected).toBe(true);
  });

  it('treats manual reconnect as a no-op when disabled', async () => {
    const { result } = renderHook(() => useTaskStream({ enabled: false }));

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      result.current.reconnect();
    });

    expect(eventSourceInstances).toHaveLength(0);
    expect(getTaskStreamUrl).not.toHaveBeenCalled();
    expect(result.current.isConnected).toBe(false);
  });

  it('notifies onError and schedules reconnect when EventSource constructor throws synchronously', async () => {
    vi.useFakeTimers();
    const onError = vi.fn();
    constructorBehaviors.push(() => {
      throw new Error('CSP blocked');
    });

    renderHook(() => useTaskStream({ enabled: true, reconnectDelay: 1500, onError }));

    await vi.runOnlyPendingTimersAsync();

    expect(onError).toHaveBeenCalledTimes(1);
    expect(eventSourceInstances).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(1500);

    expect(eventSourceInstances).toHaveLength(1);
    expect(getTaskStreamUrl).toHaveBeenCalledTimes(2);
  });

  it('ignores events from closed stale streams and non-task SSE payloads', async () => {
    const onConnected = vi.fn();
    const onTaskProgress = vi.fn();

    const { result } = renderHook(() => useTaskStream({
      enabled: true,
      onConnected,
      onTaskProgress,
    }));

    await waitFor(() => expect(eventSourceInstances).toHaveLength(1));
    const staleStream = eventSourceInstances[0];

    act(() => {
      result.current.reconnect();
    });

    expect(eventSourceInstances).toHaveLength(2);
    const activeStream = eventSourceInstances[1];

    act(() => {
      staleStream.listeners.connected?.(new MessageEvent('connected'));
      staleStream.listeners.task_progress?.(
        new MessageEvent('task_progress', {
          data: JSON.stringify({
            task_id: 'stale-task',
            stock_code: '600519',
            status: 'processing',
            progress: 10,
            report_type: 'detailed',
            created_at: '2026-03-29T08:00:00Z',
          }),
        }),
      );
    });

    expect(result.current.isConnected).toBe(false);
    expect(onConnected).not.toHaveBeenCalled();
    expect(onTaskProgress).not.toHaveBeenCalled();

    act(() => {
      activeStream.listeners.connected?.(new MessageEvent('connected'));
      activeStream.listeners.task_progress?.(new MessageEvent('task_progress', { data: 'null' }));
      activeStream.listeners.task_progress?.(new MessageEvent('task_progress', { data: '[]' }));
      activeStream.listeners.task_progress?.(new MessageEvent('task_progress', { data: '{}' }));
    });

    await waitFor(() => expect(result.current.isConnected).toBe(true));
    expect(onConnected).toHaveBeenCalledTimes(1);
    expect(onTaskProgress).not.toHaveBeenCalled();
  });

  it('reconnects when autoReconnect is re-enabled after a disconnected error', async () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ autoReconnect }) => useTaskStream({ enabled: true, autoReconnect }),
      { initialProps: { autoReconnect: false } },
    );

    await vi.runOnlyPendingTimersAsync();
    expect(eventSourceInstances).toHaveLength(1);

    act(() => {
      eventSourceInstance.listeners.connected?.(new MessageEvent('connected'));
    });
    expect(result.current.isConnected).toBe(true);

    act(() => {
      eventSourceInstance.onerror?.(new Event('error'));
    });
    expect(result.current.isConnected).toBe(false);

    await vi.advanceTimersByTimeAsync(5000);
    expect(eventSourceInstances).toHaveLength(1);

    rerender({ autoReconnect: true });
    await vi.runOnlyPendingTimersAsync();

    expect(eventSourceInstances).toHaveLength(2);
    expect(getTaskStreamUrl).toHaveBeenCalledTimes(2);
  });

  it('defers reentrant reconnect from onError during repeated EventSource constructor throws', async () => {
    vi.useFakeTimers();
    const secondError = vi.fn();
    let reconnectRef: (() => void) | null = null;
    constructorBehaviors.push(
      () => {
        throw new SyntaxError('invalid stream url');
      },
      () => {
        throw new SyntaxError('invalid stream url');
      },
    );

    const first = renderHook(() => {
      const stream = useTaskStream({
        enabled: true,
        reconnectDelay: 1500,
        onError: () => {
          reconnectRef?.();
        },
      });
      reconnectRef = stream.reconnect;
      return stream;
    });
    renderHook(() => useTaskStream({ enabled: true, reconnectDelay: 1500, onError: secondError }));

    await vi.runOnlyPendingTimersAsync();

    expect(first.result.current.isConnected).toBe(false);
    expect(secondError).toHaveBeenCalledTimes(1);
    expect(getTaskStreamUrl).toHaveBeenCalledTimes(1);
    expect(eventSourceInstances).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(1500);

    expect(secondError).toHaveBeenCalledTimes(2);
    expect(getTaskStreamUrl).toHaveBeenCalledTimes(2);
    expect(eventSourceInstances).toHaveLength(0);

    await vi.advanceTimersByTimeAsync(1500);

    expect(getTaskStreamUrl).toHaveBeenCalledTimes(3);
    expect(eventSourceInstances).toHaveLength(1);
  });

  it('notifies remaining subscribers and schedules reconnect even if one onError callback throws', async () => {
    vi.useFakeTimers();
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const secondError = vi.fn();

    try {
      renderHook(() => useTaskStream({
        enabled: true,
        autoReconnect: true,
        reconnectDelay: 1200,
        onError: () => {
          throw new Error('subscriber 1 handler failed');
        },
      }));
      renderHook(() => useTaskStream({
        enabled: true,
        autoReconnect: true,
        reconnectDelay: 1200,
        onError: secondError,
      }));

      await vi.runOnlyPendingTimersAsync();
      expect(eventSourceInstances).toHaveLength(1);

      act(() => {
        eventSourceInstance.onerror?.(new Event('error'));
      });

      expect(secondError).toHaveBeenCalledTimes(1);
      expect(consoleErrorSpy).toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(1200);
      expect(eventSourceInstances).toHaveLength(2);
    } finally {
      consoleErrorSpy.mockRestore();
    }
  });

  it('connects immediately when a new subscriber mounts during an active reconnect backoff', async () => {
    vi.useFakeTimers();

    const first = renderHook(() => useTaskStream({ enabled: true, autoReconnect: true, reconnectDelay: 5000 }));
    await vi.runOnlyPendingTimersAsync();
    expect(eventSourceInstances).toHaveLength(1);

    act(() => {
      eventSourceInstance.onerror?.(new Event('error'));
    });
    expect(first.result.current.isConnected).toBe(false);

    const second = renderHook(() => useTaskStream({ enabled: true, autoReconnect: false }));
    first.unmount();
    await vi.runOnlyPendingTimersAsync();

    expect(eventSourceInstances).toHaveLength(2);
    expect(getTaskStreamUrl).toHaveBeenCalledTimes(2);
    second.unmount();
  });

  it('does not let a disabled subscriber or autoReconnect change cancel a pending manual reconnect', async () => {
    vi.useFakeTimers();
    let reconnectRef: (() => void) | null = null;
    constructorBehaviors.push(
      () => {
        throw new SyntaxError('invalid stream url');
      },
      () => {
        throw new SyntaxError('invalid stream url');
      },
    );

    const primary = renderHook(
      ({ autoReconnect }: { autoReconnect: boolean }) => {
        const stream = useTaskStream({
          enabled: true,
          autoReconnect,
          reconnectDelay: 1500,
          onError: () => {
            reconnectRef?.();
          },
        });
        reconnectRef = stream.reconnect;
        return stream;
      },
      { initialProps: { autoReconnect: true } },
    );

    await vi.runOnlyPendingTimersAsync();
    expect(getTaskStreamUrl).toHaveBeenCalledTimes(1);

    // Mounting a disabled subscriber with autoReconnect=false must not cancel primary's pending retry.
    const disabled = renderHook(() => useTaskStream({ enabled: false, autoReconnect: false }));
    // Toggling autoReconnect=false on primary must not cancel an explicit manual reconnect either.
    primary.rerender({ autoReconnect: false });

    await vi.advanceTimersByTimeAsync(1500);
    expect(getTaskStreamUrl).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(1500);
    expect(getTaskStreamUrl).toHaveBeenCalledTimes(3);
    expect(eventSourceInstances).toHaveLength(1);

    disabled.unmount();
    primary.unmount();
  });

  it('preserves the original retry deadline if a drawer-triggered early reconnect fails before it fires', async () => {
    vi.useFakeTimers();
    const onTaskCompleted = vi.fn();

    const primary = renderHook(() => useTaskStream({ enabled: true, autoReconnect: true, reconnectDelay: 3000 }));
    await vi.runOnlyPendingTimersAsync();
    expect(eventSourceInstances).toHaveLength(1);

    // t=0: primary SSE disconnects and schedules retry at t=3000.
    act(() => {
      eventSourceInstance.onerror?.(new Event('error'));
    });

    // t=1000: drawer subscribes and preempts retry with an early connect attempt.
    await vi.advanceTimersByTimeAsync(1000);
    const drawer = renderHook(() =>
      useTaskStream({ enabled: true, autoReconnect: false, onTaskCompleted }),
    );
    await vi.advanceTimersByTimeAsync(0);
    expect(eventSourceInstances).toHaveLength(2);

    // t=1050: early connect fails; next retry must still fire at t=3000 (1950ms later), not t=4050.
    await vi.advanceTimersByTimeAsync(50);
    act(() => {
      eventSourceInstance.onerror?.(new Event('error'));
    });

    await vi.advanceTimersByTimeAsync(1949);
    expect(eventSourceInstances).toHaveLength(2);

    await vi.advanceTimersByTimeAsync(1);
    expect(eventSourceInstances).toHaveLength(3);

    // Task finishes at t=3500 over the recovered stream.
    await vi.advanceTimersByTimeAsync(500);
    act(() => {
      eventSourceInstance.listeners.task_completed?.(
        new MessageEvent('task_completed', {
          data: JSON.stringify({
            task_id: 'task-42',
            stock_code: '600519',
            status: 'completed',
            progress: 100,
            report_type: 'simple',
            created_at: '2026-11-25T00:00:00Z',
          }),
        }),
      );
    });
    expect(onTaskCompleted).toHaveBeenCalledTimes(1);

    // If the deadline-preserved retry at t=3000 had failed, the subsequent retry uses the full reconnectDelay (3000ms).
    act(() => {
      eventSourceInstance.onerror?.(new Event('error'));
    });
    await vi.advanceTimersByTimeAsync(2999);
    expect(eventSourceInstances).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(eventSourceInstances).toHaveLength(4);

    drawer.unmount();
    primary.unmount();
  });

  it('preserves original retry deadline when drawer early reconnect briefly emits connected before failing (OR-COR-d6ca81e9)', async () => {
    vi.useFakeTimers();

    const primary = renderHook(() => useTaskStream({ enabled: true, autoReconnect: true, reconnectDelay: 3000 }));
    await vi.runOnlyPendingTimersAsync();
    expect(eventSourceInstances).toHaveLength(1);

    // t=0: primary SSE disconnects and schedules retry at t=3000.
    act(() => {
      eventSourceInstance.onerror?.(new Event('error'));
    });

    // t=1000: drawer subscribes and triggers an early connect attempt.
    await vi.advanceTimersByTimeAsync(1000);
    const drawer = renderHook(() => useTaskStream({ enabled: true, autoReconnect: false }));
    await vi.advanceTimersByTimeAsync(0);
    expect(eventSourceInstances).toHaveLength(2);

    // t=1010: early attempt emits `connected`, then drops at t=1050 before t=3000.
    await vi.advanceTimersByTimeAsync(10);
    act(() => {
      eventSourceInstance.listeners.connected?.(new MessageEvent('connected'));
    });
    await vi.advanceTimersByTimeAsync(40);
    act(() => {
      eventSourceInstance.onerror?.(new Event('error'));
    });

    // Next reconnect must still fire at t=3000 (1950ms later), NOT t=4050.
    await vi.advanceTimersByTimeAsync(1949);
    expect(eventSourceInstances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(eventSourceInstances).toHaveLength(3);

    drawer.unmount();
    primary.unmount();
  });

  it('uses full reconnectDelay when drawer early reconnect stays connected past original deadline (OR-COR-d6ca81e9)', async () => {
    vi.useFakeTimers();

    const primary = renderHook(() => useTaskStream({ enabled: true, autoReconnect: true, reconnectDelay: 3000 }));
    await vi.runOnlyPendingTimersAsync();
    expect(eventSourceInstances).toHaveLength(1);

    // t=0: primary disconnects (original deadline t=3000).
    act(() => {
      eventSourceInstance.onerror?.(new Event('error'));
    });

    // t=1000: drawer triggers early reconnect and receives `connected` at t=1010.
    await vi.advanceTimersByTimeAsync(1000);
    const drawer = renderHook(() => useTaskStream({ enabled: true, autoReconnect: false }));
    await vi.advanceTimersByTimeAsync(0);
    expect(eventSourceInstances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(10);
    act(() => {
      eventSourceInstance.listeners.connected?.(new MessageEvent('connected'));
    });

    // Stream remains connected until t=5000 (well past original deadline t=3000), then disconnects.
    await vi.advanceTimersByTimeAsync(3990);
    act(() => {
      eventSourceInstance.onerror?.(new Event('error'));
    });

    // Since the preempted stream stayed connected past t=3000, wait the full 3000ms (until t=8000).
    await vi.advanceTimersByTimeAsync(2999);
    expect(eventSourceInstances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(eventSourceInstances).toHaveLength(3);

    drawer.unmount();
    primary.unmount();
  });

  it('keeps monotonic retry deadline when Date.now steps backwards during early reconnect failure (OR-COR-d6ca81e9)', async () => {
    vi.useFakeTimers();
    let wallClockOffset = 0;
    const realDateNow = Date.now;
    const dateNowSpy = vi.spyOn(Date, 'now').mockImplementation(() => realDateNow() + wallClockOffset);
    try {
      const primary = renderHook(() => useTaskStream({ enabled: true, autoReconnect: true, reconnectDelay: 3000 }));
      await vi.runOnlyPendingTimersAsync();
      expect(eventSourceInstances).toHaveLength(1);

      act(() => {
        eventSourceInstance.onerror?.(new Event('error'));
      });

      await vi.advanceTimersByTimeAsync(1000);
      const drawer = renderHook(() => useTaskStream({ enabled: true, autoReconnect: false }));
      await vi.advanceTimersByTimeAsync(0);
      expect(eventSourceInstances).toHaveLength(2);

      // Simulate system wall clock stepping backwards by 2 seconds while monotonic elapsed time advances.
      wallClockOffset = -2000;
      await vi.advanceTimersByTimeAsync(50);
      act(() => {
        eventSourceInstance.onerror?.(new Event('error'));
      });

      await vi.advanceTimersByTimeAsync(1949);
      expect(eventSourceInstances).toHaveLength(2);
      await vi.advanceTimersByTimeAsync(1);
      expect(eventSourceInstances).toHaveLength(3);

      drawer.unmount();
      primary.unmount();
    } finally {
      dateNowSpy.mockRestore();
    }
  });

  it('retries immediately when onerror starts before preserved deadline but subscriber onError crosses it (OR-COR-d6ca81e9)', async () => {
    vi.useFakeTimers();

    const primary = renderHook(() => useTaskStream({ enabled: true, autoReconnect: true, reconnectDelay: 3000 }));
    await vi.runOnlyPendingTimersAsync();
    expect(eventSourceInstances).toHaveLength(1);

    // t=0: primary disconnects and schedules retry at t=3000.
    const disconnectOrigin = performance.now();
    act(() => {
      eventSourceInstance.onerror?.(new Event('error'));
    });

    // t=1000: drawer mounts and triggers an early connect attempt that receives `connected`.
    await vi.advanceTimersByTimeAsync(1000);
    const drawerOnError = vi.fn(() => {
      // Simulate synchronous subscriber work pushing the clock past t=3000 (2999ms -> 3004ms).
      vi.advanceTimersByTime(5);
    });
    const drawer = renderHook(() =>
      useTaskStream({ enabled: true, autoReconnect: false, onError: drawerOnError }),
    );
    await vi.advanceTimersByTimeAsync(0);
    expect(eventSourceInstances).toHaveLength(2);

    await vi.advanceTimersByTimeAsync(10);
    act(() => {
      eventSourceInstance.listeners.connected?.(new MessageEvent('connected'));
    });

    // t=2999: early connect drops 1ms before the preserved deadline; subscriber onError advances clock to t=3004.
    await vi.advanceTimersByTimeAsync(1989);
    expect(performance.now() - disconnectOrigin).toBe(2999);
    act(() => {
      eventSourceInstance.onerror?.(new Event('error'));
    });

    expect(drawerOnError).toHaveBeenCalledTimes(1);
    expect(performance.now() - disconnectOrigin).toBe(3004);
    expect(eventSourceInstances).toHaveLength(2);

    // Preserved deadline is already due at t=3004: reconnect must fire immediately (0ms), not wait until t=6004.
    await vi.advanceTimersByTimeAsync(0);
    expect(eventSourceInstances).toHaveLength(3);
    expect(performance.now() - disconnectOrigin).toBe(3004);

    drawer.unmount();
    primary.unmount();
  });
});
