import type { MarketPhaseValue } from './analysis';

export type MarketStatusRegion = 'cn' | 'hk' | 'us' | 'jp' | 'kr';

export type MarketStatusItem = {
  market: MarketStatusRegion;
  phase: MarketPhaseValue;
  marketLocalTime: string;
  sessionDate?: string | null;
  effectiveDailyBarDate?: string | null;
  isTradingDay?: boolean | null;
  isMarketOpenNow?: boolean | null;
  isPartialBar?: boolean | null;
  minutesToOpen?: number | null;
  minutesToClose?: number | null;
  nextSessionOpen?: string | null;
  warnings: string[];
};

export type MarketStatusResponse = {
  generatedAt: string;
  markets: MarketStatusItem[];
};
