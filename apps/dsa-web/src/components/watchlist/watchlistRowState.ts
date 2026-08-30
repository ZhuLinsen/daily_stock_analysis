export interface WatchlistPendingAnalysisState {
  analyzedToday: boolean;
  isTodayStatusLoading?: boolean;
  isTodayStatusUnknown?: boolean;
  activeTask?: unknown;
}

export function isWatchlistRowPendingAnalysis(row: WatchlistPendingAnalysisState): boolean {
  return !row.analyzedToday && !row.isTodayStatusLoading && !row.isTodayStatusUnknown && !row.activeTask;
}
