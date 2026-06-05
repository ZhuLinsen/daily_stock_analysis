import { validateStockCode } from './validation';
import { normalizeStockCode } from './stockCode';

const EXCHANGE_PREFIXES = new Set(['SH', 'SZ', 'BJ', 'HK', 'US', 'SS']);

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
  'MACD', 'VWAP', 'BOLL',
  'TTM', 'LTM', 'NTM', 'FWD', 'YOY', 'QOQ', 'YTD',
  'EBIT', 'EBITDA', 'DCF', 'CAGR', 'FCF', 'NAV', 'AUM',
  'PE', 'PB',
  'HELLO', 'PLEASE', 'THANKS', 'CHECK', 'LOOK', 'THINK',
  'MAYBE', 'GUESS', 'TELL', 'SHOW', 'WHATS',
  'WHY', 'HOWDY', 'HEY', 'HI',
]);

function isDeniedTickerCandidate(value: string): boolean {
  return FREE_TEXT_TICKER_DENYLIST.has(value.trim().toUpperCase());
}

export function extractStockCodeFromMessage(message: string): string | null {
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
    /\b([A-Z]{2,5})\b/g,
  ];
  for (const pattern of patterns) {
    const matches = message.match(pattern);
    if (matches) {
      for (const m of matches) {
        if (EXCHANGE_PREFIXES.has(m.toUpperCase())) {
          continue;
        }
        if (isDeniedTickerCandidate(m)) {
          continue;
        }
        const { valid, normalized } = validateStockCode(m);
        if (valid) return normalizeStockCode(normalized);
      }
    }
  }
  return null;
}
