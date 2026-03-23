import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  AnalysisRequest,
  AnalysisResult,
  AnalyzeResponse,
  AnalyzeAsyncResponse,
  AnalysisReport,
  TaskStatus,
  TaskListResponse,
} from '../types/analysis';

// ============ API Interfaces ============

export const analysisApi = {
  /**
   * Trigger stock analysis.
   * @param data Analysis request payload
   * @returns Sync mode returns AnalysisResult; async mode returns accepted task payloads
   */
  analyze: async (data: AnalysisRequest): Promise<AnalyzeResponse> => {
    const requestData = {
      stock_code: data.stockCode,
      stock_codes: data.stockCodes,
      report_type: data.reportType || 'detailed',
      force_refresh: data.forceRefresh || false,
      async_mode: data.asyncMode || false,
      stock_name: data.stockName,
      original_query: data.originalQuery,
      selection_source: data.selectionSource,
    };

    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/analysis/analyze',
      requestData
    );

    const result = toCamelCase<AnalyzeResponse>(response.data);

    // Ensure the sync analysis report payload is converted recursively.
    if ('report' in result && result.report) {
      result.report = toCamelCase<AnalysisReport>(result.report);
    }

    return result;
  },

  /**
   * Trigger analysis in async mode.
   * @param data Analysis request payload
   * @returns Accepted task payloads; throws DuplicateTaskError on 409
   */
  analyzeAsync: async (data: AnalysisRequest): Promise<AnalyzeAsyncResponse> => {
    const requestData = {
      stock_code: data.stockCode,
      stock_codes: data.stockCodes,
      report_type: data.reportType || 'detailed',
      force_refresh: data.forceRefresh || false,
      async_mode: true,
      stock_name: data.stockName,
      original_query: data.originalQuery,
      selection_source: data.selectionSource,
    };

    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/analysis/analyze',
      requestData,
      {
        // Allow 202 accepted responses in addition to standard success codes.
        validateStatus: (status) => status === 200 || status === 202 || status === 409,
      }
    );

    // Handle duplicate submission compatibility.
    if (response.status === 409) {
      const errorData = toCamelCase<{
        error: string;
        message: string;
        stockCode: string;
        existingTaskId: string;
      }>(response.data);
      throw new DuplicateTaskError(errorData.stockCode, errorData.existingTaskId, errorData.message);
    }

    return toCamelCase<AnalyzeAsyncResponse>(response.data);
  },

  /**
   * Get async task status.
   * @param taskId Task ID
   */
  getStatus: async (taskId: string): Promise<TaskStatus> => {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/analysis/status/${taskId}`
    );

    const data = toCamelCase<TaskStatus>(response.data);

    // Ensure nested result payloads are converted recursively.
    if (data.result) {
      data.result = toCamelCase<AnalysisResult>(data.result);
      if (data.result.report) {
        data.result.report = toCamelCase<AnalysisReport>(data.result.report);
      }
    }

    return data;
  },

  /**
   * Get task list.
   * @param params Filter parameters
   */
  getTasks: async (params?: {
    status?: string;
    limit?: number;
  }): Promise<TaskListResponse> => {
    const response = await apiClient.get<Record<string, unknown>>(
      '/api/v1/analysis/tasks',
      { params }
    );

    const data = toCamelCase<TaskListResponse>(response.data);

    return data;
  },

  /**
   * Get the SSE stream URL.
   */
  getTaskStreamUrl: (): string => {
    // Read API base URL from the shared client.
    const baseUrl = apiClient.defaults.baseURL || '';
    return `${baseUrl}/api/v1/analysis/tasks/stream`;
  },
};

// ============ Custom Error Classes ============

/**
 * Duplicate task error.
 */
export class DuplicateTaskError extends Error {
  stockCode: string;
  existingTaskId: string;

  constructor(stockCode: string, existingTaskId: string, message?: string) {
    super(message || `股票 ${stockCode} 正在分析中`);
    this.name = 'DuplicateTaskError';
    this.stockCode = stockCode;
    this.existingTaskId = existingTaskId;
  }
}
