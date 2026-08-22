import { validateStockCode } from './validation';
import { normalizeStockCode } from './stockCode';

const EXCHANGE_PREFIXES = new Set(['SH', 'SZ', 'BJ', 'HK', 'US', 'SS']);
const BARE_HK_INTENT_RE = /换成|改看|分析|看看|研究|诊断|港股|股份|股票|建仓|关注|跟踪|比较|对比|\bvs\b|差异(?!化)|区别|不同|相比|对照|比一比/i;
// Keep quantity use of "股" as unit, but allow stock wording "股价/股票/股份/股权"
const BARE_HK_AFTER_UNIT_RE = /^\s*(?:年|月|日|元|万|亿|点|个|股(?![价票份权])|手|％|%|块|角|分|千|百)/;
const BARE_HK_YEAR_RE = /^(?:19|20)\d{2}$/;
const YEAR_CONTEXT_RE = /年|月|日|财年|年度|业绩|财报|差异|对比|同比|环比/;
const NUMERIC_SUFFIX_RE = /^\.[A-Za-z]/;
const LOWERCASE_TICKER_CONTEXT_RE = /换成|改看|分析|看看|研究|诊断|比较|对比|\bvs\b|和[^，。,.!?！？]{0,40}比|差异(?!化)|区别|不同|相比|对照|比一比|哪个|哪只|哪一个|谁更|更值得|更适合|怎么选|选哪|二选一/i;
const CONTEXTUAL_INDICATOR_TOKENS = new Set(['MA']);
const INDICATOR_CONTEXT_RE = /指标|均线|移动平均|排列|多头|空头|金叉|死叉|支撑|压力|MA\d|SMA|EMA/i;

// Mirrors backend _COMMON_WORDS for #1596 free-text extraction only.
// Explicit validation via validateStockCode() intentionally keeps its original contract.
const FREE_TEXT_TICKER_DENYLIST = new Set([
  'AM', 'AS', 'AT', 'BE', 'BY', 'DO', 'GO', 'HE', 'IF', 'IN',
  'IS', 'IT', 'ME', 'MY', 'NO', 'OF', 'ON', 'OR', 'SO', 'TO',
  'UP', 'US', 'WE',
  'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL',
  'CAN', 'HAD', 'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'HAS',
  'HIS', 'HOW', 'ITS', 'LET', 'MAY', 'NEW', 'NOW', 'OLD',
  'SEE', 'WAY', 'WHO', 'DID', 'GET', 'HIM', 'USE', 'SAY',
  'SHE', 'TOO', 'ANY', 'WITH', 'FROM', 'THAT', 'THAN',
  'THIS', 'WHAT', 'WHEN', 'WILL', 'JUST', 'ALSO',
  'BEEN', 'EACH', 'HAVE', 'MUCH', 'ONLY', 'OVER',
  'SOME', 'SUCH', 'THEM', 'THEN', 'THEY', 'VERY',
  'WERE', 'YOUR', 'ABOUT', 'AFTER', 'COULD', 'EVERY',
  'OTHER', 'THEIR', 'THERE', 'THESE', 'THOSE', 'WHICH',
  'WOULD', 'BEING', 'STILL', 'WHERE',
  'BUY', 'SELL', 'HOLD', 'LONG', 'PUT', 'CALL',
  'ETF', 'IPO', 'RSI', 'EPS', 'PEG', 'ROE', 'ROA',
  'USA', 'USD', 'CNY', 'HKD', 'EUR', 'GBP',
  'STOCK', 'TRADE', 'PRICE', 'INDEX', 'FUND',
  'HIGH', 'LOW', 'OPEN', 'CLOSE', 'STOP', 'LOSS',
  'TREND', 'BULL', 'BEAR', 'RISK', 'CASH', 'BOND',
  'MACD', 'VWAP', 'BOLL', 'KDJ',
  'TTM', 'LTM', 'NTM', 'FWD', 'YOY', 'QOQ', 'YTD',
  'EBIT', 'EBITDA', 'DCF', 'CAGR', 'FCF', 'NAV', 'AUM',
  'PE', 'PB',
  'HELLO', 'PLEASE', 'THANKS', 'CHECK', 'LOOK', 'THINK',
  'MAYBE', 'GUESS', 'TELL', 'SHOW', 'WHATS',
  'WHY', 'HOWDY', 'HEY', 'HI',
]);

