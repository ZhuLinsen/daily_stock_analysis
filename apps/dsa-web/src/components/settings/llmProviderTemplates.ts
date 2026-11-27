import type { UiLanguage } from '../../i18n/uiText';

export type ChannelProtocol = 'openai' | 'deepseek' | 'gemini' | 'anthropic' | 'vertex_ai' | 'ollama';
export type LLMProviderCapability =
  | 'openai-compatible'
  | 'aggregator'
  | 'official-api'
  | 'model-discovery'
  | 'vision'
  | 'local-runtime';

/** Filter recommendations only; saved and hand-typed model IDs stay in channel state. */
export function filterDiscoveredTextModels(models: string[]): string[] {
  const miniMaxId = (model: string) => model.split('/').at(-1)?.toLowerCase() || '';
  const current = (model: string) => /^minimax-m(?:3|3\.1-flash)(?::free|-free|-discount)?$/.test(miniMaxId(model));
  const filtered = models.filter((model) => !/^minimax-(?:m\d|(?:text|vl)-01)/.test(miniMaxId(model)) || current(model));
  const miniMaxModels = filtered.filter(current).sort((left, right) => (
    Number(miniMaxId(right).startsWith('minimax-m3.1-flash'))
    - Number(miniMaxId(left).startsWith('minimax-m3.1-flash'))
  ));
  let index = 0;
  return filtered.map((model) => current(model) ? miniMaxModels[index++] : model);
}

export const MODELFLARE_APP_REGISTRATION_URL =
  'https://modelflare.dev/sign-up?utm_source=daily_stock_analysis&utm_campaign=app';
export const X6AI_REGISTRATION_URL = 'https://console.x6pro.io/register?code=zJ2qSdns';
export const MODELFLARE_DEFAULT_MODEL = 'gpt-6.1-sol';

export interface LLMProviderTemplate {
  channelId: string;
  label: string;
  protocol: ChannelProtocol;
  baseUrl: string;
  placeholderModels: string;
  capabilities: LLMProviderCapability[];
  configHint?: string;
  registration?: { label: string; url: string };
  officialSources: Array<{
    label: string;
    url: string;
  }>;
}

export const LLM_PROVIDER_CAPABILITY_LABELS: Record<LLMProviderCapability, { label: string; hint: string }> = {
  'openai-compatible': {
    label: 'OpenAI 兼容',
    hint: '按 OpenAI-compatible endpoint 配置 Base URL，不额外拼接 /chat/completions。',
  },
  aggregator: {
    label: '聚合平台',
    hint: '模型可见性、路由和价格可能随账号权限与平台策略变化。',
  },
  'official-api': {
    label: '官方 API',
    hint: '使用服务商官方协议或官方兼容入口。',
  },
  'model-discovery': {
    label: '可获取模型',
    hint: '支持尝试通过 /models 获取模型列表；实际结果仍取决于账号权限和 API Key。',
  },
  vision: {
    label: 'Vision 提示',
    hint: '模板提示该 provider 常用于 Vision 场景；具体模型能力仍以账号和模型列表为准。',
  },
  'local-runtime': {
    label: '本地运行',
    hint: '需要当前运行环境能访问对应本地服务。',
  },
};

