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
export type DecisionSignalMarket = 'cn' | 'hk' | 'us' | 'jp' | 'kr' | 'tw';
export type DecisionSignalOutcomeEvalStatus = 'completed' | 'unable';
export type DecisionSignalOutcomeValue = 'hit' | 'miss' | 'neutral';
export type DecisionSignalFeedbackValue = 'useful' | 'not_useful';
export type DecisionSignalFeedbackSource = 'web' | 'api';
export type DecisionProfile = 'conservative' | 'balanced' | 'aggressive';
export type DecisionProfileDisplay = DecisionProfile | 'unknown';

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

export interface DecisionSignalWarning {
  code: string;
  message?: string | null;
  params?: Record<string, unknown> | null;
}

export interface DecisionSignalReassessRequest {
  sourceReportId: number;
  decisionProfile: DecisionProfile;
  persist?: false;
}

export interface DecisionSignalReassessPreview {
  action: DecisionAction;
  score?: number | null;
  confidence?: number | null;
  horizon?: DecisionSignalHorizon | null;
  entryLow?: number | null;
  entryHigh?: number | null;
  stopLoss?: number | null;
  targetPrice?: number | null;
  invalidation?: string | null;
  reason?: string | null;
  riskSummary?: string | null;
  watchConditions?: string | null;
  metadata: Record<string, unknown>;
}

export interface DecisionSignalReassessResponse {
  preview: DecisionSignalReassessPreview;
  item?: DecisionSignalItem | null;
  created: false;
  warnings: DecisionSignalWarning[];
  blockedReason?: string | null;
}

export interface DecisionSignalListResponse {
  items: DecisionSignalItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface DecisionSignalOutcomeItem {
  id: number;
  signalId: number;
  horizon: DecisionSignalHorizon;
  engineVersion: string;
  evalStatus: DecisionSignalOutcomeEvalStatus;
  outcome?: DecisionSignalOutcomeValue | null;
  directionExpected?: string | null;
  directionCorrect?: boolean | null;
  unableReason?: string | null;
  anchorDate?: string | null;
  evalWindowDays?: number | null;
  startPrice?: number | null;
  endClose?: number | null;
  maxHigh?: number | null;
  minLow?: number | null;
  stockReturnPct?: number | null;
  action?: DecisionAction | null;
  market?: DecisionSignalMarket | null;
  marketPhase?: MarketPhaseValue | null;
  sourceType?: DecisionSignalSourceType | null;
  sourceAgent?: string | null;
  planQuality?: DecisionSignalPlanQuality | null;
  dataQualityLevel?: string | null;
  holdingState: 'holding' | 'empty' | 'unknown';
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface DecisionSignalOutcomeRunRequest {
  signalId?: number;
  horizons?: DecisionSignalHorizon[];
  force?: boolean;
  market?: DecisionSignalMarket;
  stockCode?: string;
  action?: DecisionAction;
  sourceType?: DecisionSignalSourceType;
  status?: DecisionSignalStatus;
  limit?: number;
}

export interface DecisionSignalOutcomeRunResponse {
  items: DecisionSignalOutcomeItem[];
  evaluated: number;
  created: number;
  updated: number;
  skipped: number;
  engineVersion: string;
}

export interface DecisionSignalOutcomeListParams {
  signalId?: number;
  horizon?: DecisionSignalHorizon;
  engineVersion?: string;
  evalStatus?: DecisionSignalOutcomeEvalStatus;
  outcome?: DecisionSignalOutcomeValue;
  page?: number;
  pageSize?: number;
}

export interface DecisionSignalOutcomeListResponse {
  items: DecisionSignalOutcomeItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface DecisionSignalOutcomeStatsBucket {
  dimension: string;
  value: string;
  total: number;
  completed: number;
  unable: number;
  hit: number;
  miss: number;
  neutral: number;
  hitRatePct?: number | null;
  avgStockReturnPct?: number | null;
  unableReasons: Record<string, number>;
}

export interface DecisionSignalOutcomeStatsResponse {
  engineVersion: string;
  horizons?: DecisionSignalHorizon[] | null;
  statuses: DecisionSignalStatus[];
  total: number;
  completed: number;
  unable: number;
  hit: number;
  miss: number;
  neutral: number;
  hitRatePct?: number | null;
  avgStockReturnPct?: number | null;
  unableReasons: Record<string, number>;
  breakdowns: Record<string, DecisionSignalOutcomeStatsBucket[]>;
}

export interface DecisionSignalOutcomeStatsParams {
  horizons?: DecisionSignalHorizon[];
  engineVersion?: string;
  statuses?: DecisionSignalStatus[];
}

export interface DecisionSignalFeedbackItem {
  signalId: number;
  feedbackValue?: DecisionSignalFeedbackValue | null;
  reasonCode?: string | null;
  note?: string | null;
  source?: DecisionSignalFeedbackSource | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface DecisionSignalFeedbackRequest {
  feedbackValue: DecisionSignalFeedbackValue;
  reasonCode?: string | null;
  note?: string | null;
  source?: DecisionSignalFeedbackSource;
}
