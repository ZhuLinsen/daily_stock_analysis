import { describe, expect, it } from 'vitest';
import {
  LLM_PROVIDER_CAPABILITY_LABELS,
  LLM_PROVIDER_TEMPLATE_BY_ID,
  LLM_PROVIDER_TEMPLATES,
  MODEL_PLACEHOLDERS_BY_PROTOCOL,
  filterDiscoveredTextModels,
  getProviderTemplate,
  isKnownProviderTemplate,
} from '../llmProviderTemplates';

describe('llmProviderTemplates', () => {
  it('filters only MiniMax text recommendations and orders Flash before M3', () => {
    const models = [
      'gpt-4o', 'MiniMax-M2.7', 'MiniMax-Text-01', 'MiniMax-VL-01', 'MiniMax-M3', 'MiniMax-M3.1-Flash',
      'minimax/minimax-m2.5', 'minimax/minimax-m3.1-flash:free',
      'speech-2.8-hd', 'MiniMax-Hailuo-2.3', 'image-01', 'custom-model',
    ];
    expect(filterDiscoveredTextModels(models)).toEqual([
      'gpt-4o', 'MiniMax-M3.1-Flash', 'minimax/minimax-m3.1-flash:free', 'MiniMax-M3',
      'speech-2.8-hd', 'MiniMax-Hailuo-2.3', 'image-01', 'custom-model',
    ]);
    expect(models).toContain('MiniMax-M2.7');
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.minimax.placeholderModels).toBe('MiniMax-M3.1-Flash,MiniMax-M3');
  });

  it('keeps provider template order aligned with the existing preset dropdown order', () => {
    expect(LLM_PROVIDER_TEMPLATES.map((template) => template.channelId)).toEqual([
      'modelflare',
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
      'requesty',
      'gemini',
      'anthropic',
      'openai',
      'ollama',
      'custom',
    ]);
  });

  it('defines Modelflare OpenAI-compatible defaults and documented capabilities', () => {
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.modelflare).toMatchObject({
      protocol: 'openai',
      baseUrl: 'https://modelflare.dev/v1',
      placeholderModels: 'gpt-6.1-sol',
      capabilities: ['openai-compatible', 'aggregator', 'model-discovery'],
      officialSources: [
        { label: 'Modelflare 专属注册', url: 'https://modelflare.dev/sign-up?utm_source=daily_stock_analysis&utm_campaign=app' },
        { label: 'Modelflare Docs', url: 'https://docs.modelflare.dev/' },
        { label: 'Modelflare Models & Pricing', url: 'https://modelflare.dev/pricing' },
      ],
    });
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.modelflare.configHint).toContain('路由分组');
  });

  it('keeps the Anspire LLM preset available without promotional labeling', () => {
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.anspire).toMatchObject({
      label: 'Anspire Open',
      protocol: 'openai',
      baseUrl: 'https://open-gateway.anspire.cn/v6',
      placeholderModels: 'Doubao-Seed-2.0-lite,Doubao-Seed-2.0-pro,qwen3.5-flash',
    });
    expect(isKnownProviderTemplate('anspire')).toBe(true);
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
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.requesty.configHint).toContain('API Key');
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.openai.configHint).toBeUndefined();
  });

  it('uses the mainland-accessible AIHubmix referral without changing its API base URL', () => {
    expect(LLM_PROVIDER_TEMPLATE_BY_ID.aihubmix).toMatchObject({
      baseUrl: 'https://aihubmix.com/v1',
      officialSources: [{ label: 'AIHubmix', url: 'https://inferera.com/?aff=CfMq' }],
    });
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
