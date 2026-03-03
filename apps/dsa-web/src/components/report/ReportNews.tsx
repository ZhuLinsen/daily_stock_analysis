import type React from 'react';
import { useState, useEffect, useCallback } from 'react';
import { Card } from '../common';
import { historyApi } from '../../api/history';
import type { NewsIntelItem } from '../../types/analysis';

interface ReportNewsProps {
  recordId?: number;  // 分析历史记录主键 ID
  limit?: number;
}

/**
 * 资讯区组件 - 终端风格
 */
export const ReportNews: React.FC<ReportNewsProps> = ({ recordId, limit = 20 }) => {
  const [isLoading, setIsLoading] = useState(false);
  const [items, setItems] = useState<NewsIntelItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchNews = useCallback(async () => {
    if (!recordId) return;
    setIsLoading(true);
    setError(null);

    try {
      const response = await historyApi.getNews(recordId, limit);
      setItems(response.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载资讯失败');
    } finally {
      setIsLoading(false);
    }
  }, [recordId, limit]);

  useEffect(() => {
    setItems([]);
    setError(null);

    if (recordId) {
      fetchNews();
    }
  }, [recordId, fetchNews]);

  if (!recordId) {
    return null;
  }

  return (
    <Card variant="bordered" padding="md">
      <div className="flex items-center justify-between mb-3">
        <div className="mb-3 flex items-baseline gap-2">
          <span className="label-uppercase">NEWS FEED</span>
          <h3 className="text-base font-semibold text-white">相关资讯</h3>
        </div>
        <div className="flex items-center gap-2">
          {isLoading && (
            <div className="w-3.5 h-3.5 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
          )}
          <button
            type="button"
            onClick={fetchNews}
            className="text-xs text-cyan hover:text-white transition-colors"
          >
            刷新
          </button>
        </div>
      </div>

      {error && !isLoading && (
        <div className="flex items-center justify-between gap-3 p-3 rounded-lg bg-danger/10 border border-danger/20 text-xs text-danger">
          <span>{error}</span>
          <button
            type="button"
            onClick={fetchNews}
            className="text-xs text-cyan hover:text-white transition-colors"
          >
            重试
          </button>
        </div>
      )}

      {isLoading && !error && (
        <div className="flex items-center gap-2 text-xs text-secondary">
          <div className="w-4 h-4 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
          加载资讯中...
        </div>
      )}

      {!isLoading && !error && items.length === 0 && (
        <div className="text-xs text-muted">暂无相关资讯</div>
      )}

      {!isLoading && !error && items.length > 0 && (
        <div className="space-y-2 text-left">
          {items.map((item, index) => (
            <div
              key={`${item.title}-${index}`}
              className="group p-3 rounded-lg bg-elevated/80 border border-white/5 hover:border-cyan/30 hover:bg-hover transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0 text-left">
                  <p className="text-sm text-white font-medium leading-snug text-left">
                    {item.title}
                  </p>
                  {item.snippet && (
                    <p className="text-xs text-secondary mt-1 text-left">
                      {item.snippet}
                    </p>
                  )}
                </div>
                {item.url && (
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-cyan hover:text-white transition-colors inline-flex items-center gap-1 whitespace-nowrap"
                  >
                    跳转
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M14 3h7m0 0v7m0-7L10 14"
                      />
                    </svg>
                  </a>
                )}
              </div>
            </div>
          ))}

        </div>
      )}
    </Card>
  );
};
