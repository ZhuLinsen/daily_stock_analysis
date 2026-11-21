import { act, fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SettingsPage from '../SettingsPage';

const { setActiveCategory, useSystemConfigMock, llmUnmountSpy } = vi.hoisted(() => ({
  setActiveCategory: vi.fn(),
  useSystemConfigMock: vi.fn(),
  llmUnmountSpy: vi.fn(),
}));

vi.mock('../../hooks', async () => {
  const actual = await vi.importActual<typeof import('../../hooks')>('../../hooks');
  return {
    ...actual,
    useAuth: () => ({ authEnabled: false, passwordChangeable: false }),
    useSystemConfig: () => useSystemConfigMock(),
  };
});

vi.mock('../../api/systemConfig', () => ({
  systemConfigApi: {
    exportEnv: vi.fn(),
    getSchedulerStatus: vi.fn().mockResolvedValue({ enabled: false, running: false }),
    getSetupStatus: vi.fn().mockResolvedValue({ isComplete: true, readyForSmoke: true, checks: [] }),
    importEnv: vi.fn(),
    runSchedulerNow: vi.fn(),
    update: vi.fn(),
  },
}));

vi.mock('../../components/settings', () => ({
  AuthSettingsCard: () => <div>auth</div>,
  ChangePasswordCard: () => <div>password</div>,
  IntelligentImport: () => <div>import</div>,
  LLMChannelEditor: ({ onDirtyChange }: { onDirtyChange?: (dirty: boolean) => void }) => {
    const [baseUrl, setBaseUrl] = useState('https://saved.example/v1');
    useEffect(() => {
      return () => {
        llmUnmountSpy();
        onDirtyChange?.(false);
      };
    }, [onDirtyChange]);
    return (
      <div>
        <input
          aria-label="Mock Channel Base URL"
          value={baseUrl}
          onChange={(event) => {
            setBaseUrl(event.target.value);
            onDirtyChange?.(true);
          }}
        />
      </div>
    );
  },
  GenerationBackendStatusPanel: () => <div>gen-status</div>,
  AgentBackendStatusPanel: () => <div>agent-status</div>,
  NotificationTestPanel: () => <div>notify-test</div>,
  SettingsAlert: ({ title, message }: { title: string; message: string }) => <div>{title}:{message}</div>,
  SettingsCategoryNav: ({ categories, onSelect }: { categories: Array<{ category: string; title: string }>; onSelect: (c: string) => void }) => (
    <nav>
      {categories.map((cat) => (
        <button key={cat.category} type="button" onClick={() => onSelect(cat.category)}>
          {cat.title}
        </button>
      ))}
    </nav>
  ),
  SettingsField: ({ item }: { item: { key: string } }) => <div data-testid={`field-${item.key}`}>{item.key}</div>,
  SettingsLoading: () => <div>loading</div>,
  SettingsPanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SettingsSectionCard: ({ title, children }: { title: string; children: React.ReactNode }) => (
    <section>
      <h2>{title}</h2>
      {children}
    </section>
  ),
}));

function makeItem(key: string, category: string, description = '') {
  return {
    key,
    value: '',
    rawValueExists: false,
    isMasked: false,
    schema: {
      key,
      category,
      title: key,
      description,
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

describe('SettingsPage search and essential mode', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSystemConfigMock.mockReturnValue({
      categories: [
        { category: 'base', title: 'Base', description: '基础配置', displayOrder: 1, fields: [] },
        { category: 'notification', title: 'Notification', description: '通知配置', displayOrder: 2, fields: [] },
      ],
      itemsByCategory: {
        base: [
          makeItem('STOCK_LIST', 'base', '自选股列表'),
          makeItem('LONGBRIDGE_STATIC_INFO_TTL_SECONDS', 'base', '长桥静态缓存秒数'),
        ],
        notification: [
          makeItem('FEISHU_WEBHOOK_URL', 'notification', '飞书群机器人推送地址'),
        ],
      },
      issueByKey: {},
      activeCategory: 'base',
      setActiveCategory,
      hasDirty: false,
      dirtyCount: 0,
      toast: null,
      clearToast: vi.fn(),
      isLoading: false,
      isSaving: false,
      loadError: null,
      saveError: null,
      retryAction: null,
      load: vi.fn().mockResolvedValue(true),
      retry: vi.fn(),
      save: vi.fn(),
      resetDraft: vi.fn(),
      setDraftValue: vi.fn(),
      getChangedItems: () => [],
      refreshAfterExternalSave: vi.fn(),
      configVersion: 'v1',
      maskToken: '***',
      llmModelProviders: [],
    });
  });

  it('filters settings across categories via search and supports essential-only mode toggle', () => {
    const router = createMemoryRouter([{ path: '/settings', element: <SettingsPage /> }], {
      initialEntries: ['/settings'],
    });
    render(<RouterProvider router={router} />);

    expect(screen.getByTestId('field-STOCK_LIST')).toBeInTheDocument();
    expect(screen.getByTestId('field-LONGBRIDGE_STATIC_INFO_TTL_SECONDS')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '精简模式（核心项）' }));
    expect(screen.getByTestId('field-STOCK_LIST')).toBeInTheDocument();
    expect(screen.queryByTestId('field-LONGBRIDGE_STATIC_INFO_TTL_SECONDS')).not.toBeInTheDocument();

    const searchInput = screen.getByRole('searchbox');
    fireEvent.change(searchInput, { target: { value: 'FEISHU' } });
    expect(screen.getByText('搜索结果（1 项）')).toBeInTheDocument();
    expect(screen.getByTestId('field-FEISHU_WEBHOOK_URL')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '前往分类' }));
    expect(setActiveCategory).toHaveBeenCalledWith('notification');
  });

  it('finds localized Chinese fields like 飞书 even when schema title and description are English, and hides channel-managed LLM fields from search', () => {
    useSystemConfigMock.mockReturnValue({
      categories: [
        { category: 'base', title: 'Base', description: '基础配置', displayOrder: 1, fields: [] },
        { category: 'ai_model', title: 'AI Model', description: '模型配置', displayOrder: 2, fields: [] },
        { category: 'notification', title: 'Notification', description: '通知配置', displayOrder: 3, fields: [] },
      ],
      itemsByCategory: {
        base: [makeItem('STOCK_LIST', 'base', 'Comma separated tickers')],
        ai_model: [
          { ...makeItem('LLM_CHANNELS', 'ai_model', 'Channel names'), value: 'text,vision' },
          makeItem('VISION_MODEL', 'ai_model', 'Vision model'),
          { ...makeItem('LITELLM_CONFIG', 'ai_model', 'LiteLLM config'), value: '/missing/litellm.yaml' },
        ],
        notification: [makeItem('FEISHU_WEBHOOK_URL', 'notification', 'Feishu Webhook URL')],
      },
      issueByKey: {},
      activeCategory: 'base',
      setActiveCategory,
      hasDirty: false,
      dirtyCount: 0,
      toast: null,
      clearToast: vi.fn(),
      isLoading: false,
      isSaving: false,
      loadError: null,
      saveError: null,
      retryAction: null,
      load: vi.fn().mockResolvedValue(true),
      retry: vi.fn(),
      save: vi.fn(),
      resetDraft: vi.fn(),
      setDraftValue: vi.fn(),
      getChangedItems: () => [],
      refreshAfterExternalSave: vi.fn(),
      configVersion: 'v1',
      maskToken: '***',
      llmModelProviders: [],
    });

    const router = createMemoryRouter([{ path: '/settings', element: <SettingsPage /> }], {
      initialEntries: ['/settings'],
    });
    render(<RouterProvider router={router} />);

    const searchInput = screen.getByRole('searchbox');
    fireEvent.change(searchInput, { target: { value: '飞书' } });
    expect(screen.getByTestId('field-FEISHU_WEBHOOK_URL')).toBeInTheDocument();

    fireEvent.change(searchInput, { target: { value: 'LLM_CHANNELS' } });
    expect(screen.queryByTestId('field-LLM_CHANNELS')).not.toBeInTheDocument();

    fireEvent.change(searchInput, { target: { value: 'VISION_MODEL' } });
    expect(screen.queryByTestId('field-VISION_MODEL')).not.toBeInTheDocument();
  });

  it('keeps runtime model fields editable when a YAML config is present alongside fallback channels', () => {
    useSystemConfigMock.mockReturnValue({
      categories: [
        { category: 'ai_model', title: 'AI Model', description: '模型配置', displayOrder: 1, fields: [] },
      ],
      itemsByCategory: {
        ai_model: [
          { ...makeItem('LLM_CHANNELS', 'ai_model'), value: 'fallback', rawValueExists: true },
          { ...makeItem('LITELLM_CONFIG', 'ai_model'), value: '/etc/dsa/litellm.yaml', rawValueExists: true },
          { ...makeItem('VISION_MODEL', 'ai_model'), value: 'openai/vision', rawValueExists: true },
          { ...makeItem('LITELLM_MODEL', 'ai_model'), value: 'openai/chat', rawValueExists: true },
        ],
      },
      issueByKey: {},
      activeCategory: 'ai_model',
      setActiveCategory,
      hasDirty: false,
      dirtyCount: 0,
      toast: null,
      clearToast: vi.fn(),
      isLoading: false,
      isSaving: false,
      loadError: null,
      saveError: null,
      retryAction: null,
      load: vi.fn().mockResolvedValue(true),
      retry: vi.fn(),
      save: vi.fn(),
      resetDraft: vi.fn(),
      setDraftValue: vi.fn(),
      getChangedItems: () => [],
      refreshAfterExternalSave: vi.fn(),
      configVersion: 'v1',
      maskToken: '***',
      llmModelProviders: [],
    });

    const router = createMemoryRouter([{ path: '/settings', element: <SettingsPage /> }], {
      initialEntries: ['/settings'],
    });
    render(<RouterProvider router={router} />);

    expect(screen.getByTestId('field-VISION_MODEL')).toBeInTheDocument();
    expect(screen.getByTestId('field-LITELLM_MODEL')).toBeInTheDocument();
    expect(screen.queryByTestId('field-LLM_CHANNELS')).not.toBeInTheDocument();
  });

  it('keeps runtime model fields editable when YAML and fallback channels come from the process environment', () => {
    useSystemConfigMock.mockReturnValue({
      categories: [
        { category: 'ai_model', title: 'AI Model', description: '模型配置', displayOrder: 1, fields: [] },
      ],
      itemsByCategory: {
        ai_model: [
          { ...makeItem('LLM_CHANNELS', 'ai_model'), value: 'fallback', rawValueExists: false },
          { ...makeItem('LITELLM_CONFIG', 'ai_model'), value: '/etc/dsa/litellm.yaml', rawValueExists: false },
          { ...makeItem('VISION_MODEL', 'ai_model'), value: 'openai/vision', rawValueExists: false },
          { ...makeItem('LITELLM_MODEL', 'ai_model'), value: 'openai/chat', rawValueExists: false },
        ],
      },
      issueByKey: {},
      activeCategory: 'ai_model',
      setActiveCategory,
      hasDirty: false,
      dirtyCount: 0,
      toast: null,
      clearToast: vi.fn(),
      isLoading: false,
      isSaving: false,
      loadError: null,
      saveError: null,
      retryAction: null,
      load: vi.fn().mockResolvedValue(true),
      retry: vi.fn(),
      save: vi.fn(),
      resetDraft: vi.fn(),
      setDraftValue: vi.fn(),
      getChangedItems: () => [],
      refreshAfterExternalSave: vi.fn(),
      configVersion: 'v1',
      maskToken: '***',
      llmYamlActive: true,
      llmModelProviders: [],
    });

    const router = createMemoryRouter([{ path: '/settings', element: <SettingsPage /> }], {
      initialEntries: ['/settings'],
    });
    render(<RouterProvider router={router} />);

    expect(screen.getByTestId('field-VISION_MODEL')).toBeInTheDocument();
    expect(screen.getByTestId('field-LITELLM_MODEL')).toBeInTheDocument();
    expect(screen.queryByTestId('field-LLM_CHANNELS')).not.toBeInTheDocument();
  });

  it('keeps stateful LLMChannelEditor and SchedulerSettingsCard mounted across search and applies ?category= deep link only once per navigation', () => {
    let currentCategory = 'base';
    let stockListValue = '600519';
    const bridge: { trigger: () => void } = { trigger: () => {} };
    const forceRerender = () => {
      act(() => {
        bridge.trigger();
      });
    };
    const SettingsTestHarness = () => {
      const [, setTick] = useState(0);
      useEffect(() => {
        bridge.trigger = () => setTick((tick) => tick + 1);
        return () => {
          bridge.trigger = () => {};
        };
      }, []);
      return <SettingsPage />;
    };
    const setDraftValueMock = vi.fn((key: string, value: string) => {
      if (key === 'STOCK_LIST') {
        stockListValue = value;
      }
    });
    const setActiveCategoryMock = vi.fn((next: string) => {
      currentCategory = next;
      forceRerender();
    });

    const buildConfigState = () => ({
      categories: [
        { category: 'base', title: 'Base', description: '基础配置', displayOrder: 1, fields: [] },
        { category: 'ai_model', title: 'AI Model', description: '模型配置', displayOrder: 2, fields: [] },
        { category: 'system', title: 'System', description: '系统配置', displayOrder: 3, fields: [] },
        { category: 'notification', title: 'Notification', description: '通知配置', displayOrder: 4, fields: [] },
      ],
      itemsByCategory: {
        base: [{ ...makeItem('STOCK_LIST', 'base', 'Stocks'), value: stockListValue }],
        ai_model: [makeItem('LITELLM_CONFIG', 'ai_model', 'Config')],
        system: [
          { ...makeItem('SCHEDULE_ENABLED', 'system', 'Schedule'), value: 'false' },
          { ...makeItem('SCHEDULE_TIME', 'system', 'Time'), value: '18:00' },
        ],
        notification: [makeItem('FEISHU_WEBHOOK_URL', 'notification', 'Feishu')],
      },
      issueByKey: {},
      activeCategory: currentCategory,
      setActiveCategory: setActiveCategoryMock,
      hasDirty: false,
      dirtyCount: 0,
      toast: null,
      clearToast: vi.fn(),
      isLoading: false,
      isSaving: false,
      loadError: null,
      saveError: null,
      retryAction: null,
      load: vi.fn().mockResolvedValue(true),
      retry: vi.fn(),
      save: vi.fn(),
      resetDraft: vi.fn(),
      setDraftValue: setDraftValueMock,
      getChangedItems: () => [],
      refreshAfterExternalSave: vi.fn(),
      configVersion: 'v1',
      maskToken: '***',
      llmModelProviders: [],
    });

    useSystemConfigMock.mockImplementation(buildConfigState);

    const router = createMemoryRouter([{ path: '/settings', element: <SettingsTestHarness /> }], {
      initialEntries: ['/settings?category=ai_model'],
    });
    render(<RouterProvider router={router} />);

    expect(setActiveCategoryMock).toHaveBeenCalledWith('ai_model');
    // Child effects run before parent SettingsTestHarness registers bridge.trigger, so trigger one rerender now.
    forceRerender();

    const baseUrlInput = screen.getByLabelText('Mock Channel Base URL') as HTMLInputElement;
    fireEvent.change(baseUrlInput, { target: { value: 'https://draft.example/v1' } });
    expect(baseUrlInput.value).toBe('https://draft.example/v1');

    const searchInput = screen.getByRole('searchbox');
    fireEvent.change(searchInput, { target: { value: 'FEISHU' } });
    expect(llmUnmountSpy).not.toHaveBeenCalled();

    fireEvent.change(searchInput, { target: { value: '' } });
    expect((screen.getByLabelText('Mock Channel Base URL') as HTMLInputElement).value).toBe('https://draft.example/v1');

    fireEvent.change(searchInput, { target: { value: 'STOCK_LIST' } });
    fireEvent.click(screen.getByRole('button', { name: '前往分类' }));
    expect(currentCategory).toBe('base');

    // Simulate draft update rebuilding categories array; must stay on 'base' instead of snapping back to ?category=ai_model.
    setActiveCategoryMock.mockClear();
    stockListValue = '600519,AAPL';
    forceRerender();
    expect(setActiveCategoryMock).not.toHaveBeenCalledWith('ai_model');
    expect(currentCategory).toBe('base');

    // Switch to system and toggle scheduler checkbox across search.
    currentCategory = 'system';
    forceRerender();
    const schedulerCheckbox = screen.getByTestId('scheduler-enabled-checkbox') as HTMLInputElement;
    fireEvent.click(schedulerCheckbox);
    expect(schedulerCheckbox.checked).toBe(true);
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'FEISHU' } });
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '' } });
    expect((screen.getByTestId('scheduler-enabled-checkbox') as HTMLInputElement).checked).toBe(true);
  });
});
