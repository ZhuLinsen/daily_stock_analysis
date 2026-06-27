import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  WorkbenchDashboard,
  WorkbenchDailyReview,
  WorkbenchMarkdown,
  WorkbenchStockDetail,
  WorkbenchWatchlist,
} from '../types/workbench';

export const workbenchApi = {
  async getDashboard(): Promise<WorkbenchDashboard> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/workbench/dashboard');
    return toCamelCase<WorkbenchDashboard>(response.data);
  },

  async getWatchlist(): Promise<WorkbenchWatchlist> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/workbench/watchlist');
    return toCamelCase<WorkbenchWatchlist>(response.data);
  },

  async getStockDetail(symbol: string): Promise<WorkbenchStockDetail> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/workbench/stocks/${encodeURIComponent(symbol)}`);
    return toCamelCase<WorkbenchStockDetail>(response.data);
  },

  async getDailyReview(): Promise<WorkbenchDailyReview> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/workbench/daily-review');
    return toCamelCase<WorkbenchDailyReview>(response.data);
  },

  async exportDailyReviewMarkdown(): Promise<WorkbenchMarkdown> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/workbench/daily-review/markdown');
    return toCamelCase<WorkbenchMarkdown>(response.data);
  },
};
