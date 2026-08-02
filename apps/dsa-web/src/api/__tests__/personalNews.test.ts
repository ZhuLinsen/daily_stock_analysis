import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get, post, remove } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  remove: vi.fn(),
}));

vi.mock('../index', () => ({
  default: { get, post, delete: remove },
}));

import { personalNewsApi } from '../personalNews';

describe('personalNewsApi', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    remove.mockReset();
    get.mockResolvedValue({ data: [] });
    post.mockResolvedValue({ data: {} });
    remove.mockResolvedValue({ data: [] });
  });

  it('uses the versioned API prefix for reads', async () => {
    await personalNewsApi.list();
    await personalNewsApi.providers();
    await personalNewsApi.watchlist();
    await personalNewsApi.refreshStatus();

    expect(get).toHaveBeenNthCalledWith(1, '/api/v1/personal-news', { params: { limit: 100 } });
    expect(get).toHaveBeenNthCalledWith(2, '/api/v1/personal-news/providers');
    expect(get).toHaveBeenNthCalledWith(3, '/api/v1/personal-news/watchlist');
    expect(get).toHaveBeenNthCalledWith(4, '/api/v1/personal-news/refresh/status');
  });

  it('uses the versioned API prefix for mutations', async () => {
    await personalNewsApi.addWatchlist('600519');
    await personalNewsApi.refresh('manual');
    await personalNewsApi.deleteWatchlist('00700.HK');

    expect(post).toHaveBeenNthCalledWith(1, '/api/v1/personal-news/watchlist', { symbols: '600519' });
    expect(post).toHaveBeenNthCalledWith(2, '/api/v1/personal-news/refresh', { trigger: 'manual' });
    expect(remove).toHaveBeenCalledWith('/api/v1/personal-news/watchlist/00700.HK');
  });
});
