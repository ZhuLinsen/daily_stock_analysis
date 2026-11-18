import apiClient from './index';

export interface ChatGPTStatus {
  available: boolean;
  connected: boolean;
  connection_id?: string;
  account_label?: string;
  pending?: boolean;
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
  async connect(newAccount: boolean, reconsent: boolean) {
    return (await apiClient.post<{ authorization_url: string }>('/api/v1/chatgpt/connect', {
      new_account: newAccount, reconsent,
    })).data;
  },
  async models(connectionId: string, refresh: boolean) {
    return (await apiClient.get<{ models: ChatGPTModel[] }>('/api/v1/chatgpt/models', {
      params: { connection_id: connectionId, refresh },
    })).data.models;
  },
  async disconnect() {
    return (await apiClient.post<{ revocation_confirmed: boolean | null }>('/api/v1/chatgpt/disconnect')).data;
  },
};
