import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAgentChatStore } from '../agentChatStore';

vi.mock('../../api/agent', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/agent')>();
  return {
    ...actual,
    agentApi: {
      getChatSessions: vi.fn(async () => []),
      getChatSessionMessages: vi.fn(async () => []),
      chatStream: vi.fn(),
      cancelChatStream: vi.fn(),
    },
  };
});

const { agentApi } = await import('../../api/agent');
const encoder = new TextEncoder();

function createStreamResponse(lines: string[]) {
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(lines.join('\n')));
        controller.close();
      },
    }),
    {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    },
  );
}

function accepted(
  requestId: string,
  sessionId = 'session-test',
  backend: 'litellm' | 'codex_app_server' = 'litellm',
) {
  return `data: ${JSON.stringify({
    type: 'accepted',
    backend,
    request_id: requestId,
    session_id: sessionId,
  })}`;
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  localStorage.clear();
  useAgentChatStore.setState({
    messages: [],
    loading: false,
    progressSteps: [],
    sessionId: 'session-test',
    sessions: [],
    sessionsLoading: false,
    chatError: null,
    currentRoute: '/chat',
    completionBadge: false,
    hasInitialLoad: true,
    abortController: null,
    activeRequestId: null,
    serverCancellation: false,
    stopping: false,
    terminalStatus: null,
    stopError: false,
  });
  vi.clearAllMocks();
});

