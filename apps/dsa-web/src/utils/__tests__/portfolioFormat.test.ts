import { afterEach, describe, expect, it } from 'vitest';
import {
  buildFxRefreshFeedback,
  formatBrokerLabel,
  formatCashDirectionLabel,
  formatCorporateActionLabel,
  formatMoney,
  formatPositionMoney,
  formatPositionPrice,
  formatSideLabel,
  formatSignedPct,
  getCsvCommitVariant,
  getCsvParseVariant,
  getPositionPriceLabel,
} from '../portfolioFormat';
import { UI_LANGUAGE_STORAGE_KEY } from '../uiLanguage';
import type { PortfolioPositionItem } from '../../types/portfolio';

const pricedPosition: PortfolioPositionItem = {
  symbol: 'HK00700',
  market: 'hk',
  currency: 'HKD',
  quantity: 100,
  avgCost: 300,
  totalCost: 30000,
  lastPrice: 321.12345,
  marketValueBase: 32112.345,
  unrealizedPnlBase: 2112.345,
  unrealizedPnlPct: 7.04,
  valuationCurrency: 'CNY',
  priceSource: 'realtime_quote',
  priceProvider: 'longbridge',
  priceAvailable: true,
};

describe('portfolioFormat', () => {
  afterEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
  });

  it('formats money and signed percentages consistently', () => {
    expect(formatMoney(1234.5, 'USD')).toBe('USD 1,234.50');
    expect(formatMoney(null)).toBe('--');
    expect(formatSignedPct(3.456)).toBe('+3.46%');
    expect(formatSignedPct(-1.2)).toBe('-1.20%');
  });

  it('formats position price fields based on price availability', () => {
    expect(formatPositionPrice(pricedPosition)).toBe('321.1234');
    expect(formatPositionMoney(123, pricedPosition)).toBe('CNY 123.00');
    expect(getPositionPriceLabel(pricedPosition)).toBe('实时价 · longbridge');

    const missingPosition = { ...pricedPosition, priceAvailable: false, priceSource: 'missing' };
    expect(formatPositionPrice(missingPosition)).toBe('--');
    expect(formatPositionMoney(123, missingPosition)).toBe('--');
    expect(getPositionPriceLabel(missingPosition)).toBe('缺价');
  });

  it('formats broker labels and CSV result variants', () => {
    expect(formatBrokerLabel('huatai')).toBe('huatai（华泰）');
    expect(formatBrokerLabel('custom', ' 自定义 ')).toBe('custom（自定义）');
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

  it('formats portfolio labels and FX messages in English when requested or stored', () => {
    expect(getPositionPriceLabel(pricedPosition, 'en')).toBe('Live · longbridge');
    expect(getPositionPriceLabel({ ...pricedPosition, priceProvider: undefined }, 'en')).toBe('Live');
    expect(getPositionPriceLabel({ ...pricedPosition, priceSource: 'history_close', priceStale: true, priceDate: '2026-05-15' }, 'en')).toBe('Close · 2026-05-15');
    expect(getPositionPriceLabel({ ...pricedPosition, priceAvailable: false, priceSource: 'missing' }, 'en')).toBe('No price');

    expect(formatSideLabel('buy', 'en')).toBe('Buy');
    expect(formatSideLabel('sell', 'en')).toBe('Sell');
    expect(formatCashDirectionLabel('in', 'en')).toBe('Inflow');
    expect(formatCashDirectionLabel('out', 'en')).toBe('Outflow');
    expect(formatCorporateActionLabel('cash_dividend', 'en')).toBe('Cash dividend');
    expect(formatCorporateActionLabel('split_adjustment', 'en')).toBe('Split / consolidation');
    expect(formatBrokerLabel('huatai', undefined, 'en')).toBe('huatai (Huatai)');
    expect(formatBrokerLabel('citic', undefined, 'en')).toBe('citic (CITIC)');
    expect(formatBrokerLabel('cmb', undefined, 'en')).toBe('cmb (CMB)');
    expect(formatBrokerLabel('custom', ' My Broker ', 'en')).toBe('custom (My Broker)');

    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    expect(buildFxRefreshFeedback({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: false,
      disabledReason: 'disabled',
      pairCount: 1,
      updatedCount: 0,
      staleCount: 0,
      errorCount: 0,
    })).toEqual({ tone: 'neutral', text: 'Online FX refresh is disabled.' });
    expect(buildFxRefreshFeedback({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: true,
      disabledReason: null,
      pairCount: 1,
      updatedCount: 1,
      staleCount: 0,
      errorCount: 0,
    })).toEqual({ tone: 'success', text: 'FX rates refreshed (1 pair updated).' });
    expect(buildFxRefreshFeedback({
      asOf: '2026-03-19',
      accountCount: 1,
      refreshEnabled: true,
      disabledReason: null,
      pairCount: 3,
      updatedCount: 1,
      staleCount: 1,
      errorCount: 1,
    })).toEqual({
      tone: 'warning',
      text: 'Refresh attempted, but some pairs still use stale/fallback rates. Updated 1, stale 1, failed 1.',
    });
  });
});
