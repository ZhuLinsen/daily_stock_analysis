import type React from 'react';
import { useRef, useCallback, useEffect } from 'react';
import type { HistoryItem } from '../../types/analysis';
import { getSentimentColor } from '../../types/analysis';
import { formatDateTime } from '../../utils/format';

interface HistoryListProps {
  items: HistoryItem[];
  isLoading: boolean;
  isLoadingMore: boolean;
  hasMore: boolean;
  selectedId?: number;  // Selected history record ID
  selectedIds: Set<number>;
  isDeleting?: boolean;
  onItemClick: (recordId: number) => void;  // Callback with record ID
  onLoadMore: () => void;
  onToggleItemSelection: (recordId: number) => void;
  onToggleSelectAll: () => void;
  onDeleteSelected: () => void;
  className?: string;
}

/**
 * History record list component.
 * Displays recent stock analysis history, supports clicking for details, scroll-to-load-more, 
 * and batch selection for deletion.
 */
export const HistoryList: React.FC<HistoryListProps> = ({
  items,
  isLoading,
  isLoadingMore,
  hasMore,
  selectedId,
  selectedIds,
  isDeleting = false,
  onItemClick,
  onLoadMore,
  onToggleItemSelection,
  onToggleSelectAll,
  onDeleteSelected,
  className = '',
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const loadMoreTriggerRef = useRef<HTMLDivElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);

  const selectedCount = items.filter((item) => selectedIds.has(item.id)).length;
  const allVisibleSelected = items.length > 0 && selectedCount === items.length;
  const someVisibleSelected = selectedCount > 0 && !allVisibleSelected;

  // Use IntersectionObserver to detect scrolling to bottom
  const handleObserver = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      const target = entries[0];
      // Only load when trigger is truly visible and more data exists
      if (target.isIntersecting && hasMore && !isLoading && !isLoadingMore) {
        // Ensure container has scroll capacity (content exceeds container height)
        const container = scrollContainerRef.current;
        if (container && container.scrollHeight > container.clientHeight) {
          onLoadMore();
        }
      }
    },
    [hasMore, isLoading, isLoadingMore, onLoadMore]
  );

  useEffect(() => {
    const trigger = loadMoreTriggerRef.current;
    const container = scrollContainerRef.current;
    if (!trigger || !container) return;

    const observer = new IntersectionObserver(handleObserver, {
      root: container,
      rootMargin: '20px', // Reduce pre-load distance
      threshold: 0.1, // Trigger only when at least 10% of trigger is visible
    });

    observer.observe(trigger);

    return () => {
      observer.disconnect();
    };
  }, [handleObserver]);

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someVisibleSelected;
    }
  }, [someVisibleSelected]);

  return (
    <aside className={`glass-card overflow-hidden flex flex-col ${className}`}>
      <div ref={scrollContainerRef} className="p-3 flex-1 overflow-y-auto">
        <div className="mb-3 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-xs font-medium text-purple uppercase tracking-wider flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              历史记录
            </h2>
            {selectedCount > 0 && (
              <span className="text-xs text-muted">
                已选 {selectedCount} 项
              </span>
            )}
          </div>

          {items.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <label className="inline-flex items-center gap-2 text-muted cursor-pointer">
                <input
                  ref={selectAllRef}
                  type="checkbox"
                  checked={allVisibleSelected}
                  disabled={isDeleting}
                  onChange={onToggleSelectAll}
                />
                <span>全选当前已加载</span>
              </label>
              <button
                type="button"
                className="btn-secondary !px-3 !py-1.5 !text-xs"
                onClick={onDeleteSelected}
                disabled={selectedCount === 0 || isDeleting}
              >
                {isDeleting ? '删除中...' : '删除已选'}
              </button>
            </div>
          )}
        </div>

        {isLoading ? (
          <div className="flex justify-center py-6">
            <div className="w-5 h-5 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-6 text-muted text-xs">
            暂无历史记录
          </div>
        ) : (
          <div className="space-y-1.5">
            {items.map((item) => {
              const checked = selectedIds.has(item.id);
              return (
                <div key={item.id} className="flex items-start gap-2">
                  <label className="pt-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={isDeleting}
                      onChange={() => onToggleItemSelection(item.id)}
                      aria-label={`选择历史记录 ${item.stockName || item.stockCode}`}
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => onItemClick(item.id)}
                    className={`history-item w-full text-left ${selectedId === item.id ? 'active' : ''}`}
                  >
                    <div className="flex items-center gap-2 w-full">
                      {/* Sentiment score indicator bar */}
                      {item.sentimentScore !== undefined && (
                        <span
                          className="w-0.5 h-8 rounded-full flex-shrink-0"
                          style={{
                            backgroundColor: getSentimentColor(item.sentimentScore),
                            boxShadow: `0 0 6px ${getSentimentColor(item.sentimentScore)}40`
                          }}
                        />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-1.5">
                          <span className="font-medium text-white truncate text-xs">
                            {item.stockName || item.stockCode}
                          </span>
                          {item.sentimentScore !== undefined && (
                            <span
                              className="text-xs font-mono font-semibold px-1 py-0.5 rounded"
                              style={{
                                color: getSentimentColor(item.sentimentScore),
                                backgroundColor: `${getSentimentColor(item.sentimentScore)}15`
                              }}
                            >
                              {item.sentimentScore}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <span className="text-xs text-muted font-mono">
                            {item.stockCode}
                          </span>
                          <span className="text-xs text-muted/50">·</span>
                          <span className="text-xs text-muted">
                            {formatDateTime(item.createdAt)}
                          </span>
                        </div>
                      </div>
                    </div>
                  </button>
                </div>
              );
            })}

            {/* 加载更多触发器 */}
            <div ref={loadMoreTriggerRef} className="h-4" />

            {/* 加载更多状态 */}
            {isLoadingMore && (
              <div className="flex justify-center py-3">
                <div className="w-4 h-4 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
              </div>
            )}

            {/* 没有更多数据提示 */}
            {!hasMore && items.length > 0 && (
              <div className="text-center py-2 text-muted/50 text-xs">
                已加载全部
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
};
