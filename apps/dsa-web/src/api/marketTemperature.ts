import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  MarketDashboardData,
  MarketTemperatureComputeRequest,
  MarketTemperatureComputeResponse,
  MarketTemperatureListResponse,
  MarketTemperatureSnapshotItem,
} from '../types/marketTemperature';

export const marketTemperatureApi = {
  async compute(payload: MarketTemperatureComputeRequest): Promise<MarketTemperatureComputeResponse> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/market-temperature', {
      market: payload.market,
      trade_date: payload.tradeDate,
      advancers: payload.advancers,
      decliners: payload.decliners,
      limit_up: payload.limitUp,
      limit_down: payload.limitDown,
      new_high_52w: payload.newHigh52w,
      new_low_52w: payload.newLow52w,
      northbound_net: payload.northboundNet,
      margin_change_pct: payload.marginChangePct,
      turnover_pct: payload.turnoverPct,
      index_pct_chg: payload.indexPctChg,
    });
    return toCamelCase<MarketTemperatureComputeResponse>(response.data);
  },

  async latest(market: string): Promise<MarketTemperatureSnapshotItem | null> {
    const response = await apiClient.get<Record<string, unknown> | null>('/api/v1/market-temperature/latest', {
      params: { market },
    });
    return toCamelCase<MarketTemperatureSnapshotItem | null>(response.data);
  },

  async history(market?: string, page = 1, pageSize = 20): Promise<MarketTemperatureListResponse> {
    const params: Record<string, string | number> = { page, page_size: pageSize };
    if (market) params.market = market;
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/market-temperature', { params });
    return toCamelCase<MarketTemperatureListResponse>(response.data);
  },

  async dashboard(market: string): Promise<MarketDashboardData> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/market-temperature/dashboard', null, {
      params: { market },
      timeout: 180000,
    });
    return toCamelCase<MarketDashboardData>(response.data);
  },

  async computeFromProvider(market: string): Promise<MarketTemperatureComputeResponse> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/market-temperature/compute', null, {
      params: { market },
    });
    return toCamelCase<MarketTemperatureComputeResponse>(response.data);
  },

  async fromDatabase(market: string, indexPctChg?: number): Promise<MarketTemperatureComputeResponse> {
    const params: Record<string, string | number> = { market };
    if (indexPctChg != null) params.index_pct_chg = indexPctChg;
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/market-temperature/from-database', null, {
      params,
    });
    return toCamelCase<MarketTemperatureComputeResponse>(response.data);
  },
};
