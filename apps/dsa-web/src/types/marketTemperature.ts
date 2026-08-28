export type MarketTemperatureMarket = 'cn' | 'hk' | 'us' | 'jp' | 'kr' | 'tw';

export interface MarketTemperatureDimension {
  key: string;
  name: string;
  score: number;
  available: boolean;
}

export interface MarketTemperatureComputeRequest {
  market: MarketTemperatureMarket;
  tradeDate?: string;
  advancers?: number;
  decliners?: number;
  limitUp?: number;
  limitDown?: number;
  newHigh52w?: number;
  newLow52w?: number;
  northboundNet?: number;
  marginChangePct?: number;
  turnoverPct?: number;
  indexPctChg?: number;
}

export interface MarketTemperatureComputeResponse {
  market: string;
  tradeDate: string;
  score: number;
  label: string;
  labelKey: string;
  dimensions: MarketTemperatureDimension[];
  availableDimensions: number;
  reasons: string[];
  guidance: string;
  source?: string | null;
}

export interface MarketTemperatureSnapshotItem {
  id: number;
  market: string;
  tradeDate: string;
  score: number;
  label: string;
  dimensions: MarketTemperatureDimension[];
  reasons: string[];
  guidance?: string | null;
  createdAt?: string | null;
}

export interface MarketTemperatureListResponse {
  items: MarketTemperatureSnapshotItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface MarketDashboardIndex {
  code: string;
  name: string;
  changePct?: number | null;
}

export interface MarketDashboardBreadth {
  upCount: number;
  downCount: number;
  flatCount: number;
  limitUpCount: number;
  limitDownCount: number;
  totalAmount: number;
}

export interface MarketDashboardSectorItem {
  name: string;
  changePct?: number | null;
}

export interface MarketDashboardSectorGroup {
  top: MarketDashboardSectorItem[];
  bottom: MarketDashboardSectorItem[];
}

export interface MarketDashboardFlowItem {
  name: string;
  netInflow?: number | null;
}

export interface MarketDashboardFlowGroup {
  top: MarketDashboardFlowItem[];
  bottom: MarketDashboardFlowItem[];
}

export interface MarketDashboardCapitalFlow {
  status: string;
  sectorRankings: MarketDashboardFlowGroup;
}

export interface MarketDashboardCandidate {
  code: string;
  name: string;
  sector: string;
  sectorChangePct?: number | null;
  changePct?: number | null;
  price?: number | null;
  reason: string;
}

export interface MarketDashboardData {
  market: string;
  tradeDate: string;
  temperature: MarketTemperatureComputeResponse | null;
  indices: MarketDashboardIndex[];
  breadth: MarketDashboardBreadth;
  hotSectors: MarketDashboardSectorGroup;
  hotConcepts: MarketDashboardSectorGroup;
  capitalFlow: MarketDashboardCapitalFlow;
  candidates: MarketDashboardCandidate[];
  notes: string[];
  generatedAt?: string | null;
}
