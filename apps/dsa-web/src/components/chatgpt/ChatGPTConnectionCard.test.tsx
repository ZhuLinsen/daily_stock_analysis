import { act, fireEvent, render, screen } from '@testing-library/react';
import { AxiosError } from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { chatgptApi, type ChatGPTModel } from '../../api/chatgpt';
import { useChatGPTStore } from '../../stores/chatgptStore';
import { ChatGPTConnectionCard } from './ChatGPTConnectionCard';

vi.mock('../../api/chatgpt', () => ({
  chatgptApi: { status: vi.fn(), models: vi.fn(), disconnect: vi.fn() },
}));

const connected = { available: true, connected: true, connection_id: 'old', account_label: 'Test', pending: false };
const disconnected = { available: true, connected: false, account_label: 'Test', pending: false };
const model = { slug: 'fixture', display_name: 'Fixture model' };
const api = vi.mocked(chatgptApi);

async function openConnectionCard() {
  render(<ChatGPTConnectionCard />);
  await screen.findByRole('option', { name: model.display_name });
  fireEvent.change(screen.getByRole('combobox', { name: '模型' }), { target: { value: model.slug } });
}

describe('ChatGPT connection status', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    useChatGPTStore.setState({ status: null, models: [], model: '', error: null });
    api.status.mockResolvedValue(connected);
    api.models.mockResolvedValue([model]);
  });

  it('re-reads status after losing the disconnect response and discards an older model list', async () => {
    let resolveModels!: (models: ChatGPTModel[]) => void;
    const delayedModels = new Promise<ChatGPTModel[]>((resolve) => { resolveModels = resolve; });
    await openConnectionCard();
    api.models.mockReturnValueOnce(delayedModels);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '刷新模型' }));
    });
    expect(api.models).toHaveBeenLastCalledWith(connected.connection_id, true);
    api.status.mockResolvedValue(disconnected);
    api.disconnect.mockRejectedValueOnce(new AxiosError('timeout', 'ECONNABORTED'));
    fireEvent.click(screen.getByRole('button', { name: '断开连接' }));

    expect(await screen.findByText(/本地已断开/)).toBeVisible();
    await act(async () => { resolveModels([model]); });
    expect(screen.queryByText(/已授权/)).not.toBeInTheDocument();
    expect(useChatGPTStore.getState()).toMatchObject({ status: disconnected, model: '', models: [] });
    expect(api.status).toHaveBeenCalledTimes(3);
    expect(api.disconnect).toHaveBeenCalledTimes(1);
  });

  it.each([
    {
      description: 'confirmed loss of authorization',
      error: { isAxiosError: true, response: { status: 400, data: {
        detail: { error: 'chatgpt_reauthorization_required', message: 'Please reauthorize' },
      } } },
      status: { ...disconnected, error: 'chatgpt_reauthorization_required' },
      display: '连接已失效，请重新授权。',
      selected: '',
    },
    {
      description: 'temporary unavailability',
      error: new AxiosError('upstream unavailable', 'ERR_NETWORK'),
      status: connected,
      display: /无法连接|网络|上游/,
      selected: model.slug,
    },
  ])('reconciles a model refresh after $description', async ({ error, status, display, selected }) => {
    await openConnectionCard();
    api.status.mockResolvedValueOnce(connected).mockResolvedValue(status);
    api.models.mockRejectedValueOnce(error);
    fireEvent.click(screen.getByRole('button', { name: '刷新模型' }));

    expect(await screen.findByText(display)).toBeVisible();
    expect(useChatGPTStore.getState()).toMatchObject({ status, model: selected });
    expect(api.status).toHaveBeenCalledTimes(selected ? 2 : 3);
  });
});
