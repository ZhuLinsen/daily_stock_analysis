import { describe, expect, it } from 'vitest';
import type { RunFlowSnapshot } from '../../../types/runFlow';
import { buildRunFlowTopologyModel } from '../topologyViewModel';

const baseSnapshot: RunFlowSnapshot = {
  taskId: 'task-1',
  traceId: 'trace-1',
  stockCode: '600519',
  status: 'fallback',
  generatedAt: '2026-06-08T10:00:20',
  summary: {
    failedAttempts: 1,
    fallbackCount: 1,
    dataSourceCount: 2,
    eventCount: 3,
  },
  lanes: [
    { id: 'entry', label: '入口', order: 1 },
    { id: 'data_source', label: '数据来源', order: 2 },
    { id: 'analysis', label: '分析引擎', order: 3 },
  ],
  nodes: [
    {
      id: 'task_queue',
      lane: 'entry',
      kind: 'queue',
      label: '任务队列',
      status: 'success',
    },
    {
      id: 'provider_news_search_tavily_1',
      lane: 'data_source',
      kind: 'data_source',
      label: '新闻舆情 · Tavily',
      status: 'failed',
      provider: 'Tavily',
      startedAt: '2026-06-08T10:00:01',
      endedAt: '2026-06-08T10:00:02',
      durationMs: 1000,
      metadata: { data_type: 'news_search', attempt: 1 },
    },
    {
      id: 'provider_news_search_searxng_2',
      lane: 'data_source',
      kind: 'data_source',
      label: '新闻舆情 · SearXNG',
      status: 'success',
      provider: 'SearXNG',
      startedAt: '2026-06-08T10:00:03',
      endedAt: '2026-06-08T10:00:04',
      durationMs: 1000,
      recordCount: 6,
      metadata: { data_type: 'news_search', attempt: 2 },
    },
    {
      id: 'context_block_news',
      lane: 'data_source',
      kind: 'data_source',
      label: '新闻',
      status: 'success',
      recordCount: 6,
      metadata: { block_key: 'news' },
    },
    {
      id: 'context_block_fundamental',
      lane: 'data_source',
      kind: 'data_source',
      label: '基本面',
      status: 'degraded',
      metadata: { block_key: 'fundamental' },
    },
    {
      id: 'context_pack',
      lane: 'analysis',
      kind: 'analysis',
      label: 'ContextPack',
      status: 'degraded',
    },
  ],
  edges: [
    {
      id: 'queue-news-1',
      from: 'task_queue',
      to: 'provider_news_search_tavily_1',
      kind: 'control',
      status: 'failed',
    },
    {
      id: 'news-1-news-2',
      from: 'provider_news_search_tavily_1',
      to: 'provider_news_search_searxng_2',
      kind: 'fallback',
      status: 'success',
    },
    {
      id: 'news-2-block',
      from: 'provider_news_search_searxng_2',
      to: 'context_block_news',
      kind: 'data',
      status: 'success',
    },
    {
      id: 'block-pack',
      from: 'context_block_news',
      to: 'context_pack',
      kind: 'data',
      status: 'success',
    },
  ],
  events: [
    {
      id: 'evt-news-1',
      timestamp: '2026-06-08T10:00:02',
      severity: 'warning',
      type: 'provider_run',
      nodeId: 'provider_news_search_tavily_1',
      title: '新闻舆情失败',
    },
    {
      id: 'evt-block',
      timestamp: '2026-06-08T10:00:05',
      severity: 'warning',
      type: 'context_block_status',
      nodeId: 'context_block_fundamental',
      title: '基本面输入状态',
    },
  ],
};

