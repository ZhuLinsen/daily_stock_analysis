import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider, useUiLanguage } from '../../contexts/UiLanguageContext';
import DataCenterPage from '../DataCenterPage';

const { getOverview } = vi.hoisted(() => ({ getOverview: vi.fn() }));

vi.mock('../../api/dataCapability', () => ({
  dataCapabilityApi: { getOverview: () => getOverview() },
}));

const overview = {
  asOf: '2026-08-29T09:30:00+08:00',
  providers: [
    {
      name: 'akshare',
      label: 'AkShare',
      enabled: true,
      configured: true,
      status: 'partial',
      priority: 0,
      markets: ['CN'],
      datasets: ['quote.snapshot', 'financial.snapshot'],
      datasetMarkets: {
        'quote.snapshot': ['CN'],
        'financial.snapshot': ['CN'],
      },
      warnings: ['runtime_probe_unknown'],
      lastError: null,
      cooldown: false,
    },
  ],
  datasets: [
    {
      dataset: 'screening.snapshot',
      status: 'unknown',
      source: 'em_datacenter',
      stale: null,
      lastSuccess: null,
      lastError: null,
      fallbackFrom: [],
      coverage: null,
      warnings: ['screening_health_unknown'],
    },
    {
      dataset: 'quote.snapshot',
      status: 'ok',
      source: 'akshare',
      stale: false,
      lastSuccess: '2026-08-29T09:29:00+08:00',
      lastError: null,
      fallbackFrom: [],
      coverage: null,
      warnings: [],
    },
    {
      dataset: 'quote.realtime',
      status: 'ok',
      source: null,
      stale: null,
      lastSuccess: null,
      lastError: null,
      fallbackFrom: [],
      coverage: {
        markets: {
          cn: { status: 'ok', source: 'tencent', fallback_from: [], warnings: [] },
          us: { status: 'ok', source: 'yfinance', fallback_from: [], warnings: [] },
        },
      },
      warnings: [],
    },
    {
      dataset: 'daily.quality',
      status: 'partial',
      source: 'efinance',
      stale: null,
      lastSuccess: null,
      lastError: null,
      fallbackFrom: [],
      coverage: {
        markets: {
          cn: { status: 'ok', source: 'efinance', fallback_from: [], warnings: [] },
          hk: { status: 'unavailable', source: null, fallback_from: [], warnings: [] },
          us: { status: 'unavailable', source: null, fallback_from: [], warnings: [] },
        },
      },
      warnings: [],
    },
  ],
  priorities: [
    { scenario: 'cn.quote', providers: ['tencent', 'akshare'], source: 'runtime', warnings: [] },
  ],
  warnings: ['screening_health_unknown'],
};

function LanguageSwitch() {
  const { language, setLanguage } = useUiLanguage();
  return <button onClick={() => setLanguage(language === 'zh' ? 'en' : 'zh')}>switch language</button>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  getOverview.mockResolvedValue(overview);
});

describe('DataCenterPage', () => {
  it('renders the canonical overview without requesting or exposing configuration values', async () => {
    render(<MemoryRouter><DataCenterPage /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: '数据中心' })).toBeInTheDocument();
    expect(getOverview).toHaveBeenCalledTimes(1);
    expect(screen.getByText('AkShare')).toBeInTheDocument();
    expect(screen.getByText('screening.snapshot')).toBeInTheDocument();
    expect(screen.getByText('cn: tencent / us: yfinance')).toBeInTheDocument();
    expect(screen.getByText('cn: efinance')).toBeInTheDocument();
    expect(screen.getAllByText('screening_health_unknown', { exact: false })).toHaveLength(2);
    expect(screen.getByText('tencent → akshare')).toBeInTheDocument();
    expect(screen.queryByText(/API[_ ]?KEY/i)).not.toBeInTheDocument();
  });

  it('keeps cold-start quality unknown instead of presenting it as healthy', async () => {
    render(<MemoryRouter><DataCenterPage /></MemoryRouter>);

    const row = (await screen.findByText('screening.snapshot')).closest('tr');
    expect(row).toHaveTextContent('unknown');
    expect(row).not.toHaveTextContent('ok');
  });

  it('shows empty and error states and can retry the endpoint', async () => {
    getOverview.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({
      asOf: '2026-08-29T09:30:00+08:00',
      providers: [],
      datasets: [],
      priorities: [],
      warnings: [],
    });

    render(<MemoryRouter><DataCenterPage /></MemoryRouter>);

    expect(await screen.findByText('数据概览加载失败')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('暂无能力数据')).toBeInTheDocument();
    await waitFor(() => expect(getOverview).toHaveBeenCalledTimes(2));
  });

  it('ignores an older request that finishes after a language-triggered reload', async () => {
    const first = deferred<typeof overview>();
    const second = deferred<typeof overview>();
    getOverview.mockReset().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    render(
      <UiLanguageProvider>
        <LanguageSwitch />
        <MemoryRouter><DataCenterPage /></MemoryRouter>
      </UiLanguageProvider>,
    );

    await waitFor(() => expect(getOverview).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'switch language' }));
    await waitFor(() => expect(getOverview).toHaveBeenCalledTimes(2));

    second.resolve(overview);
    expect(await screen.findByText('AkShare')).toBeInTheDocument();
    first.reject(new Error('stale failure'));

    await waitFor(() => expect(screen.queryByText('Failed to load data overview')).not.toBeInTheDocument());
    expect(screen.getByText('AkShare')).toBeInTheDocument();
  });
});
