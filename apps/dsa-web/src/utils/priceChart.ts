import type { StockKLineItem } from '../api/stocks';

export interface PriceChartDatum {
  date: string;
  shortDate: string;
  close: number;
  high: number;
  low: number;
  ma5: number | null;
  ma20: number | null;
}

const INDICATOR_PREFIX_RE = /(?:MA|BOLL|RSI|KDJ|MACD|WR|BIAS|T\+)\s*(?:\d+\s*\/\s*)*$/i;
const NON_PRICE_UNIT_RE = /^(?:%|日|周|週|月|年|天|个交易日|倍|거래일|일|주|개월|년|배|(?:[-‐‑–]\s*)?(?:(?:trading\s+)?(?:days?|sessions?|periods?)|weeks?|months?|years?|times?|x|d)\b)/i;
const MOVING_AVERAGE_PERIOD_LIST_RE = /\b\d+(?:\.\d+)?(?:(?:\s*[-‐‑–—/,]+\s*(?:(?:and|or|to|&)\s+)?|\s+(?:and|or|to|&)\s+)\d+(?:\.\d+)?){1,}\s*(?:[-‐‑–—]\s*)?(?:(?:trading\s+)?(?:days?|sessions?|periods?|weeks?|months?|years?|d)|日|周|週|月|年|天|거래일|일|주|개월|년|배|MA|moving\s+averages?)(?![A-Za-z])/gi;
const CURRENT_PRICE_CONTEXT_RE = /(?:current|latest|last|market)\s+price(?:\s+(?:is|of|at))?\s*[:：]?\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)?$/i;
const CJK_CURRENT_PRICE_CONTEXT_RE = /(?:当前价(?:格)?|目前价(?:格)?|现价)\s*(?:是|为|在|约)?\s*[:：]?\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)?$/iu;
const KOREAN_CURRENT_PRICE_CONTEXT_RE = /(?:현재\s*가격?|시세)\s*(?:는|이|가)?\s*[:：]?\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)?$/iu;

function isRatioCandidate(segment: string, start: number, end: number): boolean {
  for (const match of segment.matchAll(/\d+(?:\.\d+)?\s*(?:[:：∶︓﹕꞉/／]|比)\s*\d+(?:\.\d+)?/g)) {
    const matchStart = match.index ?? 0;
    if (start >= matchStart && end <= matchStart + match[0].length) {
      return true;
    }
  }
  return false;
}

function isMovingAveragePeriod(segment: string, start: number, end: number): boolean {
  const prefix = segment.slice(0, start);
  const suffix = segment.slice(end).trimStart();
  if (INDICATOR_PREFIX_RE.test(prefix) || NON_PRICE_UNIT_RE.test(suffix)) {
    return true;
  }
  // In phrases such as "5- and 20-day" or "5/20 MA", the unit belongs to
  // the last number, but every number in the list is a moving-average period.
  return [...segment.matchAll(MOVING_AVERAGE_PERIOD_LIST_RE)].some((match) => {
    const matchStart = match.index ?? 0;
    return start >= matchStart && end <= matchStart + match[0].length;
  });
}

function isOrdinalCandidate(prefix: string, suffix: string): boolean {
  return /第\s*$/u.test(prefix)
    || /^(?:st|nd|rd|th|차|번째|个)/iu.test(suffix);
}

function isCurrentPriceCandidate(prefix: string): boolean {
  return CURRENT_PRICE_CONTEXT_RE.test(prefix)
    || CJK_CURRENT_PRICE_CONTEXT_RE.test(prefix)
    || KOREAN_CURRENT_PRICE_CONTEXT_RE.test(prefix);
}

