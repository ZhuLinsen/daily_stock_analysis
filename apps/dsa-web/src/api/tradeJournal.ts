import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  TradeJournalCreateRequest,
  TradeJournalItem,
  TradeJournalListResponse,
  TradeJournalMutationResponse,
  TradeJournalPnlResponse,
  TradeJournalReviewResponse,
} from '../types/tradeJournal';

export type TradeJournalListQuery = {
  market?: string;
  code?: string;
  side?: string;
  strategy?: string;
  emotion?: string;
  tradeDateFrom?: string;
  tradeDateTo?: string;
  page?: number;
  pageSize?: number;
};

export type TradeJournalReviewQuery = {
  market?: string;
  tradeDateFrom?: string;
  tradeDateTo?: string;
};

export const tradeJournalApi = {
  async create(payload: TradeJournalCreateRequest): Promise<TradeJournalItem> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/trade-journals', {
      code: payload.code,
      name: payload.name,
      market: payload.market,
      side: payload.side,
      quantity: payload.quantity,
      price: payload.price,
      fee: payload.fee,
      tax: payload.tax,
      currency: payload.currency,
      trade_date: payload.tradeDate,
      thesis: payload.thesis,
      strategy: payload.strategy,
      emotion: payload.emotion,
      plan_followed: payload.planFollowed,
      linked_signal_id: payload.linkedSignalId,
      tags: payload.tags,
    });
    return toCamelCase<TradeJournalMutationResponse>(response.data).item;
  },

  async list(query: TradeJournalListQuery = {}): Promise<TradeJournalListResponse> {
    const params: Record<string, string | number> = {};
    if (query.market) params.market = query.market;
    if (query.code) params.code = query.code;
    if (query.side) params.side = query.side;
    if (query.strategy) params.strategy = query.strategy;
    if (query.emotion) params.emotion = query.emotion;
    if (query.tradeDateFrom) params.trade_date_from = query.tradeDateFrom;
    if (query.tradeDateTo) params.trade_date_to = query.tradeDateTo;
    if (query.page != null) params.page = query.page;
    if (query.pageSize != null) params.page_size = query.pageSize;
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/trade-journals', { params });
    return toCamelCase<TradeJournalListResponse>(response.data);
  },

  async remove(id: number): Promise<void> {
    await apiClient.delete('/api/v1/trade-journals/' + String(id));
  },

  async review(query: TradeJournalReviewQuery = {}): Promise<TradeJournalReviewResponse> {
    const params: Record<string, string> = {};
    if (query.market) params.market = query.market;
    if (query.tradeDateFrom) params.trade_date_from = query.tradeDateFrom;
    if (query.tradeDateTo) params.trade_date_to = query.tradeDateTo;
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/trade-journals/review', { params });
    return toCamelCase<TradeJournalReviewResponse>(response.data);
  },

  async pnl(market: string, code: string): Promise<TradeJournalPnlResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/trade-journals/pnl', {
      params: { market, code },
    });
    return toCamelCase<TradeJournalPnlResponse>(response.data);
  },
};
