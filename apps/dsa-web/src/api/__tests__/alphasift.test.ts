import { beforeEach, describe, expect, it, vi } from 'vitest';
import { alphasiftApi } from '../alphasift';

const { get, post, getConfig, updateConfig } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  getConfig: vi.fn(),
  updateConfig: vi.fn(),
}));

vi.mock('../index', () => ({
  default: {
    get,
    post,
  },
}));

vi.mock('../systemConfig', () => ({
  systemConfigApi: {
    getConfig: (...args: unknown[]) => getConfig(...args),
    update: (...args: unknown[]) => updateConfig(...args),
  },
}));

describe('alphasiftApi', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    getConfig.mockReset();
    updateConfig.mockReset();
  });

  it('enables the config and checks bundled AlphaSift availability', async () => {
    getConfig.mockResolvedValueOnce({ configVersion: 'v1', maskToken: '******' });
    updateConfig.mockResolvedValueOnce({ success: true });
    get.mockResolvedValueOnce({
      data: {
        enabled: true,
        available: true,
        install_spec_is_default: true,
      },
    });

    await alphasiftApi.enable();

    expect(updateConfig).toHaveBeenCalledWith({
      configVersion: 'v1',
      maskToken: '******',
      reloadNow: true,
      items: [{ key: 'ALPHASIFT_ENABLED', value: 'true' }],
    });
    expect(get).toHaveBeenCalledWith('/api/v1/alphasift/status');
    expect(updateConfig).toHaveBeenCalledTimes(1);
    expect(post).not.toHaveBeenCalled();
  });

  it('keeps enable behavior when called without object binding', async () => {
    getConfig.mockResolvedValueOnce({ configVersion: 'v1', maskToken: '******' });
    updateConfig.mockResolvedValueOnce({ success: true });
    get.mockResolvedValueOnce({
      data: {
        enabled: true,
        available: true,
        install_spec_is_default: true,
      },
    });

    const enable = alphasiftApi.enable;
    await enable();

    expect(updateConfig).toHaveBeenCalledTimes(1);
    expect(post).not.toHaveBeenCalled();
  });

  it('rolls back ALPHASIFT_ENABLED when bundled AlphaSift is unavailable', async () => {
    getConfig
      .mockResolvedValueOnce({ configVersion: 'v1', maskToken: '******' })
      .mockResolvedValueOnce({ configVersion: 'v2', maskToken: '******' });
    updateConfig.mockResolvedValue({ success: true });
    get.mockResolvedValueOnce({
      data: {
        enabled: true,
        available: false,
        install_spec_is_default: true,
        diagnostics: { reason: 'missing_module' },
      },
    });

    await expect(alphasiftApi.enable()).rejects.toThrow('pip install -r requirements.txt');

    expect(updateConfig).toHaveBeenNthCalledWith(1, {
      configVersion: 'v1',
      maskToken: '******',
      reloadNow: true,
      items: [{ key: 'ALPHASIFT_ENABLED', value: 'true' }],
    });
    expect(updateConfig).toHaveBeenNthCalledWith(2, {
      configVersion: 'v2',
      maskToken: '******',
      reloadNow: true,
      items: [{ key: 'ALPHASIFT_ENABLED', value: 'false' }],
    });
    expect(post).not.toHaveBeenCalled();
  });

  it('loads strategies from the AlphaSift API', async () => {
    get.mockResolvedValueOnce({
      data: {
        enabled: true,
        strategies: [
          {
            id: 'dual_low',
            name: 'Dual Low',
            description: 'value',
            category: 'value',
            market_scope: ['cn'],
          },
        ],
        strategy_count: 1,
      },
    });

    const result = await alphasiftApi.getStrategies();

    expect(get).toHaveBeenCalledWith('/api/v1/alphasift/strategies', { timeout: 300000 });
    expect(result.enabled).toBe(true);
    expect(result.strategyCount).toBe(1);
    expect(result.strategies[0].id).toBe('dual_low');
    expect(result.strategies[0].marketScope).toEqual(['cn']);
  });

  it('loads hotspot themes from the AlphaSift API', async () => {
    get.mockResolvedValueOnce({
      data: {
        enabled: true,
        provider: 'akshare',
        provider_used: 'akshare',
        hotspots: [
          {
            topic: 'AI算力',
            heat_score: 88,
            trend_score: 12,
            sample_stock_count: 8,
            leaders: ['中际旭创'],
          },
        ],
        hotspot_count: 1,
        details: {
          AI绠楀姏: {
            enabled: true,
            provider: 'akshare',
            topic: 'AI绠楀姏',
            route: [{ title: '盘中发酵', description: '事件摘要' }],
            stocks: [],
            stock_count: 0,
          },
        },
      },
    });

    const result = await alphasiftApi.getHotspots({ provider: 'akshare', top: 12, refresh: true });

    expect(get).toHaveBeenCalledWith('/api/v1/alphasift/hotspots', {
      params: { provider: 'akshare', top: 12, refresh: true, include_details: true },
      timeout: 300000,
    });
    expect(result.providerUsed).toBe('akshare');
    expect(result.hotspots[0].heatScore).toBe(88);
    expect(result.hotspots[0].sampleStockCount).toBe(8);
    expect(Object.values(result.details || {})[0]?.stockCount).toBe(0);
  });

  it('keeps prefetched hotspot details addressable by the original topic', async () => {
    get.mockResolvedValueOnce({
      data: {
        enabled: true,
        provider: 'akshare',
        provider_used: 'akshare',
        hotspots: [{ topic: 'Moly Theme', heat_score: 96 }],
        hotspot_count: 1,
        details: {
          moly_theme: {
            enabled: true,
            provider: 'akshare',
            topic: 'Moly Theme',
            route: [{ title: 'catalyst', description: 'summary' }],
            stocks: [],
            stock_count: 0,
          },
        },
      },
    });

    const result = await alphasiftApi.getHotspots({ provider: 'akshare', top: 12, refresh: false });

    expect(result.details?.['Moly Theme']?.stockCount).toBe(0);
  });

  it('loads hotspot detail for a concrete topic', async () => {
    get.mockResolvedValueOnce({
      data: {
        enabled: true,
        provider: 'akshare',
        topic: '玻璃基板',
        summary: '玻璃基板盘中发酵',
        route: [{ title: '盘中发酵', description: '出现大笔买入' }],
        stocks: [{ code: '920438', name: '戈碧迦', role: '异动核心' }],
        stock_count: 1,
      },
    });

    const result = await alphasiftApi.getHotspotDetail({ topic: '玻璃基板', provider: 'akshare' });

    expect(get).toHaveBeenCalledWith('/api/v1/alphasift/hotspots/%E7%8E%BB%E7%92%83%E5%9F%BA%E6%9D%BF', {
      params: { provider: 'akshare', refresh: false },
      timeout: 300000,
    });
    expect(result.topic).toBe('玻璃基板');
    expect(result.stockCount).toBe(1);
    expect(result.stocks[0].name).toBe('戈碧迦');
  });

  it('uses a long timeout for LLM-backed screening', async () => {
    post.mockResolvedValueOnce({
      data: {
        enabled: true,
        candidates: [],
        candidate_count: 0,
        llm_ranked: true,
      },
    });

    await alphasiftApi.screen({ market: 'cn', strategy: 'dual_low', maxResults: 3 });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/alphasift/screen',
      { market: 'cn', strategy: 'dual_low', max_results: 3 },
      { timeout: 180000 }
    );
  });

  it('starts an async screening task', async () => {
    post.mockResolvedValueOnce({
      data: {
        task_id: 'screen-task-1',
        trace_id: 'screen-task-1',
        status: 'pending',
        message: 'AlphaSift 选股任务已提交',
        strategy: 'dual_low',
        market: 'cn',
        max_results: 3,
      },
    });

    const result = await alphasiftApi.startScreen({ market: 'cn', strategy: 'dual_low', maxResults: 3 });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/alphasift/screen/tasks',
      { market: 'cn', strategy: 'dual_low', max_results: 3 }
    );
    expect(result.taskId).toBe('screen-task-1');
    expect(result.maxResults).toBe(3);
  });

  it('loads async screening task status', async () => {
    get.mockResolvedValueOnce({
      data: {
        task_id: 'screen-task-1',
        trace_id: 'screen-task-1',
        status: 'completed',
        progress: 100,
        message: '任务执行完成',
        result: {
          enabled: true,
          candidates: [],
          candidate_count: 0,
          daily_enriched: true,
          daily_enrich_count: 4,
          post_analyzers: ['scorecard'],
        },
      },
    });

    const result = await alphasiftApi.getScreenTask('screen-task-1');

    expect(get).toHaveBeenCalledWith('/api/v1/alphasift/screen/tasks/screen-task-1');
    expect(result.taskId).toBe('screen-task-1');
    expect(result.result?.candidateCount).toBe(0);
    expect(result.result?.dailyEnriched).toBe(true);
    expect(result.result?.dailyEnrichCount).toBe(4);
    expect(result.result?.postAnalyzers).toEqual(['scorecard']);
  });
});
