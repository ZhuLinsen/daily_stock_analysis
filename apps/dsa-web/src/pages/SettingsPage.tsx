import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { useAuth, useSystemConfig } from '../hooks';
import { createParsedApiError, getParsedApiError, type ParsedApiError } from '../api/error';
import { systemConfigApi } from '../api/systemConfig';
import { ApiErrorAlert, Button, ConfirmDialog } from '../components/common';
import {
  AuthSettingsCard,
  ChangePasswordCard,
  IntelligentImport,
  LLMChannelEditor,
  SettingsCategoryNav,
  SettingsAlert,
  SettingsField,
  SettingsLoading,
  SettingsSectionCard,
} from '../components/settings';
import { getCategoryDescriptionZh } from '../utils/systemConfigI18n';
import type { SystemConfigCategory } from '../types/systemConfig';

type DesktopWindow = Window & {
  dsaDesktop?: {
    version?: string;
  };
};

function formatDesktopEnvFilename() {
  const now = new Date();
  const pad = (value: number) => value.toString().padStart(2, '0');
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `dsa-desktop-env_${date}_${time}.env`;
}

const SettingsPage: React.FC = () => {
  const { passwordChangeable } = useAuth();
  const [desktopActionError, setDesktopActionError] = useState<ParsedApiError | null>(null);
  const [desktopActionSuccess, setDesktopActionSuccess] = useState<string>('');
  const [isExportingEnv, setIsExportingEnv] = useState(false);
  const [isImportingEnv, setIsImportingEnv] = useState(false);
  const [showImportConfirm, setShowImportConfirm] = useState(false);
  const desktopImportRef = useRef<HTMLInputElement | null>(null);
  const isDesktopRuntime = typeof window !== 'undefined' && Boolean((window as DesktopWindow).dsaDesktop);

  // Set page title
  useEffect(() => {
    document.title = '系统设置 - DSA';
  }, []);

  const {
    categories,
    itemsByCategory,
    issueByKey,
    activeCategory,
    setActiveCategory,
    hasDirty,
    dirtyCount,
    toast,
    clearToast,
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
    refreshAfterExternalSave,
    configVersion,
    maskToken,
  } = useSystemConfig();

  useEffect(() => {
    void load();
  }, [load]);

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

  const rawActiveItems = itemsByCategory[activeCategory] || [];
  const rawActiveItemMap = new Map(rawActiveItems.map((item) => [item.key, String(item.value ?? '')]));
  const hasConfiguredChannels = Boolean((rawActiveItemMap.get('LLM_CHANNELS') || '').trim());
  const hasLitellmConfig = Boolean((rawActiveItemMap.get('LITELLM_CONFIG') || '').trim());

  // Hide channel-managed and legacy provider-specific LLM keys from the
  // generic form only when channel config is the active runtime source.
  const LLM_CHANNEL_KEY_RE = /^LLM_[A-Z0-9]+_(PROTOCOL|BASE_URL|API_KEY|API_KEYS|MODELS|EXTRA_HEADERS|ENABLED)$/;
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
  ]);
  const AGENT_HIDDEN_KEYS = new Set([
    'AGENT_DEEP_RESEARCH_BUDGET',
    'AGENT_DEEP_RESEARCH_TIMEOUT',
    'AGENT_EVENT_MONITOR_ENABLED',
    'AGENT_EVENT_MONITOR_INTERVAL_MINUTES',
    'AGENT_EVENT_ALERT_RULES_JSON',
  ]);
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
      : activeCategory === 'agent'
        ? rawActiveItems.filter((item) => !AGENT_HIDDEN_KEYS.has(item.key))
      : rawActiveItems;
  const desktopActionDisabled = isLoading || isSaving || isExportingEnv || isImportingEnv;

  const downloadDesktopEnv = async () => {
    setDesktopActionError(null);
    setDesktopActionSuccess('');
    setIsExportingEnv(true);
    try {
      const payload = await systemConfigApi.exportDesktopEnv();
      const blob = new Blob([payload.content], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = formatDesktopEnvFilename();
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
      setDesktopActionSuccess('已导出当前已保存的 .env 备份。');
    } catch (error: unknown) {
      setDesktopActionError(getParsedApiError(error));
    } finally {
      setIsExportingEnv(false);
    }
  };

  const beginDesktopImport = () => {
    setDesktopActionError(null);
    setDesktopActionSuccess('');
    if (hasDirty) {
      setShowImportConfirm(true);
      return;
    }
    desktopImportRef.current?.click();
  };

  const handleDesktopImportFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    setShowImportConfirm(false);
    if (!file) {
      return;
    }

    setDesktopActionError(null);
    setDesktopActionSuccess('');
    setIsImportingEnv(true);
    try {
      const content = await file.text();
      await systemConfigApi.importDesktopEnv({
        configVersion,
        content,
        reloadNow: true,
      });
      const reloaded = await load();
      if (!reloaded) {
        setDesktopActionError(createParsedApiError({
          title: '配置已导入但刷新失败',
          message: '备份已导入，但重新加载配置失败，请手动重载页面。',
          rawMessage: 'Desktop env import succeeded but config refresh failed',
          category: 'http_error',
        }));
        return;
      }
      setDesktopActionSuccess('已导入 .env 备份并重新加载配置。');
    } catch (error: unknown) {
      setDesktopActionError(getParsedApiError(error));
    } finally {
      setIsImportingEnv(false);
    }
  };

  return (
    <div className="min-h-full px-4 pb-6 pt-4 md:px-6">
      <div className="mb-5 rounded-xl bg-card/50 px-5 py-5 shadow-soft-card-strong">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-foreground">系统设置</h1>
            <p className="text-xs leading-6 text-muted-text">
              统一管理模型、数据源、通知、安全认证与导入能力。
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="settings-secondary"
              className="border-border/50 bg-muted/30 hover:border-border/70"
              onClick={resetDraft}
              disabled={isLoading || isSaving}
            >
              重置
            </Button>
            <Button
              type="button"
              variant="settings-primary"
              onClick={() => void save()}
              disabled={!hasDirty || isSaving || isLoading}
              isLoading={isSaving}
              loadingText="保存中..."
            >
              {isSaving ? '保存中...' : `保存配置${dirtyCount ? ` (${dirtyCount})` : ''}`}
            </Button>
          </div>
        </div>

        {saveError ? (
          <ApiErrorAlert
            className="mt-3"
            error={saveError}
            actionLabel={retryAction === 'save' ? '重试保存' : undefined}
            onAction={retryAction === 'save' ? () => void retry() : undefined}
          />
        ) : null}
      </div>

      {loadError ? (
        <ApiErrorAlert
          error={loadError}
          actionLabel={retryAction === 'load' ? '重试加载' : '重新加载'}
          onAction={() => void retry()}
          className="mb-4"
        />
      ) : null}

      {isLoading ? (
        <SettingsLoading />
      ) : (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[280px_1fr]">
          <aside className="lg:sticky lg:top-4 lg:self-start">
            <SettingsCategoryNav
              categories={categories}
              itemsByCategory={itemsByCategory}
              activeCategory={activeCategory}
              onSelect={setActiveCategory}
            />
          </aside>

          <section className="space-y-4">
            {activeCategory === 'system' ? <AuthSettingsCard /> : null}
            {activeCategory === 'system' && isDesktopRuntime ? (
              <SettingsSectionCard
                title="配置备份"
                description="导出当前已保存的 .env 备份，或从备份文件恢复桌面端配置。导入会覆盖备份中出现的键并立即重载。"
              >
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <Button
                      type="button"
                      variant="settings-secondary"
                      onClick={() => void downloadDesktopEnv()}
                      disabled={desktopActionDisabled}
                      isLoading={isExportingEnv}
                      loadingText="导出中..."
                    >
                      导出 .env
                    </Button>
                    <Button
                      type="button"
                      variant="settings-primary"
                      onClick={beginDesktopImport}
                      disabled={desktopActionDisabled}
                      isLoading={isImportingEnv}
                      loadingText="导入中..."
                    >
                      导入 .env
                    </Button>
                    <input
                      ref={desktopImportRef}
                      type="file"
                      accept=".env,.txt"
                      className="hidden"
                      onChange={(event) => {
                        void handleDesktopImportFile(event);
                      }}
                    />
                  </div>
                  <p className="text-xs leading-6 text-muted-text">
                    导出内容仅包含当前已保存配置，不包含页面上尚未保存的本地草稿。
                  </p>
                  {desktopActionError ? (
                    <ApiErrorAlert
                      error={desktopActionError}
                      actionLabel={desktopActionError.status === 409 ? '重新加载' : undefined}
                      onAction={desktopActionError.status === 409 ? () => void load() : undefined}
                    />
                  ) : null}
                  {!desktopActionError && desktopActionSuccess ? (
                    <SettingsAlert title="操作成功" message={desktopActionSuccess} variant="success" />
                  ) : null}
                </div>
              </SettingsSectionCard>
            ) : null}
            {activeCategory === 'base' ? (
              <SettingsSectionCard
                title="智能导入"
                description="从图片、文件或剪贴板中提取股票代码，并合并到自选股列表。"
              >
                <IntelligentImport
                  stockListValue={
                    (activeItems.find((i) => i.key === 'STOCK_LIST')?.value as string) ?? ''
                  }
                  configVersion={configVersion}
                  maskToken={maskToken}
                  onMerged={async () => {
                    await refreshAfterExternalSave(['STOCK_LIST']);
                  }}
                  disabled={isSaving || isLoading}
                />
              </SettingsSectionCard>
            ) : null}
            {activeCategory === 'ai_model' ? (
              <SettingsSectionCard
                title="LLM 渠道与模型"
                description="统一管理渠道协议、基础地址、API Key、主模型与回退模型。"
              >
                <LLMChannelEditor
                  items={rawActiveItems}
                  configVersion={configVersion}
                  maskToken={maskToken}
                  onSaved={async (updatedItems) => {
                    await refreshAfterExternalSave(updatedItems.map((item) => item.key));
                  }}
                  disabled={isSaving || isLoading}
                />
              </SettingsSectionCard>
            ) : null}
            {activeCategory === 'system' && passwordChangeable ? (
              <ChangePasswordCard />
            ) : null}
            {activeItems.length ? (
              <SettingsSectionCard
                title="当前分类配置项"
                description={getCategoryDescriptionZh(activeCategory as SystemConfigCategory, '') || '使用统一字段卡片维护当前分类的系统配置。'}
              >
                {activeItems.map((item) => (
                  <SettingsField
                    key={item.key}
                    item={item}
                    value={item.value}
                    disabled={isSaving}
                    onChange={setDraftValue}
                    issues={issueByKey[item.key] || []}
                  />
                ))}
              </SettingsSectionCard>
            ) : (
              <div className="settings-panel-muted rounded-[1.5rem] border p-5 text-sm text-secondary-text shadow-soft-card">
                当前分类下暂无配置项。
              </div>
            )}
          </section>
        </div>
      )}

      {toast ? (
        <div className="fixed bottom-5 right-5 z-50 w-[320px] max-w-[calc(100vw-24px)]">
          {toast.type === 'success'
            ? <SettingsAlert title="操作成功" message={toast.message} variant="success" />
            : <ApiErrorAlert error={toast.error} />}
        </div>
      ) : null}
      <ConfirmDialog
        isOpen={showImportConfirm}
        title="导入会覆盖当前草稿"
        message="当前页面还有未保存修改。继续导入会丢弃这些本地草稿，并立即用备份文件中的键值更新已保存配置。"
        confirmText="继续导入"
        cancelText="取消"
        onConfirm={() => {
          setShowImportConfirm(false);
          desktopImportRef.current?.click();
        }}
        onCancel={() => {
          setShowImportConfirm(false);
        }}
      />
    </div>
  );
};

export default SettingsPage;
