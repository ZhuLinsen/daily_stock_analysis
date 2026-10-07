import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAgentChatStore } from '../agentChatStore';
import type { ActiveStockContext, ChatSessionDetail } from '../../api/agent';

vi.mock('../../api/agent', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/agent')>();
  return {
    ...actual,
    agentApi: {
      getChatSessions: vi.fn(async () => []),
      getChatSessionMessages: vi.fn(async (sessionId: string) => ({
        session_id: sessionId,
        messages: [],
        session_state: { selected_skill_ids: [] },
      })),
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
    selectedSkillIds: null,
    savedSkillIds: null,
    activeStockContext: null,
    stateContract: 'unbound',
    sessionGeneration: null,
    sessionStateVersion: null,
    stateSource: null,
    sessionEpoch: 0,
    instanceBindingEpoch: 0,
    detailReadSequence: 0,
    skillDraftRevision: 0,
    skillDraftDirty: false,
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
  vi.mocked(agentApi.getChatSessions).mockResolvedValue([]);
  vi.mocked(agentApi.getChatSessionMessages).mockImplementation(async (sessionId) => ({
    session_id: sessionId, messages: [], session_state: { selected_skill_ids: [] },
  }));
});

const stockA: ActiveStockContext = {
  stock_code: '600519', stock_name: '贵州茅台', canonical_id: 'sh600519', asset_type: 'stock',
};
const stockB: ActiveStockContext = {
  stock_code: 'sh000001', stock_name: '上证指数', canonical_id: 'sh000001', asset_type: 'index',
};
function detailState(generation: string | null, version: number, active: ActiveStockContext | null,
  skills: string[] | null = [], sessionId = 'session-test'): ChatSessionDetail {
  return { session_id: sessionId, messages: [], session_generation: generation,
    session_state_version: version, active_stock_context: active,
    session_state: { selected_skill_ids: skills } };
}
function acceptedState(requestId: string, generation: string, version: number,
  active: ActiveStockContext | null, skills: string[] | null = []) {
  return `data: ${JSON.stringify({ ...detailState(generation, version, active, skills),
    type: 'accepted', backend: 'litellm', request_id: requestId })}\n`;
}
function openStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const response = new Response(new ReadableStream<Uint8Array>({ start(c) { controller = c; } }));
  vi.mocked(agentApi.chatStream).mockResolvedValue(response);
  return {
    send: (line: string) => controller.enqueue(encoder.encode(line)),
    finish: () => { controller.enqueue(encoder.encode('data: {"type":"done","success":true,"content":"answer"}\n'));
      controller.close(); },
  };
}

