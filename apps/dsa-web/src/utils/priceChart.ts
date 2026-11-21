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
const NON_PRICE_UNIT_RE = /^(?:%|percent(?:age)?\b|百分之|퍼센트|日|周|週|月|年|天|个交易日|倍|거래일|일|주|개월|년|배|(?:[-‐‑–]\s*)?(?:(?:trading\s+)?(?:days?|sessions?|periods?)|weeks?|months?|years?|times?|x|d)\b)/i;
const MOVING_AVERAGE_PERIOD_LIST_RE = /\b\d+(?:\.\d+)?(?:(?:\s*[-‐‑–—/,、·，]+\s*(?:(?:and|or|to|&|和|및|와)\s*)?|\s+(?:and|or|to|&|和|및|와)\s*|(?:和|및|와)\s*)\d+(?:\.\d+)?){1,}\s*(?:[-‐‑–—]\s*)?(?:(?:trading\s+)?(?:days?|sessions?|periods?|weeks?|months?|years?|d)|日|周|週|月|年|天|거래일|일|주|개월|년|배|MA|moving\s+averages?)(?![A-Za-z])/giu;
const CURRENT_PRICE_CONTEXT_RE = /(?:current|latest|last|market)\s+price(?:\s+(?:is|of|at))?\s*[:：]?\s*(?:about|around|approx(?:imately)?|approximately)?\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)?$/i;
const CJK_CURRENT_PRICE_CONTEXT_RE = /(?:当前价(?:格)?|目前价(?:格)?|现价)\s*(?:(?:约|大约)\s*)?(?:(?:是|为|在)\s*)?(?:[:：]\s*)?(?:(?:约|大约)\s*)?(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)?$/iu;
const KOREAN_CURRENT_PRICE_CONTEXT_RE = /(?:현재\s*가격?|시세)\s*(?:는|이|가)?\s*(?:[:：]\s*)?약?\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)?$/iu;

const PRICE_UNIT_AFTER_RE = /^\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY|dollars?|euros?)\b|元|美元|美金|港元|港币|港幣|日元|新台币|新臺幣|円|원)/iu;
const PRICE_UNIT_BEFORE_RE = /(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)$/iu;
const RATIO_CONTEXT_RE = /(?:risk\s*[-/]?\s*(?:to\s*[-/]?\s*)?(?:reward|return)|reward\s*(?:[-/]?\s*to\s*[-/]?\s*risk|[-/]\s*risk)|risk\s*reward|ratio|R\s*\/\s*R|风险\s*(?:回报|收益)|回报比|收益比|比率|손익\s*비)/iu;

function isRatioCandidate(segment: string, start: number, end: number): boolean {
  for (const match of segment.matchAll(/\d+(?:\.\d+)?\s*([:：∶︓﹕꞉/／]|比|to)\s*\d+(?:\.\d+)?/gi)) {
    const matchStart = match.index ?? 0;
    const matchEnd = matchStart + match[0].length;
    if (start < matchStart || end > matchEnd) {
      continue;
    }

    // A slash/to joining explicit prices ("60/65 元", "$60/$65") is a
    // price range, not a risk/reward ratio.
    const hasPriceUnit = PRICE_UNIT_AFTER_RE.test(segment.slice(matchEnd))
      || PRICE_UNIT_BEFORE_RE.test(segment.slice(0, matchStart));
    if (hasPriceUnit) {
      continue;
    }

    const separator = match[1].toLowerCase();
    const nearbyText = segment.slice(Math.max(0, matchStart - 40), Math.min(segment.length, matchEnd + 40));
    const needsRatioContext = separator === '/' || separator === '／' || separator === 'to';
    if (!needsRatioContext || RATIO_CONTEXT_RE.test(nearbyText)) {
      return true;
    }
  }
  return false;
}

