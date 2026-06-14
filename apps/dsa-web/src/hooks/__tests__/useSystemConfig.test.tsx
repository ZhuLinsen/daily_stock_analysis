import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useSystemConfig } from '../useSystemConfig';

const { getConfig, validate, update } = vi.hoisted(() => ({
  getConfig: vi.fn(),
  validate: vi.fn(),
  update: vi.fn(),
}));

vi.mock('../../api/systemConfig', () => ({
  systemConfigApi: {
    getConfig,
    validate,
    update,
  },
  SystemConfigConflictError: class extends Error {},
  SystemConfigValidationError: class extends Error {
    issues: unknown[] = [];
    parsedError = {
      title: 'validation error',
      message: 'validation error',
      rawMessage: 'validation error',
      category: 'http_error',
    };
  },
}));

const sampleConfig = {
  configVersion: 'v1',
  maskToken: '******',
  items: [
    {
      key: 'STOCK_LIST',
      value: 'SH600000',
      rawValueExists: true,
      isMasked: false,
      schema: {
        key: 'STOCK_LIST',
        category: 'base',
        dataType: 'string',
        uiControl: 'textarea',
        isSensitive: false,
        isRequired: false,
        isEditable: true,
        options: [],
        validation: {},
        displayOrder: 1,
      },
    },
  ],
};

const sampleLlmConfig = {
  ...sampleConfig,
  items: [
    ...sampleConfig.items,
    {
      key: 'LLM_CHANNELS',
      value: 'primary',
      rawValueExists: true,
      isMasked: false,
      schema: {
        key: 'LLM_CHANNELS',
        category: 'ai_model',
        dataType: 'string',
        uiControl: 'textarea',
        isSensitive: false,
        isRequired: false,
        isEditable: true,
        options: [],
        validation: {},
        displayOrder: 10,
      },
    },
    {
      key: 'LITELLM_MODEL',
      value: 'gpt-5.0',
      rawValueExists: true,
      isMasked: false,
      schema: {
        key: 'LITELLM_MODEL',
        category: 'ai_model',
        dataType: 'string',
        uiControl: 'text',
        isSensitive: false,
        isRequired: false,
        isEditable: true,
        options: [],
        validation: {},
        displayOrder: 20,
      },
    },
    {
      key: 'OPENAI_BASE_URL',
      value: 'https://api.openai.com/v1',
      rawValueExists: true,
      isMasked: false,
      schema: {
        key: 'OPENAI_BASE_URL',
        category: 'ai_model',
        dataType: 'string',
        uiControl: 'text',
        isSensitive: false,
        isRequired: false,
        isEditable: true,
        options: [],
        validation: {},
        displayOrder: 30,
      },
    },
    {
      key: 'OPENAI_VISION_MODEL',
      value: 'gpt-4o-vision',
      rawValueExists: true,
      isMasked: false,
      schema: {
        key: 'OPENAI_VISION_MODEL',
        category: 'ai_model',
        dataType: 'string',
        uiControl: 'text',
        isSensitive: false,
        isRequired: false,
        isEditable: true,
        options: [],
        validation: {},
        displayOrder: 35,
      },
    },
  ],
};

