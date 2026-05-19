import { beforeEach, describe, expect, it, vi } from 'vitest';
import { alertsApi } from '../alerts';

const { get, post, deleteRequest } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  deleteRequest: vi.fn(),
}));

vi.mock('../index', () => ({
  default: {
    get,
    post,
    delete: deleteRequest,
  },
}));

describe('alertsApi', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    deleteRequest.mockReset();
  });

  it('lists rules with snake_case query params and camelCase response fields', async () => {
    get.mockResolvedValueOnce({
      data: {
        items: [
          {
            id: 1,
            name: 'price rule',
            target_scope: 'single_symbol',
            target: '600519',
            alert_type: 'price_cross',
            parameters: { direction: 'above', price: 1800 },
            severity: 'warning',
            enabled: true,
            source: 'api',
            last_triggered_at: '2026-05-18T09:05:00',
            cooldown_until: '2026-05-18T10:05:00',
            cooldown_active: true,
            created_at: '2026-05-18T09:00:00',
            updated_at: '2026-05-18T09:10:00',
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      },
    });

    const result = await alertsApi.listRules({
      enabled: true,
      alertType: 'price_cross',
      targetScope: 'single_symbol',
      page: 1,
      pageSize: 20,
    });

    expect(get).toHaveBeenCalledWith('/api/v1/alerts/rules', {
      params: {
        enabled: true,
        alert_type: 'price_cross',
        target_scope: 'single_symbol',
        page: 1,
        page_size: 20,
      },
    });
    expect(result.pageSize).toBe(20);
    expect(result.items[0].targetScope).toBe('single_symbol');
    expect(result.items[0].alertType).toBe('price_cross');
    expect(result.items[0].cooldownUntil).toBe('2026-05-18T10:05:00');
    expect(result.items[0].cooldownActive).toBe(true);
    expect(result.items[0].updatedAt).toBe('2026-05-18T09:10:00');
  });

  it('creates rules with snake_case payload fields', async () => {
    post.mockResolvedValueOnce({
      data: {
        id: 2,
        name: 'change rule',
        target_scope: 'single_symbol',
        target: 'AAPL',
        alert_type: 'price_change_percent',
        parameters: { direction: 'down', change_pct: 3 },
        severity: 'critical',
        enabled: true,
        source: 'api',
      },
    });

    const created = await alertsApi.createRule({
      name: 'change rule',
      targetScope: 'single_symbol',
      target: 'AAPL',
      alertType: 'price_change_percent',
      parameters: { direction: 'down', changePct: 3 },
      severity: 'critical',
      enabled: true,
    });

    expect(post).toHaveBeenCalledWith('/api/v1/alerts/rules', {
      name: 'change rule',
      target_scope: 'single_symbol',
      target: 'AAPL',
      alert_type: 'price_change_percent',
      parameters: { direction: 'down', change_pct: 3 },
      severity: 'critical',
      enabled: true,
    });
    expect(created.parameters.changePct).toBe(3);
  });

  it('deletes, toggles, tests, and lists history endpoints', async () => {
    deleteRequest.mockResolvedValueOnce({ data: { deleted: 1 } });
    post
      .mockResolvedValueOnce({ data: { id: 3, name: 'enabled', target_scope: 'single_symbol', target: 'MSFT', alert_type: 'volume_spike', parameters: { multiplier: 2 }, severity: 'warning', enabled: true, source: 'api' } })
      .mockResolvedValueOnce({ data: { id: 3, name: 'disabled', target_scope: 'single_symbol', target: 'MSFT', alert_type: 'volume_spike', parameters: { multiplier: 2 }, severity: 'warning', enabled: false, source: 'api' } })
      .mockResolvedValueOnce({ data: { rule_id: 3, status: 'not_triggered', triggered: false, observed_value: 1.2, message: 'not triggered' } });
    get
      .mockResolvedValueOnce({ data: { items: [{ id: 10, rule_id: 3, target: 'MSFT', status: 'skipped', observed_value: null, triggered_at: '2026-05-18T10:00:00' }], total: 1, page: 1, page_size: 20 } })
      .mockResolvedValueOnce({ data: { items: [{ id: 11, trigger_id: 10, channel: 'wechat', attempt: 1, success: false, retryable: true, error_code: 'timeout', latency_ms: null }], total: 1, page: 1, page_size: 20 } });

    await expect(alertsApi.deleteRule(3)).resolves.toEqual({ deleted: 1 });
    await alertsApi.enableRule(3);
    await alertsApi.disableRule(3);
    const testResult = await alertsApi.testRule(3);
    const triggers = await alertsApi.listTriggers({ ruleId: 3, status: 'skipped', page: 1, pageSize: 20 });
    const notifications = await alertsApi.listNotifications({ triggerId: 10, success: false, page: 1, pageSize: 20 });

    expect(deleteRequest).toHaveBeenCalledWith('/api/v1/alerts/rules/3');
    expect(post).toHaveBeenNthCalledWith(1, '/api/v1/alerts/rules/3/enable');
    expect(post).toHaveBeenNthCalledWith(2, '/api/v1/alerts/rules/3/disable');
    expect(post).toHaveBeenNthCalledWith(3, '/api/v1/alerts/rules/3/test');
    expect(testResult.ruleId).toBe(3);
    expect(testResult.observedValue).toBe(1.2);
    expect(get).toHaveBeenNthCalledWith(1, '/api/v1/alerts/triggers', {
      params: { rule_id: 3, status: 'skipped', page: 1, page_size: 20 },
    });
    expect(get).toHaveBeenNthCalledWith(2, '/api/v1/alerts/notifications', {
      params: { trigger_id: 10, success: false, page: 1, page_size: 20 },
    });
    expect(triggers.items[0].ruleId).toBe(3);
    expect(notifications.items[0].triggerId).toBe(10);
    expect(notifications.items[0].errorCode).toBe('timeout');
  });
});
