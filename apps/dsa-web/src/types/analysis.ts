/**
 * Analysis-related type definitions.
 * Aligned with the API schema.
 */

// ============ Request Types ============

export type StockReportType = 'simple' | 'detailed' | 'full' | 'brief';
export type ReportType = StockReportType | 'market_review';
export type AnalysisPhase = 'auto' | 'premarket' | 'intraday' | 'postmarket';

export interface AnalysisRequest {
  stockCode?: string;
  stockCodes?: string[];
  reportType?: StockReportType;
  forceRefresh?: boolean;
  asyncMode?: boolean;
  analysisPhase?: AnalysisPhase;
  stockName?: string;
  originalQuery?: string;
  selectionSource?: 'manual' | 'autocomplete' | 'import' | 'image';
  notify?: boolean;
  skills?: string[];
}

export interface MarketReviewRequest {
  sendNotification?: boolean;
}

export interface MarketReviewAccepted {
  status: 'accepted';
  message: string;
  sendNotification: boolean;
  traceId?: string;
  taskId?: string;
}

// ============ Report Types ============

export type ReportLanguage = 'zh' | 'en' | 'zh_TW';

export type MarketPhaseValue =
  | 'premarket'
  | 'intraday'
  | 'lunch_break'
  | 'closing_auction'
  | 'postmarket'
  | 'non_trading'
  | 'unknown';

export interface MarketPhaseSummary {
  market?: string | null;
  phase: MarketPhaseValue;
  marketLocalTime?: string | null;
  sessionDate?: string | null;
  effectiveDailyBarDate?: string | null;
  isTradingDay?: boolean | null;
  isMarketOpenNow?: boolean | null;
  isPartialBar?: boolean | null;
  minutesToOpen?: number | null;
  minutesToClose?: number | null;
  triggerSource?: string | null;
  analysisIntent?: string | null;
  warnings: string[];
}

/** Report metadata */
export interface ReportMeta {
  id?: number;  // Analysis history record ID, present for persisted reports
  queryId: string;
  stockCode: string;
  stockName: string;
  market?: 'TW' | 'US' | string | null;
  exchange?: string | null;
  instrumentType?: string | null;
  googleFinanceExchange?: string | null;
  exchangeSource?: string | null;
  reportType: ReportType;
  reportLanguage?: ReportLanguage;
  createdAt: string;
  currentPrice?: number;
  changePct?: number;
  modelUsed?: string;  // Display-only model snapshot from persisted history; not used for runtime model selection
  marketPhaseSummary?: MarketPhaseSummary | null;
}

/** Sentiment label */
export type SentimentLabel =
  | '極度悲觀'
  | '悲觀'
  | '中性'
  | '樂觀'
  | '極度樂觀'
  | '極度悲觀'
  | '悲觀'
  | '樂觀'
  | '極度樂觀'
  | 'Very Bearish'
  | 'Bearish'
  | 'Neutral'
  | 'Bullish'
  | 'Very Bullish';

/** Report summary section */
export interface ReportSummary {
  analysisSummary: string;
  operationAdvice: string;
  trendPrediction: string;
  sentimentScore: number;
  sentimentLabel?: SentimentLabel;
}

/** Strategy section */
export interface ReportStrategy {
  idealBuy?: string;
  secondaryBuy?: string;
  stopLoss?: string;
  takeProfit?: string;
}

export interface RelatedBoard {
  name: string;
  code?: string;
  type?: string;
}

export interface SectorRankingItem {
  name: string;
  changePct?: number;
}

export interface SectorRankings {
  top?: SectorRankingItem[];
  bottom?: SectorRankingItem[];
}

export type AnalysisContextPackBlockStatus =
  | 'available'
  | 'missing'
  | 'not_supported'
  | 'fallback'
  | 'stale'
  | 'estimated'
  | 'partial'
  | 'fetch_failed';

export interface AnalysisContextPackOverviewSubject {
  code: string;
  stockName?: string | null;
  market?: string | null;
}

export interface AnalysisContextPackOverviewBlock {
  key: string;
  label: string;
  status: AnalysisContextPackBlockStatus;
  source?: string | null;
  warnings: string[];
  missingReasons: string[];
}

export interface AnalysisContextPackOverviewCounts {
  available: number;
  missing: number;
  notSupported: number;
  fallback: number;
  stale: number;
  estimated: number;
  partial: number;
  fetchFailed: number;
}

export interface AnalysisContextPackOverviewMetadata {
  triggerSource?: string | null;
  newsResultCount?: number | null;
}

