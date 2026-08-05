import apiClient from './index';
import { systemConfigApi } from './systemConfig';
import { toCamelCase } from './utils';

const SCREENING_SCREEN_TIMEOUT_MS = 180000;
const SCREENING_REQUEST_TIMEOUT_MS = 300000;
const SCREENING_VARIANT_SEED_KEY = 'dsa.screening.variantSeed.v1';
let screeningVariantSessionSeed = '';
export const SCREENING_CONFIG_CHANGED_EVENT = 'screening-config-changed';
export const SYSTEM_CONFIG_CHANGED_EVENT = 'dsa-system-config-changed';

export type ScreeningStatus = {
  enabled: boolean;
  available: boolean;
  engine?: 'builtin' | string;
  contractVersion?: string | null;
  version?: string | null;
  strategyCount?: number | null;
  referenceProject?: string | null;
  referenceRevision?: string | null;
  sourceHealth?: Record<string, Record<string, Record<string, unknown>>>;
  diagnostics?: Record<string, string>;
};

export type ScreeningCandidate = {
  rank: number;
  code: string;
  name: string;
  score?: number | null;
  screenScore?: number | null;
  reason: string;
  riskLevel?: string;
  riskFlags?: string[];
  llmScore?: number | null;
  llmConfidence?: number | null;
  llmSector?: string;
  llmTheme?: string;
  llmTags?: string[];
  llmThesis?: string;
  llmCatalysts?: string[];
  llmRisks?: string[];
  llmWatchItems?: string[];
  llmInvalidators?: string[];
  llmStyleFit?: string;
  price?: number | null;
  changePct?: number | null;
  amount?: number | null;
  industry?: string;
  factorScores?: Record<string, number>;
  postAnalysisSummaries?: Record<string, string>;
  postAnalysisTags?: string[];
  dsaContext?: {
    enriched?: boolean;
    quote?: Record<string, unknown>;
    fundamentals?: Record<string, unknown>;
    news?: {
      success?: boolean;
      query?: string;
      provider?: string;
      results?: Array<Record<string, unknown>>;
      error?: string | null;
    };
    events?: {
      success?: boolean;
      query?: string;
      provider?: string;
      results?: Array<Record<string, unknown>>;
      error?: string | null;
    };
    warnings?: string[];
  };
  dsaNews?: Array<{
    title?: string;
    snippet?: string;
    url?: string;
    source?: string;
    publishedDate?: string | null;
  }>;
  dsaEvents?: Array<{
    title?: string;
    snippet?: string;
    url?: string;
    source?: string;
    publishedDate?: string | null;
  }>;
  dsaAnalysisSummary?: string;
  raw: Record<string, unknown>;
};

export type ScreeningStrategy = {
  id: string;
  name: string;
  title?: string;
  description: string;
  version?: string;
  category?: string;
  tag?: string;
  tags?: string[];
  analysisSkills?: string[];
  marketScope?: string[];
  market?: string;
};

export type ScreeningStrategiesResponse = {
  enabled: boolean;
  strategies: ScreeningStrategy[];
  strategyCount: number;
};

export type ScreeningHotspot = {
  topic: string;
  name?: string;
  source?: string;
  rank?: number | null;
  changePct?: number | null;
  heatScore?: number | null;
  trendScore?: number | null;
  persistenceScore?: number | null;
  coolingScore?: number | null;
  observations?: number | null;
  state?: string;
  stage?: string;
  sampleStockCount?: number | null;
  leaders?: string[];
  leaderStocks?: ScreeningHotspotStock[];
  qualityStatus?: 'available' | 'partial' | 'stale' | 'failed' | string;
  missingFields?: string[];
  providerUsed?: string;
  fallbackUsed?: boolean;
  cacheUsed?: boolean;
  cachedAt?: string | null;
  sourceErrors?: string[];
  stale?: boolean;
  staleAgeHours?: number | null;
};

export type ScreeningHotspotRouteItem = {
  title: string;
  description: string;
  source?: string;
  date?: string;
  time?: string;
  publishedAt?: string;
  url?: string;
  searchResult?: boolean;
};

export type ScreeningHotspotStock = {
  code?: string;
  name?: string;
  changePct?: number | null;
  amount?: number | null;
  turnoverRate?: number | null;
  volumeRatio?: number | null;
  role?: string;
  hotStockScore?: number | null;
  source?: string;
  sourceConfidence?: number | null;
  fallbackUsed?: boolean;
};

