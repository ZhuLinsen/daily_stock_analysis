import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AlertsPage from '../AlertsPage';

const {
  listRules,
  createRule,
  deleteRule,
  enableRule,
  disableRule,
  testRule,
  listTriggers,
  listNotifications,
} = vi.hoisted(() => ({
  listRules: vi.fn(),
  createRule: vi.fn(),
  deleteRule: vi.fn(),
  enableRule: vi.fn(),
  disableRule: vi.fn(),
  testRule: vi.fn(),
  listTriggers: vi.fn(),
  listNotifications: vi.fn(),
}));

vi.mock('../../api/alerts', () => ({
  alertsApi: {
    listRules,
    createRule,
    deleteRule,
    enableRule,
    disableRule,
    testRule,
    listTriggers,
    listNotifications,
  },
}));

vi.mock('../../api/portfolio', () => ({
  portfolioApi: {
    getAccounts: vi.fn().mockResolvedValue({ accounts: [] }),
  },
}));

const parsedError = {
  title: '加载失败',
  message: '告警 API 不可用',
  rawMessage: '告警 API 不可用',
  category: 'http_error' as const,
  status: 500,
};

const rule = {
  id: 1,
  name: '茅台价格突破',
  targetScope: 'single_symbol' as const,
  target: '600519',
  alertType: 'price_cross' as const,
  parameters: { direction: 'above' as const, price: 1800 },
  severity: 'warning' as const,
  enabled: true,
  source: 'api',
  createdAt: '2026-05-18T09:00:00',
  updatedAt: '2026-05-18T09:30:00',
};

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  listRules.mockResolvedValue({ items: [rule], total: 1, page: 1, pageSize: 20 });
  listTriggers.mockResolvedValue({
    items: [
      {
        id: 10,
        ruleId: 1,
        target: '600519',
        observedValue: 1801,
        threshold: 1800,
        reason: '600519 price above 1800',
        dataSource: 'realtime_quote',
        dataTimestamp: '2026-05-18T09:30:00',
        triggeredAt: '2026-05-18T09:30:01',
        status: 'triggered',
      },
    ],
    total: 1,
    page: 1,
    pageSize: 20,
  });
  listNotifications.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 });
  testRule.mockResolvedValue({
    ruleId: 1,
    status: 'triggered',
    triggered: true,
    observedValue: 1801,
    message: '600519 price above 1800',
  });
  createRule.mockResolvedValue(rule);
  disableRule.mockResolvedValue({ ...rule, enabled: false });
  enableRule.mockResolvedValue(rule);
  deleteRule.mockResolvedValue({ deleted: 1 });
});

