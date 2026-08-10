import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import InstitutionalHoldingsPage from '../InstitutionalHoldingsPage';

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock('../../api/index', () => ({ default: { get, post } }));

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  BarChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Bar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Cell: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

const latestResponse = {
  manager_cik: '0001759760',
  manager_name: 'H&H International Investment, LLC',
  current: {
    manager_cik: '0001759760',
    manager_name: 'H&H International Investment, LLC',
    form_type: '13F-HR',
    accession_number: '0001759760-26-000001',
    report_period: '2026-03-31',
    filed_date: '2026-05-15',
    accepted_at: '2026-05-15T16:30:00Z',
    entry_count: 6,
    total_value_usd: 10000000000,
    primary_document_url: 'https://www.sec.gov/filing.html',
    information_table_url: 'https://www.sec.gov/table.xml',
  },
  previous: null,
  top_4_concentration_pct: 80.79,
  top_6_concentration_pct: 92.44,
  holdings: [
    {
      issuer_name: 'APPLE INC',
      title_of_class: 'COM',
      cusip: '037833100',
      put_call: '',
      status: 'increased',
      current_shares: 1000000,
      previous_shares: 900000,
      share_delta: 100000,
      share_delta_pct: 11.11,
      current_value_usd: 3672000000,
      previous_value_usd: 3000000000,
      current_weight_pct: 36.72,
    },
  ],
  disclosure_note: 'Form 13F is delayed and excludes cash, shorts, non-reportable securities, and intra-quarter trades.',
};

function renderPage() {
  return render(
    <UiLanguageProvider>
      <InstitutionalHoldingsPage />
    </UiLanguageProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem('dsa.uiLanguage', 'zh');
  vi.clearAllMocks();
  get.mockResolvedValue({ data: latestResponse });
  post.mockResolvedValue({
    data: {
      manager_cik: '0001759760',
      requested: 8,
      processed: 2,
      created: 1,
      refreshed: 0,
      unchanged: 1,
      holdings_saved: 12,
      errors: [],
    },
  });
});

describe('InstitutionalHoldingsPage', () => {
  it('renders concentration, source links, and share-count changes', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { name: '段永平公开仓位观察' })).toBeInTheDocument();
    expect(screen.getByText('80.79%')).toBeInTheDocument();
    expect(screen.getByText('APPLE INC')).toBeInTheDocument();
    expect(screen.getByText('增持')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /主申报文件/ })).toHaveAttribute('href', 'https://www.sec.gov/filing.html');
    expect(get).toHaveBeenCalledWith('/api/v1/institutional-holdings/0001759760/latest');
  });

  it('imports filings and reloads analysis from the empty state', async () => {
    get
      .mockRejectedValueOnce({ response: { status: 404 } })
      .mockResolvedValueOnce({ data: latestResponse });

    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: '导入并生成分析' }));

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith('/api/v1/institutional-holdings/import', {
        cik: '0001759760',
        max_filings: 8,
      });
    });
    expect(await screen.findByText(/同步完成：处理 2 期/)).toBeInTheDocument();
    expect(await screen.findByText('APPLE INC')).toBeInTheDocument();
  });

  it('renders English copy when the UI language is English', async () => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Duan Yongping public holdings' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh SEC data' })).toBeInTheDocument();
    expect(screen.getByText('Increased')).toBeInTheDocument();
  });
});
