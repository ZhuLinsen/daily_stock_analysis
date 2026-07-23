export type MarketReviewRegion = 'cn' | 'hk' | 'us' | 'jp' | 'kr';

export const MARKET_REVIEW_REGION_ORDER: MarketReviewRegion[] = ['cn', 'hk', 'us', 'jp', 'kr'];

const MARKET_REVIEW_REGION_SET = new Set<string>(MARKET_REVIEW_REGION_ORDER);

export function parseMarketReviewRegion(value?: string | null): MarketReviewRegion[] | null {
  if (typeof value !== 'string' || !value.trim()) {
    return null;
  }

  const tokens = value.toLowerCase().split(',').map((token) => token.trim());
  if (tokens.length === 1 && tokens[0] === 'both') {
    return [...MARKET_REVIEW_REGION_ORDER];
  }
  if (tokens.some((token) => !token || !MARKET_REVIEW_REGION_SET.has(token))) {
    return null;
  }

  const requested = new Set(tokens);
  return MARKET_REVIEW_REGION_ORDER.filter((region) => requested.has(region));
}

export function serializeMarketReviewRegions(regions: Iterable<MarketReviewRegion>): string {
  const requested = new Set(regions);
  const ordered = MARKET_REVIEW_REGION_ORDER.filter((region) => requested.has(region));
  return ordered.length === MARKET_REVIEW_REGION_ORDER.length ? 'both' : ordered.join(',');
}
