/**
 * Stock Index Field Constant Definitions
 *
 * For index data compression/decompression processing
 */

export const STOCK_INDEX_FIELDS = [
  'canonicalCode',
  'displayCode',
  'nameZh',
  'pinyinFull',
  'pinyinAbbr',
  'aliases',
  'market',
  'assetType',
  'active',
  'popularity',
] as const;

/**
 * Field indices for compressed format
 */
export const INDEX_FIELD = {
  CANONICAL_CODE: 0,
  DISPLAY_CODE: 1,
  NAME_ZH: 2,
  PINYIN_FULL: 3,
  PINYIN_ABBR: 4,
  ALIASES: 5,
  MARKET: 6,
  ASSET_TYPE: 7,
  ACTIVE: 8,
  POPULARITY: 9,
} as const;

/**
 * Match score thresholds
 */
export const MATCH_SCORE = {
  EXACT_MIN: 96,   // Minimum score for exact match
  PREFIX_MIN: 77,  // Minimum score for prefix match
  CONTAINS_MIN: 57, // Minimum score for contains match
  FUZZY_MIN: 1,    // Minimum score for fuzzy match
} as const;

/**
 * Search configuration
 */
export const SEARCH_CONFIG = {
  DEFAULT_LIMIT: 10,      // Default number of results to return
  DEBOUNCE_MS: 200,       // Debounce delay (milliseconds)
  MIN_QUERY_LENGTH: 2,    // Minimum query length
  ACTIVE_ONLY: true,      // Show only active stocks
} as const;
