import apiClient from './index';

export type ConnectTarget = { registration_id: string } | { retry_id: string };

export type DisconnectTarget = { connection_id: string } | { attempt_id: string };

export interface ChatGPTStatus {
  available: boolean;
  connected: boolean;
  connection_id?: string;
  account_label?: string;
  registration_id?: string;
  accounts?: { id: string; label: string }[];
  attempt_id?: string;
  revocation_unconfirmed?: boolean;
  revocation_account_label?: string | null;
  retry_id?: string | null;
  pending?: boolean;
  cancelling?: boolean;
  error?: string;
}

export interface ChatGPTModel {
  slug: string;
  display_name: string;
}

export const chatgptApi = {
  async status() {
    return (await apiClient.get<ChatGPTStatus>('/api/v1/chatgpt/status')).data;
  },
  async connect(target?: ConnectTarget) {
    return (await apiClient.post<{ authorization_url: string }>('/api/v1/chatgpt/connect', target ?? {})).data;
  },
  async models(connectionId: string, refresh: boolean) {
    return (await apiClient.get<{ models: ChatGPTModel[] }>('/api/v1/chatgpt/models', {
      params: { connection_id: connectionId, refresh },
    })).data.models;
  },
  async disconnect(target: DisconnectTarget) {
    return (await apiClient.post<{ disconnected: boolean; revocation_confirmed: boolean | null }>(
      '/api/v1/chatgpt/disconnect', target,
    )).data;
  },
};
