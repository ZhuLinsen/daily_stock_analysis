/**
 * 股票分析相关类型定义
 * 与 API 规范 (api_spec.json) 对齐
 */

// ============ 请求类型 ============

export interface AnalysisRequest {
  stockCode: string;
  reportType?: 'simple' | 'detailed';
  forceRefresh?: boolean;
  asyncMode?: boolean;
}

// ============ 报告类型 ============

/** 报告元信息 */
export interface ReportMeta {
  id?: number;  // 分析历史记录主键 ID（历史报告时有此字段）
  queryId: string;
  stockCode: string;
  stockName: string;
  reportType: 'simple' | 'detailed';
  createdAt: string;
  currentPrice?: number;
  changePct?: number;
}

/** 情绪标签 */
export type SentimentLabel = '极度悲观' | '悲观' | '中性' | '乐观' | '极度乐观';

/** 报告概览区 */
export interface ReportSummary {
  analysisSummary: string;
  operationAdvice: string;
  trendPrediction: string;
  sentimentScore: number;
  sentimentLabel?: SentimentLabel;
}

/** 策略点位区 */
export interface ReportStrategy {
  idealBuy?: string;
  secondaryBuy?: string;
  stopLoss?: string;
  takeProfit?: string;
}

/** 详情区（可折叠） */
export interface ReportDetails {
  newsContent?: string;
  rawResult?: Record<string, unknown>;
  contextSnapshot?: Record<string, unknown>;
}

/** 完整分析报告 */
export interface AnalysisReport {
  meta: ReportMeta;
  summary: ReportSummary;
  strategy?: ReportStrategy;
  details?: ReportDetails;
}

// ============ 分析结果类型 ============

/** 同步分析返回结果 */
export interface AnalysisResult {
  queryId: string;
  stockCode: string;
  stockName: string;
  report: AnalysisReport;
  createdAt: string;
}

/** 异步任务接受响应 */
export interface TaskAccepted {
  taskId: string;
  status: 'pending' | 'processing';
  message?: string;
}

/** 任务状态 */
export interface TaskStatus {
  taskId: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress?: number;
  result?: AnalysisResult;
  error?: string;
}

/** 任务详情（用于任务列表和 SSE 事件） */
export interface TaskInfo {
  taskId: string;
  stockCode: string;
  stockName?: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  message?: string;
  reportType: string;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  error?: string;
}

/** 任务列表响应 */
export interface TaskListResponse {
  total: number;
  pending: number;
  processing: number;
  tasks: TaskInfo[];
}

/** 重复任务错误响应 */
export interface DuplicateTaskError {
  error: 'duplicate_task';
  message: string;
  stockCode: string;
  existingTaskId: string;
}

// ============ 历史记录类型 ============

/** 历史记录摘要（列表展示用） */
export interface HistoryItem {
  id: number;  // Record primary key ID, always present for persisted history items
  queryId: string;  // 分析记录关联 query_id（批量分析时重复）
  stockCode: string;
  stockName?: string;
  reportType?: string;
  sentimentScore?: number;
  operationAdvice?: string;
  createdAt: string;
}

/** 历史记录列表响应 */
export interface HistoryListResponse {
  total: number;
  page: number;
  limit: number;
  items: HistoryItem[];
}

/** 新闻情报条目 */
export interface NewsIntelItem {
  title: string;
  snippet: string;
  url: string;
}

/** 新闻情报响应 */
export interface NewsIntelResponse {
  total: number;
  items: NewsIntelItem[];
}

/** 历史列表筛选参数 */
export interface HistoryFilters {
  stockCode?: string;
  startDate?: string;
  endDate?: string;
}

/** 历史列表分页参数 */
export interface HistoryPagination {
  page: number;
  limit: number;
}

// ============ 错误类型 ============

export interface ApiError {
  error: string;
  message: string;
  detail?: Record<string, unknown>;
}

// ============ 辅助函数 ============

/** 根据情绪评分获取情绪标签 */
export const getSentimentLabel = (score: number): SentimentLabel => {
  if (score <= 20) return '极度悲观';
  if (score <= 40) return '悲观';
  if (score <= 60) return '中性';
  if (score <= 80) return '乐观';
  return '极度乐观';
};

/** 根据情绪评分获取颜色 */
export const getSentimentColor = (score: number): string => {
  if (score <= 20) return '#ef4444'; // red-500
  if (score <= 40) return '#f97316'; // orange-500
  if (score <= 60) return '#eab308'; // yellow-500
  if (score <= 80) return '#22c55e'; // green-500
  return '#10b981'; // emerald-500
};
