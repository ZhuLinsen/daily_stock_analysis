import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DataSourceStatusPanel } from '../DataSourceStatusPanel';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import type { DataSourceStatusResponse } from '../../../types/systemConfig';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';

const { getDataSourceStatus } = vi.hoisted(() => ({
  getDataSourceStatus: vi.fn(),
}));

vi.mock('../../../api/systemConfig', () => ({
  systemConfigApi: {
    getDataSourceStatus: (...args: unknown[]) => getDataSourceStatus(...args),
  },
}));

const sampleStatus: DataSourceStatusResponse = {
  marketData: [
    {
      sourceId: 'efinance',
      name: 'Efinance（东方财富）',
      kind: 'market_data',
      status: 'active',
      requiresCredentials: false,
      markets: ['cn'],
      configKeys: [],
      detail: null,
      circuit: [],
    },
    {
      sourceId: 'tushare',
      name: 'Tushare Pro',
      kind: 'market_data',
      status: 'not_configured',
      requiresCredentials: true,
      markets: ['cn', 'hk'],
      configKeys: ['TUSHARE_TOKEN'],
      detail: null,
      circuit: [],
    },
    {
      sourceId: 'akshare',
      name: 'Akshare + 新浪财经',
      kind: 'market_data',
      status: 'active',
      requiresCredentials: false,
      markets: ['cn', 'hk'],
      configKeys: [],
      detail: null,
      circuit: [{ market: 'hk', state: 'open' }],
    },
  ],
  search: [
    {
      sourceId: 'searxng',
      name: 'SearXNG',
      kind: 'search',
      status: 'active',
      requiresCredentials: false,
      markets: [],
      configKeys: ['SEARXNG_BASE_URLS', 'SEARXNG_PUBLIC_INSTANCES_ENABLED'],
      detail: 'public_instance_auto_discovery',
      circuit: [],
    },
  ],
  summary: {
    marketDataActive: 2,
    marketDataTotal: 3,
    searchActive: 1,
    searchTotal: 1,
  },
};

const renderPanel = () =>
  render(
    <UiLanguageProvider>
      <DataSourceStatusPanel />
    </UiLanguageProvider>,
  );

describe('DataSourceStatusPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
  });

  it('renders market data and search sources with statuses', async () => {
    getDataSourceStatus.mockResolvedValue(sampleStatus);

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText('Efinance（东方财富）')).toBeInTheDocument();
    });
    expect(getDataSourceStatus).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Tushare Pro')).toBeInTheDocument();
    expect(screen.getByText('SearXNG')).toBeInTheDocument();
    expect(screen.getByText(/TUSHARE_TOKEN/)).toBeInTheDocument();
    expect(screen.getByText(/行情 2\/3/)).toBeInTheDocument();
  });

  it('shows circuit breaker badges for non-closed states', async () => {
    getDataSourceStatus.mockResolvedValue(sampleStatus);

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText('HK 熔断中')).toBeInTheDocument();
    });
  });

  it('renders an error alert when the request fails', async () => {
    getDataSourceStatus.mockRejectedValue(new Error('network down'));

    renderPanel();

    await waitFor(() => {
      expect(getDataSourceStatus).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.queryByText('Efinance（东方财富）')).not.toBeInTheDocument();
    });
  });
});
