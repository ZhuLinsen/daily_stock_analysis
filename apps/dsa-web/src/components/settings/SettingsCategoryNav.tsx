import type React from 'react';
import { Bell, Bot, Database, Layers3, LineChart, Settings2, SlidersHorizontal } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Badge } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { getCategoryDescription, getCategoryTitle } from '../../utils/systemConfigI18n';
import type { SystemConfigCategory, SystemConfigCategorySchema, SystemConfigItem } from '../../types/systemConfig';
import { cn } from '../../utils/cn';

interface SettingsCategoryNavProps {
  categories: SystemConfigCategorySchema[];
  itemsByCategory: Record<string, SystemConfigItem[]>;
  activeCategory: string;
  onSelect: (category: string) => void;
  /**
   * issue #1948 — 各分类未保存修改计数, 由 SettingsPage 页面层汇总后传入。
   * key 为 category (与 categories[].category 一致),value 为该分类 dirty 条目数。
   * 不传或某分类未提供时, 不显示 dirty 角标 (与原行为兼容)。
   * ZhuLinsen 2026-07-21 第 3 条契约: 分类角标必须消费页面层汇总后的未保存计数,
   * 不在 nav 组件内自己推导, 避免分類切換/重置/保存成功后三處狀態不同步。
   */
  dirtyCountByCategory?: Record<string, number>;
}

const categoryIconMap: Partial<Record<SystemConfigCategory, LucideIcon>> = {
  system: Settings2,
  base: SlidersHorizontal,
  data_source: Database,
  ai_model: Layers3,
  notification: Bell,
  agent: Bot,
  backtest: LineChart,
};

export const SettingsCategoryNav: React.FC<SettingsCategoryNavProps> = ({
  categories,
  itemsByCategory,
  activeCategory,
  onSelect,
  dirtyCountByCategory,
}) => {
  const { language, t } = useUiLanguage();

  return (
    <nav
      className="h-full rounded-lg border settings-border bg-card/90 p-2 shadow-soft-card backdrop-blur-sm"
      aria-label={t('settings.categoryNavTitle')}
    >
      <div className="hidden px-2 pb-3 pt-2 lg:block">
        <p className="settings-accent-text text-xs font-semibold uppercase tracking-[0.24em]">{t('settings.categoryNavTitle')}</p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-text">{t('settings.categoryNavDescription')}</p>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-1 lg:block lg:space-y-1.5 lg:overflow-visible lg:pb-0">
        {categories.map((category) => {
          const isActive = category.category === activeCategory;
          const count = (itemsByCategory[category.category] || []).length;
          const title = getCategoryTitle(category.category, category.title, language);
          const description = getCategoryDescription(category.category, category.description, language);
          const Icon = categoryIconMap[category.category] ?? Layers3;

          return (
            <button
              key={category.category}
              type="button"
              className={cn(
                'flex min-w-[9rem] items-center gap-2 rounded-md border px-3 py-2.5 text-left transition-[background-color,border-color,box-shadow] duration-200 lg:min-w-0 lg:w-full lg:items-start lg:gap-3 lg:px-3 lg:py-3',
                isActive
                  ? 'settings-nav-item-active'
                  : 'border-transparent bg-transparent hover:border-[var(--settings-border)] hover:bg-[var(--settings-surface-hover)]',
              )}
              onClick={() => onSelect(category.category)}
              aria-current={isActive ? 'page' : undefined}
            >
              <Icon
                className={cn('h-4 w-4 shrink-0 lg:mt-0.5', isActive ? 'text-[hsl(var(--primary))]' : 'text-muted-text')}
                aria-hidden="true"
              />
              <span className="min-w-0 flex-1">
                <span className={cn('block truncate text-sm font-medium', isActive ? 'text-foreground' : 'text-secondary-text')}>
                  {title}
                </span>
                {description ? (
                  <span className={cn('mt-1 hidden text-xs leading-5 lg:line-clamp-2', isActive ? 'text-secondary-text' : 'text-muted-text')}>
                    {description}
                  </span>
                ) : null}
              </span>
              {/* 分类 dirty 角标 — 仅在 dirtyCountByCategory 提供且该分类有值时显示 */}
              {dirtyCountByCategory?.[category.category] ? (
                <span
                  className="flex h-5 min-w-[1.2rem] items-center justify-center rounded-full border border-amber-500/30 bg-amber-500/15 px-1.5 text-[10px] font-semibold leading-none text-amber-700 dark:text-amber-400"
                  aria-label={t('settings.categoryDirtyUnit', { count: dirtyCountByCategory[category.category] })}
                  data-testid={`settings-nav-dirty-${category.category}`}
                >
                  {dirtyCountByCategory[category.category]}
                </span>
              ) : null}
              <Badge
                variant={isActive ? 'info' : 'default'}
                size="sm"
                className={cn(
                  'shrink-0 px-1.5 py-0 text-[11px]',
                  isActive
                    ? 'settings-accent-badge border-[hsl(var(--primary)/0.32)]'
                    : 'border-[var(--settings-border)] bg-[var(--settings-surface)] text-muted-text',
                )}
              >
                {count}
              </Badge>
            </button>
          );
        })}
      </div>
    </nav>
  );
};
