import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BarChart3, Check, SlidersHorizontal, X } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import { analysisApi } from '../api/analysis';
import { historyApi } from '../api/history';
import { agentApi, type SkillInfo } from '../api/agent';
import { systemConfigApi } from '../api/systemConfig';
import { ApiErrorAlert, Button, Drawer, EmptyState, InlineAlert } from '../components/common';
import { DashboardStateBlock } from '../components/dashboard';
import { StockAutocomplete } from '../components/StockAutocomplete';
import { StockHistoryTrendDrawer, StockBar } from '../components/history';
import { ReportMarkdownDrawer } from '../components/report/ReportMarkdownDrawer';
import { MarketReviewReportView } from '../components/report/MarketReviewReportView';
import { ReportSummary } from '../components/report/ReportSummary';
import { RunFlowPanel } from '../components/run-flow';
import { TaskPanel } from '../components/tasks';
import { useDashboardLifecycle, useHomeDashboardState } from '../hooks';
import { useWatchlist } from '../hooks/useWatchlist';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { SetupStatusResponse } from '../types/systemConfig';
import { normalizeReportLanguage } from '../utils/reportLanguage';
import type { MarketReviewPayload, StockBarItem, TaskInfo } from '../types/analysis';
import type { RunFlowSnapshotSource } from '../types/runFlow';

type MarketReviewNotice = {
  variant: 'success' | 'warning' | 'danger';
  title: string;
  message: string;
} | null;

type RunFlowDrawerState =
  | { open: false }
  | { open: true; source: RunFlowSnapshotSource; title: string };

type StockAnalysisNavigationState = {
  stockCode?: string;
  stockName?: string;
  autoAnalyze?: boolean;
  selectionSource?: string;
};

const DUPLICATE_BANNER_AUTO_DISMISS_MS = 5000;

