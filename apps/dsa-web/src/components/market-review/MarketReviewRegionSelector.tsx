import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Globe2, RotateCcw } from 'lucide-react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { cn } from '../../utils/cn';
import {
  MARKET_REVIEW_REGION_ORDER,
  type MarketReviewRegion,
} from '../../utils/marketReviewRegion';

type MarketReviewRegionSelectorProps = {
  value?: readonly MarketReviewRegion[];
  disabled?: boolean;
  onChange: (value: MarketReviewRegion[] | undefined) => void;
};

export const MarketReviewRegionSelector: React.FC<MarketReviewRegionSelectorProps> = ({
  value,
  disabled = false,
  onChange,
}) => {
  const { t } = useUiLanguage();
  const [open, setOpen] = useState(false);
  const menuOpen = open && !disabled;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const defaultButtonRef = useRef<HTMLButtonElement | null>(null);

  const displayedRegions = value ?? [];

  const regionLabels: Record<MarketReviewRegion, string> = {
    cn: t('home.marketRegionCn'),
    hk: t('home.marketRegionHk'),
    us: t('home.marketRegionUs'),
    jp: t('home.marketRegionJp'),
    kr: t('home.marketRegionKr'),
  };

  const formatRegions = (regions: MarketReviewRegion[]) => (
    regions.map((region) => regionLabels[region]).join(' + ')
  );
  const triggerLabel = value === undefined
    ? t('home.marketRegionServerDefault')
    : formatRegions([...displayedRegions]);

  const close = useCallback((restoreFocus = false) => {
    setOpen(false);
    if (restoreFocus) {
      triggerRef.current?.focus();
    }
  }, []);

  useEffect(() => {
    if (!menuOpen) {
      return undefined;
    }

    const focusTimer = window.setTimeout(() => defaultButtonRef.current?.focus(), 0);
    const handlePointerDown = (event: MouseEvent) => {
      if (event.target instanceof Node && containerRef.current?.contains(event.target)) {
        return;
      }
      close();
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, [close, menuOpen]);

  useEffect(() => {
    if (!disabled) {
      return undefined;
    }
    const closeTimer = window.setTimeout(() => setOpen(false), 0);
    return () => window.clearTimeout(closeTimer);
  }, [disabled]);

  const toggleRegion = (region: MarketReviewRegion) => {
    if (disabled) {
      return;
    }
    const next = new Set<MarketReviewRegion>(displayedRegions);
    if (next.has(region)) {
      if (next.size === 1) {
        return;
      }
      next.delete(region);
    } else {
      next.add(region);
    }
    onChange(MARKET_REVIEW_REGION_ORDER.filter((item) => next.has(item)));
  };

  return (
    <div ref={containerRef} className="relative min-w-0 flex-1 basis-full sm:basis-auto">
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        aria-haspopup="dialog"
        aria-expanded={menuOpen}
        aria-controls={menuOpen ? 'market-review-region-menu' : undefined}
        aria-label={t('home.marketRegionSelector')}
        onClick={() => setOpen((current) => !current)}
        className={cn(
          'flex h-10 w-full min-w-0 items-center gap-2 rounded-xl border border-subtle bg-surface/60 px-3 text-left text-xs text-secondary-text transition-colors',
          'hover:border-subtle-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:outline-none sm:w-auto sm:max-w-64',
          'disabled:cursor-not-allowed disabled:opacity-50',
        )}
      >
        <Globe2 className="h-4 w-4 flex-shrink-0 text-primary" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate">{triggerLabel}</span>
        <ChevronDown
          className={cn('h-3.5 w-3.5 flex-shrink-0 transition-transform', menuOpen && 'rotate-180')}
          aria-hidden="true"
        />
      </button>

      {menuOpen ? (
        <div
          id="market-review-region-menu"
          role="dialog"
          aria-label={t('home.marketRegionSelector')}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              close(true);
            }
          }}
          className="absolute right-0 z-50 mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-subtle bg-surface/95 p-2 shadow-2xl shadow-black/25 backdrop-blur-xl"
        >
          <div className="border-b border-subtle px-2.5 py-2">
            <p className="text-sm font-semibold text-foreground">{t('home.marketRegionTitle')}</p>
            <p className="mt-1 text-xs leading-5 text-muted-text">{t('home.marketRegionDescription')}</p>
          </div>

          <div className="space-y-1 py-2">
            <button
              ref={defaultButtonRef}
              type="button"
              disabled={disabled}
              aria-pressed={value === undefined}
              onClick={() => onChange(undefined)}
              className={cn(
                'flex min-h-10 w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:outline-none',
                value === undefined ? 'bg-primary/12 text-primary' : 'text-secondary-text hover:bg-surface-hover hover:text-foreground',
              )}
            >
              <RotateCcw className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{t('home.marketRegionServerDefault')}</span>
                <span className="mt-0.5 block truncate text-xs text-muted-text">
                  {t('home.marketRegionDefaultUnavailable')}
                </span>
              </span>
              <Check className={cn('h-4 w-4', value === undefined ? 'opacity-100' : 'opacity-0')} aria-hidden="true" />
            </button>

            <button
              type="button"
              disabled={disabled}
              aria-pressed={value !== undefined && displayedRegions.length === MARKET_REVIEW_REGION_ORDER.length}
              onClick={() => onChange([...MARKET_REVIEW_REGION_ORDER])}
              className="flex min-h-10 w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left text-sm text-secondary-text transition-colors hover:bg-surface-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:outline-none"
            >
              <span className="flex h-4 w-4 items-center justify-center rounded border border-primary/60 bg-primary/10">
                <Check
                  className={cn('h-3 w-3 text-primary', displayedRegions.length === MARKET_REVIEW_REGION_ORDER.length ? 'opacity-100' : 'opacity-0')}
                  aria-hidden="true"
                />
              </span>
              <span className="font-medium">{t('home.marketRegionAll')}</span>
            </button>

            <div className="grid grid-cols-1 gap-1 pt-1 sm:grid-cols-2">
              {MARKET_REVIEW_REGION_ORDER.map((region) => {
                const checked = displayedRegions.includes(region);
                return (
                  <label
                    key={region}
                    className="flex min-h-10 cursor-pointer items-center gap-3 rounded-xl px-2.5 py-2 text-sm text-secondary-text transition-colors hover:bg-surface-hover hover:text-foreground"
                  >
                    <input
                      type="checkbox"
                      disabled={disabled}
                      checked={checked}
                      onChange={() => toggleRegion(region)}
                      className="h-4 w-4 rounded border-border accent-primary"
                    />
                    <span>{regionLabels[region]}</span>
                    <span className="ml-auto text-[11px] uppercase text-muted-text">{region}</span>
                  </label>
                );
              })}
            </div>
          </div>

          <p className="px-2.5 pb-1 text-[11px] leading-4 text-muted-text">
            {t('home.marketRegionOneTimeHint')}
          </p>
        </div>
      ) : null}
    </div>
  );
};
