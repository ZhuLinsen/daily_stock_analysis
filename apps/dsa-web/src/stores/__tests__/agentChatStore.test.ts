import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAgentChatStore } from '../agentChatStore';

vi.mock('../../api/agent', () => ({
  agentApi: {
    getChatSessions: vi.fn(async () => []),
    getChatSessionMessages: vi.fn(async () => []),
    chatStream: vi.fn(),
  },
}));

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

describe('agentChatStore.startStream', () => {
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
    });
    vi.clearAllMocks();
  });

  it('appends the user message and final assistant message from the SSE stream', async () => {
    vi.mocked(agentApi.chatStream).mockResolvedValue(
      createStreamResponse([
        'data: {"type":"thinking","step":1,"message":"分析中"}',
        'data: {"type":"tool_done","tool":"quote","display_name":"行情","success":true,"duration":0.3}',
        'data: {"type":"done","success":true,"content":"最终分析结果"}',
      ]),
    );

    await useAgentChatStore
      .getState()
      .startStream({ message: '分析茅台', session_id: 'session-test' }, { skillName: '趋势技能' });

    const state = useAgentChatStore.getState();
    expect(state.loading).toBe(false);
    expect(state.chatError).toBeNull();
    expect(state.messages).toHaveLength(2);
    expect(state.messages[0]).toMatchObject({
      role: 'user',
      content: '分析茅台',
      skillName: '趋势技能',
    });
    expect(state.messages[1]).toMatchObject({
      role: 'assistant',
      content: '最终分析结果',
      skillName: '趋势技能',
    });
    expect(state.messages[1].thinkingSteps).toHaveLength(2);
    expect(state.progressSteps).toEqual([]);
  });
});
