import type React from 'react';
import { useCallback, useRef, useState } from 'react';
import { getParsedApiError } from '../../api/error';
import { stocksApi, type ExtractItem } from '../../api/stocks';
import { systemConfigApi, SystemConfigConflictError } from '../../api/systemConfig';
import { Badge, Button, InlineAlert } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiLanguage } from '../../i18n/uiText';

const IMG_EXT = ['.jpg', '.jpeg', '.png', '.webp', '.gif'];
const IMG_MAX = 5 * 1024 * 1024; // 5MB
const FILE_MAX = 2 * 1024 * 1024; // 2MB
const TEXT_MAX = 100 * 1024; // 100KB

interface IntelligentImportProps {
  stockListValue: string;
  configVersion: string;
  maskToken: string;
  onMerged: (newValue: string) => void | Promise<void>;
  disabled?: boolean;
}

type ItemWithChecked = ExtractItem & { id: string; checked: boolean };

function getConfidenceMeta(confidence: 'high' | 'medium' | 'low', language: UiLanguage) {
  if (confidence === 'high') {
    return { label: language === 'en' ? 'High' : '高', badge: 'success' as const };
  }
  if (confidence === 'low') {
    return { label: language === 'en' ? 'Low' : '低', badge: 'warning' as const };
  }
  return { label: language === 'en' ? 'Medium' : '中', badge: 'default' as const };
}

function normalizeConfidence(confidence?: string | null): 'high' | 'medium' | 'low' {
  if (confidence === 'high' || confidence === 'low' || confidence === 'medium') {
    return confidence;
  }
  return 'medium';
}

