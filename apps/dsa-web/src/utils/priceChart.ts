import type { StockKLineItem } from '../api/stocks';

export interface PriceChartDatum {
  date: string;
  shortDate: string;
  open?: number | null;
  close: number;
  high: number;
  low: number;
  hasValidRange?: boolean;
  volume?: number | null;
  ma5: number | null;
  ma20: number | null;
  ma60?: number | null;
  ema20?: number | null;
  bollUpper?: number | null;
  bollMid?: number | null;
  bollLower?: number | null;
  bollBandwidthPct?: number | null;
  bollPercentB?: number | null;
  rsi14?: number | null;
  macdDif?: number | null;
  macdDea?: number | null;
  macdHist?: number | null;
  macdPrevDiff?: number | null;
  kdjK?: number | null;
  kdjD?: number | null;
  kdjJ?: number | null;
  atr14?: number | null;
  atrPct?: number | null;
}

export type RsiRegime = 'oversold' | 'overbought' | 'neutral';
export type MacdSignalState = 'bullish_cross' | 'bearish_cross' | 'bullish' | 'bearish' | 'neutral';

export interface QuantTelemetrySummary {
  riskRewardRatio: number | null;
  upsidePct: number | null;
  downsidePct: number | null;
  ma20BiasPct: number | null;
  ma60BiasPct: number | null;
  annualizedVolPct: number | null;
  maxDrawdownPct: number | null;
  rsi14: number | null;
  rsiRegime: RsiRegime | null;
  bollBandwidthPct: number | null;
  bollPercentB: number | null;
  bollSqueeze: boolean;
  macdSignal: MacdSignalState | null;
  atrPct: number | null;
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

export function formatChartDisplayPrice(value: number): string {
  if (!Number.isFinite(value)) {
    return '';
  }
  const abs = Math.abs(value);
  if (abs >= 1) {
    return value.toFixed(2);
  }
  if (abs >= 0.01) {
    return value.toFixed(3);
  }
  return value.toFixed(4);
}

/**
 * Enrich chronological daily bars with rolling MA5/MA20/MA60, EMA20, BOLL(20,2),
 * RSI(14), MACD(12,26,9), KDJ(9,3,3), and ATR(14) computed over full history,
 * then keep at most the latest `displayLimit` trading sessions (default 60D; <=0 keeps all).
 */
export function enrichBarsWithMovingAverages(
  bars: StockKLineItem[],
  displayLimit = 60,
  options?: { ohlcSynthesized?: boolean },
): PriceChartDatum[] {
  const ohlcSynthesized = Boolean(options?.ohlcSynthesized);
  const preSorted = [...bars]
    .filter((b) => b && Number.isFinite(Number(b.close)) && Number(b.close) > 0)
    .sort((a, b) => String(a.date).localeCompare(String(b.date)));

  const deduped = new Map<string, StockKLineItem>();
  for (const bar of preSorted) {
    deduped.set(String(bar.date), bar);
  }
  const sorted = [...deduped.values()];

  if (sorted.length === 0) {
    return [];
  }

  let ema12 = Number(sorted[0].close);
  let ema26 = Number(sorted[0].close);
  let ema20 = Number(sorted[0].close);
  let dea = 0;
  let prevRawMacdDiff: number | null = null;

  let avgGain = 0;
  let avgLoss = 0;
  let kdjK = 50;
  let kdjD = 50;
  let atr14State = 0;
  let sumTr14 = 0;
  let atrValidCount = 0;

  const k12 = 2 / 13;
  const k26 = 2 / 27;
  const k20 = 2 / 21;
  const k9 = 2 / 10;

  const normalized = sorted.map((bar) => {
    const close = Number(bar.close);
    const validHigh =
      !ohlcSynthesized
      && bar.high != null
      && Number.isFinite(Number(bar.high))
      && Number(bar.high) > 0
        ? Number(bar.high)
        : null;
    const validLow =
      !ohlcSynthesized
      && bar.low != null
      && Number.isFinite(Number(bar.low))
      && Number(bar.low) > 0
        ? Number(bar.low)
        : null;
    const hasValidRange = validHigh != null && validLow != null;
    const high = hasValidRange ? Math.max(validHigh, validLow, close) : close;
    const low = hasValidRange ? Math.min(validHigh, validLow, close) : close;
    const open =
      !ohlcSynthesized
      && bar.open != null
      && Number.isFinite(Number(bar.open))
      && Number(bar.open) > 0
        ? Number(bar.open)
        : null;
    const volume =
      bar.volume != null && Number.isFinite(Number(bar.volume)) && Number(bar.volume) >= 0
        ? Number(bar.volume)
        : null;
    return { bar, close, high, low, hasValidRange, open, volume };
  });

  const enriched: PriceChartDatum[] = normalized.map(({ bar, close, high, low, hasValidRange, open, volume }, idx) => {
    let ma5: number | null = null;
    if (idx >= 4) {
      let sum5 = 0;
      for (let i = idx - 4; i <= idx; i += 1) {
        sum5 += normalized[i].close;
      }
      ma5 = sum5 / 5;
    }

    let ma20: number | null = null;
    let bollUpper: number | null = null;
    let bollMid: number | null = null;
    let bollLower: number | null = null;
    let bollBandwidthPct: number | null = null;
    let bollPercentB: number | null = null;
    if (idx >= 19) {
      let sum20 = 0;
      for (let i = idx - 19; i <= idx; i += 1) {
        sum20 += normalized[i].close;
      }
      ma20 = sum20 / 20;
      let variance = 0;
      for (let i = idx - 19; i <= idx; i += 1) {
        const diff = normalized[i].close - ma20;
        variance += diff * diff;
      }
      const std = Math.sqrt(variance / 20);
      bollMid = ma20;
      bollUpper = ma20 + 2 * std;
      bollLower = ma20 - 2 * std;
      bollBandwidthPct = ma20 > 0 ? ((bollUpper - bollLower) / ma20) * 100 : null;
      bollPercentB = bollUpper > bollLower ? (close - bollLower) / (bollUpper - bollLower) : null;
    }

    let ma60: number | null = null;
    if (idx >= 59) {
      let sum60 = 0;
      for (let i = idx - 59; i <= idx; i += 1) {
        sum60 += normalized[i].close;
      }
      ma60 = sum60 / 60;
    }

    if (idx > 0) {
      ema12 = close * k12 + ema12 * (1 - k12);
      ema26 = close * k26 + ema26 * (1 - k26);
      ema20 = close * k20 + ema20 * (1 - k20);
    }
    const rawDif = ema12 - ema26;
    dea = idx === 0 ? rawDif : rawDif * k9 + dea * (1 - k9);
    const rawDiff = rawDif - dea;
    const macdDif = idx >= 25 ? rawDif : null;
    const macdDea = idx >= 25 ? dea : null;
    const macdHist = idx >= 25 ? 2 * rawDiff : null;
    const macdPrevDiff = idx >= 25 ? prevRawMacdDiff : null;
    prevRawMacdDiff = rawDiff;

    let rsi14: number | null = null;
    if (idx > 0) {
      const prevClose = normalized[idx - 1].close;
      const change = close - prevClose;
      const gain = change > 0 ? change : 0;
      const loss = change < 0 ? -change : 0;
      if (idx <= 14) {
        avgGain += gain / 14;
        avgLoss += loss / 14;
      } else {
        avgGain = (avgGain * 13 + gain) / 14;
        avgLoss = (avgLoss * 13 + loss) / 14;
      }
      if (idx >= 14) {
        if (avgGain === 0 && avgLoss === 0) {
          rsi14 = 50;
        } else if (avgLoss === 0) {
          rsi14 = 100;
        } else {
          const rs = avgGain / avgLoss;
          rsi14 = 100 - 100 / (1 + rs);
        }
      }
    }

    let kOut: number | null = null;
    let dOut: number | null = null;
    let jOut: number | null = null;
    if (idx >= 8) {
      let low9 = Number.POSITIVE_INFINITY;
      let high9 = Number.NEGATIVE_INFINITY;
      let windowRangeValid = true;
      for (let i = idx - 8; i <= idx; i += 1) {
        const b = normalized[i];
        if (!b.hasValidRange) {
          windowRangeValid = false;
          break;
        }
        if (b.high > high9) high9 = b.high;
        if (b.low < low9) low9 = b.low;
      }
      if (!windowRangeValid) {
        kdjK = 50;
        kdjD = 50;
      } else {
        const rsv = high9 === low9 ? 50 : ((close - low9) / (high9 - low9)) * 100;
        kdjK = (2 * kdjK + rsv) / 3;
        kdjD = (2 * kdjD + kdjK) / 3;
        kOut = kdjK;
        dOut = kdjD;
        jOut = 3 * kdjK - 2 * kdjD;
      }
    }

    let atr14: number | null = null;
    let atrPct: number | null = null;
    if (idx > 0) {
      if (!hasValidRange) {
        atrValidCount = 0;
        sumTr14 = 0;
        atr14State = 0;
      } else {
        const prevClose = normalized[idx - 1].close;
        const tr = Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose));
        if (atrValidCount < 14) {
          sumTr14 += tr;
          atrValidCount += 1;
          if (atrValidCount === 14) {
            atr14State = sumTr14 / 14;
            atr14 = atr14State;
          }
        } else {
          atr14State = (atr14State * 13 + tr) / 14;
          atr14 = atr14State;
        }
        if (atr14 != null && close > 0) {
          atrPct = (atr14 / close) * 100;
        }
      }
    }

    return {
      date: bar.date,
      shortDate: bar.date.length >= 10 ? bar.date.slice(5, 10) : bar.date,
      open,
      close,
      high,
      low,
      hasValidRange,
      volume,
      ma5,
      ma20,
      ma60,
      ema20: idx >= 4 ? ema20 : null,
      bollUpper,
      bollMid,
      bollLower,
      bollBandwidthPct,
      bollPercentB,
      rsi14,
      macdDif,
      macdDea,
      macdHist,
      macdPrevDiff,
      kdjK: kOut,
      kdjD: dOut,
      kdjJ: jOut,
      atr14,
      atrPct,
    };
  });

  if (displayLimit > 0 && enriched.length > displayLimit) {
    return enriched.slice(-displayLimit);
  }
  return enriched;
}

