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
        backend: 'litellm',
        available: false,
        experimental: false,
        version: null,
        error_code: 'capability_unsupported',
        message: 'no_agent_primary',
      },
    });

    const result = await agentApi.getStatus();

    expect(get).toHaveBeenCalledWith('/api/v1/agent/status');
    expect(result).toEqual({
      backend: 'litellm',
      available: false,
      experimental: false,
      version: null,
      errorCode: 'capability_unsupported',
      message: 'no_agent_primary',
    });
  });

  it('returns session messages together with persisted Skill state', async () => {
    get.mockResolvedValueOnce({
      data: {
        session_id: 'session-1',
        messages: [
          { id: '1', role: 'user', content: '分析 AAPL', created_at: null },
        ],
        session_state: {
          selected_skill_ids: ['technical', 'risk'],
        },
      },
    });

    const result = await agentApi.getChatSessionMessages('session-1');

    expect(get).toHaveBeenCalledWith('/api/v1/agent/chat/sessions/session-1');
    expect(result.session_state.selected_skill_ids).toEqual(['technical', 'risk']);
  });

  it('preserves null when a legacy session has no persisted Skill state', async () => {
    get.mockResolvedValueOnce({
      data: {
        session_id: 'legacy-session',
        messages: [
          { id: '1', role: 'user', content: '继续分析', created_at: null },
        ],
        session_state: {
          selected_skill_ids: null,
        },
      },
    });

    const result = await agentApi.getChatSessionMessages('legacy-session');

    expect(result.session_state.selected_skill_ids).toBeNull();
  });
});
