import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Check, Search, X } from 'lucide-react';
import type { UiLanguage } from '../../i18n/uiText';
import {
  BUILTIN_STRATEGY_CATEGORIES,
  STRATEGY_CATEGORY_LABELS,
  getStrategyCategory,
  type StrategyCategoryId,
} from '../../locales/strategyText';

export interface StrategyOptionItem {
  id: string;
  name: string;
  description: string;
  category?: string | null;
}

export interface StrategyPickerMenuProps {
  options: StrategyOptionItem[];
  selectedId: string;
  language: UiLanguage;
  onSelect: (id: string) => void;
  onClose?: () => void;
  onTabClose?: () => void;
  initialFocusTarget?: 'selected' | 'first' | 'last' | 'search' | null;
  menuId?: string;
  labelledBy?: string;
  className?: string;
}

const PICKER_UI_TEXT: Record<
  UiLanguage,
  {
    searchPlaceholder: string;
    searchAriaLabel: string;
    clearSearchAriaLabel: string;
    emptyTitle: string;
    resetFilters: string;
  }
> = {
  zh: {
    searchPlaceholder: '搜索策略或因子（如 VCP、布林带、海龟）',
    searchAriaLabel: '搜索分析策略',
    clearSearchAriaLabel: '清空策略搜索',
    emptyTitle: '未找到匹配的策略',
    resetFilters: '重置筛选',
  },
  en: {
    searchPlaceholder: 'Search strategies or factors (e.g. VCP, Bollinger, Turtle)',
    searchAriaLabel: 'Search analysis strategies',
    clearSearchAriaLabel: 'Clear strategy search',
    emptyTitle: 'No matching strategies found',
    resetFilters: 'Reset filters',
  },
};

/**
 * Categorized, searchable strategy dropdown panel ready for Home/Chat strategy pickers.
 */
