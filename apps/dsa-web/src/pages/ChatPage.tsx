import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { agentApi } from '../api/agent';
import { ApiErrorAlert, ConfirmDialog } from '../components/common';
import { getParsedApiError } from '../api/error';
import type { StrategyInfo } from '../api/agent';
import { historyApi } from '../api/history';
import {
  useAgentChatStore,
  type Message,
  type ProgressStep,
} from '../stores/agentChatStore';
import { downloadSession, formatSessionAsMarkdown } from '../utils/chatExport';

interface FollowUpContext {
  stock_code: string;
  stock_name: string | null;
  previous_analysis_summary?: unknown;
  previous_strategy?: unknown;
  previous_price?: number;
  previous_change_pct?: number;
}

// Quick question examples shown on empty state
const QUICK_QUESTIONS = [
  { label: '用缠论分析茅台', strategy: 'chan_theory' },
  { label: '波浪理论看宁德时代', strategy: 'wave_theory' },
  { label: '分析比亚迪趋势', strategy: 'bull_trend' },
  { label: '箱体震荡策略看中芯国际', strategy: 'box_oscillation' },
  { label: '分析腾讯 hk00700', strategy: 'bull_trend' },
  { label: '用情绪周期分析东方财富', strategy: 'emotion_cycle' },
];

const ChatPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [input, setInput] = useState('');
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<string>('bull_trend');
  const [showStrategyDesc, setShowStrategyDesc] = useState<string | null>(null);
  const [expandedThinking, setExpandedThinking] = useState<Set<string>>(new Set());
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendToast, setSendToast] = useState<{
    type: 'success' | 'error';
    message: string;
  } | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const initialFollowUpHandled = useRef(false);
  const followUpContextRef = useRef<FollowUpContext | null>(null);

  const {
    messages,
    loading,
    progressSteps,
    sessionId,
    sessions,
    sessionsLoading,
    chatError,
    loadSessions,
    loadInitialSession,
    switchSession,
    startStream,
    clearCompletionBadge,
  } = useAgentChatStore();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, progressSteps]);

  useEffect(() => {
    clearCompletionBadge();
  }, [clearCompletionBadge]);

  useEffect(() => {
    loadInitialSession();
  }, [loadInitialSession]);

  useEffect(() => {
    agentApi.getStrategies().then((res) => {
      setStrategies(res.strategies);
      const defaultId =
        res.strategies.find((s) => s.id === 'bull_trend')?.id ||
        res.strategies[0]?.id ||
        '';
      setSelectedStrategy(defaultId);
    }).catch(() => {});
  }, []);

  const handleStartNewChat = useCallback(() => {
    followUpContextRef.current = null;
    useAgentChatStore.getState().startNewChat();
    setSidebarOpen(false);
  }, []);

  const handleSwitchSession = useCallback((targetSessionId: string) => {
    switchSession(targetSessionId);
    setSidebarOpen(false);
  }, [switchSession]);

  const confirmDelete = useCallback(() => {
    if (!deleteConfirmId) return;
    agentApi.deleteChatSession(deleteConfirmId).then(() => {
      loadSessions();
      if (deleteConfirmId === sessionId) {
        handleStartNewChat();
      }
    }).catch(() => {});
    setDeleteConfirmId(null);
  }, [deleteConfirmId, sessionId, loadSessions, handleStartNewChat]);

  // Handle follow-up from report page: ?stock=600519&name=贵州茅台&recordId=xxx
  useEffect(() => {
    if (initialFollowUpHandled.current) return;
    const stock = searchParams.get('stock');
    const name = searchParams.get('name');
    const recordId = searchParams.get('recordId');
    if (stock) {
      initialFollowUpHandled.current = true;
      const displayName = name ? `${name}(${stock})` : stock;
      setInput(`请深入分析 ${displayName}`);
      if (recordId) {
        historyApi.getDetail(Number(recordId)).then((report) => {
          const ctx: FollowUpContext = { stock_code: stock, stock_name: name };
          if (report.summary) ctx.previous_analysis_summary = report.summary;
          if (report.strategy) ctx.previous_strategy = report.strategy;
          if (report.meta) {
            ctx.previous_price = report.meta.currentPrice;
            ctx.previous_change_pct = report.meta.changePct;
          }
          followUpContextRef.current = ctx;
        }).catch(() => {});
      }
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const handleSend = useCallback(
    async (overrideMessage?: string, overrideStrategy?: string) => {
      const msgText = overrideMessage || input.trim();
      if (!msgText || loading) return;
      const usedStrategy = overrideStrategy || selectedStrategy;
      const usedStrategyName =
        strategies.find((s) => s.id === usedStrategy)?.name ||
        (usedStrategy ? usedStrategy : '通用');

      const payload = {
        message: msgText,
        session_id: sessionId,
        strategies: usedStrategy ? [usedStrategy] : undefined,
        context: followUpContextRef.current ?? undefined,
      };
      followUpContextRef.current = null;

      setInput('');
      await startStream(payload, { strategyName: usedStrategyName });
    },
    [input, loading, selectedStrategy, strategies, sessionId, startStream],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleQuickQuestion = (q: (typeof QUICK_QUESTIONS)[0]) => {
    setSelectedStrategy(q.strategy);
    handleSend(q.label, q.strategy);
  };

  const toggleThinking = (msgId: string) => {
    setExpandedThinking((prev) => {
      const next = new Set(prev);
      if (next.has(msgId)) next.delete(msgId);
      else next.add(msgId);
      return next;
    });
  };

  const getCurrentStage = (steps: ProgressStep[]): string => {
    if (steps.length === 0) return '正在连接...';
    const last = steps[steps.length - 1];
    if (last.type === 'thinking') return last.message || 'AI 正在思考...';
    if (last.type === 'tool_start')
      return `${last.display_name || last.tool}...`;
    if (last.type === 'tool_done')
      return `${last.display_name || last.tool} 完成`;
    if (last.type === 'generating')
      return last.message || '正在生成最终分析...';
    return '处理中...';
  };

  const renderThinkingBlock = (msg: Message) => {
    if (!msg.thinkingSteps || msg.thinkingSteps.length === 0) return null;
    const isExpanded = expandedThinking.has(msg.id);
    const toolSteps = msg.thinkingSteps.filter((s) => s.type === 'tool_done');
    const totalDuration = toolSteps.reduce(
      (sum, s) => sum + (s.duration || 0),
      0,
    );
    const summary = `${toolSteps.length} 个工具调用 · ${totalDuration.toFixed(1)}s`;

    return (
      <button
        onClick={() => toggleThinking(msg.id)}
        className="flex items-center gap-2 text-xs text-muted hover:text-secondary transition-colors mb-2 w-full text-left"
      >
        <svg
          className={`w-3 h-3 transition-transform flex-shrink-0 ${isExpanded ? 'rotate-90' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 5l7 7-7 7"
          />
        </svg>
        <span className="flex items-center gap-1.5">
          <span className="opacity-60">思考过程</span>
          <span className="text-muted/50">·</span>
          <span className="opacity-50">{summary}</span>
        </span>
      </button>
    );
  };

  const renderThinkingDetails = (steps: ProgressStep[]) => (
    <div className="mb-3 pl-5 border-l border-white/5 space-y-0.5 animate-fade-in">
      {steps.map((step, idx) => {
        let icon = '⋯';
        let text = '';
        let colorClass = 'text-muted';
        if (step.type === 'thinking') {
          icon = '🤔';
          text = step.message || `第 ${step.step} 步：思考`;
          colorClass = 'text-secondary';
        } else if (step.type === 'tool_start') {
          icon = '⚙️';
          text = `${step.display_name || step.tool}...`;
          colorClass = 'text-secondary';
        } else if (step.type === 'tool_done') {
          icon = step.success ? '✅' : '❌';
          text = `${step.display_name || step.tool} (${step.duration}s)`;
          colorClass = step.success ? 'text-green-400' : 'text-red-400';
        } else if (step.type === 'generating') {
          icon = '✍️';
          text = step.message || '生成分析';
          colorClass = 'text-cyan';
        }
        return (
          <div
            key={idx}
            className={`flex items-center gap-2 text-xs py-0.5 ${colorClass}`}
          >
            <span className="w-4 flex-shrink-0 text-center">{icon}</span>
            <span className="leading-relaxed">{text}</span>
          </div>
        );
      })}
    </div>
  );

  const sidebarContent = (
    <>
      <div className="p-3 border-b border-white/5 flex items-center justify-between">
        <span className="text-sm font-medium text-white">历史对话</span>
        <button
          onClick={handleStartNewChat}
          className="p-1.5 rounded-lg hover:bg-white/10 transition-colors text-secondary hover:text-white"
          title="新对话"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 4v16m8-8H4"
            />
          </svg>
        </button>
      </div>
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {sessionsLoading ? (
          <div className="p-4 text-center text-xs text-muted">加载中...</div>
        ) : sessions.length === 0 ? (
          <div className="p-4 text-center text-xs text-muted">暂无历史对话</div>
        ) : (
          sessions.map((s) => (
            <button
              key={s.session_id}
              onClick={() => handleSwitchSession(s.session_id)}
              className={`w-full text-left px-3 py-2.5 border-b border-white/5 hover:bg-white/5 transition-colors group ${
                s.session_id === sessionId ? 'bg-white/10' : ''
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm text-secondary group-hover:text-white truncate flex-1">
                  {s.title}
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleteConfirmId(s.session_id);
                  }}
                  className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-white/10 text-muted hover:text-red-400 transition-all flex-shrink-0"
                  title="删除"
                >
                  <svg
                    className="w-3.5 h-3.5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                    />
                  </svg>
                </button>
              </div>
              <div className="text-xs text-muted mt-0.5">
                {s.message_count} 条消息
                {s.last_active &&
                  ` · ${new Date(s.last_active).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`}
              </div>
            </button>
          ))
        )}
      </div>
    </>
  );

  return (
    <div className="h-screen flex max-w-6xl mx-auto w-full p-4 md:p-6 gap-4">
      {/* Desktop sidebar */}
      <div className="hidden md:flex flex-col w-64 flex-shrink-0 glass-card overflow-hidden">
        {sidebarContent}
      </div>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        >
          <div className="absolute inset-0 bg-black/60" />
          <div
            className="absolute left-0 top-0 bottom-0 w-72 flex flex-col glass-card overflow-hidden border-r border-white/10 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {sidebarContent}
          </div>
        </div>
      )}

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        isOpen={!!deleteConfirmId}
        title="删除对话"
        message="删除后，该对话将不可恢复，确认删除吗？"
        confirmText="确认删除"
        cancelText="取消"
        isDanger={true}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteConfirmId(null)}
      />

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="mb-4 flex-shrink-0">
          <h1 className="text-2xl font-bold text-white mb-2 flex items-center gap-2">
            <button
              onClick={() => setSidebarOpen(true)}
              className="md:hidden p-1.5 -ml-1 rounded-lg hover:bg-white/10 transition-colors text-secondary hover:text-white"
              title="历史对话"
            >
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 6h16M4 12h16M4 18h16"
                />
              </svg>
            </button>
            <svg
              className="w-6 h-6 text-cyan"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
              />
            </svg>
            问股
          </h1>
          <p className="text-secondary text-sm">
            向 AI 询问个股分析，获取基于策略的交易建议与实时决策报告。
          </p>
          {messages.length > 0 && (
            <div className="mt-2 flex gap-2 items-center">
              <button
                type="button"
                onClick={() => downloadSession(messages)}
                className="px-3 py-1.5 rounded-lg text-sm text-secondary hover:text-white hover:bg-white/10 border border-white/10 transition-colors flex items-center gap-1.5"
                title="导出会话为 Markdown 文件"
              >
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                  />
                </svg>
                导出会话
              </button>
              <button
                type="button"
                onClick={async () => {
                  if (sending) return;
                  setSending(true);
                  setSendToast(null);
                  try {
                    const content = formatSessionAsMarkdown(messages);
                    await agentApi.sendChat(content);
                    setSendToast({ type: 'success', message: '已发送到通知渠道' });
                    setTimeout(() => setSendToast(null), 3000);
                  } catch (err) {
                    const parsed = getParsedApiError(err);
                    setSendToast({
                      type: 'error',
                      message: parsed.message || '发送失败',
                    });
                    setTimeout(() => setSendToast(null), 5000);
                  } finally {
                    setSending(false);
                  }
                }}
                disabled={sending}
                className="px-3 py-1.5 rounded-lg text-sm text-secondary hover:text-white hover:bg-white/10 border border-white/10 transition-colors flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                title="发送到已配置的通知机器人/邮箱"
              >
                {sending ? (
                  <svg
                    className="w-4 h-4 animate-spin"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                    />
                  </svg>
                ) : (
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                    />
                  </svg>
                )}
                发送
              </button>
              {sendToast && (
                <span
                  className={`text-sm ${sendToast.type === 'success' ? 'text-green-400' : 'text-red-400'}`}
                >
                  {sendToast.message}
                </span>
              )}
            </div>
          )}
        </header>

        <div className="flex-1 flex flex-col glass-card overflow-hidden min-h-0 relative z-10">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 custom-scrollbar relative z-10">
            {messages.length === 0 && !loading ? (
              <div className="h-full flex flex-col items-center justify-center text-center">
                <div className="w-16 h-16 mb-4 rounded-2xl bg-white/5 flex items-center justify-center">
                  <svg
                    className="w-8 h-8 text-muted"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                    />
                  </svg>
                </div>
                <h3 className="text-lg font-medium text-white mb-2">
                  开始问股
                </h3>
                <p className="text-sm text-secondary max-w-sm mb-6">
                  输入「分析 600519」或「茅台现在能买吗」，AI
                  将调用实时数据工具为您生成决策报告。
                </p>
                <div className="flex flex-wrap gap-2 justify-center max-w-lg">
                  {QUICK_QUESTIONS.map((q, i) => (
                    <button
                      key={i}
                      onClick={() => handleQuickQuestion(q)}
                      className="px-3 py-1.5 rounded-full bg-white/5 border border-white/10 text-sm text-secondary hover:text-white hover:border-cyan/40 hover:bg-cyan/5 transition-all"
                    >
                      {q.label}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex gap-4 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
                >
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold ${
                      msg.role === 'user'
                        ? 'bg-cyan text-black'
                        : 'bg-white/10 text-white'
                    }`}
                  >
                    {msg.role === 'user' ? 'U' : 'AI'}
                  </div>
                  <div
                    className={`max-w-[80%] rounded-2xl px-5 py-3.5 ${
                      msg.role === 'user'
                        ? 'bg-cyan/10 text-white border border-cyan/20 rounded-tr-sm'
                        : 'bg-white/5 text-secondary border border-white/10 rounded-tl-sm'
                    }`}
                  >
                    {msg.role === 'assistant' && msg.strategyName && (
                      <div className="mb-2">
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan/10 border border-cyan/20 text-xs text-cyan">
                          <svg
                            className="w-3 h-3"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M13 10V3L4 14h7v7l9-11h-7z"
                            />
                          </svg>
                          {msg.strategyName}
                        </span>
                      </div>
                    )}
                    {msg.role === 'assistant' && renderThinkingBlock(msg)}
                    {msg.role === 'assistant' &&
                      expandedThinking.has(msg.id) &&
                      msg.thinkingSteps &&
                      renderThinkingDetails(msg.thinkingSteps)}
                    {msg.role === 'assistant' ? (
                      <div
                        className="prose prose-invert prose-sm max-w-none
                      prose-headings:text-white prose-headings:font-semibold prose-headings:mt-3 prose-headings:mb-1.5
                      prose-h1:text-lg prose-h2:text-base prose-h3:text-sm
                      prose-p:leading-relaxed prose-p:mb-2 prose-p:last:mb-0
                      prose-strong:text-white prose-strong:font-semibold
                      prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5
                      prose-code:text-cyan prose-code:bg-white/5 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-xs
                      prose-pre:bg-black/30 prose-pre:border prose-pre:border-white/10 prose-pre:rounded-lg prose-pre:p-3
                      prose-table:w-full prose-table:text-sm
                      prose-th:text-white prose-th:font-medium prose-th:border-white/20 prose-th:px-3 prose-th:py-1.5 prose-th:bg-white/5
                      prose-td:border-white/10 prose-td:px-3 prose-td:py-1.5
                      prose-hr:border-white/10 prose-hr:my-3
                      prose-a:text-cyan prose-a:no-underline hover:prose-a:underline
                      prose-blockquote:border-cyan/30 prose-blockquote:text-secondary
                    "
                      >
                        <Markdown remarkPlugins={[remarkGfm]}>
                          {msg.content}
                        </Markdown>
                      </div>
                    ) : (
                      msg.content
                        .split('\n')
                        .map((line, i) => (
                          <p
                            key={i}
                            className="mb-1 last:mb-0 leading-relaxed"
                          >
                            {line || '\u00A0'}
                          </p>
                        ))
                    )}
                  </div>
                </div>
              ))
            )}

            {loading && (
              <div className="flex gap-4">
                <div className="w-8 h-8 rounded-full bg-white/10 text-white flex items-center justify-center flex-shrink-0 text-xs font-bold">
                  AI
                </div>
                <div className="bg-white/5 border border-white/10 rounded-2xl rounded-tl-sm px-5 py-4 min-w-[200px] max-w-[80%]">
                  <div className="flex items-center gap-2.5 text-sm text-secondary">
                    <div className="relative w-4 h-4 flex-shrink-0">
                      <div className="absolute inset-0 rounded-full border-2 border-cyan/20" />
                      <div className="absolute inset-0 rounded-full border-2 border-cyan border-t-transparent animate-spin" />
                    </div>
                    <span className="text-secondary">
                      {getCurrentStage(progressSteps)}
                    </span>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input area */}
          <div className="p-4 md:p-6 border-t border-white/5 bg-black/20 relative z-20">
            {chatError ? (
              <ApiErrorAlert error={chatError} className="mb-3" />
            ) : null}
            {strategies.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-x-5 gap-y-2 items-start">
                <span className="text-xs text-muted font-medium uppercase tracking-wider flex-shrink-0 mt-1">
                  策略
                </span>
                <label className="flex items-center gap-1.5 text-sm cursor-pointer group mt-0.5">
                  <input
                    type="radio"
                    name="strategy"
                    value=""
                    checked={selectedStrategy === ''}
                    onChange={() => setSelectedStrategy('')}
                    className="w-3.5 h-3.5 accent-cyan"
                  />
                  <span
                    className={`transition-colors text-sm ${selectedStrategy === '' ? 'text-white font-medium' : 'text-secondary group-hover:text-white'}`}
                  >
                    通用分析
                  </span>
                </label>
                {strategies.map((s) => (
                  <label
                    key={s.id}
                    className="flex items-center gap-1.5 cursor-pointer group relative mt-0.5"
                    onMouseEnter={() => setShowStrategyDesc(s.id)}
                    onMouseLeave={() => setShowStrategyDesc(null)}
                  >
                    <input
                      type="radio"
                      name="strategy"
                      value={s.id}
                      checked={selectedStrategy === s.id}
                      onChange={() => setSelectedStrategy(s.id)}
                      className="w-3.5 h-3.5 accent-cyan"
                    />
                    <span
                      className={`transition-colors text-sm ${selectedStrategy === s.id ? 'text-white font-medium' : 'text-secondary group-hover:text-white'}`}
                    >
                      {s.name}
                    </span>
                    {showStrategyDesc === s.id && s.description && (
                      <div className="absolute left-0 bottom-full mb-2 z-50 w-64 p-2.5 rounded-lg bg-elevated border border-white/10 shadow-xl text-xs text-secondary leading-relaxed pointer-events-none animate-fade-in">
                        <p className="font-medium text-white mb-1">{s.name}</p>
                        <p>{s.description}</p>
                      </div>
                    )}
                  </label>
                ))}
              </div>
            )}

            <div className="flex gap-3 items-end">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="例如：分析 600519 / 茅台现在适合买入吗？ (Enter 发送, Shift+Enter 换行)"
                disabled={loading}
                rows={1}
                className="input-terminal flex-1 min-h-[44px] max-h-[200px] py-2.5 resize-none"
                style={{ height: 'auto' }}
                onInput={(e) => {
                  const t = e.target as HTMLTextAreaElement;
                  t.style.height = 'auto';
                  t.style.height = `${Math.min(t.scrollHeight, 200)}px`;
                }}
              />
              <button
                onClick={() => handleSend()}
                disabled={!input.trim() || loading}
                className="btn-primary h-[44px] px-6 flex-shrink-0 flex items-center justify-center gap-2"
              >
                {loading ? (
                  <svg
                    className="w-4 h-4 animate-spin"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                ) : (
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                    />
                  </svg>
                )}
                发送
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ChatPage;
