import { beforeEach, describe, expect, it, vi } from 'vitest';
import { agentApi, decodeChatState } from '../agent';
import { parseApiError } from '../error';

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
        experimental: false,
        version: null,
        error_code: 'backend_removed',
        message: 'Codex App Server has been removed',
      },
    });

    const result = await agentApi.getStatus();

    expect(get).toHaveBeenCalledWith('/api/v1/agent/status');
    expect(result).toEqual({
      backend: 'codex_app_server',
      available: false,
      experimental: false,
      version: null,
      errorCode: 'backend_removed',
      message: 'Codex App Server has been removed',
    });
  });

  it('preserves the retirement code from the real HTTP 400 stream response', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
      error: 'backend_removed', message: 'Codex App Server 已移除，请修正 Agent 设置',
    }), { status: 400, headers: { 'Content-Type': 'application/json' } }));
    try {
      await expect(agentApi.chatStream({message:'分析 AAPL'})).rejects.toMatchObject({
        parsedError: { code: 'backend_removed', status: 400 },
      });
      expect(fetch).toHaveBeenCalledTimes(1);
    } finally {
      fetch.mockRestore();
    }
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

  const active = { stock_code: 'sh000001', stock_name: '上证指数', canonical_id: 'sh000001', asset_type: 'index' };
  const state = {
    active_stock_context: active, session_generation: 'g1', session_state_version: 5,
    session_state: { selected_skill_ids: [] },
  };

  it('decodes complete server identity and explicit empty Skill state', () => {
    expect(decodeChatState(state, 'accepted')).toEqual({
      contract: 'authoritative', activeStockContext: active, sessionGeneration: 'g1',
      sessionStateVersion: 5, selectedSkillIds: [],
    });
  });

  it('separates invalidated null, version-zero recovery and old API field absence', () => {
    expect(decodeChatState({ ...state, active_stock_context: null }, 'detail').sessionStateVersion).toBe(5);
    expect(decodeChatState({ ...state, session_state_version: 0 }, 'detail').activeStockContext).toEqual(active);
    expect(decodeChatState({ session_state: { selected_skill_ids: null } }, 'detail')).toEqual({
      contract: 'legacy', activeStockContext: null, sessionGeneration: null,
      sessionStateVersion: null, selectedSkillIds: null,
    });
    expect(decodeChatState({}, 'accepted').contract).toBe('legacy');
  });

  it('permits only a genuinely empty view with null generation', () => {
    expect(decodeChatState({ ...state, active_stock_context: null, session_state_version: 0,
      session_generation: null }, 'detail').sessionGeneration).toBeNull();
    expect(() => decodeChatState({ ...state, session_generation: null }, 'detail')).toThrow();
    expect(() => decodeChatState({ ...state, session_state_version: 0 }, 'accepted')).toThrow();
  });

  it.each([
    { active_stock_context: active },
    { ...state, session_state_version: '5' },
    { ...state, session_state_version: -1 },
    { ...state, session_state_version: 1.5 },
    { ...state, session_generation: '' },
    { ...state, active_stock_context: { stock_code: 'sh000001', stock_name: '上证指数' } },
    { ...state, active_stock_context: { ...active, asset_type: 'etf' } },
    { ...state, session_state: { selected_skill_ids: [123] } },
    { ...state, session_state: {} },
  ])('rejects incomplete or damaged strict state instead of legacy fallback: %j', (payload) => {
    expect(() => decodeChatState(payload, 'detail')).toThrow();
  });

  it('preserves session conflict code and a refresh/retry instruction from the actual API 409 shape', () => {
    const parsed = parseApiError({ response: { status: 409, data: {
      error: 'session_state_conflict', message: 'Session changed; refresh and retry',
    } } });
    expect(parsed.code).toBe('session_state_conflict');
    expect(parsed.status).toBe(409);
    expect(parsed.message).toContain('刷新');
  });
});