export type AnalysisContextPackDataQualityLevel = 'good' | 'usable' | 'limited' | 'poor';

export interface AnalysisContextPackOverviewDataQuality {
  overallScore?: number | null;
  level?: AnalysisContextPackDataQualityLevel | null;
  blockScores: Record<string, number>;
  limitations: string[];
}

export interface AnalysisContextPackOverview {
  packVersion: string;
  createdAt?: string | null;
  subject: AnalysisContextPackOverviewSubject;
  blocks: AnalysisContextPackOverviewBlock[];
  counts: AnalysisContextPackOverviewCounts;
  dataQuality?: AnalysisContextPackOverviewDataQuality | null;
  warnings: string[];
  metadata: AnalysisContextPackOverviewMetadata;
}

/** Details section */
export interface ReportDetails {
  newsContent?: string;
  rawResult?: Record<string, unknown>;
  contextSnapshot?: Record<string, unknown>;
  analysisContextPackOverview?: AnalysisContextPackOverview | null;
  financialReport?: Record<string, unknown>;
  dividendMetrics?: Record<string, unknown>;
  belongBoards?: RelatedBoard[];
  sectorRankings?: SectorRankings;
}

/** Full analysis report */
export interface AnalysisReport {
  meta: ReportMeta;
  summary: ReportSummary;
  strategy?: ReportStrategy;
  details?: ReportDetails;
}

// ============ Analysis Result Types ============

export type RunDiagnosticStatus = 'normal' | 'degraded' | 'failed' | 'unknown';

export type RunDiagnosticComponentStatus =
  | 'ok'
  | 'degraded'
  | 'failed'
  | 'unknown'
  | 'not_configured'
  | 'skipped';

export interface RunDiagnosticComponent {
  key: string;
  label: string;
  status: RunDiagnosticComponentStatus;
  message: string;
  details?: Record<string, unknown>;
}

export interface RunDiagnosticSummary {
  traceId?: string;
  taskId?: string;
  queryId?: string;
  stockCode?: string;
  triggerSource?: string;
  status: RunDiagnosticStatus;
  statusLabel: string;
  reason: string;
  components: Record<string, RunDiagnosticComponent>;
  copyText: string;
}

export type NewsProviderProbeMarket = 'tw' | 'us';
export type NewsProviderProbeMode = 'runtime' | 'searxng' | 'tavily';

export interface NewsProviderProbeRequest {
  symbol: string;
  market: NewsProviderProbeMarket;
  providerMode?: NewsProviderProbeMode;
  limit?: number;
}

export interface NewsProviderProbeItem {
  title: string;
  source: string;
  url: string;
  publishedAt?: string;
}

export interface NewsProviderProbeResponse {
  symbol: string;
  market: NewsProviderProbeMarket;
  providerMode: NewsProviderProbeMode;
  status: string;
  providersAttempted: string[];
  queryVariants: string[];
  attemptCount: number;
  resultCount: number;
  fallbackUsed: boolean;
  latencyMs: number;
  items: NewsProviderProbeItem[];
  errorMessage?: string;
}

/** Sync analysis response */
export interface AnalysisResult {
  queryId: string;
  traceId?: string;
  stockCode: string;
  stockName: string;
  report: AnalysisReport;
  diagnosticSummary?: RunDiagnosticSummary;
  createdAt: string;
}

/** Async task accepted response */
export interface TaskAccepted {
  taskId: string;
  traceId?: string;
  status: 'pending' | 'processing';
  message?: string;
  analysisPhase?: AnalysisPhase;
}

export interface BatchTaskAcceptedItem {
  taskId: string;
  traceId?: string;
  stockCode: string;
  status: 'pending' | 'processing';
  message?: string;
  analysisPhase?: AnalysisPhase;
}

export interface BatchDuplicateTaskItem {
  stockCode: string;
  existingTaskId: string;
  message: string;
}

export interface BatchTaskAcceptedResponse {
  accepted: BatchTaskAcceptedItem[];
  duplicates: BatchDuplicateTaskItem[];
  message: string;
}

export type AnalyzeAsyncResponse = TaskAccepted | BatchTaskAcceptedResponse;

export type AnalyzeResponse = AnalysisResult | AnalyzeAsyncResponse;

/** Task status */
export interface TaskStatus {
  taskId: string;
  traceId?: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress?: number;
  stage?: string | null;
  stageLabel?: string | null;
  result?: AnalysisResult;
  marketReviewReport?: string;
  marketReviewSnapshot?: Record<string, unknown>;
  marketReviewSkipReason?: string;
  error?: string;
  stockName?: string;
  originalQuery?: string;
  selectionSource?: string;
  analysisPhase?: AnalysisPhase | null;
  skills?: string[];
}

