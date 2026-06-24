import type React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resolveWebBuildInfo } from '../../utils/constants';
import SettingsPage from '../SettingsPage';

const {
  exportEnv,
  getSchedulerStatus,
  importEnv,
  runSchedulerNow,
  updateSystemConfig,
  alphasiftEnable,
  alphasiftInstall,
  notifyAlphaSiftConfigChanged,
  notifySystemConfigChanged,
  desktopCheckForUpdates,
  desktopGetUpdateState,
  desktopInstallDownloadedUpdate,
  desktopOnUpdateStateChange,
  desktopOpenReleasePage,
  load,
  clearToast,
  setActiveCategory,
  save,
  resetDraft,
  setDraftValue,
  applyPartialUpdate,
  getChangedItems,
  refreshAfterExternalSave,
  refreshStatus,
  settingsPanelErrorBoundary,
  useAuthMock,
  useSystemConfigMock,
  webBuildInfoMock,
} = vi.hoisted(() => ({
  exportEnv: vi.fn(),
  getSchedulerStatus: vi.fn(),
  importEnv: vi.fn(),
  runSchedulerNow: vi.fn(),
  updateSystemConfig: vi.fn(),
  alphasiftEnable: vi.fn(),
  alphasiftInstall: vi.fn(),
  notifyAlphaSiftConfigChanged: vi.fn(),
  notifySystemConfigChanged: vi.fn(),
  desktopCheckForUpdates: vi.fn(),
  desktopGetUpdateState: vi.fn(),
  desktopInstallDownloadedUpdate: vi.fn(),
  desktopOnUpdateStateChange: vi.fn(),
  desktopOpenReleasePage: vi.fn(),
  load: vi.fn(),
  clearToast: vi.fn(),
  setActiveCategory: vi.fn(),
  save: vi.fn(),
  resetDraft: vi.fn(),
  setDraftValue: vi.fn(),
  applyPartialUpdate: vi.fn(),
  getChangedItems: vi.fn(),
  refreshAfterExternalSave: vi.fn(),
  refreshStatus: vi.fn(),
  settingsPanelErrorBoundary: vi.fn(),
  useAuthMock: vi.fn(),
  useSystemConfigMock: vi.fn(),
  webBuildInfoMock: {
    version: '3.11.0',
    rawVersion: '3.11.0',
    buildId: 'build-20260329-021530Z',
    buildTime: '2026-03-29T02:15:30.000Z',
    isFallbackVersion: false,
  },
}));

const mockedAnchorClick = vi.fn();

vi.mock('../../hooks', () => ({
  useAuth: () => useAuthMock(),
  useSystemConfig: () => useSystemConfigMock(),
}));

vi.mock('../../api/systemConfig', () => ({
  systemConfigApi: {
    exportEnv: (...args: unknown[]) => exportEnv(...args),
    getSchedulerStatus: (...args: unknown[]) => getSchedulerStatus(...args),
    importEnv: (...args: unknown[]) => importEnv(...args),
    runSchedulerNow: (...args: unknown[]) => runSchedulerNow(...args),
    update: (...args: unknown[]) => updateSystemConfig(...args),
  },
}));

vi.mock('../../api/alphasift', () => ({
  alphasiftApi: {
    enable: (...args: unknown[]) => alphasiftEnable(...args),
    install: (...args: unknown[]) => alphasiftInstall(...args),
  },
  notifyAlphaSiftConfigChanged: (...args: unknown[]) => notifyAlphaSiftConfigChanged(...args),
  notifySystemConfigChanged: (...args: unknown[]) => notifySystemConfigChanged(...args),
}));

vi.mock('../../utils/constants', async () => {
  const actual = await vi.importActual<typeof import('../../utils/constants')>('../../utils/constants');
  return {
    ...actual,
    WEB_BUILD_INFO: webBuildInfoMock,
  };
});

