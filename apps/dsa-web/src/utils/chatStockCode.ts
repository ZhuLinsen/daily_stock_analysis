import { validateStockCode } from './validation';
import { normalizeStockCode } from './stockCode';

const EXCHANGE_PREFIXES = new Set(['SH', 'SZ', 'BJ', 'HK', 'US', 'SS']);
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

export function extractStockCodeFromMessage(message: string): string | null {
  return extractStockCodesFromMessage(message)[0] ?? null;
}

export function extractStockCodesFromMessage(message: string): string[] {
  // More specific patterns first to avoid greedy \d{6} capturing inside .SH/.SZ codes
  const patterns = [
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
    /\b([A-Z]{2,5}\.[A-Z]{1,2})\b/g,
    /\b([A-Z]{2,5})\b/g,
  ];
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
