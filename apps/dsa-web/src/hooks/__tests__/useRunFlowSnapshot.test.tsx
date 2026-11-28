import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { analysisApi } from '../../api/analysis';
import { historyApi } from '../../api/history';
import type { RunFlowEvent, RunFlowSnapshot } from '../../types/runFlow';
import type { UseTaskStreamOptions } from '../useTaskStream';
import { useRunFlowSnapshot } from '../useRunFlowSnapshot';

vi.mock('../../api/analysis', () => ({
  analysisApi: {
    getTaskFlow: vi.fn(),
  },
}));

vi.mock('../../api/history', () => ({
  historyApi: {
    getRecordFlow: vi.fn(),
  },
}));

const taskStreamCalls: UseTaskStreamOptions[] = [];

vi.mock('../useTaskStream', () => ({
  useTaskStream: (options: UseTaskStreamOptions) => {
    taskStreamCalls.push(options);
    return {
      isConnected: true,
      reconnect: vi.fn(),
      disconnect: vi.fn(),
    };
  },
}));

const snapshot: RunFlowSnapshot = {
  taskId: 'task-1',
  traceId: 'trace-1',
  stockCode: '600519',
  stockName: '贵州茅台',
  status: 'running',
  generatedAt: '2026-06-08T08:00:00Z',
  summary: {
    elapsedMs: null,
    failedAttempts: 0,
    fallbackCount: 0,
    model: null,
    dataSourceCount: 0,
    eventCount: 1,
  },
  lanes: [
    { id: 'entry', label: '入口', order: 1 },
    { id: 'data_source', label: '数据来源', order: 2 },
  ],
  nodes: [
    {
      id: 'task_queue',
      lane: 'entry',
      kind: 'queue',
      label: '任务队列',
      status: 'running',
    },
  ],
  edges: [],
  events: [
    {
      id: 'evt-1',
      timestamp: '2026-06-08T08:00:00Z',
      severity: 'info',
      type: 'task_started',
      nodeId: 'task_queue',
      title: '任务开始执行',
    },
  ],
};

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

