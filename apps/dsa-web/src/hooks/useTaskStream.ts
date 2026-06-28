import { useEffect, useRef, useCallback, useState, type MutableRefObject } from 'react';
import { analysisApi } from '../api/analysis';
import { toCamelCase } from '../api/utils';
import type { TaskInfo } from '../types/analysis';
import type { RunFlowEvent } from '../types/runFlow';

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
  flowEvent?: RunFlowEvent;
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
  /** Incremental run-flow event callback carried by task_progress */
  onTaskFlowEvent?: (task: TaskInfo, event: RunFlowEvent) => void;
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

type TaskStreamCallbacks = Pick<
  UseTaskStreamOptions,
  | 'onTaskCreated'
  | 'onTaskStarted'
  | 'onTaskCompleted'
  | 'onTaskProgress'
  | 'onTaskFailed'
  | 'onTaskFlowEvent'
  | 'onConnected'
  | 'onError'
>;

type ParsedTaskStreamPayload = {
  task: TaskInfo;
  flowEvent?: RunFlowEvent;
};

type TaskStreamSubscriber = {
  callbacksRef: MutableRefObject<TaskStreamCallbacks>;
  setIsConnected: (value: boolean) => void;
  autoReconnect: boolean;
  reconnectDelay: number;
};

let sharedEventSource: EventSource | null = null;
let sharedReconnectTimeout: ReturnType<typeof setTimeout> | null = null;
let sharedConnected = false;
let nextSubscriberId = 1;
const subscribers = new Map<number, TaskStreamSubscriber>();

// Convert snake_case payloads into camelCase TaskInfo objects.
const toTaskInfo = (data: Record<string, unknown>): TaskInfo => {
  const task: TaskInfo = {
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
    analysisPhase: data.analysis_phase as TaskInfo['analysisPhase'],
    skills: Array.isArray(data.skills) ? data.skills.map(String) : undefined,
  };

  if (typeof data.trace_id === 'string' && data.trace_id.trim()) {
    task.traceId = data.trace_id;
  }

  return task;
};

const parseEventData = (eventData: string): ParsedTaskStreamPayload | null => {
  try {
    const data = JSON.parse(eventData);
    const task = toTaskInfo(data);
    const flowEvent = data.flow_event
      ? toCamelCase<RunFlowEvent>(data.flow_event)
      : undefined;
    return { task, flowEvent };
  } catch (e) {
    console.error('Failed to parse SSE event data:', e);
    return null;
  }
};

const notifyConnectionState = (connected: boolean) => {
  sharedConnected = connected;
  subscribers.forEach((subscriber) => subscriber.setIsConnected(connected));
};

const forEachSubscriber = (notify: (callbacks: TaskStreamCallbacks) => void) => {
  subscribers.forEach((subscriber) => notify(subscriber.callbacksRef.current));
};

const clearSharedReconnect = () => {
  if (sharedReconnectTimeout) {
    clearTimeout(sharedReconnectTimeout);
    sharedReconnectTimeout = null;
  }
};

const closeSharedConnection = () => {
  clearSharedReconnect();
  if (sharedEventSource) {
    sharedEventSource.close();
    sharedEventSource = null;
  }
  notifyConnectionState(false);
};

const scheduleSharedReconnect = () => {
  if (sharedReconnectTimeout || subscribers.size === 0) {
    return;
  }
  const reconnectDelays = Array.from(subscribers.values())
    .filter((subscriber) => subscriber.autoReconnect)
    .map((subscriber) => subscriber.reconnectDelay);
  if (reconnectDelays.length === 0) {
    return;
  }
  const reconnectDelay = Math.min(...reconnectDelays);
  sharedReconnectTimeout = setTimeout(() => {
    sharedReconnectTimeout = null;
    connectSharedStream();
  }, reconnectDelay);
};

