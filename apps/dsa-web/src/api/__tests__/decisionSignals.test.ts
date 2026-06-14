import { beforeEach, describe, expect, it, vi } from 'vitest';
import { decisionSignalsApi } from '../decisionSignals';

const { get, post, patch } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}));

vi.mock('../index', () => ({
  default: {
    get,
    post,
    patch,
  },
}));

describe('decisionSignalsApi', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    patch.mockReset();
  });

  it('creates signals with top-level field mapping and opaque JSON pass-through', async () => {
    post.mockResolvedValueOnce({
      data: {
        item: {
          id: 11,
          stock_code: '600519',
          stock_name: '贵州茅台',
          market: 'cn',
          source_type: 'analysis',
          source_agent: null,
          source_report_id: 3001,
          trace_id: 'trace-3001',
          market_phase: 'intraday',
          trigger_source: 'api',
          action: 'watch',
          action_label: '观察',
          confidence: 0.72,
          score: 76,
          horizon: '3d',
          entry_low: 1680,
          entry_high: 1720,
          stop_loss: 1600,
          target_price: 1850,
          invalidation: '跌破支撑',
          watch_conditions: '放量突破',
          reason: '趋势改善',
          risk_summary: '波动较高',
          catalyst_summary: '行业修复',
          evidence: { source_url: 'https://example.com/news' },
          data_quality_summary: { raw_score: 80, level: 'usable' },
          plan_quality: 'complete',
          status: 'active',
          expires_at: '2026-06-12T08:00:00',
          created_at: '2026-06-11T08:00:00',
          updated_at: '2026-06-11T08:00:00',
          metadata: { task_id: 'task-1' },
        },
        created: false,
      },
    });

    const response = await decisionSignalsApi.create({
      stockCode: '600519',
      stockName: '贵州茅台',
      market: 'cn',
      sourceType: 'analysis',
      sourceReportId: 3001,
      traceId: 'trace-3001',
      marketPhase: 'intraday',
      triggerSource: 'api',
      action: 'watch',
      actionLabel: '观察',
      confidence: 0.72,
      score: 76,
      horizon: '3d',
      entryLow: 1680,
      entryHigh: 1720,
      stopLoss: 1600,
      targetPrice: 1850,
      invalidation: '跌破支撑',
      watchConditions: '放量突破',
      reason: '趋势改善',
      riskSummary: '波动较高',
      catalystSummary: '行业修复',
      evidence: { sourceUrl: 'https://example.com/news' },
      dataQualitySummary: { level: 'usable' },
      planQuality: 'complete',
      status: 'active',
      expiresAt: '2026-06-12T08:00:00',
      metadata: { taskId: 'task-1' },
      reportLanguage: 'zh',
    });

    expect(post).toHaveBeenCalledWith('/api/v1/decision-signals', {
      stock_code: '600519',
      stock_name: '贵州茅台',
      market: 'cn',
      source_type: 'analysis',
      source_report_id: 3001,
      trace_id: 'trace-3001',
      market_phase: 'intraday',
      trigger_source: 'api',
      action: 'watch',
      action_label: '观察',
      confidence: 0.72,
      score: 76,
      horizon: '3d',
      entry_low: 1680,
      entry_high: 1720,
      stop_loss: 1600,
      target_price: 1850,
      invalidation: '跌破支撑',
      watch_conditions: '放量突破',
      reason: '趋势改善',
      risk_summary: '波动较高',
      catalyst_summary: '行业修复',
      evidence: { sourceUrl: 'https://example.com/news' },
      data_quality_summary: { level: 'usable' },
      plan_quality: 'complete',
      status: 'active',
      expires_at: '2026-06-12T08:00:00',
      metadata: { taskId: 'task-1' },
      report_language: 'zh',
    });
    expect(response.created).toBe(false);
    expect(response.item.id).toBe(11);
    expect(response.item.sourceReportId).toBe(3001);
    expect(response.item.entryLow).toBe(1680);
    expect(response.item.evidence).toEqual({ source_url: 'https://example.com/news' });
    expect(response.item.dataQualitySummary).toEqual({ raw_score: 80, level: 'usable' });
    expect(response.item.metadata).toEqual({ task_id: 'task-1' });
  });

  it('lists signals with snake_case query params', async () => {
    get.mockResolvedValueOnce({
      data: {
        items: [
          {
            id: 12,
            stock_code: 'HK00700',
            market: 'hk',
            source_type: 'manual',
            trigger_source: 'web',
            action: 'hold',
            plan_quality: 'minimal',
            status: 'active',
          },
        ],
        total: 1,
        page: 2,
        page_size: 10,
      },
    });

    const response = await decisionSignalsApi.list({
      market: 'hk',
      stockCode: '00700',
      action: 'hold',
      marketPhase: 'postmarket',
      sourceType: 'manual',
      sourceReportId: 99,
      traceId: 'trace-99',
      triggerSource: 'web',
      status: 'active',
      createdFrom: '2026-06-01T00:00:00',
      createdTo: '2026-06-11T00:00:00',
      expiresFrom: '2026-06-12T00:00:00',
      expiresTo: '2026-06-30T00:00:00',
      holdingOnly: true,
      accountId: 3,
      page: 2,
      pageSize: 10,
    });

    expect(get).toHaveBeenCalledWith('/api/v1/decision-signals', {
      params: {
        market: 'hk',
        stock_code: '00700',
        action: 'hold',
        market_phase: 'postmarket',
        source_type: 'manual',
        source_report_id: 99,
        trace_id: 'trace-99',
        trigger_source: 'web',
        status: 'active',
        created_from: '2026-06-01T00:00:00',
        created_to: '2026-06-11T00:00:00',
        expires_from: '2026-06-12T00:00:00',
        expires_to: '2026-06-30T00:00:00',
        holding_only: true,
        account_id: 3,
        page: 2,
        page_size: 10,
      },
    });
    expect(response.pageSize).toBe(10);
    expect(response.items[0].stockCode).toBe('HK00700');
  });

  it('rejects malformed list responses instead of treating missing items as empty', async () => {
    get.mockResolvedValueOnce({
      data: {
        total: 0,
        page: 1,
        page_size: 20,
      },
    });

    await expect(decisionSignalsApi.list()).rejects.toThrow(
      'DecisionSignal list response items must be an array',
    );
  });

  it('gets latest signals with a backend-supported stock code path', async () => {
    get.mockResolvedValueOnce({
      data: {
        items: [],
        total: 0,
        page: 1,
        page_size: 2,
      },
    });

    const response = await decisionSignalsApi.getLatest('00700.HK', { market: 'hk', limit: 2 });

    expect(get).toHaveBeenCalledWith('/api/v1/decision-signals/latest/00700.HK', {
      params: { market: 'hk', limit: 2 },
    });
    expect(response.pageSize).toBe(2);
  });

  it('rejects slash-containing latest stock codes before calling an unsupported backend path', async () => {
    await expect(decisionSignalsApi.getLatest('HK/00700', { market: 'hk' })).rejects.toThrow(
      'DecisionSignal latest stockCode cannot contain "/"',
    );
    expect(get).not.toHaveBeenCalled();
  });

  it('gets one signal and updates status metadata as a full replacement payload', async () => {
    get.mockResolvedValueOnce({
      data: {
        id: 13,
        stock_code: 'AAPL',
        market: 'us',
        source_type: 'agent',
        trigger_source: 'api',
        action: 'reduce',
        plan_quality: 'partial',
        status: 'active',
      },
    });
    patch.mockResolvedValueOnce({
      data: {
        id: 13,
        stock_code: 'AAPL',
        market: 'us',
        source_type: 'agent',
        trigger_source: 'api',
        action: 'reduce',
        plan_quality: 'partial',
        status: 'closed',
        metadata: { closed_by: 'tester' },
      },
    });

    const item = await decisionSignalsApi.get(13);
    const updated = await decisionSignalsApi.updateStatus(13, {
      status: 'closed',
      metadata: { closedBy: 'tester' },
    });

    expect(get).toHaveBeenCalledWith('/api/v1/decision-signals/13');
    expect(patch).toHaveBeenCalledWith('/api/v1/decision-signals/13/status', {
      status: 'closed',
      metadata: { closedBy: 'tester' },
    });
    expect(item.stockCode).toBe('AAPL');
    expect(updated.status).toBe('closed');
    expect(updated.metadata).toEqual({ closed_by: 'tester' });
  });

  it('passes API client errors through unchanged', async () => {
    const error = new Error('network failed');
    get.mockRejectedValueOnce(error);

    await expect(decisionSignalsApi.list()).rejects.toBe(error);
  });
});