describe('agentChatStore authoritative session owner', () => {
  it.each(['switch', 'new'] as const)('ignores old initialization after %s changes its route owner', async (action) => {
    localStorage.setItem('dsa_chat_session_id', 'session-test');
    useAgentChatStore.setState({ hasInitialLoad: false });
    const list = createDeferred<Awaited<ReturnType<typeof agentApi.getChatSessions>>>();
    vi.mocked(agentApi.getChatSessions).mockReturnValue(list.promise);
    const pending = useAgentChatStore.getState().loadInitialSession();
    if (action === 'switch') await useAgentChatStore.getState().switchSession('other-session');
    else useAgentChatStore.getState().startNewChat();
    const id = useAgentChatStore.getState().sessionId;
    list.resolve([]);
    await pending;
    expect(useAgentChatStore.getState().sessionId).toBe(id);
    expect(localStorage.getItem('dsa_chat_session_id')).toBe(id);
  });

  it('replaces a genuinely missing saved session with no newer request', async () => {
    localStorage.setItem('dsa_chat_session_id', 'session-test');
    useAgentChatStore.setState({ hasInitialLoad: false });
    await useAgentChatStore.getState().loadInitialSession();
    expect(useAgentChatStore.getState().sessionId).not.toBe('session-test');
    expect(useAgentChatStore.getState().sessionGeneration).toBeNull();
    expect(useAgentChatStore.getState().messages).toEqual([]);
  });

  it('keeps a new creation request before acceptance when the old list returns', async () => {
    localStorage.setItem('dsa_chat_session_id', 'session-test');
    useAgentChatStore.setState({ hasInitialLoad: false });
    const list = createDeferred<Awaited<ReturnType<typeof agentApi.getChatSessions>>>();
    vi.mocked(agentApi.getChatSessions).mockReturnValue(list.promise);
    const initial = useAgentChatStore.getState().loadInitialSession();
    const stream = openStream();
    const pending = useAgentChatStore.getState().startStream({ message: '分析600519', request_id: 'creating' });
    const ac = useAgentChatStore.getState().abortController!;
    list.resolve([]);
    await initial;
    expect(useAgentChatStore.getState().sessionId).toBe('session-test');
    expect(ac.signal.aborted).toBe(false);
    stream.send(acceptedState('creating', 'new-instance', 1, stockA));
    stream.finish();
    await pending;
    expect(useAgentChatStore.getState().sessionGeneration).toBe('new-instance');
    expect(useAgentChatStore.getState().messages).toHaveLength(2);
  });

  it('keeps the newly accepted instance when an old initial list omits it', async () => {
    localStorage.setItem('dsa_chat_session_id', 'session-test');
    useAgentChatStore.setState({ hasInitialLoad: false });
    const list = createDeferred<Awaited<ReturnType<typeof agentApi.getChatSessions>>>();
    vi.mocked(agentApi.getChatSessions).mockReturnValue(list.promise);
    const initial = useAgentChatStore.getState().loadInitialSession();
    const stream = openStream();
    const ready = createDeferred<void>();
    const pending = useAgentChatStore.getState().startStream({ message: '分析600519', request_id: 'list-race' },
      { onAccepted: () => ready.resolve() });
    stream.send(acceptedState('list-race', 'new-instance', 1, stockA, ['ma_golden_cross']));
    await ready.promise;
    const owner = useAgentChatStore.getState();
    expect(owner.sessionEpoch).toBe(0);
    expect(owner.instanceBindingEpoch).toBe(1);
    list.resolve([]);
    await initial;
    expect(useAgentChatStore.getState()).toMatchObject({
      sessionId: 'session-test', sessionGeneration: 'new-instance', sessionStateVersion: 1,
      activeStockContext: stockA, savedSkillIds: ['ma_golden_cross'], loading: true,
    });
    expect(useAgentChatStore.getState().messages).toHaveLength(1);
    expect(owner.abortController!.signal.aborted).toBe(false);
    expect(agentApi.cancelChatStream).not.toHaveBeenCalled();
    stream.finish();
    await pending;
    expect(useAgentChatStore.getState().messages.map((m) => m.role)).toEqual(['user', 'assistant']);
  });

  it('can bind its first accepted instance after a detail confirms only an empty unbound view', async () => {
    const stream = openStream();
    const ready = createDeferred<void>();
    const pending = useAgentChatStore.getState().startStream({ message: '分析600519', request_id: 'first' },
      { onAccepted: () => ready.resolve() });
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue(detailState(null, 0, null));
    await useAgentChatStore.getState().refreshSession();
    stream.send(acceptedState('first', 'g', 1, stockA));
    await ready.promise;
    expect(useAgentChatStore.getState()).toMatchObject({ activeStockContext: stockA, sessionGeneration: 'g' });
    stream.finish();
    await pending;
  });
  it('hydrates explicit null and Skills even for an empty initial history', async () => {
    localStorage.setItem('dsa_chat_session_id', 'session-test');
    useAgentChatStore.setState({ hasInitialLoad: false });
    vi.mocked(agentApi.getChatSessions).mockResolvedValue([{ session_id: 'session-test', title: '',
      message_count: 0, created_at: null, last_active: null }]);
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue(detailState('g', 0, null, ['risk']));
    await useAgentChatStore.getState().loadInitialSession();
    expect(useAgentChatStore.getState()).toMatchObject({ stateContract: 'authoritative',
      sessionGeneration: 'g', sessionStateVersion: 0, activeStockContext: null, savedSkillIds: ['risk'],
      selectedSkillIds: ['risk'] });
  });

  it('never resurrects same-version accepted state after a valid null detail (including saved Skills)', async () => {
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue(detailState('g', 5, stockA, ['old']));
    await useAgentChatStore.getState().refreshSession();
    const stream = openStream();
    const ready = createDeferred<void>();
    const pending = useAgentChatStore.getState().startStream({ message: '风险呢', request_id: 'late' },
      { onAccepted: () => ready.resolve() });
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue(detailState('g', 5, null, []));
    await useAgentChatStore.getState().refreshSession();
    stream.send(acceptedState('late', 'g', 5, stockA, ['old']));
    await ready.promise;
    expect(useAgentChatStore.getState()).toMatchObject({ activeStockContext: null,
      savedSkillIds: [], sessionStateVersion: 5, stateSource: 'detail' });
    expect(useAgentChatStore.getState().messages.map((m) => m.content)).toEqual(['风险呢']);
    stream.finish();
    await pending;
  });

  it.each(['g1', null, 'legacy'] as const)('ignores pre-binding detail %s after accepted binds g2 without abort/cancel', async (generation) => {
    const detail = createDeferred<ChatSessionDetail>();
    vi.mocked(agentApi.getChatSessionMessages).mockReturnValue(detail.promise);
    const read = useAgentChatStore.getState().refreshSession();
    const stream = openStream();
    const ready = createDeferred<void>();
    const pending = useAgentChatStore.getState().startStream({ message: '分析上证指数', request_id: 'new' },
      { onAccepted: () => ready.resolve() });
    stream.send(acceptedState('new', 'g2', 1, stockB, ['new']));
    await ready.promise;
    const ac = useAgentChatStore.getState().abortController!;
    detail.resolve(generation === 'legacy'
      ? { session_id: 'session-test', messages: [], session_state: { selected_skill_ids: ['old'] } }
      : detailState(generation, 0, generation ? stockA : null, ['old']));
    await read;
    expect(useAgentChatStore.getState()).toMatchObject({ sessionGeneration: 'g2',
      sessionStateVersion: 1, activeStockContext: stockB, savedSkillIds: ['new'], loading: true });
    expect(useAgentChatStore.getState().messages.map((m) => m.content)).toEqual(['分析上证指数']);
    expect(ac.signal.aborted).toBe(false);
    expect(agentApi.cancelChatStream).not.toHaveBeenCalled();
    stream.finish();
    await pending;
  });

  it('still gives a pre-binding same-generation same-version detail precedence', async () => {
    const detail = createDeferred<ChatSessionDetail>();
    vi.mocked(agentApi.getChatSessionMessages).mockReturnValue(detail.promise);
    const read = useAgentChatStore.getState().refreshSession();
    const stream = openStream();
    const ready = createDeferred<void>();
    const pending = useAgentChatStore.getState().startStream({ message: '分析600519', request_id: 'same' },
      { onAccepted: () => ready.resolve() });
    stream.send(acceptedState('same', 'g', 1, stockA, ['old']));
    await ready.promise;
    detail.resolve(detailState('g', 1, null, []));
    await read;
    expect(useAgentChatStore.getState()).toMatchObject({ activeStockContext: null,
      savedSkillIds: [], stateSource: 'detail', loading: true });
    expect(useAgentChatStore.getState().abortController?.signal.aborted).toBe(false);
    stream.finish();
    await pending;
  });

  it('allows a bound, newly issued detail to discover a replacement instance and retire the old stream', async () => {
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue(detailState('g1', 9, stockA));
    await useAgentChatStore.getState().refreshSession();
    const stream = openStream();
    const ready = createDeferred<void>();
    const pending = useAgentChatStore.getState().startStream({ message: '风险呢', request_id: 'old' },
      { onAccepted: () => ready.resolve() });
    stream.send(acceptedState('old', 'g1', 10, stockA));
    await ready.promise;
    const ac = useAgentChatStore.getState().abortController!;
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue(detailState('g2', 0, stockB));
    await useAgentChatStore.getState().refreshSession();
    expect(useAgentChatStore.getState()).toMatchObject({ sessionGeneration: 'g2',
      activeStockContext: stockB, loading: false, activeRequestId: null, messages: [] });
    expect(ac.signal.aborted).toBe(true);
    stream.finish();
    await pending;
    expect(useAgentChatStore.getState().sessionGeneration).toBe('g2');
  });

  it('uses latest issued detail and a new epoch for A→B→A rather than latest return', async () => {
    const firstA = createDeferred<ChatSessionDetail>();
    vi.mocked(agentApi.getChatSessionMessages).mockReturnValueOnce(firstA.promise)
      .mockResolvedValueOnce(detailState('b', 0, null, [], 'b'))
      .mockResolvedValueOnce(detailState('new-a', 1, stockB));
    const first = useAgentChatStore.getState().switchSession('session-test');
    await useAgentChatStore.getState().switchSession('b');
    await useAgentChatStore.getState().switchSession('session-test');
    firstA.resolve(detailState('old-a', 0, stockA));
    await first;
    expect(useAgentChatStore.getState().sessionGeneration).toBe('new-a');
    const slow = createDeferred<ChatSessionDetail>();
    vi.mocked(agentApi.getChatSessionMessages).mockReturnValueOnce(slow.promise)
      .mockResolvedValueOnce(detailState('new-a', 1, null));
    const olderRead = useAgentChatStore.getState().refreshSession();
    await useAgentChatStore.getState().refreshSession();
    slow.resolve(detailState('new-a', 1, stockB));
    await olderRead;
    expect(useAgentChatStore.getState().activeStockContext).toBeNull();
  });

  it('separates version-0 recovery from old API and rejects stale v0 after positive accepted', async () => {
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue(detailState('g', 0, stockA));
    await useAgentChatStore.getState().refreshSession();
    expect(useAgentChatStore.getState()).toMatchObject({ stateContract: 'authoritative',
      activeStockContext: stockA, sessionStateVersion: 0 });
    vi.mocked(agentApi.chatStream).mockResolvedValue(createStreamResponse([
      acceptedState('r', 'g', 1, stockB), 'data: {"type":"done","success":true,"content":"ok"}',
    ]));
    await useAgentChatStore.getState().startStream({ message: '改看上证指数', request_id: 'r' });
    await useAgentChatStore.getState().refreshSession();
    expect(useAgentChatStore.getState().activeStockContext).toEqual(stockB);
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue({ session_id: 'session-test',
      messages: [], session_state: { selected_skill_ids: [] } });
    await useAgentChatStore.getState().refreshSession();
    expect(useAgentChatStore.getState()).toMatchObject({ stateContract: 'legacy',
      activeStockContext: null, sessionStateVersion: null, sessionGeneration: null });
  });

  it('retains draft selection on conflict and during a detail read without overwriting saved selection', async () => {
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue(detailState('g', 2, stockA, ['saved']));
    await useAgentChatStore.getState().refreshSession();
    const detail = createDeferred<ChatSessionDetail>();
    vi.mocked(agentApi.getChatSessionMessages).mockReturnValue(detail.promise);
    const read = useAgentChatStore.getState().refreshSession();
    useAgentChatStore.getState().setSelectedSkillIds(['draft']);
    detail.resolve(detailState('g', 2, stockA, ['saved-new']));
    await read;
    vi.mocked(agentApi.chatStream).mockResolvedValue(createStreamResponse([
      'data: {"type":"error","error_code":"session_state_conflict","request_id":"conflict","session_id":"session-test"}',
    ]));
    await useAgentChatStore.getState().startStream({ message: '风险呢', skills: ['draft'], request_id: 'conflict' });
    expect(useAgentChatStore.getState()).toMatchObject({ selectedSkillIds: ['draft'],
      savedSkillIds: ['saved-new'], activeStockContext: stockA, sessionStateVersion: 2 });
    expect(agentApi.chatStream).toHaveBeenCalledWith(expect.objectContaining({ session_generation: 'g' }), expect.anything());
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue(detailState('g', 3, stockB, []));
    await useAgentChatStore.getState().refreshSession();
    expect(useAgentChatStore.getState()).toMatchObject({ selectedSkillIds: ['draft'], savedSkillIds: [],
      activeStockContext: stockB, sessionStateVersion: 3 });
  });

  it('reports invalid partial detail without accepting its messages or state', async () => {
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue({ session_id: 'session-test', messages: [],
      active_stock_context: stockA, session_state: { selected_skill_ids: [] } });
    await useAgentChatStore.getState().refreshSession();
    expect(useAgentChatStore.getState()).toMatchObject({ stateContract: 'unbound',
      activeStockContext: null, chatError: { code: 'chat_state_protocol_error' } });
  });
});

