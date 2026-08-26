import { describe, expect, it } from 'vitest';
import {
  buildFxRefreshFeedback,
  formatBrokerLabel,
  formatMoney,
  formatPositionMoney,
  formatPositionPrice,
  formatSignedPct,
  getCsvCommitVariant,
  getCsvParseVariant,
  getPositionPriceLabel,
} from '../portfolioFormat';
import type { PortfolioPositionItem } from '../../types/portfolio';

const pricedPosition: PortfolioPositionItem = {
  symbol: 'HK00700',
  market: 'kr',
  currency: 'KRW',
  quantity: 100,
  avgCost: 300,
  totalCost: 30000,
  lastPrice: 321.12345,
  marketValueBase: 32112.345,
  unrealizedPnlBase: 2112.345,
  unrealizedPnlPct: 7.04,
  valuationCurrency: 'KRW',
  priceSource: 'realtime_quote',
  priceProvider: 'longbridge',
  priceAvailable: true,
};

describe('portfolioFormat', () => {
  it('formats money and signed percentages consistently', () => {
    expect(formatMoney(1234.5, 'USD')).toBe('USD 1,234.50');
    expect(formatMoney(null)).toBe('--');
    expect(formatSignedPct(3.456)).toBe('+3.46%');
    expect(formatSignedPct(-1.2)).toBe('-1.20%');
  });

  it('formats position price fields based on price availability', () => {
    expect(formatPositionPrice(pricedPosition)).toBe('321.1234');
    expect(formatPositionMoney(123, pricedPosition)).toBe('KRW 123');
    expect(getPositionPriceLabel(pricedPosition)).toBe('실시간 시세 · longbridge');

    const missingPosition = { ...pricedPosition, priceAvailable: false, priceSource: 'missing' };
    expect(formatPositionPrice(missingPosition)).toBe('--');
    expect(formatPositionMoney(123, missingPosition)).toBe('--');
    expect(getPositionPriceLabel(missingPosition)).toBe('시세 없음');
  });

  it('formats broker labels and CSV result variants', () => {
    expect(formatBrokerLabel('huatai')).toBe('huatai(화타이증권)');
    expect(formatBrokerLabel('custom', ' 사용자 증권사 ')).toBe('custom(사용자 증권사)');
    expect(getCsvParseVariant({ broker: 'huatai', recordCount: 1, skippedCount: 1, errorCount: 0, records: [], errors: [] })).toBe('warning');
    expect(getCsvCommitVariant({ accountId: 1, recordCount: 1, insertedCount: 1, duplicateCount: 0, failedCount: 0, dryRun: false, errors: [] }, false)).toBe('success');
  });

  it('builds FX refresh feedback from refresh outcomes', () => {
    expect(buildFxRefreshFeedback({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: false,
      disabledReason: 'disabled',
      pairCount: 1,
      updatedCount: 0,
      staleCount: 0,
      errorCount: 0,
    })).toMatchObject({ tone: 'neutral' });

    expect(buildFxRefreshFeedback({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: true,
      disabledReason: null,
      pairCount: 1,
      updatedCount: 1,
      staleCount: 0,
      errorCount: 0,
    })).toMatchObject({ tone: 'success' });
  });
});
