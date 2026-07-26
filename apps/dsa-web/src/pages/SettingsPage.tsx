import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, ChevronDown, CircleAlert, CircleDashed, Clock, Play, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useAuth, useSystemConfig, useUnsavedChangesGuard } from '../hooks';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { createParsedApiError, getParsedApiError, type ParsedApiError } from '../api/error';
import { analysisApi } from '../api/analysis';
import { alphasiftApi, notifyAlphaSiftConfigChanged, notifySystemConfigChanged } from '../api/alphasift';
import { systemConfigApi } from '../api/systemConfig';
import { ApiErrorAlert, Button, ConfirmDialog, EmptyState } from '../components/common';
import {
  AgentBackendStatusPanel,
  AuthSettingsCard,
  ChangePasswordCard,
  GenerationBackendStatusPanel,
  IntelligentImport,
  LLMChannelEditor,
  type LLMChannelEditorHandle,
  NotificationTestPanel,
  SettingsCategoryNav,
  SettingsAlert,
  SettingsField,
  SettingsLoading,
  SettingsPanelErrorBoundary,
  SettingsSectionCard,
} from '../components/settings';
import { WEB_BUILD_INFO } from '../utils/constants';
import { parseStockListValue } from '../utils/stockList';
import { getCategoryDescription, getCategoryTitle } from '../utils/systemConfigI18n';
import type {
  ConfigValidationIssue,
  SchedulerStatusResponse,
  SetupStatusCheck,
  SetupStatusResponse,
  SystemConfigCategory,
  SystemConfigItem,
  SystemConfigUpdateItem,
} from '../types/systemConfig';
import type { UiLanguage, UiTextKey } from '../i18n/uiText';

type DesktopWindow = Window & {
  dsaDesktop?: {
    version?: unknown;
    getUpdateState?: () => Promise<RawDesktopUpdateState>;
    checkForUpdates?: () => Promise<RawDesktopUpdateState>;
    installDownloadedUpdate?: () => Promise<boolean>;
    openReleasePage?: (releaseUrl?: string) => Promise<boolean>;
    onUpdateStateChange?: (listener: (state: RawDesktopUpdateState) => void) => (() => void) | void;
  };
};

type DesktopUpdateState = {
  status?: string;
  updateMode?: string;
  currentVersion?: string;
  latestVersion?: string;
  releaseUrl?: string;
  checkedAt?: string;
  publishedAt?: string;
  message?: string;
  releaseName?: string;
  tagName?: string;
  downloadPercent?: number | null;
  downloadedBytes?: number | null;
  totalBytes?: number | null;
};

type RawDesktopUpdateState = {
  status?: unknown;
  updateMode?: unknown;
  currentVersion?: unknown;
  latestVersion?: unknown;
  releaseUrl?: unknown;
  checkedAt?: unknown;
  publishedAt?: unknown;
  message?: unknown;
  releaseName?: unknown;
  tagName?: unknown;
  downloadPercent?: unknown;
  downloadedBytes?: unknown;
  totalBytes?: unknown;
};

type DesktopUpdateNotice = {
  title: string;
  message: string;
  variant: 'error' | 'success' | 'warning';
  actionLabel?: string;
  actionKind?: 'release' | 'install';
};

const LLM_CHANNEL_EDITOR_RUNTIME_KEYS = new Set([
  'LITELLM_MODEL',
  'LITELLM_FALLBACK_MODELS',
  'AGENT_LITELLM_MODEL',
  'VISION_MODEL',
  'LLM_TEMPERATURE',
]);
const GENERATION_BACKEND_STATUS_KEYS = new Set([
  'GENERATION_BACKEND',
  'GENERATION_FALLBACK_BACKEND',
  'GENERATION_BACKEND_TIMEOUT_SECONDS',
  'GENERATION_BACKEND_MAX_OUTPUT_BYTES',
  'GENERATION_BACKEND_MAX_CONCURRENCY',
  'LOCAL_CLI_BACKEND_MAX_CONCURRENCY',
  'OPENCODE_CLI_MODEL',
  'LITELLM_CONFIG',
  'LITELLM_MODEL',
  'LITELLM_FALLBACK_MODELS',
  'GEMINI_API_KEY',
  'GEMINI_API_KEYS',
  'GEMINI_MODEL',
  'GEMINI_MODEL_FALLBACK',
  'GEMINI_TEMPERATURE',
  'ANTHROPIC_API_KEY',
  'ANTHROPIC_API_KEYS',
  'ANTHROPIC_MODEL',
  'ANTHROPIC_TEMPERATURE',
  'ANTHROPIC_MAX_TOKENS',
  'OPENAI_API_KEY',
  'OPENAI_API_KEYS',
  'OPENAI_BASE_URL',
  'OPENAI_MODEL',
  'OPENAI_VISION_MODEL',
  'OPENAI_TEMPERATURE',
  'OLLAMA_API_BASE',
  'OLLAMA_MODEL',
  'DEEPSEEK_API_KEY',
  'DEEPSEEK_API_KEYS',
  'AIHUBMIX_KEY',
  'ANSPIRE_LLM_ENABLED',
  'ANSPIRE_LLM_BASE_URL',
  'ANSPIRE_LLM_MODEL',
  'ANSPIRE_API_KEYS',
]);
const LLM_CHANNEL_STATUS_KEY_PATTERN = /^LLM_[A-Z0-9_]+_(PROTOCOL|BASE_URL|API_KEY|API_KEYS|MODELS|EXTRA_HEADERS|ENABLED)$/;
const AGENT_BACKEND_STATUS_KEYS = new Set([
  'AGENT_BACKEND',
  'AGENT_GENERATION_BACKEND',
  'AGENT_LITELLM_MODEL',
  'AGENT_MODE',
  'AGENT_ARCH',
  'AGENT_ORCHESTRATOR_TIMEOUT_S',
]);

function isLlmChannelEditorDraftKey(key: string): boolean {
  const normalized = key.trim().toUpperCase();
  return normalized.startsWith('LLM_') || LLM_CHANNEL_EDITOR_RUNTIME_KEYS.has(normalized);
}

function isGenerationBackendStatusDraftKey(key: string): boolean {
  const normalized = key.trim().toUpperCase();
  return (
    GENERATION_BACKEND_STATUS_KEYS.has(normalized)
    || normalized === 'LLM_CHANNELS'
    || LLM_CHANNEL_STATUS_KEY_PATTERN.test(normalized)
  );
}

function mergeGenerationBackendDraftItems(
  outerItems: SystemConfigUpdateItem[],
  llmChannelItems: SystemConfigUpdateItem[],
): SystemConfigUpdateItem[] {
  const merged = new Map<string, SystemConfigUpdateItem>();
  for (const item of outerItems) {
    const normalizedKey = item.key.trim().toUpperCase();
    if (isGenerationBackendStatusDraftKey(normalizedKey)) {
      merged.set(normalizedKey, item);
    }
  }
  for (const item of llmChannelItems) {
    const normalizedKey = item.key.trim().toUpperCase();
    if (isLlmChannelEditorDraftKey(normalizedKey) && isGenerationBackendStatusDraftKey(normalizedKey)) {
      merged.set(normalizedKey, item);
    }
  }
  return Array.from(merged.values());
}

const PROMPT_CACHE_ADVANCED_SETTING_KEYS = new Set([
  'LLM_PROMPT_CACHE_TELEMETRY_ENABLED',
  'LLM_PROMPT_CACHE_HINTS_ENABLED',
  'LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL',
]);

function isPromptCacheAdvancedSetting(item: { key: string }) {
  return PROMPT_CACHE_ADVANCED_SETTING_KEYS.has(item.key);
}

function trimDesktopRuntimeString(value: unknown) {
  return typeof value === 'string' ? value.trim() : '';
}

function normalizeDesktopRuntimeNumber(value: unknown) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const numberValue = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function getDesktopRuntimeApi() {
  if (typeof window === 'undefined') {
    return undefined;
  }

  return (window as DesktopWindow).dsaDesktop;
}

function getDesktopAppVersion() {
  return trimDesktopRuntimeString(getDesktopRuntimeApi()?.version);
}

function normalizeDesktopUpdateState(state: RawDesktopUpdateState | null | undefined) {
  if (!state || typeof state !== 'object') {
    return null;
  }

  return {
    status: trimDesktopRuntimeString(state.status) || 'idle',
    updateMode: trimDesktopRuntimeString(state.updateMode) || 'manual',
    currentVersion: trimDesktopRuntimeString(state.currentVersion),
    latestVersion: trimDesktopRuntimeString(state.latestVersion),
    releaseUrl: trimDesktopRuntimeString(state.releaseUrl),
    checkedAt: trimDesktopRuntimeString(state.checkedAt),
    publishedAt: trimDesktopRuntimeString(state.publishedAt),
    message: trimDesktopRuntimeString(state.message),
    releaseName: trimDesktopRuntimeString(state.releaseName),
    tagName: trimDesktopRuntimeString(state.tagName),
    downloadPercent: normalizeDesktopRuntimeNumber(state.downloadPercent),
    downloadedBytes: normalizeDesktopRuntimeNumber(state.downloadedBytes),
    totalBytes: normalizeDesktopRuntimeNumber(state.totalBytes),
  };
}

function getDesktopUpdateNotice(
  state: DesktopUpdateState | null,
  t: (key: UiTextKey, params?: Record<string, string | number>) => string,
): DesktopUpdateNotice | null {
  if (!state) {
    return null;
  }

  if (state.status === 'update-available') {
    const latestLabel = state.latestVersion || state.tagName || t('settings.desktopLatest');
    const currentLabel = state.currentVersion || getDesktopAppVersion() || WEB_BUILD_INFO.version;
    return {
      title: t('settings.desktopUpdateAvailable'),
      message: t('settings.desktopUpdateMessage', {
        current: currentLabel,
        latest: latestLabel,
        message: state.message || t('settings.desktopUpdateReleaseMessage'),
      }),
      variant: 'warning' as const,
      actionLabel: state.updateMode === 'auto' ? undefined : t('settings.desktopDownload'),
      actionKind: state.updateMode === 'auto' ? undefined : 'release',
    };
  }

  if (state.status === 'downloading') {
    const percentText = typeof state.downloadPercent === 'number' ? `（${state.downloadPercent}%）` : '';
    return {
      title: t('settings.desktopDownloading'),
      message: state.message || t('settings.desktopUpdateDownloadingMessage', { percent: percentText }),
      variant: 'warning' as const,
    };
  }

  if (state.status === 'update-downloaded') {
    return {
      title: t('settings.desktopDownloaded'),
      message: state.message || t('settings.desktopUpdateDownloadedMessage'),
      variant: 'success' as const,
      actionLabel: t('settings.desktopInstall'),
      actionKind: 'install',
    };
  }

  if (state.status === 'installing') {
    return {
      title: t('settings.desktopInstalling'),
      message: state.message || t('settings.desktopUpdateInstallingMessage'),
      variant: 'warning' as const,
    };
  }

  if (state.status === 'up-to-date') {
    return {
      title: t('settings.desktopUpToDate'),
      message: state.message || t('settings.desktopUpToDateMessage'),
      variant: 'success' as const,
    };
  }

  if (state.status === 'checking') {
    return {
      title: t('settings.desktopChecking'),
      message: state.message || t('settings.desktopUpdateCheckingMessage'),
      variant: 'warning' as const,
    };
  }

  if (state.status === 'error') {
    return {
      title: t('settings.desktopCheckError'),
      message: state.message || t('settings.desktopUpdateErrorMessage'),
      variant: 'error' as const,
      actionLabel: state.updateMode === 'auto' && state.releaseUrl ? t('settings.desktopDownload') : undefined,
      actionKind: state.updateMode === 'auto' && state.releaseUrl ? 'release' : undefined,
    };
  }

  return null;
}

