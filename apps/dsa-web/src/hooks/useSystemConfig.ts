import { useCallback, useMemo, useState } from 'react';
import { systemConfigApi, SystemConfigConflictError, SystemConfigValidationError } from '../api/systemConfig';
import type {
  ConfigValidationIssue,
  SystemConfigCategorySchema,
  SystemConfigItem,
  SystemConfigUpdateItem,
} from '../types/systemConfig';

type ToastState = {
  type: 'success' | 'error';
  message: string;
} | null;

type RetryAction = 'load' | 'save' | null;

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

function getReadableError(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

function isMultiValueSchema(schema: SystemConfigItem['schema'] | undefined): boolean {
  const validation = (schema?.validation ?? {}) as Record<string, unknown>;
  return Boolean(validation.multiValue ?? validation.multi_value);
}

function normalizeFieldValue(value: string, schema: SystemConfigItem['schema'] | undefined): string {
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
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [retryAction, setRetryAction] = useState<RetryAction>(null);

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
    (items: SystemConfigItem[], version: string, token: string) => {
      const sorted = sortItemsByOrder(items);
      setServerItems(sorted);
      setConfigVersion(version);
      setMaskToken(token || '******');

      const draft: Record<string, string> = {};
      for (const item of sorted) {
        draft[item.key] = item.value;
      }
      setDraftValues(draft);

      const defaultCategory = sorted[0]?.schema?.category || 'base';
      setActiveCategory((current) => {
        const exists = sorted.some((item) => item.schema?.category === current);
        return exists ? current : defaultCategory;
      });
      setValidationIssues([]);
    },
    [],
  );

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    setRetryAction(null);

    try {
      const config = await systemConfigApi.getConfig(true);
      applyServerPayload(config.items, config.configVersion, config.maskToken);
      setToast(null);
    } catch (error: unknown) {
      setLoadError(getReadableError(error, '加载系统配置失败'));
      setRetryAction('load');
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

  const save = useCallback(async (): Promise<SaveResult> => {
    if (!hasDirty) {
      setToast({ type: 'success', message: '当前没有可保存的修改。' });
      return { success: true, message: '当前没有可保存的修改' };
    }

    setIsSaving(true);
    setSaveError(null);
    setRetryAction(null);

    const changedItems = getChangedItems();

    try {
      const validateResult = await systemConfigApi.validate({ items: changedItems });
      setValidationIssues(validateResult.issues || []);

      if (!validateResult.valid) {
        setSaveError('配置校验未通过，请先修正表单错误。');
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
        items: changedItems,
      });

      const refreshed = await systemConfigApi.getConfig(true);
      applyServerPayload(refreshed.items, refreshed.configVersion, refreshed.maskToken);

      const warningText = updateResult.warnings?.length
        ? `；警告：${updateResult.warnings.join('；')}`
        : '';
      setToast({ type: 'success', message: `配置已更新${warningText}` });
      return { success: true };
    } catch (error: unknown) {
      if (error instanceof SystemConfigValidationError) {
        setValidationIssues(error.issues);
        setSaveError(error.message || '配置校验失败');
      } else if (error instanceof SystemConfigConflictError) {
        setSaveError(`${error.message}，请先重新加载配置。`);
      } else {
        setSaveError(getReadableError(error, '保存配置失败'));
      }

      setToast({ type: 'error', message: '配置保存失败。' });
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

  return {
    // Server state
    configVersion,
    maskToken,
    serverItems,
    categories,
    itemsByCategory,
    issueByKey,

    // UI state
    activeCategory,
    setActiveCategory,
    hasDirty,
    dirtyCount: dirtyKeys.length,
    toast,
    clearToast,

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
  };
}