describe('AlertsPage', () => {
  it('discloses environment rules even when the database rule list is empty', async () => {
    listRules.mockResolvedValue({
      items: [], total: 0, page: 1, pageSize: 20,
      ruleSources: { legacyConfigured: 2, legacyEffective: 1 },
    });
    render(<AlertsPage />);
    expect(await screen.findByText('存在环境变量告警规则')).toBeInTheDocument();
    expect(screen.getByText(/配置了 2 条有效规则.*去重后有 1 条/)).toBeInTheDocument();
    expect(screen.getByText(/删除或禁用页面规则不会停用环境规则/)).toBeInTheDocument();
  });

  it('keeps the warning when enabled database rules currently cover all environment rules', async () => {
    listRules.mockResolvedValue({
      items: [rule], total: 1, page: 1, pageSize: 20,
      ruleSources: { legacyConfigured: 1, legacyEffective: 0 },
    });
    render(<AlertsPage />);
    expect(await screen.findByText('存在环境变量告警规则')).toBeInTheDocument();
    expect(screen.getByText(/去重后有 0 条/)).toBeInTheDocument();
  });

  it('does not warn when no valid environment rules are configured', async () => {
    listRules.mockResolvedValue({
      items: [rule], total: 1, page: 1, pageSize: 20,
      ruleSources: { legacyConfigured: 0, legacyEffective: 0 },
    });
    render(<AlertsPage />);
    expect(await screen.findByText('茅台价格突破')).toBeInTheDocument();
    expect(screen.queryByText('存在环境变量告警规则')).not.toBeInTheDocument();
  });

  it('loads rules, trigger history, and notification empty state', async () => {
    render(<AlertsPage />);

    expect(screen.getByText('管理事件告警、日线技术指标、自选股、持仓/账户联动和大盘红绿灯规则，执行一次性测试，并查看后台评估任务记录的触发历史。')).toBeInTheDocument();
    expect(await screen.findByText('茅台价格突破')).toBeInTheDocument();
    expect(await screen.findByText('600519 price above 1800')).toBeInTheDocument();
    expect(await screen.findByText('暂无通知尝试记录')).toBeInTheDocument();
    expect(listRules).toHaveBeenCalledWith({
      enabled: undefined,
      alertType: undefined,
      page: 1,
      pageSize: 20,
    });
    expect(listTriggers).toHaveBeenCalledWith({ page: 1, pageSize: 20 });
    expect(listNotifications).toHaveBeenCalledWith({ page: 1, pageSize: 20 });
  });

  it('runs a dry-run test and renders only declared response fields', async () => {
    listTriggers.mockResolvedValueOnce({ items: [], total: 0, page: 1, pageSize: 20 });
    render(<AlertsPage />);

    fireEvent.click(await screen.findByRole('button', { name: '测试' }));

    await waitFor(() => expect(testRule).toHaveBeenCalledWith(1));
    expect(await screen.findByText('测试结果')).toBeInTheDocument();
    expect(screen.getByText(/600519 price above 1800/)).toBeInTheDocument();
    expect(screen.getByText(/观察值：1801/)).toBeInTheDocument();
    expect(screen.queryByText(/realtime_quote/)).not.toBeInTheDocument();
  });

  it('renders batch dry-run summary and target results', async () => {
    testRule.mockResolvedValueOnce({
      ruleId: 1,
      targetScope: 'watchlist',
      status: 'triggered',
      triggered: true,
      observedValue: 11,
      message: 'Evaluated 2 targets',
      evaluatedCount: 2,
      triggeredCount: 1,
      degradedCount: 1,
      skippedCount: 0,
      targetResults: [
        {
          target: '600519',
          displayTarget: '自选股 - 600519',
          status: 'triggered',
          recordStatus: 'triggered',
          triggered: true,
          observedValue: 11,
          message: 'triggered',
        },
        {
          target: '000001',
          displayTarget: '自选股 - 000001',
          status: 'not_triggered',
          recordStatus: 'degraded',
          triggered: false,
          observedValue: null,
          message: 'degraded',
        },
      ],
    });
    render(<AlertsPage />);

    fireEvent.click(await screen.findByRole('button', { name: '测试' }));

    expect(await screen.findByText(/评估 2 · 触发 1 · 降级 1 · 跳过 0/)).toBeInTheDocument();
    expect(screen.getByText('自选股 - 600519')).toBeInTheDocument();
    expect(screen.getByText(/not_triggered \/ degraded/)).toBeInTheDocument();
  });

  it('creates a rule through the page form and reloads rules', async () => {
    render(<AlertsPage />);

    await screen.findByText('茅台价格突破');
    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: 'aapl' } });
    fireEvent.change(screen.getByLabelText('价格阈值'), { target: { value: '200' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    await waitFor(() => {
      expect(createRule).toHaveBeenCalledWith(expect.objectContaining({
        target: 'AAPL',
        alertType: 'price_cross',
        parameters: { direction: 'above', price: 200 },
      }));
    });
    expect(await screen.findByText(/已创建告警规则/)).toBeInTheDocument();
  });

  it('keeps create form values when create API fails', async () => {
    createRule.mockRejectedValueOnce({ parsedError });
    render(<AlertsPage />);

    await screen.findByText('茅台价格突破');
    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: 'aapl' } });
    fireEvent.change(screen.getByLabelText('价格阈值'), { target: { value: '200' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));

    expect(await screen.findByText('加载失败')).toBeInTheDocument();
    expect(screen.getByLabelText('标的代码')).toHaveValue('aapl');
    expect(screen.getByLabelText('价格阈值')).toHaveValue(200);
  });

  it('clamps rules pagination when a mutation leaves the current page empty', async () => {
    const page2Rule = { ...rule, id: 2, name: '第二页规则', target: 'AAPL' };
    listRules
      .mockResolvedValueOnce({ items: [rule], total: 21, page: 1, pageSize: 20 })
      .mockResolvedValueOnce({ items: [page2Rule], total: 21, page: 2, pageSize: 20 })
      .mockResolvedValueOnce({ items: [], total: 20, page: 2, pageSize: 20 })
      .mockResolvedValue({ items: [rule], total: 20, page: 1, pageSize: 20 });

    render(<AlertsPage />);

    expect(await screen.findByText('茅台价格突破')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '2' }));
    expect(await screen.findByText('第二页规则')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('删除 第二页规则'));
    fireEvent.click(await screen.findByRole('button', { name: '删除' }));

    await waitFor(() => expect(deleteRule).toHaveBeenCalledWith(2));
    await waitFor(() => {
      expect(listRules).toHaveBeenCalledWith({
        enabled: undefined,
        alertType: undefined,
        page: 1,
        pageSize: 20,
      });
    });
    expect(await screen.findByText('茅台价格突破')).toBeInTheDocument();
  });

  it('keeps the latest rules response when filter requests resolve out of order', async () => {
    const initialRequest = createDeferred<{ items: Array<typeof rule>; total: number; page: number; pageSize: number }>();
    const filteredRequest = createDeferred<{ items: Array<typeof rule>; total: number; page: number; pageSize: number }>();
    const staleRule = { ...rule, id: 3, name: '旧筛选规则', enabled: true };
    const filteredRule = { ...rule, id: 4, name: '停用规则', enabled: false };
    listRules
      .mockReset()
      .mockReturnValueOnce(initialRequest.promise)
      .mockReturnValueOnce(filteredRequest.promise);

    render(<AlertsPage />);

    fireEvent.change(screen.getByLabelText('启停状态'), { target: { value: 'disabled' } });
    await waitFor(() => expect(listRules).toHaveBeenCalledTimes(2));

    filteredRequest.resolve({ items: [filteredRule], total: 1, page: 1, pageSize: 20 });
    expect(await screen.findByText('停用规则')).toBeInTheDocument();

    initialRequest.resolve({ items: [staleRule], total: 1, page: 1, pageSize: 20 });
    await waitFor(() => expect(screen.queryByText('旧筛选规则')).not.toBeInTheDocument());
    expect(screen.getByText('停用规则')).toBeInTheDocument();
  });

  it('refreshes toggle results with the latest enabled filter after a pending mutation', async () => {
    const enabledRule = { ...rule, name: '可停用规则', enabled: true };
    const disabledRule = { ...rule, id: 2, name: '已停用规则', enabled: false };
    const otherEnabledRule = { ...rule, id: 3, name: '其他启用规则', enabled: true };
    const disableRequest = createDeferred<typeof disabledRule>();
    let mutationApplied = false;

    disableRule.mockReturnValueOnce(disableRequest.promise);
    listRules.mockImplementation(async (query: { enabled?: boolean }) => {
      if (query.enabled === false) {
        return {
          items: mutationApplied ? [disabledRule, { ...enabledRule, enabled: false }] : [disabledRule],
          total: mutationApplied ? 2 : 1,
          page: 1,
          pageSize: 20,
        };
      }
      return {
        items: [mutationApplied ? { ...enabledRule, enabled: false } : enabledRule, disabledRule, otherEnabledRule],
        total: 3,
        page: 1,
        pageSize: 20,
      };
    });

    render(<AlertsPage />);

    expect(await screen.findByText('其他启用规则')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: '停用' })[0]);
    fireEvent.change(screen.getByLabelText('启停状态'), { target: { value: 'disabled' } });

    await waitFor(() => expect(screen.queryByText('其他启用规则')).not.toBeInTheDocument());
    await act(async () => {
      mutationApplied = true;
      disableRequest.resolve({ ...enabledRule, enabled: false });
    });

    await waitFor(() => expect(listRules).toHaveBeenLastCalledWith({
      enabled: false,
      alertType: undefined,
      page: 1,
      pageSize: 20,
    }));
    expect(screen.getByLabelText('启停状态')).toHaveValue('disabled');
    expect(screen.getByText('可停用规则')).toBeInTheDocument();
    expect(screen.queryByText('其他启用规则')).not.toBeInTheDocument();
  });

  it('refreshes create results with the latest type filter after a pending mutation', async () => {
    const priceRule = { ...rule, name: '价格规则', alertType: 'price_cross' as const };
    const volumeRule = { ...rule, id: 2, name: '成交量规则', alertType: 'volume_spike' as const };
    const createRequest = createDeferred<typeof priceRule>();

    createRule.mockReturnValueOnce(createRequest.promise);
    listRules.mockImplementation(async (query: { alertType?: string }) => {
      if (query.alertType === 'volume_spike') {
        return { items: [volumeRule], total: 1, page: 1, pageSize: 20 };
      }
      if (query.alertType === 'price_cross') {
        return { items: [priceRule], total: 1, page: 1, pageSize: 20 };
      }
      return { items: [priceRule, volumeRule], total: 2, page: 1, pageSize: 20 };
    });

    render(<AlertsPage />);

    expect(await screen.findByText('价格规则')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: 'aapl' } });
    fireEvent.change(screen.getByLabelText('价格阈值'), { target: { value: '200' } });
    fireEvent.click(screen.getByRole('button', { name: '创建规则' }));
    fireEvent.change(screen.getAllByLabelText('规则类型')[1], { target: { value: 'volume_spike' } });

    await waitFor(() => expect(screen.queryByText('价格规则')).not.toBeInTheDocument());
    await act(async () => {
      createRequest.resolve(priceRule);
    });

    await waitFor(() => expect(listRules).toHaveBeenLastCalledWith({
      enabled: undefined,
      alertType: 'volume_spike',
      page: 1,
      pageSize: 20,
    }));
    expect(screen.getAllByLabelText('规则类型')[1]).toHaveValue('volume_spike');
    expect(screen.getByText('成交量规则')).toBeInTheDocument();
    expect(screen.queryByText('价格规则')).not.toBeInTheDocument();
  });

  it('refreshes delete results with the latest page after a pending mutation', async () => {
    const page2Rule = { ...rule, id: 2, name: '第二页待删规则', target: 'AAPL' };
    const deleteRequest = createDeferred<{ deleted: number }>();

    deleteRule.mockReturnValueOnce(deleteRequest.promise);
    listRules.mockImplementation(async (query: { page?: number }) => {
      if (query.page === 2) {
        return { items: [page2Rule], total: 21, page: 2, pageSize: 20 };
      }
      return { items: [rule], total: 21, page: 1, pageSize: 20 };
    });

    render(<AlertsPage />);

    expect(await screen.findByText('茅台价格突破')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '2' }));
    expect(await screen.findByText('第二页待删规则')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('删除 第二页待删规则'));
    fireEvent.click(await screen.findByRole('button', { name: '删除' }));
    fireEvent.click(screen.getByRole('button', { name: '1' }));

    expect(await screen.findByText('茅台价格突破')).toBeInTheDocument();
    await act(async () => {
      deleteRequest.resolve({ deleted: 1 });
    });

    await waitFor(() => expect(listRules).toHaveBeenLastCalledWith({
      enabled: undefined,
      alertType: undefined,
      page: 1,
      pageSize: 20,
    }));
    expect(screen.getByText('茅台价格突破')).toBeInTheDocument();
    expect(screen.queryByText('第二页待删规则')).not.toBeInTheDocument();
  });

  it('renders API errors through ApiErrorAlert', async () => {
    listRules.mockRejectedValueOnce({ parsedError });

    render(<AlertsPage />);

    expect(await screen.findByText('加载失败')).toBeInTheDocument();
    expect(screen.getByText('告警 API 不可用')).toBeInTheDocument();
  });

  it('keeps concurrent rule busy states independent and ignores stale test response', async () => {
    const rule1 = { ...rule, id: 1, name: '规则一', target: '600519' };
    const rule2 = { ...rule, id: 2, name: '规则二', target: 'AAPL' };
    const testDeferred1 = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number;
      message: string;
    }>();
    const testDeferred2 = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number;
      message: string;
    }>();

    listRules.mockResolvedValue({ items: [rule1, rule2], total: 2, page: 1, pageSize: 20 });
    testRule
      .mockReturnValueOnce(testDeferred1.promise)
      .mockReturnValueOnce(testDeferred2.promise);

    render(<AlertsPage />);

    await screen.findByText('规则一');
    const testButtons = screen.getAllByRole('button', { name: '测试' });
    expect(testButtons).toHaveLength(2);

    fireEvent.click(testButtons[0]);
    fireEvent.click(testButtons[1]);

    expect(screen.getAllByRole('button', { name: '测试中' })).toHaveLength(2);

    await act(async () => {
      testDeferred2.resolve({
        ruleId: 2,
        status: 'triggered',
        triggered: true,
        observedValue: 222,
        message: 'rule2 fresh result',
      });
    });

    expect(await screen.findByText(/rule2 fresh result/)).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '测试中' })).toHaveLength(1);

    await act(async () => {
      testDeferred1.resolve({
        ruleId: 1,
        status: 'not_triggered',
        triggered: false,
        observedValue: 111,
        message: 'rule1 stale result',
      });
    });

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '测试中' })).not.toBeInTheDocument();
    });
    expect(screen.getByText(/rule2 fresh result/)).toBeInTheDocument();
    expect(screen.queryByText(/rule1 stale result/)).not.toBeInTheDocument();
  });

  it('preserves failure feedback for an earlier rule test when a concurrent rule test succeeds first', async () => {
    const rule1 = { ...rule, id: 1, name: '规则一', target: '600519' };
    const rule2 = { ...rule, id: 2, name: '规则二', target: 'AAPL' };
    const testDeferred1 = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number;
      message: string;
    }>();
    const testDeferred2 = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number;
      message: string;
    }>();

    listRules.mockResolvedValue({ items: [rule1, rule2], total: 2, page: 1, pageSize: 20 });
    testRule
      .mockReturnValueOnce(testDeferred1.promise)
      .mockReturnValueOnce(testDeferred2.promise);

    render(<AlertsPage />);

    await screen.findByText('规则一');
    const testButtons = screen.getAllByRole('button', { name: '测试' });

    fireEvent.click(testButtons[0]);
    fireEvent.click(testButtons[1]);

    await act(async () => {
      testDeferred2.resolve({
        ruleId: 2,
        status: 'not_triggered',
        triggered: false,
        observedValue: 222,
        message: 'rule2 completed cleanly',
      });
    });

    expect(await screen.findByText(/rule2 completed cleanly/)).toBeInTheDocument();

    await act(async () => {
      testDeferred1.reject({
        parsedError: {
          title: '测试失败',
          message: '规则一检测接口返回 500',
          rawMessage: '规则一检测接口返回 500',
          category: 'http_error' as const,
          status: 500,
        },
      });
    });

    expect(await screen.findByText('测试失败')).toBeInTheDocument();
    expect(screen.getByText('规则一检测接口返回 500')).toBeInTheDocument();
    expect(screen.getByText(/rule2 completed cleanly/)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '测试中' })).not.toBeInTheDocument();
    });
  });

  it('clears displayed test result when the tested rule is deleted', async () => {
    listRules
      .mockResolvedValueOnce({ items: [rule], total: 1, page: 1, pageSize: 20 })
      .mockResolvedValueOnce({ items: [], total: 0, page: 1, pageSize: 20 });
    testRule.mockResolvedValueOnce({
      ruleId: 1,
      status: 'triggered',
      triggered: true,
      observedValue: 1888,
      message: 'live rule1 test result',
    });

    render(<AlertsPage />);

    await screen.findByText('茅台价格突破');
    fireEvent.click(screen.getByRole('button', { name: '测试' }));
    expect(await screen.findByText(/live rule1 test result/)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('删除 茅台价格突破'));
    fireEvent.click(await screen.findByRole('button', { name: '删除' }));

    await waitFor(() => expect(deleteRule).toHaveBeenCalledWith(1));
    await waitFor(() => {
      expect(screen.queryByText('测试结果')).not.toBeInTheDocument();
      expect(screen.queryByText(/live rule1 test result/)).not.toBeInTheDocument();
    });
  });

  it('guards double-submit on create rule and ignores post-unmount settlements', async () => {
    const pendingTriggers = createDeferred<{ items: never[]; total: number; page: number; pageSize: number }>();
    const pendingNotifications = createDeferred<{ items: never[]; total: number; page: number; pageSize: number }>();
    const pendingCreate = createDeferred<typeof rule>();
    const pendingTest = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number;
      message: string;
    }>();
    const pendingRules = createDeferred<{ items: never[]; total: number; page: number; pageSize: number }>();

    listRules
      .mockResolvedValueOnce({ items: [rule], total: 1, page: 1, pageSize: 20 })
      .mockReturnValueOnce(pendingRules.promise);
    listTriggers.mockReturnValueOnce(pendingTriggers.promise);
    listNotifications.mockReturnValueOnce(pendingNotifications.promise);
    createRule.mockReturnValueOnce(pendingCreate.promise);
    testRule.mockReturnValueOnce(pendingTest.promise);

    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      const { unmount } = render(<AlertsPage />);

      await screen.findByText('茅台价格突破');
      fireEvent.click(screen.getByRole('button', { name: '测试' }));
      fireEvent.change(screen.getByLabelText('标的代码'), { target: { value: 'aapl' } });
      fireEvent.change(screen.getByLabelText('价格阈值'), { target: { value: '200' } });

      const createButton = screen.getByRole('button', { name: '创建规则' });
      fireEvent.click(createButton);
      fireEvent.click(createButton);
      expect(createRule).toHaveBeenCalledTimes(1);

      fireEvent.change(screen.getByLabelText('启停状态'), { target: { value: 'disabled' } });
      await waitFor(() => expect(listRules).toHaveBeenCalledTimes(2));

      unmount();

      await act(async () => {
        pendingTriggers.resolve({ items: [], total: 0, page: 1, pageSize: 20 });
        pendingNotifications.reject(new Error('unmounted abort'));
        pendingCreate.resolve(rule);
        pendingTest.resolve({
          ruleId: 1,
          status: 'triggered',
          triggered: true,
          observedValue: 1805,
          message: 'post-unmount result',
        });
        pendingRules.resolve({ items: [], total: 0, page: 1, pageSize: 20 });
        await Promise.resolve();
      });

      expect(consoleErrorSpy).not.toHaveBeenCalled();
    } finally {
      consoleErrorSpy.mockRestore();
    }
  });

  it('preserves HTTP 200 evaluation_error feedback for an earlier rule test when a concurrent rule test completes first', async () => {
    const rule1 = { ...rule, id: 1, name: '规则一', target: '600519' };
    const rule2 = { ...rule, id: 2, name: '规则二', target: 'AAPL' };
    const testDeferred1 = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number | null;
      message: string;
    }>();
    const testDeferred2 = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number;
      message: string;
    }>();

    listRules.mockResolvedValue({ items: [rule1, rule2], total: 2, page: 1, pageSize: 20 });
    testRule
      .mockReturnValueOnce(testDeferred1.promise)
      .mockReturnValueOnce(testDeferred2.promise);

    render(<AlertsPage />);

    await screen.findByText('规则一');
    const testButtons = screen.getAllByRole('button', { name: '测试' });

    fireEvent.click(testButtons[0]);
    fireEvent.click(testButtons[1]);

    await act(async () => {
      testDeferred2.resolve({
        ruleId: 2,
        status: 'not_triggered',
        triggered: false,
        observedValue: 222,
        message: 'rule2 completed cleanly',
      });
    });

    expect(await screen.findByText(/rule2 completed cleanly/)).toBeInTheDocument();

    await act(async () => {
      testDeferred1.resolve({
        ruleId: 1,
        status: 'evaluation_error',
        triggered: false,
        observedValue: null,
        message: 'No daily data available for 600519',
      });
    });

    expect(await screen.findByText('规则「规则一」测试失败')).toBeInTheDocument();
    expect(screen.getByText('No daily data available for 600519')).toBeInTheDocument();
    expect(screen.getByText(/rule2 completed cleanly/)).toBeInTheDocument();
  });

  it('retains rule test failure feedback when a concurrent listRules refresh finishes later (OR-COR-979817a9)', async () => {
    const rule1 = { ...rule, id: 1, name: '规则一', target: '600519' };
    const rule2 = { ...rule, id: 2, name: '规则二', target: 'AAPL' };
    const testDeferred1 = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number | null;
      message: string;
    }>();
    const testDeferred2 = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number;
      message: string;
    }>();
    const refreshDeferred = createDeferred<{
      items: typeof rule1[];
      total: number;
      page: number;
      pageSize: number;
    }>();

    listRules
      .mockReset()
      .mockResolvedValueOnce({ items: [rule1, rule2], total: 2, page: 1, pageSize: 20 })
      .mockReturnValueOnce(refreshDeferred.promise);
    testRule
      .mockReset()
      .mockReturnValueOnce(testDeferred1.promise)
      .mockReturnValueOnce(testDeferred2.promise);

    render(<AlertsPage />);

    await screen.findByText('规则一');
    const testButtons = screen.getAllByRole('button', { name: '测试' });

    fireEvent.click(testButtons[0]);
    fireEvent.click(testButtons[1]);

    await act(async () => {
      testDeferred2.resolve({
        ruleId: 2,
        status: 'not_triggered',
        triggered: false,
        observedValue: 222,
        message: 'rule2 completed cleanly',
      });
    });
    expect(await screen.findByText(/rule2 completed cleanly/)).toBeInTheDocument();

    // Switch filter so listRules refresh is in flight while rule1 test fails.
    fireEvent.change(screen.getByLabelText('启停状态'), { target: { value: 'disabled' } });
    await waitFor(() => expect(listRules).toHaveBeenCalledTimes(2));

    await act(async () => {
      testDeferred1.resolve({
        ruleId: 1,
        status: 'evaluation_error',
        triggered: false,
        observedValue: null,
        message: 'No daily data available for 600519',
      });
    });

    expect(await screen.findByText('规则「规则一」测试失败')).toBeInTheDocument();

    // Resolving the list refresh must not wipe test failure feedback.
    await act(async () => {
      refreshDeferred.resolve({ items: [rule1, rule2], total: 2, page: 1, pageSize: 20 });
    });

    expect(screen.getByText('规则「规则一」测试失败')).toBeInTheDocument();
    expect(screen.getByText('No daily data available for 600519')).toBeInTheDocument();
    expect(screen.getByText(/rule2 completed cleanly/)).toBeInTheDocument();
  });

  it('surfaces partial target failures when an earlier batch rule test settles with top-level not_triggered (OR-COR-cfcbe3f4)', async () => {
    const batchRule = {
      ...rule,
      id: 1,
      name: '自选股批测规则',
      targetScope: 'watchlist',
      target: 'watchlist',
    };
    const singleRule = { ...rule, id: 2, name: '单股规则二', target: 'AAPL' };
    const batchDeferred = createDeferred<{
      ruleId: number;
      targetScope: string;
      status: string;
      triggered: boolean;
      observedValue: number | null;
      message: string;
      evaluatedCount: number;
      triggeredCount: number;
      degradedCount: number;
      skippedCount: number;
      targetResults: Array<{
        target: string;
        displayTarget: string;
        status: string;
        recordStatus: string;
        triggered: boolean;
        message: string;
      }>;
    }>();
    const singleDeferred = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number;
      message: string;
    }>();

    listRules
      .mockReset()
      .mockResolvedValue({ items: [batchRule, singleRule], total: 2, page: 1, pageSize: 20 });
    testRule
      .mockReset()
      .mockReturnValueOnce(batchDeferred.promise)
      .mockReturnValueOnce(singleDeferred.promise);

    render(<AlertsPage />);

    await screen.findByText('自选股批测规则');
    const testButtons = screen.getAllByRole('button', { name: '测试' });

    fireEvent.click(testButtons[0]);
    fireEvent.click(testButtons[1]);

    await act(async () => {
      singleDeferred.resolve({
        ruleId: 2,
        status: 'not_triggered',
        triggered: false,
        observedValue: 195,
        message: 'AAPL single rule ok',
      });
    });
    expect(await screen.findByText(/AAPL single rule ok/)).toBeInTheDocument();

    await act(async () => {
      batchDeferred.resolve({
        ruleId: 1,
        targetScope: 'watchlist',
        status: 'not_triggered',
        triggered: false,
        observedValue: 185,
        message: 'Evaluated 2 targets: 0 triggered, 0 degraded, 0 skipped, 1 failed',
        evaluatedCount: 2,
        triggeredCount: 0,
        degradedCount: 0,
        skippedCount: 0,
        targetResults: [
          {
            target: 'AAPL',
            displayTarget: 'AAPL',
            status: 'not_triggered',
            recordStatus: 'skipped',
            triggered: false,
            message: 'ok',
          },
          {
            target: '600519',
            displayTarget: '600519',
            status: 'evaluation_error',
            recordStatus: 'failed',
            triggered: false,
            message: 'No daily data for 600519',
          },
        ],
      });
    });

    expect(await screen.findByText('规则「自选股批测规则」部分标的测试失败')).toBeInTheDocument();
    expect(screen.getByText(/600519: No daily data for 600519/)).toBeInTheDocument();
    expect(screen.getByText(/AAPL single rule ok/)).toBeInTheDocument();
  });

  it('surfaces truncated batch failure count when an earlier 21-target test completes after a newer test (OR-COR-cfcbe3f4)', async () => {
    const batchRule = {
      ...rule,
      id: 1,
      name: '自选股批测规则',
      targetScope: 'watchlist' as const,
      target: 'default',
    };
    const singleRule = { ...rule, id: 2, name: '单股规则二', target: 'AAPL' };
    const batchDeferred = createDeferred<{
      ruleId: number;
      targetScope: string;
      status: string;
      triggered: boolean;
      observedValue: number | null;
      message: string;
      evaluatedCount: number;
      triggeredCount: number;
      degradedCount: number;
      skippedCount: number;
      failedCount: number;
      targetResults: Array<{
        target: string;
        displayTarget: string;
        status: string;
        recordStatus: string;
        triggered: boolean;
        observedValue: number;
        message: string;
      }>;
    }>();
    const singleDeferred = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number;
      message: string;
    }>();

    listRules
      .mockReset()
      .mockResolvedValue({ items: [batchRule, singleRule], total: 2, page: 1, pageSize: 20 });
    testRule
      .mockReset()
      .mockReturnValueOnce(batchDeferred.promise)
      .mockReturnValueOnce(singleDeferred.promise);

    render(<AlertsPage />);

    await screen.findByText('自选股批测规则');
    const testButtons = screen.getAllByRole('button', { name: '测试' });

    fireEvent.click(testButtons[0]);
    fireEvent.click(testButtons[1]);

    await act(async () => {
      singleDeferred.resolve({
        ruleId: 2,
        status: 'not_triggered',
        triggered: false,
        observedValue: 195,
        message: 'AAPL single rule ok',
      });
    });
    expect(await screen.findByText(/AAPL single rule ok/)).toBeInTheDocument();

    const truncatedTriggeredTargets = Array.from({ length: 20 }, (_, idx) => ({
      target: `600${String(idx + 1).padStart(3, '0')}`,
      displayTarget: `自选股 - 600${String(idx + 1).padStart(3, '0')}`,
      status: 'triggered',
      recordStatus: 'triggered',
      triggered: true,
      observedValue: 20 + idx,
      message: 'triggered',
    }));

    await act(async () => {
      batchDeferred.resolve({
        ruleId: 1,
        targetScope: 'watchlist',
        status: 'triggered',
        triggered: true,
        observedValue: 20,
        message: 'Evaluated 21 targets: 20 triggered, 0 degraded, 0 skipped, 1 failed',
        evaluatedCount: 21,
        triggeredCount: 20,
        degradedCount: 0,
        skippedCount: 0,
        failedCount: 1,
        targetResults: truncatedTriggeredTargets,
      });
    });

    expect(await screen.findByText('规则「自选股批测规则」部分标的测试失败')).toBeInTheDocument();
    expect(screen.getByText(/Evaluated 21 targets: 20 triggered, 0 degraded, 0 skipped, 1 failed/)).toBeInTheDocument();
    expect(screen.getByText(/共 1 个标的评估失败（超出展示上限未逐条列出）/)).toBeInTheDocument();
    expect(screen.getByText(/AAPL single rule ok/)).toBeInTheDocument();
  });

  it('falls back to summary failure count when an older truncated batch response omits failedCount (OR-COR-cfcbe3f4)', async () => {
    const batchRule = {
      ...rule,
      id: 1,
      name: '旧版自选股批测',
      targetScope: 'watchlist' as const,
      target: 'default',
    };
    const singleRule = { ...rule, id: 2, name: '单股规则二', target: 'AAPL' };
    const batchDeferred = createDeferred<{
      ruleId: number;
      targetScope: string;
      status: string;
      triggered: boolean;
      observedValue: number | null;
      message: string;
      evaluatedCount: number;
      triggeredCount: number;
      degradedCount: number;
      skippedCount: number;
      targetResults: Array<{
        target: string;
        displayTarget: string;
        status: string;
        recordStatus: string;
        triggered: boolean;
        observedValue: number;
        message: string;
      }>;
    }>();
    const singleDeferred = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number;
      message: string;
    }>();

    listRules
      .mockReset()
      .mockResolvedValue({ items: [batchRule, singleRule], total: 2, page: 1, pageSize: 20 });
    testRule
      .mockReset()
      .mockReturnValueOnce(batchDeferred.promise)
      .mockReturnValueOnce(singleDeferred.promise);

    render(<AlertsPage />);

    await screen.findByText('旧版自选股批测');
    const testButtons = screen.getAllByRole('button', { name: '测试' });

    fireEvent.click(testButtons[0]);
    fireEvent.click(testButtons[1]);

    await act(async () => {
      singleDeferred.resolve({
        ruleId: 2,
        status: 'not_triggered',
        triggered: false,
        observedValue: 195,
        message: 'AAPL latest ok',
      });
    });
    expect(await screen.findByText(/AAPL latest ok/)).toBeInTheDocument();

    const truncatedTriggeredTargets = Array.from({ length: 20 }, (_, idx) => ({
      target: `600${String(idx + 1).padStart(3, '0')}`,
      displayTarget: `自选股 - 600${String(idx + 1).padStart(3, '0')}`,
      status: 'triggered',
      recordStatus: 'triggered',
      triggered: true,
      observedValue: 20 + idx,
      message: 'triggered',
    }));

    await act(async () => {
      batchDeferred.resolve({
        ruleId: 1,
        targetScope: 'watchlist',
        status: 'triggered',
        triggered: true,
        observedValue: 20,
        message: 'Evaluated 21 targets: 20 triggered, 0 degraded, 0 skipped, 1 failed',
        evaluatedCount: 21,
        triggeredCount: 20,
        degradedCount: 0,
        skippedCount: 0,
        targetResults: truncatedTriggeredTargets,
      });
    });

    expect(await screen.findByText('规则「旧版自选股批测」部分标的测试失败')).toBeInTheDocument();
    expect(screen.getByText(/共 1 个标的评估失败（超出展示上限未逐条列出）/)).toBeInTheDocument();
    expect(screen.getByText(/AAPL latest ok/)).toBeInTheDocument();
  });

  it('surfaces single-symbol skipped diagnostic when realtime quote is unavailable and settles after a newer test (OR-COR-11085181)', async () => {
    const rule1 = { ...rule, id: 1, name: '规则一', target: '600519' };
    const rule2 = { ...rule, id: 2, name: '规则二', target: 'AAPL' };
    const testDeferred1 = createDeferred<{
      ruleId: number;
      targetScope: string;
      status: string;
      triggered: boolean;
      observedValue: number | null;
      message: string;
      evaluatedCount: number;
      triggeredCount: number;
      degradedCount: number;
      skippedCount: number;
      failedCount: number;
      targetResults: Array<{
        target: string;
        displayTarget: string;
        status: string;
        recordStatus: string;
        triggered: boolean;
        observedValue: number | null;
        message: string;
      }>;
    }>();
    const testDeferred2 = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number;
      message: string;
    }>();

    listRules
      .mockReset()
      .mockResolvedValue({ items: [rule1, rule2], total: 2, page: 1, pageSize: 20 });
    testRule
      .mockReset()
      .mockReturnValueOnce(testDeferred1.promise)
      .mockReturnValueOnce(testDeferred2.promise);

    render(<AlertsPage />);

    await screen.findByText('规则一');
    const testButtons = screen.getAllByRole('button', { name: '测试' });

    fireEvent.click(testButtons[0]);
    fireEvent.click(testButtons[1]);

    await act(async () => {
      testDeferred2.resolve({
        ruleId: 2,
        status: 'not_triggered',
        triggered: false,
        observedValue: 222,
        message: 'rule2 completed cleanly',
      });
    });
    expect(await screen.findByText(/rule2 completed cleanly/)).toBeInTheDocument();

    await act(async () => {
      testDeferred1.resolve({
        ruleId: 1,
        targetScope: 'single_symbol',
        status: 'not_triggered',
        triggered: false,
        observedValue: null,
        message: 'No realtime quote available',
        evaluatedCount: 1,
        triggeredCount: 0,
        degradedCount: 0,
        skippedCount: 1,
        failedCount: 0,
        targetResults: [
          {
            target: '600519',
            displayTarget: '600519',
            status: 'not_triggered',
            recordStatus: 'skipped',
            triggered: false,
            observedValue: null,
            message: 'No realtime quote available',
          },
        ],
      });
    });

    expect(await screen.findByText('规则「规则一」测试未评估')).toBeInTheDocument();
    expect(screen.getByText('No realtime quote available')).toBeInTheDocument();
    expect(screen.getByText(/rule2 completed cleanly/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    await waitFor(() => {
      expect(screen.queryByText('规则「规则一」测试未评估')).not.toBeInTheDocument();
    });
    expect(screen.getByText(/rule2 completed cleanly/)).toBeInTheDocument();
  });

  it('surfaces single-symbol degraded diagnostic when daily data is unavailable and settles after a newer test', async () => {
    const rule1 = { ...rule, id: 1, name: '放量规则一', target: '600519' };
    const rule2 = { ...rule, id: 2, name: '规则二', target: 'AAPL' };
    const testDeferred1 = createDeferred<{
      ruleId: number;
      targetScope: string;
      status: string;
      triggered: boolean;
      observedValue: number | null;
      message: string;
      evaluatedCount: number;
      triggeredCount: number;
      degradedCount: number;
      skippedCount: number;
      failedCount: number;
      targetResults: Array<{
        target: string;
        displayTarget: string;
        status: string;
        recordStatus: string;
        triggered: boolean;
        observedValue: number | null;
        message: string;
      }>;
    }>();
    const testDeferred2 = createDeferred<{
      ruleId: number;
      status: string;
      triggered: boolean;
      observedValue: number;
      message: string;
    }>();

    listRules
      .mockReset()
      .mockResolvedValue({ items: [rule1, rule2], total: 2, page: 1, pageSize: 20 });
    testRule
      .mockReset()
      .mockReturnValueOnce(testDeferred1.promise)
      .mockReturnValueOnce(testDeferred2.promise);

    render(<AlertsPage />);

    await screen.findByText('放量规则一');
    const testButtons = screen.getAllByRole('button', { name: '测试' });

    fireEvent.click(testButtons[0]);
    fireEvent.click(testButtons[1]);

    await act(async () => {
      testDeferred2.resolve({
        ruleId: 2,
        status: 'triggered',
        triggered: true,
        observedValue: 222,
        message: 'rule2 triggered cleanly',
      });
    });
    expect(await screen.findByText(/rule2 triggered cleanly/)).toBeInTheDocument();

    await act(async () => {
      testDeferred1.resolve({
        ruleId: 1,
        targetScope: 'single_symbol',
        status: 'not_triggered',
        triggered: false,
        observedValue: null,
        message: 'No daily volume data available',
        evaluatedCount: 1,
        triggeredCount: 0,
        degradedCount: 1,
        skippedCount: 0,
        failedCount: 0,
        targetResults: [
          {
            target: '600519',
            displayTarget: '600519',
            status: 'not_triggered',
            recordStatus: 'degraded',
            triggered: false,
            observedValue: null,
            message: 'No daily volume data available',
          },
        ],
      });
    });

    expect(await screen.findByText('规则「放量规则一」测试数据降级')).toBeInTheDocument();
    expect(screen.getByText('No daily volume data available')).toBeInTheDocument();
    expect(screen.getByText(/rule2 triggered cleanly/)).toBeInTheDocument();
  });
});
