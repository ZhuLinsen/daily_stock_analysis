import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ParsedApiError } from '../../api/error';
import { getParsedApiError } from '../../api/error';
import type { StockQuoteSnapshot } from '../../api/stocks';
import { stocksApi } from '../../api/stocks';
import type { ReportLanguage } from '../../types/analysis';
import { normalizeReportLanguage } from '../../utils/reportLanguage';
import { ApiErrorAlert, Card, Tooltip } from '../common';
import { DashboardPanelHeader, DashboardStateBlock } from '../dashboard';

const QUOTE_FIELD_KEYS = [
  'price',
  'pre_close',
  'open_price',
  'high',
  'low',
  'change_amount',
  'change_pct',
  'amplitude',
  'volume',
  'amount',
  'volume_ratio',
  'turnover_rate',
  'change_60d',
  'high_52w',
  'low_52w',
  'vwap',
  'bid_ask_ratio',
  'trade_count',
] as const;

type QuoteFieldKey = (typeof QUOTE_FIELD_KEYS)[number];

const MA_KEYS = ['ma5', 'ma10', 'ma20', 'ma60'] as const;

/** 百分比口径字段（值本身已是百分数，展示时补 % 后缀） */
const PERCENT_FIELD_KEYS: ReadonlySet<QuoteFieldKey> = new Set([
  'change_pct',
  'amplitude',
  'turnover_rate',
  'change_60d',
  'bid_ask_ratio',
]);

/** 大数可读格式化字段（成交量/成交额） */
const COMPACT_FIELD_KEYS: ReadonlySet<QuoteFieldKey> = new Set(['volume', 'amount']);

/** 带正负号的涨跌字段（正绿负红） */
const SIGNED_FIELD_KEYS: ReadonlySet<QuoteFieldKey> = new Set([
  'change_amount',
  'change_pct',
  'change_60d',
]);

const QUOTE_TEXT = {
  zh: {
    eyebrow: '行情快照',
    title: '实时行情',
    refresh: '刷新',
    retry: '重试',
    dismiss: '关闭',
    loading: '加载行情中...',
    emptyTitle: '暂无行情数据',
    emptyDescription: '数据源暂未返回可用行情，可稍后刷新再试。',
    copy: '复制行情',
    copied: '已复制',
    copyFailed: '复制失败',
    partialMissing: '部分字段缺失',
    missingFieldsLabel: '缺失字段',
    stale: '行情可能滞后',
    sourceLabel: '数据源',
    maLabel: 'MA 均线（5/10/20/60）',
    price: '最新价',
    pre_close: '昨收',
    open_price: '今开',
    high: '最高',
    low: '最低',
    change_amount: '涨跌额',
    change_pct: '涨跌幅',
    amplitude: '振幅',
    volume: '成交量',
    amount: '成交额',
    volume_ratio: '量比',
    turnover_rate: '换手率',
    change_60d: '60日涨跌',
    high_52w: '52周最高',
    low_52w: '52周最低',
    vwap: 'VWAP 均价',
    bid_ask_ratio: '委比',
    trade_count: '成交笔数',
  },
  en: {
    eyebrow: 'QUOTE SNAPSHOT',
    title: 'Live Quote',
    refresh: 'Refresh',
    retry: 'Retry',
    dismiss: 'Close',
    loading: 'Loading quote...',
    emptyTitle: 'No quote data',
    emptyDescription: 'No usable quote returned yet; refresh again later.',
    copy: 'Copy quote',
    copied: 'Copied',
    copyFailed: 'Copy failed',
    partialMissing: 'Some fields missing',
    missingFieldsLabel: 'Missing fields',
    stale: 'Quote may be stale',
    sourceLabel: 'Source',
    maLabel: 'Moving Averages (5/10/20/60)',
    price: 'Latest Price',
    pre_close: 'Prev Close',
    open_price: 'Open',
    high: 'High',
    low: 'Low',
    change_amount: 'Change',
    change_pct: 'Change %',
    amplitude: 'Amplitude',
    volume: 'Volume',
    amount: 'Turnover',
    volume_ratio: 'Volume Ratio',
    turnover_rate: 'Turnover Rate',
    change_60d: '60D Change',
    high_52w: '52W High',
    low_52w: '52W Low',
    vwap: 'VWAP',
    bid_ask_ratio: 'Bid-Ask Ratio',
    trade_count: 'Trade Count',
  },
  ko: {
    eyebrow: '시세 스냅샷',
    title: '실시간 시세',
    refresh: '새로고침',
    retry: '재시도',
    dismiss: '닫기',
    loading: '시세 불러오는 중...',
    emptyTitle: '시세 데이터 없음',
    emptyDescription: '아직 사용 가능한 시세가 없습니다. 잠시 후 새로고침하세요.',
    copy: '시세 복사',
    copied: '복사됨',
    copyFailed: '복사 실패',
    partialMissing: '일부 필드 누락',
    missingFieldsLabel: '누락 필드',
    stale: '시세 지연 가능',
    sourceLabel: '데이터 소스',
    maLabel: '이동평균 (5/10/20/60)',
    price: '현재가',
    pre_close: '전일 종가',
    open_price: '시가',
    high: '고가',
    low: '저가',
    change_amount: '등락액',
    change_pct: '등락률',
    amplitude: '진폭',
    volume: '거래량',
    amount: '거래대금',
    volume_ratio: '거래 비율',
    turnover_rate: '회전율',
    change_60d: '60일 등락',
    high_52w: '52주 최고',
    low_52w: '52주 최저',
    vwap: 'VWAP',
    bid_ask_ratio: '매수·매도 비율',
    trade_count: '거래 횟수',
  },
} as const;