describe('useSystemConfig', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getConfig.mockResolvedValue(sampleConfig);
    validate.mockResolvedValue({ valid: true, issues: [] });
    update.mockResolvedValue({ warnings: [] });
  });

  it('keeps load callback stable after a successful load', async () => {
    const { result } = renderHook(() => useSystemConfig());
    const firstLoad = result.current.load;

    await act(async () => {
      await result.current.load();
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(getConfig).toHaveBeenCalledTimes(1);
    expect(result.current.load).toBe(firstLoad);
  });

  it('keeps legacy LLM provider fields in save payload without hidden-field migration', async () => {
    const savedConfig = {
      ...sampleLlmConfig,
      items: sampleLlmConfig.items.map((item) => {
        if (item.key === 'LITELLM_MODEL') {
          return { ...item, value: 'qwen/qwen2.5' };
        }
        if (item.key === 'OPENAI_BASE_URL') {
          return { ...item, value: 'https://api.example.org/v1' };
        }
        if (item.key === 'OPENAI_VISION_MODEL') {
          return { ...item, value: 'gpt-4o-mini-vision' };
        }
        return item;
      }),
    };

    getConfig.mockResolvedValueOnce(sampleLlmConfig);
    getConfig.mockResolvedValueOnce(savedConfig);

    const { result } = renderHook(() => useSystemConfig());

    await act(async () => {
      await result.current.load();
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    act(() => {
      result.current.setDraftValue('LITELLM_MODEL', 'qwen/qwen2.5');
      result.current.setDraftValue('OPENAI_BASE_URL', 'https://api.example.org/v1');
      result.current.setDraftValue('OPENAI_VISION_MODEL', 'gpt-4o-mini-vision');
    });

    expect(result.current.hasDirty).toBe(true);

    await act(async () => {
      await result.current.save();
    });

    expect(validate).toHaveBeenCalledTimes(1);
    expect(validate).toHaveBeenCalledWith({
      items: [
        { key: 'LITELLM_MODEL', value: 'qwen/qwen2.5' },
        { key: 'OPENAI_BASE_URL', value: 'https://api.example.org/v1' },
        { key: 'OPENAI_VISION_MODEL', value: 'gpt-4o-mini-vision' },
      ],
    });
    expect(update).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith({
      configVersion: 'v1',
      maskToken: '******',
      reloadNow: true,
      items: [
        { key: 'LITELLM_MODEL', value: 'qwen/qwen2.5' },
        { key: 'OPENAI_BASE_URL', value: 'https://api.example.org/v1' },
        { key: 'OPENAI_VISION_MODEL', value: 'gpt-4o-mini-vision' },
      ],
    });
    expect(result.current.serverItems.find((item) => item.key === 'OPENAI_BASE_URL')?.value).toBe('https://api.example.org/v1');
    expect(result.current.serverItems.find((item) => item.key === 'OPENAI_VISION_MODEL')?.value).toBe('gpt-4o-mini-vision');
    expect(result.current.hasDirty).toBe(false);
    expect(result.current.dirtyCount).toBe(0);
  });

  it('only resets local draft edits without mutating server values for LLM fields', async () => {
    const current = sampleLlmConfig;
    getConfig.mockResolvedValueOnce(current);

    const { result } = renderHook(() => useSystemConfig());

    await act(async () => {
      await result.current.load();
    });

    act(() => {
      result.current.setDraftValue('LITELLM_MODEL', 'qwen/qwen2.5');
      result.current.setDraftValue('OPENAI_BASE_URL', 'https://api.example.org/v1');
    });

    expect(result.current.hasDirty).toBe(true);
    expect(result.current.dirtyCount).toBe(2);

    act(() => {
      result.current.resetDraft();
    });

    expect(result.current.hasDirty).toBe(false);
    expect(result.current.dirtyCount).toBe(0);

    await act(async () => {
      await result.current.save();
    });

    expect(validate).not.toHaveBeenCalled();
    expect(update).not.toHaveBeenCalled();
  });

  it('preserves unrelated runtime model fields when saving non-runtime config keys', async () => {
    const stockUpdatedConfig = {
      ...sampleLlmConfig,
      items: sampleLlmConfig.items.map((item) => {
        if (item.key === 'STOCK_LIST') {
          return { ...item, value: 'SH600000,SH600519' };
        }
        return item;
      }),
    };

    getConfig.mockResolvedValueOnce(sampleLlmConfig);
    getConfig.mockResolvedValueOnce(stockUpdatedConfig);

    const { result } = renderHook(() => useSystemConfig());

    await act(async () => {
      await result.current.load();
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'SH600000,SH600519');
    });

    expect(result.current.hasDirty).toBe(true);
    expect(result.current.dirtyCount).toBe(1);

    await act(async () => {
      await result.current.save();
    });

    expect(validate).toHaveBeenCalledTimes(1);
    expect(validate).toHaveBeenCalledWith({
      items: [{ key: 'STOCK_LIST', value: 'SH600000,SH600519' }],
    });
    expect(update).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith({
      configVersion: 'v1',
      maskToken: '******',
      reloadNow: true,
      items: [{ key: 'STOCK_LIST', value: 'SH600000,SH600519' }],
    });

    expect(result.current.serverItems.find((item) => item.key === 'LITELLM_MODEL')?.value).toBe('gpt-5.0');
    expect(result.current.serverItems.find((item) => item.key === 'OPENAI_BASE_URL')?.value).toBe('https://api.openai.com/v1');
    expect(result.current.serverItems.find((item) => item.key === 'OPENAI_VISION_MODEL')?.value).toBe('gpt-4o-vision');
    expect(result.current.hasDirty).toBe(false);
    expect(result.current.dirtyCount).toBe(0);
  });
});
