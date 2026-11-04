import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import HistoryPage from '../HistoryPage';
import { getSentimentLabel, type DailyHistoryListResponse } from '../../types/analysis';
import { toDateInputValue } from '../../utils/format';

const { getDaily } = vi.hoisted(() => ({
  getDaily: vi.fn(),
}));

vi.mock('../../api/history', () => ({
  historyApi: {
    getDaily,
  },
}));

const today = toDateInputValue(new Date());

const latestItem = {
  id: 1,
  code: '600519',
  name: '贵州茅台',
  reportType: 'detailed',
  sentimentScore: 82,
  // 走真实标签函数生成，避免 mock 硬编码绕过标签契约
  sentimentLabel: getSentimentLabel(82, 'zh'),
  operationAdvice: '持有观望',
  trendPrediction: '震荡上行',
  isLatest: true,
  idealBuy: 1650.5,
  secondaryBuy: 1600,
  stopLoss: 1580,
  takeProfit: 1900,
  createdAt: '2026-05-18T09:30:00',
};

const expiredItem = {
  ...latestItem,
  id: 2,
  code: '000001',
  name: '平安银行',
  sentimentScore: null,
  sentimentLabel: null,
  operationAdvice: null,
  trendPrediction: null,
  isLatest: false,
  idealBuy: null,
  secondaryBuy: null,
  stopLoss: null,
  takeProfit: null,
};

const parsedError = {
  title: '历史记录加载失败',
  message: 'history API 不可用',
  rawMessage: 'history API 不可用',
  category: 'http_error' as const,
  status: 500,
};

beforeEach(() => {
  vi.clearAllMocks();
  getDaily.mockResolvedValue({ total: 1, page: 1, limit: 20, items: [latestItem] });
});

