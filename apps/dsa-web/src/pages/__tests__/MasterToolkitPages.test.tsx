import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import TradeJournalPage from '../TradeJournalPage';
import MarketTemperaturePage from '../MarketTemperaturePage';
import MasterDebatePage from '../MasterDebatePage';

const { get, post, del } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  del: vi.fn(),
}));

vi.mock('../../api/index', () => ({
  default: { get, post, delete: del },
}));

vi.mock('../../hooks/useStockIndex', () => ({
  useStockIndex: () => ({
    index: [
      {
        canonicalCode: '600519.SH',
        displayCode: '600519',
        nameZh: '贵州茅台',
        aliases: ['茅台'],
        market: 'CN',
        assetType: 'stock',
        active: true,
      },
    ],
    loading: false,
    error: null,
    fallback: false,
    loaded: true,
  }),
}));

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  del.mockReset();
});

function jsonResponse(data: unknown) {
  return Promise.resolve({ data });
}

describe('TradeJournalPage', () => {
  it('renders the review stats and empty list', async () => {
    get.mockImplementation((url: string) => {
      if (String(url).includes('/review')) {
        return jsonResponse({
          entry_count: 2,
          closed_trade_count: 1,
          win_rate: 100,
          total_pnl: 120.0,
          discipline_score: 50,
          plan_declared: 2,
          plan_followed: 1,
          linked_signal_count: 0,
          aligned_count: 0,
          emotion_breakdown: { calm: 1 },
        });
      }
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 20 });
    });

    render(
      <UiLanguageProvider>
        <TradeJournalPage />
      </UiLanguageProvider>,
    );

    await waitFor(() => expect(screen.getByText('Trade Journal')).toBeTruthy());
    expect(screen.getByText('2')).toBeTruthy();
    expect(screen.getByText('+120.00')).toBeTruthy();
  });
});

describe('MarketTemperaturePage', () => {
  it('renders the latest temperature score', async () => {
    get.mockImplementation((url: string) => {
      if (String(url).includes('/latest')) {
        return jsonResponse({
          id: 1,
          market: 'cn',
          trade_date: '2026-01-05',
          score: 84,
          label: '极度贪婪',
          dimensions: [{ key: 'breadth', name: '市场宽度', score: 90, available: true }],
          reasons: ['市场宽度处于高位'],
          guidance: '警惕过热',
        });
      }
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 20 });
    });

    render(
      <UiLanguageProvider>
        <MarketTemperaturePage />
      </UiLanguageProvider>,
    );

    await waitFor(() => expect(screen.getByText('84')).toBeTruthy());
    expect(screen.getByText('Extreme Greed')).toBeTruthy();
  });

  it('renders a live dashboard with sectors, flow and candidates', async () => {
    get.mockImplementation((url: string) => {
      if (String(url).includes('/latest')) {
        return jsonResponse(null);
      }
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 20 });
    });
    post.mockImplementation((url: string) => {
      if (String(url).includes('/dashboard')) {
        return jsonResponse({
          market: 'cn',
          trade_date: '2026-01-06',
          temperature: {
            market: 'cn',
            trade_date: '2026-01-06',
            score: 72,
            label: '贪婪',
            label_key: 'greed',
            dimensions: [{ key: 'breadth', name: '市场宽度', score: 70, available: true }],
            available_dimensions: 1,
            reasons: [],
            guidance: '情绪偏暖',
            source: 'market_stats',
          },
          indices: [{ code: '000001', name: '上证指数', change_pct: 0.8 }],
          breadth: {
            up_count: 3200,
            down_count: 1400,
            flat_count: 200,
            limit_up_count: 80,
            limit_down_count: 6,
            total_amount: 12500.0,
          },
          hot_sectors: {
            top: [{ name: '半导体', change_pct: 3.5 }],
            bottom: [{ name: '煤炭', change_pct: -1.9 }],
          },
          hot_concepts: { top: [], bottom: [] },
          capital_flow: {
            status: 'ok',
            sector_rankings: {
              top: [{ name: '半导体', net_inflow: 52.3 }],
              bottom: [{ name: '煤炭', net_inflow: -38.1 }],
            },
          },
          candidates: [
            {
              code: '688981',
              name: '中芯国际',
              sector: '半导体',
              sector_change_pct: 3.5,
              change_pct: 12.0,
              price: 55.1,
              reason: '半导体 板块领涨 +3.50%，个股涨幅 +12.00%',
            },
          ],
          notes: [],
          generated_at: '2026-01-06T15:00:00',
        });
      }
      return jsonResponse({});
    });

    render(
      <UiLanguageProvider>
        <MarketTemperaturePage />
      </UiLanguageProvider>,
    );

    const liveButton = await screen.findAllByRole('button', { name: 'Live Compute (Full Market)' });
    fireEvent.click(liveButton[0]);

    await waitFor(() => expect(screen.getByText('72')).toBeTruthy());
    expect(screen.getByText('Full-market realtime data')).toBeTruthy();
    // 指数
    expect(screen.getByText('上证指数')).toBeTruthy();
    // 热门板块（同时出现在资金流与候选板块标签中）
    expect(screen.getAllByText('半导体').length).toBeGreaterThanOrEqual(2);
    // 候选观察池
    expect(screen.getByText('中芯国际')).toBeTruthy();
    expect(screen.getByText('Candidate Watchlist')).toBeTruthy();
  });
});

