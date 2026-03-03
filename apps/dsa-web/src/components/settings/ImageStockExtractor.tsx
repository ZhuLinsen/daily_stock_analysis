import type React from 'react';
import { useCallback, useState } from 'react';
import { stocksApi } from '../../api/stocks';
import { systemConfigApi, SystemConfigConflictError } from '../../api/systemConfig';

const ALLOWED_EXT = ['.jpg', '.jpeg', '.png', '.webp', '.gif'];
const MAX_SIZE = 5 * 1024 * 1024; // 5MB

interface ImageStockExtractorProps {
  stockListValue: string;
  configVersion: string;
  maskToken: string;
  onMerged: () => void;
  disabled?: boolean;
}

export const ImageStockExtractor: React.FC<ImageStockExtractorProps> = ({
  stockListValue,
  configVersion,
  maskToken,
  onMerged,
  disabled,
}) => {
  const [codes, setCodes] = useState<string[]>([]);
  const [isExtracting, setIsExtracting] = useState(false);
  const [isMerging, setIsMerging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const parseCurrentList = useCallback(() => {
    return stockListValue
      .split(',')
      .map((c) => c.trim())
      .filter(Boolean);
  }, [stockListValue]);

  const handleFile = useCallback(
    async (file: File) => {
      const ext = '.' + (file.name.split('.').pop() ?? '').toLowerCase();
      if (!ALLOWED_EXT.includes(ext)) {
        setError('仅支持 JPG、PNG、WebP、GIF 格式');
        return;
      }
      if (file.size > MAX_SIZE) {
        setError('图片不超过 5MB');
        return;
      }

      setError(null);
      setIsExtracting(true);
      try {
        const res = await stocksApi.extractFromImage(file);
        setCodes(res.codes ?? []);
      } catch (e) {
        const err = e && typeof e === 'object' ? e as { code?: string; response?: { data?: { message?: string }; status?: number } } : null;
        const resp = err?.response ?? null;
        const msg = resp?.data?.message ?? null;
        let fallback = '识别失败，请重试';
        if (resp?.status === 429) fallback = '请求过于频繁，请稍后再试';
        else if (err?.code === 'ECONNABORTED') fallback = '请求超时，请检查网络后重试';
        setError(msg || fallback);
        setCodes([]);
      } finally {
        setIsExtracting(false);
      }
    },
    [],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const f = e.dataTransfer?.files?.[0];
      if (f) void handleFile(f);
    },
    [handleFile],
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const onFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      if (f) void handleFile(f);
      e.target.value = '';
    },
    [handleFile],
  );

  const removeCode = useCallback((code: string) => {
    setCodes((prev) => prev.filter((c) => c !== code));
  }, []);

  const mergeToWatchlist = useCallback(async () => {
    if (codes.length === 0) return;
    if (!configVersion) {
      setError('请先加载配置后再合并');
      return;
    }
    const current = parseCurrentList();
    const merged = [...new Set([...current, ...codes])];
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
      setCodes([]);
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
  }, [codes, configVersion, maskToken, onMerged, parseCurrentList]);

  return (
    <div className="rounded-xl border border-white/8 bg-elevated/40 p-4">
      <p className="mb-2 text-sm font-medium text-white">从图片添加</p>
      <p className="mb-3 text-xs text-muted">
        上传自选股截图，自动识别股票代码。需配置 Gemini、Anthropic 或 OpenAI API Key 方可使用。建议人工核对后再合并。
      </p>

      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        className={`mb-3 flex min-h-[100px] cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed transition ${
          isDragging ? 'border-accent bg-cyan/5' : 'border-white/16 hover:border-white/24'
        } ${disabled || isExtracting ? 'cursor-not-allowed opacity-60' : ''}`}
        onClick={() => !disabled && !isExtracting && document.getElementById('img-upload')?.click()}
      >
        <input
          id="img-upload"
          type="file"
          accept=".jpg,.jpeg,.png,.webp,.gif"
          className="hidden"
          onChange={onFileInput}
          disabled={disabled || isExtracting}
        />
        {isExtracting ? (
          <span className="text-sm text-secondary">识别中...</span>
        ) : (
          <span className="text-sm text-secondary">
            拖拽或点击上传图片（JPG/PNG/WebP，≤5MB）。大图识别约需 30–60 秒
          </span>
        )}
      </div>

      {error ? (
        <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </div>
      ) : null}

      {codes.length > 0 ? (
        <div className="space-y-2">
          <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-xs text-amber-400">
            ⚠️ 建议人工逐条核对后再合并，识别结果可能有误
          </p>
          <p className="text-xs text-secondary">识别结果（可删除不需要的项）：</p>
          <div className="flex flex-wrap gap-2">
            {codes.map((code) => (
              <span
                key={code}
                className="inline-flex items-center gap-1 rounded-lg border border-white/16 bg-card/60 px-2 py-1 text-sm"
              >
                {code}
                <button
                  type="button"
                  className="text-muted hover:text-white"
                  onClick={() => removeCode(code)}
                  disabled={disabled}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
          <button
            type="button"
            className="btn-primary mt-2"
            onClick={() => void mergeToWatchlist()}
            disabled={disabled || isMerging}
          >
            {isMerging ? '保存中...' : '合并到自选股'}
          </button>
        </div>
      ) : null}
    </div>
  );
};
