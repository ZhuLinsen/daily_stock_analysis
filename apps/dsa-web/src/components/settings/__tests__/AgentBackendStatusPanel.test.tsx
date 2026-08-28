import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentBackendStatusResponse } from '../../../types/systemConfig';
import { AgentBackendStatusPanel } from '../AgentBackendStatusPanel';

const { getStatus, previewStatus } = vi.hoisted(() => ({
  getStatus: vi.fn(),
  previewStatus: vi.fn(),
}));

vi.mock('../../../api/systemConfig', () => ({
  systemConfigApi: {
    getAgentBackendStatus: (...args: unknown[]) => getStatus(...args),
    previewAgentBackendStatus: (...args: unknown[]) => previewStatus(...args),
  },
}));

const litellmStatus: AgentBackendStatusResponse = {
  backend: 'litellm',
  available: true,
  experimental: false,
  version: null,
  errorCode: null,
  message: null,
};

const unsupportedStatus: AgentBackendStatusResponse = {
  backend: 'codex_app_server',
  available: false,
  experimental: false,
  version: null,
  errorCode: 'capability_unsupported',
  message: 'Unsupported AGENT_BACKEND: codex_app_server',
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

function renderPanel(overrides: Partial<React.ComponentProps<typeof AgentBackendStatusPanel>> = {}) {
  const props: React.ComponentProps<typeof AgentBackendStatusPanel> = {
    items: [],
    maskToken: '******',
    onEnableAgentMode: vi.fn(),
    ...overrides,
  };
  return { ...render(<AgentBackendStatusPanel {...props} />), props };
}

describe('AgentBackendStatusPanel', () => {
  beforeEach(() => {
    getStatus.mockReset().mockResolvedValue(litellmStatus);
    previewStatus.mockReset().mockResolvedValue(litellmStatus);
  });

  it('checks saved compatibility without offering a model smoke test', async () => {
    renderPanel();

    await waitFor(() => expect(getStatus).toHaveBeenCalledTimes(1));
    expect(previewStatus).not.toHaveBeenCalled();
    expect(await screen.findByText('默认模型')).toBeInTheDocument();
    expect(screen.getByText('可以尝试')).toBeInTheDocument();
    expect(screen.getByText(/不会登录、调用模型或读取股票数据/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /真实测试/ })).not.toBeInTheDocument();
  });

  it('previews unsaved Agent settings through the same compatibility contract', async () => {
    renderPanel({
      items: [{ key: 'AGENT_BACKEND', value: 'litellm' }],
    });

    await waitFor(() => expect(previewStatus).toHaveBeenCalledWith({
      items: [{ key: 'AGENT_BACKEND', value: 'litellm' }],
      maskToken: '******',
    }));
    expect(getStatus).not.toHaveBeenCalled();
    expect(await screen.findByText('默认模型')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /真实测试/ })).not.toBeInTheDocument();
  });

  it('explains a removed backend id from the draft preview', async () => {
    previewStatus.mockResolvedValueOnce(unsupportedStatus);
    renderPanel({
      items: [{ key: 'AGENT_BACKEND', value: 'codex_app_server' }],
    });

    await waitFor(() => expect(previewStatus).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('需要处理')).toBeInTheDocument();
    expect(screen.getByText(/仅保留默认模型/)).toBeInTheDocument();
    expect(screen.getByText(/错误代码: capability_unsupported/)).toBeInTheDocument();
    expect(screen.queryByText('Unsupported AGENT_BACKEND: codex_app_server')).not.toBeInTheDocument();
  });

  it('ignores a stale draft preview response', async () => {
    const first = deferred<AgentBackendStatusResponse>();
    const second = deferred<AgentBackendStatusResponse>();
    previewStatus.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { rerender, props } = renderPanel({
      items: [{ key: 'AGENT_BACKEND', value: 'codex_app_server' }],
    });
    await waitFor(() => expect(previewStatus).toHaveBeenCalledTimes(1));

    rerender(
      <AgentBackendStatusPanel
        {...props}
        items={[{ key: 'AGENT_BACKEND', value: 'litellm' }]}
      />,
    );
    await waitFor(() => expect(previewStatus).toHaveBeenCalledTimes(2));
    await act(async () => {
      second.resolve(litellmStatus);
      await second.promise;
    });
    expect(await screen.findByText('默认模型')).toBeInTheDocument();

    await act(async () => {
      first.resolve(unsupportedStatus);
      await first.promise;
    });
    expect(screen.queryByText('需要处理')).not.toBeInTheDocument();
  });

  it('explains disabled Agent mode and only updates the draft on action', async () => {
    const onEnableAgentMode = vi.fn();
    getStatus.mockResolvedValueOnce({
      ...litellmStatus,
      available: false,
      errorCode: 'agent_mode_disabled',
      message: 'internal message must not be shown',
    });
    renderPanel({ onEnableAgentMode });

    expect(await screen.findByText('需要启用 Agent 模式')).toBeInTheDocument();
    expect(screen.getAllByText(/保存设置后再使用问股/)).not.toHaveLength(0);
    expect(screen.queryByText('internal message must not be shown')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '启用 Agent 模式' }));
    expect(onEnableAgentMode).toHaveBeenCalledTimes(1);
  });

  it('recovers from a temporary status read failure by manual refresh', async () => {
    getStatus.mockRejectedValueOnce(new Error('temporary read failed'));
    renderPanel();

    expect(await screen.findByText('temporary read failed')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刷新状态' }));
    expect(await screen.findByText('默认模型')).toBeInTheDocument();
    expect(getStatus).toHaveBeenCalledTimes(2);
  });
});
