import type React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SettingsPage from '../SettingsPage';

const {
  getSetupStatus,
  getSchedulerStatus,
  exportEnv,
  importEnv,
  updateSystemConfig,
  runSchedulerNow,
  analyzeAsync,
  alphasiftEnable,
  alphasiftInstall,
  notifyAlphaSiftConfigChanged,
  notifySystemConfigChanged,
  load,
  save,
  resetDraft,
  setDraftValue,
  setActiveCategory,
  clearToast,
  refreshAfterExternalSave,
  refreshStatus,
  unsavedGuard,
  useAuthMock,
  useSystemConfigMock,
} = vi.hoisted(() => ({
  getSetupStatus: vi.fn(),
  getSchedulerStatus: vi.fn(),
  exportEnv: vi.fn(),
  importEnv: vi.fn(),
  updateSystemConfig: vi.fn(),
  runSchedulerNow: vi.fn(),
  analyzeAsync: vi.fn(),
  alphasiftEnable: vi.fn(),
  alphasiftInstall: vi.fn(),
  notifyAlphaSiftConfigChanged: vi.fn(),
  notifySystemConfigChanged: vi.fn(),
  load: vi.fn(),
  save: vi.fn(),
  resetDraft: vi.fn(),
  setDraftValue: vi.fn(),
  setActiveCategory: vi.fn(),
  clearToast: vi.fn(),
  refreshAfterExternalSave: vi.fn(),
  refreshStatus: vi.fn(),
  unsavedGuard: vi.fn(),
  useAuthMock: vi.fn(),
  useSystemConfigMock: vi.fn(),
}));

vi.mock('../../hooks', () => ({
  useAuth: () => useAuthMock(),
  useSystemConfig: () => useSystemConfigMock(),
  useUnsavedChangesGuard: (isDirty: boolean) => unsavedGuard(isDirty),
}));

vi.mock('../../api/systemConfig', () => ({
  systemConfigApi: {
    getSetupStatus: (...args: unknown[]) => getSetupStatus(...args),
    getSchedulerStatus: (...args: unknown[]) => getSchedulerStatus(...args),
    exportEnv: (...args: unknown[]) => exportEnv(...args),
    importEnv: (...args: unknown[]) => importEnv(...args),
    update: (...args: unknown[]) => updateSystemConfig(...args),
    runSchedulerNow: (...args: unknown[]) => runSchedulerNow(...args),
  },
}));

