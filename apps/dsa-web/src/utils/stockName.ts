/**
 * Stock name truncation configuration
 * English characters: 15 chars max
 * Chinese characters: 8 chars max
 * Mixed (Chinese + English): 10 chars max
 */
export const STOCK_NAME_MAX_LENGTH = {
  ENGLISH: 15,
  CHINESE: 8,
  MIXED: 10,
} as const;

/**
 * Get max allowed length for a stock name based on character type
 * - Pure English: 15 chars
 * - Pure Chinese: 8 chars
 * - Mixed: 10 chars
 */
function getMaxLength(name: string): number {
  const isChinese = /[\u4e00-\u9fa5]/.test(name);
  const isMixed = isChinese && /[a-zA-Z]/.test(name);
  if (isMixed) return STOCK_NAME_MAX_LENGTH.MIXED;
  if (isChinese) return STOCK_NAME_MAX_LENGTH.CHINESE;
  return STOCK_NAME_MAX_LENGTH.ENGLISH;
}

/**
 * Truncate stock name based on character type
 * - Pure English: max 15 characters
 * - Pure Chinese: max 8 characters
 * - Mixed: max 10 characters
 */
export function truncateStockName(name: string): string {
  if (!name) return name;
  const maxLen = getMaxLength(name);
  if (name.length <= maxLen) return name;
  return name.slice(0, maxLen) + '.';
}

/**
 * Check if stock name will be truncated
 */
export function isStockNameTruncated(name: string): boolean {
  if (!name) return false;
  return name.length > getMaxLength(name);
}
