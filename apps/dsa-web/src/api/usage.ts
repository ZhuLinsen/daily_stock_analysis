import apiClient from './index';
import { toCamelCase } from './utils';

export type UsagePeriod = 'today' | 'month' | 'all';

export type UsageCallTypeBreakdown = {
  callType: string;
  calls: number;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
};

export type UsageModelBreakdown = {
  model: string;
  calls: number;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  maxTotalTokens: number;
};

export type UsageCallRecord = {
  id: number;
  calledAt: string;
  callType: string;
  model: string;
  stockCode?: string | null;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
};

export type UsageDashboard = {
  period: UsagePeriod;
  fromDate: string;
  toDate: string;
  totalCalls: number;
  totalPromptTokens: number;
  totalCompletionTokens: number;
  totalTokens: number;
  byCallType: UsageCallTypeBreakdown[];
  byModel: UsageModelBreakdown[];
  recentCalls: UsageCallRecord[];
};

export const usageApi = {
  getDashboard: async (params: { period?: UsagePeriod; limit?: number } = {}): Promise<UsageDashboard> => {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/usage/dashboard', {
      params: {
        period: params.period ?? 'month',
        limit: params.limit ?? 50,
      },
    });

    return toCamelCase<UsageDashboard>(response.data);
  },
};
