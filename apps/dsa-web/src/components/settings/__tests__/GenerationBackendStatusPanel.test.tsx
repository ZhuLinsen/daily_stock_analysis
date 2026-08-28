import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GenerationBackendStatusPanel } from '../GenerationBackendStatusPanel';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import type { GenerationBackendStatusResponse, TestGenerationBackendResponse } from '../../../types/systemConfig';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';

const {
  getGenerationBackendStatus,
  previewGenerationBackendStatus,
  testGenerationBackend,
} = vi.hoisted(() => ({
  getGenerationBackendStatus: vi.fn(),
  previewGenerationBackendStatus: vi.fn(),
  testGenerationBackend: vi.fn(),
}));

vi.mock('../../../api/systemConfig', () => ({
  systemConfigApi: {
    getGenerationBackendStatus: (...args: unknown[]) => getGenerationBackendStatus(...args),
    previewGenerationBackendStatus: (...args: unknown[]) => previewGenerationBackendStatus(...args),
    testGenerationBackend: (...args: unknown[]) => testGenerationBackend(...args),
  },
}));

const litellmStatus: GenerationBackendStatusResponse = {
  primaryBackendId: 'litellm',
  fallbackBackendId: null,
  primary: {
    backendId: 'litellm',
    backendType: 'litellm',
    providerId: 'litellm',
    available: true,
    healthStatus: 'passed',
    supportsJson: true,
    supportsTools: true,
    supportsStream: true,
    supportsVision: false,
    isPrimary: true,
    fallbackTarget: null,
    maxConcurrency: 1,
    usageAvailable: true,
    lastErrorCode: null,
    lastErrorMessage: null,
  },
  fallback: null,
  backends: [],
};

const removedBackendStatus: GenerationBackendStatusResponse = {
  primaryBackendId: 'codex_cli',
  fallbackBackendId: null,
  primary: {
    backendId: 'codex_cli',
    backendType: 'litellm',
    providerId: 'codex_cli',
    available: false,
    healthStatus: 'failed',
    supportsJson: false,
    supportsTools: false,
    supportsStream: false,
    supportsVision: false,
    isPrimary: true,
    fallbackTarget: null,
    maxConcurrency: 1,
    usageAvailable: false,
    lastErrorCode: 'backend_not_configured',
    lastErrorMessage: 'Removed backend: codex_cli',
  },
  fallback: null,
  backends: [],
};

