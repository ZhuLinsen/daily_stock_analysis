import apiClient from './index';

export interface ChatRequest {
  message: string;
  skills?: string[];
}

export interface ChatResponse {
  success: boolean;
  content: string;
  session_id: string;
  error?: string;
}

export interface StrategyInfo {
  id: string;
  name: string;
  description: string;
}

export interface StrategiesResponse {
  strategies: StrategyInfo[];
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

export const agentApi = {
  async chat(payload: ChatRequest): Promise<ChatResponse> {
    const response = await apiClient.post<ChatResponse>('/api/v1/agent/chat', payload, {
      timeout: 120000,
    });
    return response.data;
  },
  async getStrategies(): Promise<StrategiesResponse> {
    const response = await apiClient.get<StrategiesResponse>('/api/v1/agent/strategies');
    return response.data;
  },
  async getChatSessions(limit = 50): Promise<ChatSessionItem[]> {
    const response = await apiClient.get<{ sessions: ChatSessionItem[] }>('/api/v1/agent/chat/sessions', { params: { limit } });
    return response.data.sessions;
  },
  async getChatSessionMessages(sessionId: string): Promise<ChatSessionMessage[]> {
    const response = await apiClient.get<{ messages: ChatSessionMessage[] }>(`/api/v1/agent/chat/sessions/${sessionId}`);
    return response.data.messages;
  },
  async deleteChatSession(sessionId: string): Promise<void> {
    await apiClient.delete(`/api/v1/agent/chat/sessions/${sessionId}`);
  },
};
