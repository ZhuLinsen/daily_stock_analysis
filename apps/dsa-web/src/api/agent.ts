import apiClient from './index';
import { API_BASE_URL } from '../utils/constants';
import { createApiError, createParsedApiError, isApiRequestError, parseApiError } from './error';
import { toCamelCase } from './utils';
import type { AgentBackendStatusResponse } from '../types/systemConfig';

export interface ChatStreamOptions {
  signal?: AbortSignal;
}

export function isAbortError(error: unknown): boolean {
  return typeof error === 'object'
    && error !== null
    && 'name' in error
    && error.name === 'AbortError';
}

export interface ChatRequest {
  message: string;
  skills?: string[];
}

export interface ChatStreamRequest extends ChatRequest {
  session_id?: string;
  session_generation?: string;
  request_id?: string;
  context?: unknown;
}

export interface CancelChatStreamResponse {
  accepted: boolean;
  request_id: string;
}

export interface ActiveStockContext {
  stock_code: string;
  stock_name: string | null;
  canonical_id: string;
  asset_type: 'stock' | 'index';
}

export interface ChatStateFields {
  active_stock_context?: ActiveStockContext | null;
  session_state_version?: number;
  session_generation?: string | null;
}

export interface DecodedChatState {
  contract: 'authoritative' | 'legacy';
  activeStockContext: ActiveStockContext | null;
  sessionStateVersion: number | null;
  sessionGeneration: string | null;
  selectedSkillIds: string[] | null;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function decodeChatState(payload: unknown, source: 'detail' | 'accepted' | 'response'): DecodedChatState {
  const invalid = () => createParsedApiError({
    title: '会话状态响应不完整', message: '请刷新会话后重试；本次响应不能确认讨论对象。',
    code: 'chat_state_protocol_error', category: 'http_error',
  });
  if (!record(payload)) throw invalid();
  const present = ['active_stock_context', 'session_state_version', 'session_generation'].filter((key) => key in payload);
  const authoritative = present.length === 3;
  if (present.length !== 0 && !authoritative) throw invalid();
  let selected: string[] | null = null;
  if ('session_state' in payload) {
    const skills = record(payload.session_state) ? payload.session_state.selected_skill_ids : undefined;
    if (skills !== null && (!Array.isArray(skills) || !skills.every((id) => typeof id === 'string'))) throw invalid();
    selected = skills === null ? null : [...skills as string[]];
  } else if (authoritative) {
    throw invalid();
  }
  if (!authoritative) return {
    contract: 'legacy', activeStockContext: null, sessionStateVersion: null,
    sessionGeneration: null, selectedSkillIds: selected,
  };

  const version = payload.session_state_version;
  const generation = payload.session_generation;
  const active = payload.active_stock_context;
  if (typeof version !== 'number' || !Number.isSafeInteger(version) || version < (source === 'detail' ? 0 : 1)) throw invalid();
  if (generation !== null && (typeof generation !== 'string' || !generation.trim())) throw invalid();
  if (generation === null && (source !== 'detail' || version !== 0 || active !== null)) throw invalid();
  if (active !== null && (!record(active)
    || typeof active.stock_code !== 'string' || !active.stock_code.trim()
    || typeof active.canonical_id !== 'string' || !active.canonical_id.trim()
    || (active.asset_type !== 'stock' && active.asset_type !== 'index')
    || (active.stock_name !== null && typeof active.stock_name !== 'string'))) throw invalid();
  return {
    contract: 'authoritative', activeStockContext: active === null ? null : {
      stock_code: active.stock_code as string, stock_name: active.stock_name as string | null,
      canonical_id: active.canonical_id as string, asset_type: active.asset_type as 'stock' | 'index',
    },
    sessionStateVersion: version, sessionGeneration: generation as string | null, selectedSkillIds: selected,
  };
}

export interface ChatResponse extends ChatStateFields {
  success: boolean;
  content: string;
  session_id: string;
  error?: string;
  session_state?: { selected_skill_ids: string[] | null };
}

export type AgentStatusResponse = AgentBackendStatusResponse;

export interface SkillInfo {
  id: string;
  name: string;
  description: string;
}

export interface SkillsResponse {
  skills: SkillInfo[];
  default_skill_id: string;
}

export interface ChatSessionItem {
  session_id: string;
  title: string;
  message_count: number;
  created_at: string | null;
  last_active: string | null;
}

export interface ChatSessionMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string | null;
}

export interface ChatSessionDetail extends ChatStateFields {
  session_id: string;
  messages: ChatSessionMessage[];
  session_state: {
    selected_skill_ids: string[] | null;
  };
}

export const agentApi = {
  async chat(payload: ChatRequest): Promise<ChatResponse> {
    const response = await apiClient.post<ChatResponse>('/api/v1/agent/chat', payload, {
      timeout: 120000,
    });
    decodeChatState(response.data, 'response');
    return response.data;
  },
  async getSkills(): Promise<SkillsResponse> {
    const response = await apiClient.get<SkillsResponse>('/api/v1/agent/skills');
    return response.data;
  },
  async getStatus(): Promise<AgentStatusResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/agent/status');
    return toCamelCase<AgentStatusResponse>(response.data);
  },
  async getChatSessions(limit = 50): Promise<ChatSessionItem[]> {
    const response = await apiClient.get<{ sessions: ChatSessionItem[] }>('/api/v1/agent/chat/sessions', { params: { limit } });
    return response.data.sessions;
  },
  async getChatSessionMessages(sessionId: string): Promise<ChatSessionDetail> {
    const response = await apiClient.get<ChatSessionDetail>(`/api/v1/agent/chat/sessions/${sessionId}`);
    decodeChatState(response.data, 'detail');
    return response.data;
  },
  async deleteChatSession(sessionId: string): Promise<void> {
    await apiClient.delete(`/api/v1/agent/chat/sessions/${sessionId}`);
  },
  async sendChat(content: string): Promise<{ success: boolean }> {
    const response = await apiClient.post<{
      success: boolean;
      error?: string;
      message?: string;
    }>('/api/v1/agent/chat/send', { content });
    const data = response.data;
    if (data.success === false) {
      throw new Error(data.message || '发送失败');
    }
    return { success: true };
  },
  async chatStream(
    payload: ChatStreamRequest,
    options?: ChatStreamOptions,
  ): Promise<Response> {
    const base = API_BASE_URL || '';
    const url = `${base}/api/v1/agent/chat/stream`;
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'include',
        signal: options?.signal,
      });

      if (response.ok) {
        return response;
      }

      const contentType = response.headers.get('content-type') || '';
      let responseData: unknown = null;
      if (contentType.includes('application/json')) {
        responseData = await response.json().catch(() => null);
      } else {
        responseData = await response.text().catch(() => null);
      }

      const parsed = parseApiError({
        response: {
          status: response.status,
          statusText: response.statusText,
          data: responseData,
        },
      });
      throw createApiError(parsed, {
        response: {
          status: response.status,
          statusText: response.statusText,
          data: responseData,
        },
      });
    } catch (error: unknown) {
      if (isApiRequestError(error)) {
        throw error;
      }
      if (isAbortError(error)) {
        throw error;
      }

      const parsed = parseApiError(error);
      throw createApiError(parsed, { cause: error });
    }
  },
  async cancelChatStream(requestId: string): Promise<CancelChatStreamResponse> {
    const response = await apiClient.post<CancelChatStreamResponse>(
      `/api/v1/agent/chat/stream/${encodeURIComponent(requestId)}/cancel`,
    );
    return response.data;
  },
};
