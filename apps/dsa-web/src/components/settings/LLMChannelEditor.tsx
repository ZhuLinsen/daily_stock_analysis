import { useEffect, useMemo, useRef, useState } from 'react';
import type React from 'react';
import { getParsedApiError } from '../../api/error';
import { systemConfigApi } from '../../api/systemConfig';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiLanguage } from '../../i18n/uiText';
import type { LLMApiSurface, LLMCapabilityCheck, LLMCapabilityCheckResult } from '../../types/systemConfig';
import { ApiErrorAlert, Badge, Button, InlineAlert, Input, Select, StatusDot, Tooltip } from '../common';
import type { ChannelProtocol } from './llmProviderTemplates';
import {
  LLM_PROVIDER_TEMPLATES,
  MODELFLARE_DEFAULT_MODEL,
  MODEL_PLACEHOLDERS_BY_PROTOCOL,
  filterDiscoveredTextModels,
  getProviderCapabilityMeta,
  getProviderTemplate,
  getProviderTemplateConfigHint,
  getProviderTemplateLabel,
  getProviderTemplateOfficialSources,
  getProviderTemplateRegistration,
  isKnownProviderTemplate,
} from './llmProviderTemplates';
import { LLM_CHANNEL_EDITOR_TEXT, type LlmChannelEditorLocale } from './llmChannelEditorText';
import { SettingsHelpButton } from './SettingsHelpButton';

const PROTOCOL_OPTIONS: Array<{ value: ChannelProtocol; label: string }> = [
  { value: 'openai', label: 'OpenAI Compatible' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'vertex_ai', label: 'Vertex AI' },
  { value: 'ollama', label: 'Ollama' },
];

const CHANNEL_FIELD_SUFFIXES = ['PROTOCOL', 'API_SURFACE', 'BASE_URL', 'API_KEY', 'API_KEYS', 'MODELS', 'EXTRA_HEADERS', 'ENABLED'] as const;
const CHANNEL_FIELD_KEY_PATTERN = /^LLM_([A-Z0-9_]+)_(PROTOCOL|API_SURFACE|BASE_URL|API_KEY|API_KEYS|MODELS|EXTRA_HEADERS|ENABLED)$/;
const FALSEY_VALUES = new Set(['0', 'false', 'no', 'off']);
const HERMES_CHANNEL_NAME = 'hermes';
const HERMES_DEFAULT_MODEL = 'hermes-agent';

const isHermesChannel = (channel: Pick<ChannelConfig, 'name'>): boolean => (
  channel.name.trim().toLowerCase() === HERMES_CHANNEL_NAME
);

function canonicalizeHermesRouteModel(model: string): string {
  const trimmed = model.trim() || HERMES_DEFAULT_MODEL;
  return trimmed.startsWith('openai/') ? trimmed : `openai/${trimmed}`;
}

function routeIdentityCandidates(model: string): Set<string> {
  const trimmed = model.trim();
  if (!trimmed) return new Set();
  const candidates = new Set<string>([trimmed]);
  if (!trimmed.startsWith('openai/') && !trimmed.includes('/')) {
    candidates.add(`openai/${trimmed}`);
  }
  return candidates;
}

function getRouteProvenance(
  routeProvenanceMap: Map<string, RouteProvenance>,
  model: string,
): RouteProvenance | undefined {
  for (const candidate of routeIdentityCandidates(model)) {
    const origin = routeProvenanceMap.get(candidate);
    if (origin) return origin;
  }
  return undefined;
}

const shouldUseSavedHermesSecret = (
  channel: Pick<ChannelConfig, 'name' | 'apiKey'>,
  maskToken: string,
  hasPersistedSecret: boolean,
): boolean => (
  isHermesChannel(channel) && channel.apiKey === maskToken && hasPersistedSecret
);

const hasRuntimeOnlyMaskedHermesSecret = (
  channel: Pick<ChannelConfig, 'name' | 'apiKey'>,
  maskToken: string,
  hasPersistedSecret: boolean,
): boolean => (
  isHermesChannel(channel) && channel.apiKey === maskToken && !hasPersistedSecret
);

interface ChannelConfig {
  id: string;
  name: string;
  protocol: ChannelProtocol;
  apiSurface: string;
  baseUrl: string;
  apiKey: string;
  models: string;
  enabled: boolean;
}

type LocalValidationMessageKey =
  | 'validationEmptyChannelName'
  | 'validationMixedHermesRoute'
  | 'validationNonCanonicalRouteAlias'
  | 'validationInvalidPrimaryModel'
  | 'validationInvalidAgentPrimaryModel'
  | 'validationInvalidFallbackModel'
  | 'validationInvalidVisionModel';

type SaveSuccessMessageKey = 'saveSuccessAi' | 'saveSuccessChannels';

interface ChannelTestState {
  status: 'idle' | 'loading' | 'success' | 'error';
  resolveText?: (locale: LlmChannelEditorLocale, lang: UiLanguage) => string;
  resolveHint?: (locale: LlmChannelEditorLocale) => string | undefined;
}

interface ChannelDiscoveryState {
  status: 'idle' | 'loading' | 'success' | 'error';
  resolveText?: (locale: LlmChannelEditorLocale, lang: UiLanguage) => string;
  resolveHint?: (locale: LlmChannelEditorLocale) => string | undefined;
  models: string[];
}

interface ChannelCapabilityState {
  selected: LLMCapabilityCheck[];
  status: 'idle' | 'loading' | 'success' | 'error';
  resolveText?: (locale: LlmChannelEditorLocale, lang: UiLanguage) => string;
  resolveHint?: (locale: LlmChannelEditorLocale) => string | undefined;
  results: Partial<Record<LLMCapabilityCheck, LLMCapabilityCheckResult>>;
}

interface RuntimeConfig {
  primaryModel: string;
  agentPrimaryModel: string;
  fallbackModels: string[];
  visionModel: string;
  temperature: string;
}

interface LLMChannelEditorProps {
  items: Array<{ key: string; value: string; rawValueExists?: boolean }>;
  configVersion: string;
  maskToken: string;
  modelProviderPrefixes?: string[];
  onSaved: (updatedItems: Array<{ key: string; value: string }>) => void | Promise<void>;
  onDraftItemsChange?: (items: Array<{ key: string; value: string }>) => void;
  onDirtyChange?: (dirty: boolean) => void;
  onSavingChange?: (saving: boolean) => void;
  draftResetToken?: number;
  llmYamlActive?: boolean;
  disabled?: boolean;
}

/** Return a shallow copy without `channelId`, preserving identity when absent. */
function omitChannelStateKey<T>(
  previous: Record<string, T>,
  channelId: string,
): Record<string, T> {
  if (!(channelId in previous)) {
    return previous;
  }
  const next = { ...previous };
  delete next[channelId];
  return next;
}

interface ChannelRowProps {
  channel: ChannelConfig;
  index: number;
  busy: boolean;
  visibleKey: boolean;
  expanded: boolean;
  testState?: ChannelTestState;
  discoveryState?: ChannelDiscoveryState;
  capabilityState?: ChannelCapabilityState;
  modelProviderPrefixes: ReadonlySet<string>;
  onUpdate: (index: number, field: keyof ChannelConfig, value: string | boolean) => void;
  onRemove: (index: number) => void;
  onToggleExpand: (channelId: string) => void;
  onToggleKeyVisibility: (channelId: string, nextVisible: boolean) => void;
  onTest: (channel: ChannelConfig) => void;
  onDiscoverModels: (channel: ChannelConfig) => void;
  onToggleCapability: (channel: ChannelConfig, capability: LLMCapabilityCheck) => void;
  onCheckCapabilities: (channel: ChannelConfig) => void;
}

function HelpLabel({
  htmlFor,
  label,
  fieldKey,
  helpKey,
  examples,
  compact = false,
}: {
  htmlFor?: string;
  label: string;
  fieldKey: string;
  helpKey: string;
  examples?: string[];
  compact?: boolean;
}) {
  const { language } = useUiLanguage();
  const helpDocs = LLM_CHANNEL_EDITOR_TEXT[language].helpDocs;

  return (
    <div className={compact ? 'mb-1 flex items-center gap-1.5' : 'mb-2 flex items-center gap-1.5'}>
      <label
        htmlFor={htmlFor}
        className={compact ? 'text-xs text-muted-text' : 'text-sm font-medium text-foreground'}
      >
        {label}
      </label>
      <SettingsHelpButton
        fieldKey={fieldKey}
        title={label}
        helpKey={helpKey}
        examples={examples}
        docs={helpDocs}
      />
    </div>
  );
}

function parseChannelFieldKeys(channel: ChannelConfig): string[] {
  const upperName = channel.name.trim().toUpperCase();
  return [
    `LLM_${upperName}_PROTOCOL`,
    `LLM_${upperName}_API_SURFACE`,
    `LLM_${upperName}_BASE_URL`,
    `LLM_${upperName}_ENABLED`,
    `LLM_${upperName}_API_KEY`,
    `LLM_${upperName}_API_KEYS`,
    `LLM_${upperName}_MODELS`,
    `LLM_${upperName}_EXTRA_HEADERS`,
  ];
}

function parseChannelFieldKeysFromName(name: string): string[] {
  const upperName = name.trim().toUpperCase();
  return CHANNEL_FIELD_SUFFIXES.map((suffix) => `LLM_${upperName}_${suffix}`);
}

function isChannelSecretFieldKey(key: string): boolean {
  const match = CHANNEL_FIELD_KEY_PATTERN.exec(key.toUpperCase());
  return match?.[2] === 'API_KEY' || match?.[2] === 'API_KEYS';
}

function resolveInitialChannelApiKeySource(
  channelName: string,
  initialItemValueByKey: Map<string, string>,
  initialItemSourceByKey: Map<string, boolean>,
): boolean | undefined {
  const upperName = channelName.trim().toUpperCase();
  const apiKeysKey = `LLM_${upperName}_API_KEYS`;
  const apiKeyKey = `LLM_${upperName}_API_KEY`;

  const apiKeysValue = (initialItemValueByKey.get(apiKeysKey) || '').trim();
  const apiKeyValue = (initialItemValueByKey.get(apiKeyKey) || '').trim();

  if (channelName.trim().toLowerCase() === HERMES_CHANNEL_NAME && apiKeyValue && initialItemSourceByKey.has(apiKeyKey)) {
    return initialItemSourceByKey.get(apiKeyKey);
  }
  if (apiKeysValue && initialItemSourceByKey.has(apiKeysKey)) {
    return initialItemSourceByKey.get(apiKeysKey);
  }
  if (apiKeyValue && initialItemSourceByKey.has(apiKeyKey)) {
    return initialItemSourceByKey.get(apiKeyKey);
  }

  if (apiKeyValue) {
    return initialItemSourceByKey.get(apiKeyKey);
  }
  if (apiKeysValue) {
    return initialItemSourceByKey.get(apiKeysKey);
  }
  if (upperName === 'MODELFLARE' && initialItemValueByKey.get('MODELFLARE_KEY')) {
    return initialItemSourceByKey.get('MODELFLARE_KEY');
  }
  return initialItemSourceByKey.get(apiKeysKey) ?? initialItemSourceByKey.get(apiKeyKey);
}

function resolveInitialChannelApiKeyValue(
  channelName: string,
  itemValueByKey: Map<string, string>,
  itemSourceByKey: Map<string, boolean>,
): string {
  const upperName = channelName.trim().toUpperCase();
  const apiKeysKey = `LLM_${upperName}_API_KEYS`;
  const apiKeyKey = `LLM_${upperName}_API_KEY`;

  const apiKeysValue = (itemValueByKey.get(apiKeysKey) || '').trim();
  const apiKeyValue = (itemValueByKey.get(apiKeyKey) || '').trim();

  if (channelName.trim().toLowerCase() === HERMES_CHANNEL_NAME && apiKeyValue) {
    return apiKeyValue;
  }
  if (apiKeysValue && itemSourceByKey.has(apiKeysKey)) {
    return apiKeysValue;
  }
  if (apiKeyValue && itemSourceByKey.has(apiKeyKey)) {
    return apiKeyValue;
  }
  if (apiKeysValue) {
    return apiKeysValue;
  }
  if (apiKeyValue) {
    return apiKeyValue;
  }
  if (upperName === 'MODELFLARE') {
    return itemValueByKey.get('MODELFLARE_KEY') || '';
  }
  return itemValueByKey.get(apiKeysKey) || itemValueByKey.get(apiKeyKey) || '';
}

