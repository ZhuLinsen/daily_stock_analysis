import { act, fireEvent, render, screen } from '@testing-library/react';
import { AxiosError } from 'axios';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { chatgptApi, type ChatGPTModel, type ChatGPTStatus } from '../../api/chatgpt';
import { useChatGPTStore } from '../../stores/chatgptStore';
import { ChatGPTConnectionCard } from './ChatGPTConnectionCard';

vi.mock('../../api/chatgpt', () => ({
  chatgptApi: { status: vi.fn(), models: vi.fn(), disconnect: vi.fn(), connect: vi.fn() },
}));

const connected: ChatGPTStatus = { actions: [{kind:"disconnect", target:{connection_id:"old"}, label:null}], available: true, connected: true, connection_id: 'old', account_label: 'Test', pending: false };
const disconnected: ChatGPTStatus = { actions: [{kind:"reauth", target:{registration_id:"saved"}, label:"Saved (saved)"}, {kind:"new", target:{mode:"new"},label:null}], available: true, connected: false, account_label: 'Test', pending: false };
const retryDisconnect: ChatGPTStatus = { ...disconnected, actions: [{kind:"retry_disconnect",target:{connection_id:"old"},label:null}], error: 'chatgpt_store_unavailable', disconnect_retry_connection_id: 'old' };
const model = { slug: 'fixture', display_name: 'Fixture model' };

