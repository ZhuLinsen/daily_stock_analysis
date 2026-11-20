import { fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SettingsPage from '../SettingsPage';

const { setActiveCategory, useSystemConfigMock } = vi.hoisted(() => ({
  setActiveCategory: vi.fn(),
  useSystemConfigMock: vi.fn(),
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
  LLMChannelEditor: () => <div>llm-editor</div>,
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
});
