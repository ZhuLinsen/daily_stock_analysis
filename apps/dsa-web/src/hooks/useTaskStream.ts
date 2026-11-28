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

type TaskStreamRuntimeOptions = {
  autoReconnect: boolean;
  reconnectDelay: number;
  enabled: boolean;
};

type TaskStreamSubscriber = {
  callbacksRef: MutableRefObject<TaskStreamCallbacks>;
  optionsRef: MutableRefObject<TaskStreamRuntimeOptions>;
  setIsConnected: (value: boolean) => void;
};

let sharedEventSource: EventSource | null = null;
let sharedReconnectTimeout: ReturnType<typeof setTimeout> | null = null;
let sharedReconnectKind: 'auto' | 'manual' | null = null;
let sharedReconnectDeadlineMs: number | null = null;
let preemptedReconnectDeadlineMs: number | null = null;
let preemptedReconnectConnected = false;
let sharedConnected = false;
let sharedConnectAttemptId = 0;
let isDispatchingConnectError = false;
let nextSubscriberId = 1;
const subscribers = new Map<number, TaskStreamSubscriber>();

const getMonotonicNow = (): number => (
  typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now()
);

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
    assetType: data.asset_type as TaskInfo['assetType'] | undefined,
  };

  if (typeof data.trace_id === 'string' && data.trace_id.trim()) {
    task.traceId = data.trace_id;
  }
  if (typeof data.region === 'string' && data.region.trim()) {
    task.region = data.region;
  }

  return task;
};

const parseEventData = (eventData: string): ParsedTaskStreamPayload | null => {
  try {
    const parsed: unknown = JSON.parse(eventData);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return null;
    }
    const record = parsed as Record<string, unknown>;
    if (typeof record.task_id !== 'string' || !record.task_id.trim()) {
      return null;
    }
    const task = toTaskInfo(record);
    const rawFlowEvent = record.flow_event;
    const flowEvent =
      rawFlowEvent && typeof rawFlowEvent === 'object' && !Array.isArray(rawFlowEvent)
        ? toCamelCase<RunFlowEvent>(rawFlowEvent as Record<string, unknown>)
        : undefined;
    return { task, flowEvent };
  } catch (e) {
    console.error('Failed to parse SSE event data:', e);
    return null;
  }
};

const notifyConnectionState = (connected: boolean) => {
  sharedConnected = connected;
  for (const [id, subscriber] of Array.from(subscribers.entries())) {
    if (subscribers.get(id) !== subscriber) {
      continue;
    }
    subscriber.setIsConnected(connected);
  }
};

const forEachSubscriber = (notify: (callbacks: TaskStreamCallbacks) => void) => {
  for (const [id, subscriber] of Array.from(subscribers.entries())) {
    if (subscribers.get(id) !== subscriber) {
      continue;
    }
    try {
      notify(subscriber.callbacksRef.current);
    } catch (error) {
      console.error('[useTaskStream] Subscriber callback failed:', error);
    }
  }
};

const clearSharedReconnect = () => {
  if (sharedReconnectTimeout) {
    clearTimeout(sharedReconnectTimeout);
    sharedReconnectTimeout = null;
  }
  sharedReconnectKind = null;
  sharedReconnectDeadlineMs = null;
  preemptedReconnectDeadlineMs = null;
  preemptedReconnectConnected = false;
};

const closeSharedConnection = () => {
  clearSharedReconnect();
  if (sharedEventSource) {
    const current = sharedEventSource;
    sharedEventSource = null;
    current.onerror = null;
    current.close();
  }
  notifyConnectionState(false);
};

const getActiveReconnectDelay = (): number | null => {
  const reconnectDelays = Array.from(subscribers.values())
    .filter((subscriber) => subscriber.optionsRef.current.autoReconnect)
    .map((subscriber) => Math.max(0, subscriber.optionsRef.current.reconnectDelay));
  if (reconnectDelays.length === 0) {
    return null;
  }
  return Math.min(...reconnectDelays);
};

const getDeferredReconnectDelay = (): number => {
  const activeDelay = getActiveReconnectDelay();
  if (activeDelay !== null) {
    return activeDelay;
  }
  const fallbackDelays = Array.from(subscribers.values())
    .map((subscriber) => Math.max(0, subscriber.optionsRef.current.reconnectDelay));
  return fallbackDelays.length > 0 ? Math.min(...fallbackDelays) : 3000;
};