type QuoteText = (typeof QUOTE_TEXT)[ReportLanguage];

const localeForLanguage = (language: ReportLanguage): string => {
  if (language === 'en') return 'en-US';
  if (language === 'ko') return 'ko-KR';
  return 'zh-CN';
};

/** 数值直出（保留合理精度，去掉多余尾零） */
const formatPlainNumber = (value: number): string => String(Math.round(value * 1e6) / 1e6);

/** 成交量/成交额等大数按语言习惯做可读压缩格式化（如 200万 / 3亿 / 51M / 3B） */
const formatCompactNumber = (value: number, language: ReportLanguage): string => {
  try {
    return new Intl.NumberFormat(localeForLanguage(language), {
      notation: 'compact',
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return formatPlainNumber(value);
  }
};

const formatQuoteValue = (
  value: number | null | undefined,
  key: QuoteFieldKey,
  language: ReportLanguage,
): string => {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—';
  }
  const compact = COMPACT_FIELD_KEYS.has(key)
    ? formatCompactNumber(value, language)
    : formatPlainNumber(value);
  return PERCENT_FIELD_KEYS.has(key) ? `${compact}%` : compact;
};

const signedValueClass = (
  value: number | null | undefined,
  key: QuoteFieldKey,
): string => {
  if (!SIGNED_FIELD_KEYS.has(key) || value === null || value === undefined || value === 0) {
    return 'text-foreground';
  }
  return value > 0 ? 'text-success' : 'text-danger';
};

type QuoteRow = { key: QuoteFieldKey; label: string; display: string; value: number | null };

const buildQuoteRows = (snapshot: StockQuoteSnapshot, text: QuoteText, language: ReportLanguage): QuoteRow[] =>
  QUOTE_FIELD_KEYS.map((key) => {
    const value = snapshot[key];
    return {
      key,
      label: text[key],
      display: formatQuoteValue(value, key, language),
      value,
    };
  });

const formatMaEntry = (value: number | null): string =>
  value === null || value === undefined ? '—' : formatPlainNumber(value);

const buildMaCopyLine = (snapshot: StockQuoteSnapshot): string =>
  MA_KEYS.map((maKey) => formatMaEntry(snapshot[maKey])).join(' / ');

/**
 * 个股行情快照面板（issue #771 看板行情 Web 部分）。
 *
 * 消费 GET /api/v1/stocks/{code}/quote（22 字段 + 数据质量元数据）：
 * - 22 字段网格（MA 四档合并一格、volume/amount 可读格式化）
 * - null/缺失字段统一"—"占位，missing_fields/source 以轻量标注透出
 * - loading/error/empty 三态（DashboardStateBlock 范式，error 可重试）
 * - 一键复制全部字段为 label: value 可读文本（navigator.clipboard）
 * - zh/en/ko 三语词条（组件内常量表，沿用报告区既有 i18n 结构）
 */
export const QuotePanel: React.FC<{
  stockCode?: string;
  language?: ReportLanguage;
}> = ({ stockCode, language = 'zh' }) => {
  const reportLanguage = normalizeReportLanguage(language);
  const text = QUOTE_TEXT[reportLanguage];
  const [snapshot, setSnapshot] = useState<StockQuoteSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const copyResetTimerRef = useRef<number | null>(null);

  const clearCopyTimer = useCallback(() => {
    if (copyResetTimerRef.current !== null) {
      window.clearTimeout(copyResetTimerRef.current);
      copyResetTimerRef.current = null;
    }
  }, []);

  const scheduleCopyReset = useCallback((nextState: 'copied' | 'failed') => {
    clearCopyTimer();
    setCopyState(nextState);
    copyResetTimerRef.current = window.setTimeout(() => {
      setCopyState('idle');
      copyResetTimerRef.current = null;
    }, 2000);
  }, [clearCopyTimer]);

  useEffect(() => {
    return () => {
      clearCopyTimer();
    };
  }, [clearCopyTimer]);

  const fetchQuote = useCallback(async () => {
    if (!stockCode) return;
    setIsLoading(true);
    setError(null);

    try {
      const data = await stocksApi.getQuote(stockCode);
      setSnapshot(data);
    } catch (err) {
      setError(getParsedApiError(err));
      setSnapshot(null);
    } finally {
      setIsLoading(false);
    }
  }, [stockCode]);

  useEffect(() => {
    setSnapshot(null);
    setError(null);

    if (stockCode) {
      void fetchQuote();
    }
  }, [stockCode, fetchQuote]);

  const handleCopy = useCallback(async () => {
    if (!snapshot || copyState !== 'idle') return;
    if (!navigator.clipboard?.writeText) {
      console.error('Copy quote failed: clipboard API unavailable');
      scheduleCopyReset('failed');
      return;
    }
    const lines: string[] = [];
    const headerParts = [snapshot.stock_code, snapshot.stock_name ?? ''].filter(Boolean);
    if (headerParts.length > 0) {
      lines.push(`${text.title} ${headerParts.join(' ')}`);
    }
    for (const row of buildQuoteRows(snapshot, text, reportLanguage)) {
      lines.push(`${row.label}: ${row.display}`);
    }
    lines.push(`${text.maLabel}: ${buildMaCopyLine(snapshot)}`);
    if (snapshot.source) {
      lines.push(`${text.sourceLabel}: ${snapshot.source}`);
    }
    const missingFields = snapshot.missing_fields ?? [];
    if (missingFields.length > 0) {
      lines.push(`${text.missingFieldsLabel}: ${missingFields.join(', ')}`);
    }
    try {
      await navigator.clipboard.writeText(lines.join('\n'));
      scheduleCopyReset('copied');
    } catch (err) {
      console.error('Copy quote failed:', err);
      scheduleCopyReset('failed');
    }
  }, [copyState, reportLanguage, scheduleCopyReset, snapshot, text]);

  if (!stockCode) {
    return null;
  }

  const missingFields = snapshot?.missing_fields ?? [];
  const isSnapshotEmpty = Boolean(
    snapshot
    && (snapshot.data_quality === 'unavailable'
      || (QUOTE_FIELD_KEYS.every((key) => snapshot[key] === null)
        && MA_KEYS.every((maKey) => snapshot[maKey] === null))),
  );

  const copyLabel = copyState === 'copied' ? text.copied : copyState === 'failed' ? text.copyFailed : text.copy;

  return (
    <Card variant="bordered" padding="md" className="home-panel-card">
      <DashboardPanelHeader
        eyebrow={text.eyebrow}
        title={text.title}
        actions={(
          <div className="flex items-center gap-2">
            {isLoading ? (
              <div className="home-spinner h-3.5 w-3.5 animate-spin border-2" aria-hidden="true" />
            ) : null}
            <button
              type="button"
              onClick={() => void handleCopy()}
              disabled={!snapshot || isSnapshotEmpty || copyState !== 'idle'}
              className="home-accent-link text-xs disabled:opacity-50"
              aria-label={copyLabel}
            >
              {copyLabel}
            </button>
            <button
              type="button"
              onClick={() => void fetchQuote()}
              className="home-accent-link text-xs"
              aria-label={text.refresh}
            >
              {text.refresh}
            </button>
          </div>
        )}
      />

      {error && !isLoading && (
        <ApiErrorAlert
          error={error}
          actionLabel={text.retry}
          onAction={() => void fetchQuote()}
          dismissLabel={text.dismiss}
        />
      )}

      {isLoading && !error && (
        <DashboardStateBlock
          compact
          loading
          title={text.loading}
        />
      )}

      {!isLoading && !error && snapshot && isSnapshotEmpty && (
        <DashboardStateBlock
          compact
          title={text.emptyTitle}
          description={text.emptyDescription}
          icon={(
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 14l-7-7m0 0l-7 7m7-7v18" />
            </svg>
          )}
        />
      )}

      {!isLoading && !error && snapshot && !isSnapshotEmpty && (
        <>
          {(snapshot.source || snapshot.currency || snapshot.is_stale || missingFields.length > 0) && (
            <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-text">
              {snapshot.source ? (
                <span className="home-accent-chip px-2 py-0.5">
                  {`${text.sourceLabel}: ${snapshot.source}`}
                </span>
              ) : null}
              {snapshot.currency ? (
                <span className="home-accent-chip px-2 py-0.5">{snapshot.currency}</span>
              ) : null}
              {snapshot.is_stale ? (
                <span className="text-warning">{text.stale}</span>
              ) : null}
              {missingFields.length > 0 ? (
                <Tooltip content={missingFields.join(', ')}>
                  <span className="text-warning">
                    {`${text.partialMissing}（${missingFields.length}）`}
                  </span>
                </Tooltip>
              ) : null}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3 text-left sm:grid-cols-3 lg:grid-cols-4">
            {buildQuoteRows(snapshot, text, reportLanguage).map((row) => (
              <div
                key={row.key}
                className="home-subpanel p-3"
                data-quote-field={row.key}
              >
                <p className="text-xs text-muted-text">{row.label}</p>
                <p className={`mt-1 font-mono text-sm font-medium ${signedValueClass(row.value, row.key)}`}>
                  {row.display}
                </p>
              </div>
            ))}
            <div className="home-subpanel p-3 sm:col-span-2 lg:col-span-4" data-quote-field="ma">
              <p className="text-xs text-muted-text">{text.maLabel}</p>
              <p className="mt-1 font-mono text-sm font-medium text-foreground">
                {MA_KEYS.map((maKey) => (
                  <span key={maKey} className="mr-4 whitespace-nowrap">
                    {`${maKey.toUpperCase()} ${formatMaEntry(snapshot[maKey])}`}
                  </span>
                ))}
              </p>
            </div>
          </div>
        </>
      )}
    </Card>
  );
};