describe('agentChatStore.startStream', () => {
  it('preserves the current request conflict before accepted without accepting a message or selection', async () => {
    useAgentChatStore.setState({ selectedSkillIds: ['risk'] });
    vi.mocked(agentApi.chatStream).mockResolvedValue(createStreamResponse([
      'data: {"type":"error","error_code":"session_state_conflict","message":"refresh and retry","request_id":"conflict-request","session_id":"session-test"}',
    ]));
    await useAgentChatStore.getState().startStream({ message: '风险呢', skills: [], request_id: 'conflict-request' });
    const state = useAgentChatStore.getState();
    expect(state.chatError).toMatchObject({ code: 'session_state_conflict' });
    expect(state.chatError?.message).toContain('刷新');
    expect(state.messages).toEqual([]);
    expect(state.selectedSkillIds).toEqual(['risk']);
    expect(state.loading).toBe(false);
    expect(agentApi.chatStream).toHaveBeenCalledTimes(1);
  });

  it('ignores an unrelated pre-accepted error and still accepts the owned request', async () => {
    vi.mocked(agentApi.chatStream).mockResolvedValue(createStreamResponse([
      'data: {"type":"error","error_code":"session_state_conflict","message":"unrelated","request_id":"other","session_id":"session-test"}',
      accepted('owned-request'),
      'data: {"type":"done","success":true,"content":"owned answer"}',
    ]));
    await useAgentChatStore.getState().startStream({ message: '分析600519', request_id: 'owned-request' });
    expect(useAgentChatStore.getState().chatError).toBeNull();
    expect(useAgentChatStore.getState().messages.map((row) => row.content)).toEqual(['分析600519', 'owned answer']);
  });

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
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue({
      session_id: 'session-2',
      messages: [
        { id: 'msg-2', role: 'assistant', content: '历史回复', created_at: null },
      ],
      session_state: { selected_skill_ids: ['risk'] },
    });
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
    expect(state.selectedSkillIds).toEqual(['risk']);
  });

  it('does not let a late session history response overwrite the current session', async () => {
    const sessionA = createDeferred<Awaited<ReturnType<typeof agentApi.getChatSessionMessages>>>();
    const sessionB = createDeferred<Awaited<ReturnType<typeof agentApi.getChatSessionMessages>>>();
    vi.mocked(agentApi.getChatSessionMessages).mockImplementation((targetSessionId: string) => {
      if (targetSessionId === 'session-a') return sessionA.promise;
      if (targetSessionId === 'session-b') return sessionB.promise;
      return Promise.resolve({
        session_id: targetSessionId,
        messages: [],
        session_state: { selected_skill_ids: [] },
      });
    });

    const switchToA = useAgentChatStore.getState().switchSession('session-a');
    const switchToB = useAgentChatStore.getState().switchSession('session-b');

    sessionB.resolve({
      session_id: 'session-b',
      messages: [{ id: 'msg-b', role: 'assistant', content: 'B 回复', created_at: null }],
      session_state: { selected_skill_ids: ['risk'] },
    });
    await switchToB;

    sessionA.resolve({
      session_id: 'session-a',
      messages: [{ id: 'msg-a', role: 'assistant', content: 'A 回复', created_at: null }],
      session_state: { selected_skill_ids: ['technical'] },
    });
    await switchToA;

    const state = useAgentChatStore.getState();
    expect(state.sessionId).toBe('session-b');
    expect(state.messages).toEqual([
      { id: 'msg-b', role: 'assistant', content: 'B 回复' },
    ]);
    expect(state.selectedSkillIds).toEqual(['risk']);
  });
});

