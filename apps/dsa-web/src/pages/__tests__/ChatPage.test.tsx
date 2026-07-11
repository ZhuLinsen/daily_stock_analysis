import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { createParsedApiError } from '../../api/error';
import { historyApi } from '../../api/history';
import type { Message, ProgressStep } from '../../stores/agentChatStore';
import ChatPage from '../ChatPage';
import { extractStockCodeFromMessage, extractStockCodesFromMessage } from '../../utils/chatStockCode';

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const {
  mockGetSkills,
  mockDeleteChatSession,
  mockSendChat,
  mockGetSystemConfig,
  mockUpdateSystemConfig,
  mockGetWatchlist,
  mockAddToWatchlist,
  mockRemoveFromWatchlist,
  mockDownloadSession,
  mockFormatSessionAsMarkdown,
} = vi.hoisted(() => ({
  mockGetSkills: vi.fn(),
  mockDeleteChatSession: vi.fn(),
  mockSendChat: vi.fn(),
  mockGetSystemConfig: vi.fn(),
  mockUpdateSystemConfig: vi.fn(),
  mockGetWatchlist: vi.fn(),
  mockAddToWatchlist: vi.fn(),
  mockRemoveFromWatchlist: vi.fn(),
  mockDownloadSession: vi.fn(),
  mockFormatSessionAsMarkdown: vi.fn(),
}));

const mockLoadSessions = vi.fn();
const mockLoadInitialSession = vi.fn();
const mockSwitchSession = vi.fn();
const mockStartStream = vi.fn();
const mockClearCompletionBadge = vi.fn();
const mockStartNewChat = vi.fn();

const mockStoreState = {
  messages: [] as Message[],
  loading: false,
  progressSteps: [] as ProgressStep[],
  sessionId: 'session-1',
  sessions: [
    {
      session_id: 'session-1',
      title: '请简要分析 600519',
      message_count: 2,
      created_at: '2026-03-15T09:00:00Z',
      last_active: '2026-03-15T09:05:00Z',
    },
  ],
  sessionsLoading: false,
  chatError: null,
  loadSessions: mockLoadSessions,
  loadInitialSession: mockLoadInitialSession,
  switchSession: mockSwitchSession,
  startStream: mockStartStream,
  clearCompletionBadge: mockClearCompletionBadge,
};

vi.mock('../../api/agent', () => ({
  agentApi: {
    getSkills: mockGetSkills,
    deleteChatSession: mockDeleteChatSession,
    sendChat: mockSendChat,
  },
}));

vi.mock('../../api/systemConfig', () => ({
  systemConfigApi: {
    getConfig: mockGetSystemConfig,
    update: mockUpdateSystemConfig,
    getWatchlist: mockGetWatchlist,
    addToWatchlist: mockAddToWatchlist,
    removeFromWatchlist: mockRemoveFromWatchlist,
  },
}));

vi.mock('../../utils/chatExport', () => ({
  downloadSession: mockDownloadSession,
  formatSessionAsMarkdown: mockFormatSessionAsMarkdown,
}));

vi.mock('../../api/history', () => ({
  historyApi: {
    getDetail: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock('../../stores/agentChatStore', () => {
  const useAgentChatStore = (
    selector?: (state: typeof mockStoreState) => unknown
  ) => (typeof selector === 'function' ? selector(mockStoreState) : mockStoreState);

  useAgentChatStore.getState = () => ({
    startNewChat: mockStartNewChat,
  });

  return { useAgentChatStore };
});

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: query === '(prefers-color-scheme: dark)',
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  Object.defineProperty(window, 'requestAnimationFrame', {
    writable: true,
    value: (callback: FrameRequestCallback) => window.setTimeout(() => callback(0), 0),
  });

  Object.defineProperty(window, 'cancelAnimationFrame', {
    writable: true,
    value: (handle: number) => window.clearTimeout(handle),
  });

  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    writable: true,
    value: vi.fn(),
  });
});

beforeEach(() => {
  vi.clearAllMocks();
  mockStoreState.messages = [];
  mockStoreState.loading = false;
  mockStoreState.progressSteps = [];
  mockStoreState.chatError = null;
  mockStoreState.sessionsLoading = false;
  mockStoreState.sessionId = 'session-1';
  mockStoreState.sessions = [
    {
      session_id: 'session-1',
      title: '请简要分析 600519',
      message_count: 2,
      created_at: '2026-03-15T09:00:00Z',
      last_active: '2026-03-15T09:05:00Z',
    },
  ];
  mockGetSkills.mockResolvedValue({
    skills: [
      { id: 'bull_trend', name: '趋势分析', description: '测试技能' },
    ],
    default_skill_id: 'bull_trend',
  });
  mockDeleteChatSession.mockResolvedValue(undefined);
  mockSendChat.mockResolvedValue({ success: true });
  mockGetWatchlist.mockResolvedValue([]);
  mockGetSystemConfig.mockResolvedValue({
    configVersion: 'cfg-v1',
    maskToken: 'mask-token',
    items: [
      {
        key: 'AGENT_CONTEXT_COMPRESSION_ENABLED',
        value: 'false',
        rawValueExists: true,
        isMasked: false,
      },
    ],
  });
  mockUpdateSystemConfig.mockResolvedValue({
    success: true,
    configVersion: 'cfg-v2',
    appliedCount: 1,
    skippedMaskedCount: 0,
    reloadTriggered: true,
    updatedKeys: ['AGENT_CONTEXT_COMPRESSION_ENABLED'],
    warnings: [],
  });
  mockDownloadSession.mockImplementation(() => {});
  mockFormatSessionAsMarkdown.mockReturnValue('# exported session');
});