const scheduleDeferredReconnect = (delay: number) => {
  if (sharedEventSource || sharedReconnectTimeout || subscribers.size === 0) {
    return;
  }
  const effectiveDelay = Math.max(0, delay);
  sharedReconnectKind = 'manual';
  sharedReconnectDeadlineMs = getMonotonicNow() + effectiveDelay;
  preemptedReconnectDeadlineMs = null;
  preemptedReconnectConnected = false;
  sharedReconnectTimeout = setTimeout(() => {
    sharedReconnectTimeout = null;
    sharedReconnectKind = null;
    sharedReconnectDeadlineMs = null;
    if (subscribers.size === 0) {
      return;
    }
    connectSharedStream();
  }, effectiveDelay);
};

const scheduleSharedReconnect = (disconnectedAt?: number) => {
  if (sharedEventSource || sharedReconnectTimeout || subscribers.size === 0) {
    return;
  }
  const reconnectDelay = getActiveReconnectDelay();
  if (reconnectDelay === null) {
    preemptedReconnectDeadlineMs = null;
    preemptedReconnectConnected = false;
    return;
  }
  const now = getMonotonicNow();
  const errorAt = disconnectedAt ?? now;
  let effectiveDelay = reconnectDelay;
  if (preemptedReconnectDeadlineMs !== null) {
    const remaining = preemptedReconnectDeadlineMs - now;
    const connectedAfterPreempt = preemptedReconnectConnected;
    const disconnectedBeforeDeadline = errorAt < preemptedReconnectDeadlineMs;
    preemptedReconnectDeadlineMs = null;
    preemptedReconnectConnected = false;
    if (!connectedAfterPreempt || disconnectedBeforeDeadline) {
      effectiveDelay = remaining > 0 ? Math.min(reconnectDelay, remaining) : 0;
    }
  }
  sharedReconnectKind = 'auto';
  sharedReconnectDeadlineMs = now + effectiveDelay;
  sharedReconnectTimeout = setTimeout(() => {
    sharedReconnectTimeout = null;
    sharedReconnectKind = null;
    sharedReconnectDeadlineMs = null;
    if (subscribers.size === 0 || getActiveReconnectDelay() === null) {
      return;
    }
    connectSharedStream();
  }, effectiveDelay);
};

function connectSharedStream() {
  if (sharedEventSource || subscribers.size === 0) {
    return;
  }

  if (typeof window.EventSource !== 'function') {
    preemptedReconnectDeadlineMs = null;
    preemptedReconnectConnected = false;
    notifyConnectionState(false);
    return;
  }

  sharedConnectAttemptId += 1;
  const url = analysisApi.getTaskStreamUrl();
  let eventSource: EventSource;
  try {
    eventSource = new window.EventSource(url, { withCredentials: true });
  } catch {
    const errorAt = getMonotonicNow();
    notifyConnectionState(false);
    isDispatchingConnectError = true;
    try {
      forEachSubscriber((callbacks) => callbacks.onError?.(new Event('error')));
    } finally {
      isDispatchingConnectError = false;
    }
    scheduleSharedReconnect(errorAt);
    return;
  }
  sharedEventSource = eventSource;

  eventSource.addEventListener('connected', () => {
    if (sharedEventSource !== eventSource) {
      return;
    }
    if (preemptedReconnectDeadlineMs !== null) {
      preemptedReconnectConnected = true;
    }
    notifyConnectionState(true);
    forEachSubscriber((callbacks) => callbacks.onConnected?.());
  });

  eventSource.addEventListener('task_created', (e) => {
    if (sharedEventSource !== eventSource) {
      return;
    }
    const payload = parseEventData((e as MessageEvent<string>).data);
    if (payload) {
      forEachSubscriber((callbacks) => callbacks.onTaskCreated?.(payload.task));
    }
  });

  eventSource.addEventListener('task_started', (e) => {
    if (sharedEventSource !== eventSource) {
      return;
    }
    const payload = parseEventData((e as MessageEvent<string>).data);
    if (payload) {
      forEachSubscriber((callbacks) => callbacks.onTaskStarted?.(payload.task));
    }
  });

  eventSource.addEventListener('task_progress', (e) => {
    if (sharedEventSource !== eventSource) {
      return;
    }
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
    if (sharedEventSource !== eventSource) {
      return;
    }
    const payload = parseEventData((e as MessageEvent<string>).data);
    if (payload) {
      forEachSubscriber((callbacks) => callbacks.onTaskCompleted?.(payload.task));
    }
  });

  eventSource.addEventListener('task_failed', (e) => {
    if (sharedEventSource !== eventSource) {
      return;
    }
    const payload = parseEventData((e as MessageEvent<string>).data);
    if (payload) {
      forEachSubscriber((callbacks) => callbacks.onTaskFailed?.(payload.task));
    }
  });

  eventSource.addEventListener('heartbeat', () => {
    if (sharedEventSource !== eventSource) {
      return;
    }
    // Optional place to record the latest heartbeat timestamp.
  });

  eventSource.onerror = (error) => {
    if (sharedEventSource !== eventSource) {
      return;
    }
    const errorAt = getMonotonicNow();
    sharedEventSource = null;
    eventSource.onerror = null;
    eventSource.close();
    notifyConnectionState(false);
    try {
      forEachSubscriber((callbacks) => callbacks.onError?.(error));
    } finally {
      scheduleSharedReconnect(errorAt);
    }
  };
}

