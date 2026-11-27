import { afterEach, describe, expect, it } from 'vitest';
import {
  attachParsedApiError,
  formatParsedApiError,
  getParsedApiError,
  localizeParsedApiError,
  parseApiError,
  toApiErrorMessage,
} from '../error';
import { stocksApi } from '../stocks';
import { UI_LANGUAGE_STORAGE_KEY } from '../../utils/uiLanguage';

describe('API error and stocksApi localization', () => {
  afterEach(() => {
    window.localStorage.removeItem(UI_LANGUAGE_STORAGE_KEY);
    document.documentElement.lang = '';
  });

  it('keeps Chinese defaults intact when active UI language is zh', () => {
    const parsed = parseApiError({
      response: {
        status: 503,
        data: { message: 'DNS lookup failed' },
      },
    });
    expect(parsed.title).toBe('服务端无法访问外部依赖');
    expect(formatParsedApiError(parsed)).toContain('：');
    expect(toApiErrorMessage({ response: { status: 400, data: { error: 'backend_removed', message: 'Removed' } } }))
      .toBe('问股后端已移除：Removed');
  });

  it('localizes all API error branches in English without CJK leakage', () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    const cjkPattern = /[\u4e00-\u9fff]/;

    const samples = [
      {
        error: {
          response: {
            status: 400,
            data: {
              detail: {
                error: 'validation_failed',
                issues: [
                  { key: 'LLM_OPENAI_API_KEY', code: 'missing_api_key' },
                  { key: 'LLM_OPENAI_MODELS', code: 'missing_models' },
                  { key: 'LITELLM_MODEL', code: 'unknown_model' },
                ],
              },
            },
          },
        },
        expectedTitle: 'Configuration Needs Attention',
        expectedMessage: 'LLM_OPENAI_API_KEY: Please enter an API Key for this channel.',
      },
      {
        error: { response: { status: 400, data: { error: 'validation_failed' } } },
        expectedTitle: 'Configuration Needs Attention',
        expectedMessage: 'Please check your channel API Key, models, and runtime parameters, then try again.',
      },
      {
        error: { response: { status: 400, data: { error: 'backend_removed', message: 'Deprecated' } } },
        expectedTitle: 'Ask AI Backend Removed',
      },
      {
        error: { response: { status: 409, data: { error: 'session_state_conflict' } } },
        expectedTitle: 'Session Updated',
        expectedMessage: 'Please refresh the session and try again.',
      },
      {
        error: { response: { status: 403, data: { message: 'Agent mode is not enabled' } } },
        expectedTitle: 'Agent Mode Disabled',
      },
      {
        error: { response: { status: 400, data: { message: 'stock_code missing' } } },
        expectedTitle: 'Missing Required Parameters',
      },
      {
        error: { response: { status: 400, data: { error: 'portfolio_oversell' } } },
        expectedTitle: 'Sell Quantity Exceeds Holdings',
      },
      {
        error: { response: { status: 409, data: { error: 'portfolio_busy' } } },
        expectedTitle: 'Portfolio Ledger Busy',
      },
      {
        error: { response: { status: 503, data: { error: 'screening_unavailable' } } },
        expectedTitle: 'Stock Screening Unavailable',
      },
      {
        error: { response: { status: 404, data: { error: 'screening_screen_task_not_found' } } },
        expectedTitle: 'Screening Task Not Recoverable',
      },
      {
        error: { response: { status: 500, data: { error: 'screening_screen_failed' } } },
        expectedTitle: 'Stock Screening Failed',
      },
      {
        error: { response: { status: 400, data: { message: 'no effective primary model configured' } } },
        expectedTitle: 'No Usable LLM Configured',
      },
      {
        error: { response: { status: 400, data: { message: 'Model does not support tools' } } },
        expectedTitle: 'Model Does Not Support Tool Calling',
      },
      {
        error: { response: { status: 400, data: { message: 'missing thought_signature in response' } } },
        expectedTitle: 'Incomplete Upstream Tool Call',
      },
      {
        error: { code: 'ECONNABORTED', message: 'connect timeout' },
        expectedTitle: 'Upstream Request Timed Out',
      },
      {
        error: { response: { status: 502, statusText: 'Bad Gateway' } },
        expectedTitle: 'Server Cannot Reach External Services',
      },
      {
        error: { response: { status: 400, data: { message: 'POST /chat/completions rejected parameter' } } },
        expectedTitle: 'Upstream Model Rejected Request',
      },
      {
        error: { code: 'ERR_NETWORK', message: 'Network Error' },
        expectedTitle: 'Cannot Connect to Local Service',
      },
      {
        error: { response: { status: 500 } },
        expectedTitle: 'Request Failed',
        expectedMessage: 'Request failed (HTTP 500).',
      },
      {
        error: {},
        expectedTitle: 'Request Failed',
        expectedMessage: 'Request did not complete. Please try again later.',
      },
    ];

    for (const sample of samples) {
      const parsed = getParsedApiError(sample.error);
      expect(parsed.title).toBe(sample.expectedTitle);
      if (sample.expectedMessage) {
        expect(parsed.message).toContain(sample.expectedMessage);
      }
      expect(parsed.title).not.toMatch(cjkPattern);
      expect(parsed.message).not.toMatch(cjkPattern);
      const formatted = formatParsedApiError(parsed);
      expect(formatted).not.toMatch(cjkPattern);
      if (parsed.title !== parsed.message) {
        expect(formatted).toContain(': ');
      }
    }

    expect(toApiErrorMessage({})).toBe('Request Failed: Request did not complete. Please try again later.');
    expect(parseApiError({ response: { status: 500 } }, 'en').title).toBe('Request Failed');
  });

  it('localizes empty import input error in English when UI language is en', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    await expect(stocksApi.parseImport()).rejects.toThrow('Please provide a file or paste text');
  });

  it('re-localizes attached Errors and validation_failed ParsedApiError dynamically across language switches', () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    const networkErr = new Error('Network Error') as Error & { code?: string };
    networkErr.code = 'ERR_NETWORK';

    const attachedZh = attachParsedApiError(networkErr);
    expect(attachedZh.title).toBe('无法连接到本地服务');
    expect(networkErr.message).toContain('无法连接到本地服务');

    const resolvedEn = getParsedApiError(networkErr, 'en');
    expect(resolvedEn.title).toBe('Cannot Connect to Local Service');
    expect(resolvedEn.message).not.toMatch(/[\u4e00-\u9fff]/);
    expect(localizeParsedApiError(attachedZh, 'zh').title).toBe('无法连接到本地服务');

    const emptyMsgErr = new Error('') as Error & { response?: { status: number; data: unknown } };
    emptyMsgErr.response = {
      status: 400,
      data: {
        detail: {
          error: 'validation_failed',
          issues: [{ key: 'LITELLM_MODEL', code: 'unknown_model' }],
        },
      },
    };
    const attachedValidationZh = attachParsedApiError(emptyMsgErr);
    expect(attachedValidationZh.title).toBe('配置需要调整');
    expect(attachedValidationZh.message).toContain('请选择当前启用渠道中的模型');

    const validationEn = localizeParsedApiError(attachedValidationZh, 'en');
    expect(validationEn.title).toBe('Configuration Needs Attention');
    expect(validationEn.message).toContain('LITELLM_MODEL: Please choose a model from an enabled channel');
    expect(validationEn.message).not.toMatch(/[\u4e00-\u9fff]/);

    const validationZhAgain = getParsedApiError(emptyMsgErr, 'zh');
    expect(validationZhAgain.title).toBe('配置需要调整');
  });
});