function isDateCandidate(segment: string, start: number, end: number): boolean {
  const dayMonthYear = [...segment.matchAll(/\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b/g)].find((match) => {
    const matchStart = match.index ?? 0;
    return start >= matchStart && end <= matchStart + match[0].length;
  });
  if (dayMonthYear) {
    const matchStart = dayMonthYear.index ?? 0;
    const matchEnd = matchStart + dayMonthYear[0].length;
    if (start >= matchStart && end <= matchEnd) return true;
  }
  return [...segment.matchAll(/\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}\s*月\s*\d{1,2}\s*(?:日|号)|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?\b|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s*,?\s*(?:\d{4})?\b|\b\d{1,2}[/-]\d{1,2}\b/giu)].some((match) => {
    const matchStart = match.index ?? 0;
    const matchEnd = matchStart + match[0].length;
    if (/^[0-9]{1,2}[/-][0-9]{1,2}$/u.test(match[0])) {
      const [month, day] = match[0].split(/[/-]/u).map(Number);
      if (month > 31 || day > 31 || (month > 12 && day > 12)) {
        return false;
      }
      if (PRICE_UNIT_AFTER_RE.test(segment.slice(matchEnd)) || PRICE_UNIT_BEFORE_RE.test(segment.slice(0, matchStart))) {
        return false;
      }
    }
    return start >= matchStart && end <= matchEnd;
  });
}

function isMovingAveragePeriod(segment: string, start: number, end: number): boolean {
  const prefix = segment.slice(0, start);
  const suffix = segment.slice(end).trimStart();
  if (INDICATOR_PREFIX_RE.test(prefix) || NON_PRICE_UNIT_RE.test(suffix)) {
    return true;
  }
  const conjunctionMatch = /\d+(?:\.\d+)?\s*(?:及|與|与|以及|并)\s*\d+(?:\.\d+)?\s*(?:日|天|周期|periods?|days?)\s*(?:均线|均線|移动平均线|moving\s+averages?)/iu.exec(segment);
  if (conjunctionMatch) {
    const matchStart = conjunctionMatch.index;
    const matchEnd = matchStart + conjunctionMatch[0].length;
    if (start >= matchStart && end <= matchEnd) return true;
  }
  // In phrases such as "5- and 20-day" or "5/20 MA", the unit belongs to
  // the last number, but every number in the list is a moving-average period.
  return [...segment.matchAll(MOVING_AVERAGE_PERIOD_LIST_RE)].some((match) => {
    const matchStart = match.index ?? 0;
    if (start < matchStart || end > matchStart + match[0].length) {
      return false;
    }
    // Keep an explicitly labelled first price in "$48, 20-day ...".
    if (start === matchStart && /(?:[$¥₩]|(?:buy|entry|price|take\s*profit|stop\s*-?\s*loss|理想买入|次优买入|买入价|买点|价格|止盈|止损)\s*[:：]?\s*)[^\d]*$/iu.test(prefix)) {
      return false;
    }
    return true;
  });
}

function isOrdinalCandidate(prefix: string, suffix: string): boolean {
  return /第\s*$/u.test(prefix)
    || /^(?:st|nd|rd|th|차|번째|个)/iu.test(suffix);
}

function isCountCandidate(prefix: string, suffix: string): boolean {
  return /^(?:根\s*K线|根\s*蜡烛|次(?:日线)?\s*收盘|daily\s+closes?\b|consecutive\s+daily\s+closes?\b|closes?\b|consecutive\s+closes?\b)/iu.test(suffix)
    || /(?:连续|consecutive)\s*$/iu.test(prefix);
}

function isIndicatorThresholdCandidate(prefix: string): boolean {
  return /(?:\bRSI|相对强弱指标)\s*(?:低于|小于|高于|超过|回落至|below|drops?\s+below|under|above|rises?\s+above|climbs?\s+above|over|<|>)\s*$/iu.test(prefix);
}

function isCurrentPriceCandidate(prefix: string): boolean {
  return CURRENT_PRICE_CONTEXT_RE.test(prefix)
    || CJK_CURRENT_PRICE_CONTEXT_RE.test(prefix)
    || /(?:当前价(?:格)?|目前价(?:格)?|现价)\s*[:：]\s*(?:约|大约)?\s*(?:是|为|在)\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)?$/iu.test(prefix)
    || KOREAN_CURRENT_PRICE_CONTEXT_RE.test(prefix);
}

function isPercentageCandidate(prefix: string, suffix: string): boolean {
  return /百分之\s*(?:约|約)?\s*$/u.test(prefix) || /^(?:%|percent(?:age)?\b|per\s+cent\b|퍼센트)/iu.test(suffix);
}

