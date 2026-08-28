export type TradeJournalSide = 'buy' | 'sell';
export type TradeJournalMarket = 'cn' | 'hk' | 'us' | 'jp' | 'kr' | 'tw';
export type TradeJournalEmotion = 'excited' | 'calm' | 'fearful' | 'fomo' | 'neutral' | 'regretful';

export interface TradeJournalCreateRequest {
  code: string;
  name?: string;
  market: TradeJournalMarket;
  side: string;
  quantity: number;
  price: number;
  fee?: number;
  tax?: number;
  currency?: string;
  tradeDate: string;
  thesis?: string;
  strategy?: string;
  emotion?: TradeJournalEmotion;
  planFollowed?: boolean;
  linkedSignalId?: number;
  tags?: string[];
}

export interface TradeJournalItem {
  id: number;
  code: string;
  name?: string | null;
  market: string;
  side: string;
  quantity: number;
  price: number;
  fee: number;
  tax: number;
  currency: string;
  tradeDate?: string | null;
  thesis?: string | null;
  strategy?: string | null;
  emotion?: string | null;
  planFollowed?: boolean | null;
  linkedSignalId?: number | null;
  tags: string[];
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface TradeJournalMutationResponse {
  item: TradeJournalItem;
}

export interface TradeJournalListResponse {
  items: TradeJournalItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface TradeJournalRealizedTrade {
  buyPrice: number;
  sellPrice: number;
  quantity: number;
  pnl: number;
  pnlPct: number;
  entryDate?: string | null;
}

export interface TradeJournalPnlResponse {
  market: string;
  code: string;
  realizedPnl: number;
  realizedTrades: TradeJournalRealizedTrade[];
  closedCount: number;
  openQuantity: number;
  avgCost?: number | null;
}

export interface TradeJournalReviewResponse {
  entryCount: number;
  closedTradeCount: number;
  winRate?: number | null;
  avgWin?: number | null;
  avgLoss?: number | null;
  profitFactor?: number | null;
  totalPnl: number;
  disciplineScore?: number | null;
  planDeclared: number;
  planFollowed: number;
  linkedSignalCount: number;
  alignedCount: number;
  emotionBreakdown: Record<string, number>;
}
