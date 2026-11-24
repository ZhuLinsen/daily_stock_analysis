import type { MarketReviewRegion } from '../types/analysis';

export type { MarketReviewRegion };

export const MARKET_REVIEW_REGION_ORDER: readonly MarketReviewRegion[] = ['cn', 'hk', 'us', 'jp', 'kr', 'tw'];

export function serializeMarketReviewRegions(regions: readonly MarketReviewRegion[]): string {
  const ordered = MARKET_REVIEW_REGION_ORDER.filter((region) => regions.includes(region));
  // Preserve the displayed selection: backend `both` can include markets that
  // this UI does not expose yet (currently AU).
  return ordered.join(',');
}
