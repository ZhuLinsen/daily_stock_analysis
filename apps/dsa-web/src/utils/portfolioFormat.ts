import type {
  PortfolioCashDirection,
  PortfolioCorporateActionType,
  PortfolioFxRefreshResponse,
  PortfolioImportCommitResponse,
  PortfolioImportParseResponse,
  PortfolioPositionItem,
  PortfolioSide,
} from '../types/portfolio';
import type { UiLanguage } from '../i18n/uiText';
import { toDateInputValue } from './format';

export type FxRefreshFeedback = {
  tone: 'neutral' | 'success' | 'warning';
  text: string;
};

export type PortfolioAlertVariant = 'info' | 'success' | 'warning' | 'danger';

export function getTodayIso(): string {
  return toDateInputValue(new Date());
}

export function formatMoney(value: number | undefined | null, currency = 'KRW'): string {
  if (value == null || Number.isNaN(value)) return '--';
  const normalizedCurrency = currency.toUpperCase();
  const fractionDigits = normalizedCurrency === 'KRW' ? 0 : 2;
  return `${normalizedCurrency} ${Number(value).toLocaleString('ko-KR', {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
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

export function formatPositionMoney(value: number, row: PortfolioPositionItem): string {
  if (!hasPositionPrice(row)) return '--';
  return formatMoney(value, row.valuationCurrency);
}

export function getPositionPriceLabel(row: PortfolioPositionItem, language: UiLanguage = 'ko'): string {
  const labels = language === 'zh'
    ? { missing: '缺价', realtime: '实时价', close: '收盘价', unknown: '未知来源' }
    : language === 'en'
      ? { missing: 'Price unavailable', realtime: 'Realtime price', close: 'Close price', unknown: 'Unknown source' }
      : { missing: '시세 없음', realtime: '실시간 시세', close: '종가', unknown: '출처 미상' };
  if (!hasPositionPrice(row)) return labels.missing;
  if (row.priceSource === 'realtime_quote') {
    return row.priceProvider ? `${labels.realtime} · ${row.priceProvider}` : labels.realtime;
  }
  if (row.priceSource === 'history_close') {
    return row.priceStale && row.priceDate ? `${labels.close} · ${row.priceDate}` : labels.close;
  }
  return row.priceSource || labels.unknown;
}

export function formatSideLabel(value: PortfolioSide, language: UiLanguage = 'ko'): string {
  if (language === 'zh') return value === 'buy' ? '买入' : '卖出';
  if (language === 'en') return value === 'buy' ? 'Buy' : 'Sell';
  return value === 'buy' ? '매수' : '매도';
}

export function formatCashDirectionLabel(value: PortfolioCashDirection, language: UiLanguage = 'ko'): string {
  if (language === 'zh') return value === 'in' ? '流入' : '流出';
  if (language === 'en') return value === 'in' ? 'Inflow' : 'Outflow';
  return value === 'in' ? '입금' : '출금';
}

export function formatCorporateActionLabel(value: PortfolioCorporateActionType, language: UiLanguage = 'ko'): string {
  if (language === 'zh') return value === 'cash_dividend' ? '现金分红' : '拆并股调整';
  if (language === 'en') return value === 'cash_dividend' ? 'Cash dividend' : 'Split adjustment';
  return value === 'cash_dividend' ? '현금배당' : '주식 분할·병합 조정';
}

export function formatBrokerLabel(value: string, displayName?: string, language: UiLanguage = 'ko'): string {
  const brackets = language === 'zh' ? ['（', '）'] : ['(', ')'];
  if (displayName && displayName.trim()) return `${value}${brackets[0]}${displayName.trim()}${brackets[1]}`;
  if (value === 'huatai') return language === 'zh' ? 'huatai（华泰）' : language === 'en' ? 'huatai (Huatai)' : 'huatai(화타이증권)';
  if (value === 'citic') return language === 'zh' ? 'citic（中信）' : language === 'en' ? 'citic (CITIC)' : 'citic(중신증권)';
  if (value === 'cmb') return language === 'zh' ? 'cmb（招商）' : language === 'en' ? 'cmb (CMB)' : 'cmb(자오상증권)';
  return value;
}

export function buildFxRefreshFeedback(data: PortfolioFxRefreshResponse, language: UiLanguage = 'ko'): FxRefreshFeedback {
  const text = language === 'zh'
    ? {
      disabled: '汇率在线刷新已被禁用。', none: '当前范围无可刷新的汇率对。', complete: (updated: number) => `汇率已刷新，共更新 ${updated} 对。`,
      summary: (updated: number, stale: number, failed: number) => `更新 ${updated} 对，仍过期 ${stale} 对，失败 ${failed} 对。`,
      partial: (summary: string) => `已尝试刷新，但仍有部分货币对使用 stale/fallback 汇率。${summary}`,
      failed: (summary: string) => `在线刷新未完全成功。${summary}`,
    }
    : language === 'en'
      ? {
        disabled: 'Online FX refresh is disabled.', none: 'No FX pairs can be refreshed for the current scope.', complete: (updated: number) => `${updated} FX pair(s) refreshed.`,
        summary: (updated: number, stale: number, failed: number) => `Updated ${updated}, stale ${stale}, failed ${failed}.`,
        partial: (summary: string) => `Refresh completed with stale or fallback FX rates remaining. ${summary}`,
        failed: (summary: string) => `Online FX refresh did not complete. ${summary}`,
      }
      : {
        disabled: '온라인 환율 새로 고침이 비활성화되어 있습니다.', none: '현재 범위에서 새로 고칠 수 있는 환율 쌍이 없습니다.', complete: (updated: number) => `환율 ${updated}개를 새로 고쳤습니다.`,
        summary: (updated: number, stale: number, failed: number) => `갱신 ${updated}개, 오래된 환율 ${stale}개, 실패 ${failed}개입니다.`,
        partial: (summary: string) => `새로 고침을 시도했지만 일부 통화 쌍은 오래된 또는 대체 환율을 사용합니다. ${summary}`,
        failed: (summary: string) => `온라인 환율 새로 고침이 완전히 완료되지 않았습니다. ${summary}`,
      };
  if (data.refreshEnabled === false) {
    return {
      tone: 'neutral',
      text: text.disabled,
    };
  }

  if (data.pairCount === 0) {
    return {
      tone: 'neutral',
      text: text.none,
    };
  }

  if (data.updatedCount > 0 && data.staleCount === 0 && data.errorCount === 0) {
    return {
      tone: 'success',
      text: text.complete(data.updatedCount),
    };
  }

  const summary = text.summary(data.updatedCount, data.staleCount, data.errorCount);
  if (data.staleCount > 0) {
    return {
      tone: 'warning',
      text: text.partial(summary),
    };
  }

  return {
    tone: 'warning',
    text: text.failed(summary),
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
