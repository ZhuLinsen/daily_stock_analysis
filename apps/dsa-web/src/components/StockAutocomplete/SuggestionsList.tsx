/**
 * SuggestionsList Component
 *
 * Stock search suggestion list
 * Displays matched stock options
 */

import type { CSSProperties } from 'react';
import type { StockSuggestion } from '../../types/stockIndex';
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
        boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3), -4px 0 15px -3px rgba(0, 0, 0, 0.2), 4px 0 15px -3px rgba(0, 0, 0, 0.2)'
      }}
      role="listbox"
    >
      {suggestions.map((suggestion, index) => (
        <li
          key={suggestion.canonicalCode}
          role="option"
          aria-selected={index === highlightedIndex}
          className={cn(
            "px-4 py-1 cursor-pointer flex items-center justify-between",
            "hover:bg-[var(--autocomplete-hover-bg)]/25",
            index === highlightedIndex && "bg-[var(--autocomplete-hover-bg)]/25"
          )}
          onClick={() => onSelect(suggestion)}
          onMouseEnter={() => onMouseEnter(index)}
        >
          <div className="flex items-center gap-3">
            {/* Market badge */}
            <MarketBadge market={suggestion.market} />

            {/* Name and code */}
            <div className="flex flex-col">
              <span className="text-sm font-medium text-primary-text">
                {suggestion.nameZh}
              </span>
              <span className="text-sm text-secondary-text">
                {suggestion.displayCode}
              </span>
            </div>
          </div>

          {/* Match type badge */}
          <MatchTypeBadge matchType={suggestion.matchType} />
        </li>
      ))}
    </ul>
  );
}

// Helper component: Market badge
const MARKET_BADGE_CONFIG = {
  CN: { label: 'A股', className: 'text-red-500 bg-red-500/10' },
  HK: { label: '港股', className: 'text-green-500 bg-green-500/10' },
  US: { label: '美股', className: 'text-blue-500 bg-blue-500/10' },
  INDEX: { label: '指数', className: 'text-purple-500 bg-purple-500/10' },
  ETF: { label: 'ETF', className: 'text-yellow-500 bg-yellow-500/10' },
  BSE: { label: '北交所', className: 'text-orange-500 bg-orange-500/10' },
} as const;

function MarketBadge({ market }: { market: string }) {
  const config = MARKET_BADGE_CONFIG[market as keyof typeof MARKET_BADGE_CONFIG];

  if (!config) {
    throw new Error(`Unsupported market in stock suggestion: ${market}`);
  }

  return (
    <span className={cn("text-xs px-2 py-0.5 rounded", config.className)}>
      {config.label}
    </span>
  );
}

// Helper component: Match type badge
function MatchTypeBadge({ matchType }: { matchType: string }) {
  const configMap = {
    exact: { label: '精确', className: 'bg-cyan/10 text-cyan' },
    prefix: { label: '前缀', className: 'bg-purple/10 text-purple' },
    contains: { label: '包含', className: 'bg-yellow/10 text-yellow' },
    fuzzy: { label: '模糊', className: 'bg-gray/10 text-gray' },
  };

  const config = configMap[matchType as keyof typeof configMap] || configMap.fuzzy;

  return (
    <span className={cn("text-xs px-1.5 py-0.5 rounded", config.className)}>
      {config.label}
    </span>
  );
}

export default SuggestionsList;
