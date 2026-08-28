import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  MasterDebateListResponse,
  MasterDebateRecordItem,
  MasterDebateRequest,
  MasterDebateResponse,
} from '../types/masterDebate';

export const masterDebateApi = {
  async run(payload: MasterDebateRequest): Promise<MasterDebateResponse> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/master-debate', {
      code: payload.code,
      name: payload.name,
      market: payload.market,
      context: payload.context,
      analysis_history_id: payload.analysisHistoryId,
      persist: payload.persist,
    }, {
      // 辩论包含多次 LLM 调用（含失败降级重试），耗时可达数分钟
      timeout: 300000,
    });
    return toCamelCase<MasterDebateResponse>(response.data);
  },

  async list(params: { market?: string; code?: string; page?: number; pageSize?: number } = {}): Promise<MasterDebateListResponse> {
    const query: Record<string, string | number> = {};
    if (params.market) query.market = params.market;
    if (params.code) query.code = params.code;
    if (params.page != null) query.page = params.page;
    if (params.pageSize != null) query.page_size = params.pageSize;
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/master-debate', { params: query });
    return toCamelCase<MasterDebateListResponse>(response.data);
  },

  async get(id: number): Promise<MasterDebateRecordItem> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/master-debate/' + String(id));
    return toCamelCase<MasterDebateRecordItem>(response.data);
  },
};