export const LLM_PROVIDER_TEMPLATES: LLMProviderTemplate[] = [
  {
    channelId: 'modelflare',
    registration: { label: '注册 Modelflare', url: MODELFLARE_APP_REGISTRATION_URL },
    label: 'Modelflare（聚合平台）',
    protocol: 'openai',
    baseUrl: 'https://modelflare.dev/v1',
    placeholderModels: MODELFLARE_DEFAULT_MODEL,
    capabilities: ['openai-compatible', 'aggregator', 'model-discovery'],
    configHint:
      'API Key 的路由分组需支持所选模型；模型 ID 请以控制台或获取模型的结果为准。modelflare 渠道的 Base URL 留空时使用默认 /v1 地址，可按需覆盖，不额外拼接 /chat/completions。',
    officialSources: [
      { label: 'Modelflare 专属注册', url: MODELFLARE_APP_REGISTRATION_URL },
      { label: 'Modelflare Docs', url: 'https://docs.modelflare.dev/' },
      { label: 'Modelflare Models & Pricing', url: 'https://modelflare.dev/pricing' },
    ],
  },
  {
    channelId: 'x6ai',
    registration: { label: '注册 x6.ai', url: X6AI_REGISTRATION_URL },
    label: 'x6.ai（聚合平台）',
    protocol: 'openai',
    baseUrl: 'https://api.x6.ai/v1',
    placeholderModels: '',
    capabilities: ['openai-compatible', 'aggregator', 'model-discovery'],
    configHint: '请通过“获取模型”查询账号可用的模型 ID，再选择模型并测试连接；实际能力和价格以 x6.ai 控制台为准。',
    officialSources: [
      { label: 'x6.ai 专属注册', url: X6AI_REGISTRATION_URL },
      { label: 'x6.ai API 文档', url: 'https://x6.ai/zh/docs' },
      { label: 'x6.ai 模型列表', url: 'https://x6.ai/zh/models' },
    ],
  },
  {
    channelId: 'deepseek',
    label: 'DeepSeek 官方',
    protocol: 'deepseek',
    baseUrl: 'https://api.deepseek.com',
    placeholderModels: 'deepseek-flash,deepseek-v4-pro',
    capabilities: ['official-api', 'openai-compatible'],
    configHint:
      '推荐使用官方当前模型名 deepseek-flash（也可搭配 deepseek-v4-pro）；旧名 deepseek-v4-flash 已退役，仅作为兼容别名临时转发。',
    officialSources: [{ label: 'DeepSeek API Docs', url: 'https://api-docs.deepseek.com/' }],
  },
  {
    channelId: 'dashscope',
    label: '通义千问（Dashscope）',
    protocol: 'openai',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    placeholderModels: 'qwen3.6-plus,qwen3.6-flash',
    capabilities: ['openai-compatible', 'model-discovery'],
    officialSources: [
      { label: 'DashScope Text Generation', url: 'https://help.aliyun.com/zh/model-studio/text-generation-model/' },
    ],
  },
  {
    channelId: 'zhipu',
    label: '智谱 GLM',
    protocol: 'openai',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    placeholderModels: 'glm-5.1,glm-4.7-flash',
    capabilities: ['openai-compatible'],
    officialSources: [{ label: 'Zhipu Model Overview', url: 'https://docs.bigmodel.cn/cn/guide/start/model-overview' }],
  },
  {
    channelId: 'moonshot',
    label: 'Moonshot（月之暗面）',
    protocol: 'openai',
    baseUrl: 'https://api.moonshot.cn/v1',
    placeholderModels: 'kimi-k2.6,kimi-k2.5',
    capabilities: ['openai-compatible'],
    officialSources: [{ label: 'Kimi Platform Docs', url: 'https://platform.kimi.com/docs/models' }],
  },
  {
    channelId: 'minimax',
    label: 'MiniMax 官方',
    protocol: 'openai',
    baseUrl: 'https://api.minimax.io/v1',
    placeholderModels: 'MiniMax-M3.1-Flash,MiniMax-M3',
    capabilities: ['openai-compatible'],
    officialSources: [
      { label: 'MiniMax OpenAI API', url: 'https://platform.minimax.io/docs/api-reference/text-chat' },
      { label: 'MiniMax Models', url: 'https://platform.minimax.io/docs/api-reference/models/openai/list-models' },
    ],
  },
  {
    channelId: 'volcengine',
    label: '火山方舟（豆包）',
    protocol: 'openai',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
    placeholderModels: 'doubao-seed-1-6-251015,doubao-seed-1-6-thinking-251015',
    capabilities: ['openai-compatible'],
    configHint: '确认在线推理 endpoint / region 与 Coding Plan 专用入口不要混用。',
    officialSources: [
      { label: 'Volcengine Ark Inference', url: 'https://www.volcengine.com/docs/82379/2121998' },
      { label: 'Volcengine Ark Models', url: 'https://www.volcengine.com/docs/82379/1949118' },
    ],
  },
  {
    channelId: 'siliconflow',
    label: '硅基流动（SiliconFlow）',
    protocol: 'openai',
    baseUrl: 'https://api.siliconflow.cn/v1',
    placeholderModels: 'deepseek-ai/DeepSeek-V3.2,Qwen/Qwen3-235B-A22B-Thinking-2507',
    capabilities: ['openai-compatible', 'model-discovery'],
    configHint: '模型列表和模型可见性依赖账号权限与 API Key。',
    officialSources: [{ label: 'SiliconFlow Models', url: 'https://docs.siliconflow.cn/quickstart/models' }],
  },
  {
    channelId: 'openrouter',
    label: 'OpenRouter',
    protocol: 'openai',
    baseUrl: 'https://openrouter.ai/api/v1',
    placeholderModels: '~anthropic/claude-sonnet-latest,~openai/gpt-latest',
    capabilities: ['openai-compatible', 'aggregator', 'model-discovery'],
    configHint: '模型列表和模型可见性依赖账号权限与 API Key。',
    officialSources: [
      { label: 'OpenRouter Models API', url: 'https://openrouter.ai/docs/api/api-reference/models/get-models' },
    ],
  },
  {
    channelId: 'requesty',
    label: 'Requesty',
    protocol: 'openai',
    baseUrl: 'https://router.requesty.ai/v1',
    placeholderModels: 'claude-sonnet-4-6,gpt-6.1-sol',
    capabilities: ['openai-compatible', 'aggregator', 'model-discovery'],
    configHint: '模型列表和模型可见性依赖账号权限与 API Key；EU 区域可将 Base URL 改为 https://router.eu.requesty.ai/v1。',
    officialSources: [
      { label: 'Requesty Models API', url: 'https://docs.requesty.ai/api-reference/endpoint/models-list' },
    ],
  },
  {
    channelId: 'gemini',
    label: 'Gemini 官方',
    protocol: 'gemini',
    baseUrl: '',
    placeholderModels: 'gemini-3.6-flash,gemini-3.5-flash-lite',
    capabilities: ['official-api', 'vision'],
    officialSources: [{ label: 'Gemini Models', url: 'https://ai.google.dev/gemini-api/docs/models' }],
  },
  {
    channelId: 'anthropic',
    label: 'Anthropic 官方',
    protocol: 'anthropic',
    baseUrl: '',
    placeholderModels: 'claude-sonnet-4-6,claude-opus-4-7',
    capabilities: ['official-api'],
    officialSources: [
      { label: 'Anthropic Models', url: 'https://docs.anthropic.com/en/docs/about-claude/models/all-models' },
    ],
  },
  {
    channelId: 'openai',
    label: 'OpenAI 官方',
    protocol: 'openai',
    baseUrl: 'https://api.openai.com/v1',
    placeholderModels: 'gpt-6.1-sol,gpt-6.1-terra',
    capabilities: ['official-api', 'openai-compatible', 'model-discovery'],
    officialSources: [{ label: 'OpenAI Models', url: 'https://platform.openai.com/docs/models' }],
  },
  {
    channelId: 'ollama',
    label: 'Ollama（本地）',
    protocol: 'ollama',
    baseUrl: 'http://127.0.0.1:11434',
    placeholderModels: 'llama3.2,qwen2.5',
    capabilities: ['local-runtime'],
    configHint: '需要本机、Docker 或 self-hosted runner 能访问 Ollama 服务。',
    officialSources: [{ label: 'Ollama API', url: 'https://github.com/ollama/ollama/blob/main/docs/api.md' }],
  },
  {
    channelId: 'aihubmix',
    label: 'AIHubmix（聚合平台）',
    protocol: 'openai',
    baseUrl: 'https://aihubmix.com/v1',
    placeholderModels: 'gpt-6.1-sol,claude-sonnet-4-6,gemini-3.6-flash',
    capabilities: ['openai-compatible', 'aggregator'],
    officialSources: [{ label: 'AIHubmix', url: 'https://inferera.com/?aff=CfMq' }],
  },
  {
    channelId: 'anspire',
    label: 'Anspire Open',
    protocol: 'openai',
    baseUrl: 'https://open-gateway.anspire.cn/v6',
    placeholderModels: 'Doubao-Seed-2.0-lite,Doubao-Seed-2.0-pro,qwen3.5-flash',
    capabilities: ['openai-compatible'],
    configHint:
      '同一 ANSPIRE_API_KEYS 可复用到搜索与 LLM 渠道。以下模型与网关为配置示例，实际可用性请以账号权限和控制台为准；建议先点“测试连接”确认。',
    officialSources: [
      { label: 'Anspire Open', url: 'https://open.anspire.cn/dsa?share_code=QFBC0FYC' },
      {
        label: 'LiteLLM OpenAI-compatible',
        url: 'https://docs.litellm.ai/docs/providers/openai_compatible',
      },
    ],
  },
  {
    channelId: 'custom',
    label: '自定义渠道',
    protocol: 'openai',
    baseUrl: '',
    placeholderModels: 'model-name-1,model-name-2',
    capabilities: [],
    officialSources: [],
  },
];