describe('agentChatStore session Skill state', () => {
  it('restores the saved Skill selection during the initial session load', async () => {
    localStorage.setItem('dsa_chat_session_id', 'saved-session');
    useAgentChatStore.setState({ hasInitialLoad: false });
    vi.mocked(agentApi.getChatSessions).mockResolvedValue([
      {
        session_id: 'saved-session',
        title: 'saved',
        message_count: 1,
        created_at: null,
        last_active: null,
      },
    ]);
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue({
      session_id: 'saved-session',
      messages: [
        { id: 'msg-1', role: 'user', content: '分析 AAPL', created_at: null },
      ],
      session_state: { selected_skill_ids: ['technical', 'risk'] },
    });

    await useAgentChatStore.getState().loadInitialSession();

    expect(useAgentChatStore.getState().selectedSkillIds).toEqual([
      'technical',
      'risk',
    ]);
  });

  it('preserves null when an initial legacy session has no persisted Skill state', async () => {
    localStorage.setItem('dsa_chat_session_id', 'legacy-session');
    useAgentChatStore.setState({ hasInitialLoad: false });
    vi.mocked(agentApi.getChatSessions).mockResolvedValue([
      {
        session_id: 'legacy-session',
        title: 'legacy',
        message_count: 1,
        created_at: null,
        last_active: null,
      },
    ]);
    vi.mocked(agentApi.getChatSessionMessages).mockResolvedValue({
      session_id: 'legacy-session',
      messages: [
        { id: 'msg-1', role: 'user', content: '分析 AAPL', created_at: null },
      ],
      session_state: { selected_skill_ids: null },
    });

    await useAgentChatStore.getState().loadInitialSession();

    expect(useAgentChatStore.getState().selectedSkillIds).toBeNull();
  });

  it('clears the previous session Skill selection for a new chat', () => {
    useAgentChatStore.setState({ selectedSkillIds: ['risk'] });

    useAgentChatStore.getState().startNewChat();

    expect(useAgentChatStore.getState().selectedSkillIds).toBeNull();
  });
});