/** Task details used by task list and SSE events */
export interface TaskInfo {
  taskId: string;
  traceId?: string;
  stockCode: string;
  stockName?: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  stage?: string;
  stageLabel?: string;
  message?: string;
  reportType: string;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  error?: string;
  originalQuery?: string;
  selectionSource?: string;
  analysisPhase?: AnalysisPhase;
  skills?: string[];
}

/** Task list response */
export interface TaskListResponse {
  total: number;
  pending: number;
  processing: number;
  tasks: TaskInfo[];
}

/** Duplicate task error response */
export interface DuplicateTaskError {
  error: 'duplicate_task';
  message: string;
  stockCode: string;
  existingTaskId: string;
}

// ============ History Types ============

/** History item summary */
export interface HistoryItem {
  id: number;  // Record primary key ID, always present for persisted history items
  queryId: string;  // Linked analysis query ID
  stockCode: string;
  stockName?: string;
  reportType?: ReportType;
  trendPrediction?: string;
  analysisSummary?: string;
  sentimentScore?: number;
  operationAdvice?: string;
  currentPrice?: number;
  changePct?: number;
  volumeRatio?: number;
  turnoverRate?: number;
  modelUsed?: string;  // Display-only model snapshot from persisted history; runtime provider/model/base URL still come from analyzer configuration
  marketPhaseSummary?: MarketPhaseSummary | null;
  createdAt: string;
}

export type StockHistoryRange = 'all' | '30d' | '90d';

export interface StockHistoryFilters {
  range: StockHistoryRange;
  model: string;
  sort: 'desc' | 'asc';
}

/** History list response */
export interface HistoryListResponse {
  total: number;
  page: number;
  limit: number;
  items: HistoryItem[];
}

/** News item */
export interface NewsIntelItem {
  title: string;
  snippet: string;
  url: string;
}

/** News response */
export interface NewsIntelResponse {
  total: number;
  items: NewsIntelItem[];
}

/** History filter parameters */
export interface HistoryFilters {
  stockCode?: string;
  startDate?: string;
  endDate?: string;
}

/** History pagination parameters */
export interface HistoryPagination {
  page: number;
  limit: number;
}

// ============ Stock Bar Types ============

export interface StockBarItem {
  id: number;
  stockCode: string;
  stockName?: string;
  reportType?: string;
  sentimentScore?: number;
  operationAdvice?: string;
  analysisCount: number;
  lastAnalysisTime?: string;
  modelUsed?: string;
  marketPhaseSummary?: MarketPhaseSummary | null;
}

export interface StockBarResponse {
  total: number;
  items: StockBarItem[];
}

// ============ K-line Types ============

export type KlineRange = '1d' | '5d' | '1w' | '1m' | '3m' | '1y';
export type VisibleKlineRange = '1d' | '5d' | '1m' | '3m' | '1y';
export type KlineGranularity = 'intraday' | 'daily' | string;

export interface KlineBar {
  date?: string;
  timestamp?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  ma20?: number | null;
  ma60?: number | null;
  ma120?: number | null;
  ma252?: number | null;
}

export interface KlineResponse {
  historyId?: number | null;
  symbol: string;
  market: 'tw' | 'us' | 'unknown' | string;
  instrumentType: InstrumentType | string;
  range: KlineRange;
  granularity?: KlineGranularity;
  interval?: string | null;
  currency?: string | null;
  timezone?: string | null;
  source: string;
  sourceType: 'db_cache' | 'provider' | 'data_gap' | string;
  sourceChain?: string[];
  asOf?: string | null;
  isCached?: boolean | null;
  rows: KlineBar[];
  candles?: KlineBar[];
  snapshotCreatedAt?: string | null;
  currentPrice?: number | null;
  supportLevel?: number | null;
  resistanceLevel?: number | null;
  dataGapReason?: string | null;
}

// ============ Error Types ============

export interface ApiError {
  error: string;
  message: string;
  detail?: Record<string, unknown>;
}

// ============ Helper Functions ============