describe('agentChatStore.startStream', () => {
  it('aborts locally before the server has accepted the request', () => {
    const ac = new AbortController();
    useAgentChatStore.setState({
      loading: true,
      abortController: ac,
      activeRequestId: 'request-before-accepted',
      serverCancellation: false,
    });

    void useAgentChatStore.getState().stopStream();

    expect(ac.signal.aborted).toBe(true);
    expect(agentApi.cancelChatStream).not.toHaveBeenCalled();
  });

  it('asks the server to stop an accepted Codex request and keeps SSE open for cleanup', async () => {
    const ac = new AbortController();
    const cancellation = createDeferred<{ accepted: boolean; request_id: string }>();
    vi.mocked(agentApi.cancelChatStream).mockReturnValue(cancellation.promise);
    useAgentChatStore.setState({
      loading: true,
      abortController: ac,
      activeRequestId: 'request-accepted',
      serverCancellation: true,
      stopping: false,
    });

    const stopPromise = useAgentChatStore.getState().stopStream();

    expect(ac.signal.aborted).toBe(false);
    expect(useAgentChatStore.getState().stopping).toBe(true);
    expect(agentApi.cancelChatStream).toHaveBeenCalledWith('request-accepted');
    cancellation.resolve({ accepted: true, request_id: 'request-accepted' });
    await stopPromise;

    expect(useAgentChatStore.getState().loading).toBe(true);
    expect(useAgentChatStore.getState().stopping).toBe(true);
    expect(ac.signal.aborted).toBe(false);
  });

  it('derives server-side stopping from the backend in accepted', async () => {
    let streamController!: ReadableStreamDefaultController<Uint8Array>;
    const acceptedReceived = createDeferred<void>();
    vi.mocked(agentApi.chatStream).mockResolvedValue(new Response(
      new ReadableStream({
        start(controller) {
          streamController = controller;
        },
      }),
      { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
    ));
    vi.mocked(agentApi.cancelChatStream).mockResolvedValue({
      accepted: true,
      request_id: 'request-live-codex',
    });

    const streamPromise = useAgentChatStore.getState().startStream(
      {
        message: '分析 AAPL',
        session_id: 'session-test',
        request_id: 'request-live-codex',
      },
      { onAccepted: () => acceptedReceived.resolve() },
    );
    streamController.enqueue(encoder.encode(
      `${accepted('request-live-codex', 'session-test', 'codex_app_server')}\n`,
    ));
    await acceptedReceived.promise;

    expect(useAgentChatStore.getState().serverCancellation).toBe(true);
    await useAgentChatStore.getState().stopStream();
    expect(agentApi.cancelChatStream).toHaveBeenCalledWith('request-live-codex');
    expect(useAgentChatStore.getState().abortController?.signal.aborted).toBe(false);

    streamController.enqueue(encoder.encode(
      'data: {"type":"done","success":false,"content":"","backend":"codex_app_server","error_code":"cancelled"}\n',
    ));
    streamController.close();
    await streamPromise;
    expect(useAgentChatStore.getState().terminalStatus).toBe('cancelled');
  });

  it('does not create a session or user message when stopped before accepted', async () => {
    vi.mocked(agentApi.chatStream).mockImplementation((_payload, options) => (
      new Promise((_resolve, reject) => {
        options?.signal?.addEventListener('abort', () => {
          reject(new DOMException('Aborted', 'AbortError'));
        });
      })
    ));

    const streamPromise = useAgentChatStore.getState().startStream({
      message: '立即停止',
      session_id: 'session-test',
      request_id: 'request-before-accepted',
    });
    await Promise.resolve();

    expect(useAgentChatStore.getState().messages).toEqual([]);
    expect(useAgentChatStore.getState().sessions).toEqual([]);
    await useAgentChatStore.getState().stopStream();
    await streamPromise;

    expect(agentApi.cancelChatStream).not.toHaveBeenCalled();
    expect(useAgentChatStore.getState().messages).toEqual([]);
    expect(useAgentChatStore.getState().chatError).toBeNull();
  });

  it('ignores late events from an old stream after switching sessions', async () => {
    let streamController!: ReadableStreamDefaultController<Uint8Array>;
    const onAccepted = vi.fn();
    useAgentChatStore.setState({ currentRoute: '/dashboard' });
    vi.mocked(agentApi.chatStream).mockResolvedValue(new Response(
      new ReadableStream({
        start(controller) {
          streamController = controller;
        },
      }),
      { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
    ));

    const streamPromise = useAgentChatStore.getState().startStream(
      {
        message: '分析 AAPL',
        session_id: 'session-test',
        request_id: 'request-old-session',
      },
      { onAccepted },
    );
    await Promise.resolve();
    await useAgentChatStore.getState().switchSession('session-next');

    streamController.enqueue(encoder.encode([
      accepted('request-old-session', 'session-test'),
      'data: {"type":"thinking","message":"旧请求处理中"}',
      'data: {"type":"error","message":"旧请求失败"}',
    ].join('\n')));
    streamController.close();
    await streamPromise;

    const state = useAgentChatStore.getState();
    expect(state.sessionId).toBe('session-next');
    expect(state.messages).toEqual([]);
    expect(state.progressSteps).toEqual([]);
    expect(state.chatError).toBeNull();
    expect(state.completionBadge).toBe(false);
    expect(onAccepted).not.toHaveBeenCalled();
    expect(agentApi.getChatSessions).not.toHaveBeenCalled();
  });

  it('ignores late events from an old stream after starting a new chat', async () => {
    let streamController!: ReadableStreamDefaultController<Uint8Array>;
    const onAccepted = vi.fn();
    vi.mocked(agentApi.chatStream).mockResolvedValue(new Response(
      new ReadableStream({
        start(controller) {
          streamController = controller;
        },
      }),
      { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
    ));

    const streamPromise = useAgentChatStore.getState().startStream(
      {
        message: '分析 AAPL',
        session_id: 'session-test',
        request_id: 'request-old-chat',
      },
      { onAccepted },
    );
    await Promise.resolve();
    useAgentChatStore.getState().startNewChat();
    const newSessionId = useAgentChatStore.getState().sessionId;

    streamController.enqueue(encoder.encode([
      accepted('request-old-chat', 'session-test'),
      'data: {"type":"thinking","message":"旧请求处理中"}',
      'data: {"type":"done","success":true,"content":"旧请求结果"}',
    ].join('\n')));
    streamController.close();
    await streamPromise;

    const state = useAgentChatStore.getState();
    expect(state.sessionId).toBe(newSessionId);
    expect(state.sessionId).not.toBe('session-test');
    expect(state.messages).toEqual([]);
    expect(state.progressSteps).toEqual([]);
    expect(state.chatError).toBeNull();
    expect(onAccepted).not.toHaveBeenCalled();
    expect(agentApi.getChatSessions).not.toHaveBeenCalled();
  });

  it('commits the user turn once on accepted and uses its actual backend', async () => {
    const onAccepted = vi.fn();
    vi.mocked(agentApi.chatStream).mockResolvedValue(
      createStreamResponse([
        accepted('request-success', 'session-test', 'codex_app_server'),
        'data: {"type":"thinking","step":1,"message":"分析中"}',
        'data: {"type":"tool_done","tool":"quote","display_name":"行情","success":true,"duration":0.3}',
        'data: {"type":"done","success":true,"content":"最终分析结果","backend":"codex_app_server"}',
      ]),
    );

    await useAgentChatStore.getState().startStream(
      {
        message: '分析茅台',
        session_id: 'session-test',
        request_id: 'request-success',
      },
      { skillName: '趋势技能', onAccepted },
    );

    const state = useAgentChatStore.getState();
    expect(onAccepted).toHaveBeenCalledTimes(1);
    expect(onAccepted).toHaveBeenCalledWith({
      type: 'accepted',
      backend: 'codex_app_server',
      request_id: 'request-success',
      session_id: 'session-test',
    });
    expect(state.messages).toHaveLength(2);
    expect(state.messages[0]).toMatchObject({
      role: 'user',
      content: '分析茅台',
      skillName: '趋势技能',
      backend: 'codex_app_server',
    });
    expect(state.messages[1]).toMatchObject({
      role: 'assistant',
      content: '最终分析结果',
      skillName: '趋势技能',
      backend: 'codex_app_server',
    });
    expect(state.messages[1].thinkingSteps).toHaveLength(2);
    expect(state.chatError).toBeNull();
  });

  it('sends the store session id when the caller omits session_id', async () => {
    useAgentChatStore.setState({ sessionId: 'session-from-store' });
    vi.mocked(agentApi.chatStream).mockResolvedValue(
      createStreamResponse([
        accepted('request-store-session', 'session-from-store'),
        'data: {"type":"done","success":true,"content":"分析完成"}',
      ]),
    );

    await useAgentChatStore.getState().startStream({
      message: '分析茅台',
      request_id: 'request-store-session',
    });

    expect(agentApi.chatStream).toHaveBeenCalledWith(
      expect.objectContaining({
        session_id: 'session-from-store',
        request_id: 'request-store-session',
      }),
      expect.any(Object),
    );
    expect(useAgentChatStore.getState().chatError).toBeNull();
  });

  it('rejects a duplicate accepted event without duplicating the user turn', async () => {
    vi.mocked(agentApi.chatStream).mockResolvedValue(
      createStreamResponse([
        accepted('request-duplicate'),
        accepted('request-duplicate'),
      ]),
    );

    await useAgentChatStore.getState().startStream({
      message: '分析茅台',
      session_id: 'session-test',
      request_id: 'request-duplicate',
    });

    const state = useAgentChatStore.getState();
    expect(state.messages).toHaveLength(1);
    expect(state.chatError).toMatchObject({
      title: '请求未被接受',
      rawMessage: 'Agent stream emitted accepted more than once.',
    });
  });

  it('rejects a terminal event before accepted without creating a ghost message', async () => {
    vi.mocked(agentApi.chatStream).mockResolvedValue(
      createStreamResponse([
        'data: {"type":"done","success":false,"error":"context failed"}',
      ]),
    );

    await useAgentChatStore.getState().startStream({
      message: '分析茅台',
      session_id: 'session-test',
      request_id: 'request-not-accepted',
    });

    const state = useAgentChatStore.getState();
    expect(state.messages).toEqual([]);
    expect(state.sessions).toEqual([]);
    expect(state.chatError).toMatchObject({
      title: '请求未被接受',
      rawMessage: 'Agent stream emitted done before accepted.',
    });
  });

  it('treats an accepted cancelled turn as a terminal state, not an error', async () => {
    vi.mocked(agentApi.chatStream).mockResolvedValue(
      createStreamResponse([
        accepted('request-cancelled', 'session-test', 'codex_app_server'),
        'data: {"type":"done","success":false,"content":"","error":"本次 Codex Agent 问股已取消。","backend":"codex_app_server","error_code":"cancelled"}',
      ]),
    );

    await useAgentChatStore.getState().startStream({
      message: '分析茅台',
      session_id: 'session-test',
      request_id: 'request-cancelled',
    });

    const state = useAgentChatStore.getState();
    expect(state.terminalStatus).toBe('cancelled');
    expect(state.chatError).toBeNull();
    expect(state.messages).toHaveLength(1);
  });

  it('preserves multiple selected skills on accepted user and assistant messages', async () => {
    vi.mocked(agentApi.chatStream).mockResolvedValue(
      createStreamResponse([
        accepted('request-skills'),
        'data: {"type":"done","success":true,"content":"多策略分析结果"}',
      ]),
    );

    await useAgentChatStore.getState().startStream(
      {
        message: '分析茅台',
        session_id: 'session-test',
        request_id: 'request-skills',
        skills: ['bull_trend', 'ma_golden_cross'],
      },
      { skillNames: ['趋势分析', '均线金叉'] },
    );

    const state = useAgentChatStore.getState();
    expect(state.messages).toHaveLength(2);
    expect(state.messages[0]).toMatchObject({
      role: 'user',
      skills: ['bull_trend', 'ma_golden_cross'],
      skill: 'bull_trend',
      skillNames: ['趋势分析', '均线金叉'],
      skillName: '趋势分析、均线金叉',
    });
    expect(state.messages[1]).toMatchObject({
      role: 'assistant',
      content: '多策略分析结果',
      skills: ['bull_trend', 'ma_golden_cross'],
      skill: 'bull_trend',
      skillNames: ['趋势分析', '均线金叉'],
      skillName: '趋势分析、均线金叉',
    });
  });

  it('reports an interrupted accepted stream without appending an empty assistant message', async () => {
    vi.mocked(agentApi.chatStream).mockResolvedValue(
      createStreamResponse([
        accepted('request-interrupted'),
        'data: {"type":"thinking","step":1,"message":"分析中"}',
      ]),
    );

    await useAgentChatStore.getState().startStream({
      message: '分析茅台',
      session_id: 'session-test',
      request_id: 'request-interrupted',
    });

    const state = useAgentChatStore.getState();
    expect(state.messages).toHaveLength(1);
    expect(state.chatError).toMatchObject({
      title: '回复未完整返回',
      message: 'Agent 流式响应在完成前中断，请重试。',
      category: 'upstream_network',
    });
  });

  it('preserves parsed error details after accepted', async () => {
    vi.mocked(agentApi.chatStream).mockResolvedValue(
      createStreamResponse([
        accepted('request-failure'),
        'data: {"type":"done","success":false,"error":"Agent LLM: no effective primary model configured"}',
      ]),
    );

    await useAgentChatStore.getState().startStream({
      message: '分析茅台',
      session_id: 'session-test',
      request_id: 'request-failure',
    });

    expect(useAgentChatStore.getState().chatError).toMatchObject({
      title: '系统没有配置可用的 LLM 模型',
      category: 'llm_not_configured',
      rawMessage: 'Agent LLM: no effective primary model configured',
    });
  });

  it('uses the shared parser for an accepted SSE error event', async () => {
    vi.mocked(agentApi.chatStream).mockResolvedValue(
      createStreamResponse([
        accepted('request-timeout'),
        'data: {"type":"error","message":"connect timeout while calling upstream provider"}',
      ]),
    );

    await useAgentChatStore.getState().startStream({
      message: '分析茅台',
      session_id: 'session-test',
      request_id: 'request-timeout',
    });

    expect(useAgentChatStore.getState().chatError).toMatchObject({
      title: '连接上游服务超时',
      category: 'upstream_timeout',
      rawMessage: 'connect timeout while calling upstream provider',
    });
  });

  it('uses a Codex-specific fallback after Codex was accepted', async () => {
    vi.mocked(agentApi.chatStream).mockResolvedValue(
      createStreamResponse([
        accepted('request-codex-error', 'session-test', 'codex_app_server'),
        'data: {"type":"error","backend":"codex_app_server","error_code":"login_required","error":"","message":""}',
      ]),
    );

    await useAgentChatStore.getState().startStream({
      message: '分析茅台',
      session_id: 'session-test',
      request_id: 'request-codex-error',
    });

    const error = useAgentChatStore.getState().chatError;
    expect(error?.message).toContain('Codex Agent');
    expect(error?.message).toContain('Agent 设置');
    expect(error?.message).not.toContain('API Key');
  });
});

describe('agentChatStore.switchSession', () => {
  it('clears transient loading state when switching sessions during a stream', async () => {
    const ac = new AbortController();
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue([
      { id: 'msg-2', role: 'assistant', content: '历史回复', created_at: null },
    ]);
    useAgentChatStore.setState({
      loading: true,
      progressSteps: [{ type: 'thinking', message: '正在制定分析路径...' }],
      abortController: ac,
      chatError: {
        title: '请求失败',
        message: '旧错误',
        category: 'unknown',
        rawMessage: '旧错误',
      },
    });

    await useAgentChatStore.getState().switchSession('session-2');

    const state = useAgentChatStore.getState();
    expect(ac.signal.aborted).toBe(true);
    expect(state.sessionId).toBe('session-2');
    expect(state.loading).toBe(false);
    expect(state.progressSteps).toEqual([]);
    expect(state.abortController).toBeNull();
    expect(state.chatError).toBeNull();
    expect(state.messages).toEqual([
      { id: 'msg-2', role: 'assistant', content: '历史回复' },
    ]);
  });

  it('does not let a late session history response overwrite the current session', async () => {
    const sessionA = createDeferred<
      Array<{ id: string; role: 'user' | 'assistant'; content: string; created_at: string | null }>
    >();
    const sessionB = createDeferred<
      Array<{ id: string; role: 'user' | 'assistant'; content: string; created_at: string | null }>
    >();
    vi.mocked(agentApi.getChatSessionMessages).mockImplementation((targetSessionId: string) => {
      if (targetSessionId === 'session-a') return sessionA.promise;
      if (targetSessionId === 'session-b') return sessionB.promise;
      return Promise.resolve([]);
    });

    const switchToA = useAgentChatStore.getState().switchSession('session-a');
    const switchToB = useAgentChatStore.getState().switchSession('session-b');

    sessionB.resolve([{ id: 'msg-b', role: 'assistant', content: 'B 回复', created_at: null }]);
    await switchToB;

    sessionA.resolve([{ id: 'msg-a', role: 'assistant', content: 'A 回复', created_at: null }]);
    await switchToA;

    const state = useAgentChatStore.getState();
    expect(state.sessionId).toBe('session-b');
    expect(state.messages).toEqual([
      { id: 'msg-b', role: 'assistant', content: 'B 回复' },
    ]);
  });
});
