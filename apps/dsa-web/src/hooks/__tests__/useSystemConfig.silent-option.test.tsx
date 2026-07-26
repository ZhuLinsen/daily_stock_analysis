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

const updatedConfig = {
  ...sampleConfig,
  items: sampleConfig.items.map((item) =>
    item.key === 'STOCK_LIST'
      ? { ...item, value: 'SH600000,SH600519' }
      : item,
  ),
};

describe('useSystemConfig save silent option (OR-COR-62780a0c)', () => {
  beforeEach(() => {
    getConfig.mockReset();
    validate.mockReset();
    update.mockReset();
  });

  it('emits success toast when save() succeeds without silent flag', async () => {
    getConfig.mockResolvedValueOnce(sampleConfig);
    getConfig.mockResolvedValueOnce(updatedConfig);
    validate.mockResolvedValueOnce({ valid: true, issues: [] });
    update.mockResolvedValueOnce({ warnings: [] });

    const { result } = renderHook(() => useSystemConfig());

    await act(async () => {
      await result.current.load();
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'SH600000,SH600519');
    });

    expect(result.current.hasDirty).toBe(true);

    let saveResult: { success: boolean } = { success: false };
    await act(async () => {
      saveResult = await result.current.save();
    });

    expect(saveResult.success).toBe(true);
    expect(result.current.toast).not.toBeNull();
    expect(result.current.toast?.type).toBe('success');
    expect(result.current.toast?.message).toContain('配置已更新');
  });

  it('suppresses success toast when save() called with silent:true', async () => {
    getConfig.mockResolvedValueOnce(sampleConfig);
    getConfig.mockResolvedValueOnce(updatedConfig);
    validate.mockResolvedValueOnce({ valid: true, issues: [] });
    update.mockResolvedValueOnce({ warnings: [] });

    const { result } = renderHook(() => useSystemConfig());

    await act(async () => {
      await result.current.load();
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'SH600000,SH600519');
    });

    expect(result.current.hasDirty).toBe(true);

    let saveResult: { success: boolean } = { success: false };
    await act(async () => {
      saveResult = await result.current.save(undefined, { silent: true });
    });

    expect(saveResult.success).toBe(true);
    // 关键断言:silent:true 时本段不发出 success toast——LLMChannelEditor.submit()
    // 仍在进行,若第二段失败,不会留下第一段与最终结果矛盾的 success toast。
    expect(result.current.toast).toBeNull();
  });

  it('suppresses no-op success toast when save() called with silent:true and no dirty drafts', async () => {
    getConfig.mockResolvedValueOnce(sampleConfig);

    const { result } = renderHook(() => useSystemConfig());

    await act(async () => {
      await result.current.load();
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    let saveResult: { success: boolean; message?: string } = { success: false };
    await act(async () => {
      saveResult = await result.current.save(undefined, { silent: true });
    });

    expect(saveResult.success).toBe(true);
    expect(validate).not.toHaveBeenCalled();
    expect(update).not.toHaveBeenCalled();
    // silent:true 抑制 no-op success toast("当前没有可保存的修改")。
    expect(result.current.toast).toBeNull();
  });

  it('still emits error toast when API fails even with silent:true', async () => {
    getConfig.mockResolvedValueOnce(sampleConfig);
    validate.mockResolvedValueOnce({ valid: true, issues: [] });
    update.mockRejectedValueOnce(new Error('network down'));

    const { result } = renderHook(() => useSystemConfig());

    await act(async () => {
      await result.current.load();
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'SH600000,SH600519');
    });

    let saveResult: { success: boolean } = { success: true };
    await act(async () => {
      saveResult = await result.current.save(undefined, { silent: true });
    });

    expect(saveResult.success).toBe(false);
    // silent 只抑制 success toast;error 反馈不丢失,与 catch 块无条件 setToast(type:error) 一致。
    expect(result.current.toast).not.toBeNull();
    expect(result.current.toast?.type).toBe('error');
  });

  it('showSuccessToast writes success toast for caller-driven unified feedback', async () => {
    getConfig.mockResolvedValueOnce(sampleConfig);
    getConfig.mockResolvedValueOnce(updatedConfig);
    validate.mockResolvedValueOnce({ valid: true, issues: [] });
    update.mockResolvedValueOnce({ warnings: [] });

    const { result } = renderHook(() => useSystemConfig());

    await act(async () => {
      await result.current.load();
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.setDraftValue('STOCK_LIST', 'SH600000,SH600519');
    });

    await act(async () => {
      await result.current.save(undefined, { silent: true });
    });

    // silent:true 路径下 save() 未发 success toast,由 SettingsPage.handleSaveConfig
    // 在两段都确认成功后调用 showSuccessToast 统一发页面级 success toast。
    expect(result.current.toast).toBeNull();

    act(() => {
      result.current.showSuccessToast('配置已更新');
    });

    expect(result.current.toast).not.toBeNull();
    expect(result.current.toast?.type).toBe('success');
    expect(result.current.toast?.message).toBe('配置已更新');
  });

  it('showErrorToast writes error toast for caller-driven unified failure feedback', async () => {
    getConfig.mockResolvedValueOnce(sampleConfig);

    const { result } = renderHook(() => useSystemConfig());

    await act(async () => {
      await result.current.load();
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.toast).toBeNull();

    act(() => {
      result.current.showErrorToast({
        title: 'LLM 渠道提交失败',
        message: '请重试',
        rawMessage: 'LLM 渠道提交失败，请重试',
        category: 'http_error',
      });
    });

    expect(result.current.toast).not.toBeNull();
    expect(result.current.toast?.type).toBe('error');
  });
});
