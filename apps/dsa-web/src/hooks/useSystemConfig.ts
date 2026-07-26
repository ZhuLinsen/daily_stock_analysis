import { useCallback, useMemo, useRef, useState } from 'react';
import { createParsedApiError, getParsedApiError, type ParsedApiError } from '../api/error';
import { systemConfigApi, SystemConfigConflictError, SystemConfigValidationError } from '../api/systemConfig';
import type {
  ConfigValidationIssue,
  SystemConfigCategorySchema,
  SystemConfigItem,
  SystemConfigUpdateItem,
} from '../types/systemConfig';
import { serializeStockListValue } from '../utils/stockList';

type ToastState = {
  type: 'success';
  message: string;
} | {
  type: 'error';
  error: ParsedApiError;
} | null;

type RetryAction = 'load' | 'save' | null;

type SaveOptions = {
  /**
   * 联合保存路径(SettingsPage.handleSaveConfig)在普通草稿 save() 成功后立即触发
   * LLMChannelEditor.submit()。若第一段立刻 setToast success,第二段 channel 仍在
   * 进行或最终失败时,页面会同时显示第一段 success toast 与第二段错误提示,且页头
   * 全局 success 反馈与最终结果矛盾。
   *
   * silent:true 时本段不写 success toast,由调用方在两段都确认成功后统一发出。
   * error toast 仍由 save() 内部正常设置,确保失败路径反馈不丢失。
   *
   * issue #1948 (OR-COR-62780a0c)
   */
  silent?: boolean;
};

type SaveResult = {
  success: boolean;
  message?: string;
  issues?: ConfigValidationIssue[];
};

const CATEGORY_DISPLAY_ORDER: Record<string, number> = {
  base: 10,
  ai_model: 20,
  data_source: 30,
  notification: 40,
  system: 50,
  agent: 55,
  backtest: 60,
  uncategorized: 99,
};

function sortItemsByOrder(items: SystemConfigItem[]): SystemConfigItem[] {
  return [...items].sort((a, b) => {
    const left = a.schema?.displayOrder ?? 9999;
    const right = b.schema?.displayOrder ?? 9999;
    if (left !== right) {
      return left - right;
    }
    return a.key.localeCompare(b.key);
  });
}

function isMultiValueSchema(schema: SystemConfigItem['schema'] | undefined): boolean {
  const validation = (schema?.validation ?? {}) as Record<string, unknown>;
  return Boolean(validation.multiValue ?? validation.multi_value);
}

function normalizeFieldValue(value: string, schema: SystemConfigItem['schema'] | undefined): string {
  if ((schema?.key ?? '').toUpperCase() === 'STOCK_LIST') {
    return serializeStockListValue(value);
  }

  if (!isMultiValueSchema(schema)) {
    return value;
  }

  return value
    .split(',')
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0)
    .join(',');
}

