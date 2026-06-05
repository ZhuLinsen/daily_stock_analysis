import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import StockScreeningPage from '../StockScreeningPage';

const { enableAlphaSift, getAlphaSiftStatus, getStrategies, screenStocks } = vi.hoisted(() => ({
  enableAlphaSift: vi.fn(),
  getAlphaSiftStatus: vi.fn(),
  getStrategies: vi.fn(),
  screenStocks: vi.fn(),
}));

vi.mock('../../api/alphasift', () => ({
  alphasiftApi: {
    enable: (...args: unknown[]) => enableAlphaSift(...args),
    getStatus: (...args: unknown[]) => getAlphaSiftStatus(...args),
    getStrategies: (...args: unknown[]) => getStrategies(...args),
    screen: (...args: unknown[]) => screenStocks(...args),
  },
}));

const mockStrategiesResponse = {
  enabled: true,
  strategies: [
    {
      id: 'dual_low',
      name: 'Dual Low',
      title: 'Dual Low',
      description: 'Low valuation strategy',
      category: 'value',
      tag: 'value',
      tags: ['value'],
      marketScope: ['cn'],
    },
  ],
  strategyCount: 1,
};

describe('StockScreeningPage', () => {
  beforeEach(() => {
    enableAlphaSift.mockReset();
    getAlphaSiftStatus.mockReset();
    getStrategies.mockReset();
    screenStocks.mockReset();
    getStrategies.mockResolvedValue(mockStrategiesResponse);
  });

  it('re-syncs enabled state when AlphaSift availability check fails after config is enabled', async () => {
    getAlphaSiftStatus
      .mockResolvedValueOnce({
        enabled: false,
        available: false,
        installSpecIsDefault: true,
      })
      .mockResolvedValueOnce({
        enabled: true,
        available: false,
        installSpecIsDefault: true,
      });
    enableAlphaSift.mockRejectedValueOnce(new Error('AlphaSift 适配层不可用。请执行 pip install -r requirements.txt'));

    render(<StockScreeningPage />);

    expect(await screen.findByText('选股未开启')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /运行选股/ })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: '开启 AlphaSift' }));

    await waitFor(() => expect(getAlphaSiftStatus).toHaveBeenCalledTimes(2));
    expect(screen.getByText('选股未开启')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /运行选股/ })).toBeDisabled();
    expect(screen.getByText(/适配层当前不可用/)).toBeInTheDocument();
    expect(screen.getByText('AlphaSift 适配层不可用。请执行 pip install -r requirements.txt')).toBeInTheDocument();
  });

  it('shows input strategy when strategy is not in preset list', async () => {
    getAlphaSiftStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
      installSpecIsDefault: true,
    });
    screenStocks.mockResolvedValue({
      enabled: true,
      candidates: [],
      candidateCount: 0,
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('选股已开启')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('策略参数'), {
      target: { value: 'custom_strategy_alpha' },
    });

    expect(screen.getByDisplayValue('custom_strategy_alpha')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));
    await waitFor(() => expect(screenStocks).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText(/自定义策略 \(custom_strategy_alpha\)/)).toBeInTheDocument());
  });

  it('uses supported AlphaSift strategy ids and cn market', async () => {
    getStrategies.mockResolvedValueOnce({
      enabled: true,
      strategies: [
        { id: 'balanced_alpha', name: '平衡选股', description: 'desc', category: '框架' },
        { id: 'capital_heat', name: '资金热度', description: 'desc', category: '动量' },
        { id: 'dual_low', name: '双低', description: 'desc', category: '价值' },
        { id: 'oversold_reversal', name: '超跌', description: 'desc', category: '反转' },
        { id: 'shrink_pullback', name: '缩量回踩', description: 'desc', category: '趋势' },
      ],
      strategyCount: 5,
    });
    getAlphaSiftStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
      installSpecIsDefault: true,
    });
    screenStocks.mockResolvedValue({
      enabled: true,
      candidates: [],
      candidateCount: 0,
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('选股已开启')).toBeInTheDocument();

    const marketSelect = screen.getByLabelText('市场') as HTMLSelectElement;
    expect(Array.from(marketSelect.options).map((option) => option.value)).toEqual(['cn']);

    [
      ['平衡选股', 'balanced_alpha'],
      ['资金热度', 'capital_heat'],
      ['超跌', 'oversold_reversal'],
      ['缩量回踩', 'shrink_pullback'],
    ].forEach(([label, id]) => {
      fireEvent.click(screen.getByRole('button', { name: new RegExp(label) }));
      expect(screen.getByDisplayValue(id)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));
    await waitFor(() => expect(screenStocks).toHaveBeenCalledTimes(1));
    expect(screenStocks).toHaveBeenCalledWith({
      market: 'cn',
      strategy: 'shrink_pullback',
      maxResults: 3,
    });
  });

  it('clears previous screening candidates when strategy changes', async () => {
    getStrategies.mockResolvedValueOnce({
      enabled: true,
      strategies: [
        { id: 'dual_low', name: '双低选股', description: 'desc', category: '价值' },
        { id: 'capital_heat', name: '资金热度', description: 'desc', category: '动量' },
      ],
      strategyCount: 2,
    });
    getAlphaSiftStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
      installSpecIsDefault: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '000001',
          name: '旧策略股票',
          score: 88.5,
          reason: 'old result',
          raw: {},
        },
      ],
      candidateCount: 1,
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('选股已开启')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));

    expect(await screen.findByText('旧策略股票')).toBeInTheDocument();
    expect(screen.getByText('选股完成')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /资金热度/ }));

    expect(screen.queryByText('旧策略股票')).not.toBeInTheDocument();
    expect(screen.getByText('等待运行')).toBeInTheDocument();
    expect(screen.getByText('当前策略：资金热度 · A 股')).toBeInTheDocument();
  });

  it('surfaces AlphaSift LLM fallback instead of showing empty LLM fields as normal', async () => {
    getAlphaSiftStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
      installSpecIsDefault: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '000001',
          name: '平安银行',
          score: 88.5,
          reason: '本地后置评分: value_quality',
          amount: 1042000000,
          factorScores: {
            value: 87.44,
            liquidity: 93.33,
          },
          raw: {},
        },
      ],
      candidateCount: 1,
      snapshotCount: 5193,
      afterFilterCount: 20,
      llmRanked: false,
      warnings: ['LLM ranking failed, falling back to screen_score: Missing gemini_api_key'],
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('选股已开启')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));

    expect(await screen.findByText('LLM 已降级')).toBeInTheDocument();
    expect(screen.getByText(/缺少可用 LLM API Key/)).toBeInTheDocument();
    expect(screen.queryByText(/Missing gemini_api_key/)).not.toBeInTheDocument();
    expect(screen.getByText('未重排')).toBeInTheDocument();
    expect(screen.getByText('本次 LLM 重排失败或未返回判断，当前展示的是本地因子评分结果。')).toBeInTheDocument();
    expect(screen.getByText('LLM 元数据未返回')).toBeInTheDocument();
    expect(screen.getAllByText('未返回（LLM 已降级）')).toHaveLength(2);
  });

  it('deduplicates AlphaSift snapshot fallback warnings and source errors', async () => {
    getAlphaSiftStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
      installSpecIsDefault: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '601919',
          name: '中远海控',
          score: 82.88,
          llmScore: 82,
          riskLevel: 'low',
          raw: {},
        },
      ],
      candidateCount: 1,
      llmRanked: true,
      warnings: ['Snapshot source fallback: tushare: tushare trade_cal returned no open trading days'],
      sourceErrors: ['tushare: tushare trade_cal returned no open trading days'],
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('选股已开启')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));

    expect(await screen.findByText('AlphaSift 提示')).toBeInTheDocument();
    expect(screen.getAllByText('数据源降级：tushare（交易日历暂无可用开市日）')).toHaveLength(1);
    expect(screen.queryByText(/trade_cal returned no open trading days/)).not.toBeInTheDocument();
  });

  it('sanitizes long AlphaSift source diagnostics and keeps the alert constrained', async () => {
    getAlphaSiftStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
      installSpecIsDefault: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '600016',
          name: '民生银行',
          score: 80.12,
          raw: {},
        },
      ],
      candidateCount: 1,
      llmRanked: true,
      warnings: [
        "Snapshot source fallback: efinance: HTTPConnectionPool(host='push2.eastmoney.com', port=80): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=200&po=1&fields=f12%2Cf14%2Cf2%2Cf3 (Caused by ProtocolError('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')))",
        "Snapshot source fallback: akshare_em: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))",
      ],
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('选股已开启')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveClass('max-w-full');
    expect(screen.getByText('数据源降级：efinance（网络连接中断）')).toBeInTheDocument();
    expect(screen.getByText('数据源降级：akshare_em（网络连接中断）')).toBeInTheDocument();
    expect(screen.queryByText(/HTTPConnectionPool/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/api\/qt\/clist\/get/)).not.toBeInTheDocument();
    expect(screen.queryByText(/RemoteDisconnected/)).not.toBeInTheDocument();
  });

  it('shows DSA enrichment summary, news, and enrichment metadata', async () => {
    getAlphaSiftStatus.mockResolvedValueOnce({
      enabled: true,
      available: true,
      installSpecIsDefault: true,
    });
    screenStocks.mockResolvedValueOnce({
      enabled: true,
      candidates: [
        {
          rank: 1,
          code: '600519',
          name: '贵州茅台',
          score: 91.2,
          reason: 'AlphaSift pick',
          dsaAnalysisSummary: 'DSA行情：现价 1688，涨跌幅 1.2%；DSA新闻：贵州茅台最新公告',
          dsaNews: [{ title: '贵州茅台最新公告', source: '测试源' }],
          dsaContext: {
            enriched: true,
            warnings: ['stock_news_unavailable'],
          },
          raw: {},
        },
      ],
      candidateCount: 1,
      dsaEnrichment: {
        enabled: true,
        requestedCount: 1,
        enrichedCount: 1,
      },
    });

    render(<StockScreeningPage />);

    expect(await screen.findByText('选股已开启')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /运行选股/ }));

    expect(await screen.findByText('DSA增强：1 / 1')).toBeInTheDocument();

    expect(screen.getByText('DSA 增强摘要')).toBeInTheDocument();
    expect(screen.getByText(/DSA行情：现价 1688/)).toBeInTheDocument();
    expect(screen.getByText('DSA 新闻')).toBeInTheDocument();
    expect(screen.getByText('贵州茅台最新公告')).toBeInTheDocument();
    expect(screen.getByText('DSA 增强提示')).toBeInTheDocument();
    expect(screen.getByText('stock_news_unavailable')).toBeInTheDocument();
  });
});
