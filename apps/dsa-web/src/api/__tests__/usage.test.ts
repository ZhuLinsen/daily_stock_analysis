import { beforeEach, describe, expect, it, vi } from 'vitest';
import { usageApi } from '../usage';

const get = vi.hoisted(() => vi.fn());

vi.mock('../index', () => ({
  default: { get },
}));

describe('usageApi', () => {
  beforeEach(() => {
    get.mockReset();
  });

  it('requests dashboard data with period and limit query params and camelCases the response', async () => {
    get.mockResolvedValueOnce({
      data: {
        period: 'today',
        from_date: '2026-06-14',
        to_date: '2026-06-14',
        total_calls: 2,
        total_prompt_tokens: 30,
        total_completion_tokens: 70,
        total_tokens: 100,
        by_call_type: [
          {
            call_type: 'analysis',
            calls: 1,
            prompt_tokens: 10,
            completion_tokens: 40,
            total_tokens: 50,
          },
        ],
        by_model: [
          {
            model: 'minimax/MiniMax-M3',
            calls: 1,
            prompt_tokens: 10,
            completion_tokens: 40,
            total_tokens: 50,
            max_total_tokens: 50,
          },
        ],
        recent_calls: [
          {
            id: 7,
            called_at: '2026-06-14T09:30:00',
            call_type: 'analysis',
            model: 'minimax/MiniMax-M3',
            stock_code: '600519',
            prompt_tokens: 10,
            completion_tokens: 40,
            total_tokens: 50,
          },
        ],
      },
    });

    const result = await usageApi.getDashboard({ period: 'today', limit: 10 });

    expect(get).toHaveBeenCalledWith('/api/v1/usage/dashboard', {
      params: { period: 'today', limit: 10 },
    });
    expect(result.fromDate).toBe('2026-06-14');
    expect(result.totalPromptTokens).toBe(30);
    expect(result.byCallType[0].callType).toBe('analysis');
    expect(result.byModel[0].maxTotalTokens).toBe(50);
    expect(result.recentCalls[0].calledAt).toBe('2026-06-14T09:30:00');
    expect(result.recentCalls[0].stockCode).toBe('600519');
  });

  it('uses month and 50 as default dashboard query params', async () => {
    get.mockResolvedValueOnce({
      data: {
        period: 'month',
        from_date: '2026-06-01',
        to_date: '2026-06-14',
        total_calls: 0,
        total_prompt_tokens: 0,
        total_completion_tokens: 0,
        total_tokens: 0,
        by_call_type: [],
        by_model: [],
        recent_calls: [],
      },
    });

    await usageApi.getDashboard();

    expect(get).toHaveBeenCalledWith('/api/v1/usage/dashboard', {
      params: { period: 'month', limit: 50 },
    });
  });
});