vi.mock('../../components/settings', () => ({
  AuthSettingsCard: () => <div>认证与登录保护</div>,
  ChangePasswordCard: () => <div>修改密码</div>,
  IntelligentImport: ({ onMerged }: { onMerged: (value: string) => void }) => (
    <button type="button" onClick={() => onMerged('SZ000001,SZ000002')}>
      merge stock list
    </button>
  ),
  LLMChannelEditor: ({
    items,
    onSaved,
  }: {
    items: Array<{ key: string; value: string }>;
    onSaved: (items: Array<{ key: string; value: string }>) => void;
  }) => (
    <div>
      <div data-testid="llm-channel-editor-items">{items.map((item) => item.key).join(',')}</div>
      <button
        type="button"
        onClick={() => onSaved([{ key: 'LLM_CHANNELS', value: 'primary,backup' }])}
      >
        save llm channels
      </button>
    </div>
  ),
  NotificationTestPanel: ({ items }: { items: Array<{ key: string; value: string }> }) => (
    <div>通知测试面板:{items.map((item) => item.key).join(',')}</div>
  ),
  SettingsAlert: ({
    title,
    message,
    actionLabel,
    onAction,
  }: {
    title: string;
    message: string;
    actionLabel?: string;
    onAction?: () => void;
  }) => (
    <div>
      {title}:{message}
      {actionLabel ? (
        <button type="button" onClick={onAction}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  ),
  SettingsCategoryNav: ({
    categories,
    activeCategory,
    onSelect,
  }: {
    categories: Array<{ category: string; title: string }>;
    activeCategory: string;
    onSelect: (value: string) => void;
  }) => (
    <nav>
      {categories.map((category) => (
        <button
          key={category.category}
          type="button"
          aria-pressed={activeCategory === category.category}
          onClick={() => onSelect(category.category)}
        >
          {category.title}
        </button>
      ))}
    </nav>
  ),
  SettingsField: ({
    item,
  }: {
    item: {
      key: string;
      schema?: {
        description?: string;
        options?: Array<string | { label: string; value: string }>;
      };
    };
  }) => (
    <div data-testid={`settings-field-${item.key}`}>
      <div>{item.key}</div>
      {item.schema?.description ? <p>{item.schema.description}</p> : null}
      {item.schema?.options?.map((option) => {
        const label = typeof option === 'string' ? option : option.label;
        const value = typeof option === 'string' ? option : option.value;
        return <span key={`${item.key}-${value}`}>{label}</span>;
      })}
    </div>
  ),
  SettingsLoading: () => <div>loading</div>,
  SettingsPanelErrorBoundary: ({
    title,
    diagnosticHint,
    children,
  }: {
    title: string;
    diagnosticHint?: React.ReactNode;
    children: React.ReactNode;
  }) => {
    settingsPanelErrorBoundary(title);
    return (
      <>
        {diagnosticHint ? <div>{diagnosticHint}</div> : null}
        {children}
      </>
    );
  },
  SettingsSectionCard: ({
    title,
    description,
    children,
  }: {
    title: string;
    description?: string;
    children: React.ReactNode;
  }) => (
    <section>
      <h2>{title}</h2>
      {description ? <p>{description}</p> : null}
      {children}
    </section>
  ),
}));

function createDesktopRuntime(overrides: Record<string, unknown> = {}) {
  return {
    version: '3.12.0',
    getUpdateState: desktopGetUpdateState,
    checkForUpdates: desktopCheckForUpdates,
    installDownloadedUpdate: desktopInstallDownloadedUpdate,
    openReleasePage: desktopOpenReleasePage,
    onUpdateStateChange: desktopOnUpdateStateChange,
    ...overrides,
  };
}

const baseCategories = [
  { category: 'system', title: 'System', description: '系统设置', displayOrder: 1, fields: [] },
  { category: 'base', title: 'Base', description: '基础配置', displayOrder: 2, fields: [] },
  { category: 'ai_model', title: 'AI', description: '模型配置', displayOrder: 3, fields: [] },
  { category: 'notification', title: 'Notification', description: '通知配置', displayOrder: 4, fields: [] },
  { category: 'agent', title: 'Agent', description: 'Agent 配置', displayOrder: 5, fields: [] },
];

type ConfigState = {
  categories: Array<{ category: string; title: string; description: string; displayOrder: number; fields: [] }>;
  itemsByCategory: Record<string, Array<Record<string, unknown>>>;
  issueByKey: Record<string, unknown[]>;
  activeCategory: string;
  setActiveCategory: typeof setActiveCategory;
  hasDirty: boolean;
  dirtyCount: number;
  toast: null;
  clearToast: typeof clearToast;
  isLoading: boolean;
  isSaving: boolean;
  loadError: null;
  saveError: null;
  retryAction: null;
  load: typeof load;
  retry: ReturnType<typeof vi.fn>;
  save: typeof save;
  resetDraft: typeof resetDraft;
  setDraftValue: typeof setDraftValue;
  applyPartialUpdate: typeof applyPartialUpdate;
  getChangedItems: () => Array<{ key: string; value: string }>;
  refreshAfterExternalSave: typeof refreshAfterExternalSave;
  configVersion: string;
  maskToken: string;
};

type ConfigOverride = Partial<ConfigState>;

function buildSystemConfigState(overrides: ConfigOverride = {}) {
  return {
    categories: baseCategories,
    itemsByCategory: {
      system: [
        {
          key: 'ADMIN_AUTH_ENABLED',
          value: 'true',
          rawValueExists: true,
          isMasked: false,
          schema: {
            key: 'ADMIN_AUTH_ENABLED',
            category: 'system',
            dataType: 'boolean',
            uiControl: 'switch',
            isSensitive: false,
            isRequired: false,
            isEditable: true,
            options: [],
            validation: {},
            displayOrder: 1,
          },
        },
      ],
      base: [
        {
          key: 'STOCK_LIST',
          value: 'SH600000',
          rawValueExists: true,
          isMasked: false,
          schema: {
            key: 'STOCK_LIST',
            category: 'base',
            dataType: 'string',
            uiControl: 'textarea',
            isSensitive: false,
            isRequired: false,
            isEditable: true,
            options: [],
            validation: {},
            displayOrder: 1,
          },
        },
      ],
      ai_model: [
        {
          key: 'LLM_CHANNELS',
          value: 'primary',
          rawValueExists: true,
          isMasked: false,
          schema: {
            key: 'LLM_CHANNELS',
            category: 'ai_model',
            dataType: 'string',
            uiControl: 'textarea',
            isSensitive: false,
            isRequired: false,
            isEditable: true,
            options: [],
            validation: {},
            displayOrder: 1,
          },
        },
      ],
      agent: [
        {
          key: 'AGENT_ORCHESTRATOR_TIMEOUT_S',
          value: '600',
          rawValueExists: true,
          isMasked: false,
          schema: {
            key: 'AGENT_ORCHESTRATOR_TIMEOUT_S',
            category: 'agent',
            dataType: 'integer',
            uiControl: 'number',
            isSensitive: false,
            isRequired: false,
            isEditable: true,
            options: [],
            validation: {},
            displayOrder: 1,
          },
        },
      ],
      notification: [
        {
          key: 'WECHAT_WEBHOOK_URL',
          value: 'https://qyapi.example.com/hook',
          rawValueExists: true,
          isMasked: false,
          schema: {
            key: 'WECHAT_WEBHOOK_URL',
            category: 'notification',
            dataType: 'string',
            uiControl: 'password',
            isSensitive: true,
            isRequired: false,
            isEditable: true,
            options: [],
            validation: {},
            displayOrder: 1,
          },
        },
      ],
    },
    issueByKey: {},
    activeCategory: 'system',
    setActiveCategory,
    hasDirty: false,
    dirtyCount: 0,
    toast: null,
    clearToast,
    isLoading: false,
    isSaving: false,
    loadError: null,
    saveError: null,
    retryAction: null,
    load,
    retry: vi.fn(),
    save,
    resetDraft,
    setDraftValue,
    applyPartialUpdate,
    getChangedItems: () => [],
    refreshAfterExternalSave,
    configVersion: 'v1',
    maskToken: '******',
    ...overrides,
  };
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    Object.assign(webBuildInfoMock, {
      version: '3.11.0',
      rawVersion: '3.11.0',
      buildId: 'build-20260329-021530Z',
      buildTime: '2026-03-29T02:15:30.000Z',
      isFallbackVersion: false,
    });
    load.mockResolvedValue(true);
    exportEnv.mockResolvedValue({
      content: 'STOCK_LIST=600519\n',
      configVersion: 'v1',
      updatedAt: '2026-03-21T00:00:00Z',
    });
    getSchedulerStatus.mockResolvedValue({
      enabled: true,
      running: false,
      scheduleTimes: ['09:20', '15:10'],
      nextRunAt: '2026-06-21T09:20:00+08:00',
      lastRunAt: null,
      lastSuccessAt: null,
      lastError: null,
    });
    runSchedulerNow.mockResolvedValue({
      accepted: true,
      running: true,
    });
    importEnv.mockResolvedValue({
      success: true,
      configVersion: 'v2',
      appliedCount: 1,
      skippedMaskedCount: 0,
      reloadTriggered: true,
      updatedKeys: ['STOCK_LIST'],
      warnings: [],
    });
    updateSystemConfig.mockResolvedValue({
      success: true,
      configVersion: 'v2',
      updatedKeys: ['ALPHASIFT_ENABLED'],
      reloadTriggered: true,
    });
    alphasiftInstall.mockResolvedValue({
      installed: true,
      alreadyInstalled: true,
      installSpecIsDefault: true,
    });
    alphasiftEnable.mockResolvedValue(undefined);
    desktopGetUpdateState.mockResolvedValue({
      status: 'idle',
      currentVersion: '3.12.0',
      latestVersion: '',
      message: '',
    });
    desktopCheckForUpdates.mockResolvedValue({
      status: 'up-to-date',
      currentVersion: '3.12.0',
      latestVersion: '3.12.0',
      message: '当前桌面端已是最新版本。',
    });
    desktopInstallDownloadedUpdate.mockResolvedValue(true);
    desktopOpenReleasePage.mockResolvedValue(true);
    desktopOnUpdateStateChange.mockImplementation(() => () => undefined);
    useAuthMock.mockReturnValue({
      authEnabled: true,
      passwordChangeable: true,
      refreshStatus,
    });
    useSystemConfigMock.mockReturnValue(buildSystemConfigState());
    delete (window as { dsaDesktop?: unknown }).dsaDesktop;
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(mockedAnchorClick);
  });

  it('renders category navigation and auth settings modules', async () => {
    render(<SettingsPage />);

    expect(await screen.findByRole('heading', { name: '系统设置' })).toBeInTheDocument();
    expect(screen.getByText('认证与登录保护')).toBeInTheDocument();
    expect(screen.getByText('修改密码')).toBeInTheDocument();
    expect(load).toHaveBeenCalled();
  });

  it('renders web build info in system settings', async () => {
    render(<SettingsPage />);

    expect(await screen.findByRole('heading', { name: '版本信息' })).toBeInTheDocument();
    expect(screen.getByText('3.11.0')).toBeInTheDocument();
    expect(screen.getByText('build-20260329-021530Z')).toBeInTheDocument();
    expect(screen.getByText('2026-03-29T02:15:30.000Z')).toBeInTheDocument();
  });

  it('renders desktop app version in system settings during desktop runtime', async () => {
    (window as { dsaDesktop?: unknown }).dsaDesktop = { version: '3.12.0' };

    render(<SettingsPage />);

    expect(await screen.findByRole('heading', { name: '版本信息' })).toBeInTheDocument();
    expect(screen.getByText('桌面端版本')).toBeInTheDocument();
    expect(screen.getByText('3.12.0')).toBeInTheDocument();
  });

  it('keeps version grid at three columns when desktop runtime has no usable version', async () => {
    (window as { dsaDesktop?: unknown }).dsaDesktop = { version: '   ' };

    render(<SettingsPage />);

    const section = (await screen.findByRole('heading', { name: '版本信息' })).closest('section');
    const versionGrid = section?.querySelector('div.grid.grid-cols-1.gap-3');

    expect(screen.queryByText('桌面端版本')).not.toBeInTheDocument();
    expect(versionGrid).toHaveClass('md:grid-cols-3');
    expect(versionGrid).not.toHaveClass('md:grid-cols-4');
  });

  it('ignores non-string desktop runtime version values without breaking render', async () => {
    (window as { dsaDesktop?: unknown }).dsaDesktop = { version: 3120 };

    render(<SettingsPage />);

    const section = (await screen.findByRole('heading', { name: '版本信息' })).closest('section');
    const versionGrid = section?.querySelector('div.grid.grid-cols-1.gap-3');

    expect(screen.queryByText('桌面端版本')).not.toBeInTheDocument();
    expect(versionGrid).toHaveClass('md:grid-cols-3');
  });

  it('normalizes malformed desktop update payloads instead of throwing', async () => {
    desktopGetUpdateState.mockResolvedValue({
      status: 123,
      currentVersion: 3120,
      latestVersion: null,
      releaseUrl: { href: 'https://example.com' },
      checkedAt: ['2026-04-25T01:02:00Z'],
      message: false,
      releaseName: { text: 'v3.13.0' },
      tagName: undefined,
    });
    (window as { dsaDesktop?: unknown }).dsaDesktop = createDesktopRuntime();

    render(<SettingsPage />);

    await waitFor(() => {
      expect(desktopGetUpdateState).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByRole('button', { name: '检查更新' })).toBeInTheDocument();
    expect(screen.queryByText('检查更新失败')).not.toBeInTheDocument();
    expect(screen.queryByText('发现新版本')).not.toBeInTheDocument();
  });

  it('falls back to build identifier when package version is still placeholder', () => {
    expect(resolveWebBuildInfo({
      packageVersion: '0.0.0',
      buildTimestamp: '2026-03-29T02:15:30.000Z',
    })).toEqual({
      version: 'build-20260329-021530Z',
      rawVersion: '0.0.0',
      buildId: 'build-20260329-021530Z',
      buildTime: '2026-03-29T02:15:30.000Z',
      isFallbackVersion: true,
    });
  });

  it('renders fallback version hint when package version is placeholder', async () => {
    Object.assign(webBuildInfoMock, {
      version: 'build-20260329-021530Z',
      rawVersion: '0.0.0',
      buildId: 'build-20260329-021530Z',
      buildTime: '2026-03-29T02:15:30.000Z',
      isFallbackVersion: true,
    });

    render(<SettingsPage />);

    expect(await screen.findByRole('heading', { name: '版本信息' })).toBeInTheDocument();
    expect(screen.getByText(/当前 package\.json 仍为占位版本 0\.0\.0/)).toBeInTheDocument();
    expect(screen.getAllByText('build-20260329-021530Z')).toHaveLength(2);
  });

  it('resets local drafts from the page header button', () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({ hasDirty: true, dirtyCount: 2 }));

    render(<SettingsPage />);

    // Clear the initial load call from useEffect
    vi.clearAllMocks();

    fireEvent.click(screen.getByRole('button', { name: '重置' }));

    // Reset should call resetDraft and NOT call load
    expect(resetDraft).toHaveBeenCalledTimes(1);
    expect(load).not.toHaveBeenCalled();
  });

  it('shows deep research and event monitor fields in the agent category when available', () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'agent',
      itemsByCategory: {
        ...buildSystemConfigState().itemsByCategory,
        agent: [
          {
            key: 'AGENT_ORCHESTRATOR_TIMEOUT_S',
            value: '600',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'AGENT_ORCHESTRATOR_TIMEOUT_S',
              category: 'agent',
              dataType: 'integer',
              uiControl: 'number',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 1,
            },
          },
          {
            key: 'AGENT_DEEP_RESEARCH_BUDGET',
            value: '30000',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'AGENT_DEEP_RESEARCH_BUDGET',
              category: 'agent',
              dataType: 'integer',
              uiControl: 'number',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 2,
            },
          },
          {
            key: 'AGENT_EVENT_MONITOR_ENABLED',
            value: 'false',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'AGENT_EVENT_MONITOR_ENABLED',
              category: 'agent',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 3,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    expect(screen.getByText('AGENT_ORCHESTRATOR_TIMEOUT_S')).toBeInTheDocument();
    expect(screen.getByText('AGENT_DEEP_RESEARCH_BUDGET')).toBeInTheDocument();
    expect(screen.getByText('AGENT_EVENT_MONITOR_ENABLED')).toBeInTheDocument();
    expect(settingsPanelErrorBoundary).toHaveBeenCalledWith('Agent 设置');
  });

  it('renders context compression profile labels and blank preset guidance in agent settings', () => {
    const configState = buildSystemConfigState();
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'agent',
      itemsByCategory: {
        ...configState.itemsByCategory,
        agent: [
          {
            key: 'AGENT_CONTEXT_COMPRESSION_PROFILE',
            value: 'balanced',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'AGENT_CONTEXT_COMPRESSION_PROFILE',
              category: 'agent',
              dataType: 'string',
              uiControl: 'select',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [
                { label: '成本优先', value: 'cost' },
                { label: '均衡推荐', value: 'balanced' },
                { label: '长上下文原文优先', value: 'long_context_raw_first' },
              ],
              validation: {
                enum: ['cost', 'balanced', 'long_context_raw_first'],
              },
              displayOrder: 72,
            },
          },
          {
            key: 'AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS',
            value: '',
            rawValueExists: false,
            isMasked: false,
            schema: {
              key: 'AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS',
              category: 'agent',
              dataType: 'integer',
              uiControl: 'number',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: { min: 1000 },
              displayOrder: 73,
              description: '估算历史 token 超过该值时触发摘要；留空则跟随当前上下文压缩策略 profile 默认值。',
            },
          },
          {
            key: 'AGENT_CONTEXT_PROTECTED_TURNS',
            value: '',
            rawValueExists: false,
            isMasked: false,
            schema: {
              key: 'AGENT_CONTEXT_PROTECTED_TURNS',
              category: 'agent',
              dataType: 'integer',
              uiControl: 'number',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: { min: 1 },
              displayOrder: 74,
              description: '压缩时最近 N 个用户轮次及其后的回复保持原文；留空则跟随当前上下文压缩策略 profile 默认值。',
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    expect(screen.getByText('AGENT_CONTEXT_COMPRESSION_PROFILE')).toBeInTheDocument();
    expect(screen.getByText('成本优先')).toBeInTheDocument();
    expect(screen.getByText('均衡推荐')).toBeInTheDocument();
    expect(screen.getByText('长上下文原文优先')).toBeInTheDocument();
    expect(screen.getByText(/估算历史 token 超过该值时触发摘要/)).toHaveTextContent('留空则跟随当前上下文压缩策略 profile 默认值');
    expect(screen.getByText(/压缩时最近 N 个用户轮次及其后的回复保持原文/)).toHaveTextContent('留空则跟随当前上下文压缩策略 profile 默认值');
  });

  it('reset button semantic: discards local changes without network request', () => {
    // Simulate user has unsaved drafts
    const dirtyState = buildSystemConfigState({
      hasDirty: true,
      dirtyCount: 2,
    });

    useSystemConfigMock.mockReturnValue(dirtyState);

    render(<SettingsPage />);

    // Clear initial useEffect load call
    vi.clearAllMocks();

    // Click reset button
    fireEvent.click(screen.getByRole('button', { name: '重置' }));

    // Verify semantic: reset should only discard local changes
    // It should NOT trigger a network load
    expect(resetDraft).toHaveBeenCalledTimes(1);
    expect(load).not.toHaveBeenCalled();
    expect(save).not.toHaveBeenCalled();
  });

  it('refreshes server state after intelligent import merges stock list', async () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({ activeCategory: 'base' }));

    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: 'merge stock list' }));

    expect(refreshAfterExternalSave).toHaveBeenCalledWith(['STOCK_LIST']);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('refreshes server state after llm channel editor saves', async () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({ activeCategory: 'ai_model' }));

    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: 'save llm channels' }));

    expect(refreshAfterExternalSave).toHaveBeenCalledWith(['LLM_CHANNELS']);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('keeps prompt cache settings collapsed and expandable at the bottom of AI model settings', () => {
    const aiField = (key: string, displayOrder: number, value = '') => ({
      key,
      value,
      rawValueExists: Boolean(value),
      isMasked: false,
      schema: {
        key,
        category: 'ai_model',
        dataType: 'string',
        uiControl: key === 'LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL' ? 'select' : 'text',
        isSensitive: false,
        isRequired: false,
        isEditable: true,
        options: key === 'LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL' ? ['off', 'basic', 'debug'] : [],
        validation: {},
        displayOrder,
      },
    });
    const configState = buildSystemConfigState();
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'ai_model',
      itemsByCategory: {
        ...configState.itemsByCategory,
        ai_model: [
          aiField('LITELLM_CONFIG', 10, './litellm.yaml'),
          aiField('LLM_PROMPT_CACHE_TELEMETRY_ENABLED', 20, 'true'),
          aiField('LLM_PROMPT_CACHE_HINTS_ENABLED', 21, 'false'),
          aiField('LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL', 22, 'off'),
        ],
      },
    }));

    const { container } = render(<SettingsPage />);

    const promptCacheSummary = screen.getByText('Provider Prompt Cache 高级设置').closest('summary');
    const promptCacheDetails = promptCacheSummary?.closest('details');
    const telemetryField = screen.getByTestId('settings-field-LLM_PROMPT_CACHE_TELEMETRY_ENABLED');
    const hintsField = screen.getByTestId('settings-field-LLM_PROMPT_CACHE_HINTS_ENABLED');
    const diagnosticsField = screen.getByTestId('settings-field-LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL');

    expect(promptCacheSummary).toBeInTheDocument();
    expect(promptCacheDetails).toBeInTheDocument();
    expect(promptCacheDetails).not.toHaveAttribute('open');
    expect(promptCacheDetails).toContainElement(telemetryField);
    expect(promptCacheDetails).toContainElement(hintsField);
    expect(promptCacheDetails).toContainElement(diagnosticsField);
    expect(telemetryField).not.toBeVisible();
    expect(hintsField).not.toBeVisible();
    expect(diagnosticsField).not.toBeVisible();

    fireEvent.click(promptCacheSummary as HTMLElement);

    expect(promptCacheDetails).toHaveAttribute('open');
    expect(telemetryField).toBeVisible();
    expect(hintsField).toBeVisible();
    expect(diagnosticsField).toBeVisible();

    expect(Array.from(container.querySelectorAll('[data-testid^="settings-field-"]')).map((node) => node.getAttribute('data-testid'))).toEqual([
      'settings-field-LITELLM_CONFIG',
      'settings-field-LLM_PROMPT_CACHE_TELEMETRY_ENABLED',
      'settings-field-LLM_PROMPT_CACHE_HINTS_ENABLED',
      'settings-field-LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL',
    ]);
  });

  it('notifies alphasift status update and skips install after generic save when ALPHASIFT_ENABLED is set false', async () => {
    save.mockResolvedValue({ success: true });
    getChangedItems.mockReturnValue([{ key: 'ALPHASIFT_ENABLED', value: 'false' }]);

    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      hasDirty: true,
      dirtyCount: 1,
      getChangedItems: () => [{ key: 'ALPHASIFT_ENABLED', value: 'false' }],
    }));

    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: /保存配置/ }));

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(notifyAlphaSiftConfigChanged).toHaveBeenCalledTimes(1);
    expect(notifySystemConfigChanged).toHaveBeenCalledTimes(1);
    expect(alphasiftEnable).not.toHaveBeenCalled();
    expect(alphasiftInstall).not.toHaveBeenCalled();
  });

  it('runs the AlphaSift enable flow after generic save when ALPHASIFT_ENABLED is set true', async () => {
    save.mockResolvedValue({ success: true });
    getChangedItems.mockReturnValue([{ key: 'ALPHASIFT_ENABLED', value: 'true' }]);

    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      hasDirty: true,
      dirtyCount: 1,
      getChangedItems: () => [{ key: 'ALPHASIFT_ENABLED', value: 'true' }],
    }));

    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: /保存配置/ }));

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(notifySystemConfigChanged).toHaveBeenCalledTimes(1);
    expect(alphasiftEnable).toHaveBeenCalledTimes(1);
    expect(alphasiftInstall).not.toHaveBeenCalled();
    expect(refreshAfterExternalSave).toHaveBeenCalledWith(['ALPHASIFT_ENABLED']);
  });

  it('does not notify alphasift status when generic save updates other fields', async () => {
    save.mockResolvedValue({ success: true });
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      hasDirty: true,
      dirtyCount: 1,
      getChangedItems: () => [{ key: 'LLM_CHANNELS', value: 'primary,backup' }],
    }));

    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: /保存配置/ }));

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(notifySystemConfigChanged).toHaveBeenCalledTimes(1);
    expect(notifyAlphaSiftConfigChanged).not.toHaveBeenCalled();
  });

  it('runs AlphaSift enable flow from the settings card', async () => {
    const configState = buildSystemConfigState();
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      itemsByCategory: {
        ...configState.itemsByCategory,
        data_source: [
          {
            key: 'ALPHASIFT_ENABLED',
            value: 'false',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'ALPHASIFT_ENABLED',
              category: 'data_source',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 16,
            },
          },
          {
            key: 'ALPHASIFT_INSTALL_SPEC',
            value: 'git+https://github.com/ZhuLinsen/alphasift.git@2c76b2b6074ae3bae01d52e5e830a4af3e3246b2',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'ALPHASIFT_INSTALL_SPEC',
              category: 'data_source',
              dataType: 'string',
              uiControl: 'password',
              isSensitive: true,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 17,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: '开启选股' }));

    await waitFor(() => expect(alphasiftEnable).toHaveBeenCalledTimes(1));
    expect(updateSystemConfig).not.toHaveBeenCalled();
    expect(alphasiftInstall).not.toHaveBeenCalled();
    expect(refreshAfterExternalSave).toHaveBeenCalledWith(['ALPHASIFT_ENABLED']);
  });

  it('does not render raw AlphaSift install spec in the settings card', () => {
    const privateInstallSpec = 'git+https://user:token@example.com/internal/alphasift.git';
    const configState = buildSystemConfigState();
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      itemsByCategory: {
        ...configState.itemsByCategory,
        data_source: [
          {
            key: 'ALPHASIFT_ENABLED',
            value: 'true',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'ALPHASIFT_ENABLED',
              category: 'data_source',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 16,
            },
          },
          {
            key: 'ALPHASIFT_INSTALL_SPEC',
            value: privateInstallSpec,
            rawValueExists: true,
            isMasked: true,
            schema: {
              key: 'ALPHASIFT_INSTALL_SPEC',
              category: 'data_source',
              dataType: 'string',
              uiControl: 'password',
              isSensitive: true,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 17,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    expect(screen.getByText('启用内置 AlphaSift 实验性质选股能力。')).toBeInTheDocument();
    expect(screen.queryByText(privateInstallSpec)).not.toBeInTheDocument();
    expect(screen.queryByText(/安装来源/)).not.toBeInTheDocument();
  });

  it('maps ALPHASIFT_ENABLED to the AlphaSift card instead of a generic settings field', () => {
    const configState = buildSystemConfigState();
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'data_source',
      itemsByCategory: {
        ...configState.itemsByCategory,
        data_source: [
          {
            key: 'ALPHASIFT_ENABLED',
            value: 'false',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'ALPHASIFT_ENABLED',
              category: 'data_source',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 16,
            },
          },
          {
            key: 'ALPHASIFT_INSTALL_SPEC',
            value: '******',
            rawValueExists: true,
            isMasked: true,
            schema: {
              key: 'ALPHASIFT_INSTALL_SPEC',
              category: 'data_source',
              dataType: 'string',
              uiControl: 'password',
              isSensitive: true,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 17,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    expect(screen.getByRole('button', { name: '开启选股' })).toBeInTheDocument();
    expect(screen.queryByTestId('settings-field-ALPHASIFT_ENABLED')).not.toBeInTheDocument();
    expect(screen.getByTestId('settings-field-ALPHASIFT_INSTALL_SPEC')).toBeInTheDocument();
  });

  it('maps schedule settings to the scheduler card instead of generic raw fields', async () => {
    const configState = buildSystemConfigState();
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'system',
      itemsByCategory: {
        ...configState.itemsByCategory,
        system: [
          ...configState.itemsByCategory.system,
          {
            key: 'SCHEDULE_ENABLED',
            value: 'true',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_ENABLED',
              category: 'system',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 8,
            },
          },
          {
            key: 'SCHEDULE_TIME',
            value: '18:00',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_TIME',
              category: 'system',
              dataType: 'time',
              uiControl: 'time',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 10,
            },
          },
          {
            key: 'SCHEDULE_TIMES',
            value: '09:20,15:10',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_TIMES',
              category: 'system',
              dataType: 'string',
              uiControl: 'text',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 11,
            },
          },
          {
            key: 'SCHEDULE_RUN_IMMEDIATELY',
            value: 'false',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_RUN_IMMEDIATELY',
              category: 'system',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 12,
            },
          },
          {
            key: 'LOG_LEVEL',
            value: 'INFO',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'LOG_LEVEL',
              category: 'system',
              dataType: 'string',
              uiControl: 'select',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: ['INFO', 'DEBUG'],
              validation: {},
              displayOrder: 50,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    expect(await screen.findByTestId('scheduler-settings-card')).toBeInTheDocument();
    expect(screen.queryByTestId('settings-field-SCHEDULE_ENABLED')).not.toBeInTheDocument();
    expect(screen.queryByTestId('settings-field-SCHEDULE_TIME')).not.toBeInTheDocument();
    expect(screen.queryByTestId('settings-field-SCHEDULE_TIMES')).not.toBeInTheDocument();
    expect(screen.queryByTestId('settings-field-SCHEDULE_RUN_IMMEDIATELY')).not.toBeInTheDocument();
    expect(screen.getByTestId('settings-field-LOG_LEVEL')).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('scheduler-time-input-0'), {
      target: { value: '10:30' },
    });

    expect(setDraftValue).toHaveBeenCalledWith('SCHEDULE_TIMES', '10:30,15:10');

    fireEvent.click(screen.getByTestId('scheduler-run-now-button'));

    await waitFor(() => expect(runSchedulerNow).toHaveBeenCalledTimes(1));
  });

  it('shows an error when run-now is rejected because analysis is already running', async () => {
    runSchedulerNow.mockRejectedValueOnce(new Error('A scheduled analysis is already running'));
    const configState = buildSystemConfigState();
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'system',
      itemsByCategory: {
        ...configState.itemsByCategory,
        system: [
          ...configState.itemsByCategory.system,
          {
            key: 'SCHEDULE_ENABLED',
            value: 'true',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_ENABLED',
              category: 'system',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 8,
            },
          },
          {
            key: 'SCHEDULE_TIMES',
            value: '18:00',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_TIMES',
              category: 'system',
              dataType: 'string',
              uiControl: 'text',
              isSensitive: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 11,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    fireEvent.click(await screen.findByTestId('scheduler-run-now-button'));

    await waitFor(() => expect(runSchedulerNow).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/A scheduled analysis is already running/)).toBeInTheDocument();
  });

  it('does not show a failed run as the last successful scheduler run', async () => {
    const configState = buildSystemConfigState();
    getSchedulerStatus.mockResolvedValueOnce({
      enabled: true,
      running: false,
      scheduleTimes: ['18:00'],
      nextRunAt: null,
      lastRunAt: '2026-06-21T17:00:00+08:00',
      lastSuccessAt: null,
      lastError: 'analysis failed',
    });
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'system',
      itemsByCategory: {
        ...configState.itemsByCategory,
        system: [
          ...configState.itemsByCategory.system,
          {
            key: 'SCHEDULE_ENABLED',
            value: 'true',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_ENABLED',
              category: 'system',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 8,
            },
          },
          {
            key: 'SCHEDULE_TIMES',
            value: '18:00',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_TIMES',
              category: 'system',
              dataType: 'string',
              uiControl: 'text',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 11,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    expect(await screen.findByTestId('scheduler-last-success')).toHaveTextContent('-');
    expect(screen.getByTestId('scheduler-last-error')).toHaveTextContent('analysis failed');
  });

  it('shows active runtime scheduler state even when saved schedule flag is false', async () => {
    const configState = buildSystemConfigState();
    getSchedulerStatus.mockResolvedValueOnce({
      enabled: true,
      running: false,
      scheduleTimes: ['18:00'],
      nextRunAt: null,
      lastRunAt: null,
      lastSuccessAt: null,
      lastError: null,
    });
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'system',
      itemsByCategory: {
        ...configState.itemsByCategory,
        system: [
          ...configState.itemsByCategory.system,
          {
            key: 'SCHEDULE_ENABLED',
            value: 'false',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_ENABLED',
              category: 'system',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 8,
            },
          },
          {
            key: 'SCHEDULE_TIMES',
            value: '18:00',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_TIMES',
              category: 'system',
              dataType: 'string',
              uiControl: 'text',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 11,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    const enabledCheckbox = await screen.findByTestId('scheduler-enabled-checkbox');
    expect(enabledCheckbox).toBeChecked();

    fireEvent.click(enabledCheckbox);

    expect(setDraftValue).toHaveBeenCalledWith('SCHEDULE_ENABLED', 'false');
    await waitFor(() => expect(enabledCheckbox).not.toBeChecked());
  });

  it('keeps local scheduler toggle edits when runtime and saved states are initially consistent', async () => {
    const configState = buildSystemConfigState();
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'system',
      itemsByCategory: {
        ...configState.itemsByCategory,
        system: [
          ...configState.itemsByCategory.system,
          {
            key: 'SCHEDULE_ENABLED',
            value: 'true',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_ENABLED',
              category: 'system',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 8,
            },
          },
          {
            key: 'SCHEDULE_TIMES',
            value: '18:00',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_TIMES',
              category: 'system',
              dataType: 'string',
              uiControl: 'text',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 11,
            },
          },
        ],
      },
    }));
    render(<SettingsPage />);

    const enabledCheckbox = await screen.findByTestId('scheduler-enabled-checkbox');
    expect(enabledCheckbox).toBeChecked();

    fireEvent.click(enabledCheckbox);

    expect(setDraftValue).toHaveBeenCalledWith('SCHEDULE_ENABLED', 'false');
    await waitFor(() => expect(enabledCheckbox).not.toBeChecked());

    const refreshButton = screen.getByTestId('scheduler-refresh-status-button');
    fireEvent.click(refreshButton);
    await waitFor(() => expect(enabledCheckbox).not.toBeChecked());
  });

  it('can reconcile runtime scheduler state when runtime is enabled but saved value is disabled', async () => {
    save.mockResolvedValue({ success: true });
    getChangedItems.mockReturnValue([]);
    const configState = buildSystemConfigState();
    getSchedulerStatus.mockResolvedValueOnce({
      enabled: true,
      running: false,
      scheduleTimes: ['18:00'],
      nextRunAt: null,
      lastRunAt: null,
      lastSuccessAt: null,
      lastError: null,
    });
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'system',
      hasDirty: false,
      dirtyCount: 0,
      getChangedItems: () => [],
      itemsByCategory: {
        ...configState.itemsByCategory,
        system: [
          ...configState.itemsByCategory.system,
          {
            key: 'SCHEDULE_ENABLED',
            value: 'false',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_ENABLED',
              category: 'system',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 8,
            },
          },
          {
            key: 'SCHEDULE_TIMES',
            value: '18:00',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_TIMES',
              category: 'system',
              dataType: 'string',
              uiControl: 'text',
              isSensitive: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 11,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    const saveButton = screen.getByRole('button', { name: /保存配置/ });
    expect(saveButton).toBeDisabled();

    const enabledCheckbox = await screen.findByTestId('scheduler-enabled-checkbox');
    expect(enabledCheckbox).toBeChecked();
    fireEvent.click(enabledCheckbox);

    await waitFor(() => expect(enabledCheckbox).not.toBeChecked());
    await waitFor(() => expect(saveButton).toBeEnabled());
    await waitFor(() => expect(saveButton).toHaveTextContent('保存配置 (1)'));

    fireEvent.click(saveButton);
    await waitFor(() => expect(save).toHaveBeenCalledWith([{ key: 'SCHEDULE_ENABLED', value: 'false' }]));
  });

  it('can reconcile runtime scheduler state when runtime is disabled but saved value is enabled', async () => {
    save.mockResolvedValue({ success: true });
    getChangedItems.mockReturnValue([]);
    const configState = buildSystemConfigState();
    getSchedulerStatus.mockResolvedValueOnce({
      enabled: false,
      running: false,
      scheduleTimes: ['18:00'],
      nextRunAt: null,
      lastRunAt: null,
      lastSuccessAt: null,
      lastError: null,
    });
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'system',
      hasDirty: false,
      dirtyCount: 0,
      getChangedItems: () => [],
      itemsByCategory: {
        ...configState.itemsByCategory,
        system: [
          ...configState.itemsByCategory.system,
          {
            key: 'SCHEDULE_ENABLED',
            value: 'true',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_ENABLED',
              category: 'system',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 8,
            },
          },
          {
            key: 'SCHEDULE_TIMES',
            value: '18:00',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_TIMES',
              category: 'system',
              dataType: 'string',
              uiControl: 'text',
              isSensitive: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 11,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    const saveButton = screen.getByRole('button', { name: /保存配置/ });
    expect(saveButton).toBeDisabled();

    const enabledCheckbox = await screen.findByTestId('scheduler-enabled-checkbox');
    expect(enabledCheckbox).not.toBeChecked();
    fireEvent.click(enabledCheckbox);

    await waitFor(() => expect(enabledCheckbox).toBeChecked());
    await waitFor(() => expect(saveButton).toBeEnabled());
    await waitFor(() => expect(saveButton).toHaveTextContent('保存配置 (1)'));

    fireEvent.click(saveButton);
    await waitFor(() => expect(save).toHaveBeenCalledWith([{ key: 'SCHEDULE_ENABLED', value: 'true' }]));
  });

  it('refreshes scheduler status after saving scheduler settings', async () => {
    const configState = buildSystemConfigState();
    getSchedulerStatus
      .mockResolvedValueOnce({
        enabled: false,
        running: false,
        scheduleTimes: [],
        nextRunAt: null,
        lastRunAt: null,
        lastSuccessAt: null,
        lastError: null,
      })
      .mockResolvedValueOnce({
        enabled: true,
        running: false,
        scheduleTimes: ['09:20', '15:10'],
        nextRunAt: '2026-06-21T09:20:00+08:00',
        lastRunAt: null,
        lastSuccessAt: null,
        lastError: null,
      });
    save.mockResolvedValue({ success: true });
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'system',
      hasDirty: true,
      dirtyCount: 1,
      getChangedItems: () => [{ key: 'SCHEDULE_ENABLED', value: 'true' }],
      itemsByCategory: {
        ...configState.itemsByCategory,
        system: [
          ...configState.itemsByCategory.system,
          {
            key: 'SCHEDULE_ENABLED',
            value: 'false',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_ENABLED',
              category: 'system',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 8,
            },
          },
          {
            key: 'SCHEDULE_TIMES',
            value: '09:20,15:10',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_TIMES',
              category: 'system',
              dataType: 'string',
              uiControl: 'text',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 11,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    expect(await screen.findByText('未启用')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '保存配置 (1)' }));

    await waitFor(() => expect(getSchedulerStatus).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('已启用')).toBeInTheDocument();
  });

  it('refreshes AlphaSift state when the enable flow fails', async () => {
    const configState = buildSystemConfigState();
    alphasiftEnable.mockRejectedValueOnce(new Error('config update failed'));
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      itemsByCategory: {
        ...configState.itemsByCategory,
        data_source: [
          {
            key: 'ALPHASIFT_ENABLED',
            value: 'false',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'ALPHASIFT_ENABLED',
              category: 'data_source',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 16,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: '开启选股' }));

    await waitFor(() => expect(alphasiftEnable).toHaveBeenCalledTimes(1));
    expect(updateSystemConfig).not.toHaveBeenCalled();
    expect(alphasiftInstall).not.toHaveBeenCalled();
    expect(refreshAfterExternalSave).toHaveBeenCalledWith(['ALPHASIFT_ENABLED']);
  });

  it('passes LLM channel support keys to the channel editor without rendering them as generic fields', async () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'ai_model',
      itemsByCategory: {
        ...buildSystemConfigState().itemsByCategory,
        ai_model: [
          {
            key: 'LLM_CHANNELS',
            value: 'my_proxy',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'LLM_CHANNELS',
              category: 'ai_model',
              dataType: 'string',
              uiControl: 'textarea',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 1,
            },
          },
          {
            key: 'LITELLM_MODEL',
            value: 'gpt-5.0',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'LITELLM_MODEL',
              category: 'ai_model',
              dataType: 'string',
              uiControl: 'text',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 2,
            },
          },
          {
            key: 'OPENAI_BASE_URL',
            value: 'https://api.openai.com/v1',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'OPENAI_BASE_URL',
              category: 'ai_model',
              dataType: 'string',
              uiControl: 'text',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 3,
            },
          },
          {
            key: 'OPENAI_MODEL',
            value: 'gpt-5.0',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'OPENAI_MODEL',
              category: 'ai_model',
              isMasked: false,
              dataType: 'string',
              uiControl: 'text',
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 4,
            },
          },
          {
            key: 'LLM_MY_PROXY_API_KEY',
            value: 'sk-test',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'LLM_MY_PROXY_API_KEY',
              category: 'ai_model',
              dataType: 'string',
              uiControl: 'password',
              isSensitive: true,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 9000,
            },
          },
          {
            key: 'LLM_MY_PROXY_MODELS',
            value: 'gpt-5.5',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'LLM_MY_PROXY_MODELS',
              category: 'ai_model',
              dataType: 'string',
              uiControl: 'text',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 9000,
            },
          },
        ],
      },
    }));

    render(<SettingsPage />);

    const llmEditorItems = await screen.findByTestId('llm-channel-editor-items');
    expect(llmEditorItems).toHaveTextContent('LLM_CHANNELS');
    expect(llmEditorItems).toHaveTextContent('LITELLM_MODEL');
    expect(llmEditorItems).toHaveTextContent('OPENAI_BASE_URL');
    expect(llmEditorItems).toHaveTextContent('OPENAI_MODEL');
    expect(llmEditorItems).toHaveTextContent('LLM_MY_PROXY_API_KEY');
    expect(llmEditorItems).toHaveTextContent('LLM_MY_PROXY_MODELS');
    expect(screen.queryByTestId('settings-field-LITELLM_MODEL')).not.toBeInTheDocument();
    expect(screen.queryByTestId('settings-field-OPENAI_BASE_URL')).not.toBeInTheDocument();
    expect(screen.queryByTestId('settings-field-OPENAI_MODEL')).not.toBeInTheDocument();
    expect(screen.queryByTestId('settings-field-LLM_MY_PROXY_API_KEY')).not.toBeInTheDocument();
    expect(screen.queryByTestId('settings-field-LLM_MY_PROXY_MODELS')).not.toBeInTheDocument();
  });

  it('renders notification test panel before notification fields', () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({ activeCategory: 'notification' }));

    render(<SettingsPage />);

    expect(screen.getByText('通知测试面板:WECHAT_WEBHOOK_URL')).toBeInTheDocument();
    expect(screen.getByText('WECHAT_WEBHOOK_URL')).toBeInTheDocument();
    expect(settingsPanelErrorBoundary).toHaveBeenCalledWith('通知测试');
    expect(settingsPanelErrorBoundary).toHaveBeenCalledWith('通知设置');
  });

  it('uses browser and backend logs in settings panel diagnostic hints outside desktop runtime', () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({ activeCategory: 'notification' }));

    render(<SettingsPage />);

    expect(screen.getAllByText(/浏览器开发者工具控制台与后端日志/)).toHaveLength(2);
    expect(screen.queryByText('desktop.log')).not.toBeInTheDocument();
  });

  it('uses desktop log in settings panel diagnostic hints during desktop runtime', () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({ activeCategory: 'notification' }));
    (window as { dsaDesktop?: unknown }).dsaDesktop = createDesktopRuntime();

    render(<SettingsPage />);

    expect(screen.getAllByText('desktop.log')).toHaveLength(2);
    expect(screen.queryByText(/浏览器开发者工具控制台与后端日志/)).not.toBeInTheDocument();
  });

  it('renders env backup actions outside desktop runtime', () => {
    render(<SettingsPage />);

    expect(screen.getByRole('heading', { name: '配置备份' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '导出 .env' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '导入 .env' })).toBeInTheDocument();
    expect(screen.getByText(/Docker 部署中/)).toHaveTextContent('ENV_FILE');
  });

  it('disables env backup actions when web auth is not enabled', () => {
    useAuthMock.mockReturnValue({
      authEnabled: false,
      passwordChangeable: false,
      refreshStatus,
    });

    render(<SettingsPage />);

    expect(screen.getByText(/当前 Web 端未开启管理员鉴权/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '导出 .env' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '导入 .env' })).toBeDisabled();
  });

  it('uses live auth state for env backup availability instead of loaded config items', () => {
    const configState = buildSystemConfigState();
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      itemsByCategory: {
        ...configState.itemsByCategory,
        system: configState.itemsByCategory.system.map((item) => (
          item.key === 'ADMIN_AUTH_ENABLED' ? { ...item, value: 'false' } : item
        )),
      },
    }));
    useAuthMock.mockReturnValue({
      authEnabled: true,
      passwordChangeable: true,
      refreshStatus,
    });

    render(<SettingsPage />);

    expect(screen.queryByText(/当前 Web 端未开启管理员鉴权/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '导出 .env' })).not.toBeDisabled();
    expect(screen.getByRole('button', { name: '导入 .env' })).not.toBeDisabled();
  });

  it('exports saved env from config backup actions', async () => {
    (window as { dsaDesktop?: unknown }).dsaDesktop = { version: '3.12.0' };

    render(<SettingsPage />);

    vi.clearAllMocks();

    fireEvent.click(screen.getByRole('button', { name: '导出 .env' }));

    await waitFor(() => expect(exportEnv).toHaveBeenCalledTimes(1));
    expect(mockedAnchorClick).toHaveBeenCalledTimes(1);
    expect(load).not.toHaveBeenCalled();
  });

  it('asks for confirmation before importing when local drafts exist', async () => {
    (window as { dsaDesktop?: unknown }).dsaDesktop = { version: '3.12.0' };
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({ hasDirty: true, dirtyCount: 2 }));

    render(<SettingsPage />);

    vi.clearAllMocks();

    fireEvent.click(screen.getByRole('button', { name: '导入 .env' }));

    expect(await screen.findByText('导入会覆盖当前草稿')).toBeInTheDocument();
    expect(importEnv).not.toHaveBeenCalled();
  });

  it('reloads config after successful env import', async () => {
    (window as { dsaDesktop?: unknown }).dsaDesktop = { version: '3.12.0' };

    const { container } = render(<SettingsPage />);

    vi.clearAllMocks();

    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();

    fireEvent.change(input as HTMLInputElement, {
      target: {
        files: [new File(['STOCK_LIST=300750\n'], 'desktop-backup.env', { type: 'text/plain' })],
      },
    });

    await waitFor(() => expect(importEnv).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  });

  it('refreshes scheduler status after successful env import updates scheduler settings', async () => {
    (window as { dsaDesktop?: unknown }).dsaDesktop = { version: '3.12.0' };
    const configState = buildSystemConfigState();
    getSchedulerStatus
      .mockResolvedValueOnce({
        enabled: false,
        running: false,
        scheduleTimes: ['18:00'],
        nextRunAt: null,
        lastRunAt: null,
        lastSuccessAt: null,
        lastError: null,
      })
      .mockResolvedValueOnce({
        enabled: true,
        running: false,
        scheduleTimes: ['09:20', '15:10'],
        nextRunAt: '2026-06-21T09:20:00+08:00',
        lastRunAt: null,
        lastSuccessAt: null,
        lastError: null,
      });
    importEnv.mockResolvedValueOnce({
      success: true,
      configVersion: 'v2',
      appliedCount: 2,
      skippedMaskedCount: 0,
      reloadTriggered: true,
      updatedKeys: ['SCHEDULE_ENABLED', 'SCHEDULE_TIMES'],
      warnings: [],
    });
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      activeCategory: 'system',
      itemsByCategory: {
        ...configState.itemsByCategory,
        system: [
          ...configState.itemsByCategory.system,
          {
            key: 'SCHEDULE_ENABLED',
            value: 'false',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_ENABLED',
              category: 'system',
              dataType: 'boolean',
              uiControl: 'switch',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 8,
            },
          },
          {
            key: 'SCHEDULE_TIMES',
            value: '18:00',
            rawValueExists: true,
            isMasked: false,
            schema: {
              key: 'SCHEDULE_TIMES',
              category: 'system',
              dataType: 'string',
              uiControl: 'text',
              isSensitive: false,
              isRequired: false,
              isEditable: true,
              options: [],
              validation: {},
              displayOrder: 11,
            },
          },
        ],
      },
    }));

    const { container } = render(<SettingsPage />);

    await waitFor(() => expect(getSchedulerStatus).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('未启用')).toBeInTheDocument();

    vi.clearAllMocks();

    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();

    fireEvent.change(input as HTMLInputElement, {
      target: {
        files: [new File(['SCHEDULE_ENABLED=true\nSCHEDULE_TIMES=09:20,15:10\n'], 'desktop-backup.env', { type: 'text/plain' })],
      },
    });

    await waitFor(() => expect(importEnv).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(getSchedulerStatus).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('已启用')).toBeInTheDocument();
  });

  it('shows an error when env import succeeds but reload fails', async () => {
    (window as { dsaDesktop?: unknown }).dsaDesktop = { version: '3.12.0' };
    load.mockResolvedValue(false);

    const { container } = render(<SettingsPage />);

    vi.clearAllMocks();
    load.mockResolvedValue(false);

    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();

    fireEvent.change(input as HTMLInputElement, {
      target: {
        files: [new File(['STOCK_LIST=300750\n'], 'desktop-backup.env', { type: 'text/plain' })],
      },
    });

    await waitFor(() => expect(importEnv).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    expect(screen.getByText('配置已导入但刷新失败')).toBeInTheDocument();
    expect(screen.getByText('备份已导入，但重新加载配置失败，请手动重载页面。')).toBeInTheDocument();
    expect(screen.queryByText('已导入 .env 备份并重新加载配置。')).not.toBeInTheDocument();
  });

  it('renders desktop update notice when a newer release is available', async () => {
    desktopGetUpdateState.mockResolvedValue({
      status: 'update-available',
      currentVersion: '3.12.0',
      latestVersion: '3.13.0',
      releaseUrl: 'https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v3.13.0',
      message: '发现新版本 3.13.0，可前往 GitHub Releases 下载更新。',
    });
    (window as { dsaDesktop?: unknown }).dsaDesktop = createDesktopRuntime();

    render(<SettingsPage />);

    expect(await screen.findByText(/发现新版本:当前 3\.12\.0，最新 3\.13\.0/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '前往下载' })).toBeInTheDocument();
  });

  it('checks desktop updates on demand and renders the latest-version state', async () => {
    (window as { dsaDesktop?: unknown }).dsaDesktop = createDesktopRuntime();

    render(<SettingsPage />);

    fireEvent.click(await screen.findByRole('button', { name: '检查更新' }));

    await waitFor(() => expect(desktopCheckForUpdates).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('已是最新版本:当前桌面端已是最新版本。')).toBeInTheDocument();
  });

  it('opens GitHub release page from desktop update notice', async () => {
    desktopGetUpdateState.mockResolvedValue({
      status: 'update-available',
      currentVersion: '3.12.0',
      latestVersion: '3.13.0',
      releaseUrl: 'https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v3.13.0',
      message: '发现新版本 3.13.0，可前往 GitHub Releases 下载更新。',
    });
    (window as { dsaDesktop?: unknown }).dsaDesktop = createDesktopRuntime();

    render(<SettingsPage />);

    fireEvent.click(await screen.findByRole('button', { name: '前往下载' }));

    await waitFor(() => {
      expect(desktopOpenReleasePage).toHaveBeenCalledWith(
        'https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v3.13.0'
      );
    });
  });

  it('renders downloaded desktop update and starts install on demand', async () => {
    desktopGetUpdateState.mockResolvedValue({
      status: 'update-downloaded',
      updateMode: 'auto',
      currentVersion: '3.12.0',
      latestVersion: '3.13.0',
      releaseUrl: 'https://github.com/ZhuLinsen/daily_stock_analysis/releases/tag/v3.13.0',
      message: '新版本 3.13.0 已下载，可重启应用完成安装。',
      downloadPercent: 100,
    });
    (window as { dsaDesktop?: unknown }).dsaDesktop = createDesktopRuntime();

    render(<SettingsPage />);

    expect(await screen.findByText('更新已下载:新版本 3.13.0 已下载，可重启应用完成安装。')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '重启安装' }));

    await waitFor(() => expect(desktopInstallDownloadedUpdate).toHaveBeenCalledTimes(1));
  });
});
