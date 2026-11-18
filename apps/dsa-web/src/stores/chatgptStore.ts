import { isAxiosError } from 'axios';
import { create } from 'zustand';
import { chatgptApi, type ChatGPTModel, type ChatGPTStatus } from '../api/chatgpt';
import { getParsedApiError } from '../api/error';
import type { ChatGPTModelSource } from '../types/modelSource';

interface ChatGPTState {
  status: ChatGPTStatus | null;
  models: ChatGPTModel[];
  model: string;
  error: string | null;
  refresh: (refreshModels?: boolean) => Promise<void>;
  selectModel: (model: string) => void;
  disconnect: () => Promise<boolean | null | undefined>;
}

const connectionErrors = new Set([
  'chatgpt_connection_inactive',
  'chatgpt_plan_permission_required',
  'chatgpt_reauthorization_required',
]);

let readSequence = 0;

export const useChatGPTStore = create<ChatGPTState>((set, get) => {
  function applyStatus(status: ChatGPTStatus) {
    const changed = status.connection_id !== get().status?.connection_id;
    set({
      status, error: null,
      ...(changed || !status.connected ? { models: [], model: '' } : {}),
    });
    return changed;
  }

  async function readStatus(read: number) {
    const status = await chatgptApi.status();
    if (read === readSequence) return { status, changed: applyStatus(status) };
  }

  return {
    status: null, models: [], model: '', error: null,
    selectModel: (model) => set({ model }),
    refresh: async (refreshModels = false) => {
      const read = ++readSequence;
      try {
        const snapshot = await readStatus(read);
        if (!snapshot || read !== readSequence) return;
        const { status, changed } = snapshot;
        if (!status.connected || !status.connection_id || !(changed || refreshModels || !get().models.length)) return;
        try {
          const models = await chatgptApi.models(status.connection_id, refreshModels);
          if (read !== readSequence) return;
          set({ models, model: models.some(({ slug }) => slug === get().model) ? get().model : '' });
        } catch (error) {
          if (read !== readSequence) return;
          const code = isAxiosError<{ detail?: { error?: string } }>(error) && error.response?.data?.detail?.error;
          if (!code || !connectionErrors.has(code)) throw error;
          await readStatus(read);
        }
      } catch (error) {
        if (read === readSequence) set({ error: getParsedApiError(error).message });
      }
    },
    disconnect: async () => {
      const connectionId = get().status?.connection_id;
      ++readSequence;
      let result;
      try {
        result = await chatgptApi.disconnect();
      } catch (error) {
        if (!isAxiosError(error) || error.response) throw error;
        const snapshot = await readStatus(++readSequence).catch(() => undefined);
        const status = snapshot?.status;
        if (status?.available && !status.connected && status.pending === false) return false;
        return undefined;
      }

      if (!result.disconnected) return undefined;
      const status = get().status;
      if (!connectionId) {
        await get().refresh();
      } else if (status?.connection_id === connectionId) {
        ++readSequence;
        applyStatus({ ...status, connected: false, pending: false, connection_id: undefined, error: undefined });
      }
      return result.revocation_confirmed;
    },
  };
});

export function currentChatGPTSource(status: ChatGPTStatus | null, model: string): ChatGPTModelSource | undefined {
  if (status?.connected && status.connection_id && model) {
    return { provider: 'chatgpt_siwc', connection_id: status.connection_id, model };
  }
}
