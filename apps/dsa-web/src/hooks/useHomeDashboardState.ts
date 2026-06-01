import { useMemo } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useStockPoolStore } from '../stores';

/**
 * Keep HomePage focused on local UI state while the store owns dashboard business state.
 * This preserves the current visual contract and only centralizes state selection.
 */
export function useHomeDashboardState() {
  const dashboardState = useStockPoolStore(
    useShallow((state) => ({
      query: state.query,
      inputError: state.inputError,
      duplicateError: state.duplicateError,
      error: state.error,
      isAnalyzing: state.isAnalyzing,
      historyItems: state.historyItems,
      selectedHistoryIds: state.selectedHistoryIds,
      isDeletingHistory: state.isDeletingHistory,
      isLoadingHistory: state.isLoadingHistory,
      isLoadingMore: state.isLoadingMore,
      hasMore: state.hasMore,
      selectedReport: state.selectedReport,
      isLoadingReport: state.isLoadingReport,
      isHistoryTrendOpen: state.isHistoryTrendOpen,
      stockHistoryItems: state.stockHistoryItems,
      stockHistoryTotal: state.stockHistoryTotal,
      stockHistoryHasMore: state.stockHistoryHasMore,
      isLoadingStockHistory: state.isLoadingStockHistory,
      isLoadingMoreStockHistory: state.isLoadingMoreStockHistory,
      stockHistoryError: state.stockHistoryError,
      stockHistoryFilters: state.stockHistoryFilters,
      activeTasks: state.activeTasks,
      markdownDrawerOpen: state.markdownDrawerOpen,
      notify: state.notify,
      setQuery: state.setQuery,
      setNotify: state.setNotify,
      clearError: state.clearError,
      loadInitialHistory: state.loadInitialHistory,
      refreshHistory: state.refreshHistory,
      loadMoreHistory: state.loadMoreHistory,
      selectHistoryItem: state.selectHistoryItem,
      toggleHistorySelection: state.toggleHistorySelection,
      toggleSelectAllVisible: state.toggleSelectAllVisible,
      deleteSelectedHistory: state.deleteSelectedHistory,
      submitAnalysis: state.submitAnalysis,
      syncTaskCreated: state.syncTaskCreated,
      syncTaskUpdated: state.syncTaskUpdated,
      syncTaskFailed: state.syncTaskFailed,
      refreshActiveTasks: state.refreshActiveTasks,
      removeTask: state.removeTask,
      openMarkdownDrawer: state.openMarkdownDrawer,
      closeMarkdownDrawer: state.closeMarkdownDrawer,
      openHistoryTrend: state.openHistoryTrend,
      closeHistoryTrend: state.closeHistoryTrend,
      setStockHistoryRange: state.setStockHistoryRange,
      loadMoreStockHistory: state.loadMoreStockHistory,
    })),
  );

  const selectedIds = useMemo(
    () => new Set(dashboardState.selectedHistoryIds),
    [dashboardState.selectedHistoryIds],
  );

  return {
    ...dashboardState,
    selectedIds,
  };
}

export default useHomeDashboardState;