export const LLM_PROVIDER_TEMPLATE_BY_ID: Record<string, LLMProviderTemplate> = Object.fromEntries(
  LLM_PROVIDER_TEMPLATES.map((template) => [template.channelId, template]),
);

export function getProviderTemplate(channelId: string): LLMProviderTemplate | undefined {
  if (!Object.prototype.hasOwnProperty.call(LLM_PROVIDER_TEMPLATE_BY_ID, channelId)) {
    return undefined;
  }
  return LLM_PROVIDER_TEMPLATE_BY_ID[channelId];
}

export function isKnownProviderTemplate(channelId: string): boolean {
  return channelId !== 'custom' && Boolean(getProviderTemplate(channelId));
}

export const MODEL_PLACEHOLDERS_BY_PROTOCOL: Record<ChannelProtocol, string> = {
  openai: 'gpt-6.1-sol,qwen3.6-plus',
  deepseek: 'deepseek-flash,deepseek-v4-pro',
  gemini: 'gemini-3.6-flash,gemini-3.5-flash-lite',
  anthropic: 'claude-sonnet-4-6,claude-opus-4-7',
  vertex_ai: 'gemini-3.6-flash',
  ollama: 'llama3.2,qwen2.5',
};

const EN_CAPABILITY_LABELS: Record<LLMProviderCapability, { label: string; hint: string }> = {
  'openai-compatible': {
    label: 'OpenAI Compatible',
    hint: 'Configure Base URL as an OpenAI-compatible endpoint without appending /chat/completions.',
  },
  aggregator: {
    label: 'Aggregator',
    hint: 'Model availability, routing, and pricing may vary by account permissions and platform policy.',
  },
  'official-api': {
    label: 'Official API',
    hint: 'Uses the provider official protocol or official compatible endpoint.',
  },
  'model-discovery': {
    label: 'Model Discovery',
    hint: 'Supports querying /models to fetch available models; actual results still depend on account permissions and API Key.',
  },
  vision: {
    label: 'Vision Hint',
    hint: 'Template indicates this provider is commonly used for Vision workflows; actual model capabilities depend on your account and model list.',
  },
  'local-runtime': {
    label: 'Local Runtime',
    hint: 'Requires the current runtime environment to reach the local service endpoint.',
  },
};

