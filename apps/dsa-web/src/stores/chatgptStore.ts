import { isAxiosError } from 'axios';
import { create } from 'zustand';
import { chatgptApi, type DisconnectTarget, type ChatGPTModel, type ChatGPTStatus } from '../api/chatgpt';
import { extractErrorCode, getParsedApiError } from '../api/error';
import type { ChatGPTModelSource } from '../types/modelSource';

interface ChatGPTState {
  status: ChatGPTStatus | null;
  models: ChatGPTModel[];
  model: string;
  error: string | null;
  refresh: (refreshModels?: boolean) => Promise<void>;
  recheckStatus: () => Promise<void>;
  selectModel: (model: string) => void;
  disconnect: (target: DisconnectTarget) => Promise<boolean | null | undefined>;
}

const connectionErrors = new Set([
  'chatgpt_connection_inactive',
  'chatgpt_plan_permission_required',
  'chatgpt_reauthorization_required',
]);
const statusReadbackErrors = new Set(['chatgpt_protocol_error', 'chatgpt_store_unavailable']);

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

  async function syncConnection(read: number, refreshModels = false) {
    let failedConnection: string | undefined;
    let catalogError: unknown;
    while (read === readSequence) {
      const status = await chatgptApi.status();
      if (read !== readSequence) return;
      const changed = applyStatus(status);
      const id = status.connection_id;
      if (!status.connected || !id) return status;
      if (id === failedConnection) {
        if (catalogError) throw catalogError;
        return status;
      }
      if (!changed && !refreshModels && get().models.length) return status;
      try {
        const models = await chatgptApi.models(id, refreshModels);
        if (read !== readSequence) return;
        set({ models, model: models.some(({ slug }) => slug === get().model) ? get().model : '' });
        return status;
      } catch (error) {
        if (read !== readSequence) return;
        const code = isAxiosError(error) && extractErrorCode(error.response?.data);
        if (code && connectionErrors.has(code)) {
          // The old selection is invalid even if the next status read fails.
          set({ status: null, model: '', models: [] });
        } else if (code && statusReadbackErrors.has(code)) {
          catalogError = error;
        } else {
          throw error;
        }
        failedConnection = id;
        refreshModels = false;
      }
    }
  }

  return {
    status: null, models: [], model: '', error: null,
    selectModel: (model) => set({ model }),
    recheckStatus: async () => {
      const read = ++readSequence;
      try {
        const status = await chatgptApi.status();
        if (read === readSequence) applyStatus(status);
      } catch (error) {
        if (read === readSequence) set({ error: getParsedApiError(error).message });
      }
    },
    refresh: async (refreshModels = false) => {
      const read = ++readSequence;
      try {
        await syncConnection(read, refreshModels);
      } catch (error) {
        if (read === readSequence) set({ error: getParsedApiError(error).message });
      }
    },
    disconnect: async (target) => {
      const connectionId = 'connection_id' in target ? target.connection_id : undefined;
      ++readSequence;
      let result;
      try {
        result = await chatgptApi.disconnect(target);
      } catch (error) {
        if (!isAxiosError(error)) throw error;
        if (error.response) {
          const code = extractErrorCode(error.response.data);
          if (code === 'chatgpt_target_changed' || code === 'chatgpt_connection_busy' || code === 'chatgpt_store_unavailable') await get().refresh();
          throw error;
        }
        const status = await syncConnection(++readSequence).catch(() => undefined);
        if (status?.available && !status.connected && status.pending === false && !status.disconnect_retry_connection_id) return false;
        return undefined;
      }

      if (!result.disconnected) return undefined;
      const status = get().status;
      if (connectionId && status?.connection_id === connectionId) {
        set({ status: null, models: [], model: '' });
      }
      await get().refresh();
      return result.revocation_confirmed;
    },
  };
});

export function currentChatGPTSource(status: ChatGPTStatus | null, model: string): ChatGPTModelSource | undefined {
  if (status?.connected && status.connection_id && model) {
    return { provider: 'chatgpt_siwc', connection_id: status.connection_id, model };
  }
}
