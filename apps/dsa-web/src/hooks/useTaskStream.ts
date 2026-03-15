import { useEffect, useRef, useCallback, useState } from 'react';
import { analysisApi } from '../api/analysis';
import type { TaskInfo } from '../types/analysis';

/**
 * SSE 事件类型
 */
export type SSEEventType =
  | 'connected'
  | 'task_created'
  | 'task_started'
  | 'task_completed'
  | 'task_failed'
  | 'heartbeat';

/**
 * SSE 事件数据
 */
export interface SSEEvent {
  type: SSEEventType;
  task?: TaskInfo;
  timestamp?: string;
}

/**
 * SSE Hook 配置
 */
export interface UseTaskStreamOptions {
  /** 任务创建回调 */
  onTaskCreated?: (task: TaskInfo) => void;
  /** 任务开始回调 */
  onTaskStarted?: (task: TaskInfo) => void;
  /** 任务完成回调 */
  onTaskCompleted?: (task: TaskInfo) => void;
  /** 任务失败回调 */
  onTaskFailed?: (task: TaskInfo) => void;
  /** 连接成功回调 */
  onConnected?: () => void;
  /** 连接错误回调 */
  onError?: (error: Event) => void;
  /** 是否自动重连 */
  autoReconnect?: boolean;
  /** 重连延迟(ms) */
  reconnectDelay?: number;
  /** 是否启用 */
  enabled?: boolean;
}

/**
 * SSE Hook 返回值
 */
export interface UseTaskStreamResult {
  /** 是否已连接 */
  isConnected: boolean;
  /** 手动重连 */
  reconnect: () => void;
  /** 手动断开 */
  disconnect: () => void;
}

/**
 * 任务流 SSE Hook
 * 用于接收实时任务状态更新
 *
 * @example
 * ```tsx
 * const { isConnected } = useTaskStream({
 *   onTaskCompleted: (task) => {
 *     console.log('Task completed:', task);
 *     refreshHistory();
 *   },
 *   onTaskFailed: (task) => {
 *     showError(task.error);
 *   },
 * });
 * ```
 */
export function useTaskStream(options: UseTaskStreamOptions = {}): UseTaskStreamResult {
  const {
    onTaskCreated,
    onTaskStarted,
    onTaskCompleted,
    onTaskFailed,
    onConnected,
    onError,
    autoReconnect = true,
    reconnectDelay = 3000,
    enabled = true,
  } = options;

  const eventSourceRef = useRef<EventSource | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectRef = useRef<() => void>(() => {});

  // 使用 ref 存储回调，避免 SSE 连接因回调变化而频繁重连
  const callbacksRef = useRef({
    onTaskCreated,
    onTaskStarted,
    onTaskCompleted,
    onTaskFailed,
    onConnected,
    onError,
  });

  // 每次渲染时更新回调 ref（确保事件处理使用最新回调）
  useEffect(() => {
    callbacksRef.current = {
      onTaskCreated,
      onTaskStarted,
      onTaskCompleted,
      onTaskFailed,
      onConnected,
      onError,
    };
  });

  // 将 snake_case 转换为 camelCase
  const toCamelCase = (data: Record<string, unknown>): TaskInfo => {
    return {
      taskId: data.task_id as string,
      stockCode: data.stock_code as string,
      stockName: data.stock_name as string | undefined,
      status: data.status as TaskInfo['status'],
      progress: data.progress as number,
      message: data.message as string | undefined,
      reportType: data.report_type as string,
      createdAt: data.created_at as string,
      startedAt: data.started_at as string | undefined,
      completedAt: data.completed_at as string | undefined,
      error: data.error as string | undefined,
    };
  };

  // 解析 SSE 数据
  const parseEventData = useCallback((eventData: string): TaskInfo | null => {
    try {
      const data = JSON.parse(eventData);
      return toCamelCase(data);
    } catch (e) {
      console.error('Failed to parse SSE event data:', e);
      return null;
    }
  }, []);

  // 创建 EventSource 连接
  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const url = analysisApi.getTaskStreamUrl();
    const eventSource = new EventSource(url, { withCredentials: true });
    eventSourceRef.current = eventSource;

    // 连接成功
    eventSource.addEventListener('connected', () => {
      setIsConnected(true);
      callbacksRef.current.onConnected?.();
    });

    // 任务创建
    eventSource.addEventListener('task_created', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskCreated?.(task);
    });

    // 任务开始
    eventSource.addEventListener('task_started', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskStarted?.(task);
    });

    // 任务完成
    eventSource.addEventListener('task_completed', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskCompleted?.(task);
    });

    // 任务失败
    eventSource.addEventListener('task_failed', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskFailed?.(task);
    });

    // 心跳 - 仅用于保持连接
    eventSource.addEventListener('heartbeat', () => {
      // 可选：更新最后心跳时间
    });

    // 错误处理
    eventSource.onerror = (error) => {
      setIsConnected(false);
      callbacksRef.current.onError?.(error);

      // 自动重连（通过 ref 避免闭包引用未声明的 connect）
      if (autoReconnect && enabled) {
        eventSource.close();
        reconnectTimeoutRef.current = setTimeout(() => {
          connectRef.current();
        }, reconnectDelay);
      }
    };
  }, [
    autoReconnect,
    reconnectDelay,
    enabled,
    parseEventData,
  ]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  // 断开连接（setState 延后执行，避免 effect 内同步 setState 触发级联渲染）
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    queueMicrotask(() => setIsConnected(false));
  }, []);

  // 重连
  const reconnect = useCallback(() => {
    disconnect();
    connect();
  }, [disconnect, connect]);

  // 启用/禁用时连接/断开
  useEffect(() => {
    if (enabled) {
      connect();
    } else {
      disconnect();
    }

    return () => {
      disconnect();
    };
  }, [enabled, connect, disconnect]);

  return {
    isConnected,
    reconnect,
    disconnect,
  };
}

export default useTaskStream;
