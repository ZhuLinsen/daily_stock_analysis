import { beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { dataCapabilityApi } from '../dataCapability';

vi.mock('../index', () => ({
  default: { get: vi.fn() },
}));

describe('dataCapabilityApi', () => {
  beforeEach(() => vi.clearAllMocks());

  it('uses the canonical overview endpoint and maps exact dataset markets', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        as_of: '2026-08-29T09:30:00+08:00',
        providers: [{
          name: 'yfinance',
          label: 'YFinance',
          enabled: true,
          configured: true,
          status: 'ok',
          priority: 2,
          markets: ['CN', 'HK', 'US'],
          datasets: ['financial.snapshot'],
          dataset_markets: { 'financial.snapshot': ['HK', 'US'] },
          warnings: [],
        }],
        datasets: [],
        priorities: [],
        warnings: [],
      },
    });

    const result = await dataCapabilityApi.getOverview();

    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/data/overview');
    expect(result.providers[0].datasetMarkets).toEqual({ 'financial.snapshot': ['HK', 'US'] });
  });
});
