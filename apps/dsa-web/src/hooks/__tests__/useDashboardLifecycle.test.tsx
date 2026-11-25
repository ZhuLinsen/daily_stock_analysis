import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useDashboardLifecycle } from '../useDashboardLifecycle';
import { useTaskStream } from '../useTaskStream';

vi.mock('../useTaskStream', () => ({
  useTaskStream: vi.fn(),
}));

const createTask = () => ({
  taskId: 'task-1',
  stockCode: '600519',
  stockName: '贵州茅台',
  status: 'completed' as const,
  progress: 100,
  reportType: 'detailed',
  createdAt: '2026-03-18T08:00:00Z',
});

const defaultMocks = {
  loadStockBar: vi.fn().mockResolvedValue(undefined),
  refreshStockBar: vi.fn().mockResolvedValue(undefined),
  loadMarketReviewHistory: vi.fn().mockResolvedValue(undefined),
  refreshMarketReviewHistory: vi.fn().mockResolvedValue(undefined),
};

describe('useDashboardLifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('loads history, refreshes on interval, and reacts to visibility changes', () => {
    const loadInitialHistory = vi.fn().mockResolvedValue(undefined);
    const refreshHistory = vi.fn().mockResolvedValue(undefined);
    const refreshActiveTasks = vi.fn().mockResolvedValue(undefined);
    const onDashboardDataRefresh = vi.fn();

    renderHook(() =>
      useDashboardLifecycle({
        loadInitialHistory,
        refreshHistory,
        refreshActiveTasks,
        syncTaskCreated: vi.fn(),
        syncTaskUpdated: vi.fn(),
        syncTaskFailed: vi.fn(),
        removeTask: vi.fn(),
        onDashboardDataRefresh,
        ...defaultMocks,
      }),
    );

    expect(loadInitialHistory).toHaveBeenCalledTimes(1);
    expect(defaultMocks.loadMarketReviewHistory).toHaveBeenCalledTimes(1);
    expect(refreshActiveTasks).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(refreshHistory).toHaveBeenCalledWith(true);
    expect(defaultMocks.refreshMarketReviewHistory).toHaveBeenCalledWith(true);
    expect(refreshActiveTasks).toHaveBeenCalledTimes(2);
    expect(onDashboardDataRefresh).toHaveBeenCalledTimes(1);

    act(() => {
      Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        value: 'visible',
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    expect(refreshHistory).toHaveBeenCalledTimes(2);
    expect(defaultMocks.refreshMarketReviewHistory).toHaveBeenCalledTimes(2);
    expect(refreshActiveTasks).toHaveBeenCalledTimes(3);
    expect(onDashboardDataRefresh).toHaveBeenCalledTimes(2);
  });

  it('cleans pending task removal timers on unmount', () => {
    const removeTask = vi.fn();

    const { unmount } = renderHook(() =>
      useDashboardLifecycle({
        loadInitialHistory: vi.fn().mockResolvedValue(undefined),
        refreshHistory: vi.fn().mockResolvedValue(undefined),
        refreshActiveTasks: vi.fn().mockResolvedValue(undefined),
        syncTaskCreated: vi.fn(),
        syncTaskUpdated: vi.fn(),
        syncTaskFailed: vi.fn(),
        removeTask,
        ...defaultMocks,
      }),
    );

    const taskStreamOptions = vi.mocked(useTaskStream).mock.calls[0]?.[0];
    expect(taskStreamOptions).toBeDefined();

    act(() => {
      taskStreamOptions?.onTaskCompleted?.(createTask());
    });

    unmount();

    act(() => {
      vi.advanceTimersByTime(2_000);
    });

    expect(removeTask).not.toHaveBeenCalled();
  });

  it('refreshes completed task history and removes completed tasks after the grace window', async () => {
    const refreshHistory = vi.fn().mockResolvedValue(undefined);
    const refreshHistoryForCompletedTask = vi.fn().mockResolvedValue(undefined);
    const syncTaskUpdated = vi.fn();
    const removeTask = vi.fn();
    const onCompletedTaskDataRefreshStarted = vi.fn();
    const onCompletedTaskDataRefreshed = vi.fn();

    renderHook(() =>
      useDashboardLifecycle({
        loadInitialHistory: vi.fn().mockResolvedValue(undefined),
        refreshHistory,
        refreshHistoryForCompletedTask,
        refreshActiveTasks: vi.fn().mockResolvedValue(undefined),
        syncTaskCreated: vi.fn(),
        syncTaskUpdated,
        syncTaskFailed: vi.fn(),
        removeTask,
        onCompletedTaskDataRefreshStarted,
        onCompletedTaskDataRefreshed,
        ...defaultMocks,
      }),
    );

    const taskStreamOptions = vi.mocked(useTaskStream).mock.calls[0]?.[0];
    const completedTask = createTask();

    await act(async () => {
      taskStreamOptions?.onTaskCompleted?.(completedTask);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(syncTaskUpdated).toHaveBeenCalledWith(completedTask);
    expect(onCompletedTaskDataRefreshStarted).toHaveBeenCalledWith(completedTask);
    expect(refreshHistoryForCompletedTask).toHaveBeenCalledWith(completedTask);
    expect(refreshHistory).not.toHaveBeenCalledWith(true);
    expect(defaultMocks.refreshMarketReviewHistory).toHaveBeenCalledWith(true);

    expect(onCompletedTaskDataRefreshed).toHaveBeenCalledWith(completedTask);

    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    expect(removeTask).toHaveBeenCalledWith(completedTask.taskId);
  });

  it('forwards task progress updates to the task sync handler', () => {
    const syncTaskUpdated = vi.fn();

    renderHook(() =>
      useDashboardLifecycle({
        loadInitialHistory: vi.fn().mockResolvedValue(undefined),
        refreshHistory: vi.fn().mockResolvedValue(undefined),
        refreshActiveTasks: vi.fn().mockResolvedValue(undefined),
        syncTaskCreated: vi.fn(),
        syncTaskUpdated,
        syncTaskFailed: vi.fn(),
        removeTask: vi.fn(),
        ...defaultMocks,
      }),
    );

    const taskStreamOptions = vi.mocked(useTaskStream).mock.calls[0]?.[0];
    const progressTask = {
      ...createTask(),
      status: 'processing' as const,
      progress: 72,
      message: 'LLM 正在生成分析结果',
    };

    act(() => {
      taskStreamOptions?.onTaskProgress?.(progressTask);
    });

    expect(syncTaskUpdated).toHaveBeenCalledWith(progressTask);
  });

  it('reports failed tasks and removes them after the failure grace window', () => {
    const syncTaskFailed = vi.fn();
    const removeTask = vi.fn();

    renderHook(() =>
      useDashboardLifecycle({
        loadInitialHistory: vi.fn().mockResolvedValue(undefined),
        refreshHistory: vi.fn().mockResolvedValue(undefined),
        refreshActiveTasks: vi.fn().mockResolvedValue(undefined),
        syncTaskCreated: vi.fn(),
        syncTaskUpdated: vi.fn(),
        syncTaskFailed,
        removeTask,
        ...defaultMocks,
      }),
    );

    const taskStreamOptions = vi.mocked(useTaskStream).mock.calls[0]?.[0];
    const failedTask = {
      ...createTask(),
      status: 'failed' as const,
      error: '分析失败',
    };

    act(() => {
      taskStreamOptions?.onTaskFailed?.(failedTask);
    });

    expect(syncTaskFailed).toHaveBeenCalledWith(failedTask);

    act(() => {
      vi.advanceTimersByTime(5_000);
    });

    expect(removeTask).toHaveBeenCalledWith(failedTask.taskId);
  });

  it('reconciles active tasks when the SSE stream connects', () => {
    const refreshActiveTasks = vi.fn().mockResolvedValue(undefined);

    renderHook(() =>
      useDashboardLifecycle({
        loadInitialHistory: vi.fn().mockResolvedValue(undefined),
        refreshHistory: vi.fn().mockResolvedValue(undefined),
        refreshActiveTasks,
        syncTaskCreated: vi.fn(),
        syncTaskUpdated: vi.fn(),
        syncTaskFailed: vi.fn(),
        removeTask: vi.fn(),
        ...defaultMocks,
      }),
    );

    const taskStreamOptions = vi.mocked(useTaskStream).mock.calls[0]?.[0];

    act(() => {
      taskStreamOptions?.onConnected?.();
    });

    expect(refreshActiveTasks).toHaveBeenCalledTimes(2);
  });

  it('skips onCompletedTaskDataRefreshed after disable or unmount while refreshes settle', async () => {
    let resolveHistory!: () => void;
    let resolveStockBar!: () => void;
    const refreshHistory = vi.fn().mockImplementation(
      () => new Promise<void>((resolve) => {
        resolveHistory = resolve;
      }),
    );
    const refreshStockBar = vi.fn().mockImplementation(
      () => new Promise<void>((resolve) => {
        resolveStockBar = resolve;
      }),
    );
    const onCompletedTaskDataRefreshed = vi.fn();

    const firstHook = renderHook(
      ({ enabled }: { enabled: boolean }) =>
        useDashboardLifecycle({
          loadInitialHistory: vi.fn().mockResolvedValue(undefined),
          refreshHistory,
          refreshActiveTasks: vi.fn().mockResolvedValue(undefined),
          loadStockBar: vi.fn().mockResolvedValue(undefined),
          refreshStockBar,
          loadMarketReviewHistory: vi.fn().mockResolvedValue(undefined),
          refreshMarketReviewHistory: vi.fn().mockResolvedValue(undefined),
          syncTaskCreated: vi.fn(),
          syncTaskUpdated: vi.fn(),
          syncTaskFailed: vi.fn(),
          removeTask: vi.fn(),
          onCompletedTaskDataRefreshed,
          enabled,
        }),
      { initialProps: { enabled: true } },
    );

    const firstOptions = vi.mocked(useTaskStream).mock.calls.at(-1)?.[0];
    act(() => {
      firstOptions?.onTaskCompleted?.(createTask());
    });

    firstHook.rerender({ enabled: false });

    await act(async () => {
      resolveHistory();
      resolveStockBar();
      await Promise.resolve();
    });

    expect(onCompletedTaskDataRefreshed).not.toHaveBeenCalled();

    let resolveHistoryUnmount!: () => void;
    let resolveStockBarUnmount!: () => void;
    const refreshHistory2 = vi.fn().mockImplementation(
      () => new Promise<void>((resolve) => {
        resolveHistoryUnmount = resolve;
      }),
    );
    const refreshStockBar2 = vi.fn().mockImplementation(
      () => new Promise<void>((resolve) => {
        resolveStockBarUnmount = resolve;
      }),
    );

    const secondHook = renderHook(() =>
      useDashboardLifecycle({
        loadInitialHistory: vi.fn().mockResolvedValue(undefined),
        refreshHistory: refreshHistory2,
        refreshActiveTasks: vi.fn().mockResolvedValue(undefined),
        loadStockBar: vi.fn().mockResolvedValue(undefined),
        refreshStockBar: refreshStockBar2,
        loadMarketReviewHistory: vi.fn().mockResolvedValue(undefined),
        refreshMarketReviewHistory: vi.fn().mockResolvedValue(undefined),
        syncTaskCreated: vi.fn(),
        syncTaskUpdated: vi.fn(),
        syncTaskFailed: vi.fn(),
        removeTask: vi.fn(),
        onCompletedTaskDataRefreshed,
      }),
    );

    const secondOptions = vi.mocked(useTaskStream).mock.calls.at(-1)?.[0];
    act(() => {
      secondOptions?.onTaskCompleted?.(createTask());
    });

    secondHook.unmount();

    await act(async () => {
      resolveHistoryUnmount();
      resolveStockBarUnmount();
      await Promise.resolve();
    });

    expect(onCompletedTaskDataRefreshed).not.toHaveBeenCalled();
  });

  it('cancels pending task removal timeouts when enabled switches to false', () => {
    const removeTask = vi.fn();

    const { rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) =>
        useDashboardLifecycle({
          loadInitialHistory: vi.fn().mockResolvedValue(undefined),
          refreshHistory: vi.fn().mockResolvedValue(undefined),
          refreshActiveTasks: vi.fn().mockResolvedValue(undefined),
          syncTaskCreated: vi.fn(),
          syncTaskUpdated: vi.fn(),
          syncTaskFailed: vi.fn(),
          removeTask,
          ...defaultMocks,
          enabled,
        }),
      { initialProps: { enabled: true } },
    );

    const taskStreamOptions = vi.mocked(useTaskStream).mock.calls.at(-1)?.[0];
    act(() => {
      taskStreamOptions?.onTaskCompleted?.(createTask());
    });

    rerender({ enabled: false });

    act(() => {
      vi.advanceTimersByTime(5_000);
    });

    expect(removeTask).not.toHaveBeenCalled();
  });
});
