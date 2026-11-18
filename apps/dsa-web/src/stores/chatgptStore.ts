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
  disconnect: () => Promise<boolean | null>;
}

let readSequence = 0;

export const useChatGPTStore = create<ChatGPTState>((set, get) => ({
  status: null, models: [], model: '', error: null,
  selectModel: (model) => set({ model }),
  refresh: async (refreshModels = false) => {
    const read = ++readSequence;
    try {
      const status = await chatgptApi.status();
      if (read !== readSequence) return;
      const changed = status.connection_id !== get().status?.connection_id;
      set({
        status, error: null,
        ...(changed || !status.connected ? { models: [], model: '' } : {}),
      });
      if (status.connected && status.connection_id && (changed || refreshModels || !get().models.length)) {
        const models = await chatgptApi.models(status.connection_id, refreshModels);
        if (read !== readSequence) return;
        set({ models, model: models.some(({ slug }) => slug === get().model) ? get().model : '' });
      }
    } catch (error) {
      if (read === readSequence) set({ error: getParsedApiError(error).message });
    }
  },
  disconnect: async () => {
    ++readSequence;
    const result = await chatgptApi.disconnect();
    const status = get().status;
    if (status) set({ status: { ...status, connected: false, pending: false, connection_id: undefined }, models: [], model: '' });
    await get().refresh();
    return result.revocation_confirmed;
  },
}));

export function currentChatGPTSource(status: ChatGPTStatus | null, model: string): ChatGPTModelSource | undefined {
  if (status?.connected && status.connection_id && model) {
    return { provider: 'chatgpt_siwc', connection_id: status.connection_id, model };
  }
}
