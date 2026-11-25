import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  const [maskToken, setMaskToken] = useState<string>('******');
  const [serverItems, setServerItems] = useState<SystemConfigItem[]>([]);
  const [llmModelProviders, setLlmModelProviders] = useState<string[]>([]);
  const [llmYamlActive, setLlmYamlActive] = useState<boolean | undefined>(undefined);

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
  const mountedRef = useRef(true);
  const nextConfigRequestSeqRef = useRef(0);
  const committedConfigSeqRef = useRef(0);
  const loadRequestIdRef = useRef(0);
  const saveInFlightRef = useRef(false);
  const lastFailedSaveItemsRef = useRef<SystemConfigUpdateItem[] | null>(null);
  const lastFailedSaveVersionRef = useRef<string | null>(null);
  const pendingCommittedKeysRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      nextConfigRequestSeqRef.current += 1;
      committedConfigSeqRef.current = nextConfigRequestSeqRef.current;
      loadRequestIdRef.current += 1;
    };
  }, []);

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
      setConfigVersion(version);
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
    [],
  );

  const load = useCallback(async (): Promise<boolean> => {
    const reqSeq = ++nextConfigRequestSeqRef.current;
    const loadId = ++loadRequestIdRef.current;
    lastFailedSaveItemsRef.current = null;
    lastFailedSaveVersionRef.current = null;
    setIsLoading(true);
    setLoadError(null);
    setRetryAction(null);

    try {
      const config = await systemConfigApi.getConfig(true);
      if (!mountedRef.current) {
        return false;
      }
      if (reqSeq < committedConfigSeqRef.current) {
        // A newer read already succeeded and committed fresher server state.
        return true;
      }
      committedConfigSeqRef.current = reqSeq;
      pendingCommittedKeysRef.current.clear();
      setSaveError(null);
      setLlmModelProviders(config.llmModelProviders || []);
      setLlmYamlActive(config.llmYamlActive);
      applyServerPayload(config.items, config.configVersion, config.maskToken);
      setToast(null);
      return true;
    } catch (error: unknown) {
      if (!mountedRef.current) {
        return false;
      }
      if (reqSeq < committedConfigSeqRef.current) {
        return true;
      }
      if (reqSeq === nextConfigRequestSeqRef.current) {
        setLoadError(getParsedApiError(error));
        setRetryAction('load');
      }
      return false;
    } finally {
      if (mountedRef.current && loadId === loadRequestIdRef.current) {
        setIsLoading(false);
      }
    }
  }, [applyServerPayload]);

  const resetDraft = useCallback(() => {
    lastFailedSaveItemsRef.current = null;
    lastFailedSaveVersionRef.current = null;
    pendingCommittedKeysRef.current.clear();
    const next: Record<string, string> = {};
    for (const item of serverItems) {
      next[item.key] = item.value;
    }
    setDraftValues(next);
    setValidationIssues([]);
    setSaveError(null);
  }, [serverItems]);

  const applyPartialUpdate = useCallback((updatedItems: Array<{ key: string; value: string }>) => {
    lastFailedSaveItemsRef.current = null;
    lastFailedSaveVersionRef.current = null;
    for (const item of updatedItems) {
      pendingCommittedKeysRef.current.delete(item.key);
    }
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
      for (const key of committedKeys) {
        pendingCommittedKeysRef.current.add(key);
      }
      const reqSeq = ++nextConfigRequestSeqRef.current;
      const config = await systemConfigApi.getConfig(true);
      if (!mountedRef.current || reqSeq < committedConfigSeqRef.current) {
        return;
      }
      committedConfigSeqRef.current = reqSeq;
      const mergedCommittedKeys = Array.from(pendingCommittedKeysRef.current);
      pendingCommittedKeysRef.current.clear();
      lastFailedSaveItemsRef.current = null;
      lastFailedSaveVersionRef.current = null;
      setSaveError(null);
      setRetryAction((prev) => (prev === 'save' ? null : prev));
      setLlmModelProviders(config.llmModelProviders || []);
      setLlmYamlActive(config.llmYamlActive);
      applyServerPayload(config.items, config.configVersion, config.maskToken, {
        preserveDirty: true,
        committedKeys: mergedCommittedKeys,
      });
    },
    [applyServerPayload],
  );

  const setDraftValue = useCallback((key: string, value: string) => {
    lastFailedSaveItemsRef.current = null;
    lastFailedSaveVersionRef.current = null;
    pendingCommittedKeysRef.current.delete(key);
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

  const save = useCallback(async (changedItems?: SystemConfigUpdateItem[]): Promise<SaveResult> => {
    if (saveInFlightRef.current) {
      return { success: false, message: '配置保存进行中' };
    }

    const explicitItems = changedItems ?? [];
    const resolvedChangedItems = explicitItems.length > 0 ? explicitItems : getChangedItems();

    if (!explicitItems.length && !hasDirty) {
      setToast({ type: 'success', message: '当前没有可保存的修改。' });
      return { success: true, message: '当前没有可保存的修改' };
    }

    if (!resolvedChangedItems.length) {
      setToast({ type: 'success', message: '当前没有可保存的修改。' });
      return { success: true, message: '当前没有可保存的修改' };
    }

    lastFailedSaveItemsRef.current = explicitItems.length > 0 ? [...explicitItems] : null;
    lastFailedSaveVersionRef.current = configVersion;
    saveInFlightRef.current = true;
    setIsSaving(true);
    setSaveError(null);
    setRetryAction(null);

    try {
      const validateResult = await systemConfigApi.validate({ items: resolvedChangedItems });
      if (!mountedRef.current) {
        return { success: false };
      }
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

      for (const item of resolvedChangedItems) {
        pendingCommittedKeysRef.current.add(item.key);
      }
      lastFailedSaveItemsRef.current = null;
      lastFailedSaveVersionRef.current = null;
      if (!mountedRef.current) {
        return { success: true };
      }

      const refreshSeq = ++nextConfigRequestSeqRef.current;
      const refreshed = await systemConfigApi.getConfig(true);
      if (!mountedRef.current) {
        return { success: true };
      }
      if (refreshSeq >= committedConfigSeqRef.current) {
        committedConfigSeqRef.current = refreshSeq;
        pendingCommittedKeysRef.current.clear();
        setLlmModelProviders(refreshed.llmModelProviders || []);
        setLlmYamlActive(refreshed.llmYamlActive);
        applyServerPayload(refreshed.items, refreshed.configVersion, refreshed.maskToken);
      }

      const warningText = updateResult.warnings?.length
        ? `；警告：${updateResult.warnings.join('；')}`
        : '';
      setToast({ type: 'success', message: `配置已更新${warningText}` });
      return { success: true };
    } catch (error: unknown) {
      if (!mountedRef.current) {
        return { success: false, message: '保存失败' };
      }

      let resolvedError: ParsedApiError;
      if (error instanceof SystemConfigValidationError) {
        setValidationIssues(error.issues);
        resolvedError = error.parsedError ?? getParsedApiError(error);
      } else if (error instanceof SystemConfigConflictError) {
        const baseParsedError = error.parsedError ?? getParsedApiError(error);
        resolvedError = createParsedApiError({
          title: '配置版本冲突',
          message: `${error.message}，请先重新加载配置。`,
          rawMessage: baseParsedError.rawMessage,
          status: baseParsedError.status,
          category: baseParsedError.category,
        });
      } else {
        resolvedError = getParsedApiError(error);
      }

      setSaveError(resolvedError);
      setToast({ type: 'error', error: resolvedError });
      setRetryAction('save');
      return { success: false, message: '保存失败' };
    } finally {
      saveInFlightRef.current = false;
      if (mountedRef.current) {
        setIsSaving(false);
      }
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
      const itemsToReplay =
        lastFailedSaveItemsRef.current && lastFailedSaveVersionRef.current === configVersion
          ? lastFailedSaveItemsRef.current
          : undefined;
      await save(itemsToReplay);
    }
  }, [configVersion, load, retryAction, save]);

  const clearToast = useCallback(() => {
    setToast(null);
  }, []);

  return {
    // Server state
    configVersion,
    maskToken,
    serverItems,
    llmYamlActive,
    llmModelProviders,
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
    getChangedItems,
    applyPartialUpdate,
    refreshAfterExternalSave,
  };
}
