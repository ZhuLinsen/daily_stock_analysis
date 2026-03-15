import { useEffect, useMemo, useRef, useState } from 'react';
import type React from 'react';
import type { ParsedApiError } from '../../api/error';
import { getParsedApiError } from '../../api/error';
import { systemConfigApi } from '../../api/systemConfig';
import { ApiErrorAlert, EyeToggleIcon, Select } from '../common';

type ChannelProtocol = 'openai' | 'deepseek' | 'gemini' | 'anthropic' | 'vertex_ai' | 'ollama';

interface ChannelPreset {
  label: string;
  protocol: ChannelProtocol;
  baseUrl: string;
  placeholder: string;
}

const CHANNEL_PRESETS: Record<string, ChannelPreset> = {
  aihubmix: {
    label: 'AIHubmix（聚合平台）',
    protocol: 'openai',
    baseUrl: 'https://aihubmix.com/v1',
    placeholder: 'gpt-4o-mini,claude-3-5-sonnet,qwen-plus',
  },
  deepseek: {
    label: 'DeepSeek 官方',
    protocol: 'deepseek',
    baseUrl: 'https://api.deepseek.com/v1',
    placeholder: 'deepseek-chat,deepseek-reasoner',
  },
  dashscope: {
    label: '通义千问（Dashscope）',
    protocol: 'openai',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    placeholder: 'qwen-plus,qwen-turbo',
  },
  zhipu: {
    label: '智谱 GLM',
    protocol: 'openai',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    placeholder: 'glm-4-flash,glm-4-plus',
  },
  moonshot: {
    label: 'Moonshot（月之暗面）',
    protocol: 'openai',
    baseUrl: 'https://api.moonshot.cn/v1',
    placeholder: 'moonshot-v1-8k',
  },
  siliconflow: {
    label: '硅基流动（SiliconFlow）',
    protocol: 'openai',
    baseUrl: 'https://api.siliconflow.cn/v1',
    placeholder: 'Qwen/Qwen3-8B,deepseek-ai/DeepSeek-V3',
  },
  openrouter: {
    label: 'OpenRouter',
    protocol: 'openai',
    baseUrl: 'https://openrouter.ai/api/v1',
    placeholder: 'openai/gpt-4o,anthropic/claude-3-5-sonnet',
  },
  gemini: {
    label: 'Gemini 官方',
    protocol: 'gemini',
    baseUrl: '',
    placeholder: 'gemini-2.5-flash,gemini-2.5-pro',
  },
  anthropic: {
    label: 'Anthropic 官方',
    protocol: 'anthropic',
    baseUrl: '',
    placeholder: 'claude-3-5-sonnet-20241022',
  },
  openai: {
    label: 'OpenAI 官方',
    protocol: 'openai',
    baseUrl: 'https://api.openai.com/v1',
    placeholder: 'gpt-4o,gpt-4o-mini',
  },
  ollama: {
    label: 'Ollama（本地）',
    protocol: 'ollama',
    baseUrl: 'http://127.0.0.1:11434',
    placeholder: 'llama3.2,qwen2.5',
  },
  custom: {
    label: '自定义渠道',
    protocol: 'openai',
    baseUrl: '',
    placeholder: 'model-name-1,model-name-2',
  },
};

const PROTOCOL_OPTIONS: Array<{ value: ChannelProtocol; label: string }> = [
  { value: 'openai', label: 'OpenAI Compatible' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'vertex_ai', label: 'Vertex AI' },
  { value: 'ollama', label: 'Ollama' },
];

const MODEL_PLACEHOLDERS: Record<ChannelProtocol, string> = {
  openai: 'gpt-4o-mini,deepseek-chat,qwen-plus',
  deepseek: 'deepseek-chat,deepseek-reasoner',
  gemini: 'gemini-2.5-flash,gemini-2.5-pro',
  anthropic: 'claude-3-5-sonnet-20241022',
  vertex_ai: 'gemini-2.5-flash',
  ollama: 'llama3.2,qwen2.5',
};

const KNOWN_MODEL_PREFIXES = new Set([
  'openai',
  'anthropic',
  'gemini',
  'vertex_ai',
  'deepseek',
  'ollama',
  'cohere',
  'huggingface',
  'bedrock',
  'sagemaker',
  'azure',
  'replicate',
  'together_ai',
  'palm',
  'text-completion-openai',
  'command-r',
  'groq',
  'cerebras',
  'fireworks_ai',
  'friendliai',
]);

const FALSEY_VALUES = new Set(['0', 'false', 'no', 'off']);

interface ChannelConfig {
  name: string;
  protocol: ChannelProtocol;
  baseUrl: string;
  apiKey: string;
  models: string;
  enabled: boolean;
}

