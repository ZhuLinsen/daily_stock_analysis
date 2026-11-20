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

const CURRENCY_MARKERS = ['元', '¥', '￥', '$', 'NT$', 'HK$', 'US$', '₩', '円'];
const INDICATOR_PREFIX_RE = /(?:MA|EMA|SMA|WMA|BOLL|RSI|KDJ|MACD|WR|BIAS|T\+)$/i;
const PERIOD_UNIT_RE = /^(?:%|％|日|周|月|年|天|个交易日)/;

function extractFirstPriceToken(segment: string): number | null {
  const numRe = /\d+(?:\.\d+)?/g;
  let match: RegExpExecArray | null;
  while ((match = numRe.exec(segment)) !== null) {
    const startIdx = match.index;
    const prefix = segment.slice(Math.max(0, startIdx - 6), startIdx);
    if (INDICATOR_PREFIX_RE.test(prefix)) {
      continue;
    }
    const suffix = segment.slice(startIdx + match[0].length).trimStart();
    if (PERIOD_UNIT_RE.test(suffix) && !CURRENCY_MARKERS.some((m) => suffix.startsWith(m))) {
      continue;
    }
    const val = Number(match[0]);
    if (Number.isFinite(val) && val > 0) {
      return val;
    }
  }
  return null;
}

/**
 * Extract finite positive trading price from strategy strings (e.g. "1480元", "$210.50", "1,480 - 1,500"),
 * while skipping technical-indicator period numbers like MA5/MA10 or pure percentage targets.
 */
export function parseStrategyPriceLevel(raw?: string | null): number | null {
  if (!raw || typeof raw !== 'string') {
    return null;
  }
  const cleaned = raw.replace(/[,，]/g, '').trim();
  if (!cleaned || cleaned === '-' || cleaned === '--' || cleaned === '—' || /^n\/?a$/i.test(cleaned)) {
    return null;
  }

  if (/^\d+(?:\.\d+)?$/.test(cleaned)) {
    const direct = Number(cleaned);
    return Number.isFinite(direct) && direct > 0 ? direct : null;
  }

  const parenPositions = [cleaned.indexOf('('), cleaned.indexOf('（')].filter((idx) => idx !== -1);
  const parenPos = parenPositions.length > 0 ? Math.min(...parenPositions) : cleaned.length;
  const beforeParen = cleaned.slice(0, parenPos).trim() || cleaned;

  const hasCurrency = CURRENCY_MARKERS.some((marker) => cleaned.includes(marker));
  if ((beforeParen.includes('%') || beforeParen.includes('％')) && !hasCurrency) {
    return null;
  }

  const colonPos = Math.max(cleaned.lastIndexOf('：'), cleaned.lastIndexOf(':'));
  const yuanPos = cleaned.indexOf('元', colonPos !== -1 ? colonPos + 1 : 0);
  if (yuanPos !== -1) {
    const segStart = colonPos !== -1 ? colonPos + 1 : 0;
    const yuanVal = extractFirstPriceToken(cleaned.slice(segStart, yuanPos));
    if (yuanVal !== null) {
      return yuanVal;
    }
  }

  return extractFirstPriceToken(beforeParen);
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