describe('ChatPage', () => {
  it('renders a fixed workspace shell with independent session and message viewports', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByTestId('chat-workspace')).toBeInTheDocument();
    expect(screen.getByTestId('chat-session-list-scroll')).toBeInTheDocument();
    expect(screen.getByTestId('chat-message-scroll')).toBeInTheDocument();
    expect(mockLoadInitialSession).toHaveBeenCalled();
    expect(mockClearCompletionBadge).toHaveBeenCalled();
  });

  it('loads and saves the global context compression setting from the chat input area', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const compressionToggle = await screen.findByRole('checkbox', { name: /上下文压缩/ });

    await waitFor(() => {
      expect(compressionToggle).not.toBeDisabled();
    });

    expect(compressionToggle).not.toBeChecked();

    fireEvent.click(compressionToggle);

    await waitFor(() => {
      expect(mockUpdateSystemConfig).toHaveBeenCalledWith({
        configVersion: 'cfg-v1',
        maskToken: 'mask-token',
        reloadNow: true,
        items: [
          {
            key: 'AGENT_CONTEXT_COMPRESSION_ENABLED',
            value: 'true',
          },
        ],
      });
    });

    expect(compressionToggle).toBeChecked();
    expect(screen.getByText('已启用')).toBeInTheDocument();
  });

  it('rolls back the context compression switch when saving fails', async () => {
    mockGetSystemConfig.mockResolvedValue({
      configVersion: 'cfg-v1',
      maskToken: 'mask-token',
      items: [
        {
          key: 'AGENT_CONTEXT_COMPRESSION_ENABLED',
          value: 'true',
          rawValueExists: true,
          isMasked: false,
        },
      ],
    });
    mockUpdateSystemConfig.mockRejectedValue(
      createParsedApiError({
        title: '保存失败',
        message: '配置服务不可用',
        category: 'unknown',
      }),
    );

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const compressionToggle = await screen.findByRole('checkbox', { name: /上下文压缩/ });

    await waitFor(() => {
      expect(compressionToggle).toBeChecked();
      expect(compressionToggle).not.toBeDisabled();
    });

    fireEvent.click(compressionToggle);

    await waitFor(() => {
      expect(mockUpdateSystemConfig).toHaveBeenCalledWith(expect.objectContaining({
        items: [
          {
            key: 'AGENT_CONTEXT_COMPRESSION_ENABLED',
            value: 'false',
          },
        ],
      }));
      expect(compressionToggle).toBeChecked();
    });
    expect(screen.getByText('配置服务不可用')).toBeInTheDocument();
  });

  it('does not switch when clicking the current session card', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const sessionCard = await screen.findByRole('button', {
      name: /切换到对话 请简要分析 600519/,
    });

    fireEvent.click(sessionCard);
    expect(mockSwitchSession).not.toHaveBeenCalled();
    expect(sessionCard).toHaveAttribute('aria-current', 'page');
  });

  it('renders a separate delete button for each session and opens confirmation without switching', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const deleteButton = await screen.findByRole('button', {
      name: /删除对话 请简要分析 600519/,
    });

    fireEvent.click(deleteButton);

    expect(mockSwitchSession).not.toHaveBeenCalled();
    expect(await screen.findByText('删除后，该对话将不可恢复，确认删除吗？')).toBeInTheDocument();
  });

  it('hides header actions when there are no messages', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByRole('heading', { name: '问股' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '导出会话' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '发送到已配置的通知机器人/邮箱' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '历史对话' })).toBeInTheDocument();
  });

  it('exports the current session from the header action', async () => {
    mockStoreState.messages = [
      { id: 'user-1', role: 'user', content: '请分析 600519' },
      { id: 'assistant-1', role: 'assistant', content: '趋势偏强', skillName: '趋势分析' },
    ];

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: '导出会话为 Markdown 文件' }));

    expect(mockDownloadSession).toHaveBeenCalledWith(mockStoreState.messages);
    expect(mockFormatSessionAsMarkdown).not.toHaveBeenCalled();
  });

  it('renders assistant skill labels with shared badge semantics', async () => {
    mockStoreState.messages = [
      { id: 'assistant-1', role: 'assistant', content: '趋势偏强', skillName: '趋势分析' },
    ];

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const skillBadge = await screen.findByLabelText('技能 趋势分析');
    expect(skillBadge).toBeInTheDocument();
    expect(skillBadge).toHaveTextContent('趋势分析');
  });

  it('renders assistant multi-skill labels with shared badge semantics', async () => {
    mockStoreState.messages = [
      {
        id: 'assistant-1',
        role: 'assistant',
        content: '趋势偏强',
        skills: ['bull_trend', 'ma_golden_cross'],
        skillNames: ['趋势分析', '均线金叉'],
      },
    ];

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const skillBadge = await screen.findByLabelText('技能 趋势分析、均线金叉');
    expect(skillBadge).toBeInTheDocument();
    expect(skillBadge).toHaveTextContent('趋势分析、均线金叉');
  });

  it('renders failed stage_done progress as a non-success state', async () => {
    mockStoreState.loading = true;
    mockStoreState.progressSteps = [
      { type: 'stage_done', stage: 'risk', status: 'failed' },
    ];
    mockStoreState.messages = [
      {
        id: 'assistant-1',
        role: 'assistant',
        content: 'Partial answer',
        thinkingSteps: [
          { type: 'stage_done', stage: 'risk', status: 'failed' },
        ],
      },
    ];

    const { container } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findAllByText('risk failed')).toHaveLength(1);

    const thinkingToggle = container.querySelector('button[class*="mb-2"][class*="w-full"]') as HTMLButtonElement;
    fireEvent.click(thinkingToggle);

    const failedStage = screen.getAllByText('risk failed').find((node) =>
      node.closest('.chat-progress-item'),
    );
    expect(failedStage).toBeDefined();
    expect(failedStage?.closest('.chat-progress-item')).toHaveClass('chat-progress-item-danger');
    expect(failedStage?.closest('.chat-progress-item')).not.toHaveClass('chat-progress-item-success');
  });

  it('renders pipeline budget skip progress without timeout severity', async () => {
    mockStoreState.loading = true;
    mockStoreState.progressSteps = [
      { type: 'pipeline_budget_skipped', stage: 'decision' },
    ];
    mockStoreState.messages = [
      {
        id: 'assistant-1',
        role: 'assistant',
        content: 'Partial answer',
        thinkingSteps: [
          { type: 'pipeline_budget_skipped', stage: 'decision' },
        ],
      },
    ];

    const { container } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findAllByText('decision skipped: insufficient budget')).toHaveLength(1);
    expect(screen.queryByText('decision timed out')).not.toBeInTheDocument();

    const thinkingToggle = container.querySelector('button[class*="mb-2"][class*="w-full"]') as HTMLButtonElement;
    fireEvent.click(thinkingToggle);

    const budgetSkipped = screen.getAllByText('decision skipped: insufficient budget').find((node) =>
      node.closest('.chat-progress-item'),
    );
    expect(budgetSkipped).toBeDefined();
    expect(budgetSkipped?.closest('.chat-progress-item')).toHaveClass('chat-progress-item-muted');
    expect(budgetSkipped?.closest('.chat-progress-item')).not.toHaveClass('chat-progress-item-danger');
  });

  it('selects the default skill after loading skills', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByRole('checkbox', { name: '趋势分析' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: '通用分析' })).not.toBeChecked();
  });

  it('sends multiple selected skills in order', async () => {
    mockGetSkills.mockResolvedValue({
      skills: [
        { id: 'bull_trend', name: '趋势分析', description: '默认趋势' },
        { id: 'ma_golden_cross', name: '均线金叉', description: '均线交叉' },
      ],
      default_skill_id: 'bull_trend',
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('checkbox', { name: '均线金叉' }));
    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '分析 600519' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '分析 600519',
          skills: ['bull_trend', 'ma_golden_cross'],
        }),
        expect.objectContaining({
          skillNames: ['趋势分析', '均线金叉'],
          skillName: '趋势分析、均线金叉',
        }),
      );
    });
  });

  it('collapses the mobile skill picker by default and keeps selected skills when sending', async () => {
    mockGetSkills.mockResolvedValue({
      skills: [
        { id: 'bull_trend', name: '趋势分析', description: '默认趋势' },
        { id: 'ma_golden_cross', name: '均线金叉', description: '均线交叉' },
      ],
      default_skill_id: 'bull_trend',
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const mobileToggle = await screen.findByRole('button', { name: '展开策略选择' });
    const skillPanel = screen.getByTestId('chat-skill-picker-panel');
    expect(mobileToggle).toHaveAttribute('aria-expanded', 'false');
    expect(skillPanel).toHaveClass('hidden');

    fireEvent.click(mobileToggle);

    expect(screen.getByRole('button', { name: '收起策略选择' })).toHaveAttribute('aria-expanded', 'true');
    expect(skillPanel).not.toHaveClass('hidden');
    expect(skillPanel).toHaveClass('flex');

    fireEvent.click(screen.getByRole('checkbox', { name: '均线金叉' }));
    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '分析 600519' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '分析 600519',
          skills: ['bull_trend', 'ma_golden_cross'],
        }),
        expect.objectContaining({
          skillName: '趋势分析、均线金叉',
        }),
      );
    });

    expect(screen.getByRole('button', { name: '展开策略选择' })).toHaveAttribute('aria-expanded', 'false');
    expect(skillPanel).toHaveClass('hidden');
  });

  it('omits skills when all concrete skills are cleared', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('checkbox', { name: '趋势分析' }));
    expect(screen.getByRole('checkbox', { name: '通用分析' })).toBeChecked();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '分析 AAPL' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalled();
    });
    const lastCall = mockStartStream.mock.calls[mockStartStream.mock.calls.length - 1];
    expect(lastCall[0]).toEqual(expect.objectContaining({ message: '分析 AAPL' }));
    expect(lastCall[0]).not.toHaveProperty('skills');
    expect(lastCall[1]).toEqual(expect.objectContaining({
      skillNames: ['通用'],
      skillName: '通用',
    }));
  });

  it('caps concrete skill selection at three and re-enables choices after unselecting', async () => {
    mockGetSkills.mockResolvedValue({
      skills: [
        { id: 'bull_trend', name: '趋势分析', description: '默认趋势' },
        { id: 'ma_golden_cross', name: '均线金叉', description: '均线交叉' },
        { id: 'chan_theory', name: '缠论', description: '结构分析' },
        { id: 'wave_theory', name: '波浪理论', description: '波浪分析' },
      ],
      default_skill_id: 'bull_trend',
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('checkbox', { name: '均线金叉' }));
    fireEvent.click(screen.getByRole('checkbox', { name: '缠论' }));

    const wave = screen.getByRole('checkbox', { name: '波浪理论' });
    expect(wave).toBeDisabled();

    fireEvent.click(screen.getByRole('checkbox', { name: '均线金叉' }));
    expect(wave).not.toBeDisabled();
  });

  it('quick questions override the current multi-skill selection', async () => {
    mockGetSkills.mockResolvedValue({
      skills: [
        { id: 'bull_trend', name: '趋势分析', description: '默认趋势' },
        { id: 'ma_golden_cross', name: '均线金叉', description: '均线交叉' },
        { id: 'chan_theory', name: '缠论', description: '结构分析' },
      ],
      default_skill_id: 'bull_trend',
    });

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('checkbox', { name: '均线金叉' }));
    fireEvent.click(screen.getByRole('button', { name: '用缠论分析茅台' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '用缠论分析茅台',
          skills: ['chan_theory'],
        }),
        expect.objectContaining({
          skillNames: ['缠论'],
          skillName: '缠论',
        }),
      );
    });
  });

  it('keeps assistant message actions directly activatable in the DOM', async () => {
    mockStoreState.messages = [
      { id: 'assistant-1', role: 'assistant', content: '趋势偏强', skillName: '趋势分析' },
    ];

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const exportButton = await screen.findByRole('button', { name: '导出此条消息为 Markdown' });
    const actionGroup = exportButton.parentElement;

    expect(actionGroup).toHaveClass('chat-message-actions');
    expect(actionGroup?.className).not.toMatch(/pointer-events-none|opacity-0/);
  });

  it('sends exported markdown to notification channel and shows success feedback', async () => {
    mockStoreState.messages = [
      { id: 'user-1', role: 'user', content: '请分析 600519' },
      { id: 'assistant-1', role: 'assistant', content: '趋势偏强', skillName: '趋势分析' },
    ];
    mockFormatSessionAsMarkdown.mockReturnValue('# exported markdown');

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: '发送到已配置的通知机器人/邮箱' }));

    await waitFor(() => {
      expect(mockFormatSessionAsMarkdown).toHaveBeenCalledWith(mockStoreState.messages);
      expect(mockSendChat).toHaveBeenCalledWith('# exported markdown');
    });

    expect(await screen.findByText('已发送到通知渠道')).toBeInTheDocument();
  });

  it('shows parsed error feedback when notification delivery fails', async () => {
    mockStoreState.messages = [
      { id: 'user-1', role: 'user', content: '请分析 AAPL' },
      { id: 'assistant-1', role: 'assistant', content: '短线震荡', skillName: '趋势分析' },
    ];
    mockSendChat.mockRejectedValue(
      createParsedApiError({
        title: '发送失败',
        message: '通知渠道不可用',
        category: 'unknown',
      }),
    );

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByRole('button', { name: '发送到已配置的通知机器人/邮箱' }));

    expect(await screen.findByText('通知渠道不可用')).toBeInTheDocument();
  });

  it('prevents duplicate notification sends while the request is in flight', async () => {
    mockStoreState.messages = [
      { id: 'user-1', role: 'user', content: '请分析 TSLA' },
      { id: 'assistant-1', role: 'assistant', content: '波动较大', skillName: '趋势分析' },
    ];
    const deferred = createDeferred<{ success: boolean }>();
    mockSendChat.mockImplementation(() => deferred.promise);

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const sendButton = await screen.findByRole('button', { name: '发送到已配置的通知机器人/邮箱' });
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(mockSendChat).toHaveBeenCalledTimes(1);
      expect(sendButton).toBeDisabled();
    });

    fireEvent.click(sendButton);
    expect(mockSendChat).toHaveBeenCalledTimes(1);

    deferred.resolve({ success: true });

    await waitFor(() => {
      expect(sendButton).not.toBeDisabled();
    });
  });

  it('allows sending with base follow-up context before report hydration completes', async () => {
    const deferred = createDeferred<Awaited<ReturnType<typeof historyApi.getDetail>>>();

    vi.mocked(historyApi.getDetail).mockImplementation(() => deferred.promise);

    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0&recordId=1']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();

    const sendButton = screen.getByRole('button', { name: /发送|处理中\.\.\./ });
    expect(sendButton).not.toBeDisabled();
    expect(screen.getByText('正在加载历史分析上下文；现在可直接发送追问。')).toBeInTheDocument();

    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '请深入分析 贵州茅台(600519)',
          context: {
            stock_code: '600519',
            stock_name: '贵州茅台',
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });

    deferred.resolve({
      meta: {
        id: 1,
        queryId: 'q-1',
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        createdAt: '2026-03-18T08:00:00Z',
        currentPrice: 1523.6,
        changePct: 1.8,
      },
      summary: {
        analysisSummary: '趋势延续',
        operationAdvice: '继续观察',
        trendPrediction: '高位震荡',
        sentimentScore: 78,
      },
      strategy: {
        stopLoss: '1450',
      },
    });

    await waitFor(() => {
      expect(screen.queryByText('正在加载历史分析上下文；现在可直接发送追问。')).not.toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '继续分析成交量' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '继续分析成交量',
          context: expect.objectContaining({
            stock_code: '600519',
            stock_name: '贵州茅台',
          }),
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '如果不考虑 TTM 呢' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '如果不考虑 TTM 呢',
          context: expect.objectContaining({
            stock_code: '600519',
            stock_name: '贵州茅台',
          }),
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('uses hydrated report context when it finishes before sending', async () => {
    vi.mocked(historyApi.getDetail).mockResolvedValue({
      meta: {
        id: 1,
        queryId: 'q-1',
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        createdAt: '2026-03-18T08:00:00Z',
        currentPrice: 1523.6,
        changePct: 1.8,
      },
      summary: {
        analysisSummary: '趋势延续',
        operationAdvice: '继续观察',
        trendPrediction: '高位震荡',
        sentimentScore: 78,
      },
      strategy: {
        stopLoss: '1450',
      },
    });

    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0&recordId=1']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.queryByText('正在加载历史分析上下文；现在可直接发送追问。')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '请深入分析 贵州茅台(600519)',
          context: expect.objectContaining({
            stock_code: '600519',
            stock_name: '贵州茅台',
            previous_price: 1523.6,
            previous_change_pct: 1.8,
            previous_strategy: expect.objectContaining({
              stopLoss: '1450',
            }),
          }),
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('falls back to base stock context when recordId is missing', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=AAPL']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 AAPL')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '请深入分析 AAPL',
          context: {
            stock_code: 'AAPL',
            stock_name: null,
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
    expect(historyApi.getDetail).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '继续看估值' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '继续看估值',
          context: {
            stock_code: 'AAPL',
            stock_name: null,
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('switches active stock context for explicit switch messages', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '换成 AAPL 看看' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '换成 AAPL 看看',
          context: {
            stock_code: 'AAPL',
            stock_name: null,
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('switches to the single new stock when the current stock appears first', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '先不看 600519，换成 AAPL 看看' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '先不看 600519，换成 AAPL 看看',
          context: {
            stock_code: 'AAPL',
            stock_name: null,
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '继续看支撑位' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '继续看支撑位',
          context: {
            stock_code: 'AAPL',
            stock_name: null,
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('keeps active stock context for compare messages', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '比较 600519 和 AAPL' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '比较 600519 和 AAPL',
          context: {
            stock_code: '600519',
            stock_name: '贵州茅台',
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('keeps active stock context for difference-style compare messages', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '分析 600519 和 AAPL 的差异' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '分析 600519 和 AAPL 的差异',
          context: {
            stock_code: '600519',
            stock_name: '贵州茅台',
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('keeps active stock context when the compared stock appears first', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '分析 AAPL 和 600519 的差异' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '分析 AAPL 和 600519 的差异',
          context: {
            stock_code: '600519',
            stock_name: '贵州茅台',
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('keeps active stock context for choice-style multi-stock messages', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: 'AAPL 和 TSLA 哪个更值得买' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: 'AAPL 和 TSLA 哪个更值得买',
          context: {
            stock_code: '600519',
            stock_name: '贵州茅台',
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('switches active stock context for single-stock difference phrasing', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '分析 AAPL 的差异化优势' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '分析 AAPL 的差异化优势',
          context: {
            stock_code: 'AAPL',
            stock_name: null,
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('switches active stock context for lowercase US ticker switch messages', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '分析tsla' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '分析tsla',
          context: {
            stock_code: 'TSLA',
            stock_name: null,
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('keeps active stock context when clicking the current session', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '切换到对话 请简要分析 600519' }));
    expect(mockSwitchSession).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '继续看成交量' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '继续看成交量',
          context: {
            stock_code: '600519',
            stock_name: '贵州茅台',
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('restores active stock context from loaded session messages', async () => {
    mockStoreState.messages = [
      { id: 'm-1', role: 'user', content: '请分析 600519' },
      { id: 'm-2', role: 'assistant', content: '600519 分析结果' },
      { id: 'm-3', role: 'user', content: '先不看 600519，换成 AAPL 看看' },
      { id: 'm-4', role: 'assistant', content: 'AAPL 分析结果' },
    ];

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByTestId('chat-workspace')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '继续看支撑位' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '继续看支撑位',
          context: {
            stock_code: 'AAPL',
            stock_name: null,
          },
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('clears active stock context when starting a new chat or switching sessions', async () => {
    mockStoreState.sessions = [
      ...mockStoreState.sessions,
      {
        session_id: 'session-2',
        title: '旧会话',
        message_count: 1,
        created_at: '2026-03-16T09:00:00Z',
        last_active: '2026-03-16T09:05:00Z',
      },
    ];

    const { unmount } = render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '开启新对话' }));
    expect(mockStartNewChat).toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '继续看成交量' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '继续看成交量',
          context: undefined,
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });

    unmount();
    mockStartStream.mockClear();

    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '切换到对话 旧会话' }));
    expect(mockSwitchSession).toHaveBeenCalledWith('session-2');

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '继续看成交量' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '继续看成交量',
          context: undefined,
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('clears active stock context when deleting the current session', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '删除对话 请简要分析 600519' }));
    fireEvent.click(screen.getByRole('button', { name: '删除' }));

    await waitFor(() => {
      expect(mockDeleteChatSession).toHaveBeenCalledWith('session-1');
    });
    expect(mockStartNewChat).toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText(/分析 600519/), {
      target: { value: '继续看成交量' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenLastCalledWith(
        expect.objectContaining({
          message: '继续看成交量',
          context: undefined,
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('ignores malformed follow-up query params', async () => {
    render(
      <MemoryRouter initialEntries={['/chat?stock=%3Cscript%3E&name=Bad%0AName&recordId=abc']}>
        <ChatPage />
      </MemoryRouter>
    );

    expect(await screen.findByRole('heading', { name: '问股' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/分析 600519/)).toHaveValue('');
    expect(historyApi.getDetail).not.toHaveBeenCalled();
  });

  it('reprocesses follow-up query params when navigating to the same chat route again', async () => {
    const firstDeferred = createDeferred<Awaited<ReturnType<typeof historyApi.getDetail>>>();
    const secondDeferred = createDeferred<Awaited<ReturnType<typeof historyApi.getDetail>>>();

    vi.mocked(historyApi.getDetail)
      .mockImplementationOnce(() => firstDeferred.promise)
      .mockImplementationOnce(() => secondDeferred.promise);

    const router = createMemoryRouter(
      [{ path: '/chat', element: <ChatPage /> }],
      {
        initialEntries: ['/chat?stock=600519&name=%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0&recordId=1'],
      },
    );

    render(<RouterProvider router={router} />);

    expect(await screen.findByDisplayValue('请深入分析 贵州茅台(600519)')).toBeInTheDocument();
    expect(screen.getByText('正在加载历史分析上下文；现在可直接发送追问。')).toBeInTheDocument();

    await router.navigate('/chat?stock=AAPL&name=Apple&recordId=2');

    expect(await screen.findByDisplayValue('请深入分析 Apple(AAPL)')).toBeInTheDocument();

    firstDeferred.resolve({
      meta: {
        id: 1,
        queryId: 'q-1',
        stockCode: '600519',
        stockName: '贵州茅台',
        reportType: 'detailed',
        createdAt: '2026-03-18T08:00:00Z',
        currentPrice: 1523.6,
        changePct: 1.8,
      },
      summary: {
        analysisSummary: '趋势延续',
        operationAdvice: '继续观察',
        trendPrediction: '高位震荡',
        sentimentScore: 78,
      },
      strategy: {
        stopLoss: '1450',
      },
    });

    secondDeferred.resolve({
      meta: {
        id: 2,
        queryId: 'q-2',
        stockCode: 'AAPL',
        stockName: 'Apple',
        reportType: 'detailed',
        createdAt: '2026-03-18T09:00:00Z',
        currentPrice: 211.5,
        changePct: 2.4,
      },
      summary: {
        analysisSummary: '趋势走强',
        operationAdvice: '继续持有',
        trendPrediction: '短线偏强',
        sentimentScore: 81,
      },
      strategy: {
        stopLoss: '205',
      },
    });

    await waitFor(() => {
      expect(screen.queryByText('正在加载历史分析上下文；现在可直接发送追问。')).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => {
      expect(mockStartStream).toHaveBeenCalledWith(
        expect.objectContaining({
          message: '请深入分析 Apple(AAPL)',
          context: expect.objectContaining({
            stock_code: 'AAPL',
            stock_name: 'Apple',
            previous_price: 211.5,
            previous_change_pct: 2.4,
            previous_strategy: expect.objectContaining({
              stopLoss: '205',
            }),
          }),
        }),
        expect.objectContaining({
          skillName: '趋势分析',
        }),
      );
    });
  });

  it('shows a jump-to-latest action when new content arrives while the user is away from bottom', async () => {
    mockStoreState.messages = [
      { id: 'user-1', role: 'user', content: '请分析 600519' },
      { id: 'assistant-1', role: 'assistant', content: '趋势偏强', skillName: '趋势分析' },
    ];

    const { rerender } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const viewport = await screen.findByTestId('chat-message-scroll');
    Object.defineProperty(viewport, 'scrollTop', { configurable: true, value: 0 });
    Object.defineProperty(viewport, 'clientHeight', { configurable: true, value: 400 });
    Object.defineProperty(viewport, 'scrollHeight', { configurable: true, value: 1200 });

    fireEvent.scroll(viewport);

    mockStoreState.messages = [
      ...mockStoreState.messages,
      { id: 'assistant-2', role: 'assistant', content: '新的补充分析', skillName: '趋势分析' },
    ];

    rerender(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const jumpButton = await screen.findByRole('button', { name: '查看最新消息' });
    expect(jumpButton).toBeInTheDocument();

    fireEvent.click(jumpButton);

    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled();
  });
});

describe('extractStockCodeFromMessage', () => {
  it('returns 6-digit A-share code', () => {
    expect(extractStockCodeFromMessage('分析 600519 趋势')).toBe('600519');
    expect(extractStockCodeFromMessage('002460')).toBe('002460');
  });

  it('returns HK prefixed code (normalized)', () => {
    expect(extractStockCodeFromMessage('分析 hk00700')).toBe('HK00700');
  });

  it('returns .HK suffix code (normalized to canonical)', () => {
    expect(extractStockCodeFromMessage('00700.HK')).toBe('HK00700');
    expect(extractStockCodeFromMessage('1810.HK')).toBe('HK01810');
  });

  it('returns code with .SH/.SZ suffix (normalized)', () => {
    expect(extractStockCodeFromMessage('看 600519.SH')).toBe('600519');
    expect(extractStockCodeFromMessage('000001.SZ')).toBe('000001');
  });

  it('returns US ticker like AAPL', () => {
    expect(extractStockCodeFromMessage('分析 AAPL 走势')).toBe('AAPL');
    expect(extractStockCodeFromMessage('TSLA')).toBe('TSLA');
    expect(extractStockCodeFromMessage('分析 BRK.B')).toBe('BRK.B');
  });

  it('does NOT return finance abbreviations as tickers', () => {
    expect(extractStockCodeFromMessage('如果不考虑 TTM 呢')).toBeNull();
    expect(extractStockCodeFromMessage('市盈率 TTM 怎么看')).toBeNull();
    expect(extractStockCodeFromMessage('PE 怎么看')).toBeNull();
    expect(extractStockCodeFromMessage('MACD 还没金叉吗')).toBeNull();
    expect(extractStockCodeFromMessage('RSI 怎么看')).toBeNull();
    expect(extractStockCodeFromMessage('WHAT IS PE')).toBeNull();
    expect(extractStockCodeFromMessage('PE IS HIGH')).toBeNull();
    expect(extractStockCodeFromMessage('WHAT IS TTM')).toBeNull();
  });

  it('does NOT return contextual moving-average MA as a ticker', () => {
    expect(extractStockCodeFromMessage('分析 MA 均线')).toBeNull();
    expect(extractStockCodeFromMessage('看看 MA 怎么排列')).toBeNull();
    expect(extractStockCodesFromMessage('MA 和 RSI 的指标怎么看')).toEqual([]);
    expect(extractStockCodeFromMessage('分析 KDJ 指标')).toBeNull();
    expect(extractStockCodeFromMessage('KDJ 怎么看')).toBeNull();
  });

  it('skips finance abbreviations before a real ticker', () => {
    expect(extractStockCodeFromMessage('PE AAPL 怎么看')).toBe('AAPL');
    expect(extractStockCodeFromMessage('TTM AAPL 怎么看')).toBe('AAPL');
    expect(extractStockCodeFromMessage('MACD AAPL 怎么看')).toBe('AAPL');
    expect(extractStockCodeFromMessage('WHAT IS PE AAPL')).toBe('AAPL');
  });

  it('does NOT return exchange prefixes as tickers', () => {
    expect(extractStockCodeFromMessage('分析 SH 走势')).toBeNull();
    expect(extractStockCodeFromMessage('看看 BJ')).toBeNull();
    expect(extractStockCodeFromMessage('HK')).toBeNull();
    expect(extractStockCodeFromMessage('买入 SZ')).toBeNull();
    expect(extractStockCodeFromMessage('US 市场')).toBeNull();
    expect(extractStockCodeFromMessage('SS')).toBeNull();
  });

  it('returns null for messages without stock codes', () => {
    expect(extractStockCodeFromMessage('茅台现在适合买入吗')).toBeNull();
    expect(extractStockCodeFromMessage('大盘走势如何')).toBeNull();
  });

  it('matches prefixed code like SH600519 (normalized)', () => {
    expect(extractStockCodeFromMessage('分析 SH600519')).toBe('600519');
  });

  it('returns SZ-prefixed code when standalone (normalized)', () => {
    expect(extractStockCodeFromMessage('SZ000001')).toBe('000001');
  });

  it('returns all stock codes in message order', () => {
    expect(extractStockCodesFromMessage('分析 600519 和 AAPL 的差异')).toEqual(['600519', 'AAPL']);
    expect(extractStockCodesFromMessage('分析 AAPL 和 600519 的差异')).toEqual(['AAPL', '600519']);
    expect(extractStockCodesFromMessage('AAPL 和 TSLA 哪个更值得买')).toEqual(['AAPL', 'TSLA']);
    expect(extractStockCodesFromMessage('比较 BRK.B 和 AAPL')).toEqual(['BRK.B', 'AAPL']);
  });

  it('extracts lowercase tickers only with explicit stock intent hints', () => {
    expect(extractStockCodesFromMessage('分析tsla')).toEqual(['TSLA']);
    expect(extractStockCodesFromMessage('看看 tsla')).toEqual(['TSLA']);
    expect(extractStockCodesFromMessage('aapl 和 tsla 哪个更值得买')).toEqual(['AAPL', 'TSLA']);
    expect(extractStockCodesFromMessage('hello tsla')).toEqual([]);
  });

  it('returns all HK and A-share variants without exchange affix tokens', () => {
    expect(extractStockCodesFromMessage('比较 01810 和 AAPL')).toEqual(['HK01810', 'AAPL']);
    expect(extractStockCodesFromMessage('比较 1810.HK 和 AAPL')).toEqual(['HK01810', 'AAPL']);
    expect(extractStockCodesFromMessage('比较 600519.SH 和 AAPL')).toEqual(['600519', 'AAPL']);
    expect(extractStockCodesFromMessage('比较 000001.SZ 和 SS')).toEqual(['000001']);
    expect(extractStockCodesFromMessage('比较 SH600519 和 AAPL')).toEqual(['600519', 'AAPL']);
    expect(extractStockCodesFromMessage('比较 SZ000001 和 AAPL')).toEqual(['000001', 'AAPL']);
    expect(extractStockCodesFromMessage('比较 BJ920748 和 AAPL')).toEqual(['920748', 'AAPL']);
    expect(extractStockCodesFromMessage('比较 HK01810 和 AAPL')).toEqual(['HK01810', 'AAPL']);
  });

  it('does not return denied abbreviations in multi-code extraction', () => {
    expect(extractStockCodesFromMessage('如果不考虑 TTM 和 PE')).toEqual([]);
    expect(extractStockCodesFromMessage('MACD AAPL 和 RSI')).toEqual(['AAPL']);
    expect(extractStockCodesFromMessage('KDJ AAPL 怎么看')).toEqual(['AAPL']);
  });
});

describe('watchlist button with code variants', () => {
  it('shows "从自选删除" when canonical code is in watchlist and user inputs variant', async () => {
    mockGetWatchlist.mockResolvedValue(['600519', 'HK01810']);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>,
    );

    const textarea = await screen.findByPlaceholderText(/例如/);
    fireEvent.change(textarea, { target: { value: '分析 600519.SH' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect(await screen.findByText('从自选删除')).toBeInTheDocument();
  });

  it('shows "从自选删除" for HK variant codes', async () => {
    mockGetWatchlist.mockResolvedValue(['HK01810']);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>,
    );

    const textarea = await screen.findByPlaceholderText(/例如/);
    fireEvent.change(textarea, { target: { value: '分析 1810.HK' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect(await screen.findByText('从自选删除')).toBeInTheDocument();
  });

  it('matches raw HK watchlist entries before rendering the watchlist action', async () => {
    mockGetWatchlist.mockResolvedValue(['01810']);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>,
    );

    const textarea = await screen.findByPlaceholderText(/例如/);
    fireEvent.change(textarea, { target: { value: '分析 1810.HK' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect(await screen.findByText('从自选删除')).toBeInTheDocument();
  });

  it('removes the matched raw HK watchlist entry instead of adding a duplicate variant', async () => {
    mockGetWatchlist.mockResolvedValue(['00700']);
    mockRemoveFromWatchlist.mockResolvedValue([]);

    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>,
    );

    const textarea = await screen.findByPlaceholderText(/例如/);
    fireEvent.change(textarea, { target: { value: '分析 00700.HK' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });
    fireEvent.click(await screen.findByText('从自选删除'));

    await waitFor(() => {
      expect(mockRemoveFromWatchlist).toHaveBeenCalledWith('00700');
    });
    expect(mockAddToWatchlist).not.toHaveBeenCalled();
  });
});
