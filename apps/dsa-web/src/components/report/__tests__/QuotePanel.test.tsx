import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { StockQuoteSnapshot } from '../../../api/stocks';
import { stocksApi } from '../../../api/stocks';
import { QuotePanel } from '../QuotePanel';

vi.mock('../../../api/stocks', () => ({
  stocksApi: {
    getQuote: vi.fn(),
  },
}));

// 与后端契约测试 tests/test_stock_quote_snapshot_api.py 的口径保持一致
const FULL_CN_SNAPSHOT: StockQuoteSnapshot = {
  stock_code: '600519',
  stock_name: '贵州茅台',
  source: 'akshare_em',
  fetched_at: '2026-11-11T10:00:00+00:00',
  provider_timestamp: '2026-11-11T09:59:00+00:00',
  is_stale: false,
  stale_seconds: 60,
  market: 'cn',
  currency: 'CNY',
  data_quality: 'ok',
  fallback_from: null,
  missing_fields: [],
  price: 1500.0,
  pre_close: 1480.0,
  open_price: 1490.0,
  high: 1510.0,
  low: 1485.0,
  volume: 2_000_000,
  amount: 3_000_000_000.0,
  change_amount: 20.0,
  change_pct: 1.35,
  amplitude: 1.69,
  volume_ratio: 1.2,
  turnover_rate: 0.16,
  change_60d: 12.5,
  high_52w: 1850.0,
  low_52w: 1300.0,
  vwap: 1500.0,
  bid_ask_ratio: 8.5,
  trade_count: null, // em 标准接口不可得 → 恒 null
  ma5: 1495.0,
  ma10: 1490.0,
  ma20: 1470.0,
  ma60: 1420.0,
};

const DEGRADED_US_SNAPSHOT: StockQuoteSnapshot = {
  stock_code: 'AAPL',
  stock_name: 'Apple',
  source: 'yfinance',
  fetched_at: '2026-11-11T10:00:00+00:00',
  provider_timestamp: null,
  is_stale: null,
  stale_seconds: null,
  market: 'us',
  currency: 'USD',
  data_quality: 'partial',
  fallback_from: null,
  missing_fields: [
    'amount',
    'amplitude',
    'bid_ask_ratio',
    'change_60d',
    'change_amount',
    'high_52w',
    'low_52w',
    'open_price',
    'pre_close',
    'trade_count',
    'turnover_rate',
    'vwap',
    'volume_ratio',
    'ma5',
    'ma10',
    'ma20',
    'ma60',
  ],
  price: 200.0,
  pre_close: null,
  open_price: null,
  high: 201.0,
  low: 198.5,
  volume: 51_000_000,
  amount: null,
  change_amount: null,
  change_pct: 0.25,
  amplitude: null,
  volume_ratio: null,
  turnover_rate: null,
  change_60d: null,
  high_52w: null,
  low_52w: null,
  vwap: null,
  bid_ask_ratio: null,
  trade_count: null,
  ma5: null,
  ma10: null,
  ma20: null,
  ma60: null,
};

const UNAVAILABLE_SNAPSHOT: StockQuoteSnapshot = {
  ...FULL_CN_SNAPSHOT,
  stock_code: '600519',
  source: null,
  currency: null,
  data_quality: 'unavailable',
  missing_fields: [
    'price', 'pre_close', 'open_price', 'high', 'low', 'volume', 'amount',
    'change_amount', 'change_pct', 'amplitude', 'volume_ratio', 'turnover_rate',
    'change_60d', 'high_52w', 'low_52w', 'vwap', 'bid_ask_ratio', 'trade_count',
    'ma5', 'ma10', 'ma20', 'ma60',
  ],
  price: null,
  pre_close: null,
  open_price: null,
  high: null,
  low: null,
  volume: null,
  amount: null,
  change_amount: null,
  change_pct: null,
  amplitude: null,
  volume_ratio: null,
  turnover_rate: null,
  change_60d: null,
  high_52w: null,
  low_52w: null,
  vwap: null,
  bid_ask_ratio: null,
  trade_count: null,
  ma5: null,
  ma10: null,
  ma20: null,
  ma60: null,
};

const expectCellDisplay = (label: string, expected: string) => {
  const cell = screen.getByText(label).closest('[data-quote-field]');
  expect(cell).not.toBeNull();
  expect(cell).toHaveTextContent(expected);
};

