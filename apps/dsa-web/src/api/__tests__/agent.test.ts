import { beforeEach, describe, expect, it, vi } from 'vitest';
import { agentApi } from '../agent';

const get = vi.hoisted(() => vi.fn());

vi.mock('../index', () => ({
  default: {
    get,
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

describe('agentApi', () => {
  beforeEach(() => {
    get.mockReset();
  });

  it('uses the shared camelCase Agent backend status contract', async () => {
    get.mockResolvedValueOnce({
      data: {
        backend: 'codex_app_server',
        available: false,
        experimental: true,
        version: '0.144.3',
        error_code: 'login_required',
        message: 'Codex login is required',
      },
    });

    const result = await agentApi.getStatus();

    expect(get).toHaveBeenCalledWith('/api/v1/agent/status');
    expect(result).toEqual({
      backend: 'codex_app_server',
      available: false,
      experimental: true,
      version: '0.144.3',
      errorCode: 'login_required',
      message: 'Codex login is required',
    });
  });
});
