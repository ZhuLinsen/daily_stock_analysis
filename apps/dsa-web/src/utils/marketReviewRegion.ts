import type { MarketReviewRegion } from '../types/analysis';

export type { MarketReviewRegion };

export const MARKET_REVIEW_REGION_ORDER: readonly MarketReviewRegion[] = ['cn', 'hk', 'us', 'jp', 'kr'];

export function serializeMarketReviewRegions(regions: readonly MarketReviewRegion[]): string {
  const ordered = MARKET_REVIEW_REGION_ORDER.filter((region) => regions.includes(region));
  return ordered.length === MARKET_REVIEW_REGION_ORDER.length ? 'both' : ordered.join(',');
}