function extractFirstPriceToken(segment: string): number | null {
  const candidates = [...segment.matchAll(/[-−]?(?:\d+(?:\.\d+)?|\.\d+)/g)].map((match) => {
    const start = match.index ?? 0;
    const end = start + match[0].length;
    const prefix = segment.slice(0, start);
    const suffix = segment.slice(end).trimStart();
    return { match, start, end, prefix, suffix };
  }).filter(({ start, end, prefix, suffix }) => (
    !isMovingAveragePeriod(segment, start, end)
    && !isRatioCandidate(segment, start, end)
    && !isOrdinalCandidate(prefix, suffix)
    && !isCountCandidate(prefix, suffix)
    && !isIndicatorThresholdCandidate(prefix)
    && !isPercentageCandidate(prefix, suffix)
    && !isDateCandidate(segment, start, end)
    && !isCurrentPriceCandidate(prefix)
  ));

  for (const { match, suffix } of candidates) {
    let value = Number(match[0]);
    if (/^¢/u.test(suffix)) value /= 100;
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
  if (/(?:止损|stop\s*-?\s*loss)[^;；,，]*(?:暂无|不设|没有|无固定|none|no\s+fixed)/iu.test(raw)) return null;
  const cleaned = raw.replace(/(?<!\d)\d{1,2}，(?=\d{3}\b)/g, match => match.replace('，', ''))
    .replace(/，/g, '\uE000').normalize('NFKC')
    .replace(/(?<![\d.])\d{1,2},\d{3}(?!,\d{3})\b/g, match => match.replace(',', ''))
    .replace(/(?<![\d.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?=\s*(?:[$¥₩]|USD|CNY|HKD|TWD|KRW|JPY|元|美元|美金|港元|港币|港幣|日元|新台币|新臺幣|円|원))/giu, match => match.replace(/,/g, ''))
    .replace(/\uE000/g, ',').trim();
  const parenthesizedPrice = /^\(\s*(?:[¥$₩]\s*)?(\d+(?:\.\d+)?)(?:\s*[元円원])?\s*\)$/.exec(cleaned);
  // Report templates put indicator values and supporting conditions in parentheses.
  // Strip indicator annotations, but retain explicit prices in parentheses such as
  // "stop-loss: ($48)" or "止损位：跌破前低（48元）".
  let priceText = parenthesizedPrice?.[1] ?? cleaned.replace(/\([^()]*\)/g, (match, offset: number, source: string) => {
    const prefix = source.slice(0, offset);
    if (/(?:止损|止盈|买入|stop\s*-?\s*loss|take\s*profit|buy)[^()]*\d/iu.test(match)) return match;
    return /(?:\b(?:MA|BOLL|RSI|KDJ|MACD|WR|BIAS)\s*[\d\s/,-]*|均线|均線|移动平均线|moving\s+averages?|이동\s*평균선)\s*(?:附近区域|附近區域|附近|一带|一帶|区域|區域|부근)?\s*[（(]?\s*$/iu.test(prefix)
      ? ' '
      : match;
  });
  if (!parenthesizedPrice) {
    priceText = priceText.replace(/\([^()]*$/g, (match, offset: number, source: string) => {
      const prefix = source.slice(0, offset);
      if (/(?:止损|止盈|买入|stop\s*-?\s*loss|take\s*profit|buy)[^()]*\d/iu.test(match)) return match;
      return /(?:\b(?:MA|BOLL|RSI|KDJ|MACD|WR|BIAS)\s*[\d\s/,-]*|均线|均線|移动平均线|moving\s+averages?|이동\s*평균선)\s*(?:附近区域|附近區域|附近|一带|一帶|区域|區域|부근)?\s*[（(]?\s*$/iu.test(prefix)
        ? ' '
        : match;
    });
  }
  return extractFirstPriceToken(priceText);
}

export function formatChartAxisPrice(value: number): string {
  if (!Number.isFinite(value)) {
    return '';
  }
  const abs = Math.abs(value);
  if (abs >= 1000) {
    return value.toFixed(0);
  }
  if (abs >= 1) {
    return value.toFixed(2);
  }
  return value.toFixed(3);
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
      ma5 = sum5 / 5;
    }

    let ma20: number | null = null;
    if (idx >= 19) {
      let sum20 = 0;
      for (let i = idx - 19; i <= idx; i += 1) {
        sum20 += Number(sorted[i].close);
      }
      ma20 = sum20 / 20;
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
