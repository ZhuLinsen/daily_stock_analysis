import type { AnalysisReport } from '../types/analysis';
import { historyApi } from '../api/history';

export interface ChatFollowUpContext {
  stock_code: string;
  stock_name: string | null;
  previous_analysis_summary?: unknown;
  previous_strategy?: unknown;
  previous_price?: number;
  previous_change_pct?: number;
}

type ResolveChatFollowUpContextParams = {
  stockCode: string;
  stockName: string | null;
  recordId?: number;
};

export function buildFollowUpPrompt(stockCode: string, stockName: string | null): string {
  const displayName = stockName ? `${stockName}(${stockCode})` : stockCode;
  return `请深入分析 ${displayName}`;
}

export function buildChatFollowUpContext(
  stockCode: string,
  stockName: string | null,
  report?: AnalysisReport | null,
): ChatFollowUpContext {
  const context: ChatFollowUpContext = {
    stock_code: stockCode,
    stock_name: stockName,
  };

  if (!report) {
    return context;
  }

  if (report.summary) {
    context.previous_analysis_summary = report.summary;
  }

  if (report.strategy) {
    context.previous_strategy = report.strategy;
  }

  if (report.meta) {
    context.previous_price = report.meta.currentPrice;
    context.previous_change_pct = report.meta.changePct;
  }

  return context;
}

export async function resolveChatFollowUpContext({
  stockCode,
  stockName,
  recordId,
}: ResolveChatFollowUpContextParams): Promise<ChatFollowUpContext> {
  if (!recordId) {
    return buildChatFollowUpContext(stockCode, stockName);
  }

  try {
    const report = await historyApi.getDetail(recordId);
    return buildChatFollowUpContext(stockCode, stockName, report);
  } catch {
    return buildChatFollowUpContext(stockCode, stockName);
  }
}
