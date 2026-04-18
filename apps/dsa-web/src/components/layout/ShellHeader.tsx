import type React from 'react';
import { Menu, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { ThemeToggle } from '../theme/ThemeToggle';

type ShellHeaderProps = {
  collapsed: boolean;
  onToggleSidebar: () => void;
  onOpenMobileNav: () => void;
};

const TITLES: Record<string, { title: string; description: string }> = {
  '/': { title: '首页', description: '股票分析与历史报告工作台' },
  '/chat': { title: '问股', description: '多轮策略问答与历史会话管理' },
  '/backtest': { title: '回测', description: '回测任务与结果浏览' },
  '/settings': { title: '设置', description: '系统配置、模型与认证管理' },
};

export const ShellHeader: React.FC<ShellHeaderProps> = ({
  collapsed,
  onToggleSidebar,
  onOpenMobileNav,
}) => {
  const location = useLocation();
  const current = TITLES[location.pathname] ?? { title: 'Daily Stock Analysis', description: 'Web workspace' };

  return (
    <header className="sticky top-0 z-30 border-b border-border/60 bg-background/84 backdrop-blur-xl">
      <div className="mx-auto flex h-16 w-full max-w-[1680px] items-center gap-3 px-4 sm:px-6 lg:px-8">
        <button
          type="button"
          onClick={onOpenMobileNav}
          className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border/70 bg-card/70 text-secondary-text transition-colors hover:bg-hover hover:text-foreground lg:hidden"
          aria-label="打开导航菜单"
        >
          <Menu className="h-5 w-5" />
        </button>

        <button
          type="button"
          onClick={onToggleSidebar}
          className="hidden h-10 w-10 items-center justify-center rounded-xl border border-border/70 bg-card/70 text-secondary-text transition-colors hover:bg-hover hover:text-foreground lg:inline-flex"
          aria-label={collapsed ? '展开侧边栏' : '折叠侧边栏'}
        >
          {collapsed ? <PanelLeftOpen className="h-5 w-5" /> : <PanelLeftClose className="h-5 w-5" />}
        </button>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-foreground">{current.title}</p>
          <p className="truncate text-xs text-secondary-text">{current.description}</p>
        </div>

        <ThemeToggle />
      </div>
    </header>
  );
};
