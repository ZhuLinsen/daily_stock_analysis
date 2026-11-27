import type { UiLanguage } from '../i18n/uiText';
import type {
  PortfolioCashDirection,
  PortfolioCorporateActionType,
  PortfolioFxRefreshResponse,
  PortfolioImportCommitResponse,
  PortfolioImportParseResponse,
  PortfolioPositionItem,
  PortfolioSide,
} from '../types/portfolio';
import { resolveActiveUiLanguage, toDateInputValue } from './format';

export type FxRefreshFeedback = {
  tone: 'neutral' | 'success' | 'warning';
  text: string;
};

export type PortfolioAlertVariant = 'info' | 'success' | 'warning' | 'danger';

export function getTodayIso(): string {
  return toDateInputValue(new Date());
}

export function formatMoney(
  value: number | undefined | null,
  currency = 'CNY',
  language?: UiLanguage,
): string {
  if (value == null || Number.isNaN(value)) return '--';
  const locale = resolveActiveUiLanguage(language) === 'en' ? 'en-US' : 'zh-CN';
  return `${currency} ${Number(value).toLocaleString(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatPct(value: number | undefined | null): string {
  if (value == null || Number.isNaN(value)) return '--';
  return `${value.toFixed(2)}%`;
}

export function formatSignedPct(value: number | undefined | null): string {
  if (value == null || Number.isNaN(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

export function hasPositionPrice(row: PortfolioPositionItem): boolean {
  return row.priceAvailable !== false && row.priceSource !== 'missing';
}

export function formatPositionPrice(row: PortfolioPositionItem): string {
  if (!hasPositionPrice(row)) return '--';
  return row.lastPrice.toFixed(4);
}

export function formatPositionMoney(
  value: number,
  row: PortfolioPositionItem,
  language?: UiLanguage,
): string {
  if (!hasPositionPrice(row)) return '--';
  return formatMoney(value, row.valuationCurrency, language);
}

export function getPositionPriceLabel(row: PortfolioPositionItem, language?: UiLanguage): string {
  const isEnglish = resolveActiveUiLanguage(language) === 'en';
  if (!hasPositionPrice(row)) return isEnglish ? 'No price' : '缺价';
  if (row.priceSource === 'realtime_quote') {
    if (isEnglish) {
      return row.priceProvider ? `Live · ${row.priceProvider}` : 'Live';
    }
    return row.priceProvider ? `实时价 · ${row.priceProvider}` : '实时价';
  }
  if (row.priceSource === 'history_close') {
    if (isEnglish) {
      return row.priceStale && row.priceDate ? `Close · ${row.priceDate}` : 'Close';
    }
    return row.priceStale && row.priceDate ? `收盘价 · ${row.priceDate}` : '收盘价';
  }
  return row.priceSource || (isEnglish ? 'Unknown source' : '未知来源');
}

export function formatSideLabel(value: PortfolioSide, language?: UiLanguage): string {
  const isEnglish = resolveActiveUiLanguage(language) === 'en';
  if (isEnglish) {
    return value === 'buy' ? 'Buy' : 'Sell';
  }
  return value === 'buy' ? '买入' : '卖出';
}

export function formatCashDirectionLabel(value: PortfolioCashDirection, language?: UiLanguage): string {
  const isEnglish = resolveActiveUiLanguage(language) === 'en';
  if (isEnglish) {
    return value === 'in' ? 'Inflow' : 'Outflow';
  }
  return value === 'in' ? '流入' : '流出';
}

export function formatCorporateActionLabel(
  value: PortfolioCorporateActionType,
  language?: UiLanguage,
): string {
  const isEnglish = resolveActiveUiLanguage(language) === 'en';
  if (isEnglish) {
    return value === 'cash_dividend' ? 'Cash dividend' : 'Split / consolidation';
  }
  return value === 'cash_dividend' ? '现金分红' : '拆并股调整';
}

export function formatBrokerLabel(
  value: string,
  displayName?: string,
  language?: UiLanguage,
): string {
  const isEnglish = resolveActiveUiLanguage(language) === 'en';
  if (displayName && displayName.trim()) {
    return isEnglish ? `${value} (${displayName.trim()})` : `${value}（${displayName.trim()}）`;
  }
  if (value === 'huatai') return isEnglish ? 'huatai (Huatai)' : 'huatai（华泰）';
  if (value === 'citic') return isEnglish ? 'citic (CITIC)' : 'citic（中信）';
  if (value === 'cmb') return isEnglish ? 'cmb (CMB)' : 'cmb（招商）';
  return value;
}

export function buildFxRefreshFeedback(
  data: PortfolioFxRefreshResponse,
  language?: UiLanguage,
): FxRefreshFeedback {
  const isEnglish = resolveActiveUiLanguage(language) === 'en';
  if (data.refreshEnabled === false) {
    return {
      tone: 'neutral',
      text: isEnglish ? 'Online FX refresh is disabled.' : '汇率在线刷新已被禁用。',
    };
  }

  if (data.pairCount === 0) {
    return {
      tone: 'neutral',
      text: isEnglish ? 'No FX pairs to refresh in the current scope.' : '当前范围无可刷新的汇率对。',
    };
  }

  if (data.updatedCount > 0 && data.staleCount === 0 && data.errorCount === 0) {
    return {
      tone: 'success',
      text: isEnglish
        ? `FX rates refreshed (${data.updatedCount} ${data.updatedCount === 1 ? 'pair' : 'pairs'} updated).`
        : `汇率已刷新，共更新 ${data.updatedCount} 对。`,
    };
  }

  const summary = isEnglish
    ? `Updated ${data.updatedCount}, stale ${data.staleCount}, failed ${data.errorCount}.`
    : `更新 ${data.updatedCount} 对，仍过期 ${data.staleCount} 对，失败 ${data.errorCount} 对。`;
  if (data.staleCount > 0) {
    return {
      tone: 'warning',
      text: isEnglish
        ? `Refresh attempted, but some pairs still use stale/fallback rates. ${summary}`
        : `已尝试刷新，但仍有部分货币对使用 stale/fallback 汇率。${summary}`,
    };
  }

  return {
    tone: 'warning',
    text: isEnglish
      ? `Online refresh did not fully succeed. ${summary}`
      : `在线刷新未完全成功。${summary}`,
  };
}

export function getFxRefreshFeedbackVariant(tone: FxRefreshFeedback['tone']): PortfolioAlertVariant {
  if (tone === 'success') return 'success';
  if (tone === 'warning') return 'warning';
  return 'info';
}

export function getCsvParseVariant(result: PortfolioImportParseResponse): PortfolioAlertVariant {
  return result.errorCount > 0 || result.skippedCount > 0 ? 'warning' : 'info';
}

export function getCsvCommitVariant(result: PortfolioImportCommitResponse, isDryRun: boolean): PortfolioAlertVariant {
  if (isDryRun) return 'info';
  return result.failedCount > 0 || result.duplicateCount > 0 ? 'warning' : 'success';
}
