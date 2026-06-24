import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  DecisionSignalCreateRequest,
  DecisionSignalFeedbackItem,
  DecisionSignalFeedbackRequest,
  DecisionSignalItem,
  DecisionSignalLatestParams,
  DecisionSignalListParams,
  DecisionSignalListResponse,
  DecisionSignalMutationResponse,
  DecisionSignalOutcomeItem,
  DecisionSignalOutcomeListParams,
  DecisionSignalOutcomeListResponse,
  DecisionSignalOutcomeRunRequest,
  DecisionSignalOutcomeRunResponse,
  DecisionSignalOutcomeStatsBucket,
  DecisionSignalOutcomeStatsParams,
  DecisionSignalOutcomeStatsResponse,
  DecisionSignalStatusUpdateRequest,
} from '../types/decisionSignals';

function omitUndefined(input: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(input).filter(([, value]) => value !== undefined),
  );
}

function serializeRepeatedQueryParams(params: Record<string, unknown>): string {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    const values = Array.isArray(value) ? value : [value];
    for (const item of values) {
      if (item === undefined || item === null || item === '') continue;
      searchParams.append(key, String(item));
    }
  }
  return searchParams.toString();
}

function toDecisionSignalItem(data: Record<string, unknown>): DecisionSignalItem {
  const item = toCamelCase<DecisionSignalItem>(data);
  if ('evidence' in data) item.evidence = data.evidence;
  if ('data_quality_summary' in data) item.dataQualitySummary = data.data_quality_summary;
  if ('metadata' in data) item.metadata = data.metadata;
  return item;
}

function toDecisionSignalMutationResponse(data: Record<string, unknown>): DecisionSignalMutationResponse {
  const response = toCamelCase<DecisionSignalMutationResponse>(data);
  response.item = toDecisionSignalItem(data.item as Record<string, unknown>);
  return response;
}

function toDecisionSignalListResponse(data: Record<string, unknown>): DecisionSignalListResponse {
  const response = toCamelCase<DecisionSignalListResponse>(data);
  if (!Array.isArray(data.items)) {
    throw new Error('DecisionSignal list response items must be an array');
  }
  response.items = data.items.map((item) => toDecisionSignalItem(item as Record<string, unknown>));
  return response;
}

function toDecisionSignalOutcomeItem(data: Record<string, unknown>): DecisionSignalOutcomeItem {
  return toCamelCase<DecisionSignalOutcomeItem>(data);
}

function toDecisionSignalOutcomeListResponse(data: Record<string, unknown>): DecisionSignalOutcomeListResponse {
  const response = toCamelCase<DecisionSignalOutcomeListResponse>(data);
  if (!Array.isArray(data.items)) {
    throw new Error('DecisionSignal outcome list response items must be an array');
  }
  response.items = data.items.map((item) => toDecisionSignalOutcomeItem(item as Record<string, unknown>));
  return response;
}

function toDecisionSignalOutcomeRunResponse(data: Record<string, unknown>): DecisionSignalOutcomeRunResponse {
  const response = toCamelCase<DecisionSignalOutcomeRunResponse>(data);
  if (!Array.isArray(data.items)) {
    throw new Error('DecisionSignal outcome run response items must be an array');
  }
  response.items = data.items.map((item) => toDecisionSignalOutcomeItem(item as Record<string, unknown>));
  return response;
}

function toDecisionSignalStatsBucket(data: Record<string, unknown>): DecisionSignalOutcomeStatsBucket {
  const bucket = toCamelCase<DecisionSignalOutcomeStatsBucket>(data);
  bucket.unableReasons = (data.unable_reasons as Record<string, number> | undefined) ?? {};
  return bucket;
}