export type ScreeningHotspotDetail = {
  enabled: boolean;
  provider: string;
  topic: string;
  name?: string;
  canonicalTopic?: string;
  aliases?: string[];
  summary?: string;
  summaryDetail?: Record<string, unknown>;
  route: ScreeningHotspotRouteItem[];
  timeline?: ScreeningHotspotRouteItem[];
  stocks: ScreeningHotspotStock[];
  leaderStocks?: ScreeningHotspotStock[];
  stockCount: number;
  sourceErrors?: string[];
  qualityStatus?: 'available' | 'partial' | 'stale' | 'failed' | string;
  missingFields?: string[];
  fallbackUsed?: boolean;
  stale?: boolean;
  staleAgeHours?: number | null;
  cacheUsed?: boolean;
  cachedAt?: string | null;
  resolverCandidates?: Record<string, unknown>[];
  newsSearchRequested?: boolean;
  newsSearchStatus?: 'available' | 'no_results' | 'unavailable' | string;
};

export type ScreeningHotspotsResponse = {
  enabled: boolean;
  provider: string;
  providerUsed?: string;
  fallbackUsed?: boolean;
  cacheUsed?: boolean;
  cachedAt?: string | null;
  sourceErrors?: string[];
  stale?: boolean;
  staleAgeHours?: number | null;
  message?: string | null;
  hotspots: ScreeningHotspot[];
  hotspotCount: number;
  details?: Record<string, ScreeningHotspotDetail>;
};

export type ScreeningScreenResponse = {
  enabled: boolean;
  candidates: ScreeningCandidate[];
  candidateCount: number;
  runId?: string;
  strategy?: string;
  market?: string;
  snapshotCount?: number;
  afterFilterCount?: number;
  llmRanked?: boolean;
  llmMarketView?: string;
  llmSelectionLogic?: string;
  llmPortfolioRisk?: string;
  llmCoverage?: number | null;
  llmParseErrors?: string[];
  llmModelUsed?: string;
  llmAttemptedModels?: string[];
  llmFailureReason?: 'invalid_response' | 'timeout' | 'call_failed' | 'no_model_configured' | string;
  rankingMode?: 'llm' | 'factor' | string;
  warnings?: string[];
  sourceErrors?: string[];
  dsaEnrichment?: {
    enabled?: boolean;
    maxCandidates?: number;
    requestedCount?: number;
    enrichedCount?: number;
    warnings?: string[];
  };
  deepAnalysisRequested?: boolean | null;
  postAnalyzers?: string[];
  dailyEnriched?: boolean | null;
  dailyEnrichCount?: number | null;
  riskEnabled?: boolean | null;
  portfolioDiversityEnabled?: boolean | null;
  portfolioConcentrationNotes?: string[];
  resultVariantApplied?: boolean;
  resultVariantPoolSize?: number;
  resultVariantRotatedSlots?: number;
};

export type ScreeningScreenAccepted = {
  taskId: string;
  traceId?: string | null;
  status: 'pending' | 'processing' | 'completed' | 'failed' | string;
  message: string;
  strategy: string;
  market: string;
  maxResults: number;
};

export type ScreeningScreenTaskStatus = {
  taskId: string;
  traceId?: string | null;
  status: 'pending' | 'processing' | 'completed' | 'failed' | string;
  progress?: number | null;
  message?: string | null;
  error?: string | null;
  result?: ScreeningScreenResponse | null;
};

export type ScreeningRunSummary = {
  runId: string;
  strategy: string;
  market: string;
  snapshotSource?: string;
  snapshotCount?: number | null;
  afterFilterCount?: number | null;
  candidateCount: number;
  llmRanked?: boolean | null;
  dailyEnriched?: boolean | null;
  sourceErrors?: string[];
  warnings?: string[];
  createdAt?: string | null;
};

export type ScreeningHistoryResponse = {
  enabled: boolean;
  runs: ScreeningRunSummary[];
  runCount: number;
};

export type ScreeningRunDetail = ScreeningRunSummary & {
  enabled: boolean;
  result: ScreeningScreenResponse;
};

export type ScreeningSourceHistory = {
  enabled: boolean;
  runsAnalyzed: number;
  fallbackRuns: number;
  sources: Record<string, {
    selectedRuns: number;
    errorCount: number;
    lastSeenAt?: string | null;
    errorSamples: string[];
  }>;
};

export function notifyScreeningConfigChanged(): void {
  window.dispatchEvent(new Event(SCREENING_CONFIG_CHANGED_EVENT));
  notifySystemConfigChanged();
}

export function notifySystemConfigChanged(): void {
  window.dispatchEvent(new Event(SYSTEM_CONFIG_CHANGED_EVENT));
}

export function getScreeningVariantSeed(): string {
  if (typeof window === 'undefined') {
    return '';
  }
  try {
    const existing = window.localStorage.getItem(SCREENING_VARIANT_SEED_KEY)?.trim();
    if (existing) {
      screeningVariantSessionSeed = existing;
      return existing;
    }
  } catch {
    // Storage may be disabled by browser privacy settings. Fall through to the
    // module-level session seed so all screening entry points stay consistent.
  }
  if (screeningVariantSessionSeed) {
    return screeningVariantSessionSeed;
  }
  const generated = typeof window.crypto?.randomUUID === 'function'
    ? window.crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  screeningVariantSessionSeed = generated;
  try {
    window.localStorage.setItem(SCREENING_VARIANT_SEED_KEY, generated);
  } catch {
    // Best-effort persistence only. The module-level value remains stable for
    // the current page session when Web Storage is unavailable.
  }
  return generated;
}

