import type React from 'react';
import { Languages } from 'lucide-react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { cn } from '../../utils/cn';

type UiLanguageToggleVariant = 'default' | 'nav' | 'rail';

interface UiLanguageToggleProps {
  variant?: UiLanguageToggleVariant;
  collapsed?: boolean;
  wrapperClassName?: string;
  triggerClassName?: string;
  triggerActiveClassName?: string;
  iconClassName?: string;
  labelClassName?: string;
}

export const UiLanguageToggle: React.FC<UiLanguageToggleProps> = ({
  variant = 'default',
  collapsed = false,
  wrapperClassName,
  triggerClassName,
  triggerActiveClassName,
  iconClassName,
  labelClassName,
}) => {
  const { language, setLanguage, t } = useUiLanguage();
  const nextLanguage = language === 'zh' ? 'en' : 'zh';
  const isNavVariant = variant === 'nav';
  const isRailVariant = variant === 'rail';
  const label = language === 'zh' ? t('language.uiLanguage') : t('language.current');

  return (
    <div className={cn('relative', isRailVariant ? 'w-full' : '', wrapperClassName)}>
      <button
        type="button"
        onClick={() => setLanguage(nextLanguage)}
        className={cn(
          triggerClassName
            ? triggerClassName
            : isRailVariant
              ? 'flex h-[var(--nav-item-height)] w-full items-center justify-center gap-2.5 rounded-2xl border border-transparent px-2 text-sm leading-none text-secondary-text transition-all hover:bg-[var(--nav-hover-bg)] hover:text-foreground'
              : isNavVariant
                ? 'group relative flex h-12 w-full select-none items-center gap-3 rounded-[1.35rem] border border-transparent px-4 text-sm text-secondary-text transition-all duration-300 hover:bg-hover hover:text-foreground'
                : 'inline-flex h-10 items-center gap-2 rounded-xl border border-border/70 bg-card/80 px-3 text-sm text-secondary-text shadow-soft-card transition-colors hover:bg-hover hover:text-foreground',
          triggerActiveClassName,
          isNavVariant && collapsed ? 'justify-center px-2' : ''
        )}
        aria-label={t('language.toggle')}
        title={t('language.toggle')}
      >
        <Languages className={iconClassName ?? cn('shrink-0', isRailVariant ? 'h-[18px] w-[18px]' : isNavVariant ? 'h-5 w-5' : 'h-4 w-4')} />
        {isRailVariant ? (
          <span className={labelClassName}>{language === 'zh' ? t('language.short.zh') : t('language.short.en')}</span>
        ) : isNavVariant ? (
          collapsed ? null : <span className="truncate text-[1.02rem] font-medium">{label}</span>
        ) : (
          <span className="hidden sm:inline">{label}</span>
        )}
      </button>
    </div>
  );
};
