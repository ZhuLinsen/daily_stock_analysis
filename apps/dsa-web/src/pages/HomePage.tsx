import type React from 'react';
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import type { HistoryItem, AnalysisReport, TaskInfo } from '../types/analysis';
import { historyApi } from '../api/history';
import { analysisApi, DuplicateTaskError } from '../api/analysis';
import { validateStockCode } from '../utils/validation';
import { getRecentStartDate, getTodayInShanghai } from '../utils/format';
import { useAnalysisStore } from '../stores/analysisStore';
import { ReportSummary } from '../components/report';
import { HistoryList } from '../components/history';
import { TaskPanel } from '../components/tasks';
import { useTaskStream } from '../hooks';

/**
 * 首页 - 单页设计
 * 顶部输入 + 左侧历史 + 右侧报告
 */
const HomePage: React.FC = () => {
  const { setLoading, setError: setStoreError } = useAnalysisStore();
  const navigate = useNavigate();

  // 输入状态
  const [stockCode, setStockCode] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [inputError, setInputError] = useState<string>();

// 历史列表状态
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 20;

  // 报告详情状态
  const [selectedReport, setSelectedReport] = useState<AnalysisReport | null>(null);
  const [isLoadingReport, setIsLoadingReport] = useState(false);

  // 任务队列状态
  const [activeTasks, setActiveTasks] = useState<TaskInfo[]>([]);
  const [duplicateError, setDuplicateError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // 用于跟踪当前分析请求，避免竞态条件
  const analysisRequestIdRef = useRef<number>(0);

  // 更新任务列表中的任务
  const updateTask = useCallback((updatedTask: TaskInfo) => {
    setActiveTasks((prev) => {
      const index = prev.findIndex((t) => t.taskId === updatedTask.taskId);
      if (index >= 0) {
        const newTasks = [...prev];
        newTasks[index] = updatedTask;
        return newTasks;
      }
      return prev;
    });
  }, []);

  // 移除已完成/失败的任务
  const removeTask = useCallback((taskId: string) => {
    setActiveTasks((prev) => prev.filter((t) => t.taskId !== taskId));
  }, []);

  // SSE 任务流
  useTaskStream({
    onTaskCreated: (task) => {
      setActiveTasks((prev) => {
        // 避免重复添加
        if (prev.some((t) => t.taskId === task.taskId)) return prev;
        return [...prev, task];
      });
    },
    onTaskStarted: updateTask,
    onTaskCompleted: (task) => {
      // 刷新历史列表
      fetchHistory();
      // 延迟移除任务，让用户看到完成状态
      setTimeout(() => removeTask(task.taskId), 2000);
    },
    onTaskFailed: (task) => {
      updateTask(task);
      // 显示错误提示
      setStoreError(task.error || '分析失败');
      // 延迟移除任务
      setTimeout(() => removeTask(task.taskId), 5000);
    },
    onError: () => {
      console.warn('SSE 连接断开，正在重连...');
    },
    enabled: true,
  });

// 用 ref 追踪易变状态，避免 fetchHistory 频繁重建导致 effect 循环
  const currentPageRef = useRef(currentPage);
  currentPageRef.current = currentPage;
  const historyItemsRef = useRef(historyItems);
  historyItemsRef.current = historyItems;
  const selectedReportRef = useRef(selectedReport);
  selectedReportRef.current = selectedReport;

  // 加载历史列表
  const fetchHistory = useCallback(async (autoSelectFirst = false, reset = true, silent = false) => {
    if (!silent) {
      if (reset) {
        setIsLoadingHistory(true);
        setCurrentPage(1);
      } else {
        setIsLoadingMore(true);
      }
    }

    // page is always 1 when reset=true, regardless of currentPageRef; the ref
    // is only used for load-more (reset=false) to get the next page number.
    const page = reset ? 1 : currentPageRef.current + 1;

    try {
      const response = await historyApi.getList({
        startDate: getRecentStartDate(30),
        endDate: getTodayInShanghai(),
        page,
        limit: pageSize,
      });

      if (silent && reset) {
        // 后台刷新：合并新增项到列表顶部，保留已加载的分页数据和滚动位置
        setHistoryItems(prev => {
          const existingIds = new Set(prev.map(item => item.id));
          const newItems = response.items.filter(item => !existingIds.has(item.id));
          return newItems.length > 0 ? [...newItems, ...prev] : prev;
        });
      } else if (reset) {
        setHistoryItems(response.items);
        setCurrentPage(1);
      } else {
        setHistoryItems(prev => [...prev, ...response.items]);
        setCurrentPage(page);
      }

      // 判断是否还有更多数据
      if (!silent) {
        const totalLoaded = reset ? response.items.length : historyItemsRef.current.length + response.items.length;
        setHasMore(totalLoaded < response.total);
      }

      // 如果需要自动选择第一条，且有数据，且当前没有选中报告
      if (autoSelectFirst && response.items.length > 0 && !selectedReportRef.current) {
        const firstItem = response.items[0];
        setIsLoadingReport(true);
        try {
          const report = await historyApi.getDetail(firstItem.id);
          setSelectedReport(report);
        } catch (err) {
          console.error('Failed to fetch first report:', err);
        } finally {
          setIsLoadingReport(false);
        }
      }
    } catch (err) {
      console.error('Failed to fetch history:', err);
    } finally {
      setIsLoadingHistory(false);
      setIsLoadingMore(false);
    }
  }, [pageSize]);

  // 加载更多历史记录
  const handleLoadMore = useCallback(() => {
    if (!isLoadingMore && hasMore) {
      fetchHistory(false, false);
    }
  }, [fetchHistory, isLoadingMore, hasMore]);

  // 初始加载 - 自动选择第一条（仅挂载时执行一次）
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    fetchHistory(true);
  }, []);

  // Background polling: re-fetch history every 30s for CLI-initiated analyses
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const interval = setInterval(() => {
      fetchHistory(false, true, true);
    }, 30_000);
    return () => clearInterval(interval);
  }, []);

  // Refresh when tab regains visibility (e.g. user ran main.py in another terminal)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        fetchHistory(false, true, true);
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  // 点击历史项加载报告
  const handleHistoryClick = async (recordId: number) => {
    // Increment request ID to cancel any in-flight auto-select result.
    const requestId = ++analysisRequestIdRef.current;

    // Keep the current report visible while
    // the new one loads so the right panel doesn't flash a blank spinner on
    // every click. isLoadingReport is only used for the initial empty state.
    try {
      const report = await historyApi.getDetail(recordId);
      // Ignore result if a newer click has already been issued.
      if (requestId === analysisRequestIdRef.current) {
        setSelectedReport(report);
      }
    } catch (err) {
      console.error('Failed to fetch report:', err);
      setStoreError(err instanceof Error ? err.message : '报告加载失败');
    }
  };

  // 分析股票（异步模式）
  const handleAnalyze = async () => {
    const { valid, message, normalized } = validateStockCode(stockCode);
    if (!valid) {
      setInputError(message);
      return;
    }

    setInputError(undefined);
    setDuplicateError(null);
    setIsAnalyzing(true);
    setLoading(true);
    setStoreError(null);

    // 记录当前请求的 ID
    const currentRequestId = ++analysisRequestIdRef.current;

    try {
      // 使用异步模式提交分析
      const response = await analysisApi.analyzeAsync({
        stockCode: normalized,
        reportType: 'detailed',
      });

      // 清空输入框
      if (currentRequestId === analysisRequestIdRef.current) {
        setStockCode('');
      }

      // 任务已提交，SSE 会推送更新
      console.log('Task submitted:', response.taskId);
    } catch (err) {
      console.error('Analysis failed:', err);
      if (currentRequestId === analysisRequestIdRef.current) {
        if (err instanceof DuplicateTaskError) {
          // 显示重复任务错误
          setDuplicateError(`股票 ${err.stockCode} 正在分析中，请等待完成`);
        } else {
          setStoreError(err instanceof Error ? err.message : '分析失败');
        }
      }
    } finally {
      setIsAnalyzing(false);
      setLoading(false);
    }
  };

  // 回车提交
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && stockCode && !isAnalyzing) {
      handleAnalyze();
    }
  };

  const sidebarContent = (
    <div className="flex flex-col gap-3 overflow-hidden min-h-0 h-full">
      <TaskPanel tasks={activeTasks} />
      <HistoryList
        items={historyItems}
        isLoading={isLoadingHistory}
        isLoadingMore={isLoadingMore}
        hasMore={hasMore}
        selectedId={selectedReport?.meta.id}
        onItemClick={(id) => { handleHistoryClick(id); setSidebarOpen(false); }}
        onLoadMore={handleLoadMore}
        className="max-h-[62vh] md:max-h-[62vh] flex-1 overflow-hidden"
      />
    </div>
  );

  return (
    <div
      className="min-h-screen flex flex-col md:grid overflow-hidden w-full"
      style={{ gridTemplateColumns: 'minmax(12px, 1fr) 256px 24px minmax(auto, 896px) minmax(12px, 1fr)', gridTemplateRows: 'auto 1fr' }}
    >
      {/* 顶部输入栏 */}
      <header
        className="md:col-start-2 md:col-end-5 md:row-start-1 py-3 px-3 md:px-0 border-b border-white/5 flex-shrink-0 flex items-center min-w-0 overflow-hidden"
      >
        <div className="flex items-center gap-2 w-full min-w-0 flex-1" style={{ maxWidth: 'min(100%, 1168px)' }}>
          {/* Mobile hamburger */}
          <button
            onClick={() => setSidebarOpen(true)}
            className="md:hidden p-1.5 -ml-1 rounded-lg hover:bg-white/10 transition-colors text-secondary hover:text-white flex-shrink-0"
            title="历史记录"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <div className="flex-1 relative min-w-0">
            <input
              type="text"
              value={stockCode}
              onChange={(e) => {
                setStockCode(e.target.value.toUpperCase());
                setInputError(undefined);
              }}
              onKeyDown={handleKeyDown}
              placeholder="输入股票代码，如 600519、00700、AAPL"
              disabled={isAnalyzing}
              className={`input-terminal w-full ${inputError ? 'border-danger/50' : ''}`}
            />
            {inputError && (
              <p className="absolute -bottom-4 left-0 text-xs text-danger">{inputError}</p>
            )}
            {duplicateError && (
              <p className="absolute -bottom-4 left-0 text-xs text-warning">{duplicateError}</p>
            )}
          </div>
          <button
            type="button"
            onClick={handleAnalyze}
            disabled={!stockCode || isAnalyzing}
            className="btn-primary flex items-center gap-1.5 whitespace-nowrap flex-shrink-0"
          >
            {isAnalyzing ? (
              <>
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                分析中
              </>
            ) : (
              '分析'
            )}
          </button>
        </div>
      </header>

      {/* Desktop sidebar */}
      <div className="hidden md:flex col-start-2 row-start-2 flex-col gap-3 overflow-hidden min-h-0">
        {sidebarContent}
      </div>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setSidebarOpen(false)}>
          <div className="absolute inset-0 bg-black/60" />
          <div
            className="absolute left-0 top-0 bottom-0 w-72 flex flex-col glass-card overflow-hidden border-r border-white/10 shadow-2xl p-3"
            onClick={(e) => e.stopPropagation()}
          >
            {sidebarContent}
          </div>
        </div>
      )}

      {/* 右侧报告详情 */}
      <section className="md:col-start-4 md:row-start-2 flex-1 overflow-y-auto overflow-x-auto px-3 md:px-0 md:pl-1 min-w-0 min-h-0">
        {isLoadingReport ? (
          <div className="flex flex-col items-center justify-center h-full">
            <div className="w-10 h-10 border-3 border-cyan/20 border-t-cyan rounded-full animate-spin" />
            <p className="mt-3 text-secondary text-sm">加载报告中...</p>
          </div>
        ) : selectedReport ? (
          <div className="max-w-4xl">
            {/* Follow-up button */}
            <div className="flex items-center justify-end mb-2">
              <button
                disabled={selectedReport.meta.id === undefined}
                onClick={() => {
                  const code = selectedReport.meta.stockCode;
                  const name = selectedReport.meta.stockName;
                  const rid = selectedReport.meta.id!;
                  navigate(`/chat?stock=${encodeURIComponent(code)}&name=${encodeURIComponent(name)}&recordId=${rid}`);
                }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan/10 border border-cyan/20 text-cyan text-sm hover:bg-cyan/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
                追问 AI
              </button>
            </div>
            <ReportSummary data={selectedReport} isHistory />
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-12 h-12 mb-3 rounded-xl bg-elevated flex items-center justify-center">
              <svg className="w-6 h-6 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            <h3 className="text-base font-medium text-white mb-1.5">开始分析</h3>
            <p className="text-xs text-muted max-w-xs">
              输入股票代码进行分析，或从左侧选择历史报告查看
            </p>
          </div>
        )}
      </section>
    </div>
  );
};

export default HomePage;
