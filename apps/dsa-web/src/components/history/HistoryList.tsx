import type React from 'react';
import { useRef, useCallback, useEffect } from 'react';
import type { HistoryItem } from '../../types/analysis';
import { getSentimentColor } from '../../types/analysis';
import { formatDateTime } from '../../utils/format';
import { Button, Badge } from '../common';

interface HistoryListProps {
  items: HistoryItem[];
  isLoading: boolean;
  isLoadingMore: boolean;
  hasMore: boolean;
  selectedId?: number;  // 当前选中的历史记录 ID
  selectedIds: Set<number>;
  isDeleting?: boolean;
  onItemClick: (recordId: number) => void;  // 点击记录的回调
  onLoadMore: () => void;
  onToggleItemSelection: (recordId: number) => void;
  onToggleSelectAll: () => void;
  onDeleteSelected: () => void;
  className?: string;
}

/**
 * 历史记录列表组件 (升级版)
 * 使用新设计系统组件实现，支持批量选择和滚动加载
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

  // 使用 IntersectionObserver 检测滚动到底部
  const handleObserver = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      const target = entries[0];
      if (target.isIntersecting && hasMore && !isLoading && !isLoadingMore) {
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
      rootMargin: '20px',
      threshold: 0.1,
    });

    observer.observe(trigger);
    return () => observer.disconnect();
  }, [handleObserver]);

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someVisibleSelected;
    }
  }, [someVisibleSelected]);

  return (
    <aside className={`glass-card overflow-hidden flex flex-col ${className}`}>
      <div ref={scrollContainerRef} className="p-4 flex-1 overflow-y-auto">
        <div className="mb-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-xs font-semibold text-purple uppercase tracking-widest flex items-center gap-2">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              历史分析
            </h2>
            {selectedCount > 0 && (
              <Badge variant="history" size="sm" className="animate-in fade-in zoom-in duration-200">
                已选 {selectedCount}
              </Badge>
            )}
          </div>

          {items.length > 0 && (
            <div className="flex items-center gap-2">
              <div className="flex-1 flex items-center gap-2 px-2 py-1 rounded-lg bg-white/5 border border-white/5">
                <input
                  ref={selectAllRef}
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={onToggleSelectAll}
                  disabled={isDeleting}
                  aria-label="全选当前已加载历史记录"
                  className="w-3.5 h-3.5 rounded border-white/20 bg-transparent text-purple focus:ring-purple/40 cursor-pointer disabled:opacity-50"
                />
                <span className="text-[11px] text-muted-text select-none">全选当前</span>
              </div>
              <Button
                variant="danger"
                size="sm"
                onClick={onDeleteSelected}
                disabled={selectedCount === 0 || isDeleting}
                isLoading={isDeleting}
                className="h-7 text-[11px] px-3"
              >
                {isDeleting ? '删除中' : '删除'}
              </Button>
            </div>
          )}
        </div>

        {isLoading ? (
          <div className="flex justify-center py-10">
            <div className="w-6 h-6 border-2 border-cyan/10 border-t-cyan rounded-full animate-spin" />
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-10 space-y-2">
            <div className="mx-auto w-10 h-10 rounded-full bg-white/5 flex items-center justify-center text-muted-text/30">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <p className="text-muted-text text-xs">暂无历史分析记录</p>
          </div>
        ) : (
          <div className="space-y-2">
            {items.map((item) => (
              <div key={item.id} className="flex items-start gap-2 group">
                <div className="pt-3">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(item.id)}
                    onChange={() => onToggleItemSelection(item.id)}
                    disabled={isDeleting}
                    className="w-3.5 h-3.5 rounded border-white/20 bg-transparent text-purple focus:ring-purple/40 cursor-pointer disabled:opacity-50"
                  />
                </div>
                <button
                  type="button"
                  onClick={() => onItemClick(item.id)}
                  className={`flex-1 text-left p-2.5 rounded-xl transition-all duration-200 border relative overflow-hidden group/item ${
                    selectedId === item.id 
                      ? 'bg-purple/10 border-purple/30 border-cyan shadow-[0_0_15px_rgba(111,97,241,0.15)]' 
                      : 'bg-white/5 border-transparent hover:bg-white/10 hover:border-white/10'
                  }`}
                >
                  <div className="absolute inset-0 opacity-0 group-hover/item:opacity-100 transition-opacity pointer-events-none">
                    <div className="absolute inset-0 p-[1px] rounded-xl bg-gradient-to-br from-purple/15 via-transparent to-cyan/10" style={{ mask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)', maskComposite: 'exclude' }} />
                  </div>
                  <div className="flex items-center gap-2.5 relative z-10">
                    {item.sentimentScore !== undefined && (
                      <div 
                        className="w-1 h-8 rounded-full flex-shrink-0"
                        style={{ 
                          backgroundColor: getSentimentColor(item.sentimentScore),
                          boxShadow: `0 0 10px ${getSentimentColor(item.sentimentScore)}40` 
                        }}
                      />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-white truncate text-sm tracking-tight">
                          {item.stockName || item.stockCode}
                        </span>
                        {item.sentimentScore !== undefined && (
                          <span 
                            className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded-full border"
                            style={{ 
                              color: getSentimentColor(item.sentimentScore),
                              borderColor: `${getSentimentColor(item.sentimentScore)}30`,
                              backgroundColor: `${getSentimentColor(item.sentimentScore)}10`
                            }}
                          >
                            {item.sentimentScore}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-[11px] text-secondary-text font-mono">
                          {item.stockCode}
                        </span>
                        <span className="w-1 h-1 rounded-full bg-white/10" />
                        <span className="text-[11px] text-muted-text">
                          {formatDateTime(item.createdAt)}
                        </span>
                      </div>
                    </div>
                  </div>
                </button>
              </div>
            ))}

            <div ref={loadMoreTriggerRef} className="h-4" />
            
            {isLoadingMore && (
              <div className="flex justify-center py-4">
                <div className="w-5 h-5 border-2 border-cyan/10 border-t-cyan rounded-full animate-spin" />
              </div>
            )}

            {!hasMore && items.length > 0 && (
              <div className="text-center py-4">
                <div className="h-px bg-white/5 w-full mb-3" />
                <span className="text-[10px] text-muted-text/30 uppercase tracking-widest">End of History</span>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
};
