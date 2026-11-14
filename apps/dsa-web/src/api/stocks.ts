import apiClient from './index';

export type ExtractItem = {
  code?: string | null;
  name?: string | null;
  confidence: string;
};

export type ExtractFromImageResponse = {
  codes: string[];
  items?: ExtractItem[];
  rawText?: string;
};

/**
 * 个股行情快照（issue #771 看板口径）。
 * 字段名与后端 api/v1/schemas/stocks.py StockQuote 响应模型逐一对齐（snake_case 直传）：
 * 22 个行情字段（直出 15 + 派生 3 + MA 4 档）+ 数据质量元数据。
 * 多市场降级：缺失字段一律显式 null，并以 missing_fields 透出，前端以"—"占位。
 */
export type StockQuoteSnapshot = {
  stock_code: string;
  stock_name?: string | null;

  // === 数据质量元数据 ===
  source?: string | null;
  fetched_at?: string | null;
  provider_timestamp?: string | null;
  is_stale?: boolean | null;
  stale_seconds?: number | null;
  market?: string | null;
  currency?: string | null;
  data_quality?: string | null;
  fallback_from?: string | null;
  missing_fields?: string[];

  // === 直出 15（UnifiedRealtimeQuote 同名） ===
  price: number | null;
  pre_close: number | null;
  open_price: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  amount: number | null;
  change_amount: number | null;
  change_pct: number | null;
  amplitude: number | null;
  volume_ratio: number | null;
  turnover_rate: number | null;
  change_60d: number | null;
  high_52w: number | null;
  low_52w: number | null;

  // === 派生 3 ===
  vwap: number | null;
  bid_ask_ratio: number | null;
  trade_count: number | null;

  // === MA 4 档 ===
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma60: number | null;
};

export const stocksApi = {
  async extractFromImage(file: File): Promise<ExtractFromImageResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
    const response = await apiClient.post(
      '/api/v1/stocks/extract-from-image',
      formData,
      {
        headers,
        timeout: 60000, // Vision API can be slow; 60s
      },
    );

    const data = response.data as { codes?: string[]; items?: ExtractItem[]; raw_text?: string };
    return {
      codes: data.codes ?? [],
      items: data.items,
      rawText: data.raw_text,
    };
  },

  /**
   * 个股行情快照（issue #771）：GET /api/v1/stocks/{code}/quote
   * 只读 22 字段快照 + 数据质量元数据；未知代码 404、非法代码 400（与后端契约一致）。
   */
  async getQuote(code: string): Promise<StockQuoteSnapshot> {
    const response = await apiClient.get(`/api/v1/stocks/${encodeURIComponent(code)}/quote`);
    return response.data as StockQuoteSnapshot;
  },

  async parseImport(file?: File, text?: string): Promise<ExtractFromImageResponse> {
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
      const response = await apiClient.post('/api/v1/stocks/parse-import', formData, { headers });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    if (text) {
      const response = await apiClient.post('/api/v1/stocks/parse-import', { text });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    throw new Error('请提供文件或粘贴文本');
  },
};
