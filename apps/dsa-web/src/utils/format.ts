import type { UiLanguage } from '../i18n/uiText';
import { getUiLanguageStorage, normalizeUiLanguage, UI_LANGUAGE_STORAGE_KEY } from './uiLanguage';

const mountedTabUiLanguages = new Map<symbol, UiLanguage>();

export function registerActiveTabUiLanguage(id: symbol, language: UiLanguage): void {
  mountedTabUiLanguages.delete(id);
  mountedTabUiLanguages.set(id, language);
}

export function unregisterActiveTabUiLanguage(id: symbol): void {
  mountedTabUiLanguages.delete(id);
}

export function resolveActiveUiLanguage(language?: UiLanguage): UiLanguage {
  if (language) {
    return language;
  }
  if (mountedTabUiLanguages.size > 0) {
    let latest: UiLanguage = 'zh';
    for (const activeLanguage of mountedTabUiLanguages.values()) {
      latest = activeLanguage;
    }
    return latest;
  }
  if (typeof document !== 'undefined') {
    const docLang = document.documentElement.lang.trim().toLowerCase();
    if (docLang.startsWith('en')) {
      return 'en';
    }
    if (docLang.startsWith('zh')) {
      return 'zh';
    }
  }
  const storage = getUiLanguageStorage();
  if (storage) {
    try {
      const stored = normalizeUiLanguage(storage.getItem(UI_LANGUAGE_STORAGE_KEY));
      if (stored) {
        return stored;
      }
    } catch {
      // Ignore storage read failures and fall through to default language.
    }
  }
  return 'zh';
}

export const formatDateTime = (value?: string | null, language?: UiLanguage): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  const locale = resolveActiveUiLanguage(language) === 'en' ? 'en-US' : 'zh-CN';
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
};

export const formatShortDateTime = (value?: string | null, language?: UiLanguage): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  const locale = resolveActiveUiLanguage(language) === 'en' ? 'en-US' : 'zh-CN';
  return new Intl.DateTimeFormat(locale, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
};

export const formatDate = (value?: string, language?: UiLanguage): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  const locale = resolveActiveUiLanguage(language) === 'en' ? 'en-US' : 'zh-CN';
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
};

export const toDateInputValue = (date: Date): string => {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
};

export function shiftDateKey(dateKey: string, days: number): string {
  const date = new Date(`${dateKey}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/**
 * Formats a Date as YYYY-MM-DD in Asia/Shanghai timezone using formatToParts()
 * so non-ISO locale formats (e.g. CLDR 42 M/d/y in en-CA) cannot produce
 * unparseable date strings.
 */
export const formatDateInShanghai = (date: Date = new Date()): string => {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date);
  const year = parts.find((part) => part.type === 'year')?.value;
  const month = parts.find((part) => part.type === 'month')?.value;
  const day = parts.find((part) => part.type === 'day')?.value;
  if (!year || !month || !day) {
    throw new RangeError('Unable to format date in Asia/Shanghai timezone');
  }
  return `${year.padStart(4, '0')}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
};

/**
 * Returns today's date as YYYY-MM-DD in Asia/Shanghai timezone.
 * Use this instead of the browser-local date for market-day UI semantics.
 */
export const getTodayInShanghai = (): string => formatDateInShanghai(new Date());

/** Returns the Shanghai calendar date N days before today. */
export const getRecentStartDate = (days: number): string =>
  shiftDateKey(getTodayInShanghai(), -days);

const REPORT_TYPE_LABELS: Record<UiLanguage, Record<string, string>> = {
  zh: {
    simple: '普通',
    detailed: '标准',
    full: '完整',
    brief: '简版',
    market_review: '大盘',
  },
  en: {
    simple: 'Simple',
    detailed: 'Detailed',
    full: 'Full',
    brief: 'Brief',
    market_review: 'Market Review',
  },
};

export const formatReportType = (value?: string, language?: UiLanguage): string => {
  if (!value) return '—';
  const labels = REPORT_TYPE_LABELS[resolveActiveUiLanguage(language)];
  return Object.hasOwn(labels, value) ? labels[value] : value;
};
