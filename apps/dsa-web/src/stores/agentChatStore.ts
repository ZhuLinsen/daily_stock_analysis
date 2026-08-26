import { create } from 'zustand';
import { agentApi, isAbortError } from '../api/agent';
import type { ChatSessionItem, ChatStreamRequest } from '../api/agent';
import {
  createParsedApiError,
  getParsedApiError,
  isApiRequestError,
  isParsedApiError,
  type ParsedApiError,
} from '../api/error';
import { generateUUID } from '../utils/uuid';

const STORAGE_KEY_SESSION = 'dsa_chat_session_id';

export interface ProgressStep {
  type: string;
  step?: number;
  stage?: string;
  tool?: string;
  display_name?: string;
  status?: string;
  success?: boolean;
  duration?: number;
  elapsed?: number;
  timeout?: number;
  remaining?: number;
  minimum?: number;
  reason?: string;
  message?: string;
  content?: string;
  meta?: Record<string, unknown>;
  backend?: string;
  error_code?: string;
  request_id?: string;
  session_id?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  skills?: string[];
  skill?: string;
  skillNames?: string[];
  skillName?: string;
  thinkingSteps?: ProgressStep[];
  backend?: string;
}

export interface StreamMeta {
  skillNames?: string[];
  skillName?: string;
  onAccepted?: (event: StreamAcceptedEvent) => void;
}

export interface StreamAcceptedEvent {
  type: 'accepted';
  backend: 'litellm' | 'codex_app_server';
  request_id: string;
  session_id: string;
}

type StreamTerminalStatus = 'cancelled' | 'timeout' | null;

type StreamFailureEvent = {
  type: string;
  success?: boolean;
  content?: string;
  error?: unknown;
  message?: unknown;
  backend?: string;
  error_code?: string;
};

function streamFailureFallback(event: StreamFailureEvent, defaultMessage: string): string {
  return event.backend === 'codex_app_server'
    ? 'Codex CLI 에이전트가 현재 종목 질의를 완료하지 못했습니다. 에이전트 설정에서 실행 상태를 확인하세요.'
    : defaultMessage;
}

function getFirstMeaningfulStreamError(...candidates: Array<unknown>): unknown {
  for (const candidate of candidates) {
    if (typeof candidate === 'string') {
      if (candidate.trim() !== '') {
        return candidate;
      }
      continue;
    }

    if (candidate != null) {
      return candidate;
    }
  }

  return undefined;
}

function getStreamFailureError(
  event: StreamFailureEvent,
  fallbackMessage: string,
): ParsedApiError {
  const upstreamError = getFirstMeaningfulStreamError(
    event.error,
    event.message,
    event.content,
  );
  if (upstreamError !== undefined) {
    return getParsedApiError(upstreamError);
  }

  return createParsedApiError({
    title: event.backend === 'codex_app_server'
      ? 'Codex CLI 에이전트를 사용할 수 없습니다'
      : 'AI 종목 질의를 완료하지 못했습니다',
    message: fallbackMessage,
    rawMessage: 'Agent stream ended without an error message.',
    category: 'unknown',
  });
}

interface AgentChatState {
  messages: Message[];
  selectedSkillIds: string[] | null;
  loading: boolean;
  progressSteps: ProgressStep[];
  sessionId: string;
  sessions: ChatSessionItem[];
  sessionsLoading: boolean;
  chatError: ParsedApiError | null;
  currentRoute: string;
  completionBadge: boolean;
  hasInitialLoad: boolean;
  abortController: AbortController | null;
  activeRequestId: string | null;
  serverCancellation: boolean;
  stopping: boolean;
  terminalStatus: StreamTerminalStatus;
  stopError: boolean;
}

interface AgentChatActions {
  setSelectedSkillIds: (skillIds: string[]) => void;
  setCurrentRoute: (path: string) => void;
  clearCompletionBadge: () => void;
  loadSessions: () => Promise<void>;
  loadInitialSession: () => Promise<void>;
  switchSession: (targetSessionId: string) => Promise<void>;
  startNewChat: () => void;
  stopStream: () => Promise<void>;
  startStream: (payload: ChatStreamRequest, meta?: StreamMeta) => Promise<void>;
}

const getInitialSessionId = (): string =>
  typeof localStorage !== 'undefined'
    ? localStorage.getItem(STORAGE_KEY_SESSION) || generateUUID()
    : generateUUID();

