import apiClient from './index';
import { toCamelCase } from './utils';

export type NewsAnalysis = {
  summary: string;
  direction: 'POSITIVE' | 'NEGATIVE' | 'MIXED' | 'UNCERTAIN';
  confidence: number;
  timeHorizon: string;
  positiveFactors: string[];
  negativeFactors: string[];
  risks: string[];
  action: string;
  actionReason: string;
  sourceUrls: string[];
  dataTime: string;
};

export type PersonalNewsItem = {
  id: number;
  title: string;
  url: string;
  source: string;
  summary: string;
  symbols: string[];
  publishedAt: string | null;
  fetchedAt: string;
  importanceScore: number;
  scoreReasons: string[];
  sourceCount: number;
  priceChangePercent: number | null;
  volumeChangePercent: number | null;
  isAnnouncement: boolean;
  analysis: NewsAnalysis | null;
  analysisStatus: string;
  analysisError: string | null;
};

export type ProviderStatus = {
  provider: string;
  providerType: string;
  status: string;
  message: string;
  checkedAt: string;
};

export const personalNewsApi = {
  async list(): Promise<PersonalNewsItem[]> {
    const response = await apiClient.get('/personal-news', { params: { limit: 100 } });
    return toCamelCase<PersonalNewsItem[]>(response.data);
  },
  async get(newsId: string): Promise<PersonalNewsItem> {
    const response = await apiClient.get(`/personal-news/${encodeURIComponent(newsId)}`);
    return toCamelCase<PersonalNewsItem>(response.data);
  },
  async providers(): Promise<ProviderStatus[]> {
    const response = await apiClient.get('/personal-news/providers');
    return toCamelCase<ProviderStatus[]>(response.data);
  },
};
