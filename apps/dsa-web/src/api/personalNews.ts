import apiClient from './index';
import { toCamelCase } from './utils';

const PERSONAL_NEWS_API_PATH = '/api/v1/personal-news';

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
  invalidationConditions: string[];
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

export type WatchlistItem = { symbol: string; name: string };

export type RefreshStatus = {
  status: 'started' | 'running' | 'cooldown' | 'completed' | 'failed';
  lastRefreshAt: string | null;
  nextAllowedRefreshAt: string | null;
  error?: string | null;
  stats?: ({ new?: number; analyzed?: number; pushed?: number; errors?: number } & Record<string, unknown>) | null;
  newArticleIds?: number[];
  message?: string;
};

export const personalNewsApi = {
  async list(): Promise<PersonalNewsItem[]> {
    const response = await apiClient.get(PERSONAL_NEWS_API_PATH, { params: { limit: 100 } });
    return toCamelCase<PersonalNewsItem[]>(response.data);
  },
  async get(newsId: string): Promise<PersonalNewsItem> {
    const response = await apiClient.get(`${PERSONAL_NEWS_API_PATH}/${encodeURIComponent(newsId)}`);
    return toCamelCase<PersonalNewsItem>(response.data);
  },
  async providers(): Promise<ProviderStatus[]> {
    const response = await apiClient.get(`${PERSONAL_NEWS_API_PATH}/providers`);
    return toCamelCase<ProviderStatus[]>(response.data);
  },
  async watchlist(): Promise<WatchlistItem[]> {
    const response = await apiClient.get(`${PERSONAL_NEWS_API_PATH}/watchlist`);
    return toCamelCase<WatchlistItem[]>(response.data);
  },
  async addWatchlist(symbols: string): Promise<{ items: WatchlistItem[]; added: string[]; refresh: RefreshStatus | null }> {
    const response = await apiClient.post(`${PERSONAL_NEWS_API_PATH}/watchlist`, { symbols });
    return toCamelCase(response.data);
  },
  async deleteWatchlist(symbol: string): Promise<WatchlistItem[]> {
    const response = await apiClient.delete(`${PERSONAL_NEWS_API_PATH}/watchlist/${encodeURIComponent(symbol)}`);
    return toCamelCase<WatchlistItem[]>(response.data);
  },
  async refresh(trigger: 'page_open' | 'manual' = 'manual'): Promise<RefreshStatus> {
    const response = await apiClient.post(`${PERSONAL_NEWS_API_PATH}/refresh`, { trigger });
    return toCamelCase<RefreshStatus>(response.data);
  },
  async refreshStatus(): Promise<RefreshStatus> {
    const response = await apiClient.get(`${PERSONAL_NEWS_API_PATH}/refresh/status`);
    return toCamelCase<RefreshStatus>(response.data);
  },
};
