import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { Check, Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';
import { cn } from '../../utils/cn';

type ThemeOption = 'light' | 'dark' | 'system';
type ThemeToggleVariant = 'default' | 'nav';

const THEME_OPTIONS: Array<{
  value: ThemeOption;
  label: string;
  icon: typeof Sun;
}> = [
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'dark', label: '深色', icon: Moon },
  { value: 'system', label: '跟随系统', icon: Monitor },
];

function resolveThemeLabel(theme: string | undefined) {
  switch (theme) {
    case 'light':
      return '浅色';
    case 'dark':
      return '深色';
    default:
      return '跟随系统';
  }
}

interface ThemeToggleProps {
  variant?: ThemeToggleVariant;
  collapsed?: boolean;
}

export const ThemeToggle: React.FC<ThemeToggleProps> = ({
  variant = 'default',
  collapsed = false,
}) => {
  const { theme, resolvedTheme, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, [open]);

  const activeTheme = (theme as ThemeOption | undefined) ?? 'system';
  const visualTheme = resolvedTheme ?? 'dark';
  const TriggerIcon = visualTheme === 'light' ? Sun : Moon;
  const isNavVariant = variant === 'nav';

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        disabled
        onClick={() => setOpen((value) => !value)}
        data-state={open ? 'open' : 'closed'}
        className={cn(
          isNavVariant
            ? 'group relative flex h-12 w-full select-none items-center gap-3 rounded-[1.35rem] border border-transparent px-4 text-sm text-secondary-text transition-all duration-300 data-[state=open]:border-subtle data-[state=open]:bg-subtle data-[state=open]:text-foreground opacity-50 cursor-not-allowed'
            : 'inline-flex h-10 items-center gap-2 rounded-xl border border-border/70 bg-card/80 px-3 text-sm text-secondary-text shadow-soft-card transition-colors opacity-50 cursor-not-allowed',
          isNavVariant && collapsed ? 'justify-center px-2' : ''
        )}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="切换主题 (暂时禁用)"
      >
        <TriggerIcon className={cn('shrink-0', isNavVariant ? 'h-5 w-5' : 'h-4 w-4')} />
        {isNavVariant ? (
          collapsed ? null : <span className="truncate text-[1.02rem] font-medium">主题</span>
        ) : (
          <span className="hidden sm:inline">{resolveThemeLabel(activeTheme)}</span>
        )}
      </button>

      {open ? (
        <div
          role="menu"
          aria-label="主题模式"
          className={cn(
            'z-[100] min-w-[8rem] overflow-hidden rounded-2xl border border-border/70 bg-elevated p-1.5 shadow-[0_24px_48px_rgba(3,8,20,0.32)] backdrop-blur-xl',
            isNavVariant
              ? 'absolute bottom-full left-0 mb-2 w-max min-w-[9rem]'
              : 'absolute right-0 mt-2'
          )}
        >
          {THEME_OPTIONS.map(({ value, label, icon: Icon }) => {
            const isActive = activeTheme === value;
            return (
              <button
                key={value}
                type="button"
                role="menuitemradio"
                aria-checked={isActive}
                onClick={() => {
                  setTheme(value);
                  setOpen(false);
                }}
                className={cn(
                  'flex w-full items-center justify-between rounded-xl px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-cyan/10 text-foreground'
                    : 'text-secondary-text hover:bg-hover hover:text-foreground'
                )}
              >
                <span className="flex items-center gap-2">
                  <Icon className="h-4 w-4" />
                  {label}
                </span>
                {isActive ? <Check className="h-4 w-4 text-cyan" /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
};