const reconnectSharedStream = () => {
  if (isDispatchingConnectError) {
    // Defer reentrant reconnect from a synchronous EventSource constructor failure
    // so the stack unwinds, sibling subscribers still receive onError, and retries stay scheduled.
    scheduleDeferredReconnect(getDeferredReconnectDelay());
    return;
  }
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
  const mountedRef = useRef(false);
  const subscriptionTokenRef = useRef(0);
  const optionsRef = useRef<TaskStreamRuntimeOptions>({
    autoReconnect,
    reconnectDelay,
    enabled,
  });

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

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      subscriptionTokenRef.current += 1;
    };
  }, []);

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

  // Keep reconnect and enabled flags fresh without tearing down the live stream.
  useEffect(() => {
    optionsRef.current = {
      autoReconnect,
      reconnectDelay,
      enabled,
    };
    if (!enabled || subscriberIdRef.current === null) {
      return;
    }
    if (
      !autoReconnect
      && sharedReconnectTimeout
      && sharedReconnectKind === 'auto'
      && getActiveReconnectDelay() === null
    ) {
      clearSharedReconnect();
      return;
    }
    if (
      autoReconnect
      && !sharedEventSource
      && !sharedReconnectTimeout
      && !connectTimerRef.current
    ) {
      connectSharedStream();
    }
  }, [autoReconnect, enabled, reconnectDelay]);

  const detachSubscriber = useCallback(() => {
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
  }, []);

  // Disconnect manually.
  const disconnect = useCallback(() => {
    subscriptionTokenRef.current += 1;
    detachSubscriber();
    if (mountedRef.current) {
      setIsConnected(false);
    }
  }, [detachSubscriber]);

  // Reconnect manually when enabled.
  const reconnect = useCallback(() => {
    if (!optionsRef.current.enabled) {
      return;
    }
    if (connectTimerRef.current) {
      window.clearTimeout(connectTimerRef.current);
      connectTimerRef.current = null;
    }
    subscriptionTokenRef.current += 1;
    if (subscriberIdRef.current === null) {
      const subscriberId = nextSubscriberId++;
      subscriberIdRef.current = subscriberId;
      subscribers.set(subscriberId, {
        callbacksRef,
        optionsRef,
        setIsConnected,
      });
    }
    reconnectSharedStream();
  }, []);

  // Connect or disconnect when the hook is enabled or disabled.
  useEffect(() => {
    if (!enabled) {
      const token = ++subscriptionTokenRef.current;
      detachSubscriber();
      queueMicrotask(() => {
        if (mountedRef.current && token === subscriptionTokenRef.current) {
          setIsConnected(false);
        }
      });
      return () => {
        subscriptionTokenRef.current += 1;
        detachSubscriber();
      };
    }

    const token = ++subscriptionTokenRef.current;
    const subscriberId = nextSubscriberId++;
    const connectAttemptAtSubscribe = sharedConnectAttemptId;
    subscriberIdRef.current = subscriberId;
    subscribers.set(subscriberId, {
      callbacksRef,
      optionsRef,
      setIsConnected,
    });
    queueMicrotask(() => {
      if (mountedRef.current && token === subscriptionTokenRef.current) {
        setIsConnected(sharedConnected);
      }
    });
    connectTimerRef.current = window.setTimeout(() => {
      connectTimerRef.current = null;
      if (subscriberIdRef.current !== subscriberId) {
        return;
      }
      if (sharedReconnectTimeout) {
        if (sharedConnectAttemptId !== connectAttemptAtSubscribe) {
          return;
        }
        const previousDeadline = sharedReconnectDeadlineMs;
        clearSharedReconnect();
        if (previousDeadline !== null) {
          preemptedReconnectDeadlineMs = previousDeadline;
          preemptedReconnectConnected = false;
        }
      }
      connectSharedStream();
    }, 0);

    return () => {
      subscriptionTokenRef.current += 1;
      detachSubscriber();
    };
  }, [detachSubscriber, enabled]);

  return {
    isConnected,
    reconnect,
    disconnect,
  };
}

export default useTaskStream;
