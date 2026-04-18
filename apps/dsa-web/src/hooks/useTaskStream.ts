import { useEffect, useRef, useCallback, useState } from 'react';
import { analysisApi } from '../api/analysis';
import type { TaskInfo } from '../types/analysis';

/**
 * SSE event types.
 */
export type SSEEventType =
  | 'connected'
  | 'task_created'
  | 'task_started'
  | 'task_progress'
  | 'task_completed'
  | 'task_failed'
  | 'heartbeat';

/**
 * SSE event payload.
 */
export interface SSEEvent {
  type: SSEEventType;
  task?: TaskInfo;
  timestamp?: string;
}

/**
 * SSE hook options.
 */
export interface UseTaskStreamOptions {
  /** Task created callback */
  onTaskCreated?: (task: TaskInfo) => void;
  /** Task started callback */
  onTaskStarted?: (task: TaskInfo) => void;
  /** Task completed callback */
  onTaskCompleted?: (task: TaskInfo) => void;
  /** Task progress callback */
  onTaskProgress?: (task: TaskInfo) => void;
  /** Task failed callback */
  onTaskFailed?: (task: TaskInfo) => void;
  /** Connected callback */
  onConnected?: () => void;
  /** Connection error callback */
  onError?: (error: Event) => void;
  /** Whether to reconnect automatically */
  autoReconnect?: boolean;
  /** Reconnect delay in milliseconds */
  reconnectDelay?: number;
  /** Whether the hook is enabled */
  enabled?: boolean;
}

/**
 * SSE hook result.
 */
export interface UseTaskStreamResult {
  /** Whether the stream is connected */
  isConnected: boolean;
  /** Reconnect manually */
  reconnect: () => void;
  /** Disconnect manually */
  disconnect: () => void;
}

/**
 * Task-stream SSE hook for realtime task status updates.
 */
export function useTaskStream(options: UseTaskStreamOptions = {}): UseTaskStreamResult {
  const {
    onTaskCreated,
    onTaskStarted,
    onTaskCompleted,
    onTaskProgress,
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

  // Store callbacks in a ref to avoid reconnecting on every render.
  const callbacksRef = useRef({
    onTaskCreated,
    onTaskStarted,
    onTaskCompleted,
    onTaskProgress,
    onTaskFailed,
    onConnected,
    onError,
  });

  // Keep the latest callbacks available to the active SSE handlers.
  useEffect(() => {
    callbacksRef.current = {
      onTaskCreated,
      onTaskStarted,
      onTaskCompleted,
      onTaskProgress,
      onTaskFailed,
      onConnected,
      onError,
    };
  });

  // Convert snake_case payloads into camelCase TaskInfo objects.
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
      originalQuery: data.original_query as string | undefined,
      selectionSource: data.selection_source as string | undefined,
    };
  };

  // Parse an SSE payload.
  const parseEventData = useCallback((eventData: string): TaskInfo | null => {
    try {
      const data = JSON.parse(eventData);
      return toCamelCase(data);
    } catch (e) {
      console.error('Failed to parse SSE event data:', e);
      return null;
    }
  }, []);

  // Create an EventSource connection.
  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const url = analysisApi.getTaskStreamUrl();
    const eventSource = new EventSource(url, { withCredentials: true });
    eventSourceRef.current = eventSource;

    // Connected event
    eventSource.addEventListener('connected', () => {
      setIsConnected(true);
      callbacksRef.current.onConnected?.();
    });

    // Task created event
    eventSource.addEventListener('task_created', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskCreated?.(task);
    });

    // Task started event
    eventSource.addEventListener('task_started', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskStarted?.(task);
    });

    eventSource.addEventListener('task_progress', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskProgress?.(task);
    });

    // Task completed event
    eventSource.addEventListener('task_completed', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskCompleted?.(task);
    });

    // Task failed event
    eventSource.addEventListener('task_failed', (e) => {
      const task = parseEventData(e.data);
      if (task) callbacksRef.current.onTaskFailed?.(task);
    });

    // Heartbeat event used to keep the connection alive.
    eventSource.addEventListener('heartbeat', () => {
      // Optional place to record the latest heartbeat timestamp.
    });

    // Connection error handling
    eventSource.onerror = (error) => {
      setIsConnected(false);
      callbacksRef.current.onError?.(error);

      // Auto-reconnect via ref to avoid stale closure issues.
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

  // Disconnect and defer the state update to avoid nested renders.
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

  // Reconnect
  const reconnect = useCallback(() => {
    disconnect();
    connect();
  }, [disconnect, connect]);

  // Connect or disconnect when the hook is enabled or disabled.
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
