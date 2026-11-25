import apiClient from './index';

export type ConnectTarget = { mode: 'new' } | { registration_id: string } | { retry_id: string };

export type DisconnectTarget = { connection_id: string } | { attempt_id: string } | { identity_id: string };

export type ChatGPTAction = { label: string | null } & (
  | { kind: 'new'; target: { mode: 'new' } }
  | { kind: 'reauth' | 'grant_plan'; target: { registration_id: string } }
  | { kind: 'continue'; target: { retry_id: string } }
  | { kind: 'disconnect' | 'retry_disconnect'; target: { connection_id: string } }
  | { kind: 'cancel'; target: { attempt_id: string } }
  | { kind: 'sign_out'; target: { identity_id: string } }
);

export interface Revocation {
  owner_kind: 'registered' | 'unverified';
  state: 'pending' | 'unknown';
  operation_id: string | null;
  label: string | null;
}

export interface ChatGPTStatus {
  available: boolean;
  restart_required?: boolean;
  connected: boolean;
  connection_id?: string;
  disconnect_retry_connection_id?: string | null;
  account_label?: string;
  actions?: ChatGPTAction[];
  revocations?: Revocation[];
  reauth_reason?: 'scope_required' | 'credential_invalid' | 'legacy_import' | null;
  attempt_id?: string;
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
