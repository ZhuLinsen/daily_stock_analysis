import type { UiLanguage } from '../i18n/uiText';

const localeFor = (language: UiLanguage): string => (
  language === 'ko' ? 'ko-KR' : language === 'en' ? 'en-US' : 'zh-CN'
);

export const formatDateTime = (value?: string | null, language: UiLanguage = 'ko'): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat(localeFor(language), {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
};

export const formatDate = (value?: string, language: UiLanguage = 'ko'): string => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat(localeFor(language), {
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

/**
 * Returns the date N days ago as YYYY-MM-DD in Asia/Seoul timezone.
 * Consistent with getTodayInSeoul() so both ends of the date range
 * are expressed in the same timezone as the backend.
 */
export const getRecentStartDate = (days: number): string => {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul' }).format(date);
};

/**
 * Returns today's date as YYYY-MM-DD in Asia/Seoul timezone.
 * Use this instead of the browser-local date for market-day UI semantics.
 */
export const getTodayInSeoul = (): string =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul' }).format(new Date());

/** @deprecated Use getTodayInSeoul for the Korean-market default. */
export const getTodayInShanghai = getTodayInSeoul;

export const formatReportType = (value?: string, language: UiLanguage = 'ko'): string => {
  if (!value) return '—';
  const labels: Record<UiLanguage, Record<string, string>> = {
    ko: {
      simple: '일반', detailed: '표준', full: '전체', brief: '요약', market_review: '시장 복기',
    },
    en: {
      simple: 'Standard', detailed: 'Detailed', full: 'Full', brief: 'Brief', market_review: 'Market review',
    },
    zh: {
      simple: '普通', detailed: '标准', full: '完整', brief: '简版', market_review: '大盘',
    },
  };
  if (labels[language][value]) return labels[language][value];
  return value;
};
