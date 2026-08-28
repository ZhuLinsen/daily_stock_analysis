import apiClient from './index';
import { toCamelCase } from './utils';
import type { MarketStatusResponse } from '../types/marketStatus';

export const marketStatusApi = {
  getStatus: async (): Promise<MarketStatusResponse> => {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/market/status');
    return toCamelCase<MarketStatusResponse>(response.data);
  },
};
