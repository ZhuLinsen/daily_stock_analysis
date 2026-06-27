import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  WorkbenchDashboard,
  WorkbenchDailyReview,
  WorkbenchFundResponse,
  WorkbenchMarkdown,
  WorkbenchStockDetail,
  WorkbenchWatchlist,
} from '../types/workbench';

const WORKBENCH_TIMEOUT_MS = 20000;

export const workbenchApi = {
  async getDashboard(): Promise<WorkbenchDashboard> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/workbench/dashboard', { timeout: WORKBENCH_TIMEOUT_MS });
    return toCamelCase<WorkbenchDashboard>(response.data);
  },

  async getWatchlist(entryBudget = 10000): Promise<WorkbenchWatchlist> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/workbench/watchlist', {
      params: { entry_budget: entryBudget },
      timeout: WORKBENCH_TIMEOUT_MS,
    });
    return toCamelCase<WorkbenchWatchlist>(response.data);
  },

  async getStockDetail(symbol: string): Promise<WorkbenchStockDetail> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/workbench/stocks/${encodeURIComponent(symbol)}`, { timeout: WORKBENCH_TIMEOUT_MS });
    return toCamelCase<WorkbenchStockDetail>(response.data);
  },

  async getDailyReview(): Promise<WorkbenchDailyReview> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/workbench/daily-review', { timeout: WORKBENCH_TIMEOUT_MS });
    return toCamelCase<WorkbenchDailyReview>(response.data);
  },

  async exportDailyReviewMarkdown(): Promise<WorkbenchMarkdown> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/workbench/daily-review/markdown', { timeout: WORKBENCH_TIMEOUT_MS });
    return toCamelCase<WorkbenchMarkdown>(response.data);
  },

  async getFundAnalysis(fundCode: string, budget = 10000): Promise<WorkbenchFundResponse> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/workbench/funds/${encodeURIComponent(fundCode)}`, {
      params: { budget },
      timeout: WORKBENCH_TIMEOUT_MS,
    });
    return toCamelCase<WorkbenchFundResponse>(response.data);
  },
};
