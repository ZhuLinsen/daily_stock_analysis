/**
 * Stock search suggestion list.
 */

import type { CSSProperties } from 'react';
import type { StockSuggestion } from '../../types/stockIndex';
import { Badge } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
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
  CN: { className: 'border-danger/25 bg-danger/10 text-danger' },
  HK: { className: 'border-success/25 bg-success/10 text-success' },
  US: { className: 'border-cyan/25 bg-cyan/10 text-cyan' },
  JP: { className: 'border-indigo-500/25 bg-indigo-500/10 text-indigo-500' },
  KR: { className: 'border-rose-500/25 bg-rose-500/10 text-rose-500' },
  INDEX: { className: 'border-purple/25 bg-purple/10 text-purple' },
  ETF: { className: 'border-warning/25 bg-warning/10 text-warning' },
  BSE: { className: 'border-orange-500/25 bg-orange-500/10 text-orange-500' },
} as const;

const MARKET_LABELS = {
  ko: { CN: '중국 A주', HK: '홍콩', US: '미국', JP: '일본', KR: '한국', INDEX: '지수', ETF: 'ETF', BSE: '베이징거래소' },
  en: { CN: 'A-shares', HK: 'Hong Kong', US: 'US', JP: 'Japan', KR: 'Korea', INDEX: 'Index', ETF: 'ETF', BSE: 'Beijing' },
  zh: { CN: 'A股', HK: '港股', US: '美股', JP: '日股', KR: '韩股', INDEX: '指数', ETF: 'ETF', BSE: '北交所' },
} as const;

function MarketBadge({ market, language }: { market: string; language: keyof typeof MARKET_LABELS }) {
  const config = MARKET_BADGE_CONFIG[market as keyof typeof MARKET_BADGE_CONFIG];

  if (!config) {
    throw new Error(`Unsupported market in stock suggestion: ${market}`);
  }

  return (
    <Badge variant="default" size="sm" className={cn('min-w-[3rem] justify-center shadow-none', config.className)}>
      {MARKET_LABELS[language][market as keyof typeof MARKET_BADGE_CONFIG]}
    </Badge>
  );
}

function MatchTypeBadge({ matchType, language }: { matchType: string; language: keyof typeof MARKET_LABELS }) {
  const labels = {
    ko: { exact: '정확 일치', prefix: '접두 일치', contains: '포함', fuzzy: '유사' },
    en: { exact: 'Exact', prefix: 'Prefix', contains: 'Contains', fuzzy: 'Fuzzy' },
    zh: { exact: '精确', prefix: '前缀', contains: '包含', fuzzy: '模糊' },
  } as const;
  const configMap = {
    exact: { className: 'border-cyan/25 bg-cyan/10 text-cyan' },
    prefix: { className: 'border-purple/25 bg-purple/10 text-purple' },
    contains: { className: 'border-warning/25 bg-warning/10 text-warning' },
    fuzzy: { className: 'border-border/55 bg-elevated/75 text-muted-text' },
  };

  const config = configMap[matchType as keyof typeof configMap] || configMap.fuzzy;

  return (
    <Badge variant="default" size="sm" className={cn('shrink-0 shadow-none', config.className)}>
      {labels[language][matchType as keyof typeof labels.ko] ?? labels[language].fuzzy}
    </Badge>
  );
}

export default SuggestionsList;