function buildChangedItemKeys(
  channels: ChannelConfig[],
  initialChannels: ChannelConfig[],
  initialItemSourceByKey: Map<string, boolean>,
  initialItemValueByKey: Map<string, string>,
): Set<string> {
  const changedKeys = new Set<string>();
  const nextChannelNames = channels.map((channel) => channel.name.trim().toLowerCase()).join(',');
  const previousChannelNames = initialChannels.map((channel) => channel.name.trim().toLowerCase()).join(',');

  if (nextChannelNames !== previousChannelNames) {
    changedKeys.add('LLM_CHANNELS');
  }

  const maxLength = Math.max(channels.length, initialChannels.length);
  for (let index = 0; index < maxLength; index += 1) {
    const current = channels[index];
    const previous = initialChannels[index];
    if (!current && !previous) {
      continue;
    }

    if (!current) {
      const previousKeys = parseChannelFieldKeys(previous);
      for (const key of previousKeys) {
        if (initialItemSourceByKey.get(key.toUpperCase()) !== false) {
          changedKeys.add(key);
        }
      }
      continue;
    }

    if (!previous) {
      for (const key of parseChannelFieldKeys(current)) {
        changedKeys.add(key);
      }
      continue;
    }

    const currentName = current.name.trim().toUpperCase();
    const previousName = previous.name.trim().toUpperCase();
    if (currentName !== previousName) {
      const previousApiKeySource = resolveInitialChannelApiKeySource(
        previous.name,
        initialItemValueByKey,
        initialItemSourceByKey,
      );
      const preserveRuntimeOnlySecret = previousApiKeySource === false && current.apiKey === previous.apiKey;
      const previousKeys = parseChannelFieldKeys(previous);
      for (const key of previousKeys) {
        if (initialItemSourceByKey.get(key.toUpperCase()) !== false) {
          changedKeys.add(key);
        }
      }

      for (const key of parseChannelFieldKeys(current)) {
        if (preserveRuntimeOnlySecret && isChannelSecretFieldKey(key)) {
          continue;
        }
        changedKeys.add(key);
      }
      continue;
    }

    const prefix = `LLM_${currentName}`;
    if (current.protocol !== previous.protocol) {
      changedKeys.add(`${prefix}_PROTOCOL`);
    }
    if (current.apiSurface !== previous.apiSurface) {
      changedKeys.add(`${prefix}_API_SURFACE`);
    }
    if (current.baseUrl !== previous.baseUrl) {
      changedKeys.add(`${prefix}_BASE_URL`);
    }
    if (current.enabled !== previous.enabled) {
      changedKeys.add(`${prefix}_ENABLED`);
    }
    if (current.apiKey !== previous.apiKey) {
      changedKeys.add(`${prefix}_API_KEY`);
      changedKeys.add(`${prefix}_API_KEYS`);
    }
    if (current.models !== previous.models) {
      changedKeys.add(`${prefix}_MODELS`);
    }
  }

  return changedKeys;
}