function toDecisionSignalOutcomeStatsResponse(data: Record<string, unknown>): DecisionSignalOutcomeStatsResponse {
  const response = toCamelCase<DecisionSignalOutcomeStatsResponse>(data);
  response.unableReasons = (data.unable_reasons as Record<string, number> | undefined) ?? {};
  const rawBreakdowns = data.breakdowns as Record<string, unknown[]> | undefined;
  response.breakdowns = {};
  if (rawBreakdowns && typeof rawBreakdowns === 'object') {
    for (const [dimension, buckets] of Object.entries(rawBreakdowns)) {
      response.breakdowns[dimension] = Array.isArray(buckets)
        ? buckets.map((bucket) => toDecisionSignalStatsBucket(bucket as Record<string, unknown>))
        : [];
    }
  }
  return response;
}

function toDecisionSignalFeedbackItem(data: Record<string, unknown>): DecisionSignalFeedbackItem {
  return toCamelCase<DecisionSignalFeedbackItem>(data);
}

function toSnakeCreatePayload(payload: DecisionSignalCreateRequest): Record<string, unknown> {
  return omitUndefined({
    stock_code: payload.stockCode,
    stock_name: payload.stockName,
    market: payload.market,
    source_type: payload.sourceType,
    source_agent: payload.sourceAgent,
    source_report_id: payload.sourceReportId,
    trace_id: payload.traceId,
    market_phase: payload.marketPhase,
    trigger_source: payload.triggerSource,
    action: payload.action,
    action_label: payload.actionLabel,
    confidence: payload.confidence,
    score: payload.score,
    horizon: payload.horizon,
    entry_low: payload.entryLow,
    entry_high: payload.entryHigh,
    stop_loss: payload.stopLoss,
    target_price: payload.targetPrice,
    invalidation: payload.invalidation,
    watch_conditions: payload.watchConditions,
    reason: payload.reason,
    risk_summary: payload.riskSummary,
    catalyst_summary: payload.catalystSummary,
    evidence: payload.evidence,
    data_quality_summary: payload.dataQualitySummary,
    plan_quality: payload.planQuality,
    status: payload.status,
    expires_at: payload.expiresAt,
    metadata: payload.metadata,
    report_language: payload.reportLanguage,
  });
}

function toSnakeOutcomeRunPayload(payload: DecisionSignalOutcomeRunRequest): Record<string, unknown> {
  return omitUndefined({
    signal_id: payload.signalId,
    horizons: payload.horizons,
    force: payload.force,
    market: payload.market,
    stock_code: payload.stockCode,
    action: payload.action,
    source_type: payload.sourceType,
    status: payload.status,
    limit: payload.limit,
  });
}

function toListParams(params: DecisionSignalListParams = {}): Record<string, string | number | boolean> {
  return omitUndefined({
    market: params.market,
    stock_code: params.stockCode,
    action: params.action,
    market_phase: params.marketPhase,
    source_type: params.sourceType,
    source_report_id: params.sourceReportId,
    trace_id: params.traceId,
    trigger_source: params.triggerSource,
    status: params.status,
    created_from: params.createdFrom,
    created_to: params.createdTo,
    expires_from: params.expiresFrom,
    expires_to: params.expiresTo,
    holding_only: params.holdingOnly,
    account_id: params.accountId,
    page: params.page,
    page_size: params.pageSize,
  }) as Record<string, string | number | boolean>;
}

function toOutcomeListParams(params: DecisionSignalOutcomeListParams = {}): Record<string, string | number> {
  return omitUndefined({
    signal_id: params.signalId,
    horizon: params.horizon,
    engine_version: params.engineVersion,
    eval_status: params.evalStatus,
    outcome: params.outcome,
    page: params.page,
    page_size: params.pageSize,
  }) as Record<string, string | number>;
}

function toOutcomeStatsParams(params: DecisionSignalOutcomeStatsParams = {}): Record<string, string | string[]> {
  return omitUndefined({
    horizons: params.horizons,
    engine_version: params.engineVersion,
    statuses: params.statuses,
  }) as Record<string, string | string[]>;
}

function toLatestParams(params: DecisionSignalLatestParams = {}): Record<string, string | number> {
  return omitUndefined({
    market: params.market,
    limit: params.limit,
  }) as Record<string, string | number>;
}