const EN_TEMPLATE_LABELS: Record<string, string> = {
  modelflare: 'Modelflare (Aggregator)',
  x6ai: 'x6.ai (Aggregator)',
  deepseek: 'DeepSeek Official',
  dashscope: 'Qwen (DashScope)',
  zhipu: 'Zhipu GLM',
  moonshot: 'Moonshot (Kimi)',
  minimax: 'MiniMax Official',
  volcengine: 'Volcengine Ark (Doubao)',
  siliconflow: 'SiliconFlow',
  openrouter: 'OpenRouter',
  requesty: 'Requesty',
  gemini: 'Gemini Official',
  anthropic: 'Anthropic Official',
  openai: 'OpenAI Official',
  ollama: 'Ollama (Local)',
  aihubmix: 'AIHubmix (Aggregator)',
  anspire: 'Anspire Open',
  custom: 'Custom Channel',
};

const EN_TEMPLATE_CONFIG_HINTS: Record<string, string> = {
  modelflare:
    'The API Key routing group must support your selected models; verify exact model IDs in the Modelflare console or via Fetch Models. Leaving Base URL blank defaults to /v1 and can be overridden without appending /chat/completions.',
  x6ai: 'Use "Fetch Models" to query model IDs available to your account, then select models and test the connection; refer to the x6.ai console for actual capabilities and pricing.',
  deepseek:
    'Recommended current Flash model ID is deepseek-flash (optionally alongside deepseek-v4-pro); legacy deepseek-v4-flash is retired and only accepted temporarily for compatibility.',
  volcengine: 'Ensure the online inference endpoint/region is not mixed up with dedicated Coding Plan endpoints.',
  siliconflow: 'Model list and model visibility depend on account permissions and your API Key.',
  openrouter: 'Model list and model visibility depend on account permissions and your API Key.',
  requesty: 'Model list and model visibility depend on account permissions and your API Key; for the EU region, set Base URL to https://router.eu.requesty.ai/v1.',
  ollama: 'Requires the local machine, Docker container, or self-hosted runner to reach the Ollama service.',
  anspire:
    'The same ANSPIRE_API_KEYS can be reused for both search and LLM channels. These models and gateway are configuration examples; verify availability against your account permissions and console, and click "Test Connection" first.',
};

