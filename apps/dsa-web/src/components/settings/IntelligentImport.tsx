import type React from 'react';
import { useCallback, useState } from 'react';
import { getParsedApiError } from '../../api/error';
import { stocksApi, type ExtractItem } from '../../api/stocks';
import { systemConfigApi, SystemConfigConflictError } from '../../api/systemConfig';

const IMG_EXT = ['.jpg', '.jpeg', '.png', '.webp', '.gif'];
const IMG_MAX = 5 * 1024 * 1024; // 5MB
const FILE_MAX = 2 * 1024 * 1024; // 2MB
const TEXT_MAX = 100 * 1024; // 100KB

interface IntelligentImportProps {
  stockListValue: string;
  configVersion: string;
  maskToken: string;
  onMerged: () => void;
  disabled?: boolean;
}

type ItemWithChecked = ExtractItem & { id: string; checked: boolean };

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
  const [items, setItems] = useState<ItemWithChecked[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isMerging, setIsMerging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [pasteText, setPasteText] = useState('');

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
        setError('图片仅支持 JPG、PNG、WebP、GIF');
        return;
      }
      if (file.size > IMG_MAX) {
        setError('图片不超过 5MB');
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
        let fallback = '识别失败，请重试';
        if (err?.response?.status === 429) fallback = '请求过于频繁，请稍后再试';
        else if (err?.code === 'ECONNABORTED') fallback = '请求超时，请检查网络后重试';
        setError(parsed.message || fallback);
      } finally {
        setIsLoading(false);
      }
    },
    [addItems],
  );

  const handleDataFile = useCallback(
    async (file: File) => {
      if (file.size > FILE_MAX) {
        setError('文件不超过 2MB');
        return;
      }
      setError(null);
      setIsLoading(true);
      try {
        const res = await stocksApi.parseImport(file);
        addItems(res.items ?? res.codes.map((c) => ({ code: c, name: null, confidence: 'medium' })));
      } catch (e) {
        const parsed = getParsedApiError(e);
        setError(parsed.message || '解析失败');
      } finally {
        setIsLoading(false);
      }
    },
    [addItems],
  );

  const handlePasteParse = useCallback(() => {
    const t = pasteText.trim();
    if (!t) return;
    if (new Blob([t]).size > TEXT_MAX) {
      setError('粘贴文本不超过 100KB');
      return;
    }
    setError(null);
    setIsLoading(true);
    stocksApi
      .parseImport(undefined, t)
      .then((res) => {
        addItems(res.items ?? res.codes.map((c) => ({ code: c, name: null, confidence: 'medium' })));
        setPasteText('');
      })
      .catch((e) => {
        const parsed = getParsedApiError(e);
        setError(parsed.message || '解析失败');
      })
      .finally(() => setIsLoading(false));
  }, [pasteText, addItems]);

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
      setError('请先加载配置后再合并');
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
      onMerged();
    } catch (e) {
      if (e instanceof SystemConfigConflictError) {
        onMerged();
        setError('配置已更新，请再次点击「合并到自选股」');
      } else {
        setError(e instanceof Error ? e.message : '合并保存失败');
      }
    } finally {
      setIsMerging(false);
    }
  }, [items, configVersion, maskToken, onMerged, parseCurrentList]);

  const validCount = items.filter((i) => i.code).length;
  const checkedCount = items.filter((i) => i.checked && i.code).length;

  return (
    <div className="rounded-xl border border-white/8 bg-elevated/40 p-4">
      <p className="mb-2 text-sm font-medium text-white">智能导入</p>
      <p className="mb-3 text-xs text-muted">
        支持图片、CSV/Excel 文件、剪贴板粘贴。图片需配置 Vision API。建议人工核对后再合并。
      </p>

      <div
        onDrop={onDrop}
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={(e) => { e.preventDefault(); setIsDragging(false); }}
        className={`mb-3 flex min-h-[80px] flex-col gap-4 rounded-lg border-2 border-dashed p-4 transition ${
          isDragging ? 'border-accent bg-cyan/5' : 'border-white/16'
        } ${disabled || isLoading ? 'cursor-not-allowed opacity-60' : ''}`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <label className="cursor-pointer">
            <span className="btn-secondary text-sm">选择图片</span>
            <input type="file" accept=".jpg,.jpeg,.png,.webp,.gif" className="hidden" onChange={onImageInput} disabled={disabled || isLoading} />
          </label>
          <label className="cursor-pointer">
            <span className="btn-secondary text-sm">选择文件</span>
            <input type="file" accept=".csv,.xlsx,.txt" className="hidden" onChange={onDataFileInput} disabled={disabled || isLoading} />
          </label>
        </div>
        <div className="flex gap-2">
          <textarea
            placeholder="或粘贴 CSV/Excel 复制的文本..."
            className="min-h-[60px] w-full rounded-lg border border-white/16 bg-card/60 px-2 py-1.5 text-sm text-white placeholder:text-muted"
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            disabled={disabled || isLoading}
          />
          <button type="button" className="btn-secondary shrink-0" onClick={handlePasteParse} disabled={disabled || isLoading || !pasteText.trim()}>
            解析
          </button>
        </div>
      </div>

      {isLoading && <p className="mb-2 text-sm text-secondary">处理中...</p>}
      {error && (
        <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">{error}</div>
      )}

      {items.length > 0 && (
        <div className="space-y-2">
          <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-xs text-amber-400">
            ⚠️ 建议人工逐条核对后再合并。高置信度默认勾选，中/低需手动勾选。
          </p>
          <div className="flex items-center justify-between">
            <span className="text-xs text-secondary">
              共 {validCount} 条可合并，已勾选 {checkedCount} 条
            </span>
            <div className="flex gap-2">
              <button type="button" className="text-xs text-muted hover:text-white" onClick={() => toggleAll(true)}>
                全选
              </button>
              <button type="button" className="text-xs text-muted hover:text-white" onClick={() => toggleAll(false)}>
                取消
              </button>
              <button type="button" className="text-xs text-muted hover:text-white" onClick={clearAll}>
                清空
              </button>
            </div>
          </div>
          <div className="max-h-[200px] overflow-y-auto space-y-1">
            {items.map((it) => (
              <div
                key={it.id}
                className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 text-sm ${
                  it.code ? 'border-white/16 bg-card/60' : 'border-red-500/30 bg-red-500/10'
                }`}
              >
                <input
                  type="checkbox"
                  checked={it.checked}
                  onChange={() => toggleChecked(it.id)}
                  disabled={!it.code || disabled}
                  className="rounded"
                />
                <span className={it.code ? 'text-white' : 'text-red-400'}>
                  {it.code || '解析失败'}
                </span>
                {it.name && <span className="text-muted">({it.name})</span>}
                <span className="ml-auto text-xs text-muted">
                  {it.confidence === 'high' ? '高' : it.confidence === 'low' ? '低' : '中'}
                </span>
                <button
                  type="button"
                  className="text-muted hover:text-white"
                  onClick={() => removeItem(it.id)}
                  disabled={disabled}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="btn-primary mt-2"
            onClick={() => void mergeToWatchlist()}
            disabled={disabled || isMerging || checkedCount === 0}
          >
            {isMerging ? '保存中...' : '合并到自选股'}
          </button>
        </div>
      )}
    </div>
  );
};
