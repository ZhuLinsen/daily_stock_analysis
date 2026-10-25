import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentBackendStatusResponse } from '../../../types/systemConfig';
import { AgentBackendStatusPanel } from '../AgentBackendStatusPanel';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';

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
  available: false,
  experimental: false,
  version: null,
  errorCode: 'backend_removed',
  message: 'removed',
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
    onEnableAgentMode: vi.fn(),
    ...overrides,
  };
  return { ...render(<AgentBackendStatusPanel {...props} />), props };
}

describe('AgentBackendStatusPanel', () => {
  beforeEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
    getStatus.mockReset().mockResolvedValue(litellmStatus);
    previewStatus.mockReset().mockResolvedValue(codexStatus);
  });

  it.each(['zh', 'en'] as const)('explains missing primary model configuration (%s)', async (language) => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, language);
    getStatus.mockResolvedValueOnce({
      ...litellmStatus,
      available: false,
      errorCode: 'capability_unsupported',
      message: 'no_agent_primary',
    });
    render(<UiLanguageProvider><AgentBackendStatusPanel
      items={[]} maskToken="******" selectedBackend="auto" onEnableAgentMode={vi.fn()}
    /></UiLanguageProvider>);

    expect(await screen.findByText(language === 'en'
      ? 'Default-model ask-stock is unavailable. Open Agent settings and review the model configuration.'
      : '默认模型问股当前不可用，请前往 Agent 设置检查模型配置。')).toBeInTheDocument();
    expect(screen.queryByText('no_agent_primary')).not.toBeInTheDocument();
    expect(screen.getByText(/capability_unsupported/)).toBeInTheDocument();
  });

  it('preserves other capability failure messages', async () => {
    getStatus.mockResolvedValueOnce({
      ...litellmStatus,
      available: false,
      errorCode: 'capability_unsupported',
      message: 'Specific capability diagnostic',
    });
    renderPanel();
    expect(await screen.findByText('Specific capability diagnostic')).toBeInTheDocument();
  });

  it('checks saved compatibility without offering a model smoke test', async () => {
    renderPanel();

    await waitFor(() => expect(getStatus).toHaveBeenCalledTimes(1));
    expect(previewStatus).not.toHaveBeenCalled();
    expect(await screen.findByText('默认模型')).toBeInTheDocument();
    expect(screen.getByText('可以尝试')).toBeInTheDocument();
    expect(screen.getByText(/不会登录、调用模型、启动外部命令或读取股票数据/)).toBeInTheDocument();
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
    expect(await screen.findAllByText('Codex App Server（已移除）')).not.toHaveLength(0);
    expect(screen.queryByText('实验功能')).not.toBeInTheDocument();
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
    expect(screen.queryByText('Codex App Server（已移除）')).not.toBeInTheDocument();
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
