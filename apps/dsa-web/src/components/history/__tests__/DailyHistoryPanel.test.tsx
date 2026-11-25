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
    // OR-COR-3a68c9f3：选中态走专用 CSS 类（.home-subpanel 的非分层样式会
    // 覆盖 Tailwind 分层工具类，必须用同层专用类表达选中）
    expect(rowB).toHaveClass('home-subpanel-selected');
    expect(screen.getByTestId('daily-history-row-11')).not.toHaveClass('home-subpanel-selected');

    fireEvent.click(screen.getByTestId('daily-history-row-11'));
    expect(onSelectRecord).toHaveBeenCalledWith(11);
  });

  it('fetches every page of the selected date so all reports are reachable (OR-COR-899887df)', async () => {
    const pageOne = Array.from({ length: 100 }, (_, index) => ({
      ...latestOfStockA,
      id: index + 1,
      code: `6005${String(index).padStart(2, '0')}`,
      name: `股票${index + 1}`,
    }));
    const pageTwo = [{ ...latestOfStockA, id: 101, code: '000001', name: '平安银行' }];
    getDaily.mockImplementation((_date: string, options: { page?: number } = {}) => {
      if ((options.page ?? 1) === 1) {
        return Promise.resolve({ total: 101, page: 1, limit: 100, items: pageOne });
      }
      return Promise.resolve({ total: 101, page: 2, limit: 100, items: pageTwo });
    });

    render(<DailyHistoryPanel selectedRecordId={null} onSelectRecord={vi.fn()} />);

    // 第 21 只起的报告此前不可达：修复后须自动翻页直到取满 total。
    // 多页加载完成前有一次首页快照重校验（OR-COR-e9d99614 总数恒定的替换竞态），
    // 静态 mock 下签名一致直接通过：2 页翻页 + 1 次重校验 = 3 次请求。
    expect(await screen.findByTestId('daily-history-row-101')).toBeInTheDocument();
    expect(getDaily).toHaveBeenCalledTimes(3);
    expect(getDaily).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.objectContaining({ page: 1, limit: 100 }),
    );
  });

  it('supports a controlled date so the selection survives drawer remount (OR-COR-278fd558)', async () => {
    const onDateKeyChange = vi.fn();
    render(
      <DailyHistoryPanel
        dateKey="2026-05-18"
        onDateKeyChange={onDateKeyChange}
        selectedRecordId={null}
        onSelectRecord={vi.fn()}
      />,
    );

    // 受控日期：请求带的是外部日期，而非组件内部重置的今天
    expect(await screen.findByTestId('daily-history-row-11')).toBeInTheDocument();
    expect(getDaily).toHaveBeenCalledWith('2026-05-18', expect.anything());

    fireEvent.change(screen.getByTestId('daily-history-date-input'), { target: { value: '2026-05-19' } });
    expect(onDateKeyChange).toHaveBeenCalledWith('2026-05-19');
  });

  it('pins a market review entry so saved recaps stay reachable (OR-COM-91cc3feb)', async () => {
    const onSelectRecord = vi.fn();
    getDaily.mockResolvedValue(dailyResponse([]));

    render(
      <DailyHistoryPanel
        marketReviewEntry={{ id: 2, name: '大盘复盘', createdAt: '2026-05-17T15:00:00+08:00' }}
        selectedRecordId={null}
        onSelectRecord={onSelectRecord}
      />,
    );

    // 当日列表为空也不得吞掉大盘复盘入口（旧个股栏的 MARKET 行语义）
    const entry = await screen.findByTestId('daily-history-market-entry-2');
    expect(screen.getByTestId('daily-history-empty')).toBeInTheDocument();
    fireEvent.click(entry);
    expect(onSelectRecord).toHaveBeenCalledWith(2);
  });

  it('scrolls the selected report row into view after load', async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    try {
      render(<DailyHistoryPanel selectedRecordId={12} onSelectRecord={vi.fn()} />);
      await screen.findByTestId('daily-history-row-12');
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
    } finally {
      delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });

  it('scopes the selected-row lookup to its own list and restores the remembered scroll position (OR-COR-278fd558)', async () => {
    // 手机上隐藏的桌面实例与抽屉实例在 DOM 中并存（桌面在前），共享同一份滚动位置存储
    const scrolledTargets: Element[] = [];
    Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
      scrolledTargets.push(this);
    };

    try {
      const scrollMemory = { current: { '2026-05-18': 320 } as Record<string, number> };
      const { getAllByTestId } = render(
        <>
          <DailyHistoryPanel
            dateKey="2026-05-18"
            scrollMemory={scrollMemory}
            selectedRecordId={12}
            onSelectRecord={vi.fn()}
          />
          <DailyHistoryPanel
            dateKey="2026-05-18"
            scrollMemory={scrollMemory}
            selectedRecordId={12}
            onSelectRecord={vi.fn()}
          />
        </>,
      );
      const lists = await waitFor(() => getAllByTestId('daily-history-list'));
      expect(lists).toHaveLength(2);

      // 每个实例各自滚动自己容器内的选中行：全局查找会先命中排在前面的那一行
      await waitFor(() => expect(scrolledTargets).toHaveLength(2));
      expect(lists[0].contains(scrolledTargets[0])).toBe(true);
      expect(lists[1].contains(scrolledTargets[1])).toBe(true);

      // 该日期上次的滚动位置被恢复，而不是回到顶部
      expect(lists[1].scrollTop).toBe(320);
    } finally {
      delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });

  it('remembers the scroll position per date when the list remounts (OR-COR-278fd558)', async () => {
    render(<DailyHistoryPanel selectedRecordId={null} onSelectRecord={vi.fn()} />);

    const dateInput = await screen.findByTestId('daily-history-date-input');
    fireEvent.change(dateInput, { target: { value: '2026-05-18' } });
    const list = await screen.findByTestId('daily-history-list');
    list.scrollTop = 240;
    fireEvent.scroll(list);

    // 换到别的日期再换回：列表按日期重挂载（与手机抽屉关闭重开同一路径）
    fireEvent.change(dateInput, { target: { value: '2026-05-19' } });
    await waitFor(() => expect(screen.getByTestId('daily-history-list')).not.toBe(list));
    fireEvent.change(dateInput, { target: { value: '2026-05-18' } });
    await waitFor(() => expect(screen.getByTestId('daily-history-list').scrollTop).toBe(240));
  });

  it('dedupes by record and re-syncs when new reports shift the page boundary (OR-COR-e9d99614)', async () => {
    // 当天已有 101 只股票（id 101 最新，排首位）
    const existingRows = Array.from({ length: 101 }, (_, index) => ({
      ...latestOfStockA,
      id: 101 - index,
      code: `6005${String(index).padStart(2, '0')}`,
      name: `股票${101 - index}`,
    }));
    let newReports: unknown[] = [];
    const requestedPages: number[] = [];
    let releaseSecondRequest: () => void = () => {};
    const secondRequestGate = new Promise<void>((resolve) => {
      releaseSecondRequest = resolve;
    });
    getDaily.mockImplementation((_date: string, options: { page?: number } = {}) => {
      const page = options.page ?? 1;
      requestedPages.push(page);
      const respond = () => {
        // 后端口径：每次请求重新排序并按偏移量切页，新报告排到列表首位
        const all = [...newReports, ...existingRows];
        const offset = (page - 1) * 100;
        return { total: all.length, page, limit: 100, items: all.slice(offset, offset + 100) };
      };
      // 第 1 页取回后、第 2 页返回前：批量任务又保存了第 102 只股票的报告
      return requestedPages.length === 2 ? secondRequestGate.then(respond) : Promise.resolve(respond());
    });

    render(<DailyHistoryPanel selectedRecordId={null} onSelectRecord={vi.fn()} />);
    await waitFor(() => expect(requestedPages).toEqual([1, 2]));
    newReports = [{ ...latestOfStockA, id: 102, code: '000002', name: '当日新报告' }];
    releaseSecondRequest();

    // 新报告必须有入口；不得出现重复行
    expect(await screen.findByTestId('daily-history-row-102')).toBeInTheDocument();
    expect(await screen.findByTestId('daily-history-row-1')).toBeInTheDocument();
    const rowIds = screen.getAllByTestId(/^daily-history-row-/).map((row) => row.getAttribute('data-testid'));
    expect(rowIds).toHaveLength(102);
    expect(new Set(rowIds).size).toBe(102);
    // 页边界移动后从第 1 页重取，而不是把偏移过的第 2 页直接拼上去；
    // 重取后的成功拼装在完成前还有一次首页快照重校验（OR-COR-e9d99614，
    // 静态响应下签名一致即通过）
    expect(requestedPages).toEqual([1, 2, 1, 2, 1]);
    expect(screen.getByText('102只')).toBeInTheDocument();
  });

  it('never renders duplicate rows even when the page boundary keeps moving (OR-COR-e9d99614)', async () => {
    const pageOne = Array.from({ length: 100 }, (_, index) => ({
      ...latestOfStockA,
      id: 101 - index,
      code: `6005${String(index).padStart(2, '0')}`,
      name: `股票${101 - index}`,
    }));
    // 第 2 页总是重复第 1 页末尾的一行并报出更大的 total：持续有新报告写入
    getDaily.mockImplementation((_date: string, options: { page?: number } = {}) => {
      if ((options.page ?? 1) === 1) {
        return Promise.resolve({ total: 101, page: 1, limit: 100, items: pageOne });
      }
      return Promise.resolve({ total: 102, page: 2, limit: 100, items: [pageOne[99]] });
    });

    render(<DailyHistoryPanel selectedRecordId={null} onSelectRecord={vi.fn()} />);

    await waitFor(() => expect(screen.getByTestId('daily-history-list')).toBeInTheDocument());
    const rowIds = screen.getAllByTestId(/^daily-history-row-/).map((row) => row.getAttribute('data-testid'));
    expect(rowIds).toHaveLength(100);
    expect(new Set(rowIds).size).toBe(100);
    // 有界重取后收尾，计数标签与实际展示的行数一致
    expect(screen.getByText('100只')).toBeInTheDocument();
    expect(getDaily.mock.calls.length).toBeLessThanOrEqual(6);
  });

  it('resyncs when a delete+add swap keeps the total unchanged (OR-COR-e9d99614)', async () => {
    // 当天 101 只股票（id 101 最新排首位），总数恒定的替换：删一只 + 新增一只
    const baseRows = Array.from({ length: 101 }, (_, index) => ({
      ...latestOfStockA,
      id: 101 - index,
      code: `6005${String(index).padStart(2, '0')}`,
      name: `股票${101 - index}`,
    }));
    let swap: { deletedId: number; added: unknown | null } = { deletedId: 0, added: null };
    const requestedPages: number[] = [];
    let releasePage2: () => void = () => {};
    const page2Gate = new Promise<void>((resolve) => {
      releasePage2 = resolve;
    });
    getDaily.mockImplementation((_date: string, options: { page?: number } = {}) => {
      const page = options.page ?? 1;
      requestedPages.push(page);
      const respond = () => {
        const all = baseRows.filter((row) => row.id !== swap.deletedId);
        if (swap.added) all.unshift(swap.added);
        const offset = (page - 1) * 100;
        return { total: all.length, page, limit: 100, items: all.slice(offset, offset + 100) };
      };
      // 第 2 页的响应被门住：等第 1 页处理完、第 2 页已请求后再做替换
      return page === 2 ? page2Gate.then(respond) : Promise.resolve(respond());
    });

    render(<DailyHistoryPanel selectedRecordId={null} onSelectRecord={vi.fn()} />);
    await waitFor(() => expect(requestedPages).toEqual([1, 2]));

    // 第 1 页已取回、第 2 页尚未返回：删除一只仍在第 1 页里的股票 + 新增一只
    //（新报告按时间倒序排到首位，落在已取过的第 1 页区间，不会再被请求）
    swap = { deletedId: 51, added: { ...latestOfStockA, id: 102, code: '000002', name: '当日新增' } };
    releasePage2();

    // total 始终是 101，去重后恰好凑满——但拼出的必须是同一快照：
    // 新增必须有入口、已删不得仍可点击、无重复行
    expect(await screen.findByTestId('daily-history-row-102')).toBeInTheDocument();
    expect(screen.queryByTestId('daily-history-row-51')).not.toBeInTheDocument();
    const rowIds = screen.getAllByTestId(/^daily-history-row-/).map((row) => row.getAttribute('data-testid'));
    expect(rowIds).toHaveLength(101);
    expect(new Set(rowIds).size).toBe(101);
    expect(screen.getByText('101只')).toBeInTheDocument();
    // 首页签名重校验保证收敛终止，不得无限重取
    expect(getDaily.mock.calls.length).toBeLessThanOrEqual(6);
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
