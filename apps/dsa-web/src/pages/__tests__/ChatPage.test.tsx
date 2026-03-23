import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { historyApi } from '../../api/history';
import ChatPage from '../ChatPage';

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const mockLoadSessions = vi.fn();
const mockLoadInitialSession = vi.fn();
const mockSwitchSession = vi.fn();
const mockStartStream = vi.fn();
const mockClearCompletionBadge = vi.fn();
const mockStartNewChat = vi.fn();

const mockStoreState = {
  messages: [],
  loading: false,
  progressSteps: [],
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
    getSkills: vi.fn().mockResolvedValue({
      skills: [
        { id: 'bull_trend', name: '趋势分析', description: '测试技能' },
      ],
      default_skill_id: 'bull_trend',
    }),
    deleteChatSession: vi.fn().mockResolvedValue(undefined),
    sendChat: vi.fn().mockResolvedValue({ success: true }),
  },
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

  it('switches session when clicking anywhere on the session card', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <ChatPage />
      </MemoryRouter>
    );

    const sessionCard = await screen.findByRole('button', {
      name: /切换到对话 请简要分析 600519/,
    });

    fireEvent.click(sessionCard);
    expect(mockSwitchSession).toHaveBeenCalledWith('session-1');
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
          context: undefined,
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
});