function mergeItems(
  prev: ItemWithChecked[],
  newItems: ExtractItem[]
): ItemWithChecked[] {
  const byCode = new Map<string, ItemWithChecked>();
  const confOrder: Record<'high' | 'medium' | 'low', number> = {
    high: 3,
    medium: 2,
    low: 1,
  };
  const failed: ItemWithChecked[] = [];
  for (const p of prev) {
    if (p.code) {
      byCode.set(p.code, p);
    } else {
      failed.push(p);
    }
  }
  for (const it of newItems) {
    const normalizedConfidence = normalizeConfidence(it.confidence);
    if (it.code) {
      const existing = byCode.get(it.code);
      if (!existing) {
        byCode.set(it.code, {
          ...it,
          confidence: normalizedConfidence,
          id: `${it.code}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
          checked: normalizedConfidence === 'high',
        });
      } else {
        const existingConfidence = normalizeConfidence(existing.confidence);
        const shouldUpgradeConfidence = confOrder[normalizedConfidence] > confOrder[existingConfidence];
        const shouldFillName = !existing.name && !!it.name;

        if (shouldUpgradeConfidence || shouldFillName) {
          byCode.set(it.code, {
            ...existing,
            name: it.name || existing.name,
            confidence: shouldUpgradeConfidence ? normalizedConfidence : existingConfidence,
            checked: shouldUpgradeConfidence
              ? (normalizedConfidence === 'high' ? true : existing.checked)
              : existing.checked,
          });
        }
      }
    } else {
      failed.push({
        ...it,
        confidence: normalizedConfidence,
        id: `fail-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        checked: false,
      });
    }
  }
  return [...byCode.values(), ...failed];
}

export const IntelligentImport: React.FC<IntelligentImportProps> = ({
  stockListValue,
  configVersion,
  maskToken,
  onMerged,
  disabled,
}) => {
  const { language, t } = useUiLanguage();
  const [items, setItems] = useState<ItemWithChecked[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isMerging, setIsMerging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [pasteText, setPasteText] = useState('');
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const dataFileInputRef = useRef<HTMLInputElement | null>(null);

  const parseCurrentList = useCallback(() => {
    return stockListValue
      .split(',')
      .map((c) => c.trim())
      .filter(Boolean);
  }, [stockListValue]);

  const addItems = useCallback((newItems: ExtractItem[]) => {
    setItems((prev) => mergeItems(prev, newItems));
  }, []);

  const handleImageFile = useCallback(
    async (file: File) => {
      const ext = '.' + (file.name.split('.').pop() ?? '').toLowerCase();
      if (!IMG_EXT.includes(ext)) {
        setError(t('settings.intelligentImportImageTypeError'));
        return;
      }
      if (file.size > IMG_MAX) {
        setError(t('settings.intelligentImportImageSizeError'));
        return;
      }
      setError(null);
      setIsLoading(true);
      try {
        const res = await stocksApi.extractFromImage(file);
        addItems(res.items ?? res.codes.map((c) => ({ code: c, name: null, confidence: 'medium' })));
      } catch (e) {
        const parsed = getParsedApiError(e);
        const err = e && typeof e === 'object' ? (e as { response?: { status?: number }; code?: string }) : null;
        let fallback = t('settings.intelligentImportRecognitionFailed');
        if (err?.response?.status === 429) fallback = t('settings.intelligentImportRateLimited');
        else if (err?.code === 'ECONNABORTED') fallback = t('settings.intelligentImportTimeout');
        setError(parsed.message || fallback);
      } finally {
        setIsLoading(false);
      }
    },
    [addItems, t],
  );

  const handleDataFile = useCallback(
    async (file: File) => {
      if (file.size > FILE_MAX) {
        setError(t('settings.intelligentImportFileSizeError'));
        return;
      }
      setError(null);
      setIsLoading(true);
      try {
        const res = await stocksApi.parseImport(file);
        addItems(res.items ?? res.codes.map((c) => ({ code: c, name: null, confidence: 'medium' })));
      } catch (e) {
        const parsed = getParsedApiError(e);
        setError(parsed.message || t('settings.intelligentImportParseFailed'));
      } finally {
        setIsLoading(false);
      }
    },
    [addItems, t],
  );

  const handlePasteParse = useCallback(() => {
    const trimmedText = pasteText.trim();
    if (!trimmedText) return;
    if (new Blob([trimmedText]).size > TEXT_MAX) {
      setError(t('settings.intelligentImportTextSizeError'));
      return;
    }
    setError(null);
    setIsLoading(true);
    stocksApi
      .parseImport(undefined, trimmedText)
      .then((res) => {
        addItems(res.items ?? res.codes.map((c) => ({ code: c, name: null, confidence: 'medium' })));
        setPasteText('');
      })
      .catch((e) => {
        const parsed = getParsedApiError(e);
        setError(parsed.message || t('settings.intelligentImportParseFailed'));
      })
      .finally(() => setIsLoading(false));
  }, [pasteText, addItems, t]);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (disabled || isLoading) return;
      const f = e.dataTransfer?.files?.[0];
      if (!f) return;
      const ext = '.' + (f.name.split('.').pop() ?? '').toLowerCase();
      if (IMG_EXT.includes(ext)) void handleImageFile(f);
      else void handleDataFile(f);
    },
    [disabled, isLoading, handleImageFile, handleDataFile],
  );

  const onImageInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      if (f) void handleImageFile(f);
      e.target.value = '';
    },
    [handleImageFile],
  );

  const onDataFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      if (f) void handleDataFile(f);
      e.target.value = '';
    },
    [handleDataFile],
  );

  const openFilePicker = useCallback((inputRef: React.RefObject<HTMLInputElement | null>) => {
    if (disabled || isLoading) {
      return;
    }
    inputRef.current?.click();
  }, [disabled, isLoading]);

  const toggleChecked = useCallback((id: string) => {
    setItems((prev) => prev.map((p) => (p.id === id && p.code ? { ...p, checked: !p.checked } : p)));
  }, []);

  const toggleAll = useCallback((checked: boolean) => {
    setItems((prev) => prev.map((p) => (p.code ? { ...p, checked } : p)));
  }, []);

  const removeItem = useCallback((id: string) => {
    setItems((prev) => prev.filter((p) => p.id !== id));
  }, []);

  const clearAll = useCallback(() => {
    setItems([]);
    setPasteText('');
    setError(null);
  }, []);

  const mergeToWatchlist = useCallback(async () => {
    const toMerge = items.filter((i) => i.checked && i.code).map((i) => i.code!);
    if (toMerge.length === 0) return;
    if (!configVersion) {
      setError(t('settings.intelligentImportLoadConfigFirst'));
      return;
    }
    const current = parseCurrentList();
    const merged = [...new Set([...current, ...toMerge])];
    const value = merged.join(',');

    setIsMerging(true);
    setError(null);
    try {
      await systemConfigApi.update({
        configVersion,
        maskToken,
        reloadNow: true,
        items: [{ key: 'STOCK_LIST', value }],
      });
      setItems([]);
      setPasteText('');
      await onMerged(value);
    } catch (e) {
      if (e instanceof SystemConfigConflictError) {
        await onMerged(value);
        setError(t('settings.intelligentImportConfigUpdated'));
      } else {
        setError(e instanceof Error ? e.message : t('settings.intelligentImportMergeFailed'));
      }
    } finally {
      setIsMerging(false);
    }
  }, [items, configVersion, maskToken, onMerged, parseCurrentList, t]);

  const validCount = items.filter((i) => i.code).length;
  const checkedCount = items.filter((i) => i.checked && i.code).length;

  return (
    <div className="space-y-4">
      <div className="settings-surface-panel settings-border-strong rounded-xl border p-4 shadow-soft-card">
        <p className="text-sm font-medium text-foreground">{t('settings.intelligentImportSupportedInputs')}</p>
        <p className="mt-1 text-xs leading-5 text-secondary-text">
          {t('settings.intelligentImportHint')}
        </p>
      </div>

      <div
        onDrop={onDrop}
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={(e) => { e.preventDefault(); setIsDragging(false); }}
        className={`flex min-h-[96px] flex-col gap-4 rounded-xl border border-dashed  p-4 transition-colors ${
          isDragging ? 'settings-drag-active' : 'settings-border-strong settings-surface-overlay-soft'
        } ${disabled || isLoading ? 'cursor-not-allowed opacity-60' : ''}`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="settings-secondary"
            disabled={disabled || isLoading}
            onClick={() => openFilePicker(imageInputRef)}
          >
            {t('settings.intelligentImportChooseImage')}
          </Button>
          <input
            ref={imageInputRef}
            type="file"
            accept=".jpg,.jpeg,.png,.webp,.gif"
            className="hidden"
            onChange={onImageInput}
            disabled={disabled || isLoading}
          />
          <Button
            type="button"
            variant="settings-secondary"
            disabled={disabled || isLoading}
            onClick={() => openFilePicker(dataFileInputRef)}
          >
            {t('settings.intelligentImportChooseFile')}
          </Button>
          <input
            ref={dataFileInputRef}
            type="file"
            accept=".csv,.xlsx,.txt"
            className="hidden"
            onChange={onDataFileInput}
            disabled={disabled || isLoading}
          />
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <textarea
            placeholder={t('settings.intelligentImportPastePlaceholder')}
            className="input-surface settings-surface-strong settings-border-strong min-h-[72px] w-full rounded-xl border px-3 py-2 text-sm text-foreground shadow-none transition-colors placeholder:text-muted-text focus:outline-none"
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            disabled={disabled || isLoading}
          />
          <Button
            type="button"
            variant="settings-secondary"
            className="shrink-0 sm:self-start"
            onClick={handlePasteParse}
            disabled={disabled || isLoading || !pasteText.trim()}
          >
            {t('settings.intelligentImportParse')}
          </Button>
        </div>
      </div>

      {isLoading && <p className="text-sm text-secondary-text">{t('common.processing')}</p>}
      {error && (
        <InlineAlert
          variant="danger"
          message={error}
          className="rounded-xl px-3 py-2 text-sm shadow-none"
        />
      )}

      {items.length > 0 && (
        <div className="space-y-2">
          <InlineAlert
            variant="warning"
            message={t('settings.intelligentImportReviewWarning')}
            className="rounded-xl px-3 py-2 text-xs shadow-none"
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-secondary-text">
              {t('settings.intelligentImportSelectionSummary', { valid: validCount, checked: checkedCount })}
            </span>
            <div className="flex gap-2">
              <button type="button" className="text-xs text-secondary-text transition-colors hover:text-foreground" onClick={() => toggleAll(true)}>
                {t('common.selectAllCurrent')}
              </button>
              <button type="button" className="text-xs text-secondary-text transition-colors hover:text-foreground" onClick={() => toggleAll(false)}>
                {t('common.cancel')}
              </button>
              <button type="button" className="text-xs text-secondary-text transition-colors hover:text-foreground" onClick={clearAll}>
                {t('settings.intelligentImportClear')}
              </button>
            </div>
          </div>
          <div className="max-h-[220px] space-y-1 overflow-y-auto rounded-xl border settings-border-strong settings-surface-overlay-soft p-2">
            {items.map((it) => {
              const confidence = normalizeConfidence(it.confidence);
              const confidenceMeta = getConfidenceMeta(confidence, language);

              return (
                <div
                  key={it.id}
                  className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-sm ${
                    it.code ? 'settings-border bg-[var(--settings-surface-strong)]' : 'border-danger/25 bg-danger/10'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={it.checked}
                    onChange={() => toggleChecked(it.id)}
                    disabled={!it.code || disabled}
                    className="settings-input-checkbox h-4 w-4 rounded border-border/70 bg-base"
                  />
                  <span className={it.code ? 'font-medium text-foreground' : 'font-medium text-danger'}>
                    {it.code || t('settings.intelligentImportParseFailed')}
                  </span>
                  {it.name && <span className="text-secondary-text">({it.name})</span>}
                  <div className="ml-auto flex items-center gap-2">
                    <Badge variant={confidenceMeta.badge} size="sm">
                      {confidenceMeta.label}
                    </Badge>
                    <button
                      type="button"
                      className="text-secondary-text transition-colors hover:text-foreground"
                      onClick={() => removeItem(it.id)}
                      disabled={disabled}
                    >
                      ×
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
          <Button
            type="button"
            variant="primary"
            className="mt-2"
            onClick={() => void mergeToWatchlist()}
            disabled={disabled || isMerging || checkedCount === 0}
          >
            {isMerging ? t('settings.saving') : t('settings.intelligentImportMergeToWatchlist')}
          </Button>
        </div>
      )}
    </div>
  );
};