interface ChannelTestState {
  status: 'idle' | 'loading' | 'success' | 'error';
  text?: string;
}

interface RuntimeConfig {
  primaryModel: string;
  fallbackModels: string[];
  visionModel: string;
  temperature: string;
}

interface LLMChannelEditorProps {
  items: Array<{ key: string; value: string }>;
  configVersion: string;
  maskToken: string;
  onSaved: () => void;
  disabled?: boolean;
}

/* ------------------------------------------------------------------ */
/*  Compact channel row with expandable detail                        */
/* ------------------------------------------------------------------ */

interface ChannelRowProps {
  channel: ChannelConfig;
  index: number;
  busy: boolean;
  visibleKey: boolean;
  expanded: boolean;
  testState?: ChannelTestState;
  onUpdate: (index: number, field: keyof ChannelConfig, value: string | boolean) => void;
  onRemove: (index: number) => void;
  onToggleExpand: (index: number) => void;
  onToggleKeyVisibility: (index: number) => void;
  onTest: (channel: ChannelConfig, index: number) => void;
}

const ChannelRow: React.FC<ChannelRowProps> = ({
  channel,
  index,
  busy,
  visibleKey,
  expanded,
  testState,
  onUpdate,
  onRemove,
  onToggleExpand,
  onToggleKeyVisibility,
  onTest,
}) => {
  const preset = CHANNEL_PRESETS[channel.name];
  const displayName = preset?.label || channel.name;
  const modelCount = splitModels(channel.models).length;
  const hasKey = channel.apiKey.length > 0;

  return (
    <div className="rounded-lg border border-white/8 bg-card/40 overflow-hidden">
      {/* Summary row — always visible */}
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer select-none hover:bg-white/[0.03] transition-colors"
        onClick={() => onToggleExpand(index)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggleExpand(index); } }}
        role="button"
        tabIndex={0}
      >
        <span className="text-[11px] text-muted w-4 shrink-0">{expanded ? '▼' : '▶'}</span>

        <input
          type="checkbox"
          checked={channel.enabled}
          disabled={busy}
          className="shrink-0"
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => onUpdate(index, 'enabled', e.target.checked)}
        />

        <span className="min-w-[100px] truncate text-sm text-white font-medium">{displayName}</span>

        <span className="hidden sm:inline rounded bg-white/8 px-1.5 py-0.5 text-[10px] text-muted uppercase tracking-wide">
          {channel.protocol}
        </span>

        <span className="text-[11px] text-muted truncate flex-1">
          {modelCount > 0 ? `${modelCount} 个模型` : '未配置模型'}
        </span>

        {/* Status indicators */}
        <span className="flex items-center gap-1.5 shrink-0">
          {testState?.status === 'success' && <span className="h-2 w-2 rounded-full bg-emerald-400" title="连接正常" />}
          {testState?.status === 'error' && <span className="h-2 w-2 rounded-full bg-rose-400" title="连接失败" />}
          {testState?.status === 'loading' && <span className="h-2 w-2 rounded-full bg-amber-400 animate-pulse" title="测试中" />}
          {!hasKey && channel.protocol !== 'ollama' && (
            <span className="text-[10px] text-amber-400/80">未填 Key</span>
          )}
        </span>

        <button
          type="button"
          className="shrink-0 text-xs text-muted hover:text-rose-300 transition-colors px-1"
          disabled={busy}
          onClick={(e) => { e.stopPropagation(); onRemove(index); }}
          title="删除渠道"
        >
          ✕
        </button>
      </div>

      {/* Detail panel — only when expanded */}
      {expanded && (
        <div className="border-t border-white/6 bg-card/20 px-3 py-3 space-y-2.5">
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <label className="mb-0.5 block text-[11px] text-muted">渠道名称</label>
              <input
                className="input-terminal text-sm"
                value={channel.name}
                disabled={busy}
                onChange={(e) => onUpdate(index, 'name', e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
                placeholder="primary"
              />
            </div>
            <div>
              <label className="mb-0.5 block text-[11px] text-muted">协议</label>
              <Select
                value={channel.protocol}
                onChange={(v) => onUpdate(index, 'protocol', normalizeProtocol(v))}
                options={PROTOCOL_OPTIONS}
                disabled={busy}
                placeholder="选择协议"
              />
            </div>
          </div>

          <div>
            <label className="mb-0.5 block text-[11px] text-muted">Base URL</label>
            <input
              className="input-terminal text-sm"
              value={channel.baseUrl}
              disabled={busy}
              onChange={(e) => onUpdate(index, 'baseUrl', e.target.value)}
              placeholder={
                channel.protocol === 'gemini' || channel.protocol === 'anthropic'
                  ? '官方接口可留空'
                  : preset?.baseUrl || 'https://api.example.com/v1'
              }
            />
          </div>

          <div>
            <label className="mb-0.5 block text-[11px] text-muted">API Key</label>
            <div className="flex items-center gap-1.5">
              <input
                type={visibleKey ? 'text' : 'password'}
                className="input-terminal text-sm flex-1"
                value={channel.apiKey}
                disabled={busy}
                onChange={(e) => onUpdate(index, 'apiKey', e.target.value)}
                placeholder={channel.protocol === 'ollama' ? '本地 Ollama 可留空' : '支持多个 Key 逗号分隔'}
              />
              <button
                type="button"
                className="btn-secondary !p-1.5"
                disabled={busy}
                onClick={() => onToggleKeyVisibility(index)}
                title={visibleKey ? '隐藏' : '显示'}
                aria-label={visibleKey ? '隐藏 API Key' : '显示 API Key'}
              >
                <EyeToggleIcon visible={visibleKey} />
              </button>
            </div>
          </div>

          <div>
            <label className="mb-0.5 block text-[11px] text-muted">模型（逗号分隔）</label>
            <input
              className="input-terminal text-sm"
              value={channel.models}
              disabled={busy}
              onChange={(e) => onUpdate(index, 'models', e.target.value)}
              placeholder={preset?.placeholder || MODEL_PLACEHOLDERS[channel.protocol]}
            />
          </div>

          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              className="btn-secondary text-xs"
              disabled={busy}
              onClick={() => onTest(channel, index)}
            >
              {testState?.status === 'loading' ? '测试中...' : '测试连接'}
            </button>
            {testState?.text && (
              <span className={`text-xs ${
                testState.status === 'success' ? 'text-emerald-300'
                : testState.status === 'error' ? 'text-rose-300'
                : 'text-muted'
              }`}>
                {testState.text}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

function normalizeProtocol(value: string): ChannelProtocol {
  const normalized = value.trim().toLowerCase().replace(/-/g, '_');
  if (normalized === 'vertex' || normalized === 'vertexai') {
    return 'vertex_ai';
  }
  if (normalized === 'claude') {
    return 'anthropic';
  }
  if (normalized === 'google') {
    return 'gemini';
  }
  if (normalized === 'deepseek') {
    return 'deepseek';
  }
  if (normalized === 'gemini') {
    return 'gemini';
  }
  if (normalized === 'anthropic') {
    return 'anthropic';
  }
  if (normalized === 'vertex_ai') {
    return 'vertex_ai';
  }
  if (normalized === 'ollama') {
    return 'ollama';
  }
  return 'openai';
}

function inferProtocol(protocol: string, baseUrl: string, models: string[]): ChannelProtocol {
  const explicit = normalizeProtocol(protocol);
  if (protocol.trim()) {
    return explicit;
  }

  const firstPrefixedModel = models.find((model) => model.includes('/'));
  if (firstPrefixedModel) {
    return normalizeProtocol(firstPrefixedModel.split('/', 1)[0]);
  }

  if (baseUrl.includes('127.0.0.1') || baseUrl.includes('localhost')) {
    return 'openai';
  }

  return baseUrl.trim() ? 'openai' : 'openai';
}

function parseEnabled(value: string | undefined): boolean {
  if (!value) {
    return true;
  }
  return !FALSEY_VALUES.has(value.trim().toLowerCase());
}

function splitModels(models: string): string[] {
  return models
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);
}

const PROTOCOL_ALIASES: Record<string, string> = {
  vertexai: 'vertex_ai',
  vertex: 'vertex_ai',
  claude: 'anthropic',
  google: 'gemini',
  openai_compatible: 'openai',
  openai_compat: 'openai',
};

function normalizeModelForRuntime(model: string, protocol: ChannelProtocol): string {
  const trimmedModel = model.trim();
  if (!trimmedModel) {
    return trimmedModel;
  }

  if (trimmedModel.includes('/')) {
    const rawPrefix = trimmedModel.split('/', 1)[0].trim();
    const lowerPrefix = rawPrefix.toLowerCase();
    const canonicalPrefix = PROTOCOL_ALIASES[lowerPrefix] || lowerPrefix;
    if (KNOWN_MODEL_PREFIXES.has(lowerPrefix) || KNOWN_MODEL_PREFIXES.has(canonicalPrefix)) {
      // Known provider — canonicalize the prefix if it's an alias
      if (canonicalPrefix !== lowerPrefix && KNOWN_MODEL_PREFIXES.has(canonicalPrefix)) {
        return `${canonicalPrefix}/${trimmedModel.split('/').slice(1).join('/')}`;
      }
      return trimmedModel;
    }
    return `${protocol}/${trimmedModel}`;
  }

  return `${protocol}/${trimmedModel}`;
}

function resolveModelPreview(models: string, protocol: ChannelProtocol): string[] {
  return splitModels(models).map((model) => normalizeModelForRuntime(model, protocol));
}

function buildModelOptions(models: string[], selectedModel: string, autoLabel: string): Array<{ value: string; label: string }> {
  const options: Array<{ value: string; label: string }> = [{ value: '', label: autoLabel }];
  if (selectedModel && !models.includes(selectedModel)) {
    options.push({ value: selectedModel, label: `${selectedModel}（当前配置）` });
  }
  for (const model of models) {
    options.push({ value: model, label: model });
  }
  return options;
}

const MANAGED_PROVIDERS = new Set(['gemini', 'vertex_ai', 'anthropic', 'openai', 'deepseek']);

function usesDirectEnvProvider(model: string): boolean {
  if (!model || !model.includes('/')) return false;
  const provider = model.split('/', 1)[0].trim().toLowerCase();
  return Boolean(provider) && !MANAGED_PROVIDERS.has(provider);
}

/** Mirror of backend resolve_unified_llm_temperature: prefers provider-specific env for the active model. */
function resolveTemperatureFromItems(itemMap: Map<string, string>): string {
  const unified = itemMap.get('LLM_TEMPERATURE');
  if (unified) return unified;

  const primaryModel = itemMap.get('LITELLM_MODEL') || '';
  const provider = primaryModel.includes('/') ? primaryModel.split('/')[0] : (primaryModel ? 'openai' : '');
  const PROVIDER_TEMPERATURE_ENV: Record<string, string> = {
    gemini: 'GEMINI_TEMPERATURE',
    vertex_ai: 'GEMINI_TEMPERATURE',
    anthropic: 'ANTHROPIC_TEMPERATURE',
    openai: 'OPENAI_TEMPERATURE',
    deepseek: 'OPENAI_TEMPERATURE',
  };
  const preferredEnv = PROVIDER_TEMPERATURE_ENV[provider];
  if (preferredEnv) {
    const val = itemMap.get(preferredEnv);
    if (val) return val;
  }

  for (const envName of ['GEMINI_TEMPERATURE', 'ANTHROPIC_TEMPERATURE', 'OPENAI_TEMPERATURE']) {
    const val = itemMap.get(envName);
    if (val) return val;
  }

  return '0.7';
}

function parseRuntimeConfigFromItems(items: Array<{ key: string; value: string }>): RuntimeConfig {
  const itemMap = new Map(items.map((item) => [item.key, item.value]));
  return {
    primaryModel: itemMap.get('LITELLM_MODEL') || '',
    fallbackModels: splitModels(itemMap.get('LITELLM_FALLBACK_MODELS') || ''),
    visionModel: itemMap.get('VISION_MODEL') || '',
    temperature: resolveTemperatureFromItems(itemMap),
  };
}

function parseChannelsFromItems(items: Array<{ key: string; value: string }>): ChannelConfig[] {
  const itemMap = new Map(items.map((item) => [item.key, item.value]));
  const channelNames = (itemMap.get('LLM_CHANNELS') || '')
    .split(',')
    .map((segment) => segment.trim())
    .filter(Boolean);

  return channelNames.map((name) => {
    const upperName = name.toUpperCase();
    const baseUrl = itemMap.get(`LLM_${upperName}_BASE_URL`) || '';
    const rawModels = itemMap.get(`LLM_${upperName}_MODELS`) || '';
    const models = splitModels(rawModels);

    return {
      name: name.toLowerCase(),
      protocol: inferProtocol(itemMap.get(`LLM_${upperName}_PROTOCOL`) || '', baseUrl, models),
      baseUrl,
      apiKey: itemMap.get(`LLM_${upperName}_API_KEYS`) || itemMap.get(`LLM_${upperName}_API_KEY`) || '',
      models: rawModels,
      enabled: parseEnabled(itemMap.get(`LLM_${upperName}_ENABLED`)),
    };
  });
}

function channelsToUpdateItems(
  channels: ChannelConfig[],
  previousChannelNames: string[],
  runtimeConfig: RuntimeConfig,
  includeRuntimeConfig: boolean,
): Array<{ key: string; value: string }> {
  const updates: Array<{ key: string; value: string }> = [];
  const activeNames = channels.map((channel) => channel.name.toUpperCase());

  updates.push({ key: 'LLM_CHANNELS', value: channels.map((channel) => channel.name).join(',') });
  if (includeRuntimeConfig) {
    updates.push({ key: 'LITELLM_MODEL', value: runtimeConfig.primaryModel });
    updates.push({ key: 'LITELLM_FALLBACK_MODELS', value: runtimeConfig.fallbackModels.join(',') });
    updates.push({ key: 'VISION_MODEL', value: runtimeConfig.visionModel });
    updates.push({ key: 'LLM_TEMPERATURE', value: runtimeConfig.temperature });
  }

  for (const channel of channels) {
    const prefix = `LLM_${channel.name.toUpperCase()}`;
    const isMultiKey = channel.apiKey.includes(',');
    updates.push({ key: `${prefix}_PROTOCOL`, value: channel.protocol });
    updates.push({ key: `${prefix}_BASE_URL`, value: channel.baseUrl });
    updates.push({ key: `${prefix}_ENABLED`, value: channel.enabled ? 'true' : 'false' });
    updates.push({ key: `${prefix}_API_KEY${isMultiKey ? 'S' : ''}`, value: channel.apiKey });
    updates.push({ key: `${prefix}_API_KEY${isMultiKey ? '' : 'S'}`, value: '' });
    updates.push({ key: `${prefix}_MODELS`, value: channel.models });
  }

  for (const oldName of previousChannelNames) {
    const upperName = oldName.toUpperCase();
    if (activeNames.includes(upperName)) {
      continue;
    }

    const prefix = `LLM_${upperName}`;
    updates.push({ key: `${prefix}_PROTOCOL`, value: '' });
    updates.push({ key: `${prefix}_BASE_URL`, value: '' });
    updates.push({ key: `${prefix}_ENABLED`, value: '' });
    updates.push({ key: `${prefix}_API_KEY`, value: '' });
    updates.push({ key: `${prefix}_API_KEYS`, value: '' });
    updates.push({ key: `${prefix}_MODELS`, value: '' });
    updates.push({ key: `${prefix}_EXTRA_HEADERS`, value: '' });
  }

  return updates;
}

function channelsAreEqual(left: ChannelConfig, right: ChannelConfig): boolean {
  return (
    left.name === right.name
    && left.protocol === right.protocol
    && left.baseUrl === right.baseUrl
    && left.apiKey === right.apiKey
    && left.models === right.models
    && left.enabled === right.enabled
  );
}

export const LLMChannelEditor: React.FC<LLMChannelEditorProps> = ({
  items,
  configVersion,
  maskToken,
  onSaved,
  disabled = false,
}) => {
  const initialChannels = useMemo(() => parseChannelsFromItems(items), [items]);
  const initialNames = useMemo(() => initialChannels.map((channel) => channel.name), [initialChannels]);
  const initialRuntimeConfig = useMemo(() => parseRuntimeConfigFromItems(items), [items]);
  const hasLitellmConfig = useMemo(
    () => items.some((item) => item.key === 'LITELLM_CONFIG' && item.value.trim().length > 0),
    [items],
  );
  const managesRuntimeConfig = !hasLitellmConfig;

  // Stable fingerprints to avoid resetting editor state when unrelated fields
  // (e.g. LITELLM_CONFIG) in the same category are edited by the user.
  const channelsFingerprint = useMemo(() => JSON.stringify(initialChannels), [initialChannels]);
  const runtimeFingerprint = useMemo(() => JSON.stringify(initialRuntimeConfig), [initialRuntimeConfig]);

  const [channels, setChannels] = useState<ChannelConfig[]>(initialChannels);
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfig>(initialRuntimeConfig);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<
    | { type: 'success'; text: string }
    | { type: 'error'; error: ParsedApiError }
    | { type: 'local-error'; text: string }
    | null
  >(null);
  const [visibleKeys, setVisibleKeys] = useState<Record<number, boolean>>({});
  const [testStates, setTestStates] = useState<Record<number, ChannelTestState>>({});
  const [expandedRows, setExpandedRows] = useState<Record<number, boolean>>({});
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [addPreset, setAddPreset] = useState('aihubmix');

  const prevChannelsRef = useRef(channelsFingerprint);
  const prevRuntimeRef = useRef(runtimeFingerprint);

  useEffect(() => {
    if (prevChannelsRef.current === channelsFingerprint && prevRuntimeRef.current === runtimeFingerprint) {
      return;
    }
    prevChannelsRef.current = channelsFingerprint;
    prevRuntimeRef.current = runtimeFingerprint;
    setChannels(initialChannels);
    setRuntimeConfig(initialRuntimeConfig);
    setVisibleKeys({});
    setTestStates({});
    setExpandedRows({});
    setSaveMessage(null);
    setIsCollapsed(false);
  }, [channelsFingerprint, runtimeFingerprint, initialChannels, initialRuntimeConfig]);

  const availableModels = useMemo(() => {
    if (!managesRuntimeConfig) {
      return [];
    }
    const seen = new Set<string>();
    const models: string[] = [];
    for (const channel of channels) {
      if (!channel.enabled || !channel.name.trim()) {
        continue;
      }
      for (const model of resolveModelPreview(channel.models, channel.protocol)) {
        if (!model || seen.has(model)) {
          continue;
        }
        seen.add(model);
        models.push(model);
      }
    }
    return models;
  }, [channels, managesRuntimeConfig]);

  const hasChanges = useMemo(() => {
    const runtimeChanged = (
      runtimeConfig.primaryModel !== initialRuntimeConfig.primaryModel
      || runtimeConfig.visionModel !== initialRuntimeConfig.visionModel
      || runtimeConfig.temperature !== initialRuntimeConfig.temperature
      || runtimeConfig.fallbackModels.join(',') !== initialRuntimeConfig.fallbackModels.join(',')
    );

    if (runtimeChanged || channels.length !== initialChannels.length) {
      return true;
    }
    return channels.some((channel, index) => !channelsAreEqual(channel, initialChannels[index]));
  }, [channels, initialChannels, initialRuntimeConfig, runtimeConfig]);

  const busy = disabled || isSaving;

  const updateChannel = (index: number, field: keyof ChannelConfig, value: string | boolean) => {
    setChannels((previous) => previous.map((channel, rowIndex) => {
      if (rowIndex !== index) return channel;
      const updated = { ...channel, [field]: value };

      // Auto-apply preset when name exactly matches a known provider
      if (field === 'name' && typeof value === 'string') {
        const newPreset = CHANNEL_PRESETS[value];
        if (newPreset) {
          const oldPreset = CHANNEL_PRESETS[channel.name];
          // Only auto-fill if value is empty or still from a previous preset
          if (!updated.baseUrl || updated.baseUrl === (oldPreset?.baseUrl ?? '')) {
            updated.baseUrl = newPreset.baseUrl;
          }
          updated.protocol = newPreset.protocol;
          if (!updated.models || updated.models === (oldPreset?.placeholder ?? '')) {
            updated.models = newPreset.placeholder;
          }
        }
      }

      return updated;
    }));
    setTestStates((previous) => {
      if (!(index in previous)) {
        return previous;
      }
      const next = { ...previous };
      delete next[index];
      return next;
    });
  };

  const removeChannel = (index: number) => {
    setChannels((previous) => previous.filter((_, rowIndex) => rowIndex !== index));
    setVisibleKeys({});
    setTestStates({});
    setExpandedRows({});
  };

  const addChannel = () => {
    const preset = CHANNEL_PRESETS[addPreset] || CHANNEL_PRESETS.custom;
    setChannels((previous) => {
      const existingNames = new Set(previous.map((channel) => channel.name));
      const baseName = addPreset === 'custom' ? 'custom' : addPreset;
      let nextName = baseName;
      let counter = 2;
      while (existingNames.has(nextName)) {
        nextName = `${baseName}${counter}`;
        counter += 1;
      }

      return [
        ...previous,
        {
          name: nextName,
          protocol: preset.protocol,
          baseUrl: preset.baseUrl,
          apiKey: '',
          models: preset.placeholder || '',
          enabled: true,
        },
      ];
    });
    setTestStates({});
    setExpandedRows((prev) => ({ ...prev, [channels.length]: true }));
    setIsCollapsed(false);
  };

  const handleSave = async () => {
    const hasEmptyName = channels.some((channel) => !channel.name.trim());
    if (hasEmptyName) {
      setSaveMessage({ type: 'local-error', text: '渠道名称不能为空，且只能包含字母、数字或下划线。' });
      return;
    }

    // Only validate model references against channel-derived models when
    // channels actually define models.  Users relying on LITELLM_CONFIG
    // or legacy API Key env vars may have models not visible here.
    if (managesRuntimeConfig && availableModels.length > 0) {
      const invalidPrimaryModel = runtimeConfig.primaryModel
        && !availableModels.includes(runtimeConfig.primaryModel)
        && !usesDirectEnvProvider(runtimeConfig.primaryModel);
      if (invalidPrimaryModel) {
        setSaveMessage({ type: 'local-error', text: '当前主模型不在已启用渠道的模型列表中，请重新选择。' });
        return;
      }

      const invalidFallbackModel = runtimeConfig.fallbackModels.some(
        (model) => !availableModels.includes(model) && !usesDirectEnvProvider(model),
      );
      if (invalidFallbackModel) {
        setSaveMessage({ type: 'local-error', text: '存在无效的 fallback 模型，请重新选择。' });
        return;
      }

      const invalidVisionModel = runtimeConfig.visionModel
        && !availableModels.includes(runtimeConfig.visionModel)
        && !usesDirectEnvProvider(runtimeConfig.visionModel);
      if (invalidVisionModel) {
        setSaveMessage({ type: 'local-error', text: '当前 Vision 模型不在已启用渠道的模型列表中，请重新选择。' });
        return;
      }
    }

    setIsSaving(true);
    setSaveMessage(null);

    try {
      const updateItems = channelsToUpdateItems(channels, initialNames, runtimeConfig, managesRuntimeConfig);
      await systemConfigApi.update({
        configVersion,
        maskToken,
        reloadNow: true,
        items: updateItems,
      });
      setSaveMessage({ type: 'success', text: managesRuntimeConfig ? 'AI 配置已保存' : '渠道配置已保存' });
      onSaved();
    } catch (error: unknown) {
      setSaveMessage({ type: 'error', error: getParsedApiError(error) });
    } finally {
      setIsSaving(false);
    }
  };

  const handleTest = async (channel: ChannelConfig, index: number) => {
    setTestStates((previous) => ({
      ...previous,
      [index]: { status: 'loading', text: '测试中...' },
    }));

    try {
      const result = await systemConfigApi.testLLMChannel({
        name: channel.name,
        protocol: channel.protocol,
        baseUrl: channel.baseUrl,
        apiKey: channel.apiKey,
        models: splitModels(channel.models),
        enabled: channel.enabled,
      });

      const text = result.success
        ? `连接成功${result.resolvedModel ? ` · ${result.resolvedModel}` : ''}${result.latencyMs ? ` · ${result.latencyMs} ms` : ''}`
        : (result.error || result.message || '测试失败');

      setTestStates((previous) => ({
        ...previous,
        [index]: {
          status: result.success ? 'success' : 'error',
          text,
        },
      }));
    } catch (error: unknown) {
      const parsed = getParsedApiError(error);
      setTestStates((previous) => ({
        ...previous,
        [index]: { status: 'error', text: parsed.message || '测试失败' },
      }));
    }
  };

  const toggleKeyVisibility = (index: number) => {
    setVisibleKeys((previous) => ({ ...previous, [index]: !previous[index] }));
  };

  const toggleExpand = (index: number) => {
    setExpandedRows((previous) => ({ ...previous, [index]: !previous[index] }));
  };

  const setPrimaryModel = (value: string) => {
    setRuntimeConfig((previous) => ({
      ...previous,
      primaryModel: value,
      fallbackModels: previous.fallbackModels.filter((model) => model !== value),
    }));
  };

  const toggleFallbackModel = (model: string) => {
    setRuntimeConfig((previous) => {
      const alreadySelected = previous.fallbackModels.includes(model);
      return {
        ...previous,
        fallbackModels: alreadySelected
          ? previous.fallbackModels.filter((item) => item !== model)
          : [...previous.fallbackModels, model],
      };
    });
  };

  return (
    <div className="rounded-xl border border-cyan/20 bg-elevated/50 p-4">
      <button
        type="button"
        className="flex w-full items-center justify-between text-left"
        onClick={() => setIsCollapsed((previous) => !previous)}
      >
        <div>
          <h3 className="text-sm font-semibold text-white">AI 模型配置</h3>
          <p className="mt-0.5 text-xs text-muted">
            添加服务商渠道，填入 API Key 和模型名称即可。配置会自动同步到 .env 文件。
          </p>
        </div>
        <span className="text-xs text-muted">{isCollapsed ? '▶ 展开' : '▼ 收起'}</span>
      </button>

      {!isCollapsed && (
        <div className="mt-4 space-y-5">
          {/* --- Add Channel --- */}
          <div className="flex items-center gap-2">
            <button type="button" className="btn-secondary whitespace-nowrap" disabled={busy} onClick={addChannel}>
              + 添加渠道
            </button>
            <Select
              value={addPreset}
              onChange={setAddPreset}
              options={Object.entries(CHANNEL_PRESETS).map(([value, preset]) => ({
                value,
                label: preset.label,
              }))}
              disabled={busy}
              placeholder="选择服务商"
              className="flex-1"
            />
          </div>

          {/* --- Channel List --- */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between px-1">
              <span className="text-xs font-medium text-muted uppercase tracking-wider">渠道列表</span>
              {channels.length > 0 && (
                <span className="text-[10px] text-muted">{channels.filter(c => c.enabled).length}/{channels.length} 已启用</span>
              )}
            </div>

          {channels.length === 0 ? (
            <div className="rounded-lg border border-dashed border-white/10 bg-card/20 px-4 py-6 text-center text-xs text-muted">
              还没有渠道，选择服务商后点击「添加渠道」
            </div>
          ) : channels.map((channel, index) => (
            <ChannelRow
              key={index}
              channel={channel}
              index={index}
              busy={busy}
              visibleKey={Boolean(visibleKeys[index])}
              expanded={Boolean(expandedRows[index])}
              testState={testStates[index]}
              onUpdate={updateChannel}
              onRemove={removeChannel}
              onToggleExpand={toggleExpand}
              onToggleKeyVisibility={toggleKeyVisibility}
              onTest={(ch, idx) => void handleTest(ch, idx)}
            />
          ))}
          </div>

          {managesRuntimeConfig ? (
            <div className="rounded-lg border border-white/8 bg-card/30 p-3">
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <span className="text-xs font-medium text-muted uppercase tracking-wider">运行时参数</span>
                  <p className="mt-0.5 text-[11px] text-secondary">留空时自动推断</p>
                </div>
              </div>

              <div className="mb-4">
                <label className="mb-1 block text-xs text-muted">Temperature</label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min="0"
                    max="2"
                    step="0.1"
                    value={runtimeConfig.temperature}
                    disabled={busy}
                    onChange={(event) => setRuntimeConfig((previous) => ({ ...previous, temperature: event.target.value }))}
                    className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-white/10 accent-cyan"
                  />
                  <span className="w-8 text-right text-sm text-secondary">{runtimeConfig.temperature}</span>
                </div>
                <p className="mt-1 text-[11px] text-secondary">
                  控制模型输出随机性，0 为确定性输出，2 为最大随机性，推荐 0.7。
                </p>
              </div>

              {availableModels.length === 0 ? (
                <div className="rounded-lg border border-dashed border-white/10 bg-card/20 px-3 py-2 text-xs text-muted">
                  先添加至少一个已启用渠道并填写模型，下面的主模型 / fallback / Vision 选项才会出现。
                </div>
              ) : (
                <div className="space-y-4">
                  <div>
                    <label className="mb-1 block text-xs text-muted">主模型</label>
                    <Select
                      value={runtimeConfig.primaryModel}
                      onChange={setPrimaryModel}
                      options={buildModelOptions(availableModels, runtimeConfig.primaryModel, '自动（使用第一个可用模型）')}
                      disabled={busy}
                      placeholder=""
                    />
                  </div>

                  <div>
                    <label className="mb-2 block text-xs text-muted">Fallback 模型</label>
                    <div className="space-y-2 rounded-lg border border-white/8 bg-card/20 p-3">
                      {availableModels.map((model) => (
                        <label key={model} className="flex items-center gap-2 text-sm text-secondary">
                          <input
                            type="checkbox"
                            checked={runtimeConfig.fallbackModels.includes(model)}
                            disabled={busy || model === runtimeConfig.primaryModel}
                            onChange={() => toggleFallbackModel(model)}
                          />
                          <span>{model}</span>
                        </label>
                      ))}
                    </div>
                    <p className="mt-1 text-[11px] text-secondary">
                      Fallback 只会在主模型失败时使用。主模型不会重复加入 fallback。
                    </p>
                  </div>

                  <div>
                    <label className="mb-1 block text-xs text-muted">Vision 模型</label>
                    <Select
                      value={runtimeConfig.visionModel}
                      onChange={(value) => setRuntimeConfig((previous) => ({ ...previous, visionModel: value }))}
                      options={buildModelOptions(availableModels, runtimeConfig.visionModel, '自动（跟随 Vision 默认逻辑）')}
                      disabled={busy}
                      placeholder=""
                    />
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
              当前已启用 `LITELLM_CONFIG`，主模型 / fallback / Vision / Temperature 继续在下方通用字段中管理；
              这里仅保存渠道条目，不会覆盖 YAML 运行时选择。
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn-primary"
              disabled={busy || !hasChanges}
              onClick={() => void handleSave()}
            >
              {isSaving ? '保存中...' : managesRuntimeConfig ? '保存 AI 配置' : '保存渠道配置'}
            </button>
            {!hasChanges ? (
              <span className="text-xs text-muted">当前没有未保存的改动</span>
            ) : null}
          </div>

          {saveMessage?.type === 'success' ? (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
              {saveMessage.text}
            </div>
          ) : null}

          {saveMessage?.type === 'local-error' ? (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
              {saveMessage.text}
            </div>
          ) : null}

          {saveMessage?.type === 'error' ? (
            <ApiErrorAlert error={saveMessage.error} />
          ) : null}
        </div>
      )}
    </div>
  );
};
