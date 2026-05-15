import type React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resolveWebBuildInfo } from '../../utils/constants';
import SettingsPage from '../SettingsPage';

const {
  exportEnv,
  importEnv,
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
  refreshAfterExternalSave,
  refreshStatus,
  useAuthMock,
  useSystemConfigMock,
  webBuildInfoMock,
} = vi.hoisted(() => ({
  exportEnv: vi.fn(),
  importEnv: vi.fn(),
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
  refreshAfterExternalSave: vi.fn(),
  refreshStatus: vi.fn(),
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
    importEnv: (...args: unknown[]) => importEnv(...args),
  },
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
    onSaved,
  }: {
    onSaved: (items: Array<{ key: string; value: string }>) => void;
  }) => (
    <button
      type="button"
      onClick={() => onSaved([{ key: 'LLM_CHANNELS', value: 'primary,backup' }])}
    >
      save llm channels
    </button>
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
  SettingsField: ({ item }: { item: { key: string } }) => <div>{item.key}</div>,
  SettingsLoading: () => <div>loading</div>,
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
    importEnv.mockResolvedValue({
      success: true,
      configVersion: 'v2',
      appliedCount: 1,
      skippedMaskedCount: 0,
      reloadTriggered: true,
      updatedKeys: ['STOCK_LIST'],
      warnings: [],
    });
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

  it('renders notification test panel before notification fields', () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({ activeCategory: 'notification' }));

    render(<SettingsPage />);

    expect(screen.getByText('通知测试面板:WECHAT_WEBHOOK_URL')).toBeInTheDocument();
    expect(screen.getByText('WECHAT_WEBHOOK_URL')).toBeInTheDocument();
  });

  it('renders env backup actions outside desktop runtime', () => {
    render(<SettingsPage />);

    expect(screen.getByRole('heading', { name: '配置备份' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '导出 .env' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '导入 .env' })).toBeInTheDocument();
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