vi.mock('../../api/analysis', () => ({
  analysisApi: {
    analyzeAsync: (...args: unknown[]) => analyzeAsync(...args),
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

vi.mock('../../components/settings', () => ({
  AuthSettingsCard: () => <div>auth</div>,
  ChangePasswordCard: () => <div>password</div>,
  GenerationBackendStatusPanel: () => <div>backend-status</div>,
  IntelligentImport: () => <div>intelligent-import</div>,
  LLMChannelEditor: () => <div>llm-channel-editor</div>,
  NotificationTestPanel: () => <div>notification-test</div>,
  SettingsCategoryNav: ({
    dirtyCountByCategory,
  }: {
    dirtyCountByCategory?: Record<string, number>;
  }) => (
    <nav data-testid="nav-dirty">{JSON.stringify(dirtyCountByCategory ?? {})}</nav>
  ),
  SettingsAlert: ({ title, message }: { title: string; message: string }) => (
    <div>{title}:{message}</div>
  ),
  SettingsField: ({ item }: { item: { key: string } }) => (
    <div data-testid={`settings-field-${item.key}`}>{item.key}</div>
  ),
  SettingsLoading: () => <div>loading</div>,
  SettingsPanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SettingsSectionCard: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
}));

function buildBaseItem(key: string) {
  return {
    key,
    value: '',
    rawValueExists: true,
    isMasked: false,
    schema: {
      key,
      category: 'base',
      dataType: 'string',
      uiControl: 'text',
      isSensitive: false,
      isRequired: false,
      isEditable: true,
      options: [],
      validation: {},
      displayOrder: 1,
    },
  };
}

function buildScheduleEnabledItem() {
  return {
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
      displayOrder: 1,
    },
  };
}

function buildSystemConfigState(overrides: Record<string, unknown> = {}) {
  return {
    categories: [
      { category: 'base', title: 'Base', description: '', displayOrder: 1, fields: [] },
    ],
    itemsByCategory: {
      base: [buildBaseItem('STOCK_LIST')],
    },
    issueByKey: {},
    activeCategory: 'base',
    setActiveCategory,
    hasDirty: false,
    dirtyKeys: [],
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
    applyPartialUpdate: vi.fn(),
    getChangedItems: () => [],
    refreshAfterExternalSave,
    configVersion: 'v1',
    maskToken: '******',
    ...overrides,
  };
}

describe('SettingsPage unsaved changes bar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    load.mockResolvedValue(true);
    save.mockResolvedValue({ success: true });
    getSetupStatus.mockResolvedValue({
      isComplete: true,
      readyForSmoke: false,
      requiredMissingKeys: [],
      nextStepKey: null,
      checks: [],
    });
    getSchedulerStatus.mockResolvedValue({
      enabled: false,
      running: false,
      scheduleTimes: [],
      nextRunAt: null,
      lastRunAt: null,
      lastSuccessAt: null,
      lastError: null,
    });
    useAuthMock.mockReturnValue({
      authEnabled: true,
      passwordChangeable: true,
      refreshStatus,
    });
    useSystemConfigMock.mockReturnValue(buildSystemConfigState());
    delete (window as { dsaDesktop?: unknown }).dsaDesktop;
  });

  it('hides the sticky unsaved bar when there are no unsaved changes', async () => {
    render(<SettingsPage />);

    await screen.findByTestId('nav-dirty');
    expect(screen.queryByText('有 2 项未保存修改')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '放弃修改' })).not.toBeInTheDocument();
  });

  it('shows the sticky unsaved bar with a change count when drafts exist', async () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      hasDirty: true,
      dirtyKeys: ['STOCK_LIST'],
      dirtyCount: 2,
    }));

    render(<SettingsPage />);

    expect(await screen.findByText('有 2 项未保存修改')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '放弃修改' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '保存配置' })).toBeInTheDocument();
  });

  it('passes per-category dirty counts to the category navigation', async () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      hasDirty: true,
      dirtyKeys: ['STOCK_LIST'],
      dirtyCount: 1,
    }));

    render(<SettingsPage />);

    const nav = await screen.findByTestId('nav-dirty');
    expect(JSON.parse(nav.textContent || '{}')).toEqual({ base: 1 });
  });

  it('discards drafts from the sticky bar without a network reload', async () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      hasDirty: true,
      dirtyKeys: ['STOCK_LIST'],
      dirtyCount: 1,
    }));

    render(<SettingsPage />);

    fireEvent.click(await screen.findByRole('button', { name: '放弃修改' }));

    expect(resetDraft).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledTimes(1); // only the initial mount load
  });

  it('saves drafts from the sticky bar', async () => {
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      hasDirty: true,
      dirtyKeys: ['STOCK_LIST'],
      dirtyCount: 1,
      getChangedItems: () => [{ key: 'STOCK_LIST', value: 'SH600000' }],
    }));

    render(<SettingsPage />);

    fireEvent.click(await screen.findByRole('button', { name: '保存配置' }));

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith([{ key: 'STOCK_LIST', value: 'SH600000' }]);
    expect(notifySystemConfigChanged).toHaveBeenCalledTimes(1);
  });

  it('discards a scheduler-only unsaved state so the bar and guard reset', async () => {
    // Runtime scheduler is disabled; toggling the card creates a runtime/override
    // mismatch that marks the page dirty without any system-config draft change.
    getSchedulerStatus.mockResolvedValue({
      enabled: false,
      running: false,
      scheduleTimes: [],
      nextRunAt: null,
      lastRunAt: null,
      lastSuccessAt: null,
      lastError: null,
    });
    useSystemConfigMock.mockReturnValue(buildSystemConfigState({
      categories: [
        { category: 'system', title: 'System', description: '', displayOrder: 1, fields: [] },
      ],
      activeCategory: 'system',
      itemsByCategory: {
        system: [buildScheduleEnabledItem()],
      },
      // getChangedItems stays empty: SCHEDULE_ENABLED is never written to the draft.
    }));

    render(<SettingsPage />);

    const checkbox = await screen.findByTestId('scheduler-enabled-checkbox');
    expect(screen.queryByRole('button', { name: '放弃修改' })).not.toBeInTheDocument();

    // Enable the scheduler in the UI only -> runtime mismatch -> unsaved bar shows.
    fireEvent.click(checkbox);
    expect(await screen.findByRole('button', { name: '放弃修改' })).toBeInTheDocument();
    expect(unsavedGuard).toHaveBeenLastCalledWith(true);

    // Discarding must clear the scheduler override too, not just the config draft.
    fireEvent.click(screen.getByRole('button', { name: '放弃修改' }));

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '放弃修改' })).not.toBeInTheDocument();
    });
    expect(resetDraft).toHaveBeenCalledTimes(1);
    expect(unsavedGuard).toHaveBeenLastCalledWith(false);
  });
});