function formatEnvBackupFilename(isDesktopRuntime: boolean) {
  const now = new Date();
  const pad = (value: number) => value.toString().padStart(2, '0');
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `${isDesktopRuntime ? 'dsa-desktop-env' : 'dsa-env'}_${date}_${time}.env`;
}

const SCHEDULE_TIME_PATTERN = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
const SCHEDULER_DEFAULT_TIME = '18:00';
const SCHEDULER_SETTING_KEYS = new Set([
  'SCHEDULE_ENABLED',
  'SCHEDULE_TIME',
  'SCHEDULE_TIMES',
  'SCHEDULE_RUN_IMMEDIATELY',
]);

function getConfigItem(items: SystemConfigItem[], key: string) {
  return items.find((item) => item.key === key);
}

function parseSetupStockList(value: unknown) {
  return parseStockListValue(String(value ?? ''));
}

function isEnabledConfigValue(value: unknown) {
  return String(value ?? '').trim().toLowerCase() === 'true';
}

function getSetupCheckIcon(check: SetupStatusCheck) {
  if (check.status === 'configured' || check.status === 'inherited') {
    return <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />;
  }
  if (check.status === 'needs_action') {
    return <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />;
  }
  return <CircleDashed className="mt-0.5 h-4 w-4 shrink-0 text-muted-text" aria-hidden="true" />;
}

function getSetupCheckStatusLabel(
  check: SetupStatusCheck,
  t: (key: UiTextKey, params?: Record<string, string | number>) => string,
) {
  if (check.status === 'configured') return t('settings.setupStatusConfigured');
  if (check.status === 'inherited') return t('settings.setupStatusInherited');
  if (check.status === 'needs_action') return t('settings.setupStatusNeedsAction');
  return t('settings.setupStatusOptional');
}

type FirstRunSetupCardProps = {
  status: SetupStatusResponse | null;
  isLoading: boolean;
  error: ParsedApiError | null;
  firstStockCode: string;
  isSaving: boolean;
  isRunningSmoke: boolean;
  smokeError: ParsedApiError | null;
  smokeSuccess: string;
  onRefresh: () => void | Promise<void>;
  onSelectCategory: (category: SystemConfigCategory) => void;
  onRunSmoke: () => void | Promise<void>;
  listSeparator: string;
  t: (key: UiTextKey, params?: Record<string, string | number>) => string;
};

