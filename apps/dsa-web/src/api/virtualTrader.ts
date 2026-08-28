import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  VirtualTraderAccount,
  VirtualTraderEquityCurve,
  VirtualTraderPredictionList,
  VirtualTraderRunResult,
  VirtualTraderStats,
  VirtualTraderTradeList,
} from '../types/virtualTrader';

export const virtualTraderApi = {
  async getAccount(): Promise<VirtualTraderAccount> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/virtual-trader/account');
    return toCamelCase<VirtualTraderAccount>(response.data);
  },

  async listTrades(params?: {
    market?: string;
    side?: string;
    page?: number;
    pageSize?: number;
  }): Promise<VirtualTraderTradeList> {
    const query: Record<string, string | number> = {
      page: params?.page ?? 1,
      page_size: params?.pageSize ?? 20,
    };
    if (params?.market) query.market = params.market;
    if (params?.side) query.side = params.side;
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/virtual-trader/trades', {
      params: query,
    });
    return toCamelCase<VirtualTraderTradeList>(response.data);
  },

  async listPredictions(params?: {
    status?: string;
    outcome?: string;
    page?: number;
    pageSize?: number;
  }): Promise<VirtualTraderPredictionList> {
    const query: Record<string, string | number> = {
      page: params?.page ?? 1,
      page_size: params?.pageSize ?? 20,
    };
    if (params?.status) query.status = params.status;
    if (params?.outcome) query.outcome = params.outcome;
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/virtual-trader/predictions', {
      params: query,
    });
    return toCamelCase<VirtualTraderPredictionList>(response.data);
  },

  async getEquityCurve(limit = 365): Promise<VirtualTraderEquityCurve> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/virtual-trader/equity-curve', {
      params: { limit },
    });
    return toCamelCase<VirtualTraderEquityCurve>(response.data);
  },

  async getStats(): Promise<VirtualTraderStats> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/virtual-trader/stats');
    return toCamelCase<VirtualTraderStats>(response.data);
  },

  async run(payload?: { market?: string; force?: boolean }): Promise<{ results: VirtualTraderRunResult[] }> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/virtual-trader/run', {
      market: payload?.market ?? null,
      force: payload?.force ?? false,
    });
    return toCamelCase<{ results: VirtualTraderRunResult[] }>(response.data);
  },

  async reset(): Promise<{ success: boolean; accountId: number }> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/virtual-trader/reset', {
      confirm: true,
    });
    return toCamelCase<{ success: boolean; accountId: number }>(response.data);
  },
};