export function useSystemConfig() {
  // Server state
  const [configVersion, setConfigVersion] = useState<string>('');
  // issue #1948 (OR-COR-d144d9cf): 同步镜像最新 configVersion 到 ref。
  // 联合保存路径(SettingsPage.handleSaveConfig)在普通草稿 save() 成功后立即触发
  // LLMChannelEditor.submit()。React state 异步更新,await save() 返回时 closure 中的
  // configVersion 仍是旧值,LLMChannelEditor 内 systemConfigApi.update 会拿到旧 version
  // 触发 409 冲突。SettingsPage 通过 latestConfigVersionRef.current 读取刷新后版本传给
  // LLMChannelEditor.submit({ configVersion }) 绕过这个问题。
  const latestConfigVersionRef = useRef<string>('');
  const setConfigVersionSync = useCallback((version: string) => {
    latestConfigVersionRef.current = version;
    setConfigVersion(version);
  }, []);
  const [maskToken, setMaskToken] = useState<string>('******');
  const [serverItems, setServerItems] = useState<SystemConfigItem[]>([]);

  // UI state
  const [draftValues, setDraftValues] = useState<Record<string, string>>({});
  const [activeCategory, setActiveCategory] = useState<string>('base');
  const [validationIssues, setValidationIssues] = useState<ConfigValidationIssue[]>([]);
  const [toast, setToast] = useState<ToastState>(null);

  // Request state
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [loadError, setLoadError] = useState<ParsedApiError | null>(null);
  const [saveError, setSaveError] = useState<ParsedApiError | null>(null);
  const [retryAction, setRetryAction] = useState<RetryAction>(null);
  const serverItemByKeyRef = useRef<Record<string, SystemConfigItem>>({});

  const mergedItems = useMemo(() => {
    return sortItemsByOrder(
      serverItems.map((item) => ({
        ...item,
        value: draftValues[item.key] ?? item.value,
      })),
    );
  }, [draftValues, serverItems]);

  const serverItemByKey = useMemo(() => {
    const map: Record<string, SystemConfigItem> = {};
    for (const item of serverItems) {
      map[item.key] = item;
    }
    serverItemByKeyRef.current = map;
    return map;
  }, [serverItems]);

  const categories = useMemo<SystemConfigCategorySchema[]>(() => {
    // Infer tabs from loaded config item schema metadata.
    const categoryMap = new Map<string, SystemConfigCategorySchema>();
    for (const item of mergedItems) {
      if (!item.schema) {
        continue;
      }

      const category = item.schema.category;
      if (!categoryMap.has(category)) {
        categoryMap.set(category, {
          category,
          title: category.replace('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase()),
          description: '',
          displayOrder: CATEGORY_DISPLAY_ORDER[category] ?? 999,
          fields: [],
        });
      }
      categoryMap.get(category)?.fields.push(item.schema);
    }

    return [...categoryMap.values()].sort((a, b) => a.displayOrder - b.displayOrder);
  }, [mergedItems]);

  const itemsByCategory = useMemo(() => {
    const map: Record<string, SystemConfigItem[]> = {};
    for (const item of mergedItems) {
      const category = item.schema?.category ?? 'uncategorized';
      if (!map[category]) {
        map[category] = [];
      }
      map[category].push(item);
    }
    return map;
  }, [mergedItems]);

  // issue #1948 — key -> category 反查表,给页面层汇总 dirtyCountByCategory 用。
  // 包括 merged items(已 schema 化)+ LLMChannelEditor 渠道草稿新增的 key(若 schema 已注册)。
  // 未注册的 key 落到 'uncategorized' (与 itemsByCategory 行为一致)。
  const keyToCategory = useMemo<Record<string, string>>(() => {
    const map: Record<string, string> = {};
    for (const item of mergedItems) {
      map[item.key] = item.schema?.category ?? 'uncategorized';
    }
    return map;
  }, [mergedItems]);

  const dirtyKeys = useMemo(() => {
    const keys: string[] = [];
    for (const item of serverItems) {
      const draftRaw = draftValues[item.key];
      if (draftRaw === undefined) {
        continue;
      }

      const normalizedDraft = normalizeFieldValue(draftRaw, item.schema);
      const normalizedCurrent = normalizeFieldValue(item.value, item.schema);
      if (normalizedDraft !== normalizedCurrent) {
        keys.push(item.key);
      }
    }
    return keys;
  }, [draftValues, serverItems]);

  const hasDirty = dirtyKeys.length > 0;

  const issueByKey = useMemo(() => {
    const map: Record<string, ConfigValidationIssue[]> = {};
    for (const issue of validationIssues) {
      if (!map[issue.key]) {
        map[issue.key] = [];
      }
      map[issue.key].push(issue);
    }
    return map;
  }, [validationIssues]);

  const applyServerPayload = useCallback(
    (
      items: SystemConfigItem[],
      version: string,
      token: string,
      options?: { preserveDirty?: boolean; committedKeys?: string[] },
    ) => {
      const sorted = sortItemsByOrder(items);
      const previousServerMap = serverItemByKeyRef.current;
      const committedKeys = new Set(options?.committedKeys ?? []);
      const preserveDirty = options?.preserveDirty ?? false;

      setServerItems(sorted);
      setConfigVersionSync(version);
      setMaskToken(token || '******');

      setDraftValues((prevDraft) => {
        const nextDraft: Record<string, string> = {};
        for (const item of sorted) {
          if (committedKeys.has(item.key)) {
            nextDraft[item.key] = item.value;
            continue;
          }

          if (preserveDirty) {
            const previousServerValue = previousServerMap[item.key]?.value;
            const hasDraft = prevDraft[item.key] !== undefined;
            const wasDirty = hasDraft && prevDraft[item.key] !== previousServerValue;
            nextDraft[item.key] = wasDirty ? prevDraft[item.key] : item.value;
            continue;
          }

          nextDraft[item.key] = item.value;
        }
        return nextDraft;
      });

      const defaultCategory = sorted[0]?.schema?.category || 'base';
      setActiveCategory((current) => {
        const exists = sorted.some((item) => item.schema?.category === current);
        return exists ? current : defaultCategory;
      });
      setValidationIssues([]);
    },
    [setConfigVersionSync],
  );

  const load = useCallback(async (): Promise<boolean> => {
    setIsLoading(true);
    setLoadError(null);
    setRetryAction(null);

    try {
      const config = await systemConfigApi.getConfig(true);
      applyServerPayload(config.items, config.configVersion, config.maskToken);
      setToast(null);
      return true;
    } catch (error: unknown) {
      setLoadError(getParsedApiError(error));
      setRetryAction('load');
      return false;
    } finally {
      setIsLoading(false);
    }
  }, [applyServerPayload]);

  const resetDraft = useCallback(() => {
    const next: Record<string, string> = {};
    for (const item of serverItems) {
      next[item.key] = item.value;
    }
    setDraftValues(next);
    setValidationIssues([]);
    setSaveError(null);
  }, [serverItems]);

  const applyPartialUpdate = useCallback((updatedItems: Array<{ key: string; value: string }>) => {
    setDraftValues((prevDraft) => {
      const nextDraft = { ...prevDraft };
      for (const item of updatedItems) {
        nextDraft[item.key] = item.value;
      }
      return nextDraft;
    });
  }, []);

  const refreshAfterExternalSave = useCallback(
    async (committedKeys: string[]) => {
      const config = await systemConfigApi.getConfig(true);
      applyServerPayload(config.items, config.configVersion, config.maskToken, {
        preserveDirty: true,
        committedKeys,
      });
    },
    [applyServerPayload],
  );

  const setDraftValue = useCallback((key: string, value: string) => {
    setDraftValues((previous) => ({
      ...previous,
      [key]: value,
    }));
  }, []);

  const getChangedItems = useCallback((): SystemConfigUpdateItem[] => {
    return dirtyKeys
      .map((key) => {
        const serverItem = serverItemByKey[key];
        const normalizedValue = normalizeFieldValue(draftValues[key] ?? '', serverItem?.schema);
        return {
          key,
          value: normalizedValue,
        };
      })
      .filter((item) => {
        const serverItem = serverItemByKey[item.key];
        const normalizedCurrent = normalizeFieldValue(serverItem?.value ?? '', serverItem?.schema);
        return item.value !== normalizedCurrent;
      });
  }, [dirtyKeys, draftValues, serverItemByKey]);

  const save = useCallback(async (changedItems?: SystemConfigUpdateItem[], opts?: SaveOptions): Promise<SaveResult> => {
    const explicitItems = changedItems ?? [];
    const resolvedChangedItems = explicitItems.length > 0 ? explicitItems : getChangedItems();
    const silent = opts?.silent === true;

    if (!explicitItems.length && !hasDirty) {
      if (!silent) {
        setToast({ type: 'success', message: '当前没有可保存的修改。' });
      }
      return { success: true, message: '当前没有可保存的修改' };
    }

    if (!resolvedChangedItems.length) {
      if (!silent) {
        setToast({ type: 'success', message: '当前没有可保存的修改。' });
      }
      return { success: true, message: '当前没有可保存的修改' };
    }

    setIsSaving(true);
    setSaveError(null);
    setRetryAction(null);

    try {
      const validateResult = await systemConfigApi.validate({ items: resolvedChangedItems });
      setValidationIssues(validateResult.issues || []);

      if (!validateResult.valid) {
        setSaveError(createParsedApiError({
          title: '配置校验未通过',
          message: '请先修正表单错误后再保存。',
          rawMessage: '配置校验未通过，请先修正表单错误。',
          category: 'http_error',
        }));
        setRetryAction('save');
        return {
          success: false,
          message: '配置校验未通过',
          issues: validateResult.issues,
        };
      }

      const updateResult = await systemConfigApi.update({
        configVersion,
        maskToken,
        reloadNow: true,
        items: resolvedChangedItems,
      });

      const refreshed = await systemConfigApi.getConfig(true);
      applyServerPayload(refreshed.items, refreshed.configVersion, refreshed.maskToken);

      const warningText = updateResult.warnings?.length
        ? `；警告：${updateResult.warnings.join('；')}`
        : '';
      // OR-COR-62780a0c: 联合保存路径(silent:true)不在第一段成功时立刻发 success
      // toast——LLMChannelEditor.submit() 仍在进行,若第二段失败,页面会同时留有
      // 第一段 success toast 与第二段错误提示。普通段 error toast 仍由下方 catch
      // 块设置,失败反馈不丢失。SettingsPage.handleSaveConfig 在两段都成功后统一
      // 调 setSuccessToast 发出页面级 success toast。
      if (!silent) {
        setToast({ type: 'success', message: `配置已更新${warningText}` });
      }
      return { success: true };
    } catch (error: unknown) {
      if (error instanceof SystemConfigValidationError) {
        setValidationIssues(error.issues);
        setSaveError(error.parsedError);
      } else if (error instanceof SystemConfigConflictError) {
        setSaveError(createParsedApiError({
          title: '配置版本冲突',
          message: `${error.message}，请先重新加载配置。`,
          rawMessage: error.parsedError.rawMessage,
          status: error.parsedError.status,
          category: error.parsedError.category,
        }));
      } else {
        setSaveError(getParsedApiError(error));
      }

      setToast({ type: 'error', error: getParsedApiError(error) });
      setRetryAction('save');
      return { success: false, message: '保存失败' };
    } finally {
      setIsSaving(false);
    }
  }, [
    applyServerPayload,
    configVersion,
    getChangedItems,
    hasDirty,
    maskToken,
  ]);

  const retry = useCallback(async () => {
    if (retryAction === 'load') {
      await load();
      return;
    }
    if (retryAction === 'save') {
      await save();
    }
  }, [load, retryAction, save]);

  const clearToast = useCallback(() => {
    setToast(null);
  }, []);

  // OR-COR-62780a0c: 联合保存路径使用 silent:true 跳过 save() 内置 success toast,
  // 在两段都确认成功后由 SettingsPage.handleSaveConfig 调用本方法统一发出页面级
  // success toast,避免第一段 toast 与第二段结果矛盾。error 反馈仍由 save() 内部
  // catch 块设置避免丢失。
  const showSuccessToast = useCallback((message: string) => {
    setToast({ type: 'success', message });
  }, []);

  const showErrorToast = useCallback((error: ParsedApiError) => {
    setToast({ type: 'error', error });
  }, []);

  return {
    // Server state
    configVersion,
    latestConfigVersionRef,
    maskToken,
    serverItems,
    categories,
    itemsByCategory,
    keyToCategory,
    issueByKey,

    // UI state
    activeCategory,
    setActiveCategory,
    hasDirty,
    dirtyCount: dirtyKeys.length,
    toast,
    clearToast,
    showSuccessToast,
    showErrorToast,

    // Request state
    isLoading,
    isSaving,
    loadError,
    saveError,
    retryAction,

    // Actions
    load,
    retry,
    save,
    resetDraft,
    setDraftValue,
    getChangedItems,
    applyPartialUpdate,
    refreshAfterExternalSave,
  };
}
