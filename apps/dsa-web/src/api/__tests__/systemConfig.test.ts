import { beforeEach, describe, expect, it, vi } from 'vitest';
import { systemConfigApi } from '../systemConfig';

const post = vi.hoisted(() => vi.fn());

vi.mock('../index', () => ({
  default: {
    get: vi.fn(),
    post,
    put: vi.fn(),
  },
}));

describe('systemConfigApi', () => {
  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({
      data: {
        success: true,
        message: 'ok',
        error: null,
        error_code: null,
        stage: 'chat_completion',
        retryable: false,
        details: {},
        resolved_protocol: 'openai',
        resolved_model: 'openai/gpt-4o-mini',
        latency_ms: 10,
        capability_results: {},
      },
    });
  });

  it('omits capability_checks from basic LLM channel test payloads', async () => {
    await systemConfigApi.testLLMChannel({
      name: 'openai',
      protocol: 'openai',
      baseUrl: 'https://api.openai.com/v1',
      apiKey: 'sk-test',
      models: ['gpt-4o-mini'],
    });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/system/config/llm/test-channel',
      expect.not.objectContaining({ capability_checks: expect.anything() }),
    );
  });

  it('sends capability_checks only for explicit runtime capability checks', async () => {
    await systemConfigApi.testLLMChannel({
      name: 'openai',
      protocol: 'openai',
      baseUrl: 'https://api.openai.com/v1',
      apiKey: 'sk-test',
      models: ['gpt-4o-mini'],
      capabilityChecks: ['json', 'stream'],
    });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/system/config/llm/test-channel',
      expect.objectContaining({ capability_checks: ['json', 'stream'] }),
    );
  });

  it('sends notification channel test payloads with snake_case fields', async () => {
    post.mockResolvedValueOnce({
      data: {
        success: true,
        message: 'ok',
        error_code: null,
        stage: 'notification_send',
        retryable: false,
        latency_ms: 15,
        attempts: [
          {
            channel: 'custom',
            success: true,
            message: 'sent',
            target: 'https://example.com/hook?token=***',
            error_code: null,
            stage: 'notification_send',
            retryable: false,
            latency_ms: 15,
            http_status: 200,
          },
        ],
      },
    });

    const result = await systemConfigApi.testNotificationChannel({
      channel: 'custom',
      items: [{ key: 'CUSTOM_WEBHOOK_URLS', value: 'https://example.com/hook?token=secret' }],
      maskToken: '******',
      title: 'hello',
      content: 'world',
      timeoutSeconds: 7,
    });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/system/config/notification/test-channel',
      {
        channel: 'custom',
        items: [{ key: 'CUSTOM_WEBHOOK_URLS', value: 'https://example.com/hook?token=secret' }],
        mask_token: '******',
        title: 'hello',
        content: 'world',
        timeout_seconds: 7,
      },
    );
    expect(result.latencyMs).toBe(15);
    expect(result.attempts[0].errorCode).toBeNull();
    expect(result.attempts[0].httpStatus).toBe(200);
  });
});
