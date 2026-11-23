/**
 * useStockIndex Hook
 *
 * Manage stock index loading and state
 */

import { useState, useEffect } from 'react';
import type { StockIndexItem } from '../types/stockIndex';
import { loadStockIndex } from '../utils/stockIndexLoader';
import type { IndexLoadResult } from '../utils/stockIndexLoader';

export interface UseStockIndexResult {
  /** Stock index data */
  index: StockIndexItem[];
  /** Is loading */
  loading: boolean;
  /** Load error */
  error: Error | null;
  /** Whether fallback mode is used */
  fallback: boolean;
  /** Is loaded */
  loaded: boolean;
}

/**
 * Stock index loading Hook
 *
 * @returns Index state and data
 */
export function useStockIndex(enabled = true): UseStockIndexResult {
  const [index, setIndex] = useState<StockIndexItem[]>([]);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<Error | null>(null);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let mounted = true;

    async function load() {
      setLoading(true);
      setError(null);

      const result: IndexLoadResult = await loadStockIndex();

      if (mounted) {
        setIndex(result.data);
        setFallback(result.fallback);
        if (result.error) {
          setError(result.error);
        }
        setLoading(false);
      }
    }

    load();

    return () => {
      mounted = false;
    };
  }, [enabled]);

  return {
    index: enabled ? index : [],
    loading: enabled ? loading : false,
    error: enabled ? error : null,
    fallback: enabled ? fallback : false,  // Whether fallback
    loaded: enabled ? !loading : false,
  };
}

/**
 * Get default exported Hook
 */
export default useStockIndex;
