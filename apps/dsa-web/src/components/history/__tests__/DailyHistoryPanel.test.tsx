import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DailyHistoryPanel from '../DailyHistoryPanel';
import type { DailyHistoryListResponse } from '../../../types/analysis';
import { getSentimentLabel } from '../../../types/analysis';

const { getDaily } = vi.hoisted(() => ({
  getDaily: vi.fn(),
}));

vi.mock('../../../api/history', () => ({
  historyApi: {
    getDaily,
    getList: vi.fn(),
  },
}));

const latestOfStockA = {
  id: 11,
  code: '600519',
  name: '贵州茅台',
  reportType: 'detailed',
  sentimentScore: 82,
  sentimentLabel: getSentimentLabel(82, 'zh'),
  operationAdvice: '持有',
  action: 'hold' as const,
  actionLabel: '持有',
  trendPrediction: '震荡上行',
  isLatest: true,
  analysisCount: 2,
  createdAt: '2026-05-18T09:30:00',
};

const supersededOfStockB = {
  id: 12,
  code: 'hk00700',
  name: '腾讯控股控股有限公司超长名称用于截断验证测试样例账户',
  reportType: 'detailed',
  sentimentScore: null,
  sentimentLabel: null,
  operationAdvice: null,
  action: null,
  actionLabel: null,
  trendPrediction: null,
  isLatest: false,
  analysisCount: 1,
  createdAt: '2026-05-18T15:05:00',
};

function dailyResponse(items: unknown[]): DailyHistoryListResponse {
  return { total: items.length, page: 1, limit: 20, items } as DailyHistoryListResponse;
}

beforeEach(() => {
  vi.clearAllMocks();
  getDaily.mockResolvedValue(dailyResponse([latestOfStockA, supersededOfStockB]));
});

describe('DailyHistoryPanel', () => {
  it('renders lightweight rows with name/code/advice prominent and secondary time/trend', async () => {
    render(<DailyHistoryPanel selectedRecordId={null} onSelectRecord={vi.fn()} />);

    expect(await screen.findByTestId('daily-history-row-11')).toBeInTheDocument();
    expect(screen.getByText('贵州茅台')).toBeInTheDocument();
    expect(screen.getByText('600519')).toBeInTheDocument();
    expect(screen.getByText('持有 82')).toBeInTheDocument();
    // 次级信息：时间与趋势
    expect(screen.getByText('09:30')).toBeInTheDocument();
    expect(screen.getByText('震荡上行')).toBeInTheDocument();
    // spec 1：无值字段自适应精简——score 缺失行不渲染分数徽标与建议
    const rowB = screen.getByTestId('daily-history-row-12');
    expect(rowB).toBeInTheDocument();
    expect(rowB.textContent).not.toContain('null');
  });

  it('marks latest vs superseded with「最新分析/已有更新」labels', async () => {
    render(<DailyHistoryPanel selectedRecordId={null} onSelectRecord={vi.fn()} />);

    expect(await screen.findByText('最新分析')).toBeInTheDocument();
    expect(screen.getByText('已有更新')).toBeInTheDocument();
  });

  it('shows same-stock day count badge and highlights the selected record on click', async () => {
    const onSelectRecord = vi.fn();
    render(<DailyHistoryPanel selectedRecordId={12} onSelectRecord={onSelectRecord} />);

    // spec 3：同股同日多份 → 行取最新一份并标注当日份数
    expect(await screen.findByText('当日2份')).toBeInTheDocument();

    const rowB = await screen.findByTestId('daily-history-row-12');
    expect(rowB.getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(screen.getByTestId('daily-history-row-11'));
    expect(onSelectRecord).toHaveBeenCalledWith(11);
  });

  it('discards stale date responses so old requests never overwrite newer results', async () => {
    const deferred: Array<(value: unknown) => void> = [];
    getDaily.mockImplementation(() => new Promise((resolve) => deferred.push(resolve)));

    render(<DailyHistoryPanel selectedRecordId={null} onSelectRecord={vi.fn()} />);

    // 第一次请求（默认今天）尚未返回，切换日期发起第二次请求
    await waitFor(() => expect(deferred.length).toBe(1));
    const dateInput = await screen.findByTestId('daily-history-date-input');
    fireEvent.change(dateInput, { target: { value: '2026-05-18' } });
    await waitFor(() => expect(deferred.length).toBe(2));

    // 旧请求先回来（慢请求）：不得覆盖新日期的结果
    deferred[0]({ total: 1, page: 1, limit: 20, items: [{ ...latestOfStockA, id: 99, name: '旧日期股票' }] });
    await waitFor(() => expect(deferred.length).toBe(2));
    expect(screen.queryByText('旧日期股票')).not.toBeInTheDocument();

    // 新请求返回：正常渲染
    deferred[1](dailyResponse([{ ...latestOfStockA, id: 11 }]));
    expect(await screen.findByTestId('daily-history-row-11')).toBeInTheDocument();
  });

  it('shows empty-state guidance for dates without records and a distinct load-failure state', async () => {
    render(<DailyHistoryPanel selectedRecordId={null} onSelectRecord={vi.fn()} />);

    getDaily.mockResolvedValue(dailyResponse([]));
    fireEvent.change(await screen.findByTestId('daily-history-date-input'), { target: { value: '2026-05-19' } });
    expect(await screen.findByTestId('daily-history-empty')).toBeInTheDocument();

    getDaily.mockRejectedValue(new Error('boom'));
    fireEvent.change(screen.getByTestId('daily-history-date-input'), { target: { value: '2026-05-20' } });
    expect(await screen.findByTestId('daily-history-load-error')).toBeInTheDocument();
  });
});
