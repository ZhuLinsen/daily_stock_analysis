export type ProviderEnvelope = {
  source: string;
  stale: boolean;
  error?: string | null;
  disclaimer: string;
};

export type MarketIndexItem = {
  code?: string | null;
  name: string;
  current?: number | null;
  change?: number | null;
  changePct?: number | null;
  amount?: number | null;
};

export type MarketBreadth = {
  upCount: number;
  downCount: number;
  flatCount: number;
  limitUpCount: number;
  limitDownCount: number;
  totalAmount?: number | null;
};

export type BoardHeatItem = {
  name: string;
  type?: string | null;
  changePct?: number | null;
  amount?: number | null;
  leadingStock?: string | null;
};

export type LimitUpItem = {
  code?: string | null;
  name?: string | null;
  changePct?: number | null;
  price?: number | null;
  amount?: number | null;
  turnoverRate?: number | null;
  sealAmount?: number | null;
  firstLimitTime?: string | null;
  lastLimitTime?: string | null;
  breakCount?: number | null;
  limitStat?: string | null;
  consecutiveBoards?: number | null;
  industry?: string | null;
};

export type WorkbenchDashboard = ProviderEnvelope & {
  indices: MarketIndexItem[];
  breadth: MarketBreadth;
  strongIndustries: BoardHeatItem[];
  strongConcepts: BoardHeatItem[];
  limitUpPool: LimitUpItem[];
  aiMarketSummary: string;
};

export type OperationReference = {
  action: '观察' | '持有' | '减仓' | '等待确认' | string;
  confidence: number;
  invalidCondition?: string | null;
};

export type AiScorePayload = {
  symbol: string;
  name: string;
  summary: string;
  aiScore: number;
  statusTag: string;
  trend: {
    direction: string;
    strength: number;
    reason: string;
  };
  technical: {
    score: number;
    summary: string;
    support?: string | null;
    resistance?: string | null;
  };
  capital: {
    score: number;
    summary: string;
  };
  sector: {
    score: number;
    hotTopics: string[];
    summary: string;
  };
  risks: string[];
  nextDayWatch: string[];
  operationReference: OperationReference;
  disclaimer: string;
};

export type WatchlistItem = {
  symbol: string;
  name: string;
  latestPrice?: number | null;
  changePct?: number | null;
  amount?: number | null;
  turnoverRate?: number | null;
  mainNetInflow?: number | null;
  industry?: string | null;
  concepts: string[];
  aiScore: number;
  statusTag: string;
  riskTags: string[];
  opportunityTags: string[];
  watchTags: string[];
  nextDayWatch: string[];
  source: string;
  stale: boolean;
  error?: string | null;
};

export type WorkbenchWatchlist = ProviderEnvelope & {
  items: WatchlistItem[];
};

export type KLineBar = {
  date: string;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  volume?: number | null;
  amount?: number | null;
  pctChg?: number | null;
  ma5?: number | null;
  ma10?: number | null;
  ma20?: number | null;
  ma60?: number | null;
  macdDif?: number | null;
  macdDea?: number | null;
  macd?: number | null;
  kdjK?: number | null;
  kdjD?: number | null;
  kdjJ?: number | null;
  rsi?: number | null;
  bollMid?: number | null;
  bollUpper?: number | null;
  bollLower?: number | null;
};

export type MoneyFlowData = {
  stockFlow?: {
    mainNetInflow?: number | null;
    inflow5d?: number | null;
    inflow10d?: number | null;
  };
  sectorRankings?: {
    top?: Array<{ name: string; netInflow?: number | null }>;
    bottom?: Array<{ name: string; netInflow?: number | null }>;
  };
};

export type StockThemes = {
  symbol: string;
  industry: string[];
  concepts: string[];
  boards: Array<{ name: string; type?: string; code?: string }>;
};

export type StockQuote = {
  code?: string | null;
  name?: string | null;
  price?: number | null;
  changePct?: number | null;
  changeAmount?: number | null;
  volume?: number | null;
  amount?: number | null;
  volumeRatio?: number | null;
  turnoverRate?: number | null;
  amplitude?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  preClose?: number | null;
  peRatio?: number | null;
  pbRatio?: number | null;
  totalMv?: number | null;
  circMv?: number | null;
  providerTimestamp?: string | null;
  fetchedAt?: string | null;
};

export type StockNewsItem = {
  title: string;
  url?: string | null;
  source?: string | null;
  publishedAt?: string | null;
};

export type WorkbenchStockDetail = ProviderEnvelope & {
  symbol: string;
  name: string;
  quote: StockQuote;
  kline: KLineBar[];
  moneyFlow: MoneyFlowData;
  themes: StockThemes;
  lhb: Record<string, unknown>;
  news: StockNewsItem[];
  aiAnalysis: AiScorePayload;
  riskTags: string[];
  opportunityTags: string[];
  watchTags: string[];
  latestReport?: Record<string, unknown> | null;
};

export type WorkbenchDailyReview = ProviderEnvelope & {
  oneLiner: string;
  strongestBoards: BoardHeatItem[];
  riskBoards: BoardHeatItem[];
  watchlistPerformance: WatchlistItem[];
  holdingRisks: WatchlistItem[];
  nextDayWatchlist: WatchlistItem[];
  aiSummary: string;
  markdown: string;
};

export type WorkbenchMarkdown = {
  markdown: string;
  filename: string;
  source: string;
  stale: boolean;
  error?: string | null;
  meta: Record<string, unknown>;
};