const EN_TEMPLATE_REGISTRATION_LABELS: Record<string, string> = {
  modelflare: 'Sign up for Modelflare',
  x6ai: 'Sign up for x6.ai',
};

const EN_OFFICIAL_SOURCE_LABELS: Record<string, string> = {
  'Modelflare 专属注册': 'Modelflare Exclusive Sign-up',
  'x6.ai 专属注册': 'x6.ai Exclusive Sign-up',
  'x6.ai API 文档': 'x6.ai API Docs',
  'x6.ai 模型列表': 'x6.ai Model List',
};

export function getProviderCapabilityMeta(
  capability: LLMProviderCapability,
  language: UiLanguage,
): { label: string; hint: string } {
  if (language === 'en') {
    return EN_CAPABILITY_LABELS[capability] ?? LLM_PROVIDER_CAPABILITY_LABELS[capability];
  }
  return LLM_PROVIDER_CAPABILITY_LABELS[capability];
}

export function getProviderTemplateLabel(
  template: LLMProviderTemplate,
  language: UiLanguage,
): string {
  if (language === 'en') {
    return EN_TEMPLATE_LABELS[template.channelId] ?? template.label;
  }
  return template.label;
}

export function getProviderTemplateConfigHint(
  template: LLMProviderTemplate,
  language: UiLanguage,
): string | undefined {
  if (!template.configHint) {
    return undefined;
  }
  if (language === 'en') {
    return EN_TEMPLATE_CONFIG_HINTS[template.channelId] ?? template.configHint;
  }
  return template.configHint;
}

export function getProviderTemplateRegistration(
  template: LLMProviderTemplate,
  language: UiLanguage,
): { label: string; url: string } | undefined {
  if (!template.registration) {
    return undefined;
  }
  if (language === 'en') {
    return {
      ...template.registration,
      label: EN_TEMPLATE_REGISTRATION_LABELS[template.channelId] ?? template.registration.label,
    };
  }
  return template.registration;
}

export function getProviderTemplateOfficialSources(
  template: LLMProviderTemplate,
  language: UiLanguage,
): Array<{ label: string; url: string }> {
  if (language === 'en') {
    return template.officialSources.map((source) => ({
      ...source,
      label: EN_OFFICIAL_SOURCE_LABELS[source.label] ?? source.label,
    }));
  }
  return template.officialSources;
}