function isDeniedTickerCandidate(value: string, message: string): boolean {
  const token = value.trim().toUpperCase();
  return (
    FREE_TEXT_TICKER_DENYLIST.has(token) ||
    (CONTEXTUAL_INDICATOR_TOKENS.has(token) && INDICATOR_CONTEXT_RE.test(message))
  );
}

function isBareHkIntent(message: string): boolean {
  const text = message.trim();
  return /^\d{4}$/.test(text) || BARE_HK_INTENT_RE.test(text);
}

function hasBareHkUnitMarker(message: string, index: number, length: number): boolean {
  return BARE_HK_AFTER_UNIT_RE.test(message.slice(index + length));
}

function hasNumericSuffix(message: string, index: number, length: number): boolean {
  return NUMERIC_SUFFIX_RE.test(message.slice(index + length));
}

function isYearLikeBareHk(value: string, message: string, index: number, length: number): boolean {
  if (!BARE_HK_YEAR_RE.test(value)) {
    return false;
  }
  const windowStart = Math.max(0, index - 12);
  const windowEnd = Math.min(message.length, index + length + 12);
  const window = message.slice(windowStart, windowEnd);
  if (YEAR_CONTEXT_RE.test(window)) {
    return true;
  }
  if (/\d{4}\s*[与和]\s*\d{4}/.test(window)) {
    return true;
  }
  const after = message.slice(index + length, index + length + 12);
  if (/^\s*[与和]\s*\d{4}/.test(after)) {
    return true;
  }
  return false;
}

export function extractStockCodeFromMessage(message: string): string | null {
  return extractStockCodesFromMessage(message)[0] ?? null;
}

export function extractStockCodesFromMessage(message: string): string[] {
  // More specific patterns first to avoid greedy \d{6} capturing inside .SH/.SZ codes
  const patterns: RegExp[] = [
    /\b(30\d{4}\.SZ)\b/gi,
    /\b(68\d{4}\.SH)\b/gi,
    /\b(00\d{4}\.SZ)\b/gi,
    /\b(60\d{4}\.SH)\b/gi,
    /\b(SH\d{6})\b/gi,
    /\b(SZ\d{6})\b/gi,
    /\b(BJ\d{6})\b/gi,
    /\b(hk\d{4,5})\b/gi,
    /\b(\d{1,5}\.HK)\b/gi,
    /\b(\d{5,6})\b/g,
    // Numeric codes with explicit suffix like 7203.T / 2330.TW / 005930.KS - must outrank bare 4-digit
    /\b(\d{4,5}\.[A-Za-z]{1,4})\b/gi,
  ];
  let bare4DigitIndex = -1;
  if (isBareHkIntent(message)) {
    bare4DigitIndex = patterns.length;
    patterns.push(/\b(\d{4})\b/g);
  }
  patterns.push(
    /\b([A-Z]{2,5}\.[A-Z]{1,2})\b/g,
    /\b([A-Z]{2,5})\b/g,
  );
  if (LOWERCASE_TICKER_CONTEXT_RE.test(message)) {
    patterns.push(/\b([a-z]{2,5}(?:\.[a-z]{1,2})?)\b/g);
  }

  const matches: Array<{ value: string; index: number; priority: number }> = [];
  patterns.forEach((pattern, priority) => {
    pattern.lastIndex = 0;
    for (const match of message.matchAll(pattern)) {
      const value = match[1] ?? match[0];
      const start = match.index ?? 0;
      const end = start + value.length;
      if (/^[A-Z]{2,5}$/.test(value) && (message[start - 1] === '.' || message[end] === '.')) {
        continue;
      }
      if (priority === bare4DigitIndex) {
        if (hasNumericSuffix(message, start, value.length)) {
          continue;
        }
        if (hasBareHkUnitMarker(message, start, value.length)) {
          continue;
        }
        if (isYearLikeBareHk(value, message, start, value.length)) {
          continue;
        }
      }
      matches.push({
        value,
        index: start,
        priority,
      });
    }
  });

  matches.sort((a, b) => a.index - b.index || a.priority - b.priority);

  const stockCodes: string[] = [];
  const seen = new Set<string>();
  for (const match of matches) {
    if (EXCHANGE_PREFIXES.has(match.value.toUpperCase())) {
      continue;
    }
    if (isDeniedTickerCandidate(match.value, message)) {
      continue;
    }
    const { valid, normalized } = validateStockCode(match.value);
    if (!valid) {
      continue;
    }
    const stockCode = normalizeStockCode(normalized);
    if (!seen.has(stockCode)) {
      seen.add(stockCode);
      stockCodes.push(stockCode);
    }
  }
  return stockCodes;
}