/**
 * Compute live quantitative risk, valuation-anchor distance, and momentum/squeeze telemetry
 * for the visible chart window and strategy price levels.
 */
export function computeQuantTelemetry(
  data: PriceChartDatum[],
  levels?: {
    idealBuy?: number | null;
    secondaryBuy?: number | null;
    stopLoss?: number | null;
    takeProfit?: number | null;
  },
  options?: { priceAdjustment?: string | null },
): QuantTelemetrySummary {
  if (data.length === 0) {
    return {
      riskRewardRatio: null,
      upsidePct: null,
      downsidePct: null,
      ma20BiasPct: null,
      ma60BiasPct: null,
      annualizedVolPct: null,
      maxDrawdownPct: null,
      rsi14: null,
      rsiRegime: null,
      bollBandwidthPct: null,
      bollPercentB: null,
      bollSqueeze: false,
      macdSignal: null,
      atrPct: null,
    };
  }

  const latest = data[data.length - 1];
  const entryRef =
    levels?.idealBuy != null && levels.idealBuy > 0
      ? levels.idealBuy
      : levels?.secondaryBuy != null && levels.secondaryBuy > 0
        ? levels.secondaryBuy
        : latest.close;
  const stopLoss = levels?.stopLoss ?? null;
  const takeProfit = levels?.takeProfit ?? null;

  const upsidePct =
    takeProfit != null && entryRef > 0 ? ((takeProfit - entryRef) / entryRef) * 100 : null;
  const downsidePct =
    stopLoss != null && entryRef > 0 ? ((entryRef - stopLoss) / entryRef) * 100 : null;
  const minStopDistance = entryRef * 1e-4;
  const riskRewardRatio =
    stopLoss != null
    && takeProfit != null
    && entryRef > 0
    && (entryRef - stopLoss) >= minStopDistance
    && takeProfit > entryRef
      ? (takeProfit - entryRef) / (entryRef - stopLoss)
      : null;

  if (options?.priceAdjustment === 'unadjusted') {
    return {
      riskRewardRatio,
      upsidePct,
      downsidePct,
      ma20BiasPct: null,
      ma60BiasPct: null,
      annualizedVolPct: null,
      maxDrawdownPct: null,
      rsi14: null,
      rsiRegime: null,
      bollBandwidthPct: null,
      bollPercentB: null,
      bollSqueeze: false,
      macdSignal: null,
      atrPct: null,
    };
  }

  const ma20BiasPct =
    latest.ma20 != null && latest.ma20 > 0 ? ((latest.close - latest.ma20) / latest.ma20) * 100 : null;
  const ma60BiasPct =
    latest.ma60 != null && latest.ma60 > 0 ? ((latest.close - latest.ma60) / latest.ma60) * 100 : null;

  const returns: number[] = [];
  for (let i = 1; i < data.length; i += 1) {
    const prev = data[i - 1].close;
    if (prev > 0) {
      returns.push((data[i].close - prev) / prev);
    }
  }
  let annualizedVolPct: number | null = null;
  if (returns.length >= 5) {
    const mean = returns.reduce((acc, r) => acc + r, 0) / returns.length;
    const sampleVar =
      returns.reduce((acc, r) => acc + (r - mean) * (r - mean), 0) / Math.max(1, returns.length - 1);
    annualizedVolPct = Math.sqrt(sampleVar) * Math.sqrt(252) * 100;
  }

  let maxDrawdownPct: number | null = null;
  if (data.length >= 2) {
    let peak = data[0].close;
    let minDd = 0;
    for (const bar of data) {
      if (bar.close > peak) {
        peak = bar.close;
      }
      if (peak > 0) {
        const dd = ((bar.close - peak) / peak) * 100;
        if (dd < minDd) {
          minDd = dd;
        }
      }
    }
    maxDrawdownPct = minDd;
  }

  const rsi14 = latest.rsi14 ?? null;
  const rsiRegime: RsiRegime | null =
    rsi14 == null ? null : rsi14 <= 30 ? 'oversold' : rsi14 >= 70 ? 'overbought' : 'neutral';

  const bollBandwidthPct = latest.bollBandwidthPct ?? null;
  const validBandwidths = data
    .map((d) => d.bollBandwidthPct)
    .filter((v): v is number => v != null && Number.isFinite(v));
  let bollSqueeze = false;
  if (bollBandwidthPct != null) {
    if (bollBandwidthPct <= 8) {
      bollSqueeze = true;
    } else if (validBandwidths.length >= 10) {
      const sortedBw = [...validBandwidths].sort((a, b) => a - b);
      const q20Index = Math.floor(sortedBw.length * 0.2);
      if (bollBandwidthPct <= sortedBw[q20Index]) {
        bollSqueeze = true;
      }
    }
  }

  let macdSignal: MacdSignalState | null = null;
  const MACD_EPSILON = 1e-9;
  if (latest.macdDif != null && latest.macdDea != null) {
    const diff = latest.macdDif - latest.macdDea;
    const prev = data.length >= 2 ? data[data.length - 2] : null;
    const prevDiff =
      prev?.macdDif != null && prev?.macdDea != null
        ? prev.macdDif - prev.macdDea
        : latest.macdPrevDiff ?? null;
    if (prevDiff != null) {
      if (prevDiff <= 0 && diff > MACD_EPSILON) {
        macdSignal = 'bullish_cross';
      } else if (prevDiff >= 0 && diff < -MACD_EPSILON) {
        macdSignal = 'bearish_cross';
      }
    }
    if (macdSignal == null) {
      if (latest.macdDif > MACD_EPSILON && latest.macdDea > MACD_EPSILON) {
        macdSignal = 'bullish';
      } else if (latest.macdDif < -MACD_EPSILON && latest.macdDea < -MACD_EPSILON) {
        macdSignal = 'bearish';
      } else {
        macdSignal = 'neutral';
      }
    }
  }

  return {
    riskRewardRatio,
    upsidePct,
    downsidePct,
    ma20BiasPct,
    ma60BiasPct,
    annualizedVolPct,
    maxDrawdownPct,
    rsi14,
    rsiRegime,
    bollBandwidthPct,
    bollPercentB: latest.bollPercentB ?? null,
    bollSqueeze,
    macdSignal,
    atrPct: latest.atrPct ?? null,
  };
}