function connectSharedStream() {
  if (sharedEventSource || subscribers.size === 0) {
    return;
  }

  if (typeof window.EventSource !== 'function') {
    notifyConnectionState(false);
    return;
  }

  const url = analysisApi.getTaskStreamUrl();
  const eventSource = new window.EventSource(url, { withCredentials: true });
  sharedEventSource = eventSource;

  eventSource.addEventListener('connected', () => {
    notifyConnectionState(true);
    forEachSubscriber((callbacks) => callbacks.onConnected?.());
  });

  eventSource.addEventListener('task_created', (e) => {
    const payload = parseEventData((e as MessageEvent<string>).data);
    if (payload) {
      forEachSubscriber((callbacks) => callbacks.onTaskCreated?.(payload.task));
    }
  });

  eventSource.addEventListener('task_started', (e) => {
    const payload = parseEventData((e as MessageEvent<string>).data);
    if (payload) {
      forEachSubscriber((callbacks) => callbacks.onTaskStarted?.(payload.task));
    }
  });

  eventSource.addEventListener('task_progress', (e) => {
    const payload = parseEventData((e as MessageEvent<string>).data);
    if (payload) {
      forEachSubscriber((callbacks) => {
        callbacks.onTaskProgress?.(payload.task);
        if (payload.flowEvent) {
          callbacks.onTaskFlowEvent?.(payload.task, payload.flowEvent);
        }
      });
    }
  });

  eventSource.addEventListener('task_completed', (e) => {
    const payload = parseEventData((e as MessageEvent<string>).data);
    if (payload) {
      forEachSubscriber((callbacks) => callbacks.onTaskCompleted?.(payload.task));
    }
  });

  eventSource.addEventListener('task_failed', (e) => {
    const payload = parseEventData((e as MessageEvent<string>).data);
    if (payload) {
      forEachSubscriber((callbacks) => callbacks.onTaskFailed?.(payload.task));
    }
  });

  eventSource.addEventListener('heartbeat', () => {
    // Optional place to record the latest heartbeat timestamp.
  });

  eventSource.onerror = (error) => {
    notifyConnectionState(false);
    forEachSubscriber((callbacks) => callbacks.onError?.(error));
    if (sharedEventSource === eventSource) {
      eventSource.close();
      sharedEventSource = null;
    }
    scheduleSharedReconnect();
  };
}

const reconnectSharedStream = () => {
  closeSharedConnection();
  connectSharedStream();
};

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
    onTaskFlowEvent,
    onConnected,
    onError,
    autoReconnect = true,
    reconnectDelay = 3000,
    enabled = true,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const subscriberIdRef = useRef<number | null>(null);
  const connectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Store callbacks in a ref to avoid reconnecting on every render.
  const callbacksRef = useRef<TaskStreamCallbacks>({
    onTaskCreated,
    onTaskStarted,
    onTaskCompleted,
    onTaskProgress,
    onTaskFailed,
    onTaskFlowEvent,
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
      onTaskFlowEvent,
      onConnected,
      onError,
    };
  });

  // Disconnect and defer the state update to avoid nested renders.
  const disconnect = useCallback(() => {
    if (connectTimerRef.current) {
      window.clearTimeout(connectTimerRef.current);
      connectTimerRef.current = null;
    }
    if (subscriberIdRef.current !== null) {
      subscribers.delete(subscriberIdRef.current);
      subscriberIdRef.current = null;
    }
    if (subscribers.size === 0) {
      closeSharedConnection();
    }
    queueMicrotask(() => setIsConnected(false));
  }, []);

  // Reconnect
  const reconnect = useCallback(() => {
    if (subscriberIdRef.current === null) {
      const subscriberId = nextSubscriberId++;
      subscriberIdRef.current = subscriberId;
      subscribers.set(subscriberId, {
        callbacksRef,
        setIsConnected,
        autoReconnect,
        reconnectDelay,
      });
    }
    reconnectSharedStream();
  }, [autoReconnect, reconnectDelay]);

  // Connect or disconnect when the hook is enabled or disabled.
  useEffect(() => {
    if (enabled) {
      const subscriberId = nextSubscriberId++;
      subscriberIdRef.current = subscriberId;
      subscribers.set(subscriberId, {
        callbacksRef,
        setIsConnected,
        autoReconnect,
        reconnectDelay,
      });
      setIsConnected(sharedConnected);
      connectTimerRef.current = window.setTimeout(() => {
        connectTimerRef.current = null;
        connectSharedStream();
      }, 0);
      return () => {
        disconnect();
      };
    }

    disconnect();
    return () => {
      disconnect();
    };
  }, [autoReconnect, disconnect, enabled, reconnectDelay]);

  return {
    isConnected,
    reconnect,
    disconnect,
  };
}

export default useTaskStream;
