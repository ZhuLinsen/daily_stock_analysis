import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, Search, Sparkles } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onToggle: () => void;
}

interface PaletteItem {
  id: string;
  titleZh: string;
  titleEn: string;
  subtitleZh: string;
  subtitleEn: string;
  keywords: string;
  to: string;
}

const STATIC_COMMANDS: PaletteItem[] = [
  { id: 'nav-home', titleZh: '首页工作台', titleEn: 'Home Dashboard', subtitleZh: '分析与决策报告主工作台', subtitleEn: 'Single-stock analysis & reports', keywords: 'home dashboard report 首页 报告 分析', to: '/' },
  { id: 'nav-chat', titleZh: '策略问股 Agent', titleEn: 'Agent Ask Chat', subtitleZh: '15 种内置策略多轮对话分析', subtitleEn: 'Multi-turn strategy Q&A', keywords: 'chat ask agent strategy 问股 策略 对话', to: '/chat' },
  { id: 'nav-screening', titleZh: '智能选股', titleEn: 'Stock Screening', subtitleZh: '多因子与自然语言条件筛选', subtitleEn: 'Multi-factor & NL screening', keywords: 'screening filter quant 选股 筛选', to: '/screening' },
  { id: 'nav-portfolio', titleZh: '真实持仓与风控', titleEn: 'Portfolio & Risk', subtitleZh: '账户快照、相关性压力测试与仓位计算', subtitleEn: 'Holdings, correlation & risk control', keywords: 'portfolio holdings risk stress 持仓 组合 风险 压力测试', to: '/portfolio' },
  { id: 'nav-signals', titleZh: 'AI 决策信号池', titleEn: 'AI Decision Signals', subtitleZh: '结构化信号与止盈止损跟踪', subtitleEn: 'Tracked AI signals & outcomes', keywords: 'signals decision 建议 信号', to: '/decision-signals' },
  { id: 'nav-backtest', titleZh: '历史回测', titleEn: 'Backtest', subtitleZh: 'T+N 历史胜率与方向验证', subtitleEn: 'Historical outcome evaluation', keywords: 'backtest 回测 胜率', to: '/backtest' },
  { id: 'nav-alerts', titleZh: '实时告警中心', titleEn: 'Alerts', subtitleZh: '价格与观点失效盯盘触发器', subtitleEn: 'Price & thesis watch rules', keywords: 'alerts monitor 告警 盯盘 监控', to: '/alerts' },
  { id: 'nav-data', titleZh: '数据源中心', titleEn: 'Data Center', subtitleZh: '行情源可用性与优先级诊断', subtitleEn: 'Quote & news source diagnostics', keywords: 'data provider quote 数据中心 行情', to: '/data' },
  { id: 'nav-usage', titleZh: 'Token 用量监控', titleEn: 'Token Usage', subtitleZh: 'LLM 调用统计与费用核算', subtitleEn: 'LLM calls & token accounting', keywords: 'usage token llm cost 用量 统计', to: '/usage' },
  { id: 'nav-settings', titleZh: '系统设置', titleEn: 'Settings', subtitleZh: '全局参数搜索与系统体检', subtitleEn: 'System configuration & Doctor', keywords: 'settings config env doctor 设置 配置 体检', to: '/settings' },
  { id: 'cfg-llm', titleZh: '设置 -> AI 模型接入', titleEn: 'Settings -> AI Models', subtitleZh: '管理 Gemini / DeepSeek / Modelflare / 多渠道', subtitleEn: 'Configure LLM channels & keys', keywords: 'llm model api key gemini deepseek modelflare 模型 渠道', to: '/settings?category=ai_model' },
  { id: 'cfg-notify', titleZh: '设置 -> 推送通知', titleEn: 'Settings -> Notifications', subtitleZh: '配置微信/飞书/Telegram/Discord 并一键测试', subtitleEn: 'Configure & test webhooks', keywords: 'notify webhook wechat feishu telegram discord 通知 推送 飞书 微信', to: '/settings?category=notification' },
];

const TICKER_PATTERN = /^[A-Za-z0-9.]{2,12}$/;

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(
    'button:not([disabled]), input:not([disabled]), [href], select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  ));
}

