import apiClient from './index';
import { toCamelCase } from './utils';
import type { SentimentReviewDate, SentimentReviewDetail, TrendPoint } from '../types/sentimentReview';

export const sentimentReviewApi = {
  run: async (tradeDate?: string, force = false): Promise<{ status: string; tradeDate: string }> => {
    const response = await apiClient.post('/api/v1/sentiment-review/run', {
      trade_date: tradeDate || null,
      market: 'cn',
      force,
    }, { timeout: 180000 });
    return toCamelCase(response.data);
  },
  dates: async (): Promise<SentimentReviewDate[]> => {
    const response = await apiClient.get('/api/v1/sentiment-review/dates');
    return toCamelCase(response.data);
  },
  detail: async (tradeDate: string): Promise<SentimentReviewDetail> => {
    const response = await apiClient.get(`/api/v1/sentiment-review/${tradeDate}`);
    return toCamelCase(response.data);
  },
  trend: async (metric: string, window: number): Promise<TrendPoint[]> => {
    const response = await apiClient.get('/api/v1/sentiment-review/trend', { params: { metric, window } });
    return toCamelCase(response.data);
  },
};
