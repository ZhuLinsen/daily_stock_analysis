import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { getParsedApiError } from '../error';

describe('authentication response redirect', () => {
  const assign = vi.fn();

  beforeEach(() => {
    assign.mockClear();
    vi.stubGlobal('window', {
      location: { pathname: '/settings', search: '?category=system', hash: '#desktop-version-info', assign },
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  it('preserves the complete destination on an expired session', async () => {
    const error = { response: { status: 401 }, message: 'expired session' };
    await expect(apiClient.get('/fixture', { adapter: () => Promise.reject(error) })).rejects.toBe(error);
    expect(assign).toHaveBeenCalledWith('/login?redirect=%2Fsettings%3Fcategory%3Dsystem%23desktop-version-info');
  });

  it('does not redirect an unauthorized login request into a loop', async () => {
    window.location.pathname = '/login';
    const error = { response: { status: 401 }, message: 'incorrect password' };
    await expect(apiClient.get('/fixture', { adapter: () => Promise.reject(error) })).rejects.toBe(error);
    expect(assign).not.toHaveBeenCalled();
  });

  it('does not treat a server error as a session expiry', async () => {
    const error = { response: { status: 500 }, message: 'server error' };
    await expect(apiClient.get('/fixture', { adapter: () => Promise.reject(error) })).rejects.toBe(error);
    expect(assign).not.toHaveBeenCalled();
  });

  it.each([
    '/api/v1/system/config/generation-backends/status/preview',
    '/api/v1/system/config/generation-backends/smoke-test',
    '/api/v1/system/config',
  ])('preserves actionable config issues through the real interceptor for %s', async (endpoint) => {
    const issues = [
      { key: 'LLM_MODELFLARE_API_KEY', code: 'missing_api_key', message: 'API key required', actual: 'private-key-value' },
      { key: 'LITELLM_FALLBACK_MODELS', code: 'unknown_model', message: 'Undeclared fallback model' },
    ];
    const error = { response: { status: 400, data: { detail: {
      error: 'validation_failed', message: 'System configuration validation failed', issues,
    } } } };
    await expect(apiClient.post(endpoint, {}, { adapter: () => Promise.reject(error) })).rejects.toBe(error);
    const parsed = getParsedApiError(error);
    expect(parsed.title).toBe('配置需要调整');
    expect(parsed.message).toContain('LLM_MODELFLARE_API_KEY：请填写此渠道的 API Key。');
    expect(parsed.message).toContain('LITELLM_FALLBACK_MODELS：请选择当前启用渠道中的模型');
    expect(parsed.rawMessage).not.toContain('private-key-value');
    expect(parsed.code).toBe('validation_failed');
    expect(assign).not.toHaveBeenCalled();
  });

  it('handles normalized validation payloads and incomplete issue objects safely', async () => {
    const error = { response: { status: 400, data: {
      error: 'validation_failed', message: 'System configuration validation failed',
      issues: [null, { actual: 'private-key-value' }],
    } } };
    await expect(apiClient.post('/fixture', {}, { adapter: () => Promise.reject(error) })).rejects.toBe(error);
    expect(getParsedApiError(error).message).toBe('请检查渠道的 API Key、模型和运行参数后重试。');
    expect(getParsedApiError(error).rawMessage).not.toContain('private-key-value');
  });
});
