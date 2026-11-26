import { beforeEach, describe, expect, it, vi } from 'vitest';
import { analysisApi } from '../analysis';

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock('../index', () => ({
  default: {
    get,
    post,
  },
}));

describe('analysisApi.triggerMarketReview', () => {
  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({
      status: 202,
      data: {
        status: 'accepted',
        message: 'accepted',
        send_notification: true,
        region: 'cn,us',
        task_id: 'market-task-1',
      },
    });
  });

  it('serializes selected markets to a comma-separated request string', async () => {
    const result = await analysisApi.triggerMarketReview({
      sendNotification: false,
      regions: ['cn', 'us'],
    });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/analysis/market-review',
      {
        send_notification: false,
        report_language: undefined,
        region: 'cn,us',
      },
      expect.any(Object),
    );
    expect(result.region).toBe('cn,us');
  });

  it('omits region when the caller inherits the server default', async () => {
    await analysisApi.triggerMarketReview({ sendNotification: true });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/analysis/market-review',
      {
        send_notification: true,
        report_language: undefined,
      },
      expect.any(Object),
    );
  });
});

it('serializes the selected ChatGPT model in both analysis entry points', async () => {
  const modelSource = { provider: 'chatgpt_siwc', connection_id: 'local', model: 'selected' } as const;
  post.mockReset();
  post.mockResolvedValue({ status: 202, data: { status: 'accepted', task_id: 'task' } });
  const request = { stockCode: '600519', notify: false, modelSource };
  await analysisApi.analyze(request);
  await analysisApi.analyzeAsync(request);
  expect(post.mock.calls.map((call) => call[1])).toEqual([
    expect.objectContaining({ model_source: modelSource, notify: false, async_mode: false }),
    expect.objectContaining({ model_source: modelSource, notify: false, async_mode: true }),
  ]);
});

it('returns a ChatGPT analysis failure without reading connection status', async () => {
  const failure = new Error('Analysis failed');
  get.mockReset();
  post.mockRejectedValueOnce(failure);

  await expect(analysisApi.analyze({
    stockCode: '600519',
    modelSource: { provider: 'chatgpt_siwc', connection_id: 'local', model: 'selected' },
  })).rejects.toBe(failure);
  expect(get).not.toHaveBeenCalled();
});