const smokePassed: TestGenerationBackendResponse = {
  success: true,
  mode: 'json',
  message: '生成后端冒烟测试通过',
  status: litellmStatus.primary,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

describe('GenerationBackendStatusPanel', () => {
  beforeEach(() => {
    window.localStorage.clear();
    getGenerationBackendStatus.mockReset();
    previewGenerationBackendStatus.mockReset();
    testGenerationBackend.mockReset();
    getGenerationBackendStatus.mockResolvedValue(litellmStatus);
    previewGenerationBackendStatus.mockResolvedValue(litellmStatus);
    testGenerationBackend.mockResolvedValue(smokePassed);
  });

  it('loads saved generation backend status without draft items', async () => {
    render(<GenerationBackendStatusPanel items={[]} maskToken="******" />);

    await waitFor(() => {
      expect(getGenerationBackendStatus).toHaveBeenCalledTimes(1);
    });
    expect(previewGenerationBackendStatus).not.toHaveBeenCalled();
    expect(await screen.findByText('litellm')).toBeInTheDocument();
    expect(screen.getByText(/当前后端用于报告生成/)).toBeInTheDocument();
  });

  it('explains a saved removed backend id as a structured failure', async () => {
    getGenerationBackendStatus.mockResolvedValueOnce(removedBackendStatus);
    render(<GenerationBackendStatusPanel items={[]} maskToken="******" />);

    expect(await screen.findByText('codex_cli')).toBeInTheDocument();
    expect(screen.getByText(/backend_not_configured: Removed backend: codex_cli/)).toBeInTheDocument();
  });

  it('previews unsaved draft generation backend status', async () => {
    render(
      <GenerationBackendStatusPanel
        items={[{ key: 'GENERATION_BACKEND', value: 'litellm' }]}
        maskToken="******"
      />,
    );

    await waitFor(() => {
      expect(previewGenerationBackendStatus).toHaveBeenCalledWith({
        items: [{ key: 'GENERATION_BACKEND', value: 'litellm' }],
        maskToken: '******',
      });
    });
    expect(getGenerationBackendStatus).not.toHaveBeenCalled();
  });

  it('runs JSON smoke test with current draft items', async () => {
    render(
      <GenerationBackendStatusPanel
        items={[{ key: 'GENERATION_BACKEND', value: 'litellm' }]}
        maskToken="******"
      />,
    );

    fireEvent.click(await screen.findByRole('button', { name: /JSON 冒烟测试/ }));

    await waitFor(() => {
      expect(testGenerationBackend).toHaveBeenCalledWith({
        mode: 'json',
        items: [{ key: 'GENERATION_BACKEND', value: 'litellm' }],
        maskToken: '******',
      });
    });
    expect(await screen.findByText('冒烟测试通过')).toBeInTheDocument();
  });

  it('clears stale smoke result when draft items change', async () => {
    const { rerender } = render(
      <GenerationBackendStatusPanel
        items={[{ key: 'GENERATION_BACKEND', value: 'litellm' }]}
        maskToken="******"
      />,
    );

    fireEvent.click(await screen.findByRole('button', { name: /JSON 冒烟测试/ }));
    expect(await screen.findByText('冒烟测试通过')).toBeInTheDocument();

    rerender(
      <GenerationBackendStatusPanel
        items={[{ key: 'LITELLM_MODEL', value: 'openai/gpt-5.5' }]}
        maskToken="******"
      />,
    );

    await waitFor(() => {
      expect(screen.queryByText('冒烟测试通过')).not.toBeInTheDocument();
    });
  });

  it('ignores stale generation backend preview responses', async () => {
    const firstPreview = deferred<GenerationBackendStatusResponse>();
    const secondPreview = deferred<GenerationBackendStatusResponse>();
    previewGenerationBackendStatus
      .mockReturnValueOnce(firstPreview.promise)
      .mockReturnValueOnce(secondPreview.promise);

    const { rerender } = render(
      <GenerationBackendStatusPanel
        items={[{ key: 'GENERATION_BACKEND', value: 'codex_cli' }]}
        maskToken="******"
      />,
    );
    await waitFor(() => expect(previewGenerationBackendStatus).toHaveBeenCalledTimes(1));

    rerender(
      <GenerationBackendStatusPanel
        items={[{ key: 'GENERATION_BACKEND', value: 'litellm' }]}
        maskToken="******"
      />,
    );
    await waitFor(() => expect(previewGenerationBackendStatus).toHaveBeenCalledTimes(2));

    await act(async () => {
      secondPreview.resolve(litellmStatus);
      await secondPreview.promise;
    });
    expect(await screen.findByText('litellm')).toBeInTheDocument();

    await act(async () => {
      firstPreview.resolve(removedBackendStatus);
      await firstPreview.promise;
    });

    await waitFor(() => expect(screen.getByText('litellm')).toBeInTheDocument());
    expect(screen.queryByText(/backend_not_configured/)).not.toBeInTheDocument();
  });

  it('clears stale status when preview request fails', async () => {
    const { rerender } = render(<GenerationBackendStatusPanel items={[]} maskToken="******" />);
    expect(await screen.findByText('litellm')).toBeInTheDocument();

    previewGenerationBackendStatus.mockRejectedValueOnce(new Error('validation failed'));
    rerender(
      <GenerationBackendStatusPanel
        items={[{ key: 'LITELLM_MODEL', value: 'bad' }]}
        maskToken="******"
      />,
    );

    await waitFor(() => {
      expect(screen.queryByText('litellm')).not.toBeInTheDocument();
    });
  });

  it('shows smoke status even when initial status has not loaded', async () => {
    getGenerationBackendStatus.mockReturnValueOnce(new Promise(() => undefined));

    render(<GenerationBackendStatusPanel items={[]} maskToken="******" />);

    fireEvent.click(screen.getByRole('button', { name: /JSON 冒烟测试/ }));

    expect(await screen.findByText('冒烟测试通过')).toBeInTheDocument();
    expect(await screen.findByText('litellm')).toBeInTheDocument();
  });

  it('renders generation backend status labels in English when UI language is English', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');

    render(
      <UiLanguageProvider>
        <GenerationBackendStatusPanel items={[]} maskToken="******" />
      </UiLanguageProvider>,
    );

    expect(await screen.findByText('Generation backend status')).toBeInTheDocument();
    expect(screen.getByText('Primary backend')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /JSON smoke test/ })).toBeInTheDocument();
  });
});