function apiError(status: number, error: string) {
  return { isAxiosError: true, response: { status, data: { error, message: 'Fixture error' } } };
}
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

  it('continues the pending retry read from status and starts fresh only on explicit request', async () => {
    const replacement = { location: { replace: vi.fn() }, close: vi.fn() } as unknown as Window;
    const popup = vi.spyOn(window, 'open').mockReturnValue(replacement);
    try {
      api.status.mockResolvedValue({ ...disconnected, retry_id: 'retry', actions: [{kind:'continue',target:{retry_id:'retry'},label:null}, ...disconnected.actions!] });
      api.connect.mockResolvedValue({ authorization_url: 'https://example.invalid/fixture' });
      render(<ChatGPTConnectionCard />);
      const retry = await screen.findByRole('button', { name: '继续上次授权' });
      await act(async () => { fireEvent.click(retry); });
      expect(api.connect).toHaveBeenLastCalledWith({ retry_id: 'retry' });

      const saved = screen.getByRole('button', { name: '放弃上次授权，改用 Saved (saved)' });
      await act(async () => { fireEvent.click(saved); });
      expect(api.connect).toHaveBeenLastCalledWith({ registration_id: 'saved' });

      api.status.mockResolvedValue({ ...disconnected, retry_id: null });
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: '重新开始授权' })); });
      expect(api.connect).toHaveBeenLastCalledWith({mode:"new"});
      expect(screen.queryByRole('button', { name: '继续上次授权' })).not.toBeInTheDocument();
    } finally {
      popup.mockRestore();
    }
  });

  it.each([false, true])('reads a named unconfirmed revocation after disconnect (stale: %s)', async (stale) => {
    const card = render(<ChatGPTConnectionCard />);
    const disconnect = await screen.findByRole('button', { name: '断开连接' });
    if (stale) {
      api.disconnect.mockRejectedValueOnce(apiError(409, 'chatgpt_target_changed'));
    } else {
      api.disconnect.mockResolvedValue({ disconnected: true, revocation_confirmed: false });
    }
    api.status.mockResolvedValue({ ...disconnected, revocations: [{state:'unknown',owner_kind:'registered',label:'Test',operation_id:null}] });
    fireEvent.click(disconnect);
    expect(await screen.findByText(/账号 Test 的远端撤销未确认/)).toBeVisible();
    card.unmount();
    useChatGPTStore.setState({ status: null });
    render(<ChatGPTConnectionCard />);
    expect(await screen.findByText(/账号 Test 的远端撤销未确认/)).toBeVisible();
  });

  it.each([
    apiError(503, 'chatgpt_store_unavailable'),
    new AxiosError('timeout', 'ECONNABORTED'),
  ])('keeps the server-owned disconnect target when the first attempt fails (%#)', async (error) => {
    const view = render(<ChatGPTConnectionCard />);
    const disconnect = await screen.findByRole('button', { name: '断开连接' });
    api.disconnect.mockRejectedValueOnce(error);
    api.status.mockResolvedValue(retryDisconnect);
    await act(async () => { fireEvent.click(disconnect); });

    expect(screen.getByRole('button', { name: '重试断开' })).toBeVisible();
    expect(screen.queryByRole('button', { name: /重新授权/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '连接其他账号' })).not.toBeInTheDocument();
    expect(screen.queryByText(/本地已断开/)).not.toBeInTheDocument();
    view.unmount();
    render(<ChatGPTConnectionCard />);

    api.disconnect.mockResolvedValueOnce({ disconnected: true, revocation_confirmed: true });
    const retry = await screen.findByRole('button', { name: '重试断开' });
    api.status.mockResolvedValue(disconnected);
    await act(async () => { fireEvent.click(retry); });
    expect(api.disconnect).toHaveBeenNthCalledWith(2, { connection_id: 'old' });
    expect(screen.queryByRole('button', { name: '重试断开' })).not.toBeInTheDocument();
  });

  it('reads a pending disconnect when a stale authorization action returns busy', async () => {
    const replacement = { close: vi.fn() } as unknown as Window;
    const popup = vi.spyOn(window, 'open').mockReturnValue(replacement);
    try {
      api.status.mockResolvedValue(disconnected);
      render(<ChatGPTConnectionCard />);
      const connect = await screen.findByRole('button', { name: /重新授权/ });
      api.connect.mockRejectedValueOnce(apiError(409, 'chatgpt_connection_busy'));
      api.status.mockResolvedValue(retryDisconnect);
      await act(async () => { fireEvent.click(connect); });

      expect(replacement.close).toHaveBeenCalledOnce();
      expect(screen.getByRole('button', { name: '重试断开' })).toBeVisible();
      expect(screen.getByText(/请先修复本机 ChatGPT 凭据存储/)).toBeVisible();
      expect(screen.queryByRole('button', { name: /重新授权/ })).not.toBeInTheDocument();
    } finally {
      popup.mockRestore();
    }
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
    expect(api.disconnect).toHaveBeenCalledWith({ connection_id: 'old' });
  });

  it('reconciles the replacement connection when its model list discovers a lost grant', async () => {
    await openConnectionCard();
    api.disconnect.mockRejectedValueOnce({ isAxiosError: true, response: { status: 409, data: {
      error: 'chatgpt_target_changed', message: 'Target changed',
    } } });
    api.status.mockResolvedValueOnce({ ...connected, connection_id: 'replacement' })
      .mockResolvedValue({ ...disconnected, error: 'chatgpt_reauthorization_required' });
    api.models.mockRejectedValueOnce({ isAxiosError: true, response: { status: 400, data: {
      error: 'chatgpt_reauthorization_required', message: 'Lost grant',
    } } });
    fireEvent.click(screen.getByRole('button', { name: '断开连接' }));

    expect(await screen.findByText('连接已失效，请重新授权。')).toBeVisible();
    expect(api.models).toHaveBeenLastCalledWith('replacement', false);
    expect(useChatGPTStore.getState()).toMatchObject({ status: { connected: false }, models: [], model: '' });
  });

  it('shows the final revocation warning after the user cancels an exchange', async () => {
    const pending: ChatGPTStatus = { ...disconnected, actions:[{kind:"cancel",target:{attempt_id:"attempt"},label:null}], pending: true, attempt_id: 'attempt' };
    api.status.mockResolvedValue(pending);
    render(<ChatGPTConnectionCard />);
    const cancel = await screen.findByRole('button', { name: '取消授权' });
    api.disconnect.mockResolvedValueOnce({ disconnected: true, revocation_confirmed: false });
    api.status.mockResolvedValue({ ...pending, cancelling: true });
    fireEvent.click(cancel);
    expect(await screen.findByText(/本地授权已取消/)).toBeVisible();

    api.status.mockResolvedValue({ ...disconnected, revocations: [{state:"unknown",owner_kind:"registered",label:"Test",operation_id:null}] });
    await act(async () => { await useChatGPTStore.getState().refresh(); });
    expect(screen.getByText(/远端撤销未确认/)).toBeVisible();
  });

  it.each([
    {
      description: 'confirmed loss of authorization',
      error: { isAxiosError: true, response: { status: 400, data: {
        error: 'chatgpt_reauthorization_required', message: 'Please reauthorize',
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
