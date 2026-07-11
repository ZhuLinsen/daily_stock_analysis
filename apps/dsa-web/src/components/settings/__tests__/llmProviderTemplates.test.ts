import { describe, expect, it } from 'vitest';
import {
  LLM_PROVIDER_CAPABILITY_LABELS,
  LLM_PROVIDER_TEMPLATE_BY_ID,
  LLM_PROVIDER_TEMPLATES,
  MODEL_PLACEHOLDERS_BY_PROTOCOL,
  getProviderTemplate,
  isKnownProviderTemplate,
} from '../llmProviderTemplates';

describe('llmProviderTemplates', () => {
  it('keeps provider template order aligned with the existing preset dropdown order', () => {
    expect(LLM_PROVIDER_TEMPLATES.map((template) => template.channelId)).toEqual([
      'aihubmix',
      'anspire',
      'deepseek',
      'dashscope',
      'zhipu',
      'moonshot',
      'minimax',
      'volcengine',
      'siliconflow',
      'openrouter',
      'gemini',
      'anthropic',
      'openai',
      'ollama',
      'custom',
    ]);
  });

  it('derives lookup keys from unique channel ids', () => {
    const channelIds = LLM_PROVIDER_TEMPLATES.map((template) => template.channelId);

    expect(new Set(channelIds).size).toBe(channelIds.length);
    for (const template of LLM_PROVIDER_TEMPLATES) {
      expect(LLM_PROVIDER_TEMPLATE_BY_ID[template.channelId]).toBe(template);
    }
  });

  it('exposes safe helpers for known, custom, and unknown channel ids', () => {
    expect(getProviderTemplate('openrouter')).toBe(LLM_PROVIDER_TEMPLATE_BY_ID.openrouter);
    expect(getProviderTemplate('custom')).toBe(LLM_PROVIDER_TEMPLATE_BY_ID.custom);
    expect(getProviderTemplate('minimax2')).toBeUndefined();
    expect(getProviderTemplate('constructor')).toBeUndefined();
    expect(getProviderTemplate('toString')).toBeUndefined();

    expect(isKnownProviderTemplate('openrouter')).toBe(true);
    expect(isKnownProviderTemplate('custom')).toBe(false);
    expect(isKnownProviderTemplate('minimax2')).toBe(false);
    expect(isKnownProviderTemplate('constructor')).toBe(false);
    expect(isKnownProviderTemplate('toString')).toBe(false);
  });

  it('only defines static provider-template capabilities for P2 UI hints', () => {
    expect(Object.keys(LLM_PROVIDER_CAPABILITY_LABELS).sort()).toEqual([
      'aggregator',
      'local-runtime',
      'model-discovery',
      'official-api',
      'openai-compatible',
      'vision',
    ]);
    expect(LLM_PROVIDER_CAPABILITY_LABELS).not.toHaveProperty('json');
    expect(LLM_PROVIDER_CAPABILITY_LABELS).not.toHaveProperty('tools');
    expect(LLM_PROVIDER_CAPABILITY_LABELS).not.toHaveProperty('stream');
  });

  it('uses volcengine as the default Volcengine Ark provider id', () => {
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.volcengine).toMatchObject({
      label: '火山方舟（豆包）',
      protocol: 'openai',
      baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
      placeholderModels: 'doubao-seed-1-6-251015,doubao-seed-1-6-thinking-251015',
      configHint: '确认在线推理 endpoint / region 与 Coding Plan 专用入口不要混用。',
    });
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.ark).toBeUndefined();
  });

  it('keeps focused config hints on providers with common setup pitfalls', () => {
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.ollama.configHint).toContain('Ollama 服务');
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.siliconflow.configHint).toContain('API Key');
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.openrouter.configHint).toContain('API Key');
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.openai.configHint).toBeUndefined();
  });

  it('keeps basic metadata on non-custom provider templates', () => {
    for (const template of LLM_PROVIDER_TEMPLATES.filter((item) => item.channelId !== 'custom')) {
      expect(template.capabilities.length).toBeGreaterThan(0);
      expect(template.officialSources.length).toBeGreaterThan(0);
    }
  });

  it('keeps protocol-level fallback placeholders centralized', () => {
    expect(MODEL_PLACEHOLDERS_BY_PROTOCOL).toMatchObject({
      openai: 'gpt-5.5,qwen3.6-plus',
      deepseek: 'deepseek-v4-flash,deepseek-v4-pro',
      gemini: 'gemini-3.1-pro-preview,gemini-3-flash-preview',
      anthropic: 'claude-sonnet-4-6,claude-opus-4-7',
      vertex_ai: 'gemini-3.1-pro-preview',
      ollama: 'llama3.2,qwen2.5',
    });
  });
});