export const StrategyPickerMenu: React.FC<StrategyPickerMenuProps> = ({
  options,
  selectedId,
  language,
  onSelect,
  onClose,
  onTabClose,
  initialFocusTarget = null,
  menuId = 'strategy-picker-menu',
  labelledBy,
  className,
}) => {
  const [query, setQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState<StrategyCategoryId>('all');
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const didApplyInitialFocusRef = useRef(false);

  const ui = PICKER_UI_TEXT[language];
  const normalizedQuery = query.trim().toLowerCase();

  const queryMatchedOptions = useMemo(() => {
    if (!normalizedQuery) {
      return options;
    }
    return options.filter(
      (option) =>
        option.name.toLowerCase().includes(normalizedQuery) ||
        option.description.toLowerCase().includes(normalizedQuery) ||
        option.id.toLowerCase().includes(normalizedQuery),
    );
  }, [normalizedQuery, options]);

  const categoryCounts = useMemo(() => {
    const counts: Record<StrategyCategoryId, number> = {
      all: queryMatchedOptions.length,
      quant: 0,
      trend: 0,
      pattern_reversal: 0,
      framework: 0,
    };
    for (const option of queryMatchedOptions) {
      if (!option.id) {
        continue;
      }
      const cat = getStrategyCategory(option.id, option.category);
      counts[cat] += 1;
    }
    return counts;
  }, [queryMatchedOptions]);

  const visibleOptions = useMemo(() => {
    if (activeCategory === 'all') {
      return queryMatchedOptions;
    }
    return queryMatchedOptions.filter(
      (option) => Boolean(option.id) && getStrategyCategory(option.id, option.category) === activeCategory,
    );
  }, [activeCategory, queryMatchedOptions]);

  useEffect(() => {
    itemRefs.current = itemRefs.current.slice(0, visibleOptions.length);
  }, [visibleOptions.length]);

  const focusItem = useCallback(
    (index: number) => {
      if (visibleOptions.length === 0) {
        return;
      }
      const bounded = ((index % visibleOptions.length) + visibleOptions.length) % visibleOptions.length;
      setFocusedId(visibleOptions[bounded].id);
      itemRefs.current[bounded]?.focus();
    },
    [visibleOptions],
  );

  useEffect(() => {
    if (!initialFocusTarget || didApplyInitialFocusRef.current) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      didApplyInitialFocusRef.current = true;
      if (initialFocusTarget === 'search') {
        searchInputRef.current?.focus();
        return;
      }
      if (initialFocusTarget === 'last') {
        focusItem(visibleOptions.length - 1);
        return;
      }
      if (initialFocusTarget === 'selected') {
        const selectedIdx = visibleOptions.findIndex((option) => option.id === selectedId);
        focusItem(selectedIdx >= 0 ? selectedIdx : 0);
        return;
      }
      focusItem(0);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [focusItem, initialFocusTarget, selectedId, visibleOptions]);

  const rovingIndex = useMemo(() => {
    if (focusedId !== null) {
      const focusedIdx = visibleOptions.findIndex((option) => option.id === focusedId);
      if (focusedIdx >= 0) {
        return focusedIdx;
      }
    }
    const selectedIdx = visibleOptions.findIndex((option) => option.id === selectedId);
    return selectedIdx >= 0 ? selectedIdx : 0;
  }, [focusedId, selectedId, visibleOptions]);

  const handleContainerKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Tab') {
      const container = containerRef.current;
      const activeEl = document.activeElement as HTMLElement | null;
      if (!container || !activeEl) {
        onTabClose?.();
        return;
      }
      // Allow Tab/Shift+Tab to move between search input, clear button, category
      // tabs, empty reset button, and roving menu option; close only on exit.
      const isMenuItem = activeEl.getAttribute('role') === 'menuitemradio';
      if (isMenuItem) {
        if (!event.shiftKey) {
          onTabClose?.();
        }
        return;
      }
      const focusables = Array.from(
        container.querySelectorAll<HTMLElement>(
          'input:not([disabled]), button:not([disabled]):not([tabindex="-1"]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusables.length === 0) {
        onTabClose?.();
        return;
      }
      const idx = focusables.indexOf(activeEl);
      if (
        idx === -1
        || (event.shiftKey && idx === 0)
        || (!event.shiftKey && idx === focusables.length - 1)
      ) {
        onTabClose?.();
      }
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      onClose?.();
    }
  };

  const handleSearchKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusItem(0);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      if (query) {
        setQuery('');
      } else {
        onClose?.();
      }
    }
  };

  const handleMenuKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const count = visibleOptions.length;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      onClose?.();
      return;
    }
    if (count === 0) {
      return;
    }
    const currentIndex = itemRefs.current.findIndex((node) => node === document.activeElement);
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusItem(currentIndex < 0 ? 0 : currentIndex + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (currentIndex === 0) {
        searchInputRef.current?.focus();
        return;
      }
      focusItem(currentIndex < 0 ? count - 1 : currentIndex - 1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      focusItem(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      focusItem(count - 1);
    }
  };

  const containerClasses = [
    'w-[min(22rem,calc(100vw-1.5rem))] rounded-xl border border-subtle bg-elevated p-2 text-sm text-foreground shadow-2xl',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div ref={containerRef} className={containerClasses} onKeyDown={handleContainerKeyDown}>
      <div className="relative mb-2">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-text"
          aria-hidden="true"
        />
        <input
          ref={searchInputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleSearchKeyDown}
          placeholder={ui.searchPlaceholder}
          aria-label={ui.searchAriaLabel}
          className="w-full rounded-lg border border-border bg-surface/60 py-1.5 pl-8 pr-7 text-xs text-foreground placeholder:text-muted-text focus:border-primary focus:outline-none"
        />
        {query ? (
          <button
            type="button"
            onClick={() => setQuery('')}
            aria-label={ui.clearSearchAriaLabel}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-text transition-colors hover:bg-hover hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        ) : null}
      </div>

      <div className="mb-2 flex flex-wrap gap-1" role="group" aria-label={language === 'en' ? 'Strategy categories' : '策略分类'}>
        {BUILTIN_STRATEGY_CATEGORIES.map((categoryId) => {
          const isActive = activeCategory === categoryId;
          const label = STRATEGY_CATEGORY_LABELS[categoryId][language];
          const count = categoryCounts[categoryId];
          return (
            <button
              key={categoryId}
              type="button"
              aria-pressed={isActive}
              onClick={() => setActiveCategory(categoryId)}
              className={`rounded-md px-2 py-1 text-[11px] font-medium transition-colors ${
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-surface/60 text-secondary-text hover:bg-hover hover:text-foreground'
              }`}
            >
              {label} ({count})
            </button>
          );
        })}
      </div>

      <div
        id={menuId}
        role="menu"
        aria-labelledby={labelledBy}
        onKeyDown={handleMenuKeyDown}
        className="max-h-72 overflow-y-auto space-y-0.5"
      >
        {visibleOptions.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-3 py-5 text-center text-xs text-muted-text">
            <span>{ui.emptyTitle}</span>
            {(query || activeCategory !== 'all') ? (
              <button
                type="button"
                onClick={() => {
                  setQuery('');
                  setActiveCategory('all');
                }}
                className="rounded-md border border-border px-2.5 py-1 text-[11px] text-secondary-text hover:bg-hover hover:text-foreground"
              >
                {ui.resetFilters}
              </button>
            ) : null}
          </div>
        ) : (
          visibleOptions.map((option, index) => {
            const selected = selectedId === option.id;
            const categoryBadge = option.id
              ? STRATEGY_CATEGORY_LABELS[getStrategyCategory(option.id, option.category)][language]
              : null;
            return (
              <button
                key={option.id || 'default'}
                ref={(node) => {
                  itemRefs.current[index] = node;
                }}
                type="button"
                role="menuitemradio"
                aria-checked={selected}
                tabIndex={index === rovingIndex ? 0 : -1}
                onFocus={() => setFocusedId(option.id)}
                onClick={() => onSelect(option.id)}
                className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-hover focus:bg-hover focus:outline-none"
              >
                <Check
                  className={`mt-0.5 h-4 w-4 flex-shrink-0 ${selected ? 'opacity-100 text-primary' : 'opacity-0'}`}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{option.name}</span>
                    {categoryBadge ? (
                      <span className="flex-shrink-0 rounded bg-surface/80 px-1.5 py-0.5 text-[10px] text-muted-text">
                        {categoryBadge}
                      </span>
                    ) : null}
                  </span>
                  <span className="mt-0.5 line-clamp-2 block text-xs leading-5 text-muted-text">
                    {option.description}
                  </span>
                </span>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
};