describe('QuotePanel', () => {
  let originalClipboard: Navigator['clipboard'] | undefined;
  let writeTextMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    originalClipboard = navigator.clipboard;
    writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: writeTextMock },
    });
  });

  afterEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: originalClipboard,
    });
  });

  it('renders the 22-field grid with values and metadata for zh reports', async () => {
    vi.mocked(stocksApi.getQuote).mockResolvedValue(FULL_CN_SNAPSHOT);

    render(<QuotePanel stockCode="600519" />);

    // price 与 VWAP 同值，findByText('1500') 会多元素命中；改为等待字段格渲染完成
    await screen.findByText('最新价');
    expect(stocksApi.getQuote).toHaveBeenCalledWith('600519');

    // 关键字段逐格断言（含可读格式化的成交量/成交额）
    expectCellDisplay('最新价', '1500');
    expectCellDisplay('昨收', '1480');
    expectCellDisplay('涨跌幅', '1.35%');
    expectCellDisplay('成交量', '200万');
    expectCellDisplay('成交额', '30亿');
    expectCellDisplay('换手率', '0.16%');

    // MA 四档合并一格展示
    const maCell = screen.getByText('MA 均线（5/10/20/60）').closest('[data-quote-field]');
    expect(maCell).toHaveTextContent('MA5 1495');
    expect(maCell).toHaveTextContent('MA60 1420');

    // 元数据透出：来源/币种；全字段齐备时不显示缺失标注
    expect(screen.getByText('数据源: akshare_em')).toBeInTheDocument();
    expect(screen.getByText('CNY')).toBeInTheDocument();
    expect(screen.queryByText('部分字段缺失（0）')).not.toBeInTheDocument();
  });

  it('falls back to "—" placeholders for degraded null fields and surfaces missing_fields', async () => {
    vi.mocked(stocksApi.getQuote).mockResolvedValue(DEGRADED_US_SNAPSHOT);

    render(<QuotePanel stockCode="AAPL" />);

    expect(await screen.findByText('200')).toBeInTheDocument();

    // 降级 null 字段统一 "—" 占位
    expectCellDisplay('昨收', '—');
    expectCellDisplay('VWAP 均价', '—');
    expectCellDisplay('委比', '—');
    expectCellDisplay('成交笔数', '—');

    // MA 合并格整体降级
    const maCell = screen.getByText('MA 均线（5/10/20/60）').closest('[data-quote-field]');
    expect(maCell).toHaveTextContent('MA5 —');
    expect(maCell).toHaveTextContent('MA60 —');

    // missing_fields 与来源轻量标注透出
    expect(screen.getByText('部分字段缺失（17）')).toBeInTheDocument();
    expect(screen.getByText('数据源: yfinance')).toBeInTheDocument();

    // 涨跌幅等可得字段仍正常展示
    expectCellDisplay('涨跌幅', '0.25%');
  });

  it('renders the empty state when the snapshot has no usable data', async () => {
    vi.mocked(stocksApi.getQuote).mockResolvedValue(UNAVAILABLE_SNAPSHOT);

    render(<QuotePanel stockCode="600519" />);

    expect(await screen.findByText('暂无行情数据')).toBeInTheDocument();
    expect(screen.getByText('数据源暂未返回可用行情，可稍后刷新再试。')).toBeInTheDocument();
  });

  it('shows the loading state while the quote request is pending', () => {
    vi.mocked(stocksApi.getQuote).mockReturnValue(new Promise(() => {}));

    render(<QuotePanel stockCode="600519" />);

    expect(screen.getByText('加载行情中...')).toBeInTheDocument();
  });

  it('renders the error state and supports retry', async () => {
    vi.mocked(stocksApi.getQuote)
      .mockRejectedValueOnce(new Error('network failed'))
      .mockResolvedValueOnce(FULL_CN_SNAPSHOT);

    render(<QuotePanel stockCode="600519" />);

    expect(await screen.findByRole('alert')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '重试' }));

    await screen.findByText('最新价');
    expectCellDisplay('最新价', '1500');
    expect(stocksApi.getQuote).toHaveBeenCalledTimes(2);
  });

  it('localizes field labels and annotations for english reports', async () => {
    vi.mocked(stocksApi.getQuote).mockResolvedValue(DEGRADED_US_SNAPSHOT);

    render(<QuotePanel stockCode="AAPL" language="en" />);

    expect(await screen.findByText('200')).toBeInTheDocument();
    expect(screen.getByText('QUOTE SNAPSHOT')).toBeInTheDocument();

    expectCellDisplay('Latest Price', '200');
    expectCellDisplay('Prev Close', '—');
    expectCellDisplay('Bid-Ask Ratio', '—');

    expect(screen.getByText('Some fields missing（17）')).toBeInTheDocument();
    expect(screen.getByText('Source: yfinance')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy quote' })).toBeInTheDocument();
  });

  it('copies all fields as readable label: value text with success feedback', async () => {
    vi.mocked(stocksApi.getQuote).mockResolvedValue(FULL_CN_SNAPSHOT);

    render(<QuotePanel stockCode="600519" />);

    await screen.findByText('最新价');

    fireEvent.click(screen.getByRole('button', { name: '复制行情' }));

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledTimes(1);
    });

    const copiedText = writeTextMock.mock.calls[0][0] as string;
    expect(copiedText).toContain('实时行情 600519 贵州茅台');
    expect(copiedText).toContain('最新价: 1500');
    expect(copiedText).toContain('涨跌幅: 1.35%');
    expect(copiedText).toContain('成交额: 30亿');
    expect(copiedText).toContain('成交笔数: —');
    expect(copiedText).toContain('MA 均线（5/10/20/60）: 1495 / 1490 / 1470 / 1420');
    expect(copiedText).toContain('数据源: akshare_em');
    expect(copiedText).not.toContain('缺失字段');

    // 复制成功反馈态
    expect(await screen.findByRole('button', { name: '已复制' })).toBeInTheDocument();
  });

  it('does not render when no stock code is available', () => {
    const { container } = render(<QuotePanel />);

    expect(container).toBeEmptyDOMElement();
    expect(stocksApi.getQuote).not.toHaveBeenCalled();
  });

  it('ignores a stale slow response that arrives after the stock code changed (OR-COR-8748a738)', async () => {
    let resolveSlow: (snapshot: StockQuoteSnapshot) => void = () => {};
    const slowPromise = new Promise<StockQuoteSnapshot>((resolve) => {
      resolveSlow = resolve;
    });
    // 600519 的请求挂起，切到 AAPL 后 AAPL 先返回
    vi.mocked(stocksApi.getQuote)
      .mockReturnValueOnce(slowPromise)
      .mockResolvedValueOnce(DEGRADED_US_SNAPSHOT);

    const { rerender } = render(<QuotePanel stockCode="600519" />);
    await screen.findByText('加载行情中...');

    rerender(<QuotePanel stockCode="AAPL" />);
    expect(await screen.findByText('200')).toBeInTheDocument();

    // 600519 旧响应晚到：不得落地覆盖 AAPL 数据
    await act(async () => {
      resolveSlow(FULL_CN_SNAPSHOT);
    });

    expectCellDisplay('最新价', '200');
    expectCellDisplay('换手率', '—');
    expect(stocksApi.getQuote).toHaveBeenNthCalledWith(1, '600519');
    expect(stocksApi.getQuote).toHaveBeenNthCalledWith(2, 'AAPL');
  });

  it('does not let a stale failed request override the newer successful quote (OR-COR-8748a738)', async () => {
    let rejectSlow: (err: Error) => void = () => {};
    const slowReject = new Promise<StockQuoteSnapshot>((_, reject) => {
      rejectSlow = reject;
    });
    vi.mocked(stocksApi.getQuote)
      .mockReturnValueOnce(slowReject)
      .mockResolvedValueOnce(DEGRADED_US_SNAPSHOT);

    const { rerender } = render(<QuotePanel stockCode="600519" />);
    await screen.findByText('加载行情中...');

    rerender(<QuotePanel stockCode="AAPL" />);
    expect(await screen.findByText('200')).toBeInTheDocument();

    // 旧请求失败晚到：不得把新标的的成功态覆盖成 error
    await act(async () => {
      rejectSlow(new Error('stale request failed'));
    });

    expectCellDisplay('最新价', '200');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText('加载行情中...')).not.toBeInTheDocument();
  });
});