describe('MasterDebatePage', () => {
  it('renders the empty history state', async () => {
    get.mockResolvedValue(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }));

    render(
      <UiLanguageProvider>
        <MasterDebatePage />
      </UiLanguageProvider>,
    );

    await waitFor(() => expect(screen.getByText('Master Persona Debate')).toBeTruthy());
    expect(screen.getByText('No debates yet. Start one.')).toBeTruthy();
  });

  it('opens a history record with full debate details', async () => {
    get.mockResolvedValue(jsonResponse({
      items: [{
        id: 12,
        code: '600519',
        name: '贵州茅台',
        market: 'cn',
        consensus: 'neutral',
        divergence: 50,
        bull_count: 2,
        bear_count: 1,
        neutral_count: 3,
        personas: [
          { persona_id: 'warren_buffett', name: '巴菲特', english_name: 'Warren Buffett', philosophy: '', stance: 'neutral', confidence: 0.4, thesis: '护城河深但估值一般', key_points: [], key_levels: {}, risk: '' },
          { persona_id: 'jesse_livermore', name: '利弗莫尔', english_name: 'Jesse Livermore', philosophy: '', stance: 'bull', confidence: 0.7, thesis: '趋势关键位已突破', key_points: [], key_levels: {}, risk: '' },
        ],
        summary: '共 6 位大师表态。',
        created_at: '2026-08-15T18:03:55',
      }],
      total: 1,
      page: 1,
      page_size: 20,
    }));

    render(
      <UiLanguageProvider>
        <MasterDebatePage />
      </UiLanguageProvider>,
    );

    const row = await screen.findByRole('button', { name: 'View debate details: 贵州茅台' });
    fireEvent.click(row);

    // 详情区展示大师卡片与摘要
    await waitFor(() => expect(screen.getByText('共 6 位大师表态。')).toBeTruthy());
    expect(screen.getByText('护城河深但估值一般')).toBeTruthy();
    expect(screen.getByText('趋势关键位已突破')).toBeTruthy();
    // 历史标识出现
    expect(screen.getByText(/Viewing a past debate/)).toBeTruthy();
  });

  it('uses one stock search and keeps optional parameters collapsed', async () => {
    get.mockResolvedValue(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }));

    render(
      <UiLanguageProvider>
        <MasterDebatePage />
      </UiLanguageProvider>,
    );

    expect(await screen.findByRole('combobox', { name: 'Stock name or code' })).toBeTruthy();
    expect(screen.getByText('A name or code is enough. We will fill in the stock and market.')).toBeTruthy();
    expect(screen.queryByText('Stock code')).toBeNull();
    expect(screen.queryByText('Stock name')).toBeNull();
    expect(screen.queryByText('Market')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Advanced options' }));
    expect(screen.getByText('Market')).toBeTruthy();
    expect(screen.getByText('Extra context (optional)')).toBeTruthy();
  });

  it('resolves a stock name to code and market before running the debate', async () => {
    get.mockResolvedValue(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }));
    post.mockResolvedValue(jsonResponse({
      code: '600519',
      name: '贵州茅台',
      market: 'cn',
      consensus: 'neutral',
      divergence: 0,
      conviction: 0,
      bull_count: 0,
      bear_count: 0,
      neutral_count: 0,
      bull_arguments: [],
      bear_arguments: [],
      personas: [],
      summary: 'done',
    }));

    render(
      <UiLanguageProvider>
        <MasterDebatePage />
      </UiLanguageProvider>,
    );

    fireEvent.change(await screen.findByRole('combobox', { name: 'Stock name or code' }), {
      target: { value: '贵州茅台' },
    });
    fireEvent.click(await screen.findByRole('option', { name: /贵州茅台/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Run debate' }));

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/master-debate', expect.objectContaining({
      code: '600519',
      name: '贵州茅台',
      market: 'cn',
    }), expect.objectContaining({ timeout: 300000 })));
  });

  it('accepts an exact stock code without requiring a name or market', async () => {
    get.mockResolvedValue(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }));
    post.mockResolvedValue(jsonResponse({
      code: '600519',
      name: '贵州茅台',
      market: 'cn',
      consensus: 'neutral',
      divergence: 0,
      conviction: 0,
      bull_count: 0,
      bear_count: 0,
      neutral_count: 0,
      bull_arguments: [],
      bear_arguments: [],
      personas: [],
      summary: 'done',
    }));

    render(
      <UiLanguageProvider>
        <MasterDebatePage />
      </UiLanguageProvider>,
    );

    fireEvent.change(await screen.findByRole('combobox', { name: 'Stock name or code' }), {
      target: { value: '600519' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Run debate' }));

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/master-debate', expect.objectContaining({
      code: '600519',
      name: '贵州茅台',
      market: 'cn',
    }), expect.objectContaining({ timeout: 300000 })));
  });
});
