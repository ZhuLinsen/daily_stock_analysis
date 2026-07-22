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

const codexStatus: AgentBackendStatusResponse = {
  backend: 'codex_app_server',
  available: true,
  experimental: true,
  version: 'codex-cli test',
  errorCode: null,
  message: null,
};

const litellmStatus: AgentBackendStatusResponse = {
  backend: 'litellm',
  available: true,
  experimental: false,
  version: null,
  errorCode: null,
  message: null,
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
    selectedBackend: 'auto',
    agentArch: 'single',
    onUseSingleAgent: vi.fn(),
    onEnableAgentMode: vi.fn(),
    ...overrides,
  };
  return { ...render(<AgentBackendStatusPanel {...props} />), props };
}

describe('AgentBackendStatusPanel', () => {
  beforeEach(() => {
    getStatus.mockReset().mockResolvedValue(litellmStatus);
    previewStatus.mockReset().mockResolvedValue(codexStatus);
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
      items: [{ key: 'AGENT_BACKEND', value: 'codex_app_server' }],
      selectedBackend: 'codex_app_server',
    });

    await waitFor(() => expect(previewStatus).toHaveBeenCalledWith({
      items: [{ key: 'AGENT_BACKEND', value: 'codex_app_server' }],
      maskToken: '******',
    }));
    expect(getStatus).not.toHaveBeenCalled();
    expect(await screen.findByText('Codex Agent')).toBeInTheDocument();
    expect(screen.getByText('实验功能')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /真实测试/ })).not.toBeInTheDocument();
  });

  it('ignores a stale draft preview response', async () => {
    const first = deferred<AgentBackendStatusResponse>();
    const second = deferred<AgentBackendStatusResponse>();
    previewStatus.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { rerender, props } = renderPanel({
      items: [{ key: 'AGENT_BACKEND', value: 'codex_app_server' }],
      selectedBackend: 'codex_app_server',
    });
    await waitFor(() => expect(previewStatus).toHaveBeenCalledTimes(1));

    rerender(
      <AgentBackendStatusPanel
        {...props}
        items={[{ key: 'AGENT_BACKEND', value: 'litellm' }]}
        selectedBackend="litellm"
      />,
    );
    await waitFor(() => expect(previewStatus).toHaveBeenCalledTimes(2));
    await act(async () => {
      second.resolve(litellmStatus);
      await second.promise;
    });
    expect(await screen.findByText('默认模型')).toBeInTheDocument();

    await act(async () => {
      first.resolve(codexStatus);
      await first.promise;
    });
    expect(screen.queryByText('Codex Agent')).not.toBeInTheDocument();
  });

  it('shows the Codex multi-agent conflict without making a status request', async () => {
    const onUseSingleAgent = vi.fn();
    renderPanel({
      items: [
        { key: 'AGENT_BACKEND', value: 'codex_app_server' },
        { key: 'AGENT_ARCH', value: 'multi' },
      ],
      selectedBackend: 'codex_app_server',
      agentArch: 'multi',
      onUseSingleAgent,
    });

    expect(screen.getByRole('button', { name: '刷新状态' })).toBeDisabled();
    expect(getStatus).not.toHaveBeenCalled();
    expect(previewStatus).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '切换为单 Agent' }));
    expect(onUseSingleAgent).toHaveBeenCalledTimes(1);
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