async function setScreeningEnabled(value: 'true' | 'false'): Promise<void> {
  const config = await systemConfigApi.getConfig(false);
  await systemConfigApi.update({
    configVersion: config.configVersion,
    maskToken: config.maskToken,
    reloadNow: true,
    items: [{ key: 'SCREENING_ENABLED', value }],
  });
  notifyScreeningConfigChanged();
}

export const screeningApi = {
  async getStatus(): Promise<ScreeningStatus> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/screening/status');
    return toCamelCase<ScreeningStatus>(response.data);
  },

  async screen(payload: { market: string; strategy: string; maxResults: number }): Promise<ScreeningScreenResponse> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/screening/screen', {
      market: payload.market,
      strategy: payload.strategy,
      max_results: payload.maxResults,
      variant_seed: getScreeningVariantSeed(),
    }, { timeout: SCREENING_SCREEN_TIMEOUT_MS });
    return toCamelCase<ScreeningScreenResponse>(response.data);
  },

  async startScreen(payload: { market: string; strategy: string; maxResults: number }): Promise<ScreeningScreenAccepted> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/screening/screen/tasks', {
      market: payload.market,
      strategy: payload.strategy,
      max_results: payload.maxResults,
      variant_seed: getScreeningVariantSeed(),
    });
    return toCamelCase<ScreeningScreenAccepted>(response.data);
  },

  async getScreenTask(taskId: string): Promise<ScreeningScreenTaskStatus> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/screening/screen/tasks/${encodeURIComponent(taskId)}`);
    return toCamelCase<ScreeningScreenTaskStatus>(response.data);
  },

  async getHistory(payload: { limit?: number; strategy?: string; market?: string } = {}): Promise<ScreeningHistoryResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/screening/history', {
      params: {
        limit: payload.limit ?? 20,
        strategy: payload.strategy || undefined,
        market: payload.market || undefined,
      },
    });
    return toCamelCase<ScreeningHistoryResponse>(response.data);
  },

  async getRun(runId: string): Promise<ScreeningRunDetail> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/screening/history/${encodeURIComponent(runId)}`);
    return toCamelCase<ScreeningRunDetail>(response.data);
  },

  async getSourceHistory(limit = 100): Promise<ScreeningSourceHistory> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/screening/source-history', {
      params: { limit },
    });
    return toCamelCase<ScreeningSourceHistory>(response.data);
  },

  async getStrategies(): Promise<ScreeningStrategiesResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/screening/strategies', { timeout: SCREENING_REQUEST_TIMEOUT_MS });
    return toCamelCase<ScreeningStrategiesResponse>(response.data);
  },

  async getHotspots(payload: { provider?: string; top?: number; refresh?: boolean; includeDetails?: boolean } = {}): Promise<ScreeningHotspotsResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/screening/hotspots', {
      params: {
        provider: payload.provider || 'akshare',
        top: payload.top ?? 12,
        refresh: payload.refresh ?? false,
        include_details: payload.includeDetails ?? false,
      },
      timeout: SCREENING_REQUEST_TIMEOUT_MS,
    });
    const normalized = toCamelCase<ScreeningHotspotsResponse>(response.data);
    if (normalized.details) {
      const detailsByTopic: Record<string, ScreeningHotspotDetail> = {};
      Object.values(normalized.details).forEach((detail) => {
        if (detail?.topic) {
          detailsByTopic[detail.topic] = detail;
        }
      });
      normalized.details = { ...normalized.details, ...detailsByTopic };
    }
    return normalized;
  },

  async getHotspotDetail(payload: {
    topic: string;
    provider?: string;
    refresh?: boolean;
    includeSearch?: boolean;
  }): Promise<ScreeningHotspotDetail> {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/screening/hotspots/${encodeURIComponent(payload.topic)}`,
      {
        params: {
          provider: payload.provider || 'akshare',
          refresh: payload.refresh ?? false,
          include_search: payload.includeSearch ?? false,
        },
        timeout: SCREENING_REQUEST_TIMEOUT_MS,
      },
    );
    return toCamelCase<ScreeningHotspotDetail>(response.data);
  },

  async enable(): Promise<void> {
    await setScreeningEnabled('true');
    try {
      const status = await screeningApi.getStatus();
      if (!status.available) {
        throw new Error('选股功能不可用。请检查策略配置、数据依赖和服务日志。');
      }
    } catch (error) {
      try {
        await setScreeningEnabled('false');
      } catch {
        // Preserve the original availability/status failure for the caller.
      }
      throw error;
    }
  },
};