describe('buildRunFlowTopologyModel', () => {
  it('collapses provider attempts into data-source topology groups', () => {
    const model = buildRunFlowTopologyModel(baseSnapshot);

    expect(model.nodes.map((node) => node.id)).not.toContain('provider_news_search_tavily_1');
    expect(model.nodes.map((node) => node.id)).not.toContain('provider_news_search_searxng_2');

    const newsGroup = model.nodes.find((node) => node.id === 'topology_data_news_search');
    expect(newsGroup).toMatchObject({
      label: '新闻舆情',
      status: 'fallback',
      provider: 'Tavily -> SearXNG',
      attempts: 2,
      recordCount: 6,
    });
    expect(newsGroup?.metadata).toMatchObject({
      topologyGroup: 'provider_attempts',
      data_type: 'news_search',
      success_count: 1,
      failed_count: 1,
      fallback_count: 1,
    });
  });

  it('honors API-normalized camelCase metadata when grouping topology nodes', () => {
    const snapshot: RunFlowSnapshot = {
      ...baseSnapshot,
      nodes: [
        baseSnapshot.nodes[0],
        {
          id: 'provider_compatible_alpha_1',
          lane: 'data_source',
          kind: 'data_source',
          label: '兼容行情 · Alpha',
          status: 'failed',
          provider: 'Alpha',
          metadata: { dataType: 'compatible_live_quote', attempt: 1 },
        },
        {
          id: 'provider_compatible_beta_2',
          lane: 'data_source',
          kind: 'data_source',
          label: '兼容行情 · Beta',
          status: 'success',
          provider: 'Beta',
          metadata: { dataType: 'compatible_live_quote', attempt: 2 },
        },
        {
          id: 'api_normalized_context_news',
          lane: 'data_source',
          kind: 'data_source',
          label: '新闻',
          status: 'success',
          recordCount: 3,
          metadata: { blockKey: 'news' },
        },
        {
          id: 'context_pack',
          lane: 'analysis',
          kind: 'analysis',
          label: 'ContextPack',
          status: 'success',
        },
      ],
      edges: [
        {
          id: 'compatible-1-compatible-2',
          from: 'provider_compatible_alpha_1',
          to: 'provider_compatible_beta_2',
          kind: 'fallback',
          status: 'success',
        },
        {
          id: 'normalized-block-pack',
          from: 'api_normalized_context_news',
          to: 'context_pack',
          kind: 'data',
          status: 'success',
        },
      ],
      events: [
        {
          id: 'evt-compatible',
          timestamp: '2026-06-08T10:00:02',
          severity: 'warning',
          type: 'provider_run',
          nodeId: 'provider_compatible_alpha_1',
          title: '兼容行情失败',
        },
        {
          id: 'evt-normalized-block',
          timestamp: '2026-06-08T10:00:05',
          severity: 'success',
          type: 'context_block_status',
          nodeId: 'api_normalized_context_news',
          title: '新闻输入状态',
        },
      ],
    };

    const model = buildRunFlowTopologyModel(snapshot);

    expect(model.nodes.map((node) => node.id)).toContain('topology_data_compatible_live_quote');
    expect(model.nodes.map((node) => node.id)).not.toContain('topology_data_compatible');
    expect(model.nodes.map((node) => node.id)).not.toContain('api_normalized_context_news');
    expect(model.nodes.find((node) => node.id === 'topology_data_compatible_live_quote')).toMatchObject({
      provider: 'Alpha -> Beta',
      attempts: 2,
    });
    expect(model.nodes.find((node) => node.id === 'context_pack')?.metadata).toMatchObject({
      topologyGroup: 'context_pack',
      context_status_counts: {
        success: 1,
      },
    });
    expect(model.events.find((event) => event.id === 'evt-compatible')?.nodeId).toBe('topology_data_compatible_live_quote');
    expect(model.events.find((event) => event.id === 'evt-normalized-block')?.nodeId).toBe('context_pack');
  });

  it('attaches context block states to ContextPack and remaps events', () => {
    const model = buildRunFlowTopologyModel(baseSnapshot);
    const contextPack = model.nodes.find((node) => node.id === 'context_pack');

    expect(model.nodes.map((node) => node.id)).not.toContain('context_block_news');
    expect(contextPack?.metadata).toMatchObject({
      topologyGroup: 'context_pack',
      context_status_counts: {
        success: 1,
        degraded: 1,
      },
    });
    expect(model.events.find((event) => event.id === 'evt-news-1')?.nodeId).toBe('topology_data_news_search');
    expect(model.events.find((event) => event.id === 'evt-block')?.nodeId).toBe('context_pack');
  });

  it('restores provider attempt nodes when a topology group is expanded', () => {
    const model = buildRunFlowTopologyModel(baseSnapshot, {
      expandedGroupIds: new Set(['topology_data_news_search']),
    });

    expect(model.nodes.map((node) => node.id)).toContain('topology_data_news_search');
    expect(model.nodes.map((node) => node.id)).toContain('provider_news_search_tavily_1');
    expect(model.nodes.map((node) => node.id)).toContain('provider_news_search_searxng_2');
    expect(model.edges).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          from: 'topology_data_news_search',
          to: 'provider_news_search_tavily_1',
        }),
        expect.objectContaining({
          from: 'provider_news_search_tavily_1',
          to: 'provider_news_search_searxng_2',
          kind: 'fallback',
        }),
      ]),
    );
    expect(model.events.find((event) => event.id === 'evt-news-1')?.nodeId).toBe('provider_news_search_tavily_1');
  });
});
