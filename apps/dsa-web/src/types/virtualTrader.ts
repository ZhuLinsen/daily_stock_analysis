export interface VirtualTraderPosition {
  id: number;
  stockCode: string;
  name?: string | null;
  market: string;
  currency: string;
  quantity: number;
  avgCost: number;
  lastPrice?: number | null;
  marketValue?: number | null;
  marketValueCny?: number | null;
  unrealizedPnlPct?: number | null;
  realizedPnl: number;
  status: string;
  openedAt?: string | null;
}

export interface VirtualTraderAccount {
  accountId: number;
  name: string;
  status: string;
  initialCashCny: number;
  cashCny: number;
  cashHkd: number;
  cashUsd: number;
  cashTotalCny: number;
  positions: VirtualTraderPosition[];
  positionsValueCny: number;
  totalValueCny: number;
  totalReturnPct: number;
  createdAt?: string | null;
}

export interface VirtualTraderTrade {
  id: number;
  stockCode: string;
  market: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  fee: number;
  currency: string;
  reason?: string | null;
  tradeDate: string;
  tradedAt?: string | null;
}

export interface VirtualTraderTradeList {
  items: VirtualTraderTrade[];
  total: number;
  page: number;
  pageSize: number;
}

export interface VirtualTraderPrediction {
  id: number;
  stockCode: string;
  market: string;
  direction: 'up' | 'down';
  anchorDate: string;
  horizonDays: number;
  targetPrice: number;
  entryPrice: number;
  rationale?: string | null;
  status: 'pending' | 'evaluated' | 'unable';
  outcome?: 'hit' | 'miss' | 'unable' | null;
  actualReturnPct?: number | null;
  windowHigh?: number | null;
  windowLow?: number | null;
}

export interface VirtualTraderPredictionList {
  items: VirtualTraderPrediction[];
  total: number;
  page: number;
  pageSize: number;
}

export interface VirtualTraderEquityPoint {
  tradeDate: string;
  totalValueCny: number;
  dailyReturnPct?: number | null;
  positionsCount: number;
}

export interface VirtualTraderEquityCurve {
  points: VirtualTraderEquityPoint[];
  initialCashCny: number;
}

export interface VirtualTraderStats {
  prediction: {
    pending: number;
    hit: number;
    miss: number;
    unable: number;
    total: number;
  };
  totalTrades: number;
  buyTrades: number;
  sellTrades: number;
  winRatePct?: number | null;
  realizedPnlTotal: number;
}

export interface VirtualTraderRunResult {
  status: string;
  market?: string;
  tradeDate?: string;
  error?: string;
  reason?: string;
  trades?: Array<{
    code: string;
    action: string;
    reason?: string;
    price?: number;
    quantity?: number;
  }>;
  totalValueCny?: number;
}