function extractFirstPriceToken(segment: string): number | null {
  const candidates = [...segment.matchAll(/[-−]?\d+(?:\.\d+)?/g)].map((match) => {
    const start = match.index ?? 0;
    const end = start + match[0].length;
    const prefix = segment.slice(0, start);
    const suffix = segment.slice(end).trimStart();
    return { match, start, end, prefix, suffix };
  }).filter(({ start, end, prefix, suffix }) => (
    !isMovingAveragePeriod(segment, start, end)
    && !isRatioCandidate(segment, start, end)
    && !isOrdinalCandidate(prefix, suffix)
    && !isCurrentPriceCandidate(prefix)
  ));

  for (const { match } of candidates) {
    const value = Number(match[0]);
    if (Number.isFinite(value) && value > 0) {
      return value;
    }
  }
  return null;
}

/**
 * Extract finite positive trading price from strategy strings (e.g. "1480元", "$210.50", "1,480 - 1,500"),
 * while skipping technical-indicator period numbers like MA5/MA10 or pure percentage targets.
 */
export function parseStrategyPriceLevel(raw?: string | null): number | null {
  if (typeof raw !== 'string') {
    return null;
  }
  const cleaned = raw.normalize('NFKC').replace(/(?<=\d),(?=\d{3}(?:\D|$))/g, '').trim();
  const parenthesizedPrice = /^\(\s*(?:[¥$₩]\s*)?(\d+(?:\.\d+)?)(?:\s*[元円원])?\s*\)$/.exec(cleaned);
  // Report templates put indicator values and supporting conditions in parentheses.
  // Strip indicator annotations, but retain explicit prices in parentheses such as
  // "stop-loss: ($48)" or "止损位：跌破前低（48元）".
  let priceText = parenthesizedPrice?.[1] ?? cleaned.replace(/\([^()]*\)/g, (match, offset: number, source: string) => {
    const prefix = source.slice(0, offset);
    return /(?:\b(?:MA|BOLL|RSI|KDJ|MACD|WR|BIAS)\s*[\d\s/,-]*|均线|移动平均线|moving\s+average)\s*$/iu.test(prefix)
      ? ' '
      : match;
  });
  if (!parenthesizedPrice) {
    priceText = priceText.replace(/\([^()]*$/g, (match, offset: number, source: string) => {
      const prefix = source.slice(0, offset);
      return /(?:\b(?:MA|BOLL|RSI|KDJ|MACD|WR|BIAS)\s*[\d\s/,-]*|均线|移动平均线|moving\s+average)\s*$/iu.test(prefix)
        ? ' '
        : match;
    });
  }
  return extractFirstPriceToken(priceText);
}

/**
 * Enrich chronological daily bars with rolling MA5 / MA20 overlays computed on full input,
 * then keep at most the latest `displayLimit` trading sessions (default 60D).
 */
export function enrichBarsWithMovingAverages(
  bars: StockKLineItem[],
  displayLimit = 60,
): PriceChartDatum[] {
  const sorted = [...bars]
    .filter((b) => b && Number.isFinite(Number(b.close)) && Number(b.close) > 0)
    .sort((a, b) => String(a.date).localeCompare(String(b.date)));

  const enriched = sorted.map((bar, idx) => {
    const close = Number(bar.close);
    const high = Number.isFinite(Number(bar.high)) && Number(bar.high) > 0 ? Number(bar.high) : close;
    const low = Number.isFinite(Number(bar.low)) && Number(bar.low) > 0 ? Number(bar.low) : close;

    let ma5: number | null = null;
    if (idx >= 4) {
      let sum5 = 0;
      for (let i = idx - 4; i <= idx; i += 1) {
        sum5 += Number(sorted[i].close);
      }
      ma5 = Number((sum5 / 5).toFixed(2));
    }

    let ma20: number | null = null;
    if (idx >= 19) {
      let sum20 = 0;
      for (let i = idx - 19; i <= idx; i += 1) {
        sum20 += Number(sorted[i].close);
      }
      ma20 = Number((sum20 / 20).toFixed(2));
    }

    return {
      date: bar.date,
      shortDate: bar.date.length >= 10 ? bar.date.slice(5, 10) : bar.date,
      close,
      high,
      low,
      ma5,
      ma20,
    };
  });

  if (displayLimit > 0 && enriched.length > displayLimit) {
    return enriched.slice(-displayLimit);
  }
  return enriched;
}
