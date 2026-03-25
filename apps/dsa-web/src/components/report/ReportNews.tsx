import type React from 'react';
import { useState, useEffect, useCallback } from 'react';
import type { ParsedApiError } from '../../api/error';
import { getParsedApiError } from '../../api/error';
import { ApiErrorAlert, Card } from '../common';
import { DashboardPanelHeader, DashboardStateBlock } from '../dashboard';
import { historyApi } from '../../api/history';
import type { NewsIntelItem, ReportLanguage } from '../../types/analysis';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';

interface ReportNewsProps {
  recordId?: number;  // 分析历史记录主键 ID
  limit?: number;
  language?: ReportLanguage;
}

/**
 * 资讯区组件 - 终端风格
 */
export const ReportNews: React.FC<ReportNewsProps> = ({ recordId, limit = 8, language = 'zh' }) => {
  const reportLanguage = normalizeReportLanguage(language);
  const text = getReportText(reportLanguage);
  const [isLoading, setIsLoading] = useState(false);
  const [items, setItems] = useState<NewsIntelItem[]>([]);
  const [error, setError] = useState<ParsedApiError | null>(null);

  const fetchNews = useCallback(async () => {
    if (!recordId) return;
    setIsLoading(true);
    setError(null);

    try {
      const response = await historyApi.getNews(recordId, limit);
      setItems(response.items || []);
    } catch (err) {
      setError(getParsedApiError(err));
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
    <Card variant="bordered" padding="md" className="home-panel-card">
      <DashboardPanelHeader
        eyebrow={text.newsFeed}
        title={text.relatedNews}
        actions={(
          <div className="flex items-center gap-2">
            {isLoading ? (
              <div className="home-spinner h-3.5 w-3.5 animate-spin border-2" aria-hidden="true" />
            ) : null}
            <button
              type="button"
              onClick={() => void fetchNews()}
              className="home-accent-link text-xs"
            >
              {text.refresh}
            </button>
          </div>
        )}
      />

      {error && !isLoading && (
        <ApiErrorAlert
          error={error}
          actionLabel={text.retry}
          onAction={() => void fetchNews()}
          dismissLabel={text.dismiss}
        />
      )}

      {isLoading && !error && (
        <DashboardStateBlock
          compact
          loading
          title={text.loadingNews}
        />
      )}

      {!isLoading && !error && items.length === 0 && (
        <DashboardStateBlock
          compact
          title={text.noNews}
          description={text.noNewsDescription}
          icon={(
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 14l-7-7m0 0l-7 7m7-7v18" />
            </svg>
          )}
        />
      )}

      {!isLoading && !error && items.length > 0 && (
        <div className="space-y-3 text-left">
          {items.map((item, index) => (
            <div
              key={`${item.title}-${index}`}
              className="home-subpanel group p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0 text-left">
                  <p className="text-sm font-medium leading-6 text-foreground text-left">
                    {item.title}
                  </p>
                  {item.snippet && (
                    <p className="mt-2 text-sm leading-6 text-secondary-text text-left overflow-hidden [display:-webkit-box] [-webkit-line-clamp:3] [-webkit-box-orient:vertical]">
                      {item.snippet}
                    </p>
                  )}
                </div>
                {item.url && (
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="home-accent-pill-link shrink-0 whitespace-nowrap px-2.5 py-1 text-xs"
                  >
                    {text.openLink}
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
