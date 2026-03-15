import apiClient from './index';
import { toCamelCase } from './utils';
import type {
  AnalysisRequest,
  AnalysisResult,
  AnalysisReport,
  TaskStatus,
  TaskListResponse,
} from '../types/analysis';

// ============ API 接口 ============

export const analysisApi = {
  /**
   * 触发股票分析
   * @param data 分析请求参数
   * @returns 同步模式返回 AnalysisResult，异步模式返回 TaskAccepted（需检查 status code）
   */
  analyze: async (data: AnalysisRequest): Promise<AnalysisResult> => {
    const requestData = {
      stock_code: data.stockCode,
      report_type: data.reportType || 'detailed',
      force_refresh: data.forceRefresh || false,
      async_mode: data.asyncMode || false,
    };

    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/analysis/analyze',
      requestData
    );

    const result = toCamelCase<AnalysisResult>(response.data);

    // 确保 report 字段正确转换
    if (result.report) {
      result.report = toCamelCase<AnalysisReport>(result.report);
    }

    return result;
  },

  /**
   * 异步模式触发分析
   * 返回 task_id，通过 SSE 或轮询获取结果
   * @param data 分析请求参数
   * @returns 任务接受响应或抛出 409 错误
   */
  analyzeAsync: async (data: AnalysisRequest): Promise<{ taskId: string; status: string; message?: string }> => {
    const requestData = {
      stock_code: data.stockCode,
      report_type: data.reportType || 'detailed',
      force_refresh: data.forceRefresh || false,
      async_mode: true,
    };

    const response = await apiClient.post<Record<string, unknown>>(
      '/api/v1/analysis/analyze',
      requestData,
      {
        // 允许 202 状态码
        validateStatus: (status) => status === 200 || status === 202 || status === 409,
      }
    );

    // 处理 409 重复提交错误
    if (response.status === 409) {
      const errorData = toCamelCase<{
        error: string;
        message: string;
        stockCode: string;
        existingTaskId: string;
      }>(response.data);
      throw new DuplicateTaskError(errorData.stockCode, errorData.existingTaskId, errorData.message);
    }

    return toCamelCase<{ taskId: string; status: string; message?: string }>(response.data);
  },

  /**
   * 获取异步任务状态
   * @param taskId 任务 ID
   */
  getStatus: async (taskId: string): Promise<TaskStatus> => {
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/analysis/status/${taskId}`
    );

    const data = toCamelCase<TaskStatus>(response.data);

    // 确保嵌套的 result 也被正确转换
    if (data.result) {
      data.result = toCamelCase<AnalysisResult>(data.result);
      if (data.result.report) {
        data.result.report = toCamelCase<AnalysisReport>(data.result.report);
      }
    }

    return data;
  },

  /**
   * 获取任务列表
   * @param params 筛选参数
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
   * 获取 SSE 流 URL
   * 用于 EventSource 连接
   */
  getTaskStreamUrl: (): string => {
    // 获取 API base URL
    const baseUrl = apiClient.defaults.baseURL || '';
    return `${baseUrl}/api/v1/analysis/tasks/stream`;
  },
};

// ============ 自定义错误类 ============

/**
 * 重复任务错误
 * 当股票正在分析中时抛出
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
