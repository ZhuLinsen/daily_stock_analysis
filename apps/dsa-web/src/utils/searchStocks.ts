/**
 * Stock Search Algorithm
 *
 * Supports multiple matching methods:
 * - Exact match: code, name, pinyin, alias
 * - Prefix match: code prefix, name prefix, pinyin prefix
 * - Contains match: code contains, name contains, pinyin contains
 */

import type { StockIndexItem, StockSuggestion } from '../types/stockIndex';
import { normalizeQuery } from './normalizeQuery';
import { MATCH_SCORE, SEARCH_CONFIG } from './stockIndexFields';

export interface SearchOptions {
  /** Limit on number of results to return */
  limit?: number;
  /** Show only active stocks */
  activeOnly?: boolean;
}

/**
 * Search stock index
 *
 * @param query - Search query
 * @param index - Stock index
 * @param options - Search options
 * @returns List of matched stock suggestions
 */
export function searchStocks(
  query: string,
  index: StockIndexItem[],
  options: SearchOptions = {}
): StockSuggestion[] {
  const normalizedQuery = normalizeQuery(query);
  if (!normalizedQuery) {
    return [];
  }
  const limit = options.limit || SEARCH_CONFIG.DEFAULT_LIMIT;
  const activeOnly = options.activeOnly !== false;

  // Filter index
  const filteredIndex = index.filter(item => {
    if (activeOnly && !item.active) return false;
    return true;
  });

  // Calculate match score for each item
  const suggestions = filteredIndex.map(item => ({
    item,
    score: calculateMatchScore(normalizedQuery, item),
  }));

  // Filter out items with score of 0
  const matched = suggestions.filter(s => s.score > 0);

  // Sort: by score descending, then by popularity descending for same score
  matched.sort((a, b) => {
    if (a.score !== b.score) return b.score - a.score;
    return (b.item.popularity || 0) - (a.item.popularity || 0);
  });

  // Return top N items
  return matched.slice(0, limit).map(s => ({
    canonicalCode: s.item.canonicalCode,
    displayCode: s.item.displayCode,
    nameZh: s.item.nameZh,
    market: s.item.market,
    matchType: determineMatchType(s.score),
    matchField: determineMatchField(normalizedQuery, s.item),
    score: s.score,
  }));
}

/**
 * Calculate match score
 *
 * Score rules:
 * - 100: Exact match canonical code
 * - 99: Exact match display code
 * - 98: Exact match Chinese name
 * - 97: Exact match alias
 * - 96: Exact match pinyin abbreviation
 * - 80-89: Prefix match
 * - 60-69: Contains match
 * - 0: No match
 */
function calculateMatchScore(query: string, item: StockIndexItem): number {
  let score = 0;
  const q = query.toLowerCase();
  const normalizedCanonicalCode = normalizeQuery(item.canonicalCode);
  const normalizedDisplayCode = normalizeQuery(item.displayCode);
  const normalizedName = normalizeQuery(item.nameZh);
  const normalizedPinyinFull = normalizeQuery(item.pinyinFull || '');
  const normalizedPinyinAbbr = normalizeQuery(item.pinyinAbbr || '');
  const normalizedAliases = item.aliases?.map(alias => normalizeQuery(alias)) || [];

  // 1. Exact match (96-100 points)
  if (q === normalizedCanonicalCode) return 100;
  if (q === normalizedDisplayCode) return 99;
  if (q === normalizedName) return 98;
  if (normalizedAliases.some(a => a === q)) return 97;
  if (q === normalizedPinyinAbbr) return 96;

  // 2. Prefix match (77-80 points)
  if (normalizedDisplayCode.startsWith(q)) score = Math.max(score, 80);
  if (normalizedName.startsWith(q)) score = Math.max(score, 79);
  if (normalizedPinyinAbbr.startsWith(q)) score = Math.max(score, 78);
  if (normalizedAliases.some(a => a.startsWith(q))) score = Math.max(score, 77);

  // 3. Contains match (57-60 points)
  if (normalizedDisplayCode.includes(q)) score = Math.max(score, 60);
  if (normalizedName.includes(q)) score = Math.max(score, 59);
  if (normalizedPinyinFull.includes(q)) score = Math.max(score, 58);
  if (normalizedAliases.some(a => a.includes(q))) score = Math.max(score, 57);

  return score;
}

/**
 * Determine match type based on score
 */
function determineMatchType(score: number): 'exact' | 'prefix' | 'contains' | 'fuzzy' {
  if (score >= MATCH_SCORE.EXACT_MIN) return 'exact';
  if (score >= MATCH_SCORE.PREFIX_MIN) return 'prefix';
  if (score >= MATCH_SCORE.CONTAINS_MIN) return 'contains';
  return 'fuzzy';
}

/**
 * Determine match field
 */
function determineMatchField(query: string, item: StockIndexItem): 'code' | 'name' | 'pinyin' | 'alias' {
  const q = query.toLowerCase();
  const normalizedCanonicalCode = normalizeQuery(item.canonicalCode);
  const normalizedDisplayCode = normalizeQuery(item.displayCode);
  const normalizedName = normalizeQuery(item.nameZh);
  const normalizedPinyinFull = normalizeQuery(item.pinyinFull || '');
  const normalizedPinyinAbbr = normalizeQuery(item.pinyinAbbr || '');
  const normalizedAliases = item.aliases?.map(alias => normalizeQuery(alias)) || [];

  if (normalizedCanonicalCode.includes(q) ||
      normalizedDisplayCode.includes(q)) {
    return 'code';
  }
  if (normalizedName.includes(q)) return 'name';
  if (normalizedPinyinFull.includes(q) ||
      normalizedPinyinAbbr.includes(q)) {
    return 'pinyin';
  }
  if (normalizedAliases.some(a => a.includes(q))) return 'alias';
  return 'name';
}

/**
 * Escape HTML entities
 */
function escapeHtml(unsafe: string): string {
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Highlight matched text
 *
 * @param text - Original text
 * @param query - Query string
 * @returns Safe HTML string with highlight markers
 */
export function highlightMatch(text: string, query: string): string {
  const normalizedQuery = normalizeQuery(query);
  if (!normalizedQuery) return escapeHtml(text);

  const index = text.toLowerCase().indexOf(normalizedQuery);
  if (index === -1) return escapeHtml(text);

  const before = text.substring(0, index);
  const match = text.substring(index, index + normalizedQuery.length);
  const after = text.substring(index + normalizedQuery.length);

  // Return escaped segments joined by safe <mark> tags
  return `${escapeHtml(before)}<mark>${escapeHtml(match)}</mark>${escapeHtml(after)}`;
}
