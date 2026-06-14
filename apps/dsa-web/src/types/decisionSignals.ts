import type { DecisionAction, MarketPhaseValue, ReportLanguage } from './analysis';

/**
 * Opaque JSON fields are passed through without inner key-name conversion.
 * Only the containing DecisionSignal API field is mapped between camelCase and snake_case.
 */
export type DecisionSignalOpaqueJson = unknown;

export type DecisionSignalSourceType = 'analysis' | 'agent' | 'alert' | 'market_review' | 'manual';
export type DecisionSignalStatus = 'active' | 'expired' | 'invalidated' | 'closed' | 'archived';
export type DecisionSignalPlanQuality = 'complete' | 'partial' | 'minimal' | 'unknown';
export type DecisionSignalHorizon = 'intraday' | '1d' | '3d' | '5d' | '10d' | 'swing' | 'long';
export type DecisionSignalMarket = 'cn' | 'hk' | 'us';

export interface DecisionSignalItem {
  id: number;
  stockCode: string;
  stockName?: string | null;
  market: DecisionSignalMarket;
  sourceType: DecisionSignalSourceType;
  sourceAgent?: string | null;
  sourceReportId?: number | null;
  traceId?: string | null;
  marketPhase?: MarketPhaseValue | null;
  triggerSource: string;
  action: DecisionAction;
  actionLabel?: string | null;
  confidence?: number | null;
  score?: number | null;
  horizon?: DecisionSignalHorizon | null;
  entryLow?: number | null;
  entryHigh?: number | null;
  stopLoss?: number | null;
  targetPrice?: number | null;
  invalidation?: string | null;
  watchConditions?: string | null;
  reason?: string | null;
  riskSummary?: string | null;
  catalystSummary?: string | null;
  evidence?: DecisionSignalOpaqueJson;
  dataQualitySummary?: DecisionSignalOpaqueJson;
  planQuality: DecisionSignalPlanQuality;
  status: DecisionSignalStatus;
  expiresAt?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  metadata?: DecisionSignalOpaqueJson;
}

export interface DecisionSignalCreateRequest {
  stockCode: string;
  stockName?: string | null;
  market: DecisionSignalMarket;
  sourceType: DecisionSignalSourceType;
  sourceAgent?: string | null;
  sourceReportId?: number | null;
  traceId?: string | null;
  marketPhase?: MarketPhaseValue | null;
  triggerSource: string;
  action: DecisionAction;
  actionLabel?: string | null;
  confidence?: number | null;
  score?: number | null;
  horizon?: DecisionSignalHorizon | null;
  entryLow?: number | null;
  entryHigh?: number | null;
  stopLoss?: number | null;
  targetPrice?: number | null;
  invalidation?: unknown;
  watchConditions?: unknown;
  reason?: unknown;
  riskSummary?: unknown;
  catalystSummary?: unknown;
  evidence?: DecisionSignalOpaqueJson;
  dataQualitySummary?: DecisionSignalOpaqueJson;
  planQuality?: DecisionSignalPlanQuality | null;
  status?: DecisionSignalStatus | null;
  expiresAt?: string | null;
  /** Opaque JSON object; inner keys are sent exactly as provided. */
  metadata?: Record<string, unknown> | null;
  reportLanguage?: ReportLanguage | null;
}

export interface DecisionSignalListParams {
  market?: DecisionSignalMarket;
  stockCode?: string;
  action?: DecisionAction;
  marketPhase?: MarketPhaseValue;
  sourceType?: DecisionSignalSourceType;
  sourceReportId?: number;
  traceId?: string;
  triggerSource?: string;
  status?: DecisionSignalStatus;
  createdFrom?: string;
  createdTo?: string;
  expiresFrom?: string;
  expiresTo?: string;
  holdingOnly?: boolean;
  accountId?: number;
  page?: number;
  pageSize?: number;
}

export interface DecisionSignalLatestParams {
  market?: DecisionSignalMarket;
  limit?: number;
}

export interface DecisionSignalStatusUpdateRequest {
  status: DecisionSignalStatus;
  /** Replaces the persisted metadata object when provided; inner keys are not converted or merged. */
  metadata?: Record<string, unknown> | null;
}

export interface DecisionSignalMutationResponse {
  item: DecisionSignalItem;
  created: boolean;
}

export interface DecisionSignalListResponse {
  items: DecisionSignalItem[];
  total: number;
  page: number;
  pageSize: number;
}
