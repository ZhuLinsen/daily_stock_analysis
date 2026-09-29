import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { analysisApi } from '../../api/analysis';
import { historyApi } from '../../api/history';
import type { RunFlowSnapshot } from '../../types/runFlow';
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
});