const FirstRunSetupCard: React.FC<FirstRunSetupCardProps> = ({
  status,
  isLoading,
  error,
  firstStockCode,
  isSaving,
  isRunningSmoke,
  smokeError,
  smokeSuccess,
  onRefresh,
  onSelectCategory,
  onRunSmoke,
  listSeparator,
  t,
}) => {
  const [isHidden, setIsHidden] = useState(false);
  const requiredMissing = status?.checks.filter((check) => check.required && check.status === 'needs_action') || [];
  const isComplete = Boolean(status?.isComplete);
  const canRunSmoke = Boolean(status?.readyForSmoke && firstStockCode);
  const summaryTitle = !status
    ? error
      ? t('settings.setupGuideUnknownTitle')
      : t('settings.setupGuideCheckingTitle')
    : isComplete
      ? t('settings.setupGuideCompleteTitle')
      : t('settings.setupGuideIncompleteTitle');
  const summaryMessage = !status
    ? error
      ? t('settings.setupGuideUnknownSummary')
      : t('settings.setupGuideCheckingSummary')
    : requiredMissing.length
      ? t('settings.setupGuideMissingSummary', {
        count: requiredMissing.length,
        labels: requiredMissing.slice(0, 3).map((check) => check.title).join(listSeparator),
      })
      : t('settings.setupGuideReadySummary');

  if (isHidden) {
    return (
      <div className="rounded-2xl border settings-border bg-card/90 px-4 py-3 shadow-soft-card">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-semibold text-foreground">{t('settings.setupGuideHiddenTitle')}</p>
            <p className="mt-1 text-xs leading-5 text-muted-text">{t('settings.setupGuideHiddenDescription')}</p>
          </div>
          <Button type="button" variant="settings-secondary" size="sm" onClick={() => setIsHidden(false)}>
            {t('settings.setupGuideOpen')}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <SettingsSectionCard
      title={t('settings.setupGuideTitle')}
      description={t('settings.setupGuideDescription')}
    >
      <div data-testid="first-run-setup-card" className="space-y-4">
        <div className="flex flex-col gap-3 rounded-2xl border settings-border bg-background/35 px-4 py-4 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground">
              {summaryTitle}
            </p>
            <p className="mt-1 text-xs leading-6 text-muted-text">
              {summaryMessage}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="settings-secondary"
              size="sm"
              disabled={isLoading}
              isLoading={isLoading}
              loadingText={t('settings.setupGuideRefreshing')}
              onClick={() => void onRefresh()}
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              {t('settings.setupGuideRefresh')}
            </Button>
            <Button type="button" variant="settings-secondary" size="sm" onClick={() => setIsHidden(true)}>
              {t('settings.setupGuideHide')}
            </Button>
          </div>
        </div>

        {error ? <ApiErrorAlert error={error} /> : null}

        {isLoading && !status ? (
          <p className="text-sm text-muted-text">{t('common.loading')}</p>
        ) : null}

        {status ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {status.checks.map((check) => (
              <div
                key={check.key}
                className="rounded-2xl border settings-border bg-card/65 px-4 py-3"
              >
                <div className="flex items-start gap-3">
                  {getSetupCheckIcon(check)}
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-foreground">{check.title}</p>
                      <span className="rounded-full border settings-border bg-background/60 px-2 py-0.5 text-[11px] font-medium text-muted-text">
                        {getSetupCheckStatusLabel(check, t)}
                      </span>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-muted-text">{check.message}</p>
                    {check.nextStep ? (
                      <p className="mt-2 text-xs leading-5 text-secondary-text">{check.nextStep}</p>
                    ) : null}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="settings-secondary" size="sm" onClick={() => onSelectCategory('ai_model')}>
            {t('settings.setupGuideConfigureLlm')}
          </Button>
          <Button type="button" variant="settings-secondary" size="sm" onClick={() => onSelectCategory('base')}>
            {t('settings.setupGuideAddStocks')}
          </Button>
          <Button type="button" variant="settings-secondary" size="sm" onClick={() => onSelectCategory('notification')}>
            {t('settings.setupGuideConfigureNotification')}
          </Button>
          <Button
            type="button"
            variant="settings-primary"
            size="sm"
            disabled={!canRunSmoke || isSaving || isRunningSmoke}
            isLoading={isRunningSmoke}
            loadingText={t('settings.setupGuideSmokeRunning')}
            title={!firstStockCode ? t('settings.setupGuideSmokeNeedsStock') : undefined}
            onClick={() => void onRunSmoke()}
          >
            <Play className="h-4 w-4" aria-hidden="true" />
            {t('settings.setupGuideRunSmoke')}
          </Button>
        </div>

        {!canRunSmoke && status ? (
          <p className="text-xs leading-6 text-muted-text">
            {firstStockCode ? t('settings.setupGuideSmokeNotReady') : t('settings.setupGuideSmokeNeedsStock')}
          </p>
        ) : null}
        {smokeError ? <ApiErrorAlert error={smokeError} /> : null}
        {!smokeError && smokeSuccess ? (
          <SettingsAlert title={t('settings.actionSuccess')} message={smokeSuccess} variant="success" />
        ) : null}
      </div>
    </SettingsSectionCard>
  );
};

function parseScheduleTimes(scheduleTimesValue?: string, fallbackValue?: string) {
  const values = String(scheduleTimesValue ?? '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);

  if (values.length > 0) {
    return values;
  }

  const fallback = String(fallbackValue ?? '').trim();
  return fallback ? [fallback] : [SCHEDULER_DEFAULT_TIME];
}

function serializeScheduleTimes(times: string[]) {
  return times.map((time) => time.trim()).filter(Boolean).join(',');
}

function formatSchedulerTimestamp(value: string | null | undefined, language: UiLanguage) {
  if (!value) {
    return '-';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(language === 'en' ? 'en-US' : 'zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

type SchedulerSettingsCardProps = {
  items: SystemConfigItem[];
  disabled: boolean;
  issueByKey: Record<string, ConfigValidationIssue[]>;
  statusRefreshToken: number;
  onChange: (key: string, value: string) => void;
  onSchedulerStateChange?: (payload: {
    runtimeEnabled: boolean | null;
    overrideEnabled: boolean | null;
  }) => void;
  t: (key: UiTextKey, params?: Record<string, string | number>) => string;
  language: UiLanguage;
};

const SchedulerSettingsCard: React.FC<SchedulerSettingsCardProps> = ({
  items,
  disabled,
  issueByKey,
  statusRefreshToken,
  onChange,
  onSchedulerStateChange,
  t,
  language,
}) => {
  const scheduleEnabledItem = getConfigItem(items, 'SCHEDULE_ENABLED');
  const scheduleTimesItem = getConfigItem(items, 'SCHEDULE_TIMES');
  const scheduleTimeItem = getConfigItem(items, 'SCHEDULE_TIME');
  const hasSchedulerSettings = Boolean(scheduleEnabledItem || scheduleTimesItem || scheduleTimeItem);
  const [status, setStatus] = useState<SchedulerStatusResponse | null>(null);
  const [isRefreshingStatus, setIsRefreshingStatus] = useState(false);
  const [isRunningNow, setIsRunningNow] = useState(false);
  const [statusError, setStatusError] = useState<ParsedApiError | null>(null);
  const [runNowError, setRunNowError] = useState<ParsedApiError | null>(null);
  const [runNowSuccess, setRunNowSuccess] = useState('');
  const [scheduleEnabledOverride, setScheduleEnabledOverride] = useState<boolean | null>(null);

  const refreshSchedulerStatus = useCallback(async () => {
    setStatusError(null);
    setIsRefreshingStatus(true);
    try {
      const payload = await systemConfigApi.getSchedulerStatus();
      setStatus(payload);
    } catch (error: unknown) {
      setStatusError(getParsedApiError(error));
    } finally {
      setIsRefreshingStatus(false);
    }
  }, []);

  useEffect(() => {
    if (!hasSchedulerSettings) {
      return;
    }
    void refreshSchedulerStatus();
  }, [hasSchedulerSettings, refreshSchedulerStatus, statusRefreshToken]);

  useEffect(() => {
    if (!onSchedulerStateChange) {
      return;
    }

    const runtimeEnabled = status?.enabled ?? null;
    onSchedulerStateChange({
      runtimeEnabled,
      overrideEnabled: scheduleEnabledOverride,
    });
  }, [onSchedulerStateChange, status?.enabled, scheduleEnabledOverride]);

  if (!hasSchedulerSettings) {
    return null;
  }

  const scheduleEnabled = isEnabledConfigValue(scheduleEnabledItem?.value);
  const scheduleTimes = parseScheduleTimes(
    String(scheduleTimesItem?.value ?? ''),
    String(scheduleTimeItem?.value ?? ''),
  );
  const timeTargetKey = scheduleTimesItem ? 'SCHEDULE_TIMES' : 'SCHEDULE_TIME';
  const statusEnabled = status?.enabled ?? scheduleEnabled;
  const displayedScheduleEnabled = scheduleEnabledOverride ?? statusEnabled;
  const effectiveStatusTimes = status?.scheduleTimes?.length ? status.scheduleTimes : scheduleTimes.filter(Boolean);
  const validationIssues = [
    ...(issueByKey.SCHEDULE_ENABLED || []),
    ...(issueByKey.SCHEDULE_TIMES || []),
    ...(issueByKey.SCHEDULE_TIME || []),
  ];

  const updateScheduleTimes = (nextTimes: string[]) => {
    if (timeTargetKey === 'SCHEDULE_TIME') {
      onChange(timeTargetKey, nextTimes[0] || '');
      return;
    }
    onChange(timeTargetKey, serializeScheduleTimes(nextTimes));
  };

  const runSchedulerNow = async () => {
    setRunNowError(null);
    setRunNowSuccess('');
    setIsRunningNow(true);
    try {
      await systemConfigApi.runSchedulerNow();
      setRunNowSuccess(t('settings.schedulerRunAccepted'));
      await refreshSchedulerStatus();
    } catch (error: unknown) {
      setRunNowError(getParsedApiError(error));
    } finally {
      setIsRunningNow(false);
    }
  };

  return (
    <SettingsSectionCard
      title={t('settings.schedulerTitle')}
      description={t('settings.schedulerDescription')}
    >
      <div data-testid="scheduler-settings-card" className="space-y-4">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(300px,360px)]">
          <div className="space-y-4 rounded-2xl border settings-border bg-background/35 px-4 py-4">
                <label className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 rounded border-border text-cyan focus:ring-cyan/20"
                    checked={displayedScheduleEnabled}
                    data-testid="scheduler-enabled-checkbox"
                    disabled={disabled || !scheduleEnabledItem?.schema?.isEditable}
                    onChange={(event) => {
                      const nextEnabled = Boolean(event.target.checked);
                      setScheduleEnabledOverride(nextEnabled);
                      onChange('SCHEDULE_ENABLED', nextEnabled ? 'true' : 'false');
                    }}
                  />
              <span>
                <span className="block text-sm font-semibold text-foreground">{t('settings.schedulerEnable')}</span>
                <span className="block text-xs leading-6 text-muted-text">{t('settings.schedulerEnableDescription')}</span>
              </span>
            </label>

            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Clock className="h-4 w-4" aria-hidden="true" />
                {t('settings.schedulerTimes')}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {scheduleTimes.map((time, index) => (
                  <div
                    key={index}
                    className="inline-flex h-11 shrink-0 items-center gap-1 rounded-xl border settings-border bg-card/90 p-1 shadow-inner"
                  >
                    <input
                      data-testid={`scheduler-time-input-${index}`}
                      type="time"
                      value={SCHEDULE_TIME_PATTERN.test(time) ? time : ''}
                      aria-label={t('settings.schedulerTimeInputAria', { index: index + 1 })}
                      className="h-9 w-[8.75rem] rounded-lg border-none bg-transparent px-2 text-sm font-medium text-foreground outline-none transition focus:bg-background/60 focus:ring-2 focus:ring-cyan/20"
                      disabled={disabled}
                      onChange={(event) => {
                        const nextTimes = scheduleTimes.map((currentTime, currentIndex) => (
                          currentIndex === index ? event.target.value : currentTime
                        ));
                        updateScheduleTimes(nextTimes);
                      }}
                    />
                    {scheduleTimes.length > 1 ? (
                      <Button
                        type="button"
                        variant="settings-secondary"
                        size="sm"
                        className="h-8 w-8 rounded-lg px-0"
                        aria-label={t('settings.schedulerRemoveTime')}
                        title={t('settings.schedulerRemoveTime')}
                        disabled={disabled}
                        onClick={() => {
                          updateScheduleTimes(scheduleTimes.filter((_, currentIndex) => currentIndex !== index));
                        }}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    ) : null}
                  </div>
                ))}
                <Button
                  type="button"
                  variant="settings-secondary"
                  size="sm"
                  className="h-11 shrink-0"
                  data-testid="scheduler-add-time-button"
                  disabled={disabled}
                  onClick={() => updateScheduleTimes([...scheduleTimes, SCHEDULER_DEFAULT_TIME])}
                >
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  {t('settings.schedulerAddTime')}
                </Button>
              </div>
            </div>
          </div>

          <div className="space-y-3 rounded-2xl border settings-border bg-background/35 px-4 py-4">
            <div>
              <p className="text-sm font-semibold text-foreground">{t('settings.schedulerStatus')}</p>
              <p className="mt-1 text-xs leading-6 text-muted-text">
                {status?.running
                  ? t('settings.schedulerRunning')
                  : statusEnabled
                    ? t('settings.schedulerEnabled')
                    : t('settings.schedulerDisabled')}
              </p>
            </div>
            <dl className="grid grid-cols-1 gap-2 text-xs">
              <div className="rounded-xl border settings-border bg-card/60 px-3 py-2">
                <dt className="text-muted-text">{t('settings.schedulerEffectiveTimes')}</dt>
                <dd className="mt-1 font-medium text-foreground">{effectiveStatusTimes.join(', ') || '-'}</dd>
              </div>
              <div className="rounded-xl border settings-border bg-card/60 px-3 py-2">
                <dt className="text-muted-text">{t('settings.schedulerNextRun')}</dt>
                <dd className="mt-1 font-medium text-foreground">
                  {formatSchedulerTimestamp(status?.nextRunAt, language)}
                </dd>
              </div>
              <div className="rounded-xl border settings-border bg-card/60 px-3 py-2">
                <dt className="text-muted-text">{t('settings.schedulerLastSuccess')}</dt>
                <dd data-testid="scheduler-last-success" className="mt-1 font-medium text-foreground">
                  {formatSchedulerTimestamp(status?.lastSuccessAt, language)}
                </dd>
              </div>
              {status?.lastError ? (
                <div className="rounded-xl border border-danger/40 bg-danger/10 px-3 py-2">
                  <dt className="text-danger">{t('settings.schedulerLastError')}</dt>
                  <dd data-testid="scheduler-last-error" className="mt-1 break-words text-danger">{status.lastError}</dd>
                </div>
              ) : null}
            </dl>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="settings-secondary"
                size="sm"
                data-testid="scheduler-refresh-status-button"
                disabled={disabled || isRefreshingStatus}
                isLoading={isRefreshingStatus}
                loadingText={t('settings.schedulerRefreshing')}
                onClick={() => void refreshSchedulerStatus()}
              >
                <RefreshCw className="h-4 w-4" aria-hidden="true" />
                {t('settings.schedulerRefresh')}
              </Button>
              <Button
                type="button"
                variant="settings-primary"
                size="sm"
                data-testid="scheduler-run-now-button"
                disabled={disabled || isRunningNow}
                isLoading={isRunningNow}
                loadingText={t('settings.schedulerRunningNow')}
                onClick={() => void runSchedulerNow()}
              >
                <Play className="h-4 w-4" aria-hidden="true" />
                {t('settings.schedulerRunNow')}
              </Button>
            </div>
          </div>
        </div>

        {validationIssues.length ? (
          <div className="space-y-1 text-xs text-danger">
            {validationIssues.map((issue) => (
              <p key={`${issue.key}-${issue.code}`}>{issue.message}</p>
            ))}
          </div>
        ) : null}
        {statusError ? <ApiErrorAlert error={statusError} /> : null}
        {runNowError ? <ApiErrorAlert error={runNowError} /> : null}
        {!runNowError && runNowSuccess ? (
          <SettingsAlert title={t('settings.actionSuccess')} message={runNowSuccess} variant="success" />
        ) : null}
      </div>
    </SettingsSectionCard>
  );
};

const SettingsPage: React.FC = () => {
  const { authEnabled, passwordChangeable } = useAuth();
  const { language: uiLanguage, t } = useUiLanguage();
  const [envBackupActionError, setEnvBackupActionError] = useState<ParsedApiError | null>(null);
  const [envBackupActionSuccess, setEnvBackupActionSuccess] = useState<string>('');
  const [alphaSiftActionError, setAlphaSiftActionError] = useState<ParsedApiError | null>(null);
  const [alphaSiftActionSuccess, setAlphaSiftActionSuccess] = useState<string>('');
  const [isExportingEnv, setIsExportingEnv] = useState(false);
  const [isImportingEnv, setIsImportingEnv] = useState(false);
  const [isUpdatingAlphaSift, setIsUpdatingAlphaSift] = useState(false);
  const [showImportConfirm, setShowImportConfirm] = useState(false);
  const [desktopUpdateState, setDesktopUpdateState] = useState<DesktopUpdateState | null>(null);
  const [isCheckingDesktopUpdate, setIsCheckingDesktopUpdate] = useState(false);
  const [schedulerStatusRefreshToken, setSchedulerStatusRefreshToken] = useState(0);
  const [schedulerRuntimeEnabled, setSchedulerRuntimeEnabled] = useState<boolean | null>(null);
  const [schedulerOverrideFromUi, setSchedulerOverrideFromUi] = useState<boolean | null>(null);
  const [setupStatus, setSetupStatus] = useState<SetupStatusResponse | null>(null);
  const [isRefreshingSetupStatus, setIsRefreshingSetupStatus] = useState(false);
  const [setupStatusError, setSetupStatusError] = useState<ParsedApiError | null>(null);
  const [isRunningSetupSmoke, setIsRunningSetupSmoke] = useState(false);
  const [setupSmokeError, setSetupSmokeError] = useState<ParsedApiError | null>(null);
  const [setupSmokeSuccess, setSetupSmokeSuccess] = useState('');
  const [llmChannelDraftItems, setLlmChannelDraftItems] = useState<SystemConfigUpdateItem[]>([]);
  // LLMChannelEditor 的 imperative handle。SettingsPage.handleSaveConfig 在普通草稿保存
  // 成功后调用 editorRef.current?.submit(),触发 channel 草稿的独立提交(API call)。
  // 这条提交路径保留了 LLMChannelEditor 内部完整的 validation 链路,由 editor 自己的
  // setSaveMessage 显示错误。详见 issue #1948 与 ZhuLinsen 2026-07-21 06:43 评论第 1 条。
  const llmChannelEditorRef = useRef<LLMChannelEditorHandle | null>(null);

  // OR-COR-62780a0c: useSystemConfig.isSaving 只反映普通草稿段保存,LLM 渠道段
  // submit() 进行中时父层 isSaving 已复位——顶部/底部全局"保存/放弃修改"按钮只依赖
  // isSaving,会在窗口期内重新启用,允许用户再次触发保存(对同一份 channel 草稿产生
  // 并发写)或先点放弃再等在途 channel 响应(状态反转)。这里用独立 state 跟踪 channel
  // 段保存进行中,与 isSaving || isLoading 组合成 pageSaveInFlight,供给所有全局按钮
  // disabled 与 useUnsavedChangesGuard 的 hasDirty, 二段式保存语义下也防止离开页面。
  const [channelSaveInProgress, setChannelSaveInProgress] = useState(false);
  // OR-COR-b1b25240: channel 段 API 失败时记录的错误对象, 配合 inline 错误提示组件在
  // 全局"保存/放弃修改"工具区附近渲染。channel 段成功保存或用户主动 reset 草稿时清空。
  const [channelSaveError, setChannelSaveError] = useState<ParsedApiError | null>(null);

  const envBackupImportRef = useRef<HTMLInputElement | null>(null);
  const setupStatusRequestIdRef = useRef(0);
  const desktopRuntimeApi = getDesktopRuntimeApi();
  const isDesktopRuntime = Boolean(desktopRuntimeApi);
  const canCheckDesktopUpdate = Boolean(
    desktopRuntimeApi?.getUpdateState && desktopRuntimeApi?.checkForUpdates && desktopRuntimeApi?.openReleasePage
  );
  const desktopAppVersion = getDesktopAppVersion();
  const shouldShowDesktopVersionCard = Boolean(desktopAppVersion);

  // Set page title
  useEffect(() => {
    document.title = t('settings.pageTitleDocument');
  }, [t]);

  const {
    categories,
    itemsByCategory,
    keyToCategory,
    issueByKey,
    activeCategory,
    setActiveCategory,
    hasDirty,
    dirtyCount,
    toast,
    clearToast,
    showSuccessToast,
    showErrorToast,
    isLoading,
    isSaving,
    loadError,
    saveError,
    retryAction,
    load,
    retry,
    save,
    resetDraft,
    setDraftValue,
    getChangedItems,
    refreshAfterExternalSave,
    configVersion,
    latestConfigVersionRef,
    maskToken,
  } = useSystemConfig();

  const currentChangedItems = getChangedItems();
  const currentChangedItemsFingerprint = JSON.stringify(currentChangedItems);
  const llmChannelDraftItemsFingerprint = JSON.stringify(llmChannelDraftItems);
  const generationBackendDraftItems = useMemo(
    () => mergeGenerationBackendDraftItems(currentChangedItems, llmChannelDraftItems),
    // Fingerprints keep the status panel from refreshing when parent renders do not change draft content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [currentChangedItemsFingerprint, llmChannelDraftItemsFingerprint],
  );
  const agentBackendDraftItems = useMemo(
    () => {
      const merged = new Map(
        generationBackendDraftItems.map((item) => [item.key.trim().toUpperCase(), item]),
      );
      for (const item of currentChangedItems) {
        const key = item.key.trim().toUpperCase();
        if (AGENT_BACKEND_STATUS_KEYS.has(key)) {
          merged.set(key, item);
        }
      }
      return Array.from(merged.values());
    },
    // The fingerprint changes only when the draft content changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [currentChangedItemsFingerprint, generationBackendDraftItems],
  );
  const handleLlmChannelDraftItemsChange = useCallback((items: Array<{ key: string; value: string }>) => {
    setLlmChannelDraftItems(items);
  }, []);

  const refreshSetupStatus = useCallback(async () => {
    const requestId = setupStatusRequestIdRef.current + 1;
    setupStatusRequestIdRef.current = requestId;
    setSetupStatusError(null);
    setIsRefreshingSetupStatus(true);
    try {
      const status = await systemConfigApi.getSetupStatus();
      if (setupStatusRequestIdRef.current !== requestId) {
        return;
      }
      setSetupStatus(status);
    } catch (error: unknown) {
      if (setupStatusRequestIdRef.current !== requestId) {
        return;
      }
      setSetupStatusError(getParsedApiError(error));
    } finally {
      if (setupStatusRequestIdRef.current === requestId) {
        setIsRefreshingSetupStatus(false);
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const requestedCategory = new URLSearchParams(window.location.search).get('category');
    if (requestedCategory && categories.some((category) => category.category === requestedCategory)) {
      setActiveCategory(requestedCategory);
    }
  }, [categories, setActiveCategory]);

  useEffect(() => {
    void refreshSetupStatus();
  }, [refreshSetupStatus]);

  useEffect(() => {
    if (!toast) {
      return;
    }

    const timer = window.setTimeout(() => {
      clearToast();
    }, 3200);

    return () => {
      window.clearTimeout(timer);
    };
  }, [clearToast, toast]);

  useEffect(() => {
    if (!canCheckDesktopUpdate) {
      setDesktopUpdateState(null);
      setIsCheckingDesktopUpdate(false);
      return;
    }

    let active = true;

    const syncDesktopUpdateState = async () => {
      try {
        const state = await desktopRuntimeApi?.getUpdateState?.();
        if (active) {
          setDesktopUpdateState(normalizeDesktopUpdateState(state));
        }
      } catch (error: unknown) {
        if (!active) {
          return;
        }
        setDesktopUpdateState({
          status: 'error',
          message: error instanceof Error ? error.message : t('settings.desktopUpdateErrorMessage'),
        });
      }
    };

    void syncDesktopUpdateState();

    const unsubscribe = desktopRuntimeApi?.onUpdateStateChange?.((state) => {
      if (!active) {
        return;
      }
      setDesktopUpdateState(normalizeDesktopUpdateState(state));
      setIsCheckingDesktopUpdate(false);
    });

    return () => {
      active = false;
      if (typeof unsubscribe === 'function') {
        unsubscribe();
      }
    };
  }, [canCheckDesktopUpdate, desktopRuntimeApi, t]);

  const rawActiveItems = itemsByCategory[activeCategory] || [];
  const rawActiveItemMap = new Map(rawActiveItems.map((item) => [item.key, String(item.value ?? '')]));
  const firstSetupStockCode = parseSetupStockList(getConfigItem(itemsByCategory.base || [], 'STOCK_LIST')?.value)[0] || '';
  const alphasiftItem = (itemsByCategory.data_source || []).find((item) => item.key === 'ALPHASIFT_ENABLED');
  const alphasiftEnabled = String(alphasiftItem?.value ?? '').trim().toLowerCase() === 'true';
  const shouldShowFirstRunSetup = activeCategory === 'base';
  const shouldShowAlphaSiftSettings = activeCategory === 'data_source' && Boolean(alphasiftItem);
  const hasConfiguredChannels = Boolean((rawActiveItemMap.get('LLM_CHANNELS') || '').trim());
  const hasLitellmConfig = Boolean((rawActiveItemMap.get('LITELLM_CONFIG') || '').trim());
  const hasRuntimeSchedulerMismatch =
    schedulerRuntimeEnabled !== null
    && schedulerOverrideFromUi !== null
    && schedulerOverrideFromUi !== schedulerRuntimeEnabled;
  const hasRuntimeSchedulerMismatchInDraft = hasRuntimeSchedulerMismatch
    && !currentChangedItems.some((item) => item.key === 'SCHEDULE_ENABLED');
  // LLM 渠道草稿单独计入页面级 dirty——useSystemConfig 的 dirtyCount/dirtyKeys 不感知
  // LLMChannelEditor 内部的 LLM_* / LITELLM_* 等渠道编辑键,因为这部分草稿由 LLMChannelEditor
  // 自管并通过 onDraftItemsChange 上报,不进入 useSystemConfig 的 draftValues。
  // channel 草稿数 = generationBackendDraftItems 中由 LLMChannelEditor 贡献的条目数,
  // 即不在 currentChangedItems(由 useSystemConfig 贡献)中的 channel 草稿条目。
  const currentChangedItemKeys = new Set(currentChangedItems.map((item) => item.key.trim().toUpperCase()));
  const llmChannelOnlyDraftCount = llmChannelDraftItems.filter(
    (item) => !currentChangedItemKeys.has(item.key.trim().toUpperCase()),
  ).length;
  const hasLlmChannelDraft = llmChannelOnlyDraftCount > 0;
  const effectiveHasDirty = hasDirty || hasRuntimeSchedulerMismatchInDraft || hasLlmChannelDraft;
  const effectiveDirtyCount = dirtyCount + (hasRuntimeSchedulerMismatchInDraft ? 1 : 0) + llmChannelOnlyDraftCount;

  // OR-COR-62780a0c: 全局按钮统一的"保存/写入进行中"信号。isSaving 只反映
  // useSystemConfig 普通草稿段,channelSaveInProgress 反映 LLM 渠道段。任何一段在
  // 写入时都不允许再次触发保存、放弃修改或路由离开,以避免并发写与状态反转。envBackup
  // 等子卡片独立操作不依赖此 flag,沿用各自 isLoading。
  const pageSaveInFlight = isSaving || channelSaveInProgress;

  // 离开拦截 — 走 useUnsavedChangesGuard (react-router useBlocker + beforeunload)。
  // 仅在 effectiveHasDirty=true 时生效;保存/重置把 effectiveHasDirty 变 false 后,
  // useUnsavedChangesGuard 内的 useEffect 会自动 reset blocker (见 hook 实现注释)。
  // blocker.state === 'blocked' 时下面 render 一段 confirm UI (页面 inner 区域里)。
  //
  // OR-COR-62780a0c: 普通 settings 段保存成功后(channel 段仍在途)虽然 dirty 仍可能
  // 暂为 true 但即将转 false, 真正关键是 channelSaveInProgress=true 时不能允许刷新
  // 或路由离开打断在途 systemConfigApi.update, 否则会留下"普通设置已落库、channel 段
  // 在客户端被中断、服务端可能也已被写入"的不一致状态。这里把 channelSaveInProgress
  // 并入 hasDirty 判定,保证保存进行中拦截离开。
  const { blocker: unsavedChangesBlocker } = useUnsavedChangesGuard({
    hasDirty: effectiveHasDirty || channelSaveInProgress,
  });

  // issue #1948 — 分类角标 dirty 计数。SettingsCategoryNav 不自己推导,只消费页面层
  // 汇总后的 Record<category, count>,避免 nav/底栏/保存条三处状态不同步。
  // 三处来源: useSystemConfig 的 currentChangedItems / LLMChannelEditor 的渠道草稿 /
  // runtime scheduler mismatch (计入 system 分类)。
  // currentChangedItems 与 llmChannelDraftItems 都只有 {key, value}, 没有 category 字段,
  // 因此用 useSystemConfig.keyToCategory 反查 (未注册 key 落 'uncategorized')。
  const dirtyCountByCategory = useMemo<Record<string, number>>(() => {
    const next: Record<string, number> = {};
    for (const item of currentChangedItems) {
      const category = keyToCategory[item.key] ?? 'uncategorized';
      next[category] = (next[category] || 0) + 1;
    }
    // LLMChannelEditor 草稿条目不进 useSystemConfig.currentChangedItems, 由 keyToCategory 反查。
    for (const item of llmChannelDraftItems) {
      const category = keyToCategory[item.key] ?? 'uncategorized';
      next[category] = (next[category] || 0) + 1;
    }
    if (hasRuntimeSchedulerMismatchInDraft) {
      next['system'] = (next['system'] || 0) + 1;
    }
    return next;
  }, [currentChangedItemsFingerprint, llmChannelDraftItemsFingerprint, hasRuntimeSchedulerMismatchInDraft, keyToCategory]);

  const handleSchedulerRuntimeStateChange = useCallback(({ runtimeEnabled, overrideEnabled }: {
    runtimeEnabled: boolean | null;
    overrideEnabled: boolean | null;
  }) => {
    setSchedulerRuntimeEnabled(runtimeEnabled);
    setSchedulerOverrideFromUi(overrideEnabled);
  }, []);

  // UI rendering rule only: hide channel-managed and legacy provider-specific
  // LLM keys from generic fields when channel mode is active. This does not
  // alter save/refresh payloads or config migration/rollback behavior.
  const LLM_CHANNEL_KEY_RE = /^LLM_[A-Z0-9_]+_(PROTOCOL|BASE_URL|API_KEY|API_KEYS|MODELS|EXTRA_HEADERS|ENABLED)$/;
  const AI_MODEL_HIDDEN_KEYS = new Set([
    'LLM_CHANNELS',
    'LLM_TEMPERATURE',
    'LITELLM_MODEL',
    'AGENT_LITELLM_MODEL',
    'LITELLM_FALLBACK_MODELS',
    'AIHUBMIX_KEY',
    'DEEPSEEK_API_KEY',
    'DEEPSEEK_API_KEYS',
    'GEMINI_API_KEY',
    'GEMINI_API_KEYS',
    'GEMINI_MODEL',
    'GEMINI_MODEL_FALLBACK',
    'GEMINI_TEMPERATURE',
    'ANTHROPIC_API_KEY',
    'ANTHROPIC_API_KEYS',
    'ANTHROPIC_MODEL',
    'ANTHROPIC_TEMPERATURE',
    'ANTHROPIC_MAX_TOKENS',
    'OPENAI_API_KEY',
    'OPENAI_API_KEYS',
    'OPENAI_BASE_URL',
    'OPENAI_MODEL',
    'OPENAI_VISION_MODEL',
    'OPENAI_TEMPERATURE',
    'VISION_MODEL',
  ]);
  const SYSTEM_HIDDEN_KEYS = new Set([
    'ADMIN_AUTH_ENABLED',
    ...SCHEDULER_SETTING_KEYS,
  ]);
  const DATA_SOURCE_HIDDEN_KEYS = new Set([
    'ALPHASIFT_ENABLED',
  ]);
  const AGENT_HIDDEN_KEYS = new Set(['AGENT_GENERATION_BACKEND']);
  const activeItems =
    activeCategory === 'ai_model'
      ? rawActiveItems.filter((item) => {
        if (hasConfiguredChannels && LLM_CHANNEL_KEY_RE.test(item.key)) {
          return false;
        }
        if (hasConfiguredChannels && !hasLitellmConfig && AI_MODEL_HIDDEN_KEYS.has(item.key)) {
          return false;
        }
        return true;
      })
      : activeCategory === 'system'
        ? rawActiveItems.filter((item) => !SYSTEM_HIDDEN_KEYS.has(item.key))
      : activeCategory === 'data_source'
        ? rawActiveItems.filter((item) => !DATA_SOURCE_HIDDEN_KEYS.has(item.key))
      : activeCategory === 'agent'
        ? rawActiveItems.filter((item) => !AGENT_HIDDEN_KEYS.has(item.key))
      : rawActiveItems;
  const promptCacheAdvancedItems = activeCategory === 'ai_model'
    ? activeItems.filter(isPromptCacheAdvancedSetting)
    : [];
  const visibleActiveItems = activeCategory === 'ai_model'
    ? activeItems.filter((item) => !isPromptCacheAdvancedSetting(item))
    : activeItems;
  const hasActiveConfigItems = visibleActiveItems.length > 0 || promptCacheAdvancedItems.length > 0;
  const isEnvBackupAllowed = isDesktopRuntime || authEnabled;
  const envBackupActionDisabled = isLoading || isSaving || isExportingEnv || isImportingEnv || !isEnvBackupAllowed;

  const downloadEnvBackup = async () => {
    setEnvBackupActionError(null);
    setEnvBackupActionSuccess('');
    setIsExportingEnv(true);
    try {
      const payload = await systemConfigApi.exportEnv();
      const blob = new Blob([payload.content], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = formatEnvBackupFilename(isDesktopRuntime);
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
      setEnvBackupActionSuccess(t('settings.envExported'));
    } catch (error: unknown) {
      setEnvBackupActionError(getParsedApiError(error));
    } finally {
      setIsExportingEnv(false);
    }
  };

  const beginEnvBackupImport = () => {
    setEnvBackupActionError(null);
    setEnvBackupActionSuccess('');
    // OR-COR-7bcf2ab7: 必须用 effectiveHasDirty(包含 useSystemConfig 的 hasDirty +
    // LLM 渠道草稿 + scheduler mismatch),否则用户在 LLMChannelEditor 里改了 channel
    // 但 useSystemConfig.hasDirty=false 时,导入 .env 不会被提示要丢失草稿。
    if (effectiveHasDirty) {
      setShowImportConfirm(true);
      return;
    }
    envBackupImportRef.current?.click();
  };

  const handleEnvBackupImportFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    setShowImportConfirm(false);
    if (!file) {
      return;
    }

    setEnvBackupActionError(null);
    setEnvBackupActionSuccess('');
    setIsImportingEnv(true);
    try {
      const content = await file.text();
      const importResult = await systemConfigApi.importEnv({
        configVersion,
        content,
        reloadNow: true,
      });
      const reloaded = await load();
      if (!reloaded) {
        setEnvBackupActionError(createParsedApiError({
          title: t('settings.envImportedRefreshFailedTitle'),
          message: t('settings.envImportedRefreshFailedMessage'),
          rawMessage: t('settings.envImportedRefreshFailedRaw'),
          category: 'http_error',
        }));
        return;
      }
      if (importResult.updatedKeys.some((key) => SCHEDULER_SETTING_KEYS.has(key))) {
        setSchedulerStatusRefreshToken((current) => current + 1);
      }
      notifySystemConfigChanged();
      void refreshSetupStatus();
      setEnvBackupActionSuccess(t('settings.envImported'));
    } catch (error: unknown) {
      setEnvBackupActionError(getParsedApiError(error));
    } finally {
      setIsImportingEnv(false);
    }
  };

  const handleDesktopUpdateCheck = async () => {
    if (!desktopRuntimeApi?.checkForUpdates) {
      return;
    }

    setIsCheckingDesktopUpdate(true);
    setDesktopUpdateState((current) => ({
      ...(current || {}),
      status: 'checking',
      message: t('settings.desktopUpdateCheckingMessage'),
    }));

    try {
      const state = await desktopRuntimeApi.checkForUpdates();
      setDesktopUpdateState(normalizeDesktopUpdateState(state));
    } catch (error: unknown) {
      setDesktopUpdateState({
        status: 'error',
        message: error instanceof Error ? error.message : t('settings.desktopUpdateErrorMessage'),
      });
    } finally {
      setIsCheckingDesktopUpdate(false);
    }
  };

  const updateAlphaSiftEnabled = async (nextEnabled: boolean) => {
    setAlphaSiftActionError(null);
    setAlphaSiftActionSuccess('');
    setIsUpdatingAlphaSift(true);
    try {
      if (nextEnabled) {
        await alphasiftApi.enable();
        await refreshAfterExternalSave(['ALPHASIFT_ENABLED']);
        setAlphaSiftActionSuccess(t('settings.enabledAlphaSiftSuccess'));
        return;
      }

      await systemConfigApi.update({
        configVersion,
        maskToken,
        reloadNow: true,
        items: [{ key: 'ALPHASIFT_ENABLED', value: 'false' }],
      });
      notifyAlphaSiftConfigChanged();
      await refreshAfterExternalSave(['ALPHASIFT_ENABLED']);
      setAlphaSiftActionSuccess(t('settings.disabledAlphaSiftSuccess'));
    } catch (error: unknown) {
      setAlphaSiftActionError(getParsedApiError(error));
      await refreshAfterExternalSave(['ALPHASIFT_ENABLED']);
    } finally {
      setIsUpdatingAlphaSift(false);
    }
  };

  const handleSaveConfig = async () => {
    const changedItems = getChangedItems();
    const syncRuntimeSchedulerState =
      schedulerOverrideFromUi !== null
      && schedulerRuntimeEnabled !== null
      && schedulerOverrideFromUi !== schedulerRuntimeEnabled
      && !changedItems.some((item) => item.key === 'SCHEDULE_ENABLED');
    const schedulerSyncItem: SystemConfigUpdateItem[] = syncRuntimeSchedulerState
      ? [{ key: 'SCHEDULE_ENABLED', value: schedulerOverrideFromUi ? 'true' : 'false' }]
      : [];
    // LLM 渠道草稿走 LLMChannelEditor 内部独立提交路径:useSystemConfig 不感知 channel
    // 草稿 keys 的 dirty 计算(LLMChannelEditor 自管),所以这里只能调 editorRef.submit()
    // 让 LLMChannelEditor 内部完成 validation + systemConfigApi.update + onSaved。
    // 注意:必须等普通草稿 save 成功之后再触发 channel 提交——否则两次 systemConfigApi.update
    // 会因为 config_version 冲突 race condition 互踩。
    const changedItemsToSave = [...changedItems, ...schedulerSyncItem];
    const changedAlphaSiftItem = changedItems.find((item) => item.key === 'ALPHASIFT_ENABLED');
    const changedSchedulerSettings = changedItemsToSave.some((item) => SCHEDULER_SETTING_KEYS.has(item.key));
    // OR-COR-62780a0c: 联合保存路径用 silent:true 抑制 save() 内置 success toast——
    // LLMChannelEditor.submit() 仍在进行,若第二段失败,页面会同时留有第一段 success
    // toast 与第二段错误提示,与最终结果矛盾。两段都成功后由本函数统一调
    // showSuccessToast 发出页面级 success toast。error toast 仍由 save() 内部 catch
    // 块或下方 channel 段 catch 块设置,失败反馈不丢失。
    const result = await save(changedItemsToSave, { silent: true });
    if (!result.success) {
      return;
    }
    notifySystemConfigChanged();
    if (changedSchedulerSettings) {
      setSchedulerStatusRefreshToken((current) => current + 1);
    }
    void refreshSetupStatus();

    // 普通草稿已成功保存 → 触发 channel 草稿的独立提交。
    // llmChannelEditorRef.current 在 LLMChannelEditor 实际 mount 之前为 null
    // (例如 ai_model 分类还没渲染过——但我们已用 CSS hidden 让 LLMChannelEditor 永久 mount,
    // 所以稳定可视)。submit 内部会判断是否有 channel 草稿,无草稿时直接 return true 不发 API。
    //
    // OR-COR-d144d9cf: 传 configVersion override。save() 内部已通过 applyServerPayload
    // 走 setConfigVersionSync,latestConfigVersionRef.current 同步保存了刷新后的版本;
    // 但 React state 异步,LLMChannelEditor 收到的 configVersion prop 仍是旧值。submit 内部
    // handleSave 会用 opts.configVersionOverride ?? configVersion,这里传入 ref.current
    // 保证 channel 提交拿到新版本,避免 409 冲突。
    //
    // OR-COR-b1b25240: submit() 现统一以 throwOnError:true 调 handleSave,channel 段 API
    // 失败时 rethrow 抛到这里。我们捕获后:不清空 LLMChannelEditor 内 saveMessage(已由
    // handleSave catch 块写入 editor 区域显示具体错误)、把 channel 草稿重新写回
    // llmChannelDraftItems 触发页面级 dirty 复算(虽 LLMChannelEditor 内部 draftItems 仍
    // 存在,但 SettingsPage 的 hasLlmChannelDraft 依赖 llmChannelDraftItems state,而
    // onSaved 成功路径里我们已 setLlmChannelDraftItems([]); 失败时不应清,这里靠
    // 隐式回滚—— chipsetEditor 内部 draftItems state 仍保留,LLMChannelEditor 通过
    // onDraftItemsChange 重新触发 SettingsPage setLlmChannelDraftItems 的链路在失败时
    // 不会触发,因此需要显式把当前 channel 草稿写回让 dirty 仍可被感知)、设置页面级
    // toast 把整体保存判失败让用户立刻看到反馈。前段已落库的普通设置无法服务端回滚,
    // 这是当前二段式 API 写入契约的固有限制;reviewer 也认可这是结构性折中,关键是
    // UI 侧不能再假装整体保存成功。
    //
    // OR-COR-62780a0c: 进入 channel 段前 setChannelSaveInProgress(true),finally 里复位,
    // 配合 pageSaveInFlight 让顶部/底部全局"保存/放弃修改"按钮在 channel 段进行中保持
    // disabled,避免用户在此窗口期内重复点击保存或先放弃草稿再让在途 channel 写入落库
    // 造成状态反转。
    if (llmChannelEditorRef.current) {
      setChannelSaveInProgress(true);
      // OR-COR-b1b25240: 进入 channel 段前先清掉之前可能残留的 channelSaveError, 避免
      // 用户重试保存成功后旧错误提示仍显示。
      setChannelSaveError(null);
      try {
        await llmChannelEditorRef.current.submit({
          configVersion: latestConfigVersionRef.current,
        });
      } catch (channelSaveError) {
        // channel 提交报错:整体保存判失败。错误细节在 LLMChannelEditor 区域内部的
        // saveMessage 显示(由 handleSave catch 块写入 ai_model 分类区),SettingsPage 这里
        // 通过 channelSaveError state 在全局"保存/放弃修改"工具区附近单独渲染一段 inline
        // 错误提示,确保用户从其他分类切回时也能立即看到反馈并知道整体保存未完成。
        // 前段已落库的普通设置无法服务端回滚,这是当前二段式 API 写入契约的固有限制;
        // 走 finally 复位 channelSaveInProgress; return 让 handleSaveConfig 提前结束。
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('[SettingsPage] LLMChannelEditor.submit() failed during handleSaveConfig', channelSaveError);
        }
        const parsedChannelError = getParsedApiError(channelSaveError);
        setChannelSaveError(parsedChannelError);
        // OR-COR-62780a0c: 把整体保存失败反馈也写到全局 toast——silent:true 让 save()
        // 第一段 success toast 不出现,这里在第二段失败时统一发出 error toast,确保用户
        // 跨分类切回时也能从顶部全局反馈立即感知整体保存未完成。
        showErrorToast(parsedChannelError);
        return;
      } finally {
        setChannelSaveInProgress(false);
      }
    }

    // OR-COR-62780a0c: 两段都成功(或无 channel 草稿且第一段成功)后统一发出页面级
    // success toast。silent:true 跳过了 save() 内置 success toast,这里补回。
    showSuccessToast(t('settings.configSavedToast'));

    if (!changedAlphaSiftItem) {
      return;
    }

    setAlphaSiftActionError(null);
    setAlphaSiftActionSuccess('');
    try {
      const isAlphaSiftEnabled = changedAlphaSiftItem.value.trim().toLowerCase() === 'true';
      if (isAlphaSiftEnabled) {
        await alphasiftApi.enable();
        await refreshAfterExternalSave(['ALPHASIFT_ENABLED']);
        setAlphaSiftActionSuccess(t('settings.enabledAlphaSiftSuccess'));
        return;
      }

      notifyAlphaSiftConfigChanged();
      setAlphaSiftActionSuccess(t('settings.disabledAlphaSiftSuccess'));
    } catch (error: unknown) {
      setAlphaSiftActionError(getParsedApiError(error));
      await refreshAfterExternalSave(['ALPHASIFT_ENABLED']);
    }
  };

  const openDesktopReleasePage = async () => {
    if (!desktopRuntimeApi?.openReleasePage) {
      return;
    }

    await desktopRuntimeApi.openReleasePage(desktopUpdateState?.releaseUrl);
  };

  const installDesktopUpdate = async () => {
    if (!desktopRuntimeApi?.installDownloadedUpdate) {
      setDesktopUpdateState((current) => ({
        ...(current || {}),
        status: 'error',
        message: t('settings.desktopManualUnsupported'),
      }));
      return;
    }

    try {
      setDesktopUpdateState((current) => ({
        ...(current || {}),
        status: 'installing',
        message: t('settings.desktopUpdateInstallingMessage'),
      }));
      await desktopRuntimeApi.installDownloadedUpdate();
    } catch (error: unknown) {
      setDesktopUpdateState((current) => ({
        ...(current || {}),
        status: 'error',
        message: error instanceof Error ? error.message : t('settings.desktopManualUnsupported'),
      }));
    }
  };

  const handleRunSetupSmoke = async () => {
    setSetupSmokeError(null);
    setSetupSmokeSuccess('');

    if (!setupStatus?.readyForSmoke) {
      setSetupSmokeError(createParsedApiError({
        title: t('settings.setupGuideSmokeUnavailableTitle'),
        message: t('settings.setupGuideSmokeNotReady'),
        rawMessage: t('settings.setupGuideSmokeNotReady'),
        category: 'missing_params',
      }));
      return;
    }

    if (!firstSetupStockCode) {
      setSetupSmokeError(createParsedApiError({
        title: t('settings.setupGuideSmokeUnavailableTitle'),
        message: t('settings.setupGuideSmokeNeedsStock'),
        rawMessage: t('settings.setupGuideSmokeNeedsStock'),
        category: 'missing_params',
      }));
      return;
    }

    setIsRunningSetupSmoke(true);
    try {
      const result = await analysisApi.analyzeAsync({
        stockCode: firstSetupStockCode,
        reportType: 'brief',
        asyncMode: true,
        notify: false,
        originalQuery: firstSetupStockCode,
        selectionSource: 'manual',
      });
      const taskId = 'taskId' in result ? result.taskId : result.accepted?.[0]?.taskId;
      setSetupSmokeSuccess(
        taskId
          ? t('settings.setupGuideSmokeAcceptedWithTask', { stock: firstSetupStockCode, taskId })
          : t('settings.setupGuideSmokeAccepted', { stock: firstSetupStockCode }),
      );
      void refreshSetupStatus();
    } catch (error: unknown) {
      setSetupSmokeError(getParsedApiError(error));
    } finally {
      setIsRunningSetupSmoke(false);
    }
  };

  const desktopUpdateNotice = getDesktopUpdateNotice(desktopUpdateState, t);
  const shouldGuardActiveConfigPanel = activeCategory === 'notification' || activeCategory === 'agent';
  const activeConfigPanelErrorTitle = activeCategory === 'agent' ? t('settings.agentSettings') : t('settings.notificationSettings');
  const settingsPanelDiagnosticHint = isDesktopRuntime
    ? uiLanguage === 'en'
      ? <>Check and provide the desktop log <code>desktop.log</code>, plus the release version, Windows version, and trigger path.</>
      : <>请查看并提供桌面端日志 <code>desktop.log</code>，同时补充 release 版本、Windows 版本和触发入口。</>
    : t('settings.diagnosticHintWeb');
  const activeCategoryTitle = getCategoryTitle(activeCategory as SystemConfigCategory, t('settings.activePanelTitle'), uiLanguage);
  const activeCategoryDescription = getCategoryDescription(activeCategory as SystemConfigCategory, '', uiLanguage);
  const selectedAgentBackend = (rawActiveItemMap.get('AGENT_BACKEND') || 'auto').trim().toLowerCase();
  const selectedAgentArch = (rawActiveItemMap.get('AGENT_ARCH') || 'single').trim().toLowerCase();
  const hasCodexArchitectureConflict = selectedAgentBackend === 'codex_app_server' && selectedAgentArch !== 'single';
  const codexArchitectureIssue: ConfigValidationIssue = {
    key: 'AGENT_ARCH',
    code: 'unsupported_agent_arch',
    message: t('settings.agentBackendSingleOnly'),
    severity: 'error',
    expected: 'single',
    actual: selectedAgentArch,
  };
  const activeConfigPanel = hasActiveConfigItems ? (
    <SettingsSectionCard
      title={activeCategoryTitle}
      description={activeCategoryDescription || t('settings.activePanelDescription')}
    >
      {visibleActiveItems.length ? (
        <div className="divide-y divide-[var(--settings-border-soft)] overflow-hidden rounded-lg border border-[var(--settings-border)] bg-[var(--settings-surface)]">
          {visibleActiveItems.map((item) => {
            const fieldIssues = item.key === 'AGENT_ARCH' && hasCodexArchitectureConflict
              ? [...(issueByKey[item.key] || []), codexArchitectureIssue]
              : issueByKey[item.key] || [];
            return (
              <SettingsField
                key={item.key}
                item={item}
                value={item.value}
                disabled={isSaving}
                onChange={setDraftValue}
                issues={fieldIssues}
              />
            );
          })}
        </div>
      ) : null}
      {promptCacheAdvancedItems.length ? (
        <details className="group/prompt-cache overflow-hidden rounded-lg border border-[var(--settings-border)] bg-[var(--settings-surface)] transition-colors duration-200 hover:bg-[var(--settings-surface-hover)]">
          <summary className="flex cursor-pointer list-none items-start justify-between gap-3 px-4 py-4 [&::-webkit-details-marker]:hidden">
            <div className="min-w-0 space-y-1">
              <p className="text-sm font-semibold text-foreground">
                {t('settings.promptCacheAdvancedTitle')}
              </p>
              <p className="text-xs leading-5 text-muted-text">
                {t('settings.promptCacheAdvancedDescription')}
              </p>
            </div>
            <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-muted-text transition-transform group-open/prompt-cache:rotate-180" aria-hidden="true" />
          </summary>
          <div className="divide-y divide-[var(--settings-border-soft)] border-t border-[var(--settings-border-soft)]">
            {promptCacheAdvancedItems.map((item) => (
              <SettingsField
                key={item.key}
                item={item}
                value={item.value}
                disabled={isSaving}
                onChange={setDraftValue}
                issues={issueByKey[item.key] || []}
              />
            ))}
          </div>
        </details>
      ) : null}
    </SettingsSectionCard>
  ) : (
    <EmptyState
      title={t('settings.currentCategoryEmptyTitle')}
      description={t('settings.currentCategoryEmptyDescription')}
      className="settings-surface-panel settings-border-strong border-none bg-transparent shadow-none"
    />
  );

  return (
    <div className="settings-page min-h-full px-4 pb-6 pt-4 md:px-6">
      <div className="mb-4 rounded-lg border settings-border bg-card/90 px-4 py-4 shadow-soft-card backdrop-blur-sm">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">{t('settings.pageTitle')}</h1>
            <p className="max-w-3xl text-xs leading-5 text-muted-text sm:text-sm sm:leading-6">
              {t('settings.pageDescription')}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="settings-secondary"
              size="sm"
              className="px-2.5"
              onClick={() => {
                // 放弃修改时同步清空 LLM 渠道草稿——否则 useSystemConfig 已 reset
                // 但 llmChannelDraftItems 仍残留,顶部 dirty 数会出现"已放弃但仍提示未保存"漂移。
                //
                // OR-COR-3ad7163c: 仅调 setLlmChannelDraftItems([]) + resetDraft() 不够。
                // resetDraft 只重置 useSystemConfig 的 draftValues(LLMChannelEditor 不感知),
                // serverItems 不变 → LLMChannelEditor 收到的 items prop 用 mergedItems,
                // initialChannels 重算 fingerprint 与 saved 一致 → LLMChannelEditor 内部
                // useEffect 不触发 → 内部 channels state 仍保留用户改的草稿 →
                // draftItems 仍非空 → onDraftItemsChange 把草稿回传父层,造成"已放弃但
                // 仍提示未保存"漂移。先调 llmChannelEditorRef.current.reset() 强制把 LLM 渠道
                // editor 内部 state 回滚到 saved 快照,再清父层镜像,双保险。
                llmChannelEditorRef.current?.reset();
                setLlmChannelDraftItems([]);
                resetDraft();
              }}
              // OR-COR-62780a0c: 用 pageSaveInFlight(普通段 isSaving || channel 段
              // channelSaveInProgress)代替单一 isSaving,确保 LLM 渠道段进行中用户也不能
              // 点放弃修改——否则 channel 段写入库的草稿会被 reset 清空,造成状态反转。
              disabled={isLoading || pageSaveInFlight}
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              {t('settings.reset')}
            </Button>
            <Button
              type="button"
              variant="settings-primary"
              size="sm"
              className="px-2.5"
              onClick={() => void handleSaveConfig()}
              // OR-COR-62780a0c: 用 pageSaveInFlight(普通段 isSaving || channel 段
              // channelSaveInProgress)统一作为禁用门槛,避免 LLM 渠道段进行中用户重复
              // 点击保存配置触发二段式 race。isLoading 仍保留以兜底初次加载未完成时按钮
              // 不可点击(此时 pageSaveInFlight 仍为 false)。
              disabled={!effectiveHasDirty || pageSaveInFlight || isLoading}
              isLoading={pageSaveInFlight}
              loadingText={t('settings.saving')}
            >
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              {isSaving
                ? t('settings.saving')
                : effectiveDirtyCount
                  ? t('settings.saveConfigWithCount', { count: effectiveDirtyCount })
                  : t('settings.saveConfig')}
            </Button>
          </div>
        </div>

        {saveError ? (
          <ApiErrorAlert
            className="mt-3"
            error={saveError}
            actionLabel={retryAction === 'save' ? t('settings.saveRetry') : undefined}
            onAction={retryAction === 'save' ? () => void retry() : undefined}
          />
        ) : null}
      </div>

      {loadError ? (
        <ApiErrorAlert
          error={loadError}
          actionLabel={retryAction === 'load' ? t('common.retry') : t('settings.reload')}
          onAction={() => void retry()}
          className="mb-4"
        />
      ) : null}

      {isLoading ? (
        <SettingsLoading />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
          <aside className="lg:sticky lg:top-4 lg:self-start">
            <SettingsCategoryNav
              categories={categories}
              itemsByCategory={itemsByCategory}
              activeCategory={activeCategory}
              onSelect={setActiveCategory}
              dirtyCountByCategory={dirtyCountByCategory}
            />
          </aside>

          <section className="space-y-4">
            {shouldShowFirstRunSetup ? (
              <FirstRunSetupCard
                status={setupStatus}
                isLoading={isRefreshingSetupStatus}
                error={setupStatusError}
                firstStockCode={firstSetupStockCode}
                isSaving={isSaving}
                isRunningSmoke={isRunningSetupSmoke}
                smokeError={setupSmokeError}
                smokeSuccess={setupSmokeSuccess}
                onRefresh={refreshSetupStatus}
                onSelectCategory={setActiveCategory}
                onRunSmoke={handleRunSetupSmoke}
                listSeparator={uiLanguage === 'en' ? ', ' : '、'}
                t={t}
              />
            ) : null}
            {shouldShowAlphaSiftSettings ? (
              <SettingsSectionCard
                title={t('settings.alphaSift')}
                description={t('settings.alphaSiftDescription')}
              >
                <div className="flex flex-col gap-4 rounded-2xl border settings-border bg-background/35 px-4 py-4 md:flex-row md:items-center md:justify-between">
                  <div>
                    <p className="text-sm font-semibold text-foreground">
                      {alphasiftEnabled ? t('settings.alphaSiftEnabled') : t('settings.alphaSiftDisabled')}
                    </p>
                    <p className="mt-1 text-xs leading-6 text-muted-text">
                      {t('settings.alphaSiftSummary')}
                    </p>
                    <p className="mt-2 text-xs leading-6 text-amber-700 dark:text-amber-300">
                      {t('settings.alphaSiftRisk')}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="button"
                      variant="settings-secondary"
                      onClick={() => setActiveCategory('data_source')}
                    >
                      {t('settings.viewConfigItems')}
                    </Button>
                    <Button
                      type="button"
                      variant={alphasiftEnabled ? 'settings-secondary' : 'settings-primary'}
                      onClick={() => void updateAlphaSiftEnabled(!alphasiftEnabled)}
                      disabled={isSaving || isLoading || isUpdatingAlphaSift}
                      isLoading={isUpdatingAlphaSift}
                      loadingText={alphasiftEnabled ? t('settings.disablingAlphaSift') : t('settings.enablingAlphaSift')}
                    >
                      {alphasiftEnabled ? t('settings.disableAlphaSift') : t('settings.enableAlphaSift')}
                    </Button>
                  </div>
                </div>
                {alphaSiftActionError ? (
                  <div className="mt-3">
                    <ApiErrorAlert error={alphaSiftActionError} />
                  </div>
                ) : null}
                {!alphaSiftActionError && alphaSiftActionSuccess ? (
                  <div className="mt-3">
                    <SettingsAlert title={t('settings.actionSuccess')} message={alphaSiftActionSuccess} variant="success" />
                  </div>
                ) : null}
              </SettingsSectionCard>
            ) : null}
            {activeCategory === 'system' ? <AuthSettingsCard /> : null}
            {activeCategory === 'system' ? (
              <SchedulerSettingsCard
                items={rawActiveItems}
                disabled={isSaving || isLoading}
                issueByKey={issueByKey}
                statusRefreshToken={schedulerStatusRefreshToken}
                onSchedulerStateChange={handleSchedulerRuntimeStateChange}
                onChange={setDraftValue}
                t={t}
                language={uiLanguage}
              />
            ) : null}
            {activeCategory === 'system' ? (
              <SettingsSectionCard
                title={t('settings.versionInfo')}
                description={t('settings.versionInfoDescription')}
              >
                <div
                  className={`grid grid-cols-1 gap-3 ${shouldShowDesktopVersionCard ? 'md:grid-cols-4' : 'md:grid-cols-3'}`}
                >
                  <div className="rounded-2xl border settings-border bg-background/40 px-4 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-text">
                      {t('settings.versionWebui')}
                    </p>
                    <p className="mt-2 break-all font-mono text-sm text-foreground">
                      {WEB_BUILD_INFO.version}
                    </p>
                  </div>
                  <div className="rounded-2xl border settings-border bg-background/40 px-4 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-text">
                      {t('settings.versionRevision')}
                    </p>
                    <p className="mt-2 break-all font-mono text-sm text-foreground">
                      {WEB_BUILD_INFO.revision}
                    </p>
                  </div>
                  <div className="rounded-2xl border settings-border bg-background/40 px-4 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-text">
                      {t('settings.versionBuildTime')}
                    </p>
                    <p className="mt-2 break-all font-mono text-sm text-foreground">
                      {WEB_BUILD_INFO.buildTime}
                    </p>
                  </div>
                  {shouldShowDesktopVersionCard ? (
                    <div className="rounded-2xl border settings-border bg-background/40 px-4 py-3">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-text">
                        {t('settings.versionDesktop')}
                      </p>
                      <p className="mt-2 break-all font-mono text-sm text-foreground">
                        {desktopAppVersion}
                      </p>
                    </div>
                  ) : null}
                </div>
                <p className="text-xs leading-6 text-muted-text">
                  {t('settings.updateBuildDescription')}
                </p>
                {canCheckDesktopUpdate ? (
                  <div className="mt-4 space-y-3 rounded-2xl border settings-border bg-background/30 px-4 py-4">
                    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                      <div>
                        <p className="text-sm font-medium text-foreground">{t('settings.desktopUpdate')}</p>
                        <p className="text-xs leading-6 text-muted-text">
                          {t('settings.desktopUpdateDescription')}
                        </p>
                      </div>
                      <Button
                        type="button"
                        variant="settings-secondary"
                        onClick={() => void handleDesktopUpdateCheck()}
                        disabled={isCheckingDesktopUpdate}
                        isLoading={isCheckingDesktopUpdate}
                        loadingText={t('settings.checkingDesktopUpdate')}
                      >
                        {t('settings.checkDesktopUpdate')}
                      </Button>
                    </div>
                    {desktopUpdateNotice ? (
                      <SettingsAlert
                        title={desktopUpdateNotice.title}
                        message={desktopUpdateNotice.message}
                        variant={desktopUpdateNotice.variant}
                        actionLabel={desktopUpdateNotice.actionLabel}
                        onAction={desktopUpdateNotice.actionLabel ? () => {
                          if (desktopUpdateNotice.actionKind === 'install') {
                            void installDesktopUpdate();
                            return;
                          }
                          void openDesktopReleasePage();
                        } : undefined}
                      />
                    ) : (
                      <p className="text-xs leading-6 text-muted-text">
                        {t('settings.desktopCurrentNoStatus')}
                      </p>
                    )}
                  </div>
                ) : null}
                {WEB_BUILD_INFO.isFallbackVersion ? (
                  <p className="text-xs leading-6 text-amber-700 dark:text-amber-300">
                    {t('settings.fallbackVersionWarning')}
                  </p>
                ) : null}
              </SettingsSectionCard>
            ) : null}
            {activeCategory === 'system' ? (
              <SettingsSectionCard
                title={t('settings.configBackup')}
                description={t('settings.configBackupDescription')}
              >
                <div className="space-y-4">
                  {!isEnvBackupAllowed ? (
                    <p className="text-xs leading-6 text-amber-700 dark:text-amber-300">
                      {t('settings.disabledAuthBackupWarning')}
                    </p>
                  ) : null}
                  <div className="flex flex-wrap items-center gap-3">
                    <Button
                      type="button"
                      variant="settings-secondary"
                      onClick={() => void downloadEnvBackup()}
                      disabled={envBackupActionDisabled}
                      isLoading={isExportingEnv}
                      loadingText={t('settings.exportingEnv')}
                    >
                      {t('settings.exportEnv')}
                    </Button>
                    <Button
                      type="button"
                      variant="settings-primary"
                      onClick={beginEnvBackupImport}
                      disabled={envBackupActionDisabled}
                      isLoading={isImportingEnv}
                      loadingText={t('settings.importingEnv')}
                    >
                      {t('settings.importEnv')}
                    </Button>
                    <input
                      ref={envBackupImportRef}
                      type="file"
                      accept=".env,.txt"
                      className="hidden"
                      onChange={(event) => {
                        void handleEnvBackupImportFile(event);
                      }}
                    />
                  </div>
                  <p className="text-xs leading-6 text-muted-text">
                    {t('settings.envExportNote')}
                  </p>
                  <p className="text-xs leading-6 text-muted-text">
                    {t('settings.envDockerNote')}
                  </p>
                  {envBackupActionError ? (
                    <ApiErrorAlert
                      error={envBackupActionError}
                      actionLabel={envBackupActionError.status === 409 ? t('settings.reload') : undefined}
                      onAction={envBackupActionError.status === 409 ? () => void load() : undefined}
                    />
                  ) : null}
                  {!envBackupActionError && envBackupActionSuccess ? (
                    <SettingsAlert title={t('settings.actionSuccess')} message={envBackupActionSuccess} variant="success" />
                  ) : null}
                </div>
              </SettingsSectionCard>
            ) : null}
            {activeCategory === 'base' ? (
              <SettingsSectionCard
                title={t('settings.intelligentImport')}
                description={t('settings.intelligentImportDescription')}
              >
                <IntelligentImport
                  stockListValue={
                    (activeItems.find((i) => i.key === 'STOCK_LIST')?.value as string) ?? ''
                  }
                  configVersion={configVersion}
                  maskToken={maskToken}
                  onMerged={async () => {
                    await refreshAfterExternalSave(['STOCK_LIST']);
                    void refreshSetupStatus();
                  }}
                  disabled={isSaving || isLoading}
                />
              </SettingsSectionCard>
            ) : null}
            {/*
              ai_model 分类下的 LLMChannelEditor 始终保持 mounted——切到其他分类时通过 CSS
              `hidden` 控制可见性而非 conditional render,以避免组件 unmount 抹掉内部 channels
              state(用户编辑过的渠道草稿)。LLMChannelEditor 的 items prop 始终绑定
              itemsByCategory.ai_model 而非 rawActiveItems(itemsByCategory[activeCategory]),
              因为切到 base 分类时 rawActiveItems 会变成 base 分类的 items,触发 LLMChannelEditor
              内部 initialChannels 重算并通过 reset effect 把 channels 重置回 server 状态。
              GenerationBackendStatusPanel 也跟着用 ai_model 分类 items,保持依赖一致。
            */}
            <div className={activeCategory === 'ai_model' ? '' : 'hidden'}>
              <SettingsSectionCard
                title={t('settings.llmAccess')}
                description={t('settings.llmAccessDescription')}
              >
                <GenerationBackendStatusPanel
                  items={activeCategory === 'ai_model' ? generationBackendDraftItems : (itemsByCategory.ai_model || [])}
                  maskToken={maskToken}
                  disabled={isSaving || isLoading}
                />
                <LLMChannelEditor
                  ref={llmChannelEditorRef}
                  items={itemsByCategory.ai_model || []}
                  configVersion={configVersion}
                  maskToken={maskToken}
                  onDraftItemsChange={handleLlmChannelDraftItemsChange}
                  onSaved={async (updatedItems) => {
                    setLlmChannelDraftItems([]);
                    await refreshAfterExternalSave(updatedItems.map((item) => item.key));
                    void refreshSetupStatus();
                  }}
                  disabled={isSaving || isLoading}
                />
              </SettingsSectionCard>
            </div>
            {activeCategory === 'system' && passwordChangeable ? (
              <ChangePasswordCard />
            ) : null}
            {activeCategory === 'notification' ? (
              <SettingsPanelErrorBoundary
                title={t('settings.notificationTest')}
                resetKey={`notification-test:${configVersion}`}
                diagnosticHint={settingsPanelDiagnosticHint}
              >
                <NotificationTestPanel
                  items={rawActiveItems.map((item) => ({ key: item.key, value: String(item.value ?? '') }))}
                  maskToken={maskToken}
                  disabled={isSaving || isLoading}
                />
              </SettingsPanelErrorBoundary>
            ) : null}
            {activeCategory === 'agent' ? (
              <SettingsPanelErrorBoundary
                title={t('settings.agentBackendStatus')}
                resetKey={`agent-backend:${configVersion}`}
                diagnosticHint={settingsPanelDiagnosticHint}
              >
                <SettingsSectionCard
                  title={t('settings.agentBackendSectionTitle')}
                  description={t('settings.agentBackendSectionDescription')}
                >
                  <AgentBackendStatusPanel
                    items={agentBackendDraftItems}
                    maskToken={maskToken}
                    selectedBackend={selectedAgentBackend}
                    agentArch={selectedAgentArch}
                    disabled={isSaving || isLoading}
                    onUseSingleAgent={() => setDraftValue('AGENT_ARCH', 'single')}
                    onEnableAgentMode={() => setDraftValue('AGENT_MODE', 'true')}
                  />
                </SettingsSectionCard>
              </SettingsPanelErrorBoundary>
            ) : null}
            {shouldGuardActiveConfigPanel && hasActiveConfigItems ? (
              <SettingsPanelErrorBoundary
                title={activeConfigPanelErrorTitle}
                resetKey={`${activeCategory}:${configVersion}`}
                diagnosticHint={settingsPanelDiagnosticHint}
              >
                {activeConfigPanel}
              </SettingsPanelErrorBoundary>
            ) : activeConfigPanel}
          </section>
        </div>
      )}

      {toast ? (
        <div className="fixed bottom-5 right-5 z-50 w-[320px] max-w-[calc(100vw-24px)]">
          {toast.type === 'success'
            ? (
                <SettingsAlert
                  title={t('settings.actionSuccess')}
                  message={toast.message}
                  variant="success"
                  presentation="toast"
                />
              )
            : <ApiErrorAlert error={toast.error} />}
        </div>
      ) : null}
      {effectiveHasDirty ? (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-4 left-1/2 z-40 -translate-x-1/2 rounded-lg border settings-border bg-card/95 px-4 py-3 shadow-soft-card backdrop-blur-sm sm:left-auto sm:right-5 sm:translate-x-0"
          data-testid="settings-unsaved-bar"
        >
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <CircleDashed className="h-4 w-4 text-amber-500" aria-hidden="true" />
            <span className="text-foreground">
              {t('settings.unsavedBarBody', { count: effectiveDirtyCount })}
            </span>
            <Button
              type="button"
              variant="settings-secondary"
              size="sm"
              className="px-2.5"
              onClick={() => {
                // 放弃修改时同步清空 LLM 渠道草稿——否则 useSystemConfig 已 reset
                // 但 llmChannelDraftItems 仍残留,底部 sticky bar 仍显示 dirty 数。
                //
                // OR-COR-3ad7163c: 见上方相同按钮注释——必须先调 reset() 强制把
                // LLMChannelEditor 内部 channels/runtime state 回滚到 saved 快照,
                // 否则 useEffect 不触发,channels state 仍保留用户改的草稿,draftItems
                // 通过 onDraftItemsChange 回传父层,造成"已放弃但仍提示未保存"漂移。
                //
                // OR-COR-b1b25240: 同时清掉 channelSaveError, 让放弃修改后旧的
                // channel 段失败提示消失,避免误以为仍需重试保存。
                llmChannelEditorRef.current?.reset();
                setLlmChannelDraftItems([]);
                setChannelSaveError(null);
                resetDraft();
              }}
              disabled={pageSaveInFlight}
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              {t('settings.unsavedBarDiscard')}
            </Button>
            <Button
              type="button"
              variant="settings-primary"
              size="sm"
              className="px-2.5"
              onClick={() => void handleSaveConfig()}
              disabled={pageSaveInFlight}
              isLoading={pageSaveInFlight}
              loadingText={t('settings.saving')}
            >
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              {pageSaveInFlight ? t('settings.saving') : t('settings.unsavedBarSave')}
            </Button>
          </div>
          {channelSaveError ? (
            // OR-COR-b1b25240: channel 段 API 失败时 inline 提示。ApiErrorAlert 直接复用
            // 既有渲染组件,与 saveError/loadError 视觉一致。固定底部 sticky bar 内顶部,
            // 离按钮近,用户立即可见。channel 成功保存/重置草稿/放弃修改时被清空。
            <div
              data-testid="settings-channel-save-error"
              className="mt-3 border-t settings-border pt-3"
            >
              <ApiErrorAlert error={channelSaveError} />
            </div>
          ) : null}
        </div>
      ) : null}
      <ConfirmDialog
        isOpen={unsavedChangesBlocker.state === 'blocked'}
        title={t('settings.unsavedLeaveTitle')}
        message={t('settings.unsavedLeaveMessage', { count: effectiveDirtyCount })}
        confirmText={t('settings.unsavedLeaveConfirm')}
        cancelText={t('settings.unsavedLeaveCancel')}
        onConfirm={() => {
          // 用户确认离开 → react-router proceed() 让 navigation 继续。
          if (unsavedChangesBlocker.state === 'blocked') {
            unsavedChangesBlocker.proceed();
          }
        }}
        onCancel={() => {
          // 用户选择留在此页 → reset() 让 blocker 退回 'unblocked' 状态。
          if (unsavedChangesBlocker.state === 'blocked') {
            unsavedChangesBlocker.reset();
          }
        }}
      />
      <ConfirmDialog
        isOpen={showImportConfirm}
        title={t('settings.importConfirmTitle')}
        message={t('settings.importConfirmMessage')}
        confirmText={t('settings.importConfirmContinue')}
        cancelText={t('common.cancel')}
        onConfirm={() => {
          setShowImportConfirm(false);
          envBackupImportRef.current?.click();
        }}
        onCancel={() => {
          setShowImportConfirm(false);
        }}
      />
    </div>
  );
};

export default SettingsPage;