describe('HistoryPage', () => {
  it('renders daily rows with score, label, valid badge, and price columns', async () => {
    getDaily.mockResolvedValue({
      total: 2,
      page: 1,
      limit: 20,
      items: [latestItem, expiredItem],
    });

    render(<HistoryPage />);

    expect(await screen.findByText('贵州茅台')).toBeInTheDocument();
    expect(screen.getByText('600519')).toBeInTheDocument();
    expect(screen.getByText('平安银行')).toBeInTheDocument();
    expect(screen.getByText('82')).toBeInTheDocument();
    expect(screen.getByText('极度乐观')).toBeInTheDocument();
    expect(screen.getByText('有效')).toBeInTheDocument();
    expect(screen.getByText('1650.5')).toBeInTheDocument();
    expect(screen.getByText('1900')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(4);
    expect(getDaily).toHaveBeenCalledWith({
      date: today,
      language: 'zh',
      page: 1,
      limit: 20,
    });
  });

  it('shows the structured avoid action instead of legacy buy advice', async () => {
    getDaily.mockResolvedValue({
      total: 1,
      page: 1,
      limit: 20,
      items: [
        {
          ...latestItem,
          sentimentScore: 35,
          operationAdvice: '买入',
          action: 'avoid',
          actionLabel: '回避',
        },
      ],
    });

    render(<HistoryPage />);

    expect(await screen.findByText('回避')).toBeInTheDocument();
    expect(screen.queryByText('买入')).not.toBeInTheDocument();
  });

  it('renders the empty state when the date has no analysis records', async () => {
    getDaily.mockResolvedValue({ total: 0, page: 1, limit: 20, items: [] });

    render(<HistoryPage />);

    expect(await screen.findByText('该日期暂无分析记录')).toBeInTheDocument();
    expect(screen.getByText('换一个交易日试试')).toBeInTheDocument();
  });

  it('renders ApiErrorAlert when getDaily rejects', async () => {
    getDaily.mockRejectedValue({ parsedError });

    render(<HistoryPage />);

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('历史记录加载失败')).toBeInTheDocument();
    expect(screen.getByText('history API 不可用')).toBeInTheDocument();
  });

  it('re-fetches with the new date and page reset when the date input changes', async () => {
    render(<HistoryPage />);

    expect(await screen.findByText('贵州茅台')).toBeInTheDocument();
    getDaily.mockClear();
    fireEvent.change(screen.getByLabelText('日期'), { target: { value: '2026-05-01' } });

    await waitFor(() => {
      expect(getDaily).toHaveBeenCalledWith({
        date: '2026-05-01',
        language: 'zh',
        page: 1,
        limit: 20,
      });
    });
  });

  it('hides stale daily results while the next date request is pending', async () => {
    render(<HistoryPage />);

    expect(await screen.findByText('贵州茅台')).toBeInTheDocument();

    // 受控 deferred promise：B 日请求 pending 期间可精确断言表格归属状态
    let resolveDateB: (response: DailyHistoryListResponse) => void = () => {};
    getDaily.mockImplementationOnce(
      () =>
        new Promise<DailyHistoryListResponse>((resolve) => {
          resolveDateB = resolve;
        }),
    );

    fireEvent.change(screen.getByLabelText('日期'), { target: { value: '2026-05-01' } });

    // pending 期间：上一日期的结果必须让位给加载提示，不得无归属标注地继续展示
    expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument();
    expect(screen.getByText('加载历史记录中...')).toBeInTheDocument();

    await act(async () => {
      resolveDateB({
        total: 1,
        page: 1,
        limit: 20,
        items: [{ ...latestItem, id: 3, name: '宁德时代', code: '300750' }],
      });
    });
    expect(await screen.findByText('宁德时代')).toBeInTheDocument();
    expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument();
    expect(screen.queryByText('加载历史记录中...')).not.toBeInTheDocument();
  });

  it('hides stale daily results while the next page request is pending', async () => {
    getDaily.mockResolvedValueOnce({ total: 40, page: 1, limit: 20, items: [latestItem, expiredItem] });
    render(<HistoryPage />);

    expect(await screen.findByText('贵州茅台')).toBeInTheDocument();

    let resolvePage2: (response: DailyHistoryListResponse) => void = () => {};
    getDaily.mockImplementationOnce(
      () =>
        new Promise<DailyHistoryListResponse>((resolve) => {
          resolvePage2 = resolve;
        }),
    );

    fireEvent.click(screen.getByRole('button', { name: '2' }));

    // pending 期间：第 1 页的结果不得顶着第 2 页的页码继续展示
    expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument();
    expect(screen.getByText('加载历史记录中...')).toBeInTheDocument();

    await act(async () => {
      resolvePage2({
        total: 40,
        page: 2,
        limit: 20,
        items: [{ ...latestItem, id: 4, name: '比亚迪', code: '002594' }],
      });
    });
    expect(await screen.findByText('比亚迪')).toBeInTheDocument();
    expect(screen.queryByText('贵州茅台')).not.toBeInTheDocument();
    expect(screen.queryByText('加载历史记录中...')).not.toBeInTheDocument();
  });

  it('renders the outdated badge for superseded records', async () => {
    getDaily.mockResolvedValue({ total: 1, page: 1, limit: 20, items: [expiredItem] });

    render(<HistoryPage />);

    expect(await screen.findByText('已过期')).toBeInTheDocument();
    expect(screen.queryByText('有效')).not.toBeInTheDocument();
  });

  it('keeps null-score rows labelless instead of the zero-score label', async () => {
    getDaily.mockResolvedValue({ total: 1, page: 1, limit: 20, items: [expiredItem] });

    render(<HistoryPage />);

    expect(await screen.findByText('平安银行')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1);
    // NULL 评分不渲染任何情绪标签，更不能显示 0 分的"极度悲观"
    expect(screen.queryByText('极度悲观')).not.toBeInTheDocument();
    expect(screen.queryByText(getSentimentLabel(0, 'zh'))).not.toBeInTheDocument();
  });

  it('does not trigger a new fetch when the date input is cleared', async () => {
    render(<HistoryPage />);

    expect(await screen.findByText('贵州茅台')).toBeInTheDocument();
    const callsBeforeClear = getDaily.mock.calls.length;
    fireEvent.change(screen.getByLabelText('日期'), { target: { value: '' } });

    await waitFor(() => {
      expect(getDaily.mock.calls.length).toBe(callsBeforeClear);
    });
  });
});
