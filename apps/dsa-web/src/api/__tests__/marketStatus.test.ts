import { beforeEach, describe, expect, it, vi } from 'vitest';
import { marketStatusApi } from '../marketStatus';

const get = vi.hoisted(() => vi.fn());

vi.mock('../index', () => ({
  default: { get },
}));

describe('marketStatusApi', () => {
  beforeEach(() => get.mockReset());

  it('maps the backend market clock payload to camel case', async () => {
    get.mockResolvedValueOnce({
      data: {
        generated_at: '2026-08-14T12:00:00+00:00',
        markets: [{
          market: 'us',
          phase: 'premarket',
          market_local_time: '2026-08-14T08:00:00-04:00',
          is_trading_day: true,
          is_market_open_now: false,
          minutes_to_open: 90,
          minutes_to_close: null,
          next_session_open: '2026-08-14T09:30:00-04:00',
          warnings: [],
        }],
      },
    });

    const result = await marketStatusApi.getStatus();

    expect(get).toHaveBeenCalledWith('/api/v1/market/status');
    expect(result.generatedAt).toBe('2026-08-14T12:00:00+00:00');
    expect(result.markets[0]).toMatchObject({
      marketLocalTime: '2026-08-14T08:00:00-04:00',
      minutesToOpen: 90,
      nextSessionOpen: '2026-08-14T09:30:00-04:00',
    });
  });
});