function toSnakeStatusPayload(payload: DecisionSignalStatusUpdateRequest): Record<string, unknown> {
  return omitUndefined({
    status: payload.status,
    metadata: payload.metadata,
  });
}

function toSnakeFeedbackPayload(payload: DecisionSignalFeedbackRequest): Record<string, unknown> {
  return omitUndefined({
    feedback_value: payload.feedbackValue,
    reason_code: payload.reasonCode,
    note: payload.note,
    source: payload.source,
  });
}

function toLatestStockCodePath(stockCode: string): string {
  if (stockCode.includes('/')) {
    throw new Error(
      'DecisionSignal latest stockCode cannot contain "/" because the backend route accepts a single path segment; use 00700, HK00700, or 00700.HK.',
    );
  }
  return encodeURIComponent(stockCode);
}

export const decisionSignalsApi = {
  async create(payload: DecisionSignalCreateRequest): Promise<DecisionSignalMutationResponse> {
    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/decision-signals',
      toSnakeCreatePayload(payload),
    );
    return toDecisionSignalMutationResponse(response.data);
  },

  async list(params: DecisionSignalListParams = {}): Promise<DecisionSignalListResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/decision-signals', {
      params: toListParams(params),
    });
    return toDecisionSignalListResponse(response.data);
  },

  async get(signalId: number): Promise<DecisionSignalItem> {
    const response = await apiClient.get<Record<string, unknown>>(`/api/v1/decision-signals/${signalId}`);
    return toDecisionSignalItem(response.data);
  },

  async getLatest(
    stockCode: string,
    params: DecisionSignalLatestParams = {},
  ): Promise<DecisionSignalListResponse> {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/decision-signals/latest/${toLatestStockCodePath(stockCode)}`,
      { params: toLatestParams(params) },
    );
    return toDecisionSignalListResponse(response.data);
  },

  async updateStatus(
    signalId: number,
    payload: DecisionSignalStatusUpdateRequest,
  ): Promise<DecisionSignalItem> {
    const response = await apiClient.patch<Record<string, unknown>>(
      `/api/v1/decision-signals/${signalId}/status`,
      toSnakeStatusPayload(payload),
    );
    return toDecisionSignalItem(response.data);
  },

  async runOutcomes(payload: DecisionSignalOutcomeRunRequest): Promise<DecisionSignalOutcomeRunResponse> {
    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/decision-signals/outcomes/run',
      toSnakeOutcomeRunPayload(payload),
    );
    return toDecisionSignalOutcomeRunResponse(response.data);
  },

  async listOutcomes(params: DecisionSignalOutcomeListParams = {}): Promise<DecisionSignalOutcomeListResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/decision-signals/outcomes', {
      params: toOutcomeListParams(params),
    });
    return toDecisionSignalOutcomeListResponse(response.data);
  },

  async getOutcomeStats(
    params: DecisionSignalOutcomeStatsParams = {},
  ): Promise<DecisionSignalOutcomeStatsResponse> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/decision-signals/outcomes/stats', {
      params: toOutcomeStatsParams(params),
      paramsSerializer: {
        serialize: serializeRepeatedQueryParams,
      },
    });
    return toDecisionSignalOutcomeStatsResponse(response.data);
  },

  async getSignalOutcomes(signalId: number): Promise<DecisionSignalOutcomeListResponse> {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/decision-signals/${signalId}/outcomes`,
    );
    return toDecisionSignalOutcomeListResponse(response.data);
  },

  async getFeedback(signalId: number): Promise<DecisionSignalFeedbackItem> {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/decision-signals/${signalId}/feedback`,
    );
    return toDecisionSignalFeedbackItem(response.data);
  },

  async putFeedback(
    signalId: number,
    payload: DecisionSignalFeedbackRequest,
  ): Promise<DecisionSignalFeedbackItem> {
    const response = await apiClient.put<Record<string, unknown>>(
      `/api/v1/decision-signals/${signalId}/feedback`,
      toSnakeFeedbackPayload(payload),
    );
    return toDecisionSignalFeedbackItem(response.data);
  },
};
