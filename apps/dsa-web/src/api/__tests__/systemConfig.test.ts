import { beforeEach, describe, expect, it, vi } from 'vitest';
import { systemConfigApi } from '../systemConfig';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());

vi.mock('../index', () => ({
  default: {
    get,
    post,
    put: vi.fn(),
  },
}));

describe('systemConfigApi', () => {
  beforeEach(() => {
    get.mockReset();
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

  it('loads first-run setup status with camelCase fields', async () => {
    get.mockResolvedValueOnce({
      data: {
        is_complete: false,
        ready_for_smoke: false,
        required_missing_keys: ['llm_primary'],
        next_step_key: 'llm_primary',
        checks: [
          {
            key: 'llm_primary',
            title: 'LLM 主渠道',
            category: 'ai_model',
            required: true,
            status: 'needs_action',
            message: '缺少主模型配置',
            next_step: '打开系统设置',
          },
        ],
      },
    });

    const result = await systemConfigApi.getSetupStatus();

    expect(get).toHaveBeenCalledWith('/api/v1/system/config/setup/status');
    expect(result.isComplete).toBe(false);
    expect(result.nextStepKey).toBe('llm_primary');
    expect(result.checks[0].nextStep).toBe('打开系统设置');
  });

  it('loads generation backend status with camelCase fields', async () => {
    get.mockResolvedValueOnce({
      data: {
        primary_backend_id: 'codex_cli',
        fallback_backend_id: null,
        primary: {
          backend_id: 'codex_cli',
          backend_type: 'local_cli',
          provider_id: 'codex_cli',
          available: true,
          health_status: 'passed',
          supports_json: true,
          supports_tools: false,
          supports_stream: true,
          supports_vision: false,
          is_primary: true,
          fallback_target: null,
          max_concurrency: 1,
          usage_available: false,
          last_error_code: null,
          last_error_message: null,
        },
        fallback: null,
        backends: [],
      },
    });

    const result = await systemConfigApi.getGenerationBackendStatus();

    expect(get).toHaveBeenCalledWith('/api/v1/system/config/generation-backends/status');
    expect(result.primaryBackendId).toBe('codex_cli');
    expect(result.primary.supportsTools).toBe(false);
    expect(result.primary.healthStatus).toBe('passed');
  });

  it('previews generation backend status with draft items and mask token', async () => {
    post.mockResolvedValueOnce({
      data: {
        primary_backend_id: 'opencode_cli',
        fallback_backend_id: null,
        primary: {
          backend_id: 'opencode_cli',
          backend_type: 'local_cli',
          provider_id: 'opencode_cli',
          available: false,
          health_status: 'failed',
          supports_json: true,
          supports_tools: false,
          supports_stream: false,
          supports_vision: false,
          is_primary: true,
          fallback_target: null,
          max_concurrency: 1,
          usage_available: false,
          last_error_code: 'command_not_found',
          last_error_message: 'Executable not found',
        },
        fallback: null,
        backends: [],
      },
    });

    const result = await systemConfigApi.previewGenerationBackendStatus({
      items: [
        { key: 'GENERATION_BACKEND', value: 'opencode_cli' },
        { key: 'OPENAI_API_KEY', value: '******' },
      ],
      maskToken: '******',
    });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/system/config/generation-backends/status/preview',
      {
        items: [
          { key: 'GENERATION_BACKEND', value: 'opencode_cli' },
          { key: 'OPENAI_API_KEY', value: '******' },
        ],
        mask_token: '******',
      },
    );
    expect(result.primary.lastErrorCode).toBe('command_not_found');
  });

  it('runs generation backend smoke tests with snake_case fields', async () => {
    post.mockResolvedValueOnce({
      data: {
        success: true,
        mode: 'json',
        message: 'JSON smoke test passed',
        status: {
          backend_id: 'litellm',
          backend_type: 'litellm',
          provider_id: 'litellm',
          available: true,
          health_status: 'passed',
          supports_json: true,
          supports_tools: false,
          supports_stream: true,
          supports_vision: false,
          is_primary: true,
          fallback_target: null,
          max_concurrency: 2,
          usage_available: true,
          last_error_code: null,
          last_error_message: null,
        },
      },
    });

    const result = await systemConfigApi.testGenerationBackend({
      backendId: 'litellm',
      mode: 'json',
      items: [{ key: 'LITELLM_MODEL', value: 'openai/gpt-4o-mini' }],
      maskToken: '******',
      timeoutSeconds: 9,
    });

    expect(post).toHaveBeenCalledWith(
      '/api/v1/system/config/generation-backends/smoke-test',
      {
        backend_id: 'litellm',
        mode: 'json',
        items: [{ key: 'LITELLM_MODEL', value: 'openai/gpt-4o-mini' }],
        mask_token: '******',
        timeout_seconds: 9,
      },
    );
    expect(result.success).toBe(true);
    expect(result.status.healthStatus).toBe('passed');
  });
});