const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { language: uiLanguage, t } = useUiLanguage();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isSubmittingMarketReview, setIsSubmittingMarketReview] = useState(false);
  const [marketReviewNotice, setMarketReviewNotice] = useState<MarketReviewNotice>(null);
  const [marketReviewError, setMarketReviewError] = useState<ParsedApiError | null>(null);
  const [marketReviewReport, setMarketReviewReport] = useState<string | null>(null);
  const [marketReviewPayload, setMarketReviewPayload] = useState<MarketReviewPayload | null>(null);
  const [analysisSkills, setAnalysisSkills] = useState<SkillInfo[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState('');
  const [strategyMenuOpen, setStrategyMenuOpen] = useState(false);
  const [runFlowDrawer, setRunFlowDrawer] = useState<RunFlowDrawerState>({ open: false });
  const [duplicateBannerVisible, setDuplicateBannerVisible] = useState(false);
  const duplicateBannerTimer = useRef<number | null>(null);
  const marketReviewPollTimer = useRef<number | null>(null);
  const dashboardScrollRef = useRef<HTMLElement | null>(null);
  const strategyMenuRef = useRef<HTMLDivElement | null>(null);
  const strategyButtonRef = useRef<HTMLButtonElement | null>(null);
  const strategyItemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const strategyInitialFocusIndexRef = useRef<number | null>(null);

  const stopMarketReviewPolling = useCallback(() => {
    if (marketReviewPollTimer.current !== null) {
      window.clearInterval(marketReviewPollTimer.current);
      marketReviewPollTimer.current = null;
    }
  }, []);

  const scrollMarketReviewFeedbackIntoView = useCallback(() => {
    const scrollContainer = dashboardScrollRef.current;
    if (!scrollContainer) {
      return;
    }

    if (typeof scrollContainer.scrollTo === 'function') {
      scrollContainer.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }

    scrollContainer.scrollTop = 0;
  }, []);

  useEffect(() => stopMarketReviewPolling, [stopMarketReviewPolling]);
  const [setupStatus, setSetupStatus] = useState<SetupStatusResponse | null>(null);

  const {
    query,
    inputError,
    duplicateError,
    error,
    isAnalyzing,
    selectedReport,
    isLoadingReport,
    isHistoryTrendOpen,
    marketReviewHistoryItems,
    stockHistoryItems,
    stockHistoryTotal,
    stockHistoryHasMore,
    isLoadingStockHistory,
    isLoadingMoreStockHistory,
    stockHistoryError,
    stockHistoryFilters,
    activeTasks,
    markdownDrawerOpen,
    setQuery,
    clearError,
    loadInitialHistory,
    refreshHistory,
    loadMarketReviewHistory,
    refreshMarketReviewHistory,
    selectHistoryItem,
    submitAnalysis,
    notify,
    setNotify,
    syncTaskCreated,
    syncTaskUpdated,
    syncTaskFailed,
    refreshActiveTasks,
    removeTask,
    openMarkdownDrawer,
    closeMarkdownDrawer,
    openHistoryTrend,
    closeHistoryTrend,
    setStockHistoryRange,
    loadMoreStockHistory,
    stockBarItems,
    isLoadingStockBar,
    loadStockBar,
    refreshStockBar,
  } = useHomeDashboardState();

  const clearDuplicateBannerTimer = useCallback(() => {
    if (duplicateBannerTimer.current !== null) {
      window.clearTimeout(duplicateBannerTimer.current);
      duplicateBannerTimer.current = null;
    }
  }, []);

  const dismissDuplicateBanner = useCallback(() => {
    clearDuplicateBannerTimer();
    setDuplicateBannerVisible(false);
  }, [clearDuplicateBannerTimer]);

  useEffect(() => {
    if (!duplicateError) {
      clearDuplicateBannerTimer();
      setDuplicateBannerVisible(false);
      return undefined;
    }

    setDuplicateBannerVisible(true);
    clearDuplicateBannerTimer();
    duplicateBannerTimer.current = window.setTimeout(() => {
      duplicateBannerTimer.current = null;
      setDuplicateBannerVisible(false);
    }, DUPLICATE_BANNER_AUTO_DISMISS_MS);

    return clearDuplicateBannerTimer;
  }, [clearDuplicateBannerTimer, duplicateError]);

  useEffect(() => {
    document.title = t('home.pageTitle');
  }, [t]);

  useEffect(() => {
    let active = true;
    systemConfigApi.getSetupStatus()
      .then((status) => {
        if (active) {
          setSetupStatus(status);
        }
      })
      .catch(() => {
        if (active) {
          setSetupStatus(null);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    agentApi.getSkills()
      .then((response) => {
        if (active) {
          setAnalysisSkills(response.skills);
        }
      })
      .catch(() => {
        if (active) {
          setAnalysisSkills([]);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!strategyMenuOpen) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target;
      if (target instanceof Node && strategyMenuRef.current?.contains(target)) {
        return;
      }
      setStrategyMenuOpen(false);
    };

    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [strategyMenuOpen]);

  useEffect(() => {
    if (selectedStrategyId && !analysisSkills.some((skill) => skill.id === selectedStrategyId)) {
      setSelectedStrategyId('');
    }
  }, [analysisSkills, selectedStrategyId]);

  const reportLanguage = normalizeReportLanguage(selectedReport?.meta.reportLanguage);
  const liveMarketReviewLanguage = normalizeReportLanguage(marketReviewPayload?.language);
  const isMarketReviewHistoryReport = selectedReport?.meta.reportType === 'market_review';
  const isHistoryTrendUnavailable = !selectedReport || !selectedReport.meta.stockCode;

  useEffect(() => {
    if (!isHistoryTrendUnavailable || !isHistoryTrendOpen) {
      return;
    }
    closeHistoryTrend();
  }, [closeHistoryTrend, isHistoryTrendOpen, isHistoryTrendUnavailable]);

  const selectedStrategy = useMemo(
    () => analysisSkills.find((skill) => skill.id === selectedStrategyId),
    [analysisSkills, selectedStrategyId],
  );
  const selectedAnalysisSkills = useMemo(
    () => (selectedStrategyId ? [selectedStrategyId] : undefined),
    [selectedStrategyId],
  );
  const strategyOptions = useMemo(
    () => [
      { id: '', name: t('home.defaultStrategyName'), description: t('home.defaultStrategyDescription') },
      ...analysisSkills.map((skill) => ({
        id: skill.id,
        name: skill.name,
        description: skill.description,
      })),
    ],
    [analysisSkills, t],
  );
  const closeStrategyMenu = useCallback((restoreFocus = false) => {
    setStrategyMenuOpen(false);
    if (restoreFocus) {
      strategyButtonRef.current?.focus();
    }
  }, []);
  const selectStrategy = useCallback((strategyId: string) => {
    setSelectedStrategyId(strategyId);
    setStrategyMenuOpen(false);
  }, []);
  const focusStrategyItem = useCallback((index: number) => {
    const itemCount = strategyOptions.length;
    if (itemCount === 0) {
      return;
    }
    const nextIndex = (index + itemCount) % itemCount;
    strategyItemRefs.current[nextIndex]?.focus();
  }, [strategyOptions.length]);
  const getSelectedStrategyIndex = useCallback(() => {
    const selectedIndex = strategyOptions.findIndex((option) => option.id === selectedStrategyId);
    return selectedIndex >= 0 ? selectedIndex : 0;
  }, [selectedStrategyId, strategyOptions]);
  useEffect(() => {
    strategyItemRefs.current = strategyItemRefs.current.slice(0, strategyOptions.length);
  }, [strategyOptions.length]);
  useEffect(() => {
    if (!strategyMenuOpen) {
      return undefined;
    }

    const targetIndex = strategyInitialFocusIndexRef.current ?? getSelectedStrategyIndex();
    strategyInitialFocusIndexRef.current = null;
    const timeout = window.setTimeout(() => focusStrategyItem(targetIndex), 0);
    return () => window.clearTimeout(timeout);
  }, [focusStrategyItem, getSelectedStrategyIndex, strategyMenuOpen]);
  const handleStrategyButtonKeyDown = useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
      return;
    }

    event.preventDefault();
    const targetIndex = event.key === 'ArrowUp' ? strategyOptions.length - 1 : 0;
    if (strategyMenuOpen) {
      focusStrategyItem(targetIndex);
      return;
    }
    strategyInitialFocusIndexRef.current = targetIndex;
    setStrategyMenuOpen(true);
  }, [focusStrategyItem, strategyMenuOpen, strategyOptions.length]);
  const handleStrategyMenuKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    const itemCount = strategyOptions.length;
    if (itemCount === 0) {
      return;
    }

    const currentIndex = strategyItemRefs.current.findIndex((item) => item === document.activeElement);
    switch (event.key) {
      case 'Escape':
        event.preventDefault();
        closeStrategyMenu(true);
        break;
      case 'ArrowDown':
        event.preventDefault();
        focusStrategyItem(currentIndex >= 0 ? currentIndex + 1 : 0);
        break;
      case 'ArrowUp':
        event.preventDefault();
        focusStrategyItem(currentIndex >= 0 ? currentIndex - 1 : itemCount - 1);
        break;
      case 'Home':
        event.preventDefault();
        focusStrategyItem(0);
        break;
      case 'End':
        event.preventDefault();
        focusStrategyItem(itemCount - 1);
        break;
      case 'Tab':
        setStrategyMenuOpen(false);
        break;
      default:
        break;
    }
  }, [closeStrategyMenu, focusStrategyItem, strategyOptions.length]);
  const setupNeedsAction = setupStatus ? !setupStatus.isComplete : false;
  const setupMissingLabels = useMemo(() => {
    if (!setupStatus) {
      return '';
    }
    const requiredNeedsAction = setupStatus.checks
      .filter((check) => check.required && check.status === 'needs_action')
      .map((check) => check.title);
    return requiredNeedsAction.slice(0, 3).join(uiLanguage === 'en' ? ', ' : '、');
  }, [setupStatus, uiLanguage]);

  useDashboardLifecycle({
    loadInitialHistory,
    refreshHistory,
    loadMarketReviewHistory,
    refreshMarketReviewHistory,
    loadStockBar,
    refreshStockBar,
    syncTaskCreated,
    syncTaskUpdated,
    syncTaskFailed,
    refreshActiveTasks,
    removeTask,
  });

  const watchlistState = useWatchlist();

  const clearMarketReviewState = useCallback(() => {
    stopMarketReviewPolling();
    setMarketReviewReport(null);
    setMarketReviewPayload(null);
    setMarketReviewNotice(null);
    setMarketReviewError(null);
  }, [stopMarketReviewPolling]);

  const handleHistoryItemClick = useCallback((recordId: number) => {
    clearMarketReviewState();
    void selectHistoryItem(recordId);
    setSidebarOpen(false);
  }, [clearMarketReviewState, selectHistoryItem]);

  const [isDeletingStock, setIsDeletingStock] = useState(false);
  const handleDeleteStock = useCallback(async (stockCode: string) => {
    if (isDeletingStock) return;
    setIsDeletingStock(true);
    try {
      await historyApi.deleteByCode(stockCode);
      await refreshStockBar();
      await refreshHistory(true);
      if (stockCode === 'MARKET') {
        await refreshMarketReviewHistory(false);
      }
    } catch {
      // error silently ignored
    } finally {
      setIsDeletingStock(false);
    }
  }, [isDeletingStock, refreshMarketReviewHistory, refreshStockBar, refreshHistory]);

  const handleSubmitAnalysis = useCallback(
    (
      stockCode?: string,
      stockName?: string,
      selectionSource?: 'manual' | 'autocomplete' | 'import' | 'image',
    ) => {
      void submitAnalysis({
        stockCode,
        stockName,
        originalQuery: query,
        selectionSource: selectionSource ?? 'manual',
        skills: selectedAnalysisSkills,
      });
    },
    [query, selectedAnalysisSkills, submitAnalysis],
  );

  useEffect(() => {
    const state = location.state as StockAnalysisNavigationState | null;
    const stockCode = typeof state?.stockCode === 'string' ? state.stockCode.trim() : '';
    if (!stockCode) {
      return;
    }
    const stockName = typeof state?.stockName === 'string' ? state.stockName.trim() : '';
    setQuery(stockCode);
    navigate(location.pathname, { replace: true, state: null });
    if (state?.autoAnalyze) {
      handleSubmitAnalysis(stockCode, stockName || undefined, 'import');
    }
  }, [handleSubmitAnalysis, location.pathname, location.state, navigate, setQuery]);

  const handleAskFollowUp = useCallback(() => {
    if (selectedReport?.meta.id === undefined || selectedReport.meta.reportType === 'market_review') {
      return;
    }

    const code = selectedReport.meta.stockCode;
    const name = selectedReport.meta.stockName;
    const rid = selectedReport.meta.id;
    navigate(`/chat?stock=${encodeURIComponent(code)}&name=${encodeURIComponent(name)}&recordId=${rid}`);
  }, [navigate, selectedReport]);

  const handleReanalyze = useCallback(() => {
    if (!selectedReport || selectedReport.meta.reportType === 'market_review') {
      return;
    }

    void submitAnalysis({
      stockCode: selectedReport.meta.stockCode,
      stockName: selectedReport.meta.stockName,
      originalQuery: selectedReport.meta.stockCode,
      selectionSource: 'manual',
      forceRefresh: true,
      skills: selectedAnalysisSkills,
    });
  }, [selectedAnalysisSkills, selectedReport, submitAnalysis]);

  const openTaskRunFlow = useCallback((task: TaskInfo) => {
    const stock = task.stockName || task.stockCode || task.taskId;
    setRunFlowDrawer({
      open: true,
      source: { type: 'task', taskId: task.taskId },
      title: t('runFlow.taskDrawerTitle', { stock }),
    });
  }, [t]);

  const openHistoryRunFlow = useCallback((recordId: number) => {
    const meta = selectedReport?.meta.id === recordId ? selectedReport.meta : null;
    const stock = meta?.stockName || meta?.stockCode || String(recordId);
    setRunFlowDrawer({
      open: true,
      source: { type: 'history', recordId },
      title: t('runFlow.historyDrawerTitle', { stock }),
    });
  }, [selectedReport, t]);

  const closeRunFlowDrawer = useCallback(() => {
    setRunFlowDrawer({ open: false });
  }, []);

  const pollMarketReviewStatus = useCallback(
    async (taskId: string) => {
      stopMarketReviewPolling();

      const maxAttempts = 120;
      const intervalMs = 2000;
      let attempts = 0;

      const poll = async (): Promise<boolean> => {
        if (attempts >= maxAttempts) {
          stopMarketReviewPolling();
          setMarketReviewReport(null);
          setMarketReviewPayload(null);
          setMarketReviewNotice({
            variant: 'danger',
            title: t('home.marketReviewTimeout'),
            message: t('home.marketReviewTimeoutMessage'),
          });
          scrollMarketReviewFeedbackIntoView();
          return false;
        }

        attempts += 1;

        try {
          const status = await analysisApi.getStatus(taskId);
          if (status.status === 'pending' || status.status === 'processing') {
            setMarketReviewReport(null);
            setMarketReviewPayload(null);
            const progress = typeof status.progress === 'number'
              ? `${status.progress}%`
              : t('home.progressActive');
            setMarketReviewNotice({
              variant: 'warning',
              title: t('home.marketReviewInProgress'),
              message: t('home.taskStatus', { status: status.status, progress }),
            });
            return true;
          }

          if (status.status === 'completed') {
            stopMarketReviewPolling();
            const marketReviewText = typeof status.marketReviewReport === 'string'
              ? status.marketReviewReport
              : '';
            setMarketReviewReport(marketReviewText ? marketReviewText.trim() : null);
            setMarketReviewPayload(status.marketReviewPayload ?? null);
            setMarketReviewNotice({
              variant: 'success',
              title: t('home.marketReviewCompleted'),
              message: marketReviewText ? t('home.marketReviewCompletedWithReport') : t('home.marketReviewCompletedWithoutReport'),
            });
            setMarketReviewError(null);
            await refreshMarketReviewHistory(true);
            scrollMarketReviewFeedbackIntoView();
            return false;
          }

          if (status.status === 'failed') {
            stopMarketReviewPolling();
            setMarketReviewReport(null);
            setMarketReviewPayload(null);
            setMarketReviewError(
              getParsedApiError({
                response: {
                  status: 500,
                  data: {
                    error: 'market_review_failed',
                    message: status.error || t('home.marketReviewFailed'),
                  },
                },
              }),
            );
            setMarketReviewNotice(null);
            scrollMarketReviewFeedbackIntoView();
            return false;
          }

          stopMarketReviewPolling();
          setMarketReviewReport(null);
          setMarketReviewPayload(null);
          setMarketReviewNotice({
            variant: 'danger',
            title: t('home.marketReviewUnknownStatus'),
            message: t('home.unknownTaskStatus', { status: status.status }),
          });
          scrollMarketReviewFeedbackIntoView();
          return false;
        } catch (err: unknown) {
          const parsed = getParsedApiError(err);
          if (attempts >= maxAttempts) {
            stopMarketReviewPolling();
            setMarketReviewReport(null);
            setMarketReviewPayload(null);
            setMarketReviewError(parsed);
            setMarketReviewNotice(null);
            scrollMarketReviewFeedbackIntoView();
            return false;
          }
          return true;
        }

        return true;
      };

      if (await poll()) {
        marketReviewPollTimer.current = window.setInterval(() => {
          void poll().then((shouldContinue) => {
            if (!shouldContinue) {
              stopMarketReviewPolling();
            }
          });
        }, intervalMs);
      }
    },
    [refreshMarketReviewHistory, scrollMarketReviewFeedbackIntoView, stopMarketReviewPolling, t],
  );

  const handleTriggerMarketReview = useCallback(async () => {
    setIsSubmittingMarketReview(true);
    setMarketReviewNotice(null);
    setMarketReviewError(null);
    setMarketReviewReport(null);
    setMarketReviewPayload(null);
    scrollMarketReviewFeedbackIntoView();
    try {
      const result = await analysisApi.triggerMarketReview({ sendNotification: notify });
      setMarketReviewNotice({
        variant: 'success',
        title: t('home.marketReviewSubmitted'),
        message: result.message,
      });
      scrollMarketReviewFeedbackIntoView();

      if (result.taskId) {
        await pollMarketReviewStatus(result.taskId);
      }
    } catch (err: unknown) {
      setMarketReviewError(getParsedApiError(err));
      setMarketReviewNotice(null);
      scrollMarketReviewFeedbackIntoView();
    } finally {
      setIsSubmittingMarketReview(false);
    }
  }, [notify, pollMarketReviewStatus, scrollMarketReviewFeedbackIntoView, t]);

  const mergedStockBarItems = useMemo<StockBarItem[]>(() => {
    const latestMarketReview = marketReviewHistoryItems[0];
    const stockItems = stockBarItems.filter((item) => item.stockCode !== 'MARKET');
    if (!latestMarketReview) {
      return stockItems;
    }

    const marketReviewItem: StockBarItem = {
      id: latestMarketReview.id,
      stockCode: 'MARKET',
      stockName: latestMarketReview.stockName || t('home.marketReview'),
      reportType: 'market_review',
      sentimentScore: latestMarketReview.sentimentScore,
      operationAdvice: latestMarketReview.operationAdvice,
      analysisCount: Math.max(marketReviewHistoryItems.length, 1),
      lastAnalysisTime: latestMarketReview.createdAt,
      modelUsed: latestMarketReview.modelUsed,
      marketPhaseSummary: latestMarketReview.marketPhaseSummary,
    };

    return [marketReviewItem, ...stockItems].sort((left, right) => {
      const leftTime = left.lastAnalysisTime ? Date.parse(left.lastAnalysisTime) : 0;
      const rightTime = right.lastAnalysisTime ? Date.parse(right.lastAnalysisTime) : 0;
      return rightTime - leftTime;
    });
  }, [marketReviewHistoryItems, stockBarItems, t]);

  const sidebarContent = useMemo(
    () => (
      <div className="flex min-h-0 h-full flex-col gap-3 overflow-hidden">
        <TaskPanel tasks={activeTasks} onOpenRunFlow={openTaskRunFlow} />
        <StockBar
          items={mergedStockBarItems}
          isLoading={isLoadingStockBar}
          selectedStockCode={selectedReport?.meta.stockCode}
          selectedRecordId={selectedReport?.meta.id}
          onItemClick={handleHistoryItemClick}
          onDeleteStock={handleDeleteStock}
          isDeleting={isDeletingStock}
          className="flex-1 overflow-hidden"
        />
      </div>
    ),
    [
      activeTasks,
      mergedStockBarItems,
      isLoadingStockBar,
      handleHistoryItemClick,
      handleDeleteStock,
      isDeletingStock,
      openTaskRunFlow,
      selectedReport?.meta.stockCode,
      selectedReport?.meta.id,
    ],
  );

  return (
    <div
      data-testid="home-dashboard"
      className="flex h-[calc(100vh-5rem)] w-full flex-col overflow-hidden md:flex-row sm:h-[calc(100vh-5.5rem)] lg:h-[calc(100vh-2rem)]"
    >
      <div className="flex-1 flex flex-col min-h-0 min-w-0 max-w-full lg:max-w-6xl mx-auto w-full">
        <header className="relative z-30 flex min-w-0 flex-shrink-0 items-center overflow-visible px-3 py-3 md:px-4 md:py-4">
          <div className="flex min-w-0 flex-1 flex-col gap-2.5 md:flex-row md:items-center">
            <div className="flex min-w-0 flex-1 items-center gap-2.5">
              <button
                onClick={() => setSidebarOpen(true)}
                className="md:hidden -ml-1 flex-shrink-0 rounded-lg p-1.5 text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
                aria-label={t('home.historyButton')}
              >
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>
              <div className="relative min-w-0 flex-1">
                <StockAutocomplete
                  value={query}
                  onChange={setQuery}
                  onSubmit={(stockCode, stockName, selectionSource) => {
                    handleSubmitAnalysis(stockCode, stockName, selectionSource);
                  }}
                  placeholder={t('home.placeholder')}
                  disabled={isAnalyzing}
                  className={inputError ? 'border-danger/50' : undefined}
                />
              </div>
              {analysisSkills.length > 0 ? (
                <div ref={strategyMenuRef} className="relative flex-shrink-0">
                  <button
                    ref={strategyButtonRef}
                    id="strategy-menu-button"
                    type="button"
                    aria-haspopup="menu"
                    aria-expanded={strategyMenuOpen}
                    aria-controls={strategyMenuOpen ? 'strategy-menu' : undefined}
                    onClick={() => setStrategyMenuOpen((open) => !open)}
                    onKeyDown={handleStrategyButtonKeyDown}
                    disabled={isAnalyzing}
                    className="home-surface-button flex h-10 max-w-[8.5rem] items-center gap-1.5 rounded-xl px-3 text-xs text-foreground disabled:cursor-not-allowed disabled:opacity-60 sm:max-w-[11rem]"
                  >
                    <SlidersHorizontal className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
                    <span className="truncate">{selectedStrategy?.name || t('home.strategy')}</span>
                  </button>
                  {strategyMenuOpen ? (
                    <div
                      id="strategy-menu"
                      role="menu"
                      aria-labelledby="strategy-menu-button"
                      onKeyDown={handleStrategyMenuKeyDown}
                      className="absolute right-0 top-11 z-[120] max-h-80 w-[min(18rem,calc(100vw-1.5rem))] overflow-y-auto rounded-xl border border-subtle bg-elevated p-1.5 text-sm text-foreground shadow-2xl"
                    >
                      {strategyOptions.map((option, index) => {
                        const selected = selectedStrategyId === option.id;
                        return (
                          <button
                            key={option.id || 'default'}
                            ref={(node) => {
                              strategyItemRefs.current[index] = node;
                            }}
                            type="button"
                            role="menuitemradio"
                            aria-checked={selected}
                            tabIndex={-1}
                            onClick={() => selectStrategy(option.id)}
                            className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-hover"
                          >
                            <Check className={`mt-0.5 h-4 w-4 flex-shrink-0 ${selected ? 'opacity-100' : 'opacity-0'}`} aria-hidden="true" />
                            <span className="min-w-0">
                              <span className="block font-medium">{option.name}</span>
                              <span className="mt-0.5 line-clamp-2 block text-xs leading-5 text-muted-text">{option.description}</span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div className="flex min-w-0 flex-shrink-0 items-center gap-2.5">
              <label className="flex h-10 flex-shrink-0 cursor-pointer items-center gap-1.5 rounded-xl border border-subtle bg-surface/60 px-3 text-xs text-secondary-text select-none transition-colors hover:border-subtle-hover hover:text-foreground">
                <input
                  type="checkbox"
                  checked={notify}
                  onChange={(e) => setNotify(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-border accent-primary"
                />
                {t('home.notify')}
              </label>
              <Button
                type="button"
                variant="secondary"
                size="md"
                isLoading={isSubmittingMarketReview}
                loadingText={t('home.submitMarketReview')}
                onClick={() => void handleTriggerMarketReview()}
                className="h-10 flex-1 whitespace-nowrap md:flex-none"
              >
                <BarChart3 className="h-4 w-4" aria-hidden="true" />
                {t('home.marketReview')}
              </Button>
              <button
                type="button"
                onClick={() => handleSubmitAnalysis()}
                disabled={!query || isAnalyzing}
                className="btn-primary flex h-10 flex-1 items-center justify-center gap-1.5 whitespace-nowrap md:flex-none"
              >
                {isAnalyzing ? (
                  <>
                    <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    {t('home.analyzing')}
                  </>
                ) : (
                  t('home.analyze')
                )}
              </button>
            </div>
          </div>
        </header>

        {inputError || (duplicateError && duplicateBannerVisible) ? (
          <div className="px-3 pb-2 md:px-4">
            {inputError ? (
              <InlineAlert
                variant="danger"
                title={t('home.inputInvalid')}
                message={inputError}
                className="rounded-xl px-3 py-2 text-xs shadow-none"
              />
            ) : null}
            {!inputError && duplicateError && duplicateBannerVisible ? (
              <InlineAlert
                variant="warning"
                title={t('home.duplicateTask')}
                message={duplicateError}
                action={(
                  <button
                    type="button"
                    onClick={dismissDuplicateBanner}
                    aria-label={t('common.close')}
                    className="-my-1 -mr-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg opacity-70 transition-colors hover:bg-warning/15 hover:opacity-100"
                  >
                    <X className="h-4 w-4" aria-hidden="true" />
                  </button>
                )}
                className="rounded-xl px-3 py-2 text-xs shadow-none"
              />
            ) : null}
          </div>
        ) : null}

        {setupNeedsAction ? (
          <div className="px-3 pb-2 md:px-4">
            <InlineAlert
              variant="warning"
              title={t('home.setupIncomplete')}
              message={
                setupMissingLabels
                  ? t('home.setupMissingWithLabels', { labels: setupMissingLabels })
                  : t('home.setupMissingGeneric')
              }
              action={(
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => navigate('/settings')}
                >
                  {t('home.goSettings')}
                </Button>
              )}
              className="rounded-xl px-3 py-2 text-xs shadow-none"
            />
          </div>
        ) : null}

        <div className="flex-1 flex min-h-0 overflow-hidden">
          <div className="hidden min-h-0 w-64 shrink-0 flex-col overflow-hidden pl-4 pb-4 md:flex lg:w-72">
            {sidebarContent}
          </div>

          {sidebarOpen ? (
            <div className="fixed inset-0 z-40 md:hidden" onClick={() => setSidebarOpen(false)}>
              <div className="page-drawer-overlay absolute inset-0" />
              <div
                className="dashboard-card absolute bottom-0 left-0 top-0 flex w-72 flex-col overflow-hidden !rounded-none !rounded-r-xl p-3 shadow-2xl"
                onClick={(event) => event.stopPropagation()}
              >
                {sidebarContent}
              </div>
            </div>
          ) : null}

          <section
            ref={dashboardScrollRef}
            data-testid="home-dashboard-scroll"
            className="flex-1 min-w-0 min-h-0 overflow-x-auto overflow-y-auto px-3 pb-4 md:px-6 touch-pan-y"
          >
            {marketReviewNotice ? (
              <div className="mb-3">
                <InlineAlert
                  variant={marketReviewNotice.variant}
                  title={marketReviewNotice.title}
                  message={marketReviewNotice.message}
                  className="rounded-xl px-3 py-2 text-xs shadow-none"
                />
              </div>
            ) : null}

            {marketReviewError ? (
              <div className="mb-3">
                <ApiErrorAlert
                  error={marketReviewError}
                  className="mb-1"
                  onDismiss={() => setMarketReviewError(null)}
                />
              </div>
            ) : null}

            {marketReviewReport ? (
              <MarketReviewReportView
                content={marketReviewReport}
                payload={marketReviewPayload}
                reportLanguage={liveMarketReviewLanguage}
                className="mb-3"
              />
            ) : null}

            {error ? (
              <ApiErrorAlert
                error={error}
                className="mb-3"
                onDismiss={clearError}
              />
            ) : null}
            {!marketReviewReport && isLoadingReport ? (
              <div className="flex h-full flex-col items-center justify-center">
                <DashboardStateBlock title={t('home.loadingReport')} loading />
              </div>
            ) : !marketReviewReport && selectedReport ? (
              <div className={isHistoryTrendOpen ? 'max-w-6xl space-y-4 pb-8' : 'max-w-4xl space-y-4 pb-8'}>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  {!isMarketReviewHistoryReport ? (
                    <>
                      <Button
                        variant="home-action-ai"
                        size="sm"
                        disabled={isAnalyzing || selectedReport.meta.id === undefined}
                        onClick={handleReanalyze}
                      >
                        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        {t('home.reanalyze')}
                      </Button>
                      <Button
                        variant="home-action-ai"
                        size="sm"
                        disabled={selectedReport.meta.id === undefined}
                        onClick={handleAskFollowUp}
                      >
                        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                        </svg>
                        {t('home.askAi')}
                      </Button>
                    </>
                  ) : (
                    <Button
                      variant="home-action-ai"
                      size="sm"
                      disabled={isSubmittingMarketReview}
                      isLoading={isSubmittingMarketReview}
                      loadingText={t('home.submitMarketReview')}
                      onClick={() => void handleTriggerMarketReview()}
                    >
                      <BarChart3 className="h-4 w-4" />
                      {t('home.rerunMarketReview')}
                    </Button>
                  )}
                  <Button
                    variant="home-action-ai"
                    size="sm"
                    disabled={selectedReport.meta.id === undefined || isHistoryTrendUnavailable}
                    className={isHistoryTrendOpen ? 'border-primary/70 bg-primary/15 text-primary shadow-glow-cyan' : undefined}
                    onClick={() => {
                      if (isHistoryTrendOpen) {
                        closeHistoryTrend();
                        return;
                      }
                      void openHistoryTrend();
                    }}
                  >
                    <BarChart3 className="h-4 w-4" />
                    {t('home.historyTrend')}
                  </Button>
                  <Button
                    variant="home-action-ai"
                    size="sm"
                    disabled={selectedReport.meta.id === undefined}
                    onClick={openMarkdownDrawer}
                  >
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    {t('home.fullReport')}
                  </Button>
                </div>
                {isHistoryTrendOpen ? (
                  <StockHistoryTrendDrawer
                    key={`stock-history-${selectedReport.meta.id}`}
                    report={selectedReport}
                    items={stockHistoryItems}
                    total={stockHistoryTotal}
                    hasMore={stockHistoryHasMore}
                    isLoading={isLoadingStockHistory}
                    isLoadingMore={isLoadingMoreStockHistory}
                    error={stockHistoryError}
                    filters={stockHistoryFilters}
                    onClose={closeHistoryTrend}
                    onRangeChange={(range) => void setStockHistoryRange(range)}
                    onLoadMore={() => void loadMoreStockHistory()}
                    onSelectRecord={(recordId) => void selectHistoryItem(recordId)}
                    onRetry={() => void openHistoryTrend()}
                  />
                ) : (
                  <ReportSummary
                    data={selectedReport}
                    isHistory
                    onOpenRunFlow={openHistoryRunFlow}
                    watchlist={{
                      isInWatchlist: watchlistState.isInWatchlist,
                      onToggle: watchlistState.toggleWatchlist,
                      isActioning: watchlistState.isActioning,
                      actionMessage: watchlistState.actionMessage,
                    }}
                  />
                )}
              </div>
            ) : !marketReviewReport ? (
              <div className="flex h-full items-center justify-center">
                <EmptyState
                  title={t('home.startAnalysisTitle')}
                  description={t('home.startAnalysisDescription')}
                  className="max-w-xl border-dashed"
                  icon={(
                    <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                    </svg>
                  )}
                />
              </div>
            ) : null}
          </section>
        </div>
      </div>

      {markdownDrawerOpen && selectedReport?.meta.id ? (
        <ReportMarkdownDrawer
          key={selectedReport.meta.id}
          recordId={selectedReport.meta.id}
          stockName={selectedReport.meta.stockName || ''}
          stockCode={selectedReport.meta.stockCode}
          reportLanguage={reportLanguage}
          onClose={closeMarkdownDrawer}
        />
      ) : null}

      {runFlowDrawer.open ? (
        <Drawer
          isOpen={runFlowDrawer.open}
          onClose={closeRunFlowDrawer}
          title={t('runFlow.drawerTitle')}
          width="max-w-[96vw]"
          zIndex={80}
        >
          <RunFlowPanel
            key={`${runFlowDrawer.source.type}-${runFlowDrawer.source.type === 'task' ? runFlowDrawer.source.taskId : runFlowDrawer.source.recordId}`}
            source={runFlowDrawer.source}
            title={runFlowDrawer.title}
          />
        </Drawer>
      ) : null}

    </div>
  );
};

export default HomePage;
