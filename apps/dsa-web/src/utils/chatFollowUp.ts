import type { AnalysisReport } from '../types/analysis';
import { historyApi } from '../api/history';
import { looksLikeStockCode, validateStockCode } from './validation';
import { normalizeStockCode, resolveRegisteredIndexCanonical } from './stockCode';
import type { RegisteredIndexIdentity } from './stockCode';

export interface ChatFollowUpContext {
  stock_code: string;
  stock_name: string | null;
  previous_analysis_summary?: unknown;
  previous_strategy?: unknown;
  previous_price?: number;
  previous_change_pct?: number;
  market_structure_context?: unknown;
}

type ResolveChatFollowUpContextParams = {
  stockCode: string;
  stockName: string | null;
  recordId?: number;
  index?: ReadonlyArray<RegisteredIndexIdentity>;
};

const MAX_FOLLOW_UP_NAME_LENGTH = 80;

function hasInvalidFollowUpNameCharacter(value: string): boolean {
  return Array.from(value).some((character) => {
    const code = character.charCodeAt(0);
    return code < 32 || code === 127;
  });
}

export function sanitizeFollowUpStockCode(stockCode: string | null): string | null {
  if (!stockCode) {
    return null;
  }

  const { valid, normalized } = validateStockCode(stockCode);
  return valid ? normalized : null;
}

export function sanitizeFollowUpStockName(stockName: string | null): string | null {
  const normalized = stockName?.trim().replace(/\s+/g, ' ') ?? '';
  if (!normalized) {
    return null;
  }

  if (
    normalized.length > MAX_FOLLOW_UP_NAME_LENGTH
    || hasInvalidFollowUpNameCharacter(normalized)
  ) {
    return null;
  }

  return normalized;
}

function toSnakeCaseKey(value: string): string {
  return value
    .replace(/([a-z\d])([A-Z])/g, '$1_$2')
    .replace(/-/g, '_')
    .toLowerCase();
}

function convertMarketStructureToSnakeCase(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => convertMarketStructureToSnakeCase(item));
  }
  if (value === null || typeof value !== 'object') {
    return value;
  }

  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, item]) => [
      toSnakeCaseKey(key),
      convertMarketStructureToSnakeCase(item),
    ]),
  );
}

function getMarketStructureContextForAgent(report?: AnalysisReport | null): unknown | undefined {
  const marketStructure = report?.details?.marketStructure;
  if (marketStructure === null || typeof marketStructure !== 'object') {
    return undefined;
  }
  if (Array.isArray(marketStructure)) {
    return undefined;
  }
  if (!Object.keys(marketStructure).length) {
    return undefined;
  }
  return convertMarketStructureToSnakeCase(marketStructure);
}

export function parseFollowUpRecordId(recordId: string | null): number | undefined {
  if (!recordId || !/^\d+$/.test(recordId)) {
    return undefined;
  }

  const parsed = Number(recordId);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    return undefined;
  }

  return parsed;
}

export function buildFollowUpPrompt(stockCode: string, stockName: string | null): string {
  const displayName = stockName ? `${stockName}(${stockCode})` : stockCode;
  return `请深入分析 ${displayName}`;
}

function reportIdentityKey(code: string, index: ReadonlyArray<RegisteredIndexIdentity>, type?: 'stock' | 'index'): string | null {
  const trimmed = code.trim();
  if (!trimmed) return null;
  const registeredIndex = type !== 'stock' ? resolveRegisteredIndexCanonical(index, trimmed) : null;
  if (type === 'index' || registeredIndex) return `index:${registeredIndex ?? trimmed.toLowerCase()}`;
  const folded = trimmed.toUpperCase();
  const matches = new Set(index.filter((item) => item.assetType !== 'index'
    && reportCodeForms(item).includes(folded))
    .map((item) => item.canonicalCode.trim().toUpperCase()));
  if (matches.size > 1) return null;
  if (matches.size === 1) return `stock:${[...matches][0]}`;
  // Only HK format aliases can be folded without losing a market. Keep full
  // CN prefixes/suffixes and JP/KR suffixes when no registry proves equivalence.
  return `stock:${/^(?:HK\d{1,5}|\d{1,5}\.HK|\d{5})$/i.test(trimmed)
    ? normalizeStockCode(trimmed).toUpperCase() : folded}`;
}

function reportCodeForms(item: RegisteredIndexIdentity): string[] {
  const forms = [item.canonicalCode, item.displayCode, ...(item.aliases ?? [])]
    .filter(looksLikeStockCode).map((code) => code.trim().toUpperCase());
  // These equivalent spellings use the row's explicit market, never a market
  // inferred from bare digits. Name aliases are not code identity evidence.
  const canonical = item.canonicalCode.trim().toUpperCase();
  const cn = /^(\d{6})\.(SH|SZ|BJ)$/.exec(canonical);
  if (cn) forms.push(`${cn[2]}${cn[1]}`);
  const hk = /^(\d{1,5})\.HK$/.exec(canonical);
  if (hk) forms.push(normalizeStockCode(canonical));
  const us = /^([A-Z]{1,5})\.US$/.exec(canonical);
  if (us) forms.push(us[1]);
  return forms;
}

export function buildChatFollowUpContext(
  stockCode: string,
  stockName: string | null,
  report?: AnalysisReport | null,
  index: ReadonlyArray<RegisteredIndexIdentity> = [],
  assetType?: 'stock' | 'index',
): ChatFollowUpContext {
  const context: ChatFollowUpContext = {
    stock_code: stockCode,
    stock_name: stockName,
  };

  const requestKey = reportIdentityKey(stockCode, index, assetType);
  const reportKey = report?.meta?.stockCode
    ? reportIdentityKey(report.meta.stockCode, index, report.meta.assetType) : null;
  if (!report || !requestKey || requestKey !== reportKey) {
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

  const marketStructureContext = getMarketStructureContextForAgent(report);
  if (marketStructureContext) {
    context.market_structure_context = marketStructureContext;
  }

  return context;
}

export async function resolveChatFollowUpContext({
  stockCode,
  stockName,
  recordId,
  index = [],
}: ResolveChatFollowUpContextParams): Promise<ChatFollowUpContext> {
  if (!recordId) {
    return buildChatFollowUpContext(stockCode, stockName);
  }

  try {
    const report = await historyApi.getDetail(recordId);
    return buildChatFollowUpContext(stockCode, stockName, report, index);
  } catch {
    return buildChatFollowUpContext(stockCode, stockName);
  }
}