const ChannelRow: React.FC<ChannelRowProps> = ({
  channel,
  index,
  busy,
  visibleKey,
  expanded,
  testState,
  discoveryState,
  capabilityState,
  modelProviderPrefixes,
  onUpdate,
  onRemove,
  onToggleExpand,
  onToggleKeyVisibility,
  onTest,
  onDiscoverModels,
  onToggleCapability,
  onCheckCapabilities,
}) => {
  const { language } = useUiLanguage();
  const text = LLM_CHANNEL_EDITOR_TEXT[language];
  const preset = getProviderTemplate(channel.name);
  const showProviderTemplateDetails = isKnownProviderTemplate(channel.name);
  const displayName = preset ? getProviderTemplateLabel(preset, language) : channel.name;
  const providerCapabilities = showProviderTemplateDetails ? (preset?.capabilities || []) : [];
  const providerSources = showProviderTemplateDetails && preset ? getProviderTemplateOfficialSources(preset, language) : [];
  const providerHint = showProviderTemplateDetails && preset ? getProviderTemplateConfigHint(preset, language) : undefined;
  const selectedModels = splitModels(channel.models);
  const runtimeCapabilityOptions = isHermesChannel(channel)
    ? text.runtimeCapabilityOptions.filter((option) => option.value === 'json')
    : text.runtimeCapabilityOptions;
  const discoveredModels = filterDiscoveredTextModels(discoveryState?.models || []);
  const manualOnlyModels = selectedModels.filter(
    (model) => !discoveredModels.some((discoveredModel) => (
      areModelsEquivalent(model, discoveredModel, channel.protocol, modelProviderPrefixes, channel.baseUrl)
    )),
  );
  const modelCount = selectedModels.length;
  const hasKey = channel.apiKey.length > 0;
  const statusVariant = testState?.status === 'success'
    ? 'success'
    : testState?.status === 'error'
      ? 'danger'
      : testState?.status === 'loading'
        ? 'warning'
        : 'default';
  const selectedCapabilities = capabilityState?.selected || [];
  const capabilityResults = capabilityState?.results || {};
  const capabilityBusy = capabilityState?.status === 'loading';
  const discoveryText = discoveryState?.resolveText?.(text, language);
  const discoveryHint = discoveryState?.resolveHint?.(text);
  const testText = testState?.resolveText?.(text, language);
  const testHint = testState?.resolveHint?.(text);
  const capabilityText = capabilityState?.resolveText?.(text, language);
  const capabilityHint = capabilityState?.resolveHint?.(text);
  const channelNameInputId = `llm-channel-${channel.id}-name`;
  const protocolInputId = `llm-channel-${channel.id}-protocol`;
  const apiSurfaceInputId = `llm-channel-${channel.id}-api-surface`;
  const baseUrlInputId = `llm-channel-${channel.id}-base-url`;
  const apiKeyInputId = `llm-channel-${channel.id}-api-key`;
  const modelsInputId = `llm-channel-${channel.id}-models`;
  const apiSurfaceOptions = text.apiSurfaceOptions.some((option) => option.value === channel.apiSurface)
    ? text.apiSurfaceOptions
    : [
        { value: channel.apiSurface, label: text.invalidApiSurfaceOption(channel.apiSurface) },
        ...text.apiSurfaceOptions,
      ];

  return (
    <div className="mb-2 overflow-hidden rounded-xl border border-[var(--settings-border)] bg-[var(--settings-surface)] shadow-soft-card transition-[background-color,border-color,box-shadow] duration-200 hover:border-[var(--settings-border-strong)] hover:bg-[var(--settings-surface-hover)]">
      <div
        className="flex cursor-pointer select-none items-center gap-2.5 px-4 py-3 transition-colors"
        onClick={() => onToggleExpand(channel.id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggleExpand(channel.id);
          }
        }}
        role="button"
        tabIndex={0}
      >
        <span className={`w-4 shrink-0 text-[11px] text-muted-text transition-transform ${expanded ? 'rotate-90' : ''}`}>▶</span>

        <input
          type="checkbox"
          checked={channel.enabled}
          disabled={busy}
          className="settings-input-checkbox h-4 w-4 shrink-0 rounded border-border/70 bg-base"
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => onUpdate(index, 'enabled', e.target.checked)}
        />

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-foreground">{displayName}</span>
            <Badge variant="info" className="hidden sm:inline-flex">
              {channel.protocol}
            </Badge>
          </div>
          <p className="mt-0.5 truncate text-[11px] text-secondary-text">
            {modelCount > 0 ? text.modelCountConfigured(modelCount) : text.modelCountEmpty}
          </p>
        </div>

        <span className="flex shrink-0 items-center gap-2">
          {testState?.status === 'success' ? (
            <Tooltip content={text.statusConnected}>
              <span className="inline-flex">
                <StatusDot tone="success" />
              </span>
            </Tooltip>
          ) : null}
          {testState?.status === 'error' ? (
            <Tooltip content={text.statusConnectionFailed}>
              <span className="inline-flex">
                <StatusDot tone="danger" />
              </span>
            </Tooltip>
          ) : null}
          {testState?.status === 'loading' ? (
            <Tooltip content={text.statusTesting}>
              <span className="inline-flex">
                <StatusDot tone="warning" pulse />
              </span>
            </Tooltip>
          ) : null}
          {!hasKey && channel.protocol !== 'ollama' ? <Badge variant="warning">{text.missingKeyBadge}</Badge> : null}
          {testState?.status !== 'idle' ? (
            <Badge variant={statusVariant}>
              {testState?.status === 'success'
                ? text.statusConnected
                : testState?.status === 'error'
                  ? text.statusConnectionFailed
                  : text.statusTesting}
            </Badge>
          ) : null}
        </span>

        <Tooltip content={text.removeChannelTooltip}>
          <span className="inline-flex">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 shrink-0 px-2 text-xs text-muted-text hover:text-rose-300"
              disabled={busy}
              onClick={(e) => {
                e.stopPropagation();
                onRemove(index);
              }}
            >
              ✕
            </Button>
          </span>
        </Tooltip>
      </div>

      {expanded ? (
        <div className="settings-surface-overlay-soft space-y-4 px-4 py-4">
          <div className="grid gap-2 sm:grid-cols-3">
            <div>
              <HelpLabel
                htmlFor={channelNameInputId}
                label={text.channelNameLabel}
                fieldKey="LLM_CHANNEL_NAME"
                helpKey="settings.llm_channel.channel_name"
                examples={['LLM_CHANNELS=deepseek,aihubmix', 'LLM_DEEPSEEK_MODELS=deepseek-flash,deepseek-v4-pro']}
              />
            <Input
              id={channelNameInputId}
              value={channel.name}
              disabled={busy}
              onChange={(e) => onUpdate(index, 'name', e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
              placeholder="primary"
            />
            </div>
            <div className="space-y-2">
              <HelpLabel
                htmlFor={protocolInputId}
                label={text.protocolLabel}
                fieldKey="LLM_CHANNEL_PROTOCOL"
                helpKey="settings.llm_channel.protocol"
                examples={['LLM_DEEPSEEK_PROTOCOL=deepseek', 'LLM_OPENROUTER_PROTOCOL=openai']}
              />
              <Select
                id={protocolInputId}
                value={channel.protocol}
                onChange={(v) => onUpdate(index, 'protocol', normalizeProtocol(v))}
                options={PROTOCOL_OPTIONS}
                disabled={busy}
                placeholder={text.protocolPlaceholder}
              />
            </div>
            <div className="space-y-2">
              <HelpLabel
                htmlFor={apiSurfaceInputId}
                label={text.apiSurfaceLabel}
                fieldKey="LLM_CHANNEL_API_SURFACE"
                helpKey="settings.llm_channel.api_surface"
                examples={['LLM_ANSPIRE_API_SURFACE=responses', 'LLM_OPENAI_API_SURFACE=chat_completions']}
              />
              <Select
                id={apiSurfaceInputId}
                value={channel.apiSurface}
                onChange={(value) => onUpdate(index, 'apiSurface', value)}
                options={apiSurfaceOptions}
                disabled={busy || (isHermesChannel(channel) && channel.apiSurface === 'chat_completions')}
                placeholder={text.apiSurfacePlaceholder}
              />
            </div>
          </div>

          <div>
            <HelpLabel
              htmlFor={baseUrlInputId}
              label={text.baseUrlLabel}
              fieldKey="LLM_CHANNEL_BASE_URL"
              helpKey="settings.llm_channel.base_url"
              examples={['LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com', 'LLM_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1']}
            />
          <Input
            id={baseUrlInputId}
            value={channel.baseUrl}
            disabled={busy}
            onChange={(e) => onUpdate(index, 'baseUrl', e.target.value)}
            placeholder={
              channel.protocol === 'gemini' || channel.protocol === 'anthropic'
                ? text.baseUrlOfficialPlaceholder
                : preset?.baseUrl || 'https://api.example.com/v1'
            }
          />
          </div>

          {showProviderTemplateDetails ? (
            <div className="space-y-2 rounded-xl border border-[var(--settings-border)] bg-[var(--settings-surface-hover)] p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-medium text-muted-text">{text.configReferenceTitle}</span>
                {providerCapabilities.map((capability) => {
                  const capabilityMeta = getProviderCapabilityMeta(capability, language);
                  return (
                    <Tooltip key={capability} content={capabilityMeta.hint}>
                      <span className="inline-flex">
                        <Badge variant="default" className="border-[var(--settings-border)] bg-[var(--settings-surface)] text-secondary-text">
                          {capabilityMeta.label}
                        </Badge>
                      </span>
                    </Tooltip>
                  );
                })}
              </div>
              {providerHint ? (
                <p className="text-[11px] leading-5 text-secondary-text">{providerHint}</p>
              ) : null}
              {providerSources.length > 0 ? (
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] leading-5 text-secondary-text">
                  <span>{text.officialSourcesPrefix}</span>
                  {providerSources.map((source) => (
                    <a
                      key={source.url}
                      href={source.url}
                      target="_blank"
                      rel="noreferrer"
                      className="settings-accent-text underline-offset-2 hover:underline"
                    >
                      {source.label}
                    </a>
                  ))}
                </p>
              ) : null}
              <p className="text-[11px] leading-5 text-muted-text">
                {text.capabilityReferenceDisclaimer}
              </p>
            </div>
          ) : null}

          <div>
            <HelpLabel
              htmlFor={apiKeyInputId}
              label={text.apiKeyLabel}
              fieldKey="LLM_CHANNEL_API_KEY"
              helpKey="settings.llm_channel.api_key"
              examples={['LLM_DEEPSEEK_API_KEY=sk-xxxx', 'LLM_OPENAI_API_KEYS=sk-key-1,sk-key-2']}
            />
          <Input
            id={apiKeyInputId}
            type="password"
            allowTogglePassword
            iconType="key"
            passwordVisible={visibleKey}
            onPasswordVisibleChange={(nextVisible) => onToggleKeyVisibility(channel.id, nextVisible)}
            value={channel.apiKey}
            disabled={busy}
            onChange={(e) => onUpdate(index, 'apiKey', e.target.value)}
            placeholder={channel.protocol === 'ollama' ? text.apiKeyOllamaPlaceholder : text.apiKeyMultiPlaceholder}
          />
          </div>

          <div className="space-y-3 rounded-xl border border-[var(--settings-border)] bg-[var(--settings-surface-hover)] p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="settings-secondary"
                size="sm"
                className="px-3 text-[11px] shadow-none"
                disabled={busy}
                onClick={() => onDiscoverModels(channel)}
              >
                {discoveryState?.status === 'loading' ? text.fetchModelsLoading : text.fetchModelsButton}
              </Button>
              <span className={`text-xs ${
                discoveryState?.status === 'success'
                  ? 'text-success'
                  : discoveryState?.status === 'error'
                    ? 'text-danger'
                    : 'text-muted-text'
              }`}
              >
                {discoveryText || text.discoveryDefaultHint}
              </span>
            </div>
            {discoveryHint ? (
              <p className="text-[11px] text-secondary-text">
                {discoveryHint}
              </p>
            ) : null}

            {discoveredModels.length > 0 ? (
              <div>
                <HelpLabel
                  label={text.discoveredModelsLabel}
                  fieldKey="LLM_CHANNEL_DISCOVERED_MODELS"
                  helpKey="settings.llm_channel.models"
                  examples={['LLM_DEEPSEEK_MODELS=deepseek-flash,deepseek-v4-pro']}
                />
                <div className="max-h-48 space-y-2 overflow-y-auto rounded-xl border border-[var(--settings-border)] bg-[var(--settings-surface)] p-3">
                  {discoveredModels.map((model) => (
                    <label key={model} className="flex items-center gap-2 text-sm text-secondary-text">
                      <input
                        type="checkbox"
                        checked={selectedModels.some((selectedModel) => (
                          areModelsEquivalent(selectedModel, model, channel.protocol, modelProviderPrefixes, channel.baseUrl)
                        ))}
                        disabled={busy}
                        onChange={() => onUpdate(
                          index,
                          'models',
                          toggleModelSelection(channel.models, model, channel.protocol, modelProviderPrefixes, channel.baseUrl),
                        )}
                        className="settings-input-checkbox h-4 w-4 rounded border-border/70 bg-base"
                      />
                      <span>{model}</span>
                    </label>
                  ))}
                </div>
              </div>
            ) : null}

            <div>
              <HelpLabel
                htmlFor={modelsInputId}
                label={discoveredModels.length > 0 ? text.manualModelsLabelWithDiscovery : text.manualModelsLabelDefault}
                fieldKey="LLM_CHANNEL_MODELS"
                helpKey="settings.llm_channel.models"
                examples={['LLM_DEEPSEEK_MODELS=deepseek-flash,deepseek-v4-pro', 'LLM_OLLAMA_MODELS=qwen3:8b,llama3.1:8b']}
              />
            <Input
              id={modelsInputId}
              value={channel.models}
              disabled={busy}
              onChange={(e) => onUpdate(index, 'models', e.target.value)}
              placeholder={preset?.placeholderModels || MODEL_PLACEHOLDERS_BY_PROTOCOL[channel.protocol]}
              hint={
                discoveredModels.length > 0
                  ? text.manualModelsHintWithDiscovery
                  : text.manualModelsHintDefault
              }
            />
            </div>

            {manualOnlyModels.length > 0 ? (
              <p className="text-[11px] text-secondary-text">
                {text.extraManualModelsPrefix}{manualOnlyModels.join(text.listSeparator)}
              </p>
            ) : null}
          </div>

          <div className="flex items-center gap-2 pt-1">
            <Button
              type="button"
              variant="settings-secondary"
              size="sm"
              className="px-3 text-[11px] shadow-none"
              disabled={busy}
              onClick={() => onTest(channel)}
            >
              {testState?.status === 'loading' ? text.testConnectionLoading : text.testConnectionButton}
            </Button>
            {testText ? (
              <div className="space-y-1">
                <span className={`block text-xs ${
                  testState?.status === 'success'
                    ? 'text-success'
                    : testState?.status === 'error'
                      ? 'text-danger'
                      : 'text-muted-text'
                }`}
                >
                  {testText}
                </span>
                {selectedModels[0] ? (
                  <p className="text-[11px] text-secondary-text">
                    {text.firstModelTestNote(selectedModels[0])}
                  </p>
                ) : null}
                {testHint ? (
                  <p className="text-[11px] text-secondary-text">
                    {testHint}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="space-y-3 rounded-xl border border-[var(--settings-border)] bg-[var(--settings-surface-hover)] p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="flex items-center gap-1.5">
                  <p className="text-[11px] font-medium text-muted-text">{text.capabilitySectionTitle}</p>
                  <SettingsHelpButton
                    fieldKey="LLM_CHANNEL_CAPABILITY_CHECKS"
                    title={text.capabilityHelpTitle}
                    helpKey="settings.llm_channel.capability_checks"
                    examples={['JSON / Tools / Stream / Vision']}
                    docs={text.helpDocs}
                  />
                </div>
                <p className="mt-0.5 text-[11px] text-secondary-text">
                  {text.capabilitySectionDesc}
                </p>
              </div>
              <Button
                type="button"
                variant="settings-secondary"
                size="sm"
                className="px-3 text-[11px] shadow-none"
                disabled={busy || capabilityBusy || selectedCapabilities.length === 0}
                onClick={() => onCheckCapabilities(channel)}
              >
                {capabilityBusy ? text.capabilityCheckLoading : text.capabilityCheckButton}
              </Button>
            </div>

            <div className="flex flex-wrap gap-2">
              {runtimeCapabilityOptions.map((option) => (
                <Tooltip key={option.value} content={option.hint}>
                  <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--settings-border)] bg-[var(--settings-surface)] px-2 py-1 text-[11px] text-secondary-text">
                    <input
                      type="checkbox"
                      checked={selectedCapabilities.includes(option.value)}
                      disabled={busy || capabilityBusy}
                      onChange={() => onToggleCapability(channel, option.value)}
                      className="settings-input-checkbox h-3.5 w-3.5 rounded border-border/70 bg-base"
                    />
                    <span>{option.label}</span>
                  </label>
                </Tooltip>
              ))}
            </div>

            {capabilityText ? (
              <div className="space-y-1">
                <p className={`text-xs ${
                  capabilityState?.status === 'success'
                    ? 'text-success'
                    : capabilityState?.status === 'error'
                      ? 'text-danger'
                      : 'text-muted-text'
                }`}
                >
                  {capabilityText}
                </p>
                {capabilityHint ? (
                  <p className="text-[11px] text-secondary-text">{capabilityHint}</p>
                ) : null}
              </div>
            ) : null}

            {Object.keys(capabilityResults).length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {runtimeCapabilityOptions.map((option) => {
                  const result = capabilityResults[option.value];
                  if (!result) return null;
                  return (
                    <Tooltip key={option.value} content={result.message}>
                      <span className="inline-flex">
                        <Badge variant={getCapabilityResultVariant(result.status)}>
                          {option.label} {text.capabilityStatusLabels[result.status]}
                        </Badge>
                      </span>
                    </Tooltip>
                  );
                })}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
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

  if (isVendorModelGatewayBaseUrl(baseUrl)) {
    return 'openai';
  }

  const firstPrefixedModel = models.find((model) => model.includes('/'));
  if (firstPrefixedModel) {
    return normalizeProtocol(firstPrefixedModel.split('/', 1)[0]);
  }

  if (baseUrl.includes('127.0.0.1') || baseUrl.includes('localhost')) {
    return 'openai';
  }

  return 'openai';
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

interface ParsedModelRef {
  name: string;
  provider: string;
  hasProvider: boolean;
}

function parseModelRef(model: string): ParsedModelRef {
  const trimmed = model.trim();
  if (!trimmed) {
    return { name: '', provider: '', hasProvider: false };
  }

  const delimiterIndex = trimmed.indexOf('/');
  if (delimiterIndex < 0) {
    return { name: trimmed.toLowerCase(), provider: '', hasProvider: false };
  }

  const rawProvider = trimmed.slice(0, delimiterIndex).trim();
  const name = trimmed.slice(delimiterIndex + 1).trim();
  if (!rawProvider || !name) {
    return { name: '', provider: '', hasProvider: false };
  }

  const lowerProvider = rawProvider.toLowerCase();
  return {
    name: name.toLowerCase(),
    provider: PROTOCOL_ALIASES[lowerProvider] || lowerProvider,
    hasProvider: true,
  };
}

function getModelComparisonKey(
  model: string,
  protocol: ChannelProtocol,
  modelProviderPrefixes: ReadonlySet<string>,
  baseUrl = '',
): string {
  const normalizedModel = normalizeModelForRuntime(model, protocol, modelProviderPrefixes, baseUrl).trim();
  const parsed = parseModelRef(normalizedModel);
  if (!parsed.name) {
    return '';
  }
  return `${parsed.provider}/${parsed.name}`;
}

function areModelsEquivalent(
  a: string,
  b: string,
  protocol: ChannelProtocol,
  modelProviderPrefixes: ReadonlySet<string>,
  baseUrl = '',
): boolean {
  const left = getModelComparisonKey(a, protocol, modelProviderPrefixes, baseUrl);
  const right = getModelComparisonKey(b, protocol, modelProviderPrefixes, baseUrl);
  return left !== '' && left === right;
}

function toggleModelSelection(
  models: string,
  targetModel: string,
  protocol: ChannelProtocol,
  modelProviderPrefixes: ReadonlySet<string>,
  baseUrl = '',
): string {
  const selectedModels = splitModels(models);
  const index = selectedModels.findIndex((model) => (
    areModelsEquivalent(model, targetModel, protocol, modelProviderPrefixes, baseUrl)
  ));
  if (index >= 0) {
    return selectedModels.filter((_, itemIndex) => itemIndex !== index).join(',');
  }
  return [...selectedModels, targetModel].join(',');
}

const PROTOCOL_ALIASES: Record<string, string> = {
  vertexai: 'vertex_ai',
  vertex: 'vertex_ai',
  claude: 'anthropic',
  google: 'gemini',
  openai_compatible: 'openai',
  openai_compat: 'openai',
};

function isVendorModelGatewayBaseUrl(baseUrl: string): boolean {
  const trimmed = baseUrl.trim();
  if (!trimmed) {
    return false;
  }
  try {
    const hostname = new URL(trimmed).hostname.toLowerCase();
    return hostname === 'requesty.ai' || hostname.endsWith('.requesty.ai') || hostname === 'api.x6.ai';
  } catch {
    return false;
  }
}

function normalizeModelForRuntime(
  model: string,
  protocol: ChannelProtocol,
  modelProviderPrefixes: ReadonlySet<string>,
  baseUrl = '',
): string {
  const trimmedModel = model.trim();
  if (!trimmedModel) {
    return trimmedModel;
  }

  // Mirrors normalize_llm_channel_model: Vendor model IDs keep the OpenAI gateway route.
  if (
    protocol === 'openai'
    && trimmedModel.includes('/')
    && trimmedModel.split('/', 1)[0].trim().toLowerCase() !== 'openai'
    && isVendorModelGatewayBaseUrl(baseUrl)
  ) {
    return `openai/${trimmedModel}`;
  }

  if (trimmedModel.includes('/')) {
    const rawPrefix = trimmedModel.split('/', 1)[0].trim();
    const lowerPrefix = rawPrefix.toLowerCase();
    const canonicalPrefix = PROTOCOL_ALIASES[lowerPrefix] || lowerPrefix;
    const isProtocolPrefix = canonicalPrefix === protocol;
    if (isProtocolPrefix || modelProviderPrefixes.has(lowerPrefix) || modelProviderPrefixes.has(canonicalPrefix)) {
      if (canonicalPrefix !== lowerPrefix && (isProtocolPrefix || modelProviderPrefixes.has(canonicalPrefix))) {
        return `${canonicalPrefix}/${trimmedModel.split('/').slice(1).join('/')}`;
      }
      return trimmedModel;
    }
    return `${protocol}/${trimmedModel}`;
  }

  return `${protocol}/${trimmedModel}`;
}

function resolveModelPreview(
  models: string,
  protocol: ChannelProtocol,
  modelProviderPrefixes: ReadonlySet<string>,
  baseUrl = '',
): string[] {
  return splitModels(models).map((model) => (
    normalizeModelForRuntime(model, protocol, modelProviderPrefixes, baseUrl)
  ));
}

interface RouteProvenance {
  routeName: string;
  hasHermes: boolean;
  hasNonHermes: boolean;
}

function resolveChannelRouteModels(
  channel: ChannelConfig,
  modelProviderPrefixes: ReadonlySet<string>,
): string[] {
  if (isHermesChannel(channel)) {
    const models = splitModels(channel.models);
    return (models.length > 0 ? models : [HERMES_DEFAULT_MODEL]).map(canonicalizeHermesRouteModel);
  }
  return resolveModelPreview(channel.models, channel.protocol, modelProviderPrefixes, channel.baseUrl);
}

function buildRouteProvenanceMap(
  channels: ChannelConfig[],
  modelProviderPrefixes: ReadonlySet<string>,
): Map<string, RouteProvenance> {
  const provenance = new Map<string, RouteProvenance>();
  for (const channel of channels) {
    if (!channel.enabled || !channel.name.trim()) {
      continue;
    }
    const hermes = isHermesChannel(channel);
    for (const routeName of resolveChannelRouteModels(channel, modelProviderPrefixes)) {
      if (!routeName) continue;
      const existing = provenance.get(routeName) || {
        routeName,
        hasHermes: false,
        hasNonHermes: false,
      };
      provenance.set(routeName, {
        ...existing,
        hasHermes: existing.hasHermes || hermes,
        hasNonHermes: existing.hasNonHermes || !hermes,
      });
    }
  }
  return provenance;
}

function buildModelOptions(
  models: string[],
  selectedModel: string,
  autoLabel: string,
  text: LlmChannelEditorLocale,
): Array<{ value: string; label: string }> {
  const options: Array<{ value: string; label: string }> = [{ value: '', label: autoLabel }];
  if (selectedModel && !models.includes(selectedModel)) {
    options.push({ value: selectedModel, label: text.currentConfigOption(selectedModel) });
  }
  for (const model of models) {
    options.push({ value: model, label: model });
  }
  return options;
}

function getLlmStageLabel(stage: string | null | undefined, text: LlmChannelEditorLocale): string {
  return text.stageLabels[stage || ''] || text.defaultStageLabel;
}

function getLlmErrorCodeLabel(code: string | null | undefined, text: LlmChannelEditorLocale): string {
  return text.errorLabels[code || ''] || text.defaultErrorLabel;
}

function getLlmTroubleshootingHint(
  code: string | null | undefined,
  stage: string | null | undefined,
  text: LlmChannelEditorLocale,
  context: 'test' | 'discovery' = 'test',
  details?: Record<string, unknown>,
): string | undefined {
  const reason = typeof details?.reason === 'string' ? details.reason : '';
  if (reason && text.reasonHints[reason]) {
    return text.reasonHints[reason];
  }
  if (code === 'format_error') {
    return context === 'discovery' || stage === 'model_discovery'
      ? text.formatErrorDiscoveryHint
      : text.formatErrorChatHint;
  }
  if (code === 'empty_response' && (context === 'discovery' || stage === 'model_discovery')) {
    return text.emptyResponseDiscoveryHint;
  }
  return text.troubleshootingHints[code || ''];
}

function buildLlmTestHint(
  result: {
    errorCode?: string | null;
    stage?: string | null;
    details?: Record<string, unknown>;
    resolvedModel?: string | null;
  },
  text: LlmChannelEditorLocale,
): string | undefined {
  const reason = typeof result.details?.reason === 'string' ? result.details.reason : '';
  const detailsModel = typeof result.details?.model === 'string' ? result.details.model : '';
  const testedModel = result.resolvedModel || detailsModel;
  const modelHint = testedModel ? text.testModelHintPrefix(testedModel) : '';
  const scopeInfo = text.testScopeInfo;
  const shouldSuggestModelListChange = reason === 'model_access_denied'
    || reason === 'model_not_found'
    || (result.errorCode === 'model_not_found' && !reason);
  const modelActionHint = shouldSuggestModelListChange
    ? text.testModelActionHint
    : '';
  const troubleshootingHint = getLlmTroubleshootingHint(result.errorCode, result.stage, text, 'test', result.details);
  return [modelHint, scopeInfo, modelActionHint, troubleshootingHint].filter(Boolean).join(' ') || undefined;
}

function buildLlmFailureText(
  result: {
    message: string;
    error?: string | null;
    stage?: string | null;
    errorCode?: string | null;
  },
  text: LlmChannelEditorLocale,
): string {
  const prefix = `${getLlmStageLabel(result.stage, text)} · ${getLlmErrorCodeLabel(result.errorCode, text)}`;
  const summary = result.message || text.defaultFailureSummary;
  if (result.error && result.error !== result.message) {
    return text.failureSummaryWithError(prefix, summary, result.error);
  }
  return text.failureSummary(prefix, summary);
}

function getCapabilityResultVariant(status: LLMCapabilityCheckResult['status']): 'success' | 'danger' | 'warning' {
  if (status === 'passed') return 'success';
  if (status === 'skipped') return 'warning';
  return 'danger';
}

function summarizeCapabilityResults(
  results: Partial<Record<LLMCapabilityCheck, LLMCapabilityCheckResult>>,
  text: LlmChannelEditorLocale,
): string {
  const values = Object.values(results);
  const passed = values.filter((result) => result?.status === 'passed').length;
  const failed = values.filter((result) => result?.status === 'failed').length;
  const skipped = values.filter((result) => result?.status === 'skipped').length;
  return text.capabilitySummary(passed, failed, skipped);
}

function getFirstCapabilityHint(
  results: Partial<Record<LLMCapabilityCheck, LLMCapabilityCheckResult>>,
  text: LlmChannelEditorLocale,
): string | undefined {
  for (const result of Object.values(results)) {
    if (!result || result.status === 'passed') continue;
    const hint = getLlmTroubleshootingHint(result.errorCode, result.stage, text, 'test', result.details);
    if (hint) return hint;
  }
  return undefined;
}

const MANAGED_PROVIDERS = new Set(['gemini', 'vertex_ai', 'anthropic', 'openai', 'deepseek']);
const LEGACY_PROVIDER_KEYS: Record<string, string[]> = {
  gemini: ['GEMINI_API_KEYS', 'GEMINI_API_KEY'],
  vertex_ai: ['GEMINI_API_KEYS', 'GEMINI_API_KEY'],
  anthropic: ['ANTHROPIC_API_KEYS', 'ANTHROPIC_API_KEY'],
  openai: ['OPENAI_API_KEYS', 'AIHUBMIX_KEY', 'OPENAI_API_KEY'],
  deepseek: ['DEEPSEEK_API_KEYS', 'DEEPSEEK_API_KEY'],
};

function getRuntimeProvider(model: string): string {
  if (!model) return '';
  if (!model.includes('/')) return 'openai';
  return model.split('/', 1)[0].trim().toLowerCase();
}

function usesDirectEnvProvider(model: string): boolean {
  const provider = getRuntimeProvider(model);
  return Boolean(provider) && !MANAGED_PROVIDERS.has(provider);
}

function hasLegacyRuntimeSource(model: string, itemMap: Map<string, string>): boolean {
  const provider = PROTOCOL_ALIASES[getRuntimeProvider(model)] || getRuntimeProvider(model);
  if (!provider || !MANAGED_PROVIDERS.has(provider)) {
    return false;
  }
  return (LEGACY_PROVIDER_KEYS[provider] || []).some((key) => (itemMap.get(key) || '').trim().length > 0);
}

function isRuntimeModelAvailable(model: string, availableModels: string[], itemMap: Map<string, string>): boolean {
  const normalizedModel = model.trim();
  const matchesAvailableModel = normalizedModel.length > 0 && availableModels.includes(normalizedModel);
  return matchesAvailableModel
    || usesDirectEnvProvider(model)
    || (availableModels.length === 0 && hasLegacyRuntimeSource(model, itemMap));
}

function hasCanonicalRouteAliasMismatch(model: string, availableModels: string[]): boolean {
  const normalizedModel = model.trim();
  if (!normalizedModel || availableModels.includes(normalizedModel) || usesDirectEnvProvider(normalizedModel)) {
    return false;
  }
  for (const candidate of routeIdentityCandidates(normalizedModel)) {
    if (candidate !== normalizedModel && availableModels.includes(candidate)) {
      return true;
    }
  }
  return false;
}

function sanitizeRuntimeConfigForSave(
  runtimeConfig: RuntimeConfig,
  generationModels: string[],
  agentSafeModels: string[],
  visionSafeModels: string[],
  itemMap: Map<string, string>,
): RuntimeConfig {
  const primaryModel = runtimeConfig.primaryModel && !isRuntimeModelAvailable(runtimeConfig.primaryModel, generationModels, itemMap)
    ? ''
    : runtimeConfig.primaryModel;
  const agentPrimaryModel = runtimeConfig.agentPrimaryModel && !isRuntimeModelAvailable(runtimeConfig.agentPrimaryModel, agentSafeModels, itemMap)
    ? ''
    : runtimeConfig.agentPrimaryModel;
  const visionModel = runtimeConfig.visionModel && !isRuntimeModelAvailable(runtimeConfig.visionModel, visionSafeModels, itemMap)
    ? ''
    : runtimeConfig.visionModel;
  const fallbackModels = runtimeConfig.fallbackModels.filter((model) => isRuntimeModelAvailable(model, generationModels, itemMap));

  return {
    ...runtimeConfig,
    primaryModel,
    agentPrimaryModel,
    fallbackModels,
    visionModel,
  };
}

function runtimeConfigsAreEqual(left: RuntimeConfig, right: RuntimeConfig): boolean {
  return left.primaryModel === right.primaryModel
    && left.agentPrimaryModel === right.agentPrimaryModel
    && left.visionModel === right.visionModel
    && left.temperature === right.temperature
    && left.fallbackModels.join(',') === right.fallbackModels.join(',');
}

function runtimeConfigChangedKeys(left: RuntimeConfig, right: RuntimeConfig): Set<string> {
  const changed = new Set<string>();
  if (left.primaryModel !== right.primaryModel) {
    changed.add('LITELLM_MODEL');
  }
  if (left.agentPrimaryModel !== right.agentPrimaryModel) {
    changed.add('AGENT_LITELLM_MODEL');
  }
  if (left.fallbackModels.join(',') !== right.fallbackModels.join(',')) {
    changed.add('LITELLM_FALLBACK_MODELS');
  }
  if (left.temperature !== right.temperature) {
    changed.add('LLM_TEMPERATURE');
  }
  if (left.visionModel !== right.visionModel) {
    changed.add('VISION_MODEL');
  }
  return changed;
}

function resolveTemperatureFromItems(itemMap: Map<string, string>): string {
  const unified = itemMap.get('LLM_TEMPERATURE');
  if (unified) return unified;

  const primaryModel = itemMap.get('LITELLM_MODEL') || '';
  const provider = primaryModel.includes('/') ? primaryModel.split('/')[0] : (primaryModel ? 'openai' : '');
  const providerTemperatureEnv: Record<string, string> = {
    gemini: 'GEMINI_TEMPERATURE',
    vertex_ai: 'GEMINI_TEMPERATURE',
    anthropic: 'ANTHROPIC_TEMPERATURE',
    openai: 'OPENAI_TEMPERATURE',
    deepseek: 'OPENAI_TEMPERATURE',
  };
  const preferredEnv = providerTemperatureEnv[provider];
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

function normalizeAgentPrimaryModel(model: string): string {
  const trimmedModel = model.trim();
  if (!trimmedModel) {
    return '';
  }
  if (trimmedModel.includes('/')) {
    return trimmedModel;
  }
  return `openai/${trimmedModel}`;
}

function parseRuntimeConfigFromItems(items: Array<{ key: string; value: string }>): RuntimeConfig {
  const itemMap = new Map(items.map((item) => [item.key, item.value]));
  return {
    primaryModel: itemMap.get('LITELLM_MODEL') || '',
    agentPrimaryModel: normalizeAgentPrimaryModel(itemMap.get('AGENT_LITELLM_MODEL') || ''),
    fallbackModels: splitModels(itemMap.get('LITELLM_FALLBACK_MODELS') || ''),
    visionModel: itemMap.get('VISION_MODEL') || '',
    temperature: resolveTemperatureFromItems(itemMap),
  };
}

function normalizeApiSurface(value: string | undefined): string {
  const normalized = (value || '').trim().toLowerCase().replaceAll('-', '_');
  if (normalized === 'responses' || normalized === 'response' || normalized === 'responses_api') {
    return 'responses';
  }
  if (!normalized || normalized === 'chat' || normalized === 'chat_completion' || normalized === 'completions') {
    return 'chat_completions';
  }
  return normalized;
}

function parseChannelsFromItems(
  items: Array<{ key: string; value: string }>,
  itemSourceByKey: Map<string, boolean> = new Map(),
): ChannelConfig[] {
  const itemMap = new Map(items.map((item) => [item.key.toUpperCase(), item.value]));
  const implicitModelflare = splitModels(itemMap.get('MODELFLARE_KEY') || '').length > 0
    || splitModels(itemMap.get('LLM_MODELFLARE_API_KEY') || '').length > 0
    || splitModels(itemMap.get('LLM_MODELFLARE_API_KEYS') || '').length > 0;
  const channelNames = ((itemMap.get('LLM_CHANNELS') || '').trim()
    || (implicitModelflare ? 'modelflare' : ''))
    .split(',')
    .map((segment) => segment.trim())
    .filter(Boolean);

  return channelNames.map((name, index) => {
    const upperName = name.toUpperCase();
    const baseUrl = itemMap.get(`LLM_${upperName}_BASE_URL`) || '';
    const primaryModel = (itemMap.get('LITELLM_MODEL') || '').trim()
      || `openai/${MODELFLARE_DEFAULT_MODEL}`;
    const inheritedModels = channelNames.length === 1 && upperName === 'MODELFLARE'
      && primaryModel.startsWith('openai/') && primaryModel.slice(7).trim()
      ? [...new Set([primaryModel, ...splitModels(itemMap.get('LITELLM_FALLBACK_MODELS') || '')]
        .filter((model) => model.startsWith('openai/') && model.slice(7).trim()))]
      : [];
    const rawModels = (itemMap.get(`LLM_${upperName}_MODELS`) || '').trim() || inheritedModels.join(',');
    const models = splitModels(rawModels);

    return {
      id: `parsed:${index}:${upperName}`,
      name: name.toLowerCase(),
      protocol: inferProtocol(itemMap.get(`LLM_${upperName}_PROTOCOL`) || '', baseUrl, models),
      apiSurface: normalizeApiSurface(itemMap.get(`LLM_${upperName}_API_SURFACE`)),
      baseUrl,
      apiKey: resolveInitialChannelApiKeyValue(name, itemMap, itemSourceByKey),
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
    updates.push({ key: 'AGENT_LITELLM_MODEL', value: runtimeConfig.agentPrimaryModel });
    updates.push({ key: 'LITELLM_FALLBACK_MODELS', value: runtimeConfig.fallbackModels.join(',') });
    updates.push({ key: 'VISION_MODEL', value: runtimeConfig.visionModel });
    updates.push({ key: 'LLM_TEMPERATURE', value: runtimeConfig.temperature });
  }

  for (const channel of channels) {
    const prefix = `LLM_${channel.name.toUpperCase()}`;
    const isMultiKey = channel.apiKey.includes(',');
    updates.push({ key: `${prefix}_PROTOCOL`, value: channel.protocol });
    updates.push({ key: `${prefix}_API_SURFACE`, value: channel.apiSurface });
    updates.push({ key: `${prefix}_BASE_URL`, value: channel.baseUrl });
    updates.push({ key: `${prefix}_ENABLED`, value: channel.enabled ? 'true' : 'false' });
    if (isHermesChannel(channel)) {
      updates.push({ key: `${prefix}_API_KEY`, value: channel.apiKey });
      updates.push({ key: `${prefix}_API_KEYS`, value: '' });
      updates.push({ key: `${prefix}_EXTRA_HEADERS`, value: '' });
    } else {
      updates.push({ key: `${prefix}_API_KEY${isMultiKey ? 'S' : ''}`, value: channel.apiKey });
      updates.push({ key: `${prefix}_API_KEY${isMultiKey ? '' : 'S'}`, value: '' });
    }
    updates.push({ key: `${prefix}_MODELS`, value: channel.models });
  }

  for (const oldName of previousChannelNames) {
    const upperName = oldName.toUpperCase();
    if (activeNames.includes(upperName)) {
      continue;
    }

    const prefix = `LLM_${upperName}`;
    updates.push({ key: `${prefix}_PROTOCOL`, value: '' });
    updates.push({ key: `${prefix}_API_SURFACE`, value: '' });
    updates.push({ key: `${prefix}_BASE_URL`, value: '' });
    updates.push({ key: `${prefix}_ENABLED`, value: '' });
    updates.push({ key: `${prefix}_API_KEY`, value: '' });
    updates.push({ key: `${prefix}_API_KEYS`, value: '' });
    updates.push({ key: `${prefix}_MODELS`, value: '' });
    updates.push({ key: `${prefix}_EXTRA_HEADERS`, value: '' });
  }

  return updates;
}

function channelNamesAreSafe(channels: ChannelConfig[]): boolean {
  return channels.every((channel) => /^[a-z0-9_]+$/.test(channel.name.trim()));
}

function buildFilteredChannelUpdateItems({
  channels,
  initialChannels,
  initialNames,
  initialItemSourceByKey,
  savedItemMap,
  runtimeConfig,
  initialRuntimeConfig,
  managesRuntimeConfig,
}: {
  channels: ChannelConfig[];
  initialChannels: ChannelConfig[];
  initialNames: string[];
  initialItemSourceByKey: Map<string, boolean>;
  savedItemMap: Map<string, string>;
  runtimeConfig: RuntimeConfig;
  initialRuntimeConfig: RuntimeConfig;
  managesRuntimeConfig: boolean;
}): Array<{ key: string; value: string }> {
  const changedKeys = new Set<string>([
    ...buildChangedItemKeys(channels, initialChannels, initialItemSourceByKey, savedItemMap),
    ...runtimeConfigChangedKeys(runtimeConfig, initialRuntimeConfig),
  ]);
  const usesSimpleModelflare = Boolean(savedItemMap.get('MODELFLARE_KEY'))
    && !(savedItemMap.get('LLM_CHANNELS') || '').trim()
    && !(savedItemMap.get('LLM_MODELFLARE_API_KEY') || '').trim()
    && !(savedItemMap.get('LLM_MODELFLARE_API_KEYS') || '').trim();
  const updates = channelsToUpdateItems(channels, initialNames, runtimeConfig, managesRuntimeConfig).filter((item) => {
    const itemKey = item.key.toUpperCase();
    if (usesSimpleModelflare && !changedKeys.has(itemKey)) return false;
    const initialItemSource = initialItemSourceByKey.get(itemKey);
    if (initialItemSource === false) {
      return changedKeys.has(itemKey);
    }
    if (isChannelSecretFieldKey(itemKey) && initialItemSource === undefined) {
      return changedKeys.has(itemKey);
    }
    return true;
  });
  if (usesSimpleModelflare) {
    const current = channels.find((channel) => channel.name.toLowerCase() === 'modelflare');
    const previous = initialChannels.find((channel) => channel.name.toLowerCase() === 'modelflare');
    if (current?.apiKey !== previous?.apiKey) {
      updates.push({ key: 'MODELFLARE_KEY', value: current?.apiKey || '' });
    }
    return updates.filter((item) => item.key !== 'LLM_MODELFLARE_API_KEY' && item.key !== 'LLM_MODELFLARE_API_KEYS');
  }
  const removedModelflare = initialNames.some((name) => name.toLowerCase() === 'modelflare')
    && !channels.some((channel) => channel.name.toLowerCase() === 'modelflare');
  if (removedModelflare && managesRuntimeConfig && (savedItemMap.get('MODELFLARE_KEY') || '').trim()) {
    updates.push({ key: 'MODELFLARE_KEY', value: '' });
  }
  return updates;
}

function buildChannelDraftItems({
  hasChanges,
  channels,
  initialChannels,
  initialNames,
  initialItemSourceByKey,
  savedItemMap,
  runtimeConfig,
  initialRuntimeConfig,
  managesRuntimeConfig,
}: {
  hasChanges: boolean;
  channels: ChannelConfig[];
  initialChannels: ChannelConfig[];
  initialNames: string[];
  initialItemSourceByKey: Map<string, boolean>;
  savedItemMap: Map<string, string>;
  runtimeConfig: RuntimeConfig;
  initialRuntimeConfig: RuntimeConfig;
  managesRuntimeConfig: boolean;
}): Array<{ key: string; value: string }> {
  if (!hasChanges || !channelNamesAreSafe(channels)) {
    return [];
  }
  return buildFilteredChannelUpdateItems({
    channels,
    initialChannels,
    initialNames,
    initialItemSourceByKey,
    savedItemMap,
    runtimeConfig,
    initialRuntimeConfig,
    managesRuntimeConfig,
  });
}

function channelsAreEqual(left: ChannelConfig, right: ChannelConfig): boolean {
  return (
    left.name === right.name
    && left.protocol === right.protocol
    && left.apiSurface === right.apiSurface
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
  modelProviderPrefixes = [],
  onSaved,
  onDraftItemsChange,
  onDirtyChange,
  onSavingChange,
  draftResetToken = 0,
  llmYamlActive,
  disabled = false,
}) => {
  const { language } = useUiLanguage();
  const text = LLM_CHANNEL_EDITOR_TEXT[language];
  const initialItemSourceByKey = useMemo(() => {
    const sourceByKey = new Map<string, boolean>();
    for (const item of items) {
      sourceByKey.set(item.key.toUpperCase(), item.rawValueExists !== false);
    }
    for (const [key, hasSource] of sourceByKey) {
      if (hasSource) {
        continue;
      }
      const match = CHANNEL_FIELD_KEY_PATTERN.exec(key);
      if (!match) {
        continue;
      }
      const channelName = match[1];
      for (const channelKey of parseChannelFieldKeysFromName(channelName)) {
        if (!sourceByKey.has(channelKey)) {
          sourceByKey.set(channelKey, false);
        }
      }
    }
    return sourceByKey;
  }, [items]);
  const initialChannels = useMemo(
    () => parseChannelsFromItems(items, initialItemSourceByKey),
    [items, initialItemSourceByKey],
  );
  const initialNames = useMemo(() => initialChannels.map((channel) => channel.name), [initialChannels]);
  const initialRuntimeConfig = useMemo(() => parseRuntimeConfigFromItems(items), [items]);
  const savedItemMap = useMemo(() => new Map(items.map((item) => [item.key.toUpperCase(), item.value])), [items]);
  const hasPersistedHermesSecret = (channel: ChannelConfig): boolean => (
    isHermesChannel(channel) && initialItemSourceByKey.get('LLM_HERMES_API_KEY') === true
  );
  // When a valid YAML source is active, the generic settings fields own the
  // runtime model aliases. The channel editor must not submit empty values
  // for aliases that only exist in YAML. If the API does not provide the
  // source status, retain the legacy path-based fallback for older clients.
  const hasActiveYaml = llmYamlActive ?? items.some((item) => item.key === 'LITELLM_CONFIG'
    && item.value.trim().length > 0
    && item.rawValueExists !== false);
  const managesRuntimeConfig = !hasActiveYaml;
  const modelProviderPrefixSet = useMemo(
    () => new Set(modelProviderPrefixes.map((provider) => provider.trim().toLowerCase()).filter(Boolean)),
    [modelProviderPrefixes],
  );

  const channelsFingerprint = useMemo(() => JSON.stringify(initialChannels), [initialChannels]);
  const runtimeFingerprint = useMemo(() => JSON.stringify(initialRuntimeConfig), [initialRuntimeConfig]);

  const [channels, setChannels] = useState<ChannelConfig[]>(initialChannels);
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfig>(initialRuntimeConfig);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<
    | { type: 'success'; key: SaveSuccessMessageKey }
    | { type: 'error'; rawError: unknown }
    | { type: 'local-error'; key: LocalValidationMessageKey }
    | null
  >(null);
  const [saveWarnings, setSaveWarnings] = useState<string[]>([]);
  const [visibleKeys, setVisibleKeys] = useState<Record<string, boolean>>({});
  const [testStates, setTestStates] = useState<Record<string, ChannelTestState>>({});
  const [discoveryStates, setDiscoveryStates] = useState<Record<string, ChannelDiscoveryState>>({});
  const [capabilityStates, setCapabilityStates] = useState<Record<string, ChannelCapabilityState>>({});
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [addPreset, setAddPreset] = useState(LLM_PROVIDER_TEMPLATES[0].channelId);
  const addPresetTemplate = getProviderTemplate(addPreset);
  const registration = addPresetTemplate ? getProviderTemplateRegistration(addPresetTemplate, language) : undefined;
  const addChannelIdRef = useRef(0);
  const lastDraftFingerprintRef = useRef<string | null>(null);
  const onDraftItemsChangeRef = useRef(onDraftItemsChange);
  const mountedRef = useRef(true);
  const saveInFlightRef = useRef(false);

  const prevDraftResetTokenRef = useRef(draftResetToken);
  const prevChannelsRef = useRef(channelsFingerprint);
  const prevRuntimeRef = useRef(runtimeFingerprint);
  const previousInitialChannelsRef = useRef(initialChannels);
  const previousInitialRuntimeConfigRef = useRef(initialRuntimeConfig);
  const removedInitialChannelNamesRef = useRef<Set<string>>(new Set());
  const pendingSaveFeedbackFingerprintRef = useRef<{
    channels: string;
    runtime: string;
    resetAfterSave?: boolean;
  } | null>(null);
  const testNonceRef = useRef<Record<string, number>>({});
  const testRequestIdRef = useRef(0);
  const discoveryNonceRef = useRef<Record<string, number>>({});
  const discoveryRequestIdRef = useRef(0);
  const capabilityNonceRef = useRef<Record<string, number>>({});
  const capabilityRequestIdRef = useRef(0);

  useEffect(() => {
    if (prevChannelsRef.current === channelsFingerprint && prevRuntimeRef.current === runtimeFingerprint
      && prevDraftResetTokenRef.current === draftResetToken) {
      return;
    }
    const isExplicitReset = prevDraftResetTokenRef.current !== draftResetToken;
    const previousInitialChannels = previousInitialChannelsRef.current;
    const previousInitialRuntimeConfig = previousInitialRuntimeConfigRef.current;
    prevDraftResetTokenRef.current = draftResetToken;
    prevChannelsRef.current = channelsFingerprint;
    prevRuntimeRef.current = runtimeFingerprint;
    // Keep snapshots for channels that temporarily disappear from `items`.
    // The shorthand MODELFLARE_KEY path can do exactly that while its draft
    // value is cleared and then entered again.
    const nextInitialChannelNames = new Set(initialChannels.map((channel) => channel.name.toLowerCase()));
    previousInitialChannelsRef.current = [
      ...initialChannels,
      ...previousInitialChannels.filter((channel) => !nextInitialChannelNames.has(channel.name.toLowerCase())),
    ];
    previousInitialRuntimeConfigRef.current = initialRuntimeConfig;
    const pendingSaveFeedbackFingerprint = pendingSaveFeedbackFingerprintRef.current;
    const resetAfterSave = pendingSaveFeedbackFingerprint?.resetAfterSave === true;
    const preserveSaveFeedback = !resetAfterSave
      && pendingSaveFeedbackFingerprint?.channels === channelsFingerprint
      && pendingSaveFeedbackFingerprint.runtime === runtimeFingerprint;
    pendingSaveFeedbackFingerprintRef.current = null;
    if (isExplicitReset) {
      removedInitialChannelNamesRef.current = new Set();
      setChannels(initialChannels);
      setRuntimeConfig(initialRuntimeConfig);
    } else if (resetAfterSave) {
      removedInitialChannelNamesRef.current = new Set();
      setChannels(initialChannels);
      setRuntimeConfig(initialRuntimeConfig);
    } else {
      setChannels((currentChannels) => {
        const removedInitialChannelNames = removedInitialChannelNamesRef.current;
        const currentChannelNames = new Set(currentChannels.map((channel) => channel.name.toLowerCase()));
        previousInitialChannels.forEach((channel) => {
          const name = channel.name.toLowerCase();
          if (!currentChannelNames.has(name)) {
            removedInitialChannelNames.add(name);
          }
        });
        currentChannelNames.forEach((name) => removedInitialChannelNames.delete(name));
        const nextChannelNames = new Set(initialChannels.map((channel) => channel.name.toLowerCase()));
        const mergedChannels = initialChannels.flatMap((nextInitial) => {
          if (removedInitialChannelNames.has(nextInitial.name.toLowerCase())
            && !currentChannelNames.has(nextInitial.name.toLowerCase())) {
            return [];
          }
          const currentChannel = currentChannels.find(
            (channel) => channel.id === nextInitial.id
              || channel.name.toLowerCase() === nextInitial.name.toLowerCase(),
          );
          const previousInitial = previousInitialChannels.find(
            (channel) => channel.id === nextInitial.id
              || channel.name.toLowerCase() === nextInitial.name.toLowerCase(),
          );
          if (!currentChannel || !previousInitial) {
            return [nextInitial];
          }
          const merged = { ...nextInitial };
          (['name', 'protocol', 'apiSurface', 'baseUrl', 'apiKey', 'models', 'enabled'] as const).forEach((field) => {
            if (currentChannel[field] !== previousInitial[field]) {
              Object.assign(merged, { [field]: currentChannel[field] });
            }
          });
          return [merged];
        });

        // A locally added channel has no previous initial snapshot. Keep it
        // until the user explicitly resets, but drop channels removed by the
        // external draft update.
        return [
          ...mergedChannels,
          ...currentChannels.filter((channel) => {
            if (nextChannelNames.has(channel.name.toLowerCase())) return false;
            const previousInitial = previousInitialChannels.find((initial) => (
              initial.id === channel.id || initial.name.toLowerCase() === channel.name.toLowerCase()
            ));
            if (!previousInitial) return true;
            return !channelsAreEqual(channel, previousInitial);
          }),
        ];
      });
      setRuntimeConfig((currentRuntime) => {
        const merged = { ...initialRuntimeConfig };
        (['primaryModel', 'agentPrimaryModel', 'fallbackModels', 'visionModel', 'temperature'] as const).forEach((field) => {
          if (JSON.stringify(currentRuntime[field]) !== JSON.stringify(previousInitialRuntimeConfig[field])) {
            Object.assign(merged, { [field]: currentRuntime[field] });
          }
        });
        return merged;
      });
    }
    setVisibleKeys({});
    setTestStates({});
    setDiscoveryStates({});
    setCapabilityStates({});
    setExpandedRows({});
    testNonceRef.current = {};
    discoveryNonceRef.current = {};
    capabilityNonceRef.current = {};
    if (!preserveSaveFeedback) {
      setSaveMessage(null);
      setSaveWarnings([]);
    }
    setIsCollapsed(false);
  }, [channelsFingerprint, runtimeFingerprint, initialChannels, initialRuntimeConfig, draftResetToken]);

  const routeProvenanceMap = useMemo(() => {
    if (!managesRuntimeConfig) {
      return new Map<string, RouteProvenance>();
    }
    return buildRouteProvenanceMap(channels, modelProviderPrefixSet);
  }, [channels, managesRuntimeConfig, modelProviderPrefixSet]);

  const availableModels = useMemo(
    () => Array.from(routeProvenanceMap.values())
      .filter((origin) => !(origin.hasHermes && origin.hasNonHermes))
      .map((origin) => origin.routeName),
    [routeProvenanceMap],
  );

  const agentSafeModels = useMemo(
    () => Array.from(routeProvenanceMap.values())
      .filter((origin) => !origin.hasHermes || origin.hasNonHermes)
      .map((origin) => origin.routeName),
    [routeProvenanceMap],
  );

  const visionSafeModels = useMemo(
    () => Array.from(routeProvenanceMap.values())
      .filter((origin) => !origin.hasHermes)
      .map((origin) => origin.routeName),
    [routeProvenanceMap],
  );

  const agentSelectedModelForOptions = useMemo(() => {
    if (!runtimeConfig.agentPrimaryModel || agentSafeModels.includes(runtimeConfig.agentPrimaryModel)) {
      return runtimeConfig.agentPrimaryModel;
    }
    const origin = getRouteProvenance(routeProvenanceMap, runtimeConfig.agentPrimaryModel);
    return origin?.hasHermes && !origin.hasNonHermes ? '' : runtimeConfig.agentPrimaryModel;
  }, [agentSafeModels, routeProvenanceMap, runtimeConfig.agentPrimaryModel]);

  const visionSelectedModelForOptions = useMemo(() => {
    if (!runtimeConfig.visionModel || visionSafeModels.includes(runtimeConfig.visionModel)) {
      return runtimeConfig.visionModel;
    }
    const origin = getRouteProvenance(routeProvenanceMap, runtimeConfig.visionModel);
    return origin?.hasHermes ? '' : runtimeConfig.visionModel;
  }, [routeProvenanceMap, runtimeConfig.visionModel, visionSafeModels]);

  const hasChanges = useMemo(() => {
    const runtimeChanged = (
      runtimeConfig.primaryModel !== initialRuntimeConfig.primaryModel
      || runtimeConfig.agentPrimaryModel !== initialRuntimeConfig.agentPrimaryModel
      || runtimeConfig.visionModel !== initialRuntimeConfig.visionModel
      || runtimeConfig.temperature !== initialRuntimeConfig.temperature
      || runtimeConfig.fallbackModels.join(',') !== initialRuntimeConfig.fallbackModels.join(',')
    );

    if (runtimeChanged || channels.length !== initialChannels.length) {
      return true;
    }
    return channels.some((channel, index) => !channelsAreEqual(channel, initialChannels[index]));
  }, [channels, initialChannels, initialRuntimeConfig, runtimeConfig]);

  useEffect(() => {
    onDirtyChange?.(hasChanges);
    return () => onDirtyChange?.(false);
  }, [hasChanges, onDirtyChange]);

  useEffect(() => {
    onSavingChange?.(isSaving);
    return () => onSavingChange?.(false);
  }, [isSaving, onSavingChange]);

  const draftItems = useMemo(() => buildChannelDraftItems({
    hasChanges,
    channels,
    initialChannels,
    initialNames,
    initialItemSourceByKey,
    savedItemMap,
    runtimeConfig,
    initialRuntimeConfig,
    managesRuntimeConfig,
  }), [
    channels,
    hasChanges,
    initialChannels,
    initialItemSourceByKey,
    initialNames,
    initialRuntimeConfig,
    managesRuntimeConfig,
    runtimeConfig,
    savedItemMap,
  ]);
  const draftFingerprint = useMemo(() => JSON.stringify(draftItems), [draftItems]);

  useEffect(() => {
    onDraftItemsChangeRef.current = onDraftItemsChange;
  }, [onDraftItemsChange]);

  useEffect(() => {
    if (!onDraftItemsChange || lastDraftFingerprintRef.current === draftFingerprint) {
      return;
    }
    lastDraftFingerprintRef.current = draftFingerprint;
    onDraftItemsChange(draftItems);
  }, [draftFingerprint, draftItems, onDraftItemsChange]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      testNonceRef.current = {};
      discoveryNonceRef.current = {};
      capabilityNonceRef.current = {};
      onDraftItemsChangeRef.current?.([]);
    };
  }, []);

  const busy = disabled || isSaving;

  const updateChannel = (index: number, field: keyof ChannelConfig, value: string | boolean) => {
    const currentChannel = channels[index];
    setChannels((previous) => previous.map((channel, rowIndex) => {
      if (rowIndex !== index) return channel;
      const updated = { ...channel, [field]: value };

      if (field === 'name' && typeof value === 'string') {
        const newPreset = getProviderTemplate(value);
        if (newPreset) {
          const oldPreset = getProviderTemplate(channel.name);
          if (!updated.baseUrl || updated.baseUrl === (oldPreset?.baseUrl ?? '')) {
            updated.baseUrl = newPreset.baseUrl;
          }
          updated.protocol = newPreset.protocol;
          updated.apiSurface = 'chat_completions';
          if (!updated.models || updated.models === (oldPreset?.placeholderModels ?? '')) {
            updated.models = newPreset.placeholderModels;
          }
        }
      }

      return updated;
    }));
    if (currentChannel) {
      delete testNonceRef.current[currentChannel.id];
      setTestStates((previous) => omitChannelStateKey(previous, currentChannel.id));
    }
    if (currentChannel && field !== 'models' && field !== 'enabled') {
      delete discoveryNonceRef.current[currentChannel.id];
      setDiscoveryStates((previous) => omitChannelStateKey(previous, currentChannel.id));
    }
    if (currentChannel) {
      delete capabilityNonceRef.current[currentChannel.id];
      setCapabilityStates((previous) => {
        const current = previous[currentChannel.id];
        if (!current) {
          return previous;
        }
        return {
          ...previous,
          [currentChannel.id]: {
            ...current,
            status: 'idle',
            resolveText: undefined,
            resolveHint: undefined,
            results: {},
          },
        };
      });
    }
  };

  const removeChannel = (index: number) => {
    const removedChannelId = channels[index]?.id || '';
    setChannels((previous) => previous.filter((_, rowIndex) => rowIndex !== index));
    if (!removedChannelId) {
      return;
    }
    delete testNonceRef.current[removedChannelId];
    delete discoveryNonceRef.current[removedChannelId];
    delete capabilityNonceRef.current[removedChannelId];
    setVisibleKeys((previous) => omitChannelStateKey(previous, removedChannelId));
    setTestStates((previous) => omitChannelStateKey(previous, removedChannelId));
    setDiscoveryStates((previous) => omitChannelStateKey(previous, removedChannelId));
    setCapabilityStates((previous) => omitChannelStateKey(previous, removedChannelId));
    setExpandedRows((previous) => omitChannelStateKey(previous, removedChannelId));
  };

  const addChannel = () => {
    const preset = getProviderTemplate(addPreset) || getProviderTemplate('custom');
    if (!preset) {
      return;
    }
    addChannelIdRef.current += 1;
    const newChannelId = `added:${addChannelIdRef.current}`;
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
          id: newChannelId,
          name: nextName,
          protocol: preset.protocol,
          apiSurface: 'chat_completions',
          baseUrl: preset.baseUrl,
          apiKey: '',
          models: preset.placeholderModels || '',
          enabled: true,
        },
      ];
    });
    setExpandedRows((prev) => ({ ...prev, [newChannelId]: true }));
    setIsCollapsed(false);
  };

  const handleSave = async () => {
    if (busy || saveInFlightRef.current) {
      return;
    }
    const hasEmptyName = channels.some((channel) => !channel.name.trim());
    if (hasEmptyName) {
      setSaveMessage({ type: 'local-error', key: 'validationEmptyChannelName' });
      return;
    }

    if (managesRuntimeConfig) {
      const mixedPrimary = runtimeConfig.primaryModel
        && getRouteProvenance(routeProvenanceMap, runtimeConfig.primaryModel)?.hasHermes
        && getRouteProvenance(routeProvenanceMap, runtimeConfig.primaryModel)?.hasNonHermes;
      const mixedFallback = runtimeConfig.fallbackModels.find((model) => {
        const origin = getRouteProvenance(routeProvenanceMap, model);
        return origin?.hasHermes && origin.hasNonHermes;
      });
      if (mixedPrimary || mixedFallback) {
        setSaveMessage({ type: 'local-error', key: 'validationMixedHermesRoute' });
        return;
      }

      const nonCanonicalRouteAlias = (
        hasCanonicalRouteAliasMismatch(runtimeConfig.primaryModel, availableModels)
        || hasCanonicalRouteAliasMismatch(runtimeConfig.agentPrimaryModel, agentSafeModels)
        || hasCanonicalRouteAliasMismatch(runtimeConfig.visionModel, visionSafeModels)
        || runtimeConfig.fallbackModels.some((model) => hasCanonicalRouteAliasMismatch(model, availableModels))
      );
      if (nonCanonicalRouteAlias) {
        setSaveMessage({ type: 'local-error', key: 'validationNonCanonicalRouteAlias' });
        return;
      }
    }

    const runtimeConfigForSave = managesRuntimeConfig
      ? sanitizeRuntimeConfigForSave(runtimeConfig, availableModels, agentSafeModels, visionSafeModels, savedItemMap)
      : runtimeConfig;
    if (!runtimeConfigsAreEqual(runtimeConfigForSave, runtimeConfig)) {
      setRuntimeConfig(runtimeConfigForSave);
    }

    if (managesRuntimeConfig) {
      const invalidPrimaryModel = runtimeConfigForSave.primaryModel
        && !isRuntimeModelAvailable(runtimeConfigForSave.primaryModel, availableModels, savedItemMap);
      if (invalidPrimaryModel) {
        setSaveMessage({ type: 'local-error', key: 'validationInvalidPrimaryModel' });
        return;
      }

      const invalidAgentPrimaryModel = runtimeConfigForSave.agentPrimaryModel
        && !isRuntimeModelAvailable(runtimeConfigForSave.agentPrimaryModel, agentSafeModels, savedItemMap);
      if (invalidAgentPrimaryModel) {
        setSaveMessage({ type: 'local-error', key: 'validationInvalidAgentPrimaryModel' });
        return;
      }

      const invalidFallbackModel = runtimeConfigForSave.fallbackModels.some(
        (model) => !isRuntimeModelAvailable(model, availableModels, savedItemMap),
      );
      if (invalidFallbackModel) {
        setSaveMessage({ type: 'local-error', key: 'validationInvalidFallbackModel' });
        return;
      }

      const invalidVisionModel = runtimeConfigForSave.visionModel
        && !isRuntimeModelAvailable(runtimeConfigForSave.visionModel, visionSafeModels, savedItemMap);
      if (invalidVisionModel) {
        setSaveMessage({ type: 'local-error', key: 'validationInvalidVisionModel' });
        return;
      }
    }

    saveInFlightRef.current = true;
    setIsSaving(true);
    setSaveMessage(null);
    setSaveWarnings([]);

    try {
      const updateItems = buildFilteredChannelUpdateItems({
        channels,
        initialChannels,
        initialNames,
        initialItemSourceByKey,
        savedItemMap,
        runtimeConfig: runtimeConfigForSave,
        initialRuntimeConfig,
        managesRuntimeConfig,
      });
      const response = await systemConfigApi.update({
        configVersion,
        maskToken,
        reloadNow: true,
        items: updateItems,
      });
      const responseWarnings = response.warnings || [];
      const resetAfterSave = updateItems.some((item) => (
        item.key.toUpperCase() === 'LLM_HERMES_API_KEY'
        || (item.key.toUpperCase() === 'MODELFLARE_KEY' && !item.value.trim())
      ));
      if (mountedRef.current) {
        pendingSaveFeedbackFingerprintRef.current = {
          channels: JSON.stringify(parseChannelsFromItems(updateItems)),
          runtime: JSON.stringify(parseRuntimeConfigFromItems(updateItems)),
          resetAfterSave,
        };
      }
      // Still notify parent so unmounting mid-save (e.g., parent reload overlay) never leaves stale configVersion/items.
      await onSaved(updateItems);
      if (!mountedRef.current) {
        return;
      }
      if (resetAfterSave) {
        setChannels((currentChannels) => currentChannels.map((channel) => {
          const initialChannel = initialChannels.find((initial) => (
            initial.id === channel.id || initial.name.toLowerCase() === channel.name.toLowerCase()
          ));
          return initialChannel ? { ...channel, apiKey: initialChannel.apiKey } : channel;
        }));
        onDraftItemsChangeRef.current?.([]);
      }
      setSaveWarnings(responseWarnings);
      setSaveMessage({ type: 'success', key: managesRuntimeConfig ? 'saveSuccessAi' : 'saveSuccessChannels' });
    } catch (error: unknown) {
      if (!mountedRef.current) {
        return;
      }
      pendingSaveFeedbackFingerprintRef.current = null;
      setSaveWarnings([]);
      setSaveMessage({ type: 'error', rawError: error });
    } finally {
      saveInFlightRef.current = false;
      if (mountedRef.current) {
        setIsSaving(false);
      }
    }
  };

  const handleTest = async (channel: ChannelConfig) => {
    if (hasRuntimeOnlyMaskedHermesSecret(channel, maskToken, hasPersistedHermesSecret(channel))) {
      delete testNonceRef.current[channel.id];
      setTestStates((previous) => ({
        ...previous,
        [channel.id]: {
          status: 'error',
          resolveText: (locale) => locale.runtimeOnlyHermesSecretMessage,
        },
      }));
      return;
    }

    const requestId = testRequestIdRef.current + 1;
    testRequestIdRef.current = requestId;
    testNonceRef.current[channel.id] = requestId;
    const nonce = requestId;

    setTestStates((previous) => ({
      ...previous,
      [channel.id]: {
        status: 'loading',
        resolveText: (locale) => locale.testLoadingText,
      },
    }));

    try {
      const result = await systemConfigApi.testLLMChannel({
        name: channel.name,
        protocol: channel.protocol,
        apiSurface: channel.apiSurface as LLMApiSurface,
        baseUrl: channel.baseUrl,
        apiKey: channel.apiKey,
        models: splitModels(channel.models),
        enabled: channel.enabled,
        useSavedSecret: shouldUseSavedHermesSecret(channel, maskToken, hasPersistedHermesSecret(channel)),
      });

      if (!mountedRef.current || testNonceRef.current[channel.id] !== nonce) {
        return;
      }

      setTestStates((previous) => ({
        ...previous,
        [channel.id]: {
          status: result.success ? 'success' : 'error',
          resolveText: (locale) => (
            result.success
              ? locale.testSuccessText(result.resolvedModel, result.latencyMs)
              : buildLlmFailureText(result, locale)
          ),
          resolveHint: result.success
            ? undefined
            : (locale) => buildLlmTestHint(result, locale),
        },
      }));
    } catch (error: unknown) {
      if (!mountedRef.current || testNonceRef.current[channel.id] !== nonce) {
        return;
      }

      setTestStates((previous) => ({
        ...previous,
        [channel.id]: {
          status: 'error',
          resolveText: (locale, lang) => getParsedApiError(error, lang).message || locale.testFailureFallback,
        },
      }));
    }
  };

  const handleDiscoverModels = async (channel: ChannelConfig) => {
    if (hasRuntimeOnlyMaskedHermesSecret(channel, maskToken, hasPersistedHermesSecret(channel))) {
      delete discoveryNonceRef.current[channel.id];
      setDiscoveryStates((previous) => ({
        ...previous,
        [channel.id]: {
          status: 'error',
          resolveText: (locale) => locale.runtimeOnlyHermesSecretMessage,
          resolveHint: undefined,
          models: previous[channel.id]?.models || [],
        },
      }));
      return;
    }

    const requestId = discoveryRequestIdRef.current + 1;
    discoveryRequestIdRef.current = requestId;
    discoveryNonceRef.current[channel.id] = requestId;
    const nonce = requestId;

    setDiscoveryStates((previous) => ({
      ...previous,
      [channel.id]: {
        status: 'loading',
        resolveText: (locale) => locale.discoveryLoadingText,
        resolveHint: undefined,
        models: previous[channel.id]?.models || [],
      },
    }));

    try {
      const result = await systemConfigApi.discoverLLMChannelModels({
        name: channel.name,
        protocol: channel.protocol,
        baseUrl: channel.baseUrl,
        apiKey: channel.apiKey,
        models: splitModels(channel.models),
        useSavedSecret: shouldUseSavedHermesSecret(channel, maskToken, hasPersistedHermesSecret(channel)),
      });

      if (!mountedRef.current || discoveryNonceRef.current[channel.id] !== nonce) return;

      setDiscoveryStates((previous) => ({
        ...previous,
        [channel.id]: {
          status: result.success ? 'success' : 'error',
          resolveText: (locale) => (
            result.success
              ? locale.discoverySuccessText(result.models.length, result.latencyMs)
              : buildLlmFailureText(result, locale)
          ),
          resolveHint: result.success
            ? undefined
            : (locale) => getLlmTroubleshootingHint(result.errorCode, result.stage, locale, 'discovery', result.details),
          models: result.success ? result.models : (previous[channel.id]?.models || []),
        },
      }));
    } catch (error: unknown) {
      if (!mountedRef.current || discoveryNonceRef.current[channel.id] !== nonce) return;

      setDiscoveryStates((previous) => ({
        ...previous,
        [channel.id]: {
          status: 'error',
          resolveText: (locale, lang) => getParsedApiError(error, lang).message || locale.discoveryFailureFallback,
          resolveHint: undefined,
          models: previous[channel.id]?.models || [],
        },
      }));
    }
  };

  const toggleCapability = (channel: ChannelConfig, capability: LLMCapabilityCheck) => {
    setCapabilityStates((previous) => {
      const current = previous[channel.id] || { selected: [], status: 'idle', results: {} };
      const selected = current.selected.includes(capability)
        ? current.selected.filter((item) => item !== capability)
        : [...current.selected, capability];
      return {
        ...previous,
        [channel.id]: {
          ...current,
          selected,
          status: current.status === 'loading' ? current.status : 'idle',
          resolveText: current.status === 'loading' ? current.resolveText : undefined,
          resolveHint: current.status === 'loading' ? current.resolveHint : undefined,
          results: current.status === 'loading' ? current.results : {},
        },
      };
    });
  };

  const handleCapabilityCheck = async (channel: ChannelConfig) => {
    const selected = (capabilityStates[channel.id]?.selected || []).filter(
      (capability) => !isHermesChannel(channel) || capability === 'json',
    );
    if (selected.length === 0) return;

    if (hasRuntimeOnlyMaskedHermesSecret(channel, maskToken, hasPersistedHermesSecret(channel))) {
      delete capabilityNonceRef.current[channel.id];
      setCapabilityStates((previous) => ({
        ...previous,
        [channel.id]: {
          selected,
          status: 'error',
          resolveText: (locale) => locale.runtimeOnlyHermesSecretMessage,
          resolveHint: undefined,
          results: {},
        },
      }));
      return;
    }

    const requestId = capabilityRequestIdRef.current + 1;
    capabilityRequestIdRef.current = requestId;
    capabilityNonceRef.current[channel.id] = requestId;
    const nonce = requestId;

    setCapabilityStates((previous) => ({
      ...previous,
      [channel.id]: {
        selected,
        status: 'loading',
        resolveText: (locale) => locale.capabilityCheckingText,
        resolveHint: undefined,
        results: {},
      },
    }));

    try {
      const result = await systemConfigApi.testLLMChannel({
        name: channel.name,
        protocol: channel.protocol,
        apiSurface: channel.apiSurface as LLMApiSurface,
        baseUrl: channel.baseUrl,
        apiKey: channel.apiKey,
        models: splitModels(channel.models),
        enabled: channel.enabled,
        capabilityChecks: selected,
        useSavedSecret: shouldUseSavedHermesSecret(channel, maskToken, hasPersistedHermesSecret(channel)),
      });

      if (!mountedRef.current || capabilityNonceRef.current[channel.id] !== nonce) return;

      const capabilityResults = result.capabilityResults || {};
      const hasFailure = Object.values(capabilityResults).some((item) => item?.status === 'failed');
      const hasSkipped = Object.values(capabilityResults).some((item) => item?.status === 'skipped');
      setCapabilityStates((previous) => ({
        ...previous,
        [channel.id]: {
          selected,
          status: hasFailure || hasSkipped || !result.success ? 'error' : 'success',
          resolveText: (locale) => (
            Object.keys(capabilityResults).length > 0
              ? summarizeCapabilityResults(capabilityResults, locale)
              : result.success
                ? locale.capabilityNoResultsText
                : buildLlmFailureText(result, locale)
          ),
          resolveHint: (locale) => (
            getFirstCapabilityHint(capabilityResults, locale)
            || (!result.success ? buildLlmTestHint(result, locale) : undefined)
          ),
          results: capabilityResults,
        },
      }));
    } catch (error: unknown) {
      if (!mountedRef.current || capabilityNonceRef.current[channel.id] !== nonce) return;

      setCapabilityStates((previous) => ({
        ...previous,
        [channel.id]: {
          selected,
          status: 'error',
          resolveText: (locale, lang) => getParsedApiError(error, lang).message || locale.capabilityFailureFallback,
          resolveHint: undefined,
          results: {},
        },
      }));
    }
  };

  const toggleKeyVisibility = (channelId: string, nextVisible: boolean) => {
    setVisibleKeys((previous) => ({ ...previous, [channelId]: nextVisible }));
  };

  const toggleExpand = (channelId: string) => {
    setExpandedRows((previous) => ({ ...previous, [channelId]: !previous[channelId] }));
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
    <div className="space-y-4">
      <button
        type="button"
        className="flex w-full items-center justify-between rounded-[1.35rem] border border-[var(--settings-border)] bg-[var(--settings-surface)] px-5 py-4 text-left shadow-soft-card transition-[background-color,border-color,box-shadow] duration-200 hover:border-[var(--settings-border-strong)] hover:bg-[var(--settings-surface-hover)]"
        onClick={() => setIsCollapsed((previous) => !previous)}
      >
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-foreground">{text.headerTitle}</h3>
            <Badge variant="info" className="settings-accent-badge">{text.headerBadge}</Badge>
          </div>
          <p className="text-xs text-muted-text">
            {text.headerDesc}
          </p>
        </div>
        <span className="text-xs text-muted-text">{isCollapsed ? text.expandLabel : text.collapseLabel}</span>
      </button>

      {!isCollapsed ? (
        <div className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-300">
          <div className="rounded-[1.35rem] border border-[var(--settings-border)] bg-[var(--settings-surface)] p-4 shadow-soft-card">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h4 className="text-sm font-medium text-foreground">{text.quickAddTitle}</h4>
                <p className="mt-1 text-xs text-secondary-text">{text.quickAddDesc}</p>
              </div>
              <Badge variant="default" className="border-[var(--settings-border)] bg-[var(--settings-surface-hover)] text-muted-text">{text.channelCountBadge(channels.length)}</Badge>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" variant="settings-primary" className="whitespace-nowrap" disabled={busy} onClick={addChannel}>
                {text.addChannelButton}
              </Button>
              <div className="flex w-full min-w-0 items-center gap-2 sm:w-auto sm:flex-1">
                <Select
                  value={addPreset}
                  onChange={setAddPreset}
                  options={LLM_PROVIDER_TEMPLATES.map((preset) => ({
                    value: preset.channelId,
                    label: getProviderTemplateLabel(preset, language),
                  }))}
                  disabled={busy}
                  placeholder={text.selectProviderPlaceholder}
                  className="min-w-0 flex-1"
                />
                {registration ? (
                  <a
                    href={registration.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="settings-button-secondary inline-flex h-11 shrink-0 items-center justify-center whitespace-nowrap rounded-xl border px-3 text-sm font-medium transition-all duration-200 hover:translate-y-[-1px] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan/15"
                  >
                    {registration.label}
                  </a>
                ) : null}
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between px-1">
              <span className="text-xs font-medium uppercase tracking-wider text-muted-text">{text.channelListTitle}</span>
              {channels.length > 0 ? (
                <span className="text-[10px] text-muted-text">{text.enabledChannelsSummary(channels.filter((c) => c.enabled).length, channels.length)}</span>
              ) : null}
            </div>

            {channels.length === 0 ? (
              <div className="settings-surface-overlay-muted rounded-[1.35rem] border border-dashed settings-border-strong px-4 py-10 text-center">
                <p className="text-sm font-medium text-secondary-text">{text.emptyChannelsTitle}</p>
                <p className="mt-1 text-xs text-muted-text">{text.emptyChannelsDesc}</p>
              </div>
            ) : channels.map((channel, index) => (
              <ChannelRow
                key={channel.id}
                channel={channel}
                index={index}
                busy={busy}
                visibleKey={Boolean(visibleKeys[channel.id])}
                expanded={Boolean(expandedRows[channel.id])}
                testState={testStates[channel.id]}
                discoveryState={discoveryStates[channel.id]}
                capabilityState={capabilityStates[channel.id]}
                modelProviderPrefixes={modelProviderPrefixSet}
                onUpdate={updateChannel}
                onRemove={removeChannel}
                onToggleExpand={toggleExpand}
                onToggleKeyVisibility={toggleKeyVisibility}
                onTest={(ch) => void handleTest(ch)}
                onDiscoverModels={(channel) => void handleDiscoverModels(channel)}
                onToggleCapability={toggleCapability}
                onCheckCapabilities={(channel) => void handleCapabilityCheck(channel)}
              />
            ))}
          </div>

          {managesRuntimeConfig ? (
            <div className="rounded-[1.35rem] border border-[var(--settings-border)] bg-[var(--settings-surface)] p-4 shadow-soft-card">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <span className="settings-accent-text text-xs font-medium uppercase tracking-wider">{text.runtimeSectionTitle}</span>
                  <p className="mt-1 text-[11px] text-muted-text">{text.runtimeSectionDesc}</p>
                </div>
                <Badge variant="default" className="border-[var(--settings-border)] bg-[var(--settings-surface-hover)] text-muted-text">{text.runtimeBadge}</Badge>
              </div>
              <div className="mb-4">
                <HelpLabel
                  label={text.temperatureLabel}
                  fieldKey="LLM_TEMPERATURE"
                  helpKey="settings.llm_channel.temperature"
                  examples={['LLM_TEMPERATURE=0.2', 'LLM_TEMPERATURE=0.7']}
                  compact
                />
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min="0"
                    max="2"
                    step="0.1"
                    value={runtimeConfig.temperature}
                    disabled={busy}
                    onChange={(event) => setRuntimeConfig((previous) => ({ ...previous, temperature: event.target.value }))}
                    className="settings-input-checkbox h-1.5 flex-1 cursor-pointer rounded-full bg-border/60"
                  />
                  <span className="w-8 text-right text-sm text-secondary-text">{runtimeConfig.temperature}</span>
                </div>
                <p className="mt-1 text-[11px] text-secondary-text">
                  {text.temperatureDesc}
                </p>
              </div>

              {availableModels.length === 0 ? (
                <div className="rounded-xl border border-dashed settings-border-strong settings-surface-overlay-soft px-3 py-2 text-xs text-muted-text">
                  {text.noAvailableModelsNotice}
                </div>
              ) : (
                <div className="space-y-4">
                  <div>
                    <HelpLabel
                      htmlFor="runtime-primary-model"
                      label={text.primaryModelLabel}
                      fieldKey="LITELLM_MODEL"
                      helpKey="settings.llm_channel.primary_model"
                      examples={['LITELLM_MODEL=deepseek/deepseek-flash']}
                      compact
                    />
                    <Select
                      id="runtime-primary-model"
                      value={runtimeConfig.primaryModel}
                      onChange={setPrimaryModel}
                      options={buildModelOptions(availableModels, runtimeConfig.primaryModel, text.primaryModelAutoOption, text)}
                      disabled={busy}
                      placeholder=""
                    />
                  </div>

                  <div>
                    <HelpLabel
                      htmlFor="runtime-agent-primary-model"
                      label={text.agentPrimaryModelLabel}
                      fieldKey="AGENT_LITELLM_MODEL"
                      helpKey="settings.llm_channel.agent_primary_model"
                      examples={['AGENT_LITELLM_MODEL=deepseek/deepseek-v4-pro']}
                      compact
                    />
                    <Select
                      id="runtime-agent-primary-model"
                      value={runtimeConfig.agentPrimaryModel}
                      onChange={(value) => setRuntimeConfig((previous) => ({
                        ...previous,
                        agentPrimaryModel: normalizeAgentPrimaryModel(value),
                      }))}
                      options={buildModelOptions(
                        agentSafeModels,
                        agentSelectedModelForOptions,
                        text.agentPrimaryModelAutoOption,
                        text,
                      )}
                      disabled={busy}
                      placeholder=""
                    />
                  </div>

                  <div>
                    <HelpLabel
                      label={text.fallbackModelsLabel}
                      fieldKey="LITELLM_FALLBACK_MODELS"
                      helpKey="settings.llm_channel.fallback_models"
                      examples={['LITELLM_FALLBACK_MODELS=deepseek/deepseek-v4-pro,gemini/gemini-3.5-flash-lite']}
                      compact
                    />
                    <div className="space-y-2 rounded-xl border settings-border-strong settings-surface-overlay-soft p-3">
                      {availableModels.map((model) => (
                        <label key={model} className="flex items-center gap-2 text-sm text-secondary-text">
                          <input
                            type="checkbox"
                            checked={runtimeConfig.fallbackModels.includes(model)}
                            disabled={busy || model === runtimeConfig.primaryModel}
                            onChange={() => toggleFallbackModel(model)}
                            className="settings-input-checkbox h-4 w-4 rounded border-border/70 bg-base"
                          />
                          <span>{model}</span>
                        </label>
                      ))}
                    </div>
                    <p className="mt-1 text-[11px] text-secondary-text">
                      {text.fallbackModelsDesc}
                    </p>
                  </div>

                  <div>
                    <HelpLabel
                      htmlFor="runtime-vision-model"
                      label={text.visionModelLabel}
                      fieldKey="VISION_MODEL"
                      helpKey="settings.llm_channel.vision_model"
                      examples={['VISION_MODEL=gemini/gemini-3.6-flash']}
                      compact
                    />
                    <Select
                      id="runtime-vision-model"
                      value={runtimeConfig.visionModel}
                      onChange={(value) => setRuntimeConfig((previous) => ({ ...previous, visionModel: value }))}
                      options={buildModelOptions(
                        visionSafeModels,
                        visionSelectedModelForOptions,
                        text.visionModelAutoOption,
                        text,
                      )}
                      disabled={busy}
                      placeholder=""
                    />
                  </div>
                </div>
              )}
            </div>
          ) : (
            <InlineAlert
              variant="warning"
              message={text.yamlActiveNotice}
              className="rounded-[1.35rem] px-4 py-3 text-xs shadow-none"
            />
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="settings-primary"
              glow
              disabled={busy || !hasChanges}
              onClick={() => void handleSave()}
            >
              {isSaving ? text.savingButton : managesRuntimeConfig ? text.saveAiConfigButton : text.saveChannelsButton}
            </Button>
            {!hasChanges ? <span className="text-xs text-muted-text">{text.noUnsavedChanges}</span> : null}
          </div>

          {saveMessage?.type === 'success' ? (
            <InlineAlert
              variant="success"
              message={text[saveMessage.key]}
              className="rounded-lg px-3 py-2 text-sm shadow-none"
            />
          ) : null}

          {saveWarnings.length > 0 ? (
            <InlineAlert
              variant="warning"
              title={text.saveWarningsTitle}
              message={(
                <div className="space-y-1">
                  {saveWarnings.map((warning) => (
                    <p key={warning}>{warning}</p>
                  ))}
                </div>
              )}
              className="rounded-lg px-3 py-2 text-sm shadow-none"
            />
          ) : null}

          {saveMessage?.type === 'local-error' ? (
            <InlineAlert
              variant="danger"
              message={text[saveMessage.key]}
              className="rounded-lg px-3 py-2 text-sm shadow-none"
            />
          ) : null}

          {saveMessage?.type === 'error' ? <ApiErrorAlert error={getParsedApiError(saveMessage.rawError, language)} /> : null}
        </div>
      ) : null}
    </div>
  );
};
