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
const MOVING_AVERAGE_PERIOD_LIST_RE = /\b\d+(?:\.\d+)?(?:(?:\s*[-‐‑–—/,]+\s*(?:(?:and|or|to|&)\s+)?|\s+(?:and|or|to|&)\s+)\d+(?:\.\d+)?){1,}\s*(?:[-‐‑–—]\s*)?(?:(?:trading\s+)?(?:days?|sessions?|periods?|weeks?|months?|years?|d)|日|周|週|月|年|天|거래일|일|주|개월|년|배|MA|moving\s+averages?)\b/gi;

function isRatioCandidate(segment: string, start: number, end: number): boolean {
  for (const match of segment.matchAll(/\d+(?:\.\d+)?\s*:\s*\d+(?:\.\d+)?/g)) {
    const matchStart = match.index ?? 0;
    if (start >= matchStart && end <= matchStart + match[0].length) {
      return true;
    }
  }
  return false;
}

function isMovingAveragePeriod(segment: string, start: number, end: number): boolean {
  const prefix = segment.slice(0, start);
  const suffix = segment.slice(end);
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
    || /^(?:st|nd|rd|th|차|번째|个)(?=\s|$|[^\p{L}\p{N}_])/iu.test(suffix);
}

function extractFirstPriceToken(segment: string): number | null {
  const candidates = [...segment.matchAll(/[-−]?\d+(?:\.\d+)?/g)].map((match) => {
    const start = match.index ?? 0;
    const end = start + match[0].length;
    const prefix = segment.slice(0, start);
    const suffix = segment.slice(end).trimStart();
    const explicitCurrency = /(?:[$¥₩]|(?:USD|CNY|KRW|JPY)\s*)$/i.test(prefix)
      || /^(?:[元円원]|(?:USD|CNY|KRW|JPY)\b)/i.test(suffix);
    return { match, start, end, suffix, explicitCurrency };
  }).filter(({ start, end, suffix }) => (
    !isMovingAveragePeriod(segment, start, end)
    && !isRatioCandidate(segment, start, end)
    && !isOrdinalCandidate(segment.slice(0, start), suffix)
  ));

  // An explicitly currency-marked candidate is a price even when an ordinal,
  // target number, or risk/reward ratio appears earlier in the sentence.
  for (const { match } of [...candidates.filter((candidate) => candidate.explicitCurrency), ...candidates]) {
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
  // Strip those annotations before looking for a level, including one stated later in the text.
  const priceText = parenthesizedPrice?.[1] ?? cleaned.replace(/\([^()]*(?:\([^()]*\)[^()]*)*\)/g, ' ').split('(', 1)[0];
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
