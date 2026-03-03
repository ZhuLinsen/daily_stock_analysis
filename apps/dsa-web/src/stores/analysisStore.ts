import { create } from 'zustand';
import type { AnalysisResult, AnalysisReport } from '../types/analysis';

interface AnalysisState {
  // 分析状态
  isLoading: boolean;
  result: AnalysisResult | null;
  error: string | null;

  // 历史报告视图
  isHistoryView: boolean;
  historyReport: AnalysisReport | null;

  // Actions
  setLoading: (loading: boolean) => void;
  setResult: (result: AnalysisResult | null) => void;
  setError: (error: string | null) => void;
  setHistoryReport: (report: AnalysisReport | null) => void;
  reset: () => void;
  resetToAnalysis: () => void;
}

export const useAnalysisStore = create<AnalysisState>((set) => ({
  // 初始状态
  isLoading: false,
  result: null,
  error: null,
  isHistoryView: false,
  historyReport: null,

  // Actions
  setLoading: (loading) => set({ isLoading: loading }),

  setResult: (result) =>
    set({
      result,
      error: null,
      isHistoryView: false,
      historyReport: null,
    }),

  setError: (error) => set({ error, isLoading: false }),

  setHistoryReport: (report) =>
    set({
      historyReport: report,
      isHistoryView: true,
      result: null,
      error: null,
      isLoading: false,
    }),

  reset: () =>
    set({
      isLoading: false,
      result: null,
      error: null,
      isHistoryView: false,
      historyReport: null,
    }),

  resetToAnalysis: () =>
    set({
      isHistoryView: false,
      historyReport: null,
    }),
}));
