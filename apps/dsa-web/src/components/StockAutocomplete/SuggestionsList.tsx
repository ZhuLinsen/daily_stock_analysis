/**
 * Stock search suggestion list.
 */

import type { CSSProperties } from 'react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiLanguage } from '../../i18n/uiText';
import type { StockSuggestion } from '../../types/stockIndex';
import { Badge } from '../common';
import { cn } from '../../utils/cn';

export interface SuggestionsListProps {
  /** Suggestion list */
  suggestions: StockSuggestion[];
  /** Highlighted index */
  highlightedIndex: number;
  /** Selection callback */
  onSelect: (suggestion: StockSuggestion) => void;
  /** Mouse hover callback */
  onMouseEnter: (index: number) => void;
  /** Custom style (for Portal fixed positioning) */
  style?: CSSProperties;
}

export function SuggestionsList({
  suggestions,
  highlightedIndex,
  onSelect,
  onMouseEnter,
  style,
}: SuggestionsListProps) {
  const { language } = useUiLanguage();

  if (suggestions.length === 0) {
    return null;
  }

  return (
    <ul
      id="suggestions-list"
      className="z-[100] border-x border-b rounded-b-lg rounded-t-none max-h-60 overflow-auto"
      style={{
        ...style,
        backgroundColor: 'hsl(var(--card) / 0.85)',
        borderColor: 'var(--border-accent)',
        boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3), -4px 0 15px -3px rgba(0, 0, 0, 0.2), 4px 0 15px -3px rgba(0, 0, 0, 0.2)',
      }}
      role="listbox"
    >
      {suggestions.map((suggestion, index) => (
        <li
          key={suggestion.canonicalCode}
          role="option"
          aria-selected={index === highlightedIndex}
          className={cn(
            'px-4 py-1 cursor-pointer flex items-center justify-between',
            'hover:bg-[var(--autocomplete-hover-bg)]/25',
            index === highlightedIndex && 'bg-[var(--autocomplete-hover-bg)]/25',
          )}
          onClick={() => onSelect(suggestion)}
          onMouseEnter={() => onMouseEnter(index)}
        >
          <div className="flex items-center gap-3">
            <MarketBadge market={suggestion.market} language={language} />

            <div className="flex flex-col">
              <span className="text-sm font-medium text-primary-text">
                {suggestion.nameZh}
              </span>
              <span className="text-sm text-secondary-text">
                {suggestion.displayCode}
              </span>
            </div>
          </div>

          <MatchTypeBadge matchType={suggestion.matchType} language={language} />
        </li>
      ))}
    </ul>
  );
}

const MARKET_BADGE_CONFIG = {
  CN: { labels: { zh: 'A股', en: 'CN' }, className: 'border-danger/25 bg-danger/10 text-danger' },
  HK: { labels: { zh: '港股', en: 'HK' }, className: 'border-success/25 bg-success/10 text-success' },
  US: { labels: { zh: '美股', en: 'US' }, className: 'border-cyan/25 bg-cyan/10 text-cyan' },
  JP: { labels: { zh: '日股', en: 'JP' }, className: 'border-indigo-500/25 bg-indigo-500/10 text-indigo-500' },
  KR: { labels: { zh: '韩股', en: 'KR' }, className: 'border-rose-500/25 bg-rose-500/10 text-rose-500' },
  INDEX: { labels: { zh: '指数', en: 'Index' }, className: 'border-purple/25 bg-purple/10 text-purple' },
  ETF: { labels: { zh: 'ETF', en: 'ETF' }, className: 'border-warning/25 bg-warning/10 text-warning' },
  BSE: { labels: { zh: '北交所', en: 'BSE' }, className: 'border-orange-500/25 bg-orange-500/10 text-orange-500' },
} as const;

function MarketBadge({ market, language }: { market: string; language: UiLanguage }) {
  const config = Object.hasOwn(MARKET_BADGE_CONFIG, market)
    ? MARKET_BADGE_CONFIG[market as keyof typeof MARKET_BADGE_CONFIG]
    : undefined;

  if (!config) {
    throw new Error(`Unsupported market in stock suggestion: ${market}`);
  }

  return (
    <Badge variant="default" size="sm" className={cn('min-w-[3rem] justify-center shadow-none', config.className)}>
      {config.labels[language]}
    </Badge>
  );
}

const MATCH_TYPE_BADGE_CONFIG = {
  exact: { labels: { zh: '精确', en: 'Exact' }, className: 'border-cyan/25 bg-cyan/10 text-cyan' },
  prefix: { labels: { zh: '前缀', en: 'Prefix' }, className: 'border-purple/25 bg-purple/10 text-purple' },
  contains: { labels: { zh: '包含', en: 'Contains' }, className: 'border-warning/25 bg-warning/10 text-warning' },
  fuzzy: { labels: { zh: '模糊', en: 'Fuzzy' }, className: 'border-border/55 bg-elevated/75 text-muted-text' },
} as const;

function MatchTypeBadge({ matchType, language }: { matchType: string; language: UiLanguage }) {
  const config = Object.hasOwn(MATCH_TYPE_BADGE_CONFIG, matchType)
    ? MATCH_TYPE_BADGE_CONFIG[matchType as keyof typeof MATCH_TYPE_BADGE_CONFIG]
    : MATCH_TYPE_BADGE_CONFIG.fuzzy;

  return (
    <Badge variant="default" size="sm" className={cn('shrink-0 shadow-none', config.className)}>
      {config.labels[language]}
    </Badge>
  );
}

export default SuggestionsList;