describe('useRunFlowSnapshot', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(analysisApi.getTaskFlow).mockReset();
    vi.mocked(historyApi.getRecordFlow).mockReset();
    taskStreamCalls.length = 0;
  });

  it('merges active task flow events, strips node metadata, and refetches after stream errors', async () => {
    vi.mocked(analysisApi.getTaskFlow).mockResolvedValue(snapshot);

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    await waitFor(() => expect(result.current.snapshot).not.toBeNull());

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 30,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'flow-1',
          timestamp: '2026-06-08T08:00:01Z',
          severity: 'success',
          type: 'provider_run',
          nodeId: 'provider_daily_1',
          title: '日线K线成功',
          metadata: {
            provider: 'DailyFetcher',
            node: {
              id: 'provider_daily_1',
              lane: 'data_source',
              kind: 'data_source',
              label: '日线K线',
              status: 'success',
            },
          },
        },
      );
    });

    expect(result.current.snapshot?.events).toHaveLength(2);
    expect(result.current.snapshot?.events[1].metadata).not.toHaveProperty('node');
    expect(result.current.snapshot?.nodes.some((node) => node.id === 'provider_daily_1')).toBe(true);

    act(() => {
      taskStreamCalls.at(-1)?.onError?.(new Event('error'));
    });

    await waitFor(() => expect(analysisApi.getTaskFlow).toHaveBeenCalledTimes(2));
  });

  it('updates started live flow nodes in place when finish events arrive', async () => {
    vi.mocked(analysisApi.getTaskFlow).mockResolvedValue(snapshot);

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    await waitFor(() => expect(result.current.snapshot).not.toBeNull());

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 30,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'flow-provider-started',
          timestamp: '2026-06-08T08:00:01Z',
          severity: 'info',
          type: 'provider_run_started',
          nodeId: 'provider_daily_data_dailyfetcher_1',
          title: '日线K线开始',
          metadata: {
            provider: 'DailyFetcher',
            dataType: 'daily_data',
            node: {
              id: 'provider_daily_data_dailyfetcher_1',
              lane: 'data_source',
              kind: 'data_source',
              label: '日线K线 · DailyFetcher',
              status: 'running',
              provider: 'DailyFetcher',
              metadata: { dataType: 'daily_data' },
            },
          },
        },
      );
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 35,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'flow-provider-finished',
          timestamp: '2026-06-08T08:00:02Z',
          severity: 'success',
          type: 'provider_run',
          nodeId: 'provider_daily_data_dailyfetcher_1',
          title: '日线K线成功',
          metadata: {
            provider: 'DailyFetcher',
            dataType: 'daily_data',
            node: {
              id: 'provider_daily_data_dailyfetcher_1',
              lane: 'data_source',
              kind: 'data_source',
              label: '日线K线 · DailyFetcher',
              status: 'success',
              provider: 'DailyFetcher',
              recordCount: 30,
              metadata: { dataType: 'daily_data' },
            },
          },
        },
      );
    });

    const providerNodes = result.current.snapshot?.nodes.filter((node) => (
      node.id === 'provider_daily_data_dailyfetcher_1'
    ));
    expect(providerNodes).toHaveLength(1);
    expect(providerNodes?.[0]).toEqual(expect.objectContaining({
      status: 'success',
      recordCount: 30,
    }));
  });

  it('does not enable task stream for history snapshots', async () => {
    vi.mocked(historyApi.getRecordFlow).mockResolvedValue({ ...snapshot, status: 'success' });

    renderHook(() => useRunFlowSnapshot({
      source: { type: 'history', recordId: 7 },
      enabled: true,
    }));

    await waitFor(() => expect(historyApi.getRecordFlow).toHaveBeenCalledWith(7));
    expect(taskStreamCalls.at(-1)?.enabled).toBe(false);
  });

  it('derives provider fallback edges and summary fields from live flow events', async () => {
    vi.mocked(analysisApi.getTaskFlow).mockResolvedValue(snapshot);

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    await waitFor(() => expect(result.current.snapshot).not.toBeNull());

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 25,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'flow-daily-failed',
          timestamp: '2026-06-08T08:00:01Z',
          severity: 'danger',
          type: 'provider_run',
          nodeId: 'provider_daily_data_primary_1',
          title: '日线K线失败',
          metadata: {
            provider: 'PrimaryDaily',
            dataType: 'daily_data',
            node: {
              id: 'provider_daily_data_primary_1',
              lane: 'data_source',
              kind: 'data_source',
              label: '日线K线 · PrimaryDaily',
              status: 'failed',
              provider: 'PrimaryDaily',
              durationMs: 120,
              metadata: { dataType: 'daily_data', attempt: 1 },
            },
          },
        },
      );
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 35,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'flow-daily-fallback',
          timestamp: '2026-06-08T08:00:02Z',
          severity: 'success',
          type: 'provider_run',
          nodeId: 'provider_daily_data_backup_2',
          title: '日线K线成功',
          metadata: {
            provider: 'BackupDaily',
            dataType: 'daily_data',
            fallbackFrom: 'PrimaryDaily',
            node: {
              id: 'provider_daily_data_backup_2',
              lane: 'data_source',
              kind: 'data_source',
              label: '日线K线 · BackupDaily',
              status: 'success',
              provider: 'BackupDaily',
              durationMs: 80,
              recordCount: 30,
              metadata: { dataType: 'daily_data', attempt: 2 },
            },
          },
        },
      );
    });

    const fallbackEdge = result.current.snapshot?.edges.find((edge) => (
      edge.from === 'provider_daily_data_primary_1'
      && edge.to === 'provider_daily_data_backup_2'
      && edge.kind === 'fallback'
    ));

    expect(fallbackEdge).toBeDefined();
    expect(fallbackEdge?.label).toBe('降级');
    expect(result.current.snapshot?.summary).toEqual(expect.objectContaining({
      failedAttempts: 1,
      fallbackCount: 1,
      dataSourceCount: 2,
      eventCount: 3,
      bottleneckNodeId: 'provider_daily_data_primary_1',
    }));
  });

  it('does not derive provider fallback edges across different data types', async () => {
    vi.mocked(analysisApi.getTaskFlow).mockResolvedValue(snapshot);

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    await waitFor(() => expect(result.current.snapshot).not.toBeNull());

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 25,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'flow-daily',
          timestamp: '2026-06-08T08:00:01Z',
          severity: 'danger',
          type: 'provider_run',
          nodeId: 'provider_daily_data_primary_1',
          title: '日线K线失败',
          metadata: {
            provider: 'PrimaryDaily',
            dataType: 'daily_data',
            node: {
              id: 'provider_daily_data_primary_1',
              lane: 'data_source',
              kind: 'data_source',
              label: '日线K线 · PrimaryDaily',
              status: 'failed',
              provider: 'PrimaryDaily',
              metadata: { dataType: 'daily_data' },
            },
          },
        },
      );
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 35,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'flow-news',
          timestamp: '2026-06-08T08:00:02Z',
          severity: 'success',
          type: 'provider_run',
          nodeId: 'provider_news_search_primary_1',
          title: '新闻检索成功',
          metadata: {
            provider: 'NewsFetcher',
            dataType: 'news_search',
            node: {
              id: 'provider_news_search_primary_1',
              lane: 'data_source',
              kind: 'data_source',
              label: '新闻舆情 · NewsFetcher',
              status: 'success',
              provider: 'NewsFetcher',
              metadata: { dataType: 'news_search' },
            },
          },
        },
      );
    });

    expect(result.current.snapshot?.edges.some((edge) => edge.kind === 'fallback' || edge.kind === 'retry')).toBe(false);
    expect(result.current.snapshot?.summary.fallbackCount).toBe(0);
  });

  it('does not derive reverse provider edges when buffered events replay over a refreshed snapshot', async () => {
    const initialRequest = createDeferred<RunFlowSnapshot>();
    const refreshedRequest = createDeferred<RunFlowSnapshot>();
    vi.mocked(analysisApi.getTaskFlow)
      .mockReturnValueOnce(initialRequest.promise)
      .mockReturnValueOnce(refreshedRequest.promise);
    const primaryNode = {
      id: 'provider_daily_data_primary_1',
      lane: 'data_source',
      kind: 'data_source',
      label: '日线K线 · PrimaryDaily',
      status: 'failed',
      provider: 'PrimaryDaily',
      metadata: { dataType: 'daily_data' },
    } as const;
    const backupNode = {
      id: 'provider_daily_data_backup_2',
      lane: 'data_source',
      kind: 'data_source',
      label: '日线K线 · BackupDaily',
      status: 'success',
      provider: 'BackupDaily',
      metadata: { dataType: 'daily_data' },
    } as const;
    const primaryEvent = {
      id: 'flow-primary',
      timestamp: '2026-06-08T08:00:01Z',
      severity: 'danger',
      type: 'provider_run',
      nodeId: primaryNode.id,
      title: '日线K线失败',
      metadata: {
        provider: 'PrimaryDaily',
        dataType: 'daily_data',
        node: primaryNode,
      },
    } as const;
    const backupEvent = {
      id: 'flow-backup',
      timestamp: '2026-06-08T08:00:02Z',
      severity: 'success',
      type: 'provider_run',
      nodeId: backupNode.id,
      title: '日线K线成功',
      metadata: {
        provider: 'BackupDaily',
        dataType: 'daily_data',
        fallbackFrom: 'PrimaryDaily',
        node: backupNode,
      },
    } as const;

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    act(() => {
      initialRequest.resolve(snapshot);
    });

    await waitFor(() => expect(result.current.snapshot?.events).toHaveLength(1));

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 25,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        primaryEvent,
      );
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 35,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        backupEvent,
      );
      taskStreamCalls.at(-1)?.onTaskCompleted?.({
        taskId: 'task-1',
        stockCode: '600519',
        status: 'completed',
        progress: 100,
        reportType: 'detailed',
        createdAt: '2026-06-08T08:00:00Z',
      });
    });

    await waitFor(() => expect(analysisApi.getTaskFlow).toHaveBeenCalledTimes(2));

    act(() => {
      refreshedRequest.resolve({
        ...snapshot,
        status: 'success',
        nodes: [
          ...snapshot.nodes,
          primaryNode,
          backupNode,
        ],
        edges: [
          {
            id: 'task_queue_to_provider_daily_data_primary_1_control',
            from: 'task_queue',
            to: primaryNode.id,
            kind: 'control',
            status: 'failed',
            label: '调用',
          },
          {
            id: 'provider_daily_data_primary_1_to_provider_daily_data_backup_2_fallback',
            from: primaryNode.id,
            to: backupNode.id,
            kind: 'fallback',
            status: 'success',
            label: '降级',
          },
        ],
        events: [
          ...snapshot.events,
          {
            ...primaryEvent,
            metadata: { provider: 'PrimaryDaily', dataType: 'daily_data' },
          },
          {
            ...backupEvent,
            metadata: { provider: 'BackupDaily', dataType: 'daily_data', fallbackFrom: 'PrimaryDaily' },
          },
        ],
        summary: {
          ...snapshot.summary,
          failedAttempts: 1,
          fallbackCount: 1,
          dataSourceCount: 2,
          eventCount: 3,
        },
      });
    });

    await waitFor(() => expect(result.current.snapshot?.status).toBe('success'));

    expect(result.current.snapshot?.edges).toEqual(expect.arrayContaining([
      expect.objectContaining({
        from: primaryNode.id,
        to: backupNode.id,
        kind: 'fallback',
      }),
    ]));
    expect(result.current.snapshot?.edges).not.toEqual(expect.arrayContaining([
      expect.objectContaining({
        from: backupNode.id,
        to: primaryNode.id,
      }),
    ]));
    expect(result.current.snapshot?.summary.fallbackCount).toBe(1);
  });

  it('replays buffered flow events into refetched task snapshots', async () => {
    const initialRequest = createDeferred<RunFlowSnapshot>();
    const refreshedRequest = createDeferred<RunFlowSnapshot>();
    vi.mocked(analysisApi.getTaskFlow)
      .mockReturnValueOnce(initialRequest.promise)
      .mockReturnValueOnce(refreshedRequest.promise);

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    act(() => {
      initialRequest.resolve(snapshot);
    });

    await waitFor(() => expect(result.current.snapshot?.events).toHaveLength(1));

    act(() => {
      taskStreamCalls.at(-1)?.onTaskCompleted?.({
        taskId: 'task-1',
        stockCode: '600519',
        status: 'completed',
        progress: 100,
        reportType: 'detailed',
        createdAt: '2026-06-08T08:00:00Z',
      });
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 99,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'flow-late',
          timestamp: '2026-06-08T08:00:02Z',
          severity: 'success',
          type: 'provider_run',
          nodeId: 'provider_news_1',
          title: '新闻检索成功',
          metadata: {
            provider: 'NewsFetcher',
            node: {
              id: 'provider_news_1',
              lane: 'data_source',
              kind: 'data_source',
              label: '新闻 · NewsFetcher',
              status: 'success',
            },
          },
        },
      );
    });

    await waitFor(() => expect(analysisApi.getTaskFlow).toHaveBeenCalledTimes(2));

    act(() => {
      refreshedRequest.resolve({
        ...snapshot,
        status: 'success',
        events: snapshot.events,
        nodes: snapshot.nodes,
      });
    });

    await waitFor(() => expect(result.current.snapshot?.status).toBe('success'));
    const lateEvent = result.current.snapshot?.events.find((event) => event.id === 'flow-late');
    expect(lateEvent).toBeDefined();
    expect(lateEvent?.metadata).not.toHaveProperty('node');
    expect(result.current.snapshot?.nodes.some((node) => node.id === 'provider_news_1')).toBe(true);
  });

  it('skips replaying buffered events when refreshed snapshot already has a completed node', async () => {
    const initialRequest = createDeferred<RunFlowSnapshot>();
    const refreshedRequest = createDeferred<RunFlowSnapshot>();
    vi.mocked(analysisApi.getTaskFlow)
      .mockReturnValueOnce(initialRequest.promise)
      .mockReturnValueOnce(refreshedRequest.promise);

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    act(() => {
      initialRequest.resolve(snapshot);
    });

    await waitFor(() => expect(result.current.snapshot?.events).toHaveLength(1));

    const liveNotificationEvent = {
      id: 'flow-live-notification',
      timestamp: '2026-06-08T08:00:02Z',
      severity: 'warning' as const,
      type: 'notification_run' as const,
      nodeId: 'notification_report_1',
      title: '通知跳过',
      metadata: {
        channel: 'report',
        node: {
          id: 'notification_report_1',
          lane: 'artifact',
          kind: 'notification',
          label: '推送通知 · report',
          status: 'skipped',
        },
      },
    };

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 99,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        liveNotificationEvent,
      );
      taskStreamCalls.at(-1)?.onTaskCompleted?.({
        taskId: 'task-1',
        stockCode: '600519',
        status: 'completed',
        progress: 100,
        reportType: 'detailed',
        createdAt: '2026-06-08T08:00:00Z',
      });
    });

    await waitFor(() => expect(analysisApi.getTaskFlow).toHaveBeenCalledTimes(2));

    act(() => {
      refreshedRequest.resolve({
        ...snapshot,
        status: 'success',
        nodes: [
          ...snapshot.nodes,
          {
            id: 'notification_report_1',
            lane: 'artifact',
            kind: 'notification',
            label: '推送通知 · report',
            status: 'skipped',
          },
        ],
        events: [
          ...snapshot.events,
          {
            id: 'history-notification',
            timestamp: '2026-06-08T08:00:02Z',
            severity: 'warning',
            type: 'notification_run',
            nodeId: 'notification_report_1',
            title: '通知跳过',
          },
        ],
      });
    });

    await waitFor(() => expect(result.current.snapshot?.status).toBe('success'));

    expect(result.current.snapshot?.events.some((event) => event.id === 'history-notification')).toBe(true);
    expect(result.current.snapshot?.events.some((event) => event.id === 'flow-live-notification')).toBe(false);
    expect(result.current.snapshot?.nodes.filter((node) => node.id === 'notification_report_1')).toHaveLength(1);
  });

  it('preserves the loaded snapshot and applies live SSE updates during refetch until switching sources', async () => {
    const initialRequest = createDeferred<RunFlowSnapshot>();
    const refreshRequest = createDeferred<RunFlowSnapshot>();
    const nextSourceRequest = createDeferred<RunFlowSnapshot>();
    vi.mocked(analysisApi.getTaskFlow)
      .mockReturnValueOnce(initialRequest.promise)
      .mockReturnValueOnce(refreshRequest.promise)
      .mockReturnValueOnce(nextSourceRequest.promise);

    const { result, rerender } = renderHook(
      ({ source }) => useRunFlowSnapshot({ source, enabled: true }),
      { initialProps: { source: { type: 'task' as const, taskId: 'task-1' } } },
    );

    act(() => {
      initialRequest.resolve(snapshot);
    });

    await waitFor(() => expect(result.current.snapshot?.taskId).toBe('task-1'));
    expect(result.current.isLoading).toBe(false);

    act(() => {
      void result.current.refetch();
    });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.snapshot?.taskId).toBe('task-1');

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 60,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'flow-during-refresh',
          timestamp: '2026-06-08T08:00:05Z',
          severity: 'info',
          type: 'llm_run_started',
          nodeId: 'llm_primary_1',
          title: '模型开始生成',
          metadata: {
            node: {
              id: 'llm_primary_1',
              lane: 'analysis',
              kind: 'model',
              label: 'DeepSeek',
              status: 'running',
              provider: 'DeepSeek',
            },
          },
        },
      );
    });

    expect(result.current.snapshot?.nodes.some((node) => node.id === 'llm_primary_1')).toBe(true);

    rerender({ source: { type: 'task', taskId: 'task-2' } });

    expect(result.current.snapshot).toBeNull();
    expect(result.current.isLoading).toBe(true);
  });

  it('keeps existing snapshot on transient refetch error and clears error on subsequent retry', async () => {
    const initialRequest = createDeferred<RunFlowSnapshot>();
    const failedRefreshRequest = createDeferred<RunFlowSnapshot>();
    const retryRequest = createDeferred<RunFlowSnapshot>();
    vi.mocked(analysisApi.getTaskFlow)
      .mockReturnValueOnce(initialRequest.promise)
      .mockReturnValueOnce(failedRefreshRequest.promise)
      .mockReturnValueOnce(retryRequest.promise);

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    act(() => {
      initialRequest.resolve(snapshot);
    });

    await waitFor(() => expect(result.current.snapshot?.taskId).toBe('task-1'));

    act(() => {
      void result.current.refetch();
    });

    await act(async () => {
      failedRefreshRequest.reject({
        response: {
          status: 500,
          data: { message: '刷新服务繁忙' },
        },
      });
      await Promise.resolve();
    });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.snapshot?.taskId).toBe('task-1');
    expect(result.current.error?.message).toBe('刷新服务繁忙');

    act(() => {
      void result.current.refetch();
    });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.error).toBeNull();
    expect(result.current.snapshot?.taskId).toBe('task-1');

    act(() => {
      retryRequest.resolve({ ...snapshot, status: 'success' });
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBeNull();
    expect(result.current.snapshot?.status).toBe('success');
  });

  it('links fallback and downstream edges when consecutive events share the same timestamp', async () => {
    vi.mocked(analysisApi.getTaskFlow).mockResolvedValue(snapshot);

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    await waitFor(() => expect(result.current.snapshot).not.toBeNull());

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 25,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'same-ts-primary',
          timestamp: '2026-06-08T08:00:02Z',
          severity: 'danger',
          type: 'provider_run',
          nodeId: 'provider_daily_data_primary_1',
          title: '主源失败',
          metadata: {
            provider: 'PrimaryDaily',
            dataType: 'daily_data',
            node: {
              id: 'provider_daily_data_primary_1',
              lane: 'data_source',
              kind: 'data_source',
              label: '日线 · PrimaryDaily',
              status: 'failed',
              provider: 'PrimaryDaily',
              metadata: { dataType: 'daily_data', attempt: 1 },
            },
          },
        },
      );
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 35,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'same-ts-backup',
          timestamp: '2026-06-08T08:00:02Z',
          severity: 'success',
          type: 'provider_run',
          nodeId: 'provider_daily_data_backup_2',
          title: '备源成功',
          metadata: {
            provider: 'BackupDaily',
            dataType: 'daily_data',
            fallbackFrom: 'PrimaryDaily',
            node: {
              id: 'provider_daily_data_backup_2',
              lane: 'data_source',
              kind: 'data_source',
              label: '日线 · BackupDaily',
              status: 'success',
              provider: 'BackupDaily',
              metadata: { dataType: 'daily_data', attempt: 2 },
            },
          },
        },
      );
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 80,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'same-ts-llm',
          timestamp: '2026-06-08T08:00:03Z',
          severity: 'success',
          type: 'llm_run',
          nodeId: 'llm_deepseek_1',
          title: '模型完成',
          metadata: {
            node: {
              id: 'llm_deepseek_1',
              lane: 'analysis',
              kind: 'model',
              label: 'DeepSeek',
              status: 'success',
              provider: 'DeepSeek',
            },
          },
        },
      );
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(
        {
          taskId: 'task-1',
          stockCode: '600519',
          status: 'processing',
          progress: 90,
          reportType: 'detailed',
          createdAt: '2026-06-08T08:00:00Z',
        },
        {
          id: 'same-ts-history',
          timestamp: '2026-06-08T08:00:03Z',
          severity: 'success',
          type: 'history_run',
          nodeId: 'history_record_1',
          title: '保存历史',
          metadata: {
            node: {
              id: 'history_record_1',
              lane: 'artifact',
              kind: 'artifact',
              label: '历史报告',
              status: 'success',
            },
          },
        },
      );
    });

    expect(result.current.snapshot?.edges).toEqual(expect.arrayContaining([
      expect.objectContaining({
        from: 'provider_daily_data_primary_1',
        to: 'provider_daily_data_backup_2',
        kind: 'fallback',
      }),
      expect.objectContaining({
        from: 'llm_deepseek_1',
        to: 'history_record_1',
        kind: 'data',
      }),
    ]));
    expect(result.current.snapshot?.summary.fallbackCount).toBe(1);
  });

  it('does not create retry edges or cycles for concurrent same-provider calls within the same millisecond', async () => {
    const initialRequest = createDeferred<RunFlowSnapshot>();
    const refreshedRequest = createDeferred<RunFlowSnapshot>();
    vi.mocked(analysisApi.getTaskFlow)
      .mockReturnValueOnce(initialRequest.promise)
      .mockReturnValueOnce(refreshedRequest.promise);

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    act(() => {
      initialRequest.resolve(snapshot);
    });

    await waitFor(() => expect(result.current.snapshot).not.toBeNull());

    const quoteTask = {
      taskId: 'task-1',
      stockCode: '600519',
      status: 'processing' as const,
      progress: 30,
      reportType: 'detailed',
      createdAt: '2026-06-08T08:00:00Z',
    };

    const start1 = {
      id: 'quote-start-1',
      timestamp: '2026-06-08T08:00:00.100100Z',
      severity: 'info' as const,
      type: 'provider_run_started' as const,
      nodeId: 'provider_realtime_quote_akshare_1',
      title: '行情获取开始 1',
      metadata: {
        provider: 'AkshareFetcher',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_akshare_1',
          lane: 'data_source' as const,
          kind: 'data_source' as const,
          label: '实时行情 · AkshareFetcher #1',
          status: 'running' as const,
          provider: 'AkshareFetcher',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };
    const start2 = {
      id: 'quote-start-2',
      timestamp: '2026-06-08T08:00:00.100600Z',
      severity: 'info' as const,
      type: 'provider_run_started' as const,
      nodeId: 'provider_realtime_quote_akshare_2',
      title: '行情获取开始 2',
      metadata: {
        provider: 'AkshareFetcher',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_akshare_2',
          lane: 'data_source' as const,
          kind: 'data_source' as const,
          label: '实时行情 · AkshareFetcher #2',
          status: 'running' as const,
          provider: 'AkshareFetcher',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };
    const finish1 = {
      id: 'quote-finish-1',
      timestamp: '2026-06-08T08:00:00.200200Z',
      severity: 'success' as const,
      type: 'provider_run' as const,
      nodeId: 'provider_realtime_quote_akshare_1',
      title: '行情获取完成 1',
      metadata: {
        provider: 'AkshareFetcher',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_akshare_1',
          lane: 'data_source' as const,
          kind: 'data_source' as const,
          label: '实时行情 · AkshareFetcher #1',
          status: 'success' as const,
          provider: 'AkshareFetcher',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };
    const finish2 = {
      id: 'quote-finish-2',
      timestamp: '2026-06-08T08:00:00.200700Z',
      severity: 'success' as const,
      type: 'provider_run' as const,
      nodeId: 'provider_realtime_quote_akshare_2',
      title: '行情获取完成 2',
      metadata: {
        provider: 'AkshareFetcher',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_akshare_2',
          lane: 'data_source' as const,
          kind: 'data_source' as const,
          label: '实时行情 · AkshareFetcher #2',
          status: 'success' as const,
          provider: 'AkshareFetcher',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, start1);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, start2);
    });

    expect(result.current.snapshot?.summary.fallbackCount).toBe(0);
    expect(result.current.snapshot?.edges.some((edge) => (
      edge.from === 'provider_realtime_quote_akshare_1'
      && edge.to === 'provider_realtime_quote_akshare_2'
    ))).toBe(false);

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, finish1);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, finish2);
    });

    expect(result.current.snapshot?.summary.fallbackCount).toBe(0);
    expect(result.current.snapshot?.edges.some((edge) => edge.kind === 'retry')).toBe(false);
    expect(result.current.snapshot?.edges.some((edge) => (
      (edge.from === 'provider_realtime_quote_akshare_1' && edge.to === 'provider_realtime_quote_akshare_2')
      || (edge.from === 'provider_realtime_quote_akshare_2' && edge.to === 'provider_realtime_quote_akshare_1')
    ))).toBe(false);

    // Buffered replay onto a snapshot with only task_queue must stay cycle-free with fallbackCount === 0.
    act(() => {
      void result.current.refetch();
    });
    act(() => {
      refreshedRequest.resolve({ ...snapshot, status: 'running' });
    });

    await waitFor(() => expect(result.current.snapshot?.nodes).toHaveLength(3));
    expect(result.current.snapshot?.summary.fallbackCount).toBe(0);
    expect(result.current.snapshot?.edges.some((edge) => edge.kind === 'retry')).toBe(false);

    // Refetching the completed server snapshot containing both concurrent nodes must also stay at 0 retries.
    const completedRefresh = createDeferred<RunFlowSnapshot>();
    vi.mocked(analysisApi.getTaskFlow).mockReturnValueOnce(completedRefresh.promise);
    act(() => {
      void result.current.refetch();
    });
    act(() => {
      completedRefresh.resolve({
        ...snapshot,
        status: 'running',
        nodes: [
          ...snapshot.nodes,
          {
            id: 'provider_realtime_quote_akshare_1',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情 · AkshareFetcher #1',
            status: 'success',
            provider: 'AkshareFetcher',
            metadata: { dataType: 'realtime_quote' },
          },
          {
            id: 'provider_realtime_quote_akshare_2',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情 · AkshareFetcher #2',
            status: 'success',
            provider: 'AkshareFetcher',
            metadata: { dataType: 'realtime_quote' },
          },
        ],
        edges: [
          {
            id: 'task_queue_to_ak1',
            from: 'task_queue',
            to: 'provider_realtime_quote_akshare_1',
            kind: 'control',
            status: 'success',
            label: '调用',
          },
          {
            id: 'task_queue_to_ak2',
            from: 'task_queue',
            to: 'provider_realtime_quote_akshare_2',
            kind: 'control',
            status: 'success',
            label: '调用',
          },
        ],
      });
    });

    await waitFor(() => expect(result.current.snapshot?.nodes).toHaveLength(3));
    expect(result.current.snapshot?.summary.fallbackCount).toBe(0);
    expect(result.current.snapshot?.edges.some((edge) => edge.kind === 'retry')).toBe(false);
  });

  it('preserves real fallback link when an unrelated concurrent call succeeds before backup starts (OR-COR-a73671b9)', async () => {
    const initialDeferred = createDeferred<RunFlowSnapshot>();
    const replayDeferred = createDeferred<RunFlowSnapshot>();
    vi.mocked(analysisApi.getTaskFlow)
      .mockReturnValueOnce(initialDeferred.promise)
      .mockReturnValueOnce(replayDeferred.promise);

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    act(() => {
      initialDeferred.resolve(snapshot);
    });
    await waitFor(() => expect(result.current.snapshot).not.toBeNull());

    const quoteTask = {
      taskId: 'task-1',
      stockCode: '600519',
      status: 'processing' as const,
      progress: 40,
      reportType: 'detailed',
      createdAt: '2026-06-08T08:00:00Z',
    };

    const failPrimary: RunFlowEvent = {
      id: 'ev-fail-tencent-1',
      timestamp: '2026-06-08T08:00:00.099900Z',
      severity: 'danger',
      type: 'provider_run',
      nodeId: 'provider_realtime_quote_tencent_1',
      title: '主源失败',
      metadata: {
        provider: 'AkshareFetcher',
        dataType: 'realtime_quote',
        fallbackTo: 'akshare_sina',
        node: {
          id: 'provider_realtime_quote_tencent_1',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · AkshareFetcher (tencent)',
          status: 'failed',
          provider: 'AkshareFetcher',
          metadata: { dataType: 'realtime_quote', fallbackTo: 'akshare_sina' },
        },
      },
    };
    const concurrentSuccess: RunFlowEvent = {
      id: 'ev-ok-tencent-2',
      timestamp: '2026-06-08T08:00:00.100200Z',
      severity: 'success',
      type: 'provider_run',
      nodeId: 'provider_realtime_quote_tencent_2',
      title: '独立成功',
      metadata: {
        provider: 'AkshareFetcher',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_tencent_2',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · AkshareFetcher (concurrent)',
          status: 'success',
          provider: 'AkshareFetcher',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };
    const startBackup: RunFlowEvent = {
      id: 'ev-start-sina-3',
      timestamp: '2026-06-08T08:00:00.100600Z',
      severity: 'info',
      type: 'provider_run_started',
      nodeId: 'provider_realtime_quote_sina_3',
      title: '备源开始',
      metadata: {
        provider: 'AkshareFetcher',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_sina_3',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · AkshareFetcher (akshare_sina)',
          status: 'running',
          provider: 'AkshareFetcher',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };
    const finishBackup: RunFlowEvent = {
      id: 'ev-ok-sina-3',
      timestamp: '2026-06-08T08:00:00.101000Z',
      severity: 'success',
      type: 'provider_run',
      nodeId: 'provider_realtime_quote_sina_3',
      title: '备源成功',
      metadata: {
        provider: 'AkshareFetcher',
        dataType: 'realtime_quote',
        fallbackFrom: 'tencent',
        node: {
          id: 'provider_realtime_quote_sina_3',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · AkshareFetcher (akshare_sina)',
          status: 'fallback',
          provider: 'AkshareFetcher',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, failPrimary);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, concurrentSuccess);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, startBackup);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, finishBackup);
    });

    expect(result.current.snapshot?.summary.fallbackCount).toBe(1);
    expect(result.current.snapshot?.edges).toEqual(expect.arrayContaining([
      expect.objectContaining({
        from: 'provider_realtime_quote_tencent_1',
        to: 'provider_realtime_quote_sina_3',
        kind: 'fallback',
      }),
    ]));

    // Also verify skeleton replay preserves the fallback link rather than attaching to concurrentSuccess.
    act(() => {
      void result.current.refetch();
    });
    act(() => {
      replayDeferred.resolve({ ...snapshot, status: 'running' });
    });

    await waitFor(() => expect(result.current.snapshot?.nodes).toHaveLength(4));
    expect(result.current.snapshot?.summary.fallbackCount).toBe(1);
    expect(result.current.snapshot?.edges).toEqual(expect.arrayContaining([
      expect.objectContaining({
        from: 'provider_realtime_quote_tencent_1',
        to: 'provider_realtime_quote_sina_3',
        kind: 'fallback',
      }),
    ]));
  });

  it('does not let an independent provider start event steal an explicit fallbackTo edge from the real fallback provider (OR-COR-a73671b9)', async () => {
    const initialDeferred = createDeferred<RunFlowSnapshot>();
    const replayDeferred = createDeferred<RunFlowSnapshot>();
    vi.mocked(analysisApi.getTaskFlow)
      .mockReturnValueOnce(initialDeferred.promise)
      .mockReturnValueOnce(replayDeferred.promise);

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    act(() => {
      initialDeferred.resolve(snapshot);
    });
    await waitFor(() => expect(result.current.snapshot).not.toBeNull());

    const quoteTask = {
      taskId: 'task-1',
      stockCode: '600519',
      status: 'processing' as const,
      progress: 40,
      reportType: 'detailed',
      createdAt: '2026-06-08T08:00:00Z',
    };

    const startPrimaryA: RunFlowEvent = {
      id: 'steal-start-tencent-1',
      timestamp: '2026-06-08T08:00:00.100000Z',
      severity: 'info',
      type: 'provider_run_started',
      nodeId: 'provider_realtime_quote_tencent_1',
      title: '主源开始',
      metadata: {
        provider: 'tencent',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_tencent_1',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · tencent',
          status: 'running',
          provider: 'tencent',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };
    const failPrimaryA: RunFlowEvent = {
      id: 'steal-fail-tencent-1',
      timestamp: '2026-06-08T08:00:00.200000Z',
      severity: 'warning',
      type: 'provider_run',
      nodeId: 'provider_realtime_quote_tencent_1',
      title: '主源失败',
      metadata: {
        provider: 'tencent',
        dataType: 'realtime_quote',
        fallbackTo: 'akshare_sina',
        node: {
          id: 'provider_realtime_quote_tencent_1',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · tencent',
          status: 'failed',
          provider: 'tencent',
          metadata: { dataType: 'realtime_quote', fallbackTo: 'akshare_sina' },
        },
      },
    };
    const startIndependentB: RunFlowEvent = {
      id: 'steal-start-tencent-2',
      timestamp: '2026-06-08T08:00:00.250000Z',
      severity: 'info',
      type: 'provider_run_started',
      nodeId: 'provider_realtime_quote_tencent_2',
      title: '独立调用开始',
      metadata: {
        provider: 'tencent',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_tencent_2',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · tencent #2',
          status: 'running',
          provider: 'tencent',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };
    const finishIndependentB: RunFlowEvent = {
      id: 'steal-ok-tencent-2',
      timestamp: '2026-06-08T08:00:00.300000Z',
      severity: 'success',
      type: 'provider_run',
      nodeId: 'provider_realtime_quote_tencent_2',
      title: '独立调用成功',
      metadata: {
        provider: 'tencent',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_tencent_2',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · tencent #2',
          status: 'success',
          provider: 'tencent',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };
    const startFallbackA: RunFlowEvent = {
      id: 'steal-start-sina-3',
      timestamp: '2026-06-08T08:00:00.350000Z',
      severity: 'info',
      type: 'provider_run_started',
      nodeId: 'provider_realtime_quote_akshare_sina_3',
      title: '备源开始',
      metadata: {
        provider: 'akshare_sina',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_akshare_sina_3',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · akshare_sina',
          status: 'running',
          provider: 'akshare_sina',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };
    const finishFallbackA: RunFlowEvent = {
      id: 'steal-ok-sina-3',
      timestamp: '2026-06-08T08:00:00.400000Z',
      severity: 'success',
      type: 'provider_run',
      nodeId: 'provider_realtime_quote_akshare_sina_3',
      title: '备源成功',
      metadata: {
        provider: 'akshare_sina',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_akshare_sina_3',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · akshare_sina',
          status: 'success',
          provider: 'akshare_sina',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, startPrimaryA);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, failPrimaryA);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, startIndependentB);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, finishIndependentB);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, startFallbackA);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, finishFallbackA);
    });

    const assertExpectedFallbackTopology = () => {
      expect(result.current.snapshot?.summary.fallbackCount).toBe(1);
      expect(result.current.snapshot?.edges).toEqual(expect.arrayContaining([
        expect.objectContaining({
          from: 'task_queue',
          to: 'provider_realtime_quote_tencent_2',
          kind: 'control',
          status: 'success',
        }),
        expect.objectContaining({
          from: 'provider_realtime_quote_tencent_1',
          to: 'provider_realtime_quote_akshare_sina_3',
          kind: 'fallback',
          status: 'success',
        }),
      ]));
      expect(result.current.snapshot?.edges).not.toEqual(expect.arrayContaining([
        expect.objectContaining({
          from: 'provider_realtime_quote_tencent_1',
          to: 'provider_realtime_quote_tencent_2',
        }),
      ]));
    };

    assertExpectedFallbackTopology();

    // Buffered replay onto a skeleton snapshot must preserve the exact same edge topology.
    act(() => {
      void result.current.refetch();
    });
    act(() => {
      replayDeferred.resolve({ ...snapshot, status: 'running' });
    });

    await waitFor(() => expect(result.current.snapshot?.nodes).toHaveLength(4));
    assertExpectedFallbackTopology();
  });

  it('keeps retry count at 0 for concurrent same-provider fail-then-succeed calls across live stream and completed history refetch (OR-COR-f0c1b782)', async () => {
    const initialDeferred = createDeferred<RunFlowSnapshot>();
    const completedDeferred = createDeferred<RunFlowSnapshot>();
    vi.mocked(analysisApi.getTaskFlow)
      .mockReturnValueOnce(initialDeferred.promise)
      .mockReturnValueOnce(completedDeferred.promise);

    const { result } = renderHook(() => useRunFlowSnapshot({
      source: { type: 'task', taskId: 'task-1' },
      enabled: true,
    }));

    act(() => {
      initialDeferred.resolve(snapshot);
    });
    await waitFor(() => expect(result.current.snapshot).not.toBeNull());

    const quoteTask = {
      taskId: 'task-1',
      stockCode: '600519',
      status: 'processing' as const,
      progress: 45,
      reportType: 'detailed',
      createdAt: '2026-06-08T08:00:00Z',
    };

    const start1: RunFlowEvent = {
      id: 'conc-fail-start-1',
      timestamp: '2026-06-08T08:00:00.100000Z',
      severity: 'info',
      type: 'provider_run_started',
      nodeId: 'provider_realtime_quote_aksharefetcher_1',
      title: '实时行情开始 1',
      metadata: {
        provider: 'AkshareFetcher',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_aksharefetcher_1',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · AkshareFetcher',
          status: 'running',
          provider: 'AkshareFetcher',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };
    const start2: RunFlowEvent = {
      id: 'conc-fail-start-2',
      timestamp: '2026-06-08T08:00:00.150000Z',
      severity: 'info',
      type: 'provider_run_started',
      nodeId: 'provider_realtime_quote_aksharefetcher_2',
      title: '实时行情开始 2',
      metadata: {
        provider: 'AkshareFetcher',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_aksharefetcher_2',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · AkshareFetcher',
          status: 'running',
          provider: 'AkshareFetcher',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };
    const fail1: RunFlowEvent = {
      id: 'conc-fail-finish-1',
      timestamp: '2026-06-08T08:00:00.300000Z',
      severity: 'warning',
      type: 'provider_run',
      nodeId: 'provider_realtime_quote_aksharefetcher_1',
      title: '实时行情失败 1',
      metadata: {
        provider: 'AkshareFetcher',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_aksharefetcher_1',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · AkshareFetcher',
          status: 'failed',
          provider: 'AkshareFetcher',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };
    const succeed2: RunFlowEvent = {
      id: 'conc-fail-finish-2',
      timestamp: '2026-06-08T08:00:00.400000Z',
      severity: 'success',
      type: 'provider_run',
      nodeId: 'provider_realtime_quote_aksharefetcher_2',
      title: '实时行情成功 2',
      metadata: {
        provider: 'AkshareFetcher',
        dataType: 'realtime_quote',
        node: {
          id: 'provider_realtime_quote_aksharefetcher_2',
          lane: 'data_source',
          kind: 'data_source',
          label: '实时行情 · AkshareFetcher',
          status: 'success',
          provider: 'AkshareFetcher',
          metadata: { dataType: 'realtime_quote' },
        },
      },
    };

    act(() => {
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, start1);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, start2);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, fail1);
      taskStreamCalls.at(-1)?.onTaskFlowEvent?.(quoteTask, succeed2);
    });

    expect(result.current.snapshot?.summary.fallbackCount).toBe(0);
    expect(result.current.snapshot?.edges.some((edge) => edge.kind === 'retry' || edge.kind === 'fallback')).toBe(false);

    act(() => {
      taskStreamCalls.at(-1)?.onTaskCompleted?.({
        ...quoteTask,
        status: 'completed',
        progress: 100,
      });
    });

    await waitFor(() => expect(analysisApi.getTaskFlow).toHaveBeenCalledTimes(2));

    act(() => {
      completedDeferred.resolve({
        ...snapshot,
        status: 'degraded',
        summary: {
          ...snapshot.summary,
          failedAttempts: 1,
          fallbackCount: 0,
          dataSourceCount: 2,
          eventCount: 3,
        },
        nodes: [
          ...snapshot.nodes,
          {
            id: 'provider_realtime_quote_aksharefetcher_1',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情 · AkshareFetcher',
            status: 'failed',
            provider: 'AkshareFetcher',
            metadata: { dataType: 'realtime_quote' },
          },
          {
            id: 'provider_realtime_quote_aksharefetcher_2',
            lane: 'data_source',
            kind: 'data_source',
            label: '实时行情 · AkshareFetcher',
            status: 'success',
            provider: 'AkshareFetcher',
            metadata: { dataType: 'realtime_quote' },
          },
        ],
        edges: [
          {
            id: 'task_queue_to_provider_realtime_quote_aksharefetcher_1_control',
            from: 'task_queue',
            to: 'provider_realtime_quote_aksharefetcher_1',
            kind: 'control',
            status: 'failed',
            label: '调用',
          },
          {
            id: 'task_queue_to_provider_realtime_quote_aksharefetcher_2_control',
            from: 'task_queue',
            to: 'provider_realtime_quote_aksharefetcher_2',
            kind: 'control',
            status: 'success',
            label: '调用',
          },
        ],
      });
    });

    await waitFor(() => expect(result.current.snapshot?.status).toBe('degraded'));
    expect(result.current.snapshot?.summary.fallbackCount).toBe(0);
    expect(result.current.snapshot?.edges.some((edge) => edge.kind === 'retry' || edge.kind === 'fallback')).toBe(false);
  });
});