const CommandPaletteDialog: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const navigate = useNavigate();
  const { language, t } = useUiLanguage();
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const isComposingRef = useRef(false);

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const timer = window.setTimeout(() => inputRef.current?.focus(), 0);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') {
        return;
      }
      const dialog = dialogRef.current;
      if (!dialog) {
        return;
      }
      const focusable = getFocusableElements(dialog);
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement;
      if (event.shiftKey) {
        if (!activeElement || !dialog.contains(activeElement) || activeElement === first) {
          event.preventDefault();
          last.focus();
        }
        return;
      }
      if (!activeElement || !dialog.contains(activeElement) || activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    const handleFocusIn = (event: FocusEvent) => {
      const dialog = dialogRef.current;
      if (dialog && !dialog.contains(event.target as Node)) {
        inputRef.current?.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown, true);
    document.addEventListener('focusin', handleFocusIn);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener('keydown', handleKeyDown, true);
      document.removeEventListener('focusin', handleFocusIn);
      if (previouslyFocused?.isConnected) {
        previouslyFocused.focus();
      }
    };
  }, []);

  const items = useMemo(() => {
    const trimmed = query.trim();
    const lowered = trimmed.toLowerCase();
    const list: Array<{ id: string; title: string; subtitle: string; to: string; isTicker?: boolean }> = [];

    for (const cmd of STATIC_COMMANDS) {
      const title = language === 'en' ? cmd.titleEn : cmd.titleZh;
      const subtitle = language === 'en' ? cmd.subtitleEn : cmd.subtitleZh;
      if (
        !lowered
        || `${cmd.titleZh} ${cmd.titleEn} ${cmd.subtitleZh} ${cmd.subtitleEn} ${cmd.keywords}`.toLowerCase().includes(lowered)
      ) {
        list.push({ id: cmd.id, title, subtitle, to: cmd.to });
      }
    }

    if (trimmed && TICKER_PATTERN.test(trimmed)) {
      const upper = trimmed.toUpperCase();
      list.push({
        id: `ticker-${upper}`,
        title: t('palette.stockAction', { code: upper }),
        subtitle: t('palette.stockHint'),
        to: `/?stock=${encodeURIComponent(upper)}`,
        isTicker: true,
      });
    }

    return list;
  }, [language, query, t]);

  const activeIndex = items.length > 0 ? Math.min(selectedIndex, items.length - 1) : 0;

  const executeItem = (to: string) => {
    onClose();
    navigate(to);
  };

  const handleInputKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    // Ignore Enter/arrow navigation while Chinese/Japanese/Korean IME is composing.
    if (isComposingRef.current || event.nativeEvent.isComposing || event.key === 'Process' || event.keyCode === 229) {
      return;
    }
    if (event.key === 'ArrowDown' && items.length > 0) {
      event.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % items.length);
    } else if (event.key === 'ArrowUp' && items.length > 0) {
      event.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + items.length) % items.length);
    } else if (event.key === 'Enter' && items.length > 0) {
      event.preventDefault();
      const target = items[activeIndex];
      if (target) executeItem(target.to);
    }
  };

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label={t('palette.triggerLabel')}
      className="fixed inset-0 z-[120] flex items-start justify-center bg-black/50 px-4 pt-20 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-border/80 bg-card shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 border-b border-border/70 px-4 py-3">
          <Search className="h-4 w-4 shrink-0 text-muted-text" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setSelectedIndex(0);
            }}
            onCompositionStart={() => {
              isComposingRef.current = true;
            }}
            onCompositionEnd={() => {
              isComposingRef.current = false;
            }}
            onKeyDown={handleInputKeyDown}
            placeholder={t('palette.placeholder')}
            aria-label={t('palette.placeholder')}
            className="w-full bg-transparent text-sm text-foreground placeholder:text-muted-text focus:outline-none"
          />
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-border/70 px-1.5 py-0.5 text-[11px] text-muted-text hover:text-foreground"
          >
            Esc
          </button>
        </div>

        <div className="max-h-80 overflow-y-auto p-2">
          {items.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-muted-text">{t('palette.empty')}</p>
          ) : (
            items.map((item, idx) => {
              const active = idx === activeIndex;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => executeItem(item.to)}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left transition-colors ${
                    active
                      ? 'bg-[hsl(var(--primary))/0.14] text-foreground'
                      : 'text-secondary-text hover:bg-hover/60 hover:text-foreground'
                  }`}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                      {item.isTicker ? <Sparkles className="h-3.5 w-3.5 text-[hsl(var(--primary))]" aria-hidden="true" /> : null}
                      <span className="truncate">{item.title}</span>
                    </div>
                    <p className="truncate text-xs text-muted-text">{item.subtitle}</p>
                  </div>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-text" aria-hidden="true" />
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

export const CommandPalette: React.FC<CommandPaletteProps> = ({ isOpen, onClose, onToggle }) => {
  useEffect(() => {
    const handleGlobalKeyDown = (event: KeyboardEvent) => {
      if (!event.isComposing && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        // A portal-based modal (for example settings help) owns focus and
        // keyboard commands until it closes. Do not open a lower-layer palette
        // behind it; an already-open palette may still be toggled closed.
        if (!isOpen && document.querySelector('[role="dialog"][aria-modal="true"]')) {
          return;
        }
        event.preventDefault();
        onToggle();
      } else if (isOpen && event.key === 'Escape' && !event.isComposing) {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown);
  }, [isOpen, onClose, onToggle]);

  if (!isOpen) {
    return null;
  }

  return <CommandPaletteDialog onClose={onClose} />;
};