/** Get sentiment label by score */
export const getSentimentLabel = (score: number, language: ReportLanguage = 'zh_TW'): SentimentLabel => {
  if (language === 'en') {
    if (score <= 20) return 'Very Bearish';
    if (score <= 40) return 'Bearish';
    if (score <= 60) return 'Neutral';
    if (score <= 80) return 'Bullish';
    return 'Very Bullish';
  }
  if (language === 'zh_TW') {
    if (score <= 20) return '極度悲觀';
    if (score <= 40) return '悲觀';
    if (score <= 60) return '中性';
    if (score <= 80) return '樂觀';
    return '極度樂觀';
  }
  if (score <= 20) return '極度悲觀';
  if (score <= 40) return '悲觀';
  if (score <= 60) return '中性';
  if (score <= 80) return '樂觀';
  return '極度樂觀';
};

/** Get sentiment color by score */
export const getSentimentColor = (score: number): string => {
  if (score <= 20) return '#ef4444'; // red-500
  if (score <= 40) return '#f97316'; // orange-500
  if (score <= 60) return '#eab308'; // yellow-500
  if (score <= 80) return '#22c55e'; // green-500
  return '#10b981'; // emerald-500
};

// ============ Visual Report Snapshot Types (Phase 19B raw_result overlay) ============
// These types mirror the backend snapshot dicts after camelCase conversion.
// Access via AnalysisReport.details.rawResult cast to VisualReportRawResult.

export type InstrumentType = 'stock' | 'etf' | 'index' | 'unknown';

export interface MarketRiskSnapshot {
  source?: string;
  asOf?: string;
  vixLevel?: number | null;
  vixStatus?: string | null;
  spxChangePct?: number | null;
  gapReason?: string | null;
  dataGapFields?: string[];
}

export type MarketFearIndexKind = 'vix' | 'vixtwn';

export interface MarketFearIndexSnapshot {
  market?: 'us' | 'tw' | string | null;
  kind?: MarketFearIndexKind | string | null;
  label?: string | null;
  value?: number | null;
  asOf?: string | null;
  source?: string | null;
  sourceUrlKey?: string | null;
  status?: string | null;
  dataGapReason?: string | null;
}

export interface MultiPeriodTrendPeriod {
  label?: string;
  period?: string;
  changePct?: number | null;
  drawdownPct?: number | null;
  // API returns drawdown_from_high_pct → toCamelCase → drawdownFromHighPct
  drawdownFromHighPct?: number | null;
  priceVsMaPct?: number | null;
  // test fixtures use `status`; real API returns trend_status → toCamelCase → trendStatus
  status?: string | null;
  trendStatus?: string | null;
}

export interface MultiPeriodTrendSnapshot {
  source?: string;
  asOf?: string;
  periods?: MultiPeriodTrendPeriod[];
  dataGapFields?: string[];
}

export interface DataSnapshot {
  source?: string;
  asOf?: string;
  dataGapFields?: string[];
  gapReason?: string | null;
  [key: string]: unknown;
}

export interface ValuationSnapshot extends DataSnapshot {
  peTtm?: number | null;
  peForward?: number | null;
  pb?: number | null;
  dividendYield?: number | null;
  marketCap?: number | null;
}

export interface FundamentalSnapshot extends DataSnapshot {
  revenueYoy?: number | null;
  earningsYoy?: number | null;
  netProfitYoy?: number | null;
  roe?: number | null;
  grossMargin?: number | null;
}

/** Typed overlay for AnalysisReport.details.rawResult in history detail responses */
export interface VisualReportRawResult {
  instrumentType?: InstrumentType;
  // Price/technical fields (also in meta, but raw_result may have richer data)
  currentPrice?: number | null;
  changePct?: number | null;
  ma5?: number | null;
  ma10?: number | null;
  ma20?: number | null;
  deviationRate?: number | null;
  supportLevel?: number | null;
  resistanceLevel?: number | null;
  trendStrength?: number | null;
  volumeRatio?: number | null;
  turnoverRate?: number | null;
  rsi?: number | null;
  rsi6?: number | null;
  rsi12?: number | null;
  // Phase 19B snapshots
  marketRiskSnapshot?: MarketRiskSnapshot | null;
  marketFearIndexSnapshot?: MarketFearIndexSnapshot | null;
  multiPeriodTrendSnapshot?: MultiPeriodTrendSnapshot | null;
  valuationSnapshot?: ValuationSnapshot | null;
  fundamentalSnapshot?: FundamentalSnapshot | null;
  exposureSnapshot?: DataSnapshot | null;
  valueNetworkMermaid?: string | null;
  // Phase 25.7: optional four-masters commentary supplement (commentary-only;
  // structured shape validated by fourMastersCommentaryAdapter before render).
  fourMastersCommentary?: Record<string, unknown> | null;
  [key: string]: unknown;
}
