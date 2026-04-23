/**
 * useAutocomplete Hook
 *
 * Manage autocomplete interaction logic
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import type { StockIndexItem, StockSuggestion } from '../types/stockIndex';
import { searchStocks } from '../utils/searchStocks';
import { SEARCH_CONFIG } from '../utils/stockIndexFields';

export interface UseAutocompleteOptions {
  /** Minimum query length */
  minLength?: number;
  /** Debounce delay (milliseconds) */
  debounceMs?: number;
  /** Limit on number of results to return */
  limit?: number;
}

export interface UseAutocompleteResult {
  /** Current query string */
  query: string;
  /** Set query string */
  setQuery: (value: string) => void;
  /** Search suggestions list */
  suggestions: StockSuggestion[];
  /** Whether to show suggestions list */
  isOpen: boolean;
  /** Highlighted item index */
  highlightedIndex: number;
  /** Set highlighted item index */
  setHighlightedIndex: (index: number) => void;
  /** Highlight previous item */
  highlightPrevious: () => void;
  /** Highlight next item */
  highlightNext: () => void;
  /** Select suggestion item */
  handleSelect: (suggestion: StockSuggestion) => void;
  /** Close suggestions list */
  close: () => void;
  /** Reset state */
  reset: () => void;
  /** Whether IME is composing */
  isComposing: boolean;
  /** Set IME composing state */
  setIsComposing: (composing: boolean) => void;
  /** Whether runtime fallback mode is active */
  runtimeFallback: boolean;
  /** Runtime error captured from search flow */
  error: Error | null;
}

/**
 * Autocomplete Hook
 *
 * @param index - Stock index
 * @param options - Configuration options
 * @returns Autocomplete state and methods
 */
export function useAutocomplete(
  index: StockIndexItem[],
  options: UseAutocompleteOptions = {}
): UseAutocompleteResult {
  const {
    minLength = SEARCH_CONFIG.MIN_QUERY_LENGTH,
    debounceMs = SEARCH_CONFIG.DEBOUNCE_MS,
    limit = SEARCH_CONFIG.DEFAULT_LIMIT,
  } = options;

  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<StockSuggestion[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState<number>(-1);
  const [isComposing, setIsComposing] = useState(false);
  const [runtimeFallback, setRuntimeFallback] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // Use ref to store debounce timer
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Search function (debounced)
  const search = useCallback((q: string) => {
    if (runtimeFallback) {
      return;
    }

    if (q.length < minLength) {
      setSuggestions([]);
      setIsOpen(false);
      setHighlightedIndex(-1);
      return;
    }

    try {
      const results = searchStocks(q, index, { limit });
      setSuggestions(results);
      setIsOpen(results.length > 0);
      setHighlightedIndex(-1);
    } catch (caught) {
      const runtimeError = caught instanceof Error ? caught : new Error('Autocomplete search failed');
      console.error('Autocomplete search failed. Falling back to plain input.', runtimeError);
      setError(runtimeError);
      setRuntimeFallback(true);
      setSuggestions([]);
      setIsOpen(false);
      setHighlightedIndex(-1);
    }
  }, [index, minLength, limit, runtimeFallback]);

  // Input handling (with debounce)
  const handleInputChange = useCallback((value: string) => {
    setQuery(value);

    // Clear previous timer
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    if (runtimeFallback) {
      return;
    }

    // Set new timer
    debounceTimerRef.current = setTimeout(() => {
      search(value);
    }, debounceMs);
  }, [search, debounceMs, runtimeFallback]);

  // Select suggestion item
  const handleSelect = useCallback((suggestion: StockSuggestion) => {
    setQuery(suggestion.displayCode);
    setIsOpen(false);
    setSuggestions([]);
    setHighlightedIndex(-1);
  }, []);

  // Highlight previous item
  const highlightPrevious = useCallback(() => {
    setHighlightedIndex(prev => {
      if (prev <= 0) return suggestions.length - 1;
      return prev - 1;
    });
  }, [suggestions.length]);

  // Highlight next item
  const highlightNext = useCallback(() => {
    setHighlightedIndex(prev => {
      if (prev >= suggestions.length - 1) return 0;
      return prev + 1;
    });
  }, [suggestions.length]);

  // Close dropdown
  const close = useCallback(() => {
    setIsOpen(false);
    setHighlightedIndex(-1);
  }, []);

  // Reset
  const reset = useCallback(() => {
    setQuery('');
    setSuggestions([]);
    setIsOpen(false);
    setHighlightedIndex(-1);
  }, []);

  // Cleanup timer (on component unmount)
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  return {
    query,
    setQuery: handleInputChange,
    suggestions,
    isOpen,
    highlightedIndex,
    setHighlightedIndex,
    highlightPrevious,
    highlightNext,
    handleSelect,
    close,
    reset,
    isComposing,
    setIsComposing,
    runtimeFallback,
    error,
  };
}

/**
 * Get default exported Hook
 */
export default useAutocomplete;