export const useAgentChatStore = create<AgentChatState & AgentChatActions>((set, get) => {
  const deliverServerCancellation = async (requestId: string): Promise<void> => {
    try {
      await agentApi.cancelChatStream(requestId);
    } catch {
      const current = get();
      if (current.activeRequestId === requestId && current.loading) {
        set({ stopping: false, stopError: true });
      }
    }
  };

  return {
  messages: [],
  selectedSkillIds: null,
  loading: false,
  progressSteps: [],
  sessionId: getInitialSessionId(),
  sessions: [],
  sessionsLoading: false,
  chatError: null,
  currentRoute: '',
  completionBadge: false,
  hasInitialLoad: false,
  abortController: null,
  activeRequestId: null,
  serverCancellation: false,
  stopping: false,
  terminalStatus: null,
  stopError: false,

  setSelectedSkillIds: (skillIds) => set({ selectedSkillIds: skillIds }),

  setCurrentRoute: (path) => set({ currentRoute: path }),

  clearCompletionBadge: () => set({ completionBadge: false }),

  loadSessions: async () => {
    set({ sessionsLoading: true });
    try {
      const sessions = await agentApi.getChatSessions();
      set({ sessions });
    } catch {
      // Ignore load errors
    } finally {
      set({ sessionsLoading: false });
    }
  },

  loadInitialSession: async () => {
    const { hasInitialLoad } = get();
    if (hasInitialLoad) return;
    set({ hasInitialLoad: true, sessionsLoading: true });

    try {
      const sessionList = await agentApi.getChatSessions();
      set({ sessions: sessionList });

      const savedId = localStorage.getItem(STORAGE_KEY_SESSION);
      if (savedId) {
        const sessionExists = sessionList.some((s) => s.session_id === savedId);
        if (sessionExists) {
          const detail = await agentApi.getChatSessionMessages(savedId);
          if (detail.messages.length > 0) {
            set({
              messages: detail.messages.map((m) => ({
                id: m.id,
                role: m.role,
                content: m.content,
              })),
              selectedSkillIds: detail.session_state.selected_skill_ids,
            });
          }
        } else {
          const newId = generateUUID();
          set({ sessionId: newId, selectedSkillIds: null });
          localStorage.setItem(STORAGE_KEY_SESSION, newId);
        }
      } else {
        localStorage.setItem(STORAGE_KEY_SESSION, get().sessionId);
      }
    } catch {
      // Ignore
    } finally {
      set({ sessionsLoading: false });
    }
  },

  switchSession: async (targetSessionId) => {
    const { sessionId, messages, abortController } = get();
    if (targetSessionId === sessionId && messages.length > 0) return;

    abortController?.abort();
    set({
      messages: [],
      selectedSkillIds: null,
      sessionId: targetSessionId,
      loading: false,
      progressSteps: [],
      chatError: null,
      abortController: null,
      activeRequestId: null,
      serverCancellation: false,
      stopping: false,
      terminalStatus: null,
      stopError: false,
    });
    localStorage.setItem(STORAGE_KEY_SESSION, targetSessionId);

    try {
      const detail = await agentApi.getChatSessionMessages(targetSessionId);
      if (get().sessionId !== targetSessionId) {
        return;
      }
      set({
        messages: detail.messages.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
        })),
        selectedSkillIds: detail.session_state.selected_skill_ids,
      });
    } catch {
      // Ignore
    }
  },

  startNewChat: () => {
    // Abort any in-flight stream so the old request does not keep running
    get().abortController?.abort();
    const newId = generateUUID();
    set({
      sessionId: newId,
      messages: [],
      selectedSkillIds: null,
      loading: false,
      progressSteps: [],
      chatError: null,
      abortController: null,
      activeRequestId: null,
      serverCancellation: false,
      stopping: false,
      terminalStatus: null,
      stopError: false,
    });
    localStorage.setItem(STORAGE_KEY_SESSION, newId);
  },

  stopStream: async () => {
    const state = get();
    if (!state.loading || state.stopping) return;
    if (!state.serverCancellation || !state.activeRequestId) {
      state.abortController?.abort();
      return;
    }

    set({ stopping: true, stopError: false });
    await deliverServerCancellation(state.activeRequestId);
  },

  startStream: async (payload, meta) => {
    if (get().loading) return;
    const { abortController: prevAc, sessionId: storeSessionId } = get();
    prevAc?.abort();

    const ac = new AbortController();
    const requestId = payload.request_id || generateUUID();
    set({
      abortController: ac,
      activeRequestId: requestId,
      serverCancellation: false,
      stopping: false,
      terminalStatus: null,
      stopError: false,
    });

    const streamSessionId = payload.session_id || storeSessionId;
    const ownsStream = () => {
      const state = get();
      return state.abortController === ac
        && state.activeRequestId === requestId
        && state.sessionId === streamSessionId;
    };
    const skillNames = meta?.skillNames?.length
      ? meta.skillNames
      : [meta?.skillName ?? '일반'];
    const skillName = skillNames.join(' · ');

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: payload.message,
      skills: payload.skills,
      skill: payload.skills?.[0],
      skillNames,
      skillName,
    };

    set({
      loading: true,
      progressSteps: [],
      chatError: null,
    });

    try {
      const response = await agentApi.chatStream(
        { ...payload, session_id: streamSessionId, request_id: requestId },
        { signal: ac.signal },
      );
      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let finalContent: string | null = null;
      let finalBackend: string | undefined;
      let receivedDoneEvent = false;
      let acceptedEvent: StreamAcceptedEvent | null = null;
      const currentProgressSteps: ProgressStep[] = [];
      const protocolError = (message: string) => createParsedApiError({
        title: '요청이 접수되지 않았습니다',
        message: '에이전트가 이 질문의 수신을 확인하지 못했습니다. 현재 내용을 유지한 뒤 다시 시도하세요.',
        rawMessage: message,
        category: 'upstream_network',
      });
      const processLine = (line: string) => {
        if (!line.startsWith('data: ') || !ownsStream() || ac.signal.aborted) return;

        const event = JSON.parse(line.slice(6)) as ProgressStep;
        if (event.type === 'accepted') {
          if (acceptedEvent) {
            throw protocolError('Agent stream emitted accepted more than once.');
          }
          if (
            (event.backend !== 'litellm' && event.backend !== 'codex_app_server')
            || event.request_id !== requestId
            || event.session_id !== streamSessionId
          ) {
            throw protocolError('Agent stream emitted an invalid accepted event.');
          }
          acceptedEvent = event as StreamAcceptedEvent;
          finalBackend = acceptedEvent.backend;
          set((s) => ({
            messages: [...s.messages, { ...userMessage, backend: acceptedEvent!.backend }],
            serverCancellation: acceptedEvent!.backend === 'codex_app_server',
            sessions: s.sessions.some((x) => x.session_id === streamSessionId)
              ? s.sessions
              : [
                  {
                    session_id: streamSessionId,
                    title: payload.message.slice(0, 60),
                    message_count: 1,
                    created_at: new Date().toISOString(),
                    last_active: new Date().toISOString(),
                  },
                  ...s.sessions,
                ],
          }));
          meta?.onAccepted?.(acceptedEvent);
          return;
        }
        if (!acceptedEvent) {
          throw protocolError(`Agent stream emitted ${event.type || 'an unknown event'} before accepted.`);
        }
        if (event.type === 'done') {
          set({ stopError: false });
          receivedDoneEvent = true;
          const doneEvent = event as unknown as StreamFailureEvent;
          if (doneEvent.error_code === 'cancelled') {
            set({ terminalStatus: 'cancelled' });
            return;
          }
          if (doneEvent.error_code === 'timeout') {
            set({ terminalStatus: 'timeout' });
            return;
          }
          if (doneEvent.success === false) {
            const failureEvent = {
              ...doneEvent,
              backend: doneEvent.backend || acceptedEvent.backend,
            };
            throw getStreamFailureError(
              failureEvent,
              streamFailureFallback(failureEvent, 'AI 모델 호출에 실패했습니다. API 키 설정을 확인하세요.'),
            );
          }
          finalContent = doneEvent.content ?? '';
          return;
        }

        if (event.type === 'error') {
          set({ stopError: false });
          const failureEvent = {
            ...(event as unknown as StreamFailureEvent),
            backend: event.backend || acceptedEvent.backend,
          };
          throw getStreamFailureError(
            failureEvent,
            streamFailureFallback(failureEvent, '분석 중 오류가 발생했습니다.'),
          );
        }

        currentProgressSteps.push(event);
        set((s) => ({ progressSteps: [...s.progressSteps, event] }));
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() ?? '';

        for (const line of lines) {
          try {
            processLine(line);
          } catch (parseErr: unknown) {
            if (isParsedApiError(parseErr) || isApiRequestError(parseErr)) {
              throw parseErr;
            }
          }
        }
      }

      if (buf.trim().startsWith('data: ')) {
        try {
          processLine(buf.trim());
        } catch (parseErr: unknown) {
          if (isParsedApiError(parseErr) || isApiRequestError(parseErr)) {
            throw parseErr;
          }
        }
      }

      if (!acceptedEvent && !ac.signal.aborted) {
        throw protocolError('Agent stream ended before accepted.');
      }

      if (!receivedDoneEvent && !ac.signal.aborted) {
        throw createParsedApiError({
          title: '응답이 완전히 수신되지 않았습니다',
          message: '에이전트의 스트리밍 응답이 완료 전에 중단되었습니다. 다시 시도하세요.',
          rawMessage: 'Agent stream ended before a done event was received.',
          category: 'upstream_network',
        });
      }

      const { currentRoute } = get();
      const shouldAppend = ownsStream() && !ac.signal.aborted && finalContent !== null;

      if (shouldAppend) {
        set((s) => ({
          messages: [
            ...s.messages,
            {
              id: (Date.now() + 1).toString(),
              role: 'assistant',
              content: finalContent || '(내용 없음)',
              skills: payload.skills,
              skill: payload.skills?.[0],
              skillNames,
              skillName,
              thinkingSteps: [...currentProgressSteps],
              backend: finalBackend,
            },
          ],
        }));
      }

      if (ownsStream() && !ac.signal.aborted && currentRoute !== '/chat') {
        set({ completionBadge: true });
      }
    } catch (error: unknown) {
      if (isAbortError(error) || !ownsStream() || ac.signal.aborted) {
        // Aborted or superseded requests must not affect the active chat.
      } else {
        set({ chatError: getParsedApiError(error) });
        const { currentRoute } = get();
        if (currentRoute !== '/chat') {
          set({ completionBadge: true });
        }
      }
    } finally {
      if (ownsStream()) {
        set({
          loading: false,
          progressSteps: [],
          abortController: null,
          activeRequestId: null,
          serverCancellation: false,
          stopping: false,
        });
        await get().loadSessions();
      }
    }
  },
  };
});
