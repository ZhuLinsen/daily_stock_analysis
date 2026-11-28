import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { attachParsedApiError, createParsedApiError, type ParsedApiError } from '../../api/error';
import { SystemConfigConflictError, SystemConfigValidationError } from '../../api/systemConfig';
import { UiLanguageProvider, useUiLanguage } from '../../contexts/UiLanguageContext';
import type { ConfigValidationIssue } from '../../types/systemConfig';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';
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
    issues: ConfigValidationIssue[];
    parsedError: ParsedApiError;

    constructor(
      message = '',
      issues: ConfigValidationIssue[] = [],
      parsedError: ParsedApiError = {
        title: 'validation error',
        message: message || 'validation error',
        rawMessage: message || 'validation error',
        category: 'http_error',
      },
    ) {
      super(message);
      this.issues = issues;
      this.parsedError = parsedError;
    }
  },
}));

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

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
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
    document.documentElement.lang = '';
    getConfig.mockResolvedValue(sampleConfig);
    validate.mockResolvedValue({ valid: true, issues: [] });
    update.mockResolvedValue({ warnings: [] });
  });

  afterEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
    document.documentElement.lang = '';
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

  it('normalizes STOCK_LIST separators before saving', async () => {
    const savedConfig = {
      ...sampleConfig,
      items: sampleConfig.items.map((item) => (
        item.key === 'STOCK_LIST'
          ? { ...item, value: 'SH600000,SH600519,AAPL' }
          : item
      )),
    };

    getConfig.mockResolvedValueOnce(sampleConfig);
    getConfig.mockResolvedValueOnce(savedConfig);

    const { result } = renderHook(() => useSystemConfig());

    await act(async () => {
      await result.current.load();
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'SH600000，SH600519\nAAPL');
    });

    await act(async () => {
      await result.current.save();
    });

    expect(validate).toHaveBeenCalledWith({
      items: [{ key: 'STOCK_LIST', value: 'SH600000,SH600519,AAPL' }],
    });
    expect(update).toHaveBeenCalledWith({
      configVersion: 'v1',
      maskToken: '******',
      reloadNow: true,
      items: [{ key: 'STOCK_LIST', value: 'SH600000,SH600519,AAPL' }],
    });
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

  it('ignores stale load responses when newer load or refreshAfterExternalSave resolves first', async () => {
    const firstLoadDeferred = createDeferred<typeof sampleConfig>();
    const secondLoadDeferred = createDeferred<typeof sampleConfig>();
    const staleLoadDeferred = createDeferred<typeof sampleConfig>();
    const externalRefreshDeferred = createDeferred<typeof sampleConfig>();

    const newerConfig = {
      ...sampleConfig,
      configVersion: 'v2',
      items: [{ ...sampleConfig.items[0], value: 'SH600519' }],
    };
    const refreshedConfig = {
      ...sampleConfig,
      configVersion: 'v3',
      items: [{ ...sampleConfig.items[0], value: 'AAPL' }],
    };

    getConfig
      .mockReturnValueOnce(firstLoadDeferred.promise)
      .mockReturnValueOnce(secondLoadDeferred.promise)
      .mockReturnValueOnce(staleLoadDeferred.promise)
      .mockReturnValueOnce(externalRefreshDeferred.promise);

    const { result } = renderHook(() => useSystemConfig());

    let p1!: Promise<boolean>;
    let p2!: Promise<boolean>;
    act(() => {
      p1 = result.current.load();
      p2 = result.current.load();
    });

    expect(result.current.isLoading).toBe(true);

    let secondResult = false;
    await act(async () => {
      secondLoadDeferred.resolve(newerConfig);
      secondResult = await p2;
    });

    expect(secondResult).toBe(true);
    expect(result.current.configVersion).toBe('v2');
    expect(result.current.serverItems[0]?.value).toBe('SH600519');
    expect(result.current.isLoading).toBe(false);

    let firstResult = true;
    await act(async () => {
      firstLoadDeferred.resolve(sampleConfig);
      firstResult = await p1;
    });

    expect(firstResult).toBe(true);
    expect(result.current.configVersion).toBe('v2');
    expect(result.current.serverItems[0]?.value).toBe('SH600519');
    expect(result.current.isLoading).toBe(false);

    let p3!: Promise<boolean>;
    let pRefresh!: Promise<void>;
    act(() => {
      p3 = result.current.load();
      pRefresh = result.current.refreshAfterExternalSave(['STOCK_LIST']);
    });

    expect(result.current.isLoading).toBe(true);

    await act(async () => {
      externalRefreshDeferred.resolve(refreshedConfig);
      await pRefresh;
    });

    expect(result.current.configVersion).toBe('v3');
    expect(result.current.serverItems[0]?.value).toBe('AAPL');

    let thirdResult = false;
    await act(async () => {
      staleLoadDeferred.resolve(sampleConfig);
      thirdResult = await p3;
    });

    expect(thirdResult).toBe(true);
    expect(result.current.configVersion).toBe('v3');
    expect(result.current.serverItems[0]?.value).toBe('AAPL');
    expect(result.current.isLoading).toBe(false);
  });

  it('skips state updates and follow-up calls when unmounted mid-flight', async () => {
    const loadDeferred = createDeferred<typeof sampleConfig>();
    getConfig.mockReturnValueOnce(loadDeferred.promise);

    const firstHook = renderHook(() => useSystemConfig());
    let pendingLoad!: Promise<boolean>;
    act(() => {
      pendingLoad = firstHook.result.current.load();
    });

    firstHook.unmount();

    let loadOutcome = true;
    await act(async () => {
      loadDeferred.resolve(sampleConfig);
      loadOutcome = await pendingLoad;
    });
    expect(loadOutcome).toBe(false);

    const validateDeferred = createDeferred<{ valid: boolean; issues: ConfigValidationIssue[] }>();
    getConfig.mockResolvedValueOnce(sampleConfig);
    validate.mockReturnValueOnce(validateDeferred.promise);

    const secondHook = renderHook(() => useSystemConfig());
    await act(async () => {
      await secondHook.result.current.load();
    });

    act(() => {
      secondHook.result.current.setDraftValue('STOCK_LIST', 'SH600519');
    });

    let pendingSave!: Promise<{ success: boolean }>;
    act(() => {
      pendingSave = secondHook.result.current.save();
    });

    secondHook.unmount();

    let saveOutcome: { success: boolean } = { success: true };
    await act(async () => {
      validateDeferred.resolve({ valid: true, issues: [] });
      saveOutcome = await pendingSave;
    });

    expect(saveOutcome.success).toBe(false);
    expect(update).not.toHaveBeenCalled();
  });

  it('guards against concurrent save re-entry until the active save finishes', async () => {
    const savedConfigV2 = {
      ...sampleConfig,
      configVersion: 'v2',
      items: [{ ...sampleConfig.items[0], value: 'SH600519' }],
    };
    const savedConfigV3 = {
      ...sampleConfig,
      configVersion: 'v3',
      items: [{ ...sampleConfig.items[0], value: 'AAPL' }],
    };
    const validateDeferred = createDeferred<{ valid: boolean; issues: ConfigValidationIssue[] }>();

    getConfig
      .mockResolvedValueOnce(sampleConfig)
      .mockResolvedValueOnce(savedConfigV2)
      .mockResolvedValueOnce(savedConfigV3);
    validate
      .mockReturnValueOnce(validateDeferred.promise)
      .mockResolvedValueOnce({ valid: true, issues: [] });

    const { result } = renderHook(() => useSystemConfig());
    await act(async () => {
      await result.current.load();
    });

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'SH600519');
    });

    let firstSave!: Promise<{ success: boolean; message?: string }>;
    let secondSave!: Promise<{ success: boolean; message?: string }>;
    act(() => {
      firstSave = result.current.save();
      secondSave = result.current.save();
    });

    const secondOutcome = await secondSave;
    expect(secondOutcome).toEqual({ success: false, message: '配置保存进行中' });
    expect(validate).toHaveBeenCalledTimes(1);
    expect(update).not.toHaveBeenCalled();

    let firstOutcome!: { success: boolean; message?: string };
    await act(async () => {
      validateDeferred.resolve({ valid: true, issues: [] });
      firstOutcome = await firstSave;
    });

    expect(firstOutcome.success).toBe(true);
    expect(validate).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledTimes(1);
    expect(result.current.isSaving).toBe(false);

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'AAPL');
    });

    let thirdOutcome!: { success: boolean; message?: string };
    await act(async () => {
      thirdOutcome = await result.current.save();
    });

    expect(thirdOutcome.success).toBe(true);
    expect(validate).toHaveBeenCalledTimes(2);
    expect(update).toHaveBeenCalledTimes(2);
  });

  it('propagates structured conflict and validation errors into both saveError and toast', async () => {
    getConfig.mockResolvedValueOnce(sampleConfig);

    const { result } = renderHook(() => useSystemConfig());
    await act(async () => {
      await result.current.load();
    });

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'SH600519');
    });

    update.mockRejectedValueOnce(new SystemConfigConflictError('版本已过期'));
    await act(async () => {
      await result.current.save();
    });

    expect(result.current.saveError?.title).toBe('配置版本冲突');
    expect(result.current.saveError?.message).toContain('版本已过期');
    expect(result.current.saveError?.message).toContain('请先重新加载配置');
    expect(result.current.toast).toEqual({
      type: 'error',
      error: result.current.saveError,
    });
    expect(result.current.retryAction).toBe('save');

    const validationParsedError = createParsedApiError({
      title: '配置校验失败',
      message: '股票代码格式无效',
      rawMessage: '股票代码格式无效',
      status: 400,
      category: 'http_error',
    });
    const validationIssues: ConfigValidationIssue[] = [
      {
        key: 'STOCK_LIST',
        code: 'invalid_stock_code',
        message: '股票代码格式无效',
        severity: 'error',
      },
    ];
    update.mockRejectedValueOnce(
      new SystemConfigValidationError('股票代码格式无效', validationIssues, validationParsedError),
    );

    await act(async () => {
      await result.current.save();
    });

    expect(result.current.issueByKey.STOCK_LIST).toEqual(validationIssues);
    expect(result.current.saveError).toEqual(validationParsedError);
    expect(result.current.toast).toEqual({
      type: 'error',
      error: validationParsedError,
    });
  });

  it('replays explicit changedItems on retry after failure and clears them on manual edits', async () => {
    const refreshedAfterRetry = {
      ...sampleConfig,
      configVersion: 'v2',
    };

    getConfig
      .mockResolvedValueOnce(sampleConfig)
      .mockResolvedValueOnce(refreshedAfterRetry);

    const { result } = renderHook(() => useSystemConfig());
    await act(async () => {
      await result.current.load();
    });

    update.mockRejectedValueOnce(new Error('network glitch'));
    await act(async () => {
      const outcome = await result.current.save([{ key: 'SCHEDULE_ENABLED', value: 'true' }]);
      expect(outcome.success).toBe(false);
    });

    expect(result.current.retryAction).toBe('save');

    await act(async () => {
      await result.current.retry();
    });

    expect(validate).toHaveBeenNthCalledWith(2, {
      items: [{ key: 'SCHEDULE_ENABLED', value: 'true' }],
    });
    expect(update).toHaveBeenNthCalledWith(2, {
      configVersion: 'v1',
      maskToken: '******',
      reloadNow: true,
      items: [{ key: 'SCHEDULE_ENABLED', value: 'true' }],
    });
    expect(result.current.toast?.type).toBe('success');

    update.mockRejectedValueOnce(new Error('second glitch'));
    await act(async () => {
      await result.current.save([{ key: 'SCHEDULE_ENABLED', value: 'false' }]);
    });

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'AAPL');
    });

    getConfig.mockResolvedValueOnce({
      ...refreshedAfterRetry,
      configVersion: 'v3',
    });

    await act(async () => {
      await result.current.retry();
    });

    expect(update).toHaveBeenNthCalledWith(4, {
      configVersion: 'v2',
      maskToken: '******',
      reloadNow: true,
      items: [{ key: 'STOCK_LIST', value: 'AAPL' }],
    });
  });

  it('clears failed explicit save replay state after refreshAfterExternalSave so retry cannot clobber merged imports', async () => {
    const mergedConfig = {
      ...sampleConfig,
      configVersion: 'v2',
      items: [{ ...sampleConfig.items[0], value: 'SH600519,AAPL' }],
    };

    getConfig
      .mockResolvedValueOnce(sampleConfig)
      .mockResolvedValueOnce(mergedConfig);

    const { result } = renderHook(() => useSystemConfig());
    await act(async () => {
      await result.current.load();
    });

    update.mockRejectedValueOnce(new Error('network glitch'));
    await act(async () => {
      const outcome = await result.current.save([{ key: 'STOCK_LIST', value: 'SH600519' }]);
      expect(outcome.success).toBe(false);
    });
    expect(result.current.saveError).not.toBeNull();
    expect(result.current.retryAction).toBe('save');

    await act(async () => {
      await result.current.refreshAfterExternalSave(['STOCK_LIST']);
    });

    expect(result.current.configVersion).toBe('v2');
    expect(result.current.saveError).toBeNull();
    expect(result.current.retryAction).toBeNull();
    expect(result.current.serverItems[0]?.value).toBe('SH600519,AAPL');

    await act(async () => {
      await result.current.retry();
    });
    expect(update).toHaveBeenCalledTimes(1);
  });

  it('accumulates committedKeys across overlapping external refreshes so earlier committed fields do not stay dirty', async () => {
    const baseWithScreening = {
      ...sampleConfig,
      configVersion: 'v1',
      items: [
        sampleConfig.items[0],
        {
          key: 'SCREENING_ENABLED',
          value: 'false',
          rawValueExists: true,
          isMasked: false,
          schema: {
            key: 'SCREENING_ENABLED',
            category: 'system',
            dataType: 'boolean',
            uiControl: 'switch',
            isSensitive: false,
            isRequired: false,
            isEditable: true,
            options: [],
            validation: {},
            displayOrder: 2,
          },
        },
      ],
    };
    const refresh1 = createDeferred<typeof baseWithScreening>();
    const refresh2 = createDeferred<typeof baseWithScreening>();

    getConfig
      .mockResolvedValueOnce(baseWithScreening)
      .mockReturnValueOnce(refresh1.promise)
      .mockReturnValueOnce(refresh2.promise);

    const { result } = renderHook(() => useSystemConfig());
    await act(async () => {
      await result.current.load();
    });

    // User had an unsaved local edit on STOCK_LIST before external merge ran.
    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'SH600519');
    });

    let p1!: Promise<void>;
    let p2!: Promise<void>;
    act(() => {
      p1 = result.current.refreshAfterExternalSave(['STOCK_LIST']);
      p2 = result.current.refreshAfterExternalSave(['SCREENING_ENABLED']);
    });

    await act(async () => {
      refresh1.resolve({
        ...baseWithScreening,
        configVersion: 'v2',
        items: [
          { ...baseWithScreening.items[0], value: 'SH600519,AAPL' },
          baseWithScreening.items[1],
        ],
      });
      refresh2.resolve({
        ...baseWithScreening,
        configVersion: 'v3',
        items: [
          { ...baseWithScreening.items[0], value: 'SH600519,AAPL' },
          { ...baseWithScreening.items[1], value: 'true' },
        ],
      });
      await Promise.all([p1, p2]);
    });

    expect(result.current.configVersion).toBe('v3');
    expect(result.current.serverItems.find((i) => i.key === 'STOCK_LIST')?.value).toBe('SH600519,AAPL');
    expect(result.current.serverItems.find((i) => i.key === 'SCREENING_ENABLED')?.value).toBe('true');
    expect(result.current.hasDirty).toBe(false);
  });

  it('commits post-save config snapshot when a newer external refresh rejects', async () => {
    const postSaveDeferred = createDeferred<typeof sampleConfig>();
    const failedExternalDeferred = createDeferred<typeof sampleConfig>();

    getConfig
      .mockResolvedValueOnce(sampleConfig)
      .mockReturnValueOnce(postSaveDeferred.promise)
      .mockReturnValueOnce(failedExternalDeferred.promise);

    const { result } = renderHook(() => useSystemConfig());
    await act(async () => {
      await result.current.load();
    });

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'SH600519');
    });

    let savePromise!: Promise<{ success: boolean }>;
    act(() => {
      savePromise = result.current.save();
    });

    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));

    let extPromise!: Promise<void>;
    act(() => {
      extPromise = result.current.refreshAfterExternalSave(['OTHER']).catch(() => undefined);
    });

    await act(async () => {
      failedExternalDeferred.reject(new Error('500 external read failed'));
      await extPromise;
      postSaveDeferred.resolve({
        ...sampleConfig,
        configVersion: 'v2',
        items: [{ ...sampleConfig.items[0], value: 'SH600519' }],
      });
      const res = await savePromise;
      expect(res.success).toBe(true);
    });

    expect(result.current.configVersion).toBe('v2');
    expect(result.current.hasDirty).toBe(false);
    expect(result.current.serverItems[0]?.value).toBe('SH600519');
  });

  it('preserves local STOCK_LIST draft when a conflict refresh fails and a later unrelated external refresh succeeds (OR-COR-1e937175)', async () => {
    const configWithScreening = {
      ...sampleConfig,
      configVersion: 'v1',
      items: [
        sampleConfig.items[0],
        {
          key: 'SCREENING_ENABLED',
          value: 'true',
          rawValueExists: true,
          isMasked: false,
          schema: {
            key: 'SCREENING_ENABLED',
            category: 'system',
            dataType: 'boolean',
            uiControl: 'switch',
            isSensitive: false,
            isRequired: false,
            isEditable: true,
            options: [],
            validation: {},
            displayOrder: 2,
          },
        },
      ],
    };

    getConfig
      .mockResolvedValueOnce(configWithScreening)
      .mockRejectedValueOnce(new Error('500 conflict refresh failed'))
      .mockResolvedValueOnce({
        ...configWithScreening,
        configVersion: 'v2',
        items: [
          configWithScreening.items[0],
          { ...configWithScreening.items[1], value: 'false' },
        ],
      });

    const { result } = renderHook(() => useSystemConfig());
    await act(async () => {
      await result.current.load();
    });

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'SH600519,TSLA');
    });

    await act(async () => {
      await result.current.refreshAfterExternalSave([]).catch(() => undefined);
    });
    expect(result.current.getChangedItems()).toEqual([
      { key: 'STOCK_LIST', value: 'SH600519,TSLA' },
    ]);
    expect(result.current.hasDirty).toBe(true);

    await act(async () => {
      await result.current.refreshAfterExternalSave(['SCREENING_ENABLED']);
    });

    expect(result.current.getChangedItems()).toEqual([
      { key: 'STOCK_LIST', value: 'SH600519,TSLA' },
    ]);
    expect(result.current.hasDirty).toBe(true);
    expect(
      result.current.itemsByCategory.system?.find((item) => item.key === 'SCREENING_ENABLED')?.value,
    ).toBe('false');
  });

  it('clears STOCK_LIST dirty state when an external refresh supersedes save post-update getConfig (OR-COR-c582b495)', async () => {
    const baseWithScreening = {
      ...sampleConfig,
      configVersion: 'v1',
      items: [
        sampleConfig.items[0],
        {
          key: 'SCREENING_ENABLED',
          value: 'false',
          rawValueExists: true,
          isMasked: false,
          schema: {
            key: 'SCREENING_ENABLED',
            category: 'system',
            dataType: 'boolean',
            uiControl: 'switch',
            isSensitive: false,
            isRequired: false,
            isEditable: true,
            options: [],
            validation: {},
            displayOrder: 2,
          },
        },
      ],
    };

    const postSaveGet = createDeferred<typeof baseWithScreening>();
    const screeningGet = createDeferred<typeof baseWithScreening>();

    getConfig
      .mockResolvedValueOnce(baseWithScreening)
      .mockReturnValueOnce(postSaveGet.promise)
      .mockReturnValueOnce(screeningGet.promise);

    const { result } = renderHook(() => useSystemConfig());
    await act(async () => {
      await result.current.load();
    });

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'SH600519');
    });

    let savePromise!: Promise<{ success: boolean }>;
    act(() => {
      savePromise = result.current.save([{ key: 'STOCK_LIST', value: 'SH600519' }]);
    });

    await waitFor(() => expect(getConfig).toHaveBeenCalledTimes(2));

    let extPromise!: Promise<void>;
    act(() => {
      extPromise = result.current.refreshAfterExternalSave(['SCREENING_ENABLED']);
    });

    await waitFor(() => expect(getConfig).toHaveBeenCalledTimes(3));

    await act(async () => {
      const latestServerState = {
        ...baseWithScreening,
        configVersion: 'v3',
        items: [
          { ...baseWithScreening.items[0], value: 'SH600519,AAPL' },
          { ...baseWithScreening.items[1], value: 'true' },
        ],
      };
      screeningGet.resolve(latestServerState);
      await extPromise;
      postSaveGet.resolve(latestServerState);
      const outcome = await savePromise;
      expect(outcome.success).toBe(true);
    });

    expect(result.current.configVersion).toBe('v3');
    expect(result.current.serverItems.find((item) => item.key === 'STOCK_LIST')?.value).toBe('SH600519,AAPL');
    expect(
      result.current.itemsByCategory.base?.find((item) => item.key === 'STOCK_LIST')?.value,
    ).toBe('SH600519,AAPL');
    expect(result.current.hasDirty).toBe(false);
    expect(result.current.getChangedItems()).toEqual([]);
  });

  it('localizes save and validation feedback in English when active language is en', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    getConfig.mockResolvedValue(sampleConfig);

    const { result } = renderHook(() => useSystemConfig());
    await act(async () => {
      await result.current.load();
    });

    // No-op save without dirty changes
    let noOpOutcome!: { success: boolean; message?: string };
    await act(async () => {
      noOpOutcome = await result.current.save();
    });
    expect(noOpOutcome).toEqual({ success: true, message: 'No unsaved changes' });
    expect(result.current.toast).toEqual({ type: 'success', message: 'No unsaved changes.' });

    // Validation failure
    const validationIssues: ConfigValidationIssue[] = [
      { key: 'STOCK_LIST', code: 'invalid_stock_code', message: 'Invalid stock code', severity: 'error' },
    ];
    validate.mockResolvedValueOnce({ valid: false, issues: validationIssues });
    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'BAD_CODE');
    });
    let invalidOutcome!: { success: boolean; message?: string; issues?: ConfigValidationIssue[] };
    await act(async () => {
      invalidOutcome = await result.current.save();
    });
    expect(invalidOutcome).toEqual({
      success: false,
      message: 'Configuration validation failed',
      issues: validationIssues,
    });
    expect(result.current.saveError?.title).toBe('Configuration validation failed');
    expect(result.current.saveError?.message).toBe('Fix the form errors before saving.');

    // In-flight duplicate save guard + success toast with warnings
    const updateDeferred = createDeferred<{ warnings: string[] }>();
    update.mockImplementationOnce(() => updateDeferred.promise);
    let firstSave!: Promise<{ success: boolean; message?: string }>;
    let duplicateSave!: Promise<{ success: boolean; message?: string }>;
    act(() => {
      firstSave = result.current.save();
      duplicateSave = result.current.save();
    });
    expect(await duplicateSave).toEqual({
      success: false,
      message: 'Configuration save already in progress',
    });
    await act(async () => {
      updateDeferred.resolve({ warnings: ['warn A', 'warn B'] });
      await firstSave;
    });
    expect(result.current.toast).toEqual({
      type: 'success',
      message: 'Settings updated; Warnings: warn A; warn B',
    });

    // Conflict error formatting
    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'AAPL');
    });
    update.mockRejectedValueOnce(new SystemConfigConflictError('version stale'));
    let conflictOutcome!: { success: boolean; message?: string };
    await act(async () => {
      conflictOutcome = await result.current.save();
    });
    expect(conflictOutcome).toEqual({ success: false, message: 'Save failed' });
    expect(result.current.saveError?.title).toBe('Configuration version conflict');
    expect(result.current.saveError?.message).toBe('version stale. Please reload settings first.');
  });

  it('re-localizes validation and save toast when UI language switches mid-request and post-save (OR-COR-07f319b1)', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    getConfig.mockResolvedValue(sampleConfig);

    const { result } = renderHook(
      () => ({ config: useSystemConfig(), ui: useUiLanguage() }),
      { wrapper: UiLanguageProvider },
    );
    await act(async () => {
      await result.current.config.load();
    });

    const deferredValidate = createDeferred<{ valid: boolean; issues: ConfigValidationIssue[] }>();
    validate.mockImplementationOnce(() => deferredValidate.promise);
    act(() => {
      result.current.config.setDraftValue('STOCK_LIST', 'BAD_CODE');
    });

    let invalidSave!: Promise<{ success: boolean; message?: string; issues?: ConfigValidationIssue[] }>;
    act(() => {
      invalidSave = result.current.config.save();
    });
    act(() => {
      result.current.ui.setLanguage('en');
    });
    await act(async () => {
      deferredValidate.resolve({
        valid: false,
        issues: [{ key: 'STOCK_LIST', code: 'invalid', message: 'invalid', severity: 'error' }],
      });
      await invalidSave;
    });
    expect(result.current.config.saveError?.title).toBe('Configuration validation failed');

    act(() => {
      result.current.ui.setLanguage('zh');
      result.current.config.setDraftValue('STOCK_LIST', 'AAPL');
    });
    const deferredUpdate = createDeferred<{ warnings: string[] }>();
    update.mockImplementationOnce(() => deferredUpdate.promise);

    let okSave!: Promise<{ success: boolean; message?: string }>;
    act(() => {
      okSave = result.current.config.save();
    });
    act(() => {
      result.current.ui.setLanguage('en');
    });
    await act(async () => {
      deferredUpdate.resolve({ warnings: [] });
      await okSave;
    });
    expect(result.current.config.toast).toEqual({
      type: 'success',
      message: 'Settings updated',
    });

    act(() => {
      result.current.ui.setLanguage('zh');
    });
    expect(result.current.config.toast).toEqual({
      type: 'success',
      message: '配置已更新',
    });
  });

  it('re-localizes settled loadError, saveError, and error toast across zh/en switches (OR-COR-5a9e1d7c)', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');

    const loadNetworkError = new Error('Network Error') as Error & { code?: string };
    loadNetworkError.code = 'ERR_NETWORK';
    attachParsedApiError(loadNetworkError);
    getConfig.mockRejectedValueOnce(loadNetworkError);

    const { result } = renderHook(
      () => ({ config: useSystemConfig(), ui: useUiLanguage() }),
      { wrapper: UiLanguageProvider },
    );

    await act(async () => {
      await result.current.config.load();
    });
    expect(result.current.config.loadError?.title).toBe('无法连接到本地服务');

    act(() => {
      result.current.ui.setLanguage('en');
    });
    expect(result.current.config.loadError?.title).toBe('Cannot Connect to Local Service');
    expect(result.current.config.loadError?.message).not.toMatch(/[\u4e00-\u9fff]/);

    act(() => {
      result.current.ui.setLanguage('zh');
    });
    expect(result.current.config.loadError?.title).toBe('无法连接到本地服务');

    // Load succeeds, then test settled validation error switching zh -> en -> zh
    getConfig.mockResolvedValue(sampleConfig);
    await act(async () => {
      await result.current.config.load();
    });
    expect(result.current.config.loadError).toBeNull();

    validate.mockResolvedValueOnce({
      valid: false,
      issues: [{ key: 'STOCK_LIST', code: 'invalid', message: 'invalid', severity: 'error' }],
    });
    act(() => {
      result.current.config.setDraftValue('STOCK_LIST', 'BAD_CODE');
    });
    await act(async () => {
      await result.current.config.save();
    });
    expect(result.current.config.saveError?.title).toBe('配置校验未通过');
    expect(result.current.config.saveError?.message).toBe('请先修正表单错误后再保存。');

    act(() => {
      result.current.ui.setLanguage('en');
    });
    expect(result.current.config.saveError?.title).toBe('Configuration validation failed');
    expect(result.current.config.saveError?.message).toBe('Fix the form errors before saving.');

    // Settled conflict error + toast switching en -> zh -> en
    validate.mockResolvedValue({ valid: true, issues: [] });
    update.mockRejectedValueOnce(new SystemConfigConflictError('version stale'));
    await act(async () => {
      await result.current.config.save();
    });
    expect(result.current.config.saveError?.title).toBe('Configuration version conflict');
    expect(result.current.config.saveError?.message).toBe('version stale. Please reload settings first.');
    expect(result.current.config.toast).toMatchObject({
      type: 'error',
      error: {
        title: 'Configuration version conflict',
        message: 'version stale. Please reload settings first.',
      },
    });

    act(() => {
      result.current.ui.setLanguage('zh');
    });
    expect(result.current.config.saveError?.title).toBe('配置版本冲突');
    expect(result.current.config.saveError?.message).toBe('version stale，请先重新加载配置。');
    expect(result.current.config.toast).toMatchObject({
      type: 'error',
      error: {
        title: '配置版本冲突',
        message: 'version stale，请先重新加载配置。',
      },
    });

    // Settled network error on save (with toast) switching zh -> en
    const saveNetworkError = new Error('Network Error') as Error & { code?: string };
    saveNetworkError.code = 'ERR_NETWORK';
    attachParsedApiError(saveNetworkError);
    update.mockRejectedValueOnce(saveNetworkError);
    await act(async () => {
      await result.current.config.save();
    });
    expect(result.current.config.saveError?.title).toBe('无法连接到本地服务');
    expect(result.current.config.toast).toMatchObject({
      type: 'error',
      error: { title: '无法连接到本地服务' },
    });

    act(() => {
      result.current.ui.setLanguage('en');
    });
    expect(result.current.config.saveError?.title).toBe('Cannot Connect to Local Service');
    expect(result.current.config.toast).toMatchObject({
      type: 'error',
      error: { title: 'Cannot Connect to Local Service' },
    });
  });
});
